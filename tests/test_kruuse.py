"""Contract test del adaptador Kruuse contra un fixture real de su feed.

El fixture son 7 de los 3.772 productos de `/cl/product-feed.json` (capturado el
2026-09-26), podados a los campos que el parser lee — de cada entrada se sacaron
`description`, `technical_specs`, `highlights`, `images` y los `shipping_*`. El
`product_count` se bajó a 7 para que el fixture sea internamente consistente; el
caso del feed truncado se prueba aparte, moviendo ese campo.

Los 7 son los casos que hacen distinta a esta tienda:

- Tres en **`Lijadoras`** con las tres disponibilidades que importan
  (`in_stock`, `backorder`, `out_of_stock`): con ellos se prueba de una vez el
  filtrado por categoría y la regla de stock, que acá es la que decide si la
  tienda publica o no.
- Uno en **`Corte y Poda`**, para que el filtro tenga contra qué contrastar.
- Uno **sin GTIN** (44 de los 3.772).
- Uno con **`price: null`** — es una variante `-ADDON`, y son 5 en el catálogo.
- Uno **sobre `MAX_PLAUSIBLE_CLP`**: una plegadora de $115.099.000 que es una
  máquina real, no un centinela. Se descarta igual, y eso es una decisión tomada.
"""
from __future__ import annotations

import json
import logging
from decimal import Decimal
from pathlib import Path

import pytest

from scrapers.base import CategoryRef
from scrapers.stores.kruuse import (
    PAGE_SIZE,
    CategoryNotInFeed,
    FeedShapeChanged,
    KruuseAdapter,
    parse_page,
    parse_price,
    to_product,
)

FIXTURE = Path(__file__).parent / "fixtures" / "kruuse_product_feed.json"

LIJADORAS = CategoryRef(
    slug="ferre-herramientas", store_key="Lijadoras", label="Lijadoras"
)
PODA = CategoryRef(slug="ferre-jardin", store_key="Corte y Poda", label="Corte y poda")


def _feed() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def _entradas(category: CategoryRef) -> list[dict]:
    return [e for e in _feed()["products"] if (e.get("category") or "") == category.store_key]


@pytest.fixture
def http():
    """Cliente falso: una respuesta por página, y cuenta las requests."""

    class _Http:
        def __init__(self, *paginas: str) -> None:
            self.paginas = paginas or (FIXTURE.read_text(encoding="utf-8"),)
            self.urls: list[str] = []

        async def get_text(self, url: str, **kw: object) -> str:
            self.urls.append(url)
            indice = min(len(self.urls), len(self.paginas)) - 1
            pagina = self.paginas[indice]
            if isinstance(pagina, Exception):
                raise pagina
            return pagina

    return _Http


# -----------------------------------------------------------------------------
# El parseo de una entrada
# -----------------------------------------------------------------------------


@pytest.fixture(scope="module")
def lijadoras():
    from datetime import datetime, timezone

    ahora = datetime(2026, 9, 26, 16, 0, tzinfo=timezone.utc)
    entradas = [
        e
        for e in json.loads(FIXTURE.read_text(encoding="utf-8"))["products"]
        if (e.get("category") or "") == "Lijadoras"
    ]
    return [
        to_product(e, store_slug="kruuse", category=LIJADORAS, scraped_at=ahora)
        for e in entradas
    ]


def test_las_tres_lijadoras_se_emiten(lijadoras):
    assert [p.store_sku for p in lijadoras] == ["5909240900", "5901500", "5903825901"]
    assert all(p.store_slug == "kruuse" for p in lijadoras)
    assert all(p.category_path == "ferre-herramientas" for p in lijadoras)


def test_precios_enteros_en_clp(lijadoras):
    """El feed ya los da enteros: ni unidad mínima ni decimales."""
    assert [p.price_effective for p in lijadoras] == [
        Decimal("99990"),
        Decimal("3999000"),
        Decimal("259990"),
    ]
    for p in lijadoras:
        assert p.price_effective == p.price_effective.to_integral_value()


