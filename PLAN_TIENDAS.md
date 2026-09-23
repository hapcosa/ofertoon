# Plan de expansión de tiendas — Ofertoon

Estado del documento: **2026-09-23**. Verificado con `curl` contra los sitios
reales ese día, no con memoria ni con documentación de terceros.

Punto de partida: 6 tiendas, 19.052 listings, 50 días de historia. La hipótesis
que motiva esta expansión es que **el tamaño del catálogo no predice la cantidad
de ofertas reales** — y los datos propios la sostienen:

| Tienda | Listings | Aceptados | Aceptados / 1.000 listings |
|---|---:|---:|---:|
| Paris | 4.718 | 1.304 | **276** |
| PC Factory | 586 | 170 | **290** |
| SP Digital | 640 | 117 | **183** |
| Easy | 2.111 | 366 | 173 |
| Sodimac | 1.965 | 228 | 116 |
| Falabella | 9.032 | 740 | **82** |

Falabella tiene el doble de catálogo que Paris y produce un tercio de la tasa de
ofertas reales. Las tiendas chicas y medianas rinden más por SKU. Eso es lo que
este plan persigue.

---

## 1. Las tres restricciones que ordenan todo el plan

Antes de la lista de tiendas, porque cambian el orden de implementación.

### 1.1 Una tienda nueva no publica nada durante 30 días

`MIN_POINTS=30` y `MIN_DAYS=30` son un rechazo, no un default. Cualquier tienda
que se conecte hoy entrega su primera oferta a fines de octubre. **Ninguna
tienda de este plan afecta la calibración de θ del 2026-10-02.**

Corolario útil: esos 30 días de espera son gratis y hay que gastarlos en
paralelo, no en serie. Conviene conectar temprano y evaluar después, en vez de
estudiar la tienda antes de conectarla.

### 1.2 La espera de 30 días ES el test de estabilidad de catálogo

Una tienda que rota SKUs no acumula 30 días por producto y nunca publica nada,
por grande que sea su catálogo. No hace falta un estudio previo: se conecta, se
esperan 30 días y se mide `listing_baselines.n_days >= 30` **sobre la cohorte de
listings que tuvieron la oportunidad de madurar** — no sobre el catálogo vivo,
que incluye a los recién llegados y confunde crecimiento con rotación (§Fase 0).
Ese número es el criterio de aceptación de cada tienda nueva.

### 1.3 La taxonomía actual **no tiene ropa ni deportes**

La tabla `categories` tiene 7 filas y todas son tecno / ferretería / hogar:

```
tecno-notebooks   θ=0.150     ferre-herramientas  θ=0.250
tecno-celulares   θ=0.150     ferre-jardin        θ=0.250
tecno-componentes θ=0.150     hogar-electro       θ=0.200
tecno-tv          θ=0.180
```

Agregar una tienda de ferretería o tecnología es **un adaptador**. Agregar una
de ropa o deportes es **un adaptador + categorías nuevas + θ nuevos sin
calibrar + su propia ventana de 30 días + su propia calibración**. No es el
mismo trabajo y no debería ir en la misma fase.

Y hay un problema de dominio, no de ingeniería, que hay que resolver antes de
escribir una línea de ropa: **la liquidación de fin de temporada es un descuento
real que se ve exactamente como un escalón permanente**, que es justo el patrón
que `backtest.py` etiqueta como `fake`. El detector, tal como está, va a
rechazar las mejores ofertas de vestuario o a etiquetarlas mal. Eso se decide
antes, no durante.

---

## 2. Catálogo de tiendas por categoría

Leyenda de **Vía**: cómo se extraen los datos, verificado el 2026-09-23.
Leyenda de **Costo**: esfuerzo de adaptador, asumiendo que la familia de
plataforma ya existe (`XS` = fila en `stores` + fixture; `L` = adaptador propio).

### 2.1 Ferretería, construcción y taller

La categoría más densa de la lista, la que mejor calza con θ=0.250 ya existente,
y donde caen las cuatro tiendas que aportaste.

