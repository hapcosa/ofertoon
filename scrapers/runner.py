"""Orquestador de ingesta: recorre tienda × categoría y escribe la serie de precios.

Los targets NO están hardcodeados: salen de `stores` + `store_categories`, así que
activar una tienda o agregarle una categoría es un `UPDATE`/`INSERT`, no un deploy.
El adaptador se resuelve desde la columna `stores.adapter` (`modulo:Clase`).

Cada par (tienda, categoría) es una unidad de trabajo independiente con su fila en
`scrape_runs`. Si una tienda cambia el HTML y su adaptador revienta, se degrada esa
tienda y las demás siguen — nunca se cae la pasada entera.

Cerrada la pasada corre la fase de pricing (`pricing/pipeline.py`): baselines y
detector sobre las observaciones recién escritas. Vive acá porque el trigger de
una baseline es "hay dato nuevo", no una hora del reloj.

Uso:
    python -m scrapers.runner                      # loop cada SCRAPE_INTERVAL_HOURS
    python -m scrapers.runner --once               # una pasada y sale
    python -m scrapers.runner --once --dry-run     # imprime, no escribe
    python -m scrapers.runner --once --skip-pricing
    python -m scrapers.runner --once --store sodimac --category ferre-jardin
"""
from __future__ import annotations

import argparse
import asyncio
import importlib
import logging
import os
import signal
import statistics
import sys
from collections.abc import Sequence
from typing import Any

import db
from alerts import RunOutcome, format_summary, send_alert
from scrapers.base import CategoryRef, CountingAdapter, RawProduct, StoreAdapter
from scrapers.http import HttpClient

logger = logging.getLogger("runner")

#: Cada cuántos productos se hace flush a DB. Acotado para que una caída a mitad de
#: una categoría larga no tire a la basura lo ya scrapeado.
BATCH_SIZE = 100

#: Piso absoluto para un target SIN historia con qué compararse. No se aplica
#: cuando la hay: existen categorías que de verdad tienen 3 productos, y marcarlas
#: `partial` para siempre —como venía pasando con `Tarjetas Gráficas AMD` de PC
#: Factory— es ruido que entierra los errores reales.
CANARY_MIN_ITEMS = 5

#: El modo de falla real de un adaptador no es "cero items", es "muchos menos".
#: Una categoría de Falabella devuelve 942: un parser roto a medias que entregue
#: 60 pasa cualquier umbral absoluto y envenena la baseline en silencio. Por eso
#: la vara es relativa a lo que ESE target viene devolviendo.
CANARY_DROP_RATIO = 0.40

#: Cuántas corridas sanas se miran hacia atrás. 7 ≈ 3,5 días a 2 pasadas/día:
#: suficiente para promediar el ruido de paginación, corto para seguir un
#: catálogo que crece o se achica de verdad.
CANARY_WINDOW = 7

#: Mínimo de corridas para que la mediana signifique algo. Con menos, solo rige
#: el piso absoluto — mejor ciego que gritando por ruido.
CANARY_MIN_HISTORY = 3


