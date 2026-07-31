"""Orquestador de ingesta: recorre tienda × categoría y escribe la serie de precios.

Los targets NO están hardcodeados: salen de `stores` + `store_categories`, así que
activar una tienda o agregarle una categoría es un `UPDATE`/`INSERT`, no un deploy.
El adaptador se resuelve desde la columna `stores.adapter` (`modulo:Clase`).

Cada par (tienda, categoría) es una unidad de trabajo independiente con su fila en
`scrape_runs`. Si una tienda cambia el HTML y su adaptador revienta, se degrada esa
tienda y las demás siguen — nunca se cae la pasada entera.

Uso:
    python -m scrapers.runner                      # loop cada SCRAPE_INTERVAL_HOURS
    python -m scrapers.runner --once               # una pasada y sale
    python -m scrapers.runner --once --dry-run     # imprime, no escribe
    python -m scrapers.runner --once --store sodimac --category ferre-jardin
"""
from __future__ import annotations

import argparse
import asyncio
import importlib
import logging
import os
import signal
import sys
from collections.abc import Sequence
from typing import Any

import db
from scrapers.base import CategoryRef, RawProduct, StoreAdapter
from scrapers.http import HttpClient

logger = logging.getLogger("runner")

#: Cada cuántos productos se hace flush a DB. Acotado para que una caída a mitad de
#: una categoría larga no tire a la basura lo ya scrapeado.
BATCH_SIZE = 100

#: Si una categoría devuelve menos que esto, el adaptador probablemente se rompió.
#: Es el canario: no aborta nada, pero deja la corrida marcada para que se mire.
CANARY_MIN_ITEMS = 5


def resolve_adapter(path: str) -> type:
    """`"scrapers.stores.falabella_family:FalabellaAdapter"` → la clase."""
    module_name, _, class_name = path.partition(":")
    if not class_name:
        raise ValueError(f"adapter debe ser 'modulo:Clase', llegó {path!r}")
    return getattr(importlib.import_module(module_name), class_name)


def group_targets(rows: Sequence[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Agrupa las filas planas de la query por tienda."""
    stores: dict[str, dict[str, Any]] = {}
    for row in rows:
        store = stores.setdefault(
            row["store_slug"],
            {
                "store_id": row["store_id"],
                "adapter": row["adapter"],
                "rate_limit_rps": float(row["rate_limit_rps"]),
                "targets": [],
            },
        )
        store["targets"].append(
            {
                "category_id": row["category_id"],
                "category": CategoryRef(
                    slug=row["category_slug"],
                    store_key=row["store_key"],
                    label=row["category_name"],
                ),
            }
        )
    return stores


async def _flush(
    pool: Any, buffer: list[RawProduct], *, store_id: int, category_id: int, dry_run: bool
) -> int:
    if not buffer:
        return 0
    if dry_run:
        for product in buffer:
            logger.info(
                "  %s/%s  efectivo=$%s  normal_declarado=%s  %s",
                product.store_slug,
                product.store_sku,
                f"{int(product.price_effective):,}".replace(",", "."),
                product.price_normal,
                product.name[:60],
            )
        return len(buffer)
    return await db.persist_batch(
        pool, buffer, store_id=store_id, category_id=category_id
    )


async def scrape_target(
    pool: Any,
    adapter: StoreAdapter,
    target: dict[str, Any],
    *,
    store_id: int,
    dry_run: bool,
) -> None:
    """Una categoría de una tienda: discover → persistir → cerrar el run."""
    category: CategoryRef = target["category"]
    category_id: int = target["category_id"]

    run_id: int | None = None
    if not dry_run:
        async with pool.acquire() as conn:
            run_id = await db.start_run(conn, store_id=store_id, category_id=category_id)

    seen = 0
    written = 0
    buffer: list[RawProduct] = []
    status = "ok"
    error: str | None = None

    try:
        async for product in adapter.discover(category):
            seen += 1
            buffer.append(product)
            if len(buffer) >= BATCH_SIZE:
                written += await _flush(
                    pool, buffer, store_id=store_id, category_id=category_id, dry_run=dry_run
                )
                buffer.clear()
        written += await _flush(
            pool, buffer, store_id=store_id, category_id=category_id, dry_run=dry_run
        )
    except Exception as exc:  # el adaptador de una tienda no tumba la pasada
        status = "failed"
        error = f"{type(exc).__name__}: {exc}"[:500]
        logger.exception("fallo %s/%s", adapter.slug, category.slug)
    else:
        if seen < CANARY_MIN_ITEMS:
            status = "partial"
            error = f"canario: solo {seen} items"
            logger.warning(
                "canario %s/%s devolvió %d items (<%d) — revisar el adaptador",
                adapter.slug,
                category.slug,
                seen,
                CANARY_MIN_ITEMS,
            )

    logger.info(
        "%s/%s → %d vistos, %d observaciones nuevas [%s]",
        adapter.slug,
        category.slug,
        seen,
        written,
        status,
    )

    if run_id is not None:
        async with pool.acquire() as conn:
            await db.finish_run(
                conn, run_id, status=status, items_seen=seen, items_ok=written, error=error
            )


async def run_once(
    pool: Any,
    *,
    only_store: str | None = None,
    only_category: str | None = None,
    dry_run: bool = False,
) -> None:
    async with pool.acquire() as conn:
        if not dry_run:
            stale = await db.sweep_stale_runs(conn)
            if stale:
                logger.warning("cerradas %d corrida(s) huérfana(s) en 'running'", stale)
        rows = await db.load_store_targets(conn)

    stores = group_targets(rows)
    if only_store:
        stores = {k: v for k, v in stores.items() if k == only_store}
        if not stores:
            logger.error("tienda %r no está activa o no existe", only_store)
            return

    async with HttpClient() as http:
        for store_slug, store in stores.items():
            targets = store["targets"]
            if only_category:
                targets = [t for t in targets if t["category"].slug == only_category]
            if not targets:
                continue

            try:
                adapter_cls = resolve_adapter(store["adapter"])
            except (ImportError, AttributeError, ValueError) as exc:
                logger.error("adaptador de %s no cargó: %s", store_slug, exc)
                continue

            adapter = adapter_cls(http, [t["category"] for t in targets])
            for target in targets:
                await scrape_target(
                    pool, adapter, target, store_id=store["store_id"], dry_run=dry_run
                )


async def main() -> int:
    parser = argparse.ArgumentParser(description="Ingesta de precios OfertasCL")
    parser.add_argument("--once", action="store_true", help="una pasada y salir")
    parser.add_argument("--dry-run", action="store_true", help="no escribe a DB")
    parser.add_argument("--store", help="limitar a un slug de tienda")
    parser.add_argument("--category", help="limitar a un slug de categoría")
    args = parser.parse_args()

    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    dsn = os.environ.get("DATABASE_URL", "").strip()
    if not dsn:
        logger.error("DATABASE_URL es obligatoria")
        return 2

    interval = float(os.environ.get("SCRAPE_INTERVAL_HOURS", "12")) * 3600
    stopping = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stopping.set)

    pool = await db.create_pool(dsn)
    try:
        while True:
            await run_once(
                pool,
                only_store=args.store,
                only_category=args.category,
                dry_run=args.dry_run,
            )
            if args.once or stopping.is_set():
                break
            try:
                await asyncio.wait_for(stopping.wait(), timeout=interval)
                break  # llegó la señal durante la espera
            except asyncio.TimeoutError:
                pass
    finally:
        await pool.close()

    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
