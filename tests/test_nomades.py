"""Contract test de `scrapers.stores.nomades` contra payload real.

El fixture son **4 de los Products reales** del `__NEXT_DATA__` de
`nomades.com/san-pedro-de-atacama`, `/roma` y `/amsterdam` (2026-11-05), podados a
los campos que el parser lee (`sku`, `name`, `url`, la primera imagen, `brand` y
el `offers` con `price`/`priceCurrency`/`availability`).

Los 4 no son los primeros del archivo: cada uno ejercita una guarda, y **los
cuatro casos existen en el catálogo de verdad** — no hay ninguno sintético:

| sku | moneda | precio | qué prueba |
|---|---|---|---|
| `3` | CLP | 17.000 | el camino feliz |
| `528` | **USD** | 169 | el filtro de moneda — y es un producto **USD dentro de un destino chileno** (`/san-pedro-de-atacama`), que es la prueba de que la moneda es del producto y no del destino |
| `1536` | **CLP** | **0** | un *free tour*: precio cero en la moneda correcta. Cero no es un precio |
| `2111` | EUR | **37.5** | el único decimal de 144 ofertas medidas |

`numberOfItems` se dejó en **34**, el valor real de la página, aunque el fixture
traiga 4 productos: así el test del canario comprueba que `completeness()` reporta
`(enumerados, declarado)` y no dos veces lo mismo.

El fixture se guarda como JSON y el test lo envuelve en el `<script
id="__NEXT_DATA__">`, que es lo que `parse_listing` busca en el HTML. Guardar
1,4 MB de HTML real para leerle 3 KB de JSON no aportaba nada.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from scrapers.base import CategoryRef
from scrapers.stores.nomades import (
    MONEDA,
    NomadesAdapter,
    NotAListingPage,
    _parse_precio,
    parse_listing,
)

FIXTURE = Path(__file__).parent / "fixtures" / "nomades_san_pedro.json"
CATEGORY = CategoryRef(
    slug="viajes-tours", store_key="san-pedro-de-atacama", label="San Pedro de Atacama"
)
NOW = datetime(2026, 11, 5, 12, 0, tzinfo=timezone.utc)


def html(payload: dict | None = None) -> str:
    """Envuelve el payload como lo sirve Next.js."""
    datos = json.loads(FIXTURE.read_text()) if payload is None else payload
    return (
        "<!doctype html><html><body>"
        f'<script id="__NEXT_DATA__" type="application/json">{json.dumps(datos)}</script>'
        "</body></html>"
    )


def parsear(**kwargs):
    return parse_listing(
        html(), store_slug="nomades", category=CATEGORY, scraped_at=NOW, **kwargs
    )


# --- el camino feliz y las cuatro guardas -------------------------------


def test_emite_solo_la_oferta_en_la_moneda_del_pipeline():
    """De los 4 productos reales, solo uno es publicable hoy.

    Los otros tres se descartan por moneda (USD), por precio cero (CLP) y por
    decimal (EUR). Es el resumen de todo este adaptador en un test.
    """
    productos, enumerados, declarado = parsear()
    assert enumerados == 4
    assert [p.store_sku for p in productos] == ["3"]
    assert productos[0].price_effective == Decimal("17000")


def test_el_filtro_de_moneda_es_por_producto_no_por_destino():
    """`sku=528` es USD y vive en un destino chileno. Ver el docstring."""
    productos, _, _ = parsear()
    assert "528" not in {p.store_sku for p in productos}
    # Y con el pipeline en USD, el que entra es ese y no el de CLP.
    usd, _, _ = parsear(moneda="USD")
    assert [p.store_sku for p in usd] == ["528"]
    assert usd[0].price_effective == Decimal("169")


def test_el_free_tour_de_precio_cero_se_descarta():
    """`sku=1536` es CLP y vale 0: pasa el filtro de moneda y no el de precio."""
    productos, _, _ = parsear()
    assert "1536" not in {p.store_sku for p in productos}


def test_el_precio_con_decimales_se_descarta_en_vez_de_adivinar_la_escala():
    """`sku=2111` es `37.5`. Truncar a 375 o a 3750 son dos errores distintos."""
    eur, _, _ = parsear(moneda="EUR")
    assert [p.store_sku for p in eur] == []


# --- el canario exacto --------------------------------------------------


def test_declara_el_total_y_no_lo_confunde_con_lo_enumerado():
    productos, enumerados, declarado = parsear()
    assert declarado == 34
    assert enumerados == 4
    assert len(productos) == 1


def test_enumerados_cuenta_productos_del_payload_no_emitidos():
    """Mezclarlos volvería heurística la guarda exacta de `completeness()`."""
    _, enumerados, _ = parsear()
    assert enumerados == 4


# --- el contenido de la fila --------------------------------------------


def test_el_store_sku_sale_del_campo_sku():
    producto = parsear()[0][0]
    assert producto.store_sku == "3"
    # y la URL lo repite como sufijo, que es de donde NO se lo lee
    assert producto.url.endswith("-id3")


def test_la_marca_no_es_la_agencia():
    """`brand` es siempre "Nomades": una marca que es la tienda no es identidad."""
    producto = parsear()[0][0]
    assert producto.brand is None


def test_no_se_cree_un_antes_que_la_tienda_no_declara():
    producto = parsear()[0][0]
    assert producto.price_normal is None
    assert producto.price_card is None
    assert producto.gtin is None


def test_la_disponibilidad_se_lee_del_offer():
    producto = parsear()[0][0]
    assert producto.in_stock is True
    assert producto.raw_payload["availability"] == "InStock"


def test_marca_agotado_solo_con_OutOfStock_explicito():
    datos = json.loads(FIXTURE.read_text())
    items = datos["props"]["pageProps"]["schema"]["@graph"][0]["itemListElement"]
    items[0]["item"]["offers"]["availability"] = "https://schema.org/OutOfStock"
    productos, _, _ = parse_listing(
        html(datos), store_slug="nomades", category=CATEGORY, scraped_at=NOW
    )
    assert productos[0].in_stock is False


# --- lo que tiene que fallar ruidosamente -------------------------------


def test_sin_next_data_es_un_store_key_mal_escrito():
    with pytest.raises(NotAListingPage):
        parse_listing(
            "<html><body>nada</body></html>",
            store_slug="nomades",
            category=CATEGORY,
            scraped_at=NOW,
        )


def test_un_payload_sin_products_tambien_grita():
    vacio = {"props": {"pageProps": {"schema": {"@graph": []}}}}
    with pytest.raises(NotAListingPage):
        parse_listing(
            html(vacio), store_slug="nomades", category=CATEGORY, scraped_at=NOW
        )


def test_json_ilegible_grita_en_vez_de_devolver_vacio():
    roto = (
        '<script id="__NEXT_DATA__" type="application/json">{"props":</script>'
    )
    with pytest.raises(NotAListingPage):
        parse_listing(roto, store_slug="nomades", category=CATEGORY, scraped_at=NOW)


# --- `_parse_precio` ----------------------------------------------------


@pytest.mark.parametrize(
    "crudo, esperado",
    [
        (17000, Decimal("17000")),
        ("17000", Decimal("17000")),
        (17000.0, Decimal("17000")),   # el .0 de un float en CLP es ruido
        ("17000.00", Decimal("17000")),
        (37.5, None),                  # el decimal real medido
        ("189.90", None),
        ("1.189,90", None),
        (0, None),
        (-100, None),
        (None, None),
        ("", None),
        (True, None),                  # un bool es int en Python; no es un precio
    ],
)
def test_parse_precio(crudo, esperado):
    assert _parse_precio(crudo) == esperado


# --- el adaptador -------------------------------------------------------


def test_el_adaptador_usa_el_ua_identificable():
    """160 destinos sin un 403 ni un 429 con el UA propio."""
    adapter = NomadesAdapter(None, (CATEGORY,))
    assert "ofertascl-bot" in adapter.headers()["User-Agent"]


def test_la_moneda_por_defecto_es_la_unica_que_el_pipeline_sabe_guardar():
    assert MONEDA == "CLP"
