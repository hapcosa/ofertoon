"""Bot público de onboarding Telegram-nativo con menú multi-tier.

PORT de `signalsTrading/onboarding_bot/main.py`. El FSM del trial, el checkout
PayPal y el loop de entrega de invitaciones se conservan tal cual: es el flujo
que ya se depuró contra usuarios reales. Lo reescrito es el track record del
menú (ofertas publicadas en vez de win-rate de trading) y las rutas de import.
"""
from __future__ import annotations

import asyncio
from contextlib import suppress
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from html import escape
import logging
from math import isfinite
import os
from pathlib import Path
import sys
from typing import Any

import asyncpg
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandStart, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from ..email import send_email
from ..paypal.client import (
    PayPalAPIError,
    PayPalClient,
    PayPalConfigurationError,
    PayPalUnavailable,
)

from . import db
from .delivery import deliver_pending
from .email_validation import load_disposable_domains, normalize_email
from .email_verification import (
    generate_code,
    hash_code,
    render_code_email,
    verify_decision_message,
)
from .menu import MenuModel, TierStats, build_menu_model
from .metrics import (
    build_conversion_report,
    format_conversion_report,
    is_admin,
    parse_admin_ids,
)
from .payments import (
    PaymentConfigurationError,
    PlanChoice,
    PlanChoiceMode,
    build_custom_id,
    build_request_id,
    format_pay_prompt,
    format_plan_button,
    resolve_redirect_urls,
    select_plan_options,
)
from .trial import (
    evaluate_trial_eligibility,
    grant_conflict_message,
    trial_decision_message,
)

logger = logging.getLogger("ofertascl.bot")
logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO"),
    format="%(asctime)s [%(name)s] %(message)s",
)


def _load_trial_days() -> int:
    raw = os.environ.get("ONBOARDING_TRIAL_DAYS", "7").strip()
    try:
        days = int(raw)
    except ValueError:
        logger.warning("ONBOARDING_TRIAL_DAYS inválido; se usa el default 7")
        return 7
    if days <= 0:
        logger.warning("ONBOARDING_TRIAL_DAYS debe ser positivo; se usa el default 7")
        return 7
    return days


def _load_dm_poll_seconds() -> float:
    raw = os.environ.get("ONBOARDING_DM_POLL_SECONDS", "5").strip()
    try:
        seconds = float(raw)
    except ValueError:
        logger.warning("ONBOARDING_DM_POLL_SECONDS inválido; se usa el default 5")
        return 5.0
    if not isfinite(seconds) or seconds <= 0:
        logger.warning(
            "ONBOARDING_DM_POLL_SECONDS debe ser positivo; se usa el default 5"
        )
        return 5.0
    return seconds


def _load_positive_int(name: str, default: int) -> int:
    raw = os.environ.get(name, str(default)).strip()
    try:
        value = int(raw)
    except ValueError:
        logger.warning("%s inválido; se usa el default %s", name, default)
        return default
    if value <= 0:
        logger.warning("%s debe ser positivo; se usa el default %s", name, default)
        return default
    return value


_DISPOSABLE_DOMAINS = load_disposable_domains(
    Path(__file__).with_name("disposable_domains.txt")
)
_TRIAL_DAYS = _load_trial_days()
_DM_POLL_SECONDS = _load_dm_poll_seconds()
_EMAIL_VERIFICATION = (
    os.environ.get("ONBOARDING_EMAIL_VERIFICATION", "0") == "1"
)
_EMAIL_CODE_TTL_MINUTES = _load_positive_int(
    "ONBOARDING_EMAIL_CODE_TTL_MINUTES",
    15,
)
_EMAIL_CODE_MAX_ATTEMPTS = _load_positive_int(
    "ONBOARDING_EMAIL_CODE_MAX_ATTEMPTS",
    5,
)
# Decisión F4.3 confirmada: máximo 50 invitaciones por ciclo.
_DM_BATCH_LIMIT = 50
# Allowlist del comando admin /stats. Sin ids válidos el comando queda cerrado.
_ADMIN_IDS = parse_admin_ids(os.environ.get("ONBOARDING_ADMIN_IDS"))


