"""Nomades (ex deNomades): tours y actividades, el primer adaptador de viajes.

POR QUÉ ESTA TIENDA Y NO UNA AGENCIA DE VIAJES
----------------------------------------------

`PLAN_EXPANSION.md` §6 explica que la mayor parte de "viajes" **no entra en este
sistema**, y el motivo no es el acceso sino el detector: un pasaje o una noche de
hotel no tienen *un* precio, tienen un precio **por fecha de viaje**, así que la
serie pasa de 1-D a 2-D y el p50 de 60 días mezclaría 60 fechas de salida
distintas.

Los tours y actividades son la excepción: un transfer al aeropuerto o un tour a
los geysers tiene **precio por producto y sin fecha dentro del precio**, igual que
un televisor. Por eso esta tienda entra con el detector tal como está, y por eso
se empieza por tours y no por los packs de Cocha o Travel Security — un pack con
salida fija **desaparece del catálogo cuando se agota o cuando pasa la fecha**, y
su vida puede ser más corta que `MIN_DAYS`.

EL PAYLOAD ES JSON-LD, NO UN GRID
---------------------------------

La página de destino (`/san-pedro-de-atacama`) trae el catálogo completo en el
`__NEXT_DATA__` como `schema.org`: un `ItemList` cuyos `itemListElement[].item`
son `Product` con `name`, `url`, `image`, `sku` y un `offers` con `price`,
`priceCurrency` y `availability`. Es más estable que cualquier parseo posicional
de HTML de los que ya tiene el repo.

Dos cosas que eso regala y que casi ninguna tienda conectada tiene:

- **El total declarado está en el payload** (`ItemList.numberOfItems`) y en la
  medición del 2026-11-05 **coincide exacto** con los items servidos (43 y 43 en
  `/santiago`). De ahí sale `completeness()`, o sea el canario **exacto**.
- **`sku` viene poblado al 100%** y coincide con el `-id<N>` del final de la URL
  en los 99 productos medidos sobre tres destinos. Se usa el campo `sku`, no el
  sufijo de la URL: el slug lo puede reescribir el comerciante, el id no.

**NO PAGINA, y hay que no implementarlo.** Verificado: `?page=2` devuelve **los
mismos 43 productos** que la página 1. Es la misma trampa que el SSR de Paris
—que ignora los parámetros de paginación— y un adaptador que "pagine" acá
recolectaría el mismo producto N veces, haciéndolo pesar N veces en su propio p50.
Un request por destino trae el destino entero.

⚠️ ESTA TIENDA ES MULTI-MONEDA, Y LA MONEDA ES DEL PRODUCTO
-----------------------------------------------------------

Medido el 2026-11-05 sobre **los 160 destinos**: 9 monedas conviven —USD 408,
**CLP 282**, EUR 260, PEN 136, COP 119, BRL 110, ARS 62, MXN 51, GBP 12—. Y no
alcanza con elegir destinos chilenos:

- `madrid` y `roma` cotizan en **CLP** (se venden al viajero chileno),
- `bariloche` sirve **USD y ARS en la misma página** (10 y 9 ofertas),
- `cancun` mezcla **USD y MXN**, `roma` mezcla **EUR, CLP y USD**.

O sea no existe "la moneda de la tienda" ni "la moneda del destino": **la moneda
es del producto**. Por eso el filtro es por oferta (`MONEDA`) y no una lista de
`store_key` elegida a mano — una llave que de golpe empieza a servir EUR
envenenaría las series de ese destino **sin un solo error**.

Hoy se ingiere **solo CLP**, y es una limitación del esquema y no de la tienda:
`RawProduct` no tiene campo de moneda y su `__post_init__` valida contra
`MAX_PLAUSIBLE_CLP`, así que un `USD 229` pasaría el techo y quedaría guardado
como si fueran 229 pesos. El dueño decidió el 2026-11-05 que USD y EUR también
sirven; habilitarlos es trabajo de esquema (columna de moneda en el listing,
techo de plausibilidad por moneda y símbolo en el copy) y está acotado en
`INVESTIGACION_viajes.md` §2.bis. **Lo que sigue prohibido es convertir**: si el
precio se pasa a CLP cada día, el p50 de 60 días mezcla 60 tipos de cambio y
`discount_real` empieza a medir el dólar en vez de la oferta.
"""
from __future__ import annotations

import json
import logging
import re
from collections.abc import AsyncIterator, Sequence
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from catalog.normalize import clean_text
from scrapers.base import MAX_PLAUSIBLE_CLP, CategoryRef, RawProduct
from scrapers.http import DEFAULT_USER_AGENT, HttpClient

logger = logging.getLogger(__name__)

SITE_BASE = "https://www.nomades.com"