def test_solo_in_stock_cuenta_como_disponible(lijadoras):
    """`backorder` es la mayoría del catálogo y NO es disponible.

    3.467 de 3.772 productos están en backorder: Kruuse vende a pedido. Si
    `backorder` contara como stock, esta tienda publicaría ofertas de máquinas que
    no se pueden comprar hoy, que es exactamente lo que el proyecto existe para no
    hacer.
    """
    assert [p.in_stock for p in lijadoras] == [True, False, False]
    disponibilidades = [p.raw_payload["availability"] for p in lijadoras]
    assert disponibilidades == ["in_stock", "backorder", "out_of_stock"]


def test_el_gtin_es_la_identidad_de_esta_tienda(lijadoras):
    """GTIN-13 en 3.728 de 3.772. Con Ferretek, sostienen el matching del sistema."""
    assert [p.gtin for p in lijadoras] == [
        "4046664216810",
        "4036351053750",
        "4046664249337",
    ]


def test_el_mpn_no_se_usa_como_modelo(lijadoras):
    """`mpn` es igual al `sku` en 3.772 de 3.772: es su código, no un modelo.

    Tomarlo como modelo inventaría pares (marca, modelo) capaces de fusionar dos
    productos distintos de dos tiendas — lo que la regla 6 prohíbe.
    """
    entradas = _entradas(LIJADORAS)
    assert all(e["mpn"] == e["sku"] for e in entradas)
    assert all(p.model is None for p in lijadoras)


def test_marca_y_sin_descuento_declarado(lijadoras):
    assert [p.brand for p in lijadoras] == ["Scheppach", "Holzstar", "Scheppach"]
    # `sale_price` viene nulo en los 3.772 y `regular_price` es idéntico a `price`.
    assert all(p.price_normal is None for p in lijadoras)
    assert all(p.price_card is None for p in lijadoras)
    assert all(p.claimed_discount is None for p in lijadoras)


def test_sin_gtin_no_es_un_error():
    """44 de los 3.772 no lo traen: se emiten igual, sin identidad."""
    from datetime import datetime, timezone

    entrada = next(e for e in _feed()["products"] if e["sku"] == "227909201713")
    categoria = CategoryRef(
        slug="ferre-herramientas", store_key="Kits de Baterías y Cargadores"
    )
    producto = to_product(
        entrada,
        store_slug="kruuse",
        category=categoria,
        scraped_at=datetime(2026, 9, 26, tzinfo=timezone.utc),
    )
    assert producto is not None
    assert producto.gtin is None
    assert producto.price_effective == Decimal("99990")


@pytest.mark.parametrize(
    "sku, motivo",
    [
        ("3100131-ADDON", "price null: las variantes -ADDON no tienen precio propio"),
        ("3779403", "sobre MAX_PLAUSIBLE_CLP: $115.099.000"),
    ],
)
def test_lo_que_no_se_emite(sku, motivo):
    from datetime import datetime, timezone

    entrada = next(e for e in _feed()["products"] if e["sku"] == sku)
    assert (
        to_product(
            entrada,
            store_slug="kruuse",
            category=LIJADORAS,
            scraped_at=datetime(2026, 9, 26, tzinfo=timezone.utc),
        )
        is None
    ), motivo


@pytest.mark.parametrize(
    "crudo, esperado",
    [
        (249990, Decimal("249990")),
        (1, Decimal("1")),
        (0, None),
        (-1000, None),
        (None, None),
        # El feed los da enteros; un string o un float serían un cambio de forma
        # y no algo que haya que interpretar.
        ("249990", None),
        (249990.0, None),
        (True, None),
    ],
)
def test_parse_price(crudo, esperado):
    assert parse_price(crudo) == esperado


def test_una_respuesta_sin_products_es_cambio_de_forma():
    with pytest.raises(FeedShapeChanged):
        parse_page({"product_count": 3772})
    with pytest.raises(FeedShapeChanged):
        parse_page([])


# -----------------------------------------------------------------------------
# El adaptador: el feed se baja una vez por pasada
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_filtra_por_el_nombre_de_categoria_de_la_tienda(http):
    cliente = http()
    adapter = KruuseAdapter(cliente, [LIJADORAS, PODA])

    lija = [p async for p in adapter.discover(LIJADORAS)]
    poda = [p async for p in adapter.discover(PODA)]

    assert [p.store_sku for p in lija] == ["5909240900", "5901500", "5903825901"]
    assert [p.store_sku for p in poda] == ["5911606400"]
    assert cliente.urls == [
        f"https://kruuse.cl/cl/product-feed.json?page=1&limit={PAGE_SIZE}"
    ], "dos categorías, una sola bajada del feed"


