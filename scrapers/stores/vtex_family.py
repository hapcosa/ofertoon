"""Familia VTEX: tiendas con la API pública de catálogo de VTEX.

    GET /api/catalog_system/pub/products/search?fq=C:/<path>/&_from=N&_to=M

VTEX es la plataforma de buena parte del retail chileno, así que esta familia
destraba varias tiendas con un solo adaptador — el plan la quería para Colloky y
la Fase 3 entera. La primera en usarla es Nike.

Tres cosas de VTEX que no son obvias y que definen este módulo:

1. **Contesta `206 Partial Content`, siempre.** El rango que se pide con
   `_from`/`_to` es parcial respecto del total, así que 206 es la respuesta normal
   y completa. Está resuelto en `http.SUCCESS_STATUS`; sin eso el primer fetch
   moría con `FetchError: HTTP 206`.

2. **El total de la categoría viene en un HEADER, no en el cuerpo**:
   `Resources: 0-49/2546`. De ahí sale `completeness()`, o sea el canario
   **exacto** del runner, que es la guarda más barata que tiene. Por eso esta
   familia usa `get_with_headers` y no `get_text`.

3. **Un producto tiene N items y los items son los talles.** Un zapato es un
   `product` con 10 `items`, todos al mismo precio. Emitir uno por talle
   multiplicaría los listings por 10 con series idénticas, así que se emite **uno
   por producto** (ver `_elegir_item`).

El `store_key` es el path de categorías de VTEX **sin** barras de los extremos:
`2/3` es `nike/calzado`. Se arma `fq=C:/2/3/`.
"""
from __future__ import annotations

import json
import logging
import re
from collections.abc import AsyncIterator, Iterable, Sequence
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from scrapers.base import CategoryRef, RawProduct
from scrapers.http import BROWSER_HEADERS_JSON, HttpClient

logger = logging.getLogger(__name__)

#: Máximo que VTEX devuelve por request. Pedir más no da error: devuelve 50.
PAGE_SIZE = 50

#: VTEX corta la paginación profunda: `_from` por encima de ~2.500 devuelve error.
#: No es un límite nuestro y no se puede subir, así que una categoría con más de
#: eso **no se puede enumerar completa** y hay que partirla en subcategorías. El
#: canario exacto lo grita solo: enumerados < declarados.
MAX_OFFSET = 2500


class NotAListingPage(RuntimeError):
    """El `store_key` no corresponde a una categoría con productos."""


def _clp(valor: Any) -> Decimal | None:
    """Precio de VTEX (`119990.0`, float) a CLP entero.

    VTEX serializa los precios como float y en CLP no hay centavos, así que el
    decimal es siempre `.0`. Se trunca explícitamente en vez de confiar: un
    `Decimal(str(119990.0))` deja `119990.0` y arrastra un decimal fantasma a una
    columna que es entera por definición de dominio.
    """
    if valor is None:
        return None
    try:
        entero = Decimal(str(valor)).to_integral_value()
    except Exception:
        return None
    return entero if entero > 0 else None


def _oferta(item: dict[str, Any]) -> dict[str, Any]:
    """`commertialOffer` del primer seller, o `{}`."""
    sellers = item.get("sellers") or []
    if not sellers:
        return {}
    return sellers[0].get("commertialOffer") or {}


def _disponible(item: dict[str, Any]) -> bool:
    oferta = _oferta(item)
    return bool(oferta.get("IsAvailable")) and (oferta.get("AvailableQuantity") or 0) > 0


def _elegir_item(items: Sequence[dict[str, Any]]) -> dict[str, Any] | None:
    """Qué talle representa al producto.

    Se emite **un** `RawProduct` por producto, no uno por talle: los talles de un
    zapato comparten precio, así que uno por talle multiplicaría los listings por
    10 con series idénticas y haría pesar al mismo producto diez veces en
    cualquier agregado.

    Gana el **disponible más barato**, y si ninguno está disponible, el más
    barato. Que sea el disponible importa: el detector rechaza por stock, y tomar
    el precio de un talle agotado publicaría un precio que nadie puede pagar.
    """
    con_precio = [(i, _clp(_oferta(i).get("Price"))) for i in items]
    con_precio = [(i, p) for i, p in con_precio if p is not None]
    if not con_precio:
        return None
    disponibles = [(i, p) for i, p in con_precio if _disponible(i)]
    pool = disponibles or con_precio
    return min(pool, key=lambda par: par[1])[0]