| Tienda | Plataforma | Vía verificada | Costo | Nota |
|---|---|---|---|---|
| **Ferretek** (`ferretek.cl`) | Magento 2 | ✅ **REST abierta sin token**: `/rest/V1/products` → **48.454 productos**, con `price`, `sku`, `marca` | **S** | El `sku` parece EAN-13 (`2615000001008`) → identidad posible. Catálogo de repuestos de maquinaria (Stens, Oregon, Rotary): muy de nicho |
| **Urban Comercial** (`urbancomercial.cl`) | WooCommerce | ✅ **Store API pública**: `/wp-json/wc/store/v1/products` → JSON con precio y stock | **S** | Herramientas de marca (Dewalt visto en el primer item) |
| **Ferretería Prat** (`ferreteriaprat.cl`) | Shopify | ✅ `/products.json?limit=250&page=N` | **S** | Trae `variants[].available` → **`in_stock` real** |
| **Construmart** (`construmart.cl`) | Magento 2 | REST **cerrada** (`consumer isn't authorized`) → grid HTML `?p=N` | **M** | Cadena nacional, la más grande de las no integradas |
| **Kupfer** (`kupfer.cl`) | Magento 2 | REST cerrada → grid HTML | **M** | Ferretería industrial |
| **Kruuse** (`kruuse.cl`) | Next.js App Router | Payload RSC (`self.__next_f`), sin API JSON encontrada. Rutas `/cl/categories/<slug>` | **L** | Importador Scheppach. Catálogo chico y muy específico |
| **Chilemat** (`chilemat.cl`) | sin determinar | HTTP 200, plataforma no identificada. Declara `Crawl-delay` en robots | **M?** | Requiere una sesión de inspección |
| **MTS** (`mts.cl`) | — | ❌ **HTTP 403** a UA de Chrome | **L** | Anti-bot. No en las primeras fases |
| **Imperial** (`imperial.cl`) | — | ❌ **HTTP 520** persistente (Cloudflare no alcanza el origen) | **?** | Puede ser caída temporal o bloqueo de IPs de datacenter. **Reintentar antes de descartar** |

*(Sodimac y Easy ya están integradas.)*

### 2.2 Deportes y outdoor

Categoría **nueva** en la taxonomía. Dos tiendas son casi gratis si existe la
familia Shopify.

| Tienda | Plataforma | Vía verificada | Costo | Nota |
|---|---|---|---|---|
| **Doite** (`doite.cl`) | Shopify | ✅ `/products.json` | **XS** | Camping, carpas, sacos |
| **Lippi** (`lippioutdoor.com`) | Shopify | ✅ `/products.json` | **XS** | Ropa y equipo outdoor |
| **Sparta** (`sparta.cl`) | Magento 2 | REST cerrada → grid HTML. `Crawl-delay: 1` | **M** | La cadena deportiva nacional |
| **Andesgear** (`andesgear.cl`) | Magento 2 | REST cerrada → grid HTML | **M** | Outdoor de marca |
| **Mountain** (`mountain.cl`) | sin determinar | HTTP 200 | **M?** | |
| **Decathlon** (`decathlon.cl`) | — | ❌ HTTP 403 | **L** | La más valiosa de la categoría y la más difícil |
| **Nike** (`nike.cl`) / **Adidas** (`adidas.cl`) | — | ❌ HTTP 403 | **L** | Tiendas de marca, descuentos reales frecuentes |

### 2.3 Computación y tecnología

Categoría ya existente en la taxonomía (θ=0.150–0.180), pero **ya cubierta por
SP Digital y PC Factory**, que son justamente las dos de mejor rendimiento por
SKU. El margen de mejora acá es el más bajo del plan.

