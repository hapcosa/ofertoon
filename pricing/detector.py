"""El detector: decide si el precio de hoy es una oferta real.

La señal es una sola línea —

    discount_real = 1 − price_today / p50_60d

— y todo lo demás son guardas. El valor del sistema está ahí: cualquiera compara
contra el "precio normal" que declara la tienda; esto compara contra lo que ese
SKU costó de verdad las últimas 8 semanas.

TODO candidato se persiste, aceptado o rechazado, con su motivo. Ese dataset es
lo que permite mover un umbral con evidencia en vez de a ojo, y es el insumo de
`pricing/backtest.py`.

La cuota diaria por canal NO está acá aunque el plan la liste entre las guardas:
es una decisión de curación (cuántos de los aceptados se publican hoy), no de
detección (si esto es o no una oferta real). Vive en `curation/ranker.py`, F3.
Que un candidato no entre en la cuota de hoy no lo vuelve una oferta falsa.
"""
from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

import asyncpg

from pricing.baselines import Baseline

logger = logging.getLogger("pricing.detector")

#: No republicar el mismo listing dentro de esta ventana…
COOLDOWN_DAYS = 21
#: …salvo que el precio haya bajado al menos esto respecto del post anterior.
COOLDOWN_OVERRIDE_RATIO = Decimal("0.95")

#: Motivos de rechazo. Son los valores que van a `deal_candidates.reject_reason`
#: (VARCHAR(32)); cambiarlos rompe la comparabilidad del histórico.
REJECT_STOCK = "out_of_stock"
REJECT_HISTORY = "history"
REJECT_RAMP = "ramp"
REJECT_THRESHOLD = "threshold"
REJECT_ABOVE_FLOOR = "above_floor"
REJECT_COOLDOWN = "cooldown"


@dataclass(frozen=True)
class Decision:
    """Veredicto sobre una observación."""

    verdict: str  # 'accepted' | 'rejected'
    discount_real: Decimal
    score: Decimal | None = None
    reject_reason: str | None = None

    @property
    def accepted(self) -> bool:
        return self.verdict == "accepted"


@dataclass(frozen=True)
class PriorPost:
    """Última publicación del listing, para el cooldown."""

    posted_at: datetime
    price: Decimal


def compute_score(discount_real: Decimal, price: Decimal, baseline: Baseline) -> Decimal:
    """Cuánto vale la pena esta oferta frente a otras del mismo día.

    Dos factores, ambos ya calculados: el descuento contra el precio de verdad,
    y cuánto se mete por debajo del piso habitual (`p10`). Lo segundo desempata
    entre dos ofertas del mismo % — la que rompe el piso histórico es la noticia.

    No entra el precio absoluto: un 40% en un notebook y un 40% en un taladro
    valen lo mismo para el suscriptor de su canal, y ponderar por ticket
    inundaría los canales de electrónica cara.
    """
    below_floor = Decimal(0)
    if baseline.p10 > 0:
        below_floor = max(Decimal(0), (baseline.p10 - price) / baseline.p10)
    return (discount_real * 100 + below_floor * 50).quantize(Decimal("0.001"))


def evaluate(
    *,
    price: Decimal,
    in_stock: bool,
    baseline: Baseline,
    threshold: Decimal,
    prior_post: PriorPost | None = None,
    now: datetime | None = None,
) -> Decision:
    """Aplica las guardas en orden y devuelve el veredicto.

    El orden importa para el dataset, no para el resultado: cuando varias
    guardas fallan se registra la primera, así que van de la más fundamental
    (no hay serie confiable) a la más de política (ya lo publicamos hace poco).
    """
    now = now or datetime.now(timezone.utc)
    discount_real = Decimal(0)
    if baseline.p50 > 0:
        discount_real = ((baseline.p50 - price) / baseline.p50).quantize(Decimal("0.0001"))

    def reject(reason: str) -> Decision:
        return Decision("rejected", discount_real, None, reason)

    # 1. Stock. Publicar lo que no se puede comprar quema la credibilidad del
    #    canal más rápido que cualquier falso positivo de precio.
    if not in_stock:
        return reject(REJECT_STOCK)

    # 2. Historia mínima: sin serie no hay "precio de verdad" contra qué medir.
    if not baseline.has_min_history:
        return reject(REJECT_HISTORY)

    # 3. Anti-inflado: el precio subió y se sostuvo antes de este "descuento".
    if baseline.ramp_flag:
        return reject(REJECT_RAMP)

    # 4. Umbral por categoría: debajo de esto es fluctuación normal, no oferta.
    if discount_real < threshold:
        return reject(REJECT_THRESHOLD)

    # 5. Cercanía al piso: si está por encima del p10, este precio ya se vio
    #    varias veces en dos meses. No es noticia.
    if price > baseline.p10:
        return reject(REJECT_ABOVE_FLOOR)

    # 6. Cooldown: no repetir el mismo producto salvo que haya bajado de verdad.
    if prior_post is not None and now - prior_post.posted_at < timedelta(days=COOLDOWN_DAYS):
        if price > prior_post.price * COOLDOWN_OVERRIDE_RATIO:
            return reject(REJECT_COOLDOWN)

    return Decision("accepted", discount_real, compute_score(discount_real, price, baseline))


