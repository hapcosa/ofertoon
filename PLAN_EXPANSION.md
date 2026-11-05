# PLAN_EXPANSION.md

Plan de expansión de verticales, escrito el **2026-11-04** para que lo ejecute
**otro agente en su propio worktree y rama**.

Cubre seis frentes pedidos por el dueño: **hardware/tecnología**,
**outdoor/deporte**, **ropa**, **mayoristas** (supermercado y ferretería de
reventa), **viajes** y **vehículos** (usados y nuevos). Los cuatro primeros son más
tiendas para el sistema que ya existe. Los dos últimos no: viajes y los vehículos
usados **rompen la regla 1 del CLAUDE.md**, así que tienen una sección de diseño
cada uno (§6 y §7) en vez de una lista de tiendas. El veredicto corto de esas dos:
de viajes entra el **pack vendido como producto**, no la búsqueda de hoteles ni de
vuelos; de vehículos entran los **repuestos** y con reservas los **nuevos**, no los
usados.

**La Fase 0 es una investigación exhaustiva y es bloqueante.** Nada se conecta
antes de que esté escrita y revisada. No es burocracia: en este repo el
diagnóstico de acceso a una tienda se equivocó **tres veces** —Tottus, Jumbo y
Santa Isabel estaban marcadas como bloqueadas y las tres eran viables— y cada
error costó semanas de catálogo no recolectado.

---

## 0. Antes de empezar: el worktree, y una trampa de arranque

```bash
cd ~/servicios/ofertoon
git worktree add ../ofertoon-expansion -b feat/expansion-verticales
cd ../ofertoon-expansion
```

⚠️ **Un worktree arranca del último COMMIT, no del árbol de trabajo**, y eso ya
fue un problema real al escribir este plan: el trabajo del 2026-11-04 —el
adaptador `cencosud_family`, el fix de `scripts/aceptacion_tienda.py` y las
migraciones **36 a 39**— estaba sin commitear, así que un worktree creado en ese
momento no lo habría visto y el agente habría numerado su primera migración como
la 36, que ya existe. Quedó commiteado antes de crear el worktree.

**Verificar igual antes de escribir una sola línea**, porque el mismo riesgo vuelve
cada vez que esta rama tiene trabajo en vuelo:

```bash
ls migrations/ | tail -4        # tiene que mostrar 36, 37, 38 y 39
ls scrapers/stores/             # tiene que estar cencosud_family.py
git log --oneline -1            # y el último commit tiene que incluirlos
```

Si no están, pedirle al dueño que commitee antes de seguir.

### Lo que el agente del worktree NO hace

- **No aplica migraciones y no reconstruye contenedores.** El worktree comparte el
  Postgres `:5436` y el proyecto Docker con producción, que está **encendida**
  (scraper cada 12 h, publisher y gate activos, `GATE_ENABLED=true`). Un
  `db-migrate` desde el worktree escribe en la base real. Las migraciones se
  **escriben** y se dejan sin aplicar; aplicarlas es una acción del dueño.
- **No reinicia el scraper mientras hay una pasada corriendo.** Mata la pasada a
  medias, que es exactamente el modo de falla que `runner.pasadas_flacas` vigila.
  Verificar con `scrape_runs` antes de cualquier cosa.
- **No toca signalsTrading** (`KryptoLab/`, `PySignalGenerator/`,
  `reconcile_daemon/`, Postgres `:5434`).
- **No commitea ni pushea salvo que el dueño lo pida.** `gh` no está autenticado
  en este host, así que tampoco se pueden abrir PRs.
- **No construye evasión de bot management.** Es la línea que el repo ya fijó: con
  `BROWSER_HEADERS` se llega hasta donde se llega, y una tienda que de verdad no
  nos quiere, no nos tiene. Sin fingerprint de TLS, sin navegador headless.

---

## 1. Fase 0 — Investigación exhaustiva (bloqueante)

El entregable es **un documento por vertical** en el worktree
(`INVESTIGACION_<vertical>.md`) con una fila por tienda y **las doce respuestas de
abajo**. Una tienda sin las doce no pasa a implementación.

No alcanza con "responde 200". Las doce preguntas no son un formulario: cada una
existe porque su ausencia ya rompió algo en producción, y la referencia está en
`CLAUDE.md` §Trampas conocidas.

