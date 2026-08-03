"""Contract test del adaptador Easy contra un fixture real.

El fixture es HTML capturado de producción (2026-07-31), categoría
`herramientas/herramientas-electricas/taladros-y-atornilladores`, con 6
productos elegidos para cubrir los tres casos de precio que existen en la
tienda: con tarjeta Cencosud, sin tarjeta, y sin oferta.

Se podaron los campos que el parser no lee (`description`, `specifications`,
`variants`, `facets`) porque inflaban el archivo a 100 KB y lo volvían ilegible
en un diff. Todo lo que el adaptador sí toca está tal cual lo sirvió la tienda.
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from scrapers.base import CategoryRef
from scrapers.http import BROWSER_USER_AGENT, DEFAULT_USER_AGENT
from scrapers.stores.easy import (
    EasyAdapter,
    NextDataMissing,
    NotAListingPage,
    extract_next_data,
    parse_listing,
    resolve_prices,
)

FIXTURE = Path(__file__).parent / "fixtures" / "easy_listing_taladros.html"
CATEGORY = CategoryRef(
    slug="ferre-herramientas",
    store_key="herramientas/herramientas-electricas/taladros-y-atornilladores",
    label="Herramientas eléctricas",
)
NOW = datetime(2026, 7, 31, 12, 0, tzinfo=timezone.utc)


@pytest.fixture(scope="module")
def parsed():
    html = FIXTURE.read_text(encoding="utf-8")
    return parse_listing(html, store_slug="easy", category=CATEGORY, scraped_at=NOW)


def test_extrae_todos_los_productos(parsed):
    products, total = parsed
    assert len(products) == 6
    assert total == 140


def test_campos_obligatorios_no_nulos(parsed):
    products, _ = parsed
    for p in products:
        assert p.store_sku and p.store_sku.isdigit()
        assert p.url.startswith("https://www.easy.cl/")
        assert p.url.endswith("/p")
        assert p.name
        assert p.price_effective > 0
        assert p.brand
        assert p.image_url
        assert p.scraped_at == NOW


def test_precio_efectivo_ignora_la_tarjeta_cencosud(parsed):
    """`brandPrice` es el precio con Tarjeta Cencosud: se guarda, no se compara.

    Es el análogo del `cmrPrice` de Falabella y el vehículo favorito del
    descuento fantasma: requiere plástico de la casa, así que no es lo que paga
    cualquiera.
    """
    products, _ = parsed
    taladro = next(p for p in products if p.store_sku == "1323156")
    assert taladro.price_card == Decimal("89990")  # brandPrice
    assert taladro.price_effective == Decimal("92990")  # offerPrice
    assert taladro.price_effective > taladro.price_card


def test_brand_price_sale_de_default_offer_no_del_bloque_de_producto():
    """Easy publica el bloque de precios dos veces y solo uno trae la tarjeta.

    `prices` (nivel producto) deja `brandPrice` en null sistemáticamente; el
    valor real vive en `commercialOffer.defaultOffer.prices`. Si el parser leyera
    el primero, el precio-tarjeta se perdería entero.
    """
    producto = {
        "prices": {"normalPrice": 149990, "offerPrice": 92990, "brandPrice": None},
        "commercialOffer": {
            "defaultOffer": {
                "prices": {"normalPrice": 149990, "offerPrice": 92990, "brandPrice": 89990}
            }
        },
    }
    _, _, card = resolve_prices(producto)
    assert card == Decimal("89990")


def test_sin_oferta_el_normal_es_el_precio_de_hoy(parsed):
    """Sin `offerPrice` no hay descuento: el normal es el vigente, no un 'antes'.

    Registrar el normal como `price_normal` en ese caso inventaría un descuento
    del 0% que después ensucia el análisis de qué tiendas declaran rebajas.
    """
    products, _ = parsed
    sin_oferta = next(p for p in products if p.store_sku == "1493522")
    assert sin_oferta.price_effective == Decimal("19990")
    assert sin_oferta.price_normal is None


def test_precio_normal_se_guarda_pero_no_se_cree(parsed):
    """Con oferta, el 'antes' tachado se persiste como evidencia."""
    products, _ = parsed
    p = next(p for p in products if p.store_sku == "1510312")
    assert p.price_normal == Decimal("189990")
    assert p.price_effective == Decimal("89990")


def test_descuento_declarado_es_el_general_no_el_de_tarjeta(parsed):
    """La promo `payment` es el % con tarjeta; el comparable es la `general`.

    Guardar el 40% de la tarjeta como descuento declarado sobreestimaría lo que
    la tienda ofrece a quien paga sin plástico (38%).
    """
    products, _ = parsed
    taladro = next(p for p in products if p.store_sku == "1323156")
    assert taladro.claimed_discount == "38%"


def test_marca_normalizada(parsed):
    products, _ = parsed
    taladro = next(p for p in products if p.store_sku == "1323156")
    assert taladro.brand == "Einhell"


# --- resolve_prices: casos que el fixture no cubre ---------------------------


def test_resolve_prices_producto_vacio():
    assert resolve_prices({}) == (None, None, None)


def test_resolve_prices_normal_igual_a_oferta_no_es_descuento():
    """Si el 'antes' no es mayor que el precio de hoy, no hay antes que guardar."""
    producto = {"prices": {"normalPrice": 19990, "offerPrice": 19990}}
    effective, claimed, _ = resolve_prices(producto)
    assert effective == Decimal("19990")
    assert claimed is None


def test_resolve_prices_cero_no_es_precio():
    """Un 0 no es un precio barato: es un campo sin llenar."""
    producto = {"prices": {"normalPrice": 0, "offerPrice": 0, "brandPrice": 0}}
    assert resolve_prices(producto) == (None, None, None)


def test_producto_sin_precio_se_descarta():
    html = (
        '<script id="__NEXT_DATA__" type="application/json">'
        '{"props":{"pageProps":{"serverProductsResponse":{"recordsFiltered":1,'
        '"productList":[{"sku":"1","linkText":"x/p","productName":"Sin precio",'
        '"prices":{}}]}}}}</script>'
    )
    products, _ = parse_listing(
        html, store_slug="easy", category=CATEGORY, scraped_at=NOW
    )
    assert products == []


def test_html_sin_next_data_falla_ruidosamente():
    with pytest.raises(NextDataMissing):
        extract_next_data("<html><body>nada</body></html>")


# --- paginación y guardas del adaptador --------------------------------------


def test_url_de_pagina_conserva_el_path_completo():
    adapter = EasyAdapter(None, [])
    assert adapter._page_url(CATEGORY, 3) == (
        "https://www.easy.cl/herramientas/herramientas-electricas/"
        "taladros-y-atornilladores?page=3"
    )


def test_easy_usa_user_agent_de_navegador():
    """Easy hace UA-sniffing: con el UA identificable sirve la home con HTTP 200.

    Es una degradación silenciosa, no un bloqueo — sin este header el adaptador
    ingeriría cero productos sin un solo error de red. Verificado en vivo el
    2026-07-31.
    """
    assert EasyAdapter._headers["User-Agent"] == BROWSER_USER_AGENT
    assert "ofertascl-bot" not in BROWSER_USER_AGENT
    assert "ofertascl-bot" in DEFAULT_USER_AGENT


_SHELL_SIN_PRODUCTOS = (
    '<script id="__NEXT_DATA__" type="application/json">'
    '{"page":"/","props":{"pageProps":{"categoriesData":[],"headerViewData":{}}}}</script>'
)


@pytest.mark.asyncio
async def test_pagina_1_sin_listado_es_error_de_configuracion():
    """Un departamento de primer nivel (`/herramientas`) es CMS, no listado.

    También es la forma en que se manifiesta el UA-sniffing: la home responde
    HTTP 200 sin `serverProductsResponse`. Debe propagar, nunca verse como una
    categoría vacía.
    """

    class _Http:
        async def get_text(self, url, **kw):
            return _SHELL_SIN_PRODUCTOS

    adapter = EasyAdapter(_Http(), [])
    with pytest.raises(NotAListingPage):
        async for _ in adapter.discover(CategoryRef(slug="x", store_key="herramientas")):
            pass


@pytest.mark.asyncio
async def test_shell_despues_de_la_pagina_1_es_fin_de_catalogo():
    """Pasado el final, Easy deja de emitir `serverProductsResponse`."""

    class _Http:
        def __init__(self):
            self.calls = 0

        async def get_text(self, url, **kw):
            self.calls += 1
            if self.calls == 1:
                return FIXTURE.read_text(encoding="utf-8")
            return _SHELL_SIN_PRODUCTOS

    http = _Http()
    adapter = EasyAdapter(http, [])
    productos = [p async for p in adapter.discover(CATEGORY)]
    assert len(productos) == 6
    assert http.calls == 2  # cortó en la segunda, no siguió hasta max_pages
