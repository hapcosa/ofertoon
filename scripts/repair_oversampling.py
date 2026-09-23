"""Reparación puntual: deduplica el sobremuestreo del 2026-08-14 al 2026-08-19.

No es una migración —no cambia el esquema— sino un arreglo de datos de una sola
vez, consecuencia del incidente del 17 de agosto (178 reinicios del scraper).

Por qué hace falta: `compute_baseline` saca el p50 de los puntos **crudos**, no
de los mínimos diarios, así que la cantidad de observaciones de un día es su peso
en la mediana. Esos seis días aportan 2.013.243 de las 2.567.689 filas de la
tabla —el 61,3 % de la ventana de cada listing en promedio— y el p50 dejó de ser
"la mediana de 8 semanas" para ser "la mediana del 14 al 19 de agosto".

El daño no es solo un descuento inflado: el umbral de la guarda anti-rampa es
`p50 * 1.15`, así que un p50 inflado también **apaga la detección de inflado**.
Medido: de los 70 aceptados del 1-sep, 28 desaparecen al deduplicar y los
rechazos por `ramp` suben de 72 a 88.

Criterio de deduplicación: se conserva la primera observación de cada mitad del
día (00–11 y 12–23), que reproduce la cadencia normal de 2 pasadas diarias. Los
días fuera del rango no se tocan.

Uso:
    docker compose cp scripts/repair_oversampling.py scraper:/tmp/
    docker compose exec -T scraper python /tmp/repair_oversampling.py --dry-run
    docker compose exec -T scraper python /tmp/repair_oversampling.py --apply
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
from datetime import date

import asyncpg

logger = logging.getLogger("repair")

DESDE = date(2026, 8, 14)
HASTA = date(2026, 8, 20)  # exclusivo
CHUNK = 500

SELECT_LISTINGS = """
    SELECT DISTINCT listing_id FROM price_points
     WHERE observed_at >= $1::date AND observed_at < $2::date
     ORDER BY listing_id
"""

DELETE_CHUNK = """
    DELETE FROM price_points pp
     USING (
        SELECT listing_id, observed_at,
               ROW_NUMBER() OVER (
                   PARTITION BY listing_id, observed_at::date,
                                (EXTRACT(hour FROM observed_at)::int / 12)
                   ORDER BY observed_at
               ) AS rn
          FROM price_points
         WHERE listing_id = ANY($1::int[])
           AND observed_at >= $2::date AND observed_at < $3::date
     ) AS d
     WHERE pp.listing_id  = d.listing_id
       AND pp.observed_at = d.observed_at
       AND d.rn > 1
"""

COUNT_DRY = """
    WITH r AS (
      SELECT ROW_NUMBER() OVER (
               PARTITION BY listing_id, observed_at::date,
                            (EXTRACT(hour FROM observed_at)::int / 12)
               ORDER BY observed_at) AS rn
        FROM price_points
       WHERE observed_at >= $1::date AND observed_at < $2::date)
    SELECT COUNT(*) FILTER (WHERE rn > 1) AS borrar,
           COUNT(*) FILTER (WHERE rn = 1) AS quedan
      FROM r
"""

#: Las decisiones del 1-sep se tomaron contra la baseline sucia: como dataset de
#: calibración son inválidas. Borrarlas hace que la pasada siguiente las
#: reevalúe — el detector filtra por `NOT EXISTS` sobre (listing_id,
#: detected_at), así que sin esto no las vuelve a mirar nunca.
#: Los `out_of_stock` se conservan: esa guarda es la primera y no usa baseline.
WHERE_CANDIDATES = """
     WHERE detected_at >= '2026-09-01'::date
       AND reject_reason IS DISTINCT FROM 'out_of_stock'
"""


async def main() -> int:
    ap = argparse.ArgumentParser()
    modo = ap.add_mutually_exclusive_group(required=True)
    modo.add_argument("--dry-run", action="store_true", help="cuenta sin borrar")
    modo.add_argument("--apply", action="store_true", help="borra de verdad")
    args = ap.parse_args()

    logging.basicConfig(level="INFO", format="%(asctime)s %(levelname)s %(message)s")
    conn = await asyncpg.connect(os.environ["DATABASE_URL"])
    try:
        if args.dry_run:
            row = await conn.fetchrow(COUNT_DRY, DESDE, HASTA)
            cands = await conn.fetchval(
                "SELECT COUNT(*) FROM deal_candidates" + WHERE_CANDIDATES
            )
            logger.info("borraría %d puntos, quedan %d", row["borrar"], row["quedan"])
            logger.info("borraría %d filas de deal_candidates del 1-sep", cands)
            return 0

        ids = [r["listing_id"] for r in await conn.fetch(SELECT_LISTINGS, DESDE, HASTA)]
        logger.info("listings con puntos en %s..%s: %d", DESDE, HASTA, len(ids))

        borradas = 0
        for i in range(0, len(ids), CHUNK):
            chunk = ids[i : i + CHUNK]
            async with conn.transaction():
                tag = await conn.execute(DELETE_CHUNK, chunk, DESDE, HASTA)
            borradas += int(tag.split()[-1])
            logger.info(
                "%d/%d listings — %d puntos borrados",
                i + len(chunk), len(ids), borradas,
            )

        tag = await conn.execute("DELETE FROM deal_candidates" + WHERE_CANDIDATES)
        logger.info("deal_candidates borrados: %s", tag.split()[-1])
        logger.info("listo. Corré VACUUM ANALYZE price_points_202608 después.")
        return 0
    finally:
        await conn.close()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
