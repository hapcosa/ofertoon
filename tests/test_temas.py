"""Enrutamiento a temas de un grupo-foro: cada rubro a su conversación.

Lo que se prueba acá no es la cuota (eso es `test_ranker.py`, puro) sino el
**ruteo**: que el candidato de ferretería termine en el tema de Ferretería y no
en el de Tecnología. El modo de falla que importa es silencioso —un
`message_thread_id` equivocado publica igual, en el tema de al lado— así que no
alcanza con ver que `published == 1`: hay que mirar a qué thread se mandó.

Necesita `TEST_DATABASE_URL` apuntando a una base descartable; sin ella se saltea.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from curation import ranker
from publisher import poster

pytestmark = pytest.mark.asyncio

CHAT_ID = -1002812345678
#: Un martes a las 13:00 de Santiago: dentro de la ventana de publicación.
NOW = datetime(2026, 8, 4, 13, 0, tzinfo=ranker.TZ)


class FakeTelegram:
    """Registra a qué chat y a qué tema fue cada mensaje."""

    def __init__(self, *, fail: bool = False) -> None:
        self.sent: list[dict] = []
        self.fail = fail
        self._next_id = 2000

    async def send_message(
        self,
        chat_id,
        text,
        parse_mode=None,
        *,
        disable_web_page_preview=True,
        message_thread_id=None,
    ):
        if self.fail:
            return None
        self._next_id += 1
        self.sent.append(
            {"chat_id": chat_id, "thread_id": message_thread_id, "text": text}
        )
        return self._next_id


async def _seed_tier(conn) -> int:
    return await conn.fetchval(
        """
        INSERT INTO telegram_tiers (name, slug, telegram_channel_id, is_active)
             VALUES ('Ofertoon VIP', 'vip', $1, TRUE)
          RETURNING id
        """,
        CHAT_ID,
    )


async def _seed_topic(
    conn,
    *,
    tier_id: int,
    slug: str,
    thread_id: int | None,
    quota: int = 2,
    categorias: tuple[str, ...] = (),
) -> int:
    topic_id = await conn.fetchval(
        """
        INSERT INTO telegram_topics
               (tier_id, slug, name, message_thread_id, daily_quota)
             VALUES ($1, $2, $3, $4, $5)
          RETURNING id
        """,
        tier_id,
        slug,
        slug.capitalize(),
        thread_id,
        quota,
    )
    for category_slug in categorias:
        await conn.execute(
            """
            INSERT INTO telegram_tier_categories (tier_id, category_id, topic_id)
            SELECT $1, id, $3 FROM categories WHERE slug = $2
            ON CONFLICT (tier_id, category_id) DO UPDATE SET topic_id = $3
            """,
            tier_id,
            category_slug,
            topic_id,
        )
    return topic_id


async def _seed_candidate(
    conn, *, category_slug: str, sku: str, score: str = "30.0"
) -> int:
    """Un aceptado listo para publicar, sin pasar por el detector."""
    store_id = await conn.fetchval("SELECT id FROM stores WHERE slug = 'falabella'")
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
        f"Producto {sku}",
    )
    return await conn.fetchval(
        """
        INSERT INTO deal_candidates
               (listing_id, price, p50_60d, discount_real, score, verdict,
                detected_at)
             VALUES ($1, 300000, 500000, 0.40, $2, 'accepted', $3)
          RETURNING id
        """,
        listing_id,
        Decimal(score),
        NOW - timedelta(hours=1),
    )


# -----------------------------------------------------------------------------
# El ruteo
# -----------------------------------------------------------------------------


async def test_el_candidato_va_al_tema_de_su_categoria(db_conn, telegram_pool) -> None:
    """El modo de falla que este test existe para ver: el tema de al lado."""
    tier_id = await _seed_tier(db_conn)
    await _seed_topic(
        db_conn,
        tier_id=tier_id,
        slug="tecnologia",
        thread_id=11,
        categorias=("tecno-notebooks",),
    )
    ferre = await _seed_topic(
        db_conn,
        tier_id=tier_id,
        slug="ferreteria",
        thread_id=22,
        categorias=("ferre-herramientas",),
    )
    await _seed_candidate(db_conn, category_slug="ferre-herramientas", sku="TALADRO")

    fake = FakeTelegram()
    stats = await poster.run_once(telegram_pool, fake, now=NOW)

    assert stats.published == 1
    assert len(fake.sent) == 1
    assert fake.sent[0]["chat_id"] == CHAT_ID
    assert fake.sent[0]["thread_id"] == 22, "un taladro no va al tema de Tecnología"

    assert await db_conn.fetchval("SELECT topic_id FROM deal_posts") == ferre


async def test_un_solo_mensaje_por_vuelta_aunque_haya_varios_temas_con_oferta(
    db_conn, telegram_pool
) -> None:
    """Siete temas publicando a la vez son siete notificaciones juntas."""
    tier_id = await _seed_tier(db_conn)
    await _seed_topic(
        db_conn,
        tier_id=tier_id,
        slug="tecnologia",
        thread_id=11,
        categorias=("tecno-notebooks",),
    )
    await _seed_topic(
        db_conn,
        tier_id=tier_id,
        slug="ferreteria",
        thread_id=22,
        categorias=("ferre-herramientas",),
    )
    await _seed_candidate(db_conn, category_slug="tecno-notebooks", sku="NOTE")
    await _seed_candidate(db_conn, category_slug="ferre-herramientas", sku="TALADRO")

    fake = FakeTelegram()
    stats = await poster.run_once(telegram_pool, fake, now=NOW)

    assert stats.published == 1
    assert len(fake.sent) == 1


async def test_el_turno_rota_para_que_el_tema_chico_tambien_publique(
    db_conn, telegram_pool
) -> None:
    """Sin rotación, Tecnología (más volumen) dejaría a Ferretería muda siempre.

    El orden lo decide `load_active_topics` por último post, así que la segunda
    vuelta —pasado el espaciado— le toca al otro tema.
    """
    tier_id = await _seed_tier(db_conn)
    await _seed_topic(
        db_conn,
        tier_id=tier_id,
        slug="tecnologia",
        thread_id=11,
        categorias=("tecno-notebooks",),
    )
    await _seed_topic(
        db_conn,
        tier_id=tier_id,
        slug="ferreteria",
        thread_id=22,
        categorias=("ferre-herramientas",),
    )
    # Dos de tecno para que, sin rotación, la segunda vuelta volvería a Tecnología.
    await _seed_candidate(db_conn, category_slug="tecno-notebooks", sku="NOTE1")
    await _seed_candidate(db_conn, category_slug="tecno-notebooks", sku="NOTE2")
    await _seed_candidate(db_conn, category_slug="ferre-herramientas", sku="TALADRO")

    fake = FakeTelegram()
    await poster.run_once(telegram_pool, fake, now=NOW)
    await poster.run_once(
        telegram_pool,
        fake,
        now=NOW + timedelta(minutes=ranker.MIN_MINUTES_BETWEEN + 5),
    )

    assert [m["thread_id"] for m in fake.sent] == [11, 22]


async def test_la_cuota_es_del_tema_y_no_del_canal(db_conn, telegram_pool) -> None:
    """Un tema con cuota 1 se calla después del primero; el otro sigue."""
    tier_id = await _seed_tier(db_conn)
    await _seed_topic(
        db_conn,
        tier_id=tier_id,
        slug="hogar",
        thread_id=33,
        quota=1,
        categorias=("hogar-electro",),
    )
    await _seed_candidate(db_conn, category_slug="hogar-electro", sku="REFRI1")
    await _seed_candidate(db_conn, category_slug="hogar-electro", sku="REFRI2")

    fake = FakeTelegram()
    await poster.run_once(telegram_pool, fake, now=NOW)
    await poster.run_once(
        telegram_pool,
        fake,
        now=NOW + timedelta(minutes=ranker.MIN_MINUTES_BETWEEN + 5),
    )

    assert len(fake.sent) == 1, "la cuota del tema es 1"


async def test_un_tema_sin_thread_no_es_destino(db_conn, telegram_pool) -> None:
    """El estado en que nace la migración 26: temas creados, ids sin cablear."""
    tier_id = await _seed_tier(db_conn)
    await _seed_topic(
        db_conn,
        tier_id=tier_id,
        slug="supermercado",
        thread_id=None,
        categorias=("tecno-notebooks",),
    )
    await _seed_candidate(db_conn, category_slug="tecno-notebooks", sku="NOTE")

    async with telegram_pool.acquire() as conn:
        assert await poster.load_active_topics(conn, tier_id=tier_id) == []


async def test_sin_temas_cableados_publica_al_chat_plano(db_conn, telegram_pool) -> None:
    """La compatibilidad que permitió aplicar la 26 con el publisher encendido."""
    tier_id = await _seed_tier(db_conn)
    await db_conn.execute(
        """
        INSERT INTO telegram_tier_categories (tier_id, category_id)
        SELECT $1, id FROM categories WHERE slug = 'tecno-notebooks'
        """,
        tier_id,
    )
    await _seed_candidate(db_conn, category_slug="tecno-notebooks", sku="NOTE")

    fake = FakeTelegram()
    stats = await poster.run_once(telegram_pool, fake, now=NOW)

    assert stats.published == 1
    assert fake.sent[0]["thread_id"] is None, "sin temas no se manda thread"
    assert await db_conn.fetchval("SELECT topic_id FROM deal_posts") is None


async def test_una_categoria_sin_tema_queda_muda_y_se_avisa(
    db_conn, telegram_pool
) -> None:
    """El síntoma es indistinguible de 'no hubo ofertas', así que se loguea."""
    tier_id = await _seed_tier(db_conn)
    await _seed_topic(
        db_conn,
        tier_id=tier_id,
        slug="tecnologia",
        thread_id=11,
        categorias=("tecno-notebooks",),
    )
    # Ruteada al tier pero sin tema: el caso de una categoría nueva.
    await db_conn.execute(
        """
        INSERT INTO telegram_tier_categories (tier_id, category_id)
        SELECT $1, id FROM categories WHERE slug = 'ferre-jardin'
        """,
        tier_id,
    )
    await _seed_candidate(db_conn, category_slug="ferre-jardin", sku="MANGUERA")

    fake = FakeTelegram()
    stats = await poster.run_once(telegram_pool, fake, now=NOW)

    assert stats.published == 0, "sin tema no hay destino"
    async with telegram_pool.acquire() as conn:
        huerfanas = await poster.warn_categories_without_topic(conn, tier_id=tier_id)
    assert huerfanas == ["ferre-jardin"]


async def test_dos_temas_no_pueden_compartir_thread(db_conn) -> None:
    """Un thread repetido publica en el tema equivocado sin fallar: lo ataja el UNIQUE."""
    import asyncpg

    tier_id = await _seed_tier(db_conn)
    await _seed_topic(db_conn, tier_id=tier_id, slug="tecnologia", thread_id=11)
    with pytest.raises(asyncpg.exceptions.UniqueViolationError):
        await _seed_topic(db_conn, tier_id=tier_id, slug="hogar", thread_id=11)


async def test_el_posteo_en_un_tema_no_gasta_la_cuota_del_canal_viejo(
    db_conn, telegram_pool
) -> None:
    """Las filas pre-migración tienen `topic_id` NULL y no cuentan para un tema."""
    tier_id = await _seed_tier(db_conn)
    topic_id = await _seed_topic(
        db_conn,
        tier_id=tier_id,
        slug="tecnologia",
        thread_id=11,
        quota=1,
        categorias=("tecno-notebooks",),
    )
    # Un post del canal plano, de hoy, sin tema: es lo que dejó el publisher
    # encendido antes de cablear los temas.
    viejo = await _seed_candidate(db_conn, category_slug="tecno-notebooks", sku="VIEJO")
    await db_conn.execute(
        """
        INSERT INTO deal_posts (candidate_id, tier_id, posted_at, topic_id)
             VALUES ($1, $2, $3, NULL)
        """,
        viejo,
        tier_id,
        NOW - timedelta(hours=2),
    )
    await _seed_candidate(db_conn, category_slug="tecno-notebooks", sku="NUEVO")

    async with telegram_pool.acquire() as conn:
        posted = await ranker.load_posted_today(
            conn, tier_id=tier_id, now=NOW, topic_id=topic_id
        )
    assert posted.total == 0, "el post sin tema no gasta la cuota del tema"

    fake = FakeTelegram()
    stats = await poster.run_once(telegram_pool, fake, now=NOW)
    assert stats.published == 1