# -----------------------------------------------------------------------------
# Corrida contra la DB
# -----------------------------------------------------------------------------

#: θ de fallback cuando el listing no tiene categoría (no debería pasar; el
#: upsert le asigna una en la primera pasada que lo ve).
DEFAULT_THRESHOLD = Decimal("0.20")

#: Vencimiento de la observación. Un listing que dejó de aparecer en el catálogo
#: conserva para siempre su último `price_point`, y sin este corte el detector lo
#: re-evaluaría en cada corrida como si fuera el precio de hoy — publicando una
#: oferta de un producto que ya nadie vende. Dos ciclos de scraping (12 h) más
#: margen: una pasada que falla no descarta el catálogo entero, dos sí.
PRICE_MAX_AGE_HOURS = 26


async def _load_candidates(conn: asyncpg.Connection) -> list[dict[str, Any]]:
    """Observaciones frescas todavía sin evaluar, de listings con baseline.

    El detector corre después del job de baselines, sobre la foto más reciente:
    la observación de hoy contra la referencia de los 60 días previos.

    Dos filtros que hacen al job re-ejecutable. El de edad descarta la foto
    vieja de un listing que ya no se raspa (ver `PRICE_MAX_AGE_HOURS`). El
    `NOT EXISTS` descarta lo ya decidido: cada observación se evalúa una sola
    vez, así correr el pipeline dos veces seguidas no duplica candidatos ni
    infla las stats. Los rechazos por `history` sí se re-evalúan en cada
    corrida, porque no dejan fila — y son justamente los que hay que seguir
    contando para saber cuánto falta para tener catálogo publicable.
    """
    rows = await conn.fetch(
        """
        SELECT l.id AS listing_id,
               COALESCE(c.discount_threshold, $1) AS threshold,
               b.p50_60d, b.p10_60d, b.min_60d, b.n_points, b.n_days, b.ramp_flag,
               pp.price_effective, pp.in_stock, pp.observed_at
          FROM listings          AS l
          JOIN listing_baselines AS b ON b.listing_id = l.id
          LEFT JOIN categories   AS c ON c.id = l.category_id
          JOIN LATERAL (
               SELECT price_effective, in_stock, observed_at
                 FROM price_points
                WHERE listing_id = l.id
                ORDER BY observed_at DESC
                LIMIT 1
          ) AS pp ON TRUE
         WHERE l.is_active
           AND pp.observed_at >= NOW() - ($2 || ' hours')::INTERVAL
           AND NOT EXISTS (
               SELECT 1 FROM deal_candidates AS dc
                WHERE dc.listing_id  = l.id
                  AND dc.detected_at = pp.observed_at
           )
        """,
        DEFAULT_THRESHOLD,
        str(PRICE_MAX_AGE_HOURS),
    )
    return [dict(r) for r in rows]


async def _prior_post(
    conn: asyncpg.Connection, listing_id: int
) -> PriorPost | None:
    """Última publicación real del listing (no el último candidato aceptado).

    Es deliberado: el cooldown protege al suscriptor de ver dos veces lo mismo,
    y lo que el suscriptor vio son los `deal_posts`. Un aceptado que la cuota
    diaria dejó afuera no consume cooldown.
    """
    row = await conn.fetchrow(
        """
        SELECT dp.posted_at, dc.price
          FROM deal_posts     AS dp
          JOIN deal_candidates AS dc ON dc.id = dp.candidate_id
         WHERE dc.listing_id = $1
         ORDER BY dp.posted_at DESC
         LIMIT 1
        """,
        listing_id,
    )
    return PriorPost(row["posted_at"], row["price"]) if row else None


