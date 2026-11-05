"""Adaptadores de los supermercados de Cencosud: Jumbo y Santa Isabel.

Las dos tiendas corren el **mismo front** —Next.js con App Router sobre un
backend VTEX— servido desde el mismo código: el `sitemap.xml` de Santa Isabel
todavía lista `/compromisos-jumbo` y `/jumbo-ofertas`. Por eso comparten
adaptador y solo se diferencian en el host, el slug y sus llaves.

DE DÓNDE SALE EL LISTADO, Y DE DÓNDE NO
--------------------------------------------------------------------------------
Del **JSON-LD `ItemList`** que la página trae renderizada server-side: 40
productos por página con `name`, `url`, `image`, `brand`, `offers.price` y
`offers.availability`.

Las otras dos vías se descartaron con motivo:

- **La API pública de VTEX contesta 404** en las dos tiendas (medido el
  2026-10-19, PLAN_SUPERMERCADO §4). Y el `robots.txt` de Santa Isabel prohíbe
  `/api/` explícitamente, así que tampoco se buscó una ruta alternativa.
- **El payload RSC de la página trae MÁS datos y no se toca.** Ahí viven, por
  producto, `listPrice` (el "antes" tachado), `stock`, y —lo que más dolería
  perder— `ppumPrice` + `ppumMeasurementUnit`, o sea **el precio por unidad de
  medida** que PLAN_SUPERMERCADO §2bis convirtió en el argumento central del
  copy de supermercado. No se lee porque es el formato de flight de React:
  JSON escapado dentro de strings, con referencias (`$L1ce`), back-references
  (`$16c:props:children:props:products:0:categoryNames`) y centinelas
  (`$undefined`). Es el mismo criterio que ya aplicó el adaptador de Kruuse al
  elegir su feed por sobre el RSC de sus categorías. **Que el `pum` de estas dos
  tiendas sea alcanzable a ese precio es una decisión de producto, no una tarea
  pendiente**: hoy sus ofertas saldrían sin la línea del precio por kilo, como
  salen las 8 de 24 de Tottus que no tienen unidad de medida.

LO QUE SÍ PAGINA, CONTRA LO QUE DECÍA EL PLAN
--------------------------------------------------------------------------------
⚠️ PLAN_SUPERMERCADO §4 concluyó que **no paginan** —"probadas ocho variantes,
las ocho devuelven los mismos 40 primeros"— y de ahí salía una estrategia de
hojas elegidas a mano de ≤40 productos. **Está medido que sí paginan**, el
2026-11-04, con `?page=N`:

    jumbo/lacteos-huevos-y-congelados/leches   8 págs   7×40+18 = 298 = declarado
    jumbo/despensa                            83 págs  82×40+19 = 3.299 = declarado
    santaisabel/limpieza                      19 págs            724 = declarado

y la página siguiente a la última contesta **HTTP 404**, igual que Easy. No hay
tope de paginación profunda: la 83 de `despensa` sirve sus 19 productos finales.

Ese total declarado NO alcanza para un canario exacto, aunque las tres líneas de
arriba lo sugieran: sobre las diez llaves conectadas, siete quedan entre 1 y 10
ítems cortas y la misma llave da ratio 1,0000 en un recorrido y 0,9988 en el
siguiente. La medición y la decisión están en el docstring de `completeness`.

Qué cambió entre una medición y la otra: la tienda **reorganizó su taxonomía** y
las URLs del plan ahora responden 301 (`/lacteos-y-quesos/leches` →
`/lacteos-huevos-y-congelados/leches`). La redirección conserva el query string
—verificado—, así que no es la explicación; lo que importa es que hoy pagina y
que el sitemap quedó viejo.

⚠️ **Y la taxonomía vieja es una trampa de solapamiento**: `desayuno` y
`congelados` ya no existen y redirigen a `/despensa` y a
`/lacteos-huevos-y-congelados`. Dos `store_key` distintos que caen en el mismo
destino escriben dos `price_points` del mismo listing por pasada y lo hacen
pesar el doble en su propio p50. Las llaves tienen que ser los paths VIGENTES,
leídos de la navegación de la tienda y no de su sitemap.

POR QUÉ ESTE ADAPTADOR DEDUPLICA EN LA PASADA ENTERA
--------------------------------------------------------------------------------
Por dos solapamientos distintos, los dos medidos:

1. **El bloque patrocinado se sirve además de su posición natural.** La página 1
   de `leches` abre con 4 productos que el payload RSC marca `"Patrocinado"` y
   que vuelven a aparecer más adelante en el recorrido: 298 filas → 294 únicos.
   En `jumbo/mascotas`, 848 filas → 846 únicos.
2. **Dos departamentos cross-listan el mismo SKU.** Medido sobre 800 SKUs de las
   cinco llaves de Jumbo: `despensa` ∩ `chocolates-galletas-y-snacks` = 2
   (galletas Club Social y un pack Colac). Las otras nueve combinaciones son
   disjuntas, y las cinco de Santa Isabel lo son entre sí sobre 760 SKUs.

Es el caso de `AndesgearAdapter`, con su misma advertencia: deduplicar entre
llaves es inocuo **solo mientras las llaves que se solapan mapeen a la misma
categoría interna**, porque el SKU se emite una vez y la llave que gana es la
primera del orden de `db.load_store_targets` (`store_slug, category_slug,
store_key`). Hoy las diez llaves van a `supermercado` y el supuesto se cumple.
⚠️ **El día que se conecte `belleza` en estas tiendas hay que volver acá**:
`belleza` ordena antes que `supermercado`, así que un SKU que estuviera en
`limpieza` y en `belleza-y-cuidado-personal` se le asignaría a belleza y
desaparecería de la serie de supermercado.

EL STOCK ES SEÑAL DE VERDAD, Y SERÍA LA PRIMERA DEL SUPERMERCADO
--------------------------------------------------------------------------------
`in_stock` sale de `offers.availability`, y eso hace de estas dos las primeras
tiendas de supermercado del sistema con stock real en el listado: en Tottus,
Falabella y Paris se asume `True` a ciegas.

Lo que prueba que no es un adorno constante —ni la trampa del `availability` de
Tottus, que habla de modos de envío— es **dónde caen los agotados**: el orden
por defecto los manda al final. Medido sobre `jumbo/despensa` (3.299 productos,
83 páginas):

    páginas 1, 2, 20, 41    100% InStock
    páginas 81, 82, 83      100% OutOfStock  (99 productos, 3% del catálogo)

Sobre 1.560 productos de las diez llaves, 198 vienen `OutOfStock` (12,7%). Ojo
que medido **solo sobre la página 1** el número es 0,8%: es otra vez el engaño
de la página 1 que este repo ya documentó para los GTIN de Paris y para el
descuento declarado de Tottus.

**La ficha NO sirve para cruzar ese dato.** Ocho fichas abiertas a mano el
2026-11-04 —tres que el listado marcaba `OutOfStock` y cinco `InStock`—
devolvieron las ocho `schema.org/InStock` en su JSON-LD. O sea el `availability`
de la ficha parece constante y no contradice al listado: no construyas un lector
de `publisher/stock.py` sobre él.

Dos consecuencias que conviene tener claras antes de leer los indicadores:

- Un listing permanentemente agotado **no madura nunca**: `compute_baseline`
  filtra `if in_stock`, así que no tiene baseline ni `n_days`. Es el mecanismo de
  Kruuse, y es exactamente lo que `scripts.aceptacion_tienda` descuenta del
  denominador desde el 2026-11-04. Sin esa corrección, ese 3% de cola
  permanentemente agotada iría a hundir la estabilidad medida de estas dos
  tiendas.
- El agotado **se persiste igual** (viene con precio): la observación entra a
  `price_points` con `in_stock = false` y el filtro vive en la baseline, no acá.

LO QUE ESTAS TIENDAS NO DAN
--------------------------------------------------------------------------------
- **GTIN: ninguno.** Las claves del item son `@type, brand, image, name, offers,
  url` y nada más. No desbloquean el cross-store, que hoy da cero mensajes.
- **`price_normal`: tampoco.** `offers` trae un solo precio, así que no hay
  "antes" declarado que contrastar. Es el caso de Nike: el θ de sus categorías no
  se puede fijar midiendo cuánto declara la tienda, porque no declara nada. El
  lateral bueno es el mismo — acá no hay número de la tienda que inflar, el
  descuento sale entero de nuestra baseline.
"""
from __future__ import annotations

