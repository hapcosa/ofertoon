"""Adaptador de Easy (Cencosud).

Easy corre Next.js sobre un backend VTEX (las imágenes salen de
`easycl.vteximg.com.br`). El listado viene renderizado server-side dentro de
`__NEXT_DATA__`, en `props.pageProps.serverProductsResponse.productList`, 40
productos por página. No se usa la API pública de VTEX
(`/api/catalog_system/pub/products/search`): está muerta en easy.cl (404).

El `store_key` es un path de categoría de 2 o 3 niveles
(`herramientas/herramientas-electricas/taladros-y-atornilladores`), tomado del
árbol que la propia tienda publica en `pageProps.categoriesData`. NO se usa el
buscador: `/search?q=...` responde 404.
"""
from __future__ import annotations

import json
import logging
import re
from collections.abc import AsyncIterator, Sequence
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from catalog.normalize import clean_text, normalize_brand
from scrapers.base import MAX_PLAUSIBLE_CLP, CategoryRef, RawProduct
from scrapers.http import BROWSER_USER_AGENT, FetchError, HttpClient

logger = logging.getLogger(__name__)

_NEXT_DATA = re.compile(
    r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', re.S
)

#: Productos por página que sirve el listado. Solo se usa como cota de cordura.
PAGE_SIZE = 40


class NextDataMissing(RuntimeError):
    """El HTML no trae `__NEXT_DATA__` — la tienda cambió el frontend."""


class NotAListingPage(RuntimeError):
    """La respuesta no trae `serverProductsResponse`: no es un listado.

    Igual que en la familia Falabella, el significado depende de la página:

    - **página 1** → el `store_key` no es una categoría con productos. Puede ser
      un departamento de primer nivel (`/herramientas` renderiza el template
      `/[department]`, que es CMS puro) o un path inexistente. Error de
      configuración: ruidoso.
    - **página > 1** → se pasó del final. Easy no devuelve una lista vacía:
      devuelve la página sin la clave `serverProductsResponse`.
    """


#: Easy responde **HTTP 404** a la primera página que se pasa del final, en vez
#: de servir el shell sin `serverProductsResponse` que documenta
#: `NotAListingPage`. Verificado en vivo el 2026-09-23 sobre
#: `sierras-electricas`: página 8 → 200, página 9 → 404.
#:
#: El 404 llega como `FetchError` desde el cliente HTTP y, antes de este guard,
#: escapaba de `discover` y el runner marcaba `failed` la categoría **entera**.
#: No era solo ruido: el lote pendiente en el buffer se perdía, así que cada
#: corrida fallida tiraba entre 20 y 99 observaciones ya scrapeadas (medido
#: sobre `scrape_runs`, 3 categorías × 2 pasadas/día).
#:
#: Por qué la paginación se pasa del final en vez de cortar con
#: `len(seen) >= total`: `recordsFiltered` cuenta lo que la tienda tiene, y
#: nosotros descartamos los ítems sin precio. `seen` nunca alcanza a `total`.
_END_OF_CATALOG_STATUS = 404


def extract_next_data(html: str) -> dict[str, Any]:
    match = _NEXT_DATA.search(html)
    if match is None:
        raise NextDataMissing("no se encontró el bloque __NEXT_DATA__")
    return json.loads(match.group(1))


def _clp(value: Any) -> Decimal | None:
    """Los precios de Easy ya vienen numéricos en CLP, sin separadores."""
    if value is None:
        return None
    try:
        price = Decimal(str(value))
    except (ArithmeticError, ValueError):
        return None
    return price if price > 0 else None


def resolve_prices(
    product: dict[str, Any],
) -> tuple[Decimal | None, Decimal | None, Decimal | None]:
    """Reparte los precios en (efectivo, normal declarado, tarjeta).

    Easy expone el bloque de precios dos veces: en `prices` (nivel producto) y en
    `commercialOffer.defaultOffer.prices`. Manda el segundo porque es el único
    que trae `brandPrice`; el primero lo deja en `null` sistemáticamente.

    Semántica verificada contra producción (2026-07-31):

    - `offerPrice` — el precio que paga cualquiera. Es el efectivo. Puede venir
      `null`: ahí no hay oferta y el vigente es `normalPrice`.
    - `normalPrice` — el "antes" tachado que declara la tienda. Solo cuenta como
      "antes" si hay un `offerPrice` menor; si no, es simplemente el precio de
      hoy y no hay descuento que declarar.
    - `brandPrice` — precio con **Tarjeta Cencosud**. Confirmado por el
      `cardPromotions` que lo acompaña: `type="payment"`, `id="CAT"` y el monto
      embebido en el nombre (`PF_89990_CENCO...` ↔ `brandPrice: 89990`). Requiere
      plástico de la casa, así que es el análogo del `cmrPrice` de Falabella:
      se guarda para mostrarlo y **queda fuera del detector**.
    """
    offer = (product.get("commercialOffer") or {}).get("defaultOffer") or {}
    prices = offer.get("prices") or product.get("prices") or {}

    normal = _clp(prices.get("normalPrice"))
    offer_price = _clp(prices.get("offerPrice"))
    card = _clp(prices.get("brandPrice"))

    effective = offer_price or normal
    # Sin un precio de oferta más bajo no existe un "antes": el normal ES el hoy.
    claimed_normal = normal if (offer_price and normal and normal > offer_price) else None
    return effective, claimed_normal, card


