"""Adaptadores de Falabella y Sodimac.

Las dos tiendas corren sobre el mismo frontend (`falabella-b2c-ui`) y devuelven
un `__NEXT_DATA__` con la MISMA forma, verificado contra ambas: el listado viene
renderizado server-side en `props.pageProps.results`, con `pagination` al lado.
Por eso comparten parser y solo se diferencian en host y prefijo de path.

No se usa el BFF interno (`/s/browse/v1/listing/cl`): existe y responde, pero
exige `pgid`, `pid` (uuid de ubicación) y la lista completa de `zones`, que son
efímeros y se obtienen... del mismo HTML. Parsear el SSR es más simple y menos
frágil que sostener esos tres parámetros.
"""
from __future__ import annotations

import json
import logging
import re
from collections.abc import AsyncIterator, Sequence
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from catalog.normalize import clean_text, normalize_brand, parse_clp
from scrapers.base import MAX_PLAUSIBLE_CLP, CategoryRef, RawProduct
from scrapers.http import HttpClient

logger = logging.getLogger(__name__)

_NEXT_DATA = re.compile(
    r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', re.S
)

#: Precio con tarjeta propia de la casa. Requiere plástico → NO es el precio que
#: paga cualquiera, así que queda fuera del detector (se guarda para mostrarlo).
_CARD_PRICE_TYPES = frozenset({"cmrPrice"})
#: El "antes" tachado que declara la tienda. Es exactamente el número que se
#: infla, así que se guarda como evidencia y nunca alimenta el descuento.
_CLAIMED_NORMAL_TYPES = frozenset({"normalPrice"})


class NextDataMissing(RuntimeError):
    """El HTML no trae `__NEXT_DATA__` — la tienda cambió el frontend."""


class NotAListingPage(RuntimeError):
    """La respuesta no trae `results`: no es una página de listado.

    Ocurre en dos situaciones que el llamador debe distinguir por número de página:

    - **página 1** → el `store_key` está mal (par id/nombre incongruente), la
      tienda sirvió una landing. Es un error de configuración y debe ser ruidoso.
    - **página > 1** → se pasó del final del catálogo. Falabella y Sodimac no
      devuelven una lista vacía ahí: devuelven un shell sin la clave `results`.
      Es el fin normal de la paginación.

    `discover()` hace esa distinción; el parser solo reporta el hecho.
    """


def extract_next_data(html: str) -> dict[str, Any]:
    match = _NEXT_DATA.search(html)
    if match is None:
        raise NextDataMissing("no se encontró el bloque __NEXT_DATA__")
    return json.loads(match.group(1))


def resolve_prices(
    prices: Sequence[dict[str, Any]],
) -> tuple[Decimal | None, Decimal | None, Decimal | None]:
    """Reparte los precios de un producto en (efectivo, normal declarado, tarjeta).

    Tipos observados en producción: `cmrPrice`, `internetPrice`, `eventPrice`,
    `normalPrice`. El efectivo es el MÍNIMO de los precios pagables sin tarjeta
    de la casa y no tachados; si no hay ninguno, cae al normal no tachado.
    """
    card: Decimal | None = None
    claimed_normal: Decimal | None = None
    payable: list[Decimal] = []
    fallback: list[Decimal] = []

    for entry in prices:
        raw = entry.get("price")
        value = parse_clp(raw[0] if isinstance(raw, list) and raw else raw)
        if value is None:
            continue

        price_type = entry.get("type") or ""
        if price_type in _CARD_PRICE_TYPES:
            card = value if card is None else min(card, value)
            continue
        if price_type in _CLAIMED_NORMAL_TYPES:
            claimed_normal = value if claimed_normal is None else min(claimed_normal, value)
            # Un normalPrice sin tachar es el precio vigente (no hay oferta).
            if not entry.get("crossed"):
                fallback.append(value)
            continue
        if not entry.get("crossed"):
            payable.append(value)

    effective = min(payable) if payable else (min(fallback) if fallback else None)
    return effective, claimed_normal, card


def parse_listing(
    html: str, *, store_slug: str, category: CategoryRef, scraped_at: datetime
) -> tuple[list[RawProduct], dict[str, Any]]:
    """Extrae los productos de una página de listado y su bloque de paginación."""
    page_props = extract_next_data(html)["props"]["pageProps"]
    if "results" not in page_props:
        raise NotAListingPage(
            f"{store_slug}/{category.slug}: store_key={category.store_key!r} no es una "
            f"categoría hoja (claves: {sorted(page_props)[:8]})"
        )
    results = page_props.get("results") or []
    pagination = page_props.get("pagination") or {}

    products: list[RawProduct] = []
    for item in results:
        sku = item.get("skuId") or item.get("productId")
        url = item.get("url")
        name = clean_text(item.get("displayName"))
        if not (sku and url and name):
            continue

        effective, claimed_normal, card = resolve_prices(item.get("prices") or [])
        if effective is None:
            # Sin precio pagable no hay serie que construir; se descarta en vez
            # de inventar un cero que ensucie la baseline.
            logger.debug("sin_precio store=%s sku=%s", store_slug, sku)
            continue
        if effective > MAX_PLAUSIBLE_CLP:
            # Centinela de la tienda ($99.999.999.999) para productos sin precio
            # real. Se descarta acá, no en RawProduct, para que un placeholder no
            # aborte la pasada completa de la categoría.
            logger.debug(
                "precio_centinela store=%s sku=%s valor=%s", store_slug, sku, effective
            )
            continue

        media = item.get("mediaUrls") or []
        badge = item.get("discountBadge") or {}

        products.append(
            RawProduct(
                store_slug=store_slug,
                store_sku=str(sku),
                url=url,
                name=name,
                price_effective=effective,
                price_normal=claimed_normal,
                price_card=card,
                brand=normalize_brand(item.get("brand")),
                category_path=category.slug,
                image_url=media[0] if media else None,
                claimed_discount=clean_text(badge.get("label")),
                in_stock=True,  # el listado solo devuelve comprables
                scraped_at=scraped_at,
                raw_payload=item,
            )
        )

    return products, pagination