_pool: asyncpg.Pool | None = None
_paypal_client: PayPalClient | None = None


async def _ensure_pool() -> asyncpg.Pool:
    global _pool
    if _pool is None:
        dsn = os.environ["DATABASE_URL"]
        _pool = await asyncpg.create_pool(dsn, min_size=1, max_size=4)
    return _pool


def _tier_stats_from_rows(rows: list) -> dict[int, TierStats]:
    """Convierte las filas ya agregadas de `fetch_tier_stat_rows` en TierStats.

    La query agrupa por tier, así que acá no hay agregación: solo tipado. Un
    tier sin publicaciones no viene en las filas y por lo tanto no tiene stats.
    """
    stats: dict[int, TierStats] = {}
    for row in rows:
        posts = int(row["posts"])
        if posts == 0:  # pragma: no cover - el GROUP BY nunca emite cero.
            continue
        stats[int(row["tier_id"])] = TierStats(
            posts=posts,
            avg_discount=Decimal(str(row["avg_discount"] or 0)),
            best_discount=Decimal(str(row["best_discount"] or 0)),
        )
    return stats


def _render_menu_text(model: MenuModel) -> str:
    parts = [f"<b>{escape(model.title)}</b>", escape(model.copy)]
    if not model.rows:
        parts.append("No hay canales VIP disponibles en este momento.")
    for row in model.rows:
        details = [f"<b>{escape(row.name)}</b>"]
        if row.description:
            details.append(escape(row.description))
        if row.stats_line:
            details.append(escape(row.stats_line))
        details.append(f"Estado: {escape(row.status_label)}")
        parts.append("\n".join(details))
    return "\n\n".join(parts)


def _build_markup(model: MenuModel) -> InlineKeyboardMarkup | None:
    keyboard = [
        [
            InlineKeyboardButton(
                text=button.text,
                callback_data=button.callback_data,
            )
            for button in row.buttons
        ]
        for row in model.rows
        if row.buttons
    ]
    if not keyboard:
        return None
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def _payment_markup(tier_id: int, tier_name: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=f"💳 Pagar: {tier_name}",
                    callback_data=f"pay:{tier_id}",
                )
            ]
        ]
    )


def _email_code_markup() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Reenviar código",
                    callback_data="email_code:resend",
                )
            ]
        ]
    )


def _plan_choice_markup(tier_id: int, choice: PlanChoice) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=format_plan_button(plan),
                    callback_data=f"pay_plan:{tier_id}:{int(plan['id'])}",
                )
            ]
            for plan in choice.plans
        ]
    )


def _paypal_approval_markup(approval_url: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="💳 Pagar en PayPal",
                    url=approval_url,
                )
            ]
        ]
    )


def _get_paypal_client() -> PayPalClient:
    global _paypal_client
    if _paypal_client is None:
        _paypal_client = PayPalClient.from_env()
    return _paypal_client


def _paypal_redirect_urls() -> tuple[str, str]:
    return resolve_redirect_urls(
        bot_username=os.environ.get("ONBOARDING_BOT_USERNAME", ""),
        return_url=os.environ.get("ONBOARDING_PAYPAL_RETURN_URL"),
        cancel_url=os.environ.get("ONBOARDING_PAYPAL_CANCEL_URL"),
    )


async def _send_paypal_checkout(
    callback: CallbackQuery,
    tier: Any,
    plan: Any,
    email: str | None,
) -> None:
    """Crea la suscripción sin mutar la membresía y entrega la approve URL."""
    if not isinstance(callback.message, Message):
        return  # pragma: no cover - los handlers validan el mensaje primero.
    try:
        return_url, cancel_url = _paypal_redirect_urls()
        subscription = await _get_paypal_client().create_subscription(
            plan_id=str(plan["paypal_plan_id"]),
            custom_id=build_custom_id(callback.from_user.id, int(tier["id"])),
            request_id=build_request_id(
                callback.id,
                callback.from_user.id,
                int(tier["id"]),
                int(plan["id"]),
            ),
            return_url=return_url,
            cancel_url=cancel_url,
            email=email,
        )
    except (PaymentConfigurationError, PayPalConfigurationError) as exc:
        logger.error("paypal_onboarding_configuration_error reason=%s", exc)
        await callback.message.answer(
            "Los pagos no están configurados en este momento. Intentá más tarde."
        )
        return
    except PayPalAPIError as exc:
        logger.warning("paypal_onboarding_request_rejected reason=%s", exc)
        await callback.message.answer(
            "PayPal rechazó el inicio del pago. Intentá nuevamente."
        )
        return
    except PayPalUnavailable as exc:
        logger.warning("paypal_onboarding_unavailable reason=%s", exc)
        await callback.message.answer(
            "PayPal no está disponible temporalmente. Intentá nuevamente en unos minutos."
        )
        return

    await callback.message.answer(
        format_pay_prompt(tier, plan),
        reply_markup=_paypal_approval_markup(subscription.approval_url),
    )


