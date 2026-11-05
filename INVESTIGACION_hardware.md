# INVESTIGACION_hardware.md

Fase 0 de `PLAN_EXPANSION.md` §2.2. Medido el **2026-11-04**.

El plan pedía dos tiendas sin auditar (`myshop.cl`, `megabytes.cl`) y daba una
lista de diez candidatas a barrer. Barrí las que existen: **de 13 dominios
mirados, 3 entran con una familia que ya existe, 4 necesitarían adaptador nuevo,
y 6 no son tiendas.**

## El encuadre que el plan corrige, y conviene tener presente

`PLAN_TIENDAS.md` §2.3 decía que hardware es "el margen de mejora más bajo del
plan" porque SP Digital y PC Factory ya la cubren. `PLAN_EXPANSION.md` §2.2 da
vuelta el argumento con el dato de estabilidad de cohorte: **`spdigital` 4% y
`pcfactory` 39%**, las dos por debajo del `UMBRAL_ESTABILIDAD = 0.40`. O sea la
categoría **no necesita más catálogo, necesita tiendas que acumulen serie**.

Eso cambia qué buscar: **las preguntas que deciden son la 5 (orden estable) y la
11 (catálogo o vitrina), no el tamaño.** Y tiene una consecuencia que vale
escribir: las tres tiendas que entran tienen catálogos **chicos** (336 a 1.615
productos), y eso **no es un defecto para este propósito** — un catálogo chico y
estable produce baselines, y uno grande que rota no.

---

## 1. Las tres que entran: WooCommerce, familia que ya existe

Las tres responden la **Store API pública de WooCommerce**, que es el endpoint
que usa `woo_family` (`/wp-json/wc/store/v1/products?per_page=100&page=N&category={id}`),
el mismo con el que está conectada Urban Comercial.

| | **Megabytes** | **TecnoPlaza** | **Infor-Ingen** |
|---|---|---|---|
| Host | `www.megabytes.cl` | `tecnoplaza.cl` | `store.infor-ingen.com` |
| Firma Woo en la home | — (la API es la prueba) | 230 | 719 |
| `robots.txt` | ⚠️ ver abajo | 200, sin `Crawl-delay` | 200, sin `Crawl-delay` |
| **Catálogo (`X-WP-Total`)** | **336** | **512** | **1.615** |
| Categorías con productos | 28 | 15 | 58 |
| Suma de sus `count` | 682 (**2,0×**) | 539 (1,05×) | 3.431 (**2,1×**) |
| `currency_minor_unit` | **0** (CLP, sin trampa de escala) | 0 | 0 |
| `is_in_stock` en la muestra | 100/100 | 100/100 | **70/100** |
| "antes" declarado en la muestra | **91/100** | **0/100** | **100/100** |
| EAN en `attributes` | 0/100 | 0/100 | 0/100 |
| Categorías más grandes | Componentes PC 157, Accesorios 132 | Periféricos 229, Audio 154 | Placas Madres 320, Gabinetes 291 |

### Las llaves y el orden, medidos sobre SKUs reales (2026-11-05)

Enumeré **todas** las categorías de cada tienda y crucé los ids de producto. Los
dos números que deciden:

| | **Megabytes** | **Infor-Ingen** | **TecnoPlaza** |
|---|---|---|---|
| Categorías enumeradas | 28 | 58 | 🔴 **0 — su endpoint falló** |
| Suma de enumerados | 623 | 3.431 | — |
| **Unión única** | **327** | **1.615** | — |
| Factor de duplicación | **1,91×** | **2,12×** | — |
| Contenciones ≥80% hijo⊂padre | 16, **todas al 100%** | 60, **todas al 100%** | — |
| `count` declarado == enumerado | 8 de 28 **no** calzan | **58 de 58 calzan** | — |
| **Orden estable (Jaccard, 2 recorridos)** | **1,0000** (`Componentes PC`, 153) | **1,0000** (`Placas Madres`, 320) | — |

🟢 **El solapamiento es jerarquía pura, no desorden.** Las contenciones dan
**100%** exacto en los dos casos: `Ventilación` ⊂ `Componentes PC`,
`Gabinetes s/Fuente` ⊂ `Gabinetes`, `AM5` ⊂ `Placas Madres`,
`Memorias Ram Pc` ⊂ `Memorias`, `Discos Duros SSD` ⊂ `Almacenamiento`… Eso hace
la decisión trivial y es el mismo criterio que en Falabella con
`cat2083/Zapatillas`: **entra el paraguas, no la hoja.**

**Las llaves concretas** — las categorías que no están contenidas en ninguna otra:

- **Megabytes: 9 llaves** (`Componentes PC` 153, `Accesorios` 133, `Otros` 38,
  `Seguridad` 23, `cámara de seguridad` 8, `Servicios técnicos` 8, `PC armados` 7,
  `Notebooks` 5, `All in One` 1) → cubren **327 de 327 SKUs (100%)** con
  **1,15×** de solapamiento residual.
- **Infor-Ingen: 14 llaves** (`Placas Madres` 320, `Gabinetes` 291,
  `Refrigeracion` 205, `Memorias` 161, `Varios` 154, `Video` 134,
  `Almacenamiento` 116, `Procesadores` 98, `Teclados y Mouse` 97, `Monitores` 91,
  `Computadores` 15, `Escritorios Gamer` 5, `Sin categoría` 4, `WIFI` 2) →
  **1.615 de 1.615 (100%)** con **1,048×** residual.

🟢 **Y el orden es perfectamente estable en las dos**: Jaccard 1,0000 sobre dos
recorridos completos de su categoría más grande. Es exactamente lo que el
encuadre de esta vertical pedía — tiendas que **acumulen serie**, no más
catálogo — y es mejor que lo que hoy tienen `spdigital` (4%) y `pcfactory` (39%).

🟢 **Infor-Ingen sostiene el canario exacto**: `count` declarado == enumerado en
**las 58** categorías. Es la única tienda de esta tanda que lo sostiene.

⚠️ **Megabytes NO lo sostiene, y el motivo es informativo**: 8 de sus 28
categorías no calzan, y **5 declaran productos y devuelven cero**
(`Gabinetes` count=18, `Más accesorios` count=28, `Monitores` count=6,
`MegaDays` count=1, `Memorias Ram` count=1). Eso explica también por qué su unión
da **327** cuando `X-WP-Total` declara **336**: los 9 que faltan son los que solo
cuelgan de esas categorías huérfanas. No es un bug del adaptador —la Store API
contesta 200 con lista vacía— sino `count` desactualizado del lado de la tienda.
Con el canario exacto encendido serían 5 llaves en `partial` permanente, o sea la
alarma que suena siempre: **canario estadístico para Megabytes.**

🔴 **TecnoPlaza quedó sin medir.** Su
`/wp-json/wc/store/v1/products/categories` agotó **3 reintentos con
`ReadTimeout`** a 90 s de timeout, dos corridas distintas. Ayer el mismo endpoint
respondió con 15 categorías, así que no es que no exista: es un origen lento o
intermitente. **Hay que re-medirlo antes de conectarla**, y si el timeout es
estable, es razón suficiente para dejarla afuera de la primera tanda — una tienda
cuyo endpoint de categorías se cae deja al runner marcando `failed` sin que haya
nada que arreglar de nuestro lado.

### Lo que hay que resolver por tienda

- ⚠️ **Megabytes anda SOLO con `DEFAULT_USER_AGENT`.** 200 las 4 veces con el UA
  identificable; `RemoteProtocolError` **las 4 veces** con `BROWSER_USER_AGENT`
  **y** con `BROWSER_HEADERS` (el servidor corta la conexión). Es el **patrón
  inverso** a Prat y a Easy: lo que rompe acá es el juego de headers de
  navegador. Su `robots.txt` tampoco se puede leer con los headers de navegador,
  por el mismo motivo — hay que re-pedirlo con el UA identificable antes de
  conectarla, porque la pregunta 2 todavía no está respondida para esta tienda.
  Regla general que vale anotar: **ante un fallo de transporte, probar también el
  UA identificable**; el reflejo de escalar a `BROWSER_HEADERS` puede ser la
  causa.
- ⚠️ **El solape padre/hijo es real y hay que cruzarlo**: en Megabytes e
  Infor-Ingen la suma de los `count` de categoría duplica el total de la tienda
  (**2,0×** y **2,1×**), o sea las categorías padre contienen a sus hijas.
  Conectar las dos hace pesar el doble a cada listing en su propio p50. En
  Infor-Ingen se ve a ojo en el árbol: `AM5` (122) es seguramente hijo de
  `Placas Madres` (320), y `Gabinetes s/Fuente` (175) de `Gabinetes` (291).
  **La pregunta 11 queda pendiente de cruzar sobre SKUs reales** — es lo que hice
  con Sparta y Colloky y es lo que falta acá.
- 🔴 **TecnoPlaza no declara "antes" en ninguno de los 100 productos de la
  muestra.** Es el caso Nike: **θ no se puede fijar midiendo** y hay que
  heredarlo de sus vecinos (`tecno-*`), anotándolo como herencia y no como
  medición.
- 🟢 **Infor-Ingen trae stock real** (70 de 100 disponibles), igual que Shopify y
  que el resto de `woo_family`. Megabytes y TecnoPlaza dieron 100% disponible en
  la muestra, lo que hay que verificar **contra productos agotados** antes de
  creerle al campo — el camino feliz no ejercita la guarda.
