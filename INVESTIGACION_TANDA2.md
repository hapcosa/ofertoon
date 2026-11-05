# INVESTIGACION_TANDA2.md

Segunda tanda de Fase 0, **2026-11-05**. Lo que la primera no cubrió: candidatas
sacadas de **fuentes reales** en vez de inventadas, y el censo de qué familia del
repo cubre cada tienda.

## Por qué esta tanda existe

En la primera tanda armé la lista de candidatas de hardware a mano, y **10 de 32
dominios no existían** (DNS no resuelve). Inventar nombres de dominio no escala y
además sesga: se encuentran las tiendas que uno ya conoce.

Esta tanda usa dos fuentes: búsqueda web y **listas de competidores por dominio**
de las tiendas ya conectadas (`pcfactory.cl`, `spdigital.cl`, `casaroyal.cl`,
`andesgear.cl`, `sparta.cl`, `construmart.cl`, `cocha.com`). El salto es grande:
**31 de 35 candidatas nuevas responden 200**.

⚠️ **Y la primera cosa que corrigió**: PC Express es **`pc-express.cl`, con
guión**. `PLAN_TIENDAS.md` y mi propia sonda usaron `pcexpress.cl`, que es otro
sitio (403). Un veredicto de "403, bloqueada" sobre el dominio equivocado no dice
nada — la misma lección que la llave `cat2049/Audifonos`, un nivel más arriba.

## El censo: qué familia cubre qué

Verificado **probando el endpoint**, no la firma del HTML. Hace falta decirlo
porque mi detección por firma se equivocó mucho: marcaba `vtex` en 8 tiendas y
solo 2 tienen la API de VTEX, y marcaba `magento` donde el patrón `mage/`
matcheaba `image/`.

| familia | ¿existe? | tiendas nuevas | estado |
|---|---|---|---|
| **`magento_html`** | 🟢 | **8** | **7 parsean** (ver §Magento) |
| **`shopify_family`** | 🟢 | **3** volkanica, stanley1913, underarmour | endpoint OK, sin medir |
| **`vtex_family`** | 🟢 | **2** casaroyal, asics | `category/tree` OK, sin medir |
| **`woo_family`** | 🟢 | **3** megabytes, infor-ingen, tecnoplaza | medidas en la tanda 1 |
| `salesforce_family` | 🔴 falta | **5** hites, tricot, abc, **marathon**, **newbalance** | 2 nuevas respecto de la tanda 1 |
| `presta_family` | 🔴 falta | **4** alltec, todoclick, compuchile, globalmac | solo firma |
| `jumpseller_family` | 🔴 falta | **3** sipoonline, toptec, rutaoutdoor | solo firma |
| `opencart_family` | 🔴 falta | **2** pc-express, sistemax | solo firma |

**~16 tiendas caen en familias que ya existen.** Eso es el trabajo barato, y es
donde conviene empezar.

⚠️ **`newbalance.cl` aparece en dos filas y no es un error**: su home trae a la
vez la firma estricta de Magento y la de Demandware. Hay que decidir por cuál se
conecta antes de escribir su fila en `stores` — y el camino Magento ya está
verificado parseando (abajo), así que es el que cuesta cero.

## Magento: 7 de 8 parsean, y en tres configuraciones que la familia ya tiene

Lo que decide la configuración es el `robots.txt`, igual que en Kupfer y
Construmart. Los ocho se parten en tres grupos con robots **idénticos** dentro de
cada grupo:

### Grupo A — la plantilla de Sparta (`paginates = False`)

`speedo.cl`, `trekbikeschile.com`, `newbalance.cl`: **87 `Disallow`,
`Crawl-delay: 1`**, y entre ellos `/*?`, `/?`, `/*?*`, `/*&*`,
`/*product_list_limit=`, `/*?limit=*`. O sea **ninguna query string permitida**:
es el robots de Sparta carácter por carácter, lo que sugiere el mismo operador.

