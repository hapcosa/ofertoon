"""Contract test de Jumbo y Santa Isabel contra payload real.

Los dos fixtures son el JSON-LD `ItemList` que sirve
`jumbo.cl/lacteos-huevos-y-congelados/leches`, capturado el 2026-11-04: la
página 1 y la 8, que es la última. Los items van verbatim; lo que se recortó es
el resto del HTML (la página real pesa 2,0 MB, casi toda payload RSC que este
adaptador no lee a propósito) y la cantidad de items.

El fixture de la página 8 existe por la moraleja del caso `isOutOfStock` de la
familia Falabella: **un lector de stock hay que probarlo contra productos
agotados, no contra los que están a la venta**. Sus 18 productos vienen
`OutOfStock` porque el orden por defecto manda los agotados al final.
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from scrapers.base import CategoryRef, CountingAdapter, StoreAdapter
from scrapers.http import DEFAULT_USER_AGENT, FetchError
from scrapers.stores.cencosud_family import (
    PAGE_SIZE,
    JumboAdapter,
    NotAListingPage,
    SantaIsabelAdapter,
    declared_total,
    parse_listing,
    sku_from_url,
)

FIXTURES = Path(__file__).parent / "fixtures"
PAGINA_1 = FIXTURES / "cencosud_jumbo_leches.html"
PAGINA_8 = FIXTURES / "cencosud_jumbo_leches_p8.html"

CATEGORY = CategoryRef(
    slug="supermercado",
    store_key="lacteos-huevos-y-congelados/leches",
    label="Supermercado",
)
NOW = datetime(2026, 11, 4, 12, 0, tzinfo=timezone.utc)


def _parse(path: Path, *, store_slug: str = "jumbo"):
    return parse_listing(
        path.read_text(encoding="utf-8"),
        store_slug=store_slug,
        category=CATEGORY,
        scraped_at=NOW,
    )


@pytest.fixture(scope="module")
def pagina1():
    return _parse(PAGINA_1)


@pytest.fixture(scope="module")
def pagina8():
    return _parse(PAGINA_8)


class _Http:
    """Sirve las respuestas en orden; un `int` se devuelve como ese HTTP status."""

    def __init__(self, *respuestas: str | int) -> None:
        self._respuestas = list(respuestas)
        self.urls: list[str] = []
        self.headers: list[dict[str, str] | None] = []

    async def get_text(self, url: str, **kw: object) -> str:
        self.urls.append(url)
        self.headers.append(kw.get("headers"))  # type: ignore[arg-type]
        respuesta = self._respuestas[min(len(self.urls) - 1, len(self._respuestas) - 1)]
        if isinstance(respuesta, int):
            raise FetchError(f"{url} -> HTTP {respuesta}", status_code=respuesta)
        return respuesta


# -----------------------------------------------------------------------------
# Parseo del JSON-LD
# -----------------------------------------------------------------------------


def test_parsea_los_items_del_itemlist(pagina1):
    assert len(pagina1.products) == 6
    assert pagina1.enumerated == 6
    assert pagina1.declared == 298


def test_campos_obligatorios_no_nulos(pagina1):
    for p in pagina1.products:
        assert p.store_sku and "/" not in p.store_sku
        assert p.url.startswith("https://www.jumbo.cl/") and p.url.endswith("/p")
        assert p.name
        assert p.price_effective > 0
        assert p.brand
        assert p.image_url
        assert p.category_path == "supermercado"
        assert p.scraped_at == NOW


def test_el_precio_es_un_entero_en_clp(pagina1):
    """La tienda manda el precio numérico y entero (`10990`), sin separadores."""
    nido = next(p for p in pagina1.products if p.store_sku == "nido-1-800g-2074962")
    assert nido.price_effective == Decimal("10990")
    assert nido.price_effective == nido.price_effective.to_integral_value()


def test_no_se_inventa_un_antes_tachado(pagina1):
    """`offers` trae UN precio y nada más: no hay `price_normal` que declarar.

    Es el caso de Nike — sin "antes" de la tienda, θ no se puede fijar midiendo
    cuánto declara descontar. El lateral bueno es que acá no hay número de la
    tienda que inflar.
    """
    assert all(p.price_normal is None for p in pagina1.products)
    assert all(p.claimed_discount is None for p in pagina1.products)


def test_esta_familia_no_aporta_identidad(pagina1):
    """Sin GTIN ni modelo: no desbloquea el cross-store."""
    assert all(p.gtin is None and p.model is None for p in pagina1.products)


def test_el_pum_no_se_lee_aunque_la_tienda_lo_tenga(pagina1):
    """El `ppumPrice` vive en el payload RSC, que este adaptador no toca.

    Está en el docstring del módulo: leerlo es parsear el formato de flight de
    React. Que estas ofertas salgan sin la línea del precio por kilo es una
    decisión tomada, no un olvido.
    """
    assert all(p.pum is None for p in pagina1.products)


def test_la_marca_sale_del_objeto_brand(pagina1):
    nido = next(p for p in pagina1.products if p.store_sku == "nido-1-800g-2074962")
    assert nido.brand == "Nido"


# -----------------------------------------------------------------------------
# Stock: la guarda se prueba contra los agotados
# -----------------------------------------------------------------------------


def test_la_pagina_1_viene_toda_con_stock(pagina1):
    assert all(p.in_stock for p in pagina1.products)


def test_la_ultima_pagina_viene_toda_agotada(pagina8):
    """`OutOfStock` → `in_stock = False`. Serían las primeras tiendas de
    supermercado del sistema con stock real en el listado."""
    assert pagina8.products
    assert not any(p.in_stock for p in pagina8.products)


def test_el_agotado_igual_se_persiste_con_su_precio(pagina8):
    """El filtro de stock vive en `compute_baseline`, no en el adaptador.

    Descartarlo acá sería tirar una observación que la baseline sabe ignorar, y
    el histórico de precio de un producto agotado sigue siendo información.
    """
    assert all(p.price_effective > 0 for p in pagina8.products)


# -----------------------------------------------------------------------------
# El total declarado y el canario exacto
# -----------------------------------------------------------------------------


def test_el_total_sale_del_span_y_no_del_texto_suelto():
    """"productos" aparece 98 veces en la página real: el patrón va anclado al
    markup del `<span>` que sigue al `<h1>`."""
    assert declared_total(PAGINA_1.read_text(encoding="utf-8")) == 298
    assert declared_total('<span class="x">3.299 productos</span>') == 3299
    assert declared_total('<input placeholder="Busca productos, marcas">') is None


def test_sin_total_declarado_no_se_inventa_uno():
    """`None` degrada al canario estadístico. Una guarda más débil es correcta;
    un total inventado anularía la exacta en silencio."""
    html = PAGINA_1.read_text(encoding="utf-8").replace("298 productos", "")
    assert _parse_html_declared(html) is None


def _parse_html_declared(html: str) -> int | None:
    return parse_listing(
        html, store_slug="jumbo", category=CATEGORY, scraped_at=NOW
    ).declared


@pytest.mark.asyncio
async def test_esta_familia_no_sostiene_un_canario_exacto():
    """`completeness()` siempre `None`, aunque el dato esté a mano.

    El total declarado y el grid paginado no concuerdan de forma estable: siete de
    las diez llaves quedaron entre 1 y 10 ítems cortas en el recorrido completo
    del 2026-11-04, y `jumbo/despensa` dio 3.299 de 3.299 en un recorrido y 3.299
    de 3.303 en el siguiente. Un `partial` manda un mensaje de Telegram por
    pasada, así que encenderlo sería una alarma que suena siempre — el mismo
    motivo por el que la familia Falabella tampoco lo implementa. La tabla está en
    el docstring del método.
    """
    http = _Http(PAGINA_1.read_text(encoding="utf-8"), 404)
    adapter = JumboAdapter(http, [CATEGORY])

    _ = [p async for p in adapter.discover(CATEGORY)]

    assert adapter.completeness(CATEGORY) is None


@pytest.mark.asyncio
async def test_el_total_declarado_avisa_cuando_el_catalogo_no_entra(caplog):
    """Es la guarda que reemplaza al canario exacto, y la que importaba de verdad.

    Un recorte por `max_pages` es silencioso —el volumen enumerado queda estable
    pasada a pasada, así que el canario estadístico lo ve sano— y en la familia
    Falabella eso recortó el catálogo durante diez días.
    """
    html = PAGINA_1.read_text(encoding="utf-8").replace(
        "298 productos", "99999 productos"
    )
    adapter = JumboAdapter(_Http(html, 404), [CATEGORY])

    with caplog.at_level("WARNING"):
        _ = [p async for p in adapter.discover(CATEGORY)]

    assert "catalogo_mas_grande_que_la_ventana" in caplog.text
    assert "declarados=99999" in caplog.text


# -----------------------------------------------------------------------------
# Paginación
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_la_pagina_1_no_lleva_el_parametro_page():
    http = _Http(PAGINA_1.read_text(encoding="utf-8"), 404)
    adapter = JumboAdapter(http, [CATEGORY])

    _ = [p async for p in adapter.discover(CATEGORY)]

    assert http.urls[0] == (
        "https://www.jumbo.cl/lacteos-huevos-y-congelados/leches"
    )
    assert http.urls[1].endswith("/leches?page=2")


@pytest.mark.asyncio
async def test_404_despues_de_la_pagina_1_es_fin_de_catalogo():
    """La primera página pasada del final contesta 404, igual que Easy.

    Sin este guard el runner marcaría `failed` la categoría entera y perdería el
    lote pendiente en el buffer: cada corrida fallida tira las observaciones ya
    scrapeadas.
    """
    http = _Http(PAGINA_1.read_text(encoding="utf-8"), 404)
    adapter = JumboAdapter(http, [CATEGORY])

    productos = [p async for p in adapter.discover(CATEGORY)]

    assert len(productos) == 6
    assert len(http.urls) == 2


@pytest.mark.asyncio
async def test_404_en_la_pagina_1_es_error_de_configuracion():
    """Mismo status, otro significado: la llave no existe. Tiene que ser ruidoso."""
    adapter = JumboAdapter(_Http(404), [CATEGORY])

    with pytest.raises(FetchError):
        async for _ in adapter.discover(CATEGORY):
            pass


@pytest.mark.asyncio
async def test_una_pagina_sin_itemlist_en_la_1_es_error_de_configuracion():
    """Un path de CMS (`/locales`) responde 200 sin listado."""
    adapter = JumboAdapter(_Http("<html><body>sin json-ld</body></html>"), [CATEGORY])

    with pytest.raises(NotAListingPage):
        async for _ in adapter.discover(CATEGORY):
            pass


@pytest.mark.asyncio
async def test_la_paginacion_corta_con_el_404_y_no_con_el_total_declarado():
    """El total declarado NO decide dónde cortar, y eso es deliberado.

    Se lee en la página 1 y deriva respecto del grid (ver `completeness`): cortar
    con él truncaría la llave las veces que viene por debajo de lo que la tienda
    sirve. El final lo dice la tienda con su 404, y el precio es un request de
    más por llave.
    """
    html = PAGINA_1.read_text(encoding="utf-8").replace("298 productos", "6 productos")
    http = _Http(html, PAGINA_8.read_text(encoding="utf-8"), 404)
    adapter = JumboAdapter(http, [CATEGORY])

    productos = [p async for p in adapter.discover(CATEGORY)]

    assert len(productos) == 11, "siguió pasado el total declarado"
    assert len(http.urls) == 3


@pytest.mark.asyncio
async def test_una_pagina_repetida_corta_la_paginacion():
    """El síntoma de una tienda que dejó de respetar `?page=`.

    Acá el daño sería silencioso: con el dedupe de la pasada esa página no emite
    nada, así que sin el guard se seguirían pidiendo páginas idénticas hasta
    `max_pages` — 90 requests por llave.
    """
    html = PAGINA_1.read_text(encoding="utf-8")
    http = _Http(html, html, html, html)
    adapter = JumboAdapter(http, [CATEGORY])

    productos = [p async for p in adapter.discover(CATEGORY)]

    assert len(productos) == 6
    assert len(http.urls) == 2, "pidió la 2, no aportó un SKU nuevo, cortó"


@pytest.mark.asyncio
async def test_no_se_pasa_del_techo_de_paginas(monkeypatch):
    """`max_pages` es la cota de cordura; el corte normal es el 404 o el total."""
    html = PAGINA_1.read_text(encoding="utf-8").replace("298 productos", "99999 productos")
    monkeypatch.setattr(JumboAdapter, "max_pages", 3)
    # Cada página trae un SKU distinto para que no corte por página repetida.
    paginas = [html.replace("nido-1-800g-2074962", f"nido-{i}") for i in range(5)]
    http = _Http(*paginas)
    adapter = JumboAdapter(http, [CATEGORY])

    _ = [p async for p in adapter.discover(CATEGORY)]

    assert len(http.urls) == 3


# -----------------------------------------------------------------------------
# Dedupe: el patrocinado y el cross-listado entre departamentos
# -----------------------------------------------------------------------------

CAT_A = CategoryRef(slug="supermercado", store_key="despensa")
CAT_B = CategoryRef(slug="supermercado", store_key="chocolates-galletas-y-snacks")


@pytest.mark.asyncio
async def test_el_sku_se_emite_una_vez_aunque_este_en_dos_llaves():
    """Medido: `despensa` ∩ `chocolates-galletas-y-snacks` = 2 de 800 SKUs.

    La segunda llave no emite nada y eso es correcto: el producto ya entró por la
    primera del orden de `db.load_store_targets`.
    """
    html = PAGINA_1.read_text(encoding="utf-8")
    http = _Http(html, 404, html, 404)
    adapter = JumboAdapter(http, [CAT_A, CAT_B])

    primera = [p async for p in adapter.discover(CAT_A)]
    segunda = [p async for p in adapter.discover(CAT_B)]

    assert len(primera) == 6
    assert segunda == []


@pytest.mark.asyncio
async def test_el_dedupe_no_corta_la_paginacion_de_la_llave_siguiente():
    """El bug de Andesgear: `locales` y el `seen` de la pasada son dos conjuntos.

    Con uno solo, la primera página cuya carga ya entró por OTRA llave se leería
    como "página que no aporta nada" y cortaría la paginación ahí.
    """
    p1 = PAGINA_1.read_text(encoding="utf-8")
    p8 = PAGINA_8.read_text(encoding="utf-8")
    http = _Http(p1, 404, p1, p8, 404)
    adapter = JumboAdapter(http, [CAT_A, CAT_B])

    _ = [p async for p in adapter.discover(CAT_A)]
    segunda = [p async for p in adapter.discover(CAT_B)]

    assert len(segunda) == 5, "siguió a la página 2 y emitió lo que sí era nuevo"


@pytest.mark.asyncio
async def test_cada_adaptador_nuevo_arranca_limpio():
    """El `seen` vive en la instancia, que vive una pasada: así se vacía solo."""
    html = PAGINA_1.read_text(encoding="utf-8")
    primera = [p async for p in JumboAdapter(_Http(html, 404), [CAT_A]).discover(CAT_A)]
    segunda = [p async for p in JumboAdapter(_Http(html, 404), [CAT_A]).discover(CAT_A)]

    assert len(primera) == len(segunda) == 6


# -----------------------------------------------------------------------------
# Identidad del SKU y configuración de las dos tiendas
# -----------------------------------------------------------------------------


@pytest.mark.parametrize(
    "url,esperado",
    [
        ("https://www.jumbo.cl/nido-1-800g-2074962/p", "nido-1-800g-2074962"),
        ("https://www.santaisabel.cl/leche-entera-1l/p", "leche-entera-1l"),
        ("https://www.jumbo.cl/nido-1-800g-2074962/p?idsku=1", "nido-1-800g-2074962"),
        # No es una ficha de producto: sin `/p` no hay SKU que leer.
        ("https://www.jumbo.cl/despensa", None),
        ("https://www.jumbo.cl/p", None),
        (None, None),
    ],
)
def test_el_sku_es_el_slug_de_la_ficha(url, esperado):
    """El JSON-LD no trae GTIN ni el `productId` interno: el slug es la única
    identidad estable, y es la URL canónica que usa la tienda."""
    assert sku_from_url(url) == esperado


def test_las_dos_tiendas_implementan_los_dos_protocolos():
    for cls in (JumboAdapter, SantaIsabelAdapter):
        adapter = cls(_Http(), [])
        assert isinstance(adapter, StoreAdapter)
        assert isinstance(adapter, CountingAdapter)


def test_hosts_y_slugs_distintos_mismo_adaptador():
    """Mismo front, catálogos y departamentos propios: `botilleria` en Santa
    Isabel es `licores-bebidas-y-aguas` en Jumbo."""
    assert JumboAdapter.slug == "jumbo"
    assert JumboAdapter.base_url == "https://www.jumbo.cl"
    assert SantaIsabelAdapter.slug == "santaisabel"
    assert SantaIsabelAdapter.base_url == "https://www.santaisabel.cl"


@pytest.mark.asyncio
async def test_ninguna_de_las_dos_necesita_disfrazar_el_user_agent():
    """Medido el 2026-11-04: `DEFAULT_USER_AGENT` devuelve el listado completo en
    las dos. No hacen UA-sniffing como Easy ni piden el juego completo de
    cabeceras como Tottus — y sus `robots.txt` habilitan a ClaudeBot por nombre.
    """
    http = _Http(PAGINA_1.read_text(encoding="utf-8"), 404)
    adapter = JumboAdapter(http, [CATEGORY])

    _ = [p async for p in adapter.discover(CATEGORY)]

    assert http.headers == [None, None], "no manda cabeceras propias"
    assert "(+ofertascl-bot)" in DEFAULT_USER_AGENT


def test_el_tamano_de_pagina_es_el_que_sirve_la_tienda():
    """40, y no se puede cambiar: ninguna variante de tamaño hace efecto."""
    assert PAGE_SIZE == 40
    assert SantaIsabelAdapter.rate_limit_rps == 0.5, "Crawl-delay: 1 permite 1.0"
