"""Baseline por listing: el "precio de verdad" del SKU y su historia reciente.

Contra esto se mide el descuento — nunca contra el `price_normal` que declara la
tienda, que es exactamente el número que inflan.

Todo el cálculo vive en funciones puras sobre la serie (`compute_baseline`), no
en SQL. Es a propósito: `pricing/backtest.py` necesita recomputar la baseline
"como se habría visto el día t" para hacer replay sin look-ahead, y si la lógica
estuviera en un `percentile_cont` del job diario habría dos implementaciones
divergiendo — la que corre en producción y la que se backtestea. El costo es
traer ~120 observaciones por listing una vez al día, que es nada.
"""
from __future__ import annotations

import logging
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

import asyncpg

logger = logging.getLogger("pricing.baselines")

#: Ventana de la baseline.
WINDOW_DAYS = 60

#: Historia mínima para que la baseline sea publicable. Menos que esto y el p50
#: es una opinión, no una referencia: un SKU nuevo cuyo precio de lanzamiento se
#: "descuenta" a los 10 días no tiene con qué contrastarse.
MIN_POINTS = 30
MIN_DAYS = 30

#: Anti-inflado. Un alza de este tamaño sobre el p50 que se sostiene estos días
#: dentro de la ventana previa es la firma del "subo y después descuento".
RAMP_RISE = Decimal("0.15")
RAMP_MIN_DAYS = 5
#: La ventana donde se busca la rampa: d−21 a d−3. El corte en d−3 es lo que
#: evita que la propia bajada de hoy se lea como parte del escalón.
RAMP_FROM_DAYS = 21
RAMP_TO_DAYS = 3


@dataclass(frozen=True)
class Baseline:
    """Resumen de la serie de un listing a una fecha dada."""

    p50: Decimal
    p10: Decimal
    minimum: Decimal
    n_points: int
    n_days: int
    ramp_flag: bool

    @property
    def has_min_history(self) -> bool:
        return self.n_points >= MIN_POINTS and self.n_days >= MIN_DAYS


def percentile(values: Sequence[Decimal], q: float) -> Decimal:
    """Percentil con interpolación lineal. `values` no necesita venir ordenado.

    Se implementa acá en vez de usar `statistics.quantiles` porque este trabaja
    sobre floats y la serie es Decimal: convertir a float y volver introduce
    centavos fantasma en precios que son enteros por definición (CLP).

    >>> percentile([Decimal(1), Decimal(2), Decimal(3)], 0.5)
    Decimal('2')
    >>> percentile([Decimal(10), Decimal(20)], 0.5)
    Decimal('15')
    """
    if not values:
        raise ValueError("percentile de una serie vacía")
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]

    position = Decimal(str(q)) * (len(ordered) - 1)
    low = int(position)
    high = min(low + 1, len(ordered) - 1)
    fraction = position - low
    return ordered[low] + (ordered[high] - ordered[low]) * fraction


def daily_minimums(
    points: Iterable[tuple[datetime, Decimal]]
) -> list[tuple[date, Decimal]]:
    """Colapsa el muestreo 2×/día a un punto diario, quedándose con el mínimo.

    El mínimo y no el promedio: una flash sale de la mañana es un precio que
    alguien pudo pagar ese día, y para la guarda anti-inflado interesa el precio
    más benigno del día — así el escalón solo se marca si el día ENTERO estuvo
    caro.
    """
    per_day: dict[date, Decimal] = {}
    for observed_at, price in points:
        day = observed_at.date()
        current = per_day.get(day)
        if current is None or price < current:
            per_day[day] = price
    return sorted(per_day.items())


def detect_ramp(
    daily: Sequence[tuple[date, Decimal]], p50: Decimal, *, today: date
) -> bool:
    """True si hubo un alza sostenida antes de la bajada de hoy.

    Persistencia = el span entre el primer y el último día caro de una racha.
    Un día sin observación (una pasada que falló) no corta la racha; solo la
    corta un día observado que SÍ estuvo barato. Al revés, un hueco de datos
    borraría la evidencia del inflado, que es justo lo que hay que detectar.
    """
    threshold = p50 * (1 + RAMP_RISE)
    start = today - timedelta(days=RAMP_FROM_DAYS)
    end = today - timedelta(days=RAMP_TO_DAYS)

    run_start: date | None = None
    for day, price in daily:
        if not (start <= day <= end):
            continue
        if price >= threshold:
            if run_start is None:
                run_start = day
            elif (day - run_start).days + 1 >= RAMP_MIN_DAYS:
                return True
        else:
            run_start = None
    return False


