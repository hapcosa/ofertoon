"""Familia Magento 2 sobre el grid HTML, para las tiendas con la REST cerrada.

Ferretek es la excepción del rubro: su `/rest/V1/products` contesta sin token.
Kupfer, Construmart, Sparta y Andesgear corren el mismo Magento y responden
`consumer isn't authorized`, así que lo único público es el listado renderizado
server-side. Ahí sí está todo lo que el detector necesita: `data-price-amount` en
el bloque de precio y el SKU propio de la tienda en el grid.

LO QUE HACE DISTINTA A ESTA FAMILIA: NO PAGINA
--------------------------------------------------------------------------------
El `robots.txt` de Kupfer prohíbe `/*?p=`, que es exactamente el parámetro de
paginación de Magento (leído el 2026-09-24). `product_list_limit` —el tamaño de
página— no está prohibido, así que una categoría se enumera en **una sola
request** pidiendo la página más grande que la tienda ofrece, y lo que no entra
NO se va a buscar. Es más barato para la tienda que paginar (una request en vez
de cuatro) y respeta la letra y la intención de su robots.

Eso convierte "la categoría no entra en una página" en una condición que hay que
**reportar**, no resolver: `completeness()` compara lo enumerado contra el total
que la tienda declara en `span.toolbar-number` y el runner marca la corrida
`partial` con "36 de 118". Sin ese chequeo, conectar una categoría que crece
pasando de 36 productos se vería igual que una categoría sana: 36 items todas las
pasadas, canario estadístico contento, y 82 productos que nunca existieron para
el sistema.

LA TRAMPA DEL `product_list_limit`
--------------------------------------------------------------------------------
Solo valen los valores que el limiter ofrece (12, 24 y 36 en Kupfer). Con
`product_list_limit=96` la tienda responde **HTTP 200 y sirve 12 productos** —el
default— sin un solo error: no clampea al máximo, ignora el parámetro. Verificado
en vivo sobre una categoría de 118. O sea que subir `PAGE_SIZE` a ojo no amplía
el alcance, lo reduce a un cuarto en silencio.
"""
from __future__ import annotations

import logging
import re
from collections.abc import AsyncIterator, Sequence
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any

from selectolax.parser import HTMLParser

from catalog.normalize import clean_text, normalize_brand
from scrapers.base import MAX_PLAUSIBLE_CLP, CategoryRef, RawProduct
from scrapers.http import HttpClient

logger = logging.getLogger(__name__)

#: Tamaño de página. Tiene que ser uno de los valores del `<select id="limiter">`
#: de la tienda: cualquier otro cae al default de 12 sin avisar (ver el docstring
#: del módulo). 36 es el máximo que ofrece Kupfer.
PAGE_SIZE = 36

#: Contenedor del grid. Es la ancla de todo el parseo: los temas de Magento
#: repiten `product-item` en los carruseles de "relacionados" y "más vendidos",
#: así que buscar esa clase en la página entera mete productos que no son de la
#: categoría. En Construmart el grid trae 20 y la página 26.
_GRID = "ol.products.list.items.product-items"
_ITEM = "li.item.product.product-item"

#: "No podemos encontrar productos que coincida con la selección." Magento la
#: emite cuando la categoría existe y está vacía, y en ese caso NO hay grid.
_EMPTY_MESSAGE = "div.message.info.empty"

_SKU_PREFIX = re.compile(r"^\s*SKU\s*:\s*", re.I)


class NotAListingPage(RuntimeError):
    """La respuesta no es un listado de categoría.

    Se distingue de una categoría vacía a propósito: vacía trae el mensaje de
    Magento y ninguna fila; esto es una llave que no apunta a un listado (un
    landing de CMS, una redirección a la home, una plantilla cambiada). Lo
    primero es un dato del catálogo y lo tiene que reportar el canario; lo
    segundo es un error de configuración y tiene que ser ruidoso.
    """


