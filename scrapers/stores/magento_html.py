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

#: De dónde salen el nombre y la URL de la ficha. El default es el enlace que
#: pone el tema `Luma` de Magento y que usan Kupfer, Construmart, Andesgear,
#: Sparta y New Balance.
#:
#: **Pero no todos los temas lo ponen**, y cuando falta el producto se descarta
#: entero aunque su precio y su SKU estén a la vista: medido el 2026-11-05,
#: `speedo.cl` y `trekbikeschile.com` enumeran 33 y 36 filas del grid y emiten
#: **cero**, porque ahí el nombre vive en el elemento que lleva
#: `data-product-sku` y la URL en el enlace de la foto
#: (`a.product-item-photo`). Es la misma clase de variación que
#: `BRAND_SELECTOR`: la elige el tema, no Magento.
NAME_SELECTOR = "a.product-item-link"
URL_SELECTOR = "a.product-item-link"

#: Dónde vive el SKU de la tienda. `form[data-product-sku]` es el del botón
#: "añadir al carrito" y es el default; `span.product-item-sku` se mira siempre
#: porque es el que se imprime en la ficha.
#:
#: Speedo y Trek cuelgan el atributo de un elemento que **no es un `form`**, así
#: que el selector tiene que poder aflojarse a `[data-product-sku]`. Y hay temas
#: que no lo traen en ninguna parte (`weplay.cl`): ahí no hay SKU que leer del
#: grid y la tienda **no entra** por esta vía — inventarle uno del `id` interno
#: rompería la serie en la primera reindexación del catálogo.
SKU_SELECTOR = "form[data-product-sku]"

#: Cuántas páginas declara el paginador. Es de Amasty, no de Magento, pero las
#: dos tiendas de la familia lo traen. Sirve para NO probar una página pasada del
#: final: se piden exactamente las que la tienda dice tener.
_PAGE_COUNT = "#am-page-count"

#: Vocabulario que convierte a `span.price-label` en una señal de stock. Sin este
#: filtro, cualquier rótulo de precio se leería como disponibilidad.
_STOCK_WORDS = ("disponible", "agotado", "stock")


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


def _sku_of(item: Any, selector: str = SKU_SELECTOR) -> str | None:
    """SKU propio de la tienda, el mismo que imprime la boleta.

    No se usa el `id` interno de `product-item-info_16211`: el SKU es el código
    de artículo de la empresa y sobrevive a una reindexación del catálogo.
    """
    shown = _text(item, "span.product-item-sku")
    if shown:
        sku = clean_text(_SKU_PREFIX.sub("", shown))
        if sku:
            return sku
    nodo = item.css_first(selector)
    return clean_text(nodo.attributes.get("data-product-sku")) if nodo else None


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
    label = (_text(item, "span.price-label") or "").casefold()
    if not any(palabra in label for palabra in _STOCK_WORDS):
        # La etiqueta no habla de stock: en Sparta dice "Precio habitual" y es el
        # rótulo del precio tachado. Leerla como señal de disponibilidad marcaba
        # agotados exactamente a los 14 de 36 productos CON descuento, o sea a los
        # únicos que esta tienda podría publicar.
        return True
    return "disponible" in label


def total_pages(tree: Any) -> int | None:
    """Páginas que declara el paginador, o `None` si no lo declara."""
    node = tree.css_first(_PAGE_COUNT)
    if node is None:
        return None
    text = node.text(strip=True)
    return int(text) if text.isdigit() else None


