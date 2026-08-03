"""Reporte puro de conversión por ref/tier para el comando admin /stats.

El reporte se **deriva** de las tablas existentes (``telegram_subscribers`` y
``telegram_memberships``); no introduce write-path nuevo en los handlers calientes
ni requiere migración. Las funciones de armado y formato son puras: reciben filas
ya agregadas por SQL y devuelven dataclasses o texto, sin tocar la red ni asyncpg.
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from html import escape
from typing import Any


@dataclass(frozen=True)
class TierConversion:
    """Embudo de un tier dentro de un ref."""

    tier_id: int
    tier_slug: str
    trials: int
    paid: int
    active: int


@dataclass(frozen=True)
class RefConversion:
    """Embudo agregado de un ref, con el desglose por tier."""

    ref: str
    arrivals: int
    trials: int
    paid: int
    active: int
    tiers: tuple[TierConversion, ...] = ()


@dataclass(frozen=True)
class ConversionTotals:
    """Totales globales del reporte."""

    arrivals: int
    trials: int
    paid: int
    active: int


@dataclass(frozen=True)
class ConversionReport:
    """Reporte completo: refs ordenados por llegadas y totales globales."""

    refs: tuple[RefConversion, ...]
    totals: ConversionTotals


def _field(record: Mapping[str, Any] | Any, key: str) -> Any:
    try:
        return record[key]
    except (KeyError, TypeError):
        return None


def _as_int(value: Any) -> int:
    if value is None:
        return 0
    return int(value)


def _as_str(value: Any) -> str:
    if value is None:
        return "(sin ref)"
    return str(value)


@dataclass
class _RefAccumulator:
    ref: str
    arrivals: int = 0
    tiers: list[TierConversion] = field(default_factory=list)

    @property
    def trials(self) -> int:
        return sum(tier.trials for tier in self.tiers)

    @property
    def paid(self) -> int:
        return sum(tier.paid for tier in self.tiers)

    @property
    def active(self) -> int:
        return sum(tier.active for tier in self.tiers)


def build_conversion_report(
    arrival_rows: Iterable[Mapping[str, Any] | Any],
    funnel_rows: Iterable[Mapping[str, Any] | Any],
) -> ConversionReport:
    """Combina llegadas por ref con el embudo por (ref, tier).

    ``arrival_rows`` aporta el total de personas que llegaron por cada ref
    (tabla de identidad). ``funnel_rows`` aporta trials/pagos/activos por
    (ref, tier). Un ref presente solo en el embudo igual aparece (con las
    llegadas que traiga el otro set, o cero); así ningún tier queda invisible.
    """
    accumulators: dict[str, _RefAccumulator] = {}

    def _ensure(ref: str) -> _RefAccumulator:
        acc = accumulators.get(ref)
        if acc is None:
            acc = _RefAccumulator(ref=ref)
            accumulators[ref] = acc
        return acc

    for row in arrival_rows:
        ref = _as_str(_field(row, "ref"))
        _ensure(ref).arrivals += _as_int(_field(row, "arrivals"))

    for row in funnel_rows:
        ref = _as_str(_field(row, "ref"))
        acc = _ensure(ref)
        acc.tiers.append(
            TierConversion(
                tier_id=_as_int(_field(row, "tier_id")),
                tier_slug=_as_str(_field(row, "tier_slug")),
                trials=_as_int(_field(row, "trials")),
                paid=_as_int(_field(row, "paid")),
                active=_as_int(_field(row, "active")),
            )
        )

    refs: list[RefConversion] = []
    for acc in accumulators.values():
        tiers = tuple(sorted(acc.tiers, key=lambda t: t.tier_id))
        refs.append(
            RefConversion(
                ref=acc.ref,
                arrivals=acc.arrivals,
                trials=acc.trials,
                paid=acc.paid,
                active=acc.active,
                tiers=tiers,
            )
        )

    # Orden estable: más llegadas primero, desempate alfabético por ref.
    refs.sort(key=lambda r: (-r.arrivals, r.ref))

    totals = ConversionTotals(
        arrivals=sum(r.arrivals for r in refs),
        trials=sum(r.trials for r in refs),
        paid=sum(r.paid for r in refs),
        active=sum(r.active for r in refs),
    )
    return ConversionReport(refs=tuple(refs), totals=totals)


def format_conversion_report(report: ConversionReport) -> str:
    """Formatea el reporte como HTML de Telegram, listo para send_message."""
    totals = report.totals
    lines = [
        "<b>📊 Conversión por campaña</b>",
        (
            f"Total · llegadas {totals.arrivals} · "
            f"trials {totals.trials} · pagos {totals.paid} · "
            f"activos {totals.active}"
        ),
    ]
    if not report.refs:
        lines.append("Todavía no hay datos de llegadas.")
        return "\n".join(lines)

    for ref in report.refs:
        lines.append("")
        lines.append(
            f"<b>{escape(ref.ref)}</b> · llegadas {ref.arrivals} · "
            f"trials {ref.trials} · pagos {ref.paid} · activos {ref.active}"
        )
        for tier in ref.tiers:
            lines.append(
                f"  · {escape(tier.tier_slug)}: trials {tier.trials} · "
                f"pagos {tier.paid} · activos {tier.active}"
            )
    return "\n".join(lines)


def parse_admin_ids(raw: str | None) -> frozenset[int]:
    """Interpreta ``ONBOARDING_ADMIN_IDS`` (ids separados por coma/espacio).

    Los ids no numéricos se descartan en silencio: el env es de operación y un
    valor sucio no debe tumbar el bot. Sin ids válidos el comando queda cerrado.
    """
    if not raw:
        return frozenset()
    ids: set[int] = set()
    for chunk in raw.replace(",", " ").split():
        try:
            ids.add(int(chunk))
        except ValueError:
            continue
    return frozenset(ids)


def is_admin(user_id: int | None, admin_ids: frozenset[int]) -> bool:
    """True solo si el usuario está en la allowlist de admins."""
    if user_id is None:
        return False
    return user_id in admin_ids
