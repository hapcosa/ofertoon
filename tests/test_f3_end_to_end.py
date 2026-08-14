"""F3 completo contra Postgres: ingesta simulada → detector → cuota → canal.

Este archivo existe por una restricción concreta: la base arrancó el 2026-08-03
y `pricing/baselines.py` exige 30 días calendario distintos, así que hasta
~2026-09-02 el detector rechaza el 100% del catálogo por `history` y el
resultado correcto en producción es **cero publicaciones**. No se puede validar
F3 corriéndolo y mirando el canal: una tabla vacía y un job que nunca corrió son
indistinguibles desde afuera.

Acá se siembra la historia que la realidad todavía no tiene —60 días de serie
sintética con un pozo real y con un escalón inflado— y se corre el pipeline
entero. Es la única prueba disponible hoy de que las tres piezas se hablan.

Necesita `TEST_DATABASE_URL` apuntando a una base descartable; sin ella se
saltea (y la suite igual da verde, que es la trampa que documenta el HANDOFF).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from curation import ranker
from publisher import poster
from publisher.poster import Tier

pytestmark = pytest.mark.asyncio

#: Ancla de la serie sintética. Todo se cuenta hacia atrás desde acá.
#:
#: Es el día en que corre la suite, NO una fecha fija: el detector descarta las
#: observaciones de más de `PRICE_MAX_AGE_HOURS` (26 h) contra el reloj del
#: servidor, así que una serie anclada a una fecha absoluta deja de evaluarse a
#: los dos días y estos tests se apagan solos sin que nadie toque el código. Ya
#: pasó: escritos el 2026-08-04, el 2026-08-06 fallaban 12 de 17.
#:
#: La hora sí es fija (15:00 UTC) para que `PUBLISH_AT` caiga siempre dentro de
#: la ventana del ranker. Que la ancla quede unas horas en el futuro cuando la
#: suite corre de madrugada no molesta: el filtro de edad solo mira hacia atrás.
NOW = datetime.now(timezone.utc).replace(hour=15, minute=0, second=0, microsecond=0)
#: Un mediodía de Santiago (16:00 UTC es 12:00 con UTC−4, 13:00 con UTC−3):
#: dentro de la ventana de publicación y lejos de los bordes del día calendario
#: local en cualquier época del año.
PUBLISH_AT = NOW + timedelta(hours=1)

PRECIO_NORMAL = Decimal("500000")
PRECIO_OFERTA = Decimal("300000")  # −40% contra el p50


class FakeTelegram:
    """Registra los envíos en vez de hablar con Telegram.

    Imita el contrato defensivo del cliente real: devuelve `None` ante fallo en
    vez de lanzar, que es lo que el poster espera para liberar la reserva.
    """

    def __init__(self, *, fail: bool = False) -> None:
        self.sent: list[dict] = []
        self.fail = fail
        self._next_id = 1000

    async def send_message(
        self, chat_id, text, parse_mode=None, *, disable_web_page_preview=True
    ):
        if self.fail:
            return None
        self._next_id += 1
        self.sent.append(
            {
                "chat_id": chat_id,
                "text": text,
                "parse_mode": parse_mode,
                "preview": not disable_web_page_preview,
            }
        )
        return self._next_id


async def _seed_catalog(conn) -> tuple[int, int]:
    """Una tienda, un canal y el ruteo canal↔categoría. Devuelve (tier_id, store_id).

    `categories` y `stores` los siembran las migraciones y el fixture no los
    trunca, así que se reusan tal cual: `tecno-notebooks` con θ=0.15.
    """
    store_id = await conn.fetchval("SELECT id FROM stores WHERE slug = 'falabella'")
    category_id = await conn.fetchval(
        "SELECT id FROM categories WHERE slug = 'tecno-notebooks'"
    )
    assert category_id is not None
    tier_id = await conn.fetchval(
        """
        INSERT INTO telegram_tiers (name, slug, telegram_channel_id, is_active)
             VALUES ('Ofertoon VIP', 'vip', -1003914468578, TRUE)
          RETURNING id
        """
    )
    # Las 7 categorías al canal único, igual que la migración 12.
    await conn.execute(
        """
        INSERT INTO telegram_tier_categories (tier_id, category_id)
        SELECT $1, id FROM categories
        """,
        tier_id,
    )
    return tier_id, store_id


async def _ensure_partitions(conn, serie: list[tuple[datetime, Decimal]]) -> None:
    """Particiones mensuales para el rango de la serie sintética.

    `ensure_price_partitions()` de la migración 01 solo crea del mes en curso
    hacia adelante, que es lo correcto para producción: la ingesta nunca escribe
    hacia atrás. Un backtest sintético sí, y sin esto el INSERT falla con
    "no partition of relation price_points found for row".
    """
    meses = {(at.year, at.month) for at, _ in serie}
    for year, month in sorted(meses):
        desde = datetime(year, month, 1, tzinfo=timezone.utc)
        hasta = datetime(year + (month == 12), month % 12 + 1, 1, tzinfo=timezone.utc)
        await conn.execute(
            f"""
            CREATE TABLE IF NOT EXISTS price_points_{year}{month:02d}
                PARTITION OF price_points
                FOR VALUES FROM ('{desde:%Y-%m-%d}') TO ('{hasta:%Y-%m-%d}')
            """
        )


async def _seed_listing(
    conn,
    *,
    store_id: int,
    sku: str,
    name: str,
    serie: list[tuple[datetime, Decimal]],
    category_slug: str = "tecno-notebooks",
) -> int:
    """Un listing con su serie de precios. Todas las observaciones con stock."""
    await _ensure_partitions(conn, serie)
    category_id = await conn.fetchval(
        "SELECT id FROM categories WHERE slug = $1", category_slug
    )
    listing_id = await conn.fetchval(
        """
        INSERT INTO listings (store_id, category_id, store_sku, url, name_raw)
             VALUES ($1, $2, $3, $4, $5)
          RETURNING id
        """,
        store_id,
        category_id,
        sku,
        f"https://falabella.com/p/{sku}",
        name,
    )
    await conn.executemany(
        """
        INSERT INTO price_points (listing_id, observed_at, price_effective, in_stock)
             VALUES ($1, $2, $3, TRUE)
        """,
        [(listing_id, at, price) for at, price in serie],
    )
    return listing_id


def serie_con_pozo(*, dias: int = 60) -> list[tuple[datetime, Decimal]]:
    """Precio estable 60 días y una bajada real hoy. Esto SÍ es una oferta."""
    puntos = [
        (NOW - timedelta(days=d), PRECIO_NORMAL) for d in range(dias, 0, -1)
    ]
    puntos.append((NOW, PRECIO_OFERTA))
    return puntos


def serie_inflada(*, dias: int = 60) -> list[tuple[datetime, Decimal]]:
    """El patrón que el detector existe para rechazar.

    El precio sube 20% sobre el p50 y se sostiene tres semanas; recién después
    llega el "descuento", que deja el precio apenas debajo del original. La
    tienda declararía −33%; contra la serie real no es una oferta.
    """
    puntos = [
        (NOW - timedelta(days=d), PRECIO_NORMAL) for d in range(dias, 21, -1)
    ]
    inflado = PRECIO_NORMAL * Decimal("1.20")
    puntos += [(NOW - timedelta(days=d), inflado) for d in range(21, 0, -1)]
    puntos.append((NOW, PRECIO_OFERTA))
    return puntos


# -----------------------------------------------------------------------------
# El pipeline: baselines + detector
# -----------------------------------------------------------------------------


async def test_pipeline_acepta_el_pozo_real(db_conn, telegram_pool) -> None:
    from pricing.pipeline import run as run_pipeline

    _, store_id = await _seed_catalog(db_conn)
    listing_id = await _seed_listing(
        db_conn,
        store_id=store_id,
        sku="REAL-1",
        name="Notebook con bajada real",
        serie=serie_con_pozo(),
    )

    stats = await run_pipeline(telegram_pool)

    assert stats.baselines.written == 1
    assert stats.baselines.publishable == 1, "60 días de serie deberían alcanzar"
    assert stats.detector.accepted == 1

    row = await db_conn.fetchrow(
        "SELECT * FROM deal_candidates WHERE listing_id = $1", listing_id
    )
    assert row["verdict"] == "accepted"
    assert row["reject_reason"] is None
    assert row["price"] == PRECIO_OFERTA
    assert row["discount_real"] == Decimal("0.4000")


async def test_pipeline_rechaza_el_precio_inflado(db_conn, telegram_pool) -> None:
    """La guarda anti-rampa: la razón de ser del proyecto, verificada de punta a punta."""
    from pricing.pipeline import run as run_pipeline

    _, store_id = await _seed_catalog(db_conn)
    listing_id = await _seed_listing(
        db_conn,
        store_id=store_id,
        sku="FAKE-1",
        name="Notebook inflado antes de descontar",
        serie=serie_inflada(),
    )

    stats = await run_pipeline(telegram_pool)

    assert stats.detector.accepted == 0
    row = await db_conn.fetchrow(
        "SELECT * FROM deal_candidates WHERE listing_id = $1", listing_id
    )
    assert row["verdict"] == "rejected"
    assert row["reject_reason"] == "ramp"


async def test_el_cold_start_rechaza_por_history_y_no_deja_fila(
    db_conn, telegram_pool
) -> None:
    """El estado de producción HOY, hecho explícito.

    Con dos días de historia todo se rechaza por `history`, y esos rechazos no
    se persisten. Este test fija la consecuencia operativa: `deal_candidates`
    vacía NO prueba que el job no corrió — hay que mirar las stats.
    """
    from pricing.pipeline import run as run_pipeline

    _, store_id = await _seed_catalog(db_conn)
    await _seed_listing(
        db_conn,
        store_id=store_id,
        sku="JOVEN-1",
        name="Listing recién nacido",
        serie=serie_con_pozo(dias=2),
    )

    stats = await run_pipeline(telegram_pool)

    assert stats.detector.rejected_by == {"history": 1}
    assert stats.detector.accepted == 0
    assert await db_conn.fetchval("SELECT count(*) FROM deal_candidates") == 0


async def test_el_pipeline_es_idempotente(db_conn, telegram_pool) -> None:
    """Correrlo dos veces sobre la misma observación no duplica candidatos.

    Sin la migración 14 (`detected_at` = `observed_at` + UNIQUE) cada corrida
    insertaba una fila nueva, y el job programado iba a llenar la tabla de
    copias que además habrían inflado la cuota del ranker.
    """
    from pricing.pipeline import run as run_pipeline

    _, store_id = await _seed_catalog(db_conn)
    await _seed_listing(
        db_conn,
        store_id=store_id,
        sku="REAL-1",
        name="Notebook con bajada real",
        serie=serie_con_pozo(),
    )

    primera = await run_pipeline(telegram_pool)
    segunda = await run_pipeline(telegram_pool)

    assert primera.detector.accepted == 1
    assert segunda.detector.evaluated == 0, "la observación ya estaba decidida"
    assert await db_conn.fetchval("SELECT count(*) FROM deal_candidates") == 1


async def test_detected_at_es_la_hora_de_la_observacion(db_conn, telegram_pool) -> None:
    from pricing.pipeline import run as run_pipeline

    _, store_id = await _seed_catalog(db_conn)
    listing_id = await _seed_listing(
        db_conn,
        store_id=store_id,
        sku="REAL-1",
        name="Notebook",
        serie=serie_con_pozo(),
    )
    await run_pipeline(telegram_pool)

    detected_at = await db_conn.fetchval(
        "SELECT detected_at FROM deal_candidates WHERE listing_id = $1", listing_id
    )
    assert detected_at == NOW


async def test_observacion_vieja_no_se_evalua(db_conn, telegram_pool) -> None:
    """Un listing que dejó de aparecer en el catálogo no se publica para siempre.

    Sin el filtro de edad, su último `price_point` se re-evaluaba en cada
    corrida como si fuera el precio de hoy.
    """
    from pricing.pipeline import run as run_pipeline

    _, store_id = await _seed_catalog(db_conn)
    vieja = [
        (at - timedelta(days=40), price) for at, price in serie_con_pozo()
    ]
    await _seed_listing(
        db_conn, store_id=store_id, sku="MUERTO-1", name="Descatalogado", serie=vieja
    )

    stats = await run_pipeline(telegram_pool)

    # La baseline se escribe igual (parte de la serie sigue dentro de la ventana
    # de 60 días), pero el detector no llega a evaluarla: su observación más
    # reciente tiene 40 días y el filtro de edad la descarta antes.
    assert stats.baselines.written == 1
    assert stats.detector.evaluated == 0


# -----------------------------------------------------------------------------
# El publisher: cuota + posteo + deal_posts
# -----------------------------------------------------------------------------


async def test_publica_el_aceptado_y_registra_el_post(db_conn, telegram_pool) -> None:
    from pricing.pipeline import run as run_pipeline

    tier_id, store_id = await _seed_catalog(db_conn)
    listing_id = await _seed_listing(
        db_conn,
        store_id=store_id,
        sku="REAL-1",
        name="Notebook con bajada real",
        serie=serie_con_pozo(),
    )
    await run_pipeline(telegram_pool)

    fake = FakeTelegram()
    stats = await poster.run_once(telegram_pool, fake, now=PUBLISH_AT)

    assert stats.published == 1
    assert len(fake.sent) == 1

    enviado = fake.sent[0]
    assert enviado["chat_id"] == -1003914468578
    assert enviado["parse_mode"] == "HTML"
    assert enviado["preview"] is True, "la card del link es la foto del producto"
    assert "−40%" in enviado["text"]
    assert "antes real <s>$500.000</s>" in enviado["text"]

    post = await db_conn.fetchrow(
        """
        SELECT dp.*, dc.listing_id
          FROM deal_posts AS dp
          JOIN deal_candidates AS dc ON dc.id = dp.candidate_id
         WHERE dp.tier_id = $1
        """,
        tier_id,
    )
    assert post["listing_id"] == listing_id
    assert post["telegram_message_id"] == 1001


async def test_no_publica_dos_veces_el_mismo_candidato(db_conn, telegram_pool) -> None:
    """El UNIQUE(candidate_id, tier_id) es la defensa que no se puede deshacer."""
    from pricing.pipeline import run as run_pipeline

    tier_id, store_id = await _seed_catalog(db_conn)
    await _seed_listing(
        db_conn,
        store_id=store_id,
        sku="REAL-1",
        name="Notebook",
        serie=serie_con_pozo(),
    )
    await run_pipeline(telegram_pool)

    fake = FakeTelegram()
    await poster.run_once(telegram_pool, fake, now=PUBLISH_AT)
    # Segunda vuelta pasado el espaciado mínimo: el candidato ya está publicado,
    # así que el ranker no lo devuelve y no hay nada que postear.
    await poster.run_once(
        telegram_pool,
        fake,
        now=PUBLISH_AT + timedelta(minutes=ranker.MIN_MINUTES_BETWEEN + 5),
    )

    assert len(fake.sent) == 1
    assert await db_conn.fetchval("SELECT count(*) FROM deal_posts") == 1


async def test_un_envio_fallido_libera_la_reserva_para_reintentar(
    db_conn, telegram_pool
) -> None:
    """Fallar publicando no puede quemar el candidato."""
    from pricing.pipeline import run as run_pipeline

    _, store_id = await _seed_catalog(db_conn)
    await _seed_listing(
        db_conn,
        store_id=store_id,
        sku="REAL-1",
        name="Notebook",
        serie=serie_con_pozo(),
    )
    await run_pipeline(telegram_pool)

    roto = FakeTelegram(fail=True)
    stats = await poster.run_once(telegram_pool, roto, now=PUBLISH_AT)
    assert stats.failed == 1
    assert await db_conn.fetchval("SELECT count(*) FROM deal_posts") == 0

    sano = FakeTelegram()
    stats = await poster.run_once(telegram_pool, sano, now=PUBLISH_AT)
    assert stats.published == 1
    assert await db_conn.fetchval("SELECT count(*) FROM deal_posts") == 1


async def test_respeta_la_cuota_diaria(db_conn, telegram_pool) -> None:
    """Aunque haya doce aceptados, el canal no publica más de MAX_PER_DAY.

    Se varían tienda Y categoría para que los topes finos (2 por cada una) no
    corten antes que el diario, que es lo que este test mide. Con seis tiendas
    y siete categorías el techo de 6/día es el primero en activarse.
    """
    from pricing.pipeline import run as run_pipeline

    tier_id, _ = await _seed_catalog(db_conn)
    stores = await db_conn.fetch("SELECT id FROM stores ORDER BY id")
    slugs = [r["slug"] for r in await db_conn.fetch("SELECT slug FROM categories")]
    for i in range(12):
        await _seed_listing(
            db_conn,
            store_id=stores[i % len(stores)]["id"],
            sku=f"REAL-{i}",
            name=f"Notebook {i}",
            serie=serie_con_pozo(),
            category_slug=slugs[i % len(slugs)],
        )
    await run_pipeline(telegram_pool)

    fake = FakeTelegram()
    momento = PUBLISH_AT
    for _ in range(12):
        await poster.run_once(telegram_pool, fake, now=momento)
        momento += timedelta(minutes=ranker.MIN_MINUTES_BETWEEN + 1)

    publicados = await db_conn.fetchval(
        "SELECT count(*) FROM deal_posts WHERE tier_id = $1", tier_id
    )
    assert publicados == ranker.MAX_PER_DAY
    assert len(fake.sent) == ranker.MAX_PER_DAY


async def test_no_publica_fuera_de_la_ventana_horaria(db_conn, telegram_pool) -> None:
    from pricing.pipeline import run as run_pipeline

    await _seed_catalog(db_conn)
    store_id = await db_conn.fetchval("SELECT id FROM stores WHERE slug='falabella'")
    await _seed_listing(
        db_conn,
        store_id=store_id,
        sku="REAL-1",
        name="Notebook",
        serie=serie_con_pozo(),
    )
    await run_pipeline(telegram_pool)

    # 06:00 UTC = 02:00 en Santiago. Relativo a la ancla, por lo mismo que ella.
    madrugada = NOW.replace(hour=6)
    fake = FakeTelegram()
    stats = await poster.run_once(telegram_pool, fake, now=madrugada)

    assert stats.published == 0
    assert fake.sent == []


async def test_el_tier_inactivo_no_recibe_nada(db_conn, telegram_pool) -> None:
    """`ferre` quedó inactivo en la migración 12 pero conserva sus categorías.

    Sin el filtro `is_active` en `load_active_tiers`, las dos categorías de
    ferretería se publicarían dos veces: una en cada canal.
    """
    tier_id, _ = await _seed_catalog(db_conn)
    await db_conn.execute(
        "UPDATE telegram_tiers SET is_active = FALSE WHERE id = $1", tier_id
    )

    async with telegram_pool.acquire() as conn:
        tiers = await poster.load_active_tiers(conn)
    assert tiers == []


async def test_el_tier_sin_canal_no_recibe_nada(db_conn, telegram_pool) -> None:
    tier_id, _ = await _seed_catalog(db_conn)
    await db_conn.execute(
        "UPDATE telegram_tiers SET telegram_channel_id = NULL WHERE id = $1", tier_id
    )

    async with telegram_pool.acquire() as conn:
        assert await poster.load_active_tiers(conn) == []


async def test_solo_publica_categorias_ruteadas_al_canal(db_conn, telegram_pool) -> None:
    """El ruteo sale de `telegram_tier_categories`, no de "todo lo aceptado"."""
    from pricing.pipeline import run as run_pipeline

    tier_id, store_id = await _seed_catalog(db_conn)
    await db_conn.execute(
        "DELETE FROM telegram_tier_categories WHERE tier_id = $1", tier_id
    )
    await _seed_listing(
        db_conn,
        store_id=store_id,
        sku="REAL-1",
        name="Notebook",
        serie=serie_con_pozo(),
    )
    await run_pipeline(telegram_pool)

    fake = FakeTelegram()
    stats = await poster.run_once(telegram_pool, fake, now=PUBLISH_AT)

    assert await db_conn.fetchval("SELECT count(*) FROM deal_candidates") == 1
    assert stats.published == 0, "aceptado sí, pero sin canal al que ir"


async def test_el_ranker_trae_el_minimo_previo_sin_la_observacion_actual(
    db_conn, telegram_pool
) -> None:
    """`min_prior` excluye la observación evaluada, y por eso significa algo.

    `listing_baselines.min_60d` no sirve para esto: las baselines se recomputan
    ANTES del detector, así que ese mínimo ya incluye el precio de la oferta y
    "el más barato en 60 días" sería cierto para todo aceptado que sea mínimo.
    """
    from pricing.pipeline import run as run_pipeline

    tier_id, store_id = await _seed_catalog(db_conn)
    await _seed_listing(
        db_conn,
        store_id=store_id,
        sku="REAL-1",
        name="Notebook",
        serie=serie_con_pozo(),
    )
    await run_pipeline(telegram_pool)

    async with telegram_pool.acquire() as conn:
        candidates = await ranker.load_candidates(conn, tier_id=tier_id, now=NOW)

    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.min_prior == PRECIO_NORMAL, "el mínimo de ANTES de la oferta"
    assert candidate.price < candidate.min_prior

    min_baseline = await db_conn.fetchval("SELECT min_60d FROM listing_baselines")
    assert min_baseline == PRECIO_OFERTA, "la baseline sí incluye la oferta"


async def test_el_mensaje_publicado_dice_el_mas_barato_en_60_dias(
    db_conn, telegram_pool
) -> None:
    from pricing.pipeline import run as run_pipeline

    _, store_id = await _seed_catalog(db_conn)
    await _seed_listing(
        db_conn,
        store_id=store_id,
        sku="REAL-1",
        name="Notebook",
        serie=serie_con_pozo(),
    )
    await run_pipeline(telegram_pool)

    fake = FakeTelegram()
    await poster.run_once(telegram_pool, fake, now=PUBLISH_AT)

    assert "🏆 El más barato en 60 días" in fake.sent[0]["text"]