class TrialFlow(StatesGroup):
    awaiting_email = State()
    awaiting_code = State()


dp = Dispatcher()


@dp.message(CommandStart())
async def on_start(
    message: Message,
    command: CommandObject,
    state: FSMContext,
) -> None:
    """Cancela cualquier captura pendiente y muestra el menú multi-tier."""
    # Decisión F4.2: /start también funciona como cancelación segura del FSM.
    await state.clear()
    user = message.from_user
    if user is None:
        return

    ref = (command.args or "").strip() or None
    pool = await _ensure_pool()
    async with pool.acquire() as conn:
        identity = await db.upsert_identity(conn, user.id, user.username, ref)
        tiers = await db.fetch_active_tiers(conn)
        memberships = await db.fetch_memberships(conn, user.id)
        stat_rows = await db.fetch_tier_stat_rows(conn)

    model = build_menu_model(
        tiers,
        db.memberships_by_tier_id(memberships),
        identity,
        now=datetime.now(timezone.utc),
        stats_by_tier_id=_tier_stats_from_rows(stat_rows),
    )
    logger.info("menú solicitado por telegram_user_id=%s", user.id)
    await message.answer(
        _render_menu_text(model),
        parse_mode="HTML",
        reply_markup=_build_markup(model),
    )


@dp.message(Command("stats"))
async def on_stats(message: Message) -> None:
    """Reporte de conversión por campaña/tier, restringido a admins.

    A un no-admin no se le revela la existencia del comando: se responde con el
    mismo mensaje neutro que a un usuario que se equivocó de comando.
    """
    user = message.from_user
    if not is_admin(user.id if user else None, _ADMIN_IDS):
        await message.answer("Comando no disponible. Enviá /start para ver los canales.")
        return

    pool = await _ensure_pool()
    async with pool.acquire() as conn:
        arrivals = await db.fetch_arrivals_by_ref(conn)
        funnel = await db.fetch_conversion_by_ref_tier(conn)

    report = build_conversion_report(arrivals, funnel)
    await message.answer(format_conversion_report(report), parse_mode="HTML")