| # | Pregunta | Por qué, y qué la invalida |
|---|---|---|
| 1 | **¿Qué plataforma usa DE VERDAD?** | Tottus estuvo descartada semanas porque su API VTEX daba 503 — y Tottus no es VTEX, corre la plataforma de Falabella. Un 503 de una API que la tienda no usa no dice nada del origen. Buscar la firma en el HTML (`__NEXT_DATA__`, `vtex`, `Magento`, `Shopify`, `demandware`/`dwr`), no adivinar rutas. |
| 2 | **¿El `robots.txt` permite el listado, y declara `Crawl-delay`?** | El `rate_limit_rps` sale del `Crawl-delay` declarado, nunca de lo que aguante el servidor. SP Digital declara 5 → 0.2. Winpy declara **10** → 0.1, que es un presupuesto de fetches ridículo y puede ser razón para no conectarla. Si prohíbe los listados, es Lider: vía permitida pero carísima. |
| 3 | **¿Pasa con `DEFAULT_USER_AGENT`?** Si no, ¿con `BROWSER_USER_AGENT`? ¿Con `BROWSER_HEADERS`? | Probar los tres, **4 intentos de cada uno**, aislando la variable. Y la trampa caro: **un 429 persistente puede ser el UA y no la tasa** — Prat da 429 las 4 veces con el UA identificable y 200 las 4 veces con el de navegador. Bajar el rps no lo arregla nunca. Ante un 429, probar el UA ANTES de tocar el rps. |
| 4 | **¿Pagina? ¿Con qué parámetro? ¿Y cómo señala el final?** | No todas devuelven lista vacía: Easy y Cencosud dan **HTTP 404**, Falabella/Easy sirven la página sin el bloque de productos. Si el adaptador no lo distingue de un error real, el runner marca `failed` la categoría entera y **pierde el lote pendiente del buffer**. Y verificar que el parámetro sobreviva a una redirección. |
| 5 | **¿El orden es estable entre requests?** | **La pregunta que más barato sale y más caro cuesta ignorar.** El default de Tottus es `_score,desc` con boost de publicidad y cambia entre requests: 0,911 de cobertura y dos recorridos del mismo día dando 326 y 389 únicos. Un SKU que aparece de forma intermitente **nunca llega a `MIN_DAYS` y por lo tanto nunca produce una baseline**. Medir: dos recorridos completos de la misma llave, contar únicos. Si es inestable, buscar un orden determinista antes de dar el faltante por perdido. |
| 6 | **¿Declara el total de la categoría? ¿Dónde?** | Es la diferencia entre el canario exacto y una inferencia. VTEX lo pone en el **header** `Resources: 0-49/2546`; Magento en el **último** `span.toolbar-number` (quedarse con el primero daba 1 para 1.080 y **pasaba el canario en silencio**); Cencosud en un `<span>` junto al `<h1>`. ⚠️ Y declarar el total **no** significa que el canario exacto sea viable: ver §3. |
| 7 | **¿Trae GTIN/EAN? ¿En qué fracción, y medido sobre más de una página?** | Es lo único que desbloquearía el cross-store, que hoy da **cero mensajes**. Y la medición miente si se hace en la página 1: Paris trae EAN solo en los primeros ~60 por **posición absoluta**, así que el fixture de la página 1 engaña. |
| 8 | **¿Trae `price_normal` (el "antes" tachado)?** | Si no lo trae, el θ de su categoría **no se puede fijar midiendo** (caso Nike y caso Cencosud) y hay que heredarlo de los vecinos, anotándolo como herencia y no como medición. |
| 9 | **¿Hay señal de stock en el LISTADO, y es señal o es otra cosa?** | El `availability` del listado de Tottus habla de **modos de envío**, no de stock. Verificarlo **contra productos agotados**, no contra los que están a la venta: el camino feliz no ejercita la guarda. En Cencosud la prueba de que sí es señal fue que los agotados caen al final del orden. |
| 10 | **¿Usa precios centinela?** | Falabella publica $99.999.999.999 para productos sin precio real. Un valor así **envenena la baseline del SKU para siempre**. Reportar el precio máximo observado sobre el catálogo completo. |
| 11 | **¿Las llaves candidatas son disjuntas SOBRE SKUs REALES, y son catálogo o vitrina?** | Dos `store_key` solapados hacen pesar el doble a un listing en su propio p50. Y una vitrina curada a mano se ve igual que un catálogo hasta que el comerciante la reedita: Prat perdió 240 series de productos **que seguían a la venta**. ⚠️ El tamiz de la tasa de stock es de Shopify y **no transfiere** (en Cencosud los departamentos traen 90-97% y son catálogo); lo que vale es cruzar los SKUs y mirar si la llave es un nodo de la navegación propia de la tienda. |
| 12 | **¿Cuánto cuesta por pasada: requests, MB y listings?** | El sistema está en ~105.000 observaciones/día y la pasada en ~57 min después de las dos cadenas de hoy. `db.PASS_WINDOW` son 2 h: una pasada que las cruce se partiría en dos para la guarda de volumen. Cada tienda nueva tiene que venir con su número. |

