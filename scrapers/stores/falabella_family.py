"""Adaptadores de Falabella y Sodimac.

Las dos tiendas corren sobre el mismo frontend (`falabella-b2c-ui`) y devuelven
un `__NEXT_DATA__` con la MISMA forma, verificado contra ambas: el listado viene
renderizado server-side en `props.pageProps.results`, con `pagination` al lado.
Por eso comparten parser y solo se diferencian en host y prefijo de path.

No se usa el BFF interno (`/s/browse/v1/listing/cl`): existe y responde, pero
exige `pgid`, `pid` (uuid de ubicación) y la lista completa de `zones`, que son
efímeros y se obtienen... del mismo HTML. Parsear el SSR es más simple y menos
frágil que sostener esos tres parámetros.
"""
from __future__ import annotations

import json
import logging
import re
from collections.abc import AsyncIterator, Sequence
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from catalog.normalize import clean_text, normalize_brand, parse_clp
from scrapers.base import (
    MAX_PLAUSIBLE_CLP,
    PUM_LABEL_MAX_CHARS,
    CategoryRef,
    Pum,
    RawProduct,
)
from scrapers.http import BROWSER_HEADERS, HttpClient

logger = logging.getLogger(__name__)

_NEXT_DATA = re.compile(
    r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', re.S
)

#: Productos por página que sirve esta familia. Solo es el respaldo para calcular
#: la ventana: el valor real viene en `pagination.perPage` de cada respuesta.
PAGE_SIZE = 48

#: Precio con tarjeta propia de la casa. Requiere plástico → NO es el precio que
#: paga cualquiera, así que queda fuera del detector (se guarda para mostrarlo).
_CARD_PRICE_TYPES = frozenset({"cmrPrice"})
#: El "antes" tachado que declara la tienda. Es exactamente el número que se
#: infla, así que se guarda como evidencia y nunca alimenta el descuento.
_CLAIMED_NORMAL_TYPES = frozenset({"normalPrice"})


class NextDataMissing(RuntimeError):
    """El HTML no trae `__NEXT_DATA__` — la tienda cambió el frontend."""


class NotAListingPage(RuntimeError):
    """La respuesta no trae `results`: no es una página de listado.

    Ocurre en dos situaciones que el llamador debe distinguir por número de página:

    - **página 1** → el `store_key` está mal (par id/nombre incongruente), la
      tienda sirvió una landing. Es un error de configuración y debe ser ruidoso.
    - **página > 1** → se pasó del final del catálogo. Falabella y Sodimac no
      devuelven una lista vacía ahí: devuelven un shell sin la clave `results`.
      Es el fin normal de la paginación.

    `discover()` hace esa distinción; el parser solo reporta el hecho.
    """


def extract_next_data(html: str) -> dict[str, Any]:
    match = _NEXT_DATA.search(html)
    if match is None:
        raise NextDataMissing("no se encontró el bloque __NEXT_DATA__")
    return json.loads(match.group(1))


def _entry_price(entry: dict[str, Any]) -> Decimal | None:
    """El precio de una entrada de `prices`. La tienda lo manda en una lista."""
    raw = entry.get("price")
    return parse_clp(raw[0] if isinstance(raw, list) and raw else raw)


def resolve_pum(entry: dict[str, Any]) -> Pum | None:
    """El precio por unidad de medida de UNA entrada de `prices`, si lo trae.

    Nunca lanza: el `pum` es un dato opcional del copy, así que una etiqueta rara
    o un número ilegible lo descartan en silencio en vez de voltear la categoría
    entera. Por eso valida las precondiciones acá y recién después construye el
    `Pum`, que sí es estricto.
    """
    pum = entry.get("pum")
    if not isinstance(pum, dict):
        return None
    label = clean_text(pum.get("label"))
    price = _entry_price(pum)
    if not label or price is None or len(label) > PUM_LABEL_MAX_CHARS:
        logger.debug("pum_ilegible label=%r price=%r", pum.get("label"), pum.get("price"))
        return None
    return Pum(label=label, price=price)