async def _process_trial_candidate(
    message: Message,
    state: FSMContext,
    user_id: int,
    tier_id: int,
    email_raw: str,
) -> None:
    """Orquesta lecturas, decisión pura y escritura transaccional del trial."""
    pool = await _ensure_pool()
    async with pool.acquire() as conn:
        identity = await db.fetch_identity(conn, user_id)
        tier = await db.fetch_active_tier(conn, tier_id)
        if identity is None or tier is None:
            await state.clear()
            await message.answer(
                "Ese canal ya no está disponible. Enviá /start para actualizar el menú."
            )
            return

        normalized = normalize_email(email_raw)
        email_owner = None
        if normalized is not None:
            email_owner = await db.find_trial_owner_by_email(conn, normalized)
        decision = evaluate_trial_eligibility(
            email_raw=email_raw,
            denylist=_DISPOSABLE_DOMAINS,
            identity_trial_used_at=identity["trial_used_at"],
            email_owner_trial_used_at=(
                email_owner["trial_used_at"] if email_owner else None
            ),
        )

        if not decision.allowed:
            if decision.should_retry_email:
                await state.update_data(tier_id=tier_id)
                await state.set_state(TrialFlow.awaiting_email)
                await message.answer(trial_decision_message(decision))
                return

            await state.clear()
            await message.answer(
                trial_decision_message(decision),
                reply_markup=_payment_markup(tier_id, tier["name"]),
            )
            return

        if decision.email_normalized is None:  # pragma: no cover - contrato puro.
            raise RuntimeError("Una decisión permitida debe incluir email normalizado")
        if _EMAIL_VERIFICATION:
            code = generate_code()
            await db.create_email_verification(
                conn,
                user_id,
                decision.email_normalized,
                hash_code(code),
                datetime.now(timezone.utc)
                + timedelta(minutes=_EMAIL_CODE_TTL_MINUTES),
            )
            subject, html = render_code_email(code=code, tier_name=tier["name"])
            sent = await send_email(
                to=email_raw.strip(),
                subject=subject,
                html=html,
            )
            if not sent:
                await state.update_data(tier_id=tier_id)
                await state.set_state(TrialFlow.awaiting_email)
                await message.answer(
                    "No pudimos enviar el código. Ingresá tu email para reintentar."
                )
                return

            await state.update_data(
                tier_id=tier_id,
                email_raw=email_raw.strip(),
                email_normalized=decision.email_normalized,
            )
            await state.set_state(TrialFlow.awaiting_code)
            await message.answer(
                "Te mandamos un código a tu email, ingresalo acá.",
                reply_markup=_email_code_markup(),
            )
            return

        grant = await db.grant_trial(
            conn=conn,
            user_id=user_id,
            tier_id=tier_id,
            email=email_raw.strip(),
            email_normalized=decision.email_normalized,
            source_ref=identity["source_ref"],
            trial_days=_TRIAL_DAYS,
        )

    await state.clear()
    if not grant.granted:
        reply_markup = (
            None
            if grant.reason == "membership_exists"
            else _payment_markup(tier_id, tier["name"])
        )
        await message.answer(
            grant_conflict_message(grant.reason),
            reply_markup=reply_markup,
        )
        return
    await message.answer(f"Preparando tu acceso a {tier['name']} ⏳")


@dp.callback_query(F.data.startswith("trial:"))
async def on_trial(callback: CallbackQuery, state: FSMContext) -> None:
    """Inicia el trial inmediatamente o entra al FSM para capturar email."""
    try:
        tier_id = int((callback.data or "").split(":", 1)[1])
    except (IndexError, ValueError):
        await callback.answer("Ese canal no es válido.", show_alert=True)
        return

    if not isinstance(callback.message, Message):
        await callback.answer("Enviá /start para actualizar el menú.", show_alert=True)
        return

    pool = await _ensure_pool()
    async with pool.acquire() as conn:
        identity = await db.fetch_identity(conn, callback.from_user.id)
        tier = await db.fetch_active_tier(conn, tier_id)
    if identity is None or tier is None:
        await callback.answer("Ese canal ya no está disponible.", show_alert=True)
        return

    if not identity["email"]:
        await state.update_data(tier_id=tier_id)
        await state.set_state(TrialFlow.awaiting_email)
        await callback.answer()
        await callback.message.answer(
            f"Ingresá tu email para activar el trial de {tier['name']}."
        )
        return

    await callback.answer("Procesando tu trial…")
    await _process_trial_candidate(
        callback.message,
        state,
        callback.from_user.id,
        tier_id,
        identity["email"],
    )


@dp.message(TrialFlow.awaiting_email)
async def on_trial_email(message: Message, state: FSMContext) -> None:
    """Valida el email candidato y retoma el tier guardado en el FSM."""
    user = message.from_user
    if user is None:
        return
    data = await state.get_data()
    tier_id = data.get("tier_id")
    if not isinstance(tier_id, int):
        await state.clear()
        await message.answer("El pedido venció. Enviá /start e intentá de nuevo.")
        return
    await _process_trial_candidate(
        message,
        state,
        user.id,
        tier_id,
        message.text or "",
    )