import json
import logging
import re
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any
from urllib.parse import urlsplit

from catalog.normalize import clean_text, normalize_brand
from scrapers.base import MAX_PLAUSIBLE_CLP, CategoryRef, RawProduct
from scrapers.http import FetchError, HttpClient

logger = logging.getLogger(__name__)

#: Productos por página del listado. No se puede cambiar: ninguna variante de
#: tamaño de página hace efecto (probadas en PLAN_SUPERMERCADO §4).
PAGE_SIZE = 40

_LD_BLOCK = re.compile(
    r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>', re.S
)

#: El total de la categoría, en el `<span>` que sigue al `<h1>` del título:
#: `<h1 ...>Leches</h1><span class="...">298 productos</span>`.
#:
#: Está anclado al markup y no al texto suelto a propósito: "productos" aparece
#: 98 veces en la página (el placeholder del buscador, el menú de "Productos
#: Importados", los `data-gtm-*`) y el mismo número vuelve a aparecer escapado
#: dentro del payload RSC, donde no hay `</span>` que cerrar.
_DECLARED = re.compile(r">\s*([\d.]+)\s*productos\s*</span>", re.I)

#: La primera página pasada del final contesta **HTTP 404**, igual que Easy
#: (verificado el 2026-11-04: `despensa` página 83 → 200 con 19 productos,
#: página 84 → 404). Llega como `FetchError` desde el cliente HTTP y sin este
#: guard el runner marcaría `failed` la categoría entera y perdería el lote
#: pendiente en el buffer.
_END_OF_CATALOG_STATUS = 404