### El tamiz de la página 1, que aplica a TODO lo que se mida acá

**Cualquier fracción medida sobre una sola página no sirve para decidir nada.** Ya
pasó tres veces: los GTIN de Paris (solo los primeros ~60), el descuento declarado
de Tottus (79% sobre 48 productos contra 43% sobre 192 — alcanzó para inventar dos
categorías que no existían) y el stock de Cencosud (0,8% de agotados en la página 1
contra 12,7% en el catálogo). Mínimo **4 páginas**, y cuando se pueda el catálogo
completo.

### Verdictos que ya existen y hay que RE-verificar, no heredar

`PLAN_TIENDAS.md` §2 tiene una tabla auditada al 2026-09-23 y al 2026-10-01. Es el
punto de partida — y su lección principal es que **se equivocó tres veces**. Para
cada tienda que ahí figure como bloqueada, la Fase 0 tiene que decir si el
veredicto sigue en pie, con fecha y con el método de la pregunta 1.

⚠️ Las dos excepciones donde el "no" es firme y **no hay que volver a intentar**:

- **Unimarc** — once accesos probados, 403 en todo, hasta en `smu.cl`. Lo único que
  queda es evasión.
- **Decathlon, Nice One, MTS, Imperial, Adidas** — 403 duro de Cloudflare/Akamai
  con `BROWSER_HEADERS` puesto. Decathlon es "la más valiosa de la categoría y la
  más difícil" y sigue siéndolo. Re-chequear el `robots.txt` y el borde una vez
  (cuesta un request) y si sigue en 403, se para ahí.

---

## 2. Los cuatro frentes de tiendas, y dónde está lo barato

El orden de esta sección **es** la prioridad sugerida, y el criterio es costo de
adaptador contra catálogo aportado — no simpatía por la vertical.

### 2.1 Lo que cuesta casi nada porque la familia ya existe

Esto es lo primero que la Fase 0 tiene que confirmar, porque si se sostiene son
tiendas a **una fila en `stores` + un fixture**, sin una línea de adaptador.

| Tienda | Familia que ya existe | Estado en el repo |
|---|---|---|
| **Sparta** (`sparta.cl`) | `magento_html` | ⭐ **El más barato de todo el plan**: ya tiene fixture (`tests/fixtures/sparta_zapatillas.html`) y los dos bugs que encontró —el total en el último `toolbar-number` y el `price-label` que no es stock— ya están arreglados **en la familia**. No está conectada y es la cadena deportiva nacional. |
| **Colloky** (`colloky.cl`) | `vtex_family` | API de catálogo pública confirmada devolviendo productos (PLAN_TIENDAS §2.4). Ropa infantil. |
| **Doite** (`doite.cl`) | `shopify_family` | `/products.json` verificado. Camping, carpas, sacos. |
| **Lippi** (`lippioutdoor.com`) | `shopify_family` | `/products.json` verificado. Ropa y equipo outdoor. |

⚠️ Para los tres últimos, `vtex_family` y `shopify_family` traen su propia letra
chica que la Fase 0 tiene que chequear por tienda: en VTEX **la paginación profunda
corta en ~2.500**, así que las llaves son las subcategorías y nunca la raíz; y **un
producto VTEX tiene N items que son los talles**, así que se emite uno por producto
con el precio del talle **disponible más barato** (tomar el de un talle agotado
publica un precio que nadie puede pagar).

### 2.2 Hardware y tecnología

Las dos que pidió el dueño **no están auditadas en ningún plan**, así que arrancan
de cero en la Fase 0:

- **`myshop.cl`**
- **`megabytes.cl`**

Y la vertical tiene un contexto que conviene no ignorar: PLAN_TIENDAS §2.3 dice que
es **el margen de mejora más bajo del plan** porque SP Digital y PC Factory ya la
cubren y son las dos de mejor rendimiento por SKU. Eso era antes de medir que
`spdigital` da **4% de estabilidad de cohorte** y `pcfactory` **39%** (las dos bajo
el umbral de apagado), así que el argumento se da vuelta: la categoría necesita
tiendas que **acumulen serie**, no más catálogo. **La pregunta 5 (orden estable) y
la 11 (catálogo o vitrina) son las que deciden acá**, no el tamaño.

