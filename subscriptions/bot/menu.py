"""Modelo puro del menú multi-tier del bot de onboarding."""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from math import ceil
from typing import Any


@dataclass(frozen=True)
class MenuButton:
    """Botón independiente de aiogram/Telegram Bot API."""

    text: str
    callback_data: str


@dataclass(frozen=True)
class TierStats:
    """Track record agregado de un tier: lo que se publicó ahí, no lo prometido.

    ``posts`` es la cantidad de ofertas publicadas en la ventana rodante,
    ``avg_discount`` y ``best_discount`` son fracciones (0.35 = 35%) medidas
    contra el p50 de 60 días — el descuento real, no el que declara la tienda.
    """

    posts: int
    avg_discount: Decimal
    best_discount: Decimal


@dataclass(frozen=True)
class TierMenuRow:
    """Estado y acciones visibles para un tier."""

    tier_id: int
    name: str
    slug: str
    description: str | None
    status_label: str
    trial_available: bool
    payment_available: bool
    buttons: tuple[MenuButton, ...]
    stats_line: str | None = None


@dataclass(frozen=True)
class MenuModel:
    """Contenido completo del menú, sin dependencias de red o aiogram."""

    title: str
    copy: str
    rows: tuple[TierMenuRow, ...]


_STATUS_LABELS = {
    "pending": "Pendiente",
    "trialing": "⏳ En trial",
    "active": "✅ Miembro",
    "past_due": "Pago pendiente",
    "grace": "Período de gracia",
    "canceled": "Cancelado",
    "expired": "Vencido",
}

# Copy del avance de entrega para una membresía activa. Un miembro ya entró al
# canal; 'invited' recibió el link pero todavía no se unió; el resto está a la
# espera de que el gate genere el acceso.
_ACTIVE_CHANNEL_LABELS = {
    "member": "✅ Miembro",
    "invited": "✅ Activo · link enviado",
    "kicked": "⚠️ Activo · reingreso pendiente",
}
_ACTIVE_DEFAULT_LABEL = "✅ Activo · preparando acceso"


def membership_status_label(
    status: str | None,
    channel_state: str | None,
) -> str:
    """Traduce todos los estados válidos de membresía a copy español.

    ``status`` es la autoridad del producto. Para una membresía ``active`` el
    ``channel_state`` refina el copy (miembro vs link enviado vs preparando),
    de modo que el usuario vea el avance real de su acceso al canal.
    """
    if status is None:
        return "Sin acceso"
    if status == "active":
        return _ACTIVE_CHANNEL_LABELS.get(channel_state, _ACTIVE_DEFAULT_LABEL)
    return _STATUS_LABELS.get(status, "Estado desconocido")


def trial_days_left(
    trial_ends_at: datetime | None,
    now: datetime | None,
) -> int | None:
    """Días enteros que restan del trial (0 = vence hoy). None si no aplica.

    Redondea hacia arriba mientras quede tiempo positivo, así un trial que
    vence en unas horas se muestra como "1 día" y nunca como "0".
    """
    if trial_ends_at is None or now is None:
        return None
    seconds = (trial_ends_at - now).total_seconds()
    if seconds <= 0:
        return 0
    return max(1, ceil(seconds / 86400))


def _format_trial_countdown(days: int) -> str:
    if days <= 0:
        return "vence hoy"
    if days == 1:
        return "1 día restante"
    return f"{days} días restantes"


def _format_pct(value: Decimal) -> str:
    """Fracción a porcentaje entero (``0.352`` → ``35%``)."""
    return f"{(value * 100).quantize(Decimal('1'))}%"


def format_stats_line(stats: TierStats | None) -> str | None:
    """Línea compacta de track record para una fila del menú.

    Devuelve ``None`` cuando el canal todavía no publicó nada: un tier recién
    creado se muestra por su estado, sin inventar métricas. La ventana rodante
    (90d) se rotula explícito para que los números no se lean como all-time;
    debe coincidir con el INTERVAL de `db._TIER_STATS_QUERY`.
    """
    if stats is None or stats.posts == 0:
        return None
    return "📊 " + " · ".join(
        [
            "90d",
            f"{stats.posts} ofertas",
            f"{_format_pct(stats.avg_discount)} promedio",
            f"mejor {_format_pct(stats.best_discount)}",
        ]
    )


def _field(record: Mapping[str, Any] | Any | None, key: str) -> Any:
    if record is None:
        return None
    try:
        return record[key]
    except (KeyError, TypeError):
        return None


def build_menu_model(
    tiers: Sequence[Mapping[str, Any] | Any],
    memberships_by_tier_id: Mapping[int, Mapping[str, Any] | Any],
    identity: Mapping[str, Any] | Any | None,
    *,
    now: datetime | None = None,
    stats_by_tier_id: Mapping[int, TierStats] | None = None,
) -> MenuModel:
    """Arma el menú multi-tier conservando el orden recibido de los tiers.

    ``now`` es opcional: cuando se provee, las membresías en trial muestran la
    cuenta regresiva de ``trial_ends_at`` en su etiqueta de estado.
    ``stats_by_tier_id`` es opcional: cuando se provee, cada fila muestra el
    track record del tier (ofertas publicadas y descuento real, sobre la ventana
    rodante). Sin él, el menú se comporta como antes.
    """
    trial_unused = _field(identity, "trial_used_at") is None
    stats_by_tier = stats_by_tier_id or {}
    rows: list[TierMenuRow] = []

    for tier in tiers:
        tier_id = int(_field(tier, "id"))
        name = str(_field(tier, "name"))
        slug = str(_field(tier, "slug"))
        raw_description = _field(tier, "description")
        description = str(raw_description).strip() if raw_description else None

        membership = memberships_by_tier_id.get(tier_id)
        status = _field(membership, "status")
        channel_state = _field(membership, "channel_state")

        status_label = membership_status_label(status, channel_state)
        if status == "trialing":
            days = trial_days_left(_field(membership, "trial_ends_at"), now)
            if days is not None:
                status_label = f"{status_label} · {_format_trial_countdown(days)}"

        trial_available = trial_unused and status not in {"active", "trialing"}
        payment_available = status != "active"
        buttons: list[MenuButton] = []
        if trial_available:
            buttons.append(
                MenuButton(
                    text=f"🎁 Trial: {name}",
                    callback_data=f"trial:{tier_id}",
                )
            )
        if payment_available:
            buttons.append(
                MenuButton(
                    text=f"💳 Pagar: {name}",
                    callback_data=f"pay:{tier_id}",
                )
            )

        rows.append(
            TierMenuRow(
                tier_id=tier_id,
                name=name,
                slug=slug,
                description=description,
                status_label=status_label,
                trial_available=trial_available,
                payment_available=payment_available,
                buttons=tuple(buttons),
                stats_line=format_stats_line(stats_by_tier.get(tier_id)),
            )
        )

    return MenuModel(
        title="🔥 Canales VIP de OfertasCL",
        copy=(
            "Estos son los canales disponibles y tu estado en cada uno. "
            "Probá gratis con el trial o activá tu acceso con el pago."
        ),
        rows=tuple(rows),
    )
