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

⚠️ **Los días que habilitan a un listing a madurar son los días OBSERVADOS, no
los días calendario**, y confundirlos hace que el script culpe a la tienda de un
agujero de infraestructura. Pasó el 2026-11-04: Tottus y Nike, conectadas el
1-oct, daban **0% de maduros y veredicto APAGAR** con 2.755 y 80 aceptados
respectivamente. La causa era aritmética: 34 días calendario menos los 5 del
agujero del 14-18 de octubre son 29 días observados, así que **ningún** listing
suyo podía llegar a los 30 que exige `MIN_DAYS` — el 0% era por construcción y no
por rotación. Hacerle caso habría apagado dos tiendas grandes a la vez, que es
justo lo que la guarda de volumen vigila. Por eso el veredicto mira
`dias_con_serie` (de `scrape_runs`) y no la antigüedad de la conexión.

⚠️ **Un listing que nunca tuvo stock tampoco pudo madurar, y por eso sale del
denominador.** `compute_baseline` filtra `if in_stock` sobre los puntos crudos:
un listing sin una sola observación con stock no tiene baseline ni `n_days` por
diseño, y su reloj de `MIN_DAYS` arranca el día que aparece stock. Es el mismo
error conceptual que el caso de Easy —meter en el denominador listings que no
pudieron madurar—, una capa más abajo. Pasó el 2026-11-04 con Kruuse, que es un
importador de maquinaria y vende a pedido (3.467 de 3.772 productos en
`backorder`, documentado en su adaptador): de los 628 listings de su cohorte
**518 nunca tuvieron una observación con stock**, y el veredicto salía APAGAR
con 14%. Sobre los 110 que pudieron madurar son 89, o sea **81%: MANTENER**.

Medido sobre las 15 tiendas, la corrección mueve tres y no empeora a ninguna:
kruuse 14%→81%, prat 82%→96% (199 sin stock, ya era MANTENER) y nike, cuyos 163
sin stock **no** cambian su 0% porque ahí la causa es el agujero de octubre. Son
dos falsos positivos distintos del mismo indicador y conviene no confundirlos.
Las columnas `s/stock` y `%bruto` dejan ver cuántos se descontaron y qué decía
el número viejo, para que la corrección no sea invisible.

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
    -- Listings con al menos una observación con stock. Los demás no tienen
    -- baseline por diseño (`compute_baseline` filtra `if in_stock`), así que no
    -- pertenecen al denominador: nunca pudieron madurar. Un DISTINCT sobre los
    -- 3,1M de `price_points` resuelve en 0,2 s; no hace falta acotarlo por fecha
    -- y acotarlo sería peor, porque un listing con stock en agosto y backorder
    -- desde entonces sí tuvo su oportunidad.
    con_stock AS (
        SELECT DISTINCT listing_id
          FROM price_points
         WHERE in_stock
    ),
    cohorte AS (
        SELECT l.store_id,
               COUNT(*)                                        AS n,
               COUNT(*) FILTER (WHERE k.listing_id IS NULL)     AS sin_stock,
               -- El numerador se restringe al mismo conjunto que el
               -- denominador. Hoy es redundante —una baseline con `n_days` ya
               -- implica stock— pero garantiza `maduros <= medible`, que es el
               -- número del que cuelga el veredicto.
               COUNT(*) FILTER (
                   WHERE k.listing_id IS NOT NULL
                     AND b.n_days >= $1 AND b.n_points >= $2
               )                                               AS maduros
          FROM listings AS l
          LEFT JOIN listing_baselines AS b ON b.listing_id = l.id
          LEFT JOIN con_stock AS k ON k.listing_id = l.id
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
    ),
    -- Días en que la tienda DEJÓ serie. Es el techo de `n_days` de cualquiera
    -- de sus listings, así que es lo que decide si la cohorte pudo madurar.
    -- Sale de `scrape_runs` (26.744 filas) y no de `price_points` (millones):
    -- `items_ok > 0` es exactamente "esta pasada escribió observaciones".
    serie AS (
        SELECT store_id, COUNT(DISTINCT started_at::date) AS dias
          FROM scrape_runs
         WHERE items_ok > 0
         GROUP BY store_id
    )
    SELECT s.slug,
           s.is_active,
           (NOW()::date - x.desde)      AS dias_conectada,
           COALESCE(d.dias, 0)          AS dias_con_serie,
           x.nuevos                     AS nuevos,
           COALESCE(c.n, 0)             AS cohorte,
           COALESCE(c.sin_stock, 0)     AS sin_stock,
           COALESCE(c.maduros, 0)       AS maduros,
           COALESCE(a.n, 0)             AS aceptados
      FROM stores AS s
      JOIN conexion AS x ON x.store_id = s.id
      LEFT JOIN cohorte AS c ON c.store_id = s.id
      LEFT JOIN aceptados AS a ON a.store_id = s.id
      LEFT JOIN serie AS d ON d.store_id = s.id
     WHERE ($3::text IS NULL OR s.slug = $3)
     ORDER BY s.slug
