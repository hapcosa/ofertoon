"""Familia Magento 2 sobre el grid HTML, para las tiendas con la REST cerrada.

Ferretek es la excepción del rubro: su `/rest/V1/products` contesta sin token.
Kupfer, Construmart, Sparta y Andesgear corren el mismo Magento y responden
`consumer isn't authorized`, así que lo único público es el listado renderizado
server-side. Ahí sí está todo lo que el detector necesita: `data-price-amount` en
el bloque de precio y el SKU propio de la tienda en el grid.

SI PAGINA O NO LO DECIDE EL `robots.txt` DE CADA TIENDA
--------------------------------------------------------------------------------
`?p=` es el parámetro de paginación de Magento, y las dos tiendas de esta familia
opinan distinto sobre él (leídos el 2026-09-24):

- **Kupfer lo prohíbe** (`Disallow: /*?p=`). Ahí una categoría se enumera en **una
  sola request** pidiendo la página más grande que el limiter ofrece, y lo que no
  entra NO se va a buscar. Es más barato para la tienda que paginar y respeta la
  letra y la intención de su robots.
- **Construmart no lo prohíbe** (prohíbe `?limit=`, `?mode=`, `?dir=` y
  `?order=`). Ahí se pagina normalmente, con el tamaño de página por defecto para
  no tocar ningún parámetro discutible.

De ahí los atributos `paginates` y `page_size` por tienda. Con `paginates=False`,
"la categoría no entra en una página" es una condición que hay que **reportar**,
no resolver: `completeness()` compara lo enumerado contra el total que la tienda
declara en `span.toolbar-number` y el runner marca `partial` con "36 de 118". Sin
ese chequeo, una categoría que crece pasando de 36 productos se vería igual que
una sana —36 items estables en cada pasada, canario estadístico contento— y 82
productos no existirían para el sistema.

Cuando sí se pagina, el corte NO es probar la página siguiente hasta que falle:
Magento publica cuántas páginas tiene (`#am-page-count` de Amasty en Construmart),
así que se piden exactamente esas y nunca se golpea una URL pasada del final.

LA TRAMPA DEL `product_list_limit`
--------------------------------------------------------------------------------
Solo valen los valores que el limiter de ESA tienda ofrece: 12/24/36 en Kupfer,
4/5/10/20 en Construmart. Con `product_list_limit=96` Kupfer responde **HTTP 200 y
sirve 12 productos** —su default— sin un solo error: no clampea al máximo, ignora
el parámetro. Verificado en vivo sobre una categoría de 118. O sea que subir
`page_size` a ojo no amplía el alcance, lo reduce a un cuarto en silencio. Por eso
Construmart usa `page_size = None`: su default (20) ya es su máximo y así la URL
no lleva el parámetro.

LOS PRECIOS DE CONSTRUMART VIVEN DETRÁS DE UNA COOKIE
--------------------------------------------------------------------------------
Construmart cotiza **por sucursal**: cada una es un `customer_group_id` de Magento
(el módulo se llama `Construmart_CatalogPriceByGroup`). Para un visitante sin
sucursal elegida el listado no trae un solo precio y todas las filas salen "Sin
Stock" — no es un bloqueo, es el sitio funcionando como está diseñado ("Para ver
los precios y stock, selecciona la región y tienda", dice su propio popup).

Lo único que su front hace antes de recargar es escribir la cookie
`persistent_customer_group_id`, así que el adaptador manda esa misma cookie y ve
lo que ve cualquiera que haya elegido esa sucursal. La consecuencia que hay que
tener presente al leer la serie: **el precio de un SKU es el de ESA sucursal**. La
señal queda consistente porque baseline y precio de hoy salen del mismo grupo, que
es lo que pide la regla 1, pero la oferta vale ahí.
"""
from __future__ import annotations

import logging
import re
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass, field
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

#: Marca del producto en el grid. El nombre de la clase lo elige el tema, no
#: Magento: Kupfer usa `product-item-brand` y Construmart `atributte-brand` (con
#: el typo incluido). De ahí que sea un atributo por tienda.
BRAND_SELECTOR = "span.product-item-brand"

