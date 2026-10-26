"""Contract test del adaptador Ferretek contra un fixture real.

El fixture es la respuesta de `/rest/V1/products` de producción (2026-09-23)
para `category_id=738` (Herramientas Eléctricas), podada a 4 de los 100 items de
la página y, dentro de cada uno, a los `custom_attributes` que el parser lee (de
los ~35 que sirve la tienda). `total_count: 801` es el real, por eso no coincide
con los 4 items del archivo.

Los 4 cubren los caminos que deciden si un producto se publica o no: uno
**publicado sin special**, uno **publicado con special vigente**, uno **no
publicado** (`status = 2`) y uno con el **special vencido** (su ventana cerró el
2026-09-03). Los dos últimos son los que más importan: registrarles un precio
inventaría la serie de un producto que la tienda no vende a ese valor.
"""
from __future__ import annotations

import json
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from scrapers.base import CategoryRef
from scrapers.stores.ferretek import (
    FerretekAdapter,
    NotAListingPage,
    parse_listing,
    parse_price,
    resolve_prices,
)

FIXTURE = Path(__file__).parent / "fixtures" / "ferretek_categoria_electricas.json"
CATEGORY = CategoryRef(
    slug="ferre-herramientas", store_key="738", label="Herramientas Eléctricas"
)
NOW = datetime(2026, 9, 23, 12, 0, tzinfo=timezone.utc)
BRANDS = {"165": "BOSCH", "354": "NICHOLSON"}


@pytest.fixture(scope="module")
def parsed():
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    return parse_listing(
        payload,
        store_slug="ferretek",
        category=CATEGORY,
        scraped_at=NOW,
        brands=BRANDS,
    )


def test_descarta_lo_no_publicado(parsed):
    """`status = 2` no es "sin stock": la ficha devuelve 404.

    De los 4 items del fixture, 2 tienen `status = 2` y ninguno debe emitirse.
    """
    productos, enumerados, declarados = parsed
    assert len(productos) == 2
    # Enumerados cuenta lo que trajo la paginación, no lo emitido: el descarte
    # por `status` es decisión nuestra y no puede romper el chequeo de
    # completitud del runner.
    assert enumerados == 4
    assert declarados == 801


def test_el_special_vigente_es_el_precio_efectivo(parsed):
    """Verificado contra la ficha: sirve data-price-amount 103000 y 123220."""
    productos, _, _ = parsed
    con_special = [p for p in productos if p.price_normal is not None]
    assert len(con_special) == 1
    assert con_special[0].price_effective == Decimal("103000")
    assert con_special[0].price_normal == Decimal("123220")


def test_sin_special_no_inventa_un_normal(parsed):
    productos, _, _ = parsed
    sin_special = [p for p in productos if p.price_normal is None]
    assert len(sin_special) == 1
    assert sin_special[0].price_effective == Decimal("246440")


def test_trae_gtin_y_marca_resuelta(parsed):
    """El regalo de esta tienda: GTIN en el 97% y marca en el 100% (medido)."""
    productos, _, _ = parsed
    assert all(p.gtin is not None for p in productos)
    assert productos[0].gtin == "3165140750691"
    # `marca` llega como id de opción (165), no como texto.
    assert productos[0].brand == "Bosch"


def test_la_url_lleva_sufijo_html(parsed):
    """Sin `.html` Magento responde 404 (verificado en vivo)."""
    productos, _, _ = parsed
    assert all(p.url.startswith("https://ferretek.cl/") for p in productos)
    assert all(p.url.endswith(".html") for p in productos)


def test_el_stock_es_ciego_y_se_declara_asi(parsed):
    """El payload no trae stock; se asume True como en Paris y Falabella."""
    productos, _, _ = parsed
    assert all(p.in_stock for p in productos)


# --- vigencia del special --------------------------------------------------
# Los valores son los del producto real `4138950`: $62.220 con special de
# $52.890 vigente sólo del 2026-08-31 al 2026-09-03.
VENTANA = {
    "special_price": "52890.000000",
    "special_from_date": "2026-08-31 00:00:00",
    "special_to_date": "2026-09-03 00:00:00",
}