def canary_verdict(
    seen: int,
    history: Sequence[int],
    *,
    completeness: tuple[int, int] | None = None,
) -> tuple[str, str | None]:
    """`('ok'|'partial', motivo)` para una corrida que no lanzó excepción.

    `history` son los `items_seen` de las últimas corridas del mismo target, más
    reciente primero. `completeness` es `(enumerados, declarados)` para las
    tiendas que declaran cuántos productos tiene la categoría
    (`scrapers.base.CountingAdapter`).

    Cuando la tienda declara un total, ese chequeo **reemplaza** al estadístico:
    es exacto donde el otro es una inferencia, y no se equivoca cuando el
    catálogo cambia de nivel de verdad.
    """
    if completeness is not None:
        enumerated, declared = completeness
        if enumerated < declared:
            return "partial", (
                f"canario: {enumerated} de {declared} que declara la tienda "
                f"(paginación incompleta)"
            )
        return "ok", None

    # Sin historia no hay con qué comparar: solo rige el piso absoluto. Mejor
    # ciego que gritando por ruido.
    if len(history) < CANARY_MIN_HISTORY:
        if seen < CANARY_MIN_ITEMS:
            return "partial", (
                f"canario: solo {seen} items (piso {CANARY_MIN_ITEMS}, sin historia)"
            )
        return "ok", None

    if seen == 0:
        return "partial", "canario: 0 items y la historia dice que debería haber"

    median = statistics.median(history)
    if median <= 0:
        return "ok", None

    floor = median * (1 - CANARY_DROP_RATIO)
    if seen < floor:
        drop = round((1 - seen / median) * 100)
        return "partial", (
            f"canario: {seen} items vs mediana {median:g} de las últimas "
            f"{len(history)} corridas ({drop}% menos)"
        )
    return "ok", None


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
) -> RunOutcome:
    """Una categoría de una tienda: discover → persistir → cerrar el run."""
    category: CategoryRef = target["category"]
    category_id: int = target["category_id"]

    run_id: int | None = None
    history: list[int] = []
    if not dry_run:
        async with pool.acquire() as conn:
            # La historia se lee ANTES de abrir la corrida: la fila propia entra
            # en 'running', no en 'ok', pero pedirla primero deja la intención
            # explícita y no depende de ese detalle.
            history = await db.recent_items_seen(
                conn,
                store_id=store_id,
                category_id=category_id,
                store_key=category.store_key,
                window=CANARY_WINDOW,
            )
            run_id = await db.start_run(
                conn,
                store_id=store_id,
                category_id=category_id,
                store_key=category.store_key,
            )

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
    except Exception as exc:  # el adaptador de una tienda no tumba la pasada
        status = "failed"
        error = f"{type(exc).__name__}: {exc}"[:500]
        logger.exception("fallo %s/%s", adapter.slug, category.slug)

    # El remanente se escribe también cuando el adaptador reventó a mitad: lo ya
    # scrapeado es historia que no se recupera. Cuando este flush vivía en el
    # camino feliz, cada corrida fallida tiraba hasta BATCH_SIZE-1 observaciones
    # que ya estaban en memoria (el 404 de Easy perdía entre 20 y 99 por corrida).
    try:
        written += await _flush(
            pool, buffer, store_id=store_id, category_id=category_id, dry_run=dry_run
        )
    except Exception as exc:
        status = "failed"
        error = f"{type(exc).__name__}: {exc}"[:500]
        logger.exception("fallo el último lote de %s/%s", adapter.slug, category.slug)

    if status == "ok":
        completeness = (
            adapter.completeness(category)
            if isinstance(adapter, CountingAdapter)
            else None
        )
        status, error = canary_verdict(seen, history, completeness=completeness)
        if status == "partial":
            logger.warning(
                "canario %s/%s [%s] — %s",
                adapter.slug,
                category.slug,
                category.store_key,
                error,
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

    return RunOutcome(
        store_slug=adapter.slug,
        category_slug=category.slug,
        store_key=category.store_key,
        status=status,
        items_seen=seen,
        items_ok=written,
        error=error,
    )


async def run_once(
    pool: Any,
    *,
    only_store: str | None = None,
    only_category: str | None = None,
    dry_run: bool = False,
) -> list[RunOutcome]:
    outcomes: list[RunOutcome] = []
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
            return outcomes

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
                # Se reporta una vez por target: una tienda que no carga es
                # exactamente lo que la alerta tiene que gritar, no tragarse.
                outcomes.extend(
                    RunOutcome(
                        store_slug=store_slug,
                        category_slug=t["category"].slug,
                        store_key=t["category"].store_key,
                        status="failed",
                        items_seen=0,
                        items_ok=0,
                        error=f"adaptador no cargó: {exc}",
                    )
                    for t in targets
                )
                continue

            adapter = adapter_cls(http, [t["category"] for t in targets])
            for target in targets:
                outcomes.append(
                    await scrape_target(
                        pool, adapter, target, store_id=store["store_id"], dry_run=dry_run
                    )
                )

    return outcomes


async def run_pricing(pool: Any) -> None:
    """Fase de pricing post-pasada: baselines + detector sobre lo recién escrito.

    Va acá y no en un servicio aparte porque el trigger correcto es "llegaron
    observaciones nuevas", y este proceso es el único que sabe cuándo pasó eso
    (ver el docstring de `pricing/pipeline.py`).

    Envuelto porque la ingesta es lo irreversible: una pasada perdida es historia
    que no se recupera, mientras que una corrida de pricing salteada se rehace
    sola en la siguiente. Un bug en el detector NO puede tumbar el scraper. Es el
    mismo criterio con el que un adaptador roto degrada su tienda y nada más.
    """
    try:
        # El import va adentro del try: perezoso como el de alerts, pero además
        # un ImportError es exactamente el modo de falla que se dio en prod
        # (imagen construida sin `pricing/pipeline.py`), y afuera escapaba a esta
        # guarda y tumbaba el ciclo entero.
        from pricing.pipeline import run as run_pipeline

        await run_pipeline(pool)
    except Exception:
        logger.exception("la fase de pricing falló; la ingesta sigue")


async def main() -> int:
    parser = argparse.ArgumentParser(description="Ingesta de precios OfertasCL")
    parser.add_argument("--once", action="store_true", help="una pasada y salir")
    parser.add_argument("--dry-run", action="store_true", help="no escribe a DB")
    parser.add_argument("--store", help="limitar a un slug de tienda")
    parser.add_argument("--category", help="limitar a un slug de categoría")
    parser.add_argument(
        "--skip-pricing",
        action="store_true",
        help="no correr baselines/detector después de la pasada",
    )
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
            outcomes = await run_once(
                pool,
                only_store=args.store,
                only_category=args.category,
                dry_run=args.dry_run,
            )
            if not args.dry_run:
                if not args.skip_pricing:
                    await run_pricing(pool)
                await send_alert(format_summary(outcomes))
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
