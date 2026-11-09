# INVESTIGACION_viajes.md

Fase 0 de la vertical **viajes** (`PLAN_EXPANSION.md` §6). Medido el **2026-11-05**.

El tema `viajes` de Telegram existe (`message_thread_id = 20547`) y **está mudo**:
tiene cero categorías ruteadas. Esta investigación responde si se puede llenar.

**Veredicto corto: sí, con una sola tienda de las seis vivas.** `nomades.com`
(tours y actividades) encaja sin tocar el detector. `cruceros.cl` queda afuera
por moneda, no por acceso. Los metabuscadores quedan afuera por diseño.

---

## 1. Qué está vivo

| sitio | borde | plataforma | veredicto |
|---|---|---|---|
| **`nomades.com`** (ex `denomades.com`) | 200 con `DEFAULT_UA` | **Next.js** | 🟢 **entra** |
| `cruceros.cl` | 200, 1,4 MB | MUI/React | 🔴 **no entra: USD** |
| `cocha.com` | 200, robots 200 | sin determinar | 🟡 acotar a packs |
| `travelsecurity.cl` | 200, robots 200 | sin determinar | 🟡 acotar a packs |
| `kayak.cl` | 200 | — | 🔴 metabuscador |
| `turismocity.cl` | 200 **solo con `BROWSER_HEADERS`**, `Crawl-delay: 15` | — | 🔴 metabuscador |
| `viajesfalabella.cl`, `despegar.cl`, `atrapalo.cl`, `viajeselcorteingleslatam.com` | 🔴 sin 200 | — | — |
| `nilsentours.cl`, `crucerostotal.cl`, `turismocomolotravel.cl`, `chileviajes.cl`, `raptortravel.cl`, `viajesinteligentes.cl`, `asatej.cl`, `wakacje.cl`, `tursimochile.cl` | 🔴 **DNS no resuelve** | — | — |

⚠️ **`denomades.com` redirige a `nomades.com`.** Las dos resuelven; la canónica es
la segunda, y su sitemap y su `robots.txt` apuntan ahí. La llave tiene que ser
`nomades.com` o se recolecta contra una redirección.

---

## 2. `nomades.com` — 🟢 entra, y es la única que encaja sin tocar nada

Es tours y actividades: **precio por producto, sin fecha dentro del precio**, que
es exactamente el subconjunto que `PLAN_EXPANSION.md` §6.2 identifica como
compatible con el detector actual.

### Lo medido

- **`robots.txt` 200 y permisivo**: 33 `Disallow`, todos de pago y reserva
  (`/webpay/*/*`, `/paypal/*/*`, `/direct-payment`, `/bookings/complete-information/*`,
  `/cotizacion/*`). **Nada que toque las páginas de destino ni las de producto.**
  Sin `Crawl-delay` ⇒ default conservador del repo.
- **Sitemap con 5.868 URLs**, organizado por **destino**: `/santiago`,
  `/san-pedro-de-atacama`, `/isla-de-pascua`, …
- **La página de destino ES el listado**, y trae los datos en `__NEXT_DATA__`
  como **JSON-LD de schema.org**. En `/san-pedro-de-atacama`: **39 objetos
  `Offer`**, cada uno con

      {"@type":"Offer", "price":17000, "priceCurrency":"CLP",
       "availability":"https://schema.org/InStock",
       "url":".../san-pedro-de-atacama/transfer-aeropuerto-calama-id3"}

Las cosas que eso resuelve de un golpe:

1. ⚠️ **CLP… pero solo en los destinos chilenos, y eso lo medí mal primero.** La
   conclusión de arriba sale de `/san-pedro-de-atacama`, **un solo destino**.
   Barridos 14 destinos, `nomades.com` resultó **multi-moneda y la moneda la
   define el destino**: amsterdam/atenas/barcelona **EUR**, antigua/arenal/aruba
   **USD**, arequipa/ayacucho **PEN**, armenia **COP**, antofagasta/arica
   **CLP** — y **bariloche mezcla USD y ARS en la misma página** (10 y 9
   ofertas). Es el engaño de la página 1 trasladado a la elección de destino: un
   destino no representa al catálogo, igual que una página no representa a una
   categoría. ⇒ **Solo se pueden conectar los destinos en CLP**, y hay que
   filtrar por `priceCurrency` en el adaptador, no por nombre de destino.
