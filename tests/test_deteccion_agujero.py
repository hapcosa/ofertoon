"""`db.dias_sin_observaciones`: encontrar los días en que la serie se cortó.

La consulta existe porque el aviso de una caída de red no puede viajar por la
red que se cayó. Del 18 al 20 de septiembre de 2026 el host perdió la salida a
internet: las seis tiendas fallaron al 100 %, se acumularon 562 corridas
`failed` y ni una sola alerta salió, porque `api.telegram.org` tampoco
resolvía. El agujero se descubrió cinco días después mirando `price_points` a
mano — y es un agujero caro: le baja `n_days` a cada listing vivo y deja al
backtest sin candidatos que evaluar esos días.

Lo único que sobrevive a esa caída es la serie misma, que vive en el Postgres
local. De ahí sale esta consulta.

Necesita `TEST_DATABASE_URL` apuntando a una base descartable; sin ella se
saltea.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal

import pytest

import db as db_module

pytestmark = pytest.mark.asyncio


async def _listing(conn) -> int:
    store_id = await conn.fetchval("SELECT id FROM stores WHERE slug = 'falabella'")
    category_id = await conn.fetchval(
        "SELECT id FROM categories WHERE slug = 'tecno-notebooks'"
    )
    return await conn.fetchval(
        """
        INSERT INTO listings (store_id, category_id, store_sku, url, name_raw, is_active)
             VALUES ($1, $2, 'sku-gap', 'https://example.cl/x', 'Notebook', TRUE)
          RETURNING id
        """,
        store_id,
        category_id,
    )


async def _observar(conn, listing_id: int, dia: date) -> None:
    """Una observación a mediodía de ese día, con su partición."""
    at = datetime.combine(dia, time(12, 0), tzinfo=timezone.utc)
    desde = at.replace(day=1, hour=0, minute=0)
    hasta = datetime(desde.year + (desde.month == 12), desde.month % 12 + 1, 1,
                     tzinfo=timezone.utc)
    await conn.execute(
        f"""CREATE TABLE IF NOT EXISTS price_points_{desde:%Y%m}
            PARTITION OF price_points
            FOR VALUES FROM ('{desde:%Y-%m-%d}') TO ('{hasta:%Y-%m-%d}')"""
    )
    await conn.execute(
        """INSERT INTO price_points (listing_id, observed_at, price_effective, in_stock)
                VALUES ($1, $2, $3, TRUE)""",
        listing_id,
        at,
        Decimal("199990"),
    )


async def test_serie_continua_no_reporta_nada(db_conn):
    listing_id = await _listing(db_conn)
    hoy = date.today()
    for atras in range(1, 5):
        await _observar(db_conn, listing_id, hoy - timedelta(days=atras))
    assert await db_module.dias_sin_observaciones(db_conn) == []


async def test_encuentra_el_dia_que_falta(db_conn):
    """El patrón del 18-sep: un día entero sin una sola fila."""
    listing_id = await _listing(db_conn)
    hoy = date.today()
    await _observar(db_conn, listing_id, hoy - timedelta(days=1))
    # falta hoy-2
    await _observar(db_conn, listing_id, hoy - timedelta(days=3))
    assert await db_module.dias_sin_observaciones(db_conn) == [hoy - timedelta(days=2)]


async def test_reporta_los_agujeros_del_mas_viejo_al_mas_nuevo(db_conn):
    listing_id = await _listing(db_conn)
    hoy = date.today()
    await _observar(db_conn, listing_id, hoy - timedelta(days=1))
    faltantes = await db_module.dias_sin_observaciones(db_conn)
    assert faltantes == [hoy - timedelta(days=3), hoy - timedelta(days=2)]


async def test_hoy_nunca_cuenta_como_agujero(db_conn):
    """Hasta que corra la primera pasada del día, hoy está legítimamente vacío.

    Sin esta exclusión el aviso saldría cada mañana y a la semana se ignoraría,
    que es exactamente cómo se pierde la alerta que sí importa.
    """
    listing_id = await _listing(db_conn)
    hoy = date.today()
    for atras in range(1, 4):
        await _observar(db_conn, listing_id, hoy - timedelta(days=atras))
    assert hoy not in await db_module.dias_sin_observaciones(db_conn)


async def test_la_ventana_no_mira_mas_atras_de_lo_pedido(db_conn):
    """El aviso tiene que callarse solo: sin estado, el corte es la ventana.

    Una caída vieja ya se reportó cuando pasó; seguir gritándola sería ruido.
    """
    listing_id = await _listing(db_conn)
    hoy = date.today()
    await _observar(db_conn, listing_id, hoy - timedelta(days=1))
    assert await db_module.dias_sin_observaciones(db_conn, lookback=1) == []
