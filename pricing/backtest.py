"""Replay histórico del detector: la parte que hace esto medible.

Un descuento real y un precio inflado-normalizado se ven idénticos el día que
aparecen. Se distinguen por lo que pasa después:

    oferta real     = pozo temporal   → el precio vuelve a subir hacia el p50
    precio inflado  = escalón nuevo   → el "descuento" se queda y nunca vuelve

**Pero "se queda abajo" tiene dos causas, no una, y hace falta separarlas.** Una
liquidación de temporada baja el precio y NO vuelve a subir: la temporada se
terminó. Eso es una oferta real —el suscriptor compra barato algo que estaba
caro— y con la regla de arriba sola quedaba etiquetada `fake`, castigando al
detector por acertar. Como el backtest es de donde sale θ, esa etiqueta
equivocada empujaba θ hacia arriba hasta dejar afuera justamente las mejores
ofertas de vestuario y calzado.

El discriminante no es el futuro, es el pasado, y ya está calculado:

    precio inflado  → el "descuento" vuelve a un nivel que YA existía en la
                      ventana, así que `price >= min_60d`
    liquidación     → el precio rompe el piso: `price < min_60d`, un valor que
                      no se había visto nunca en 60 días

Y hay una razón más fuerte que lo hace defendible: un candidato **aceptado** ya
pasó la guarda 3 del detector (`ramp_flag` → `reject_reason = 'ramp'`), que es la
que detecta el "subo y después descuento", y la guarda 5 (`price <= p10`). O sea
que entre los aceptados, el inflado ya se filtró antes de llegar acá. Ver
`LABEL_LIQUIDATION`.

El replay recorre la historia día por día emitiendo las señales que el detector
habría emitido **con la información disponible a esa fecha** (la baseline se
recomputa a cada paso con `pricing.baselines.compute_baseline`, que es la misma
función que corre en producción: sin look-ahead y sin una segunda
implementación que pueda divergir), y las etiqueta a posteriori con la ventana
+30d.

La salida es la curva precisión-volumen por umbral. **De ahí sale el θ de cada
categoría** — no de una intuición. Criterio de lanzamiento del plan: precisión
≥80% con ≥3 ofertas/día/canal.

**Hay días que no se pueden replayear como si fueran normales** (ver
`DIAS_DEGRADADOS` y `--exclude-day`). Un día en que el scraper corrió a medias no
es un día de mercado: entra en el divisor de señales/día —que es la mitad del
gate— sin haber tenido la oportunidad de producir señales.

Uso:
    python -m pricing.backtest --from 2026-08-01 --to 2026-09-15 --report
    python -m pricing.backtest --from ... --to ... --category tecno-notebooks
    python -m pricing.backtest --from ... --to ... --exclude-day 2026-09-18
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
from pricing.baselines import WINDOW_DAYS, compute_baseline
from pricing.detector import PriorPost, evaluate

logger = logging.getLogger("pricing.backtest")

#: Ventana de etiquetado. Si el precio vuelve a subir ≥10% dentro de estos días,
#: el pozo era real. Si se queda abajo, era el precio nuevo con otro nombre.
LABEL_WINDOW_DAYS = 30
LABEL_RECOVERY = Decimal("1.10")

LABEL_REAL = "real"
LABEL_FAKE = "fake"
LABEL_UNKNOWN = "unknown"

#: El pozo se quedó abajo **pero rompiendo el piso de 60 días**: un precio que
#: nunca se había visto. Es la liquidación de temporada, y es una oferta real —
#: decisión de producto tomada el 2026-10-01: los precios bajan de verdad, así
#: que van al canal.
#:
#: Se cuenta como acierto en `precision` y se lleva columna propia en el reporte.
#: Lo segundo no es cosmético: un canal cuya precisión viene toda de
#: liquidaciones es un canal de outlet, no de ofertas, y eso hay que poder verlo
#: antes de fijar θ.
#:
#: Por qué el piso y no "no volvió a subir": un inflado-normalizado vuelve a un
#: nivel que YA existía en la ventana (el precio de antes de inflar), así que
#: `price >= min_60d`. Una liquidación va por debajo de todo lo observado. El
#: discriminante mira el pasado, que es dato duro, y no la intención.
LABEL_LIQUIDATION = "liquidation"

#: Días en que la ingesta corrió a medias y por eso NO son días de mercado. No
#: se excluyen solos —cambiar el divisor del gate en silencio sería peor que el
#: problema—, pero si el rango los toca y no se los excluyó, el comando avisa.
#:
#: - 2026-09-18 y 2026-09-19: cero observaciones. El host perdió la salida a
#:   internet 48 h; 562 corridas `failed`.
#: - 2026-09-29: 19.361 puntos contra ~33.000. Fallos de DNS a ráfagas más un
#:   reboot del host a las 03:58 UTC se llevaron 62 de 129 objetivos. Ojo: su
#:   pasada de la tarde SÍ corrió, así que la emisión de ese día es legítima
#:   —`replay_listing` toma la última observación del día, igual que producción—.
#:   Lo que ese día distorsiona es el PESO en el p50, porque `percentile` corre
#:   sobre los puntos crudos y casi todos los listings tienen 1 punto en vez
#:   de 2. Es la razón por la que está acá y no es tan grave como los otros dos.
DIAS_DEGRADADOS = (
    date(2026, 9, 18),
    date(2026, 9, 19),
    date(2026, 9, 29),
)

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
    price: Decimal,
    future: Sequence[Point],
    *,
    day: date,
    series_end: datetime,
    prior_min: Decimal | None = None,
) -> str:
    """Etiqueta la señal mirando los 30 días siguientes.

    `unknown` cuando la serie todavía no llegó a cubrir la ventana: contar esos
    casos como aciertos o como errores sesgaría la precisión justo en las
    señales más recientes, que son las que más interesan.

    `prior_min` es el `min_60d` de la baseline **antes** de esta bajada (sale de
    `compute_baseline` sobre la historia previa, sin look-ahead). Separa las dos
    causas de "se quedó abajo": por debajo del piso es liquidación —precio nunca
    visto— y por encima es el inflado volviendo a un nivel que ya existía. Sin
    `prior_min` el etiquetado es el binario de antes, que es lo que hace que los
    tests viejos sigan valiendo.
    """
    horizon = datetime.combine(day, time.max, tzinfo=timezone.utc) + timedelta(
        days=LABEL_WINDOW_DAYS
    )
    if series_end < horizon:
        return LABEL_UNKNOWN

    prices = [p for observed_at, p, in_stock in future if in_stock]
    if not prices:
        return LABEL_UNKNOWN
    if max(prices) >= price * LABEL_RECOVERY:
        return LABEL_REAL
    if prior_min is not None and price < prior_min:
        return LABEL_LIQUIDATION
    return LABEL_FAKE


def _day_bounds(day: date) -> tuple[datetime, datetime]:
    start = datetime.combine(day, time.min, tzinfo=timezone.utc)
    return start, start + timedelta(days=1)


def piso_previo(points: Sequence[Point], day_start: datetime) -> Decimal | None:
    """El precio más bajo con stock en los 60 días ANTERIORES a este día.

    Es el piso contra el que se decide si una bajada es liquidación, y tiene que
    cortar en el comienzo del día —no en la observación— por una razón que no es
    obvia: la pasada de la mañana ya trae el precio nuevo. El `min_60d` de la
    baseline con la que el detector acepta incluye ese punto (es `history` hasta
    la observación de la tarde), así que el piso ya contiene la bajada y
    `price < min_60d` nunca se cumple. Con eso, una liquidación de libro quedaba
    etiquetada `fake` igual que antes.

    La pregunta que separa liquidación de inflado es "¿este precio existía
    **antes de hoy**?", y esa se contesta con la serie hasta ayer. Mirar menos
    datos nunca es look-ahead: es la versión conservadora.

    Misma ventana y mismo filtro de stock que `compute_baseline` —un agotado
    suele quedar con un precio congelado o absurdo y falsearía el piso—.
    """
    window_start = day_start - timedelta(days=WINDOW_DAYS)
    previos = [
        price
        for observed_at, price, in_stock in points
        if in_stock and window_start <= observed_at < day_start
    ]
    return min(previos) if previos else None


def replay_listing(
    points: Sequence[Point],
    *,
    listing_id: int,
    category_slug: str,
    threshold: Decimal,
    start: date,
    end: date,
    skip_days: frozenset[date] = frozenset(),
) -> list[Signal]:
    """Corre el detector día a día sobre la serie de un listing.

    El cooldown se simula con las señales que el propio replay fue emitiendo:
    de otro modo el volumen saldría inflado, porque en producción una señal
    aceptada silencia a ese listing por 21 días.

    `skip_days` son días que no emiten señal. **Sus puntos siguen alimentando la
    baseline**, y eso es deliberado: la regla de dominio dice que la baseline se
    recomputa "como se veía el día t" con la MISMA función que corre en
    producción, así que borrarle puntos a la serie sería la segunda
    implementación divergente que esa regla existe para prohibir. Lo que un día
    degradado invalida no es la historia —la historia es la que hubo— sino su
    derecho a contar como un día de mercado en el divisor del gate.
    """
    if not points:
        return []

    ordered = sorted(points, key=lambda p: p[0])
    series_end = ordered[-1][0]
    signals: list[Signal] = []
    prior: PriorPost | None = None

    day = start
    while day <= end:
        if day in skip_days:
            day += timedelta(days=1)
            continue

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
                        price,
                        future,
                        day=day,
                        series_end=series_end,
                        # El piso hasta AYER, no el de la baseline: ver
                        # `piso_previo`. El de la baseline ya incluye la pasada
                        # de la mañana, que trae la bajada.
                        prior_min=piso_previo(ordered, day_start),
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
    liquidation: int = 0

    @property
    def labeled(self) -> int:
        return self.real + self.liquidation + self.fake

    @property
    def hits(self) -> int:
        """Aciertos: el pozo que se recuperó MÁS la liquidación.

        La liquidación cuenta porque es una oferta real —decisión de producto
        del 2026-10-01—: el precio bajó de verdad y el suscriptor compra barato.
        Lo que la distingue del inflado es que rompió el piso de 60 días, no que
        haya vuelto a subir. Ver `LABEL_LIQUIDATION`.
        """
        return self.real + self.liquidation

    @property
    def precision(self) -> float | None:
        """`None` cuando no hay ninguna señal madura: no es 0%, es 'no se sabe'."""
        return self.hits / self.labeled if self.labeled else None

    @property
    def liquidation_share(self) -> float | None:
        """Qué fracción de los aciertos es liquidación.

        Un canal cuya precisión viene toda de acá es un canal de outlet, no de
        ofertas. Hay que poder verlo ANTES de fijar θ, no después.
        """
        return self.liquidation / self.hits if self.hits else None

    @property
    def total(self) -> int:
        return self.real + self.liquidation + self.fake + self.unknown

    @property
    def per_day(self) -> float:
        return self.total / self.days if self.days else 0.0

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
        lambda: {
            LABEL_REAL: 0,
            LABEL_LIQUIDATION: 0,
            LABEL_FAKE: 0,
            LABEL_UNKNOWN: 0,
        }
    )
    for signal in signals:
        buckets[(signal.category_slug, signal.threshold)][signal.label] += 1

    return sorted(
        (
            Metrics(
                category_slug=category,
                threshold=threshold,
                real=counts[LABEL_REAL],
                liquidation=counts[LABEL_LIQUIDATION],
                fake=counts[LABEL_FAKE],
                unknown=counts[LABEL_UNKNOWN],
                days=days,
            )
            for (category, threshold), counts in buckets.items()
        ),
        key=lambda m: (m.category_slug, m.threshold),
    )


def format_report(
    metrics: Sequence[Metrics], *, excluidos: Sequence[date] = ()
) -> str:
    """Tabla legible en terminal. Es el output que decide el gate de F1.

    `excluidos` se imprime al pie porque cambia el divisor de `/día`, y una
    columna del gate que se mueve sin decirlo convierte el reporte en un número
    que no se puede auditar después.
    """
    if not metrics:
        return "sin señales en el rango — ¿hay baselines con historia suficiente?"

    header = (
        f"{'categoría':<24} {'θ':>6} {'señales':>8} {'/día':>6} "
        f"{'reales':>7} {'liquid.':>8} {'falsas':>7} {'s/madurar':>10} "
        f"{'precisión':>10}  gate"
    )
    lines = [header, "-" * len(header)]
    for m in metrics:
        precision = "—" if m.precision is None else f"{m.precision * 100:.1f}%"
        lines.append(
            f"{m.category_slug:<24} {float(m.threshold):>6.2f} "
            f"{m.total:>8} {m.per_day:>6.1f} "
            f"{m.real:>7} {m.liquidation:>8} {m.fake:>7} {m.unknown:>10} "
            f"{precision:>10}  {'✓' if m.meets_gate else ''}"
        )
    apoyadas = [
        m
        for m in metrics
        if m.liquidation_share is not None and m.liquidation_share > 0.5
    ]
    if apoyadas:
        lines.append("")
        lines.append(
            f"⚠️  {len(apoyadas)} fila(s) con MÁS de la mitad de los aciertos en "
            "liquidación: ese θ describe un canal de outlet, no de ofertas."
        )
    if excluidos:
        dias = ", ".join(d.isoformat() for d in sorted(excluidos))
        lines.append("")
        lines.append(
            f"{len(excluidos)} día(s) excluido(s) del divisor de /día: {dias}"
        )
        lines.append("La ingesta corrió a medias esos días: no son días de mercado.")
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


def dias_de_mercado(start: date, end: date, skip_days: frozenset[date]) -> int:
    """Días del rango que de verdad pudieron producir señales.

    Es el divisor de `señales/día`, o sea **la mitad del gate de F1**. Contar un
    día en que la ingesta corrió a medias subestima el volumen sin que se vea:
    el numerador pierde las señales que ese día no se pudieron emitir y el
    denominador igual lo cuenta. Sobre un rango de 30 días con los tres días
    degradados adentro, el error es del 10%.

    Solo se descuentan los días excluidos que caen DENTRO del rango: pasar
    `--exclude-day` de una fecha de afuera no puede inflar el resultado.
    """
    total = (end - start).days + 1
    dentro = sum(1 for d in skip_days if start <= d <= end)
    return max(0, total - dentro)


async def run_backtest(
    pool: Any,
    *,
    start: date,
    end: date,
    thresholds: Sequence[Decimal] = DEFAULT_THRESHOLDS,
    category: str | None = None,
    skip_days: frozenset[date] = frozenset(),
) -> list[Metrics]:
    series, categories = await load_series(pool, start=start, end=end, category=category)
    dias = dias_de_mercado(start, end, skip_days)
    logger.info(
        "backtest sobre %d listings, %s → %s (%d días de mercado, %d excluidos)",
        len(series),
        start,
        end,
        dias,
        (end - start).days + 1 - dias,
    )

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
                    skip_days=skip_days,
                )
            )
    return summarize(signals, days=dias)


async def main() -> int:
    parser = argparse.ArgumentParser(description="Replay histórico del detector")
    parser.add_argument("--from", dest="start", required=True, help="YYYY-MM-DD")
    parser.add_argument("--to", dest="end", required=True, help="YYYY-MM-DD")
    parser.add_argument("--category", help="limitar a un slug de categoría")
    parser.add_argument(
        "--exclude-day",
        dest="exclude_days",
        action="append",
        default=[],
        metavar="YYYY-MM-DD",
        help=(
            "día que no emite señal y no cuenta como día de mercado; repetible. "
            "Los conocidos: " + ", ".join(d.isoformat() for d in DIAS_DEGRADADOS)
        ),
    )
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

    try:
        skip_days = frozenset(date.fromisoformat(d) for d in args.exclude_days)
    except ValueError as exc:
        logger.error("--exclude-day no es una fecha YYYY-MM-DD: %s", exc)
        return 2

    # No se excluyen solos: cambiar el divisor del gate sin que se vea sería
    # peor que el problema. Pero quedarse callado es cómo se calibra θ contra un
    # día que no existió, así que el comando avisa y sigue.
    olvidados = [
        d for d in DIAS_DEGRADADOS if start <= d <= end and d not in skip_days
    ]
    if olvidados:
        logger.warning(
            "el rango incluye %d día(s) en que la ingesta corrió a medias y NO "
            "están excluidos: %s. Entran en el divisor de señales/día sin haber "
            "podido producir señales, así que el volumen sale subestimado. "
            "Agregá --exclude-day por cada uno.",
            len(olvidados),
            ", ".join(d.isoformat() for d in olvidados),
        )

    pool = await db.create_pool(dsn)
    try:
        metrics = await run_backtest(
            pool, start=start, end=end, category=args.category, skip_days=skip_days
        )
    finally:
        await pool.close()

    print(format_report(metrics, excluidos=sorted(skip_days)))
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
