"""Familia Shopify: tiendas que exponen `/products.json`.

Cualquier tienda Shopify publica su catálogo en JSON sin token:

    GET {base}/collections/{handle}/products.json?limit=250&page=N

No es una API privada adivinada: es el endpoint público que Shopify sirve por
defecto en todos sus storefronts. El `store_key` es el **handle de la colección**
(`herramientas-electricas`), el mismo que aparece en la URL de la tienda.

Lo que esta familia trae y ninguna otra del sistema tenía: **`variants[].available`
es stock real**. Paris y Falabella asumen `in_stock=True` a ciegas, así que la
guarda de stock del detector no las protege; acá sí. En la primera muestra de
Ferretería Prat, 113 de 250 variantes de `herramientas-electricas` estaban
agotadas — o sea que el 45% de ese catálogo no debería producir una oferta.

Lo que NO trae: **`products.json` no expone `barcode`** (verificado contra Prat y
consistente con Doite). La identidad de producto sale solo de `vendor`, así que
estas tiendas aportan señal de precio pero casi nada de comparación cross-store.
Por la regla de identidad del sistema (GTIN → marca+modelo → nada), eso es
aceptable: degrada el copy, nunca la señal.
"""
from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator, Sequence
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from catalog.normalize import clean_text, normalize_brand
from scrapers.base import MAX_PLAUSIBLE_CLP, CategoryRef, RawProduct
from scrapers.http import HttpClient

logger = logging.getLogger(__name__)

#: Tope que Shopify acepta en `limit`. Pedir más devuelve 250 igual.
PAGE_SIZE = 250


class NotAListingPage(RuntimeError):
    """La colección no devolvió productos en la página 1.

    Shopify responde **HTTP 200 con `{"products": []}` tanto para un handle
    inexistente como para una página pasada del final** (verificado en vivo:
    `/collections/no-existe-xyz/products.json` → 200 `{"products":[]}`). Los dos
    casos son indistinguibles por el payload, así que los distingue el número de
    página, igual que en Falabella y Easy:

    - **página 1 vacía** → el `store_key` está mal escrito. Error de
      configuración: tiene que ser ruidoso.
    - **página > 1 vacía** → fin normal del catálogo.
    """


def parse_price(raw: Any) -> Decimal | None:
    """Precio de Shopify a CLP entero, rechazando los que traen decimales.

    Shopify serializa el precio como **string en la unidad mayor de la moneda de
    la tienda**: en CLP (cero decimales) es `"181990"`, pero una tienda en USD
    sirve `"189.90"`. `catalog.normalize.parse_clp` borra todo lo que no sea
    dígito, así que un `"1819.90"` se convertiría en 181.990 en silencio — un
    error de 100× que nadie notaría hasta ver una oferta imposible.

    Como esta familia está pensada para crecer a varias tiendas, la guarda no
    asume que todas estén en CLP: cualquier precio con separador decimal se
    descarta y se logea en vez de adivinar la escala.
    """
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None
    if "." in text or "," in text:
        logger.warning("shopify_precio_con_decimales valor=%r", text[:32])
        return None
    if not text.isdigit():
        return None
    price = Decimal(text)
    return price if price > 0 else None


def _image(product: dict[str, Any], variant: dict[str, Any]) -> str | None:
    featured = (variant.get("featured_image") or {}).get("src")
    if featured:
        return featured
    for image in product.get("images") or []:
        src = (image or {}).get("src")
        if src:
            return src
    return None


def parse_listing(
    payload: dict[str, Any],
    *,
    store_slug: str,
    base_url: str,
    category: CategoryRef,
    scraped_at: datetime,
    non_brand_vendors: frozenset[str] = frozenset(),
) -> list[RawProduct]:
    """Convierte una página de `/products.json` en productos.

    Emite **una fila por variante**, no por producto: cada variante tiene su
    propio precio y su propio stock, y son las que la tienda vende.
    """
    products_raw = payload.get("products")
    if not isinstance(products_raw, list):
        raise NotAListingPage(
            f"{store_slug}/{category.slug}: la respuesta no trae la lista `products`"
        )

    products: list[RawProduct] = []
    for entry in products_raw:
        if not isinstance(entry, dict):
            continue
        handle = entry.get("handle")
        title = clean_text(entry.get("title"))
        if not (handle and title):
            continue

        vendor = clean_text(entry.get("vendor")) or ""
        brand = (
            None
            if vendor.casefold() in non_brand_vendors
            else normalize_brand(vendor)
        )

        for variant in entry.get("variants") or []:
            if not isinstance(variant, dict):
                continue
            variant_id = variant.get("id")
            if variant_id is None:
                continue

            price = parse_price(variant.get("price"))
            if price is None:
                logger.debug(
                    "sin_precio store=%s handle=%s variante=%s",
                    store_slug,
                    handle,
                    variant_id,
                )
                continue
            if price > MAX_PLAUSIBLE_CLP:
                logger.debug(
                    "precio_centinela store=%s variante=%s valor=%s",
                    store_slug,
                    variant_id,
                    price,
                )
                continue

            # El "antes" tachado. Se guarda como evidencia y NUNCA se usa para
            # calcular el descuento — en Prat vale exactamente price/0.9 en 249
            # de 250 productos (ver la nota de la clase PratAdapter).
            claimed_normal = parse_price(variant.get("compare_at_price"))
            if claimed_normal is not None and claimed_normal <= price:
                claimed_normal = None

            # El nombre de la variante se agrega solo cuando distingue algo: la
            # variante única de un producto simple se llama "Default Title".
            variant_title = clean_text(variant.get("title"))
            name = (
                f"{title} {variant_title}"
                if variant_title and variant_title.casefold() != "default title"
                else title
            )

            products.append(
                RawProduct(
                    store_slug=store_slug,
                    # La variante, no el `sku`: el id es el identificador que
                    # Shopify garantiza único y estable, mientras que el `sku` es
                    # texto libre del comerciante. Dos variantes con el mismo sku
                    # fundirían dos productos distintos en una sola serie de
                    # precios, que es el peor error posible acá; un id que cambia
                    # solo cuesta volver a esperar los 30 días de baseline.
                    store_sku=str(variant_id),
                    url=f"{base_url}/products/{handle}?variant={variant_id}",
                    name=name,
                    price_effective=price,
                    price_normal=claimed_normal,
                    # Shopify no tiene concepto de tarjeta de la casa.
                    price_card=None,
                    brand=brand,
                    # `products.json` no expone `barcode` ni un modelo limpio.
                    model=None,
                    gtin=None,
                    category_path=category.slug,
                    image_url=_image(entry, variant),
                    # La tienda no declara un porcentaje; el "antes" queda en
                    # `price_normal`, que es donde se puede auditar.
                    claimed_discount=None,
                    in_stock=bool(variant.get("available")),
                    scraped_at=scraped_at,
                    raw_payload=variant,
                )
            )

    return products


