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

Y hay un problema de dominio, no de ingeniería, que había que resolver antes de
escribir una línea de ropa: **la liquidación de fin de temporada es un descuento
real que se ve exactamente como un escalón permanente**, que es justo el patrón
que `backtest.py` etiquetaba como `fake`.

#### DECIDIDO el 2026-10-01: la liquidación es una oferta y va al canal

El precio baja de verdad, el suscriptor compra barato algo que estaba caro. **No
se filtra.** Esto cierra la decisión que este plan dejaba abierta y desbloquea
las Fases 3 y 3b.

Lo que había que corregir no era el detector —ya las aceptaba: `detect_ramp`
exige un alza sostenida ANTES de la baja, y una liquidación baja sin haber
subido, así que `ramp_flag` queda en False—. Era la **medición**: como θ sale del
backtest, etiquetar `fake` una liquidación empujaba θ hacia arriba hasta dejar
afuera justo las mejores ofertas de vestuario y calzado. Se iba a calibrar en
contra de lo que el canal quiere publicar.

La corrección es una tercera etiqueta, `LABEL_LIQUIDATION`, y el discriminante
mira el **pasado**, que es dato duro, no el futuro:

```
el pozo se quedó abajo:
    price <  piso de 60 días  → liquidación: precio nunca visto     → ACIERTO
    price >= piso de 60 días  → inflado que volvió a su nivel real  → falso
```

Dos cosas que la hacen defendible. Una: un candidato **aceptado** ya pasó la
guarda 3 del detector (`ramp_flag` → `reject_reason = 'ramp'`), que es la que caza
el "subo y después descuento", así que entre los aceptados el inflado ya se
filtró antes de llegar al etiquetado. Dos: el inflado-normalizado vuelve a un
nivel que **ya existía** en la ventana (el precio de antes de inflar), mientras
que una liquidación va por debajo de todo lo observado.

El piso se calcula con la serie **hasta ayer** (`backtest.piso_previo`), no con el
`min_60d` de la baseline: la pasada de la mañana ya trae el precio nuevo, así que
ese `min_60d` incluye la bajada y `price < min_60d` nunca se cumpliría. Costó un
test y está fijado.

La liquidación cuenta como acierto en `precision` **y lleva columna propia en el
reporte**, con un aviso cuando pasa la mitad de los aciertos: un canal cuya
precisión viene toda de liquidación es un outlet, no un canal de ofertas, y eso
hay que poder verlo antes de fijar θ.

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
| **Ferretería Prat** (`ferreteriaprat.cl`) | Shopify | ✅ `/products.json?limit=250&page=N` | **S** | Conectada el 2026-09-23. Trae `variants[].available` → **`in_stock` real**. Llaves: `herramientas-y-maquinarias` (1.089) + `jardin` (49); la vitrina `herramientas-electricas` se desactivó en la migración 22 |
| **Construmart** (`construmart.cl`) | Magento 2 | ✅ REST cerrada → grid HTML **con la cookie `persistent_customer_group_id`**: sin ella no hay un solo precio, con ella el grid completo. Pagina con `?p=`, que su robots permite | **S** | Conectada el 2026-09-26, sucursal 35 (DEPARTAMENTAL). 19 llaves, ~217 listings con precio. **Su serie es de esa sucursal** |
| **Kupfer** (`kupfer.cl`) | Magento 2 | ✅ REST cerrada (401) → grid HTML con `data-price-amount` y SKU propio. **Sin `?p=`**: su robots lo prohíbe | **S** | Conectada el 2026-09-24. Ferretería industrial: solo 24 productos mapean a la taxonomía |
| **Kruuse** (`kruuse.cl`) | Medusa + Next | ✅ **`/cl/product-feed.json`**: feed paginado que su propio `llms.txt` ofrece para indexar y su `robots.txt` permite a ClaudeBot. 3.772 productos, `limit` clamea honesto en 100 → 38 requests | **S** | Conectada el 2026-09-26: 24 llaves, 628 listings, **GTIN en el 99%**. Pero **92% del catálogo es `backorder`** (96 de sus 628 listings disponibles): importador de maquinaria que vende a pedido |
| **Chilemat** (`chilemat.cl`) | SPA React + Firebase | ❌ **No vende**: su bundle declara `/noticias`, `/encuentra-ferreteria`, `/ferreterias`, `/concursos`, `/unete-ferretero` y **cero** rutas de producto, carrito, catálogo o precio. El sitemap solo trae páginas institucionales | — | Sitio corporativo de una cadena de franquicias con localizador de locales. **Descartada: no hay catálogo que scrapear** |
| **MTS** (`mts.cl`) | — | ❌ **HTTP 403** a UA de Chrome | **L** | Anti-bot. No en las primeras fases |
| **Imperial** (`imperial.cl`) | — | ❌ **HTTP 403 de Akamai** (`errors.edgesuite.net`) con UA propio, y con UA de navegador el servidor resetea el stream HTTP/2 | **L** | El 520 del primer relevamiento era el mismo WAF. **Descartada: es bloqueo, no caída** → mismo balde que MTS (Fase 6) |

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

