"""Contract test de Tottus contra un fixture real.

Tottus no trae un parser propio: corre la plataforma de Falabella y `parse_listing`
de `falabella_family` la entiende tal cual. Por eso lo que se prueba acá es
distinto de lo que prueba `test_falabella_family.py` —que ya cubre la forma del
`__NEXT_DATA__`— y es lo específico de esta tienda:

  * que el payload de ESTA tienda se parsee con el parser compartido, que es la
    afirmación de la que depende no haber escrito un adaptador nuevo;
  * que el adaptador mande headers de navegador, porque sin eso son 403 todas las
    páginas y el síntoma no se parece a un problema de headers;
  * que `max_pages` alcance para su catálogo, porque pasarse de largo recorta el
    catálogo **en silencio**.

El fixture es HTML capturado de producción (2026-10-01) con 6 de los 48 productos
de la página 1 de Aseo-y-Limpieza: 3 con `normalPrice` declarado y 3 sin.
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from scrapers.base import CategoryRef
from scrapers.http import BROWSER_HEADERS, DEFAULT_USER_AGENT
from scrapers.stores.falabella_family import (
    FalabellaAdapter,
    SodimacAdapter,
    TottusAdapter,
    parse_listing,
)

FIXTURE = Path(__file__).parent / "fixtures" / "tottus_aseo_limpieza.html"
CATEGORY = CategoryRef(
    slug="supermercado", store_key="CATG27074/Aseo-y-Limpieza", label="Aseo y Limpieza"
)
NOW = datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc)


@pytest.fixture(scope="module")
def parsed():
    html = FIXTURE.read_text(encoding="utf-8")
    return parse_listing(html, store_slug="tottus", category=CATEGORY, scraped_at=NOW)


def test_el_parser_compartido_entiende_a_tottus(parsed):
    """La afirmación que justifica no haber escrito un adaptador nuevo."""
    products, _ = parsed
    assert len(products) == 6
    assert {p.store_slug for p in products} == {"tottus"}


def test_campos_obligatorios_no_nulos(parsed):
    products, _ = parsed
    for p in products:
        assert p.store_sku and p.name and p.url
        assert p.price_effective > 0
        assert p.scraped_at == NOW


def test_precios_en_clp_enteros(parsed):
    """Nunca float para dinero, y el separador de miles chileno no es decimal."""
    products, _ = parsed
    precios = {p.store_sku: p.price_effective for p in products}
    assert precios["119445474"] == Decimal("4190")
    assert precios["110615129"] == Decimal("520")
    assert precios["120217125"] == Decimal("12790")
    for valor in precios.values():
        assert isinstance(valor, Decimal)
        assert valor == valor.to_integral_value()


def test_el_precio_normal_se_guarda_pero_no_se_cree(parsed):
    """`normalPrice` es el "antes" que declara la tienda: evidencia, no baseline."""
    products, _ = parsed
    por_sku = {p.store_sku: p for p in products}

    assert por_sku["119445474"].price_normal == Decimal("5090")
    assert por_sku["119445474"].price_effective == Decimal("4190")
    # Los tres sin "antes" declarado no inventan uno.
    assert por_sku["110615129"].price_normal is None
    assert por_sku["120217125"].price_normal is None


def test_la_paginacion_declara_el_total_de_la_categoria(parsed):
    """`count` es la fuente del canario exacto: lo enumerado contra lo declarado."""
    _, pagination = parsed
    assert pagination["count"] == 1162
    assert pagination["perPage"] == 48
    assert pagination["currentPage"] == 1


def test_marca_normalizada(parsed):
    products, _ = parsed
    marcas = {p.brand for p in products}
    assert "Soft" in marcas, f"marcas: {marcas}"
    assert all(m is None or m == m.strip() for m in marcas)


def test_no_trae_gtin_y_eso_esta_medido(parsed):
    """Como Falabella y Sodimac: habría que abrir fichas. No es un bug del parser."""
    products, _ = parsed
    assert all(p.gtin is None for p in products)


def test_in_stock_es_ciego_en_tottus(parsed):
    """Su `availability` habla de modos de envío, no de stock.

    Se asume `True` como en Falabella y Paris. Queda documentado para que nadie
    confíe en la guarda de stock del detector en esta tienda.
    """
    products, _ = parsed
    assert all(p.in_stock for p in products)


def test_el_precio_por_unidad_de_medida_se_guarda_con_su_base(parsed):
    """El dato que vuelve comparable una oferta de supermercado (§2bis del plan).

    Hasta la migración 34 llegaba en el payload y se tiraba. Las seis filas del
    fixture lo traen, y traen cuatro bases distintas — que es el punto: `100UN`
    y `MT` no son errores, son la base que la tienda eligió para que el número
    sea legible, así que el precio no significa nada sin su etiqueta y dos `pum`
    de bases distintas NO se comparan entre sí.
    """
    products, _ = parsed
    pums = {p.store_sku: p.pum for p in products}

    assert all(pum is not None for pum in pums.values())
    assert (pums["119445474"].label, pums["119445474"].price) == ("LT", Decimal("2095"))
    assert (pums["110609732"].label, pums["110609732"].price) == ("100UN", Decimal("8"))
    assert (pums["110615129"].label, pums["110615129"].price) == ("UN", Decimal("52"))
    assert {pum.label for pum in pums.values()} == {"LT", "MT", "100UN", "UN"}


def test_el_pum_tambien_es_dinero_y_va_en_clp_enteros(parsed):
    """Nunca float, igual que `price_effective`. Vale para el pum de $8 también."""
    products, _ = parsed
    for p in products:
        assert isinstance(p.pum.price, Decimal)
        assert p.pum.price == p.pum.price.to_integral_value()
        assert p.pum.price > 0


def test_el_pum_corresponde_al_precio_efectivo_y_no_al_tachado(parsed):
    """El del `normalPrice` tachado sería el precio por litro de un precio muerto.

    En el fixture, el SKU 119445474 vale $4.190 con `normalPrice` $5.090 tachado:
    el pum publicable es el de los $4.190 ($2.095 el litro = la mitad, o sea 2 L),
    no uno derivado del "antes" que declara la tienda.
    """
    products, _ = parsed
    soft = next(p for p in products if p.store_sku == "119445474")
    assert soft.price_normal == Decimal("5090")
    assert soft.pum.price * 2 == soft.price_effective


# -----------------------------------------------------------------------------
# Lo del adaptador
# -----------------------------------------------------------------------------


def test_manda_headers_de_navegador_completos():
    """Sin esto son 403 todas las páginas.

    Medido el 2026-10-01 con 3 intentos de cada variante contra la misma URL:
    `DEFAULT_USER_AGENT` 403×3, `BROWSER_USER_AGENT` 403×3, `BROWSER_HEADERS`
    200×3. El UA de navegador solo NO alcanza — la diferencia con Prat.
    """
    adapter = TottusAdapter(None, [])
    assert adapter._headers == BROWSER_HEADERS
    assert "Accept-Language" in adapter._headers
    assert "Sec-Fetch-Mode" in adapter._headers
    assert DEFAULT_USER_AGENT not in adapter._headers.values()


def test_las_hermanas_no_heredan_los_headers():
    """Falabella y Sodimac no los necesitan: el default sigue identificándose."""
    assert FalabellaAdapter(None, [])._headers is None
    assert SodimacAdapter(None, [])._headers is None


def test_max_pages_alcanza_para_el_paraguas_mas_grande():
    """Pasarse de `max_pages` recorta el catálogo sin un solo error.

    Despensa declara 2.060 productos a 48 por página: 43. Tottus tenía un override
    de 45 por esto; desde el 2026-10-12 la familia entera trae 55 por defecto —ver
    `_FalabellaFamilyAdapter.max_pages`— así que el override quedó redundante y se
    quitó. Lo que este test fija es la propiedad, no el número: su paraguas más
    grande tiene que entrar.
    """
    adapter = TottusAdapter(None, [])
    paginas_de_despensa = -(-2060 // 48)
    assert paginas_de_despensa == 43
    assert adapter.max_pages >= paginas_de_despensa


def test_pide_orden_por_precio_para_estabilizar_la_paginacion():
    """Su default (`_score,desc`) repite productos y deja otros sin ver nunca.

    Medido el 2026-10-01 sobre `Mascotas` (427 declarados): sin `sortBy` la
    cobertura es 0,911 y con precio ascendente 0,988. Lo que importa no es la
    cobertura en sí: un SKU que aparece de forma intermitente nunca llega a
    `MIN_DAYS` y por lo tanto nunca produce una baseline.
    """
    adapter = TottusAdapter(None, [])
    url = adapter._page_url(CATEGORY, 2)

    assert "sortBy=derived.currentPrice%2Casc" in url
    assert url == (
        "https://www.tottus.cl/tottus-cl/lista/CATG27074/Aseo-y-Limpieza"
        "?page=2&sortBy=derived.currentPrice%2Casc"
    )


def test_las_hermanas_no_mandan_sortby():
    """Falabella y Sodimac paginan estable con su default: no se les toca la URL."""
    cat = CategoryRef(slug="tecno-notebooks", store_key="cat70057/Notebooks")
    assert "sortBy" not in FalabellaAdapter(None, [])._page_url(cat, 1)
    assert "sortBy" not in SodimacAdapter(None, [])._page_url(cat, 1)