_IN_STOCK = "instock"


class NotAListingPage(RuntimeError):
    """La respuesta no trae un `ItemList` en su JSON-LD: no es un listado.

    Igual que en Easy y en la familia Falabella, el significado depende de la
    página:

    - **página 1** → el `store_key` no es una categoría con productos (un path
      inexistente, o una landing de CMS como `/locales`). Error de
      configuración: ruidoso.
    - **página > 1** → se pasó del final sin el 404. No se ha observado, pero el
      guard existe porque callar un cambio de formato es peor que una categoría
      en `failed`.
    """


@dataclass(frozen=True)
class ParsedListing:
    """Lo que una página de listado aporta.

    `enumerated` cuenta **entradas del `ItemList`**, no productos emitidos: separa
    lo que la paginación devolvió de lo que nuestro parser decidió descartar. No
    alimenta un canario —ver `_CencosudSupermarketAdapter.completeness`— sino el
    log de cierre de la llave, que es donde se mira si el recorrido llegó hasta
    el final.
    """

    products: list[RawProduct]
    enumerated: int
    declared: int | None


def _clp(value: Any) -> Decimal | None:
    """El precio viene numérico y entero en CLP, sin separadores (`10990`)."""
    if value is None:
        return None
    try:
        price = Decimal(str(value))
    except (ArithmeticError, ValueError):
        return None
    return price if price > 0 else None


def extract_item_list(html: str) -> list[dict[str, Any]]:
    """Las entradas del `ItemList`, o `NotAListingPage` si no hay listado."""
    for block in _LD_BLOCK.findall(html):
        try:
            data = json.loads(block)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict) and data.get("@type") == "ItemList":
            return list(data.get("itemListElement") or [])
    raise NotAListingPage("el HTML no trae un ItemList en su JSON-LD")


def declared_total(html: str) -> int | None:
    """El total que la categoría declara, o `None` si no está.

    No decide ni el corte de la paginación ni la completitud (ver
    `_CencosudSupermarketAdapter.completeness`): su único consumidor es el aviso
    `catalogo_mas_grande_que_la_ventana`. Por eso `None` acá no rompe nada —
    simplemente no se puede avisar de un recorte, que es mejor que inventar un
    total.
    """
    match = _DECLARED.search(html)
    if match is None:
        return None
    return int(match.group(1).replace(".", ""))


