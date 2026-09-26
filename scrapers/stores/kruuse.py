"""Adaptador de Kruuse (importador Scheppach / Optimum / Metallkraft).

Kruuse corre **Medusa** detrás de un Next App Router, y la tienda publica su
catálogo entero en un feed JSON:

    GET /cl/product-feed.json?page=N&limit=100

No es un endpoint que haya que descubrir: su `llms.txt` lo ofrece explícitamente
"for compact catalog discovery... use the feed for discovery or catalog indexing",
y su `robots.txt` tiene un grupo que **permite** a los bots de agente (GPTBot,
ClaudeBot, PerplexityBot, CCBot) sobre `/cl/product-feed.json`, `/cl/products/` y
`/cl/categories/`. Por eso no se toca el payload RSC de las páginas de categoría,
que era el plan original: frágil y sin necesidad.

Lo que el feed trae y casi nadie más da:

- **GTIN-13 en 3.728 de 3.772 productos (99%)**. Con Ferretek (97%), son las dos
  fuentes que sostienen el matching cross-store del sistema entero.
- `availability` de cuatro valores reales, no un `True` inventado.
- Precios CLP **enteros**, sin decimales ni unidades mínimas.

EL FEED ES PLANO, Y ESO DECIDE LA FORMA DEL ADAPTADOR
--------------------------------------------------------------------------------
No acepta filtro por categoría: `?category=Lijadoras` devuelve el catálogo entero
igual (verificado; también `?category_handle=` y `?q=`). Así que el `store_key` es
**el nombre de la categoría tal como lo escribe la tienda** y el filtrado es
nuestro: la pasada baja el feed **una sola vez** —38 requests— y las ~21
categorías conectadas se sirven de esa copia. Sin la caché serían 21 × 38.

Que un `store_key` no matchee ninguna entrada es un error de configuración y se
grita (`CategoryNotInFeed`): los nombres de categoría son texto libre y si la
tienda renombra una, sin este guard la llave dejaría de recolectar en silencio.

LO QUE HAY QUE SABER ANTES DE ESPERAR OFERTAS DE ESTA TIENDA
--------------------------------------------------------------------------------
**3.467 de 3.772 productos están en `backorder`** (236 `in_stock`, 59
`out_of_stock`, 10 `preorder`). Kruuse es un importador de maquinaria que vende a
pedido, no un retailer con stock. Acá `in_stock` es `True` **solo** para
`in_stock`: una oferta de algo que no se puede comprar hoy no es una oferta, y la
guarda de stock del detector va a rechazar casi todo lo de esta tienda.

Eso no la hace inútil: la serie se construye igual y queda lista para el día en
que un SKU entre en stock, y el 99% de GTIN mejora el copy de **todas** las demás
tiendas ("más barato que en Paris"). Pero el volumen de publicación esperado es
bajo, y eso está asumido.
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

FEED_PATH = "/cl/product-feed.json"

#: Tope de `limit`. El feed **clampea honesto**: se le pide 200, sirve 100 y lo
#: dice en su propio campo `limit`. Es el contraste exacto con el
#: `product_list_limit` de Magento, que ante un valor que no ofrece cae al default
#: (12) con HTTP 200 y sin avisar. Igual se verifica lo que devolvió.
PAGE_SIZE = 100

#: 60 × 100 = 6.000, cómodo sobre los 3.772 de hoy. Es cota de cordura: el corte
#: real es `has_more`.
MAX_PAGES = 60

#: El único valor de `availability` que significa "se puede comprar hoy".
IN_STOCK = "in_stock"


class FeedShapeChanged(RuntimeError):
    """La respuesta no tiene la forma del feed (sin `products`, o no es JSON)."""


class CategoryNotInFeed(RuntimeError):
    """Ningún producto del feed declara esta categoría.

    Es un error de configuración, no un dato del catálogo: el `store_key` es el
    nombre que la tienda le puso a la categoría, y si lo renombra la llave deja de
    recolectar. Ruidoso a propósito.
    """


def parse_price(raw: Any) -> Decimal | None:
    """Precio del feed a CLP entero.

    Viene ya entero y en CLP (`249990`), sin la unidad mínima de WooCommerce ni
    los decimales de Magento. Lo único que hace falta es rechazar lo que no es un
    precio: 5 de los 3.772 productos traen `price: null` (son variantes `-ADDON`).
    """
    if isinstance(raw, bool) or not isinstance(raw, int):
        return None
    return Decimal(raw) if raw > 0 else None


def parse_page(payload: Any) -> tuple[list[dict[str, Any]], bool, int | None, int | None]:
    """Una página del feed → `(entradas, has_more, product_count, limit_aplicado)`."""
    if not isinstance(payload, dict) or not isinstance(payload.get("products"), list):
        raise FeedShapeChanged("la respuesta no trae una lista `products`")
    count = payload.get("product_count")
    limit = payload.get("limit")
    return (
        [e for e in payload["products"] if isinstance(e, dict)],
        bool(payload.get("has_more")),
        count if isinstance(count, int) else None,
        limit if isinstance(limit, int) else None,
    )


def to_product(
    entry: dict[str, Any],
    *,
    store_slug: str,
    category: CategoryRef,
    scraped_at: datetime,
) -> RawProduct | None:
    """Una entrada del feed a `RawProduct`, o `None` si no es publicable."""
    sku = clean_text(entry.get("sku"))
    name = clean_text(entry.get("title"))
    url = entry.get("url")
    if not (sku and name and url):
        logger.debug("entrada_incompleta store=%s sku=%r", store_slug, sku)
        return None

    price = parse_price(entry.get("price"))
    if price is None:
        logger.debug("sin_precio store=%s sku=%s", store_slug, sku)
        return None
    if price > MAX_PLAUSIBLE_CLP:
        # Acá el techo descarta dos máquinas industriales de verdad (una
        # plegadora de $115.099.000 y una taladradora radial de $101.999.000),
        # no centinelas. Es una pérdida aceptada de 2 en 3.772: el techo existe
        # para que el placeholder de $99.999.999.999 de Falabella no envenene una
        # baseline de forma permanente, y no se mueve por dos SKUs.
        logger.debug("sobre_el_techo store=%s sku=%s valor=%s", store_slug, sku, price)
        return None

    # `regular_price` es idéntico a `price` en los 3.772 y `sale_price` viene nulo
    # en todos: hoy esta tienda no declara ningún descuento. Se deja la lógica
    # para cuando lo haga, y se guarda solo como evidencia — nunca alimenta el
    # descuento, que se mide contra la baseline propia.
    claimed_normal = parse_price(entry.get("regular_price"))
    if claimed_normal is not None and claimed_normal <= price:
        claimed_normal = None

    return RawProduct(
        store_slug=store_slug,
        store_sku=sku,
        url=url,
        name=name,
        price_effective=price,
        price_normal=claimed_normal,
        # Kruuse no tiene tarjeta de la casa.
        price_card=None,
        brand=normalize_brand(entry.get("brand")),
        # `mpn` NO es un modelo: es igual al `sku` en 3.772 de 3.772, o sea el
        # código interno de la tienda. Usarlo como modelo inventaría pares
        # (marca, modelo) que podrían fusionar productos distintos de dos
        # tiendas, que es exactamente lo que la regla 6 prohíbe. La identidad de
        # esta tienda viene del GTIN, que trae en el 99%.
        model=None,
        gtin=normalize_gtin(entry.get("gtin"), sku),
        category_path=category.slug,
        image_url=entry.get("image"),
        claimed_discount=None,
        in_stock=entry.get("availability") == IN_STOCK,
        scraped_at=scraped_at,
        raw_payload={
            "id": entry.get("id"),
            "availability": entry.get("availability"),
            "category": entry.get("category"),
            "gtin_type": entry.get("gtin_type"),
            "updated_at": entry.get("updated_at"),
        },
    )


class KruuseAdapter:
    """`store_key` = el nombre de la categoría tal como lo escribe la tienda.

    Su `robots.txt` no declara `Crawl-delay`, así que rige el default conservador.
    """

    slug = "kruuse"
    rate_limit_rps = 0.5
    base_url = "https://kruuse.cl"
    page_size = PAGE_SIZE
    max_pages = MAX_PAGES

    def __init__(self, http: HttpClient, categories: Sequence[CategoryRef]) -> None:
        self._http = http
        self._categories = tuple(categories)
        self._entries: list[dict[str, Any]] | None = None
        self._read_at: datetime | None = None
        self._error: Exception | None = None

    def categories(self) -> Sequence[CategoryRef]:
        return self._categories

    def _url(self, page: int) -> str:
        return f"{self.base_url}{FEED_PATH}?page={page}&limit={self.page_size}"

    async def _feed(self) -> tuple[list[dict[str, Any]], datetime]:
        """El catálogo entero, bajado una sola vez por pasada.

        El fallo también se cachea: sin eso, una tienda caída se llevaría 21
        categorías × 38 páginas de reintentos en la misma pasada. Cada categoría
        igual queda `failed` —no recolectó—, pero el feed se intenta una vez.
        """
        if self._error is not None:
            raise self._error
        if self._entries is not None and self._read_at is not None:
            return self._entries, self._read_at

        try:
            entries: list[dict[str, Any]] = []
            declared: int | None = None
            page = 1
            while page <= self.max_pages:
                payload = json.loads(
                    await self._http.get_text(self._url(page), rps=self.rate_limit_rps)
                )
                nuevas, has_more, count, limit = parse_page(payload)
                if page == 1:
                    declared = count
                    if limit is not None and limit != self.page_size:
                        # A diferencia de Magento, este feed dice qué límite
                        # aplicó. Si algún día deja de aceptar 100, se ve acá en
                        # vez de en un catálogo que encogió sin explicación.
                        logger.warning(
                            "limite_no_respetado store=%s pedido=%d aplicado=%d",
                            self.slug,
                            self.page_size,
                            limit,
                        )
                entries += nuevas
                if not has_more:
                    break
                page += 1
        except Exception as exc:
            self._error = exc
            raise

        if declared is not None and len(entries) != declared:
            # No se corta la pasada: lo que se bajó son observaciones válidas. La
            # caída proporcional la ve el canario estadístico de cada categoría.
            logger.warning(
                "feed_incompleto store=%s bajados=%d declarados=%d paginas=%d",
                self.slug,
                len(entries),
                declared,
                page,
            )

        self._entries = entries
        self._read_at = datetime.now(timezone.utc)
        return self._entries, self._read_at

    async def discover(self, category: CategoryRef) -> AsyncIterator[RawProduct]:
        entries, read_at = await self._feed()

        de_la_categoria = [
            e for e in entries if (e.get("category") or "") == category.store_key
        ]
        if not de_la_categoria:
            raise CategoryNotInFeed(
                f"{self.slug}/{category.slug}: ninguna entrada del feed declara "
                f"la categoría {category.store_key!r}"
            )

        seen: set[str] = set()
        for entry in de_la_categoria:
            product = to_product(
                entry,
                store_slug=self.slug,
                category=category,
                scraped_at=read_at,
            )
            if product is None or product.store_sku in seen:
                continue
            seen.add(product.store_sku)
            yield product
