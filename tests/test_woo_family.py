"""Contract test de la familia WooCommerce contra un fixture real de Urban Comercial.

El fixture es la respuesta de producción (2026-09-23) de
`/wp-json/wc/store/v1/products?per_page=100&page=1&category=27`, podada a 4 de
los 100 productos y, dentro de cada uno, a los campos que el parser lee. De
`attributes` quedaron solo `EAN` y `Marca` (la tienda sirve también `Color` y
otros) y de `images` la primera.

Los 4 cubren los casos que hacen distinta a esta familia: uno con **EAN y Marca**
—la identidad que Shopify no puede dar—, uno con **entidad HTML** en el nombre
(39 de los 100 traían `&#8211;`), uno sin identidad ninguna y uno **sin
descuento declarado**, que era el caso raro: 94 de 100 venían con
`regular_price` por encima del precio de venta.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from scrapers.base import CategoryRef
from scrapers.stores.woo_family import (
    NotAListingPage,
    UrbanAdapter,
    parse_listing,
    parse_price,
)

FIXTURE = Path(__file__).parent / "fixtures" / "urban_categoria_herramientas.json"
CATEGORY = CategoryRef(
    slug="ferre-herramientas", store_key="27", label="Herramientas Eléctricas"
)
NOW = datetime(2026, 9, 23, 12, 0, tzinfo=timezone.utc)


@pytest.fixture(scope="module")
def productos():
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    return parse_listing(
        payload, store_slug="urban", category=CATEGORY, scraped_at=NOW
    )


def test_parsea_los_cuatro(productos):
    assert len(productos) == 4
    assert all(p.store_slug == "urban" for p in productos)
    assert all(p.category_path == "ferre-herramientas" for p in productos)


def test_precios_enteros_en_clp(productos):
    assert productos[0].price_effective == Decimal("64990")
    assert productos[0].price_normal == Decimal("99990")
    for p in productos:
        assert p.price_effective == p.price_effective.to_integral_value()


def test_trae_identidad_cuando_la_tienda_la_publica(productos):
    """El diferencial contra Shopify: Woo puede exponer EAN y Marca."""
    assert productos[0].gtin == "4006825685022"
    assert productos[0].brand == "Einhell"


def test_no_inventa_identidad_cuando_falta(productos):
    """Regla 6: ante la duda no se agrupa."""
    sin_identidad = [p for p in productos if p.gtin is None]
    assert sin_identidad, "el fixture tiene que traer un producto sin EAN"
    assert all(p.model is None for p in productos)


def test_desescapa_las_entidades_html_del_nombre(productos):
    """39 de 100 nombres traían `&#8211;`; sin esto el canal publica la entidad."""
    assert not any("&#" in p.name or "&amp;" in p.name for p in productos)
    assert any("–" in p.name for p in productos)


def test_regular_price_igual_al_precio_no_es_descuento(productos):
    """`price_normal` solo cuando de verdad está por encima: si no, es None."""
    sin_descuento = [p for p in productos if p.price_normal is None]
    assert len(sin_descuento) == 1
    assert sin_descuento[0].price_effective == Decimal("254990")


def test_url_es_el_permalink_de_la_tienda(productos):
    assert all(p.url.startswith("https://urbancomercial.cl/") for p in productos)


@pytest.mark.parametrize(
    "crudo, minor_unit, esperado",
    [
        ("6490", 0, Decimal("6490")),
        (6490, 0, Decimal("6490")),
        # La trampa de la familia: la misma API en una tienda con 2 decimales
        # devuelve el precio en centavos.
        ("649000", 2, Decimal("6490")),
        # CLP no tiene decimales: redondear inventaría un precio que no existe.
        ("649050", 2, None),
        ("0", 0, None),
        ("", 0, None),
        (None, 0, None),
        ("gratis", 0, None),
    ],
)
def test_parse_price_respeta_currency_minor_unit(crudo, minor_unit, esperado):
    assert parse_price(crudo, minor_unit) == esperado


def test_respuesta_que_no_es_lista_es_error():
    with pytest.raises(NotAListingPage):
        parse_listing(
            {"code": "woocommerce_rest_invalid_param"},
            store_slug="urban",
            category=CATEGORY,
            scraped_at=NOW,
        )


class _Http:
    def __init__(self, paginas):
        self.paginas = paginas
        self.urls = []

    async def get_text(self, url, **kw):
        self.urls.append(url)
        return self.paginas[len(self.urls) - 1]


@pytest.mark.asyncio
async def test_pagina_vacia_despues_de_la_1_es_fin_de_catalogo():
    http = _Http([FIXTURE.read_text(encoding="utf-8"), "[]"])
    productos = [p async for p in UrbanAdapter(http, []).discover(CATEGORY)]
    assert len(productos) == 4
    assert len(http.urls) == 2
    assert "per_page=100&page=1&category=27" in http.urls[0]


@pytest.mark.asyncio
async def test_pagina_1_vacia_es_error_de_configuracion():
    """La Store API devuelve 200 `[]` también para una categoría inexistente."""
    http = _Http(["[]"])
    with pytest.raises(NotAListingPage):
        async for _ in UrbanAdapter(http, []).discover(CATEGORY):
            pass