Candidatas a barrer, además de las dos de arriba: Winpy (⚠️ `Crawl-delay: 10`),
MacOnline, Zmart, TecnoPlaza, Reifstore, Infor-Ingen, PC Mix, SpaceStore,
Dinamicpc, Mercado Digital. Ninguna verificada: es trabajo de la Fase 0 descubrir
cuáles existen, cuáles venden de verdad y cuáles son revendedores de catálogo
ajeno. **Ojo con los agregadores**: Solotodo y similares son comparadores de
precio, no tiendas — su "precio" es de terceros y no tiene serie propia.

### 2.3 Outdoor y deporte

Categorías ya existentes (`deporte-calzado` 0.300, `deporte-vestuario` 0.350,
`deporte-equipamiento` 0.250) con Andesgear (79% de estabilidad, 1.059 aceptados) y
Nike conectadas.

Además de Sparta, Doite y Lippi de la §2.1: Mountain (`mountain.cl`, 200 sin
determinar), Rockford, Columbia Chile, The North Face Chile, Patagonia Chile,
Puma Chile, New Balance Chile, Under Armour Chile, Bazar Deportivo, Mundo Ciclismo,
Bikeshop. **Decathlon**: ver la excepción de la §1.

⚠️ Para toda tienda de marca con talles, vale la letra chica VTEX de la §2.1. Y
para toda tienda outdoor, **la liquidación de temporada es una oferta y va al
canal** (decidido el 2026-10-01): el detector ya la acepta porque `detect_ramp`
exige un alza sostenida ANTES de la baja, y `LABEL_LIQUIDATION` arregla la
medición. No hay nada que hacer, solo no "arreglarlo".

### 2.4 Ropa

Categorías `ropa-calzado` (0.350) y `ropa-accesorios` (0.350), hoy alimentadas por
Falabella y Nike.

El hallazgo de PLAN_TIENDAS §2.4 que vale la pena perseguir: **Hites, La Polar,
Tricot y ABCDin corren las cuatro Salesforce Commerce Cloud**. O sea **un adaptador
nuevo (`salesforce_family.py`) cubre cuatro tiendas**, y ABCDin además es mixta
(ropa + tecno + electro) así que cae en categorías que ya existen. Es el mejor
retorno por adaptador escrito que queda en el plan.

Candidatas sin auditar: Zara Chile, H&M Chile, Mango Chile, Rip Curl, Billabong,
Opaline, Foster (Next.js, costo L). **Dafiti y Ripley** son marketplaces o casi:
precio por vendedor, con el mismo ruido que MercadoLibre — la Fase 0 tiene que
decir si el precio que se ve es de un vendedor estable o rota entre sellers,
porque una serie que cambia de vendedor no es una serie.

### 2.5 Mayoristas: supermercado de reventa y ferretería

Lo que pidió el dueño: **Don Lee** y las que venden para que otras tiendas
revendan, incluida ferretería.

Candidatas: Don Lee, Alvi, Mayorista 10, Central Mayorista, Adelco, Rabie, Dipac,
Comercial Montserrat; y en ferretería Dartel, Weldmar, Electro Comercial,
Sodimac Constructor, Imperial (403 duro).

⚠️ **Esta vertical rompe tres supuestos y la Fase 0 tiene que medirlos explícitamente**:

1. **El precio puede estar detrás de un login o de una sucursal.** Es el caso
   Construmart ya resuelto: su HTML público no trae un solo `$` y todas las filas
   salen "Sin Stock" hasta que se manda la cookie
   `persistent_customer_group_id=35`. En un mayorista eso es la norma, no la
   excepción. Y hay una consecuencia dura: **la serie es la de esa sucursal o ese
   grupo de cliente**, así que cambiarlo después invalida el histórico entero de la
   tienda. Si el precio exige una cuenta, **eso es una decisión del dueño**, no del
   agente.
2. **La unidad de compra es la caja, no la unidad.** El `pum` (precio por unidad de
   medida) deja de ser copy y pasa a ser el único número comparable. Hoy
   `price_points.pum_price` existe y `formatter.PUM_CATEGORIES` lo limita a
   `supermercado`.
3. **El rango de ticket es otro otra vez.** Un pallet de detergente no compite con
   un televisor ni con un detergente suelto. Si entra, probablemente quiere su
   propia categoría y su propio tema, como pasó con `supermercado` y con `belleza`.

### 2.6 Lo que NO se conecta, en ninguna vertical

- **Categorías de precio estacional.** `Frutas-y-Verduras` y `Carnes` quedaron
  afuera a propósito: el p50 de 60 días de un tomate es el promedio de dos
  temporadas y el detector marcaría "oferta real" cada vez que baja la
  estacionalidad. Lo mismo aplica a cualquier vertical: en deporte, el equipo de
  nieve; en ropa, la temporada.