#### Auditoría de los 6 supermercados grandes — 2026-10-01

Pedidos explícitamente por producto. **Las seis están bloqueadas o movidas**, y es
el grupo más duro del plan: ninguna tiene hoy una vía limpia. Medido con UA de
navegador:

| Tienda | robots.txt | Vía de catálogo | Veredicto |
|---|---|---|---|
| **Jumbo** | 200, con la firma VTEX (`Disallow: *?map=`) | `/api/catalog_system/pub/*` → **404** en las 4 rutas estándar (`products/search`, `category/tree`, graphql IO, `sessions`). Migró a `provider-jumbo.ecomm.cencosud.com`, que da **403**. `sitemap.xml` sí responde (153 KB) | **L** — sin API pública; quedaría sitemap → ficha por ficha |
| **Santa Isabel** | igual que Jumbo (mismo stack Cencosud) | idéntico: 404 en todas | **L** — se resuelve junto con Jumbo |
| **Lider** | **200, y `Disallow: /search*`** | `super.lider.cl/search?q=` responde **200 con precios en `__NEXT_DATA__`** (996 KB, contiene `priceInfo`) — o sea que técnicamente funciona | ⚠️ **DECISIÓN, ver abajo** |
| **aCuenta** | ConnectError + `CERTIFICATE_VERIFY_FAILED` | — | **L** — el dominio no resuelve con certificado válido |
| **Unimarc** | **403 hasta en el `robots.txt`**, con UA de navegador y sin UA | — | **L** — bloqueo de borde tipo Fase 6 |
| **Tottus** | 200 | sitio **403**, API **503** | **L** — bloqueo de borde tipo Fase 6 |

#### Lider: el tecnicismo NO hace falta — hay vía limpia (2026-10-01)

Se aprobó usar el tecnicismo del `robots.txt`, pero buscando primero apareció una
vía **inequívocamente permitida**, que además es mejor:

- Las fichas viven en **`/ip/<categoría>/<slug>/<ean>`**, y `/ip` **no está en
  ningún `Disallow`** (la lista completa es `/cart`, `/tu-cuenta`, `/checkout`,
  `/search`, `/wallet`, `/thankyou`, `/opiniones`, `/orchestra`).
- El `robots.txt` **ofrece** cuatro sitemaps, y ahí está el catálogo entero.
- Las fichas traen precio (`"price":4990` + schema.org) **y la URL trae el EAN**.

Medido sobre los 21 `productSitemap*.xml`: **102.880 productos, 221 categorías,
100% con EAN en la URL**. Ese 100% de EAN es lo más valioso de todo:
CLAUDE.md registra que de 3.357 `products` solo 11 tienen 2+ tiendas porque las
tiendas con GTIN no se solapan. Lider sola cambiaría eso.

⚠️ **Pero el presupuesto de fetches no da, y por lejos.** Es ficha por ficha:

```
top  5 categorías:  41.586 SKUs →  83.172 fetches/día
top 10 categorías:  54.318 SKUs → 108.636 fetches/día
el sistema ENTERO hoy:            ~5.800 fetches/día
```

Y un dato que cambia el encuadre: **el top de Lider no es supermercado.** Es
`vestuario` 15.699, `muebles-y-decoracion` 10.219, `jugueteria` 6.854,
`libreria` 4.951, `tecnologia` 3.863. `supermercado` propiamente son 2.625.

#### Medido el peso real: "todo" no entra en este host

Se pidió conectar Lider completa. **No es viable, y es físico, no una decisión de
alcance.** Medido sobre 5 fichas reales: **752 KB en el cable cada una** (gzip
declarado, pero el HTML ya viene casi incompresible) y 1,0–1,9 s de latencia.

```
102.880 SKUs × 752 KB  →   73,8 GB por pasada   =  147,6 GB/día a 2 pasadas
tiempo: 42,9 h secuencial · 5,4 h con 8 concurrentes · 2,7 h con 16
```

El tiempo se arregla con concurrencia. **El tráfico no**: 147,6 GB/día salen por el
adaptador WiFi USB del host, el mismo que tiene 3.774 beacons perdidos y ráfagas de
fallos de DNS documentadas como irreparables desde el repo.

Se buscó un endpoint liviano y **no hay**: el `/_next/data/<buildId>/...json` de
Next.js devuelve **404** (buildId `production_20260831T100751610Z-es-CL`). Son 752 KB
por precio, sin atajo.

Con un presupuesto de ~5 GB/día —que para ese enlace ya es mucho— el techo es
**~3.500 SKUs por pasada**. Alcanza para `supermercado` (2.625) o para `tecnologia`
(3.863), no para las dos.