#: Única moneda que el pipeline sabe guardar hoy. Ver el docstring del módulo.
MONEDA = "CLP"

_NEXT_DATA = re.compile(
    r'<script[^>]+id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.S
)


class NotAListingPage(RuntimeError):
    """El `store_key` no devolvió un destino con productos.

    Se distingue de un destino legítimamente vacío igual que en el resto del
    repo: si el payload no trae `__NEXT_DATA__` o no trae un solo `Product`, el
    `store_key` está mal escrito y tiene que ser ruidoso.
    """


def _parse_precio(raw: Any) -> Decimal | None:
    """Precio de schema.org a entero, descartando el que trae decimales.

    En CLP no hay centavos, así que el precio llega como `17000`. La guarda
    existe para las otras monedas: sobre 144 ofertas de 8 monedas, **143 eran
    enteras y una vino `37.5` (EUR)**. Se descarta en vez de adivinar la escala,
    que es la misma decisión que `shopify_family.parse_price` — un `189.90`
    truncado a `18990` es un error de 100× que nadie nota hasta ver una oferta
    imposible.
    """
    if raw is None:
        return None
    if isinstance(raw, bool):
        return None
    if isinstance(raw, float) and raw != int(raw):
        logger.debug("nomades_precio_con_decimales valor=%r", raw)
        return None
    texto = str(raw).strip()
    if "," in texto:
        return None
    if "." in texto:
        entero, _, resto = texto.partition(".")
        if resto.strip("0"):
            logger.debug("nomades_precio_con_decimales valor=%r", texto)
            return None
        texto = entero
    if not texto.lstrip("-").isdigit():
        return None
    precio = Decimal(texto)
    return precio if precio > 0 else None


