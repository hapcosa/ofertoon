# INVESTIGACION_deporte_outdoor.md

Fase 0 de `PLAN_EXPANSION.md` §2.1 y §2.3. Medido el **2026-11-04**.

Alcance de esta sesión: las tres tiendas que el plan daba como "familia que ya
existe" en deporte/outdoor — **Sparta** (`magento_html`), **Doite** y **Lippi**
(`shopify_family`).

**Veredictos:** Sparta 🟢 entra con techo de cobertura; Lippi 🟡 entra pero con
una decisión de producto abierta que la bloquea; Doite 🔴 no entra.

---

## 1. Sparta — 🟢 entra, pero NO es "el más barato de todo el plan"

`PLAN_EXPANSION.md` §2.1 la llama "⭐ el más barato de todo el plan: ya tiene
fixture y los dos bugs que encontró ya están arreglados en la familia". Lo
primero es cierto. Lo segundo esconde que **su `robots.txt` prohíbe paginar**, y
eso le pone un techo de ~24% al catálogo.

### Las doce respuestas

| # | Pregunta | Respuesta medida |
|---|---|---|
| 1 | **Plataforma** | **Magento**, confirmado contando firmas en la home: 99 ocurrencias de `mage/` + `/static/version`. Cero de vtex, shopify, demandware, Next.js. ⇒ `magento_html`, familia que ya existe. |
| 2 | **`robots.txt`** | 200. `Crawl-delay: 1` en el bloque `User-agent: *` ⇒ `rate_limit_rps = 1.0`. **Y la restricción que define la tienda**: `Disallow: /*?`, `/*?*`, `/*&*`, `/*?limit=*`, `/*?dir=*`, `/*?order=*`, `/*?mode=*` y `Disallow: /*product_list_limit=`. O sea **ninguna query string está permitida**. ⇒ `paginates = False` **y** `page_size = None`: la configuración de Kupfer exactamente. |
| 3 | **UA** | `DEFAULT_USER_AGENT` alcanza y sobra: **545 de 545 fetches con 200**, cero reintentos, cero 403, cero 429. No hace falta `BROWSER_USER_AGENT` ni `BROWSER_HEADERS`. |
| 4 | **Paginación** | **Prohibida por robots** (ver 2). No se mide el final de paginación porque no se pagina. La página 1 sirve **36 productos**, que es el default de la tienda (el fixture `sparta_zapatillas.html` lo confirma: "Artículos 1-36 de 1080"). |
| 5 | **¿Orden estable?** | 🟢 **Sí, y es la pregunta que decidía la tienda.** Con `paginates=False` vemos la página 1 **siempre**, así que un orden rotatorio dejaría a todo el catálogo sin llegar nunca a `MIN_DAYS`. Medido con ~15 min de separación real (no back-to-back, para no medir la cache) sobre 9 hojas, 6 de ellas con más de 300 productos declarados: **8 de 9 con Jaccard 1,000**. La novena (`vestuario-deportivo/poleras-y-shorts`) dio 0,972: perdió 1 producto de 36 y no ganó ninguno — eso es deriva de catálogo, el patrón ya documentado de Andesgear, no reordenamiento. |
| 6 | **Total declarado** | Sí, en `p.toolbar-amount`, y es el **último** `span.toolbar-number` de tres — el bug que Sparta misma le enseñó a la familia y que ya está arreglado. **485 de 545 hojas lo declaran**; las 60 restantes son categorías vacías (el parser las logea `categoria_vacia`, que es correcto). |
| 7 | **GTIN** | **No**, y no hace falta medirlo: `magento_html.parse_listing` fija `gtin=None` por diseño, porque el grid de Magento no lo expone. Sparta no aporta nada al cross-store. |
| 8 | **`price_normal`** | 🟢 **Sí, en 41,6%** (3.775 de 9.083 filas emitidas, sobre el catálogo alcanzable completo, no sobre una página). ⇒ **θ se puede fijar midiendo**, al revés que Nike. Es además el primer Magento del sistema que lo trae: el docstring de la familia dice "no se observó ninguno en el catálogo auditado", que era Kupfer y Construmart. |
| 9 | **Stock en el listado** | 🟡 **No hay señal, y no hace falta.** `sin_stock = 0` sobre las 9.083 filas: `_in_stock` devuelve `True` para todo porque ningún `span.price-label` de Sparta contiene una palabra de `_STOCK_WORDS`. Medido después (2026-11-04, 3 categorías / 108 productos): **Sparta oculta los agotados en vez de marcarlos** — cero ocurrencias de "agotado", "sin stock" o "no disponible" en el HTML, y botón `tocart` en todas las filas. Sus `price-label` son solo rótulos de precio ("Precio habitual", "Desde", "Precio especial"). ⇒ el `in_stock` ciego **no cuesta nada estructural**: un producto que se agota desaparece del listado y su serie queda con un hueco, igual que en Colloky. Es distinto de Paris/Falabella, donde el agotado SÍ se lista como si estuviera a la venta. <br>⚠️ Lo que sí hay que anotar es el **"Desde"**: aparece 6 a 15 veces por categoría, o sea el precio del grid de un producto configurable es el **mínimo entre sus talles**. Es la misma elección que hace `vtex_family`, y es la correcta, pero significa que para esos productos el precio observado no es "el precio" sino "el más barato". |
| 10 | **Centinelas** | 🟢 **No.** Precio máximo observado sobre el catálogo alcanzable: **$10.990.000**, que es una máquina de gimnasio o una bici de alta gama — plausible, y dos órdenes por debajo de `MAX_PLAUSIBLE_CLP`. |
| 11 | **Llaves disjuntas** | 🔴 **No hay conjunto disjunto, y es el problema de diseño de esta tienda.** Sparta expone el mismo catálogo por **tres ejes a la vez**. |
| 12 | **Costo por pasada** | Medido: **545 requests, 575 s, 252,5 MB**. Con el conjunto recomendado (340 hojas): **≈340 requests, ≈360 s (6 min), ≈157 MB**. Entra en el presupuesto de ~1 h que deja `PASS_WINDOW`, pero se come el 10% de él. |

