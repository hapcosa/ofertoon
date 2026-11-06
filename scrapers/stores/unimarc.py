"""Catálogo público de Unimarc, servido dentro de `__NEXT_DATA__`.

El front es Next.js y lo que hay detrás es VTEX (`categoryData.url` apunta a
`unimarc.vtexcommercestable.com.br`), pero **no se entra por la API VTEX**: la
página de categoría ya trae el catálogo con precio, EAN, `ppum` y la promoción
resueltos para un canal, y la API cruda obligaría a resolver eso de nuevo.

EL CANAL DE VENTA ES PARTE DE LA SERIE
-------------------------------------

Unimarc cotiza por `salesChannel`, y el canal sale de la dirección que el
cliente eligió (el front lo escribe en la cookie `co_sc` vía
`/api/setCookie?co_sc=N`, y el BFF lo deriva de coordenadas en
`/address/validate-sc`). Un visitante anónimo recibe el **39**: lo declara la
home en `pageProps.salesChannel` y lo pone el SSR por default.

Medido el 2026-11-06 sobre `leches-blancas` (33 SKUs), pidiendo la misma URL con
distintas cookies: `co_sc=39` da exactamente lo mismo que no mandar cookie (0
diferencias), `co_sc=1` cambia el precio de 1 SKU, `co_sc=2` el de 2, y
`co_sc=40` **cambia el surtido** (35 entradas en vez de 33). O sea el canal
cambia precio y catálogo.

Por eso `SALES_CHANNEL` se manda **explícito en toda request** y no se deja al
default del servidor: es el mismo caso que `ConstrumartAdapter.CUSTOMER_GROUP_ID`
y tiene la misma consecuencia — **cambiar este número invalida el histórico
entero de la tienda**, porque el p50 de un SKU quedaría mezclando dos canales.

CLUB UNIMARC ES OFERTA, Y LA CONDICIÓN VIAJA CON EL PRECIO
----------------------------------------------------------

Decisión del dueño del 2026-11-05: el precio Club cuenta como oferta porque ser
Club es solo dar el RUT. No es una tarjeta de la casa, así que **no** va a
`price_card` — va a `price_effective`, con su condición en `price_condition`
para que el copy la declare (migración 47).

La etiqueta vive en `priceDetail.promotionalTag.text` y **`membership` viene
vacío en ofertas que sí dicen Club**, así que mirar ese arreglo no alcanza.

NOTA DEL USER-AGENT: ACÁ EL CASO ESTÁ AL REVÉS
----------------------------------------------

Medido el 2026-11-06 contra la misma URL, 4 intentos de cada juego de headers:

    DEFAULT_USER_AGENT   200, 200, 200, 200   catálogo 4/4
    BROWSER_USER_AGENT   403, 403, 403, 403   catálogo 0/4
    BROWSER_HEADERS      200, 200, 200, 200   catálogo 4/4

O sea el **inverso** de Prat, Easy y Ferretek: lo que esta tienda rechaza no es
el UA identificable sino un UA de navegador **sin el resto de los headers que un
navegador manda**. Por eso el adaptador no pasa `BROWSER_HEADERS` ni fuerza
`BROWSER_USER_AGENT` —que la rompería— y se queda con el default de `HttpClient`,
que es el UA identificable. Verificado además sobre una paginación completa
(`mascotas`, 5 páginas, 241/241, cinco 200), no solo sobre requests sueltas.

Es el orden que manda TRAMPAS §A y acá paga al revés: probar los tres aislando la
variable, en vez de copiar el juego de headers del adaptador de al lado.

Lo que sí manda a `price_card` es un `paymentMethod` no vacío: ese precio exige
un medio de pago, no un RUT, y entonces el precio que paga cualquiera es el de
lista. No se observó ninguno en las 8.216 entradas medidas el 2026-11-06, y la
guarda existe igual porque el día que aparezca el default silencioso sería
publicar un precio con plástico como si fuera el de todos.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

from selectolax.parser import HTMLParser

from scrapers.base import (
    MAX_PLAUSIBLE_CLP,
    PRICE_CONDITION_MAX_CHARS,
    PROMO_LABEL_MAX_CHARS,
    PUM_LABEL_MAX_CHARS,
    CategoryRef,
    PromoCantidad,
    Pum,
    RawProduct,
)
from scrapers.http import HttpClient

BASE_URL = "https://www.unimarc.cl"

#: Canal de venta del visitante anónimo. Ver el docstring del módulo: cambiarlo
#: invalida el histórico de la tienda.
SALES_CHANNEL = "39"

#: Entradas por página. Lo fija la tienda (`?page=N` sirve de 50 en 50) y no es
#: configurable: no hay parámetro de tamaño.
PAGE_SIZE = 50

#: `$1.190 x litro`. Las tres bases observadas —`Kg`, `litro`, `unidad`— entran
#: en `price_points.pum_label`; una más larga se descarta en vez de truncarse,
#: porque media etiqueta es una unidad equivocada.
_PPUM_RE = re.compile(r"^\$([\d.]+)\s*x\s*(.+)$")

#: `4 x $1.150`. Es el texto que el canal publica verbatim, y de paso la fuente
#: del total en CLP entero: `promotion.price` llega como float (287.5) y el
#: dinero no se guarda en float.
_PROMO_RE = re.compile(r"^(\d+)\s*x\s*\$([\d.]+)$")


class NotAListingPage(RuntimeError):
    """La página respondió, pero no es un listado de catálogo."""


def clp(value: object) -> Decimal | None:
    """CLP entero y plausible, o `None`. Nunca float para dinero."""
    try:
        price = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None
    if price.is_finite() and 0 < price <= MAX_PLAUSIBLE_CLP and price == price.to_integral_value():
        return price
    return None


def _entero_cl(texto: str) -> Decimal | None:
    """`1.150` → 1150. El punto es separador de miles, no decimal."""
    return clp(texto.replace(".", "")) if texto else None


def parse_pum(ppum: object) -> Pum | None:
    """`"$1.190 x litro"` → `Pum("litro", 1190)`.

    El `ppum` que se lee es el de `sellers[0]`, que es el del precio publicado.
    El de `priceDetail.ppumListPrice` es el del precio tachado: el precio por
    kilo de un precio que ya no existe.
    """
    if not isinstance(ppum, str):
        return None
    match = _PPUM_RE.match(ppum.strip())
    if match is None:
        return None
    price = _entero_cl(match.group(1))
    label = match.group(2).strip()
    if price is None or not label or len(label) > PUM_LABEL_MAX_CHARS:
        return None
    return Pum(label=label, price=price)


def parse_promo(product: dict) -> PromoCantidad | None:
    """La promoción de multicompra, o `None` si no hay o si no cuadra.

    Tres fuentes dicen lo mismo y se exige que concuerden, porque una promo mal
    leída publica un ahorro que no existe:

    * `priceDetail.itemsRequiredForPromotion` — las unidades que exige;
    * `promotion.descriptionMessage` — `"4 x $1.150"`, el texto del canal;
    * `promotion.price` — el unitario bajo promo, en float.

    Se toma `qty` y `total` del **texto** (enteros, en CLP) y se verifica contra
    los otros dos. Si discrepan no se emite promo: el producto entra igual con su
    precio unitario, que es lo que de verdad paga quien compra una.
    """
    detail = product.get("priceDetail") or {}
    promotion = product.get("promotion") or {}
    qty_declarado = detail.get("itemsRequiredForPromotion")
    mensaje = (promotion.get("descriptionMessage") or "").strip()
    if not qty_declarado or not mensaje:
        return None
    match = _PROMO_RE.match(mensaje)
    if match is None:
        return None
    qty = int(match.group(1))
    total = _entero_cl(match.group(2))
    if total is None or qty < 2 or qty != qty_declarado or len(mensaje) > PROMO_LABEL_MAX_CHARS:
        return None
    # Control cruzado contra el unitario que declara la tienda. Se compara con
    # tolerancia de un peso: `promotion.price` es float y `4 x $1.150` da 287,5.
    unitario = promotion.get("price")
    if isinstance(unitario, (int, float)) and unitario > 0:
        if abs(Decimal(str(unitario)) * qty - total) > 1:
            return None
    return PromoCantidad(qty=qty, total=total, label=mensaje)


def _condicion(product: dict, *, condiciona: bool) -> str | None:
    """La condición que hay que cumplir para pagar el precio publicado.

    Es la etiqueta promocional verbatim (`"Club Unimarc"`, `"Exclusivo .cl"`),
    pero **solo cuando de verdad condiciona un precio**, y eso lo decide
    `condiciona`: que el precio publicado sea menor al de lista, o que haya una
    promoción de multicompra.

    `promotionalTag` NO es un campo de condiciones — es el espacio de marketing
    del tile, y la tienda pone ahí lo que quiere. Medido el 2026-11-06 sobre las
    8.213 entradas de las ocho llaves, aparecen cuatro etiquetas y solo dos son
    condiciones:

        Club Unimarc        2.615   precio < lista (2.007) o promo (608)
        Exclusivo .cl         220   precio < lista (194)   o promo (26)
        Diamante                5   precio == lista, sin promo  → un sello de
                                    vino, no una condición de compra
        Pronto disponible      15   los 15 agotados, 14 con precio 0 → es un
                                    estado de STOCK, no de precio

    El filtro clasifica bien las 8.213: de las Club y las Exclusivo **ninguna**
    tiene precio igual al de lista sin promo, y Diamante y Pronto disponible no
    pasan nunca. Y es una regla de dominio en vez de una lista de nombres a
    mantener: una etiqueta nueva sobre un precio rebajado se declara verbatim
    —que es lo correcto, porque el suscriptor tiene que leerla aunque nosotros no
    sepamos qué significa— y un sello nuevo sobre un precio sin rebaja no inventa
    letra chica. Publicar "Requiere Diamante" sobre un vino que cuesta lo mismo
    que siempre sería tan malo como callar el Club.
    """
    if not condiciona:
        return None
    tag = ((product.get("priceDetail") or {}).get("promotionalTag") or {}).get("text")
    if not isinstance(tag, str):
        return None
    tag = " ".join(tag.split())
    return tag[:PRICE_CONDITION_MAX_CHARS] if tag else None


def _exige_medio_de_pago(product: dict) -> bool:
    """¿El precio publicado exige un medio de pago? Ver el docstring del módulo."""
    return bool((product.get("priceDetail") or {}).get("paymentMethod"))


def listing_data(html: str) -> tuple[int, int, list[dict], list[dict]]:
    """`(página servida, total declarado, disponibles, agotados)`.

    `notAvailableProducts` se devuelve aparte y **no se descarta**: es la señal
    de stock de la tienda y alimenta `in_stock`, que es lo que frena la
    publicación de algo que no se puede comprar.
    """
    node = HTMLParser(html).css_first("#__NEXT_DATA__")
    try:
        props = json.loads(node.text())["props"]["pageProps"]
        for query in props["dehydratedState"]["queries"]:
            key = query.get("queryKey")
            if isinstance(key, list) and key and key[0] == "productsSearch-client":
                data = query["state"]["data"]
                disponibles = data["availableProducts"]
                agotados = data["notAvailableProducts"]
                if not isinstance(disponibles, list) or not isinstance(agotados, list):
                    raise ValueError("catálogo inválido")
                return int(props["page"]), int(data["resource"]), disponibles, agotados
    except (AttributeError, KeyError, TypeError, ValueError) as exc:
        raise NotAListingPage("Unimarc: falta el catálogo estructurado") from exc
    raise NotAListingPage("Unimarc: la página no trae productsSearch-client")


def parse_product(
    item: dict, *, category: CategoryRef, in_stock: bool, scraped_at: datetime
) -> RawProduct | None:
    """Una entrada del listado a `RawProduct`, o `None` si no es publicable.

    La identidad del listing es `sku`, que en esta tienda es el identificador que
    la propia ficha usa y es uno por producto: acá no hay talles, así que no se
    repite el problema de `vtex_family`, donde la identidad es el talle y cambia
    de pasada a pasada.
    """
    sku = str(item.get("sku") or "")
    nombre = (item.get("name") or "").strip()
    detail_url = item.get("detailUrl") or ""
    seller = (item.get("sellers") or [{}])[0]
    publicado = clp(seller.get("price"))
    lista = clp(seller.get("listPrice"))
    if not sku or not nombre or not detail_url or publicado is None:
        return None

    promo = parse_promo(item)
    # Un precio que exige medio de pago no es el que paga cualquiera: se muestra
    # como precio de tarjeta y el efectivo pasa a ser el de lista. La condición
    # entonces no corresponde: la etiqueta calificaba al precio con plástico, que
    # ya no es el que se publica.
    if _exige_medio_de_pago(item):
        if lista is None:
            return None
        efectivo, tarjeta, condicion = lista, publicado, None
    else:
        efectivo, tarjeta = publicado, None
        condicion = _condicion(
            item,
            condiciona=(lista is not None and publicado < lista) or promo is not None,
        )

    declarado = (item.get("priceDetail") or {}).get("discountPercentage")
    return RawProduct(
        store_slug="unimarc",
        store_sku=sku,
        url=BASE_URL + detail_url,
        name=nombre,
        price_effective=efectivo,
        price_normal=lista if lista is not None and lista > efectivo else None,
        price_card=tarjeta,
        price_condition=condicion,
        scraped_at=scraped_at,
        in_stock=in_stock and (seller.get("availableQuantity") or 0) > 0,
        brand=(item.get("brand") or None),
        gtin=(item.get("ean") or None),
        category_path=category.store_key,
        image_url=(item.get("images") or [None])[0],
        claimed_discount=f"-{declarado}%" if isinstance(declarado, int) and declarado else None,
        pum=parse_pum(seller.get("ppum")),
        promo=promo,
    )


class UnimarcAdapter:
    """Supermercado Unimarc. Una llave por departamento, paginada con `?page=N`.

    No implementa `completeness`, y no por falta de dato: la tienda declara el
    total y la paginación llega al final. Sobre el recorrido completo de las ocho
    llaves del 2026-11-06, cinco cerraron exacto y **tres quedaron UNA entrada
    cortas** (`despensa` 1.680/1.681, `desayuno-y-dulces` 1.314/1.315, `limpieza`
    810/811). Es la misma deriva entre el servicio que cuenta y el que pagina que
    documenta `cencosud_family`, y es inestable: `bebidas-y-licores` cerró
    1.588/1.588 en este recorrido. Con el canario exacto encendido serían tres
    llaves en `partial` casi toda pasada por **una entrada de 1.681** — la misma
    alarma que suena siempre, y por lo tanto apagada, que la familia Falabella
    documenta para su llave corta por un producto de 352. Queda el canario
    estadístico.

    Tampoco deduplica entre llaves, y eso es una medición, no un descuido: de
    8.213 entradas recorridas salieron **8.212 SKUs únicos**. El único solapado es
    un espumador de leche (`97701`) que vive en `desayuno-y-dulces` y aparece
    cross-listado en `lacteos-huevos-y-refrigerados`; su efecto es pesar doble en
    su propio p50, sobre 1 listing de 8.212.

    Deduplicar en la pasada entera —como `cencosud_family` y `AndesgearAdapter`—
    arreglaría ese caso y traería el riesgo que esos dos documentan: gana la
    primera llave del orden de `db.load_store_targets`, lo cual es inocuo solo
    mientras las llaves que solapan mapeen a la misma categoría interna. Acá
    `perfumeria` mapea a `belleza` y las otras siete a `supermercado`, así que un
    solapamiento futuro con `perfumeria` haría que un producto de belleza se
    midiera con el θ de supermercado **en silencio**. Por un listing de 8.212 no
    vale pagar ese riesgo. Si el solapamiento crece, hay que volver a decidirlo
    con el número a la vista.

    ⚠️ Y si alguna vez se agrega una llave, medirlo de nuevo: la tienda tiene
    vitrinas transversales que cross-listan catálogo —`fiestas-patrias` reaparece
    como `categorySlug` de 32 de las 50 entradas de la página 1 de
    `bebidas-y-licores`— y una de esas sí solaparía en serio.
    """

    slug = "unimarc"
    #: Las ocho llaves son 169 requests medidas (8.213 entradas, 2026-11-06): a
    #: este ritmo son ~7 min por pasada, que caben de sobra en la ventana de 120.
    #: No hay motivo para ir más rápido.
    rate_limit_rps = 0.4
    #: 80 × 50 = 4.000, el doble de la llave más grande (`despensa`, 1.681). Es
    #: tope de seguridad contra una paginación que no termine, no un recorte.
    max_pages = 80

    def __init__(self, http: HttpClient, categories: list[CategoryRef]) -> None:
        self._http = http
        self._categories = tuple(categories)

    def categories(self) -> tuple[CategoryRef, ...]:
        return self._categories

    async def discover(self, category: CategoryRef):
        # Solo la cookie: el `User-Agent` identificable y el `Accept-Language`
        # los pone `HttpClient`, y alcanzan. Ver NOTA DEL USER-AGENT arriba.
        headers = {"Cookie": f"co_sc={SALES_CHANNEL}"}
        vistos: set[str] = set()
        declarado: int | None = None
        for page in range(1, self.max_pages + 1):
            url = f"{BASE_URL}/category/{category.store_key.strip('/')}?page={page}"
            html = await self._http.get_text(url, rps=self.rate_limit_rps, headers=headers)
            servida, total, disponibles, agotados = listing_data(html)
            # La tienda echa la página pedida en su propio payload. Si sirve otra,
            # paginar es recorrer la 1 en loop y cada pasada pesaría 50 veces el
            # mismo precio en el p50.
            if servida != page:
                raise NotAListingPage(
                    f"Unimarc: pedí la página {page} y la tienda sirvió la {servida}"
                )
            if declarado is None:
                declarado = total
                if total <= 0 or not (disponibles or agotados):
                    raise NotAListingPage(
                        f"Unimarc: la llave {category.store_key!r} no tiene catálogo"
                    )
            scraped_at = datetime.now(timezone.utc)
            nuevos = 0
            for items, in_stock in ((disponibles, True), (agotados, False)):
                for item in items:
                    sku = str(item.get("sku") or "")
                    if not sku or sku in vistos:
                        continue
                    vistos.add(sku)
                    nuevos += 1
                    product = parse_product(
                        item, category=category, in_stock=in_stock, scraped_at=scraped_at
                    )
                    if product is not None:
                        yield product
            # Tres cortes: la página vino vacía, ya cubrimos el total declarado, o
            # dejó de aparecer SKU nuevo (que es lo que pasa cuando la tienda
            # repite la última página en vez de devolver vacío).
            if not (disponibles or agotados) or page * PAGE_SIZE >= declarado or nuevos == 0:
                break