Así que Lider entra solo como **tajada chica y elegida a mano** (p. ej. `vinos`
1.390 + `snacks-y-picoteo` 848 = 2.238 SKUs ≈ 4.476 fetches/día, que ya es casi
todo el presupuesto actual), y es la primera tienda cuyo costo es **por SKU y no
por página de listado**. Eso es una decisión de producto con un número al lado, no
un detalle de implementación.

⚠️ **La decisión de Lider sobre el tecnicismo queda sin efecto.** Su `robots.txt` dice
`Disallow: /search*`, y `/search` es justamente la única vía que funciona y trae
precios. Hay un tecnicismo: los `Disallow` están escritos **después** del grupo
`User-agent: Googlebot-Image`, así que por la especificación pertenecen a ese
grupo y el grupo `User-agent: *` queda sin reglas — o sea, todo permitido. Pero la
intención del sitio es evidente. Este repo respetó robots cada vez que le costó
alcance (Kupfer: una request por categoría; Construmart: sin `limit`; Sparta:
bloqueada entera; SP Digital: `rate_limit_rps = 0.2`), así que **apoyarse en el
tecnicismo sería la primera excepción y no la tomo por mi cuenta.**

La alternativa limpia en Lider: su robots **ofrece cuatro sitemaps** (incluido
`/v/nc/sitemap/sitemap.xml`), que es el dueño del sitio invitando a recorrer URLs
de producto. Pero eso es ficha por ficha, y el diseño del scraper es por listado —
un supermercado son decenas de miles de SKUs y el presupuesto de fetches no da.

**Prerrequisito que sigue vigente y ahora está medido**: el piso absoluto de ahorro
en CLP. `detector.compute_score` es `discount_real*100 + below_floor*50` y
**excluye el precio absoluto a propósito**, así que un 40% sobre $990 (ahorro
$400) puntúa igual que un 40% sobre $990.000. Lo que acota el daño hoy es
`ranker.MAX_PER_CATEGORY_PER_DAY = 2`: con supermercado como **una** categoría, se
lleva como máximo 2 de las 6 ofertas del día. Si se parte en varias
(lácteos, limpieza, …), cada una se lleva 2 y el canal se inunda. **Si entra
supermercado, entra como una sola categoría hasta que el ranker tenga piso en
CLP.**

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
| **`magento_html.py`** ✅ | Kupfer, Construmart, **Andesgear** (Sparta pendiente) | grid HTML. Pagina con `?p=` o trae una sola página, **según lo que permita el `robots.txt` de cada tienda**; deduplica entre categorías si la tienda cross-lista | total exacto en el `toolbar-amount` → canario exacto en vez de estadístico |
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
- **Una llave puede ser una vitrina, y elegirla mal cuesta las series**
  *(aprendido el 2026-09-28, no el 23)*. La migración 15 eligió
  `herramientas-electricas` creyendo que era un paraguas. Era una colección
  curada a mano: el 2026-09-25 la tienda la reeditó y bajó de 345 a 131 items.
  **240 de los 246 listings que dejó de mostrar seguían a la venta** (cruzado
  contra las 39 páginas de su `/products.json`, 9.466 variantes). El tamiz está
  en el §5.2 del checklist y el reemplazo en la migración 22.

**1b. Las de grid HTML — cerrada el 2026-09-24, con una sola tienda de dos.**

| Orden | Tienda | Entrega | Resultado |
|---|---|---|---|
| 4 | **Kupfer** | `scrapers/stores/magento_html.py` + 3 fixtures + migración 18 | ✅ conectada, 24 listings |
| 5 | **Construmart** | — | ❌ **no construible como estaba planeado** → 1c |

Lo que la inspección del día encontró, y que el paso 1 del checklist §5 existe
para encontrar:

- **El `robots.txt` de Kupfer prohíbe `/*?p=`**, que es el parámetro de
  paginación de Magento. Por eso la familia **no pagina**: trae cada categoría en
  una request con `product_list_limit=36` (que su robots no prohíbe) y reporta lo
  que no entra en vez de ir a buscarlo. Sale más barato para la tienda que
  paginar. La consecuencia es que **solo se pueden conectar categorías de ≤36
  productos**, y por eso Kupfer entra con una llave y no con cinco.
- **`product_list_limit=96` devuelve HTTP 200 con 12 productos** — el default. No
  clampea al máximo: ignora el parámetro. Subirlo a ojo reduce el alcance a un
  cuarto sin un solo error.
- **Construmart no publica precios.** Sus precios y su stock son por sucursal
  (cada una es un `customer_group_id`) y el propio sitio lo dice: "Para ver los
  precios y stock, selecciona la región y tienda". Para un anónimo el HTML no
  trae un solo `$` en 800 KB y las 20 filas del grid salen "Sin Stock". Su
  `/rest/default/V1/products-render-info` **sí** contesta sin token —es la ruta
  anónima que usa su propio front— pero devuelve `final_price: 0` e
  `is_salable: ""` en los 20 productos.
