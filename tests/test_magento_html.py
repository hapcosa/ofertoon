"""Contract test de la familia Magento HTML contra fixtures reales de Kupfer.

Los tres fixtures son HTML de producción capturado el 2026-09-24 con
`?product_list_limit=36`, y cada uno existe por un caso distinto:

- `kupfer_taladros_rotomartillos.html` — la página **entera**, sin recortar, de
  una categoría que declara 5 productos y trae 5. Es el caso sano y el único que
  puede probar que `completeness()` dice `ok`, para lo que enumerados y
  declarados tienen que coincidir de verdad. Uno de sus precios
  (`2424922.500001` → `$2.424.923`) cae justo en el medio punto y fija el
  redondeo.
- `kupfer_categoria_paginada.html` — 2 de las 36 filas de una categoría que
  declara 118, con su paginador real. Es el caso que esta familia NO resuelve:
  no pagina porque el `robots.txt` de Kupfer prohíbe `?p=`, así que lo reporta.
  Recortado a 2 filas a propósito (una con marca, una sin).
- `kupfer_categoria_vacia.html` — una categoría que existe y no tiene productos.
  Magento no devuelve un grid vacío: devuelve el mensaje "No podemos encontrar
  productos" y ningún `<ol>`. Sin distinguir ese caso, una categoría vacía se
  vería igual que una llave mal escrita.
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from scrapers.base import CategoryRef
from scrapers.runner import canary_verdict
from scrapers.stores.magento_html import (
    PAGE_SIZE,
    KupferAdapter,
    NotAListingPage,
    parse_listing,
    parse_price,
)

FIXTURES = Path(__file__).parent / "fixtures"
COMPLETA = FIXTURES / "kupfer_taladros_rotomartillos.html"
PAGINADA = FIXTURES / "kupfer_categoria_paginada.html"
VACIA = FIXTURES / "kupfer_categoria_vacia.html"

CATEGORY = CategoryRef(
    slug="ferre-herramientas",
    store_key="equipos-herramientas-y-maquinarias-industriales/herramientas-electricas.html",
    label="Herramientas eléctricas",
)
NOW = datetime(2026, 9, 24, 15, 0, tzinfo=timezone.utc)


def _parse(path: Path):
    return parse_listing(
        path.read_text(encoding="utf-8"),
        store_slug="kupfer",
        category=CATEGORY,
        scraped_at=NOW,
    )


@pytest.fixture(scope="module")
def completa():
    return _parse(COMPLETA)


def test_parsea_las_cinco_filas(completa):
    productos, enumerados, declarados = completa
    assert len(productos) == 5
    assert (enumerados, declarados) == (5, 5)
    assert all(p.store_slug == "kupfer" for p in productos)
    assert all(p.category_path == "ferre-herramientas" for p in productos)
    assert all(p.scraped_at == NOW for p in productos)


def test_el_sku_es_el_de_la_tienda_sin_el_prefijo(completa):
    """`<span class="product-item-sku">SKU: 114564</span>` → `114564`.

    No el id interno del `<div id="product-item-info_16211">`: el SKU es el
    código de artículo de la empresa y sobrevive a una reindexación.
    """
    productos, _, _ = completa
    assert [p.store_sku for p in productos] == [
        "114564",
        "9830",
        "109904",
        "116937",
        "168942",
    ]


def test_precios_enteros_y_redondeados_como_los_muestra_la_tienda(completa):
    """El `data-price-amount` trae decimales; el CLP que se guarda es entero.

    Los cinco valores del fixture son el neto por 1,19 con la basura del float de
    PHP encima (`1137035.480001`). El entero esperado es el que la tienda
    imprime en su propio `<span class="price">`, incluido el `.500001` que cae
    justo en el medio punto y que por eso sube.
    """
    productos, _, _ = completa
    assert [p.price_effective for p in productos] == [
        Decimal("1137035"),  # 1137035.480001 → $1.137.035
        Decimal("185309"),  # 185309.180001  → $185.309
        Decimal("109318"),  # 109318.160001  → $109.318
        Decimal("2424923"),  # 2424922.500001 → $2.424.923  ← el medio punto
        Decimal("2911631"),  # 2911631.310001 → $2.911.631
    ]
    for p in productos:
        assert p.price_effective == p.price_effective.to_integral_value()


def test_sin_descuento_declarado_no_se_inventa_uno(completa):
    """El grid solo trae `oldPrice` cuando hay `special_price` cargado."""
    productos, _, _ = completa
    assert all(p.price_normal is None for p in productos)
    assert all(p.price_card is None for p in productos)
    assert all(p.claimed_discount is None for p in productos)


def test_la_etiqueta_del_grid_es_el_stock(completa):
    productos, _, _ = completa
    assert all(p.in_stock for p in productos)


def test_esta_familia_no_aporta_identidad(completa):
    """El grid de Magento no expone GTIN ni modelo — solo marca, a veces."""
    productos, _, _ = completa
    assert all(p.gtin is None for p in productos)
    assert all(p.model is None for p in productos)


def test_la_marca_se_lee_cuando_la_tienda_la_llena():
    """`<span class="product-item-brand">` existe siempre y viene vacío seguido.

    En las tres categorías auditadas la cobertura fue de 8 de 24, 6 de 12 y 1 de
    36, así que el vacío es el caso común y no puede ser un error.
    """
    productos, _, _ = _parse(PAGINADA)
    marcas = {p.store_sku: p.brand for p in productos}
    assert marcas == {"196889": None, "143985": "Loctite"}


# -----------------------------------------------------------------------------
# Lo que esta familia NO resuelve, y por eso tiene que reportar
# -----------------------------------------------------------------------------


def test_la_categoria_que_no_entra_en_una_pagina_queda_declarada_incompleta():
    """118 declarados contra lo que trajo una sola request.

    No se pagina por decisión: el `robots.txt` de Kupfer prohíbe `/*?p=`. Lo que
    no se puede hacer es traer 36 de 118 y que se vea sano, porque el canario
    estadístico vería 36 items estables en cada pasada y nunca se quejaría.
    """
    _, enumerados, declarados = _parse(PAGINADA)
    assert declarados == 118
    assert enumerados < declarados

    status, motivo = canary_verdict(
        enumerados, [], completeness=(enumerados, declarados)
    )
    assert status == "partial"
    assert "118" in motivo


def test_la_categoria_completa_pasa_el_canario_exacto(completa):
    _, enumerados, declarados = completa
    assert canary_verdict(enumerados, [], completeness=(enumerados, declarados)) == (
        "ok",
        None,
    )


def test_una_categoria_vacia_no_es_un_error_de_configuracion():
    """Existe y no tiene productos: cero filas, sin excepción.

    Es un dato del catálogo y lo reporta el canario por el piso de items, no una
    llave mal escrita. Magento no sirve un grid vacío para esto: no sirve grid.
    """
    productos, enumerados, declarados = _parse(VACIA)
    assert (productos, enumerados, declarados) == ([], 0, None)
    assert canary_verdict(0, [])[0] == "partial"


def test_una_pagina_sin_grid_ni_mensaje_es_error_de_configuracion():
    """Un landing de CMS o una redirección a la home: ruidoso a propósito."""
    with pytest.raises(NotAListingPage):
        parse_listing(
            "<!doctype html><html><body><h1>Kupfer</h1></body></html>",
            store_slug="kupfer",
            category=CATEGORY,
            scraped_at=NOW,
        )


def test_solo_se_parsea_el_grid_y_no_los_carruseles():
    """`product-item` aparece también en "relacionados" y "más vendidos".

    En Construmart la página trae 26 y el grid 20. Anclar el parseo al `<ol>` es
    lo que evita ingerir productos que no son de la categoría.
    """
    html = COMPLETA.read_text(encoding="utf-8")
    carrusel = (
        '<ol class="products list items"><li class="item product product-item">'
        '<a class="product-item-link" href="https://kupfer.cl/intruso-1.html">'
        "INTRUSO</a><span class=\"product-item-sku\">SKU: 999999</span>"
        '<span data-price-type="finalPrice" data-price-amount="1000"></span>'
        "</li></ol>"
    )
    productos, enumerados, _ = parse_listing(
        html.replace("</body>", carrusel + "</body>"),
        store_slug="kupfer",
        category=CATEGORY,
        scraped_at=NOW,
    )
    assert enumerados == 5
    assert "999999" not in {p.store_sku for p in productos}


@pytest.mark.parametrize(
    "crudo, esperado",
    [
        ("4442.270001", Decimal("4442")),
        # El medio punto sube, que es como lo redondea la tienda.
        ("2424922.500001", Decimal("2424923")),
        ("8687.000001", Decimal("8687")),
        # Un centinela como el de Falabella no se filtra acá sino en el parser,
        # pero tampoco se convierte en basura.
        ("99999999999", Decimal("99999999999")),
        ("0", None),
        ("-1500", None),
        ("", None),
        (None, None),
        ("consultar", None),
    ],
)
def test_parse_price(crudo, esperado):
    assert parse_price(crudo) == esperado


def test_el_centinela_no_entra_al_catalogo():
    """Por encima de `MAX_PLAUSIBLE_CLP` no es un precio: es un placeholder."""
    html = COMPLETA.read_text(encoding="utf-8").replace(
        'data-price-amount="185309.180001"', 'data-price-amount="99999999999"'
    )
    productos, enumerados, _ = parse_listing(
        html, store_slug="kupfer", category=CATEGORY, scraped_at=NOW
    )
    assert enumerados == 5, "la fila se enumeró"
    assert len(productos) == 4, "pero no se emitió"
    assert "9830" not in {p.store_sku for p in productos}


# -----------------------------------------------------------------------------
# El adaptador
# -----------------------------------------------------------------------------


class _Http:
    """Devuelve las respuestas en orden, una por request."""

    def __init__(self, *respuestas: str) -> None:
        self.respuestas = respuestas
        self.urls: list[str] = []

    async def get_text(self, url: str, **kw: object) -> str:
        self.urls.append(url)
        return self.respuestas[min(len(self.urls), len(self.respuestas)) - 1]


@pytest.mark.asyncio
async def test_una_categoria_es_una_sola_request():
    http = _Http(COMPLETA.read_text(encoding="utf-8"))
    adapter = KupferAdapter(http, [CATEGORY])

    productos = [p async for p in adapter.discover(CATEGORY)]

    assert len(productos) == 5
    assert http.urls == [
        "https://kupfer.cl/equipos-herramientas-y-maquinarias-industriales/"
        f"herramientas-electricas.html?product_list_limit={PAGE_SIZE}"
    ]
    assert "?p=" not in http.urls[0], "el robots.txt de Kupfer prohíbe ?p="


@pytest.mark.asyncio
async def test_el_adaptador_expone_la_completitud_de_la_ultima_corrida():
    http = _Http(PAGINADA.read_text(encoding="utf-8"))
    adapter = KupferAdapter(http, [CATEGORY])

    assert adapter.completeness(CATEGORY) is None, "antes de correr no se sabe"
    _ = [p async for p in adapter.discover(CATEGORY)]
    assert adapter.completeness(CATEGORY) == (2, 118)


@pytest.mark.asyncio
async def test_la_completitud_no_arrastra_el_valor_de_la_pasada_anterior():
    """Si una corrida no puede saber el total, no hereda el de la anterior."""
    http = _Http(
        PAGINADA.read_text(encoding="utf-8"), VACIA.read_text(encoding="utf-8")
    )
    adapter = KupferAdapter(http, [CATEGORY])

    _ = [p async for p in adapter.discover(CATEGORY)]
    assert adapter.completeness(CATEGORY) == (2, 118)

    _ = [p async for p in adapter.discover(CATEGORY)]
    assert adapter.completeness(CATEGORY) is None
