"""Replay histórico del detector: la parte que hace esto medible.

Un descuento real y un precio inflado-normalizado se ven idénticos el día que
aparecen. Se distinguen por lo que pasa después:

    oferta real     = pozo temporal   → el precio vuelve a subir hacia el p50
    precio inflado  = escalón nuevo   → el "descuento" se queda y nunca vuelve

El replay recorre la historia día por día emitiendo las señales que el detector
habría emitido **con la información disponible a esa fecha** (la baseline se
recomputa a cada paso con `pricing.baselines.compute_baseline`, que es la misma
función que corre en producción: sin look-ahead y sin una segunda
implementación que pueda divergir), y las etiqueta a posteriori con la ventana
+30d.

La salida es la curva precisión-volumen por umbral. **De ahí sale el θ de cada
categoría** — no de una intuición. Criterio de lanzamiento del plan: precisión
≥80% con ≥3 ofertas/día/canal.

Uso:
    python -m pricing.backtest --from 2026-08-01 --to 2026-09-15 --report
    python -m pricing.backtest --from ... --to ... --category tecno-notebooks
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from typing import Any

import db
from pricing.baselines import compute_baseline
from pricing.detector import PriorPost, evaluate

logger = logging.getLogger("pricing.backtest")

#: Ventana de etiquetado. Si el precio vuelve a subir ≥10% dentro de estos días,
#: el pozo era real. Si se queda abajo, era el precio nuevo con otro nombre.
LABEL_WINDOW_DAYS = 30
LABEL_RECOVERY = Decimal("1.10")

LABEL_REAL = "real"
LABEL_FAKE = "fake"
LABEL_UNKNOWN = "unknown"

#: Umbrales que se barren por defecto. Cubren de "casi todo pasa" a "solo
#: liquidación de verdad"; el θ de producción sale de mirar esta curva.
DEFAULT_THRESHOLDS = (
    Decimal("0.10"),
    Decimal("0.15"),
    Decimal("0.20"),
    Decimal("0.25"),
    Decimal("0.30"),
    Decimal("0.35"),
    Decimal("0.40"),
)

Point = tuple[datetime, Decimal, bool]


@dataclass(frozen=True)
class Signal:
    """Una señal que el detector habría emitido ese día."""

    day: date
    listing_id: int
    category_slug: str
    threshold: Decimal
    price: Decimal
    discount_real: Decimal
    label: str


def label_outcome(
    price: Decimal, future: Sequence[Point], *, day: date, series_end: datetime
) -> str:
    """Etiqueta la señal mirando los 30 días siguientes.

    `unknown` cuando la serie todavía no llegó a cubrir la ventana: contar esos
    casos como aciertos o como errores sesgaría la precisión justo en las
    señales más recientes, que son las que más interesan.
    """
    horizon = datetime.combine(day, time.max, tzinfo=timezone.utc) + timedelta(
        days=LABEL_WINDOW_DAYS
    )
    if series_end < horizon:
        return LABEL_UNKNOWN

    prices = [p for observed_at, p, in_stock in future if in_stock]
    if not prices:
        return LABEL_UNKNOWN
    return LABEL_REAL if max(prices) >= price * LABEL_RECOVERY else LABEL_FAKE


def _day_bounds(day: date) -> tuple[datetime, datetime]:
    start = datetime.combine(day, time.min, tzinfo=timezone.utc)
    return start, start + timedelta(days=1)


def replay_listing(
    points: Sequence[Point],
    *,
    listing_id: int,
    category_slug: str,
    threshold: Decimal,
    start: date,
    end: date,
) -> list[Signal]:
    """Corre el detector día a día sobre la serie de un listing.

    El cooldown se simula con las señales que el propio replay fue emitiendo:
    de otro modo el volumen saldría inflado, porque en producción una señal
    aceptada silencia a ese listing por 21 días.
    """
    if not points:
        return []

    ordered = sorted(points, key=lambda p: p[0])
    series_end = ordered[-1][0]
    signals: list[Signal] = []
    prior: PriorPost | None = None

    day = start
    while day <= end:
        day_start, day_end = _day_bounds(day)
        # La observación del día: la última, que es la que el detector real ve
        # cuando corre después de la pasada de la tarde.
        today = [p for p in ordered if day_start <= p[0] < day_end]
        if not today:
            day += timedelta(days=1)
            continue
        observed_at, price, in_stock = today[-1]

        # Sin look-ahead: la baseline solo ve lo anterior a esta observación.
        history = [p for p in ordered if p[0] < observed_at]
        baseline = compute_baseline(history, now=observed_at)
        if baseline is None:
            day += timedelta(days=1)
            continue

        decision = evaluate(
            price=price,
            in_stock=in_stock,
            baseline=baseline,
            threshold=threshold,
            prior_post=prior,
            now=observed_at,
        )
        if decision.accepted:
            future = [p for p in ordered if p[0] > observed_at]
            signals.append(
                Signal(
                    day=day,
                    listing_id=listing_id,
                    category_slug=category_slug,
                    threshold=threshold,
                    price=price,
                    discount_real=decision.discount_real,
                    label=label_outcome(
                        price, future, day=day, series_end=series_end
                    ),
                )
            )
            prior = PriorPost(observed_at, price)

        day += timedelta(days=1)
    return signals


@dataclass(frozen=True)
class Metrics:
    """Precisión y volumen de un (categoría, θ)."""

    category_slug: str
    threshold: Decimal
    real: int
    fake: int
    unknown: int
    days: int

    @property
    def labeled(self) -> int:
        return self.real + self.fake

    @property
    def precision(self) -> float | None:
        """`None` cuando no hay ninguna señal madura: no es 0%, es 'no se sabe'."""
        return self.real / self.labeled if self.labeled else None

    @property
    def per_day(self) -> float:
        return (self.real + self.fake + self.unknown) / self.days if self.days else 0.0

    @property
    def meets_gate(self) -> bool:
        """El gate de F1 del plan: ≥80% de precisión con ≥3 señales/día."""
        return (
            self.precision is not None
            and self.precision >= 0.80
            and self.per_day >= 3.0
        )


def summarize(signals: Sequence[Signal], *, days: int) -> list[Metrics]:
    """Agrupa las señales en la curva precisión-volumen."""
    buckets: dict[tuple[str, Decimal], dict[str, int]] = defaultdict(
        lambda: {LABEL_REAL: 0, LABEL_FAKE: 0, LABEL_UNKNOWN: 0}
    )
    for signal in signals:
        buckets[(signal.category_slug, signal.threshold)][signal.label] += 1

    return sorted(
        (
            Metrics(
                category_slug=category,
                threshold=threshold,
                real=counts[LABEL_REAL],
                fake=counts[LABEL_FAKE],
                unknown=counts[LABEL_UNKNOWN],
                days=days,
            )
            for (category, threshold), counts in buckets.items()
        ),
        key=lambda m: (m.category_slug, m.threshold),
    )


def format_report(metrics: Sequence[Metrics]) -> str:
    """Tabla legible en terminal. Es el output que decide el gate de F1."""
    if not metrics:
        return "sin señales en el rango — ¿hay baselines con historia suficiente?"

    header = (
        f"{'categoría':<24} {'θ':>6} {'señales':>8} {'/día':>6} "
        f"{'reales':>7} {'falsas':>7} {'s/madurar':>10} {'precisión':>10}  gate"
    )
    lines = [header, "-" * len(header)]
    for m in metrics:
        precision = "—" if m.precision is None else f"{m.precision * 100:.1f}%"
        lines.append(
            f"{m.category_slug:<24} {float(m.threshold):>6.2f} "
            f"{m.real + m.fake + m.unknown:>8} {m.per_day:>6.1f} "
            f"{m.real:>7} {m.fake:>7} {m.unknown:>10} {precision:>10}"
            f"  {'✓' if m.meets_gate else ''}"
        )
    return "\n".join(lines)


# -----------------------------------------------------------------------------
# Carga de datos
# -----------------------------------------------------------------------------


async def load_series(
    pool: Any, *, start: date, end: date, category: str | None = None
) -> tuple[dict[int, list[Point]], dict[int, str]]:
    """Serie completa de cada listing con historia en el rango.

    Se traen también los 60 días previos al inicio (para que la baseline del
    primer día no arranque vacía) y los 30 posteriores al final (para poder
    etiquetar). Sin esos márgenes el backtest mediría otra cosa.
    """
    window_start = datetime.combine(start, time.min, tzinfo=timezone.utc) - timedelta(
        days=60
    )
    window_end = datetime.combine(end, time.max, tzinfo=timezone.utc) + timedelta(
        days=LABEL_WINDOW_DAYS
    )

    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT pp.listing_id, pp.observed_at, pp.price_effective, pp.in_stock,
                   COALESCE(c.slug, 'sin-categoria') AS category_slug
              FROM price_points AS pp
              JOIN listings     AS l ON l.id = pp.listing_id
              LEFT JOIN categories AS c ON c.id = l.category_id
             WHERE pp.observed_at BETWEEN $1 AND $2
               AND ($3::text IS NULL OR c.slug = $3)
             ORDER BY pp.listing_id, pp.observed_at
            """,
            window_start,
            window_end,
            category,
        )

    series: dict[int, list[Point]] = defaultdict(list)
    categories: dict[int, str] = {}
    for row in rows:
        series[row["listing_id"]].append(
            (row["observed_at"], row["price_effective"], row["in_stock"])
        )
        categories[row["listing_id"]] = row["category_slug"]
    return dict(series), categories


