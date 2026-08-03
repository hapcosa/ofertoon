"""Adaptador de PC Factory.

PC Factory es la única tienda del MVP con una **API JSON pública y sin auth**:

    GET https://api.pcfactory.cl/pcfactory-services-catalogo/v1/catalogo/productos
        ?search=*&categorias=<nombre>&page=<N>&size=48

No se parsea HTML. El sitio es una SPA sobre Modyo cuyo listado se arma en el
cliente contra esta misma API — el HTML de una categoría no contiene un solo
producto, así que scrapearlo sería reimplementar la SPA para obtener menos.

Dos particularidades del endpoint:

- `search` es **obligatorio** (sin él responde 422). `*` es el comodín que
  devuelve todo, y el filtro real lo hace `categorias`.
- `categorias` filtra por el **nombre** de la categoría (`Notebooks`), no por su
  id ni por su slug. Pasarle el id devuelve cero resultados en silencio, que es
  la razón por la que cada `store_key` está verificado contra la tienda antes de
  entrar al seed.

El árbol de categorías vive en
`GET https://api.pcfactory.cl/api-dex-catalog/v1/catalog/category/PCF/menu`.
"""
from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator, Sequence
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any
from urllib.parse import quote

from catalog.normalize import clean_text, normalize_brand
from scrapers.base import MAX_PLAUSIBLE_CLP, CategoryRef, RawProduct
from scrapers.http import HttpClient

logger = logging.getLogger(__name__)

API_BASE = "https://api.pcfactory.cl/pcfactory-services-catalogo/v1"
ASSETS_BASE = "https://assets.pcfactory.cl"
SITE_BASE = "https://www.pcfactory.cl"

#: Tope de la API. Pedir más igual devuelve 48.
PAGE_SIZE = 48


class NotAListingPage(RuntimeError):
    """La respuesta no tiene la forma esperada del catálogo."""


def _clp(value: Any) -> Decimal | None:
    if value is None:
        return None
    try:
        price = Decimal(str(value))
    except (ArithmeticError, ValueError):
        return None
    return price if price > 0 else None


def resolve_prices(
    precio: dict[str, Any],
) -> tuple[Decimal | None, Decimal | None, Decimal | None]:
    """Reparte el bloque `precio` en (efectivo, normal declarado, tarjeta).

    PC Factory cotiza cuatro números y los rótulos salen del propio JS del sitio
    (`priceClasses` en el bundle de la home):

    - `efectivo` → clase `rr-item__price` / `main-price`. Es **el precio que la
      tienda muestra en grande**: pagando débito, efectivo o transferencia. Lo
      paga cualquiera, así que es el efectivo del sistema.
    - `normal` → clase `rr-item__special-price`. Es el precio con tarjeta de
      crédito, y es **más caro** que `efectivo` (505.190 vs 489.990 en el
      ejemplo). OJO: pese al nombre, **no** es el "antes" tachado — confundirlo
      con el `normalPrice` de Falabella o Easy invertiría el descuento.
    - `referencia` → clase `rr-item__old-price` ("anterior"). *Ese* es el "antes"
      tachado que declara la tienda, y el que se guarda como evidencia.
    - `bancoEstado` → "Oferta BancoEstado". Requiere plástico de un banco
      concreto, así que es precio-tarjeta y queda fuera del detector. Viene en 0
      cuando no aplica, que es el caso en 212 de 212 productos muestreados.
    """
    efectivo = _clp(precio.get("efectivo"))
    credito = _clp(precio.get("normal"))
    referencia = _clp(precio.get("referencia"))
    card = _clp(precio.get("bancoEstado"))

    # Mínimo de lo pagable sin plástico de la tienda; `normal` (crédito) solo
    # entra si por alguna razón no vino el efectivo.
    pagables = [p for p in (efectivo, credito) if p is not None]
    effective = min(pagables) if pagables else None

    # Un "antes" que no es mayor que el precio de hoy no es un antes.
    claimed_normal = (
        referencia if (referencia and effective and referencia > effective) else None
    )
    return effective, claimed_normal, card