| Tienda | Plataforma | Vía verificada | Costo | Nota |
|---|---|---|---|---|
| **Winpy** (`winpy.cl`) | sin determinar | HTTP 200. **`Crawl-delay: 10`** en robots → `rate_limit_rps = 0.1` | **M** | El delay obliga a un presupuesto de fetches muy chico |
| **MacOnline** (`maconline.com`) | sin determinar | HTTP 200 | **M** | Apple premium reseller: catálogo chico, precios estables, pocas ofertas reales esperables |
| **Nice One** (`niceone.cl`) | — | ❌ HTTP 403 | **L** | |
| **PC Express** (`pcexpress.cl`) | — | ❌ HTTP 403 | **L** | |

### 2.4 Ropa y vestuario

Categoría **nueva** en la taxonomía + el problema de liquidación descrito en
§1.3 sin resolver. Alto costo conceptual, no técnico.

| Tienda | Plataforma | Vía verificada | Costo | Nota |
|---|---|---|---|---|
| **Colloky** (`colloky.cl`) | VTEX | ✅ **API de catálogo pública**: `/api/catalog_system/pub/products/search` — confirmada devolviendo productos | **S** | Ropa infantil. Es el mejor banco de pruebas para escribir `vtex_family.py` |
| **Hites** (`hites.com`) | Salesforce CC | Grid HTML paginado | **M** | |
| **La Polar** (`lapolar.cl`) | Salesforce CC | Grid HTML paginado | **XS** tras Hites | |
| **Tricot** (`tricot.cl`) | Salesforce CC | Grid HTML paginado | **XS** tras Hites | |
| **ABCDin** (`abcdin.cl`) | Salesforce CC | Grid HTML paginado | **XS** tras Hites | Mixta: ropa + tecno + electro, encaja en categorías ya existentes |
| **Foster** (`foster.cl`) | Next.js | sin determinar | **L** | |
| **Dafiti** (`dafiti.cl`) | sin determinar | HTTP 200 | **M** | Marketplace de moda: precio por vendedor, mismo ruido que MercadoLibre |
| ~~Corona~~ | — | — | — | **Cerró en julio de 2025.** Descartada |

### 2.5 Retail general

| Tienda | Plataforma | Vía verificada | Costo | Nota |
|---|---|---|---|---|
| **Ripley** (`ripley.cl`) | Next.js custom | sin API pública encontrada | **L** | **El hueco más grande del sistema**: tercer retailer del país, ausente |
| **Tottus** (`tottus.cl`) | Next.js | ❌ HTTP 403 con www | **L** | |
| **Lider** (`lider.cl`) | custom Walmart | sin API pública | **L** | |

*(Falabella y Paris ya están integradas.)*

### 2.6 Supermercado, farmacia y belleza

**Decisión de producto pendiente, no de ingeniería.** Un canal VIP de ofertas
reales de herramientas y tecnología tiene sentido; uno que mezcla shampoo y
detergente es otro producto. Además el precio unitario bajo hace que un 25% de
descuento sea $800 de ahorro: el ranker lo va a ordenar mal salvo que se le
agregue un piso absoluto de ahorro en CLP.

| Tienda | Plataforma | Vía |
|---|---|---|
| Jumbo (`jumbo.cl`) | VTEX + front Next | API de catálogo no respondió en la ruta estándar; requiere inspección |
| Preunic (`preunic.cl`) | Next.js | sin determinar |
| Salcobrand (`salcobrand.cl`) | sin determinar | sin determinar |
| Maicao (`maicao.cl`) | Salesforce CC | grid HTML |

### 2.7 Agregadores — no son tiendas y no se publican

| Fuente | Estado | Para qué sirve |
|---|---|---|
| **SoloTodo** (`publicapi.solotodo.com`) | ✅ responde **sin token** | Hace historia de precios de retail chileno. Es el **único tercero independiente contra el cual validar el detector** cuando se calibre θ el 2-oct. No como fuente de publicación |
| **MercadoLibre** (`api.mercadolibre.com`) | ❌ **403 sin OAuth** desde 2025 | Catálogo enorme, pero marketplace: el precio es por vendedor y la baseline por SKU se rompe. Baja prioridad |

---

## 3. Las cuatro familias de adaptador

El ahorro real del plan no está en el orden de las tiendas sino en agrupar por
plataforma. `falabella_family.py` ya demuestra el patrón: un adaptador, dos
tiendas, solo cambia la `base_url`.

