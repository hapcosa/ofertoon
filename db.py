"""Acceso a datos. SQL puro con asyncpg, sin ORM.

El contrato de ingesta es un upsert por listing + un insert de observación. La
observación es inmutable: si una pasada repite el mismo `(listing, observed_at)`
no se pisa el precio, se ignora — una serie histórica no se reescribe.
"""
from __future__ import annotations

import logging
from collections.abc import Sequence
from datetime import date, datetime
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
         -- `store_key` también, y no es cosmético: cuando una tienda cross-lista
         -- el mismo SKU en dos llaves de la misma categoría (Andesgear), el
         -- adaptador lo emite UNA vez y la llave que gana es la primera de este
         -- orden. Sin el tercer criterio, el empate lo resolvía Postgres y la
         -- asignación podía cambiar entre pasadas.
         ORDER BY s.slug, c.slug, sc.store_key
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
    """`items_seen` de las últimas `window` corridas del MISMO target.

    Se listan `ok` y `partial`. Queda afuera `failed` —una corrida que reventó no
    vio nada, su cero no es un volumen— y `running`, que no terminó y cuyo
    `items_seen` todavía es 0. Antes solo entraban las `ok`, y
    eso enclavaba el canario: apenas un target caía en `partial`, sus corridas
    dejaban de alimentar la historia y la mediana quedaba congelada en el nivel
    viejo **para siempre**. Pasó con SP Digital, que perdió un tercio de su stock
    el 28 de agosto y siguió reportando "18 items vs mediana 47" días después,
    con las siete corridas previas en 18. Una alarma que no se apaga no es una
    alarma: entierra los errores de verdad.

    El riesgo que el filtro anterior quería evitar —que el canario se
    autoanestesie— lo cubre la mediana: con `window=7` hacen falta 4 corridas
    degradadas seguidas (2 días) para mover la vara, así que un adaptador roto
    sigue gritando mientras hay margen para arreglarlo.

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
           AND status IN ('ok', 'partial')
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


#: Cuántos días hacia atrás se buscan agujeros en la serie. El aviso tiene que
#: salir cuando el scraper se recupera y después callarse solo, sin estado que
#: mantener ni tabla que marcar como "ya notificado": el corte es la ventana.
#:
#: Eran 3 días, y 3 días es más corto que el tiempo que tarda un operador en
#: mirar. El agujero del 18-19 de septiembre de 2026 se descubrió cinco días
#: después, o sea que esta consulta ya no lo veía: una caída de viernes a la que
#: se llega el lunes caía afuera de la ventana y no se reportaba NUNCA. Con 7
#: días el aviso sobrevive a un fin de semana, que es el ciclo real de atención.
#: El costo es repetir el mismo aviso en 14 pasadas en vez de 6; el mensaje dice
#: cuántos días son y desaparece solo.
GAP_LOOKBACK_DAYS = 7


async def dias_sin_observaciones(
    conn: asyncpg.Connection, *, lookback: int = GAP_LOOKBACK_DAYS
) -> list[date]:
    """Días COMPLETOS sin una sola fila en `price_points`, del más viejo al más nuevo.

    Hoy queda afuera a propósito: hasta que corra la primera pasada del día está
    legítimamente vacío, y avisar de eso sería una falsa alarma cada mañana.

    Un día sin observaciones no es "la pasada salió con pocos items" —eso lo
    cubre el canario—, es la serie interrumpida: le baja `n_days` a cada listing
    vivo y deja al backtest sin candidatos que evaluar ese día.
    """
    rows = await conn.fetch(
        """
        SELECT d::date AS dia
          FROM generate_series(
                   CURRENT_DATE - ($1::int) * INTERVAL '1 day',
                   CURRENT_DATE - INTERVAL '1 day',
                   INTERVAL '1 day'
               ) AS d
         WHERE NOT EXISTS (
               SELECT 1 FROM price_points
                WHERE observed_at >= d::date
                  AND observed_at <  d::date + INTERVAL '1 day'
           )
         ORDER BY dia
        """,
        lookback,
    )
    return [r["dia"] for r in rows]


#: Cuánto puede durar una pasada. Con las tiendas conectadas a septiembre de
#: 2026 tarda 11-14 min; 2 h deja
#: margen para el doble de catálogo y sigue estando lejísimos de las 12 h que
#: separan una pasada de la siguiente, que es la única confusión posible.
PASS_WINDOW = "2 hours"


async def ultima_pasada(conn: asyncpg.Connection) -> datetime | None:
    """Instante en que ARRANCÓ la última pasada, sin importar cómo terminó.

    Es el ancla de la cadencia del loop: la serie tiene que quedar muestreada a
    intervalos parejos porque `compute_baseline` saca el p50 de los puntos
    crudos, así que la cantidad de observaciones de un día ES su peso en la
    mediana. Contar el intervalo desde el arranque del proceso en vez de desde
    la última pasada hace que cada despliegue y cada reinicio corra su propia
    pasada extra.

    Ojo con el `MIN`: `scrape_runs` tiene una fila por (tienda, llave), no una
    por pasada, y esas filas arrancan escalonadas a lo largo de los ~13 min que
    la pasada tarda en recorrer todas las tiendas. Un `MAX(started_at)` acá
    devolvería el arranque de la ÚLTIMA tienda y le sumaría esos 13 min al
    ciclo, que es exactamente la deriva que este ancla existe para eliminar.
    """
    return await conn.fetchval(
        f"""
        SELECT MIN(started_at)
          FROM scrape_runs
         WHERE started_at >= (SELECT MAX(started_at) FROM scrape_runs)
                             - INTERVAL '{PASS_WINDOW}'
        """
    )


#: Cuántas pasadas se traen para evaluar volumen. Son las `evaluar` que se
#: reportan más las que hacen de historia, y quien las reparte es el runner.
#:
#: El scan se acota a 30 días por costo: `scrape_runs` crece ~300 filas/día y la
#: función window tiene que ordenarlas enteras. Con 2 pasadas/día, 30 días son
#: 60 pasadas y el límite que manda es siempre el `LIMIT`, nunca la fecha.
VOLUME_SCAN_DAYS = 30


async def volumen_por_pasada(
    conn: asyncpg.Connection, *, limite: int
) -> list[tuple[datetime, int]]:
    """`(inicio, observaciones escritas)` por pasada, de la más nueva a la más vieja.

    `scrape_runs` no tiene una fila por pasada sino una por (tienda, llave), y
    esas filas arrancan escalonadas a lo largo de los ~13 min que la pasada
    tarda en recorrer las tiendas. La pasada se reconstruye agrupando por el
    hueco: dos corridas separadas por más de `PASS_WINDOW` son de pasadas
    distintas. Es el mismo criterio que usa `ultima_pasada`, por el mismo motivo.

    Se suma `items_ok` —observaciones NUEVAS escritas— y no `items_seen`, porque
    lo que esta guarda vigila es cuánta serie entró. Un target que enumera 900
    productos y no logra persistir ninguno es exactamente el agujero que hay que
    ver, y en `items_seen` no se nota.

    Una corrida que murió a mitad queda en 'running' con `items_ok` en 0 hasta
    que `sweep_stale_runs` la cierre, así que su volumen real no se cuenta. El
    sesgo es hacia subestimar, que del lado seguro de una guarda de "faltó
    volumen" es el lado correcto.
    """
    rows = await conn.fetch(
        f"""
        WITH corridas AS (
            SELECT started_at, items_ok,
                   CASE WHEN started_at - LAG(started_at) OVER (ORDER BY started_at)
                             > INTERVAL '{PASS_WINDOW}'
                        THEN 1 ELSE 0 END AS corte
              FROM scrape_runs
             WHERE started_at >= NOW() - ($1::int) * INTERVAL '1 day'
        ), pasadas AS (
            SELECT SUM(corte) OVER (ORDER BY started_at) AS pasada,
                   started_at, items_ok
              FROM corridas
        )
        SELECT MIN(started_at) AS inicio, SUM(items_ok)::int AS observaciones
          FROM pasadas
         GROUP BY pasada
         ORDER BY inicio DESC
         LIMIT $2
        """,
        VOLUME_SCAN_DAYS,
        limite,
    )
    return [(r["inicio"], int(r["observaciones"])) for r in rows]