def parse_listing(
    payload: dict[str, Any],
    *,
    store_slug: str,
    category: CategoryRef,
    scraped_at: datetime,
) -> tuple[list[RawProduct], int, int]:
    """Convierte una página de la API en productos. Devuelve (items, pág, total pág)."""
    content = payload.get("content")
    if not isinstance(content, dict) or "items" not in content:
        raise NotAListingPage(
            f"{store_slug}/{category.slug}: respuesta sin `content.items` "
            f"(claves: {sorted(payload)[:8]})"
        )

    pageable = content.get("pageable") or {}
    page_number = int(pageable.get("pageNumber") or 0)
    total_pages = int(pageable.get("totalPages") or 0)

    products: list[RawProduct] = []
    for item in content.get("items") or []:
        sku = item.get("id")
        slug = item.get("slug")
        name = clean_text(item.get("nombre"))
        if not (sku and slug and name):
            continue

        effective, claimed_normal, card = resolve_prices(item.get("precio") or {})
        if effective is None:
            logger.debug("sin_precio store=%s sku=%s", store_slug, sku)
            continue
        if effective > MAX_PLAUSIBLE_CLP:
            logger.debug(
                "precio_centinela store=%s sku=%s valor=%s", store_slug, sku, effective
            )
            continue

        thumbnail = item.get("thumbnail")
        products.append(
            RawProduct(
                store_slug=store_slug,
                store_sku=str(sku),
                url=f"{SITE_BASE}/producto/{slug}",
                name=name,
                price_effective=effective,
                price_normal=claimed_normal,
                price_card=card,
                brand=normalize_brand(item.get("marca")),
                category_path=category.slug,
                image_url=f"{ASSETS_BASE}{thumbnail}" if thumbnail else None,
                # La API del listado no publica el % de descuento (sí lo hace el
                # detalle, vía `precio.descuento`). No se calcula acá: este campo
                # es lo que la tienda DECLARA, no lo que nosotros derivamos.
                claimed_discount=None,
                in_stock=_in_stock(item.get("stock")),
                scraped_at=scraped_at,
                raw_payload=item,
            )
        )

    return products, page_number, total_pages


def _in_stock(stock: Any) -> bool:
    """`stock` llega como "+100", "+50" o un entero en texto ("1", "27").

    El "+" es un techo de visualización (la tienda no revela cuántas unidades
    tiene arriba de 30), así que se lo saca y se lee el número. La API solo
    lista productos comprables — en 212 muestreados no apareció un solo 0 —
    pero se interpreta el campo igual en vez de asumir True.

    Un formato desconocido se trata como **con stock**: el campo es informativo
    y descartar el producto por no entender su stock perdería una oferta real.
    """
    if stock is None:
        return False
    text = str(stock).strip().lstrip("+")
    if not text:
        return False
    if text.isdigit():
        return int(text) > 0
    logger.debug("stock_no_numerico store=pcfactory valor=%r", stock)
    return True


class PcFactoryAdapter:
    """`store_key` = **nombre** de la categoría, p. ej. `Notebooks`.

    No es el id ni el slug: el parámetro `categorias` de la API filtra por
    nombre. Un id devuelve cero resultados sin error, así que cada llave se
    verifica contra la tienda antes de entrar al seed.
    """

    slug = "pcfactory"
    rate_limit_rps: float = 0.5
    max_pages = 25

    def __init__(self, http: HttpClient, categories: Sequence[CategoryRef]) -> None:
        self._http = http
        self._categories = tuple(categories)

    def categories(self) -> Sequence[CategoryRef]:
        return self._categories

    def _page_url(self, category: CategoryRef, page: int) -> str:
        return (
            f"{API_BASE}/catalogo/productos?search=*"
            f"&categorias={quote(category.store_key)}"
            f"&page={page}&size={PAGE_SIZE}"
        )

    async def discover(self, category: CategoryRef) -> AsyncIterator[RawProduct]:
        seen: set[str] = set()
        page = 0  # la paginación de la API es 0-indexada (Spring pageable)

        while page < self.max_pages:
            raw = await self._http.get_text(
                self._page_url(category, page), rps=self.rate_limit_rps
            )
            scraped_at = datetime.now(timezone.utc)
            products, served_page, total_pages = parse_listing(
                json.loads(raw),
                store_slug=self.slug,
                category=category,
                scraped_at=scraped_at,
            )

            if not products:
                break

            # Guarda de paginación honesta: si la API sirve una página distinta de
            # la pedida está ignorando el parámetro, y seguir sería releer lo
            # mismo. Se emite lo recibido y se corta.
            if served_page != page:
                logger.warning(
                    "paginacion_ignorada store=%s categoria=%s pedida=%d servida=%d",
                    self.slug,
                    category.slug,
                    page,
                    served_page,
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

            if fresh == 0:
                break
            page += 1
            if total_pages and page >= total_pages:
                break