@pytest.mark.parametrize(
    "hoy, efectivo, normal",
    [
        # Dentro de la ventana: manda el special.
        (date(2026, 9, 1), Decimal("52890"), Decimal("62220")),
        (date(2026, 8, 31), Decimal("52890"), Decimal("62220")),
        (date(2026, 9, 3), Decimal("52890"), Decimal("62220")),
        # Antes de que arranque y después de que venza: manda el precio base.
        (date(2026, 8, 30), Decimal("62220"), None),
        (date(2026, 9, 23), Decimal("62220"), None),
    ],
)
def test_el_special_solo_vale_dentro_de_su_ventana(hoy, efectivo, normal):
    """Publicar un special vencido sería publicar un precio que nadie cobra."""
    assert resolve_prices(VENTANA, 62220, today=hoy) == (efectivo, normal)


def test_special_sin_fechas_vale_siempre():
    assert resolve_prices({"special_price": "103000"}, 123220, today=date(2026, 9, 23)) == (
        Decimal("103000"),
        Decimal("123220"),
    )


def test_special_mayor_al_precio_no_es_descuento():
    assert resolve_prices({"special_price": "999999"}, 123220, today=date(2026, 9, 23)) == (
        Decimal("123220"),
        None,
    )


def test_sin_precio_base_no_hay_nada_que_publicar():
    """El special es un descuento *sobre* algo."""
    assert resolve_prices({"special_price": "103000"}, None, today=date(2026, 9, 23)) == (
        None,
        None,
    )


@pytest.mark.parametrize(
    "crudo, esperado",
    [
        ("103000.000000", Decimal("103000")),
        (123220, Decimal("123220")),
        ("0", None),
        (None, None),
        # CLP no tiene decimales: redondear publicaría un precio que la ficha
        # no muestra.
        ("103000.500000", None),
        ("gratis", None),
    ],
)
def test_parse_price(crudo, esperado):
    assert parse_price(crudo) == esperado


class _Http:
    def __init__(self, paginas):
        self.paginas = paginas
        self.urls = []

    async def get_text(self, url, **kw):
        self.urls.append(url)
        if "attributes/marca" in url:
            return json.dumps({"options": [{"value": "165", "label": "BOSCH"}]})
        return self.paginas[len([u for u in self.urls if "attributes" not in u]) - 1]


@pytest.mark.asyncio
async def test_corta_cuando_enumero_todo_lo_declarado():
    """`total_count` convierte el canario estadístico en un chequeo exacto."""
    pagina = json.loads(FIXTURE.read_text(encoding="utf-8"))
    pagina["total_count"] = 4  # el fixture trae sus 4 items: una sola página
    http = _Http([json.dumps(pagina)])
    adapter = FerretekAdapter(http, [])
    productos = [p async for p in adapter.discover(CATEGORY)]

    assert len(productos) == 2
    assert adapter.completeness(CATEGORY) == (4, 4)
    # marca + una sola página de catálogo: no siguió pidiendo de más.
    assert len([u for u in http.urls if "attributes" not in u]) == 1


@pytest.mark.asyncio
async def test_categoria_inexistente_es_error_de_configuracion():
    """Magento devuelve 200 con `items: []`, pero `total_count: 0` la delata."""
    http = _Http([json.dumps({"items": [], "total_count": 0})])
    with pytest.raises(NotAListingPage):
        async for _ in FerretekAdapter(http, []).discover(CATEGORY):
            pass


@pytest.mark.asyncio
async def test_la_marca_irresoluble_no_tumba_la_corrida():
    """Sin marca el producto se publica igual: solo pierde una línea del copy."""

    class _RompeMarca(_Http):
        async def get_text(self, url, **kw):
            if "attributes/marca" in url:
                raise RuntimeError("503")
            return await super().get_text(url, **kw)

    pagina = json.loads(FIXTURE.read_text(encoding="utf-8"))
    pagina["total_count"] = 4
    productos = [
        p
        async for p in FerretekAdapter(_RompeMarca([json.dumps(pagina)]), []).discover(
            CATEGORY
        )
    ]
    assert len(productos) == 2
    assert all(p.brand is None for p in productos)


def test_respuesta_sin_items_es_error():
    with pytest.raises(NotAListingPage):
        parse_listing(
            {"message": "no autorizado"},
            store_slug="ferretek",
            category=CATEGORY,
            scraped_at=NOW,
        )