- **El catálogo de Kupfer que mapea a nuestra taxonomía es chico**: es una
  ferretería industrial (amarre, cadenas, cabos, mantención). `herramientas-electricas`
  declara 24 productos y 7 de sus 10 hojas tienen cero: los productos están
  asignados al padre, que es anchor y los contiene.

**1c. Investigación — cerrada el 2026-09-26. Las cuatro respondidas:**

- ✅ **Construmart: conectada.** No hacía falta sostener una sesión. El módulo es
  `Construmart_CatalogPriceByGroup/js/store-popup` y lo único que su front hace
  antes de recargar es escribir la cookie `persistent_customer_group_id`; con esa
  cookie sola, el mismo listado que no tenía un solo `$` en 800 KB devuelve
  precios. Sí hubo que aceptar la decisión de modelo: la serie es la de la
  **sucursal 35 (DEPARTAMENTAL)**. 19 llaves, 219 listings, migración 19.
- ❌ **Imperial: descartada.** Ya no da 520: da **403 de Akamai**
  (`errors.edgesuite.net`) con UA propio y, con UA de navegador, el servidor
  resetea el stream HTTP/2. El criterio del plan se cumplió al revés de lo
  esperado: no era una caída temporal, es un WAF. Mismo balde que MTS.
- ❌ **Chilemat: descartada, y conviene que quede escrito para no re-inspeccionarla.**
  No es un e-commerce. Es un SPA de React con Firebase cuyo bundle declara
  `/noticias`, `/encuentra-ferreteria`, `/ferreterias`, `/concursos`,
  `/unete-ferretero` y **cero** ocurrencias de producto, carrito, catálogo, precio
  o stock. Es el sitio corporativo de una cadena de franquicias con localizador
  de locales.
- ✅ **Kruuse: conectada el 2026-09-26** (24 llaves, 628 listings, migración 20).
  El plan la subestimaba, pero no por lo que parecía. No es payload RSC: corre **Medusa** y publica
  `/cl/product-feed.json`, un feed paginado que su propio `llms.txt` ofrece para
  "catalog discovery" y que su `robots.txt` **permite explícitamente a ClaudeBot**.
  3.753 productos, `limit` clamea honesto en 100 (→ 38 requests por pasada),
  **GTIN-13 en el 99%** —la mejor identidad del sistema junto a Ferretek—, marca y
  SKU en el 100%, precios CLP enteros y `availability` de tres valores.

  Lo que la frena: **3.467 de 3.753 productos son `backorder`** (221 `in_stock`).
  Es un importador de maquinaria que vende a pedido, así que `backorder` y
  `preorder` tienen que mapear a `in_stock=False` y la guarda del detector va a
  rechazar casi todo. Su valor hoy es la identidad cross-store, no el volumen de
  publicación.
  `category` viene en el 65%; mapean ~905 productos a `ferre-herramientas` y ~139
  a `ferre-jardin` contando accesorios, ~650 descontando consumibles.

  ⚠️ **Corrección del 2026-09-28: la serie de un `backorder` NO se está
  construyendo.** Lo que se escribió acá y en la migración 20 —"la serie ya
  construida para cuando un SKU entre en stock"— es falso. Los `price_points` sí
  se acumulan (628 de 628 listings tienen observaciones), pero
  `compute_baseline` (`pricing/baselines.py:149`) filtra `if in_stock` **al
  computar**, sobre los puntos crudos: los 532 listings en backorder no tienen
  baseline ni `n_days`, y esos puntos van a seguir filtrándose para siempre. El
  reloj de `MIN_POINTS=30` / `MIN_DAYS=30` de un producto en backorder **arranca
  el día que aparece stock**, no el día que lo empezamos a observar. Medido hoy:
  `kruuse: 628 listings | 628 con observaciones | 96 con baseline`.

  El filtro está bien —un precio que nadie puede pagar no debe entrar al p50—;
  lo que estaba mal era la expectativa. Consecuencia para la evaluación del
  2026-10-26: esperar "≥1 candidato aceptado propio" es casi imposible, porque
  solo 96 de sus 628 listings están construyendo baseline.
- **MTS**: 403. Queda para la Fase 6.

**Criterio de salida (30 días después):** cada tienda con ≥40% de su **cohorte**
(los listings nacidos hace más de 30 días) con `n_days >= 30`, y ≥1 candidato aceptado propio. Las que no lleguen, se
desactivan.

---

### Fase 2 — Deportes y outdoor

Va segunda porque **Doite y Lippi son costo XS**: reusan la familia Shopify de
la Fase 1 sin escribir un adaptador. Es la mejor relación valor/esfuerzo del
plan completo, pero depende de la Fase 1 para existir.

**Trabajo previo obligatorio — hecho el 2026-09-26, migración 21:**

