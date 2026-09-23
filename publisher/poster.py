"""Publica al canal y registra en `deal_posts`. La parte irreversible de F3.

Un mensaje enviado a un canal no se puede "desenviar" de la cabeza de nadie, así
que el orden de las operaciones acá es la única defensa real contra publicar dos
veces lo mismo:

    1. RESERVAR  — INSERT en `deal_posts` con `telegram_message_id` NULL.
                   Si el UNIQUE(candidate_id, tier_id) lo rechaza, otro ciclo o
                   proceso ya lo tomó: se saltea sin enviar nada.
    2. ENVIAR    — recién ahora se habla con Telegram.
    3. CONFIRMAR — UPDATE con el `message_id` que devolvió.

El orden inverso (enviar y después registrar) es el que produce el error que no
se puede deshacer: si el proceso muere entre el envío y el INSERT, el ciclo
siguiente lo publica de nuevo. Con este orden, morir entre el paso 2 y el 3 deja
una fila con `message_id` NULL — el candidato no se re-publica (correcto) y la
fila queda visible para auditar. Un envío fallido sí borra la reserva, para que
el próximo ciclo reintente.

El costo de esta elección es que un crash en el peor momento puede *perder* una
oferta. Es la dirección correcta para equivocarse: nadie nota la oferta que no
se publicó, todos notan la repetida.
"""
from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timezone

import asyncpg

from curation import ranker
from curation.ranker import Candidate
from publisher.formatter import format_deal
from subscriptions.telegram_client import TelegramClient

logger = logging.getLogger("publisher.poster")


@dataclass(frozen=True)
class Tier:
    """Un canal de destino."""

    id: int
    slug: str
    channel_id: int


#: Resultado de un intento de publicación. Se distingue el duplicado del fallo
#: porque significan cosas opuestas: el duplicado es la defensa funcionando, el
#: fallo es algo roto que hay que mirar.
PUBLISHED = "published"
DUPLICATE = "duplicate"
FAILED = "failed"


@dataclass(frozen=True)
class PublishStats:
    tiers: int = 0
    considered: int = 0
    published: int = 0
    failed: int = 0
    skipped_duplicate: int = 0

    def __str__(self) -> str:
        return (
            f"{self.tiers} canal(es), {self.considered} elegidos, "
            f"{self.published} publicados, {self.failed} fallidos, "
            f"{self.skipped_duplicate} duplicados salteados"
        )


async def load_active_tiers(conn: asyncpg.Connection) -> list[Tier]:
    """Canales que pueden recibir ofertas.

    `is_active` es la guarda que importa: el tier 'ferre' quedó inactivo en la
    migración 12 pero conserva sus filas en `telegram_tier_categories`, así que
    sin este filtro las dos categorías de ferretería se publicarían dos veces.
    Un tier sin `telegram_channel_id` tampoco entra: no hay dónde postear.
    """
    rows = await conn.fetch(
        """
        SELECT id, slug, telegram_channel_id
          FROM telegram_tiers
         WHERE is_active
           AND telegram_channel_id IS NOT NULL
         ORDER BY id
        """
    )
    return [Tier(r["id"], r["slug"], int(r["telegram_channel_id"])) for r in rows]


async def _reserve(
    conn: asyncpg.Connection,
    *,
    candidate_id: int,
    tier_id: int,
    posted_at: datetime,
) -> int | None:
    """Toma el turno para publicar. `None` si ya estaba tomado."""
    row = await conn.fetchrow(
        """
        INSERT INTO deal_posts (candidate_id, tier_id, posted_at)
             VALUES ($1, $2, $3)
        ON CONFLICT (candidate_id, tier_id) DO NOTHING
          RETURNING id
        """,
        candidate_id,
        tier_id,
        posted_at,
    )
    return row["id"] if row else None


async def publish_one(
    pool: asyncpg.Pool,
    client: TelegramClient,
    *,
    tier: Tier,
    candidate: Candidate,
    now: datetime | None = None,
) -> tuple[str, int | None]:
    """Reserva, publica y confirma.

    Devuelve `(PUBLISHED, message_id)`, `(DUPLICATE, None)` o `(FAILED, None)`.
    """
    now = now or datetime.now(timezone.utc)

    async with pool.acquire() as conn:
        post_id = await _reserve(
            conn, candidate_id=candidate.candidate_id, tier_id=tier.id, posted_at=now
        )
    if post_id is None:
        logger.info(
            "candidato %s ya publicado en %s — se saltea",
            candidate.candidate_id,
            tier.slug,
        )
        return DUPLICATE, None

    try:
        message_id = await client.send_message(
            tier.channel_id,
            format_deal(candidate),
            "HTML",
            # La card del link es la foto del producto. Ver `publisher/formatter.py`.
            disable_web_page_preview=False,
        )
    except Exception:
        # `TelegramClient` no lanza, pero `format_deal` sí podría ante un dato
        # inesperado. Sin este rescate la reserva quedaría huérfana y el
        # candidato no se reintentaría nunca: se perdería en silencio, que es
        # el modo de falla más caro de diagnosticar.
        logger.exception(
            "error armando o enviando el candidato %s; se libera la reserva",
            candidate.candidate_id,
        )
        message_id = None

    async with pool.acquire() as conn:
        if message_id is None:
            # El envío no salió: se libera el turno para reintentar. `TelegramClient`
            # nunca lanza, devuelve None ante cualquier fallo — token, red o 429.
            await conn.execute("DELETE FROM deal_posts WHERE id = $1", post_id)
            logger.warning(
                "no se pudo publicar el candidato %s en %s; se reintenta",
                candidate.candidate_id,
                tier.slug,
            )
            return FAILED, None

        await conn.execute(
            "UPDATE deal_posts SET telegram_message_id = $2 WHERE id = $1",
            post_id,
            message_id,
        )

    logger.info(
        "publicado candidato %s en %s (message_id=%s): %s",
        candidate.candidate_id,
        tier.slug,
        message_id,
        candidate.name[:60],
    )
    return PUBLISHED, message_id


async def run_once(
    pool: asyncpg.Pool,
    client: TelegramClient,
    *,
    now: datetime | None = None,
    limit_per_tier: int | None = 1,
) -> PublishStats:
    """Una vuelta del publisher sobre todos los canales activos.

    `limit_per_tier=1` es el default a propósito: el daemon despierta seguido y
    publica de a una, y el espaciado mínimo del ranker hace el resto. Publicar la
    cuota entera de una vuelta convertiría el canal en una ráfaga cada 12 h.
    """
    now = now or datetime.now(timezone.utc)

    async with pool.acquire() as conn:
        tiers = await load_active_tiers(conn)

    considered = published = failed = duplicates = 0
    for tier in tiers:
        async with pool.acquire() as conn:
            batch: Sequence[Candidate] = await ranker.next_batch(
                conn, tier_id=tier.id, now=now, limit=limit_per_tier
            )
        considered += len(batch)
        for candidate in batch:
            outcome, _ = await publish_one(
                pool, client, tier=tier, candidate=candidate, now=now
            )
            if outcome == PUBLISHED:
                published += 1
            elif outcome == DUPLICATE:
                duplicates += 1
            else:
                failed += 1

    stats = PublishStats(len(tiers), considered, published, failed, duplicates)
    if considered or published:
        logger.info("publisher: %s", stats)
    return stats
