"""Adaptador de Ferretek.

Ferretek corre Magento 2 con la **REST de catálogo abierta sin token**, que es
raro: Construmart, Kupfer, Sparta y Andesgear corren el mismo Magento y todas
responden `consumer isn't authorized`. Acá:

    GET /rest/V1/products?searchCriteria[filter_groups][0][filters][0][field]=category_id
                         &searchCriteria[filter_groups][0][filters][0][value]={id}
                         &searchCriteria[pageSize]=100
                         &searchCriteria[currentPage]={n}

El `store_key` es el **id numérico de la categoría** del árbol que publica
`/rest/V1/categories`.

Por eso no comparte código con una futura `magento_html.py`: el resto de la
familia Magento hay que rasparla del grid HTML, y este payload no se parece en
nada a eso.

**Requiere User-Agent de navegador.** El Varnish que tiene adelante responde
`403 Empty UA blocked` a cualquier cosa que no parezca un navegador —incluido el
UA identificable que el sistema usa por defecto—, y también al `robots.txt`.
Mismo caso que el UA-sniffing de Easy.

Tres cosas que el payload de Magento hace distinto a las demás tiendas:

1. **`status` es publicación, no stock.** Un producto con `status = 2`
   (Disabled) devuelve **HTTP 404 en su ficha**: no existe para el cliente.
   Verificado el 2026-09-23 sobre `lijadora-orbital-gss-23-ae-190w-37`. Son el
   55% de la categoría 738, y registrarles un precio sería inventar la serie de
   un producto que no se vende.
2. **El precio de venta está en `special_price`, con vigencia.** `price` es el
   número tachado. Verificado contra la ficha real: el esmeril `06013961E0`
   sirve `data-price-amount="103000"` (su `special_price`) y
   `data-price-amount="123220"` (su `price`).
3. **`marca` es el id de una opción**, no un texto: `165` es `BOSCH`. Se
   resuelve contra `/rest/V1/products/attributes/marca`, una vez por corrida.

El regalo de esta tienda es el **GTIN**: viene en el 100% de los productos
muestreados, con largos de 12 y 13. El sistema entero tiene identidad para ~875
de sus ~11.000 listings, así que es la mejor fuente de matching cross-store que
se ha conectado.
"""
from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator, Sequence
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.parse import quote

from catalog.normalize import clean_text, normalize_brand, normalize_gtin
from scrapers.base import MAX_PLAUSIBLE_CLP, CategoryRef, RawProduct
from scrapers.http import BROWSER_USER_AGENT, HttpClient

logger = logging.getLogger(__name__)

SITE_BASE = "https://ferretek.cl"
API_BASE = f"{SITE_BASE}/rest/V1"

#: Magento acepta más, pero 100 mantiene la respuesta en un tamaño manejable:
#: cada item trae ~35 `custom_attributes`.
PAGE_SIZE = 100

#: `status` en Magento: 1 = Enabled, 2 = Disabled. Ver la nota 1 del módulo.
STATUS_ENABLED = 1


class NotAListingPage(RuntimeError):
    """La categoría no existe en la tienda.

    Magento devuelve **HTTP 200 con `items: []`** tanto para un `category_id`
    inexistente como para una página pasada del final, pero acá sí se pueden
    distinguir sin mirar el número de página: `total_count` vale 0 en el primer
    caso y el total real en el segundo.
    """


def _custom(entry: dict[str, Any]) -> dict[str, Any]:
    return {
        a["attribute_code"]: a.get("value")
        for a in entry.get("custom_attributes") or []
        if isinstance(a, dict) and a.get("attribute_code")
    }


def parse_price(raw: Any) -> Decimal | None:
    """Precio de Magento a CLP entero.

    Magento serializa los precios como decimales (`'103000.000000'`) aunque la
    moneda no tenga decimales. Un valor con parte fraccionaria no nula es un
    error de carga de la tienda, no un precio chileno: se descarta en vez de
    redondearse, porque redondear publicaría un número que la ficha no muestra.
    """
    if raw is None:
        return None
    try:
        value = Decimal(str(raw).strip())
    except (InvalidOperation, ValueError):
        return None
    if value != value.to_integral_value():
        logger.warning("ferretek_precio_no_entero valor=%r", str(raw)[:32])
        return None
    value = value.to_integral_value()
    return value if value > 0 else None