1. ✅ **Categorías nuevas**: `deporte-vestuario` (θ 0.350), `deporte-calzado`
   (0.300) y `deporte-equipamiento` (0.250), las tres mapeadas al canal `vip`.
   Los θ son de partida **sin calibrar**, y más altos que los de ferretería a
   propósito: en vestuario un 25% de descuento es precio de lista de cualquier
   martes.
2. ✅ **La liquidación de temporada: ubicada, no resuelta — y no bloquea.** Se
   revisó el código antes de conectar, y el efecto no está donde esta advertencia
   sugería:

   - La ingesta no se entera.
   - **El detector NO la rechaza**: `detect_ramp` exige un alza sostenida (≥15%
     sobre el p50 por ≥5 días entre d−21 y d−3) ANTES de la baja, y una
     liquidación baja sin haber subido → `ramp_flag=False` → la oferta se acepta.
   - **Pega en el backtest**: `label_outcome` marca `fake` todo pozo que se queda
     abajo, y una liquidación se queda abajo. Así que la precisión medida de estas
     3 categorías va a verse mal y la calibración empujaría sus θ hacia arriba
     hasta excluirlas.

   O sea que la decisión es **de calibración y se toma con datos**: aceptar que se
   filtren, o agregarle al backtest una etiqueta para "se quedó abajo pero fue una
   ganga real".

   ⚠️ Y ya no hay red de contención: el publisher está encendido desde el
   2026-09-21 y las tres `deporte-*` están en las categorías del tier `vip`. Que
   todavía no haya salido ninguna oferta de deportes es solo porque Andesgear se
   conectó el 26-sep y sus baselines no maduran hasta el **2026-10-26**. Desde esa
   fecha las liquidaciones de temporada salen al canal medidas contra θ de partida,
   sin que nadie las haya calibrado. La decisión se toma **antes** del 26-oct.

| Orden | Tienda | Costo | Estado al 2026-09-26 |
|---|---|---|---|
| 1 | **Doite** | — | ❌ **Su `robots.txt` prohíbe 212 handles de `/collections/`**, que es exactamente el endpoint de la familia Shopify. No conectar |
| 2 | **Lippi** | — | ❌ **No hay tienda.** `lippi.cl` no resuelve (NXDOMAIN), `lippioutdoor.cl` resuelve pero no responde, y `lippi.com` es un WordPress de marca sin `/products.json` ni precios en CLP |
| 3 | **Andesgear** | S | ✅ **Conectada el 2026-09-26** (migración 21): 25 llaves, 3.042 productos declarados, ~140 páginas por pasada a 0.33 rps ≈ 7 min. Pagina con `?p=` y **deduplica entre categorías** |
| 4 | **Sparta** | M, pendiente | Magento, `Crawl-delay: 1`, pero **`Disallow: /*?` + `/*?*`**: ninguna URL con query string, o sea **no se puede paginar**. `zapatillas.html` declara 1.080 y una request trae 36. Las únicas tajadas disjuntas son sus facetas de marca (`/zapatillas/filtro/adidas.html`): ~200 llaves para cubrir el árbol. **Decisión aparte** |
| 5 | Mountain | investigación | — |

**Doite, con detalle, porque el veredicto no es técnico.** Su `products.json`
global responde 200 y no está en el `Disallow`, así que se *podría* usar. Pero la
lista de 212 colecciones prohibidas cubre el árbol de categorías entero
(`hombre`, `ofertas`, `novedades`, `chaquetas-hombre`, `poleras-hombre`,
`parka-termica-hombre`...) y el `robots.txt` abre con un banner propio sobre
scraping automatizado. La intención de la tienda es clara, y este repo respeta
intenciones declaradas incluso cuando la letra deja una puerta abierta — igual que
con el `Crawl-delay: 5` de SP Digital y el `?p=` de Kupfer. **Si alguna vez se
revierte esta decisión, que sea explícita y de quien la toma, no por descuido.**

✅ **Lo que Sparta y Andesgear ya NO heredan de la Fase 1b**: `magento_html`
aprendió a paginar en la Fase 1c (Construmart), y `paginates`/`page_size` son por
tienda. Andesgear puede paginar; Sparta no, por su prohibición de query strings.
Falta, para las dos, mirar qué valores ofrece su `<select id="limiter">`: un
`product_list_limit` que la tienda no ofrezca cae a su default en silencio.

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

#### RESUELTA (parcialmente) el 2026-10-01 — y la hipótesis era otra

El plan asumía que había que "mirar headers y fingerprint". **Fingerprint no hizo
falta en ninguna**: lo que delataba al scraper no era el User-Agent sino la
**ausencia** de los headers que cualquier navegador manda, sobre todo
`Accept-Language`, `Accept-Encoding` y la familia `Sec-Fetch-*`. Con el UA de
navegador solo contra el juego completo (`http.BROWSER_HEADERS`):

