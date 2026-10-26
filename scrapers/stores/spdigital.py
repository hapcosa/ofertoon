"""Adaptador de SP Digital.

SP Digital corre un front Gatsby estático sobre S3 + Cloudflare y un backend
**Saleor** (GraphQL) detrás de un proxy propio:

    POST https://bff.spdigital.cl/api/v1/saleor
    query(... $categories: [ID!] ...) { products(first: $first after: $after ...) }

El endpoint y el nombre del canal (`sp-digital`) salen del propio bundle de la
tienda (`BASE_API_URL` + `SALEOR_PATH` + `SALEOR_DEFAULT_CHANNEL`), no son una
API privada adivinada. El HTML no sirve: el listado se hidrata en el cliente y
las rutas de categoría se resuelven client-side.

**El 403 del probe inicial era un falso positivo**: `/categories/notebooks/` no
existe como objeto en S3 y Cloudflare devuelve el 403 de AccessDenied con el
shell de la SPA. Con la URL correcta la tienda responde 200, y el endpoint
GraphQL acepta nuestro User-Agent identificable sin `Origin` ni `Referer`. No
hay anti-bot que esquivar acá.

`robots.txt` declara `Crawl-delay: 5` → `rate_limit_rps = 0.2`. Es la tienda más
lenta del MVP a propósito: son ~400 productos en total, no hay apuro.

El `store_key` es el **id Saleor de la categoría** en base64
(`Q2F0ZWdvcnk6MTIzOA==` = `Category:1238`), el mismo que la tienda publica en
`defaultCategoryNameToIDMapping` de su `page-data.json`.

Los tres precios (ver `resolve_prices`) son la parte delicada: el número que
Saleor devuelve como precio **no** es el que la tienda muestra en grande.
"""
from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator, Sequence
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from catalog.normalize import clean_text, normalize_brand, normalize_gtin
from scrapers.base import MAX_PLAUSIBLE_CLP, CategoryRef, RawProduct
from scrapers.http import HttpClient

logger = logging.getLogger(__name__)

API_URL = "https://bff.spdigital.cl/api/v1/saleor"
SITE_BASE = "https://www.spdigital.cl"
CHANNEL = "sp-digital"

#: Saleor cobra por costo de query (`maximumAvailable: 50000`); 50 nodos con
#: estos campos cuesta ~400, así que sobra margen.
PAGE_SIZE = 50

#: Se ordena por nombre y no por relevancia para que la paginación por cursor sea
#: estable entre páginas: un orden que cambia mientras paginamos duplica y saltea.
PRODUCTS_QUERY = """
query($channel: String, $first: Int, $after: String, $categories: [ID!]) {
  products(
    first: $first
    after: $after
    channel: $channel
    filter: {isPublished: true, categories: $categories, stockAvailability: IN_STOCK}
    sortBy: {field: NAME, direction: ASC}
  ) {
    totalCount
    pageInfo { endCursor hasNextPage }
    edges { node {
      id name slug
      metadata { key value }
      defaultVariant { sku quantityAvailable }
      media { url }
      attributes { attribute { slug } values { name } }
      pricing { priceRange { start { gross { amount currency } } } }
    } }
  }
}
"""


class NotAListingPage(RuntimeError):
    """La respuesta no tiene la forma esperada del catálogo."""


def _metadata(node: dict[str, Any]) -> dict[str, str]:
    return {
        m["key"]: m.get("value") or ""
        for m in node.get("metadata") or []
        if isinstance(m, dict) and m.get("key")
    }


def _attributes(node: dict[str, Any]) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for entry in node.get("attributes") or []:
        slug = (entry.get("attribute") or {}).get("slug")
        values = [v.get("name") for v in entry.get("values") or [] if v.get("name")]
        if slug and values:
            out[slug] = values
    return out


def _saleor_amount(node: dict[str, Any]) -> Decimal | None:
    try:
        amount = node["pricing"]["priceRange"]["start"]["gross"]["amount"]
    except (KeyError, TypeError):
        return None
    if amount is None:
        return None
    price = Decimal(str(amount))
    return price if price > 0 else None