#: Cuántas páginas declara el paginador. Es de Amasty, no de Magento, pero las
#: dos tiendas de la familia lo traen. Sirve para NO probar una página pasada del
#: final: se piden exactamente las que la tienda dice tener.
_PAGE_COUNT = "#am-page-count"


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
    """Stock según lo que el grid marca, con los dos marcadores de la familia.

    Construmart pone `<div class="stock unavailable">Sin Stock</div>`; Kupfer una
    etiqueta "Disponible para compra online" al lado del precio. Se miran los dos
    porque son marcadores de tema y no cuesta nada, así que no hacen falta hooks
    por tienda.

    **El caso negativo casi no se puede observar**: en las dos tiendas, el
    producto sin stock viene además sin precio, y sin precio lo descartamos antes
    de llegar acá (20 de 20 en Construmart sin cookie, 4 de 4 con cookie; 0 de 72
    en Kupfer). O sea que esta guarda es el cinturón y el descarte por precio es
    el tirante.

    Si una tienda cambiara el texto de su etiqueta, esto daría `False` para todo y
    el detector dejaría de publicarla por `out_of_stock` — la serie se sigue
    guardando igual. Es el lado seguro del error: preferimos callarnos a publicar
    una oferta de algo que no se puede comprar.
    """
    if item.css_first("div.stock.unavailable") is not None:
        return False
    label = _text(item, "span.price-label")
    if label is None:
        return True
    return "disponible" in label.casefold()


def total_pages(tree: Any) -> int | None:
    """Páginas que declara el paginador, o `None` si no lo declara."""
    node = tree.css_first(_PAGE_COUNT)
    if node is None:
        return None
    text = node.text(strip=True)
    return int(text) if text.isdigit() else None


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


@dataclass(frozen=True)
class ParsedPage:
    """Una página del grid, ya convertida.

    `enumerated` son las **filas del grid** y no los productos emitidos: un item
    que se descarta por no traer precio es una decisión nuestra, no una página que
    se perdió, y mezclarlos volvería heurística la guarda exacta de
    `completeness()`.
    """

    products: list[RawProduct] = field(default_factory=list)
    enumerated: int = 0
    declared: int | None = None
    pages: int | None = None


def parse_listing(
    html: str,
    *,
    store_slug: str,
    category: CategoryRef,
    scraped_at: datetime,
    brand_selector: str = BRAND_SELECTOR,
) -> ParsedPage:
    """Convierte el grid en productos."""
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
            return ParsedPage(declared=declared_total(tree), pages=total_pages(tree))
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
                brand=normalize_brand(_text(item, brand_selector)),
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

    return ParsedPage(
        products=products,
        enumerated=len(items),
        declared=declared_total(tree),
        pages=total_pages(tree),
    )


class _MagentoHtmlAdapter:
    """Base compartida. Las subclases fijan host, paginación y selectores."""

    slug: str = ""
    rate_limit_rps: float = 0.5
    base_url: str = ""
    #: Valor de `product_list_limit`, o `None` para no mandarlo y usar el default
    #: de la tienda. Solo valen los valores de SU limiter (ver el docstring del
    #: módulo): cualquier otro cae al default sin avisar.
    page_size: int | None = PAGE_SIZE
    #: ¿El `robots.txt` de la tienda permite `?p=`? Es la única razón por la que
    #: una tienda de esta familia pagina y otra no.
    paginates: bool = False
    #: Techo de páginas por categoría. Vale como cota de cordura: el corte normal
    #: es el total que declara el paginador.
    max_pages: int = 30
    brand_selector: str = BRAND_SELECTOR

    def __init__(self, http: HttpClient, categories: Sequence[CategoryRef]) -> None:
        self._http = http
        self._categories = tuple(categories)
        self._completeness: dict[str, tuple[int, int]] = {}

    def categories(self) -> Sequence[CategoryRef]:
        return self._categories

    def completeness(self, category: CategoryRef) -> tuple[int, int] | None:
        return self._completeness.get(category.store_key)

    def headers(self) -> dict[str, str] | None:
        """Cabeceras extra de la tienda. Ver `ConstrumartAdapter`."""
        return None

    def _url(self, category: CategoryRef, page: int) -> str:
        query = []
        if page > 1:
            query.append(f"p={page}")
        if self.page_size is not None:
            query.append(f"product_list_limit={self.page_size}")
        suffix = f"?{'&'.join(query)}" if query else ""
        return f"{self.base_url}/{category.store_key.lstrip('/')}{suffix}"

    async def discover(self, category: CategoryRef) -> AsyncIterator[RawProduct]:
        self._completeness.pop(category.store_key, None)
        seen: set[str] = set()
        enumerated = 0
        declared: int | None = None
        page, pages = 1, 1

        while page <= min(pages, self.max_pages):
            html = await self._http.get_text(
                self._url(category, page),
                rps=self.rate_limit_rps,
                headers=self.headers(),
            )
            scraped_at = datetime.now(timezone.utc)
            parsed = parse_listing(
                html,
                store_slug=self.slug,
                category=category,
                scraped_at=scraped_at,
                brand_selector=self.brand_selector,
            )
            enumerated += parsed.enumerated

            if page == 1:
                # El total se toma de la primera página y no se vuelve a mirar:
                # si el catálogo se mueve mientras paginamos, la referencia tiene
                # que ser la del arranque o el chequeo se persigue la cola.
                declared = parsed.declared
                pages = parsed.pages or 1 if self.paginates else 1

            nuevos = 0
            for product in parsed.products:
                if product.store_sku in seen:
                    continue
                seen.add(product.store_sku)
                nuevos += 1
                yield product

            # Una página que EMITE productos y no aporta ni un SKU nuevo es el
            # síntoma de una tienda que dejó de respetar `?p=` y sirve la primera
            # para siempre. Que no emita nada no lo es: la última página de
            # Construmart suele traer solo filas sin precio (lo que esa sucursal
            # no tiene), y avisar de eso sería una alerta por pasada para siempre.
            if page > 1 and parsed.products and nuevos == 0:
                logger.warning(
                    "pagina_repetida store=%s categoria=%s pagina=%d",
                    self.slug,
                    category.slug,
                    page,
                )
                break
            page += 1

        if declared is not None:
            self._completeness[category.store_key] = (enumerated, declared)