@dp.callback_query(TrialFlow.awaiting_code, F.data == "email_code:resend")
async def on_email_code_resend(
    callback: CallbackQuery,
    state: FSMContext,
) -> None:
    """Regenera el código solo tras volver a pasar las defensas D-4a."""
    if not isinstance(callback.message, Message):
        await callback.answer("Enviá /start para reintentar.", show_alert=True)
        return
    data = await state.get_data()
    tier_id = data.get("tier_id")
    email_raw = data.get("email_raw")
    if not isinstance(tier_id, int) or not isinstance(email_raw, str):
        await state.clear()
        await callback.answer("El pedido venció. Enviá /start.", show_alert=True)
        return

    await callback.answer("Reenviando código…")
    await _process_trial_candidate(
        callback.message,
        state,
        callback.from_user.id,
        tier_id,
        email_raw,
    )


@dp.message(TrialFlow.awaiting_code)
async def on_trial_code(message: Message, state: FSMContext) -> None:
    """Consume el código y concede el trial dentro de una transacción única."""
    user = message.from_user
    if user is None:
        return
    data = await state.get_data()
    tier_id = data.get("tier_id")
    email_raw = data.get("email_raw")
    if not isinstance(tier_id, int) or not isinstance(email_raw, str):
        await state.clear()
        await message.answer("El pedido venció. Enviá /start e intentá de nuevo.")
        return

    pool = await _ensure_pool()
    async with pool.acquire() as conn:
        identity = await db.fetch_identity(conn, user.id)
        tier = await db.fetch_active_tier(conn, tier_id)
        if identity is None or tier is None:
            await state.clear()
            await message.answer(
                "Ese canal ya no está disponible. Enviá /start para actualizar el menú."
            )
            return

        transaction = conn.transaction()
        await transaction.start()
        transaction_open = True
        try:
            consumed = await db.consume_email_verification(
                conn,
                user.id,
                (message.text or "").strip(),
                max_attempts=_EMAIL_CODE_MAX_ATTEMPTS,
                now=datetime.now(timezone.utc),
            )
            grant = None
            if consumed.ok:
                if consumed.email_normalized is None:  # pragma: no cover
                    raise RuntimeError("El código consumido no identifica un email")
                grant = await db.grant_trial(
                    conn=conn,
                    user_id=user.id,
                    tier_id=tier_id,
                    email=email_raw,
                    email_normalized=consumed.email_normalized,
                    source_ref=identity["source_ref"],
                    trial_days=_TRIAL_DAYS,
                )
                if grant.granted:
                    await transaction.commit()
                else:
                    # No persiste consumed_at/email_verified_at sin trial.
                    await transaction.rollback()
                transaction_open = False
            else:
                await transaction.commit()
                transaction_open = False
        except BaseException:
            if transaction_open:
                with suppress(Exception):
                    await transaction.rollback()
            raise

    if not consumed.ok:
        if consumed.decision.reason == "mismatch":
            await message.answer(
                f"{verify_decision_message(consumed.decision)} "
                f"Quedan {consumed.attempts_remaining} intentos.",
                reply_markup=_email_code_markup(),
            )
            return

        await state.clear()
        await state.update_data(tier_id=tier_id)
        await state.set_state(TrialFlow.awaiting_email)
        await message.answer(verify_decision_message(consumed.decision))
        return

    if grant is None:  # pragma: no cover - contrato de ConsumeResult.
        raise RuntimeError("Código válido sin resultado de concesión")
    await state.clear()
    if not grant.granted:
        reply_markup = (
            None
            if grant.reason == "membership_exists"
            else _payment_markup(tier_id, tier["name"])
        )
        await message.answer(
            grant_conflict_message(grant.reason),
            reply_markup=reply_markup,
        )
        return
    await message.answer(f"Preparando tu acceso a {tier['name']} ⏳")