def _productos_del_payload(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Todos los nodos `@type: Product` del `__NEXT_DATA__`.

    Se recorre el árbol completo en vez de indexar
    `props.pageProps.schema["@graph"][2].itemListElement` porque esa ruta es una
    posición y las posiciones se mueven: el día que la tienda agregue un bloque
    al `@graph`, un índice fijo devolvería otra cosa **con HTTP 200**.
    """
    encontrados: list[dict[str, Any]] = []

    def recorrer(nodo: Any) -> None:
        if isinstance(nodo, dict):
            if nodo.get("@type") == "Product":
                encontrados.append(nodo)
            for valor in nodo.values():
                recorrer(valor)
        elif isinstance(nodo, list):
            for valor in nodo:
                recorrer(valor)

    recorrer(payload)
    return encontrados


def _total_declarado(payload: dict[str, Any]) -> int | None:
    """`ItemList.numberOfItems`, la fuente del canario exacto."""
    encontrado: list[int] = []

    def recorrer(nodo: Any) -> None:
        if isinstance(nodo, dict):
            n = nodo.get("numberOfItems")
            if isinstance(n, int):
                encontrado.append(n)
            for valor in nodo.values():
                recorrer(valor)
        elif isinstance(nodo, list):
            for valor in nodo:
                recorrer(valor)

    recorrer(payload)
    return max(encontrado) if encontrado else None


def _imagen(producto: dict[str, Any]) -> str | None:
    img = producto.get("image")
    if isinstance(img, str):
        return img
    if isinstance(img, list):
        for x in img:
            if isinstance(x, str) and x:
                return x
    return None


def parse_listing(
    html: str,
    *,
    store_slug: str,
    category: CategoryRef,
    scraped_at: datetime,
    moneda: str = MONEDA,
) -> tuple[list[RawProduct], int, int | None]:
    """Convierte una página de destino en productos.

    Devuelve `(productos, enumerados, declarado)`. `enumerados` son los nodos
    `Product` del payload y no los emitidos: un producto descartado por moneda o
    por precio es una decisión nuestra, no un producto que la tienda no sirvió, y
    mezclarlos volvería heurística la guarda exacta de `completeness()`.
    """
    m = _NEXT_DATA.search(html)
    if m is None:
        raise NotAListingPage(
            f"{store_slug}/{category.slug}: store_key={category.store_key!r} "
            "no devolvió __NEXT_DATA__"
        )
    try:
        payload = json.loads(m.group(1))
    except json.JSONDecodeError as exc:
        raise NotAListingPage(
            f"{store_slug}/{category.slug}: __NEXT_DATA__ ilegible: {exc}"
        ) from exc

    crudos = _productos_del_payload(payload)
    if not crudos:
        raise NotAListingPage(
            f"{store_slug}/{category.slug}: store_key={category.store_key!r} "
            "no trae ningún Product"
        )

    productos: list[RawProduct] = []
    for crudo in crudos:
        sku = crudo.get("sku")
        name = clean_text(crudo.get("name"))
        url = crudo.get("url")
        if sku is None or not name or not url:
            logger.debug("nomades_producto_incompleto sku=%r", sku)
            continue

        oferta = crudo.get("offers")
        if isinstance(oferta, list):
            oferta = oferta[0] if oferta else None
        if not isinstance(oferta, dict):
            logger.debug("nomades_sin_oferta sku=%r", sku)
            continue

        if oferta.get("priceCurrency") != moneda:
            # No es un error: la tienda vende en 9 monedas y el pipeline sabe
            # guardar una. Ver el docstring del módulo.
            logger.debug(
                "nomades_otra_moneda sku=%s moneda=%r", sku, oferta.get("priceCurrency")
            )
            continue

        precio = _parse_precio(oferta.get("price"))
        if precio is None:
            logger.debug("nomades_sin_precio sku=%s valor=%r", sku, oferta.get("price"))
            continue
        if precio > MAX_PLAUSIBLE_CLP:
            logger.debug("nomades_precio_centinela sku=%s valor=%s", sku, precio)
            continue

        disponible = str(oferta.get("availability") or "").rsplit("/", 1)[-1]
        productos.append(
            RawProduct(
                store_slug=store_slug,
                # El campo `sku`, no el sufijo `-id<N>` de la URL: coinciden en
                # los 99 productos medidos, pero el slug lo reescribe el
                # comerciante y el id no.
                store_sku=str(sku),
                url=url,
                name=name,
                price_effective=precio,
                # La agencia no declara un "antes" tachado en el listado, así
                # que θ de esta categoría se hereda y no se mide.
                price_normal=None,
                price_card=None,
                # `brand` es siempre "Nomades", o sea la propia agencia: es el
                # caso `non_brand_vendors` de Shopify. Una marca que es la tienda
                # degrada el copy sin aportar identidad.
                brand=None,
                model=None,
                gtin=None,
                category_path=category.slug,
                image_url=_imagen(crudo),
                claimed_discount=None,
                # ⚠️ En los 120 productos de la muestra `availability` dio
                # `InStock` el 100%, así que probablemente es una constante y no
                # una señal — el caso de Colloky, donde el agotado desaparece del
                # listado en vez de marcarse. Se lee igual porque no cuesta nada;
                # no construir una guarda sobre esto sin verlo dar `OutOfStock`.
                in_stock=disponible != "OutOfStock",
                scraped_at=scraped_at,
                raw_payload={"sku": sku, "availability": disponible},
            )
        )

    return productos, len(crudos), _total_declarado(payload)


class NomadesAdapter:
    """`store_key` = el slug del destino (`san-pedro-de-atacama`, `pucon`).

    `robots.txt` es permisivo —33 `Disallow`, todos de pago y reserva
    (`/webpay/*/*`, `/paypal/*/*`, `/bookings/complete-information/*`,
    `/cotizacion/*`); nada que toque las páginas de destino— y **no declara
    `Crawl-delay`**, así que rige el default conservador del repo.

    ⚠️ **El host canónico es `nomades.com`.** `denomades.com` redirige ahí, y su
    `robots.txt` y su sitemap apuntan al primero: usar el viejo es recolectar
    contra una redirección.

    ⚠️ **Solo las rutas sin prefijo de idioma.** El sitemap trae cada destino tres
    veces (`/santiago`, `/en/santiago`, `/pt/santiago`): es el mismo catálogo
    traducido, y conectar los tres haría pesar el triple a cada listing en su
    propio p50.
    """

    slug = "nomades"
    rate_limit_rps = 0.5
    base_url = SITE_BASE

    def __init__(self, http: HttpClient, categories: Sequence[CategoryRef]) -> None:
        self._http = http
        self._categories = tuple(categories)
        self._completeness: dict[str, tuple[int, int]] = {}

    def categories(self) -> Sequence[CategoryRef]:
        return self._categories

    def completeness(self, category: CategoryRef) -> tuple[int, int] | None:
        """Canario exacto: `ItemList.numberOfItems` contra lo enumerado."""
        return self._completeness.get(category.store_key)

    def headers(self) -> dict[str, str] | None:
        """El UA identificable alcanza: 160 destinos sin un 403 ni un 429."""
        return {"User-Agent": DEFAULT_USER_AGENT}

    async def discover(self, category: CategoryRef) -> AsyncIterator[RawProduct]:
        self._completeness.pop(category.store_key, None)
        html = await self._http.get_text(
            f"{self.base_url}/{category.store_key.strip('/')}",
            rps=self.rate_limit_rps,
            headers=self.headers(),
        )
        productos, enumerados, declarado = parse_listing(
            html,
            store_slug=self.slug,
            category=category,
            scraped_at=datetime.now(timezone.utc),
        )
        if declarado is not None:
            self._completeness[category.store_key] = (enumerados, declarado)
        for producto in productos:
            yield producto