⇒ Configuración Kupfer/Sparta: `paginates = False`, `page_size = None`, y el
techo de cobertura de una página por llave.

### Grupo B — la plantilla de Andesgear (`paginates = True`, `Crawl-delay: 3`)

`thenorthface.cl`, `kliper.cl`, `mammut.cl`, `marmot.cl`: **17 `Disallow`,
`Crawl-delay: 3`**, nada que prohíba `?p=` ni el `limit`. ⇒ `paginates = True`
con `rate_limit_rps` respetando el delay (0,33), igual que Andesgear.

⚠️ **Las cuatro usan URLs limpias SIN `.html`** (`/hombre`, `/zapatos`,
`/equipamiento`), a diferencia de todas las Magento ya conectadas. Mi primer
barrido las dio por `NotAListingPage` en el 100% de las candidatas **y era mi
error**: filtré candidatas exigiendo `.html` y nunca probé una categoría real.
Peor: la ruta más enlazada de su home no es una categoría (`/tiendas`, `/ayuda`),
así que "probar el enlace más frecuente" tampoco sirve. **La llave hay que
sacarla del menú de catálogo, no del conteo de enlaces.**

### Grupo C — `weplay.cl`

Sin `Crawl-delay`, 40 `Disallow`, nada prohibido ⇒ `paginates = True` con el
default de la familia. **Es la única que NO entra** (ver abajo).

### Medido con el parser real del repo

| tienda | llave probada | emitidos / enumerados | declarado | págs | `price_normal` | pmax |
|---|---|---|---|---|---|---|
| **thenorthface** | `/hombre` | **48 / 49** | 1.014 | 22 | 13 | $399.990 |
| **kliper** | `/marcas` | **24 / 24** | **13.769** | 574 | 11 | $399.990 |
| **mammut** | `/hombre` | **24 / 24** | 235 | 10 | 14 | $499.990 |
| **marmot** | `/sale` | **24 / 24** | 208 | 9 | 24 | $317.990 |
| **newbalance** | `/ropa` | **36 / 36** | 493 | 14 | 1 | $124.990 |
| **speedo** | `/mujer` | **33 / 33** ⚠️ | 226 | 7 | 7 | $79.990 |
| **trekbikeschile** | `/sale` | **36 / 36** ⚠️ | 136 | 4 | 36 | $5.990.000 |
| weplay | `/juegos` | 🔴 **1 / 36** | 1.670 | — | 0 | $39.990 |

⚠️ Speedo y Trek **solo** después del cambio de código de abajo.

🔴 **`sin_stock = 0` en las siete**: ninguna trae señal de stock en el grid. Mismo
caso que Sparta — hay que verificar si ocultan el agotado (entonces no cuesta
nada) o lo listan como disponible (entonces el `in_stock` ciego sí engaña).

## El cambio de código que desbloqueó Speedo y Trek

`magento_html.parse_listing` tenía **hardcodeado** `a.product-item-link` para el
nombre y la URL, y `form[data-product-sku]` para el SKU. En Speedo y Trek ese
enlace **no existe**: el nombre vive en el elemento que lleva `data-product-sku`
y la URL en el enlace de la foto (`a.product-item-photo`).

El síntoma era el peor posible: el parser **encontraba el grid, enumeraba las 33
filas, leía el total declarado y el número de páginas** — y emitía **cero
productos**, porque cada fila fallaba el contrato de nombre+URL. Un `enumerated`
sano con `emit=0` no lo ve ninguna guarda: el canario compara enumerado contra
declarado y ahí todo cerraba.

Se agregaron tres atributos por tienda al lado del `brand_selector` que ya
existía —`name_selector`, `url_selector`, `sku_selector`— con los defaults
exactamente en el comportamiento de hoy. Los 40 tests de la familia pasan sin
cambios.

Para Speedo y Trek la configuración es:

```python
name_selector = "[data-product-sku]"
url_selector = "a.product-item-photo"
sku_selector = "[data-product-sku]"
```

🔴 **Weplay queda afuera y la razón es de dominio, no de selectores**: su grid
**no publica el SKU de la tienda** en ninguna parte (1 de 36 filas lo trae, y lo
que trae —`045496591779`— parece un EAN). Sin SKU no hay `store_sku` estable, y
derivarlo del `id` interno de Magento rompería la serie en la primera
reindexación del catálogo. Es la misma razón por la que `shopify_family` usa el
`id` de variante y no el `sku` del comerciante.

## Las llaves del grupo A, medidas sobre SKUs reales

Barrí **las hojas de catálogo con el parser de producción** (misma receta que
Sparta y Colloky): descubrir el árbol por jerarquía, enumerar la página 1 de cada
hoja, cruzar los `store_sku`.

| tienda | hojas barridas | ok | MB | seg | SKUs únicos | dup bruta |
|---|---|---|---|---|---|---|
| speedo | 107 | 103 | 33 | 124 | **425** | 4,71× |
| trekbikeschile | 140 | 138 | 41 | 177 | **527** | 3,64× |
| newbalance | 258 | 219 | 92 | 310 | **1.408** | 3,35× |

Y el mismo diagnóstico que en Sparta: **la duplicación bruta es vitrinas**. Al
quedarse solo con los ejes de catálogo:

| tienda | ejes de catálogo | hojas | cobertura | **dup residual** |
|---|---|---|---|---|
| **speedo** | `equipamiento`, `lentes`, `hombre`, `mujer`, `ninos` | 70 | **383 / 425 = 90,1%** | **1,15×** |
| **trekbikeschile** | `equipamiento`, `montana`, `ruta`, `gravel`, `urbana`, `bicicletas-electricas`, `accesorios-ciclismo`, `ninos` | 93 | **513 / 527 = 97,3%** | **1,05×** |
| **newbalance** | `deportes`, `hombre`, `mujer`, `ninos`, `ropa`, `running`, `zapatillas` | 81 | 909 / 1.408 = **64,6%** | 1,87× |

Las vitrinas descartadas son las mismas tres en speedo y trek (`destacado`,
`cyber`, `sale`) y seis en newbalance (`cyber`, `destacados`, `grey-days`,
`mas-vendidas`, `recien-llegados`, `sale`). Que son vitrinas lo dice la medición,
no el nombre: `destacado` solapa 36-55% con **todos** los demás ejes de speedo, y
en trek `destacado × ninos` y `cyber × accesorios-ciclismo` dan **100%** — los
ejes chicos están contenidos enteros ahí.

🟢 **speedo y trek quedan resueltas**: 1,15× y 1,05× de solapamiento residual es
tan bueno como lo mejor del repo, y 90% y 97% de cobertura.

⚠️ **New Balance plantea una decisión de producto, no técnica.** Sus vitrinas
tienen **499 SKUs exclusivos de 1.408 — el 35% del catálogo solo es alcanzable a
través de `cyber` y `mas-vendidas`**. Las dos opciones tienen costo:

- **Excluirlas** (lo recomendado por defecto) deja la tienda en 909 SKUs y
  **1,87×** de duplicación residual, que sigue siendo alto.
- **Incluir una vitrina** recupera el 35% y trae la trampa de Prat: el comerciante
  la reedita y mata series sin avisar —240 listings en ese caso, y el canario solo
  se queja ~4 corridas—. Y en una tienda con `paginates = False` la vitrina es
  además el único lugar donde esos SKUs aparecen, así que al reeditarla
  desaparecen del todo.

### ✅ Decidido (dueño, 2026-11-05): **se excluyen las vitrinas**