2. ⚠️ **Hay ofertas con `price = 0`** (vistas en amsterdam, arequipa, barcelona y
   bariloche). Cero no es un precio: el adaptador tiene que descartarlas, igual
   que `magento_html` descarta la fila sin precio.
3. 🟡 **Señal de stock**, `availability`. Pero en los 120 productos de la muestra
   dio **`InStock` el 100%**, así que probablemente es una constante y no una
   señal — el mismo caso que Colloky, donde el agotado desaparece del listado en
   vez de marcarse. No construir una guarda sobre esto sin verlo dar `OutOfStock`.
4. 🟢 **SKU estable en la URL**: el sufijo `-id3` es el id del producto. No hay
   que inventarlo ni derivarlo de un slug que el comerciante puede reescribir.
5. 🟢 **Es JSON-LD estándar**, no un parseo posicional de HTML: menos frágil que
   cualquier adaptador de grid de los que ya existen.
6. 🟢 **Los destinos son disjuntos de verdad.** Medido sobre 14 destinos: **120
   SKUs, 120 únicos, cero pares con solapamiento (1,00×)**. Es una partición
   real, como las cuatro raíces de Colloky — y era la pregunta que más importaba
   acá, porque un tour de Atacama podría haber estado en varios destinos.

### El censo completo (160 destinos, 2026-11-05)

Barrí **los 160 destinos en español**, uno por request:

| moneda | ofertas |
|---|---|
| USD | 408 |
| **CLP** | **282** |
| EUR | 260 |
| PEN | 136 |
| COP | 119 |
| BRL | 110 |
| ARS | 62 |
| MXN | 51 |
| GBP | 12 |

🟢 **Lo conectable son 282 ofertas en CLP repartidas en 24 destinos**, y los
**282 SKUs son únicos**: solapamiento cero sobre el sitio completo, no solo sobre
la muestra de 14. Los 24 destinos:

```
antofagasta  arica  caleta-tortel  castro  copiapo  coyhaique  el-calafate
iquique  isla-de-pascua  la-serena  madrid  melipeuco  pucon  puerto-montt
puerto-natales  puerto-rio-tranquilo  puerto-varas  puerto-williams
punta-arenas  roma  san-pedro-de-atacama  santiago  valdivia
villa-cerro-castillo
```

⚠️ **Y no son "los destinos chilenos"**: `madrid`, `roma` y `el-calafate` cotizan
en CLP (se venden al viajero chileno) mientras `bariloche` cotiza en USD+ARS. O
sea **el filtro tiene que ser `priceCurrency == "CLP"` por oferta, nunca una
lista de destinos escrita a mano** — la lista cambia cuando la agencia cambia de
mercado, y una llave que de golpe empieza a traer EUR envenenaría las series de
ese destino sin un solo error.

**Costo por pasada: 24 requests.** Es la tienda más barata de todo el plan.

**Dimensionamiento contra el canal**: el tema `viajes` tiene `daily_quota = 1`, y
`MAX_PER_CATEGORY_PER_DAY = 3`. Con 282 SKUs maduros alcanza de sobra para una
oferta por día — el cuello no va a ser el catálogo.

### Lo que falta medir antes de escribirlo

| # | pregunta | estado |
|---|---|---|
| 4 | ¿Pagina la página de destino, o los 39 son todo? | 🔴 sin medir |
| 5 | **¿Orden estable?** | 🔴 sin medir |
| 6 | ¿Declara el total de actividades del destino? | 🔴 sin medir |
| 7 | GTIN — no aplica a un tour | n/a |
| 8 | ¿Hay `price_normal` (un "antes" tachado)? | 🔴 sin medir. Si no lo trae, θ se hereda |
| 10 | Centinelas | 🔴 sin medir |
| 11 | ¿Los destinos son disjuntos sobre SKUs reales? | 🟢 **medido: sí, 1,00× sobre 14 destinos** |
| 12 | Costo | 🟢 **medido: 24 requests por pasada** (los destinos con ofertas en CLP) |

⚠️ **El sitemap trae los tres idiomas** (`/santiago`, `/en/santiago`,
`/pt/santiago`). Son **el mismo catálogo tres veces**: si entran los tres, cada
listing pesa el triple en su propio p50. **Solo las rutas sin prefijo de idioma.**