- **Perecederos de rotación diaria.** Segunda razón, independiente: lo que no se
  puede guardar no se compra en cantidad.
- **Reacondicionado.** `detector.REJECT_REFURBISHED` ya lo rechaza, y está medido
  por qué: en `tecno-celulares` la precisión sube de 67,4% a 78,1% al sacarlos, y
  son el 46% del catálogo de celulares. Para una tienda de hardware usado, el
  filtro va a rechazar casi todo — eso no es un bug, es la razón para no
  conectarla.
- **Hardware de servidor.** `detector.REJECT_SERVER_HW`, por los dos discos HPE de
  $6M y $7,8M que se llevaron 2 de los 14 lugares de un día.

---

## 3. Lo que hay que decidir por tienda, y que no es obvio

Tres cosas que la Fase 0 produce como **recomendación** y que el implementador
tiene que resolver antes de escribir la migración:

1. **¿Canario exacto, sí o no?** Que la tienda declare el total no alcanza. La
   familia Falabella **no puede** sostenerlo (repite productos cuanto más profundo
   se pagina: el gap es función de la profundidad y dejaba 19 llaves en `partial`
   permanente) y Cencosud **tampoco** (el total declarado y el grid derivan entre
   sí: 7 de 10 llaves quedan 1-10 ítems cortas, y la misma llave da 1,0000 en un
   recorrido y 0,9988 en el siguiente). Un `partial` manda un mensaje de Telegram
   **por pasada**: una alarma que suena siempre es una alarma apagada. El criterio
   es: implementarlo solo si lo enumerado iguala lo declarado de forma **estable**
   sobre recorridos completos repetidos. Y **nunca ponerle una tolerancia** —
   cualquier umbral es inventado.
2. **¿`max_pages` alcanza?** El recorte por `max_pages` es **silencioso**: el
   volumen enumerado queda estable pasada a pasada, así que el canario estadístico
   lo ve sano. En la familia Falabella eso recortó el catálogo **diez días** (960 de
   18.412). Dimensionarlo contra la llave más grande **y** dejar el aviso
   `catalogo_mas_grande_que_la_ventana`.
3. **¿Categoría existente o nueva?** La regla medida es: **un solo comportamiento
   de precio → una sola categoría**. Con 4 páginas por llave, las cinco llaves de
   Tottus dieron la misma distribución (p50 del descuento declarado 18-22%) → una
   categoría. Pero la migración 24 mandó separar cuando la distribución difería. Si
   la tienda no declara `price_normal`, esto **no se puede medir** y el θ se hereda.

---

## 4. Entregables por tienda que se conecte

Sale de `CLAUDE.md` §Agregar una tienda y `PLAN_TIENDAS.md` §5:

1. Módulo en `scrapers/stores/` que implemente `StoreAdapter` — **o solo una fila**
   si la familia ya existe.
2. **Fixture con payload real** en `tests/fixtures/`, recortado y con un comentario
   que diga de qué URL salió, en qué fecha y qué se podó. Si la tienda tiene stock
   en el listado, **el fixture tiene que incluir productos agotados**.
3. Tests de contrato.
4. **Migración numerada** (la próxima libre después de la 39 es la **40**) con la
   fila en `stores`, sus `store_categories` mapeadas a la taxonomía canónica, la
   **fecha de conexión anotada** y la fecha de evaluación = conexión + 30 días.
   Categorías nuevas → θ de partida explícito y anotado como **no calibrado**.
5. Los 781 tests pasando con `TEST_DATABASE_URL` apuntando a una base
   **descartable** (el setup hace `DROP SCHEMA public CASCADE`):

   ```bash
   set -a && . ./.env && set +a && \
   export TEST_DATABASE_URL="postgresql://ofertas:$POSTGRES_PASSWORD@localhost:5436/ofertas_test" && \
   .venv/bin/python -m pytest -q
   ```

   Sin `TEST_DATABASE_URL` saltea los 54 de DB y **parece verde**: no vale.

**Nunca editar una migración ya aplicada**: `migrate.py` guarda checksum y grita
`checksum_mismatch`. Si hay que corregir, se escribe una nueva.

---

## 5. Presupuesto: por qué no se conectan veinte tiendas de una

Estado al 2026-11-04, después de Jumbo y Santa Isabel:

| | |
|---|---|
| Tiendas activas | 17 |
| Categorías | 15 |
| Targets activos | 165 |
| Observaciones/día | ~105.000 |
| Duración de la pasada | ~57 min (era ~41 antes de hoy) |
| `db.PASS_WINDOW` | **2 h** |