def _imagen(item: dict[str, Any]) -> str | None:
    for img in item.get("images") or []:
        url = img.get("imageUrl")
        if url:
            return url
    return None


def _categoria_path(producto: dict[str, Any]) -> str | None:
    cats = producto.get("categories") or []
    return cats[0].strip("/").replace("/", " > ") if cats else None


def parse_listing(
    payload: Iterable[dict[str, Any]],
    *,
    store_slug: str,
    category: CategoryRef,
    scraped_at: datetime,
) -> list[RawProduct]:
    """Productos de una respuesta de `products/search`.

    Lo que se descarta y por qué:

    - **Sin item con precio** → no hay nada que medir. VTEX deja productos
      publicados sin oferta activa.
    - **Precio fuera del techo de plausibilidad** → lo rechaza `RawProduct` en su
      `__post_init__`, y acá se traga el error y se sigue: un centinela de una
      tienda no puede tumbar la categoría entera.

    `price_normal` sale de `ListPrice` **solo si es mayor** que el precio de
    venta. VTEX repite el mismo valor en los dos campos cuando no hay descuento, y
    guardar un "antes" igual al "ahora" ensuciaría la evidencia de cuánto miente
    cada tienda.
    """
    salida: list[RawProduct] = []
    for producto in payload:
        items = producto.get("items") or []
        item = _elegir_item(items)
        if item is None:
            continue

        oferta = _oferta(item)
        precio = _clp(oferta.get("Price"))
        if precio is None:
            continue

        lista = _clp(oferta.get("ListPrice"))
        normal = lista if lista is not None and lista > precio else None

        sku = str(item.get("itemId") or producto.get("productId") or "").strip()
        if not sku:
            continue

        # `in_stock` mira TODOS los talles: el producto es comprable si alguno
        # está disponible, aunque el talle que da el precio no lo esté.
        hay_stock = any(_disponible(i) for i in items)

        try:
            salida.append(
                RawProduct(
                    store_slug=store_slug,
                    store_sku=sku,
                    url=str(producto.get("link") or ""),
                    name=str(producto.get("productName") or item.get("name") or "").strip(),
                    price_effective=precio,
                    scraped_at=scraped_at,
                    in_stock=hay_stock,
                    brand=(producto.get("brand") or None),
                    # `productReference` es el código de modelo del fabricante
                    # (`CW2288-111`), que es lo que `catalog/identity` usa como
                    # modelo cuando no hay GTIN.
                    model=(producto.get("productReference") or None),
                    gtin=(str(item.get("ean")).strip() or None) if item.get("ean") else None,
                    category_path=_categoria_path(producto),
                    price_normal=normal,
                    image_url=_imagen(item),
                    claimed_discount=None,
                )
            )
        except ValueError as exc:
            # Centinela de precio: se descarta el producto, no la categoría.
            logger.warning(
                "precio_implausible store=%s categoria=%s sku=%s: %s",
                store_slug,
                category.slug,
                sku,
                exc,
            )
    return salida


def parse_total(resources: str | None) -> int | None:
    """`'0-49/2546'` → `2546`. El total declarado, del header `Resources`.

    Es la fuente del canario exacto. Si el header falta o cambia de forma se
    devuelve `None` y el runner cae al canario estadístico — degradar a la guarda
    más débil es correcto; inventar un total no.
    """
    if not resources:
        return None
    m = re.search(r"/(\d+)\s*$", resources.strip())
    return int(m.group(1)) if m else None


