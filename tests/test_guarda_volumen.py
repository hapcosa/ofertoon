"""La guarda por volumen de pasada: ver que la pasada corrió a medias.

Existe porque el 29 de septiembre de 2026 la pasada de las 03:16 UTC perdió 62
de sus 129 objetivos —fallos de DNS a ráfagas y un reboot del host a las 03:58
que la cortó por la mitad— y escribió 1.481 observaciones contra las ~16.500 de
siempre. **Ninguna de las tres guardas dijo una palabra**, y eso está verificado
contra la DB de producción, no supuesto:

- `dias_sin_observaciones` solo ve días COMPLETAMENTE vacíos, y ese día tenía
  datos: pasó como sano.
- el canario de `runner.canary_verdict` compara cada target contra su propia
  historia, y los 62 objetivos que nunca corrieron no dejaron fila que comparar.
  Los 67 que sí corrieron salieron `ok`, porque individualmente estaban bien.
- los `outcomes` de esa pasada nunca llegaron a `format_summary`: el proceso
  murió DENTRO de `run_once`, o sea antes de `run_pricing` y de `send_alert`.

La alerta de la pasada siguiente salió normal y dijo "2 degradadas de 129". Es
el tercer episodio del mismo modo de falla (19-ago, 18-20-sep, 29-sep) y el
primero con una guarda que lo mira.

Los tests puros corren en cualquier máquina; los de `volumen_por_pasada` piden
`TEST_DATABASE_URL` apuntando a una base descartable y si no se saltean.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

import db as db_module
from scrapers import runner

AHORA = datetime(2026, 9, 29, 15, 16, tzinfo=timezone.utc)


def serie(*observaciones: int) -> list[tuple[datetime, int]]:
    """Pasadas cada 12 h, de la más nueva a la más vieja — como las da la DB."""
    return [
        (AHORA - timedelta(hours=12 * i), obs) for i, obs in enumerate(observaciones)
    ]


# --- La lógica pura ---------------------------------------------------------


def test_serie_estable_no_reporta_nada():
    """El caso normal: el volumen oscila unos cientos y nada de eso es un fallo."""
    assert runner.pasadas_flacas(serie(16509, 16627, 16666, 15384, 16035, 16604, 16508)) == []


def test_encuentra_la_pasada_a_medias():
    """El 29-sep con los números reales de producción."""
    volumenes = serie(1481, 16509, 16627, 16666, 15384, 20035, 11604, 11508)
    flacas = runner.pasadas_flacas(volumenes)

    assert len(flacas) == 1
    assert flacas[0].observaciones == 1481
    assert flacas[0].mediana == 16509  # mediana de las 7 previas
    assert flacas[0].inicio == AHORA


def test_una_pasada_en_cero_tambien_es_flaca():
    """El patrón del 18-sep visto por pasada y no por día.

    Importa porque la pasada en cero se ve ~12 h antes que el día vacío: el
    agujero del día no se puede reportar hasta que el día termine.
    """
    flacas = runner.pasadas_flacas(serie(0, 10713, 10874, 10610, 10861, 10817, 10545, 10565))
    assert len(flacas) == 1 and flacas[0].observaciones == 0


def test_sin_historia_suficiente_no_se_opina():
    """Base recién creada o tienda recién conectada: mejor ciego que ruidoso."""
    assert runner.pasadas_flacas(serie(100, 9000, 9000)) == []


def test_con_mediana_cero_la_guarda_se_apaga_sola():
    """Una racha larga se reporta hasta que la mediana móvil llega a cero.

    Con `window=7` hacen falta CUATRO pasadas caídas para que la mediana sea
    cero, así que la quinta y las que siguen ya no tienen vara contra la cual
    compararse y salen en silencio. Es el mismo autoapagado que ya tiene el
    canario por target y está documentado en CLAUDE.md: el diagnóstico se hace
    en esa ventana o no se hace. Un silencio posterior no dice que se haya
    resuelto — dice que la guarda dejó de mirar.

    Las 48 h del 18-sep son exactamente esto: 4 pasadas caídas, y la quinta ya
    no habría avisado. `dias_sin_observaciones` es la guarda que cubre ese
    tramo, porque un día vacío no se autoanestesia.
    """
    racha = runner.pasadas_flacas(serie(0, 0, 0, 0, 0, 10713, 10874, 10610))

    # Las cuatro más viejas de la racha avisan; la más nueva ya está ciega.
    assert [f.observaciones for f in racha] == [0, 0, 0, 0]
    assert AHORA not in [f.inicio for f in racha]
    assert racha[0].inicio == AHORA - timedelta(hours=48)


def test_la_racha_caida_deja_de_avisar_en_la_quinta_pasada():
    """El corolario operativo del autoapagado, aislado para que no se pierda."""
    assert runner.pasadas_flacas(serie(0, 0, 0, 0, 0, 0, 0, 10713, 10874, 10610)) != []
    # Con la ventana entera en cero no queda nada contra qué comparar.
    assert runner.pasadas_flacas(serie(0, 0, 0, 0, 0, 0, 0, 0)) == []


def test_la_mediana_resiste_el_outlier_del_backfill():
    """El 15-ago una pasada escribió 1.659.450 (la migración al host nuevo).

    Con un promedio, la vara habría quedado en ~240.000 y cada pasada sana de la
    semana siguiente se habría reportado como flaca. Con mediana, el outlier no
    mueve nada.
    """
    assert runner.pasadas_flacas(serie(9824, 9824, 1659450, 9737, 9577, 9627, 9691, 9701)) == []


def test_conectar_una_tienda_sube_el_nivel_sin_disparar():
    """Del 23 al 27-sep el volumen pasó de 10.869 a 16.500 al conectar tiendas.

    Un cambio de nivel hacia arriba nunca es un fallo, y la mediana lo absorbe.
    """
    assert runner.pasadas_flacas(serie(16666, 15384, 20035, 12927, 13085, 12990, 10869, 10515)) == []


def test_el_lookback_acota_lo_que_se_reporta():
    """El aviso se calla solo: sin estado que mantener, el corte es la ventana."""
    volumenes = serie(*([10000] * 3 + [100] + [10000] * 8))
    assert len(runner.pasadas_flacas(volumenes)) == 1
    assert runner.pasadas_flacas(volumenes, lookback=3) == []


def test_las_flacas_salen_de_la_mas_vieja_a_la_mas_nueva():
    """Mismo orden que `dias_sin_observaciones`: primero lo que hay que explicar."""
    volumenes = serie(*([100] + [10000] * 3 + [100] + [10000] * 7))
    flacas = runner.pasadas_flacas(volumenes)
    assert len(flacas) == 2
    assert flacas[0].inicio < flacas[1].inicio


def test_el_umbral_exacto_no_es_delicado():
    """Medido: la sana más flaca da 0,89 y el peor incidente 0,09.

    Entre esos dos no hay nada, así que mover el umbral dentro del hueco no
    cambia ni un veredicto. Es lo que hace defendible el 0,40.
    """
    sana = serie(8900, 10000, 10000, 10000, 10000, 10000, 10000, 10000)
    incidente = serie(900, 10000, 10000, 10000, 10000, 10000, 10000, 10000)
    for ratio in (0.20, 0.40, 0.60, 0.80):
        assert runner.pasadas_flacas(sana, drop_ratio=ratio) == []
        assert len(runner.pasadas_flacas(incidente, drop_ratio=ratio)) == 1


# --- La consulta contra la DB real ------------------------------------------
# `scrape_runs` no tiene una fila por pasada sino una por (tienda, llave), y
# arrancan escalonadas a lo largo de los ~13 min que la pasada tarda en recorrer
# las tiendas. Reconstruir la pasada a partir de eso es donde esta guarda se
# puede romper en silencio, así que se prueba contra Postgres.

pytestmark_db = pytest.mark.asyncio


async def _corrida(conn, cuando: datetime, items_ok: int, status: str = "ok") -> None:
    store_id = await conn.fetchval("SELECT id FROM stores WHERE slug = 'falabella'")
    await conn.execute(
        """INSERT INTO scrape_runs (store_id, started_at, finished_at, status, items_ok)
                VALUES ($1, $2, $2, $3, $4)""",
        store_id,
        cuando,
        status,
        items_ok,
    )


@pytest.mark.asyncio
async def test_las_corridas_escalonadas_son_una_sola_pasada(db_conn):
    inicio = datetime.now(timezone.utc) - timedelta(hours=6)
    for minuto in (0, 4, 9, 13):  # la pasada recorriendo tienda por tienda
        await _corrida(db_conn, inicio + timedelta(minutes=minuto), 2500)

    assert await db_module.volumen_por_pasada(db_conn, limite=10) == [(inicio, 10000)]


@pytest.mark.asyncio
async def test_el_hueco_de_12_h_separa_dos_pasadas(db_conn):
    anterior = datetime.now(timezone.utc) - timedelta(hours=18)
    actual = datetime.now(timezone.utc) - timedelta(hours=6)
    for minuto in (0, 13):
        await _corrida(db_conn, anterior + timedelta(minutes=minuto), 5000)
        await _corrida(db_conn, actual + timedelta(minutes=minuto), 700)

    assert await db_module.volumen_por_pasada(db_conn, limite=10) == [
        (actual, 1400),
        (anterior, 10000),
    ]


@pytest.mark.asyncio
async def test_se_suma_items_ok_y_no_items_seen(db_conn):
    """Lo que la guarda vigila es cuánta serie entró.

    Un target que enumera 900 productos y no persiste ninguno es exactamente el
    agujero que hay que ver, y en `items_seen` no se nota.
    """
    inicio = datetime.now(timezone.utc) - timedelta(hours=3)
    store_id = await db_conn.fetchval("SELECT id FROM stores WHERE slug = 'falabella'")
    await db_conn.execute(
        """INSERT INTO scrape_runs (store_id, started_at, finished_at, status,
                                    items_seen, items_ok)
                VALUES ($1, $2, $2, 'ok', 900, 0)""",
        store_id,
        inicio,
    )
    assert await db_module.volumen_por_pasada(db_conn, limite=10) == [(inicio, 0)]


@pytest.mark.asyncio
async def test_una_corrida_fallida_aporta_su_cero(db_conn):
    """A diferencia de `recent_items_seen`, acá las `failed` SÍ cuentan.

    Allá el cero de una corrida que reventó no es un volumen y contaminaría la
    mediana de ese target. Acá es justo al revés: la pasada del 18-sep fue 100 %
    `failed` y su volumen real fue cero. Descartarlas dejaría a la guarda sin
    ver la caída que existe para ver.
    """
    inicio = datetime.now(timezone.utc) - timedelta(hours=3)
    await _corrida(db_conn, inicio, 0, status="failed")
    await _corrida(db_conn, inicio + timedelta(minutes=5), 0, status="failed")

    assert await db_module.volumen_por_pasada(db_conn, limite=10) == [(inicio, 0)]


@pytest.mark.asyncio
async def test_el_limite_devuelve_las_mas_nuevas(db_conn):
    ahora = datetime.now(timezone.utc)
    for i in range(5):
        await _corrida(db_conn, ahora - timedelta(hours=12 * i), 1000 * (i + 1))

    volumenes = await db_module.volumen_por_pasada(db_conn, limite=2)
    assert [obs for _, obs in volumenes] == [1000, 2000]


@pytest.mark.asyncio
async def test_sin_corridas_no_hay_volumen(db_conn):
    assert await db_module.volumen_por_pasada(db_conn, limite=10) == []


@pytest.mark.asyncio
async def test_la_consulta_y_la_logica_encajan(db_conn):
    """El contrato entre las dos mitades: orden y forma de la tupla.

    Se prueba junto porque el error que nadie ve es el orden invertido: con la
    serie al revés, `pasadas_flacas` compararía cada pasada contra su FUTURO y
    la guarda seguiría pareciendo que anda.
    """
    ahora = datetime.now(timezone.utc)
    # 8 pasadas sanas y la última (la más nueva) a medias, como el 29-sep.
    for i, obs in enumerate([1481, 16509, 16627, 16666, 15384, 20035, 11604, 11508]):
        await _corrida(db_conn, ahora - timedelta(hours=12 * i), obs)

    volumenes = await db_module.volumen_por_pasada(db_conn, limite=21)
    flacas = runner.pasadas_flacas(volumenes)

    assert len(flacas) == 1
    assert flacas[0].observaciones == 1481