def _parse_magento_date(raw: Any) -> date | None:
    """`'2024-12-26 00:00:00'` → date. None si falta o no se entiende."""
    if not raw:
        return None
    try:
        return datetime.strptime(str(raw)[:10], "%Y-%m-%d").date()
    except ValueError:
        logger.debug("ferretek_fecha_ilegible valor=%r", str(raw)[:32])
        return None


def resolve_prices(
    attributes: dict[str, Any], base_price: Any, *, today: date
) -> tuple[Decimal | None, Decimal | None]:
    """Reparte en `(efectivo, normal declarado)`.

    El `special_price` de Magento tiene ventana de vigencia
    (`special_from_date` / `special_to_date`) y **fuera de ella la tienda cobra
    el `price`**. Ignorar las fechas publicaría un precio que el cliente no
    recibe — en las dos direcciones: un special que todavía no arrancó, o uno
    que ya venció y quedó en el atributo.

    Cuando el special aplica, `price` pasa a `price_normal`: es exactamente el
    número tachado de la ficha, y como todo `price_normal` se guarda solo como
    evidencia.
    """
    price = parse_price(base_price)
    special = parse_price(attributes.get("special_price"))
    if price is None:
        # Sin precio base no hay nada que publicar, aunque haya special: el
        # special es un descuento *sobre* algo.
        return None, None
    if special is None or special >= price:
        return price, None

    desde = _parse_magento_date(attributes.get("special_from_date"))
    hasta = _parse_magento_date(attributes.get("special_to_date"))
    if (desde and today < desde) or (hasta and today > hasta):
        return price, None

    return special, price


def parse_listing(
    payload: dict[str, Any],
    *,
    store_slug: str,
    category: CategoryRef,
    scraped_at: datetime,
    brands: dict[str, str] | None = None,
) -> tuple[list[RawProduct], int, int]:
    """Convierte una página de la REST en productos.

    Devuelve `(items, enumerados, declarados)`. `enumerados` cuenta las entradas
    que la paginación trajo —no las emitidas—, que es lo que el chequeo de
    completitud del runner necesita.
    """
    items = payload.get("items")
    if not isinstance(items, list):
        raise NotAListingPage(
            f"{store_slug}/{category.slug}: la respuesta no trae la lista `items`"
        )
    declared = payload.get("total_count")
    declared = int(declared) if isinstance(declared, int) else 0
    brands = brands or {}
    today = scraped_at.date()

    products: list[RawProduct] = []
    for entry in items:
        if not isinstance(entry, dict):
            continue
        sku = clean_text(entry.get("sku"))
        name = clean_text(entry.get("name"))
        if not (sku and name):
            continue

        if entry.get("status") != STATUS_ENABLED:
            # No es "sin stock": la ficha devuelve 404. Ver la nota 1 del módulo.
            logger.debug("no_publicado store=%s sku=%s", store_slug, sku)
            continue

        attributes = _custom(entry)
        effective, claimed_normal = resolve_prices(
            attributes, entry.get("price"), today=today
        )
        if effective is None:
            logger.debug("sin_precio store=%s sku=%s", store_slug, sku)
            continue
        if effective > MAX_PLAUSIBLE_CLP:
            logger.debug(
                "precio_centinela store=%s sku=%s valor=%s", store_slug, sku, effective
            )
            continue

        url_key = clean_text(attributes.get("url_key"))
        if not url_key:
            continue

        image = clean_text(attributes.get("image"))
        products.append(
            RawProduct(
                store_slug=store_slug,
                store_sku=sku,
                # Magento sirve las fichas con sufijo `.html`; sin él responde
                # 404 (verificado).
                url=f"{SITE_BASE}/{url_key}.html",
                name=name,
                price_effective=effective,
                price_normal=claimed_normal,
                # Ferretek no tiene tarjeta de la casa.
                price_card=None,
                brand=normalize_brand(brands.get(str(attributes.get("marca")))),
                model=None,
                gtin=normalize_gtin(attributes.get("GTIN"), sku),
                category_path=category.slug,
                image_url=f"{SITE_BASE}/media/catalog/product{image}" if image else None,
                claimed_discount=None,
                # El payload no trae stock: `extension_attributes` viene solo con
                # `website_ids` y `category_links`. Misma ceguera que Paris y
                # Falabella, y se arregla igual — abriendo la ficha del candidato.
                in_stock=True,
                scraped_at=scraped_at,
                raw_payload=entry,
            )
        )

    return products, len(items), declared