def declared_total(tree: Any) -> int | None:
    """Cuántos productos declara la categoría, del bloque `toolbar-amount`.

    Se toma el **último** entero del bloque, no el primero, porque las tres
    plantillas de Magento que la familia ve escriben el total al final:

        Kupfer       "5 artículos"            → 5
        Construmart  "23 Productos"           → 23
        Sparta       "Artículos 1-36 de 1080" → 1080

    Sparta es el caso que fija la regla: emite **tres** `span.toolbar-number` (1,
    36 y 1080) y quedarse con el primero daba 1 para una categoría de 1.080. Eso
    no fallaba ruidosamente: `canary_verdict` solo marca `partial` cuando lo
    enumerado es MENOR que lo declarado, así que 36 contra 1 pasaba como `ok` y
    la guarda exacta quedaba anulada en silencio.
    """
    node = tree.css_first("p.toolbar-amount") or tree.css_first("span.toolbar-number")
    if node is None:
        return None
    numeros = re.findall(r"\d+", node.text(strip=True).replace(".", ""))
    return int(numeros[-1]) if numeros else None


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
    name_selector: str = NAME_SELECTOR,
    url_selector: str = URL_SELECTOR,
    sku_selector: str = SKU_SELECTOR,
) -> ParsedPage:
    """Convierte el grid en productos.

    Los cuatro selectores son por tienda porque los elige el **tema** de
    Magento, no Magento: ver los docstrings de `BRAND_SELECTOR` y
    `NAME_SELECTOR`. Los defaults son los del tema `Luma`, que es el de las
    tiendas ya conectadas.
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
            return ParsedPage(declared=declared_total(tree), pages=total_pages(tree))
        raise NotAListingPage(
            f"{store_slug}/{category.slug}: store_key={category.store_key!r} "
            "no devolvió un grid de categoría"
        )

    items = grid.css(_ITEM)
    products: list[RawProduct] = []
    for item in items:
        sku = _sku_of(item, sku_selector)
        nombre_nodo = item.css_first(name_selector)
        name = clean_text(nombre_nodo.text(strip=True)) if nombre_nodo is not None else None
        url_nodo = item.css_first(url_selector)
        url = url_nodo.attributes.get("href") if url_nodo is not None else None
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
    #: ¿La tienda cross-lista el mismo SKU en varias categorías? Con esto en
    #: `True`, el `seen` vive en la pasada y no en la categoría: el producto se
    #: emite una vez y la llave que gana es la primera del orden de
    #: `db.load_store_targets`. Ver `AndesgearAdapter`.
    dedupe_across_categories: bool = False
    #: Techo de páginas por categoría. Vale como cota de cordura: el corte normal
    #: es el total que declara el paginador.
    max_pages: int = 30
    brand_selector: str = BRAND_SELECTOR
    #: Los tres que dependen del tema de la tienda. Ver `NAME_SELECTOR`.
    name_selector: str = NAME_SELECTOR
    url_selector: str = URL_SELECTOR
    sku_selector: str = SKU_SELECTOR

    def __init__(self, http: HttpClient, categories: Sequence[CategoryRef]) -> None:
        self._http = http
        self._categories = tuple(categories)
        self._completeness: dict[str, tuple[int, int]] = {}
        #: Solo se usa con `dedupe_across_categories`. La instancia vive una
        #: pasada, así que el conjunto se vacía solo entre pasadas.
        self._seen_en_la_pasada: set[str] = set()

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
        seen = (
            self._seen_en_la_pasada if self.dedupe_across_categories else set()
        )
        locales: set[str] = set()
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
                name_selector=self.name_selector,
                url_selector=self.url_selector,
                sku_selector=self.sku_selector,
            )
            enumerated += parsed.enumerated

            if page == 1:
                # El total se toma de la primera página y no se vuelve a mirar:
                # si el catálogo se mueve mientras paginamos, la referencia tiene
                # que ser la del arranque o el chequeo se persigue la cola.
                declared = parsed.declared
                pages = parsed.pages or 1 if self.paginates else 1

            # Dos conjuntos, y la distinción importa: `locales` detecta que la
            # tienda sirvió otra vez la misma página, y `seen` decide si el
            # producto se emite. Con `dedupe_across_categories` son distintos, y
            # confundirlos cortaba la paginación en la primera página cuyos
            # productos ya habían entrado por OTRA categoría — que en Andesgear
            # pasó en 3 de 25 categorías y dejó `mujer/calzado` en 140 de 224.
            nuevos_en_la_pagina = 0
            for product in parsed.products:
                if product.store_sku in locales:
                    continue
                locales.add(product.store_sku)
                nuevos_en_la_pagina += 1
                if product.store_sku in seen:
                    continue
                seen.add(product.store_sku)
                yield product

            # Una página que EMITE productos y no aporta ni un SKU nuevo A ESTA
            # CATEGORÍA es el síntoma de una tienda que dejó de respetar `?p=` y
            # sirve la primera para siempre. Que no emita nada no lo es: la última
            # página de Construmart suele traer solo filas sin precio (lo que esa
            # sucursal no tiene), y avisar de eso sería una alerta por pasada.
            if page > 1 and parsed.products and nuevos_en_la_pagina == 0:
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


class AndesgearAdapter(_MagentoHtmlAdapter):
    """Andesgear. `store_key` = el path de la categoría, sin `.html`.

    Pagina —su `robots.txt` no prohíbe `?p=`— y **respeta su `Crawl-delay: 3`**
    con `rate_limit_rps = 0.33`, que es lo que hace que una pasada suya cueste
    ~7 min: 25 llaves, ~140 páginas de 24. No se manda `product_list_limit`
    porque esta tienda **no publica un limiter**: sin la lista de valores que
    acepta, pedir uno sería adivinar, y un valor que no ofrece cae a su default
    sin avisar (la trampa que documenta el docstring del módulo).

    **Cross-lista el mismo SKU en varias categorías, y por eso deduplica por
    pasada.** Medido el 2026-09-26 sobre la primera página de 25 categorías: el
    árbol `montana-nieve/*` re-lista productos de `hombre/*`, `mujer/*` y
    `escalada/*`, el calzado unisex aparece en `hombre/calzado` y en
    `mujer/calzado`, y hay una chaqueta de niño en `ninos/top`. Con 24 de cientos
    de productos por muestra ya aparecieron 13 pares solapados: el catálogo real
    solapa más.

    Lo que hace seguro deduplicar acá es que **los 13 pares caen dentro de la
    misma categoría interna** (montana-nieve/vestuario con hombre y mujer son
    todos `deporte-vestuario`; el calzado unisex es todo `deporte-calzado`), así
    que cuál llave gana no cambia el θ contra el que se mide ese producto. Si
    alguna vez se conecta una llave que cruce dos categorías internas, esto deja
    de ser inocuo.

    No aporta identidad: su grid no expone GTIN ni modelo, y tampoco marca (0 de
    24 con los dos selectores de la familia).
    """

    slug = "andesgear"
    base_url = "https://www.andesgear.cl"
    #: `Crawl-delay: 3` en su robots.txt.
    rate_limit_rps = 0.33
    page_size = None
    paginates = True
    dedupe_across_categories = True
    #: 28 páginas es la categoría más grande medida (`hombre/accesorios`, 662
    #: productos, que igual no se conecta). 30 deja margen sin ser un cheque en
    #: blanco.
    max_pages = 30


# ---------------------------------------------------------------------------
# LA PLANTILLA DE ROBOTS DE SPARTA: cuatro tiendas, ninguna pagina
# ---------------------------------------------------------------------------
#
# Sparta, Speedo, Trek Chile y New Balance Chile sirven un `robots.txt`
# **idéntico**: 87 `Disallow`, `Crawl-delay: 1`, y entre ellos `/*?`, `/?`,
# `/*?*`, `/*&*`, `/*product_list_limit=` y `/*?limit=*`. O sea **ninguna query
# string está permitida**, lo que deja a las cuatro en la configuración de Kupfer:
# una request por llave y el techo de cobertura que eso implica.
#
# Que el robots sea el mismo carácter por carácter sugiere un mismo operador
# detrás, y vale como aviso: si una de las cuatro cambia de política, conviene
# revisar las otras tres.


class SpartaAdapter(_MagentoHtmlAdapter):
    """Sparta. `store_key` = el path de la categoría, con `.html`.

    **No pagina**, y no por elección nuestra: su `robots.txt` prohíbe toda query
    string (ver el comentario de arriba). Eso le pone techo a la cobertura:
    medido el 2026-11-04 sobre **545 hojas de catálogo**, lo alcanzable son
    **3.615 SKUs de los 13.448 que declara su sitemap, o sea el 24%**. De las 485
    hojas con total declarado, 375 entran completas (declaran ≤36) y 110 declaran
    10.996 y aportan 36 cada una.

    **Orden estable**, que es lo que hace viable no paginar: con la página 1 como
    única ventana, un orden rotatorio dejaría a todo el catálogo sin llegar nunca
    a `MIN_DAYS`. Medido con ~15 min de separación real sobre 9 hojas (6 de ellas
    con más de 300 productos declarados): **8 de 9 con Jaccard 1,000**, y la
    novena perdió 1 producto de 36 sin ganar ninguno — deriva de catálogo, no
    reordenamiento.

    **Cross-lista fuerte y por eso deduplica.** Expone el mismo catálogo por tres
    ejes: la taxonomía de producto, un árbol paralelo `deportes/` (189 hojas que
    solapan 49-91% con todos los demás) y los ejes de género más las vitrinas.
    El conjunto recomendado son las 9 raíces de taxonomía: 340 hojas, 3.157 SKUs
    (87,3% de lo alcanzable), **1,72× residual**.

    ⚠️ **Y ese 1,72× tiene una letra chica que el precedente de Andesgear NO
    cubre.** Acá los solapamientos cruzan **categorías internas distintas**:
    `vestuario-deportivo` × `deportes-individuales` solapan 30% y
    `entrenamiento-funcional` × `deportes-individuales` 36%, y esos ejes mapean a
    `deporte-vestuario` contra `deporte-equipamiento`. Con el dedupe puesto gana
    la primera llave del orden de `db.load_store_targets`, así que una polera
    podría quedar puntuando con el θ de equipamiento. **Hay que ordenar los
    `store_key` a propósito**, o renunciar a los ejes que se cruzan.

    `price_normal` en **41,6%** de 9.083 filas ⇒ θ se puede fijar midiendo. Es el
    primer Magento del sistema que lo trae.

    **Oculta los agotados en vez de marcarlos** (medido sobre 3 categorías / 108
    productos: cero vocabulario de stock, botón `tocart` en todas las filas), así
    que el `in_stock` ciego no cuesta nada estructural: un producto que se agota
    desaparece y su serie queda con un hueco. ⚠️ Pero su grid muestra "Desde" en
    6-15 filas por categoría: para un producto configurable el precio es **el
    mínimo entre sus talles**, no "el precio".
    """

    slug = "sparta"
    base_url = "https://sparta.cl"
    #: `Crawl-delay: 1`.
    rate_limit_rps = 1.0
    #: Su robots prohíbe `/*product_list_limit=`.
    page_size = None
    #: Su robots prohíbe `/*?` y `/*?*`.
    paginates = False
    dedupe_across_categories = True


class SpeedoAdapter(_MagentoHtmlAdapter):
    """Speedo Chile. `store_key` = el path de la categoría, con `.html`.

    **Su tema no pone `a.product-item-link`**, y eso la dejaba emitiendo cero con
    los selectores por defecto de la familia — con el agravante de que el fallo
    era invisible: el parser encontraba el grid, enumeraba las 33 filas y leía el
    total declarado y el número de páginas, así que `canary_verdict` cerraba sano.
    Un `enumerated` correcto con `emit=0` no lo ve ninguna guarda.

    Acá el nombre vive en el elemento que lleva `data-product-sku` y la URL en el
    enlace de la foto. Con eso: **33 de 33 filas emitidas**.

    Llaves medidas el 2026-11-05 sobre **107 hojas**: 425 SKUs alcanzables, y el
    conjunto de catálogo (`equipamiento`, `lentes`, `hombre`, `mujer`, `ninos`)
    son **70 hojas, 383 SKUs (90,1%) y 1,15× residual**. Las tres vitrinas
    descartadas (`destacado`, `cyber`, `sale`) aportarían 42 SKUs exclusivos, y
    que son vitrinas lo dice la medición: `destacado` solapa 36-55% con **todos**
    los demás ejes.

    `price_normal` en **41,5%** de 2.000 filas ⇒ θ medible. `sin_stock = 0`: sin
    señal de stock en el grid. Precio máximo $599.990.
    """

    slug = "speedo"
    base_url = "https://speedo.cl"
    rate_limit_rps = 1.0
    page_size = None
    paginates = False
    dedupe_across_categories = True
    #: Ver el docstring: su tema no trae el enlace que la familia espera.
    name_selector = "[data-product-sku]"
    url_selector = "a.product-item-photo"
    sku_selector = "[data-product-sku]"


class TrekChileAdapter(_MagentoHtmlAdapter):
    """Trek Chile. `store_key` = el path de la categoría, con `.html`.

    Mismo tema que Speedo —sin `a.product-item-link`— y los mismos selectores.
    Con ellos: **36 de 36 filas emitidas**.

    Llaves medidas sobre **140 hojas**: 527 SKUs, y el conjunto de catálogo
    (`equipamiento`, `montana`, `ruta`, `gravel`, `urbana`,
    `bicicletas-electricas`, `accesorios-ciclismo`, `ninos`) son **93 hojas, 513
    SKUs (97,3%) y 1,05× residual** — el mejor número de toda la tanda. Las
    vitrinas descartadas aportarían 14 SKUs exclusivos, y su contención es
    flagrante: `destacado × ninos` y `cyber × accesorios-ciclismo` dan **100%**.

    `price_normal` en **42,4%** ⇒ θ medible. `sin_stock = 0`.

    ⚠️ **Su rango de ticket llega a $10.990.000** (una bicicleta de ruta), contra
    los $599.990 de Speedo. `compute_score` es `discount_real*100 +
    below_floor*50` y **no mira el precio absoluto** a propósito, así que un 30%
    sobre esa bici son **$3,3M de ahorro puntuando igual** que un 30% sobre unos
    anteojos de natación de $39.990. Es el mismo choque de rango que trajo el
    supermercado, y la respuesta por precedente es la misma: **destino propio, no
    tocar el score**.
    """

    slug = "trekbikeschile"
    base_url = "https://trekbikeschile.com"
    rate_limit_rps = 1.0
    page_size = None
    paginates = False
    dedupe_across_categories = True
    name_selector = "[data-product-sku]"
    url_selector = "a.product-item-photo"
    sku_selector = "[data-product-sku]"


class NewBalanceChileAdapter(_MagentoHtmlAdapter):
    """New Balance Chile. `store_key` = el path de la categoría, con `.html`.

    Esta **sí** trae `a.product-item-link`, así que usa los selectores por
    defecto: 36 de 36 filas emitidas.

    Llaves medidas sobre **258 hojas**: 1.408 SKUs alcanzables. El conjunto de
    catálogo (`deportes`, `hombre`, `mujer`, `ninos`, `ropa`, `running`,
    `zapatillas`) son **81 hojas, 909 SKUs (64,6%) y 1,87× residual**.

    ⚠️ **Se excluyen las vitrinas por decisión del dueño (2026-11-05), y eso
    cuesta el 35% del catálogo**: `cyber`, `destacados`, `grey-days`,
    `mas-vendidas`, `recien-llegados` y `sale` tienen **499 SKUs exclusivos de
    1.408**. Los que no entran **no son un faltante de cobertura**: es la decisión
    de no construir series sobre una vitrina que el comerciante puede reeditar,
    que es lo que le pasó a Prat con `herramientas-electricas` (240 listings
    muertos de golpe, y el canario callado a las 4 corridas). Y acá sería peor:
    con `paginates = False` esa vitrina es el **único** lugar donde esos SKUs
    aparecen.

    ⚠️ **Es la única tienda de la tanda conectable por dos familias**: su home
    trae a la vez la firma estricta de Magento y la de Demandware. Entra por
    Magento porque está verificado parseando y la familia ya existe; si alguna vez
    se escribe `salesforce_family`, **no conectarla dos veces**.

    `price_normal` en **39,5%** ⇒ θ medible. `sin_stock = 0`. Precio máximo
    $249.990.
    """

    slug = "newbalance"
    base_url = "https://newbalance.cl"
    rate_limit_rps = 1.0
    page_size = None
    paginates = False
    dedupe_across_categories = True


# ---------------------------------------------------------------------------
# LA PLANTILLA DE ROBOTS DE ANDESGEAR: cuatro tiendas outdoor que SÍ paginan
# ---------------------------------------------------------------------------
#
# The North Face, Kliper, Mammut y Marmot sirven un `robots.txt` idéntico: 17
# `Disallow`, `Crawl-delay: 3`, y nada que prohíba `?p=` ni el `limit`. O sea la
# configuración de Andesgear.
#
# ⚠️ **Y las cuatro son el mismo operador.** `kliper.cl` es el multimarca: su
# propio menú enlaza `/marcas/the-north-face`, `/marcas/marmot`, `/marcas/mammut`
# y **`/marcas/andesgear`** — o sea vende las marcas de las otras tres **y de una
# tienda ya conectada**. Dos consecuencias que no se arreglan en el adaptador:
#
# 1. El mismo producto va a existir como listing en Kliper y en la tienda de su
#    marca. Para la serie no es problema (son `store_id` distintos, cada uno con
#    su p50), pero el **canal** puede publicar la misma oferta dos veces con dos
#    precios. Eso lo acota `MAX_PER_STORE_PER_DAY`, no el detector.
# 2. Conectar las cuatro es contar el mismo catálogo cuatro veces en el
#    presupuesto de pasada. Si hay que elegir, Kliper sola cubre más.
#
# ⚠️ **Sus URLs de categoría van SIN `.html`**, a diferencia de las cuatro de
# arriba. Y la ruta más enlazada de su home no es una categoría (`/tiendas`,
# `/ayuda`): la llave sale del menú de catálogo, no del conteo de enlaces.


class _OutdoorKliperFamilia(_MagentoHtmlAdapter):
    """Base de las cuatro: `Crawl-delay: 3`, paginan, selectores por defecto."""

    #: `Crawl-delay: 3` en su robots.txt.
    rate_limit_rps = 0.33
    #: No publican un limiter, así que pedir un `product_list_limit` sería
    #: adivinar — y un valor que no ofrecen cae a su default sin avisar.
    page_size = None
    paginates = True
    dedupe_across_categories = True
    #: Sirven 24 por página. 30 páginas son 720 productos por llave: suficiente
    #: para todas las llaves medidas salvo las de Kliper, que hay que dimensionar
    #: aparte (declara 13.769 productos en `/marcas`).
    max_pages = 30


class TheNorthFaceAdapter(_OutdoorKliperFamilia):
    """The North Face Chile. `store_key` = el path, **sin** `.html`.

    Sirve **48 por página**, a diferencia de las otras tres de su familia.

    Llaves medidas sobre **196 hojas** (186 ok; las 10 `NotAListingPage` son
    rutas de su nav que no son catálogo): el conjunto de catálogo
    (`equipamiento`, `hombre`, `mujer`, `ni-os`, `zapatos`) son **113 hojas,
    1.211 de 1.269 SKUs de página 1 (95,4%) y 1,40× residual**. Sus vitrinas
    aportarían apenas 58 SKUs exclusivos.

    `price_normal` en **36,5%** de 4.586 filas ⇒ θ medible. `sin_stock = 0`.

    ⚠️ **Precio máximo observado $6.999.990**, muy por encima del resto del
    outdoor ($1,0M a $1,8M). Antes de conectarla hay que mirar qué es: o es
    equipamiento de expedición legítimo, o es un centinela — y la diferencia
    importa porque un valor así **envenena la baseline de ese SKU de forma
    permanente**.
    """

    slug = "thenorthface"
    base_url = "https://www.thenorthface.cl"


class KliperAdapter(_OutdoorKliperFamilia):
    """Kliper. `store_key` = el path, **sin** `.html`. El multimarca del grupo.

    Llaves medidas sobre **270 hojas** (269 ok): el conjunto de catálogo
    (`accesorios`, `hombre`, `mujer`, `ni-os`, `zapatos-zapatillas`) son **111
    hojas, 1.576 de 2.462 SKUs de página 1 (64,0%) y 1,26× residual**.

    ⚠️ **Y acá la decisión es más dura que en New Balance.** Sus vitrinas tienen
    **886 SKUs exclusivos de 2.462 (36%)**, y el grueso está en el eje **`marcas`
    (670 SKUs)** — que **no es una vitrina de promoción sino el eje de marca**, o
    sea la forma natural de navegar un multimarca. Descartarlo pierde más de un
    tercio; incluirlo lo pone a solapar con `hombre` (684) y `mujer` (732). Queda
    como decisión abierta.

    ⚠️ **Y es la tienda a dimensionar antes de conectar**: declara **13.769
    productos** en `/marcas` y 6.366 y 5.485 en `hombre` y `mujer`. A 24 por
    página, sus 111 hojas de catálogo son del orden de **cientos de requests por
    pasada** — hay que compararlo contra la hora de presupuesto que deja
    `db.PASS_WINDOW` antes de meterla.

    `price_normal` en **51,3%** ⇒ θ medible. `sin_stock = 0`. Precio máximo
    $1.799.990.
    """

    slug = "kliper"
    base_url = "https://www.kliper.cl"


class MammutAdapter(_OutdoorKliperFamilia):
    """Mammut Chile. `store_key` = el path, **sin** `.html`.

    La más limpia del grupo: **193 de 193 hojas barridas sin un solo error**. El
    conjunto de catálogo (`accesorios`, `calzado`, `equipamiento-mammut`,
    `hombre`, `mujer`) son **97 hojas, 465 de 475 SKUs (97,9%) y 1,27×
    residual**, y sus vitrinas aportarían **10** SKUs exclusivos — o sea
    descartarlas no cuesta nada.

    `price_normal` en **55,3%** ⇒ θ medible. `sin_stock = 0`. Precio máximo
    $1.039.990.
    """

    slug = "mammut"
    base_url = "https://www.mammut.cl"


class MarmotAdapter(_OutdoorKliperFamilia):
    """Marmot Chile. `store_key` = el path, **sin** `.html`.

    **144 de 144 hojas sin error.** El conjunto de catálogo (`accesorios`,
    `calzado`, `equipamiento`, `hombre`, `mujer`, `ni-os`) son **77 hojas, 296 de
    319 SKUs (92,8%) y 1,24× residual**; sus vitrinas aportarían 23 exclusivos.

    `price_normal` en **64,8%**, el más alto de toda la tanda ⇒ θ medible con
    buena muestra. `sin_stock = 0`. Precio máximo $1.000.000.
    """

    slug = "marmot"
    base_url = "https://www.marmot.cl"
