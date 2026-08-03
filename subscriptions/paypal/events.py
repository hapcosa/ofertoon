"""Aplicación idempotente de eventos PayPal a las membresías Telegram.

PORT de `signalsTrading/dashboard/backend/paypal_subscription_events.py`. La
lógica de estados, orden de eventos y validación de montos se copia sin tocar.
Solo se sacó lo que pertenece al checkout web de signalsTrading, que OfertasCL
no porta: el cruce con la tabla `users` (`web_user_id`) y el espejo en
`paypal_checkout_sessions`. Acá toda identidad nace en el bot.

El estado de cobro vive por `(telegram_user_id, tier_id)` en
`telegram_memberships`; `telegram_subscribers` queda como IDENTIDAD (email). El
`custom_id` de PayPal acepta `tg:<user>` y `tg:<user>:<tier>`. El tier
autoritativo se resuelve SIEMPRE por el plan
(`telegram_tier_plans.paypal_plan_id → tier_id`); el tier del custom_id, si
viene, debe coincidir (si no, se rechaza). Un plan/precio/identidad desconocidos
se auditan sin conceder acceso.
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import re
from typing import Any


# tg:<user_id>  ó  tg:<user_id>:<tier_id>
_TELEGRAM_CUSTOM_ID = re.compile(
    r"^tg:([1-9][0-9]{0,18})(?::([1-9][0-9]{0,9}))?$"
)
_TERMINAL_STATUSES = {"canceled", "expired"}

_SUBSCRIPTION_SYNC_EVENTS = {
    "BILLING.SUBSCRIPTION.ACTIVATED",
    "BILLING.SUBSCRIPTION.UPDATED",
}
_SUBSCRIPTION_TERMINAL_EVENTS = {
    "BILLING.SUBSCRIPTION.SUSPENDED": "past_due",
    "BILLING.SUBSCRIPTION.CANCELLED": "canceled",
    "BILLING.SUBSCRIPTION.EXPIRED": "expired",
}
_PAYMENT_RISK_EVENTS = {
    "BILLING.SUBSCRIPTION.PAYMENT.FAILED",
    "PAYMENT.SALE.REFUNDED",
    "PAYMENT.SALE.REVERSED",
}


class RejectedPayPalEvent(ValueError):
    """Evento auténtico pero inconsistente; se audita sin conceder acceso."""


def _event_time(event: dict[str, Any]) -> datetime:
    value = event.get("create_time")
    if not isinstance(value, str) or not value.strip():
        raise RejectedPayPalEvent("missing create_time")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise RejectedPayPalEvent("invalid create_time") from exc
    if parsed.tzinfo is None:
        raise RejectedPayPalEvent("create_time must include timezone")
    return parsed.astimezone(timezone.utc)


def _optional_time(value: Any, field: str) -> datetime | None:
    if value in (None, ""):
        return None
    if not isinstance(value, str):
        raise RejectedPayPalEvent(f"invalid {field}")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise RejectedPayPalEvent(f"invalid {field}") from exc
    if parsed.tzinfo is None:
        raise RejectedPayPalEvent(f"{field} must include timezone")
    return parsed.astimezone(timezone.utc)


def _clean_string(value: Any, *, max_length: int) -> str | None:
    if value is None:
        return None
    cleaned = str(value).strip()
    if not cleaned:
        return None
    if len(cleaned) > max_length:
        raise RejectedPayPalEvent("PayPal field exceeds schema limit")
    return cleaned


def _telegram_custom_id(custom_id: Any) -> tuple[int | None, int | None]:
    """Devuelve (telegram_user_id, tier_id) parseados del custom_id.

    Acepta `tg:<user>` (F2, sin tier) y `tg:<user>:<tier>` (F4). Un custom_id
    ausente o malformado devuelve (None, None): la identidad se resuelve por el
    subscription_id ya conocido (evento UPDATED sin custom_id, p.ej.).
    """
    if not isinstance(custom_id, str):
        return None, None
    match = _TELEGRAM_CUSTOM_ID.fullmatch(custom_id.strip())
    if not match:
        return None, None
    user_id = int(match.group(1))
    if user_id > 9_223_372_036_854_775_807:
        return None, None
    tier_id = int(match.group(2)) if match.group(2) is not None else None
    return user_id, tier_id


def _subscription_id(event_type: str, resource: dict[str, Any]) -> str | None:
    for key in ("billing_agreement_id", "subscription_id"):
        value = _clean_string(resource.get(key), max_length=64)
        if value:
            return value
    if event_type.startswith("BILLING.SUBSCRIPTION."):
        return _clean_string(resource.get("id"), max_length=64)
    return None


def _resource(event: dict[str, Any]) -> dict[str, Any]:
    resource = event.get("resource")
    if not isinstance(resource, dict):
        raise RejectedPayPalEvent("resource must be an object")
    return resource


def _status_from_resource(resource: dict[str, Any]) -> str | None:
    status = str(resource.get("status") or "").strip().upper()
    return {
        "ACTIVE": "active",
        "SUSPENDED": "past_due",
        "CANCELLED": "canceled",
        "EXPIRED": "expired",
    }.get(status)


async def _upsert_identity(conn, telegram_user_id: int, email: str | None) -> None:
    """Garantiza la fila de IDENTIDAD (FK de la membresía).

    El email que manda PayPal puede no ser el que el usuario verificó en el bot,
    así que solo rellena un hueco: `COALESCE` deja intacto el que ya estaba.
    """
    await conn.execute(
        """INSERT INTO telegram_subscribers (telegram_user_id, email)
                VALUES ($1, $2)
           ON CONFLICT (telegram_user_id) DO UPDATE
                 SET email = COALESCE(telegram_subscribers.email, $2),
                     updated_at = NOW()""",
        telegram_user_id,
        email,
    )


async def _sync_subscription(
    conn, event_type: str, event: dict[str, Any]
) -> tuple[str, str | None]:
    resource = _resource(event)
    subscription_id = _subscription_id(event_type, resource)
    if not subscription_id:
        raise RejectedPayPalEvent("missing PayPal subscription id")

    existing_by_sub = await conn.fetchrow(
        """SELECT telegram_user_id, tier_id
             FROM telegram_memberships
            WHERE paypal_subscription_id = $1""",
        subscription_id,
    )
    plan_id = _clean_string(resource.get("plan_id"), max_length=64)
    if not plan_id:
        raise RejectedPayPalEvent("missing PayPal plan id")
    plan = await conn.fetchrow(
        """SELECT p.id AS tier_plan_id, p.tier_id
             FROM telegram_tier_plans p
             JOIN telegram_tiers t ON t.id = p.tier_id
            WHERE p.paypal_plan_id = $1
              AND (p.is_active = TRUE OR $2::boolean = TRUE)
              AND t.is_active = TRUE""",
        plan_id,
        existing_by_sub is not None,
    )
    if not plan:
        raise RejectedPayPalEvent("unknown or inactive PayPal plan")

    custom_user, custom_tier = _telegram_custom_id(resource.get("custom_id"))
    tier_id = plan["tier_id"]
    if custom_tier is not None and custom_tier != tier_id:
        raise RejectedPayPalEvent("custom_id tier conflicts with PayPal plan")
    if existing_by_sub:
        if custom_user not in (None, existing_by_sub["telegram_user_id"]):
            raise RejectedPayPalEvent("custom_id conflicts with existing subscription")
        if existing_by_sub["tier_id"] != tier_id:
            raise RejectedPayPalEvent("PayPal plan tier conflicts with subscription")
        telegram_user_id = existing_by_sub["telegram_user_id"]
    else:
        telegram_user_id = custom_user
    if telegram_user_id is None:
        raise RejectedPayPalEvent("custom_id must use tg:<telegram_user_id>[:<tier_id>]")

    subscriber = resource.get("subscriber")
    subscriber = subscriber if isinstance(subscriber, dict) else {}
    payer_id = _clean_string(subscriber.get("payer_id"), max_length=64)
    email = _clean_string(subscriber.get("email_address"), max_length=255)
    billing_info = resource.get("billing_info")
    billing_info = billing_info if isinstance(billing_info, dict) else {}
    period_end = _optional_time(
        billing_info.get("next_billing_time"), "billing_info.next_billing_time"
    )
    event_at = _event_time(event)
    status = "active" if event_type.endswith(".ACTIVATED") else _status_from_resource(resource)
    if status is None:
        return "ignored", "subscription update has no actionable status"

    current = await conn.fetchrow(
        """SELECT payment_provider, status, paypal_subscription_id,
                  paypal_last_event_at
             FROM telegram_memberships
            WHERE telegram_user_id = $1 AND tier_id = $2
            FOR UPDATE""",
        telegram_user_id,
        tier_id,
    )
    if current:
        current_provider = current["payment_provider"]
        current_status = current["status"]
        current_subscription = current["paypal_subscription_id"]
        if (
            current_provider not in (None, "paypal")
            and current_status not in _TERMINAL_STATUSES
        ):
            raise RejectedPayPalEvent("membership has another active payment provider")
        if (
            current_subscription not in (None, subscription_id)
            and current_status not in _TERMINAL_STATUSES
        ):
            raise RejectedPayPalEvent("membership has another active PayPal subscription")
        if current["paypal_last_event_at"] and event_at < current["paypal_last_event_at"]:
            return "ignored", "out-of-order subscription event"
        if (
            current["paypal_last_event_at"] == event_at
            and current_status in _TERMINAL_STATUSES
            and status not in _TERMINAL_STATUSES
        ):
            return "ignored", "equal-time event cannot override terminal status"

    await _upsert_identity(conn, telegram_user_id, email)
    if current:
        await conn.execute(
            """UPDATE telegram_memberships
                  SET payment_provider = 'paypal',
                      paypal_payer_id = COALESCE($3, paypal_payer_id),
                      paypal_subscription_id = $4,
                      paypal_last_event_at = $5,
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
            subscription_id,
            event_at,
            plan["tier_plan_id"],
            status,
            period_end,
        )
    else:
        await conn.execute(
            """INSERT INTO telegram_memberships
                   (telegram_user_id, tier_id, payment_provider, paypal_payer_id,
                    paypal_subscription_id, paypal_last_event_at, tier_plan_id,
                    status, current_period_end, source_ref)
                 VALUES ($1, $2, 'paypal', $3, $4, $5, $6, $7, $8,
                         (SELECT source_ref
                            FROM telegram_subscribers
                           WHERE telegram_user_id = $1))""",
            telegram_user_id,
            tier_id,
            payer_id,
            subscription_id,
            event_at,
            plan["tier_plan_id"],
            status,
            period_end,
        )
    return "processed", None