| Tienda | Borde | UA solo | Headers completos | Estado |
|---|---|---|---|---|
| **Nike** | Cloudflare | 403 | **200** + **API VTEX pública abierta** | ✅ **CONECTADA 2026-10-01 (migración 25)** |
| **Tottus** | Cloudflare | 403 | home **200**, pero catálogo **503/526** | 🟡 el borde pasa; el ORIGEN falla |
| **Unimarc** | — | 403 | home sigue **403**; API VTEX **500 en todo** | ❌ corregido: es callejón sin salida |
| **PC Express** | LiteSpeed | 403 | **pasa**: 404 en robots y sitemap | 🟡 falta descubrir rutas |
| **Adidas** | Akamai | 403 | **robots.txt 200**, home sigue 403 | 🟡 parcial |
| **Decathlon** | Cloudflare | 403 | 403 en todo (robots, sitemap, API VTEX) | ❌ bot management |
| **Nice One** | Cloudflare | 403 | 403 en todo | ❌ bot management |
| **MTS** | Cloudflare | 403 | 403 en todo | ❌ bot management |

#### Lo verificado después, que corrige dos de las filas

- **Nike es el premio, y está lista.** Su API VTEX pública responde: `products/search`
  da **HTTP 206** y `category/tree/3` da 200. `Resources: 0-49/2546` → **2.546
  productos**, o sea **51 requests por pasada**: nada. El payload trae todo lo que
  `RawProduct` pide y además **`ean`** (`194500874862` en el Air Force 1), que
  alimenta `catalog/identity.py`. Árbol: `nike` (calzado, ropa, accesorios) y
  `snkrs`. **Es zapatilla urbana con GTIN**, justo lo que la Fase 3b quería de
  Sparta y Decathlon, con una fracción del costo.
- **Tottus NO está usable, me equivoqué al cantarla.** Ese 200 era la **home**.
  Las rutas de catálogo dan **503** (API VTEX) y **526** (categoría y búsqueda).
  526 es error de certificado del origen detrás de Cloudflare: el borde nos deja
  pasar y el origen está roto para esas rutas. Puede ser transitorio — reintentar
  antes de invertir en su adaptador.
- **Unimarc es callejón sin salida.** Su home sigue en **403** con headers
  completos, y su API VTEX devuelve **500 uniforme en los 7 endpoints probados**
  (`products/search` con y sin `sc`/`ft`, `category/tree`, `brand/list`). Un 500
  igual en todo no es un parámetro que falte: la API de catálogo está deshabilitada
  en ese host. Sale del grupo 🟡 y pasa al duro.

#### Navegador headless: PROBADO el 2026-10-01, y NO funciona

Se pidió implementarlo para las tres que httpx no puede. Se instaló Playwright +
Chromium y se probó de verdad. **Falla igual.** No es una objeción de diseño: es un
resultado medido, y conviene que quede para que nadie lo vuelva a intentar.

| Intento | Decathlon | Nice One | MTS |
|---|---|---|---|
| httpx + `BROWSER_HEADERS` | 403 | 403 | 403 |
| Chromium headless-shell | 403 | 403 | 403 (página de bloqueo explícita) |
| Chromium completo + `--disable-blink-features=AutomationControlled`, viewport 1920×1080, locale es-CL, `navigator.webdriver=False` verificado | **403** | **403** | **403** |

La detección **no está en el JavaScript**: con `navigator.webdriver` en `False` y un
Chromium real, sigue siendo 403. El header lo dice:

```
cf-mitigated: challenge      (Decathlon)
server: cloudflare           cf-ray: ...-SCL
```

O sea que Cloudflare emite un **desafío interactivo** y nuestro cliente lo falla
antes de llegar al contenido. El 403 llega incluso en `/robots.txt`, así que **no
se puede ni leer la política del sitio** — que era la única razón por la que valía
la pena encender el navegador.

Nice One además redirige a `n1g.cl/Home/`, igual de bloqueado.

Lo único que quedaría es una capa dedicada de anti-detección: parches de
*stealth*, spoofing de fingerprint TLS/JA3, o un servicio que resuelva el
challenge. **Eso no se construye**: es herramienta de evasión de un producto de
seguridad, no identificarse correctamente, y además la pista apunta a reputación de
IP (la del host lleva meses haciendo requests automatizados a 13 retailers), contra
lo que ningún navegador ayuda — haría falta un proxy residencial.

La vía limpia para estas tres sigue siendo **pedirles acceso** (feed, API o
afiliados).

⚠️ **Playwright quedó instalado solo en el `.venv` local (~250 MB con Chromium) y
NO se agregó a `requirements.txt` ni al `Dockerfile`**: la imagen de producción
sigue en 570 MB. Si no se le encuentra otro uso, se puede desinstalar sin tocar
nada más.

**Cinco de ocho pasan el borde con headers legítimos.** Las tres duras tienen bot
management de verdad y **ahí se para**: pasarlo pide fingerprint de TLS o un
navegador headless, y este scraper es deliberadamente httpx + parseo posicional,
sin browser (ver §Stack). Una tienda que de verdad no nos quiere, no nos tiene.