@dp.callback_query(F.data.startswith("pay:"))
async def on_payment(callback: CallbackQuery) -> None:
    """Resuelve el tier y salta o muestra la selección de período."""
    try:
        tier_id = int((callback.data or "").split(":", 1)[1])
    except (IndexError, ValueError):
        await callback.answer("Ese canal no es válido.", show_alert=True)
        return
    if not isinstance(callback.message, Message):
        await callback.answer("Enviá /start para actualizar el menú.", show_alert=True)
        return

    pool = await _ensure_pool()
    async with pool.acquire() as conn:
        identity = await db.fetch_identity(conn, callback.from_user.id)
        tier = await db.fetch_active_tier(conn, tier_id)
        plans = await db.fetch_active_plans(conn, tier_id) if tier else []
    if identity is None or tier is None:
        await callback.answer("Ese canal ya no está disponible.", show_alert=True)
        return

    choice = select_plan_options(plans)
    if choice.mode is PlanChoiceMode.UNAVAILABLE:
        await callback.answer(
            "Este canal no tiene un plan de PayPal disponible.",
            show_alert=True,
        )
        return
    if choice.mode is PlanChoiceMode.MENU:
        await callback.answer()
        await callback.message.answer(
            f"Elegí el período para {tier['name']}:",
            reply_markup=_plan_choice_markup(tier_id, choice),
        )
        return

    await callback.answer("Preparando tu enlace de pago…")
    await _send_paypal_checkout(
        callback,
        tier,
        choice.direct_plan,
        identity["email"],
    )


@dp.callback_query(F.data.startswith("pay_plan:"))
async def on_payment_plan(callback: CallbackQuery) -> None:
    """Valida nuevamente tier/plan antes de crear la suscripción PayPal."""
    try:
        _prefix, raw_tier_id, raw_plan_id = (callback.data or "").split(":", 2)
        tier_id = int(raw_tier_id)
        plan_id = int(raw_plan_id)
    except (ValueError, TypeError):
        await callback.answer("Ese plan no es válido.", show_alert=True)
        return
    if not isinstance(callback.message, Message):
        await callback.answer("Enviá /start para actualizar el menú.", show_alert=True)
        return

    pool = await _ensure_pool()
    async with pool.acquire() as conn:
        identity = await db.fetch_identity(conn, callback.from_user.id)
        tier = await db.fetch_active_tier(conn, tier_id)
        plans = await db.fetch_active_plans(conn, tier_id) if tier else []
    plan = next((row for row in plans if int(row["id"]) == plan_id), None)
    if identity is None or tier is None or plan is None:
        await callback.answer("Ese plan ya no está disponible.", show_alert=True)
        return

    await callback.answer("Preparando tu enlace de pago…")
    await _send_paypal_checkout(callback, tier, plan, identity["email"])


async def _delivery_loop(bot: Bot) -> None:
    """Cablea DB + Bot API y mantiene el polling best-effort de invitaciones."""

    async def send_dm(user_id: int, text: str) -> None:
        await bot.send_message(chat_id=user_id, text=text)

    while True:
        try:
            pool = await _ensure_pool()
            async with pool.acquire() as conn:
                summary = await deliver_pending(
                    conn,
                    send_dm,
                    limit=_DM_BATCH_LIMIT,
                )
            if summary.delivered or summary.blocked or summary.errors:
                logger.info(
                    "batch DM: entregados=%s bloqueados=%s errores=%s",
                    summary.delivered,
                    summary.blocked,
                    summary.errors,
                )
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Falló el ciclo de entrega DM; se reintentará")
        await asyncio.sleep(_DM_POLL_SECONDS)


async def _main() -> int:
    token = os.environ.get("ONBOARDING_BOT_TOKEN", "").strip()
    if not token:
        logger.error(
            "Falta ONBOARDING_BOT_TOKEN; el bot de onboarding no puede iniciar."
        )
        return 2

    bot = Bot(token=token)
    delivery_task: asyncio.Task[None] | None = None
    try:
        me = await bot.get_me()
        logger.info("bot de onboarding iniciado como @%s (id=%s)", me.username, me.id)
        delivery_task = asyncio.create_task(
            _delivery_loop(bot),
            name="ofertascl-dm-delivery",
        )
        await dp.start_polling(bot, handle_signals=False)
    finally:
        if delivery_task is not None:
            delivery_task.cancel()
            with suppress(asyncio.CancelledError):
                await delivery_task
        await bot.session.close()
        if _pool is not None:
            await _pool.close()
    return 0


def main() -> int:
    try:
        return asyncio.run(_main())
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    sys.exit(main())