def _claimed_discount(product: dict[str, Any]) -> str | None:
    """El % que la tienda declara sobre el precio sin tarjeta (promo `general`)."""
    offer = (product.get("commercialOffer") or {}).get("defaultOffer") or {}
    for promo in offer.get("cardPromotions") or []:
        if promo.get("type") == "general":
            return clean_text(promo.get("label"))
    return None


def parse_listing(
    html: str, *, store_slug: str, category: CategoryRef, scraped_at: datetime
) -> tuple[list[RawProduct], int | None]:
    """Extrae los productos de una página de listado y el total de la categoría."""
    page_props = extract_next_data(html)["props"]["pageProps"]
    response = page_props.get("serverProductsResponse")
    if not response:
        raise NotAListingPage(
            f"{store_slug}/{category.slug}: store_key={category.store_key!r} no trae "
            f"serverProductsResponse (claves: {sorted(page_props)[:8]})"
        )

    total = response.get("recordsFiltered")
    products: list[RawProduct] = []

    for item in response.get("productList") or []:
        sku = item.get("sku") or item.get("productId")
        link = item.get("linkText")
        name = clean_text(item.get("productName"))
        if not (sku and link and name):
            continue

        effective, claimed_normal, card = resolve_prices(item)
        if effective is None:
            logger.debug("sin_precio store=%s sku=%s", store_slug, sku)
            continue
        if effective > MAX_PLAUSIBLE_CLP:
            logger.debug(
                "precio_centinela store=%s sku=%s valor=%s", store_slug, sku, effective
            )
            continue

        products.append(
            RawProduct(
                store_slug=store_slug,
                store_sku=str(sku),
                url=f"https://www.easy.cl/{link.lstrip('/')}",
                name=name,
                price_effective=effective,
                price_normal=claimed_normal,
                price_card=card,
                brand=normalize_brand(item.get("brand")),
                category_path=category.slug,
                image_url=item.get("imageUrl"),
                claimed_discount=_claimed_discount(item),
                in_stock=int(item.get("availableQuantity") or 0) > 0,
                scraped_at=scraped_at,
                raw_payload=item,
            )
        )

    return products, total


class EasyAdapter:
    """`store_key` = path de categoría, p. ej.
    `herramientas/herramientas-electricas/taladros-y-atornilladores`.

    Se usan hojas del árbol. Un departamento de primer nivel (`herramientas`)
    renderiza el template `/[department]`, que es CMS y no lista productos —
    `NotAListingPage` lo detecta en la página 1.
    """

    slug = "easy"
    rate_limit_rps: float = 0.5
    base_url = "https://www.easy.cl"
    max_pages = 25

    #: Easy hace UA-sniffing: con el UA identificable del proyecto devuelve
    #: HTTP 200 con la home en vez del listado (ver `BROWSER_USER_AGENT`). Es la
    #: única tienda del MVP que lo exige.
    _headers = {"User-Agent": BROWSER_USER_AGENT}

    def __init__(self, http: HttpClient, categories: Sequence[CategoryRef]) -> None:
        self._http = http
        self._categories = tuple(categories)

    def categories(self) -> Sequence[CategoryRef]:
        return self._categories

    def _page_url(self, category: CategoryRef, page: int) -> str:
        return f"{self.base_url}/{category.store_key.strip('/')}?page={page}"

    async def discover(self, category: CategoryRef) -> AsyncIterator[RawProduct]:
        seen: set[str] = set()
        page = 1

        while page <= self.max_pages:
            url = self._page_url(category, page)
            try:
                html = await self._http.get_text(
                    url, rps=self.rate_limit_rps, headers=self._headers
                )
            except FetchError as exc:
                # Mismo criterio que `NotAListingPage`: en la página 1 un 404 es
                # un `store_key` mal configurado y tiene que ser ruidoso; más
                # allá, es el final del catálogo.
                if exc.status_code != _END_OF_CATALOG_STATUS or page == 1:
                    raise
                logger.debug(
                    "fin_de_catalogo store=%s categoria=%s pagina=%d (HTTP 404)",
                    self.slug,
                    category.slug,
                    page,
                )
                break
            scraped_at = datetime.now(timezone.utc)
            try:
                products, total = parse_listing(
                    html, store_slug=self.slug, category=category, scraped_at=scraped_at
                )
            except NotAListingPage:
                if page == 1:
                    raise
                logger.debug(
                    "fin_de_catalogo store=%s categoria=%s pagina=%d",
                    self.slug,
                    category.slug,
                    page,
                )
                break

            if not products:
                break

            fresh = 0
            for product in products:
                if product.store_sku in seen:
                    continue
                seen.add(product.store_sku)
                fresh += 1
                yield product

            # Si una página entera no aporta un SKU nuevo, la tienda está
            # repitiendo resultados: seguir paginando solo gasta requests.
            if fresh == 0:
                break
            if total and len(seen) >= total:
                break
            page += 1
