"""Contract test de la familia Magento HTML contra fixtures reales.

Cinco fixtures de producción capturados el 2026-09-24, cada uno por un caso que
las dos tiendas de la familia resuelven distinto.

De **Kupfer** (`?product_list_limit=36`, sin paginar porque su robots prohíbe `?p=`):

- `kupfer_taladros_rotomartillos.html` — la página **entera**, sin recortar, de
  una categoría que declara 5 productos y trae 5. Es el caso sano y el único que
  puede probar que `completeness()` dice `ok`, para lo que enumerados y
  declarados tienen que coincidir de verdad. Uno de sus precios
  (`2424922.500001` → `$2.424.923`) cae justo en el medio punto y fija el
  redondeo.
- `kupfer_categoria_paginada.html` — 2 de las 36 filas de una categoría que
  declara 118, con su paginador real. Es el caso que Kupfer NO resuelve: reporta
  la incompletitud en vez de ir a buscar el resto. Recortado a 2 filas a
  propósito (una con marca, una sin).
- `kupfer_categoria_vacia.html` — una categoría que existe y no tiene productos.
  Magento no devuelve un grid vacío: devuelve el mensaje "No podemos encontrar
  productos" y ningún `<ol>`. Sin distinguir ese caso, una categoría vacía se
  vería igual que una llave mal escrita.

De **Construmart** (con la cookie de sucursal, paginando porque su robots lo
permite):

- `construmart_taladros_g35.html` — 3 de las 20 filas de `taladros-y-atornilladores`
  servidas a la sucursal DEPARTAMENTAL (`customer_group_id=35`), con su
  `toolbar-number` (23), su paginador y su `#am-page-count` (2) reales. Las 3
  filas son los tres casos del grid: una con marca y precio, otra igual para
  contrastar, y una **"Sin Stock" sin precio ni SKU**, que es cómo esta tienda
  marca lo que esa sucursal no tiene.
- `construmart_taladros_g35_p2.html` — la **página 2 real** de esa misma
  categoría, que trae 3 filas y las 3 son "Sin Stock". No es un caso raro: es la
  cola normal de una categoría de Construmart, y es la razón por la que "una
  página que no emite nada" NO puede tratarse como señal de que la tienda dejó de
  respetar `?p=`.
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
    ConstrumartAdapter,
    KupferAdapter,
    NotAListingPage,
    parse_listing,
    parse_price,
)

FIXTURES = Path(__file__).parent / "fixtures"
COMPLETA = FIXTURES / "kupfer_taladros_rotomartillos.html"
PAGINADA = FIXTURES / "kupfer_categoria_paginada.html"
VACIA = FIXTURES / "kupfer_categoria_vacia.html"
CONSTRUMART = FIXTURES / "construmart_taladros_g35.html"
CONSTRUMART_P2 = FIXTURES / "construmart_taladros_g35_p2.html"

CATEGORY = CategoryRef(
    slug="ferre-herramientas",
    store_key="equipos-herramientas-y-maquinarias-industriales/herramientas-electricas.html",
    label="Herramientas eléctricas",
)
CAT_CONSTRUMART = CategoryRef(
    slug="ferre-herramientas",
    store_key="herramientas/herramientas-electricas-e-inalambricas/taladros-y-atornilladores",
    label="Taladros y atornilladores",
)
NOW = datetime(2026, 9, 24, 15, 0, tzinfo=timezone.utc)


def _parse(path: Path, *, store_slug: str = "kupfer", **kw):
    return parse_listing(
        path.read_text(encoding="utf-8"),
        store_slug=store_slug,
        category=CATEGORY,
        scraped_at=NOW,
        **kw,
    )


@pytest.fixture(scope="module")
def completa():
    return _parse(COMPLETA)


def test_parsea_las_cinco_filas(completa):
    assert len(completa.products) == 5
    assert (completa.enumerated, completa.declared) == (5, 5)
    assert all(p.store_slug == "kupfer" for p in completa.products)
    assert all(p.category_path == "ferre-herramientas" for p in completa.products)
    assert all(p.scraped_at == NOW for p in completa.products)


def test_el_sku_es_el_de_la_tienda_sin_el_prefijo(completa):
    """`<span class="product-item-sku">SKU: 114564</span>` → `114564`.

    No el id interno del `<div id="product-item-info_16211">`: el SKU es el
    código de artículo de la empresa y sobrevive a una reindexación.
    """
    assert [p.store_sku for p in completa.products] == [
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
    assert [p.price_effective for p in completa.products] == [
        Decimal("1137035"),  # 1137035.480001 → $1.137.035
        Decimal("185309"),  # 185309.180001  → $185.309
        Decimal("109318"),  # 109318.160001  → $109.318
        Decimal("2424923"),  # 2424922.500001 → $2.424.923  ← el medio punto
        Decimal("2911631"),  # 2911631.310001 → $2.911.631
    ]
    for p in completa.products:
        assert p.price_effective == p.price_effective.to_integral_value()


def test_sin_descuento_declarado_no_se_inventa_uno(completa):
    """El grid solo trae `oldPrice` cuando hay `special_price` cargado."""
    assert all(p.price_normal is None for p in completa.products)
    assert all(p.price_card is None for p in completa.products)
    assert all(p.claimed_discount is None for p in completa.products)


def test_la_etiqueta_del_grid_es_el_stock(completa):
    assert all(p.in_stock for p in completa.products)


def test_esta_familia_no_aporta_identidad(completa):
    """El grid de Magento no expone GTIN ni modelo — solo marca, a veces."""
    assert all(p.gtin is None for p in completa.products)
    assert all(p.model is None for p in completa.products)


def test_la_marca_se_lee_cuando_la_tienda_la_llena():
    """`<span class="product-item-brand">` existe siempre y viene vacío seguido.

    En las tres categorías de Kupfer auditadas la cobertura fue de 8 de 24, 6 de
    12 y 1 de 36, así que el vacío es el caso común y no puede ser un error.
    """
    parsed = _parse(PAGINADA)
    assert {p.store_sku: p.brand for p in parsed.products} == {
        "196889": None,
        "143985": "Loctite",
    }


# -----------------------------------------------------------------------------
# Lo que Kupfer NO resuelve, y por eso tiene que reportar
# -----------------------------------------------------------------------------


def test_la_categoria_que_no_entra_en_una_pagina_queda_declarada_incompleta():
    """118 declarados contra lo que trajo una sola request.

    Kupfer no pagina por decisión: su `robots.txt` prohíbe `/*?p=`. Lo que no se
    puede hacer es traer 36 de 118 y que se vea sano, porque el canario
    estadístico vería 36 items estables en cada pasada y nunca se quejaría.
    """
    parsed = _parse(PAGINADA)
    assert parsed.declared == 118
    assert parsed.enumerated < parsed.declared

    status, motivo = canary_verdict(
        parsed.enumerated, [], completeness=(parsed.enumerated, parsed.declared)
    )
    assert status == "partial"
    assert "118" in motivo


def test_la_categoria_completa_pasa_el_canario_exacto(completa):
    assert canary_verdict(
        completa.enumerated, [], completeness=(completa.enumerated, completa.declared)
    ) == ("ok", None)


def test_una_categoria_vacia_no_es_un_error_de_configuracion():
    """Existe y no tiene productos: cero filas, sin excepción.

    Es un dato del catálogo y lo reporta el canario por el piso de items, no una
    llave mal escrita. Magento no sirve un grid vacío para esto: no sirve grid.
    """
    parsed = _parse(VACIA)
    assert (parsed.products, parsed.enumerated, parsed.declared) == ([], 0, None)
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
        'INTRUSO</a><span class="product-item-sku">SKU: 999999</span>'
        '<span data-price-type="finalPrice" data-price-amount="1000"></span>'
        "</li></ol>"
    )
    parsed = parse_listing(
        html.replace("</body>", carrusel + "</body>"),
        store_slug="kupfer",
        category=CATEGORY,
        scraped_at=NOW,
    )
    assert parsed.enumerated == 5
    assert "999999" not in {p.store_sku for p in parsed.products}


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
    parsed = parse_listing(
        html, store_slug="kupfer", category=CATEGORY, scraped_at=NOW
    )
    assert parsed.enumerated == 5, "la fila se enumeró"
    assert len(parsed.products) == 4, "pero no se emitió"
    assert "9830" not in {p.store_sku for p in parsed.products}


# -----------------------------------------------------------------------------
# Construmart: cookie de sucursal, paginación y un total en el que no se cree
# -----------------------------------------------------------------------------


@pytest.fixture(scope="module")
def construmart():
    return parse_listing(
        CONSTRUMART.read_text(encoding="utf-8"),
        store_slug="construmart",
        category=CAT_CONSTRUMART,
        scraped_at=NOW,
        brand_selector=ConstrumartAdapter.brand_selector,
    )


def test_construmart_emite_solo_las_filas_con_precio(construmart):
    """Las 3 filas del fixture son 2 vendibles y una "Sin Stock".

    La fila sin stock viene **sin precio y sin `form[data-product-sku]`**, o sea
    sin SKU: así marca Construmart lo que esa sucursal no tiene. Se enumera
    —existe en la categoría— y no se emite, que es lo que deja la serie con un
    hueco en vez de con un precio inventado.
    """
    assert construmart.enumerated == 3
    assert [p.store_sku for p in construmart.products] == ["225066", "240421"]


def test_construmart_trae_precio_y_marca_de_la_sucursal(construmart):
    """Sin la cookie, estas mismas filas no traen un solo `$`.

    Y a diferencia de Kupfer, acá el `data-price-amount` ya viene entero
    (`229990`, no `229990.000001`), así que el redondeo no hace nada: el mismo
    parser sirve para las dos.
    """
    assert [p.price_effective for p in construmart.products] == [
        Decimal("229990"),
        Decimal("79990"),
    ]
    assert [p.brand for p in construmart.products] == ["Dewalt", "Bosch"]
    assert all(p.in_stock for p in construmart.products)


def test_construmart_necesita_su_propio_selector_de_marca():
    """Con el selector de Kupfer, la marca de Construmart se pierde.

    El nombre de la clase lo elige el tema (`atributte-brand`, con el typo), no
    Magento. Este test es el que justifica que el selector sea por tienda.
    """
    con_default = parse_listing(
        CONSTRUMART.read_text(encoding="utf-8"),
        store_slug="construmart",
        category=CAT_CONSTRUMART,
        scraped_at=NOW,
    )
    assert all(p.brand is None for p in con_default.products)


def test_construmart_declara_cuantos_tiene_y_cuantas_paginas(construmart):
    """23 productos en 2 páginas, y el 23 cuenta las filas, no las vendibles.

    La categoría real sirve 20 filas en la página 1 y 3 en la 2 = 23, que es
    exactamente lo que declara `toolbar-number`. De esas 23, solo 16 traen precio
    en esta sucursal: las otras 7 son "Sin Stock". Contar solo las vendibles haría
    parecer que la tienda declara de más y dejaría la categoría en `partial` para
    siempre — el fixture está recortado a 3 filas, así que este test verifica el
    par declarado/páginas y no la igualdad, que se midió en vivo.
    """
    assert construmart.declared == 23
    assert construmart.pages == 2


# -----------------------------------------------------------------------------
# Los adaptadores
# -----------------------------------------------------------------------------


class _Http:
    """Devuelve las respuestas en orden, una por request."""

    def __init__(self, *respuestas: str) -> None:
        self.respuestas = respuestas
        self.urls: list[str] = []
        self.headers: list[dict[str, str] | None] = []

    async def get_text(self, url: str, *, headers=None, **kw: object) -> str:
        self.urls.append(url)
        self.headers.append(headers)
        return self.respuestas[min(len(self.urls), len(self.respuestas)) - 1]


@pytest.mark.asyncio
async def test_kupfer_trae_una_categoria_en_una_sola_request():
    http = _Http(COMPLETA.read_text(encoding="utf-8"))
    adapter = KupferAdapter(http, [CATEGORY])

    productos = [p async for p in adapter.discover(CATEGORY)]

    assert len(productos) == 5
    assert http.urls == [
        "https://kupfer.cl/equipos-herramientas-y-maquinarias-industriales/"
        f"herramientas-electricas.html?product_list_limit={PAGE_SIZE}"
    ]
    assert "?p=" not in http.urls[0], "el robots.txt de Kupfer prohíbe ?p="
    assert http.headers == [None]


@pytest.mark.asyncio
async def test_kupfer_expone_la_completitud_de_la_ultima_corrida():
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


@pytest.mark.asyncio
async def test_construmart_manda_la_cookie_de_sucursal_en_cada_pagina():
    """Sin esta cookie el listado no trae precios: no es opcional."""
    html = CONSTRUMART.read_text(encoding="utf-8")
    http = _Http(html, html)
    adapter = ConstrumartAdapter(http, [CAT_CONSTRUMART])

    _ = [p async for p in adapter.discover(CAT_CONSTRUMART)]

    esperada = {"Cookie": "persistent_customer_group_id=35"}
    assert http.headers == [esperada, esperada]


@pytest.mark.asyncio
async def test_construmart_pide_exactamente_las_paginas_que_la_tienda_declara():
    """`#am-page-count` dice 2, así que se piden 2 y no se prueba una tercera.

    Probar hasta que falle costaría una request de más por categoría por pasada y
    dejaría al runner interpretando un error que no es un error.
    """
    html = CONSTRUMART.read_text(encoding="utf-8")
    http = _Http(html, html)
    adapter = ConstrumartAdapter(http, [CAT_CONSTRUMART])

    _ = [p async for p in adapter.discover(CAT_CONSTRUMART)]

    base = (
        "https://www.construmart.cl/herramientas/"
        "herramientas-electricas-e-inalambricas/taladros-y-atornilladores"
    )
    assert http.urls == [base, f"{base}?p=2"]
    assert "product_list_limit" not in http.urls[1], (
        "su robots prohíbe ?limit=; el default (20) ya es su máximo"
    )


@pytest.mark.asyncio
async def test_construmart_acumula_las_filas_de_todas_las_paginas():
    """`completeness` suma las filas enumeradas y compara contra el total de la 1.

    Con los fixtures reales de las dos páginas —recortados a 3 filas cada uno— el
    par es (6, 23). En vivo es (23, 23): la categoría sirve 20 + 3 filas y declara
    23. Lo que importa acá es que el enumerado se acumule y que el declarado salga
    de la primera página y no se vuelva a mirar.
    """
    http = _Http(
        CONSTRUMART.read_text(encoding="utf-8"), CONSTRUMART_P2.read_text(encoding="utf-8")
    )
    adapter = ConstrumartAdapter(http, [CAT_CONSTRUMART])

    _ = [p async for p in adapter.discover(CAT_CONSTRUMART)]

    assert adapter.completeness(CAT_CONSTRUMART) == (6, 23)


@pytest.mark.asyncio
async def test_una_pagina_repetida_corta_la_paginacion():
    """El síntoma de una tienda que dejó de respetar `?p=` y sirve la primera.

    Se corta en vez de seguir pidiendo páginas idénticas hasta el techo. Ojo con
    la condición: tiene que ser "emitió productos y ninguno es nuevo". Una página
    que no emite NADA es normal —la última de una categoría de Construmart suele
    traer solo filas sin precio— y tratarla como repetida sería una alerta por
    pasada para siempre.
    """
    html = CONSTRUMART.read_text(encoding="utf-8").replace(
        '<div id="am-page-count" style="display: none">2</div>',
        '<div id="am-page-count" style="display: none">5</div>',
    )
    http = _Http(html, html, html, html, html)
    adapter = ConstrumartAdapter(http, [CAT_CONSTRUMART])

    productos = [p async for p in adapter.discover(CAT_CONSTRUMART)]

    assert [p.store_sku for p in productos] == ["225066", "240421"]
    assert len(http.urls) == 2, "se pidió la 2, no aportó nada nuevo, se cortó"