⚠️ Ojo con la ironía: **Decathlon era "la más valiosa de este grupo y justifica
sola el esfuerzo"**, y es una de las tres que no cede. El valor del grupo quedó en
Tottus y Nike.

Entregable reusable: `http.BROWSER_HEADERS` y `http.BROWSER_HEADERS_JSON` (la
variante coherente para XHR: un `Sec-Fetch-Mode: navigate` pidiendo JSON es
incoherente y algunos bordes lo marcan). Igual que `BROWSER_USER_AGENT`, se usa
**por adaptador y nunca como default** — el `DEFAULT_USER_AGENT` sigue
identificándose como bot.

**Decathlon es la más valiosa de este grupo** y justifica sola el esfuerzo.

En paralelo: **decidir si supermercado y farmacia son parte del producto**
(§2.6). Si la respuesta es sí, el ranker necesita antes un piso absoluto de
ahorro en CLP.

---

## 4bis. Las tres que pidió el producto (2026-10-01)

Vienen de una observación contra los datos: **el canal no saca ofertas de ropa,
zapatillas ni cosas chicas**, y eso es verdad. Medido el 2026-10-01 sobre las 63
ofertas publicadas: ticket p50 **$279.990**, solo 12 por debajo de $50.000, y el
p50 de `tecno-tv` es $1.579.990.

**El ranker no es la causa** y conviene no perder el tiempo ahí:
`detector.compute_score` excluye el precio absoluto a propósito —"ponderar por
ticket inundaría los canales de electrónica cara"— y está bien así. La causa es
la composición del catálogo. De 9.729 baselines maduras:

| tramo | listings | |
|---|---|---|
| < $20.000 | 607 | |
| $20–50k | 576 | **12% bajo $50.000** |
| $50–150k | 1.497 | |
| $150–500k | 4.075 | |
| > $500.000 | 2.974 | **72% sobre $150.000** |

El detector sí acepta barato (448 aceptados bajo $50.000), pero el pool viene
6:1 en contra: la cuota sale cara sin que nadie la sesgue. Se arregla con
catálogo y taxonomía, no con código.

---

### Fase 3 — Ropa y vestuario · DESBLOQUEADA

Estaba trabada por la decisión de liquidación (§1.3), que se tomó el 2026-10-01.
Las 5 tiendas y su orden no cambian (ver abajo). Lo que cambia es que ya se puede
empezar, y que las categorías `ropa-*` nacen sabiendo que sus liquidaciones
cuentan como aciertos.

### Fase 3b — Calzado urbano y zapatillas ✅ ARRANCADA 2026-10-01 (migración 24)

> **Segunda entrega, el mismo día: Nike (migración 25).** Salió de la Fase 6 — su
> 403 era solo por headers. Se escribió `scrapers/stores/vtex_family.py`, o sea la
> **familia VTEX completa**, que es la que el plan ya quería para Colloky y la
> Fase 3 entera. **2.554 productos en ~57 requests por pasada y 100% de cobertura
> de EAN**, que es lo que mueve la aguja de `catalog/identity`: hoy de 3.357
> `products` solo 11 tienen 2+ tiendas. Mapeo: calzado (1.188 + 119) a
> `ropa-calzado`, ropa (929 + 45) a `deporte-vestuario`. Verificado que `snkrs` NO
> es paraguas de `nike` (intersección 0 sobre itemIds, en los dos pares).
> **Sparta y Decathlon ya no son necesarias** para tener zapatilla urbana de marca.

> **Lo hecho el 2026-10-01**, antes de Sparta y sin tocar un adaptador: Falabella
> ya tenía zapatilla urbana. `ropa-calzado` (θ 0.350) con `cat2083/Zapatillas` y
> `cat690245/Botines-Mujer`. **Categoría nueva y no `deporte-calzado` porque se
> midió**: 66% y 60% moda/urbano contra 22% y 1% deportivo, y `deporte-calzado` es
> "Calzado outdoor" con un θ elegido para ese comportamiento. El θ 0.350 también
> es medido, no copiado: el 56-58% del catálogo ya declara ≥30%, o sea que a 0.30
> el umbral no filtraría nada. **Y es lo que baja el ticket del canal**: p50
> $48.990 y $41.990, mínimos $9.990 y $7.990, contra los $279.990 de lo publicado.
> Sparta y Decathlon siguen en el plan para profundidad, ya no como bloqueo.

Lo que hay hoy es **Andesgear y nada más**: 393 listings de `deporte-calzado`, y
es calzado **outdoor**. No hay zapatillas urbanas en el sistema.