def sku_from_url(url: str | None) -> str | None:
    """El slug del producto, que es su única identidad acá.

    `https://www.jumbo.cl/nido-1-800g-2074962/p` → `nido-1-800g-2074962`. El
    JSON-LD no trae ni GTIN ni el `productId` interno, así que el slug es lo
    único estable que queda; la tienda lo usa como su propia URL canónica.
    """
    if not url:
        return None
    # Sobre el PATH y no sobre la URL cruda: partir la URL entera por "/" deja
    # el host como un segmento más, y `https://www.jumbo.cl/p` devolvía
    # `www.jumbo.cl` como si fuera un SKU.
    partes = [p for p in urlsplit(url).path.split("/") if p]
    if len(partes) < 2 or partes[-1] != "p":
        return None
    return partes[-2] or None


def parse_listing(
    html: str, *, store_slug: str, category: CategoryRef, scraped_at: datetime
) -> ParsedListing:
    """Extrae los productos de una página de listado, su total y lo enumerado."""
    entradas = extract_item_list(html)
    products: list[RawProduct] = []

    for entrada in entradas:
        item = entrada.get("item") if isinstance(entrada, dict) else None
        if not isinstance(item, dict):
            continue

        sku = sku_from_url(item.get("url"))
        name = clean_text(item.get("name"))
        offers = item.get("offers") or {}
        if not (sku and name):
            continue

        effective = _clp(offers.get("price"))
        if effective is None:
            logger.debug("sin_precio store=%s sku=%s", store_slug, sku)
            continue
        if effective > MAX_PLAUSIBLE_CLP:
            logger.debug(
                "precio_centinela store=%s sku=%s valor=%s", store_slug, sku, effective
            )
            continue

        brand = item.get("brand")
        availability = str(offers.get("availability") or "")

        products.append(
            RawProduct(
                store_slug=store_slug,
                store_sku=sku,
                url=item["url"].split("?")[0],
                name=name,
                price_effective=effective,
                # Sin "antes" declarado y sin GTIN: ver el docstring del módulo.
                price_normal=None,
                brand=normalize_brand(
                    brand.get("name") if isinstance(brand, dict) else brand
                ),
                category_path=category.slug,
                image_url=item.get("image"),
                in_stock=availability.rsplit("/", 1)[-1].lower() == _IN_STOCK,
                scraped_at=scraped_at,
                raw_payload=item,
            )
        )

    return ParsedListing(
        products=products, enumerated=len(entradas), declared=declared_total(html)
    )