async def _persist(
    conn: asyncpg.Connection,
    *,
    listing_id: int,
    price: Decimal,
    p50: Decimal,
    decision: Decision,
    detected_at: datetime,
) -> None:
    await conn.execute(
        """
        INSERT INTO deal_candidates (listing_id, detected_at, price, p50_60d,
                                     discount_real, score, verdict, reject_reason)
             VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
        ON CONFLICT (listing_id, detected_at) DO NOTHING
        """,
        listing_id,
        detected_at,
        price,
        p50,
        decision.discount_real,
        decision.score,
        decision.verdict,
        decision.reject_reason,
    )


#: Rechazos que NO se persisten. `history` es el estado normal de un listing
#: joven, no una decisión informativa: durante el cold-start son ~10.800 filas
#: por corrida (650k/mes) que no le dicen nada a la calibración. Se cuentan en
#: las stats, que es donde sirven — para ver cuánto falta para tener catálogo
#: publicable. Todo rechazo que SÍ discrimina (rampa, umbral, piso, cooldown) se
#: guarda entero: ese es el dataset con el que se mueven los umbrales.
UNPERSISTED_REJECTS = frozenset({REJECT_HISTORY})


@dataclass(frozen=True)
class DetectorStats:
    evaluated: int = 0
    accepted: int = 0
    rejected_by: dict[str, int] | None = None

    def __str__(self) -> str:
        reasons = ", ".join(
            f"{k}={v}" for k, v in sorted((self.rejected_by or {}).items())
        )
        return f"{self.evaluated} evaluados, {self.accepted} aceptados ({reasons})"


async def run(pool: asyncpg.Pool, *, persist_rejects: bool = True) -> DetectorStats:
    """Evalúa las observaciones frescas sin decidir y persiste los candidatos.

    Cada observación se evalúa **a su propia fecha** (`observed_at`), no a la
    hora en que corre el job: es la misma convención que usa
    `pricing/backtest.py` al hacer replay, y es lo que hace que el resultado no
    dependa de cuándo se disparó el pipeline. `detected_at` guarda esa fecha, y
    con el UNIQUE de la migración 14 correr el job dos veces es un no-op.

    `persist_rejects=False` existe solo para corridas exploratorias: en
    producción los rechazos SON el dato que permite calibrar.
    """
    rejected_by: dict[str, int] = {}
    evaluated = accepted = 0

    async with pool.acquire() as conn:
        rows = await _load_candidates(conn)
        for row in rows:
            observed_at = row["observed_at"]
            baseline = Baseline(
                p50=row["p50_60d"],
                p10=row["p10_60d"],
                minimum=row["min_60d"],
                n_points=row["n_points"],
                n_days=row["n_days"],
                ramp_flag=row["ramp_flag"],
            )
            decision = evaluate(
                price=row["price_effective"],
                in_stock=row["in_stock"],
                baseline=baseline,
                threshold=Decimal(str(row["threshold"])),
                prior_post=await _prior_post(conn, row["listing_id"]),
                now=observed_at,
            )
            evaluated += 1
            if decision.accepted:
                accepted += 1
            else:
                rejected_by[decision.reject_reason] = (
                    rejected_by.get(decision.reject_reason, 0) + 1
                )
                if not persist_rejects or decision.reject_reason in UNPERSISTED_REJECTS:
                    continue
            await _persist(
                conn,
                listing_id=row["listing_id"],
                price=row["price_effective"],
                p50=row["p50_60d"],
                decision=decision,
                detected_at=observed_at,
            )

    stats = DetectorStats(evaluated, accepted, rejected_by)
    logger.info("detector: %s", stats)
    return stats


async def accepted_since(
    conn: asyncpg.Connection, since: datetime
) -> Sequence[dict[str, Any]]:
    """Candidatos aceptados aún sin publicar. Lo que consume el ranker en F3."""
    rows = await conn.fetch(
        """
        SELECT dc.*, l.store_id, l.category_id, l.url, l.name_raw, l.image_url
          FROM deal_candidates AS dc
          JOIN listings        AS l ON l.id = dc.listing_id
         WHERE dc.verdict = 'accepted'
           AND dc.detected_at >= $1
           AND NOT EXISTS (SELECT 1 FROM deal_posts WHERE candidate_id = dc.id)
         ORDER BY dc.score DESC NULLS LAST
        """,
        since,
    )
    return [dict(r) for r in rows]