class _FalabellaFamilyAdapter:
    """Base compartida. Las subclases solo fijan slug, host y path."""

    slug: str = ""
    rate_limit_rps: float = 0.5
    base_url: str = ""
    #: Prefijo del listado por categoría. `store_key` es el resto del path
    #: (`cat70057/Notebooks`), así que NO se url-encodea: lleva `/` significativo.
    listing_path: str = ""
    max_pages: int = 20

    def __init__(self, http: HttpClient, categories: Sequence[CategoryRef]) -> None:
        self._http = http
        self._categories = tuple(categories)

    def categories(self) -> Sequence[CategoryRef]:
        return self._categories

    def _page_url(self, category: CategoryRef, page: int) -> str:
        return f"{self.base_url}{self.listing_path}/{category.store_key}?page={page}"

    async def discover(self, category: CategoryRef) -> AsyncIterator[RawProduct]:
        seen: set[str] = set()
        page = 1

        while page <= self.max_pages:
            url = self._page_url(category, page)
            html = await self._http.get_text(url, rps=self.rate_limit_rps)
            scraped_at = datetime.now(timezone.utc)
            try:
                products, pagination = parse_listing(
                    html, store_slug=self.slug, category=category, scraped_at=scraped_at
                )
            except NotAListingPage:
                if page == 1:
                    # El store_key está mal configurado: no hay nada que salvar.
                    raise
                # Fin del catálogo: pasada la última página, la tienda devuelve un
                # shell sin `results` en vez de una lista vacía.
                logger.debug(
                    "fin_de_catalogo store=%s categoria=%s pagina=%d",
                    self.slug,
                    category.slug,
                    page,
                )
                break

            if not products:
                break

            # Guarda de paginación honesta: si la tienda nos devuelve una página
            # distinta de la pedida, está ignorando el parámetro (Sodimac lo hacía
            # al 301-redirigir /search y perder el query string). Seguir pidiendo
            # páginas sería releer la misma una y otra vez.
            served = pagination.get("currentPage")
            if served is not None and int(served) != page:
                logger.warning(
                    "paginacion_ignorada store=%s categoria=%s pedida=%d servida=%s",
                    self.slug,
                    category.slug,
                    page,
                    served,
                )
                for product in products:
                    if product.store_sku not in seen:
                        seen.add(product.store_sku)
                        yield product
                break

            fresh = 0
            for product in products:
                if product.store_sku in seen:
                    continue
                seen.add(product.store_sku)
                fresh += 1
                yield product

            # La paginación de Falabella repite resultados cuando se pasa del
            # final; sin SKUs nuevos, se corta aunque `count` prometa más.
            if fresh == 0:
                break

            total = pagination.get("count") or 0
            if len(seen) >= total:
                break
            page += 1


class FalabellaAdapter(_FalabellaFamilyAdapter):
    """`store_key` = path de categoría, p. ej. `cat70057/Notebooks`.

    Se navega por categoría y NO por término de búsqueda. El buscador funciona y
    pagina bien, pero su resultado es difuso: "celular" devolvía ~940 items con
    accesorios, fundas y televisores mezclados. Como el umbral de descuento del
    detector se aplica **por categoría**, un SKU mal clasificado recibe el umbral
    equivocado y se convierte en un falso positivo o en una oferta que nunca se
    publica. El path de categoría es la clasificación de la propia tienda.

    El `store_key` debe ser el par id/nombre EXACTO que publica la tienda. Si el
    nombre no corresponde al id (`cat7090034/Notebooks`), Falabella redirige a una
    landing de CMS cuyo `__NEXT_DATA__` trae `containers` y no `results` — de ahí
    `NotAListingPage`.

    Se usan categorías hoja. Las de nivel alto son listados válidos pero inútiles
    para el detector: `cat7090034/Tecnologia` devuelve 201.124 productos bajo un
    solo umbral de descuento, que es justamente lo que se quiere evitar.
    """

    slug = "falabella"
    base_url = "https://www.falabella.com"
    listing_path = "/falabella-cl/category"


class SodimacAdapter(_FalabellaFamilyAdapter):
    """`store_key` = path de categoría, p. ej. `cat14080023/Taladros`.

    Además de la razón de clasificación que aplica a toda la familia, en Sodimac
    el buscador directamente no es una opción: `/sodimac-cl/search?Ntt=...`
    responde 301 hacia la categoría equivalente y **descarta el query string**,
    con lo que `page` se pierde y toda pasada devuelve la página 1.
    """

    slug = "sodimac"
    base_url = "https://www.sodimac.cl"
    listing_path = "/sodimac-cl/lista"
