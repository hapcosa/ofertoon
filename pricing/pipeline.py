"""La fase de pricing: recomputa baselines y corre el detector.

Es la pieza que hasta F3 no existía. `baselines.py` y `detector.py` estaban
escritos y testeados pero no los invocaba nadie en producción: el único
entrypoint era `backtest.py`, una herramienta offline. Esto los conecta.

**Corre dentro del ciclo del scraper**, no como servicio con reloj propio. La
razón es que el trigger correcto de una baseline no es una hora del día sino
"llegaron observaciones nuevas", y el único proceso que sabe cuándo pasó eso es
el runner que las acaba de escribir. Un cron separado tendría que adivinarlo —
y cuando se desincroniza (una pasada tarda más que otra) el detector evalúa
medio catálogo contra la foto de hace 12 h y medio contra la de recién.

El publisher NO vive acá. Ése sí tiene reloj propio, porque *cuándo se publica*
es una decisión de producto independiente de cuándo llegó el dato.

Uso:
    python -m pricing.pipeline          # una corrida contra DATABASE_URL
"""
from __future__ import annotations

import asyncio
import logging
import os
import sys
from dataclasses import dataclass

import asyncpg

import db
from pricing import baselines, detector

logger = logging.getLogger("pricing.pipeline")


@dataclass(frozen=True)
class PipelineStats:
    baselines: baselines.BaselineStats
    detector: detector.DetectorStats

    def __str__(self) -> str:
        return f"baselines[{self.baselines}] detector[{self.detector}]"


async def run(pool: asyncpg.Pool) -> PipelineStats:
    """Recomputa baselines y evalúa las observaciones nuevas. Idempotente.

    El orden es obligatorio: el detector lee `listing_baselines`, así que
    correrlo antes de recomputar mediría el precio de hoy contra la referencia
    de ayer.
    """
    baseline_stats = await baselines.recompute_all(pool)
    detector_stats = await detector.run(pool)

    stats = PipelineStats(baseline_stats, detector_stats)
    # Este log es el que distingue "el job no corrió" de "el job corrió y
    # descartó todo". Durante el cold-start (hasta ~2026-09-02) el resultado
    # correcto es 0 aceptados con todo el catálogo rechazado por `history`, y
    # esos rechazos no dejan fila en `deal_candidates` — una tabla vacía no
    # prueba nada por sí sola. Estas dos líneas sí.
    logger.info("pipeline: %s", stats)
    return stats


async def main() -> int:
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    dsn = os.environ.get("DATABASE_URL", "").strip()
    if not dsn:
        logger.error("DATABASE_URL es obligatoria")
        return 2

    pool = await db.create_pool(dsn)
    try:
        await run(pool)
    finally:
        await pool.close()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