def compute_baseline(
    points: Sequence[tuple[datetime, Decimal, bool]], *, now: datetime | None = None
) -> Baseline | None:
    """Baseline a partir de la serie cruda. `None` si no hay nada con stock.

    `points` son `(observed_at, price_effective, in_stock)` en cualquier orden;
    se filtran acá los de la ventana y los sin stock. Filtrar el sin-stock es
    esencial: un producto agotado suele quedar con un precio congelado o
    absurdo, y arrastraría el p50 hacia donde nadie compró nunca.
    """
    now = now or datetime.now(timezone.utc)
    window_start = now - timedelta(days=WINDOW_DAYS)

    in_window = [
        (observed_at, price)
        for observed_at, price, in_stock in points
        if in_stock and window_start <= observed_at <= now
    ]
    if not in_window:
        return None

    prices = [price for _, price in in_window]
    daily = daily_minimums(in_window)
    p50 = percentile(prices, 0.50)

    return Baseline(
        p50=p50,
        p10=percentile(prices, 0.10),
        minimum=min(prices),
        n_points=len(prices),
        n_days=len(daily),
        ramp_flag=detect_ramp(daily, p50, today=now.date()),
    )


# -----------------------------------------------------------------------------
# Job diario
# -----------------------------------------------------------------------------

#: Cuántos listings se traen por vuelta. Acota la memoria: cada listing son
#: ~120 observaciones en la ventana.
CHUNK = 500


async def _listing_ids(conn: asyncpg.Connection) -> list[int]:
    rows = await conn.fetch(
        """
        SELECT DISTINCT l.id
          FROM listings AS l
          JOIN price_points AS pp ON pp.listing_id = l.id
         WHERE l.is_active
           AND pp.observed_at >= NOW() - ($1 || ' days')::INTERVAL
         ORDER BY l.id
        """,
        str(WINDOW_DAYS),
    )
    return [int(r["id"]) for r in rows]


async def _load_points(
    conn: asyncpg.Connection, listing_ids: Sequence[int]
) -> dict[int, list[tuple[datetime, Decimal, bool]]]:
    rows = await conn.fetch(
        """
        SELECT listing_id, observed_at, price_effective, in_stock
          FROM price_points
         WHERE listing_id = ANY($1::int[])
           AND observed_at >= NOW() - ($2 || ' days')::INTERVAL
        """,
        list(listing_ids),
        str(WINDOW_DAYS),
    )
    series: dict[int, list[tuple[datetime, Decimal, bool]]] = {}
    for row in rows:
        series.setdefault(row["listing_id"], []).append(
            (row["observed_at"], row["price_effective"], row["in_stock"])
        )
    return series


async def _store(conn: asyncpg.Connection, listing_id: int, baseline: Baseline) -> None:
    await conn.execute(
        """
        INSERT INTO listing_baselines (listing_id, computed_at, p50_60d, p10_60d,
                                       min_60d, n_points, n_days, ramp_flag)
             VALUES ($1, NOW(), $2, $3, $4, $5, $6, $7)
        ON CONFLICT (listing_id) DO UPDATE
                SET computed_at = NOW(),
                    p50_60d     = EXCLUDED.p50_60d,
                    p10_60d     = EXCLUDED.p10_60d,
                    min_60d     = EXCLUDED.min_60d,
                    n_points    = EXCLUDED.n_points,
                    n_days      = EXCLUDED.n_days,
                    ramp_flag   = EXCLUDED.ramp_flag
        """,
        listing_id,
        baseline.p50,
        baseline.p10,
        baseline.minimum,
        baseline.n_points,
        baseline.n_days,
        baseline.ramp_flag,
    )


@dataclass(frozen=True)
class BaselineStats:
    listings: int = 0
    written: int = 0
    publishable: int = 0
    ramps: int = 0

    def __str__(self) -> str:
        return (
            f"{self.listings} listings, {self.written} baselines escritas, "
            f"{self.publishable} con historia suficiente, {self.ramps} con rampa"
        )


async def recompute_all(pool: asyncpg.Pool) -> BaselineStats:
    """Recomputa la baseline de todos los listings activos. Idempotente."""
    async with pool.acquire() as conn:
        ids = await _listing_ids(conn)

    listings = written = publishable = ramps = 0
    for start in range(0, len(ids), CHUNK):
        chunk = ids[start : start + CHUNK]
        async with pool.acquire() as conn:
            series = await _load_points(conn, chunk)
            async with conn.transaction():
                for listing_id in chunk:
                    listings += 1
                    baseline = compute_baseline(series.get(listing_id, []))
                    if baseline is None:
                        continue
                    await _store(conn, listing_id, baseline)
                    written += 1
                    publishable += int(baseline.has_min_history)
                    ramps += int(baseline.ramp_flag)

    stats = BaselineStats(listings, written, publishable, ramps)
    logger.info("baselines: %s", stats)
    return stats


async def load_baseline(
    conn: asyncpg.Connection, listing_id: int
) -> dict[str, Any] | None:
    row = await conn.fetchrow(
        "SELECT * FROM listing_baselines WHERE listing_id = $1", listing_id
    )
    return dict(row) if row else None