### El problema de las llaves, medido sobre SKUs reales

Barrí las **545 hojas** de catálogo (hoja = ninguna otra ruta la tiene como
prefijo) y crucé los SKUs. 9.083 filas emitidas → **3.615 SKUs únicos**, o sea
**2,51× de duplicación**.

Los tres ejes:

1. **Taxonomía de producto** — `zapatillas`, `vestuario-deportivo`, `ciclismo`,
   `deportes-de-equipo`, `deportes-individuales`, `deportes-de-raqueta`,
   `deportes-al-aire-libre`, `entrenamiento-funcional`, `maquinas-de-ejercicios`.
2. **Árbol paralelo `deportes/`** — 189 hojas que replican la taxonomía un nivel
   más abajo (`deportes/ciclismo`, `deportes/deportes-individuales`, …). Solapa
   con **todos** los demás ejes entre **49% y 91%**.
3. **Género** (`hombre` 35, `mujer` 35, `ninos` 22) y **vitrinas**
   (`destacado` 321, `cyber` 91, `sale` 60, `fan-store` 41, `marcas` 33,
   `busca-tu-talla`, `entrena-en-casa`, `dia-del-nino`, `dia-del-padre`,
   `navidad`, `team-chile`, `joma`, `trek`) — segundo y tercer corte del mismo
   catálogo.

Y dos contenciones puras dentro de la propia taxonomía:
`bicicletas` ⊂ `ciclismo` (**94,5%** del menor) y
`maquinas` ⊂ `maquinas-de-ejercicios` (**97,4%**).

**Recomendación**: las 9 raíces de taxonomía de producto → **340 hojas, 3.157
SKUs únicos (87,3% de lo alcanzable), 1,72× de duplicación residual**.
Excluir `deportes/`, el género, las vitrinas, `bicicletas` y `maquinas`.

