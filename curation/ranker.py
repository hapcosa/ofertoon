"""La cuota diaria por canal: cuáles de los aceptados se publican hoy.

Vive acá y no en `pricing/detector.py` por la frontera que ese módulo declara en
su docstring: el detector decide **si esto es una oferta real**, la curación
decide **cuántas de las reales entran hoy**. Que un candidato no entre en la
cuota no lo vuelve una oferta falsa — sigue aceptado en `deal_candidates` y
sigue contando para calibrar θ.

Los números de abajo son producto, no ingeniería. El criterio: un canal que se
lee vs. uno que se silencia. Seis mensajes al día se leen; treinta son un feed y
el suscriptor lo mutea. El piso lo fija el gate de F1, que pide ≥3 ofertas por
día y canal para considerar el sistema lanzable — 6 deja margen sin pasarse.

Todo el ordenamiento es una función pura (`select`) sobre dataclasses; la única
parte con I/O es la query que la alimenta. Es lo que permite testear la cuota sin
base de datos y sin esperar a que el catálogo tenga historia.
"""
from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import asyncpg

logger = logging.getLogger("curation.ranker")

#: El canal es chileno: el día calendario y la ventana horaria son de Santiago,
#: no UTC. Con UTC la cuota diaria se cortaría a las 20:00 o 21:00 hora local
#: según el horario de verano, justo en el mejor momento para publicar.
TZ = ZoneInfo("America/Santiago")

#: Techo diario por canal.
MAX_PER_DAY = 6
#: Que no sean seis de la misma tienda ni seis notebooks.
MAX_PER_STORE_PER_DAY = 2
MAX_PER_CATEGORY_PER_DAY = 2

#: Espaciado mínimo entre posts. El pipeline produce en dos ráfagas de 12 h; sin
#: esto el canal escupiría la cuota entera en cuatro minutos y quedaría mudo el
#: resto del día.
MIN_MINUTES_BETWEEN = 45

#: Ventana de publicación, hora de Santiago. `END` es exclusiva.
WINDOW_START_HOUR = 9
WINDOW_END_HOUR = 22

#: Vencimiento del candidato. Un aceptado que no entró en la cuota de ayer no se
#: publica hoy: su precio tiene más de un ciclo de scraping de antigüedad y no
#: está verificado. Si la oferta sigue viva, la pasada siguiente la vuelve a
#: detectar con precio fresco. Es preferible perder una oferta a publicar un
#: precio que ya no existe — eso es exactamente lo que el canal promete no hacer.
MAX_AGE_HOURS = 13


@dataclass(frozen=True)
class Candidate:
    """Un aceptado listo para evaluar contra la cuota, con lo que el mensaje pide."""

    candidate_id: int
    listing_id: int
    store_id: int
    store_name: str
    category_id: int | None
    category_name: str | None
    name: str
    url: str
    price: Decimal
    p50: Decimal
    discount_real: Decimal
    score: Decimal | None
    detected_at: datetime
    #: p10 de la baseline vigente: el "piso habitual" de los últimos 60 días.
    p10: Decimal | None = None
    #: Mínimo con stock de los 60 días PREVIOS a esta observación — excluyéndola.
    #: No se puede usar `listing_baselines.min_60d` para esto: las baselines se
    #: recomputan antes de correr el detector, así que ese mínimo ya incluye el
    #: precio de la oferta y `price <= min_60d` sería cierto para todo aceptado
    #: que sea mínimo. La afirmación "el más barato en 60 días" quedaría vacía.
    min_prior: Decimal | None = None


@dataclass(frozen=True)
class PostedToday:
    """Lo ya publicado hoy en el canal. Es el estado contra el que corre la cuota."""

    total: int = 0
    by_store: dict[int, int] = field(default_factory=dict)
    by_category: dict[int | None, int] = field(default_factory=dict)
    last_posted_at: datetime | None = None


def local_day_bounds(now: datetime) -> tuple[datetime, datetime]:
    """Comienzo y fin del día calendario de Santiago que contiene a `now`."""
    local = now.astimezone(TZ)
    start = local.replace(hour=0, minute=0, second=0, microsecond=0)
    return start, start + timedelta(days=1)


def within_window(now: datetime) -> bool:
    """¿Es horario de publicar? Nadie compra un taladro a las 4 de la mañana."""
    return WINDOW_START_HOUR <= now.astimezone(TZ).hour < WINDOW_END_HOUR


def is_fresh(candidate: Candidate, now: datetime) -> bool:
    return now - candidate.detected_at <= timedelta(hours=MAX_AGE_HOURS)


