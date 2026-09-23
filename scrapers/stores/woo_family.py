"""Familia WooCommerce: tiendas con la Store API pública.

WooCommerce expone su catálogo sin token ni clave en la Store API v1, que está
pensada para el front del propio carrito:

    GET {base}/wp-json/wc/store/v1/products?per_page=100&page=N&category={id}

El `store_key` es el **id numérico de la categoría** (no el slug), el mismo que
devuelve `/wp-json/wc/store/v1/products/categories`.

Lo que trae y no todas las familias tienen:

- **`is_in_stock` es stock real**, igual que Shopify.
- **`attributes` puede traer EAN y Marca**, así que estas tiendas sí aportan
  identidad de producto. No siempre: en Urban Comercial, 15 de 100 productos
  traían EAN y 32 de 100 traían Marca.

La trampa de la familia es `currency_minor_unit`: la Store API devuelve el
precio como entero **en la unidad mínima de la moneda**. En CLP (cero decimales)
`"6490"` son $6.490, pero la misma API en una tienda en USD devolvería `"649000"`
para $6.490,00. Ver `parse_price`.
"""
from __future__ import annotations

import html
import json
import logging
from collections.abc import AsyncIterator, Sequence
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

from catalog.normalize import clean_text, normalize_brand, normalize_gtin
from scrapers.base import MAX_PLAUSIBLE_CLP, CategoryRef, RawProduct
from scrapers.http import HttpClient

logger = logging.getLogger(__name__)

#: Tope que la Store API acepta en `per_page`.
PAGE_SIZE = 100

#: Nombres de atributo de los que sale la identidad. WooCommerce los deja
#: definir al comerciante, así que son por-tienda en la práctica; estos dos son
#: los que usa Urban Comercial y la convención más común en Woo chileno.
ATTR_BRAND = "marca"
ATTR_GTIN = "ean"


class NotAListingPage(RuntimeError):
    """La categoría no devolvió productos en la página 1.

    La Store API responde **HTTP 200 con `[]` tanto para una categoría
    inexistente como para una página pasada del final** (verificado en vivo:
    `category=99999999` → 200 `[]`). Se distinguen por el número de página, igual
    que en la familia Shopify.
    """


def parse_price(raw: Any, minor_unit: int) -> Decimal | None:
    """Precio de la Store API a CLP entero.

    El valor viene en la **unidad mínima** de la moneda y `currency_minor_unit`
    dice cuántos decimales tiene: con 0 (el caso de CLP) el entero ya es el
    precio; con 2, hay que dividir por 100.

    Un resultado no entero se descarta en vez de redondearse: el sistema guarda
    CLP enteros en todas sus capas, y redondear acá inventaría un precio que la
    tienda no publica.
    """
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None
    try:
        value = Decimal(text)
    except InvalidOperation:
        return None
    if minor_unit:
        value = value / (Decimal(10) ** minor_unit)
    if value != value.to_integral_value():
        logger.warning(
            "woo_precio_no_entero valor=%r minor_unit=%d", text[:32], minor_unit
        )
        return None
    value = value.to_integral_value()
    return value if value > 0 else None


def _attribute(entry: dict[str, Any], name: str) -> str | None:
    """Primer término de un atributo, buscado sin distinguir mayúsculas."""
    for attribute in entry.get("attributes") or []:
        if not isinstance(attribute, dict):
            continue
        if (attribute.get("name") or "").strip().casefold() != name:
            continue
        for term in attribute.get("terms") or []:
            value = clean_text((term or {}).get("name"))
            if value:
                return value
    return None


def _image(entry: dict[str, Any]) -> str | None:
    for image in entry.get("images") or []:
        src = (image or {}).get("src")
        if src:
            return src
    return None