⚠️ **Y la pregunta que decide la vertical sigue abierta**, la de §6.2: **¿el SKU
sobrevive 30 días?** Un tour regular (un transfer, un tour a los geysers) es
catálogo permanente y debería sobrevivir, a diferencia de un pack con salida
fija. Es la razón por la que **tours es el subconjunto correcto para empezar** y
no los packs. Pero medirlo de verdad requiere `scripts.aceptacion_tienda` 30 días
después de conectarla, como cualquier tienda.

### Categoría y ticket

No hay categoría interna de viajes. El ticket medido va de **$17.000** (un
transfer) para arriba, o sea el rango no rompe nada —está entre el supermercado y
la tecnología—. Necesita una categoría nueva (`viajes-tours`) con θ **heredado y
anotado como herencia**, porque hasta no medir el `price_normal` no se puede fijar
midiendo.

---

## 2.bis ✅ Decidido (dueño, 2026-11-05): **USD y EUR también sirven**

El dueño decidió aceptar ofertas en moneda extranjera. Eso cambia el veredicto de
`cruceros.cl` y abre los otros 136 destinos de `nomades.com`. **Mi "no entra" de
más arriba era demasiado fuerte y conviene decir por qué:**

🟢 **Lo que yo objetaba era CONVERTIR, y convertir sigue estando mal.** Si el
precio se pasa a CLP cada día, el p50 de 60 días mezcla 60 tipos de cambio y
`discount_real` empieza a medir el dólar en vez de la oferta.

🟢 **Pero guardar el precio en su propia moneda NO tiene ese problema.** La señal
es `discount_real = 1 − price_today / p50_60d`, y si las dos puntas están en la
misma moneda **el tipo de cambio se cancela**: un crucero que baja de US$229 a
US$180 bajó 21%, y eso es cierto sin mirar el peso ni una vez. La fórmula es
**neutral a la moneda** siempre que la serie no la mezcle.

⇒ La regla que hay que sostener es una sola, y es más fuerte que la actual:

> **La moneda viaja con el precio y una serie NUNCA mezcla dos monedas.**

### Qué toca eso, y es más que un adaptador

1. **Una columna de moneda.** Hoy `price_points` no la tiene: la regla 3 asume CLP
   en todas las capas. Lo correcto es colgarla del **listing** (o de la tienda),
   no de cada punto: si el `currency` de un listing cambiara, su serie dejó de ser
   comparable y hay que empezarla de nuevo — igual que cambiar
   `ConstrumartAdapter.CUSTOMER_GROUP_ID` invalida el histórico de esa tienda.
   ⚠️ Y hay tres casos medidos que lo exigen a nivel listing y no de tienda ni de
   llave: **`bariloche` sirve USD y ARS en la misma página** (10 y 9 ofertas),
   **`cancun` mezcla USD y MXN** (20 y 2) y **`roma` mezcla EUR, CLP y USD** (7, 1
   y 1). O sea "la moneda de la tienda" no existe, y tampoco "la moneda del
   destino": **la moneda es del producto**.
2. **El techo de plausibilidad es de escala CLP.** `MAX_PLAUSIBLE_CLP = 100.000.000`
   no sirve para USD: un centinela de US$99.999.999 pasaría, y al revés, un precio
   legítimo nunca se acerca. Hace falta un techo por moneda.
3. ⚠️ **Decimales — medido, y es más benigno de lo que parecía.** La regla 3
   prohíbe `float` para dinero, y en CLP no hay centavos, así que nunca fue un
   problema. Barrido de 144 ofertas en 10 destinos de 8 monedas (EUR, USD, PEN,
   COP, ARS, BRL, MXN, GBP): **143 enteras y 1 con decimal** (`EUR 37.5`), o sea
   **0,7%**.
   ⇒ Alcanza con la solución que el repo ya tiene escrita,
   `shopify_family.parse_price`: **descartar el precio con separador decimal en
   vez de adivinar la escala**. Cuesta ~1 de cada 140 ofertas y no agrega una
   unidad nueva al pipeline. Guardar en unidad mínima (centavos), como hace la
   Store API de WooCommerce con `currency_minor_unit`, cubriría el 100% pero
   obliga a que toda la capa sepa la escala de cada moneda.
   Lo que **no** se puede es truncar en silencio: un `189.90` leído como `18990`
   es un error de 100× que nadie nota hasta ver una oferta imposible.
