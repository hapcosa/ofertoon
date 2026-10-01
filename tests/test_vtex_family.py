"""La familia VTEX, con Nike como primera tienda.

VTEX es la plataforma de buena parte del retail chileno, así que este módulo
destraba varias tiendas de una (el plan la quería para Colloky y la Fase 3).

El fixture es el payload real de `nike/calzado` capturado el 2026-10-01 contra
`/api/catalog_system/pub/products/search?fq=C:/2/3/`.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from scrapers.base import CategoryRef, CountingAdapter, StoreAdapter
from scrapers.stores.vtex_family import (
    MAX_OFFSET,
    PAGE_SIZE,
    NikeAdapter,
    NotAListingPage,
    _clp,
    _elegir_item,
    parse_listing,
    parse_total,
)

FIXTURE = Path(__file__).parent / "fixtures" / "nike_catalog_calzado.json"
CATEGORY = CategoryRef(slug="ropa-calzado", store_key="2/3", label="Calzado")
AHORA = datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
def payload():
    return json.loads(FIXTURE.read_text())


@pytest.fixture
def productos(payload):
    return parse_listing(payload, store_slug="nike", category=CATEGORY, scraped_at=AHORA)


# --- El contrato con el runner ----------------------------------------------


def test_nike_implementa_los_dos_protocolos():
    """`CountingAdapter` es lo que le da al runner el canario EXACTO.

    Sin él, Nike caería al canario estadístico, que es una inferencia. Con él,
    "enumeró 1.188 de 1.188" es una verdad, no una mediana.
    """
    ad = NikeAdapter.__new__(NikeAdapter)
    assert isinstance(ad, StoreAdapter)
    assert isinstance(ad, CountingAdapter)


def test_el_total_sale_del_header_resources():
    """VTEX no pone el total en el cuerpo: va en `Resources: 0-49/2546`."""
    assert parse_total("0-49/2546") == 2546
    assert parse_total("0-7/1188") == 1188


def test_sin_header_no_se_inventa_un_total():
    """Degradar al canario estadístico es correcto; inventar un total no."""
    assert parse_total(None) is None
    assert parse_total("") is None
    assert parse_total("basura") is None


# --- Parseo contra payload real ---------------------------------------------


def test_parsea_el_fixture_real(productos, payload):
    assert productos, "el fixture real tiene que producir productos"
    assert len(productos) <= len(payload)
    for p in productos:
        assert p.store_slug == "nike"
        assert p.store_sku
        assert p.name
        assert p.price_effective > 0


def test_los_precios_son_clp_ENTEROS(productos):
    """Regla de dominio: nunca float para dinero, en ninguna capa.

    VTEX serializa `119990.0`, y arrastrar ese `.0` a una columna que es entera
    por definición es exactamente lo que esta conversión existe para evitar.
    """
    for p in productos:
        assert isinstance(p.price_effective, Decimal)
        assert p.price_effective == p.price_effective.to_integral_value()
        if p.price_normal is not None:
            assert p.price_normal == p.price_normal.to_integral_value()


def test_el_clp_trunca_el_float_de_vtex():
    assert _clp(119990.0) == Decimal(119990)
    assert _clp("172990.0") == Decimal(172990)
    assert _clp(0) is None       # 0 no es un precio
    assert _clp(None) is None
    assert _clp("no-es-un-precio") is None


def test_trae_ean_que_es_lo_que_alimenta_identidad(productos):
    """El motivo principal para conectar Nike.

    CLAUDE.md: de 3.357 `products` solo 11 tienen 2+ tiendas porque las tiendas
    con GTIN casi no se solapan. Nike trae EAN por talle.
    """
    con_ean = [p for p in productos if p.gtin]
    assert con_ean, "el fixture real trae EAN"
    for p in con_ean:
        assert p.gtin.isdigit()


def test_trae_marca_y_modelo(productos):
    assert all(p.brand for p in productos)
    # `productReference` es el código del fabricante (CW2288-111), que es lo que
    # usa `catalog/identity` como modelo cuando no hay GTIN.
    assert any(p.model for p in productos)


def test_price_normal_solo_cuando_de_verdad_es_mayor(productos):
    """VTEX repite el mismo valor en Price y ListPrice cuando no hay descuento.

    Guardar un "antes" igual al "ahora" ensuciaría la evidencia de cuánto miente
    cada tienda, que es para lo único que `price_normal` existe.
    """
    for p in productos:
        if p.price_normal is not None:
            assert p.price_normal > p.price_effective


# --- Un producto por producto, no por talle ---------------------------------


def test_un_producto_por_producto_y_no_uno_por_talle(payload, productos):
    """Un zapato son 10 talles al mismo precio.

    Uno por talle multiplicaría los listings por 10 con series idénticas y haría
    pesar al mismo producto diez veces en cualquier agregado.
    """
    talles = sum(len(p.get("items") or []) for p in payload)
    assert talles > len(payload), "el fixture real tiene productos con varios talles"
    assert len(productos) <= len(payload)


def test_gana_el_talle_disponible_mas_barato():
    """Tomar el precio de un talle agotado publica un precio que nadie puede pagar."""
    def item(iid, precio, disponible):
        return {"itemId": iid, "ean": "1", "sellers": [{"commertialOffer": {
            "Price": precio, "ListPrice": precio,
            "IsAvailable": disponible,
            "AvailableQuantity": 5 if disponible else 0}}]}

    elegido = _elegir_item([item("agotado", 50000, False), item("vivo", 90000, True)])
    assert elegido["itemId"] == "vivo"

    # Entre dos disponibles gana el más barato.
    elegido = _elegir_item([item("caro", 90000, True), item("barato", 70000, True)])
    assert elegido["itemId"] == "barato"


def test_sin_ningun_disponible_igual_se_toma_el_mas_barato():
    """El producto se registra con precio aunque esté agotado.

    La serie tiene que seguir existiendo: el detector ya rechaza por stock, y un
    agujero en la serie es peor que un punto que el detector va a descartar.
    """
    def item(iid, precio):
        return {"itemId": iid, "sellers": [{"commertialOffer": {
            "Price": precio, "IsAvailable": False, "AvailableQuantity": 0}}]}

    assert _elegir_item([item("a", 90000), item("b", 70000)])["itemId"] == "b"


def test_in_stock_mira_todos_los_talles():
    """El producto es comprable si ALGÚN talle lo está."""
    payload = [{
        "productId": "1", "productName": "Zapatilla", "link": "https://x/p",
        "brand": "Nike",
        "items": [
            {"itemId": "s1", "sellers": [{"commertialOffer": {
                "Price": 50000, "IsAvailable": False, "AvailableQuantity": 0}}]},
            {"itemId": "s2", "sellers": [{"commertialOffer": {
                "Price": 50000, "IsAvailable": True, "AvailableQuantity": 3}}]},
        ],
    }]
    p = parse_listing(payload, store_slug="nike", category=CATEGORY, scraped_at=AHORA)[0]
    assert p.in_stock is True

    payload[0]["items"][1]["sellers"][0]["commertialOffer"].update(
        IsAvailable=False, AvailableQuantity=0
    )
    p = parse_listing(payload, store_slug="nike", category=CATEGORY, scraped_at=AHORA)[0]
    assert p.in_stock is False


# --- Descartes ---------------------------------------------------------------


def test_un_producto_sin_oferta_se_descarta():
    """VTEX deja productos publicados sin oferta activa: no hay qué medir."""
    payload = [{"productId": "1", "productName": "X", "items": [{"itemId": "s", "sellers": []}]}]
    assert parse_listing(payload, store_slug="nike", category=CATEGORY, scraped_at=AHORA) == []


def test_un_centinela_de_precio_no_tumba_la_categoria(caplog):
    """El techo de plausibilidad rechaza el producto, no la corrida."""
    payload = [
        {"productId": "1", "productName": "Centinela", "link": "https://x/p", "items": [
            {"itemId": "s1", "sellers": [{"commertialOffer": {
                "Price": 99999999999, "IsAvailable": True, "AvailableQuantity": 1}}]}]},
        {"productId": "2", "productName": "Normal", "link": "https://x/q", "items": [
            {"itemId": "s2", "sellers": [{"commertialOffer": {
                "Price": 59990, "IsAvailable": True, "AvailableQuantity": 1}}]}]},
    ]
    out = parse_listing(payload, store_slug="nike", category=CATEGORY, scraped_at=AHORA)
    assert [p.store_sku for p in out] == ["s2"]


# --- Paginación y guardas ---------------------------------------------------


class FakeHttp:
    """Sirve páginas y devuelve el header `Resources` como lo hace VTEX."""

    def __init__(self, paginas, total=None):
        self.paginas = paginas
        self.total = total if total is not None else sum(len(p) for p in paginas)
        self.urls = []

    async def get_with_headers(self, url, *, rps=None, headers=None):
        self.urls.append(url)
        i = len(self.urls) - 1
        pag = self.paginas[i] if i < len(self.paginas) else []
        desde = i * PAGE_SIZE
        hasta = desde + max(0, len(pag) - 1)
        return json.dumps(pag), {"resources": f"{desde}-{hasta}/{self.total}"}


def _prod(pid, precio=50000):
    return {"productId": str(pid), "productName": f"P{pid}", "link": f"https://x/{pid}",
            "brand": "Nike", "items": [{"itemId": f"s{pid}", "ean": "1234567890123",
            "sellers": [{"commertialOffer": {"Price": precio, "ListPrice": precio,
            "IsAvailable": True, "AvailableQuantity": 5}}]}]}


async def _recoger(ad, cat):
    return [p async for p in ad.discover(cat)]


@pytest.mark.asyncio
async def test_pagina_hasta_que_la_pagina_viene_corta():
    http = FakeHttp([[_prod(i) for i in range(PAGE_SIZE)], [_prod(100), _prod(101)]])
    ad = NikeAdapter(http, [CATEGORY])
    out = await _recoger(ad, CATEGORY)
    assert len(out) == PAGE_SIZE + 2
    assert "_from=0&_to=49" in http.urls[0]
    assert "_from=50&_to=99" in http.urls[1]


@pytest.mark.asyncio
async def test_completeness_compara_enumerado_contra_el_header():
    http = FakeHttp([[_prod(i) for i in range(3)]], total=3)
    ad = NikeAdapter(http, [CATEGORY])
    await _recoger(ad, CATEGORY)
    assert ad.completeness(CATEGORY) == (3, 3)


@pytest.mark.asyncio
async def test_completeness_delata_una_paginacion_incompleta():
    """Lo que el canario exacto existe para ver."""
    http = FakeHttp([[_prod(i) for i in range(3)]], total=99)
    ad = NikeAdapter(http, [CATEGORY])
    await _recoger(ad, CATEGORY)
    assert ad.completeness(CATEGORY) == (3, 99)


@pytest.mark.asyncio
async def test_store_key_malo_revienta_en_la_primera_pagina():
    """Una categoría vacía en la página 1 es un `store_key` mal configurado.

    Es el mismo guard que el resto de las familias: sin él, una llave mal escrita
    ingiere cero productos **sin un solo error**, que es el fallo que más caro
    sale porque no se nota.
    """
    http = FakeHttp([[]], total=0)
    ad = NikeAdapter(http, [CATEGORY])
    with pytest.raises(NotAListingPage):
        await _recoger(ad, CATEGORY)


@pytest.mark.asyncio
async def test_una_respuesta_que_no_es_lista_tambien_revienta():
    class Raro:
        async def get_with_headers(self, url, *, rps=None, headers=None):
            return json.dumps({"error": "nope"}), {}

    ad = NikeAdapter(Raro(), [CATEGORY])
    with pytest.raises(NotAListingPage):
        await _recoger(ad, CATEGORY)


@pytest.mark.asyncio
async def test_una_pagina_repetida_corta_la_paginacion():
    """Síntoma de una tienda que dejó de respetar `_from`."""
    pag = [_prod(i) for i in range(PAGE_SIZE)]
    http = FakeHttp([pag, pag, pag], total=999)
    ad = NikeAdapter(http, [CATEGORY])
    out = await _recoger(ad, CATEGORY)
    assert len(out) == PAGE_SIZE      # la segunda no aportó nada nuevo
    assert len(http.urls) == 2        # y no se pidió una tercera


@pytest.mark.asyncio
async def test_manda_headers_de_navegador():
    """Con el UA por defecto, Nike responde 403. Verificado el 2026-10-01."""
    vistos = []

    class Espia(FakeHttp):
        async def get_with_headers(self, url, *, rps=None, headers=None):
            vistos.append(headers)
            return await super().get_with_headers(url, rps=rps, headers=headers)

    ad = NikeAdapter(Espia([[_prod(1)]]), [CATEGORY])
    await _recoger(ad, CATEGORY)
    assert vistos[0]["Accept"] == "application/json"
    assert "ofertascl-bot" not in vistos[0]["User-Agent"]


def test_el_tope_de_paginacion_de_vtex_esta_declarado():
    """VTEX no deja paginar más profundo que ~2.500: una categoría más grande se
    parte en subcategorías, y el canario exacto lo grita solo."""
    assert MAX_OFFSET == 2500