- 🔴 **Ninguna de las tres trae EAN** en `attributes` (0 de 100 en cada una), a
  diferencia de Urban Comercial que traía 15 de 100. No aportan al cross-store.
- 🔴 **Orden estable (pregunta 5): sin medir en las tres.** Es la pregunta que el
  encuadre de arriba vuelve decisiva, y queda pendiente.
- **Costo por pasada**: chico. Con `per_page=100`, Megabytes son 4 requests,
  TecnoPlaza 6 e Infor-Ingen 17 por el catálogo completo (más las llamadas por
  categoría según cómo se elijan las llaves). Las tres juntas caben en ~30
  requests, lo más barato del plan en presupuesto de pasada.

---

## 2. Las cuatro que necesitarían adaptador nuevo

Todas pasan el borde sin problema (200 las 4 veces con los tres juegos de
headers), pero **ninguna expone una API de catálogo conocida**: probé
`/products.json` (Shopify), `/api/catalog_system/pub/category/tree/*` (VTEX) y
`/wp-json/wc/store/products` (Woo) en las cuatro.

| Tienda | Borde | Plataforma | Rutas probadas | Qué haría falta |
|---|---|---|---|---|
| **MyShop** (`myshop.cl`) | 200 ×4 con los tres UA | **sin determinar** (cero firmas de vtex/shopify/magento/demandware/next/woo) | `/sitemap.xml` **200**; las tres APIs 404 | Adaptador HTML nuevo. El sitemap es la vía de descubrimiento de llaves |
| **Winpy** (`winpy.cl`) | 200 ×4 con los tres UA | **sin determinar** | `/sitemap.xml` **200**; las tres APIs 404 | ⚠️ **`Crawl-delay: 5`**, no 10 como dice el plan ⇒ `rate_limit_rps = 0.2`, el mismo presupuesto que SP Digital (que está conectada). El argumento del plan para descartarla por costo se cae a la mitad |
| **MacOnline** (`maconline.com`) | 200 ×4 con los tres UA | **sin determinar**; `nginx/1.18.0` | `/products.json` → **500** (interesante: responde JSON, o sea hay algo ahí); `/sitemap.xml` 404 | Adaptador nuevo. Sin sitemap, el descubrimiento de llaves sale de su propia navegación |
| **Spacestore** (`spacestore.cl`) | ⚠️ **el `www` da 403, el ápex da 200 ×4** con los tres UA | 🟢 **Shopify** (corregido el 2026-11-05) | `/products.json` de raíz **403**, pero `/collections/{handle}/products.json` **200** | **Ninguno: `shopify_family` la cubre tal cual.** Ver abajo — pero **no es una tienda de hardware** |

### ⚠️ Spacestore entra con cero código, y no es de esta vertical

Medido el 2026-11-05, y corrige mi propio "sin determinar" del día anterior:

- **Es Shopify.** Su sitemap tiene la forma canónica
  (`sitemap_products_N.xml?from=…&to=…`) y la home trae 7 referencias a
  `cdn.shopify`. El 403 de `/products.json` de raíz es el mismo caso que Doite y
  **no dice nada** del endpoint que la familia usa.
- **Su `robots.txt` SÍ permite el endpoint de la familia.** Prohíbe únicamente las
  variantes con parámetros de `/collections/*` (`*sort_by*`, `*+*`, `*%2B*`,
  `*filter*&*filter*`) — no el `/collections/{handle}/products.json` plano. Es
  **exactamente la diferencia con Doite**, que prohíbe `/collections/*` entero.
- `/collections.json` devuelve **250 colecciones** (el tope del `limit`, así que
  puede haber más) y `/collections/disney/products.json` da 200 con 250 productos.
- **1,31 variantes por producto** → `emitir_por_producto` va en **`False`**: acá
  la variante no es el talle y la emisión por variante de la familia es la
  correcta. Es el contraste útil con Lippi (5,34).
- `barcode` **0 de 327** variantes; `available` real (**306 de 327**, 93,6%);
  `compare_at_price > price` en 93 de 327 (**28%**) ⇒ θ medible.
- ⚠️ **`vendor` es `Space Store` en el 100% de la muestra**: es el nombre de la
  propia tienda, o sea el caso `pratcl` / `NO DEFINIDO`. Va a
  `non_brand_vendors` — si no, toda la tienda queda con la misma "marca".

