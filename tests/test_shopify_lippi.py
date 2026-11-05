"""Contract test del modo `emitir_por_producto` de la familia Shopify, con Lippi.

El fixture es la respuesta de producción (2026-11-04) de
`/collections/{poleras-hombre,impermeables-hombre}/products.json?limit=250&page=1`,
podada a **2 de los ~1.800 productos** y a los campos que el parser lee (`id`,
`handle`, `title`, `vendor`, la primera imagen y, por variante, `id`/`title`/
`price`/`compare_at_price`/`available`/`featured_image`).

Los 2 se eligieron para cubrir lo que distingue a este modo, y no son los
primeros del archivo:

- **Liquen Celeste** tiene 5 talles con **dos precios distintos** (4.990 y 9.990)
  y **uno solo disponible**. Es el 0,6% medido: casi ningún producto de Lippi
  tiene precios distintos entre talles, y este existe. Trae además un
  `compare_at_price` (14.990) que **sí** supera al precio.
- **Adventure Page** tiene 5 talles al **mismo** precio, 4 disponibles, y su
  `compare_at_price` es **igual** al precio — el caso que la guarda de la familia
  tiene que descartar en vez de publicar un descuento de 0%.

⚠️ Lo que el fixture NO tiene, porque **no se observó en el catálogo**: un
producto con **todos** los talles agotados. En las 5 colecciones medidas no
apareció ninguno, lo que sugiere que Lippi oculta el producto cuando se le agotan
todos los talles (el mismo tamiz de disponibilidad que en Prat separa catálogo de
vitrina). Ese caso y el del talle más barato agotado se prueban **sintéticos y
marcados como tales**: son las dos ramas de `_elegir_variante` que deciden si se
publica un precio que nadie puede pagar, así que no pueden quedar sin test
esperando a que la tienda produzca el dato.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from scrapers.base import CategoryRef
from scrapers.http import BROWSER_USER_AGENT
from scrapers.stores.shopify_family import (
    LippiAdapter,
    PratAdapter,
    _elegir_variante,
    parse_listing,
)

FIXTURE = Path(__file__).parent / "fixtures" / "lippi_collection_poleras.json"
CATEGORY = CategoryRef(
    slug="deporte-vestuario", store_key="poleras-hombre", label="Poleras Hombre"
)
NOW = datetime(2026, 11, 4, 12, 0, tzinfo=timezone.utc)
BASE = "https://www.lippioutdoor.com"

#: id del producto con dos precios y un solo talle disponible.
LIQUEN = "8206448886081"
#: id del producto con los 5 talles al mismo precio.
ADVENTURE = "10042817773889"


def payload() -> dict:
    return json.loads(FIXTURE.read_text())


def parsear(**kwargs):
    return parse_listing(
        payload(),
        store_slug="lippi",
        base_url=BASE,
        category=CATEGORY,
        scraped_at=NOW,
        **kwargs,
    )


def por_sku(productos):
    return {p.store_sku: p for p in productos}


# --- el modo por producto -------------------------------------------------


def test_emite_una_fila_por_producto_y_no_una_por_talle():
    """Es la razón de existir del flag: 2 productos de 5 talles son 2 filas."""
    productos = parsear(emitir_por_producto=True)
    assert len(productos) == 2
    # Y el default sigue siendo una por variante: los mismos 2 productos son 10.
    assert len(parsear()) == 10


def test_el_store_sku_es_el_id_del_producto():
    productos = por_sku(parsear(emitir_por_producto=True))
    assert set(productos) == {LIQUEN, ADVENTURE}


def test_la_url_no_lleva_parametro_de_variante():
    """Con una fila por producto, la ficha es la del producto."""
    p = por_sku(parsear(emitir_por_producto=True))[LIQUEN]
    assert p.url == f"{BASE}/products/polera-hombre-liquen-celeste-geography"
    assert "?variant=" not in p.url


def test_el_nombre_no_arrastra_el_talle():
    """Colgarle "S" al nombre nombraría mal lo que se publica."""
    p = por_sku(parsear(emitir_por_producto=True))[LIQUEN]
    assert p.name == "Polera Hombre Liquen Celeste Geography"
    # Por variante, en cambio, el talle sí distingue la fila.
    nombres = {x.name for x in parsear()}
    assert f"{p.name} S" in nombres


def test_el_precio_sale_del_talle_disponible_mas_barato():
    """Liquen: S a 4.990 disponible, L/XL/XXL a 9.990 agotados."""
    p = por_sku(parsear(emitir_por_producto=True))[LIQUEN]
    assert p.price_effective == Decimal("4990")
    assert p.in_stock is True


def test_in_stock_es_alguna_talla_disponible():
    """Adventure tiene la L agotada y 4 talles a la venta: es comprable."""
    p = por_sku(parsear(emitir_por_producto=True))[ADVENTURE]
    assert p.in_stock is True
    assert p.price_effective == Decimal("22990")


def test_el_antes_que_no_supera_al_precio_se_descarta():
    """Adventure declara compare_at == price: un descuento de 0% no es un antes."""
    p = por_sku(parsear(emitir_por_producto=True))[ADVENTURE]
    assert p.price_normal is None
    # Liquen sí trae uno real, y se guarda como evidencia (nunca como señal).
    assert por_sku(parsear(emitir_por_producto=True))[LIQUEN].price_normal == Decimal(
        "14990"
    )


def test_no_hay_gtin_en_ningun_modo():
    """`products.json` no expone `barcode`: 0 de 9.773 variantes medidas."""
    assert all(p.gtin is None for p in parsear(emitir_por_producto=True))
    assert all(p.gtin is None for p in parsear())


def test_el_vendor_de_lippi_es_marca_y_no_se_descarta():
    productos = por_sku(parsear(emitir_por_producto=True))
    assert productos[LIQUEN].brand == "Geography"
    assert productos[ADVENTURE].brand == "Lippi"


# --- `_elegir_variante`: las dos ramas que el catálogo no produjo ---------
#
# SINTÉTICOS a propósito. Ver el docstring del módulo: deciden si se publica un
# precio que nadie puede pagar, y esperar a que Lippi los produzca dejaría la
# guarda sin test.


def _v(vid, price, available):
    return {"id": vid, "price": price, "available": available}


def test_el_talle_mas_barato_agotado_no_gana():
    """El caso que justifica la regla: tomar el agotado publica un precio falso."""
    elegida = _elegir_variante(
        [_v(1, "4990", False), _v(2, "9990", True), _v(3, "12990", True)]
    )
    assert elegida["id"] == 2


def test_sin_ningun_talle_disponible_cae_al_mas_barato():
    """No se descarta el producto: se emite con el precio más bajo y agotado."""
    elegida = _elegir_variante([_v(1, "9990", False), _v(2, "4990", False)])
    assert elegida["id"] == 2


def test_sin_precio_usable_no_hay_variante():
    """Un producto sin precio no es una observación, es un hueco en la serie."""
    assert _elegir_variante([_v(1, None, True), _v(2, "", True)]) is None
    assert _elegir_variante([]) is None


def test_la_variante_sin_id_no_puede_representar_al_producto():
    assert _elegir_variante([{"price": "4990", "available": True}]) is None


def test_un_precio_con_decimales_se_descarta_al_elegir():
    """La guarda de escala de `parse_price` vale también acá: no se adivina."""
    elegida = _elegir_variante([_v(1, "189.90", True), _v(2, "9990", True)])
    assert elegida["id"] == 2


# --- que el flag sea por tienda ------------------------------------------


def test_prat_no_hereda_el_modo_por_producto():
    """Cambiarle la granularidad a Prat le reiniciaría el reloj de MIN_DAYS."""
    assert PratAdapter.emitir_por_producto is False
    assert LippiAdapter.emitir_por_producto is True


def test_lippi_no_manda_headers_de_navegador():
    """Es el INVERSO de Prat y está medido: ver el docstring de `LippiAdapter`.

    Con `BROWSER_HEADERS` Lippi responde 403 las 4 veces y con
    `BROWSER_HEADERS_JSON` 429 las 4 veces; con el `DEFAULT_USER_AGENT`
    identificable, 200 las 4 veces. Copiarle el `_headers` de `PratAdapter`
    —que es lo natural al mirar la familia— trae el 429 de vuelta, así que este
    `None` es carga estructural y no un olvido.
    """
    assert LippiAdapter._headers is None
    assert PratAdapter._headers == {"User-Agent": BROWSER_USER_AGENT}


def test_lippi_deduplica_por_pasada_y_prat_no():
    """Medido: 4.481 filas → 3.418 productos únicos (1,311×) en sus 76 hojas.

    Y lo que hace seguro el dedupe es **dónde** cae: de las 1.191 coincidencias,
    las 1.191 caen dentro de la misma categoría interna y **cero** cruzan
    categorías. Prat tiene 3 colecciones no jerárquicas y no lo necesita.
    """
    assert LippiAdapter.dedupe_across_categories is True
    assert PratAdapter.dedupe_across_categories is False


def test_el_dedupe_de_pasada_no_corta_la_paginacion():
    """`locales` y `seen` son dos conjuntos distintos, y confundirlos cortaría la
    paginación en la primera página cuyos productos ya entraron por otra
    colección — el bug que `magento_html` documenta y que en Andesgear dejó tres
    categorías a medias.

    Acá se comprueba la estructura: el adaptador arranca con el conjunto de
    pasada vacío y es un atributo de la instancia (vive una pasada), no global.
    """
    a = LippiAdapter(None, (CATEGORY,))
    b = LippiAdapter(None, (CATEGORY,))
    assert a._visto_en_la_pasada == set()
    a._visto_en_la_pasada.add("x")
    assert b._visto_en_la_pasada == set(), "el conjunto no puede ser compartido"