def select(
    candidates: Sequence[Candidate],
    *,
    posted: PostedToday,
    now: datetime,
    limit: int | None = None,
) -> list[Candidate]:
    """Los candidatos que pueden publicarse ahora, en orden de publicación.

    Greedy por `score` descendente con los topes aplicados sobre la marcha. No
    hace falta nada más sofisticado: los topes por tienda y por categoría YA
    fuerzan la mezcla, porque en cuanto se llenan dejan pasar al siguiente
    candidato distinto aunque tenga menos score. Un round-robin explícito
    ordenaría distinto los mismos seis mensajes.

    Devuelve `[]` cuando no toca publicar — fuera de ventana, cuota agotada o
    demasiado pronto desde el último post. El daemon llama con `limit=1`.
    """
    if not within_window(now):
        return []

    if posted.last_posted_at is not None:
        if now - posted.last_posted_at < timedelta(minutes=MIN_MINUTES_BETWEEN):
            return []

    remaining = MAX_PER_DAY - posted.total
    if remaining <= 0:
        return []

    by_store = dict(posted.by_store)
    by_category = dict(posted.by_category)

    # `score` puede ser None solo por un bug (el detector siempre lo calcula al
    # aceptar); esos van al fondo en vez de reventar la comparación.
    ordered = sorted(
        (c for c in candidates if is_fresh(c, now)),
        key=lambda c: (c.score is None, -(c.score or Decimal(0)), c.candidate_id),
    )

    chosen: list[Candidate] = []
    for candidate in ordered:
        if len(chosen) >= remaining:
            break
        if limit is not None and len(chosen) >= limit:
            break
        if by_store.get(candidate.store_id, 0) >= MAX_PER_STORE_PER_DAY:
            continue
        if by_category.get(candidate.category_id, 0) >= MAX_PER_CATEGORY_PER_DAY:
            continue
        chosen.append(candidate)
        by_store[candidate.store_id] = by_store.get(candidate.store_id, 0) + 1
        by_category[candidate.category_id] = (
            by_category.get(candidate.category_id, 0) + 1
        )
    return chosen


# -----------------------------------------------------------------------------
# Carga de datos
# -----------------------------------------------------------------------------

#: La query vive acá y no en `detector.accepted_since` a propósito: el dueño de
#: una consulta es quien la consume. El detector no sabe ni tiene por qué saber
#: qué campos necesita el mensaje del canal.
_CANDIDATES_SQL = """
    SELECT dc.id AS candidate_id,
           dc.listing_id,
           dc.price,
           dc.p50_60d      AS p50,
           dc.discount_real,
           dc.score,
           dc.detected_at,
           l.store_id,
           l.category_id,
           l.name_raw      AS name,
           l.url,
           s.name          AS store_name,
           c.name          AS category_name,
           b.p10_60d       AS p10,
           (SELECT MIN(pp.price_effective)
              FROM price_points AS pp
             WHERE pp.listing_id = l.id
               AND pp.in_stock
               AND pp.observed_at >= dc.detected_at - INTERVAL '60 days'
               AND pp.observed_at <  dc.detected_at) AS min_prior
      FROM deal_candidates AS dc
      JOIN listings        AS l ON l.id = dc.listing_id
      JOIN stores          AS s ON s.id = l.store_id
      -- El ruteo canal↔categoría. El INNER JOIN es la guarda: un candidato de
      -- una categoría que no está ruteada a este tier simplemente no existe
      -- para él.
      JOIN telegram_tier_categories AS tc
             ON tc.category_id = l.category_id AND tc.tier_id = $1
      LEFT JOIN categories        AS c ON c.id = l.category_id
      LEFT JOIN listing_baselines AS b ON b.listing_id = l.id
     WHERE dc.verdict = 'accepted'
       AND dc.detected_at >= $2
       AND NOT EXISTS (
           SELECT 1 FROM deal_posts AS dp
            WHERE dp.candidate_id = dc.id AND dp.tier_id = $1
       )
     ORDER BY dc.score DESC NULLS LAST, dc.id
"""


async def load_candidates(
    conn: asyncpg.Connection, *, tier_id: int, now: datetime
) -> list[Candidate]:
    """Aceptados frescos y sin publicar en este canal."""
    rows = await conn.fetch(
        _CANDIDATES_SQL, tier_id, now - timedelta(hours=MAX_AGE_HOURS)
    )
    return [Candidate(**dict(row)) for row in rows]


async def load_posted_today(
    conn: asyncpg.Connection, *, tier_id: int, now: datetime
) -> PostedToday:
    """Cuánto se publicó hoy en este canal, en día calendario de Santiago.

    Cuenta TODA fila de `deal_posts`, incluidas las que quedaron con
    `telegram_message_id` NULL. Esa fila significa "se reservó y el envío pudo
    haber salido": contarla es el lado seguro de la duda — como mucho se publica
    una oferta menos hoy.
    """
    day_start, day_end = local_day_bounds(now)
    rows = await conn.fetch(
        """
        SELECT l.store_id, l.category_id, dp.posted_at
          FROM deal_posts      AS dp
          JOIN deal_candidates AS dc ON dc.id = dp.candidate_id
          JOIN listings        AS l  ON l.id  = dc.listing_id
         WHERE dp.tier_id = $1
           AND dp.posted_at >= $2
           AND dp.posted_at <  $3
        """,
        tier_id,
        day_start,
        day_end,
    )

    by_store: dict[int, int] = {}
    by_category: dict[int | None, int] = {}
    last: datetime | None = None
    for row in rows:
        by_store[row["store_id"]] = by_store.get(row["store_id"], 0) + 1
        by_category[row["category_id"]] = by_category.get(row["category_id"], 0) + 1
        if last is None or row["posted_at"] > last:
            last = row["posted_at"]

    return PostedToday(len(rows), by_store, by_category, last)


async def next_batch(
    conn: asyncpg.Connection, *, tier_id: int, now: datetime, limit: int | None = 1
) -> list[Candidate]:
    """Qué publicar ahora mismo en este canal. `[]` es la respuesta normal."""
    posted = await load_posted_today(conn, tier_id=tier_id, now=now)
    candidates = await load_candidates(conn, tier_id=tier_id, now=now)
    chosen = select(candidates, posted=posted, now=now, limit=limit)
    logger.debug(
        "ranker tier=%s: %d candidatos, %d publicados hoy, %d elegidos",
        tier_id,
        len(candidates),
        posted.total,
        len(chosen),
    )
    return chosen
