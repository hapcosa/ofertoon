"""Disponibilidad del candidato, leída de su ficha justo antes de publicar.

Existe porque `in_stock` es ciego en cuatro tiendas: Paris, Falabella, Sodimac y
Tottus no dicen nada de stock en el listado y el adaptador lo asume `True`, así
que la guarda del detector (`reject_reason = 'out_of_stock'`) no protege nada en
22.000 de los 35.000 listings. La ficha sí lo dice, y abrirla **solo para el
candidato** cuesta 10-30 fetches al día en vez de 22.000.

Vive en `publisher/` y no en `scrapers/` a propósito: no alimenta la serie ni la
baseline, y no corrige la detección. Es la última guarda antes de lo irreversible.

Cuánto arregla, medido el 2026-10-02 sobre los 40 candidatos aceptados más
recientes de Falabella y Sodimac: **39 disponibles, 1 agotado**, señal legible en
los 40. O sea ~2,5%, un pulido de una oferta cada cinco días a la cuota actual —
no un salto de precisión. Se hace igual porque publicar algo que no se puede
comprar es el peor error posible justo en lo que el canal promete.

**La duda nunca bloquea.** Una tienda sin verificador, una ficha que no responde o
un formato que cambió devuelven `None`, y `None` publica. El costo de publicar una
oferta agotada es menor que el de callar el canal porque una ficha no contestó.
"""
from __future__ import annotations

import json
import logging
import re

from scrapers.http import BROWSER_HEADERS, FetchError, HttpClient

logger = logging.getLogger("publisher.stock")

#: Tiendas cuya ficha sabemos leer. Las tres corren la plataforma de Falabella
#: (`__NEXT_DATA__` + JSON-LD de schema.org), así que es un solo lector.
#:
#: Paris **no está**: su ficha trae un JSON-LD de Product pero **sin**
#: `offers.availability` (verificado el 2026-10-02 contra una ficha real), así que
#: no hay de dónde leerlo todavía. Queda devolviendo `None`, que no bloquea.
FAMILIA_FALABELLA = frozenset({"falabella", "sodimac", "tottus"})

#: Rate limit de estas consultas. Son 10-30 por día contra tiendas que ya
#: aceptan 0,5 rps en la ingesta: no hay razón para ir más rápido y sí para que
#: una ráfaga de candidatos no se note en su borde.
RPS = 0.5

_NEXT_DATA = re.compile(
    r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', re.S
)
_AVAILABILITY = re.compile(r'"availability"\s*:\s*"([^"]+)"')


def leer_disponibilidad(html: str) -> bool | None:
    """`True` disponible, `False` agotado, `None` si la ficha no lo dice.

    Dos señales, en orden de confianza, las dos verificadas contra fichas reales
    el 2026-10-02:

    1. `isOutOfStock` del `__NEXT_DATA__`. Es lo que la propia página usa para
       habilitar el botón de compra: la fuente, no un reflejo.
    2. `offers.availability` del JSON-LD de schema.org, como respaldo.

    Se prefiere la primera porque el JSON-LD trae **varias** ofertas por ficha
    (Falabella publica una por seller y una por forma de pago: en una ficha medida
    había dos `Offer`, $189.990 y $309.990). Con varias, "agotado" sale de que lo
    diga la primera que aparece, y eso es una heurística; `isOutOfStock` es un solo
    booleano sobre el SKU.

    ⚠️ **`isOutOfStock` cambia de lugar entre fichas** y eso ya costó un agujero.
    Está en `pageProps` en algunas y en `pageProps.productData` en otras, así que se
    miran las dos. Mirando solo la primera, dos de catorce fichas quedaban sin
    señal — **y las dos estaban agotadas**: el fallback de "no sé, publico" se
    activaba exactamente en el caso que esta guarda existe para atajar, porque las
    fichas que traen el dato anidado son justamente las que no traen
    `availability` en su JSON-LD.
    """
    m = _NEXT_DATA.search(html)
    if m:
        try:
            page_props = json.loads(m.group(1))["props"]["pageProps"]
        except (ValueError, KeyError, TypeError):
            page_props = {}
        if not isinstance(page_props, dict):
            page_props = {}
        producto = page_props.get("productData")
        for fuente in (page_props, producto if isinstance(producto, dict) else {}):
            if isinstance(fuente.get("isOutOfStock"), bool):
                return not fuente["isOutOfStock"]

    for match in _AVAILABILITY.finditer(html):
        valor = match.group(1).lower()
        if "outofstock" in valor or "soldout" in valor:
            return False
        if "instock" in valor:
            return True
    return None


def sabe_leer(store_slug: str | None) -> bool:
    """¿Tenemos lector para la ficha de esta tienda?

    Se expone aparte de `verificar` para que el llamador distinga "no se intentó"
    de "se intentó y no se supo". No es un detalle: si se registrara
    `stock_checked_at` para una tienda sin lector, el dataset no podría separar las
    dos cosas, y el daemon haría un UPDATE inútil por cada candidato de esa tienda
    en cada vuelta de 5 minutos.
    """
    return store_slug in FAMILIA_FALABELLA


async def verificar(http: HttpClient, *, store_slug: str, url: str) -> bool | None:
    """Abre la ficha del candidato y devuelve su disponibilidad.

    `None` cuando no se sabe, y no saber no bloquea: tienda sin verificador, fetch
    fallido o ficha con un formato que cambió. Los tres casos se loguean distinto
    porque significan cosas distintas — el tercero es el que avisa de que la tienda
    movió el dato y hay que volver a mirar.
    """
    if not sabe_leer(store_slug):
        return None

    try:
        html = await http.get_text(url, rps=RPS, headers=BROWSER_HEADERS)
    except FetchError as exc:
        # Que la ficha no responda no puede costar la publicación.
        logger.warning("stock_no_verificado store=%s url=%s: %s", store_slug, url, exc)
        return None

    disponible = leer_disponibilidad(html)
    if disponible is None:
        # Esta tienda SÍ tiene verificador, así que una ficha sin señal es un
        # cambio de formato y no un caso previsto.
        logger.warning(
            "stock_sin_senal store=%s url=%s — la ficha ya no trae isOutOfStock "
            "ni availability; revisar el lector",
            store_slug,
            url,
        )
    return disponible