New Balance entra con sus **81 hojas de catálogo** (`deportes`, `hombre`, `mujer`,
`ninos`, `ropa`, `running`, `zapatillas`), **909 SKUs** y **1,87×** de
solapamiento residual, **asumiendo la pérdida del 35%**. Las seis vitrinas
(`cyber`, `destacados`, `grey-days`, `mas-vendidas`, `recien-llegados`, `sale`)
quedan fuera de `store_categories`.

Lo que hay que anotar en la migración para que nadie "mejore" esto después: los
499 SKUs que no entran **no son un bug ni un faltante de cobertura** — es la
decisión de no construir series sobre una vitrina que el comerciante puede
reeditar, que es exactamente lo que le pasó a Prat con `herramientas-electricas`
(240 listings muertos de golpe, y el canario callado a las 4 corridas).

⚠️ Y queda una decisión abierta aparte: **New Balance es la única de la tanda
conectable por dos familias** (Magento, verificado parseando; o Salesforce, por su
firma de Demandware). Por Magento cuesta cero porque la familia ya existe, y es el
camino recomendado.

### Dos datos transversales del grupo A

- **`price_normal` en 39-42%** (speedo 41,5%, trek 42,4%, newbalance 39,5%) ⇒ **θ
  se puede fijar midiendo** en las tres, igual que en Sparta.
- 🔴 **`sin_stock = 0` en las tres**, sobre 2.000, 1.917 y 4.722 filas. Ninguna
  trae señal de stock en el grid. Hay que verificar si ocultan el agotado (como
  Sparta y Colloky, y entonces no cuesta nada) o lo listan (como Paris, y entonces
  el `in_stock` ciego engaña).
- **Precio máximo**: speedo $599.990, newbalance $249.990, **trek $10.990.000**
  (una bicicleta de ruta). Ninguno roza `MAX_PLAUSIBLE_CLP`, pero el de trek
  merece una nota: ⚠️ con `compute_score` ciego al precio absoluto, un 30% sobre
  una bici de $10,9M son **$3,3M de ahorro puntuando igual** que un 30% sobre unos
  anteojos de natación de $39.990. Es el mismo choque de rango de ticket que trajo
  el supermercado y que tiene Colloky al revés, y la respuesta por precedente es
  la misma: **destino propio**, no tocar el score.

## Las llaves del grupo B (`Crawl-delay: 3`), medidas

Mismo método, a 0,33 rps. **803 hojas, 556 MB, 51 min.**

| tienda | hojas | ok | universo p1 | dup bruta | ejes de catálogo | hojas cat. | cobertura | **dup residual** |
|---|---|---|---|---|---|---|---|---|
| **mammut** | 193 | **193/193** | 475 | 3,78× | `accesorios`, `calzado`, `equipamiento-mammut`, `hombre`, `mujer` | 97 | **465 = 97,9%** | **1,27×** |
| **marmot** | 144 | **144/144** | 319 | 3,68× | + `ni-os` | 77 | **296 = 92,8%** | **1,24×** |
| **thenorthface** | 196 | 186/196 | 1.269 | 3,61× | `equipamiento`, `hombre`, `mujer`, `ni-os`, `zapatos` | 113 | **1.211 = 95,4%** | **1,40×** |
| **kliper** | 270 | 269/270 | 2.462 | 2,02× | `accesorios`, `hombre`, `mujer`, `ni-os`, `zapatos-zapatillas` | 111 | 1.576 = **64,0%** | 1,26× |

🟢 **mammut, marmot y thenorthface quedan resueltas**: 1,24× a 1,40× de
solapamiento residual con 93-98% de cobertura, y sus vitrinas aportan apenas **10,
23 y 58 SKUs exclusivos** respectivamente — o sea descartarlas no cuesta
prácticamente nada. mammut y marmot además barrieron **sin un solo error** (193/193
y 144/144).