⚠️ **Y ese 1,72× exige `dedupe_across_categories = True`, con una letra chica que
el precedente de Andesgear NO cubre.** `CLAUDE.md` dice que el dedupe de
Andesgear es inocuo "**solo porque los solapamientos medidos caen dentro de la
misma categoría interna**". Acá no: `vestuario-deportivo` × `deportes-individuales`
solapan 30% y `entrenamiento-funcional` × `deportes-individuales` 36%, y esos ejes
mapean a categorías internas **distintas** (`deporte-vestuario` contra
`deporte-equipamiento`). Con el dedupe puesto, gana la primera llave del orden de
`db.load_store_targets`, así que una polera podría quedar puntuando con el θ de
equipamiento. **Es una decisión del implementador y hay que tomarla a ojos
abiertos**: o se acepta y se ordena el `store_key` a propósito para que el eje
"correcto" gane, o se renuncia a los ejes que se cruzan y se baja la cobertura.

### El techo de cobertura

El sitemap de Sparta trae **13.448 fichas de producto**. Lo alcanzable sin
paginar son **3.615** (todas las hojas) o **3.157** (el conjunto recomendado), o
sea **24% a 27% del catálogo**.

No es un bug y no se arregla: es la consecuencia aritmética de `Disallow: /*?`
sobre un catálogo cuyas hojas más grandes declaran 463, 461 y 407 productos
contra una página de 36. **375 de las 485 hojas con total declarado entran
completas** (declaran ≤36 y suman 5.183); las otras 110 declaran 10.996 y
aportan 36 cada una.

---

## 2. Doite — 🔴 no entra

Detalle completo en `TIENDAS_PROHIBIDAS.md`. Resumen: su `robots.txt` trae
**`Disallow: /collections/*`** en el bloque `User-agent: *` (línea 261 de 16-308),
que es exactamente el endpoint de `shopify_family`
(`/collections/{handle}/products.json`); y la alternativa `/products.json` de
raíz, que su robots **no** prohíbe, responde **403**.

El plan la daba por viable con "`/products.json` verificado" — cierto como
capacidad técnica, falso como permiso. **Es la pregunta 2 aplicada antes que la
4**, que es el orden correcto.

---

## 3. Lippi — 🟡 entra, con una decisión de producto que la bloquea

### Las doce respuestas

