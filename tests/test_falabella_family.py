"""Contract test del adaptador Falabella/Sodimac contra un fixture real.

El fixture es HTML capturado de producción (2026-07-31) con 6 productos. Si la
tienda cambia la forma de `__NEXT_DATA__`, este test se pone rojo antes de que
el canario en vivo lo detecte.
"""
from __future__ import annotations

import json
import logging
import re

from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from scrapers.base import MAX_PLAUSIBLE_CLP, CategoryRef
from scrapers.stores.falabella_family import (
    FalabellaAdapter,
    NextDataMissing,
    NotAListingPage,
    SodimacAdapter,
    extract_next_data,
    parse_listing,
    resolve_prices,
)

FIXTURE = Path(__file__).parent / "fixtures" / "falabella_search_notebook.html"
CATEGORY = CategoryRef(slug="tecno-notebooks", store_key="notebook", label="Notebooks")
NOW = datetime(2026, 7, 31, 12, 0, tzinfo=timezone.utc)


@pytest.fixture(scope="module")
def parsed():
    html = FIXTURE.read_text(encoding="utf-8")
    return parse_listing(html, store_slug="falabella", category=CATEGORY, scraped_at=NOW)


def test_extrae_todos_los_productos(parsed):
    products, _ = parsed
    assert len(products) == 6


def test_campos_obligatorios_no_nulos(parsed):
    products, _ = parsed
    for p in products:
        assert p.store_sku and p.store_sku.isdigit()
        assert p.url.startswith("https://www.falabella.com/")
        assert p.name
        assert p.price_effective > 0
        assert p.brand
        assert p.image_url
        assert p.scraped_at == NOW


def test_paginacion_presente(parsed):
    _, pagination = parsed
    assert pagination["count"] > 0
    assert pagination["currentPage"] == 1


def test_precio_efectivo_ignora_la_tarjeta_de_la_casa(parsed):
    """El cmrPrice es más barato, pero requiere plástico: no es el efectivo."""
    products, _ = parsed
    macbook = next(p for p in products if p.store_sku == "80725439")
    assert macbook.price_card == Decimal("679990")  # cmrPrice
    assert macbook.price_effective == Decimal("699990")  # internetPrice
    assert macbook.price_effective > macbook.price_card


def test_event_price_cuenta_como_efectivo(parsed):
    """`eventPrice` es pagable sin tarjeta, así que sí alimenta la serie."""
    products, _ = parsed
    acer = next(p for p in products if p.store_sku == "151970879")
    assert acer.price_effective == Decimal("299990")
    assert acer.price_card == Decimal("289990")


def test_precio_normal_se_guarda_pero_no_se_cree(parsed):
    """El 'antes' tachado se persiste como evidencia, no como baseline."""
    products, _ = parsed
    tuf = next(p for p in products if p.store_sku == "17535916")
    assert tuf.price_normal == Decimal("1199990")
    assert tuf.price_effective == Decimal("769990")
    # El descuento que declara la tienda queda registrado sin usarse.
    assert tuf.claimed_discount is not None


def test_marca_normalizada(parsed):
    products, _ = parsed
    macbook = next(p for p in products if p.store_sku == "80725439")
    assert macbook.brand == "Apple"  # el crudo viene "APPLE"


# --- resolve_prices: casos que el fixture no cubre ---------------------------


def test_resolve_prices_sin_precio_pagable_cae_al_normal():
    prices = [{"type": "normalPrice", "price": ["149.990"], "crossed": False}]
    effective, claimed, card = resolve_prices(prices)
    assert effective == Decimal("149990")
    assert claimed == Decimal("149990")
    assert card is None


def test_resolve_prices_normal_tachado_no_es_efectivo():
    """Un normalPrice tachado sin alternativa pagable no da precio efectivo."""
    prices = [{"type": "normalPrice", "price": ["149.990"], "crossed": True}]
    effective, claimed, _ = resolve_prices(prices)
    assert effective is None
    assert claimed == Decimal("149990")


def test_resolve_prices_toma_el_minimo_pagable():
    prices = [
        {"type": "internetPrice", "price": ["199.990"], "crossed": False},
        {"type": "eventPrice", "price": ["179.990"], "crossed": False},
    ]
    effective, _, _ = resolve_prices(prices)
    assert effective == Decimal("179990")


def test_resolve_prices_vacio():
    assert resolve_prices([]) == (None, None, None)


def test_producto_sin_precio_se_descarta():
    """Sin precio pagable no se emite el producto: un cero ensucia la baseline."""
    html = (
        '<script id="__NEXT_DATA__" type="application/json">'
        '{"props":{"pageProps":{"results":[{"skuId":"1","url":"https://x/p",'
        '"displayName":"Sin precio","prices":[]}],"pagination":{}}}}'
        "</script>"
    )
    products, _ = parse_listing(
        html, store_slug="falabella", category=CATEGORY, scraped_at=NOW
    )
    assert products == []


