"""La cadencia del loop: una pasada cada `SCRAPE_INTERVAL_HOURS`, no por reinicio.

Importa porque `compute_baseline` percentila los puntos CRUDOS, así que la
cantidad de observaciones de un día es su peso en la mediana. El loop contaba el
intervalo desde el arranque del proceso, de modo que cada despliegue y cada
reinicio del daemon de Docker metía una pasada extra ese día.

Medido sobre el catálogo entero de producción (2026-09-24), el efecto de ese
sobremuestreo en la señal es despreciable —97,1 % de los listings con historia
mínima conservan el p50 exacto y cambian 4 decisiones de 13.490—, así que lo que
este cambio protege no es el p50: es a las tiendas. Un crash-loop disparaba una
pasada completa contra las nueve por reinicio (562 corridas en las 48 h de la
caída del 18-sep-2026).
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone

import pytest

import db as db_module
from scrapers import runner

INTERVALO = 12 * 3600


class FakePool:
    def __init__(self):
        self.conn = object()

    @asynccontextmanager
    async def acquire(self):
        yield self.conn


@pytest.fixture
def pool_con_ultima(monkeypatch):
    """Fija qué devuelve `db.ultima_pasada` y entrega un pool de juguete."""

    def _fijar(ultima):
        async def fake(conn):
            return ultima

        monkeypatch.setattr(db_module, "ultima_pasada", fake)
        return FakePool()

    return _fijar


async def test_base_vacia_corre_ya(pool_con_ultima):
    """Primera puesta en marcha: no hay de qué colgarse, se arranca."""
    pool = pool_con_ultima(None)
    assert await runner.espera_hasta_proxima(pool, INTERVALO) == 0.0


async def test_pasada_vencida_corre_ya(pool_con_ultima):
    """Si el intervalo ya se cumplió, no se espera nada."""
    pool = pool_con_ultima(datetime.now(timezone.utc) - timedelta(hours=13))
    assert await runner.espera_hasta_proxima(pool, INTERVALO) == 0.0


async def test_reinicio_reciente_espera_lo_que_falta(pool_con_ultima):
    """El caso que motiva todo: reiniciar 1 h después de una pasada.

    Antes esto corría una pasada entera contra las nueve tiendas. Ahora duerme
    las 11 h que faltan.
    """
    pool = pool_con_ultima(datetime.now(timezone.utc) - timedelta(hours=1))
    espera = await runner.espera_hasta_proxima(pool, INTERVALO)
    assert 10.9 * 3600 < espera <= 11 * 3600


async def test_la_espera_se_ancla_al_inicio_y_no_al_fin_de_la_pasada(pool_con_ultima):
    """Sin esto el ciclo real era de 12,2 h y no de 12: la deriva acumulaba.

    Una pasada tarda ~13 min; contar el intervalo desde que TERMINA corre el
    horario un poco cada día. Anclando al `started_at` la cadencia queda fija.
    """
    inicio = datetime.now(timezone.utc) - timedelta(hours=6)
    pool = pool_con_ultima(inicio)
    espera = await runner.espera_hasta_proxima(pool, INTERVALO)
    proxima = datetime.now(timezone.utc) + timedelta(seconds=espera)
    assert abs((proxima - (inicio + timedelta(seconds=INTERVALO))).total_seconds()) < 2


# --- El ancla contra la DB real -------------------------------------------
# Lo de arriba prueba la aritmética con un `ultima_pasada` de juguete. Lo que
# sigue prueba la CONSULTA, que es donde estaba el error: `scrape_runs` tiene una
# fila por (tienda, llave) y esas filas arrancan escalonadas a lo largo de los
# ~13 min que dura la pasada. Un `MAX(started_at)` devolvía el arranque de la
# última tienda y dejaba la deriva intacta (12 h + 13 min por ciclo, o sea las
# mismas 12,2 h que el cambio decía corregir: media hora por día, y el horario
# da la vuelta al reloj en un mes).


async def _corrida(conn, cuando: datetime) -> None:
    store_id = await conn.fetchval("SELECT id FROM stores WHERE slug = 'falabella'")
    await conn.execute(
        """INSERT INTO scrape_runs (store_id, started_at, finished_at, status)
                VALUES ($1, $2, $2, 'ok')""",
        store_id,
        cuando,
    )


async def test_el_ancla_es_el_arranque_de_la_pasada_no_el_de_la_ultima_tienda(db_conn):
    inicio = datetime.now(timezone.utc) - timedelta(hours=6)
    for minuto in (0, 4, 9, 13):  # la pasada recorriendo tienda por tienda
        await _corrida(db_conn, inicio + timedelta(minutes=minuto))

    assert await db_module.ultima_pasada(db_conn) == inicio


async def test_la_pasada_anterior_no_arrastra_el_ancla_hacia_atras(db_conn):
    """Las pasadas viejas quedan afuera de la ventana: 12 h las separa."""
    anterior = datetime.now(timezone.utc) - timedelta(hours=18)
    actual = datetime.now(timezone.utc) - timedelta(hours=6)
    for minuto in (0, 13):
        await _corrida(db_conn, anterior + timedelta(minutes=minuto))
        await _corrida(db_conn, actual + timedelta(minutes=minuto))

    assert await db_module.ultima_pasada(db_conn) == actual


async def test_sin_corridas_no_hay_ancla(db_conn):
    assert await db_module.ultima_pasada(db_conn) is None
