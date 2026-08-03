"""Contract test del adaptador PC Factory contra un fixture real.

El fixture es la respuesta JSON de producción (2026-07-31) para
`categorias=Smartphones&page=0&size=48`, recortada a 6 de los 48 productos: los
4 primeros (con precio de referencia) más los dos que la tienda publica **sin**
referencia, que es el caso que distingue "hay un antes" de "no lo hay".

Se recortó `items`; el bloque `pageable` quedó tal cual lo sirvió la tienda
(`totalElements: 38`), por eso el test de conteo y el de total no coinciden — es
deliberado y sirve para verificar que el parser lee la paginación de `pageable`
y no del largo de la lista.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from scrapers.base import CategoryRef
from scrapers.stores.pcfactory import (
    NotAListingPage,
    PcFactoryAdapter,
    parse_listing,
    resolve_prices,
)

FIXTURE = Path(__file__).parent / "fixtures" / "pcfactory_listing_smartphones.json"
CATEGORY = CategoryRef(slug="tecno", store_key="Smartphones", label="Smartphones")
NOW = datetime(2026, 7, 31, 12, 0, tzinfo=timezone.utc)


@pytest.fixture(scope="module")
def parsed():
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    return parse_listing(payload, store_slug="pcfactory", category=CATEGORY, scraped_at=NOW)


def test_extrae_todos_los_productos(parsed):
    products, page, total_pages = parsed
    assert len(products) == 6
    assert page == 0  # la API es 0-indexada
    assert total_pages == 1


def test_campos_obligatorios_no_nulos(parsed):
    products, _, _ = parsed
    for p in products:
        assert p.store_sku.isdigit()
        assert p.url.startswith("https://www.pcfactory.cl/producto/")
        assert p.name
        assert p.price_effective > 0
        assert p.brand
        assert p.image_url.startswith("https://assets.pcfactory.cl/")
        assert p.in_stock
        assert p.scraped_at == NOW


def test_efectivo_es_el_precio_grande_no_el_de_credito(parsed):
    """`normal` en PC Factory es el precio con CRÉDITO, y es más caro.

    Es la trampa nominal de esta tienda: en Falabella y Easy `normalPrice` es el
    "antes" tachado; acá `normal` es un precio de hoy más alto. Tomarlo como
    efectivo publicaría un precio que nadie paga, y tomarlo como "antes"
    inventaría un descuento de ~3% en cada producto del catálogo.
    """
    products, _, _ = parsed
    moto = next(p for p in products if p.store_sku == "56783")
    assert moto.price_effective == Decimal("289990")  # efectivo
    assert moto.price_normal == Decimal("419990")  # referencia, el antes real
    # 298990 (`normal`, crédito) no aparece en ningún campo persistido.
    assert Decimal("298990") not in (moto.price_effective, moto.price_normal, moto.price_card)


def test_sin_referencia_no_hay_antes(parsed):
    """`referencia: 0` = la tienda no declara precio anterior."""
    products, _, _ = parsed
    zte = next(p for p in products if p.store_sku == "50037")
    assert zte.price_effective == Decimal("92490")
    assert zte.price_normal is None


def test_banco_estado_es_precio_tarjeta_no_efectivo():
    """La "Oferta BancoEstado" exige plástico de un banco: se muestra, no se compara.

    Hoy viene 0 en todo el catálogo muestreado, pero el mapeo tiene que estar
    bien el día que la tienda la active — si entrara como efectivo, el detector
    vería descuentos que el comprador promedio no puede pagar.
    """
    effective, claimed, card = resolve_prices(
        {"efectivo": 100000, "normal": 105000, "referencia": 150000, "bancoEstado": 89990}
    )
    assert effective == Decimal("100000")
    assert claimed == Decimal("150000")
    assert card == Decimal("89990")


def test_marca_normalizada(parsed):
    products, _, _ = parsed
    samsung = next(p for p in products if p.store_sku == "47713")
    assert samsung.brand == "Samsung"


def test_listado_no_declara_descuento(parsed):
    """La API del listado no trae el % (sí el detalle). No se inventa uno.

    `claimed_discount` es lo que la tienda DECLARA; derivarlo nosotros mezclaría
    evidencia con cálculo propio.
    """
    products, _, _ = parsed
    assert all(p.claimed_discount is None for p in products)


# --- resolve_prices: casos que el fixture no cubre ---------------------------


def test_resolve_prices_bloque_vacio():
    assert resolve_prices({}) == (None, None, None)


def test_resolve_prices_referencia_menor_no_es_antes():
    effective, claimed, _ = resolve_prices({"efectivo": 50000, "referencia": 40000})
    assert effective == Decimal("50000")
    assert claimed is None


def test_resolve_prices_sin_efectivo_cae_al_credito():
    """Si falta el efectivo, el crédito es lo único pagable conocido."""
    effective, _, _ = resolve_prices({"efectivo": 0, "normal": 105000})
    assert effective == Decimal("105000")


def test_producto_sin_precio_se_descarta():
    payload = {
        "content": {
            "items": [{"id": 1, "slug": "x", "nombre": "Sin precio", "precio": {}}],
            "pageable": {"pageNumber": 0, "totalPages": 1},
        }
    }
    products, _, _ = parse_listing(
        payload, store_slug="pcfactory", category=CATEGORY, scraped_at=NOW
    )
    assert products == []


def test_respuesta_sin_items_falla_ruidosamente():
    """Un 422 o un cambio de contrato no puede verse como "categoría vacía"."""
    with pytest.raises(NotAListingPage):
        parse_listing({"message": "error"}, store_slug="pcfactory", category=CATEGORY, scraped_at=NOW)


# --- stock -------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw,esperado",
    [("+100", True), ("+30", True), ("1", True), ("0", False), ("", False), (None, False)],
)
def test_stock(raw, esperado):
    from scrapers.stores.pcfactory import _in_stock

    assert _in_stock(raw) is esperado


# --- paginación --------------------------------------------------------------


def test_url_usa_search_comodin_y_nombre_de_categoria():
    """`search` es obligatorio (sin él: HTTP 422) y `categorias` filtra por nombre."""
    adapter = PcFactoryAdapter(None, [])
    url = adapter._page_url(CategoryRef(slug="tecno", store_key="Tarjetas Gráficas NVIDIA"), 2)
    assert "search=*" in url
    assert "categorias=Tarjetas%20Gr%C3%A1ficas%20NVIDIA" in url
    assert "page=2" in url and "size=48" in url


@pytest.mark.asyncio
async def test_pagina_vacia_corta_la_paginacion():
    """Pasado el final la API devuelve `items: []` con HTTP 200, sin error."""
    fixture = FIXTURE.read_text(encoding="utf-8")
    vacio = json.dumps({"content": {"items": [], "pageable": {"pageNumber": 1, "totalPages": 9}}})

    class _Http:
        def __init__(self):
            self.calls = 0

        async def get_text(self, url, **kw):
            self.calls += 1
            return fixture if self.calls == 1 else vacio

    http = _Http()
    # totalPages=1 en el fixture ya cortaría; se fuerza el caso pidiendo el
    # escenario contrario con un adaptador que sigue hasta encontrar el vacío.
    adapter = PcFactoryAdapter(http, [])
    productos = [p async for p in adapter.discover(CATEGORY)]
    assert len(productos) == 6
    assert http.calls == 1  # cortó por totalPages, sin gastar un request de más


@pytest.mark.asyncio
async def test_paginacion_ignorada_corta_en_vez_de_repetir():
    """Si la API sirve siempre la misma página, seguir solo gasta requests.

    Es la degradación que tendría un endpoint que ignora `page`: sin este guard
    el adaptador leería 25 veces lo mismo antes de rendirse.
    """
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    payload["content"]["pageable"]["totalPages"] = 9
    fixture = json.dumps(payload)

    class _Http:
        def __init__(self):
            self.calls = 0

        async def get_text(self, url, **kw):
            self.calls += 1
            return fixture  # siempre pageNumber=0

    http = _Http()
    adapter = PcFactoryAdapter(http, [])
    productos = [p async for p in adapter.discover(CATEGORY)]
    assert len(productos) == 6
    assert http.calls == 2  # pidió la 1, vio que servía la 0, cortó