def test_html_sin_next_data_falla_ruidosamente():
    """Si la tienda cambia el frontend, se rompe fuerte y no en silencio."""
    with pytest.raises(NextDataMissing):
        extract_next_data("<html><body>nada</body></html>")


def test_precio_centinela_se_descarta():
    """Falabella publica $99.999.999.999 para productos sin precio real.

    No es un producto caro: es un placeholder. Si entrara a la serie, la baseline
    de ese SKU quedaría envenenada para siempre y todo lo posterior se vería como
    un -99,99% de descuento.
    """
    html = FIXTURE.read_text(encoding="utf-8")
    envenenado = html.replace(
        '"type":"internetPrice","price":["699.990"]',
        '"type":"internetPrice","price":["99.999.999.999"]',
        1,
    )
    assert envenenado != html, "el fixture cambió: revisar el precio que se sustituye"

    limpios, _ = parse_listing(
        envenenado, store_slug="falabella", category=CATEGORY, scraped_at=NOW
    )
    originales, _ = parse_listing(
        html, store_slug="falabella", category=CATEGORY, scraped_at=NOW
    )

    # El producto envenenado se descarta entero, no se cuela con otro precio: su
    # única alternativa era el precio-tarjeta, que no es comparable.
    assert len(limpios) == len(originales) - 1
    assert all(p.price_effective <= MAX_PLAUSIBLE_CLP for p in limpios)


def test_url_de_pagina_usa_path_de_categoria():
    """Ambas tiendas navegan por categoría; el `/` del store_key es significativo.

    Si se url-encodeara, `cat70057/Notebooks` se volvería `cat70057%2FNotebooks`
    y la tienda respondería una landing en vez del listado.
    """
    fala = FalabellaAdapter(None, [])
    sodi = SodimacAdapter(None, [])
    cat = CategoryRef(slug="tecno-notebooks", store_key="cat70057/Notebooks")

    assert fala._page_url(cat, 3) == (
        "https://www.falabella.com/falabella-cl/category/cat70057/Notebooks?page=3"
    )
    assert sodi._page_url(
        CategoryRef(slug="ferre-herramientas", store_key="cat14080023/Taladros"), 1
    ) == "https://www.sodimac.cl/sodimac-cl/lista/cat14080023/Taladros?page=1"


def test_landing_de_cms_falla_ruidosamente():
    """Un store_key mal configurado no debe verse como categoría vacía.

    Falabella responde una landing (`containers`, sin `results`) cuando el par
    id/nombre no coincide. Devolver [] haría que se confundiera con una categoría
    legítimamente sin stock, y el store_key roto sobreviviría en silencio.
    """
    landing = (
        '<script id="__NEXT_DATA__" type="application/json">'
        '{"props":{"pageProps":{"containers":[],"components":[]}}}</script>'
    )
    with pytest.raises(NotAListingPage):
        parse_listing(landing, store_slug="falabella", category=CATEGORY, scraped_at=NOW)


_SHELL_SIN_RESULTS = (
    '<script id="__NEXT_DATA__" type="application/json">'
    '{"props":{"pageProps":{"searchTerm":"","isImageSearch":false}}}</script>'
)


@pytest.mark.asyncio
async def test_pagina_1_sin_results_es_error_de_configuracion():
    """En la página 1, un shell sin `results` = store_key roto. Debe propagar."""

    class _Http:
        async def get_text(self, url, **kw):
            return _SHELL_SIN_RESULTS

    adapter = FalabellaAdapter(_Http(), [])
    cat = CategoryRef(slug="tecno-notebooks", store_key="cat70057/Nombre-Errado")
    with pytest.raises(NotAListingPage):
        async for _ in adapter.discover(cat):
            pass


@pytest.mark.asyncio
async def test_shell_despues_de_la_pagina_1_es_fin_de_catalogo():
    """Pasado el final, la tienda devuelve un shell sin `results`, no una lista
    vacía. Eso NO es un error: es cómo termina la paginación."""

    class _Http:
        def __init__(self):
            self.calls = 0

        async def get_text(self, url, **kw):
            self.calls += 1
            return FIXTURE.read_text(encoding="utf-8") if self.calls == 1 else _SHELL_SIN_RESULTS

    adapter = FalabellaAdapter(_Http(), [])
    cat = CategoryRef(slug="tecno-notebooks", store_key="cat70057/Notebooks")
    productos = [p async for p in adapter.discover(cat)]
    assert productos, "la página 1 del fixture debe haberse consumido"


# -----------------------------------------------------------------------------
# El canario exacto (2026-10-12): esta familia era la única grande sin él
# -----------------------------------------------------------------------------