El runner es **secuencial**: recorre tienda por tienda y llave por llave en un solo
`HttpClient`. Así que el tiempo de pasada crece lineal con los requests, y hay un
techo real: **una pasada que supere `PASS_WINDOW` se parte en dos** para
`runner.pasadas_flacas`, y eso convierte la guarda de volumen en una fuente de
falsos positivos. Con ~57 min usados de 120, el presupuesto que queda es de **una
hora de requests**, o sea del orden de 1.800 requests a 0,5 rps.

Dos consecuencias para el plan:

- **Conectar por tandas**, midiendo la duración de la pasada después de cada una.
- Una tienda con `Crawl-delay` alto se come el presupuesto de varias: Winpy a 0,1
  rps son **10 s por request**, o sea 360 requests por hora de pasada.

Y el recordatorio que vale para todas: **una tienda nueva no publica nada durante
30 días** (`MIN_POINTS`/`MIN_DAYS` son un rechazo, no un default), así que el
retorno de esta fase se ve en diciembre de 2026, no en noviembre.

---

## 6. Viajes: el tema existe, está mudo, y no se llena con un adaptador

`telegram_topics.viajes` existe (`message_thread_id = 20547`, cuota 1) y **tiene
cero categorías ruteadas**, así que hoy no publica nada. La pregunta del dueño es
cómo abordarlo: hoteles, Airbnb, buses, cruceros, aviones, packs todo pagado.

**La respuesta corta: la mayoría de eso no entra en este sistema, y el motivo no es
el acceso sino el detector.** Esta sección es análisis para que la Fase 0 no se
gaste en scrapear Booking antes de entender el problema.

### 6.1 Por qué rompe la regla 1

La señal del sistema es **una sola línea**:
`discount_real = 1 − price_today / p50_60d`, y el p50 es de los últimos 60 días de
observación de **un** `listing`, que es un par (tienda, `store_sku`).

Un pasaje o una noche de hotel **no tienen un precio**: tienen un precio por fecha
de viaje. El precio de "LATAM SCL-LIM" no existe; existe el de SCL-LIM el 14 de
enero en economy. Así que:

1. **La identidad se parte en dos dimensiones**: el producto (propiedad, ruta) × la
   fecha de viaje. La serie pasa de 1-D (precio por día de observación) a 2-D
   (precio observado el día *t* para la fecha de viaje *d*).
2. **El p50 de 60 días de observación mezcla 60 fechas de viaje distintas**, o sea
   fines de semana con días de semana y temporada alta con baja. Es exactamente el
   p50 del tomate de la regla contra categorías estacionales, pero peor: en el
   tomate la estacionalidad es del precio, acá es **del producto mismo**.
3. **La comparación correcta es otra**: "¿está más barato de lo que ha estado
   **para esta fecha de viaje**?". Eso es un detector distinto, no un adaptador
   distinto, y además tiene una asimetría que el actual no tiene — el precio de un
   vuelo sube estructuralmente al acercarse la fecha, así que una baja cerca de la
   salida significa algo distinto que la misma baja seis meses antes.
4. **La explosión combinatoria es real**: 100 propiedades × 180 fechas de salida ×
   3 tipos de habitación son **54.000 series** por ciudad. El sistema entero hace
   ~105.000 observaciones por día.

A eso se suma lo obvio: Airbnb y las OTAs grandes prohíben el scraping en sus
términos, y las aerolíneas tienen bot management de verdad — o sea la línea que
este repo ya decidió no cruzar.

### 6.2 Lo que SÍ encaja sin tocar el detector

Hay un subconjunto de viajes que **tiene SKU con precio publicado y sin fecha en el
precio**, y ese entra con el sistema tal como está. La Fase 0 de esta vertical es
exactamente **buscar cuáles de estos existen en Chile con catálogo accesible**:

- **Packs todo pagado vendidos como producto**: el paquete "7 noches en Punta Cana,
  salida 12 de enero" es un SKU con una fecha fija y un precio por persona. Se
  comporta como catálogo: tiene precio de lista, tiene promoción y tiene serie.
  Candidatos a investigar: Cocha, Viajes Falabella, Travel Security, Despegar
  (packs), Turismo Cocha, Viajes El Corte Inglés Chile.
- **Cruceros por salida**: cada zarpada es un SKU con fecha fija y precio por
  categoría de cabina.
- **Tours y actividades**: precio por producto, sin fecha en el precio.
- **Gift cards y vouchers de viaje**: SKU puro.

⚠️ Y hay que medir, no suponer, **dos cosas específicas de esta vertical**:

