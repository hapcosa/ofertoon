"""Adaptador de Paris (Cencosud).

Paris corre Next.js con App Router. El listado que llega en el HTML **no sirve**
para este sistema por una razón concreta: el servidor **ignora los parámetros de
query**. `?page=2`, `?offset=30` y `?start=30` devuelven el mismo cuerpo byte a
byte que la página sin parámetros (verificado 2026-07-31, 3.485.015 bytes en los
cuatro casos). El SSR entrega siempre los primeros 30 productos y el "ver más"
lo resuelve el cliente contra un microservicio.

Ese microservicio es lo que se usa acá:

    POST https://be-paris-backend-cl-ms-api.ccom.paris.cl/products/
    {"filters":[{"key":"group_id","stringValues":["<store_key>"]}],
     "pagination":{"page":1,"pageSize":40},"sortBy":"relevance","term":""}

Sale del propio bundle de la tienda (`PRODUCTS_HOST` +
`createHttpProductListRepository`), no es una API privada adivinada. Es además
~100× más barato que las 3,4 MB de HTML por página.

El `store_key` es el **id de grupo** de la categoría (`tecCelSmartphones`), el
mismo que aparece en `categories[].id` de cada producto y en el `group_id` que
usa el PLP.
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

API_URL = "https://be-paris-backend-cl-ms-api.ccom.paris.cl/products/"
SITE_BASE = "https://www.paris.cl"
LOCALE = "es-CL"

#: El front redondea el pageSize a múltiplos de 5 y usa 40 en la grilla ancha.
PAGE_SIZE = 40


class NotAListingPage(RuntimeError):
    """La respuesta no tiene la forma esperada del catálogo."""


def _localized(value: Any) -> str | None:
    """Paris devuelve `name` y `slug` como diccionarios por locale."""
    if isinstance(value, dict):
        return clean_text(value.get(LOCALE))
    return clean_text(value)


def _money(block: Any) -> Decimal | None:
    """Convierte un `{value: {centAmount, fractionDigits}}` de commercetools.

    En CLP `fractionDigits` es 0 y `centAmount` ya es el monto entero, pero se
    respeta el campo en vez de asumirlo: si la tienda algún día publica con 2
    decimales, asumir 0 multiplicaría cada precio por cien.
    """
    if not isinstance(block, dict):
        return None
    value = block.get("value")
    if not isinstance(value, dict):
        return None
    amount = value.get("centAmount")
    if amount is None:
        return None
    try:
        price = Decimal(str(amount)) / (10 ** int(value.get("fractionDigits") or 0))
    except (ArithmeticError, ValueError):
        return None
    return price if price > 0 else None


def resolve_prices(
    prices: dict[str, Any],
) -> tuple[Decimal | None, Decimal | None, Decimal | None]:
    """Reparte los precios en (efectivo, normal declarado, tarjeta).

    Paris publica hasta tres bloques, con nombres que dicen lo que son:

    - `offer` — el precio de hoy, sin condiciones. Es el efectivo.
    - `regular` — el "antes" tachado. Solo cuenta como "antes" si es mayor que
      el efectivo.
    - `paymentMethod` — trae `method: "cencosudCard"`: es el precio con Tarjeta
      Cencosud. Mismo tratamiento que el `brandPrice` de Easy y el `cmrPrice` de
      Falabella — se guarda para mostrarlo y **queda fuera del detector**.
      Aparece en ~23 de cada 30 productos.

    Se toma el mínimo entre `offer` y `regular` en vez de confiar en que `offer`
    siempre es el menor: si un día `offer` viniera más caro, publicar ese número
    sería inventar un precio que nadie paga.
    """
    offer = _money(prices.get("offer"))
    regular = _money(prices.get("regular"))

    payment = prices.get("paymentMethod")
    card = _money(payment)
    if card is not None and isinstance(payment, dict):
        method = payment.get("method")
        if method and method != "cencosudCard":
            # Un método nuevo (otro banco, otro convenio) no se asume tarjeta de
            # la casa en silencio: se registra igual, pero queda el rastro.
            logger.info("paris_metodo_pago_desconocido method=%s", method)

    pagables = [p for p in (offer, regular) if p is not None]
    effective = min(pagables) if pagables else None

    claimed_normal = regular if (regular and effective and regular > effective) else None
    return effective, claimed_normal, card


def _claimed_discount(prices: dict[str, Any]) -> str | None:
    """El % que la tienda declara sobre el precio sin tarjeta.

    Se usa `offer.discountOnRegular` —el descuento del precio que paga
    cualquiera—, no el de `paymentMethod`, que es mayor y exige plástico
    Cencosud.
    """
    offer = prices.get("offer")
    if not isinstance(offer, dict):
        return None
    fraction = offer.get("discountOnRegular")
    if not isinstance(fraction, (int, float)) or fraction <= 0:
        return None
    return f"{round(fraction * 100)}%"


def parse_listing(
    payload: dict[str, Any],
    *,
    store_slug: str,
    category: CategoryRef,
    scraped_at: datetime,
) -> tuple[list[RawProduct], int]:
    """Convierte una respuesta de la API en productos. Devuelve (items, total)."""
    if "results" not in payload:
        raise NotAListingPage(
            f"{store_slug}/{category.slug}: respuesta sin `results` "
            f"(claves: {sorted(payload)[:8]})"
        )

    total = int(payload.get("total") or 0)
    products: list[RawProduct] = []

    for item in payload.get("results") or []:
        variant = item.get("masterVariant") or {}
        sku = variant.get("sku")
        slug = _localized(item.get("slug"))
        name = _localized(item.get("name"))
        if not (sku and slug and name):
            continue

        prices = variant.get("prices") or {}
        effective, claimed_normal, card = resolve_prices(prices)
        if effective is None:
            logger.debug("sin_precio store=%s sku=%s", store_slug, sku)
            continue
        if effective > MAX_PLAUSIBLE_CLP:
            logger.debug(
                "precio_centinela store=%s sku=%s valor=%s", store_slug, sku, effective
            )
            continue

        images = variant.get("images") or []
        products.append(
            RawProduct(
                store_slug=store_slug,
                store_sku=str(sku),
                url=f"{SITE_BASE}/{slug}.html",
                name=name,
                price_effective=effective,
                price_normal=claimed_normal,
                price_card=card,
                brand=normalize_brand(item.get("brand")),
                # Paris publica el EAN real en el listado — es el mejor insumo de
                # matching cross-store de las seis tiendas y no cuesta un request
                # extra. Pero SOLO para los primeros ~60 productos del ranking de
                # cada categoría (medido 2026-08-02: página 1 → 38/40 con EAN,
                # página 2 → 19/40, página 5 en adelante → 0/40; con pageSize=100
                # son 62/100, así que el corte es por posición absoluta, no por
                # página). No hay forma de sacar el resto sin abrir cada ficha.
                #
                # No se compensa forzando nada: el upsert guarda el GTIN con
                # COALESCE y el orden "relevance" rota entre pasadas, así que la
                # cobertura se acumula sola con los días. Es exactamente el tipo
                # de dato que justifica haberlo empezado a guardar ya.
                gtin=normalize_gtin(variant.get("ean"), sku),
                category_path=category.slug,
                image_url=images[0].get("url") if images else None,
                claimed_discount=_claimed_discount(prices),
                # La API del listado no expone stock por SKU: `published` es lo
                # más cercano y es un flag de publicación, no de inventario. Se
                # asume disponible; el detector lo re-verifica antes de publicar.
                in_stock=True,
                scraped_at=scraped_at,
                raw_payload=item,
            )
        )

    return products, total


class ParisAdapter:
    """`store_key` = id de grupo de la categoría, p. ej. `tecCelSmartphones`."""

    slug = "paris"
    rate_limit_rps: float = 0.5
    max_pages = 30

    def __init__(self, http: HttpClient, categories: Sequence[CategoryRef]) -> None:
        self._http = http
        self._categories = tuple(categories)

    def categories(self) -> Sequence[CategoryRef]:
        return self._categories

    def _body(self, category: CategoryRef, page: int) -> dict[str, Any]:
        return {
            "filters": [{"key": "group_id", "stringValues": [category.store_key]}],
            "pagination": {"page": page, "pageSize": PAGE_SIZE},
            "sortBy": "relevance",
            "term": "",
        }

    async def discover(self, category: CategoryRef) -> AsyncIterator[RawProduct]:
        seen: set[str] = set()
        page = 1  # la paginación de esta API es 1-indexada

        while page <= self.max_pages:
            raw = await self._http.post_json(
                API_URL, self._body(category, page), rps=self.rate_limit_rps
            )
            scraped_at = datetime.now(timezone.utc)
            products, total = parse_listing(
                json.loads(raw),
                store_slug=self.slug,
                category=category,
                scraped_at=scraped_at,
            )

            # Pasado el final la API devuelve `results: []` con `total: 0` y
            # HTTP 200 — no es un error, es el fin del catálogo.
            if not products:
                if page == 1:
                    raise NotAListingPage(
                        f"{self.slug}/{category.slug}: store_key="
                        f"{category.store_key!r} no devolvió productos"
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
            if total and len(seen) >= total:
                break
            page += 1