class _CencosudSupermarketAdapter:
    """Lo común de Jumbo y Santa Isabel. Las subclases solo fijan host y slug.

    `store_key` = el path del departamento tal como lo navega la tienda HOY
    (`despensa`, `licores-bebidas-y-aguas`), sin barra inicial.
    """

    slug: str = ""
    base_url: str = ""
    #: Default conservador del repo. Santa Isabel declara `Crawl-delay: 1`, que
    #: permitiría el doble; Jumbo no declara ninguno. No se sube: el sistema hace
    #: dos pasadas diarias, no necesita velocidad.
    rate_limit_rps: float = 0.5
    #: Techo de páginas por categoría. El corte normal es el 404 del final; esto
    #: es la cota de cordura. 110 × 40 = 4.400 cubre la llave más grande medida
    #: (`jumbo/belleza-y-cuidado-personal`, 3.519 en 88 páginas) con holgura.
    #:
    #: **Un recorte por acá es silencioso** —el volumen enumerado queda estable
    #: pasada a pasada, así que el canario estadístico lo ve sano— y en la familia
    #: Falabella eso recortó el catálogo diez días. Por eso avisa, ver `discover`.
    #:
    #: Arrancó en 90, dimensionado para `despensa` (83 páginas). Subió a 110 al
    #: conectar belleza (migración 38): 88 de 90 son dos páginas de margen, y un
    #: 3% de crecimiento de catálogo habría recortado la llave sin un solo error.
    max_pages: int = 110

    def __init__(self, http: HttpClient, categories: Sequence[CategoryRef]) -> None:
        self._http = http
        self._categories = tuple(categories)
        #: Vive una pasada, igual que la instancia del adaptador: ver el docstring
        #: del módulo (bloque patrocinado + cross-listado entre departamentos).
        self._seen_en_la_pasada: set[str] = set()

    def categories(self) -> Sequence[CategoryRef]:
        return self._categories

    def completeness(self, category: CategoryRef) -> tuple[int, int] | None:
        """Siempre `None`: esta familia no puede sostener un canario exacto.

        Y conviene dejar escrito por qué, porque la idea parece gratis: la tienda
        declara el total en el HTML y la paginación llega al final sin tope de
        profundidad, o sea que el chequeo exacto **se puede calcular**. El problema
        es otro: el total declarado y el grid paginado **no concuerdan de forma
        estable**. Recorrido completo de las diez llaves el 2026-11-04,
        `enumerados / declarados`:

            jumbo/mascotas                        848 de   848   1,0000
            jumbo/chocolates-galletas-y-snacks  1.873 de 1.873   1,0000
            santaisabel/limpieza                  723 de   723   1,0000
            santaisabel/chocolates-...-snacks   1.082 de 1.083   0,9991
            jumbo/limpieza                      1.541 de 1.542   0,9994
            jumbo/licores-bebidas-y-aguas       3.207 de 3.209   0,9994
            jumbo/despensa                      3.299 de 3.303   0,9988
            santaisabel/botilleria              1.450 de 1.453   0,9979
            santaisabel/despensa                1.591 de 1.601   0,9938
            santaisabel/mascotas                  186 de   188   0,9894

        Son faltantes de 1 a 10 ítems en **siete de las diez llaves**, y no son
        estables ni por llave:
        `jumbo/despensa` dio 3.299 de 3.299 en un recorrido y 3.299 de 3.303 en el
        siguiente. Es deriva entre el servicio que cuenta y el que pagina — el
        total se lee en la página 1 y no se vuelve a mirar, a propósito.

        Con el canario exacto encendido eso deja **siete de las diez llaves en
        `partial`**, y un `partial` manda un mensaje de
        Telegram por pasada (`alerts.build_message`). Una alarma que suena siempre
        es una alarma apagada, que es la razón exacta por la que la familia
        Falabella tampoco lo implementa. Y ponerle una tolerancia sería inventar
        un umbral, que es justo lo que CLAUDE.md prohíbe para el chequeo exacto.

        Lo que sí queda es lo que de verdad hace falta: el aviso
        `catalogo_mas_grande_que_la_ventana` cuando `max_pages` recortaría —ese es
        el fallo silencioso— y el canario **estadístico**, que compara cada llave
        contra su propia historia y al que un gap de 0,1% no le molesta. El total
        igual se loguea al cerrar la llave, que es donde se mira.
        """
        return None

    def _page_url(self, category: CategoryRef, page: int) -> str:
        base = f"{self.base_url}/{category.store_key.strip('/')}"
        return base if page == 1 else f"{base}?page={page}"

    async def discover(self, category: CategoryRef) -> AsyncIterator[RawProduct]:
        # Dos conjuntos, y la distinción importa (es el bug de Andesgear):
        # `locales` detecta que la tienda sirvió otra vez la misma página;
        # `self._seen_en_la_pasada` decide si el producto se emite. Confundirlos
        # cortaría la paginación en la primera página cuyos productos ya hubieran
        # entrado por OTRA llave.
        locales: set[str] = set()
        enumerated = 0
        declared: int | None = None
        page = 1

        while page <= self.max_pages:
            try:
                html = await self._http.get_text(
                    self._page_url(category, page), rps=self.rate_limit_rps
                )
            except FetchError as exc:
                if exc.status_code != _END_OF_CATALOG_STATUS or page == 1:
                    raise
                logger.debug(
                    "fin_de_catalogo store=%s categoria=%s pagina=%d (HTTP 404)",
                    self.slug,
                    category.slug,
                    page,
                )
                break

            scraped_at = datetime.now(timezone.utc)
            try:
                parsed = parse_listing(
                    html, store_slug=self.slug, category=category, scraped_at=scraped_at
                )
            except NotAListingPage:
                if page == 1:
                    raise
                logger.debug(
                    "fin_de_catalogo store=%s categoria=%s pagina=%d",
                    self.slug,
                    category.slug,
                    page,
                )
                break

            enumerated += parsed.enumerated
            if page == 1:
                # El total se lee en la primera página y no se vuelve a mirar: si
                # el catálogo se mueve mientras paginamos, la referencia tiene que
                # ser la del arranque o el chequeo se persigue la cola.
                declared = parsed.declared
                if declared is not None and declared > self.max_pages * PAGE_SIZE:
                    logger.warning(
                        "catalogo_mas_grande_que_la_ventana store=%s categoria=%s "
                        "llave=%s declarados=%d techo=%d",
                        self.slug,
                        category.slug,
                        category.store_key,
                        declared,
                        self.max_pages * PAGE_SIZE,
                    )

            if not parsed.products and parsed.enumerated == 0:
                break

            nuevos_en_la_pagina = 0
            for product in parsed.products:
                if product.store_sku in locales:
                    continue
                locales.add(product.store_sku)
                nuevos_en_la_pagina += 1
                if product.store_sku in self._seen_en_la_pasada:
                    continue
                self._seen_en_la_pasada.add(product.store_sku)
                yield product

            # Una página que emite productos y no aporta un solo SKU nuevo A ESTA
            # LLAVE es el síntoma de una tienda que dejó de respetar `?page=` y
            # sirve la primera para siempre. Sin esto el daño sería silencioso:
            # el dedupe de la pasada haría que no se emitiera nada y la
            # paginación seguiría hasta `max_pages` gastando 90 requests.
            if page > 1 and parsed.products and nuevos_en_la_pagina == 0:
                logger.warning(
                    "pagina_repetida store=%s categoria=%s pagina=%d",
                    self.slug,
                    category.slug,
                    page,
                )
                break

            page += 1

        logger.info(
            "llave_cerrada store=%s categoria=%s llave=%s enumerados=%d "
            "declarados=%s paginas=%d",
            self.slug,
            category.slug,
            category.store_key,
            enumerated,
            declared if declared is not None else "?",
            page - 1,
        )


