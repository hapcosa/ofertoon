"""Cadencia de muestreo de la serie: ¿está pareja, o hay días que pesan de más?

Existe porque el modo de falla que motiva este script no deja alerta. Una caída
de la red saliente del host tumba el scraping de las seis tiendas Y el envío del
aviso, que viaja por `api.telegram.org`. Del 18 al 20 de septiembre de 2026 eso
dejó 48 h sin una sola observación y 562 corridas `failed` sin que nadie se
enterara; se encontró cinco días después mirando `price_points` a mano. Esto es
esa consulta, hecha repetible.

Qué mirar en la salida:

- **`obs/listing` ≈ 2,0** es la cadencia sana (`SCRAPE_INTERVAL_HOURS=12`).
  Cerca de 1,0 es media pasada perdida; arriba de 2,5 es sobremuestreo.
- **`—— sin datos ——`** es un agujero: le baja `n_days` a todos los listings
  vivos y deja al backtest sin candidatos ese día.
- **`dup`** son las mitades de día (00–11 / 12–23) con más de una observación
  del mismo listing. Es el peso extra que ese día mete en su propio p50, porque
  `compute_baseline` percentila los puntos crudos.

Importa porque el p50 se saca de los puntos crudos: la cantidad de
observaciones de un día ES su peso en la mediana. El desastre de agosto de 2026
(61 % de las filas de la ventana en seis días) se ve acá de un vistazo.

Uso:
    DATABASE_URL=<dsn> python -m scripts.salud_serie [--dias 60]
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from datetime import timedelta

import asyncpg

CONSULTA = """
    WITH p AS (
        SELECT listing_id, observed_at::date AS d,
               (EXTRACT(hour FROM observed_at)::int / 12) AS mitad
          FROM price_points
         WHERE observed_at >= CURRENT_DATE - ($1::int) * INTERVAL '1 day'
    ), b AS (
        SELECT d, listing_id, mitad, COUNT(*) AS n FROM p GROUP BY 1, 2, 3
    )
    SELECT d,
           SUM(n)                          AS obs,
           COUNT(DISTINCT listing_id)      AS listings,
           COUNT(*) FILTER (WHERE n > 1)   AS dup
      FROM b GROUP BY d ORDER BY d
"""

RUNS = """
    SELECT started_at::date AS d,
           COUNT(*)                                   AS runs,
           COUNT(*) FILTER (WHERE status = 'failed')  AS failed
      FROM scrape_runs
     WHERE started_at >= CURRENT_DATE - ($1::int) * INTERVAL '1 day'
     GROUP BY 1
"""


async def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dias", type=int, default=60, help="ventana a revisar")
    args = ap.parse_args()

    dsn = os.environ.get("DATABASE_URL", "").strip()
    if not dsn:
        print("DATABASE_URL es obligatoria", file=sys.stderr)
        return 2

    conn = await asyncpg.connect(dsn)
    try:
        filas = {r["d"]: r for r in await conn.fetch(CONSULTA, args.dias)}
        runs = {r["d"]: r for r in await conn.fetch(RUNS, args.dias)}
        desde = await conn.fetchval(
            "SELECT MIN(observed_at)::date FROM price_points"
        )
    finally:
        await conn.close()

    if not filas:
        print("no hay observaciones en la ventana")
        return 1

    print(f"{'día':12} {'obs':>8} {'listings':>9} {'obs/listing':>12} "
          f"{'dup':>7} {'runs':>6} {'failed':>7}")
    huecos = []
    primero, ultimo = min(filas), max(filas)
    dia = primero
    while dia <= ultimo:
        f, r = filas.get(dia), runs.get(dia, {})
        if f is None:
            # Antes del primer dato el sistema no existía: eso no es un agujero.
            marca = "—— sin datos ——" if desde and dia > desde else "(sin sistema)"
            print(f"{dia!s:12} {marca:>48}")
            if desde and dia > desde:
                huecos.append(dia)
        else:
            ratio = f["obs"] / f["listings"]
            flag = "  ⚠" if ratio < 1.5 or ratio > 2.4 else ""
            print(f"{dia!s:12} {f['obs']:>8} {f['listings']:>9} {ratio:>12.2f} "
                  f"{f['dup']:>7} {r.get('runs', 0):>6} {r.get('failed', 0):>7}{flag}")
        dia += timedelta(days=1)

    print()
    if huecos:
        print(f"⚠ {len(huecos)} día(s) SIN observaciones: "
              f"{', '.join(str(d) for d in huecos)}")
    else:
        print("✓ sin agujeros en la ventana")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