⚠️ **Kliper repite el problema de New Balance y más grande**: sus vitrinas tienen
**886 SKUs exclusivos de 2.462 (36%)**, y el grueso está en el eje **`marcas`
(670 SKUs)** — que no es una vitrina de promoción sino **el eje de marca**, o sea
la forma natural de navegar un multimarca. Clasificarlo como vitrina y descartarlo
pierde más de un tercio del catálogo; incluirlo lo pone a solapar con `hombre` y
`mujer` (684 y 732 SKUs). Es la misma decisión que se tomó en New Balance
—excluir— pero acá el costo es mayor y el eje descartado es legítimo.

### ⚠️ Una aclaración importante sobre estos porcentajes

El barrido lee **solo la página 1** de cada hoja, igual que en Sparta. Para el
grupo A eso es el techo real, porque esas tiendas **no paginan**
(`Disallow: /*?`). **Para el grupo B no lo es**: las cuatro paginan, así que el
adaptador en producción va a recolectar mucho más que lo medido acá. Kliper
declara **13.769 productos** en `/marcas` y yo vi 2.462.

⇒ De esta medición hay que leer **qué llaves usar** (el solapamiento residual, que
sí es válido porque compara los mismos conjuntos), **no cuánto catálogo se
alcanza**. La cobertura real la da la paginación y hay que dimensionarla aparte:
a 24 por página, las 111 hojas de catálogo de Kliper con sus totales declarados
son del orden de **cientos de requests por pasada**, que es el número que hay que
comparar contra el presupuesto de 1 h.

### Transversales del grupo B

- 🟢 **`price_normal` entre 36,5% y 64,8%** (thenorthface 36,5%, kliper 51,3%,
  mammut 55,3%, marmot 64,8%) ⇒ θ medible en las cuatro.
- 🔴 **`sin_stock = 0` en las cuatro**, sobre 4.586, 4.972, 1.797 y 1.173 filas.
  Ninguna trae señal de stock en el grid — igual que el grupo A y que Sparta.
- ⚠️ **`thenorthface` tiene un precio máximo de $6.999.990**, muy por encima del
  resto de outdoor ($1,0M a $1,8M). Vale mirar qué es antes de conectarla: o es
  equipamiento de expedición legítimo, o es un centinela, y la diferencia importa
  porque un valor así **envenena la baseline de ese SKU de forma permanente**.
- Las 10 `NotAListingPage` de thenorthface son rutas de su nav que no son catálogo
  (el mismo caso de `/tiendas` y `/ayuda`), no un fallo del parser.

## ⚠️ Kliper es el distribuidor de otras tres de la lista

`kliper.cl` declara **13.769 productos** en `/marcas` y su propio menú enlaza
`/marcas/the-north-face`, `/marcas/marmot`, `/marcas/mammut` y
**`/marcas/andesgear`** — o sea vende las marcas de tres de las candidatas de esta
tanda **y de una tienda ya conectada**. Sumado a que las cuatro comparten el
`robots.txt` carácter por carácter, lo más probable es que sean **un solo operador
con cuatro storefronts de marca más el multimarca**.

Qué implica, y no es menor:

1. **El mismo producto va a existir como listing en Kliper y en la tienda de su
   marca.** Para la serie no es un problema —son `store_id` distintos, cada uno
   con su propio p50— pero para el **canal** significa que la misma oferta puede
   salir dos veces con dos precios. Eso lo acota `MAX_PER_STORE_PER_DAY`, no el
   detector.
2. **Conectar Kliper y las tres marcas es contar el mismo catálogo cuatro
   veces** en el presupuesto de pasada. Si hay que elegir, Kliper sola cubre más
   (13.769 contra 1.014 + 235 + 208).
3. ⚠️ **Y su `/marcas` con 574 páginas no es una llave usable**: a 24 por página
   son 574 requests para una sola llave. Las llaves tienen que ser las hojas de
   marca o de categoría, nunca ese paraguas.

## Viajes: cuatro sitios vivos, ninguno es catálogo todavía