🔴 **Pero no es hardware.** Sus colecciones más grandes son `disney` (17.095),
`fandom` (16.568), `cultura-pop` (16.485), `disney-store-japon`, `mickey-y-amigos`,
`disney-parks`: es **merchandising y coleccionables**. El plan la listaba entre las
candidatas de tecnología y eso está mal. Entra barata, pero **no tiene categoría
en el sistema**: decidir si se le crea una (`merch`/`coleccionables`, con tema
propio por el rango de ticket) es una decisión de producto, no de esta Fase 0.
⚠️ Y antes de conectarla hay que mirar el solapamiento con lupa: `disney`,
`fandom` y `cultura-pop` declaran 17.095, 16.568 y 16.485 — casi idénticos, lo que
huele a tres nombres para el mismo catálogo. (Y recordar que en Shopify
`products_count` cuenta **variantes**, no productos: el hallazgo de Lippi aplica
igual acá.)

### Corrección: la "firma Magento" de cuatro tiendas era un falso positivo mío

En el barrido del 2026-11-04 reporté `magento: 4` en MyShop, Winpy, MacOnline y
Spacestore. **Era un bug de mi regex**: el patrón `mage/` matchea `image/`.
Medido con la firma estricta (`/static/version`, `mage-init`, `Magento_`,
`mage/requirejs`), las cuatro dan **0**. O sea su plataforma seguía sin
determinar, no era Magento.

Lo que sí se determinó el 2026-11-05:

- **Winpy declara `<meta name="generator" content="Winpy.cl">`** → plataforma
  propia, hecha en casa. Su sitemap son 326 URLs y la mayoría páginas estáticas
  (`que-es-winpy`, `como-comprar`, …), así que el catálogo no sale de ahí.
  `robots.txt`: 7 `Disallow` y `Crawl-delay: 5`.
- **MyShop**: sitemap partido en `categorias_sitemap.xml` +
  `productos_sitemap_1..5.xml` — nomenclatura propia, en español. 64 `Disallow`.
  El `categorias_sitemap.xml` es la vía limpia para descubrir llaves.
- **MacOnline**: su sitemap es **gzipeado** (`sitemap.xml.gz`, 17 KB) y hay que
  descomprimirlo; `laravel_csrf` presente, o sea probablemente una app Laravel a
  medida.

**Mercado Digital** (`mercadodigital.cl`) queda aparte: borde 200, pero
`robots.txt` **404**, sitemap **404**, las tres APIs 404, y la home pesa 22 KB.
No hay por dónde empezar a descubrir llaves; es la menos prometedora de las
cinco.

---

## 3. Las que no son tiendas

Detalle en `TIENDAS_PROHIBIDAS.md`. En esta vertical:

| Dominio | Qué pasó |
|---|---|
| `zmart.cl` | **Cambió de rubro**: redirige a `botin.cl`, juguetes y cartas TCG |
| `reifstore.cl` | **DNS no resuelve** |
| `pcmix.cl` | **DNS no resuelve** |
| `dinamicpc.cl` | **DNS no resuelve** |
| `pcexpress.cl` | **403** en www y ápex — y **retrocedió**: en octubre de 2026 pasaba el borde |

Y el aviso del plan sobre agregadores se sostiene: **Solotodo y similares son
comparadores, no tiendas** — su "precio" es de terceros y no tiene serie propia.
Ninguno de los dominios de arriba cae en esa categoría, pero conviene no
agregarlos a la lista más adelante.

---

## 4. Recomendación

**Conectar las tres de WooCommerce en una sola tanda**, en este orden de
prioridad:

1. **Infor-Ingen** — el catálogo más grande de las tres (1.615), stock real, y
   "antes" declarado en el 100% de la muestra ⇒ θ medible. 17 requests.
2. **Megabytes** — 336 productos, "antes" en 91%. Resolver primero su
   `robots.txt` con el UA identificable y fijar `user_agent=DEFAULT_USER_AGENT`
   explícitamente en su adaptador, con el comentario de por qué (si alguien lo
   "mejora" a `BROWSER_HEADERS`, la tienda deja de responder).
3. **TecnoPlaza** — 512 productos, pero θ heredado por falta de `price_normal`.

Antes de escribir la migración, las tres necesitan: **cruzar el solape
padre/hijo sobre SKUs reales** (pregunta 11) y **medir el orden estable**
(pregunta 5). Las dos son barridos cortos — los catálogos son chicos — y las dos
son las que este plan declara decisivas para esta vertical.

El costo total de las tres es de ~30 requests por pasada, o sea **ruido** contra
los ~57 min que ya ocupa la pasada. No hay razón de presupuesto para conectarlas
de a una.

**No perseguir** MyShop, Winpy, MacOnline ni Spacestore todavía: son cuatro
adaptadores HTML nuevos para una vertical que, según el propio encuadre del
plan, no necesita más catálogo. Winpy es la primera de la cola si alguna entra,
porque su `Crawl-delay` real (5, no 10) la hace más barata de lo que el plan
suponía.