- **¿El precio es por persona, por pareja o total?** Un cambio de base es el error
  del `pum`: dos precios de bases distintas no se comparan sin normalizar.
- **¿El SKU sobrevive 30 días?** Un pack con salida fija **desaparece del catálogo
  cuando se agota o cuando pasa la fecha**, así que su vida puede ser más corta que
  `MIN_DAYS` y entonces nunca produce baseline. Esto se mide con
  `scripts.aceptacion_tienda` **después** de conectar, pero se puede estimar antes:
  ¿cuántos de los packs de hoy siguen publicados en 30 días? Si la respuesta es
  "pocos", la vertical no funciona con este detector y **no hay adaptador que lo
  arregle**. Es la misma pregunta que el umbral de estabilidad le hace a cualquier
  tienda, solo que acá se sabe de antemano que es el riesgo principal.

### 6.3 La recomendación

**No construir búsqueda de hoteles ni de vuelos dentro de OfertasCL.** Sería un
segundo producto con un segundo detector (serie 2-D por fecha de viaje), y hacerlo
adentro contaminaría el único activo del proyecto: que `discount_real` significa
una sola cosa.

Lo que sí se puede hacer ya, y es lo que la Fase 0 debe acotar: **packs, cruceros y
tours como catálogo**, con la pregunta de supervivencia del SKU (§6.2) respondida
ANTES de escribir el adaptador. Si esa pregunta da mal, el tema `viajes` se queda
mudo con razón y conviene decirlo en vez de llenarlo con ofertas que el sistema no
puede validar.

---

## 7. Vehículos: la vertical se parte en tres y solo dos tercios sirven

Pedido por el dueño: **vehículos usados y nuevos**. La respuesta no es una sola,
porque "automotriz" son tres negocios con tres formas de precio distintas, y el
sistema les responde cosas distintas.

### 7.1 Usados: el detector YA los rechaza, y tiene razón

`detector.REJECT_REFURBISHED` llama a `catalog.normalize.es_segunda_mano`, que
marca el nombre contra siete patrones — y **uno de ellos es literalmente
`"usado"`**. O sea un listing de auto usado se rechaza por nombre antes de llegar
al umbral, hoy, sin tocar una línea.

Y el motivo del docstring de esa función es **exactamente** el del auto usado:

> un reacondicionado **no tiene la curva de precio de una oferta**: baja y se queda
> abajo, porque el precio sigue la depreciación y el grado del equipo, no una
> promoción

Un Corolla 2019 con 80.000 km no baja de precio porque esté en oferta: baja porque
se deprecia y porque le suman kilómetros. Es el mismo `SIGUE_BAJO` que explica el
68% de los `fake` del backtest, pero estructural en vez de ocasional.

Y hay dos razones independientes, cada una suficiente por sí sola:

1. **El SKU no sobrevive, y además es único.** Cada unidad usada es un `store_sku`
   distinto (una patente, un VIN) que aparece una vez y desaparece cuando se vende.
   `MIN_DAYS = 30` exige treinta días de serie **del mismo listing**: un auto que se
   vende en tres semanas nunca produce baseline. Es el mismo problema que los packs
   de viaje de la §6.2, pero garantizado en vez de probable.
2. **La comparación correcta es transversal, y este sistema la rechaza a
   propósito.** Para un usado la pregunta útil es "¿está barato **contra autos
   comparables**?" —mismo modelo, año y banda de kilometraje—, o sea un p50 de un
   corte transversal. Este repo tiene una regla escrita contra eso: el criterio de
   aceptación mide por **cohorte y no transversalmente** porque lo transversal mete
   en el denominador cosas que no son comparables, y el caso Easy (34% transversal
   contra 96% por cohorte) es el ejemplo. Un detector de usados sería un modelo
   hedónico de comparables: **otro producto, con otro detector**, igual que la
   búsqueda de hoteles.

**Recomendación: no se conectan vehículos usados.** Si el dueño los quiere, lo que
corresponde es decidirlo como producto aparte — y entonces hay que sacar `"usado"`
de `_SEGUNDA_MANO`, que es un cambio que afecta a **todas** las categorías y que
degradaría `tecno-celulares` en 10-30 puntos de precisión. No se hace de costado.

### 7.2 Nuevos: entran, pero con dos problemas que hay que medir antes

Un vehículo nuevo **sí** es un SKU estable: (marca, modelo, versión, año) vive
meses, y su precio se mueve por campaña comercial, que es justo lo que el detector
busca. Así que técnicamente encaja. Lo que hay que medir en la Fase 0:

1. **El "desde $" y el bono.** El precio publicado de un auto nuevo suele ser
   `desde $X` por la versión más barata, y el precio real cuelga de un bono por
   financiamiento con la automotora. Eso es **el `cmrPrice` de Falabella llevado al
   extremo**: la regla del sistema es que `price_effective` es *el que paga
   cualquiera, sin plástico de la casa*, así que un precio que exige crédito propio
   va a `price_card` y **no** al efectivo. Si la tienda publica **solo** el precio
   con bono, no hay `price_effective` que recolectar y la tienda no entra.
   Medirlo explícitamente, ficha en mano y contra varias marcas.
2. **El rango de ticket rompe el score, al revés que el supermercado.**
   `compute_score` es `discount_real*100 + below_floor*50` y **no mira el precio
   absoluto** a propósito. Con supermercado el problema fue que un ahorro de $670
   puntuaba igual que uno de $20.000; con autos es al revés: un 10% sobre $20
   millones son **$2 millones** de ahorro puntuando 10, por debajo de un 30% en
   unas zapatillas. Igual que con supermercado, **la solución no es tocar el score**
   sino darle destino propio: categoría propia y tema propio.
3. **El techo de plausibilidad alcanza, pero por poco.**
   `MAX_PLAUSIBLE_CLP = 100.000.000` cubre un auto ($15-40M) y **`RawProduct`
   levanta `ValueError` por encima**, así que un camión o una maquinaria de más de
   $100M se descartaría en el adaptador. Para autos no es problema; si la vertical
   se extiende a camiones, hay que mirarlo.

Candidatas a barrer en la Fase 0 (ninguna auditada): sitios de marca (Toyota,
Chevrolet, Suzuki, Hyundai, Kia, Nissan, Peugeot, MG, Chery) y grupos
concesionarios (Kaufmann, Ditec, Salazar Israel, Bruno Fritsch, Curifor, Coseche,
Rosselot, Williamson, Autofrance). ⚠️ Y una pregunta propia de la vertical: **¿el
precio es nacional o por concesionario?** Si es por sucursal, es el caso Construmart
—la serie sería de esa sucursal y cambiarla invalida el histórico— y conviene
decidirlo antes, no después.

### 7.3 Repuestos y accesorios: acá está lo que funciona hoy

Es el tercio que el pedido no nombra y probablemente el más rentable: **un
amortiguador, una batería, un juego de pastillas o una alfombra son catálogo puro**
— SKU estable, precio publicado sin crédito, stock, muchas veces GTIN, y promoción
real. Se comporta como la ferretería, que es la vertical donde el sistema mejor
rinde (Ferretek 99% de estabilidad, Prat 96%, Construmart 92%).

Entra en una categoría nueva tipo `auto-repuestos` con θ heredado de
`ferre-herramientas` (0.250) hasta que el backtest lo calibre, y muy posiblemente
sin tema nuevo: cabe en Ferretería.

Candidatas a barrer: Autoplanet, Mundo Repuestos, Pardo Repuestos, Repuestos
Fierro, Dercocenter Repuestos, Bosch Car Service, y las tiendas de neumáticos
(Pana, Neumáticos Chile). **Ojo con la compatibilidad**: muchos listados de
repuestos se navegan por (marca, modelo, año) del vehículo y el mismo repuesto
aparece bajo decenas de combinaciones — eso es solapamiento masivo entre llaves y
la pregunta 11 de la Fase 0 es acá la más importante de todas. La llave buena
probablemente sea la categoría de producto (`baterias`, `amortiguadores`), no el
árbol de compatibilidad.

### 7.4 Resumen de la vertical

| | ¿entra? | por qué |
|---|---|---|
| **Repuestos y accesorios** | 🟢 sí, y es lo primero | Catálogo puro, igual que ferretería |
| **Vehículos nuevos** | 🟡 sí, con categoría y tema propios | Mide primero el "desde $"/bono y si el precio es por concesionario |
| **Vehículos usados** | 🔴 no | El SKU no sobrevive a `MIN_DAYS`, la comparación correcta es transversal, y `es_segunda_mano` ya los rechaza por nombre con el razonamiento correcto |

---

## 8. Qué NO hace este plan

- No decide apagar ninguna tienda. `UMBRAL_ESTABILIDAD = 0.40` manda apagar
  Falabella (8%) y Paris (15%), que son el **46% del canal** y llevan 114
  publicaciones cada una. Está sin calibrar y es decisión de producto.
- No toca θ, ni el score, ni `MIN_MINUTES_BETWEEN`. El ritmo del chat es una
  decisión abierta del dueño (con ocho temas el daemon puede poner hasta 13
  mensajes/hora).
- No aplica migraciones ni toca producción. Ver §0.
