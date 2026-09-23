"""Criterio de aceptación de una tienda nueva, como consulta fija.

Conectar una tienda es barato; dejarla conectada cuando no rinde no lo es —
suma requests, ruido en el canario y filas en `price_points` que no producen
una sola oferta. Este script responde con datos si la tienda se queda o se apaga.

La pregunta que contesta es **una sola**: ¿esta tienda acumula historia por SKU?
Una tienda que rota su catálogo nunca llega a `MIN_DAYS` por listing y no publica
nada por grande que sea. No hace falta estudiarla antes de conectarla: se conecta,
se esperan 30 días y se mide.

Por qué el denominador es `listing_baselines` y no `listings`: la tabla de
baselines tiene una fila por listing con observaciones en la ventana de 60 días,
o sea lo que la tienda está sirviendo **hoy**. `listings` acumula todo lo que
alguna vez se vio y castigaría a una tienda por su propio pasado.

El umbral es un criterio de producto, no una constante del detector: por debajo
de `UMBRAL_ESTABILIDAD` la tienda rota demasiado catálogo y se desactiva con
`UPDATE stores SET is_active = false`.

Uso:
    python -m scripts.aceptacion_tienda                  # todas las tiendas
    python -m scripts.aceptacion_tienda --store easy
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys

import asyncpg

from pricing.baselines import MIN_DAYS, MIN_POINTS

#: Fracción mínima de los listings vivos que debe alcanzar `MIN_DAYS` de historia.
#: Valor de partida del plan de expansión, no calibrado: se revisa cuando haya
#: media docena de tiendas medidas con esta misma consulta.
UMBRAL_ESTABILIDAD = 0.40

#: Los aceptados van en su propia subconsulta a propósito: unir
#: `deal_candidates` al mismo nivel que `listing_baselines` multiplica las filas
#: por candidato y el conteo de listings sale inflado diez veces.
CONSULTA = """
    WITH estabilidad AS (
        SELECT l.store_id,
               MIN(l.first_seen_at)::date                     AS desde,
               COUNT(b.listing_id)                            AS con_baseline,
               COUNT(b.listing_id) FILTER (
                   WHERE b.n_days >= $1 AND b.n_points >= $2
               )                                              AS maduros
          FROM listings AS l
          LEFT JOIN listing_baselines AS b ON b.listing_id = l.id
         GROUP BY l.store_id
    ),
    aceptados AS (
        SELECT l.store_id, COUNT(*) AS n
          FROM deal_candidates AS c
          JOIN listings AS l ON l.id = c.listing_id
         WHERE c.verdict = 'accepted'
         GROUP BY l.store_id
    )
    SELECT s.slug,
           s.is_active,
           (NOW()::date - e.desde)      AS dias_conectada,
           e.con_baseline,
           e.maduros,
           COALESCE(a.n, 0)             AS aceptados
      FROM stores AS s
      JOIN estabilidad AS e ON e.store_id = s.id
      LEFT JOIN aceptados AS a ON a.store_id = s.id
     WHERE ($3::text IS NULL OR s.slug = $3)
     ORDER BY s.slug
"""


def veredicto(dias: int, con_baseline: int, maduros: int, aceptados: int) -> str:
    """El criterio, en un solo lugar.

    Antes de los 30 días no hay nada que decidir: `MIN_DAYS` es un rechazo, no un
    default, y toda tienda recién conectada da 0% por construcción.
    """
    if dias < MIN_DAYS:
        return f"EN ESPERA — faltan {MIN_DAYS - dias} días para poder evaluarla"
    if con_baseline == 0:
        return "APAGAR — ni un listing con observaciones en la ventana"
    ratio = maduros / con_baseline
    if ratio < UMBRAL_ESTABILIDAD:
        # Los aceptados van en el mismo renglón a propósito: apagar una tienda
        # que igual produce ofertas es una decisión de producto, no automática.
        return (
            f"APAGAR — solo {ratio:.0%} de los listings llega a {MIN_DAYS} días "
            f"(mínimo {UMBRAL_ESTABILIDAD:.0%}): rota demasiado catálogo "
            f"[pero lleva {aceptados} aceptados]"
        )
    if aceptados == 0:
        return f"REVISAR — estabilidad {ratio:.0%} pero ni un candidato aceptado propio"
    return f"MANTENER — estabilidad {ratio:.0%}, {aceptados} aceptados"


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--store", help="limitar a un slug de tienda")
    args = parser.parse_args()

    dsn = os.environ.get("DATABASE_URL", "").strip()
    if not dsn:
        print("DATABASE_URL es obligatoria", file=sys.stderr)
        return 2

    conn = await asyncpg.connect(dsn)
    try:
        rows = await conn.fetch(CONSULTA, MIN_DAYS, MIN_POINTS, args.store)
    finally:
        await conn.close()

    if not rows:
        print("sin tiendas que reportar", file=sys.stderr)
        return 1

    print(f"{'tienda':<12} {'días':>5} {'listings':>9} {'maduros':>8} {'%':>5} "
          f"{'acept.':>7}  veredicto")
    print("-" * 110)
    for row in rows:
        con_baseline = row["con_baseline"]
        pct = (row["maduros"] / con_baseline) if con_baseline else 0.0
        estado = "" if row["is_active"] else "  [ya desactivada]"
        print(
            f"{row['slug']:<12} {row['dias_conectada']:>5} {con_baseline:>9} "
            f"{row['maduros']:>8} {pct:>5.0%} {row['aceptados']:>7}  "
            f"{veredicto(row['dias_conectada'], con_baseline, row['maduros'], row['aceptados'])}"
            f"{estado}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