| # | Respuesta medida |
|---|---|
| 1 | **Shopify** confirmado (`cdn.shopify`, `Shopify.theme`). ⇒ `shopify_family`. |
| 2 | `robots.txt` 200 y **permisivo**: `Allow: /` y 41 `Disallow` en nuestro bloque, todos los estándar de Shopify (carrito, checkout, cuenta, filtros `sort_by`). **Nada que toque `/collections/*/products.json`**. Sin `Crawl-delay` ⇒ rige el default conservador de la familia, `rate_limit_rps = 0.5`. |
| 3 | 🔴 **Y acá me equivoqué primero, así que va completo.** Medido el 2026-11-05 aislando la variable, 4 intentos de cada juego: `DEFAULT_USER_AGENT` **200 ×4**; `BROWSER_USER_AGENT` 200, 200, **429**, 200; `BROWSER_HEADERS` **403 ×4**; `BROWSER_HEADERS_JSON` **429 ×4**; sin UA **200 ×4**. O sea **el 429 es por headers, no por tasa, y es el INVERSO de Prat**: acá pasa el UA identificable con el sufijo `(+ofertascl-bot)` y lo que bloquea es parecerse a un navegador. ⚠️ Yo perseguí el fantasma bajando el rps de 0,5 a 0,33 y a 0,08 —y el 429 seguía, 44 veces en una corrida— porque mis barridos mandaban `BROWSER_USER_AGENT`. Con el UA correcto a **0,5 rps**: 117 colecciones, 161 requests, **0 errores**, 32 × 429 todos recuperados por reintento. La regla de `CLAUDE.md` —probar el UA ANTES del rps— aplica en las dos direcciones. |
| 4 | Pagina con `?limit=250&page=N`. El final es `{"products": []}`, que la familia ya distingue por número de página. |
| 5 | 🟡 **Sin la prueba A/B explícita, pero sin señal de inestabilidad**: el recorrido completo de las 117 colecciones dio **0 errores y 0 grupos de alias**, y los conteos por colección son consistentes con sus `products_count` (una vez corregido que ése cuenta variantes). Falta el segundo recorrido comparando conjuntos, que es barato ahora que el UA está resuelto (~95 requests). |
| 6 | 🟡 Sí, pero **`products_count` cuenta VARIANTES, no productos** — medido el 2026-11-05 y corrige mi propio número del día anterior: la colección `poleras` declara `products_count = 1.746` y enumerada da **342 productos**; 342 × 5,34 variantes ≈ 1.826. ⇒ **`all = 16.406` son variantes**, o sea ~3.100 productos, no 16.406. Cualquier dimensionamiento que use `products_count` como si fueran productos sobreestima por ~5×. |
| 7 | **GTIN: 0 de 9.773 variantes** traen `barcode`. Consistente con el docstring de la familia ("`products.json` no expone `barcode`"), ahora medido también acá. |
| 8 | 🟢 **Sí, y no es el "antes" fabricado de Prat.** 9.745 de 9.773 variantes traen el campo `compare_at_price`, pero **solo 1.136 (11,6%) tienen `compare_at > price`**. Su distribución es un abanico de tramos redondos —**0,6 (32%), 0,7 (16%), 0,8 (11%), 0,9 (9%)**, o sea 40/30/20/10% off— y no el `price/0.9` constante que Prat tenía en 249 de 250. ⇒ **θ se puede medir**. |
| 9 | 🟢 **`available` es stock real**: 7.306 de 9.773 variantes disponibles (**74,8%**), o sea **25% del catálogo agotado**. Igual que Prat. |
| 10 | No se observaron centinelas. |
| 11 | ⚠️ **La navegación vigente tiene 117 colecciones** (medido sobre su menú, que es de donde la regla del repo manda sacar las llaves) y está organizada en **tres ejes que se cruzan**: segmento (`hombre`, `mujer`, `ninos`, más `accesorios`/`equipamiento` unisex), tipo de producto (`chaquetas-*` → `cortaviento-*`, `impermeables-*`, `plumas-*`, …; `top-*`, `bottom-*`, `calzado-*`) y **actividad** (`trekking-hiking-*`, `nieve-*`, `trail-running-*`, `escalada-y-montana-*`, `lifestyle-*`). Las 76 hojas de tipo de producto son el conjunto candidato; los 21 paraguas y las 20 de actividad son los que hay que cruzar para ver cuánto solapan. <br>Además, **634 colecciones publicadas, 594 con productos, y hay handles aliasados** — dos llaves distintas al mismo conjunto: `trekking-hiking` / `trekking-y-hiking` (1.557 cada una), `textil` / `vestuario` (2.298), `banner` / `last-chance` (3.733), `sale-ut` / `ultimas-tallas` (2.373). Conectar las dos de un par hace pesar el doble a cada listing en su propio p50. Vitrinas evidentes a excluir: `all`, `cyber`, `sale`, `winter-sale`, `black-winter`, `black-2026`, `last-chance`, `verano2024`, `dia-de-la-madre`, `dia-del-nino`, `dia-del-padre`, `coleccion-carrito`, `banner`. **Pendiente**: cruzar SKUs reales, como se hizo con Sparta y Colloky. |
| 12 | Pendiente de dimensionar, y depende enteramente de la decisión de abajo. |

### ⚠️ La decisión que bloquea Lippi: una fila por variante o una por producto

`shopify_family.parse_listing` emite **una fila por variante**, y lo justifica en
su docstring: "cada variante tiene su propio precio y su propio stock, y son las
que la tienda vende". En **Prat** eso es correcto: es ferretería, las variantes
casi no existen.