class FerretekAdapter:
    """`store_key` = id numérico de categoría, p. ej. `738`."""

    slug = "ferretek"
    #: `robots.txt` no declara `Crawl-delay` (de hecho responde 403 sin UA de
    #: navegador). Default conservador del sistema.
    rate_limit_rps: float = 0.5
    #: 100 × 40 = 4.000 por categoría, más que la más grande de las conectadas
    #: (`herramientas-manuales`, 1.209) y un techo si la tienda deja de respetar
    #: `currentPage`.
    max_pages: int = 40

    def __init__(self, http: HttpClient, categories: Sequence[CategoryRef]) -> None:
        self._http = http
        self._categories = tuple(categories)
        self._completeness: dict[str, tuple[int, int]] = {}
        #: id de opción → etiqueta. Se resuelve una vez por corrida.
        self._brands: dict[str, str] | None = None

    def categories(self) -> Sequence[CategoryRef]:
        return self._categories

    def completeness(self, category: CategoryRef) -> tuple[int, int] | None:
        return self._completeness.get(category.store_key)

    @property
    def _headers(self) -> dict[str, str]:
        return {"User-Agent": BROWSER_USER_AGENT, "Accept": "application/json"}

    def _page_url(self, category: CategoryRef, page: int) -> str:
        filtro = "searchCriteria[filter_groups][0][filters][0]"
        return (
            f"{API_BASE}/products"
            f"?{quote(filtro + '[field]')}=category_id"
            f"&{quote(filtro + '[value]')}={quote(str(category.store_key))}"
            f"&{quote(filtro + '[condition_type]')}=eq"
            f"&{quote('searchCriteria[pageSize]')}={PAGE_SIZE}"
            f"&{quote('searchCriteria[currentPage]')}={page}"
        )

    async def _brand_labels(self) -> dict[str, str]:
        """Mapa id → etiqueta del atributo `marca`, cacheado por corrida.

        Un fallo acá no puede tumbar la corrida: sin marca el producto se
        publica igual, solo pierde una línea del copy.
        """
        if self._brands is not None:
            return self._brands
        self._brands = {}
        try:
            raw = await self._http.get_text(
                f"{API_BASE}/products/attributes/marca",
                rps=self.rate_limit_rps,
                headers=self._headers,
            )
            for option in json.loads(raw).get("options") or []:
                value = str((option or {}).get("value") or "").strip()
                label = clean_text((option or {}).get("label"))
                if value and label:
                    self._brands[value] = label
        except Exception:
            logger.warning("ferretek_marcas_no_resueltas", exc_info=True)
        return self._brands

    async def discover(self, category: CategoryRef) -> AsyncIterator[RawProduct]:
        brands = await self._brand_labels()
        seen: set[str] = set()
        enumerated = 0
        declared: int | None = None
        page = 1
        self._completeness.pop(category.store_key, None)

        while page <= self.max_pages:
            raw = await self._http.get_text(
                self._page_url(category, page),
                rps=self.rate_limit_rps,
                headers=self._headers,
            )
            scraped_at = datetime.now(timezone.utc)
            products, page_count, page_declared = parse_listing(
                json.loads(raw),
                store_slug=self.slug,
                category=category,
                scraped_at=scraped_at,
                brands=brands,
            )

            if declared is None:
                # Se toma de la primera página y no se vuelve a mirar: si el
                # catálogo se mueve mientras paginamos, la referencia tiene que
                # ser la del arranque o el chequeo se persigue la cola.
                declared = page_declared
                if declared == 0:
                    raise NotAListingPage(
                        f"{self.slug}/{category.slug}: store_key="
                        f"{category.store_key!r} no existe en la tienda"
                    )
            enumerated += page_count
            self._completeness[category.store_key] = (enumerated, declared)

            if not page_count:
                logger.debug(
                    "fin_de_catalogo store=%s categoria=%s pagina=%d",
                    self.slug,
                    category.slug,
                    page,
                )
                break

            for product in products:
                if product.store_sku in seen:
                    continue
                seen.add(product.store_sku)
                yield product

            if enumerated >= declared:
                break
            page += 1