| sitio | estado | plataforma |
|---|---|---|
| `cocha.com` | 200, robots 200 | sin determinar |
| `travelsecurity.cl` | 200, robots 200 | sin determinar |
| `denomades.com` | 200, robots 200 | **Next.js** |
| `cruceros.cl` | 200 (1,4 MB), robots 200 | sin determinar |
| `turismocity.cl` | 200 **solo con `BROWSER_HEADERS`**, `Crawl-delay: 15` | sin determinar |
| `kayak.cl` | 200 | sin determinar |
| `viajesfalabella.cl`, `despegar.cl`, `atrapalo.cl`, `viajeselcorteingleslatam.com` | 🔴 sin 200 | — |

Ninguna tiene aún una ruta de catálogo verificada, así que **no hay veredicto de
viabilidad**. Lo que sí se puede decir ya, cruzando con `PLAN_EXPANSION.md` §6:

- **`kayak.cl` y `turismocity.cl` son metabuscadores de vuelos y hoteles** → caen
  de lleno en lo que §6.3 dice no construir: precio por fecha de viaje, serie 2-D,
  otro detector.
- **`cruceros.cl` y `denomades.com` son las dos candidatas que importan**: la
  primera anuncia "más de 9.000 ofertas de cruceros" (una zarpada es un SKU con
  fecha fija) y la segunda es tours y actividades (precio por producto, sin fecha
  en el precio). Son exactamente los dos casos de §6.2.
- **`cocha.com` y `travelsecurity.cl` son agencias mixtas**: tienen packs (lo que
  entra) junto con vuelos y hoteles (lo que no). Habría que acotar la llave a la
  sección de paquetes.

⚠️ **Y la pregunta que decide la vertical sigue sin responder**, la de §6.2: **¿el
SKU de un pack sobrevive 30 días?** Antes de escribir un adaptador de viajes hay
que mirar si los packs publicados hoy siguen publicados en un mes. Si no, no hay
baseline posible y **ningún adaptador lo arregla**.

## Dominios que no son tienda (tanda 2)

| dominio | qué es |
|---|---|
| `tecnoshop.cl` | 🔴 **secuestrado**: sirve "MB66 NIKO — Trang Chủ", sitio vietnamita de apuestas |
| `ggames.cl` | 🔴 **secuestrado**: "1win Casino Online y Apuestas Deportivas" |
| `pcofertas.cl` | dominio **en venta** ("esta disponible \| Dominios") |
| `solotodo.cl` | **comparador**, no tienda: su precio es de terceros y no tiene serie propia. Ya lo advierte `PLAN_EXPANSION.md` §2.2 |
| `nicetech.cl`, `dustin.cl`, `hardwaremix.cl`, `mercadopc.cl`, `sonicpc.cl`, `istyle.cl`, `nexus.cl`, `cyberpc.cl`, `intcomex.cl`, `ttec.cl`, `nilsentours.cl`, `crucerostotal.cl` y 5 más de viajes | **DNS no resuelve** |
| `progaming.cl`, `intelec.cl`, `gamerzone.cl`, `macstore.cl`, `prisa.cl`, `tecnoglobal.cl`, `nortechile.cl`, `solucionesit.cl` | sin 200 en ápex ni `www` |

## Lo que falta para conectar cualquiera de estas

Nada de esta tanda está listo para una migración. Por tienda falta:

1. **Las llaves, y que sean disjuntas sobre SKUs reales.** Es la medición que más
   cuesta y la que más caro sale omitir. En Magento se puede hacer con el parser
   real, como se hizo con Sparta (545 hojas) y Colloky.
2. **Si ocultan o listan el agotado** (las 7 Magento dan `sin_stock = 0`).
3. **Un fixture con payload real** y, si la tienda lista agotados, que los
   incluya.
4. **La fila en `stores` + `store_categories`**, con fecha de conexión anotada y
   evaluación a +30 días.
5. Para `casaroyal`, `asics`, `volkanica`, `stanley1913` y `underarmour`: las doce
   preguntas, de las que hoy solo está respondida la 1.