4. **El copy.** `publisher/formatter.format_clp` imprime `$`. Una oferta en USD que
   diga "$229" se lee como 229 pesos. El símbolo tiene que salir de la moneda del
   listing.
5. **El cross-store se rompe entre monedas**, pero eso hoy da cero mensajes de
   todas formas, así que no cuesta nada.

### Lo que esto habilita, medido

| | SKUs | destinos/llaves | requests/pasada |
|---|---|---|---|
| **nomades solo CLP** | 282 | 24 | 24 |
| **nomades todas las monedas** | **~1.440** | **160** | **160** |
| **cruceros.cl** (USD) | **14.285** | sitemap propio | a dimensionar |

o sea la decisión multiplica la vertical por **5× en nomades** y **habilita
cruceros entero**, que es la tienda con más SKUs de todo el plan de expansión.

**Mi recomendación de orden**: conectar `nomades.com` **primero y solo en CLP**,
que no necesita ninguno de los cinco cambios de arriba, y usar esos 30 días de
baseline para validar la vertical (¿sobrevive el SKU? ¿da ofertas publicables?).
Recién con eso probado, hacer el trabajo de moneda y sumar las otras monedas más
cruceros. Así el cambio de dominio se paga contra una vertical que ya demostró
funcionar, en vez de ser una apuesta.

## 3. `cruceros.cl` — 🟡 viable, pendiente del soporte de moneda

**El acceso es excelente**, lo que hace el veredicto más frustrante:

- `robots.txt` 200, 20 `Disallow`, todos de endpoints AJAX y de búsqueda
  (`/ajax_moteur.php`, `/search?`, `*/package-*`, `/listeV4.php`).
- **`sitemap-productos.xml` con 14.285 URLs**, una por **zarpada**:
  `/f-12937523-msc-msc-divina-transpacifico` = `f-<id>-<compañía>-<barco>-<destino>`.
  Es literalmente lo que §6.2 pide: "cada zarpada es un SKU con fecha fija".
- ✅ Y **ninguna de las 14.285 contiene `package`**, así que el
  `Disallow: */package-*` **no las toca** — el dato que parecía un bloqueador no
  lo es.
- La página de destino es un listado usable: **25 zarpadas con precio** por
  página, con los links `/f-…` a la vista.

🟡 **Lo que lo frenaba era la moneda — y el dueño decidió el 2026-11-05 que USD
sirve** (ver §2.bis). Queda pendiente del soporte de moneda, no descartada.
Medido sobre
`/d-23-antillas`: **76 ocurrencias de `US$`, 50 de `USD`, CERO de `CLP`**, y el
nodo de precio es literalmente
`<p class="price" data-testid="result-item-price-cruise-0">US$ 229</p>`.

Por qué eso no se arregla con una conversión, que es la tentación obvia:

1. **La regla 3 es CLP entero en todas las capas.** Ingerir `229` como CLP es
   absurdo y `MAX_PLAUSIBLE_CLP` no lo atrapa porque está *por debajo*, no por
   encima.
2. **Convertir mete el tipo de cambio dentro de la señal.** `discount_real` es
   `1 − price_today / p50_60d`; si el precio se convierte a CLP cada día, el p50
   de 60 días mezcla 60 tipos de cambio distintos y **el detector marcaría
   "oferta real" cada vez que el peso se aprecia**. Es el mismo defecto que el
   p50 del tomate de la regla contra estacionalidad, con el dólar en lugar de la
   temporada.
3. Guardar la moneda y comparar solo contra la propia serie en USD sería
   defendible, pero es **una columna nueva en `price_points` y una segunda unidad
   en todo el pipeline** — un cambio de dominio, no un adaptador.

⇒ **Es la primera de la cola el día que haya soporte de moneda**: 14.285 SKUs con
fecha fija, sitemap propio y listado con precios. Lo que sigue pendiente de medir
es su propio costo por pasada y si su listado por destino alcanza para cubrir los
14.285 sin abrir ficha por ficha.

⚠️ Y hay un segundo problema que conviene anotar aunque el primero ya alcance:
**sus otros 10 sitemaps son facetas, no categorías.** `sitemap-barcos.xml` (5.707
URLs), `sitemap-empresas.xml` (2.510) y `sitemap-destinos.xml` (2.104) son
combinaciones barco × destino, compañía × destino y destino × mes — el mismo
catálogo recombinado. Conectar cualquiera de ellos como llave sería solapamiento
masivo, y el único sitemap que es catálogo es `sitemap-productos.xml`.