| Familia | Tiendas que cubre | Endpoint | Regalo que trae |
|---|---|---|---|
| **`shopify_family.py`** | Prat, Doite, Lippi (+ decenas de tiendas chilenas medianas) | `/products.json?limit=250&page=N` | `variants[].available` → **primer `in_stock` no ciego del sistema** |
| **`woo_family.py`** | Urban Comercial (+ cualquier Woo con Store API) | `/wp-json/wc/store/v1/products` | precio y stock en el mismo JSON |
| **`vtex_family.py`** | Colloky (+ los VTEX que se confirmen) | `/api/catalog_system/pub/products/search?_from=&_to=` | **EAN** en el payload → identidad de producto |
| **`sfcc_family.py`** | Hites, La Polar, Tricot, ABCDin, Maicao | grid HTML paginado | 5 tiendas por un adaptador |
| **`magento_html.py`** | Construmart, Kupfer, Sparta, Andesgear | grid HTML `?p=N&product_list_limit=N` | 4 tiendas por un adaptador |
| *(caso propio)* | Ferretek | `/rest/V1/products` abierta | es Magento pero con REST abierta: no comparte código con el grid HTML |

**Limitación conocida de Shopify**: `products.json` **no expone `barcode`**
(verificado en Doite). Trae `sku` y `price` enteros, pero la identidad solo
puede salir de marca+modelo. Por la regla 6 del dominio, eso significa que estas
tiendas aportan señal pero casi no aportan comparación cross-store.

---

## 4. Plan de implementación, categoría por categoría

Cada fase entrega tiendas en producción, no código en una rama. El criterio de
salida de cada fase se mide **30 días después** de conectarla.

### Fase 0 — Higiene previa (antes de cualquier tienda nueva) ✅ 2026-09-23

No agrega tiendas; hace que agregarlas no ensucie las señales que ya existen.

1. **Arreglar el 404 de paginación de Easy.** ✅ Easy responde HTTP 404 —no el
   shell sin productos que el adaptador ya sabía manejar— a la primera página
   pasada del final (verificado en vivo: `sierras-electricas` página 8 → 200,
   página 9 → 404). El `FetchError` escapaba de `discover` y el runner marcaba
   `failed` la categoría entera.

   **Era peor que ruido**: el lote pendiente en el buffer del runner se perdía,
   así que cada corrida fallida tiraba entre 20 y 99 observaciones **ya
   scrapeadas** (`items_seen` 499 vs `items_ok` 400). Tres categorías × 2
   pasadas/día × ~50 días. Se ve en el dato: `ferre-herramientas` de Easy tiene
   28% de listings maduros contra 42–45% de sus otras dos categorías.

   Fix en dos partes: `FetchError.status_code` para que un adaptador pueda leer
   el status sin parsear el mensaje, y el guard en `easy.py` con el mismo
   criterio que `NotAListingPage` (404 en página 1 = `store_key` mal
   configurado y grita; más allá = fin de catálogo). Además el runner ahora
   persiste el buffer pendiente aunque el adaptador reviente, que era el
   agujero de fondo.
2. **Criterio de aceptación de tienda nueva** ✅ →
   `scripts/aceptacion_tienda.py`. Validado contra los 6 listings conocidos.
3. **Checklist reutilizable por tienda** ✅ — §5 de este documento, referenciado
   desde `CLAUDE.md` §Agregar una tienda con las tres trampas no obvias.

**Criterio de salida:** ✅ 8/8 targets de Easy en `ok` en una pasada completa
(antes fallaban taladros, sierras y motosierras).

**Decisión resuelta (2026-09-23):** el criterio transversal daba `APAGAR` para
Easy (34%) y salvaba raspando a Falabella (41%), cuando Easy produce 175
aceptados por cada 1.000 listings y Falabella 84. No era el umbral: **era el
denominador**.