def resolve_prices(
    node: dict[str, Any],
) -> tuple[Decimal | None, Decimal | None, str | None]:
    """Reparte los precios en (efectivo, normal declarado, % declarado).

    Acá está la trampa de esta tienda, y es la peor de las cuatro del MVP: **el
    precio que devuelve Saleor no es ninguno de los dos que la tienda muestra**.
    La ficha publica tres números —"Normal" tachado, "Pago con transferencia" y
    "Otros medios de pago"— y el front los deriva así (fórmula copiada del propio
    bundle, módulo `getMetadataPricing`):

        otherPrice    = pricing.priceRange.start.gross.amount   ← lo que da la API
        originalPrice = metadata["pricing"].cash                ← el "Normal" tachado
        cashPrice     = floor(other * cash_meta / other_meta / 10) * 10
        discount      = round((other_meta − other) / other_meta * 100)

    Verificado contra la ficha real de `22u401a-monitor-fhd-215-100hz-2`
    (2026-07-31): API 73.145 → transferencia $69.990, normal $139.990, y la
    tienda declara 50%.

    Consecuencias que definen el mapeo:

    - **`metadata["pricing"].cash` NO es el precio de contado de hoy**: es el
      precio de lista ("Normal"), y es el número tachado. Pese al nombre, tomarlo
      como efectivo publicaría el precio más caro de la ficha — el error inverso
      al de `normal` en PC Factory.
    - `cashPrice` (transferencia bancaria) es lo que paga cualquiera sin plástico
      de ninguna tienda: **ese es `price_effective`**.
    - `otherPrice` es el recargo por tarjeta/otros medios (un 4,5% fijo sobre el
      contado en todo el catálogo muestreado). No se persiste: `price_card` está
      reservado a tarjetas **de la casa** (CMR, Cencosud, BancoEstado) y SP Digital
      no tiene una. Mismo criterio que el precio con crédito de PC Factory.
    """
    other = _saleor_amount(node)
    if other is None:
        return None, None, None

    raw = _metadata(node).get("pricing")
    if not raw:
        # Sin el bloque de metadata no hay forma de derivar el precio de
        # transferencia. Se usa el de otros medios, que es real y más caro: nunca
        # publica una oferta que no existe, solo se pierde una que sí.
        logger.debug("spdigital_sin_metadata_pricing")
        return other, None, None

    try:
        block = json.loads(raw)[CHANNEL]
        cash_meta = Decimal(str(block["cash"]))
        other_meta = Decimal(str(block["other"]))
    except (ValueError, KeyError, TypeError, ArithmeticError):
        logger.warning("spdigital_metadata_pricing_ilegible valor=%r", raw[:120])
        return other, None, None

    if other_meta <= 0 or cash_meta <= 0:
        return other, None, None

    # La misma aritmética del front, con truncado a la decena incluido: cualquier
    # otro redondeo publicaría un precio que la ficha no muestra.
    effective = (other * cash_meta / other_meta / 10).to_integral_value(
        rounding="ROUND_FLOOR"
    ) * 10
    if effective <= 0:
        return other, None, None

    claimed_normal = cash_meta if cash_meta > effective else None
    pct = ((other_meta - other) / other_meta * 100).to_integral_value(
        rounding="ROUND_HALF_EVEN"
    )
    claimed_discount = f"{int(pct)}%" if pct > 0 else None
    return effective, claimed_normal, claimed_discount


def _gtin(metadata: dict[str, str], sku: str) -> str | None:
    """El GTIN solo cuando es un GTIN.

    La tienda rellena el campo con el propio SKU interno (`NA0000086755`) cuando
    no tiene el código de barras. La validación es compartida con las demás
    tiendas (`catalog.normalize.normalize_gtin`): mismo criterio para todas, o el
    matching de F1 hereda un campo con reglas distintas según quién lo escribió.
    """
    return normalize_gtin(metadata.get("gtin"), sku)


def _image(node: dict[str, Any]) -> str | None:
    """Primera imagen del CDN.

    Se descartan las URLs `http://bff.spdigital.cl/thumbnail/...` que la API
    intercala: son del proxy, no del CDN, y van sin TLS.
    """
    for media in node.get("media") or []:
        url = (media or {}).get("url") or ""
        if url.startswith("https://media.spdigital.cl/"):
            return url
    return None