def resolve_prices(
    prices: Sequence[dict[str, Any]],
) -> tuple[Decimal | None, Decimal | None, Decimal | None, Pum | None]:
    """Reparte los precios en (efectivo, normal declarado, tarjeta, pum).

    Tipos observados en producción: `cmrPrice`, `internetPrice`, `eventPrice`,
    `normalPrice`. El efectivo es el MÍNIMO de los precios pagables sin tarjeta
    de la casa y no tachados; si no hay ninguno, cae al normal no tachado.

    El `pum` **cuelga de una entrada concreta**, así que se devuelve el de la
    entrada que ganó el precio efectivo y no el primero que aparezca: el del
    `normalPrice` tachado sería el precio por kilo de un precio que ya no existe,
    y el del `cmrPrice` el de un precio que exige tarjeta de la casa.
    """
    card: Decimal | None = None
    claimed_normal: Decimal | None = None
    payable: list[tuple[Decimal, Pum | None]] = []
    fallback: list[tuple[Decimal, Pum | None]] = []

    for entry in prices:
        value = _entry_price(entry)
        if value is None:
            continue

        price_type = entry.get("type") or ""
        if price_type in _CARD_PRICE_TYPES:
            card = value if card is None else min(card, value)
            continue
        if price_type in _CLAIMED_NORMAL_TYPES:
            claimed_normal = value if claimed_normal is None else min(claimed_normal, value)
            # Un normalPrice sin tachar es el precio vigente (no hay oferta).
            if not entry.get("crossed"):
                fallback.append((value, resolve_pum(entry)))
            continue
        if not entry.get("crossed"):
            payable.append((value, resolve_pum(entry)))

    winners = payable or fallback
    if not winners:
        return None, claimed_normal, card, None
    # `key` explícito: dos entradas al mismo precio harían comparar los `Pum`,
    # que no son ordenables.
    effective, pum = min(winners, key=lambda w: w[0])
    return effective, claimed_normal, card, pum


def parse_listing(
    html: str, *, store_slug: str, category: CategoryRef, scraped_at: datetime
) -> tuple[list[RawProduct], dict[str, Any]]:
    """Extrae los productos de una página de listado y su bloque de paginación."""
    page_props = extract_next_data(html)["props"]["pageProps"]
    if "results" not in page_props:
        raise NotAListingPage(
            f"{store_slug}/{category.slug}: store_key={category.store_key!r} no es una "
            f"categoría hoja (claves: {sorted(page_props)[:8]})"
        )
    results = page_props.get("results") or []
    pagination = page_props.get("pagination") or {}

    products: list[RawProduct] = []
    for item in results:
        sku = item.get("skuId") or item.get("productId")
        url = item.get("url")
        name = clean_text(item.get("displayName"))
        if not (sku and url and name):
            continue

        effective, claimed_normal, card, pum = resolve_prices(item.get("prices") or [])
        if effective is None:
            # Sin precio pagable no hay serie que construir; se descarta en vez
            # de inventar un cero que ensucie la baseline.
            logger.debug("sin_precio store=%s sku=%s", store_slug, sku)
            continue
        if effective > MAX_PLAUSIBLE_CLP:
            # Centinela de la tienda ($99.999.999.999) para productos sin precio
            # real. Se descarta acá, no en RawProduct, para que un placeholder no
            # aborte la pasada completa de la categoría.
            logger.debug(
                "precio_centinela store=%s sku=%s valor=%s", store_slug, sku, effective
            )
            continue

        media = item.get("mediaUrls") or []
        badge = item.get("discountBadge") or {}

        products.append(
            RawProduct(
                store_slug=store_slug,
                store_sku=str(sku),
                url=url,
                name=name,
                price_effective=effective,
                price_normal=claimed_normal,
                price_card=card,
                brand=normalize_brand(item.get("brand")),
                category_path=category.slug,
                image_url=media[0] if media else None,
                claimed_discount=clean_text(badge.get("label")),
                pum=pum,
                in_stock=True,  # el listado solo devuelve comprables
                scraped_at=scraped_at,
                raw_payload=item,
            )
        )

    return products, pagination