Medir `maduros / listings con baseline` mete a los SKUs recién llegados en el
denominador, y esos no maduraron por ser nuevos, no por rotación. El indicador
hacía ver idéntica a la tienda que **crece** su catálogo y a la que lo **rota**.
El 65% del catálogo de Easy tenía menos de 30 días.

Corregido a una **cohorte**: solo los listings nacidos hace más de `MIN_DAYS`
—los que tuvieron la oportunidad de madurar— y hace menos de
`VENTANA_COHORTE_DIAS = 90`, para que el catálogo muerto histórico no hunda el
indicador con el paso del tiempo. El orden se invierte y pasa a coincidir con el
rendimiento por SKU:

| Tienda | Transversal | **Cohorte** | Supervivencia | Nuevos <30d | Acept./1.000 |
|---|---:|---:|---:|---:|---:|
| Easy | 34% | **96%** | 91% | 65% | 175 |
| PC Factory | 61% | **73%** | 66% | 16% | 295 |
| Paris | 56% | **71%** | 68% | 20% | 281 |
| Sodimac | 63% | **71%** | 66% | 11% | 116 |
| SP Digital | 52% | **64%** | 62% | 19% | 186 |
| Falabella | 41% | **51%** | 55% | 20% | 84 |

Maduración por cohorte y supervivencia son casi el mismo número en las seis: un
listing madura si y sólo si sigue vivo, que es la confirmación de que lo que el
indicador mide es rotación. Easy queda **prendido**; la tienda que de verdad
rota catálogo es Falabella, y se mantiene igual por volumen absoluto.

El umbral del 40% se conserva sin cambio: sobre la cohorte pasan las seis, y
Falabella al 51% marca el piso real observado. Sigue **sin calibrar** — se
revisa cuando haya media docena de tiendas nuevas medidas con esta consulta.

---

### Fase 1 — Ferretería (la categoría de tus cuatro links) — 1a ✅

Es la primera porque: θ=0.250 ya existe y no hay taxonomía nueva que inventar;
tres de las tiendas tienen **API JSON abierta y verificada**; y es donde tu
hipótesis de "las grandes no tienen las mejores ofertas" es más probable que sea
cierta, porque Sodimac y Easy son justamente las dos de peor rendimiento por SKU
después de Falabella.

**1a. Las tres con API abierta** ✅ **2026-09-23** — una familia nueva cada una,
y las tres familias se reusan después:

| Orden | Tienda | Entrega | Conectado |
|---|---|---|---|
| 1 | **Ferretería Prat** | `scrapers/stores/shopify_family.py` + fixture + migración 15 | 2 colecciones, 344 items |
| 2 | **Urban Comercial** | `scrapers/stores/woo_family.py` + fixture + migración 16 | 1 categoría, 223 items |
| 3 | **Ferretek** | `scrapers/stores/ferretek.py` + fixture + migración 17 | 7 categorías, 3.302 declarados |

Lo que se aprendió conectándolas, que cambia lo que decía este plan:

- **El solapamiento de categorías es el riesgo real de esta fase, no el
  volumen.** Las tres tiendas anidan sus categorías y las vitrinas
  (`Ofertas`, `Outlet`, `Marcas`, `Despacho Gratis`) repiten los mismos
  productos. Dos llaves solapadas producen dos `price_points` por pasada para
  el mismo listing, y como `compute_baseline` saca el p50 de los puntos crudos,
  ese SKU pesa el doble en su propia mediana. Es el mismo daño que reparó
  `scripts/repair_oversampling.py`. **Toda llave nueva se verifica disjunta
  contra las ya conectadas, sobre SKUs reales**, antes de entrar a la migración.
- **Los 48.454 de Ferretek eran un número de tabla, no de catálogo.** El árbol
  declara 10.333 bajo la raíz `Herramientas`; el resto son repuestos de
  maquinaria sin categoría visible. Conviene leer `/rest/V1/categories` antes de
  asustarse con un `total_count`.