@pytest.mark.asyncio
async def test_todas_las_categorias_comparten_el_mismo_scraped_at(http):
    """El feed se leyó una vez; las 21 categorías son esa misma lectura."""
    adapter = KruuseAdapter(http(), [LIJADORAS, PODA])

    lija = [p async for p in adapter.discover(LIJADORAS)]
    poda = [p async for p in adapter.discover(PODA)]

    assert {p.scraped_at for p in lija + poda} == {lija[0].scraped_at}


@pytest.mark.asyncio
async def test_una_llave_que_no_existe_en_el_feed_es_ruidosa(http):
    """Los nombres de categoría son texto libre: si la tienda renombra una, la
    llave dejaría de recolectar en silencio."""
    renombrada = CategoryRef(slug="ferre-herramientas", store_key="Lijadoras Orbitales")
    adapter = KruuseAdapter(http(), [renombrada])

    with pytest.raises(CategoryNotInFeed):
        async for _ in adapter.discover(renombrada):
            pass


@pytest.mark.asyncio
async def test_sigue_has_more_hasta_el_final(http):
    p1 = _feed()
    p1["has_more"] = True
    p1["product_count"] = 8
    p2 = _feed()
    p2["page"] = 2
    p2["has_more"] = False
    p2["products"] = [dict(p2["products"][0], sku="OTRO-SKU", id="prod_otro")]

    cliente = http(json.dumps(p1), json.dumps(p2))
    adapter = KruuseAdapter(cliente, [LIJADORAS])

    productos = [p async for p in adapter.discover(LIJADORAS)]

    assert len(cliente.urls) == 2
    assert "page=2" in cliente.urls[1]
    assert "OTRO-SKU" in {p.store_sku for p in productos}


@pytest.mark.asyncio
async def test_un_feed_caido_se_intenta_una_sola_vez_por_pasada(http):
    """Sin cachear el fallo, una tienda caída se lleva 21 × 38 requests.

    Cada categoría igual queda `failed` —no recolectó nada—, pero el feed se
    intenta una vez.
    """
    from scrapers.http import FetchError

    cliente = http(FetchError("503", status_code=503))
    adapter = KruuseAdapter(cliente, [LIJADORAS, PODA])

    for categoria in (LIJADORAS, PODA, LIJADORAS):
        with pytest.raises(FetchError):
            async for _ in adapter.discover(categoria):
                pass

    assert len(cliente.urls) == 1


@pytest.mark.asyncio
async def test_avisa_si_el_feed_no_trajo_lo_que_declara(http, caplog):
    """Un feed truncado no corta la pasada: lo bajado son observaciones válidas.

    La caída proporcional la ve el canario estadístico de cada categoría; esto es
    para poder explicarla después.
    """
    truncado = _feed()
    truncado["product_count"] = 3772  # dice 3.772 y trae 7

    adapter = KruuseAdapter(http(json.dumps(truncado)), [LIJADORAS])
    with caplog.at_level(logging.WARNING):
        productos = [p async for p in adapter.discover(LIJADORAS)]

    assert len(productos) == 3, "lo que llegó se ingiere igual"
    assert "feed_incompleto" in caplog.text
    assert "declarados=3772" in caplog.text


@pytest.mark.asyncio
async def test_avisa_si_el_feed_deja_de_respetar_el_limite(http, caplog):
    """Este feed clampea honesto y reporta el `limit` que aplicó.

    Es el contraste con `product_list_limit` de Magento, que ante un valor que no
    ofrece cae al default con HTTP 200 y sin decir nada.
    """
    recortado = _feed()
    recortado["limit"] = 25

    adapter = KruuseAdapter(http(json.dumps(recortado)), [LIJADORAS])
    with caplog.at_level(logging.WARNING):
        _ = [p async for p in adapter.discover(LIJADORAS)]

    assert "limite_no_respetado" in caplog.text
    assert "aplicado=25" in caplog.text