---

## 3.bis Aerolíneas directas — investigadas el 2026-11-05, y **no abren**

El dueño objetó, con razón, que una baja por temporada baja **es** una oferta
legítima —la gente usa esas vicisitudes del mercado para viajar más barato— y que
el sistema ya tomó esa decisión en otro lado: `LABEL_LIQUIDATION` existe porque el
backtest marcaba `fake` toda liquidación de temporada y eso se corrigió.

Y tenía razón también en lo técnico: **mi "serie 2-D" era un problema de cómo yo
planteaba el SKU, no del detector.** Si `store_sku` es `SCL-LIM:2026-01-14` en vez
de `SCL-LIM`, la serie vuelve a ser 1-D —60 días de observación **del mismo
vuelo**— y una baja ahí se mide como cualquier otra. **No hace falta ningún cambio
de esquema**: al sistema no le importa que el SKU contenga una fecha, solo que sea
estable y único. Lo escribo explícito porque lo había presentado como imposible y
no lo es.

Así que fui a buscar la versión limpia —aerolíneas directas, que venden su propia
tarifa y por lo tanto **no tienen vendedor rotando**—. Medido:

| aerolínea | borde | `robots.txt` | ¿publica tarifa en ruta permitida? |
|---|---|---|---|
| **JetSmart** | 200 con `DEFAULT_UA`, 849 KB | 200, **un solo `Disallow`: `booking.jetsmart.com`** | 🔴 **no** |
| **Sky** | 200 con `DEFAULT_UA`, **22 KB** | 200, **cero `Disallow`** | 🔴 **no** |
| **LATAM** | **403 con `DEFAULT_UA`, 200 con `BROWSER_HEADERS`** | 200, 123 `Disallow` | 🔴 sin determinar |

🔴 **JetSmart**: su sitemap chileno tiene **28 URLs y todas son institucionales**
(términos, quiénes somos, gift cards, mailing list) — **cero páginas de ruta o de
tarifa**. La tarifa vive en `booking.jetsmart.com`, que es **lo único que su
`robots.txt` prohíbe**. Su home tiene 821 menciones de `CLP` y **cero** precios
renderizados: están en el payload de JS. Y su página `packs_jetsmart`, que parecía
la excepción interesante, no trae **ningún** precio (0 patrones de `$`, 0 JSON-LD).

🔴 **Sky**: el `robots.txt` no prohíbe nada —es el más permisivo de toda la Fase
0— y eso no sirve, porque **su home son 22 KB de shell SystemJS sin texto**: cero
hosts propios de API referenciados, cero rutas con pinta de API, todo cargado por
módulos JS en runtime. Para llegar a la tarifa habría que revertir sus bundles
minificados, que es **exactamente** lo que `CLAUDE.md` descartó para el stock de
Paris por "frágil y desproporcionado".

🟡 **LATAM**: pasa el borde con `BROWSER_HEADERS` (patrón Tottus/Nike), pero su
`sitemapindex.xml` dio **timeout en tres intentos** a 60 y 120 s. Queda sin
determinar — es la única de las tres que merece otra sesión.

### La conclusión, y es distinta de la que yo había dado

**La vertical de vuelos no se abre, pero el motivo NO es el que yo dije.** No es
que el detector no pueda con un vuelo: con el SKU bien elegido puede. Es que
**ninguna de las tres aerolíneas publica la tarifa en una ruta permitida y
renderizada en servidor** — están todas detrás de un motor de reservas (prohibido
por robots en JetSmart) o detrás de bundles de JS (Sky).

Lo que sí quedó identificado como costo real, para cuando alguna abra:

1. **Volumen.** Una ruta × 180 fechas de salida son 180 series. Con ~50 rutas
   domésticas son **9.000 series por aerolínea**, contra las ~105.000
   observaciones/día de todo el sistema. Caro, pero acotable a rutas y ventanas.
2. **El SKU muere en la salida.** Con `MIN_DAYS = 30` la ventana útil va de ~30 a
   ~180 días antes del vuelo: los primeros 30 días de cada SKU son inservibles por
   diseño, y después del despegue la serie no sirve para nada.