"""


def veredicto(
    dias: int,
    cohorte: int,
    sin_stock: int,
    maduros: int,
    aceptados: int,
    dias_con_serie: int,
) -> str:
    """El criterio, en un solo lugar.

    Antes de los 30 días no hay nada que decidir: `MIN_DAYS` es un rechazo, no un
    default, y toda tienda recién conectada da 0% por construcción.

    `dias_con_serie` es la guarda contra culpar a la tienda de un agujero del
    sistema: mientras la tienda no haya sido observada `MIN_DAYS` días distintos,
    su techo de maduración es menor que el umbral y el porcentaje no significa
    nada. Ver el aviso del docstring del módulo (Tottus y Nike, 2026-11-04).

    `sin_stock` es la otra guarda, y descuenta del denominador los listings que
    nunca tuvieron una observación con stock: su reloj de `MIN_DAYS` todavía no
    arrancó. Ver el segundo aviso del módulo (Kruuse, 2026-11-04).
    """
    medible = cohorte - sin_stock
    if dias < MIN_DAYS:
        return f"EN ESPERA — faltan {MIN_DAYS - dias} días para poder evaluarla"
    if dias_con_serie < MIN_DAYS:
        faltan = MIN_DAYS - dias_con_serie
        return (
            f"EN ESPERA — lleva {dias} días conectada pero solo {dias_con_serie} "
            f"OBSERVADOS ({dias - dias_con_serie} perdidos en agujeros del "
            f"sistema): ningún listing puede llegar a {MIN_DAYS} todavía, así que "
            f"el {maduros / medible if medible else 0:.0%} de arriba no mide la "
            f"tienda. Faltan {faltan} pasada(s) diaria(s) "
            f"[lleva {aceptados} aceptados]"
        )
    if cohorte == 0:
        return "EN ESPERA — ni un listing cumplió aún la ventana de la cohorte"
    if medible == 0:
        # Una tienda de puro backorder no es una tienda que rote catálogo: es
        # una que todavía no empezó a medirse. Apagarla por 0% sería el error
        # de Kruuse llevado al extremo.
        return (
            f"EN ESPERA — los {cohorte} listings de la cohorte nunca tuvieron una "
            f"observación con stock, así que su reloj de {MIN_DAYS} días no "
            f"arrancó: no hay nada que medir todavía "
            f"[lleva {aceptados} aceptados]"
        )
    ratio = maduros / medible
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

    # `%bruto` es el indicador viejo —maduros sobre la cohorte entera— y queda a
    # la vista al lado del real a propósito: en 12 de las 15 tiendas los dos son
    # el mismo número, y donde difieren la diferencia es el diagnóstico.
    print(f"{'tienda':<12} {'días':>5} {'serie':>6} {'cohorte':>8} {'s/stock':>8} "
          f"{'medible':>8} {'maduros':>8} {'%':>5} {'%bruto':>7} {'nuevos':>7} "
          f"{'acept.':>7}  veredicto")
    print("-" * 160)
    for row in rows:
        cohorte = row["cohorte"]
        sin_stock = row["sin_stock"]
        medible = cohorte - sin_stock
        pct = (row["maduros"] / medible) if medible else 0.0
        pct_bruto = (row["maduros"] / cohorte) if cohorte else 0.0
        estado = "" if row["is_active"] else "  [ya desactivada]"
        print(
            f"{row['slug']:<12} {row['dias_conectada']:>5} "
            f"{row['dias_con_serie']:>6} {cohorte:>8} {sin_stock:>8} "
            f"{medible:>8} {row['maduros']:>8} {pct:>5.0%} {pct_bruto:>7.0%} "
            f"{row['nuevos']:>7} {row['aceptados']:>7}  "
            f"{veredicto(row['dias_conectada'], cohorte, sin_stock, row['maduros'], row['aceptados'], row['dias_con_serie'])}"
            f"{estado}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