- **El `in_stock` real llegó a medias.** Prat sí discrimina (172 de 344
  variantes agotadas). Urban trae el campo pero oculta lo agotado del listado,
  así que da 223 de 223 en stock — igual es mejor que la ceguera de
  Paris/Falabella: el producto agotado desaparece y su serie queda con un hueco,
  en vez de registrar un precio con `in_stock` inventado. Ferretek no trae stock
  y queda ciega como Paris.
- **La identidad mejoró donde no se esperaba.** El plan daba a Woo como "precio
  y stock"; Urban expone EAN y Marca como atributos. Y Ferretek trae GTIN en el
  97%, que la vuelve la mejor fuente de matching cross-store del sistema.
- **Confirmación de la regla 1 con dato propio**: el `compare_at_price` de Prat
  declara **exactamente 10,0% en 249 de 250 productos**, rango 10,0%..10,0%. No
  es un descuento: es un margen fijo sobre todo el catálogo.

**1b. Las dos de grid HTML:**

| Orden | Tienda | Entrega |
|---|---|---|
| 4 | **Construmart** | `scrapers/stores/magento_html.py` + fixture + fila |
| 5 | **Kupfer** | solo fixture + fila (reusa la familia) |

**1c. Investigación, sin compromiso de entrega:**

- **Imperial**: reintentar. Si el 520 persiste una semana, es bloqueo, no caída.
- **Chilemat** y **Kruuse**: una sesión de inspección cada una para decidir si
  el adaptador vale lo que cuesta. Kruuse en particular es payload RSC de Next
  App Router: frágil y de catálogo chico.
- **MTS**: 403. Queda para la Fase 6.

**Criterio de salida (30 días después):** cada tienda con ≥40% de su **cohorte**
(los listings nacidos hace más de 30 días) con `n_days >= 30`, y ≥1 candidato aceptado propio. Las que no lleguen, se
desactivan.

---

### Fase 2 — Deportes y outdoor

Va segunda porque **Doite y Lippi son costo XS**: reusan la familia Shopify de
la Fase 1 sin escribir un adaptador. Es la mejor relación valor/esfuerzo del
plan completo, pero depende de la Fase 1 para existir.

**Trabajo previo obligatorio** (esto es lo que la hace segunda y no primera):

1. **Migración con categorías nuevas**: `deporte-outdoor`, `deporte-calzado`,
   `deporte-equipamiento` (o la partición que decidas). θ de partida sin
   calibrar, igual que los 7 actuales.
2. **Decidir qué hacer con la liquidación de temporada** (§1.3). Si no se
   resuelve, esta fase publica mal. Opciones a evaluar, no decididas acá:
   ampliar la ventana de baseline más allá de 60d para vestuario, o agregar una
   etiqueta de outcome específica al backtest.

| Orden | Tienda | Costo |
|---|---|---|
| 1 | **Doite** | XS (fixture + fila) |
| 2 | **Lippi** | XS (fixture + fila) |
| 3 | **Sparta** | XS tras Fase 1b (reusa `magento_html`), respetar `Crawl-delay: 1` |
| 4 | **Andesgear** | XS tras Fase 1b |
| 5 | Mountain | investigación |

**Criterio de salida:** el mismo de la Fase 1, **más** una revisión manual de 20
candidatos aceptados para ver si el problema de liquidación apareció.

---

### Fase 3 — Ropa y vestuario

Va después de deportes porque comparte el problema de liquidación y conviene
haberlo resuelto con un catálogo más chico primero. El grueso del trabajo es
**una sola familia que destraba cinco tiendas**.

| Orden | Tienda | Entrega |
|---|---|---|
| 1 | **Colloky** | `scrapers/stores/vtex_family.py` + fixture + fila. **Banco de pruebas de la familia VTEX**, que además trae EAN → identidad |
| 2 | **Hites** | `scrapers/stores/sfcc_family.py` + fixture + fila |
| 3 | **La Polar** | XS |
| 4 | **Tricot** | XS |
| 5 | **ABCDin** | XS — y sus categorías de tecno/electro mapean a la taxonomía **ya existente**, así que rinde desde el día 30 sin θ nuevos |

Requiere migración con categorías `ropa-*` y sus θ.