class _FalabellaFamilyAdapter:
    """Base compartida. Las subclases solo fijan slug, host y path."""

    slug: str = ""
    rate_limit_rps: float = 0.5
    base_url: str = ""
    #: Prefijo del listado por categoría. `store_key` es el resto del path
    #: (`cat70057/Notebooks`), así que NO se url-encodea: lleva `/` significativo.
    listing_path: str = ""
    #: Páginas máximas por llave. 55 × 48 = 2.640 productos.
    #:
    #: Eran 20 (960) y eso recortaba el catálogo **en silencio** — ver
    #: `completeness`. Con 55 entran completas las llaves medianas, que son las que
    #: producen la baseline del sistema hoy:
    #:
    #:     cat70057/Notebooks     1.243 → 26 páginas ✓
    #:     cat720161/Smartphones  2.022 → 43 páginas ✓
    #:     cat690245/Botines      2.545 → 54 páginas ✓
    #:     cat7190148/Smart-TV      324 →  7 páginas ✓
    #:
    #: Las tres gigantes siguen sin entrar (Zapatillas 18.412 pediría 384 páginas,
    #: Refrigeradores 13.754 → 287, Audífonos 8.485 → 177) pero pasan de ver 960 a
    #: ver 2.640. Cubrirlas enteras costaría ~850 requests por pasada para tres
    #: llaves, contra las ~440 que hoy cuesta Falabella completa.
    max_pages: int = 55
    #: Headers por request. `None` = los del `HttpClient`, que se identifican como
    #: bot. Una tienda cuyo borde exige parecer un navegador lo sobreescribe (ver
    #: `TottusAdapter`).
    _headers: dict[str, str] | None = None

    def __init__(self, http: HttpClient, categories: Sequence[CategoryRef]) -> None:
        self._http = http
        self._categories = tuple(categories)

    def categories(self) -> Sequence[CategoryRef]:
        return self._categories

    def completeness(self, category: CategoryRef) -> tuple[int, int] | None:
        """Siempre `None`: esta familia NO puede sostener un canario exacto.

        Lo intenté el 2026-10-12 y hay que dejar escrito por qué no va, porque la
        idea es tentadora: `pagination.count` trae el total declarado en cada
        página, así que parece gratis.

        **El problema es que Falabella repite productos cuanto más profundo se
        pagina**, así que lo enumerado nunca alcanza lo declarado y el gap es
        función de la profundidad, no de un incidente. Medido llave por llave
        contra producción:

            Lavadoras              5 págs    204 de  204   100%   ok
            Microondas             4 págs    174 de  175  99,4%
            Refrigeradores         8 págs    351 de  352  99,7%
            Tarjetas-de-Memoria   15 págs    614 de  697    88%
            Notebooks             26 págs  1.047 de 1244    84%
            Almacenamiento        37 págs  1.351 de 1750    77%
            Smartphones           43 págs  1.675 de 2019    83%

        Con el canario exacto encendido, **diecinueve llaves quedarían en `partial`
        permanente** — incluida Refrigeradores, que saltaría por UN producto de 352.
        Una alarma que suena siempre es una alarma apagada: es el mismo error que
        las corridas manuales ensuciando la guarda de volumen, y ponerle una
        tolerancia sería inventar un umbral, que es justo lo que CLAUDE.md prohíbe
        para el chequeo exacto de Andesgear.

        Lo que sí quedó de ese intento es lo que de verdad hacía falta: el aviso
        `catalogo_mas_grande_que_la_ventana` cuando `max_pages` recorta —el problema
        real, que estuvo tapado diez días— y el canario **estadístico**, que compara
        cada llave contra su propia historia y por lo tanto no le molesta un gap
        constante. Para el recorte no hace falta un canario: hace falta saber el
        total, y eso ahora se loguea.
        """
        return None

    def _page_url(self, category: CategoryRef, page: int) -> str:
        return f"{self.base_url}{self.listing_path}/{category.store_key}?page={page}"

    async def discover(self, category: CategoryRef) -> AsyncIterator[RawProduct]:
        seen: set[str] = set()
        declarado: int | None = None
        page = 1

        while page <= self.max_pages:
            url = self._page_url(category, page)
            html = await self._http.get_text(
                url, rps=self.rate_limit_rps, headers=self._headers
            )
            scraped_at = datetime.now(timezone.utc)
            try:
                products, pagination = parse_listing(
                    html, store_slug=self.slug, category=category, scraped_at=scraped_at
                )
            except NotAListingPage:
                if page == 1:
                    # El store_key está mal configurado: no hay nada que salvar.
                    raise
                # Fin del catálogo: pasada la última página, la tienda devuelve un
                # shell sin `results` en vez de una lista vacía.
                logger.debug(
                    "fin_de_catalogo store=%s categoria=%s pagina=%d",
                    self.slug,
                    category.slug,
                    page,
                )
                break

            if not products:
                break

            # Guarda de paginación honesta: si la tienda nos devuelve una página
            # distinta de la pedida, está ignorando el parámetro (Sodimac lo hacía
            # al 301-redirigir /search y perder el query string). Seguir pidiendo
            # páginas sería releer la misma una y otra vez.
            served = pagination.get("currentPage")
            if served is not None and int(served) != page:
                logger.warning(
                    "paginacion_ignorada store=%s categoria=%s pedida=%d servida=%s",
                    self.slug,
                    category.slug,
                    page,
                    served,
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

            # La paginación de Falabella repite resultados cuando se pasa del
            # final; sin SKUs nuevos, se corta aunque `count` prometa más.
            if fresh == 0:
                break

            total = pagination.get("count") or 0
            if total:
                declarado = int(total)
            if len(seen) >= total:
                break
            page += 1

        if declarado is not None:
            alcanzable = self.max_pages * (pagination.get("perPage") or PAGE_SIZE)
            if declarado > alcanzable:
                # El catálogo excede lo que decidimos enumerar, así que NO se
                # reporta completitud: el runner cae al canario estadístico.
                #
                # Reportar `(2.640, 18.412)` dejaría estas tres llaves en `partial`
                # permanente, y una alarma que siempre suena es una alarma apagada
                # —el mismo error que las corridas manuales ensuciando la guarda de
                # volumen—. Degradar a la guarda más débil es correcto; inventar un
                # total alcanzable y llamarlo "completo" sería mentir. El hecho
                # queda en el log, que es donde se mira a propósito.
                logger.warning(
                    "catalogo_mas_grande_que_la_ventana store=%s categoria=%s "
                    "llave=%s enumerados=%d declarados=%d ventana=%d — sin canario "
                    "exacto para esta llave",
                    self.slug,
                    category.slug,
                    category.store_key,
                    len(seen),
                    declarado,
                    alcanzable,
                )


class FalabellaAdapter(_FalabellaFamilyAdapter):
    """`store_key` = path de categoría, p. ej. `cat70057/Notebooks`.

    Se navega por categoría y NO por término de búsqueda. El buscador funciona y
    pagina bien, pero su resultado es difuso: "celular" devolvía ~940 items con
    accesorios, fundas y televisores mezclados. Como el umbral de descuento del
    detector se aplica **por categoría**, un SKU mal clasificado recibe el umbral
    equivocado y se convierte en un falso positivo o en una oferta que nunca se
    publica. El path de categoría es la clasificación de la propia tienda.

    El `store_key` debe ser el par id/nombre EXACTO que publica la tienda. Si el
    nombre no corresponde al id (`cat7090034/Notebooks`), Falabella redirige a una
    landing de CMS cuyo `__NEXT_DATA__` trae `containers` y no `results` — de ahí
    `NotAListingPage`.

    Se usan categorías hoja. Las de nivel alto son listados válidos pero inútiles
    para el detector: `cat7090034/Tecnologia` devuelve 201.124 productos bajo un
    solo umbral de descuento, que es justamente lo que se quiere evitar.
    """

    slug = "falabella"
    base_url = "https://www.falabella.com"
    listing_path = "/falabella-cl/category"


class SodimacAdapter(_FalabellaFamilyAdapter):
    """`store_key` = path de categoría, p. ej. `cat14080023/Taladros`.

    Además de la razón de clasificación que aplica a toda la familia, en Sodimac
    el buscador directamente no es una opción: `/sodimac-cl/search?Ntt=...`
    responde 301 hacia la categoría equivalente y **descarta el query string**,
    con lo que `page` se pierde y toda pasada devuelve la página 1.
    """

    slug = "sodimac"
    base_url = "https://www.sodimac.cl"
    listing_path = "/sodimac-cl/lista"


class TottusAdapter(_FalabellaFamilyAdapter):
    """El supermercado del grupo Falabella. `store_key` = `CATG27055/Despensa`.

    **No es VTEX, y eso costó un descarte equivocado.** El plan la tenía como
    "borde abierto, origen roto" porque su API de catálogo VTEX contesta 503 y las
    rutas inventadas 526. Las dos cosas son ciertas y ninguna es un problema:
    Tottus corre la plataforma de Falabella (`__NEXT_DATA__`, 641 menciones de
    `falabella` en su home), así que **nunca tuvo una API VTEX** — el 503 es lo
    que devuelve un upstream al que se le pide una ruta que no existe. Verificado
    el 2026-10-01: con el `store_key` real da HTTP 200 y `parse_listing` lo
    entiende sin una línea nueva.

    Y el 200 de la home tampoco probaba nada: venía con `cf-cache-status: HIT` y
    `age: 2381`, o sea de la cache de Cloudflare, no del origen.

    **Exige el juego COMPLETO de headers de navegador**, no solo el User-Agent.
    Aislado el 2026-10-01, 3 intentos de cada uno contra la misma URL:

        DEFAULT_USER_AGENT      403 ×3
        BROWSER_USER_AGENT      403 ×3   ← el UA solo NO alcanza
        BROWSER_HEADERS         200 ×3

    Es el caso que `http.BROWSER_HEADERS` documenta —lo que delata al cliente es
    la ausencia de `Accept-Language`, `Accept-Encoding` y `Sec-Fetch-*`— y la
    diferencia con Prat, donde el UA de navegador bastaba.

    Su paraguas más grande, Despensa, declara 2.060 productos = 43 páginas, así que
    entra en el `max_pages = 55` que la familia trae por defecto desde el
    2026-10-12. Antes tenía un override de 45 por la misma razón, hoy redundante.

    ⚠️ **`in_stock` es ciego acá, igual que en Falabella y Paris.** Su
    `availability` no habla de stock sino de modos de envío (`expressShipping`,
    `pickUpFromStoreShipping`), así que no sirve para la guarda del detector.
    """

    slug = "tottus"
    base_url = "https://www.tottus.cl"
    listing_path = "/tottus-cl/lista"
    #: Sin esto, HTTP 403 en todas las páginas. Ver el docstring.
    _headers = BROWSER_HEADERS

    #: Orden explícito por precio ascendente, y es lo que hace confiable su serie.
    #:
    #: Su default es `_score,desc` ("Recomendados"), un ranking de relevancia con
    #: boost de publicidad que **cambia entre requests**: paginarlo devuelve
    #: productos repetidos en el medio del catálogo y deja otros sin ver nunca.
    #: Medido el 2026-10-01 sobre `Mascotas` (427 declarados, 9 páginas), tres
    #: recorridos completos:
    #:
    #:     sin sortBy          435 filas → 389 únicos   cobertura 0,911
    #:     _score,desc         435 filas → 389 únicos   cobertura 0,911
    #:     currentPrice,asc    427 filas → 422 únicos   cobertura 0,988
    #:
    #: El perfil por página lo explica: con el orden por precio cada página aporta
    #: casi 48 nuevos (48, 45, 48, 48, 48, 46, 48, 48, 43), con el default las
    #: páginas 5 a 8 aportan 40, 46, 40 y 28. Y el default no es estable ni entre
    #: corridas: dos recorridos del mismo día dieron 326 y 389 únicos.
    #:
    #: Lo que se gana no es cobertura por la cobertura: un SKU que aparece de
    #: forma intermitente no acumula observaciones y nunca llega a `MIN_DAYS`, así
    #: que con el orden inestable una fracción del catálogo jamás produce una
    #: baseline. El precio tampoco es perfectamente estable —cambia dos veces al
    #: día y mueve productos de página— pero es dos órdenes más estable que un
    #: score de relevancia, y los números lo confirman.
    SORT_BY = "derived.currentPrice%2Casc"

    def _page_url(self, category: CategoryRef, page: int) -> str:
        return f"{super()._page_url(category, page)}&sortBy={self.SORT_BY}"
