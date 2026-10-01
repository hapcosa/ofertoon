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


async def _serie_completa(conn, listing_id, hoy, *, salvo=()) -> None:
    """Observa todos los días de la ventana menos los de `salvo`.

    Se siembra la ventana ENTERA en vez de un puñado de días fijos: estos tests
    se escribieron contra `GAP_LOOKBACK_DAYS = 3` sembrando cuatro días, así que
    al ampliar la ventana a 7 fallaron los tres por los días de más que quedaban
    sin sembrar — no por un cambio de comportamiento. Lo que prueban es el
    contrato (qué cuenta como agujero), no cuánto mide la ventana; eso lo fija
    `test_la_ventana_llega_a_una_caida_de_hace_cinco_dias`.
    """
    for atras in range(1, db_module.GAP_LOOKBACK_DAYS + 1):
        if atras not in salvo:
            await _observar(conn, listing_id, hoy - timedelta(days=atras))


async def test_serie_continua_no_reporta_nada(db_conn):
    listing_id = await _listing(db_conn)
    hoy = date.today()
    await _serie_completa(db_conn, listing_id, hoy)
    assert await db_module.dias_sin_observaciones(db_conn) == []


async def test_encuentra_el_dia_que_falta(db_conn):
    """El patrón del 18-sep: un día entero sin una sola fila."""
    listing_id = await _listing(db_conn)
    hoy = date.today()
    await _serie_completa(db_conn, listing_id, hoy, salvo=(2,))
    assert await db_module.dias_sin_observaciones(db_conn) == [hoy - timedelta(days=2)]


async def test_reporta_los_agujeros_del_mas_viejo_al_mas_nuevo(db_conn):
    listing_id = await _listing(db_conn)
    hoy = date.today()
    await _serie_completa(db_conn, listing_id, hoy, salvo=(2, 3))
    faltantes = await db_module.dias_sin_observaciones(db_conn)
    assert faltantes == [hoy - timedelta(days=3), hoy - timedelta(days=2)]


async def test_la_ventana_llega_a_una_caida_de_hace_cinco_dias(db_conn):
    """Por qué la ventana pasó de 3 días a 7, y el test que lo sujeta.

    El agujero del 18-19 de septiembre de 2026 se descubrió CINCO días después,
    mirando `price_points` a mano. Con la ventana de 3 días esta consulta ya no
    lo veía: una caída de viernes a la que se llega el lunes caía afuera y no se
    reportaba nunca. El ciclo real de atención de un operador es el fin de
    semana, así que la ventana tiene que cubrirlo.
    """
    listing_id = await _listing(db_conn)
    hoy = date.today()
    await _serie_completa(db_conn, listing_id, hoy, salvo=(5,))
    assert hoy - timedelta(days=5) in await db_module.dias_sin_observaciones(db_conn)


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