async def run_backtest(
    pool: Any,
    *,
    start: date,
    end: date,
    thresholds: Sequence[Decimal] = DEFAULT_THRESHOLDS,
    category: str | None = None,
) -> list[Metrics]:
    series, categories = await load_series(pool, start=start, end=end, category=category)
    logger.info("backtest sobre %d listings, %s → %s", len(series), start, end)

    signals: list[Signal] = []
    for threshold in thresholds:
        for listing_id, points in series.items():
            signals.extend(
                replay_listing(
                    points,
                    listing_id=listing_id,
                    category_slug=categories[listing_id],
                    threshold=threshold,
                    start=start,
                    end=end,
                )
            )
    return summarize(signals, days=(end - start).days + 1)


async def main() -> int:
    parser = argparse.ArgumentParser(description="Replay histórico del detector")
    parser.add_argument("--from", dest="start", required=True, help="YYYY-MM-DD")
    parser.add_argument("--to", dest="end", required=True, help="YYYY-MM-DD")
    parser.add_argument("--category", help="limitar a un slug de categoría")
    # `--report` viene del plan; la tabla se imprime siempre porque es la única
    # salida útil del comando. Se acepta para que el comando documentado corra.
    parser.add_argument("--report", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()

    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    dsn = os.environ.get("DATABASE_URL", "").strip()
    if not dsn:
        logger.error("DATABASE_URL es obligatoria")
        return 2

    start = date.fromisoformat(args.start)
    end = date.fromisoformat(args.end)
    if end < start:
        logger.error("--to es anterior a --from")
        return 2

    pool = await db.create_pool(dsn)
    try:
        metrics = await run_backtest(pool, start=start, end=end, category=args.category)
    finally:
        await pool.close()

    print(format_report(metrics))
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
