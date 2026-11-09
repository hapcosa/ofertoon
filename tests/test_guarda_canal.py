"""La guarda del canal: ver que el canal ARRANCÓ, no cuánto publicó.

Existe por el incidente del 2026-11-06 —primer post 17:18 UTC contra las 11:00
de todos los días, 6 h 18 min de ventana perdidos, siete servicios `Up` y cero
errores en pantalla— que ninguna de las tres guardas de ingesta podía ver y que
**un chequeo de total diario tampoco habría visto**: ese día terminó con 23
posts, un total sano. Ver `research/2026-11-06/INCIDENTE_canal_mudo.md` y
`research/2026-11-09/GUARDA_canal_mudo.md`.

Los tests puros corren en cualquier máquina. Los de `posts_hoy_y_ayer` y
`revisar_canal_mudo` piden `TEST_DATABASE_URL` apuntando a una base descartable
y si no se saltean.

**El caso de control está en `BACKTEST`**: son los 46 días sanos de la historia
real del canal que la guarda tiene que dejar pasar en silencio. Una alerta que
habla todos los días se mutea la primera semana, y entonces no existe.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal

import pytest

from curation import ranker
from publisher.daemon import revisar_canal_mudo
from publisher.guarda_canal import (
    DEADLINE_HOUR_UTC,
    canal_mudo_hoy,
    posts_hoy_y_ayer,
)

#: El día del incidente, a la hora del deadline por default.
INCIDENTE = datetime(2026, 11, 6, 13, 0, tzinfo=timezone.utc)


# -----------------------------------------------------------------------------
# La condición, pura
# -----------------------------------------------------------------------------


def test_un_dia_sano_no_dispara() -> None:
    """El caso de control. A las 13:00 UTC un día sano lleva 4 posts."""
    assert (
        canal_mudo_hoy(posts_hoy=4, posts_ayer=25, ahora=INCIDENTE) is None
    ), "una alerta que habla los días sanos se mutea y deja de existir"


def test_el_incidente_dispara() -> None:
    texto = canal_mudo_hoy(posts_hoy=0, posts_ayer=25, ahora=INCIDENTE)
    assert texto is not None
    # El mensaje tiene que traer qué hacer, no solo que algo pasó: la mitigación
    # del incidente es una línea y olvidarla cuesta la jornada entera.
    assert "scrapers.runner --once" in texto
    assert "2026-11-06" in texto
    assert "25" in texto


def test_un_solo_post_ya_calla() -> None:
    """La pregunta es si ARRANCÓ. Cuánto publicó es otra guarda, y otra falla."""
    assert canal_mudo_hoy(posts_hoy=1, posts_ayer=25, ahora=INCIDENTE) is None


def test_antes_del_deadline_calla() -> None:
    temprano = INCIDENTE.replace(hour=12)
    assert canal_mudo_hoy(posts_hoy=0, posts_ayer=25, ahora=temprano) is None


def test_fuera_de_la_ventana_calla() -> None:
    """23:30 de Santiago: la ventana cerró, el deadline pasó, no hay qué pedir.

    El instante es 02:30 UTC del día siguiente a propósito: con la ventana
    cerrando a las 23:00 de Santiago (02:00 UTC), este es el único momento en que
    el deadline ya pasó y la ventana ya cerró. Si la guarda mirara la fecha UTC
    en vez del día de Santiago, acá se confundiría de día.
    """
    cerrada = datetime(2026, 11, 7, 2, 30, tzinfo=timezone.utc)
    assert not ranker.within_window(cerrada)
    assert canal_mudo_hoy(posts_hoy=0, posts_ayer=25, ahora=cerrada) is None


def test_la_cola_de_la_ventana_es_el_dia_de_santiago() -> None:
    """A las 22:00 de Santiago del 6-nov son las 01:00 UTC del 7, y el día es el 6.

    Agrupar por fecha UTC partiría las últimas tres horas de cada jornada en un
    día nuevo, y la guarda nombraría el día equivocado en el aviso.
    """
    cola = datetime(2026, 11, 7, 1, 0, tzinfo=timezone.utc)
    texto = canal_mudo_hoy(posts_hoy=0, posts_ayer=25, ahora=cola)
    assert texto is not None
    assert "2026-11-06" in texto and "2026-11-07" not in texto


def test_si_ayer_tampoco_publico_no_es_una_caida_nueva() -> None:
    """Dos ceros seguidos son un canal que ya viene mudo: avisó ayer."""
    assert canal_mudo_hoy(posts_hoy=0, posts_ayer=0, ahora=INCIDENTE) is None


def test_el_deadline_es_un_parametro() -> None:
    """Mismo minuto, dos umbrales: el default calla y el de las 12 dispara.

    Es la decisión que el dueño tiene abierta, y está acá como test para que
    cambiarla sea una variable y no un rediseño.
    """
    media_manana = datetime(2026, 11, 6, 12, 30, tzinfo=timezone.utc)
    assert DEADLINE_HOUR_UTC == 13
    assert canal_mudo_hoy(posts_hoy=0, posts_ayer=25, ahora=media_manana) is None
    assert (
        canal_mudo_hoy(
            posts_hoy=0, posts_ayer=25, ahora=media_manana, deadline_hour_utc=12
        )
        is not None
    )


# -----------------------------------------------------------------------------
# El backtest: la historia real del canal, día por día
# -----------------------------------------------------------------------------

#: `(día de Santiago, total, publicados <12:00 UTC, publicados <13:00 UTC,
#: total de ayer)`. Medido contra `deal_posts` de producción el 2026-11-09:
#: toda la historia del canal, del primer post (2026-09-21) al último día
#: cerrado (2026-11-08). Los días sin una sola fila están incluidos a propósito
#: —son los que la guarda existe para ver— y por eso el rango es continuo.
#: ⚠️ El rango cruza un cambio de ventana: `WINDOW_START_HOUR` era 9 hasta el
#: 2026-10-21 y es 8 desde el 22, así que el primer post se mueve de 12:0x UTC a
#: 11:0x UTC a mitad de la tabla. No es ruido: es la mitad del backtest que el
#: umbral tiene que aguantar.
BACKTEST: tuple[tuple[str, int, int, int, int], ...] = (
    ("2026-09-21", 6, 0, 0, 0),
    ("2026-09-22", 6, 0, 2, 6),
    ("2026-09-23", 6, 0, 2, 6),
    ("2026-09-24", 6, 0, 2, 6),
    ("2026-09-25", 6, 0, 2, 6),
    ("2026-09-26", 6, 0, 2, 6),
    ("2026-09-27", 6, 0, 2, 6),
    ("2026-09-28", 6, 0, 2, 6),
    ("2026-09-29", 6, 0, 0, 6),
    ("2026-09-30", 6, 0, 2, 6),
    ("2026-10-01", 6, 0, 2, 6),
    ("2026-10-02", 6, 0, 2, 6),
    ("2026-10-03", 6, 0, 2, 6),
    ("2026-10-04", 6, 0, 2, 6),
    ("2026-10-05", 6, 0, 2, 6),
    ("2026-10-06", 6, 0, 2, 6),
    ("2026-10-07", 6, 0, 2, 6),
    ("2026-10-08", 6, 0, 2, 6),
    ("2026-10-09", 6, 0, 2, 6),
    ("2026-10-10", 6, 0, 2, 6),
    ("2026-10-11", 6, 0, 2, 6),
    ("2026-10-12", 6, 0, 2, 6),
    ("2026-10-13", 6, 0, 2, 6),
    ("2026-10-14", 0, 0, 0, 6),
    ("2026-10-15", 0, 0, 0, 0),
    ("2026-10-16", 0, 0, 0, 0),
    ("2026-10-17", 0, 0, 0, 0),
    ("2026-10-18", 0, 0, 0, 0),
    ("2026-10-19", 8, 0, 0, 0),
    ("2026-10-20", 14, 0, 2, 8),
    ("2026-10-21", 25, 0, 2, 14),
    ("2026-10-22", 26, 2, 4, 25),
    ("2026-10-23", 25, 2, 4, 26),
    ("2026-10-24", 23, 2, 4, 25),
    ("2026-10-25", 23, 2, 4, 23),
    ("2026-10-26", 24, 2, 4, 23),
    ("2026-10-27", 19, 2, 4, 24),
    ("2026-10-28", 21, 2, 4, 19),
    ("2026-10-29", 23, 2, 4, 21),
    ("2026-10-30", 24, 2, 4, 23),
    ("2026-10-31", 21, 2, 4, 24),
    ("2026-11-01", 22, 2, 4, 21),
    ("2026-11-02", 25, 2, 4, 22),
    ("2026-11-03", 25, 2, 4, 25),
    ("2026-11-04", 34, 2, 4, 25),
    ("2026-11-05", 25, 10, 17, 34),
    ("2026-11-06", 23, 0, 0, 25),
    ("2026-11-07", 22, 10, 17, 23),
    ("2026-11-08", 23, 11, 17, 22),
)

#: Los tres días en que la guarda tiene que hablar, con el default de las 13:00.
#: Los tres están diagnosticados y ninguno es una sospecha:
#:   29-sep — la pasada a medias de `tests/test_guarda_volumen.py`; el canal
#:            arrancó 15:44 UTC.
#:   14-oct — primer día de un apagón de cinco: cero `scrape_runs` del 14 al 18.
#:   06-nov — el incidente del canal mudo; arrancó 17:18 UTC.
DISPARA_CON_13 = {date(2026, 9, 29), date(2026, 10, 14), date(2026, 11, 6)}


def _veredictos(deadline: int) -> set[date]:
    disparos = set()
    for iso, _total, h12, h13, ayer in BACKTEST:
        dia = date.fromisoformat(iso)
        instante = datetime.combine(dia, time(hour=deadline), tzinfo=timezone.utc)
        if canal_mudo_hoy(
            posts_hoy=h12 if deadline == 12 else h13,
            posts_ayer=ayer,
            ahora=instante,
            deadline_hour_utc=deadline,
        ):
            disparos.add(dia)
    return disparos


def test_backtest_el_default_dispara_solo_en_los_tres_dias_malos() -> None:
    assert _veredictos(DEADLINE_HOUR_UTC) == DISPARA_CON_13


def test_backtest_los_46_dias_sanos_callan() -> None:
    """El caso de control, explícito: 46 de 49 días en silencio."""
    sanos = {date.fromisoformat(d[0]) for d in BACKTEST} - DISPARA_CON_13
    assert len(sanos) == 46
    assert _veredictos(DEADLINE_HOUR_UTC) & sanos == set()


def test_backtest_el_deadline_de_las_12_no_sobrevive_un_cambio_de_ventana() -> None:
    """Por qué el default NO son las 12:00 UTC, medido y no argumentado.

    `WINDOW_START_HOUR` era **9** hasta el commit `7fef769` (2026-10-21): la
    ventana abría 12:00 UTC y el primer post salía 12:00-12:04. O sea el
    deadline de las 12 caía *antes* de que el canal pudiera publicar, y habría
    disparado en falso **23 días seguidos** — una alerta así se mutea la primera
    semana, que es peor que no tenerla.

    Es la corrección del backtest anterior
    (`research/2026-11-07/GUARDA_canal_mudo_propuesta.md`): medía 12 días, todos
    posteriores a ese cambio, y por eso daba cero falsos positivos para las
    12:00. La lección general es más grande que este umbral: **un deadline en
    hora UTC absoluta solo vale para la ventana que lo produjo**, y la ventana
    se movió una vez por código y se va a mover otra por horario de verano
    (Santiago pasa a UTC-4 el 2027-04-04, y ahí 08:00 local son las 12:00 UTC).
    """
    disparos = _veredictos(12)
    falsos = disparos - DISPARA_CON_13
    assert len(falsos) == 23
    assert date(2026, 9, 22) in falsos, "primer día sano con la ventana vieja"
    assert date(2026, 10, 21) in falsos, "último día con la ventana abriendo 09:00"
    assert disparos > DISPARA_CON_13, "y encima sigue viendo los tres días malos"


def test_el_volumen_diario_no_mueve_la_condicion() -> None:
    """La cuota pasó de 6 a 33 a 160 y la guarda mira lo mismo: el primer post.

    `test_backtest_*` ya cubre 6/día (sep-oct) y 22-34/día (nov) con el mismo
    umbral, así que el re-backtest contra días de cuota 160 no puede cambiar el
    veredicto de un día sano: el día más cargado de la historia (34 posts, el
    4-nov) y el más flaco (6) dan la misma cuenta a las 13:00 UTC. Lo que la
    cuota mueve es el total del día, que esta guarda no mira.
    """
    for total in (6, 33, 160):
        assert canal_mudo_hoy(posts_hoy=1, posts_ayer=total, ahora=INCIDENTE) is None
        assert canal_mudo_hoy(posts_hoy=0, posts_ayer=total, ahora=INCIDENTE)


# -----------------------------------------------------------------------------
# La query y el cableado, contra Postgres
# -----------------------------------------------------------------------------

async def _tier(conn) -> int:
    """El tier al que se publica. `deal_posts.tier_id` tiene FK desde la 16."""
    return await conn.fetchval(
        """
        INSERT INTO telegram_tiers (name, slug, telegram_channel_id, is_active)
             VALUES ('Ofertoon VIP', 'vip', -1002812345678, TRUE)
        ON CONFLICT (slug) DO UPDATE SET name = EXCLUDED.name
          RETURNING id
        """
    )


async def _seed_post(
    conn, *, posted_at: datetime, sku: str, message_id: int | None
) -> None:
    """Un post publicado (o una reserva en vuelo, con `message_id=None`)."""
    tier_id = await _tier(conn)
    store_id = await conn.fetchval("SELECT id FROM stores WHERE slug = 'falabella'")
    category_id = await conn.fetchval(
        "SELECT id FROM categories WHERE slug = 'tecno-notebooks'"
    )
    listing_id = await conn.fetchval(
        """
        INSERT INTO listings (store_id, category_id, store_sku, url, name_raw)
             VALUES ($1, $2, $3, $4, $5) RETURNING id
        """,
        store_id,
        category_id,
        sku,
        f"https://falabella.com/p/{sku}",
        f"Producto {sku}",
    )
    candidate_id = await conn.fetchval(
        """
        INSERT INTO deal_candidates
               (listing_id, price, p50_60d, discount_real, score, verdict, detected_at)
             VALUES ($1, 300000, 500000, 0.40, $2, 'accepted', $3) RETURNING id
        """,
        listing_id,
        Decimal("30.0"),
        posted_at - timedelta(hours=1),
    )
    await conn.execute(
        """
        INSERT INTO deal_posts (candidate_id, tier_id, telegram_message_id, posted_at)
             VALUES ($1, $2, $3, $4)
        """,
        candidate_id,
        tier_id,
        message_id,
        posted_at,
    )


@pytest.mark.asyncio
async def test_posts_hoy_y_ayer_cuenta_por_dia_de_santiago(db_conn) -> None:
    ahora = datetime(2026, 11, 6, 13, 0, tzinfo=timezone.utc)
    # 11-05 23:30 de Santiago = 11-06 02:30 UTC: es AYER en Santiago y HOY en UTC.
    await _seed_post(
        db_conn,
        posted_at=datetime(2026, 11, 6, 2, 30, tzinfo=timezone.utc),
        sku="COLA-DE-AYER",
        message_id=900,
    )
    await _seed_post(
        db_conn,
        posted_at=datetime(2026, 11, 6, 11, 0, tzinfo=timezone.utc),
        sku="DE-HOY",
        message_id=901,
    )
    # Anteayer: fuera de los dos días, no tiene que contar en ninguno.
    await _seed_post(
        db_conn,
        posted_at=datetime(2026, 11, 4, 14, 0, tzinfo=timezone.utc),
        sku="ANTEAYER",
        message_id=902,
    )

    hoy, ayer = await posts_hoy_y_ayer(db_conn, ahora=ahora)
    assert (hoy, ayer) == (1, 1)


@pytest.mark.asyncio
async def test_una_reserva_en_vuelo_no_cuenta_como_post(db_conn) -> None:
    """Sin `telegram_message_id` nadie vio ese mensaje: el canal sigue mudo.

    Es el falso negativo que importa — `poster._reserve` inserta la fila ANTES de
    hablarle a Telegram y la borra si el envío falla, así que contarla haría que
    la guarda se calle justo el día en que todos los envíos fallan.
    """
    ahora = datetime(2026, 11, 6, 13, 0, tzinfo=timezone.utc)
    await _seed_post(
        db_conn,
        posted_at=datetime(2026, 11, 6, 11, 0, tzinfo=timezone.utc),
        sku="RESERVA",
        message_id=None,
    )
    hoy, _ayer = await posts_hoy_y_ayer(db_conn, ahora=ahora)
    assert hoy == 0


@pytest.mark.asyncio
async def test_revisar_canal_mudo_avisa_una_vez_por_dia(
    telegram_pool, db_conn, monkeypatch
) -> None:
    """La condición queda prendida 10 h; sin memoria serían ~120 mensajes."""
    enviados: list[str] = []

    async def fake_send(text):
        enviados.append(text)
        return True

    monkeypatch.setattr("publisher.daemon.send_alert", fake_send)

    ahora = datetime(2026, 11, 6, 13, 0, tzinfo=timezone.utc)
    await _seed_post(
        db_conn,
        posted_at=datetime(2026, 11, 5, 14, 0, tzinfo=timezone.utc),
        sku="AYER-SI",
        message_id=910,
    )

    avisado = await revisar_canal_mudo(telegram_pool, now=ahora)
    assert avisado == date(2026, 11, 6)
    assert len(enviados) == 1

    # Media hora después, mismo día mudo: la condición sigue prendida.
    otra = await revisar_canal_mudo(
        telegram_pool, now=ahora + timedelta(minutes=30), ya_avisado=avisado
    )
    assert otra == date(2026, 11, 6)
    assert len(enviados) == 1, "un aviso por día; el resto es ruido que se mutea"


@pytest.mark.asyncio
async def test_revisar_canal_mudo_calla_el_dia_sano(
    telegram_pool, db_conn, monkeypatch
) -> None:
    """El control del cableado: con el primer post publicado, nadie habla."""
    enviados: list[str] = []

    async def fake_send(text):
        enviados.append(text)
        return True

    monkeypatch.setattr("publisher.daemon.send_alert", fake_send)

    ahora = datetime(2026, 11, 6, 13, 0, tzinfo=timezone.utc)
    await _seed_post(
        db_conn,
        posted_at=datetime(2026, 11, 5, 14, 0, tzinfo=timezone.utc),
        sku="AYER-SANO",
        message_id=920,
    )
    await _seed_post(
        db_conn,
        posted_at=datetime(2026, 11, 6, 11, 0, tzinfo=timezone.utc),
        sku="HOY-SANO",
        message_id=921,
    )

    assert await revisar_canal_mudo(telegram_pool, now=ahora) is None
    assert enviados == []


# -----------------------------------------------------------------------------
# El default apagado, probado en el loop de verdad
# -----------------------------------------------------------------------------
#
# Es el único lugar donde se puede ver que la guarda NO corre sola. Los tests de
# `revisar_canal_mudo` la llaman a mano, así que no dicen nada sobre si el daemon
# la invoca cuando nadie la prendió — y "apagado por default" es media feature:
# lo que habla hacia afuera no se prende con un despliegue (regla 8).
#
# Lo que se afirma es si el daemon **llama** a la guarda, no si esa llamada
# termina en aviso: el aviso depende de la hora real y la suite corre a cualquier
# hora. El umbral y el mensaje ya están cubiertos arriba con un `now` explícito;
# acá lo único bajo prueba es el interruptor.


async def _corrida_del_daemon(monkeypatch, *, flag: str | None) -> int:
    """Una vuelta de `daemon.run`. Devuelve cuántas veces corrió la guarda."""
    from publisher import daemon

    llamadas = 0
    real = daemon.revisar_canal_mudo

    async def spy(pool, **kwargs):
        nonlocal llamadas
        llamadas += 1
        return await real(pool, **kwargs)

    monkeypatch.setattr("publisher.daemon.revisar_canal_mudo", spy)
    monkeypatch.setenv("PUBLISHER_ENABLED", "true")
    if flag is None:
        monkeypatch.delenv("PUBLISHER_ALERTA_CANAL_MUDO", raising=False)
    else:
        monkeypatch.setenv("PUBLISHER_ALERTA_CANAL_MUDO", flag)

    await daemon.run(once=True)
    return llamadas


# `db_conn` no se usa: está para que estos dos se SALTEEN sin `TEST_DATABASE_URL`
# en vez de fallar. `daemon.run` abre su propio pool desde `DATABASE_URL`, que el
# conftest apunta a la base de test, así que sin DB no hay nada que correr — y la
# suite pura tiene que seguir verde en una máquina sin Docker.


@pytest.mark.asyncio
async def test_el_daemon_no_corre_la_guarda_si_nadie_la_prendio(
    db_conn, monkeypatch
) -> None:
    assert await _corrida_del_daemon(monkeypatch, flag=None) == 0


@pytest.mark.asyncio
async def test_el_daemon_corre_la_guarda_con_el_flag_prendido(
    db_conn, monkeypatch
) -> None:
    """El caso de control del test anterior.

    Sin este par, el 0 de arriba podría venir de que el loop ni siquiera llega a
    la guarda por cualquier otro motivo.
    """
    assert await _corrida_del_daemon(monkeypatch, flag="true") == 1