class JumboAdapter(_CencosudSupermarketAdapter):
    """Jumbo. `store_key` = el path del departamento (`despensa`).

    Su `robots.txt` responde 200, no declara `Crawl-delay`, permite los listados
    y tiene un grupo que **habilita explícitamente** a ClaudeBot, GPTBot y
    PerplexityBot. Lo que prohíbe son los filtros facetados (`*?map=`, `*?PS=`,
    `*sc=*`) y el checkout, nada de lo que este adaptador toca.

    No hace UA-sniffing: medido el 2026-11-04, `DEFAULT_USER_AGENT` devuelve el
    listado completo con su `ItemList` en dos intentos de dos. No necesita
    `BROWSER_HEADERS` como Tottus ni `BROWSER_USER_AGENT` como Easy.
    """

    slug = "jumbo"
    base_url = "https://www.jumbo.cl"


class SantaIsabelAdapter(_CencosudSupermarketAdapter):
    """Santa Isabel. Mismo front que Jumbo, catálogo propio y más chico.

    Su `robots.txt` declara `Crawl-delay: 1` y prohíbe `/api/`, `/_next/`,
    `/admin/` y `/private/`: nada que afecte a los listados, y es otra razón para
    no ir a buscar la API de VTEX.

    Sus departamentos **no se llaman igual** que los de Jumbo —`botilleria` en vez
    de `licores-bebidas-y-aguas`, `cuidado-personal-y-bebe` en vez de
    `belleza-y-cuidado-personal`— así que las llaves no se copian de una tienda a
    la otra.
    """

    slug = "santaisabel"
    base_url = "https://www.santaisabel.cl"