3. ⚠️ **`detect_ramp` rechazaría justo lo que se busca.** El precio de un vuelo
   **sube estructuralmente** al acercarse la fecha, y el detector rechaza cuando
   hubo un alza sostenida (≥15% sobre el p50 por ≥5 días entre d−21 y d−3)
   **antes** de la baja. Un vuelo que subió como siempre y después tuvo una promo
   quedaría marcado `ramp`. **Esto hay que medirlo con datos reales antes de
   conectar nada**: es la diferencia entre una vertical que funciona y una que
   rechaza el 100% de sus candidatos.

## 4. Los metabuscadores — 🔴 no, y ahora con el motivo correcto

`kayak.cl` y `turismocity.cl` responden 200 en el borde. **No entran igual, y por
dos razones medidas que no tienen nada que ver con la estacionalidad** (ver §3.bis:
el argumento de "una oferta de temporada baja es una oferta" es correcto):

1. 🔴 **El `robots.txt` de Kayak prohíbe exactamente lo que necesitaríamos.** Tiene
   **872 `Disallow`**, y entre ellos **`Disallow: /flights/`** y
   **`Disallow: /hotels/`**. Es el caso Doite: la tienda nos dice que no, por
   escrito.
2. 🔴 **Su precio es de un tercero.** Medido en su home: **210 menciones de
   "proveedor", 133 de OTAs nombradas** (Despegar, Expedia, Booking, eDreams,
   Kiwi) y 222 de "comparar". Es un comparador, y el repo ya decidió esta clase
   con MercadoLibre: *"el precio es por vendedor y la baseline por SKU se rompe"*.
   **Una serie que cambia de vendedor no es una serie** — y eso vale igual para un
   vuelo barato de temporada baja que para un televisor. Es el mismo criterio que
   deja afuera a `solotodo.cl`.

(`turismocity.cl` además declara `Crawl-delay: 15` y solo pasa con
`BROWSER_HEADERS`, así que tampoco sería barato.)

---

## 5. `cocha.com` y `travelsecurity.cl` — 🟡 pendientes, y hay que acotarlas

Las dos responden 200 con `DEFAULT_USER_AGENT` y `robots.txt` 200. Son agencias
**mixtas**: venden packs (lo que entra) junto con vuelos y hoteles (lo que no).

No tienen veredicto porque falta lo esencial: **encontrar la ruta de catálogo de
la sección de paquetes** y ver si publica precio en el listado. Si lo hace, el
riesgo que queda es el de §6.2 —un pack con salida fija desaparece cuando se
agota o cuando pasa la fecha, así que su vida puede ser menor que `MIN_DAYS`— y
ése es el riesgo principal de la vertical, no el acceso.

**Recomendación: no empezar por acá.** Tours (`nomades.com`) tiene SKU
permanente; los packs tienen SKU con fecha de vencimiento. Conectar primero lo
que sabemos que sobrevive, medir su estabilidad real a los 30 días, y recién
entonces decidir si vale la pena pelear con los packs.

---

## 6. Resumen

| | ¿entra? | por qué |
|---|---|---|
| **Tours y actividades** (`nomades.com`) | 🟢 **sí, y primero** | CLP, stock real, SKU en la URL, JSON-LD, robots permisivo |
| **Cruceros** (`cruceros.cl`) | 🟡 **sí, tras el soporte de moneda** | 14.285 zarpadas; cotiza en **USD** y eso ahora se acepta (§2.bis). Lo prohibido sigue siendo **convertir** |
| **Packs** (`cocha`, `travelsecurity`) | 🟡 después | Falta la ruta de catálogo, y el SKU con fecha fija puede no llegar a `MIN_DAYS` |
| **Vuelos y hoteles vía metabuscador** (`kayak`, `turismocity`) | 🔴 no | Kayak **prohíbe `/flights/` y `/hotels/`** en su robots, y su precio es de un **proveedor tercero** que rota (caso MercadoLibre) |
| **Vuelos de aerolínea directa** (`jetsmart`, `sky`, `latam`) | 🔴 no, por ahora | **Ninguna publica la tarifa en ruta permitida renderizada en servidor**: motor de reservas prohibido por robots (JetSmart) o bundles de JS (Sky). LATAM sin determinar. El detector **sí** podría con ellas si el SKU incluye la fecha — ver §3.bis |
