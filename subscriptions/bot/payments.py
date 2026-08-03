"""Decisiones puras del checkout PayPal del bot de onboarding."""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from enum import Enum
import re
from typing import Any
from urllib.parse import urlsplit
from uuid import NAMESPACE_URL, uuid5


class PlanChoiceMode(str, Enum):
    """Resultado posible al resolver los planes pagables de un tier."""

    UNAVAILABLE = "unavailable"
    DIRECT = "direct"
    MENU = "menu"


@dataclass(frozen=True)
class PlanChoice:
    """Selección de plan independiente de DB, aiogram y PayPal."""

    mode: PlanChoiceMode
    plans: tuple[Any, ...]
    direct_plan: Any | None = None


class PaymentConfigurationError(ValueError):
    """La configuración local no permite crear un checkout seguro."""


_PERIOD_LABELS = {
    "weekly": "Semanal",
    "monthly": "Mensual",
    "quarterly": "Trimestral",
    "semiannual": "Semestral",
    "annual": "Anual",
}
_BOT_USERNAME_RE = re.compile(r"^[A-Za-z0-9_]{5,32}$")


def _field(record: Mapping[str, Any] | Any, key: str) -> Any:
    try:
        return record[key]
    except (KeyError, TypeError):
        return None


def build_custom_id(user_id: int, tier_id: int) -> str:
    """Construye la identidad exacta que consume el webhook F4.0."""
    if user_id <= 0 or tier_id <= 0:
        raise ValueError("user_id y tier_id deben ser positivos")
    return f"tg:{user_id}:{tier_id}"


def select_plan_options(plans: list[Any]) -> PlanChoice:
    """Decide si no hay checkout, si es directo o si requiere submenú."""
    options = tuple(plans)
    if not options:
        return PlanChoice(PlanChoiceMode.UNAVAILABLE, options)
    if len(options) == 1:
        return PlanChoice(PlanChoiceMode.DIRECT, options, options[0])
    return PlanChoice(PlanChoiceMode.MENU, options)


def format_period(plan: Mapping[str, Any] | Any) -> str:
    """Traduce el período persistido a copy estable en español."""
    period = str(_field(plan, "period") or "").strip().lower()
    return _PERIOD_LABELS.get(period, period.capitalize() or "Período")


def _format_price(plan: Mapping[str, Any] | Any) -> str:
    try:
        price = Decimal(str(_field(plan, "price_usd")))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError("El plan no tiene un precio USD válido") from exc
    if price <= 0:
        raise ValueError("El precio USD debe ser positivo")
    return f"USD {price:.2f}"


def format_plan_button(plan: Mapping[str, Any] | Any) -> str:
    """Copy compacto de una opción del submenú de períodos."""
    return f"{format_period(plan)} · {_format_price(plan)}"


def format_pay_prompt(
    tier: Mapping[str, Any] | Any,
    plan: Mapping[str, Any] | Any,
) -> str:
    """Mensaje mostrado junto al enlace externo de aprobación."""
    tier_name = str(_field(tier, "name") or "canal VIP").strip()
    return (
        f"Completá el pago de {tier_name} "
        f"({format_period(plan)}, {_format_price(plan)}) en PayPal. "
        "Tu acceso se activará cuando PayPal confirme el pago."
    )


def build_request_id(
    callback_id: str,
    user_id: int,
    tier_id: int,
    plan_id: int,
) -> str:
    """Genera una clave PayPal estable para reintentos del mismo callback."""
    if not callback_id:
        raise ValueError("callback_id no puede estar vacío")
    identity = f"telegram-paypal:{callback_id}:{user_id}:{tier_id}:{plan_id}"
    return str(uuid5(NAMESPACE_URL, identity))


def _valid_https_url(value: str) -> bool:
    parsed = urlsplit(value)
    try:
        port = parsed.port
    except ValueError:
        return False
    return bool(
        parsed.scheme == "https"
        and parsed.hostname
        and parsed.username is None
        and parsed.password is None
        and port in (None, 443)
        and not parsed.fragment
    )


def resolve_redirect_urls(
    *,
    bot_username: str,
    return_url: str | None,
    cancel_url: str | None,
) -> tuple[str, str]:
    """Resuelve overrides HTTPS o deep-links seguros de regreso al bot."""
    username = bot_username.strip().lstrip("@").strip()
    if username and not _BOT_USERNAME_RE.fullmatch(username):
        username = ""
    default_return = (
        f"https://t.me/{username}?start=paypal_approved" if username else ""
    )
    default_cancel = (
        f"https://t.me/{username}?start=paypal_cancelled" if username else ""
    )
    resolved_return = (return_url or "").strip() or default_return
    resolved_cancel = (cancel_url or "").strip() or default_cancel
    if not _valid_https_url(resolved_return) or not _valid_https_url(resolved_cancel):
        raise PaymentConfigurationError(
            "Configurá URLs HTTPS de PayPal o un ONBOARDING_BOT_USERNAME válido"
        )
    return resolved_return, resolved_cancel