def parse_listing(
    payload: Any,
    *,
    store_slug: str,
    category: CategoryRef,
    scraped_at: datetime,
) -> list[RawProduct]:
    """Convierte una página de la Store API en productos."""
    if not isinstance(payload, list):
        raise NotAListingPage(
            f"{store_slug}/{category.slug}: la respuesta no es una lista de productos"
        )

    products: list[RawProduct] = []
    for entry in payload:
        if not isinstance(entry, dict):
            continue
        product_id = entry.get("id")
        # El nombre viene con entidades HTML: 39 de 100 productos de Urban traen
        # `&#8211;` (guión largo) en el título. Sin desescapar, el copy del canal
        # publicaría la entidad cruda.
        name = clean_text(html.unescape(entry.get("name") or ""))
        permalink = entry.get("permalink")
        if not (product_id and name and permalink):
            continue

        prices = entry.get("prices") or {}
        minor_unit = prices.get("currency_minor_unit")
        minor_unit = int(minor_unit) if isinstance(minor_unit, int) else 0

        price = parse_price(prices.get("price"), minor_unit)
        if price is None:
            logger.debug("sin_precio store=%s id=%s", store_slug, product_id)
            continue
        if price > MAX_PLAUSIBLE_CLP:
            logger.debug(
                "precio_centinela store=%s id=%s valor=%s", store_slug, product_id, price
            )
            continue

        # El "antes" tachado. En Urban, 94 de 100 productos lo traen por encima
        # del precio de venta; se guarda como evidencia y no alimenta el detector.
        claimed_normal = parse_price(prices.get("regular_price"), minor_unit)
        if claimed_normal is not None and claimed_normal <= price:
            claimed_normal = None

        sku = clean_text(entry.get("sku"))
        products.append(
            RawProduct(
                store_slug=store_slug,
                # El id del producto, no el `sku`: mismo criterio que la familia
                # Shopify. El `sku` es texto libre del comerciante.
                store_sku=str(product_id),
                url=permalink,
                name=name,
                price_effective=price,
                price_normal=claimed_normal,
                # WooCommerce no tiene concepto de tarjeta de la casa.
                price_card=None,
                brand=normalize_brand(_attribute(entry, ATTR_BRAND)),
                model=None,
                gtin=normalize_gtin(_attribute(entry, ATTR_GTIN), sku),
                category_path=category.slug,
                image_url=_image(entry),
                claimed_discount=None,
                in_stock=bool(entry.get("is_in_stock")),
                scraped_at=scraped_at,
                raw_payload=entry,
            )
        )

    return products


class _WooFamilyAdapter:
    """Base compartida. Las subclases solo fijan slug y host."""

    slug: str = ""
    rate_limit_rps: float = 0.5
    base_url: str = ""
    #: 100 por página × 20 = 2.000 productos por categoría, más de lo que
    #: cualquier categoría conectada tiene, y un techo si la tienda deja de
    #: respetar `page` y sirve la primera para siempre.
    max_pages: int = 20

    def __init__(self, http: HttpClient, categories: Sequence[CategoryRef]) -> None:
        self._http = http
        self._categories = tuple(categories)

    def categories(self) -> Sequence[CategoryRef]:
        return self._categories

    def _page_url(self, category: CategoryRef, page: int) -> str:
        return (
            f"{self.base_url}/wp-json/wc/store/v1/products"
            f"?per_page={PAGE_SIZE}&page={page}&category={category.store_key}"
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
                category=category,
                scraped_at=scraped_at,
            )

            if not payload:
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

            if fresh == 0:
                break
            page += 1


class UrbanAdapter(_WooFamilyAdapter):
    """Urban Comercial. `store_key` = id numérico de categoría, p. ej. `27`.

    `robots.txt` no declara `Crawl-delay`, así que se usa el default conservador
    de la familia.
    """

    slug = "urban"
    base_url = "https://urbancomercial.cl"
    #: **Esta tienda no lista sus productos agotados.** Las 223 filas de la
    #: categoría 27 vinieron con `is_in_stock: true` el 2026-09-23, en las tres
    #: páginas. O sea que el campo es real pero no discrimina: Woo está
    #: configurado para ocultar lo que no tiene stock.
    #:
    #: El efecto se parece a la ceguera de `in_stock` de Paris y Falabella, pero
    #: es mejor y conviene no confundirlos: acá un producto que se agota
    #: **desaparece del listado**, así que su serie queda con un hueco. Allá se
    #: sigue registrando un precio con `in_stock=True` inventado, que es lo que
    #: de verdad envenena la baseline.
