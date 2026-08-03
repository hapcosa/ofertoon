"""Contract test del adaptador SP Digital contra un fixture real.

El fixture es la respuesta GraphQL de producción (2026-07-31) para la categoría
`Q2F0ZWdvcnk6MTIzOA==` (Notebooks), primera página de 5 productos.

Se podaron los campos que el parser no lee: de `metadata` quedaron `pricing`,
`gtin` y `mpn` (de once claves), de `attributes` solo `brand` y `condition` (de
más de treinta, casi todas vacías) y de `media` la primera imagen. Los bloques
`pricing`, `defaultVariant`, `pageInfo` y `totalCount` están tal cual los sirvió
la tienda — `totalCount: 86` es el real, por eso no coincide con los 5 productos
del archivo.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from scrapers.base import CategoryRef
from scrapers.stores.spdigital import (
    NotAListingPage,
    SpDigitalAdapter,
    parse_listing,
    resolve_prices,
)

FIXTURE = Path(__file__).parent / "fixtures" / "spdigital_listing_notebooks.json"
CATEGORY = CategoryRef(
    slug="tecno-notebooks", store_key="Q2F0ZWdvcnk6MTIzOA==", label="Notebooks"
)
NOW = datetime(2026, 7, 31, 12, 0, tzinfo=timezone.utc)


@pytest.fixture(scope="module")
def parsed():
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    return parse_listing(payload, store_slug="spdigital", category=CATEGORY, scraped_at=NOW)


def test_extrae_todos_los_productos(parsed):
    products, end_cursor, has_next = parsed
    assert len(products) == 5
    assert end_cursor
    assert has_next is True


def test_campos_obligatorios_no_nulos(parsed):
    products, _, _ = parsed
    for p in products:
        assert p.store_sku.startswith("NA")
        assert p.url.startswith("https://www.spdigital.cl/") and p.url.endswith("/")
        assert p.name
        assert p.price_effective > 0
        assert p.brand
        assert p.image_url.startswith("https://media.spdigital.cl/")
        assert p.in_stock
        assert p.scraped_at == NOW


def test_efectivo_es_la_transferencia_no_el_precio_de_la_api(parsed):
    """El número que devuelve Saleor es el de "otros medios", el MÁS caro de los dos.

    Y `metadata.pricing.cash`, pese al nombre, es el "Normal" tachado. Publicar
    cualquiera de los dos como precio de hoy sería un precio que la ficha no
    muestra: uno más caro por el recargo de tarjeta, el otro por ser el de lista.
    """
    products, _, _ = parsed
    dell = next(p for p in products if p.store_sku == "NA0000095239")
    assert dell.price_effective == Decimal("1750910")  # transferencia
    assert dell.price_normal == Decimal("2162430")  # "Normal" tachado
    # 1.829.711 (el amount de la API) no queda persistido en ningún campo.
    assert Decimal("1829711") not in (dell.price_effective, dell.price_normal)


def test_formula_de_transferencia_replica_la_ficha_real():
    """Caso verificado contra la ficha de `22u401a-monitor-fhd-215-100hz-2`.

    La tienda mostraba: Normal $139.990, transferencia $69.990, otros medios
    $73.145, "50%". El truncado a la decena es parte de la fórmula del front —
    redondear al peso daría $69.995 y ese precio no existe en la ficha.
    """
    node = {
        "pricing": {"priceRange": {"start": {"gross": {"amount": 73145.0}}}},
        "metadata": [
            {"key": "pricing", "value": '{"sp-digital":{"cash":139990,"other":146290}}'}
        ],
    }
    assert resolve_prices(node) == (Decimal("69990"), Decimal("139990"), "50%")


def test_sin_tarjeta_de_la_casa_no_hay_precio_tarjeta(parsed):
    """SP Digital no emite tarjeta propia: `price_card` queda vacío por diseño.

    El precio "otros medios" es un recargo por tarjeta bancaria (4,5% fijo), no
    un precio exclusivo de la tienda. Guardarlo en `price_card` lo mezclaría con
    los CMR/Cencosud/BancoEstado, que son otra cosa.
    """
    products, _, _ = parsed
    assert all(p.price_card is None for p in products)


def test_descuento_declarado_es_el_de_la_tienda(parsed):
    products, _, _ = parsed
    hp = next(p for p in products if p.store_sku == "NA0000098749")
    assert hp.claimed_discount == "19%"


def test_gtin_solo_cuando_es_gtin(parsed):
    """La tienda deja el campo vacío o lo rellena con su propio SKU."""
    products, _, _ = parsed
    con_gtin = next(p for p in products if p.store_sku == "NA0000095239")
    sin_gtin = next(p for p in products if p.store_sku == "NA0000093994")
    assert con_gtin.gtin == "884116671206"
    assert sin_gtin.gtin is None


def test_gtin_igual_al_sku_se_descarta():
    """Un SKU interno disfrazado de GTIN envenenaría el matching cross-store."""
    from scrapers.stores.spdigital import _gtin

    assert _gtin({"gtin": "NA0000086755"}, "NA0000086755") is None
    assert _gtin({"gtin": "196548244195"}, "NA0000098116") == "196548244195"


def test_modelo_sale_del_mpn(parsed):
    products, _, _ = parsed
    asus = next(p for p in products if p.store_sku == "NA0000093994")
    assert asus.model == "90NX03V1-M008J0"


def test_marca_normalizada(parsed):
    products, _, _ = parsed
    assert next(p for p in products if p.store_sku == "NA0000093994").brand == "Asus"


# --- resolve_prices: casos que el fixture no cubre ---------------------------


def _node(amount, pricing=None):
    node = {"pricing": {"priceRange": {"start": {"gross": {"amount": amount}}}}}
    if pricing is not None:
        node["metadata"] = [{"key": "pricing", "value": pricing}]
    return node


def test_resolve_prices_sin_precio():
    assert resolve_prices({}) == (None, None, None)
    assert resolve_prices(_node(0)) == (None, None, None)


def test_resolve_prices_sin_metadata_cae_al_precio_de_otros_medios():
    """Sin el bloque no se puede derivar la transferencia. Se usa el caro.

    Es el sesgo correcto: publicar de más nunca inventa una oferta que no existe,
    solo deja pasar una real.
    """
    assert resolve_prices(_node(10000)) == (Decimal("10000"), None, None)


def test_resolve_prices_metadata_ilegible_no_revienta(caplog):
    with caplog.at_level("WARNING"):
        effective, claimed, pct = resolve_prices(_node(10000, "{no es json"))
    assert (effective, claimed, pct) == (Decimal("10000"), None, None)
    assert "spdigital_metadata_pricing_ilegible" in caplog.text


def test_resolve_prices_sin_descuento_no_declara_antes():
    """Si el precio de lista no supera al efectivo, no hay "antes" que guardar."""
    effective, claimed, pct = resolve_prices(
        _node(10000, '{"sp-digital":{"cash":10000,"other":10000}}')
    )
    assert effective == Decimal("10000")
    assert claimed is None
    assert pct is None


def test_producto_sin_sku_se_descarta():
    payload = {
        "data": {
            "products": {
                "totalCount": 1,
                "pageInfo": {"endCursor": None, "hasNextPage": False},
                "edges": [{"node": {"name": "Sin variante", "slug": "x", "defaultVariant": None}}],
            }
        }
    }
    products, _, _ = parse_listing(
        payload, store_slug="spdigital", category=CATEGORY, scraped_at=NOW
    )
    assert products == []


def test_respuesta_con_errores_falla_ruidosamente():
    """Un error de GraphQL viaja con HTTP 200: sin este guard sería "0 productos"."""
    with pytest.raises(NotAListingPage):
        parse_listing(
            {"errors": [{"message": "boom"}]},
            store_slug="spdigital",
            category=CATEGORY,
            scraped_at=NOW,
        )


# --- paginación --------------------------------------------------------------


def test_body_pide_por_id_de_categoria_y_solo_con_stock():
    adapter = SpDigitalAdapter(None, [])
    body = adapter._body(CATEGORY, "CURSOR")
    assert body["variables"] == {
        "channel": "sp-digital",
        "first": 50,
        "after": "CURSOR",
        "categories": ["Q2F0ZWdvcnk6MTIzOA=="],
    }
    assert "stockAvailability: IN_STOCK" in body["query"]
    # El orden estable es lo que hace segura la paginación por cursor.
    assert "sortBy: {field: NAME, direction: ASC}" in body["query"]


@pytest.mark.asyncio
async def test_categoria_inexistente_es_error_de_configuracion():
    vacio = json.dumps(
        {"data": {"products": {"edges": [], "pageInfo": {"hasNextPage": False}}}}
    )

    class _Http:
        async def post_json(self, url, payload, **kw):
            return vacio

    adapter = SpDigitalAdapter(_Http(), [])
    with pytest.raises(NotAListingPage):
        async for _ in adapter.discover(CATEGORY):
            pass


@pytest.mark.asyncio
async def test_pagina_con_cursor_y_corte_al_final():
    primera = FIXTURE.read_text(encoding="utf-8")
    ultima = json.dumps(
        {
            "data": {
                "products": {
                    "edges": [],
                    "pageInfo": {"endCursor": None, "hasNextPage": False},
                }
            }
        }
    )

    class _Http:
        def __init__(self):
            self.cursors: list[str | None] = []

        async def post_json(self, url, payload, **kw):
            self.cursors.append(payload["variables"]["after"])
            return primera if len(self.cursors) == 1 else ultima

    http = _Http()
    adapter = SpDigitalAdapter(http, [])
    productos = [p async for p in adapter.discover(CATEGORY)]

    assert len(productos) == 5
    assert http.cursors[0] is None  # la primera página va sin cursor
    assert http.cursors[1]  # la segunda usa el endCursor de la anterior
    assert len(http.cursors) == 2  # cortó al ver hasNextPage=false
