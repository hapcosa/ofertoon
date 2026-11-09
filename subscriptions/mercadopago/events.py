"""Aplicación idempotente de eventos MercadoPago a las membresías Telegram.

Mismo modelo de estados que `subscriptions/paypal/events.py` (mismo
`telegram_memberships`, mismo `(telegram_user_id, tier_id)`), pero con una
diferencia estructural real: la notificación de MercadoPago NO trae el recurso
—solo `{type, data: {id}}`—, así que acá SIEMPRE hay que ir a buscar el recurso
autoritativo a la API (`client.get_preapproval` / `client.get_authorized_payment`)
antes de poder decidir nada. Eso es, de hecho, más seguro que confiar en campos
de un body de webhook: lo único que prueba la firma es "MercadoPago me dijo que
mire este id"; lo que prueba el monto y el estado es la respuesta de la API,
autenticada con nuestro propio access token.

Por la misma razón, `subscription_preapproval` es UN solo tipo de evento para
las cuatro transiciones de estado (a diferencia de PayPal, que tiene un tipo de
evento por transición), así que no hay forma de distinguir "primera vez que
vemos esta suscripción" de "ya la conocíamos" mirando el tipo de evento: la
resolución por plan + por suscripción existente se hace siempre, para las
cuatro.
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import re
from typing import Any, Protocol

from .client import MercadoPagoAPIError


# tg:<user_id>  ó  tg:<user_id>:<tier_id> — mismo formato que
# subscriptions/paypal/events.py. Se duplica a propósito en vez de compartir
# import: cada proveedor se audita solo, igual que el resto del port de
# signalsTrading ya eligió hacer en este repo.
_TELEGRAM_CUSTOM_ID = re.compile(
    r"^tg:([1-9][0-9]{0,18})(?::([1-9][0-9]{0,9}))?$"
)
_TERMINAL_STATUSES = {"canceled", "expired"}

# Mapeo de `preapproval.status` (MercadoPago) a nuestro `status` deseado.
# "pending" no es accionable todavía — el pagador creó la suscripción pero no
# la aprobó — igual que BILLING.SUBSCRIPTION.CREATED en PayPal.
_PREAPPROVAL_STATUS_MAP = {
    "authorized": "active",
    "paused": "past_due",
    "cancelled": "canceled",
}


class RejectedMercadoPagoEvent(ValueError):
    """Evento auténtico pero inconsistente, o recurso referenciado inexistente;
    se audita sin conceder acceso."""


class MercadoPagoResourceFetcher(Protocol):
    async def get_preapproval(self, preapproval_id: str) -> dict[str, Any]: ...
    async def get_authorized_payment(self, authorized_payment_id: str) -> dict[str, Any]: ...


def _clean_string(value: Any, *, max_length: int) -> str | None:
    if value is None:
        return None
    cleaned = str(value).strip()
    if not cleaned:
        return None
    if len(cleaned) > max_length:
        raise RejectedMercadoPagoEvent("MercadoPago field exceeds schema limit")
    return cleaned


def _optional_time(value: Any, field: str) -> datetime | None:
    if value in (None, ""):
        return None
    if not isinstance(value, str):
        raise RejectedMercadoPagoEvent(f"invalid {field}")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise RejectedMercadoPagoEvent(f"invalid {field}") from exc
    if parsed.tzinfo is None:
        raise RejectedMercadoPagoEvent(f"{field} must include timezone")
    return parsed.astimezone(timezone.utc)


def _event_time(envelope: dict[str, Any]) -> datetime:
    """Hora del EVENTO (la notificación), no del recurso: mismo criterio de
    orden que `paypal/events.py._event_time` usa sobre `create_time`."""
    value = envelope.get("date_created")
    if not isinstance(value, str) or not value.strip():
        raise RejectedMercadoPagoEvent("missing date_created")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise RejectedMercadoPagoEvent("invalid date_created") from exc
    if parsed.tzinfo is None:
        raise RejectedMercadoPagoEvent("date_created must include timezone")
    return parsed.astimezone(timezone.utc)


def _telegram_custom_id(external_reference: Any) -> tuple[int | None, int | None]:
    """Devuelve (telegram_user_id, tier_id) parseados de `external_reference`."""
    if not isinstance(external_reference, str):
        return None, None
    match = _TELEGRAM_CUSTOM_ID.fullmatch(external_reference.strip())
    if not match:
        return None, None
    user_id = int(match.group(1))
    if user_id > 9_223_372_036_854_775_807:
        return None, None
    tier_id = int(match.group(2)) if match.group(2) is not None else None
    return user_id, tier_id


def _data_id(envelope: dict[str, Any]) -> str:
    data = envelope.get("data")
    if not isinstance(data, dict):
        raise RejectedMercadoPagoEvent("missing data object")
    value = _clean_string(data.get("id"), max_length=64)
    if not value:
        raise RejectedMercadoPagoEvent("missing data.id")
    return value


async def _fetch_or_reject(
    coro,
) -> dict[str, Any]:
    """Traduce un 404/4xx de MercadoPago en rechazo auditable.

    Deliberadamente NO atrapa `MercadoPagoUnavailable` ni
    `MercadoPagoConfigurationError`: esas dos no son culpa del evento (son un
    5xx transitorio o un access token roto) y tienen que propagar para que el
    webhook conteste 503 y MercadoPago reintente — convertirlas en "rejected"
    clasificaría mal un pago real por una falla nuestra.
    """
    try:
        return await coro
    except MercadoPagoAPIError as exc:
        raise RejectedMercadoPagoEvent(
            f"mercadopago resource fetch rejected: {exc}"
        ) from exc


async def _sync_preapproval(
    conn, envelope: dict[str, Any], client: MercadoPagoResourceFetcher
) -> tuple[str, str | None]:
    preapproval_id = _data_id(envelope)
    resource = await _fetch_or_reject(client.get_preapproval(preapproval_id))
    returned_id = _clean_string(resource.get("id"), max_length=64)
    if returned_id != preapproval_id:
        raise RejectedMercadoPagoEvent("MercadoPago returned a mismatched preapproval")

    existing_by_sub = await conn.fetchrow(
        """SELECT telegram_user_id, tier_id
             FROM telegram_memberships
            WHERE mercadopago_preapproval_id = $1""",
        preapproval_id,
    )
    plan_id = _clean_string(resource.get("preapproval_plan_id"), max_length=64)
    if not plan_id:
        raise RejectedMercadoPagoEvent("missing MercadoPago plan id")
    plan = await conn.fetchrow(
        """SELECT p.id AS tier_plan_id, p.tier_id
             FROM telegram_tier_plans p
             JOIN telegram_tiers t ON t.id = p.tier_id
            WHERE p.mercadopago_plan_id = $1
              AND (p.is_active = TRUE OR $2::boolean = TRUE)
              AND t.is_active = TRUE""",
        plan_id,
        existing_by_sub is not None,
    )
    if not plan:
        raise RejectedMercadoPagoEvent("unknown or inactive MercadoPago plan")

    custom_user, custom_tier = _telegram_custom_id(resource.get("external_reference"))
    tier_id = plan["tier_id"]
    if custom_tier is not None and custom_tier != tier_id:
        raise RejectedMercadoPagoEvent("external_reference tier conflicts with MercadoPago plan")
    if existing_by_sub:
        if custom_user not in (None, existing_by_sub["telegram_user_id"]):
            raise RejectedMercadoPagoEvent("external_reference conflicts with existing subscription")
        if existing_by_sub["tier_id"] != tier_id:
            raise RejectedMercadoPagoEvent("MercadoPago plan tier conflicts with subscription")
        telegram_user_id = existing_by_sub["telegram_user_id"]
    else:
        telegram_user_id = custom_user
    if telegram_user_id is None:
        raise RejectedMercadoPagoEvent(
            "external_reference must use tg:<telegram_user_id>[:<tier_id>]"
        )

    payer_id = _clean_string(resource.get("payer_id"), max_length=64)
    email = _clean_string(resource.get("payer_email"), max_length=255)
    period_end = _optional_time(resource.get("next_payment_date"), "next_payment_date")
    event_at = _event_time(envelope)

    mp_status = str(resource.get("status") or "").strip().lower()
    status = _PREAPPROVAL_STATUS_MAP.get(mp_status)
    if status is None:
        return "ignored", f"preapproval status '{mp_status}' is not actionable"

    current = await conn.fetchrow(
        """SELECT payment_provider, status, mercadopago_preapproval_id,
                  mercadopago_last_event_at
             FROM telegram_memberships
            WHERE telegram_user_id = $1 AND tier_id = $2
            FOR UPDATE""",
        telegram_user_id,
        tier_id,
    )
    if current:
        current_provider = current["payment_provider"]
        current_status = current["status"]
        current_sub = current["mercadopago_preapproval_id"]
        if (
            current_provider not in (None, "mercadopago")
            and current_status not in _TERMINAL_STATUSES
        ):
            raise RejectedMercadoPagoEvent("membership has another active payment provider")
        if (
            current_sub not in (None, preapproval_id)
            and current_status not in _TERMINAL_STATUSES
        ):
            raise RejectedMercadoPagoEvent("membership has another active MercadoPago subscription")
        if current["mercadopago_last_event_at"] and event_at < current["mercadopago_last_event_at"]:
            return "ignored", "out-of-order subscription event"
        if (
            current["mercadopago_last_event_at"] == event_at
            and current_status in _TERMINAL_STATUSES
            and status not in _TERMINAL_STATUSES
        ):
            return "ignored", "equal-time event cannot override terminal status"

    await conn.execute(
        """INSERT INTO telegram_subscribers (telegram_user_id, email)
                VALUES ($1, $2)
           ON CONFLICT (telegram_user_id) DO UPDATE
                 SET email = COALESCE(telegram_subscribers.email, $2),
                     updated_at = NOW()""",
        telegram_user_id,
        email,
    )
    if current:
        await conn.execute(
            """UPDATE telegram_memberships
                  SET payment_provider = 'mercadopago',
                      mercadopago_payer_id = COALESCE($3, mercadopago_payer_id),
                      mercadopago_preapproval_id = $4,
                      mercadopago_last_event_at = $5,
                      tier_plan_id = $6,
                      status = $7,
                      current_period_end = COALESCE($8, current_period_end),
                      source_ref = COALESCE(
                          telegram_memberships.source_ref,
                          (SELECT source_ref
                             FROM telegram_subscribers
                            WHERE telegram_user_id = $1)
                      ),
                      updated_at = NOW()
                WHERE telegram_user_id = $1 AND tier_id = $2""",
            telegram_user_id,
            tier_id,
            payer_id,
            preapproval_id,
            event_at,
            plan["tier_plan_id"],
            status,
            period_end,
        )
    else:
        await conn.execute(
            """INSERT INTO telegram_memberships
                   (telegram_user_id, tier_id, payment_provider, mercadopago_payer_id,
                    mercadopago_preapproval_id, mercadopago_last_event_at, tier_plan_id,
                    status, current_period_end, source_ref)
                 VALUES ($1, $2, 'mercadopago', $3, $4, $5, $6, $7, $8,
                         (SELECT source_ref
                            FROM telegram_subscribers
                           WHERE telegram_user_id = $1))""",
            telegram_user_id,
            tier_id,
            payer_id,
            preapproval_id,
            event_at,
            plan["tier_plan_id"],
            status,
            period_end,
        )
    return "processed", None


def _payment_amount(resource: dict[str, Any]) -> tuple[int, str]:
    raw_value = resource.get("transaction_amount")
    currency = str(resource.get("currency_id") or "").strip().upper()
    try:
        value = Decimal(str(raw_value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise RejectedMercadoPagoEvent("invalid payment amount") from exc
    if value <= 0 or value != value.to_integral_value() or not currency:
        raise RejectedMercadoPagoEvent("invalid payment amount")
    return int(value), currency


async def _authorized_payment(
    conn, envelope: dict[str, Any], client: MercadoPagoResourceFetcher
) -> tuple[str, str | None]:
    authorized_payment_id = _data_id(envelope)
    resource = await _fetch_or_reject(
        client.get_authorized_payment(authorized_payment_id)
    )
    preapproval_id = _clean_string(resource.get("preapproval_id"), max_length=64)
    if not preapproval_id:
        raise RejectedMercadoPagoEvent("missing MercadoPago preapproval id")
    amount, currency = _payment_amount(resource)

    membership = await conn.fetchrow(
        """SELECT m.telegram_user_id, m.tier_id, m.status, p.price_clp
             FROM telegram_memberships m
             JOIN telegram_tier_plans p ON p.id = m.tier_plan_id
            WHERE m.mercadopago_preapproval_id = $1
            FOR UPDATE OF m""",
        preapproval_id,
    )
    if not membership:
        raise RejectedMercadoPagoEvent("unknown MercadoPago subscription")
    expected = membership["price_clp"]
    if expected is None:
        raise RejectedMercadoPagoEvent("MercadoPago plan has no CLP price")
    if currency != "CLP" or amount != expected:
        raise RejectedMercadoPagoEvent("payment amount or currency mismatch")

    event_at = _event_time(envelope)
    mp_status = str(resource.get("status") or "").strip().lower()

    if mp_status == "processed":
        row = await conn.fetchrow(
            """UPDATE telegram_memberships
                  SET status = CASE
                          WHEN status IN ('canceled', 'expired') THEN status
                          WHEN mercadopago_last_event_at IS NULL
                               OR mercadopago_last_event_at <= $2 THEN 'active'
                          ELSE status END,
                      mercadopago_last_payment_at = CASE
                          WHEN mercadopago_last_payment_at IS NULL
                               OR mercadopago_last_payment_at < $2
                          THEN $2 ELSE mercadopago_last_payment_at END,
                      mercadopago_last_event_at = CASE
                          WHEN mercadopago_last_event_at IS NULL
                               OR mercadopago_last_event_at < $2
                          THEN $2 ELSE mercadopago_last_event_at END,
                      updated_at = NOW()
                WHERE mercadopago_preapproval_id = $1
            RETURNING status""",
            preapproval_id,
            event_at,
        )
    elif mp_status == "rejected":
        row = await conn.fetchrow(
            """UPDATE telegram_memberships
                  SET status = CASE
                          WHEN status IN ('canceled', 'expired') THEN status
                          WHEN mercadopago_last_event_at IS NULL
                               OR mercadopago_last_event_at <= $2 THEN 'past_due'
                          ELSE status END,
                      mercadopago_last_event_at = CASE
                          WHEN mercadopago_last_event_at IS NULL
                               OR mercadopago_last_event_at < $2
                          THEN $2 ELSE mercadopago_last_event_at END,
                      updated_at = NOW()
                WHERE mercadopago_preapproval_id = $1
            RETURNING status""",
            preapproval_id,
            event_at,
        )
    else:
        return "ignored", f"authorized_payment status '{mp_status}' is not actionable"
    if not row:
        raise RejectedMercadoPagoEvent("unknown MercadoPago subscription")
    return "processed", None


async def apply_mercadopago_event(
    conn, envelope: dict[str, Any], client: MercadoPagoResourceFetcher
) -> tuple[str, str | None]:
    """Aplica una notificación ya verificada y devuelve (estado, detalle)."""
    event_type = _clean_string(envelope.get("type"), max_length=96)
    if not event_type:
        raise RejectedMercadoPagoEvent("missing type")

    if event_type == "subscription_preapproval":
        return await _sync_preapproval(conn, envelope, client)
    if event_type == "subscription_authorized_payment":
        return await _authorized_payment(conn, envelope, client)
    return "ignored", "event type is not used by OfertasCL"
