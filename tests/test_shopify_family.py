"""Contract test de la familia Shopify contra un fixture real de Ferretería Prat.

El fixture es la respuesta de producción (2026-09-23) de
`/collections/herramientas-electricas/products.json?limit=250&page=1`, podada a 4
de los 250 productos y a los campos que el parser lee (`handle`, `title`,
`vendor`, la primera imagen y, por variante, `id`/`title`/`sku`/`price`/
`compare_at_price`/`available`).

Los 4 no son los primeros del archivo: se eligieron para cubrir los casos que
distinguen a esta familia —una variante **agotada**, un `vendor` que es la propia
tienda y un producto **sin** `compare_at_price`—. La página 1 tal cual venía los
escondía: de sus 250 variantes, 249 traían `compare_at_price` y las agotadas
aparecen mezcladas más abajo. Es el engaño de fixture que documenta
`PLAN_TIENDAS.md` §5.3.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from scrapers.base import CategoryRef
from scrapers.stores.shopify_family import (
    NotAListingPage,
    PratAdapter,
    parse_listing,
    parse_price,
)

FIXTURE = Path(__file__).parent / "fixtures" / "prat_collection_herramientas.json"
CATEGORY = CategoryRef(
    slug="ferre-herramientas",
    store_key="herramientas-electricas",
    label="Herramientas Eléctricas",
)
NOW = datetime(2026, 9, 23, 12, 0, tzinfo=timezone.utc)
BASE = "https://ferreteriaprat.cl"


@pytest.fixture(scope="module")
def productos():
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    return parse_listing(
        payload,
        store_slug="prat",
        base_url=BASE,
        category=CATEGORY,
        scraped_at=NOW,
        non_brand_vendors=PratAdapter.non_brand_vendors,
    )


def test_parsea_las_cuatro_variantes(productos):
    assert len(productos) == 4
    assert all(p.store_slug == "prat" for p in productos)
    assert all(p.category_path == "ferre-herramientas" for p in productos)


def test_precios_son_enteros_clp(productos):
    for p in productos:
        assert isinstance(p.price_effective, Decimal)
        assert p.price_effective == p.price_effective.to_integral_value()
    assert productos[0].price_effective == Decimal("95076")


def test_el_stock_no_es_ciego(productos):
    """El regalo de esta familia: `available` es stock real, no un True asumido."""
    agotado = [p for p in productos if not p.in_stock]
    assert len(agotado) == 1
    assert agotado[0].price_effective == Decimal("188838")


def test_compare_at_se_guarda_como_normal_declarado(productos):
    """Se persiste como evidencia; el detector no lo mira."""
    assert productos[0].price_normal == Decimal("105640")
    # El que no trae `compare_at_price` queda en None, no en 0 ni en el precio.
    sin_compare = [p for p in productos if p.price_normal is None]
    assert len(sin_compare) == 1
    assert sin_compare[0].brand == "Bosch"


def test_el_descuento_declarado_de_prat_es_un_margen_fijo(productos):
    """Justifica la regla 1 del dominio con el dato de la propia tienda.

    249 de los 250 productos de la página declaraban 10,0% exacto. Si alguna vez
    este test falla, es que Prat cambió de política de precios — no que el parser
    se rompió.
    """
    declarados = [
        (p.price_normal - p.price_effective) / p.price_normal
        for p in productos
        if p.price_normal is not None
    ]
    assert declarados, "el fixture tiene que traer al menos un compare_at_price"
    assert all(abs(d - Decimal("0.10")) < Decimal("0.005") for d in declarados)


def test_el_vendor_basura_no_se_toma_como_marca(productos):
    """`pratcl` es la propia tienda; una marca equivocada degrada el copy."""
    por_marca = {p.brand for p in productos}
    assert "Pratcl" not in por_marca
    assert None in por_marca
    assert "Einhell" in por_marca


def test_no_inventa_identidad(productos):
    """`products.json` no expone `barcode`: GTIN y modelo quedan vacíos."""
    assert all(p.gtin is None and p.model is None for p in productos)


def test_url_apunta_a_la_variante(productos):
    assert productos[0].url.startswith(f"{BASE}/products/")
    assert "?variant=" in productos[0].url


def test_store_sku_es_el_id_de_variante(productos):
    """No el `sku` del comerciante: ver la nota en `parse_listing`."""
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    ids = {str(v["id"]) for p in payload["products"] for v in p["variants"]}
    assert {p.store_sku for p in productos} == ids


@pytest.mark.parametrize(
    "crudo, esperado",
    [
        ("181990", Decimal("181990")),
        (181990, Decimal("181990")),
        ("  95076 ", Decimal("95076")),
        ("0", None),
        ("", None),
        (None, None),
        # El caso que justifica el parser propio: `parse_clp` devolvería 18199000.
        ("181990.00", None),
        ("1819,90", None),
        ("gratis", None),
    ],
)
def test_parse_price_rechaza_decimales(crudo, esperado):
    """Una tienda Shopify en otra moneda sirve `"189.90"`; multiplicar por 100 en
    silencio publicaría una oferta imposible."""
    assert parse_price(crudo) == esperado


def test_payload_sin_lista_products_es_error():
    with pytest.raises(NotAListingPage):
        parse_listing(
            {"errors": "nope"},
            store_slug="prat",
            base_url=BASE,
            category=CATEGORY,
            scraped_at=NOW,
        )


class _Http:
    """Cliente falso: devuelve el fixture en la página 1 y vacío después."""

    def __init__(self, paginas):
        self.paginas = paginas
        self.urls = []

    async def get_text(self, url, **kw):
        self.urls.append(url)
        return self.paginas[len(self.urls) - 1]


VACIA = json.dumps({"products": []})


@pytest.mark.asyncio
async def test_pagina_vacia_despues_de_la_1_es_fin_de_catalogo():
    http = _Http([FIXTURE.read_text(encoding="utf-8"), VACIA])
    productos = [p async for p in PratAdapter(http, []).discover(CATEGORY)]
    assert len(productos) == 4
    assert len(http.urls) == 2  # cortó en la vacía, no siguió hasta max_pages
    assert "limit=250&page=1" in http.urls[0]


@pytest.mark.asyncio
async def test_pagina_1_vacia_es_error_de_configuracion():
    """Shopify devuelve 200 `{"products": []}` también para un handle que no
    existe, así que la página 1 vacía no puede pasar como catálogo agotado."""
    http = _Http([VACIA])
    with pytest.raises(NotAListingPage):
        async for _ in PratAdapter(http, []).discover(CATEGORY):
            pass