def parse_price(raw: Any) -> Decimal | None:
    """`data-price-amount` a CLP entero.

    Magento publica el monto con decimales (`"4442.270001"`, que es el neto por
    1,19 más la basura del float de PHP) y renderiza `$4.442`, o sea el mismo
    número redondeado. Se redondea igual acá, con `Decimal` y nunca con `float`:
    el entero que sale es el precio que la tienda muestra, y los tests lo
    verifican contra el texto del `<span class="price">` del fixture.
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
    value = value.quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return value if value > 0 else None


def _text(node: Any, selector: str) -> str | None:
    found = node.css_first(selector)
    return clean_text(found.text(strip=True)) if found is not None else None


def _price_of(item: Any, price_type: str) -> Decimal | None:
    node = item.css_first(f'[data-price-type="{price_type}"]')
    if node is None:
        return None
    return parse_price(node.attributes.get("data-price-amount"))


def _sku_of(item: Any) -> str | None:
    """SKU propio de la tienda, el mismo que imprime la boleta.

    No se usa el `id` interno de `product-item-info_16211`: el SKU es el código
    de artículo de la empresa y sobrevive a una reindexación del catálogo.
    """
    shown = _text(item, "span.product-item-sku")
    if shown:
        sku = clean_text(_SKU_PREFIX.sub("", shown))
        if sku:
            return sku
    form = item.css_first("form[data-product-sku]")
    return clean_text(form.attributes.get("data-product-sku")) if form else None


def _in_stock(item: Any) -> bool:
    """Stock según la etiqueta que el grid pone al lado del precio.

    Los 72 productos auditados el 2026-09-24 en tres categorías traían la misma
    ("Disponible para compra online") y ninguno vino sin precio, así que **el
    caso negativo no está observado**: lo más probable es que Kupfer no liste lo
    agotado (como Urban) o que le saque el precio, y sin precio lo descartamos
    antes de llegar acá.

    Si la tienda cambiara el texto de la etiqueta, esto daría `False` para todo y
    el detector dejaría de publicar esta tienda por `out_of_stock` — la serie se
    sigue guardando igual. Es el lado seguro del error: preferimos callarnos a
    publicar una oferta de algo que no se puede comprar.
    """
    label = _text(item, "span.price-label")
    if label is None:
        return True
    return "disponible" in label.casefold()


def declared_total(tree: Any) -> int | None:
    """Cuántos productos declara la categoría, de `span.toolbar-number`.

    El texto cambia de plantilla en plantilla ("24" en una, "118 productos" en
    otra), así que se toma el primer entero y no el nodo completo.
    """
    node = tree.css_first("span.toolbar-number")
    if node is None:
        return None
    match = re.search(r"\d+", node.text(strip=True).replace(".", ""))
    return int(match.group()) if match else None


def parse_listing(
    html: str,
    *,
    store_slug: str,
    category: CategoryRef,
    scraped_at: datetime,
) -> tuple[list[RawProduct], int, int | None]:
    """Convierte el grid en productos.

    Devuelve `(productos, enumerados, declarados)`. `enumerados` son las filas
    del grid y no los productos emitidos: un item que se descarta por no traer
    precio es una decisión nuestra, no una página que se perdió, y mezclarlos
    volvería heurística la guarda exacta de `completeness()`.
    """
    tree = HTMLParser(html)
    grid = tree.css_first(_GRID)
    if grid is None:
        if tree.css_first(_EMPTY_MESSAGE) is not None:
            logger.warning(
                "categoria_vacia store=%s categoria=%s llave=%s",
                store_slug,
                category.slug,
                category.store_key,
            )
            return [], 0, declared_total(tree)
        raise NotAListingPage(
            f"{store_slug}/{category.slug}: store_key={category.store_key!r} "
            "no devolvió un grid de categoría"
        )

    items = grid.css(_ITEM)
    products: list[RawProduct] = []
    for item in items:
        link = item.css_first("a.product-item-link")
        sku = _sku_of(item)
        name = clean_text(link.text(strip=True)) if link is not None else None
        url = link.attributes.get("href") if link is not None else None
        if not (sku and name and url):
            logger.debug("item_incompleto store=%s sku=%r", store_slug, sku)
            continue

        price = _price_of(item, "finalPrice")
        if price is None:
            # Sin precio no hay observación. Es lo que pasa con un agotado en las
            # tiendas que igual lo listan: la serie queda con un hueco en vez de
            # con un precio inventado.
            logger.debug("sin_precio store=%s sku=%s", store_slug, sku)
            continue
        if price > MAX_PLAUSIBLE_CLP:
            logger.debug("precio_centinela store=%s sku=%s valor=%s", store_slug, sku, price)
            continue

        # El "antes" tachado aparece solo cuando hay `special_price` cargado. No
        # se observó ninguno en el catálogo auditado; se guarda como evidencia
        # para medir cuánto miente la tienda, nunca para calcular el descuento.
        claimed_normal = _price_of(item, "oldPrice")
        if claimed_normal is not None and claimed_normal <= price:
            claimed_normal = None

        image = item.css_first("img.product-image-photo")
        products.append(
            RawProduct(
                store_slug=store_slug,
                store_sku=sku,
                url=url,
                name=name,
                price_effective=price,
                price_normal=claimed_normal,
                # Magento no modela la tarjeta de la casa; estas tiendas tampoco
                # tienen una.
                price_card=None,
                brand=normalize_brand(_text(item, "span.product-item-brand")),
                model=None,
                gtin=None,
                category_path=category.slug,
                image_url=image.attributes.get("src") if image is not None else None,
                claimed_discount=None,
                in_stock=_in_stock(item),
                scraped_at=scraped_at,
                raw_payload={"sku": sku, "grid_html_len": len(item.html or "")},
            )
        )

    return products, len(items), declared_total(tree)


class _MagentoHtmlAdapter:
    """Base compartida. Las subclases solo fijan slug y host."""

    slug: str = ""
    rate_limit_rps: float = 0.5
    base_url: str = ""
    page_size: int = PAGE_SIZE

    def __init__(self, http: HttpClient, categories: Sequence[CategoryRef]) -> None:
        self._http = http
        self._categories = tuple(categories)
        self._completeness: dict[str, tuple[int, int]] = {}

    def categories(self) -> Sequence[CategoryRef]:
        return self._categories

    def completeness(self, category: CategoryRef) -> tuple[int, int] | None:
        return self._completeness.get(category.store_key)

    def _url(self, category: CategoryRef) -> str:
        return (
            f"{self.base_url}/{category.store_key.lstrip('/')}"
            f"?product_list_limit={self.page_size}"
        )

    async def discover(self, category: CategoryRef) -> AsyncIterator[RawProduct]:
        self._completeness.pop(category.store_key, None)
        html = await self._http.get_text(self._url(category), rps=self.rate_limit_rps)
        scraped_at = datetime.now(timezone.utc)
        products, enumerated, declared = parse_listing(
            html,
            store_slug=self.slug,
            category=category,
            scraped_at=scraped_at,
        )
        if declared is not None:
            self._completeness[category.store_key] = (enumerated, declared)

        seen: set[str] = set()
        for product in products:
            if product.store_sku in seen:
                continue
            seen.add(product.store_sku)
            yield product


class KupferAdapter(_MagentoHtmlAdapter):
    """Kupfer. `store_key` = el path de la categoría, con `.html`.

    Su `robots.txt` no declara `Crawl-delay`, así que rige el default conservador
    de la familia. Lo que sí declara es `Disallow: /*?p=`, que es por lo que esta
    familia no pagina.

    **El catálogo que mapea a nuestra taxonomía es chico**: Kupfer es industrial
    (amarre, cadenas, mantención) y su rama de herramientas eléctricas tiene 24
    productos. No es una tienda que vaya a mover el volumen del canal; entra
    porque cuesta una request por pasada y porque es el primer caso de esta
    familia, que Sparta y Andesgear reusan después sin escribir código.
    """

    slug = "kupfer"
    base_url = "https://kupfer.cl"