class _ShopifyFamilyAdapter:
    """Base compartida. Las subclases solo fijan slug, host y vendors basura."""

    slug: str = ""
    rate_limit_rps: float = 0.5
    base_url: str = ""
    #: Con 250 por página, 20 páginas son 5.000 productos por colección: más de
    #: lo que cualquier colección conectada tiene, y un techo si la tienda
    #: empieza a ignorar `page` y nos sirve la primera para siempre.
    max_pages: int = 20
    #: Valores de `vendor` que NO son una marca. Shopify obliga a llenar el campo
    #: y los comerciantes ponen su propio nombre o un placeholder. Se comparan en
    #: casefold. Ante la duda se descarta: una marca equivocada degrada el copy.
    non_brand_vendors: frozenset[str] = frozenset()

    def __init__(self, http: HttpClient, categories: Sequence[CategoryRef]) -> None:
        self._http = http
        self._categories = tuple(categories)

    def categories(self) -> Sequence[CategoryRef]:
        return self._categories

    def _page_url(self, category: CategoryRef, page: int) -> str:
        return (
            f"{self.base_url}/collections/{category.store_key}"
            f"/products.json?limit={PAGE_SIZE}&page={page}"
        )

    async def discover(self, category: CategoryRef) -> AsyncIterator[RawProduct]:
        seen: set[str] = set()
        page = 1

        while page <= self.max_pages:
            raw = await self._http.get_text(
                self._page_url(category, page), rps=self.rate_limit_rps
            )
            scraped_at = datetime.now(timezone.utc)
            payload = json.loads(raw)
            products = parse_listing(
                payload,
                store_slug=self.slug,
                base_url=self.base_url,
                category=category,
                scraped_at=scraped_at,
                non_brand_vendors=self.non_brand_vendors,
            )

            if not payload.get("products"):
                if page == 1:
                    raise NotAListingPage(
                        f"{self.slug}/{category.slug}: store_key="
                        f"{category.store_key!r} no devolvió productos"
                    )
                logger.debug(
                    "fin_de_catalogo store=%s categoria=%s pagina=%d",
                    self.slug,
                    category.slug,
                    page,
                )
                break

            fresh = 0
            for product in products:
                if product.store_sku in seen:
                    continue
                seen.add(product.store_sku)
                fresh += 1
                yield product

            # Sin variantes nuevas no hay nada que ganar en la página siguiente:
            # o la tienda dejó de respetar `page`, o el resto son duplicados.
            if fresh == 0:
                break
            page += 1


class PratAdapter(_ShopifyFamilyAdapter):
    """Ferretería Prat. `store_key` = handle de colección, p. ej. `jardin`.

    **El `compare_at_price` de esta tienda no es un precio anterior**: en la
    muestra del 2026-09-23, 249 de los 250 productos de `herramientas-electricas`
    declaraban exactamente 10,0% de descuento —rango 10,0%..10,0%, sin una sola
    excepción— y la colección `jardin` repite el patrón. Es un margen fijo que la
    tienda aplica a todo el catálogo, no una oferta.

    Es el ejemplo más limpio de por qué el descuento se mide contra la baseline
    propia: quien confíe en el `price_normal` de Prat publica el catálogo entero
    como oferta permanente del 10%.

    `robots.txt` no declara `Crawl-delay` y permite el catálogo público, así que
    se usa el default conservador de la familia.
    """

    slug = "prat"
    base_url = "https://ferreteriaprat.cl"
    #: `pratcl` es la propia tienda y `NO DEFINIDO` su placeholder.
    non_brand_vendors = frozenset({"pratcl", "prat", "no definido"})