| Orden | Tienda | Nota |
|---|---|---|
| 1 | **Sparta** | Ya auditada (§Fase 2): `zapatillas.html` declara 1.080. Su robots prohíbe toda URL con query string, así que **no se puede paginar**: las únicas tajadas disjuntas son ~200 facetas de marca (`/zapatillas/filtro/adidas.html`). Es la decisión que estaba pendiente y ahora tiene un motivo de producto para resolverse |
| 2 | **Decathlon** | 403 hoy (Fase 6). El plan ya la marca como "la más valiosa de ese grupo" — esto lo confirma |
| 3 | Nike, Adidas | 403 hoy. Mismo patrón de bloqueo que Decathlon: una sesión sirve para las tres |

Reusa `deporte-calzado` o abre `ropa-calzado` según de qué surta Sparta. **Decidir
al conectar, no antes**: si Sparta trae mayormente zapatilla deportiva, reusar la
categoría existente evita un θ nuevo sin calibrar y 30 días más de espera.

### Fase 3c — Audio y accesorios ✅ HECHA 2026-10-01 (migración 23)

Esto no estaba en ninguna fase: lo busqué en este archivo y audio, audífonos y
accesorios **no se mencionaban**. No es que estuviera postergado; faltaba.

Estado medido el 2026-10-01: **47 audífonos en el catálogo, 19 ya con baseline
madura, 0 publicados**. Son residuo incidental de `tecno-celulares` de Falabella
y Paris —nadie los scrapea a propósito—, y con 47 de 25.429 listings no van a
salir ni por casualidad.

Entrega, en orden:

1. **Migración con la categoría nueva** y su θ de partida. `tecno-audio` si se
   acota a audio, `tecno-accesorios` si entra también teclado, mouse, cargador,
   powerbank. **Recomendado: `tecno-audio` sola primero** — es la que el producto
   pidió, y una categoría ancha con θ único mezcla cosas de $8.000 y de $400.000,
   que es exactamente lo que vuelve inútil un umbral porcentual.
2. **Llaves en las tiendas que ya están conectadas.** No requiere adaptador
   nuevo: Falabella, Paris, PC Factory y SP Digital ya tienen audio en catálogo y
   las cuatro familias ya están escritas. Es la fase más barata de todo el plan.
   ⚠️ Verificar que las llaves nuevas sean **disjuntas** de `tecno-celulares`
   sobre SKUs reales antes de meterlas en la migración: hoy los 47 audífonos
   entran por ahí, y dos llaves solapadas escriben dos `price_points` del mismo
   listing por pasada y lo hacen pesar el doble en su propio p50.
3. 30 días de espera y recién ahí su primera oferta.

Candidatas nuevas si hace falta profundidad, en orden de valor: **Nice One**
(403, Fase 6) y **MacOnline** (Fase 5, accesorios Apple).

---

## 5. Checklist por tienda nueva

Idéntico para todas, independiente de la fase. Sale de `CLAUDE.md` §Agregar una
tienda, con lo que este plan agrega.

1. **Inspección**: confirmar la vía (API o grid) y **releer el `robots.txt`**
   ese día. El `rate_limit_rps` sale del `Crawl-delay` declarado, no de lo que
   aguante el servidor.
2. **Elegir la llave: ¿catálogo o vitrina?** Una colección curada a mano se ve
   igual que un catálogo hasta que el comerciante la reedita y mata las series
   (el caso Prat del 2026-09-25: −240 listings que **seguían a la venta**). El
   tamiz barato es la tasa de stock de la llave contra la del catálogo entero:
   una colección que trae ~100% disponible está filtrada por stock y es catálogo;
   una muy por debajo es una vitrina editorial. Y **verificá la jerarquía sobre
   SKUs, no sobre el nombre**: en Prat, `herramientas-electricas` tenía solo 71
   de sus 131 SKUs dentro de `herramientas-y-maquinarias`.
3. **Adaptador**: módulo en `scrapers/stores/` que implemente `StoreAdapter`.
   Si la familia existe, no se escribe código: solo la fila.
4. **Fixture**: payload **real** en `tests/fixtures/`. Ojo con el engaño de la
   página 1 (el caso Paris/EAN): si el campo aparece solo en los primeros N
   items, el fixture miente.
5. **Migración numerada** con la fila en `stores` y sus `store_categories`,
   mapeadas a la taxonomía canónica. Categorías nuevas → θ de partida explícito
   y anotado como **no calibrado**.
6. **`MAX_PLAUSIBLE_CLP`**: verificar si la tienda usa centinelas como los
   $99.999.999.999 de Falabella. Un centinela envenena la baseline del SKU de
   forma permanente.
7. **Canario**: la primera pasada no tiene historia, así que solo rige el piso
   absoluto de 5 items. Revisar a mano la tercera pasada, cuando la mediana de
   7 corridas empieza a tener sentido.
8. **`docker compose up -d --build scraper`**. El Dockerfile copia las fuentes,
   no las monta.
9. **Anotar la fecha de conexión.** El criterio de aceptación se evalúa 30 días
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