class _VtexFamilyAdapter:
    """Base compartida. Las subclases fijan slug, host y rate limit."""

    slug: str = ""
    base_url: str = ""
    rate_limit_rps: float = 0.5
    #: Headers de navegador con `Accept: application/json`. Para las tiendas VTEX
    #: detrás de Cloudflare —Nike es una— un cliente HTTP pelado recibe 403: lo
    #: que delata no es el User-Agent sino la ausencia de `Accept-Language` y la
    #: familia `Sec-Fetch-*`. Ver `http.BROWSER_HEADERS`.
    _headers: dict[str, str] | None = BROWSER_HEADERS_JSON

    def __init__(self, http: HttpClient, categories: Sequence[CategoryRef]) -> None:
        self._http = http
        self._categories = tuple(categories)
        self._completeness: dict[str, tuple[int, int]] = {}

    def categories(self) -> Sequence[CategoryRef]:
        return self._categories

    def completeness(self, category: CategoryRef) -> tuple[int, int] | None:
        return self._completeness.get(category.store_key)

    def _page_url(self, category: CategoryRef, desde: int) -> str:
        hasta = desde + PAGE_SIZE - 1
        path = category.store_key.strip("/")
        return (
            f"{self.base_url}/api/catalog_system/pub/products/search"
            f"?fq=C:/{path}/&_from={desde}&_to={hasta}"
        )

    async def discover(self, category: CategoryRef) -> AsyncIterator[RawProduct]:
        self._completeness.pop(category.store_key, None)
        vistos: set[str] = set()
        enumerados = 0
        declarado: int | None = None
        desde = 0

        while desde <= MAX_OFFSET:
            crudo, headers = await self._http.get_with_headers(
                self._page_url(category, desde),
                rps=self.rate_limit_rps,
                headers=self._headers,
            )
            scraped_at = datetime.now(timezone.utc)
            payload = json.loads(crudo)
            if not isinstance(payload, list):
                raise NotAListingPage(
                    f"{self.slug}/{category.slug}: store_key="
                    f"{category.store_key!r} no devolvió una lista"
                )

            if desde == 0:
                # El total se lee una sola vez, igual que en la familia Magento: si
                # el catálogo se mueve mientras paginamos, la referencia tiene que
                # ser la del arranque o el chequeo se persigue la cola.
                declarado = parse_total(headers.get("resources"))
                if not payload:
                    raise NotAListingPage(
                        f"{self.slug}/{category.slug}: store_key="
                        f"{category.store_key!r} no devolvió productos"
                    )

            if not payload:
                break

            enumerados += len(payload)
            nuevos = 0
            for producto in parse_listing(
                payload,
                store_slug=self.slug,
                category=category,
                scraped_at=scraped_at,
            ):
                if producto.store_sku in vistos:
                    continue
                vistos.add(producto.store_sku)
                nuevos += 1
                yield producto

            # Una página con productos que no aporta ni un SKU nuevo es el síntoma
            # de una tienda que dejó de respetar `_from` y sirve la primera para
            # siempre. Mismo criterio que la familia Magento.
            if desde > 0 and payload and nuevos == 0:
                logger.warning(
                    "pagina_repetida store=%s categoria=%s desde=%d",
                    self.slug,
                    category.slug,
                    desde,
                )
                break

            if len(payload) < PAGE_SIZE:
                break
            desde += PAGE_SIZE

        if declarado is not None:
            if declarado > MAX_OFFSET:
                # No es un fallo del adaptador: VTEX no deja paginar más profundo.
                # Se avisa para que la categoría se parta en subcategorías.
                logger.warning(
                    "categoria_mas_grande_que_el_tope store=%s categoria=%s "
                    "declarado=%d tope=%d",
                    self.slug,
                    category.slug,
                    declarado,
                    MAX_OFFSET,
                )
            self._completeness[category.store_key] = (enumerados, declarado)


class NikeAdapter(_VtexFamilyAdapter):
    """Nike Chile. `store_key` = path de categorías VTEX, p. ej. `2/3` (nike/calzado).

    Su API pública de catálogo está abierta y **trae `ean` por talle**, que es lo
    más valioso para `catalog/identity`: CLAUDE.md registra que de 3.357 `products`
    solo 11 tienen 2+ tiendas porque las tiendas con GTIN casi no se solapan.

    Está detrás de Cloudflare y con `DEFAULT_USER_AGENT` responde **403**; con el
    juego completo de headers de navegador, 200. Lo hereda de la familia.

    Árbol medido el 2026-10-01: `nike` (id 2) con `calzado` (3), `ropa` (4) y
    `accesorios` (5), y `snkrs` (6) con sus tres. El total de la tienda son 2.546
    productos, así que **las llaves son las subcategorías y no el raíz**: `2` sola
    declara más que el tope de paginación de VTEX.
    """

    slug = "nike"
    base_url = "https://www.nike.cl"
    #: Su `robots.txt` no declara `Crawl-delay`. Se usa el default conservador: el
    #: catálogo entero son ~51 requests por pasada, la velocidad no hace falta.
    rate_limit_rps = 0.5
