"""La guarda de disponibilidad: no publicar algo que no se puede comprar.

El lector se prueba contra los dos formatos reales de la familia Falabella; el
cableado con el poster se prueba contra Postgres, porque lo que importa ahí es que
un agotado NO deje fila en `deal_posts` y que el resultado quede persistido para
no re-consultar la ficha en cada vuelta del daemon.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from decimal import Decimal

import pytest

from curation import ranker
from publisher import poster, stock
from scrapers.http import FetchError

#: Un martes a las 13:00 de Santiago: dentro de la ventana de publicación.
NOW = datetime(2026, 8, 4, 13, 0, tzinfo=ranker.TZ)
CHAT_ID = -1002812345678


def ficha(*, is_out_of_stock=None, availability=None) -> str:
    """Una ficha mínima con la forma de la familia Falabella."""
    partes = ['<!doctype html><html><head>']
    if is_out_of_stock is not None:
        payload = {"props": {"pageProps": {"isOutOfStock": is_out_of_stock}}}
        partes.append(
            '<script id="__NEXT_DATA__" type="application/json">'
            + json.dumps(payload)
            + "</script>"
        )
    if availability is not None:
        ld = {
            "@type": "Product",
            "offers": [{"@type": "Offer", "availability": availability}],
        }
        partes.append(
            '<script type="application/ld+json">' + json.dumps(ld) + "</script>"
        )
    partes.append("</head><body></body></html>")
    return "".join(partes)


# -----------------------------------------------------------------------------
# El lector, puro
# -----------------------------------------------------------------------------


def test_lee_is_out_of_stock():
    assert stock.leer_disponibilidad(ficha(is_out_of_stock=False)) is True
    assert stock.leer_disponibilidad(ficha(is_out_of_stock=True)) is False


def test_lee_el_json_ld_de_schema_org():
    assert (
        stock.leer_disponibilidad(ficha(availability="https://schema.org/InStock"))
        is True
    )
    assert (
        stock.leer_disponibilidad(ficha(availability="https://schema.org/OutOfStock"))
        is False
    )


def test_is_out_of_stock_gana_sobre_el_json_ld():
    """El JSON-LD trae una oferta por seller y por forma de pago; esto, un booleano.

    En la ficha medida el 2026-10-02 había dos `Offer` con precios distintos
    ($189.990 y $309.990) para el mismo SKU. `isOutOfStock` es lo que la propia
    página usa para habilitar el botón de compra: es la fuente, no un reflejo.
    """
    html = ficha(is_out_of_stock=False, availability="https://schema.org/OutOfStock")
    assert stock.leer_disponibilidad(html) is True


def test_sin_senal_es_none_y_no_false():
    """La diferencia que hace que una ficha ilegible no silencie el canal."""
    assert stock.leer_disponibilidad("<html><body>nada</body></html>") is None


def test_un_next_data_roto_no_revienta():
    html = (
        '<script id="__NEXT_DATA__" type="application/json">{roto</script>'
        '<script type="application/ld+json">'
        '{"@type":"Product","offers":{"availability":"https://schema.org/InStock"}}'
        "</script>"
    )
    assert stock.leer_disponibilidad(html) is True


class FakeHttp:
    def __init__(self, respuesta=None, *, falla=False):
        self.respuesta = respuesta
        self.falla = falla
        self.pedidos: list[str] = []

    async def get_text(self, url, *, rps=None, headers=None):
        self.pedidos.append(url)
        if self.falla:
            raise FetchError("la ficha no respondió")
        return self.respuesta


@pytest.mark.asyncio
async def test_una_tienda_sin_verificador_no_se_consulta():
    """Paris no está en la familia: su ficha no trae `availability`.

    Lo importante es que no se gaste un fetch y que devuelva `None`, que no bloquea.
    """
    http = FakeHttp(ficha(is_out_of_stock=True))
    assert await stock.verificar(http, store_slug="paris", url="https://x") is None
    assert http.pedidos == []


@pytest.mark.asyncio
async def test_un_fetch_fallido_es_none_y_no_bloquea():
    http = FakeHttp(falla=True)
    assert await stock.verificar(http, store_slug="falabella", url="https://x") is None


@pytest.mark.asyncio
async def test_verifica_las_tres_de_la_familia():
    for slug in ("falabella", "sodimac", "tottus"):
        http = FakeHttp(ficha(is_out_of_stock=True))
        assert await stock.verificar(http, store_slug=slug, url="https://x") is False
        assert len(http.pedidos) == 1


# -----------------------------------------------------------------------------
# El cableado con el poster, contra Postgres
# -----------------------------------------------------------------------------

pytestmark_db = pytest.mark.asyncio


class FakeTelegram:
    def __init__(self):
        self.sent: list[dict] = []

    async def send_message(
        self,
        chat_id,
        text,
        parse_mode=None,
        *,
        disable_web_page_preview=True,
        message_thread_id=None,
    ):
        self.sent.append({"chat_id": chat_id, "thread_id": message_thread_id})
        return 4242


async def _seed(conn, *, store_slug: str = "falabella") -> int:
    """Un tier con una categoría ruteada y un candidato aceptado. Devuelve candidate_id."""
    await conn.execute(
        """
        INSERT INTO telegram_tiers (name, slug, telegram_channel_id, is_active)
             VALUES ('Ofertoon VIP', 'vip', $1, TRUE)
        """,
        CHAT_ID,
    )
    tier_id = await conn.fetchval("SELECT id FROM telegram_tiers WHERE slug = 'vip'")
    await conn.execute(
        """
        INSERT INTO telegram_tier_categories (tier_id, category_id)
        SELECT $1, id FROM categories WHERE slug = 'tecno-notebooks'
        """,
        tier_id,
    )
    store_id = await conn.fetchval("SELECT id FROM stores WHERE slug = $1", store_slug)
    category_id = await conn.fetchval(
        "SELECT id FROM categories WHERE slug = 'tecno-notebooks'"
    )
    listing_id = await conn.fetchval(
        """
        INSERT INTO listings (store_id, category_id, store_sku, url, name_raw)
             VALUES ($1, $2, 'SKU1', 'https://falabella.com/p/1', 'Notebook')
          RETURNING id
        """,
        store_id,
        category_id,
    )
    return await conn.fetchval(
        """
        INSERT INTO deal_candidates
               (listing_id, price, p50_60d, discount_real, score, verdict, detected_at)
             VALUES ($1, 300000, 500000, 0.40, 30.0, 'accepted', $2)
          RETURNING id
        """,
        listing_id,
        NOW - timedelta(hours=1),
    )


@pytest.mark.asyncio
async def test_un_agotado_no_se_publica_ni_deja_fila(db_conn, telegram_pool) -> None:
    candidate_id = await _seed(db_conn)
    fake = FakeTelegram()
    http = FakeHttp(ficha(is_out_of_stock=True))

    stats = await poster.run_once(telegram_pool, fake, now=NOW, http=http)

    assert stats.published == 0
    assert stats.skipped_out_of_stock == 1
    assert fake.sent == []
    assert await db_conn.fetchval("SELECT COUNT(*) FROM deal_posts") == 0, (
        "un agotado no puede dejar reserva: habría que explicarla después"
    )
    fila = await db_conn.fetchrow(
        "SELECT stock_ok, stock_checked_at FROM deal_candidates WHERE id = $1",
        candidate_id,
    )
    assert fila["stock_ok"] is False
    assert fila["stock_checked_at"] is not None


@pytest.mark.asyncio
async def test_el_agotado_no_se_reconsulta_en_la_vuelta_siguiente(
    db_conn, telegram_pool
) -> None:
    """Sin esto serían ~150 fetches de la misma ficha contra un presupuesto de 10-30."""
    await _seed(db_conn)
    fake = FakeTelegram()
    http = FakeHttp(ficha(is_out_of_stock=True))

    await poster.run_once(telegram_pool, fake, now=NOW, http=http)
    assert len(http.pedidos) == 1

    await poster.run_once(
        telegram_pool,
        fake,
        now=NOW + timedelta(minutes=ranker.MIN_MINUTES_BETWEEN + 5),
        http=http,
    )
    assert len(http.pedidos) == 1, "el ranker ya no lo devuelve: stock_ok es FALSE"


@pytest.mark.asyncio
async def test_un_disponible_se_publica_y_queda_registrado(
    db_conn, telegram_pool
) -> None:
    candidate_id = await _seed(db_conn)
    fake = FakeTelegram()
    http = FakeHttp(ficha(is_out_of_stock=False))

    stats = await poster.run_once(telegram_pool, fake, now=NOW, http=http)

    assert stats.published == 1
    assert len(fake.sent) == 1
    assert await db_conn.fetchval(
        "SELECT stock_ok FROM deal_candidates WHERE id = $1", candidate_id
    ) is True


@pytest.mark.asyncio
async def test_sin_senal_se_publica_igual(db_conn, telegram_pool) -> None:
    """La duda no bloquea: callar el canal es peor que una oferta agotada."""
    candidate_id = await _seed(db_conn)
    fake = FakeTelegram()
    http = FakeHttp("<html><body>sin señal</body></html>")

    stats = await poster.run_once(telegram_pool, fake, now=NOW, http=http)

    assert stats.published == 1
    fila = await db_conn.fetchrow(
        "SELECT stock_ok, stock_checked_at FROM deal_candidates WHERE id = $1",
        candidate_id,
    )
    assert fila["stock_ok"] is None
    assert fila["stock_checked_at"] is not None, (
        "se intentó: sin esto se re-consultaría la ficha en cada vuelta"
    )


@pytest.mark.asyncio
async def test_sin_http_no_se_verifica_nada(db_conn, telegram_pool) -> None:
    """El comportamiento de antes de la migración 30, que es el default."""
    candidate_id = await _seed(db_conn)
    fake = FakeTelegram()

    stats = await poster.run_once(telegram_pool, fake, now=NOW)

    assert stats.published == 1
    assert await db_conn.fetchval(
        "SELECT stock_checked_at FROM deal_candidates WHERE id = $1", candidate_id
    ) is None


@pytest.mark.asyncio
async def test_una_tienda_sin_verificador_se_publica_sin_fetch(
    db_conn, telegram_pool
) -> None:
    candidate_id = await _seed(db_conn, store_slug="paris")
    fake = FakeTelegram()
    http = FakeHttp(ficha(is_out_of_stock=True))

    stats = await poster.run_once(telegram_pool, fake, now=NOW, http=http)

    assert stats.published == 1
    assert http.pedidos == [], "Paris no tiene verificador: no se gasta el fetch"
    assert await db_conn.fetchval(
        "SELECT stock_checked_at FROM deal_candidates WHERE id = $1", candidate_id
    ) is None


def test_is_out_of_stock_tambien_se_busca_anidado_en_product_data():
    """Cambia de lugar entre fichas, y mirar solo uno dejaba pasar agotados.

    Medido el 2026-10-02: de 14 fichas reales, dos quedaban sin señal con el lector
    que solo miraba `pageProps.isOutOfStock` — **y las dos estaban agotadas**. Las
    fichas que anidan el dato en `productData` son justamente las que no traen
    `availability` en su JSON-LD, así que el fallback "no sé, publico" se activaba
    exactamente en el caso que la guarda existe para atajar.
    """
    anidado = (
        '<script id="__NEXT_DATA__" type="application/json">'
        '{"props":{"pageProps":{"productData":{"isOutOfStock":true}}}}'
        "</script>"
    )
    assert stock.leer_disponibilidad(anidado) is False

    disponible = (
        '<script id="__NEXT_DATA__" type="application/json">'
        '{"props":{"pageProps":{"productData":{"isOutOfStock":false}}}}'
        "</script>"
    )
    assert stock.leer_disponibilidad(disponible) is True


def test_el_no_anidado_tiene_prioridad_sobre_product_data():
    """Si están los dos, manda el del nivel de la página."""
    html = (
        '<script id="__NEXT_DATA__" type="application/json">'
        '{"props":{"pageProps":{"isOutOfStock":false,'
        '"productData":{"isOutOfStock":true}}}}'
        "</script>"
    )
    assert stock.leer_disponibilidad(html) is True