async def _set_subscription_status(
    conn, event_type: str, event: dict[str, Any], status: str
) -> tuple[str, str | None]:
    resource = _resource(event)
    subscription_id = _subscription_id(event_type, resource)
    if not subscription_id:
        raise RejectedPayPalEvent("missing PayPal subscription id")
    event_at = _event_time(event)
    row = await conn.fetchrow(
        """UPDATE telegram_memberships
              SET status = $2,
                  paypal_last_event_at = $3,
                  updated_at = NOW()
            WHERE paypal_subscription_id = $1
              AND (paypal_last_event_at IS NULL OR paypal_last_event_at <= $3)
        RETURNING telegram_user_id""",
        subscription_id,
        status,
        event_at,
    )
    if row:
        return "processed", None
    exists = await conn.fetchval(
        "SELECT 1 FROM telegram_memberships WHERE paypal_subscription_id = $1",
        subscription_id,
    )
    if exists:
        return "ignored", "out-of-order subscription event"
    raise RejectedPayPalEvent("unknown PayPal subscription")


def _payment_amount(resource: dict[str, Any]) -> tuple[Decimal, str]:
    amount = resource.get("amount")
    if not isinstance(amount, dict):
        raise RejectedPayPalEvent("missing payment amount")
    raw_value = amount.get("total", amount.get("value"))
    currency = str(amount.get("currency") or amount.get("currency_code") or "").upper()
    try:
        value = Decimal(str(raw_value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise RejectedPayPalEvent("invalid payment amount") from exc
    if value <= 0 or not currency:
        raise RejectedPayPalEvent("invalid payment amount")
    return value, currency


async def _payment_completed(
    conn, event_type: str, event: dict[str, Any]
) -> tuple[str, str | None]:
    resource = _resource(event)
    subscription_id = _subscription_id(event_type, resource)
    if not subscription_id:
        raise RejectedPayPalEvent("missing PayPal subscription id")
    amount, currency = _payment_amount(resource)
    membership = await conn.fetchrow(
        """SELECT m.telegram_user_id, m.tier_id, m.status, p.price_usd
             FROM telegram_memberships m
             JOIN telegram_tier_plans p ON p.id = m.tier_plan_id
            WHERE m.paypal_subscription_id = $1
            FOR UPDATE OF m""",
        subscription_id,
    )
    if not membership:
        raise RejectedPayPalEvent("unknown PayPal subscription")
    expected = membership["price_usd"]
    if expected is None:
        raise RejectedPayPalEvent("PayPal plan has no USD price")
    if currency != "USD" or amount != expected:
        raise RejectedPayPalEvent("payment amount or currency mismatch")

    event_at = _event_time(event)
    # El pago más reciente siempre se conserva (paypal_last_payment_at avanza a
    # su máximo), pero el `status` solo se reactiva a 'active' cuando este evento
    # es al menos tan nuevo como el último aplicado. Un pago viejo entregado
    # fuera de orden (posterior a un evento de riesgo más nuevo) NO reactiva.
    # Los estados terminales canceled/expired nunca se reactivan.
    row = await conn.fetchrow(
        """UPDATE telegram_memberships
              SET status = CASE
                      WHEN status IN ('canceled', 'expired') THEN status
                      WHEN paypal_last_event_at IS NULL
                           OR paypal_last_event_at <= $2 THEN 'active'
                      ELSE status END,
                  paypal_last_payment_at = CASE
                      WHEN paypal_last_payment_at IS NULL OR paypal_last_payment_at < $2
                      THEN $2 ELSE paypal_last_payment_at END,
                  paypal_last_event_at = CASE
                      WHEN paypal_last_event_at IS NULL OR paypal_last_event_at < $2
                      THEN $2 ELSE paypal_last_event_at END,
                  updated_at = NOW()
            WHERE paypal_subscription_id = $1
        RETURNING status""",
        subscription_id,
        event_at,
    )
    if not row:
        raise RejectedPayPalEvent("unknown PayPal subscription")
    return "processed", None


async def _payment_at_risk(
    conn, event_type: str, event: dict[str, Any]
) -> tuple[str, str | None]:
    resource = _resource(event)
    subscription_id = _subscription_id(event_type, resource)
    if not subscription_id:
        raise RejectedPayPalEvent("missing PayPal subscription id")
    event_at = _event_time(event)
    # Solo degradar a 'past_due' cuando el evento de riesgo es al menos tan
    # nuevo como el último aplicado; un riesgo viejo entregado fuera de orden
    # (posterior a una activación/pago más nuevo) NO debe degradar. Los estados
    # terminales canceled/expired nunca se reactivan ni cambian.
    row = await conn.fetchrow(
        """UPDATE telegram_memberships
              SET status = CASE
                      WHEN status IN ('canceled', 'expired') THEN status
                      WHEN paypal_last_event_at IS NULL
                           OR paypal_last_event_at <= $2 THEN 'past_due'
                      ELSE status END,
                  paypal_last_event_at = CASE
                      WHEN paypal_last_event_at IS NULL OR paypal_last_event_at < $2
                      THEN $2 ELSE paypal_last_event_at END,
                  updated_at = NOW()
            WHERE paypal_subscription_id = $1
        RETURNING status""",
        subscription_id,
        event_at,
    )
    if not row:
        raise RejectedPayPalEvent("unknown PayPal subscription")
    return "processed", None


async def apply_paypal_event(
    conn, event: dict[str, Any]
) -> tuple[str, str | None]:
    """Aplica un evento ya verificado y devuelve (estado, detalle de auditoría)."""
    event_type = _clean_string(event.get("event_type"), max_length=96)
    if not event_type:
        raise RejectedPayPalEvent("missing event_type")

    if event_type == "BILLING.SUBSCRIPTION.CREATED":
        return "ignored", "subscription created but not active"
    if event_type in _SUBSCRIPTION_SYNC_EVENTS:
        return await _sync_subscription(conn, event_type, event)
    if event_type in _SUBSCRIPTION_TERMINAL_EVENTS:
        return await _set_subscription_status(
            conn, event_type, event, _SUBSCRIPTION_TERMINAL_EVENTS[event_type]
        )
    if event_type == "PAYMENT.SALE.COMPLETED":
        return await _payment_completed(conn, event_type, event)
    if event_type in _PAYMENT_RISK_EVENTS:
        return await _payment_at_risk(conn, event_type, event)
    return "ignored", "event type is not used by OfertasCL"