En Lippi las variantes son **talles**. Medido sobre 1.830 productos de 5
colecciones de catálogo (9 páginas, no una):

| | |
|---|---|
| Variantes por producto | **5,34** |
| Productos con >1 variante | 1.713 |
| …de ellos con **precios distintos** entre variantes | **11 (0,6%)** |

O sea en **99,4%** de los casos los talles comparten un único precio. Emitir por
variante crearía **~5,3 series idénticas por producto**.

Y el orden de magnitud importa: la colección `all` declara **16.406 productos**,
que a 5,34 son **~87.600 listings**. El sistema entero hace ~105.000
observaciones por día. **Lippi sola casi duplicaría el volumen del sistema, con
5× de redundancia.**

Es exactamente la pregunta que `vtex_family` resolvió **al revés** —"un producto
tiene N items y los items son los talles […] se emite **uno por producto**", con
el precio del **talle disponible más barato**, porque tomar el de un talle
agotado publica un precio que nadie puede pagar—. Las dos familias contestan
distinto a la misma pregunta, y cada una tiene razón para su tienda.

**Lo que NO se hizo es tocar `shopify_family` de costado**: Prat está conectada y
en producción con 96% de estabilidad de cohorte, y cambiar la granularidad de
emisión le **cambiaría el `store_sku` a todos sus listings**, lo que reinicia su
reloj de `MIN_DAYS` y tira su histórico de precios.

### El barrido completo de Lippi (2026-11-05): 117 colecciones, 0 errores

Con el `DEFAULT_USER_AGENT` correcto (ver abajo) el catálogo entero se enumera en
**161 requests, 100,7 MB, 386 s**.

🟢 **El universo real son 3.581 productos únicos**, no 16.406 — otra confirmación
de que `products_count` cuenta variantes: 3.581 × ~5,2 ≈ los ~18.600 variantes
sumados.

**Las llaves: los 76 nodos de tipo de producto, y nada más.**

| eje | n | productos sumados | **únicos** | variantes | dup |
|---|---|---|---|---|---|
| **hojas de tipo** | 76 | 4.481 | **3.418 (95,4% del universo)** | 23.195 | **1,31×** |
| actividad | 20 | 4.822 | 2.807 | 24.068 | 1,72× |
| paraguas | 21 | 9.994 | 3.570 | 52.557 | 2,80× |

- **El eje de actividad es redundante**: 2.725 de sus 2.807 productos
  (**97,1%**) ya están en las hojas. Aporta **82 productos exclusivos** y a cambio
  duplicaría 2.725 series. No entra.
- **Los paraguas también**: 3.407 de 3.570 (**95,4%**) están en las hojas.
- ⇒ **76 llaves, 3.418 SKUs, 1,31× residual.** Costo estimado: ~95 requests,
  ~65 MB, ~230 s por pasada.
- 🟢 **Cero grupos de alias** entre las 117 por conjunto exacto de productos. Los
  pares que yo había sospechado por tener el mismo `products_count`
  (`textil`/`vestuario`, `trekking-hiking`/`trekking-y-hiking`) **no están en la
  navegación vigente**, así que quedan fuera del conjunto recomendado de todos
  modos.

**Y dos números que confirman el flag sobre el catálogo entero, no sobre 5
colecciones:**

- **5,18 variantes por producto.**
- **Solo 72 de 19.297 filas (0,37%)** tienen precios distintos entre sus
  variantes. El muestreo daba 0,6%; medido completo es la mitad. O sea el 99,63%
  de los productos de Lippi tienen **un** precio para todos sus talles.
- 🟢 **`sin_ninguna_disponible = 0` sobre las 19.297 filas.** Queda **confirmado**
  lo que el fixture sugería: **Lippi nunca muestra un producto con todos los
  talles agotados** — los oculta. Consecuencia concreta: con
  `emitir_por_producto`, `in_stock` **nunca va a dar `False`** en esta tienda, y
  por eso esa rama de `_elegir_variante` se testea sintética (ver
  `tests/test_shopify_lippi.py`).