class KupferAdapter(_MagentoHtmlAdapter):
    """Kupfer. `store_key` = el path de la categoría, con `.html`.

    Su `robots.txt` no declara `Crawl-delay`, así que rige el default conservador
    de la familia. Lo que sí declara es `Disallow: /*?p=`, que es por lo que esta
    tienda **no pagina** y por lo que solo se le conectan categorías que entren en
    una página de 36.

    **El catálogo que mapea a nuestra taxonomía es chico**: Kupfer es industrial
    (amarre, cadenas, mantención) y su rama de herramientas eléctricas tiene 24
    productos. No es una tienda que vaya a mover el volumen del canal; entra
    porque cuesta una request por pasada y porque es el primer caso de esta
    familia, que Sparta y Andesgear reusan después sin escribir código.
    """

    slug = "kupfer"
    base_url = "https://kupfer.cl"


class ConstrumartAdapter(_MagentoHtmlAdapter):
    """Construmart. `store_key` = el path de la categoría, sin `.html`.

    Pagina —su `robots.txt` permite `?p=`— con el tamaño de página por defecto
    (20, que además es el máximo que ofrece su limiter), así que la URL no lleva
    `product_list_limit` y no toca ninguno de los parámetros que su robots sí
    prohíbe (`?limit=`, `?mode=`, `?dir=`, `?order=`).

    **Manda la cookie de sucursal**, sin la cual el listado no trae precios (ver
    el docstring del módulo). `CUSTOMER_GROUP_ID` es la sucursal cuya serie
    estamos construyendo, y cambiarlo cambia el significado de todo el histórico
    de esta tienda: el p50 de un SKU sería una mezcla de dos sucursales. Si alguna
    vez hay que moverlo, la serie vieja no sirve.
    """

    slug = "construmart"
    base_url = "https://www.construmart.cl"
    page_size = None
    paginates = True
    #: Construmart usa `atributte-brand`, con el typo del tema.
    brand_selector = "p.atributte-brand"
    #: Su total declarado SÍ es confiable y por eso el canario queda exacto:
    #: las filas del grid coinciden con `toolbar-number` categoría por categoría
    #: (18=18, 18=18, 12=12, y 20+3=23 en la paginada; medido el 2026-09-24).
    #: Ojo con cómo se cuenta: las filas sin precio —lo que esa sucursal no
    #: tiene— también se enumeran, y son hasta un tercio de la categoría. Contar
    #: solo las vendibles hace parecer que la tienda declara de más.

    #: DEPARTAMENTAL (Av. Departamental 541, Santiago), `customer_group_id` 35.
    #: Sucursal urbana grande; elegida sobre Las Condes y Las Rejas para no tomar
    #: ni el extremo caro ni el barato del abanico de precios de la cadena.
    CUSTOMER_GROUP_ID = "35"

    def headers(self) -> dict[str, str] | None:
        return {"Cookie": f"persistent_customer_group_id={self.CUSTOMER_GROUP_ID}"}