Dafiti y Foster quedan fuera: marketplace el primero, adaptador propio el
segundo, ninguno justifica el costo frente a las cinco de arriba.

---

### Fase 4 — Ripley

Sola, en su propia fase, porque es **L** y no comparte familia con nada. Es el
único retailer grande ausente y sus categorías mapean a la taxonomía existente,
así que entrega valor desde el día 30 sin θ nuevos.

Es también la tienda con más probabilidad de requerir mantenimiento continuo:
front custom, sin API pública encontrada.

---

### Fase 5 — Tecnología

Deliberadamente tarde. SP Digital (183 aceptados/1.000) y PC Factory (290/1.000)
ya cubren la categoría y son dos de las tres mejores del sistema. Winpy obliga a
`rate_limit_rps = 0.1` por su `Crawl-delay: 10`, y MacOnline tiene catálogo chico
y precios estables. El margen es bajo.

| Orden | Tienda | Nota |
|---|---|---|
| 1 | Winpy | presupuesto de fetches muy acotado por el crawl-delay |
| 2 | MacOnline | pocas ofertas reales esperables |

---

### Fase 6 — Las bloqueadas, y la decisión de supermercado

Todo lo que devuelve 403 hoy: **MTS, Decathlon, Nike, Adidas, Nice One,
PC Express, Tottus**. Son las de mayor valor de marca y las de mayor costo. Una
sola sesión dedicada a resolver el patrón de bloqueo sirve para todas, y es la
única fase donde hay que mirar headers y fingerprint.

**Decathlon es la más valiosa de este grupo** y justifica sola el esfuerzo.

En paralelo: **decidir si supermercado y farmacia son parte del producto**
(§2.6). Si la respuesta es sí, el ranker necesita antes un piso absoluto de
ahorro en CLP.

---

## 5. Checklist por tienda nueva

Idéntico para todas, independiente de la fase. Sale de `CLAUDE.md` §Agregar una
tienda, con lo que este plan agrega.

1. **Inspección**: confirmar la vía (API o grid) y **releer el `robots.txt`**
   ese día. El `rate_limit_rps` sale del `Crawl-delay` declarado, no de lo que
   aguante el servidor.
2. **Adaptador**: módulo en `scrapers/stores/` que implemente `StoreAdapter`.
   Si la familia existe, no se escribe código: solo la fila.
3. **Fixture**: payload **real** en `tests/fixtures/`. Ojo con el engaño de la
   página 1 (el caso Paris/EAN): si el campo aparece solo en los primeros N
   items, el fixture miente.
4. **Migración numerada** con la fila en `stores` y sus `store_categories`,
   mapeadas a la taxonomía canónica. Categorías nuevas → θ de partida explícito
   y anotado como **no calibrado**.
5. **`MAX_PLAUSIBLE_CLP`**: verificar si la tienda usa centinelas como los
   $99.999.999.999 de Falabella. Un centinela envenena la baseline del SKU de
   forma permanente.
6. **Canario**: la primera pasada no tiene historia, así que solo rige el piso
   absoluto de 5 items. Revisar a mano la tercera pasada, cuando la mediana de
   7 corridas empieza a tener sentido.
7. **`docker compose up -d --build scraper`**. El Dockerfile copia las fuentes,
   no las monta.
8. **Anotar la fecha de conexión.** El criterio de aceptación se evalúa 30 días
   después de esa fecha, no antes.

---

## 6. Lo que este plan NO hace

- **No toca θ ni la calibración del 2026-10-02.** Ninguna tienda de acá tiene
  historia suficiente para esa fecha.
- **No resuelve la ceguera de `in_stock` en Paris y Falabella.** Solo agrega
  tiendas donde el stock sí viene (Shopify, Woo). El fix de las existentes sigue
  siendo abrir la ficha del candidato.
- **No agrega fuzzy matching de nombres.** La identidad sigue siendo
  GTIN → marca+modelo → nada. Las tiendas Shopify van a aportar poca identidad y
  eso es aceptable: degrada el copy, no la señal.