class _FakeHttp:
    """Sirve páginas canned por número de página."""

    def __init__(self, paginas: dict[int, str]) -> None:
        self.paginas = paginas
        self.pedidos: list[int] = []

    async def get_text(self, url, *, rps=None, headers=None):
        page = int(re.search(r"page=(\d+)", url).group(1))
        self.pedidos.append(page)
        return self.paginas.get(page, _pagina([], declarado=0))


def _pagina(skus, *, declarado, current=None):
    """Una página con la forma de `__NEXT_DATA__` de la familia."""
    results = [
        {
            "skuId": str(s),
            "url": f"https://x/{s}",
            "displayName": f"Producto {s}",
            "prices": [{"type": "internetPrice", "price": ["10.000"]}],
        }
        for s in skus
    ]
    payload = {
        "props": {
            "pageProps": {
                "results": results,
                "pagination": {
                    "count": declarado,
                    "perPage": 48,
                    "currentPage": current if current is not None else 1,
                },
            }
        }
    }
    return (
        '<script id="__NEXT_DATA__" type="application/json">'
        + json.dumps(payload)
        + "</script>"
    )


@pytest.mark.asyncio
async def test_completeness_reporta_enumerados_contra_declarados():
    cat = CategoryRef(slug="tecno-notebooks", store_key="cat1/X")
    http = _FakeHttp({1: _pagina(range(10), declarado=10, current=1)})
    adapter = FalabellaAdapter(http, [cat])

    productos = [p async for p in adapter.discover(cat)]

    assert len(productos) == 10
    assert adapter.completeness(cat) == (10, 10)


@pytest.mark.asyncio
async def test_un_catalogo_mas_grande_que_la_ventana_no_reporta_completitud(caplog):
    """Y no es una omisión: es para no dejar una alarma sonando para siempre.

    Las tres llaves gigantes de Falabella (Zapatillas 18.412, Refrigeradores
    13.754, Audífonos 8.485) no entran en la ventana de 2.640 ni van a entrar.
    Reportar `(2.640, 18.412)` las dejaría en `partial` permanente, y una alarma
    que suena siempre es una alarma apagada — el mismo error que las corridas
    manuales ensuciando la guarda de volumen. Se cae al canario estadístico, que
    sigue vigilando el volumen contra su propia historia, y el hecho queda en el
    log.
    """
    cat = CategoryRef(slug="ropa-calzado", store_key="cat2083/Zapatillas")
    paginas = {
        p: _pagina(range(p * 100, p * 100 + 48), declarado=5000, current=p)
        for p in range(1, 4)
    }
    http = _FakeHttp(paginas)

    class Recortado(FalabellaAdapter):
        max_pages = 3

    adapter = Recortado(http, [cat])
    with caplog.at_level(logging.WARNING):
        productos = [p async for p in adapter.discover(cat)]

    assert len(productos) == 144
    assert adapter.completeness(cat) is None, (
        "una llave que excede la ventana a propósito no puede quedar en partial "
        "permanente"
    )
    assert "catalogo_mas_grande_que_la_ventana" in caplog.text


@pytest.mark.asyncio
async def test_el_canario_exacto_aplica_cuando_el_catalogo_entra(caplog):
    """La contracara: si el catálogo entra en la ventana, la guarda sí mide.

    Es el caso de Notebooks (1.243), Smartphones (2.022), Botines (2.545) y
    Smart-TV (324) con `max_pages = 55`, o sea las llaves que producen la baseline
    del sistema hoy. Acá una página que la tienda sirve a medias SÍ tiene que
    marcar `partial`.
    """
    cat = CategoryRef(slug="tecno-notebooks", store_key="cat70057/Notebooks")
    # Declara 100 y sirve 48: entra en la ventana, así que se mide y falta.
    http = _FakeHttp({1: _pagina(range(48), declarado=100, current=1)})
    adapter = FalabellaAdapter(http, [cat])

    with caplog.at_level(logging.WARNING):
        [p async for p in adapter.discover(cat)]

    assert adapter.completeness(cat) == (48, 100)
    assert "catalogo_mas_grande_que_la_ventana" not in caplog.text


@pytest.mark.asyncio
async def test_sin_recorte_no_avisa(caplog):
    """Un catálogo que entra completo no tiene que ensuciar el log."""
    cat = CategoryRef(slug="tecno-notebooks", store_key="cat1/X")
    http = _FakeHttp({1: _pagina(range(5), declarado=5, current=1)})
    adapter = FalabellaAdapter(http, [cat])

    with caplog.at_level(logging.WARNING):
        [p async for p in adapter.discover(cat)]

    assert "catalogo_recortado_por_max_pages" not in caplog.text
