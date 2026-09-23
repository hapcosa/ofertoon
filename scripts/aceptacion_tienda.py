"""Criterio de aceptación de una tienda nueva, como consulta fija.

Conectar una tienda es barato; dejarla conectada cuando no rinde no lo es —
suma requests, ruido en el canario y filas en `price_points` que no producen
una sola oferta. Este script responde con datos si la tienda se queda o se apaga.

La pregunta que contesta es **una sola**: ¿esta tienda acumula historia por SKU?
Una tienda que rota su catálogo nunca llega a `MIN_DAYS` por listing y no publica
nada por grande que sea. No hace falta estudiarla antes de conectarla: se conecta,
se esperan 30 días y se mide.

El denominador es una **cohorte**, no un corte transversal: solo los listings
que tuvieron la oportunidad de madurar, o sea los nacidos hace más de `MIN_DAYS`.
Medirlo transversalmente (maduros / listings vivos) mete en el denominador a los
SKUs recién llegados, que no maduraron por ser nuevos y no por rotación: hace
ver idéntica a la tienda que **crece** su catálogo y a la que lo **rota**.

No es teórico — es el caso de Easy, medido el 2026-09-23: 34% transversal contra
96% por cohorte, porque el 65% de su catálogo tenía menos de 30 días. El criterio
transversal mandaba apagar la tienda más estable del sistema y salvaba a
Falabella (41% transversal, 51% por cohorte), que es la que de verdad rota.

La cohorte además se acota por arriba (`VENTANA_COHORTE`): sin ese corte, los
listings muertos hace meses se acumulan en el denominador para siempre y el
indicador de cualquier tienda se degrada solo con el paso del tiempo.

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

#: Fracción mínima de la cohorte que debe alcanzar `MIN_DAYS` de historia.
#: Valor de partida del plan de expansión, no calibrado: se revisa cuando haya
#: media docena de tiendas medidas con esta misma consulta.
UMBRAL_ESTABILIDAD = 0.40

#: Antigüedad máxima de la cohorte. Mide "de los SKUs que la tienda tenía hace
#: un trimestre, cuántos siguen vivos", y mantiene el indicador comparable en el
#: tiempo en vez de dejarlo hundirse bajo el peso del catálogo muerto histórico.
VENTANA_COHORTE_DIAS = 90

#: Los aceptados van en su propia subconsulta a propósito: unir
#: `deal_candidates` al mismo nivel que `listing_baselines` multiplica las filas
#: por candidato y el conteo de listings sale inflado diez veces.
#:
#: `cohorte` no exige que exista la fila en `listing_baselines`: un listing de la
#: cohorte sin baseline es exactamente uno que murió y se cayó de la ventana de
#: 60 días, y tiene que contar como fallo, no desaparecer del denominador.
CONSULTA = """
    WITH conexion AS (
        SELECT store_id,
               MIN(first_seen_at)::date   AS desde,
               COUNT(*) FILTER (
                   WHERE first_seen_at >= NOW() - MAKE_INTERVAL(days => $1)
               )                          AS nuevos
          FROM listings
         GROUP BY store_id
    ),
    cohorte AS (
        SELECT l.store_id,
               COUNT(*)                                        AS n,
               COUNT(*) FILTER (
                   WHERE b.n_days >= $1 AND b.n_points >= $2
               )                                               AS maduros
          FROM listings AS l
          LEFT JOIN listing_baselines AS b ON b.listing_id = l.id
         WHERE l.first_seen_at <  NOW() - MAKE_INTERVAL(days => $1)
           AND l.first_seen_at >= NOW() - MAKE_INTERVAL(days => $4)
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
           (NOW()::date - x.desde)      AS dias_conectada,
           x.nuevos                     AS nuevos,
           COALESCE(c.n, 0)             AS cohorte,
           COALESCE(c.maduros, 0)       AS maduros,
           COALESCE(a.n, 0)             AS aceptados
      FROM stores AS s
      JOIN conexion AS x ON x.store_id = s.id
      LEFT JOIN cohorte AS c ON c.store_id = s.id
      LEFT JOIN aceptados AS a ON a.store_id = s.id
     WHERE ($3::text IS NULL OR s.slug = $3)
     ORDER BY s.slug
"""


def veredicto(dias: int, cohorte: int, maduros: int, aceptados: int) -> str:
    """El criterio, en un solo lugar.

    Antes de los 30 días no hay nada que decidir: `MIN_DAYS` es un rechazo, no un
    default, y toda tienda recién conectada da 0% por construcción.
    """
    if dias < MIN_DAYS:
        return f"EN ESPERA — faltan {MIN_DAYS - dias} días para poder evaluarla"
    if cohorte == 0:
        return "EN ESPERA — ni un listing cumplió aún la ventana de la cohorte"
    ratio = maduros / cohorte
    if ratio < UMBRAL_ESTABILIDAD:
        # Los aceptados van en el mismo renglón a propósito: apagar una tienda
        # que igual produce ofertas es una decisión de producto, no automática.
        return (
            f"APAGAR — de los listings que pudieron madurar solo {ratio:.0%} "
            f"llegó a {MIN_DAYS} días (mínimo {UMBRAL_ESTABILIDAD:.0%}): rota "
            f"demasiado catálogo [pero lleva {aceptados} aceptados]"
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
        rows = await conn.fetch(
            CONSULTA, MIN_DAYS, MIN_POINTS, args.store, VENTANA_COHORTE_DIAS
        )
    finally:
        await conn.close()

    if not rows:
        print("sin tiendas que reportar", file=sys.stderr)
        return 1

    print(f"{'tienda':<12} {'días':>5} {'cohorte':>8} {'maduros':>8} {'%':>5} "
          f"{'nuevos':>7} {'acept.':>7}  veredicto")
    print("-" * 118)
    for row in rows:
        cohorte = row["cohorte"]
        pct = (row["maduros"] / cohorte) if cohorte else 0.0
        estado = "" if row["is_active"] else "  [ya desactivada]"
        print(
            f"{row['slug']:<12} {row['dias_conectada']:>5} {cohorte:>8} "
            f"{row['maduros']:>8} {pct:>5.0%} {row['nuevos']:>7} "
            f"{row['aceptados']:>7}  "
            f"{veredicto(row['dias_conectada'], cohorte, row['maduros'], row['aceptados'])}"
            f"{estado}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