### ✅ Resuelto: un flag por tienda (decisión del dueño, 2026-11-05)

Implementado en `scrapers/stores/shopify_family.py`:

- **`emitir_por_producto: bool = False`** como atributo del adaptador. El default
  es `False` y el docstring del módulo explica por qué tiene que seguir siéndolo:
  el flag se prende en tiendas **nuevas**, nunca se le cambia a una que ya tiene
  serie.
- **`_elegir_variante()`**, que porta la regla de `vtex_family._elegir_item`: gana
  la **disponible más barata**, y si ninguna está disponible, la más barata. El
  motivo es el mismo y hay que decirlo: tomar el precio de un talle agotado
  publica un precio que nadie puede pagar.
- Con el flag puesto, la fila cambia en cuatro cosas: `store_sku` es el id del
  **producto**, la `url` va sin `?variant=`, el nombre **no** arrastra el talle
  (colgarle "S" nombraría mal lo que se publica) y `in_stock` es "**alguna** talla
  disponible" — no la de la variante que dio el precio.
- **`LippiAdapter`** con `emitir_por_producto = True`. Su `non_brand_vendors`
  queda **vacío a propósito**: sus `vendor` son marcas reales (`Lippi` 374,
  `Haka Honu` 171, `Vulcano` 98, `Geography` 4 en la muestra), no placeholders
  como el `pratcl` / `NO DEFINIDO` de Prat.

**Tests**: `tests/test_shopify_lippi.py`, 15 casos sobre un fixture real de 2
productos (`tests/fixtures/lippi_collection_poleras.json`). Los 24 de Prat siguen
pasando sin cambios, que es la regresión que importaba. Suite completa: **680
pasan, 116 saltados** (los de DB, sin `TEST_DATABASE_URL`).

⚠️ **Dos ramas de `_elegir_variante` se testean sintéticas, y está marcado en el
docstring del test**: el producto con **todos** los talles agotados y el producto
cuyo talle **más barato está agotado**. Ninguno de los dos apareció en las cinco
colecciones medidas —lo que sugiere que Lippi oculta el producto cuando se le
agotan todos los talles, el mismo tamiz de disponibilidad que en Prat separa
catálogo de vitrina—, y son justo las dos ramas que deciden si se publica un
precio imposible. Esperar a que la tienda produzca el dato era dejar la guarda sin
test.

El caso real del fixture que más enseña es **Polera Hombre Liquen Celeste**: 5
talles, dos precios (4.990 y 9.990), **uno solo disponible** (la S, a 4.990) y un
`compare_at_price` de 14.990. Es el 0,6% medido — y sirve de advertencia sobre lo
que un fixture puede no probar: acá el más barato **está** disponible, así que
"más barato" y "más barato disponible" dan el mismo número. El caso que discrimina
es el inverso y por eso va sintético.

## 4. Lo que queda sin medir en esta vertical

Dicho explícitamente para que no se confunda con "medido y está bien":

- **Orden estable de Lippi** (pregunta 5) — sin medir, y es la que más cuesta
  ignorar.
- **Solapamiento de Lippi sobre SKUs reales** (pregunta 11) — identificados los
  alias por `products_count`, sin cruzar SKUs.
- **Si Sparta lista agotados o los oculta** — decide si su `in_stock` ciego
  cuesta algo.
- **Las demás candidatas de §2.3** (Columbia, The North Face, Patagonia, Puma,
  New Balance, Under Armour, Bazar Deportivo, Mundo Ciclismo, Bikeshop) — sin
  tocar. De las que el plan nombraba, en esta sesión se descartaron `mountain.cl`
  (no es e-commerce, es una copia HTTrack de 2022) y `rockford.cl` (TLS roto);
  ver `TIENDAS_PROHIBIDAS.md`.
