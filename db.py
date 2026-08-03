"""Acceso a datos. SQL puro con asyncpg, sin ORM.

El contrato de ingesta es un upsert por listing + un insert de observación. La
observación es inmutable: si una pasada repite el mismo `(listing, observed_at)`
no se pisa el precio, se ignora — una serie histórica no se reescribe.
"""
from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import Any

import asyncpg

from scrapers.base import RawProduct

logger = logging.getLogger(__name__)


async def create_pool(dsn: str, *, min_size: int = 1, max_size: int = 4) -> asyncpg.Pool:
    return await asyncpg.create_pool(dsn, min_size=min_size, max_size=max_size)


async def load_store_targets(conn: asyncpg.Connection) -> list[dict[str, Any]]:
    """Tiendas activas con sus categorías y llaves."""
    rows = await conn.fetch(
        """
        SELECT s.id   AS store_id,
               s.slug AS store_slug,
               s.adapter,
               s.rate_limit_rps,
               c.id   AS category_id,
               c.slug AS category_slug,
               c.name AS category_name,
               sc.store_key
          FROM stores           AS s
          JOIN store_categories AS sc ON sc.store_id = s.id
          JOIN categories       AS c  ON c.id = sc.category_id
         WHERE s.is_active AND sc.is_active
         ORDER BY s.slug, c.slug
        """
    )
    return [dict(r) for r in rows]


async def upsert_listing(
    conn: asyncpg.Connection,
    product: RawProduct,
    *,
    store_id: int,
    category_id: int | None,
) -> int:
    """Crea o refresca el listing y devuelve su id."""
    return await conn.fetchval(
        """
        INSERT INTO listings (store_id, category_id, store_sku, url, name_raw,
                              brand_raw, image_url, gtin_raw, model_raw,
                              last_seen_at)
             VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, NOW())
        ON CONFLICT (store_id, store_sku) DO UPDATE
                SET url          = EXCLUDED.url,
                    name_raw     = EXCLUDED.name_raw,
                    brand_raw    = EXCLUDED.brand_raw,
                    image_url    = COALESCE(EXCLUDED.image_url, listings.image_url),
                    -- Identidad: COALESCE en ese orden, igual que la imagen. Una
                    -- pasada que llega sin GTIN (la tienda lo omite en el listado
                    -- o le cambia el nombre al campo) NO puede borrar el que ya
                    -- teníamos — el dato es irrecuperable hacia atrás.
                    gtin_raw     = COALESCE(EXCLUDED.gtin_raw, listings.gtin_raw),
                    model_raw    = COALESCE(EXCLUDED.model_raw, listings.model_raw),
                    -- La categoría NO se pisa. Las búsquedas de una tienda se
                    -- solapan (un mismo SKU cae en "celular" y en "smart tv"), y
                    -- si la última pasada mandara, el listing rebotaría de
                    -- categoría entre corridas y con él su umbral de descuento.
                    -- La primera categoría que lo vio manda.
                    category_id  = COALESCE(listings.category_id, EXCLUDED.category_id),
                    is_active    = TRUE,
                    last_seen_at = NOW()
          RETURNING id
        """,
        store_id,
        category_id,
        product.store_sku,
        product.url,
        product.name,
        product.brand,
        product.image_url,
        product.gtin,
        product.model,
    )


async def insert_price_point(
    conn: asyncpg.Connection, listing_id: int, product: RawProduct
) -> bool:
    """Registra la observación. False si ya existía (serie inmutable)."""
    status = await conn.execute(
        """
        INSERT INTO price_points (listing_id, observed_at, price_effective,
                                  price_normal, price_card, in_stock,
                                  claimed_discount)
             VALUES ($1, $2, $3, $4, $5, $6, $7)
        ON CONFLICT (listing_id, observed_at) DO NOTHING
        """,
        listing_id,
        product.scraped_at,
        product.price_effective,
        product.price_normal,
        product.price_card,
        product.in_stock,
        product.claimed_discount,
    )
    return status.endswith("1")


async def persist_batch(
    pool: asyncpg.Pool,
    products: Sequence[RawProduct],
    *,
    store_id: int,
    category_id: int | None,
) -> int:
    """Persiste un lote en una transacción. Devuelve observaciones nuevas."""
    if not products:
        return 0
    written = 0
    async with pool.acquire() as conn, conn.transaction():
        for product in products:
            listing_id = await upsert_listing(
                conn, product, store_id=store_id, category_id=category_id
            )
            if await insert_price_point(conn, listing_id, product):
                written += 1
    return written


async def sweep_stale_runs(conn: asyncpg.Connection) -> int:
    """Cierra corridas que quedaron en 'running' (proceso matado a mitad).

    Sin esto la observabilidad se ensucia: un 'running' viejo es indistinguible
    de uno en curso, y el canario de F0 se vuelve inútil.
    """
    status = await conn.execute(
        """
        UPDATE scrape_runs
           SET status = 'failed', finished_at = NOW(),
               error = COALESCE(error, 'corrida huérfana: el proceso murió a mitad')
         WHERE status = 'running' AND started_at < NOW() - INTERVAL '6 hours'
        """
    )
    return int(status.rsplit(" ", 1)[-1])


async def start_run(
    conn: asyncpg.Connection,
    *,
    store_id: int,
    category_id: int | None,
    store_key: str | None = None,
) -> int:
    return await conn.fetchval(
        """
        INSERT INTO scrape_runs (store_id, category_id, store_key)
             VALUES ($1, $2, $3)
          RETURNING id
        """,
        store_id,
        category_id,
        store_key,
    )


async def recent_items_seen(
    conn: asyncpg.Connection,
    *,
    store_id: int,
    category_id: int | None,
    store_key: str | None,
    window: int = 7,
) -> list[int]:
    """`items_seen` de las últimas `window` corridas sanas del MISMO target.

    Solo `status='ok'`: una corrida rota no puede ser referencia de lo que es
    volumen normal, y si lo fuera el canario se autoanestesiaría (dos pasadas
    degradadas seguidas bajarían la vara para la tercera).

    El target incluye `store_key` porque un mismo (tienda, categoría) puede
    tener varias — con volúmenes que difieren en un orden de magnitud.
    """
    rows = await conn.fetch(
        """
        SELECT items_seen
          FROM scrape_runs
         WHERE store_id = $1
           AND category_id IS NOT DISTINCT FROM $2
           AND store_key   IS NOT DISTINCT FROM $3
           AND status = 'ok'
         ORDER BY started_at DESC
         LIMIT $4
        """,
        store_id,
        category_id,
        store_key,
        window,
    )
    return [int(r["items_seen"]) for r in rows]


async def finish_run(
    conn: asyncpg.Connection,
    run_id: int,
    *,
    status: str,
    items_seen: int,
    items_ok: int,
    error: str | None = None,
) -> None:
    await conn.execute(
        """
        UPDATE scrape_runs
           SET finished_at = NOW(), status = $2, items_seen = $3,
               items_ok = $4, error = $5
         WHERE id = $1
        """,
        run_id,
        status,
        items_seen,
        items_ok,
        error,
    )