def parse_listing(
    payload: dict[str, Any],
    *,
    store_slug: str,
    category: CategoryRef,
    scraped_at: datetime,
) -> tuple[list[RawProduct], str | None, bool]:
    """Convierte una respuesta GraphQL en productos.

    Devuelve `(items, end_cursor, has_next_page)`.
    """
    products_block = ((payload.get("data") or {}).get("products")) or None
    if products_block is None or "edges" not in products_block:
        errors = payload.get("errors")
        raise NotAListingPage(
            f"{store_slug}/{category.slug}: respuesta sin `data.products.edges` "
            f"(errors: {json.dumps(errors)[:200] if errors else 'ninguno'})"
        )

    page_info = products_block.get("pageInfo") or {}
    end_cursor = page_info.get("endCursor")
    has_next = bool(page_info.get("hasNextPage"))

    products: list[RawProduct] = []
    for edge in products_block.get("edges") or []:
        node = (edge or {}).get("node") or {}
        variant = node.get("defaultVariant") or {}
        sku = variant.get("sku")
        slug = node.get("slug")
        name = clean_text(node.get("name"))
        if not (sku and slug and name):
            continue

        effective, claimed_normal, claimed_discount = resolve_prices(node)
        if effective is None:
            logger.debug("sin_precio store=%s sku=%s", store_slug, sku)
            continue
        if effective > MAX_PLAUSIBLE_CLP:
            logger.debug(
                "precio_centinela store=%s sku=%s valor=%s", store_slug, sku, effective
            )
            continue

        metadata = _metadata(node)
        attributes = _attributes(node)
        quantity = variant.get("quantityAvailable")

        products.append(
            RawProduct(
                store_slug=store_slug,
                store_sku=str(sku),
                url=f"{SITE_BASE}/{slug}/",
                name=name,
                price_effective=effective,
                price_normal=claimed_normal,
                # SP Digital no tiene tarjeta propia: el precio "otros medios" es
                # un recargo por tarjeta bancaria, no un precio de la casa.
                price_card=None,
                brand=normalize_brand((attributes.get("brand") or [None])[0]),
                model=clean_text(metadata.get("mpn")) or None,
                gtin=_gtin(metadata, str(sku)),
                category_path=category.slug,
                image_url=_image(node),
                claimed_discount=claimed_discount,
                # La query ya filtra por `stockAvailability: IN_STOCK`, así que
                # esto es una verificación redundante a propósito: si la tienda
                # cambia la semántica del filtro, el flag sigue siendo correcto.
                in_stock=bool(quantity) and int(quantity) > 0,
                scraped_at=scraped_at,
                raw_payload=node,
            )
        )

    return products, end_cursor, has_next


class SpDigitalAdapter:
    """`store_key` = id Saleor de la categoría en base64, p. ej. `Q2F0ZWdvcnk6MTIzOA==`."""

    slug = "spdigital"
    #: `Crawl-delay: 5` en su robots.txt. Se respeta.
    rate_limit_rps: float = 0.2
    max_pages = 40

    def __init__(self, http: HttpClient, categories: Sequence[CategoryRef]) -> None:
        self._http = http
        self._categories = tuple(categories)
        #: store_key → (edges enumerados, totalCount declarado) de la última
        #: `discover`. Alimenta el chequeo de completitud del runner; ver
        #: `scrapers.base.CountingAdapter`.
        self._completeness: dict[str, tuple[int, int]] = {}

    def categories(self) -> Sequence[CategoryRef]:
        return self._categories

    def completeness(self, category: CategoryRef) -> tuple[int, int] | None:
        return self._completeness.get(category.store_key)

    def _body(self, category: CategoryRef, cursor: str | None) -> dict[str, Any]:
        return {
            "query": PRODUCTS_QUERY,
            "variables": {
                "channel": CHANNEL,
                "first": PAGE_SIZE,
                "after": cursor,
                "categories": [category.store_key],
            },
        }

    async def discover(self, category: CategoryRef) -> AsyncIterator[RawProduct]:
        seen: set[str] = set()
        cursor: str | None = None
        enumerated = 0
        declared: int | None = None
        self._completeness.pop(category.store_key, None)

        for page in range(self.max_pages):
            raw = await self._http.post_json(
                API_URL, self._body(category, cursor), rps=self.rate_limit_rps
            )
            scraped_at = datetime.now(timezone.utc)
            payload = json.loads(raw)
            products, end_cursor, has_next = parse_listing(
                payload,
                store_slug=self.slug,
                category=category,
                scraped_at=scraped_at,
            )

            block = (payload.get("data") or {}).get("products") or {}
            enumerated += len(block.get("edges") or [])
            if declared is None and isinstance(block.get("totalCount"), int):
                # Se toma de la primera página y no se vuelve a mirar: si el
                # inventario se mueve mientras paginamos, la referencia tiene que
                # ser la del arranque o el chequeo se persigue la cola.
                declared = block["totalCount"]
            if declared is not None:
                self._completeness[category.store_key] = (enumerated, declared)

            if not products and page == 0:
                # Un id de categoría inexistente devuelve `edges: []` con HTTP
                # 200 y sin errores. Sin este guard, una llave mal escrita se
                # vería idéntica a una categoría sin stock.
                raise NotAListingPage(
                    f"{self.slug}/{category.slug}: store_key="
                    f"{category.store_key!r} no devolvió productos"
                )

            fresh = 0
            for product in products:
                if product.store_sku in seen:
                    continue
                seen.add(product.store_sku)
                fresh += 1
                yield product

            if not has_next or not end_cursor or fresh == 0:
                break
            cursor = end_cursor
