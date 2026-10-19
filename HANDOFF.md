# Handoff Ofertoon — estado al 2026-10-01

Pegá el bloque de abajo como primer mensaje de la próxima sesión.

---

Vengo a seguir con **Ofertoon** (antes OfertasCL), en `~/servicios/ofertoon` del
host de producción `10.244.117.161` (repo propio, **no** es signalsTrading).
Rama `feat/migracion-nuevo-prod`, git user `hapcosa`.

## Qué es

Un canal VIP de Telegram con **ofertas reales** de retail chileno. El
diferenciador es que sean reales: nada de precios inflados semanas antes para
después "descontarlos". Eso convierte el proyecto en un problema de **series de
precios**, no de scraping — el scraping es la parte mecánica, el valor está en
el detector. Reusa la maquinaria de suscripción de signalsTrading (bot,
membresías, PayPal), pero con repo, Postgres (`:5436`) y marca separados.

## Reglas que aplican

- Respondé **siempre en español**, directo y sin preámbulo.
- signalsTrading corre en **producción con dinero real**. Ofertoon no lo toca:
  no se modifica nada de `KryptoLab/`, `PySignalGenerator/`, `reconcile_daemon/`
  ni el Postgres `:5434`. De signalsTrading solo se **lee** para portar.
- SQL puro con asyncpg, **sin ORMs**. Migraciones idempotentes numeradas.
- **Avisá cualquier decisión que tomes por tu cuenta**, por chica que parezca.
- Honestidad 100%, cero condescendencia. Si algo falla, decilo con el output.
- **No commitees ni pushees salvo que te lo pida.**

## Estado real (verificado, no supuesto)

**F0, F1, F2 y F3 cerrados en código y desplegados. El detector empezó a aceptar
ofertas el 2026-09-01**, el día que la primera cohorte cruzó los 30 días de
historia. Lo que falta para publicar ya no es baseline: es calibrar θ, y eso
**no se puede antes del 2026-10-02** (ver "Cuándo empiezan a salir ofertas": la
cuenta de 45 días que decía este handoff estaba mal).

- **35.211 listings** en **15 tiendas activas**, **14 categorías**, **153
  objetivos** y 1.261.438 observaciones (2026-10-01 21:00). Por tienda:
  falabella 9.520, **tottus 5.419**, paris 4.949, andesgear 2.794, easy 2.598,
  **nike 2.554**, sodimac 2.048, ferretek 1.583, prat 1.347, spdigital 643,
  pcfactory 629, kruuse 628, urban 249, construmart 226, kupfer 24.
  De 34.329 baselines escritas, **9.742 tienen historia suficiente**
  (`n_points>=30 AND n_days>=30`) — ninguna de las tiendas nuevas todavía.
  `products` saltó de 3.653 a **5.935** porque Nike trae EAN en el 100%.
- **Migraciones 01..28 aplicadas**, 0 pendientes. Las 26, 27 y 28 se aplicaron el
  2026-10-01 en la segunda sesión del día.
- **θ vigentes, los 14 sin calibrar**: tecno-celulares/componentes/notebooks 0.15,
  tecno-tv 0.18, tecno-audio 0.20, hogar-electro 0.20, ferre-* 0.25,
  deporte-equipamiento 0.25, deporte-calzado 0.30, deporte-vestuario 0.35,
  ropa-calzado 0.35, ropa-accesorios 0.35, **supermercado 0.25**.

⚠️ **Dos cosas que este handoff daba por hechas y NO estaban efectivas en
producción, por la misma causa: faltó el rebuild del scraper.** Descubierto el
2026-10-01 a las 20:45 mirando `scrape_runs`:

  * **Las 4 llaves de Nike de la migración 25 nunca corrieron, ni una vez.** No
    había corrida fallida — simplemente no se ejecutaban: el contenedor tenía una
    imagen sin `scrapers/stores/vtex_family.py`, así que su adaptador no se podía
    importar y la tienda quedaba fuera de los targets **sin dejar fila**.
  * **Prat seguía fallando** (`FetchError` en sus dos categorías en la pasada de
    las 15:16), aunque el fix del User-Agent estaba escrito desde la mañana.

Las dos quedaron verificadas en vivo tras reconstruir: Nike 2.554 observaciones en
sus 5 llaves, Prat 1.086 + 49, todas `ok`. **Es la trampa que CLAUDE.md ya
documenta** ("el Dockerfile copia las fuentes, no las monta") y el modo de falla
es el peor: una tienda que no se puede importar no deja rastro en `scrape_runs`,
así que no la ve ninguna de las tres guardas. Después de una migración que conecta
una tienda nueva, **verificar que haya filas en `scrape_runs` para ella**, no
alcanza con que la migración diga "aplicada".
- **Una pasada completa pasó de ~13 a ~20 min**: Andesgear sola cuesta ~7 min por
  su `Crawl-delay: 3`.
- **538 tests con DB** (3:54 contra una base recién creada), **460 sin DB**
  (78 salteados, 2,6 s). El handoff decía ~40 minutos: eso era el `TRUNCATE` de
  `price_points` con datos, no la suite.
- **33 commits**, el último `docs: cerrar la Fase 2 con vestuario adentro`.
- Servicios arriba: `postgres` (healthy), `scraper`, `bot`, `gate`,
  `paypal-webhook`, `publisher`, `cloudflared`. `scraper` corre la imagen
  reconstruida el 2026-09-26 17:08 (Andesgear + los 3 fixes de la familia).
- **La cadencia quedó arreglada y medido en vivo**: las pasadas van a 03:2x y
  15:2x UTC (2 por día, ±10 min), y las mitades de día duplicadas que
  `scripts.salud_serie` cuenta como `dup` cayeron de **13.293 el 24-sep a ~600**
  por día. Antes del fix, cada despliegue metía una pasada extra.

### Incidente 2026-08-17 — el scraper llevaba 2 días sin correr el pipeline

La imagen del scraper se construyó el 2026-08-14 17:48; `pricing/pipeline.py` se
escribió a las 17:50. La imagen quedó **dos minutos antes que el archivo** y
nunca se reconstruyó, así que `run_pricing()` moría con
`ModuleNotFoundError: No module named 'pricing.pipeline'` → `restart:
unless-stopped` → pasada nueva desde cero. **178 reinicios, 11.906 corridas,
1.453.533 observaciones en un solo día** contra las ~19.500 normales: ~75× el
tráfico previsto a las seis tiendas. Resuelto reconstruyendo. Consecuencia viva
en los datos: ver "la baseline quedó sesgada" abajo.

### ✅ La baseline sesgada por el sobremuestreo — RESUELTO el 2026-09-01

`compute_baseline` calcula `p50`/`p10`/`min` sobre los puntos **crudos**
(`baselines.py:154-162`, `percentile(prices, …)`), no sobre los mínimos diarios.
`daily_minimums` alimenta únicamente `n_days` y `detect_ramp`. Por eso el
sobremuestreo del incidente entraba en la señal: la cantidad de observaciones de
un día **es su peso en la mediana**.

El rango sucio resultó ser **14–19 de agosto, no 15–17**: el 14 tenía 13,19
puntos por listing y el 19 tenía 4,97, contra los ~1,90 normales. Esos seis días
aportaban 2.013.243 de las 2.567.689 filas de `price_points` — el **61,3 %** de
la ventana de cada listing en promedio, y más del 80 % en 10.450 listings.

El daño era doble, y la segunda mitad es la peligrosa: además de inflar
`discount_real`, un p50 inflado **apaga la guarda anti-rampa**, porque su umbral
es `p50 × 1.15`. Medido sobre los 70 aceptados del 1-sep: 28 desaparecían al
deduplicar y 22 de esos caían por `ramp`. Es decir, el sesgo estaba dejando pasar
justo el patrón inflar-y-descontar que este proyecto existe para no publicar.

**Reparado** con `scripts/repair_oversampling.py --apply` (backup previo en
`~/backup_ofertas_2026-09-01.dump`, 27 MB, verificado con `pg_restore -l`):

- 2.013.243 puntos borrados conservando la primera observación de cada mitad del
  día. `price_points` quedó en 554.446 filas y agosto entero volvió a 1,85–1,97
  puntos por listing y día.
- Las 5.227 decisiones del 1-sep se borraron también: se habían tomado contra la
  baseline sucia y como dataset de calibración eran inválidas. Sin borrarlas el
  detector no las reevalúa nunca (filtra con `NOT EXISTS` sobre
  `(listing_id, detected_at)`). Los `out_of_stock` viejos se conservaron: esa
  guarda es la primera y no usa baseline.
- El pipeline reejecutado dio **42 aceptados**, exactamente lo que había
  anticipado la simulación previa, con `ramp` de 72→88 y `above_floor` de 10→12.

La partición sigue pesando 285 MB: `VACUUM` marca el espacio reutilizable pero no
se lo devuelve al SO. Es lo esperado y no hay que hacer nada.

**El script queda en el repo como evidencia de qué se borró y con qué criterio.**
No es una migración —no toca esquema— y no debe moverse a `migrations/`.

Alternativa de diseño que se evaluó y se descartó: calcular el percentil sobre
`daily_minimums` en vez de sobre los crudos. Inmuniza solo en parte (el mínimo de
133 muestras diarias sigue siendo ≤ el de 2), cambia el significado de `p10` y
vuelve redundante `MIN_POINTS`. Si alguna vez se hace, la forma correcta es una
**mediana** diaria, no el mínimo, y es una decisión de diseño aparte.

Los tests que tocan DB piden `TEST_DATABASE_URL` apuntando a una base
**descartable** (el setup hace `DROP SCHEMA public CASCADE`). Sin la variable se
saltean y la suite igual queda verde — un "350 passed, 70 skipped" sin ella no
prueba lo que creés:
```bash
cd ~/servicios/ofertoon && set -a && . ./.env && set +a && \
export TEST_DATABASE_URL="postgresql://ofertas:$POSTGRES_PASSWORD@localhost:5436/ofertas_test" && \
.venv/bin/python -m pytest tests/ -q
```
Corré **una suite por vez**: dos pytest en paralelo contra la misma base se
deadlockean en el `TRUNCATE` del fixture y parece un bug del proyecto.

### F3 — cerrado el 2026-08-04, arreglado el 2026-08-06

Las tres piezas que conectan `pricing/` con el canal. Hasta F3 nada en
producción invocaba el detector: estaba escrito y testeado pero el único
entrypoint era `backtest.py`, una herramienta offline.

- **`pricing/pipeline.py`** — baselines + detector, invocado desde
  `scrapers/runner.py:run_pricing()` al cerrar cada pasada. Corriendo: 4
  corridas registradas, la última hoy 09:04.
- **`curation/ranker.py`** — la cuota diaria: 6/día, 2 por tienda, 2 por
  categoría, 45 min de espaciado, ventana 09–22 de Santiago. El ordenamiento es
  una función pura (`select`) sobre dataclasses; solo la query que la alimenta
  tiene I/O.
- **`publisher/`** — `daemon.py` (reloj propio), `poster.py` (reserva → envía →
  confirma) y `formatter.py` (el mensaje). **Levantado y publicando desde el
  2026-09-21**: `PUBLISHER_ENABLED=true`. Es una decisión deliberada de adelantar
  el canal al backtest, no un descuido — pero significa que lo que sale está
  medido contra los θ de partida, **sin calibrar**. Al 2026-09-29: 48 filas en
  `deal_posts`, **6 por día sin faltar uno** (la cuota del ranker), descuentos
  entre 0,226 y 0,620. Los 48 tienen `outcome_label` nulo: ninguno pasó por
  `label_outcome`, así que **no son evidencia de precisión**, son el material que
  el backtest va a etiquetar.
- **Migración 14** — `detected_at` pasa a ser el `observed_at` de la observación
  y `UNIQUE(listing_id, detected_at)` hace el job re-ejecutable.

**El cold-start terminó el 2026-09-01.** El binding era `MIN_DAYS = 30`
(`MIN_POINTS = 30` se cumplía de sobra). La serie arranca el **2026-08-03**, así
que el día 30 cayó el 1-sep y **5.227 listings** cruzaron el umbral en la pasada
de las 07:54. `deal_candidates` pasó de 17 filas (todas `out_of_stock`) a 5.255.
Los rechazos por `history` siguen sin dejar fila (ver más abajo).

### Cuándo empiezan a salir ofertas

> **Corrección 2026-09-21.** Este handoff decía que el backtest podía calibrar θ
> "con ≥45 días, ~17 de septiembre". **Está mal, y la fecha real es el 2-oct.**
> La cuenta de 45 días era 30 de baseline + 15, pero la ventana de etiquetado es
> de 30 días, no 15 (`backtest.py:46`, `LABEL_WINDOW_DAYS = 30`). La cadena
> completa es: la serie arranca el 3-ago → la baseline recién cumple
> `MIN_DAYS = 30` el **2-sep**, que es el primer día en que el replay puede
> emitir una señal → esa señal no se puede etiquetar hasta el **2-oct**. Antes
> de eso `label_outcome` devuelve `unknown` para todo (`series_end < horizon`) y
> la precisión sale `None`, que es lo correcto: no es 0 %, es "no se sabe".

Verificado el 21-sep corriendo el backtest de verdad, no deducido:

```
categoría              θ  señales  /día  reales  falsas  s/madurar  precisión
tecno-notebooks     0.10       60   1.2       0       0         60          —
tecno-notebooks     0.15       31   0.6       0       0         31          —
tecno-notebooks     0.25        9   0.2       0       0          9          —
```

| Hito | Fecha | Estado |
|---|---|---|
| Historia suficiente | **2026-09-01** | ✅ hecho. 8.750 baselines publicables al 21-sep |
| Primera señal etiquetable | **2026-10-02** | pendiente. Es el piso duro, y con una sola cohorte de señales |
| Backtest con volumen para fijar θ | **~mediados de octubre** | pendiente. Un θ por categoría necesita más de un día de señales maduras |
| `PUBLISHER_ENABLED=true` | **2026-09-21** | ✅ hecho, **adelantado a propósito**. El canal recibe 6/día medidas contra θ sin calibrar: es prueba en vivo del formato y del gate, no señal validada. Lo que sigue pendiente es re-evaluar esas ofertas cuando el backtest fije θ |

Con la baseline ya reparada, los candidatos que se acumulen desde el 1-sep 18:13
son dataset limpio para el backtest. Que el publisher ya esté sacando 6 por día
**no los valida**: son los mismos candidatos, y el backtest los va a etiquetar
igual. Lo que cambió el 21-sep es que además salen al canal.

### El canario — tres arreglos, 2026-09-01

El disparador: SP Digital venía marcando 5 de sus 13 categorías como `partial` en
cada pasada. **El adaptador estaba sano.** Sondeando la API en vivo, el
`totalCount` con `stockAvailability: IN_STOCK` coincide exactamente con lo que
raspamos (18=18, 8=8, 1=1, 3=3, 74=74, 23=23), mientras el catálogo sin filtrar
tiene 886, 278, 277, 97, 2019 y 150. La tienda perdió stock, no nosotros
cobertura: entre la pasada del **28-ago 18:00 UTC (359 ítems)** y la del **29-ago
06:00 (235)** cayeron las 13 categorías a la vez.

Eso destapó tres defectos del canario, todos corregidos:

1. **Se enclavaba y no se recuperaba nunca.** `db.recent_items_seen` leía solo
   `status='ok'`, así que apenas un target caía en `partial` sus corridas dejaban
   de alimentar la historia y la mediana quedaba congelada en el nivel viejo para
   siempre. El log seguía diciendo `18 items vs mediana 47` con las siete
   corridas previas en 18. Ahora lista `ok` y `partial` (queda afuera `failed`,
   que no vio nada, y `running`, que no terminó). La autoanestesia que el filtro
   quería evitar la cubre la mediana: con `window=7` hacen falta 4 corridas
   degradadas seguidas —2 días— para mover la vara.
2. **El piso absoluto generaba falsos positivos permanentes.**
   `CANARY_MIN_ITEMS = 5` marcaba para siempre a categorías que de verdad tienen
   3 productos (`Tarjetas Gráficas AMD` de PC Factory lleva 12 corridas en 3).
   Ahora el piso solo rige cuando **no hay historia**; con historia manda la vara
   relativa, y `seen == 0` sigue siendo `partial` siempre.
3. **Chequeo de completitud exacto** (`scrapers.base.CountingAdapter`). Cuando la
   tienda declara cuántos productos tiene la categoría, ese chequeo *reemplaza*
   al estadístico: si dice 74 y la paginación enumeró 74, la corrida está
   completa por definición. Cuenta **edges enumerados**, no productos emitidos —
   un ítem que el parser descarta por no traer precio es una decisión nuestra,
   no una página perdida; mezclarlos volvería heurística una guarda exacta.

Verificado contra la base de producción: los 11 targets de SP Digital vuelven
`ok` y su historia refleja el nivel real. Lo que el canario **no** vio, y sigue
sin ver: cayeron las 13 categorías pero solo 5 dispararon, porque
`CANARY_DROP_RATIO = 0.40` deja pasar caídas del 25–34 %. Como alarma de "SP
Digital perdió un tercio de su stock" el canario estadístico es flojo por diseño;
la respuesta correcta es el punto 3, no bajar el ratio.

Los `failed` del histórico no son un problema vivo: 145 de 148 son `FetchError`
del **19-ago ~20:20 UTC** repartidos entre las 6 tiendas a la vez — un evento de
red/host, no de adaptador.

### La cadencia de muestreo — medida y cerrada el 2026-09-24

Quedaba abierto del 23-sep: "hay pasadas de más por despliegue y no está medido
cuánto mueven el p50". Se midió, y **el diagnóstico estaba equivocado en las dos
mitades**.

**Mitad 1: el sobremuestreo por despliegue es inocuo. No hay que deduplicar.**

Comparando listing por listing la baseline sobre la serie cruda contra la
deduplicada con el criterio de `repair_oversampling.py` (primera observación de
cada mitad del día), con `compute_baseline` y `evaluate` reales sobre los 21.378
listings y 1.003.864 observaciones de la ventana:

| Medida | Resultado |
|---|---|
| p50 idéntico | **8.812 de 9.073** (97,1 %) con historia mínima |
| Δp50 medio | **−0,003 %** (mediana 0,000 %; p01 −0,26 %, p99 0,00 %) |
| \|Δ\| > 1 % | 101 listings (1,11 %) |
| Historia mínima perdida al deduplicar | **0** por `n_points`, **0** por `n_days` |
| Decisiones del detector que cambian | **4 de 13.490** (aceptados 91→92) |

Nada que ver con el desastre de agosto (61 % de las filas de la ventana). La
razón es aritmética: las pasadas extra son 2 días sobre ~53 con datos, y el
punto extra casi siempre trae el mismo precio que el del día. **Deduplicar
movería 4 decisiones y tocaría 1M de filas antes de la calibración: no se
hace.** SP Digital es la única tienda medianamente sensible (132 de 347
listings cambian algo, media −0,076 %) y aun así por debajo del ruido.

**Mitad 2: lo que el handoff anterior leyó como "3 pasadas ese día" era una
caída de 48 h.** Los días **18 y 19 de septiembre no tienen una sola fila en
`price_points`**. Lo que se contó como pasadas extra eran reintentos de un
crash-loop:

- 18-sep: 336 corridas, **336 `failed`**. 19-sep: 226 corridas, **226 `failed`**.
- Las **seis tiendas al 100 % de fallo** (`agotados 3 reintentos` contra todos
  los hosts) → caída de la red saliente del host, no un adaptador roto.
- 20 y 21 de septiembre quedaron además con **una sola pasada** (1,03
  obs/listing).

Es el mismo evento que este handoff ya describía para el **19-ago ~20:20 UTC**
(145 de 148 `failed` repartidos entre las 6 tiendas a la vez). **Pasa más de una
vez; hay que tratarlo como recurrente, no como anécdota.**

**Por qué nadie se enteró, que es la parte que había que arreglar.**
`ALERT_BOT_TOKEN`/`ALERT_CHAT_ID` están configurados y `alerts.py` funciona. Pero
la alerta viaja por `api.telegram.org`, o sea **por la misma red saliente que se
cayó**: el canal de aviso comparte el modo de falla que debe reportar. Se
descubrió cinco días después, mirando `price_points` a mano.

Lo que se hizo (2026-09-24):

1. **`db.dias_sin_observaciones()`** detecta días completos sin una sola fila,
   leyendo el Postgres **local** — lo único que sobrevive a esa caída. El runner
   lo consulta después de cada pasada y `format_summary` lo reporta **aunque la
   pasada haya salido verde**, así el aviso sale en la primera pasada que vuelve
   a alcanzar Telegram. Sin estado ni tabla nueva: la ventana de 3 días
   (`GAP_LOOKBACK_DAYS`) hace que se calle solo.
2. **`scripts/salud_serie.py`** es esa misma consulta a mano, para mirar la
   cadencia de un vistazo: `obs/listing` por día (2,0 es sano), agujeros y
   mitades de día duplicadas. `DATABASE_URL=<dsn> python -m scripts.salud_serie`.
3. **`runner.espera_hasta_proxima()`** ancla la cadencia al arranque de la
   última pasada registrada, en vez de contar el intervalo desde el arranque del
   proceso. Antes, la primera vuelta del loop entraba directo a `run_once`: cada
   `up -d --build` y **cada reinicio del daemon de Docker** disparaba una pasada
   completa contra las nueve tiendas. `--once` y `--dry-run` la saltean (son una
   orden directa del operador). De paso corrige la deriva: el intervalo se
   contaba desde el FIN de la pasada, así que el ciclo real era de 12,2 h y el
   horario daba la vuelta al reloj en un mes.

   El ancla es `db.ultima_pasada` y es el **`MIN(started_at)` de la última
   pasada**, no el `MAX`: `scrape_runs` tiene una fila por (tienda, llave) y
   arrancan escalonadas a lo largo de los 11-14 min que la pasada tarda en
   recorrer las nueve tiendas (medido en producción el 2026-09-24). Con `MAX` el
   ancla era el arranque de la ÚLTIMA tienda y el ciclo seguía siendo de 12,2 h:
   el mismo número que este cambio dice corregir. Lo cubren tres tests con DB en
   `tests/test_runner_cadencia.py`.

**Lo que esto NO arregla, y hay que tener presente al calibrar θ el 2026-10-02:**
el agujero del 18-19 ya está en los datos y no se rellena. Concretamente:

- La ventana de 60 d tiene **51 días con observaciones**, no 53.
- **~75 listings** quedaron bajo `MIN_DAYS` por el agujero (verificado: de 298
  con edad suficiente y `n_days` 28-29, solo 75 estaban vivos a ambos lados del
  hueco; los otros 223 son intermitencia propia, no el gap).
- Más importante: **el backtest va a hacer replay sobre dos días sin ningún
  candidato.** La métrica de salida es "precisión ≥80 % con ≥3 ofertas/día/canal"
  — esos dos días no tienen que contarse como "días sin ofertas".

### Fase 1b del plan de tiendas — cerrada el 2026-09-24 con una tienda de dos

**Kupfer conectada** (`scrapers/stores/magento_html.py`, migración 18, 3 fixtures,
25 tests). **Construmart no es construible como estaba planeado** y pasó a la
Fase 1c. Lo que encontró la inspección del día:

| Hallazgo | Consecuencia |
|---|---|
| El `robots.txt` de Kupfer prohíbe `/*?p=` | La familia **no pagina**: una request por categoría con `product_list_limit=36`. Solo se pueden conectar categorías de ≤36 productos |
| `product_list_limit=96` → **HTTP 200 con 12 productos** (el default) | Subir `PAGE_SIZE` a ojo reduce el alcance a un cuarto **en silencio**. Solo valen los valores del `<select id="limiter">` |
| `span.toolbar-number` declara el total exacto ("118 productos") | La familia implementa `CountingAdapter`: el canario es exacto ("36 de 118" → `partial`) en vez de estadístico. Sin eso, una categoría que crece pasando de 36 se vería sana para siempre |
| Construmart no publica precios a un anónimo | Sus precios y stock son **por sucursal** (cada una es un `customer_group_id`). En 800 KB de HTML no hay un solo `$` y las 20 filas del grid salen "Sin Stock". El propio sitio lo dice: "Para ver los precios y stock, selecciona la región y tienda" |
| Su `/rest/default/V1/products-render-info` **sí** contesta sin token | Pero devuelve `final_price: 0` e `is_salable: ""` en los 20 productos. Es la ruta anónima de su propio front, y para el anónimo no hay precio |
| El catálogo de Kupfer que mapea a la taxonomía es chico | Es ferretería industrial: `herramientas-electricas` declara 24 y 7 de sus 10 hojas tienen cero (los productos están asignados al padre, que es anchor) |

**Kupfer entra asumiendo que 24 listings no mueven el volumen del canal.** Cuesta
una request por pasada y es el primer caso de la familia, que Sparta y Andesgear
reusan en la Fase 2. Se evalúa el **2026-10-24**; si no deja un candidato aceptado
propio, `UPDATE stores SET is_active = false WHERE slug = 'kupfer'`.

Primera pasada real, verificada en producción: `kupfer/ferre-herramientas → 24
vistos, 24 observaciones nuevas [ok]`, `completeness=(24, 24)`, precios de $2.674
a $2.911.631, marca en 7 de 24, **sin GTIN** (el grid de Magento no lo expone).

**Lo que Construmart necesita, para cuando se retome:** reversear el endpoint que
fija la sucursal (el botón "ENTRAR A CONSTRUMART.CL" del componente `storePopup`;
del lado visible solo queda `localStorage.selected_store_name` y un
`customer_group_id` por tienda), sostener una sesión con UNA sucursal de
referencia de Santiago, y aceptar explícitamente que la serie de un SKU es la de
**esa** sucursal. Eso último es una decisión de modelo: hoy el sistema asume un
precio por SKU por tienda.

### Fase 1c del plan de tiendas — cerrada el 2026-09-26

Era "investigación sin compromiso de entrega" y terminó con **una tienda
conectada y tres preguntas respondidas**. El detalle largo está en
PLAN_TIENDAS §1c; acá lo que hay que saber para operar:

**Construmart entró** (`ConstrumartAdapter` en la familia `magento_html`,
migración 19, 19 llaves, **219 listings**, primera pasada `ok` en las 19). No hizo
falta reversear ninguna sesión: su front escribe la cookie
`persistent_customer_group_id` y con esa cookie sola el listado devuelve precios.

Lo que hay que tener presente sobre esta tienda, en orden de importancia:

1. **Su serie es la de la sucursal 35 (DEPARTAMENTAL, Av. Departamental 541).**
   Cada sucursal es un `customer_group_id` y hay 32. La señal es correcta porque
   baseline y precio de hoy salen del mismo grupo, pero **la oferta vale ahí**, y
   eso hay que decirlo en el copy si esta tienda llega a publicar. Cambiar
   `ConstrumartAdapter.CUSTOMER_GROUP_ID` invalida el histórico entero.
2. **`items_seen` mucho menor que las filas del grid es lo normal.** Las filas
   "Sin Stock" de esa sucursal vienen sin precio ni SKU: se enumeran (y cuentan
   para el total que el canario compara) pero no se emiten. De 302 filas
   conectadas, 219 traían precio.
3. **Pagina con `?p=`** porque su robots lo permite —al revés que Kupfer— y corta
   en el `#am-page-count` que la tienda declara, así que nunca pide una página
   pasada del final.
4. **Trae marca en el 100% pero no aporta identidad**, porque la regla 6 pide GTIN
   o (marca, modelo) y el grid no da modelo. Si algún día se quiere aprovechar,
   está ahí; sacar el modelo del nombre sería fuzzy y eso está deliberadamente
   afuera.

**Las tres que no entraron:**

| Tienda | Veredicto |
|---|---|
| **Imperial** | Descartada. Ya no da 520: da **403 de Akamai** y con UA de navegador resetea el stream HTTP/2. Es un WAF, no una caída. Mismo balde que MTS |
| **Chilemat** | Descartada, **no es un e-commerce**: SPA de React + Firebase cuyo bundle declara noticias, localizador de ferreterías y concursos, y cero rutas de producto, carrito o precio. No re-inspeccionarla |
| **Kruuse** | **Vale la pena y no está conectada.** Corre Medusa y publica `/cl/product-feed.json` —que su `llms.txt` ofrece para indexar y su robots permite a ClaudeBot—: 3.753 productos, **GTIN en el 99%**, 38 requests por pasada. El freno: **3.467 de 3.753 son `backorder`** (221 `in_stock`), así que publicaría casi nada; su valor es la identidad cross-store |

**Si se retoma Kruuse**, lo que ya está medido: `limit` clamea honesto en 100 (y
lo reporta, al revés de Magento), `category` viene en el 65%, `sale_price` en 0 de
3.753, 2 productos superan `MAX_PLAUSIBLE_CLP` y son máquinas industriales reales
(no centinelas), y `backorder`/`preorder` tienen que mapear a `in_stock=False`.

### Kruuse conectada, y el agujero de identidad que encontró — 2026-09-26

**Kruuse entró por su propio feed** (`scrapers/stores/kruuse.py`, migración 20, 24
llaves, **628 listings**, 21 corridas `ok` + 3 `partial` previstas). Lo que hay que
saber para operar:

1. **Su feed es plano y la pasada lo baja UNA vez** (38 requests con `limit=100`);
   las 24 llaves se sirven de esa copia y el `store_key` es el nombre de la
   categoría tal como lo escribe la tienda. El fallo también se cachea: sin eso,
   una tienda caída se llevaría 24 bajadas completas en la misma pasada.
2. **96 de sus 628 listings están disponibles.** El resto es `backorder`: vende a
   pedido. `in_stock` es `True` solo para `in_stock`, así que el detector va a
   rechazar casi todo lo suyo — correctamente. Al evaluarla el 2026-10-26, el
   criterio de "≥1 candidato aceptado propio" puede no cumplirse por esta razón y
   no por inestabilidad de catálogo: ahí la decisión es de producto.

   ⚠️ **Corrección del 2026-09-28.** Este archivo y la migración 20 decían que
   "la serie se construye igual y queda lista para cuando un SKU entre en
   stock". **Es falso.** Los `price_points` sí se acumulan —628 de 628 listings
   tienen observaciones—, pero `compute_baseline`
   (`pricing/baselines.py:149`) filtra `if in_stock` al computar, sobre los
   puntos crudos, así que los 532 en backorder **no tienen baseline ni
   `n_days`** y esos puntos van a seguir filtrándose para siempre. El reloj de
   `MIN_POINTS=30` / `MIN_DAYS=30` arranca el día que aparece stock, no el día
   que empezamos a observar. Medido: `628 listings | 628 con observaciones | 96
   con baseline`. El filtro está bien; la expectativa escrita estaba mal.
   La migración 20 ya está aplicada y **no se edita** (checksum): su comentario
   queda viejo a propósito y la corrección vive acá y en PLAN_TIENDAS §1c.
   Andesgear no tiene este problema (2.768 de 2.768 con baseline).
3. **Las 3 llaves de 4 productos salen `partial` sus primeras 3 corridas** por el
   piso absoluto del canario. Está previsto en la migración; a la cuarta pasada la
   mediana toma el control.

**El hallazgo que importa más que la tienda: `catalog/identity.assign_products()`
no tiene llamador.** Buscado en todo el repo, solo lo importan su propio test y la
documentación. Consecuencia medida hoy:

| | |
|---|---|
| `products` | **0 filas** |
| `listings.product_id` no nulo | **0 de 22.665** |
| `listings.gtin_raw` | **3.216** (ferretek 1.504, kruuse 614, paris 623, spdigital 458, urban 17) |
| `gtin_raw` compartidos por 2+ tiendas | **11** |

Dos lecturas, las dos importantes:

- **No hay pérdida de datos.** La migración 07 existe justo para esto: el GTIN
  crudo se guarda en `listings` en cada pasada, así que el paso de agrupamiento se
  puede correr cuando se quiera y reconstruye `products` hacia atrás. Lo que este
  handoff y CLAUDE.md afirmaban —"~875 de ~11.000 listings tienen identidad"— era
  **falso** y quedó corregido.
- **La expectativa hay que bajarla.** Aun con el paso corriendo, hoy solo 11 GTIN
  están en dos tiendas o más, porque las cuatro tiendas con GTIN casi no se
  solapan en catálogo (Ferretek = repuestos de maquinaria, Kruuse = máquinas
  Scheppach, Paris = electrónica, SP Digital = componentes PC). El copy "más
  barato que en Paris" no se destraba conectando más ferreterías: se destraba
  cuando dos tiendas que venden lo mismo traigan las dos el código.

**Wireado el 2026-09-28.** `pricing/pipeline.py` llama a `assign_products()`
después de baselines y detector, dentro de su propio `try`: la identidad no
alimenta al detector, así que un fallo suyo no puede costar la corrida de la
señal que ya quedó persistida. `PipelineStats.identity` es `None` cuando falla —
`None` y no un stats en cero, porque "falló" no es "no había nada que vincular".
`tests/test_pipeline.py` cubre las dos cosas; es un test de cableado, que es
justo lo que faltaba: la función era correcta, nadie la invocaba.

Simulado en seco contra la DB de producción antes de wirearlo (3.401 listings
elegibles, cabe en un `batch_size` de 5.000):

| | |
|---|---|
| escaneados / vinculados | **3.401 / 3.401** (0 sin identidad) |
| `products` a crear | **3.357** (3.216 por GTIN, 185 por marca+modelo) |
| products con **2+ tiendas** | **11** — 8 paris+spdigital, 3 ferretek+urban |

Dos cosas que salieron de esa simulación y no estaban escritas:

1. **Falta el consumidor, no solo el productor.** `cross_store_prices()` no lo
   llama nadie y `publisher/formatter.py` solo emite "El más barato en 60 días",
   que sale de la historia propia del listing. Poblar `products` es condición
   **necesaria y no suficiente**: el copy "más barato que en Paris" sigue sin
   existir en el código. Escribirlo es una decisión de producto con retorno hoy
   casi nulo (11 products cruzados). Ojo que el publisher **no** está inerte: lo que
   sale al canal usa el copy que ya existe, "El más barato en 60 días".
2. **Una tienda repite el mismo GTIN en dos listings propios** — Paris publica el
   GS51MPP con `store_sku` numérico (`218673999`) y otra vez alfanumérico
   (`EAGASW7UCP-1`). Medidos: 13 GTIN así en Paris, 13 en Ferretek, 1 en SP
   Digital. Comparten `product_id`, que es correcto, pero `cross_store_prices()`
   solo filtraba `o.id <> l.id`: habría devuelto el gemelo y el copy habría dicho
   "más barato que en Paris" sobre una oferta **de Paris**. Corregido a
   `o.store_id <> l.store_id`, con test. Era un bug latente que wirear la
   identidad **activaba**.

⚠️ **Lo wireado todavía no corrió contra producción.** `products` sigue en 0
filas: el cambio está en el working tree, el contenedor del scraper **no** se
reconstruyó y la próxima pasada corre con la imagen vieja. Para activarlo hace
falta `docker compose up -d --build scraper`, que es una decisión de despliegue.

### Fase 2 — inspeccionada el 2026-09-26, no arrancó y hay que saber por qué

Las dos tiendas que la hacían "la mejor relación valor/esfuerzo del plan" no
existen como premisa:

- **Doite**: su `robots.txt` prohíbe **212 handles de `/collections/`** —el
  endpoint exacto de la familia Shopify— cubriendo el árbol de categorías
  completo, y abre con un banner propio sobre scraping automatizado. Su
  `/products.json` global responde 200 y no está prohibido, así que técnicamente
  se podría; **no se hace**, por la misma razón por la que se respeta el
  `Crawl-delay: 5` de SP Digital y el `?p=` de Kupfer. Si alguna vez se revierte,
  que sea una decisión explícita.
- **Lippi**: no hay tienda. `lippi.cl` no resuelve, `lippioutdoor.cl` resuelve y
  no responde, `lippi.com` es un WordPress de marca sin `/products.json` ni
  precios en CLP.

Quedan **Sparta** (Magento, `Crawl-delay: 1`, y `Disallow: /*?` → ninguna URL con
query string, así que va sin paginar) y **Andesgear** (Magento, `Crawl-delay: 3` →
`rate_limit_rps = 0.33`, y sí puede paginar). Las dos reusan `magento_html` sin
escribir adaptador.

**Pero la fase sigue bloqueada por lo que PLAN_TIENDAS §1.3 dejó abierto a
propósito**, y son decisiones de producto, no de código:

1. **Categorías nuevas** (`deporte-*`) con θ de partida sin calibrar, y a qué
   canal se mapean. Hoy el único canal vivo es `vip` (`-1003914468578`,
   `gate_enabled=true`) y tiene las 7 categorías actuales. Una categoría sin fila
   en `telegram_tier_categories` se ingesta y se evalúa pero **no puede
   publicarse**, así que conectar primero y decidir el canal después es gratis.
2. **La liquidación de fin de temporada**: es un descuento real que se ve igual
   que el escalón permanente que `backtest.py` etiqueta `fake`. §1.3 dice que se
   decide antes, no durante.

### Fase 2 arrancada: deportes con vestuario incluido — 2026-09-26

**Decisión del dueño del producto: la ropa va.** Eso pone en juego lo que
PLAN_TIENDAS §1.3 dejaba como prerrequisito, así que antes de conectar se fue a
mirar el código. **El efecto no está donde la advertencia decía:**

| Capa | Qué le hace una liquidación de temporada |
|---|---|
| Ingesta | Nada. Guarda precios. |
| **Detector** | **No la rechaza.** `detect_ramp` exige un alza sostenida (≥15% sobre el p50 por ≥5 días entre d−21 y d−3) ANTES de la baja; una liquidación baja sin haber subido → `ramp_flag=False` → se acepta como candidata. |
| **Backtest** | **Acá pega.** `label_outcome` marca `fake` todo pozo que se queda abajo, y una liquidación se queda abajo. La precisión medida de las 3 categorías nuevas va a verse mal y la calibración empujaría sus θ hacia arriba hasta excluirlas. |

O sea que §1.3 es una decisión **de calibración, con datos**, no un bloqueo para
conectar: aceptar que las liquidaciones se filtren, o darle al backtest una
etiqueta para "se quedó abajo pero fue una ganga real". Mientras no se decida,
nada se publica igual y la serie se acumula.

**Lo que entró** (migración 21): 3 categorías nuevas —`deporte-vestuario` θ 0.350,
`deporte-calzado` 0.300, `deporte-equipamiento` 0.250, **las tres mapeadas al canal
`vip`**— y **Andesgear** con 25 llaves y 3.042 productos declarados. Los θ son de
partida y más altos que los de ferretería a propósito: en vestuario un 25% es
precio de lista de cualquier martes.

Tres cosas de Andesgear que hay que saber:

1. **Cuesta ~7 min de pasada** (~140 páginas de 24 a `rate_limit_rps = 0.33`, que
   es su `Crawl-delay: 3`). La pasada completa pasó de ~13 a ~20 min.
2. **Cross-lista el mismo SKU en varias categorías** y por eso su adaptador
   deduplica por pasada (`dedupe_across_categories`). Es inocuo **solo porque los
   13 pares solapados medidos caen dentro de la misma categoría interna**; una
   llave que cruce dos categorías internas rompe el supuesto. Por eso
   `db.load_store_targets` ahora ordena también por `store_key`: sin eso, cuál
   llave gana un SKU duplicado lo decidía Postgres y podía cambiar entre pasadas.
3. **Las categorías de 20+ páginas van a marcar `partial` de vez en cuando.**
   `hombre/top` enumeró 520 contra 521 declarados en la primera pasada: el
   catálogo se movió un item mientras paginábamos un minuto. El `partial` dice la
   verdad —esa corrida no vio todo— y no hay tolerancia que agregarle a una guarda
   que vale por ser exacta.

**Sparta no entró y es una decisión pendiente, no un olvido.** Su `robots.txt`
prohíbe toda URL con query string (`Disallow: /*?`), o sea que **no se puede
paginar**: `zapatillas.html` declara 1.080 productos y una request trae 36. Las
únicas tajadas disjuntas que ofrece son sus facetas de marca
(`/zapatillas/filtro/adidas.html`, sin query string), que serían ~200 llaves para
cubrir el árbol.

Igual dejó dos regalos: **encontró dos bugs de la familia `magento_html`** que
estaban activos para Kupfer y Construmart, con fixture propio en los tests:

- `declared_total` tomaba el PRIMER `span.toolbar-number`. Sparta escribe
  "Artículos 1-36 de 1080" en tres, así que declaraba 1 para una categoría de
  1.080 — y eso no fallaba ruidosamente: el canario solo marca `partial` cuando lo
  enumerado es MENOR que lo declarado, así que 36 contra 1 pasaba `ok` y la guarda
  exacta quedaba anulada en silencio.
- `_in_stock` leía cualquier `span.price-label` como señal de stock. Sparta pone
  ahí "Precio habitual" (el rótulo del precio tachado), lo que marcaba agotados
  justo a los 14 de 36 productos CON descuento.

### El canario de Prat que se calló solo — diagnosticado el 2026-09-28

`prat` / `herramientas-electricas` cayó de **345 a 131 items el 2026-09-25**,
estuvo `partial` cuatro corridas y volvió a `ok` el 27-sep **sin que nadie
arreglara nada**. Diagnóstico completo:

**No fue el adaptador.** Comprobado en vivo contra el endpoint:
`?limit=250&page=1` devuelve 131 productos y `page=2` devuelve 0 — fin legítimo,
no tope de paginación, y `limit=250` ni siquiera ata con 131.

**Fue la tienda.** Su propio `collections.json` lo publica:

```
herramientas-electricas   products_count=150   updated_at=2026-09-25T16:28:37-03:00
maquinarias               products_count= 32   updated_at=2026-09-25T16:21:05-03:00
```

El `updated_at` cae exactamente en la corrida que se cayó: el comerciante re-curó
la colección a mano y de paso repobló `maquinarias`.

**Y es peor que "rotación de catálogo".** Bajé las 39 páginas de su
`/products.json` (9.466 variantes) y crucé los SKUs:

| | |
|---|---:|
| listings que la colección dejó de mostrar | **246** |
| …que **siguen a la venta** en la tienda | **240 (98%)** |
| …borrados de verdad del catálogo | **6** |

O sea que 240 series murieron por una decisión editorial, no porque los productos
dejaran de existir.

**Lo que separa una vitrina de un catálogo es la tasa de stock:**

```
jardin (llave)                49 variantes    49 con stock (100%)
herramientas-electricas      131 variantes    71 con stock ( 54%)
herramientas-y-maquinarias 1.089 variantes 1.088 con stock (100%)
catálogo completo          9.466 variantes 6.698 con stock ( 71%)
```

`jardin` y el paraguas están **filtrados por disponibilidad**; la vitrina no. Eso
explica de una la anomalía de Prat que estaba anotada y sin medir: de sus 430
listings, los **204 sin baseline son EXACTAMENTE los que nunca se observaron con
stock**, y los 204 caen en `ferre-herramientas`. `ferre-jardin` tiene 49 de 49.

```
ferre-herramientas | sin baseline | nunca tuvo stock | 204
ferre-herramientas | con baseline | tuvo stock       | 177
ferre-jardin       | con baseline | tuvo stock       |  49
```

**Arreglo: migración 22**, `herramientas-electricas` → `herramientas-y-maquinarias`
(la vieja queda `is_active=false`, no se borra: 11 corridas la referencian por
texto). Medido antes de aplicarla: pasa a observar 1.089 listings en vez de 131,
recupera 101 de los 240 SKUs vivos, es disjunta de `jardin` (0 SKUs compartidos),
y de los 131 actuales deja de observar 60 que son **exactamente los 60 agotados**
— no se pierde ni una serie viva. Las series no se reinician: `listings` es único
por `(store_id, store_sku)` y la llave no entra en esa identidad.

⚠️ **La evaluación de Prat se corre al 2026-10-28**, no al 10-23: el reloj de
`MIN_DAYS` arranca de cero para los ~1.000 SKUs que entran hoy.

⚠️ **La llave nueva todavía no corrió cuando se escribió esto.** La migración se
aplicó a las 15:34 UTC del 28-sep y la pasada de las 15:16 ya estaba en marcha, así
que usó la vieja (`items_seen = 131`): `db.load_store_targets` se consulta una vez
al arrancar la pasada, no por tienda. Su primera corrida real es la siguiente
pasada — y la del 29-sep 03:16 murió antes de llegar a Prat (ver el incidente de
esa pasada más abajo).

✅ **Verificado en la pasada del 2026-09-29 15:16 UTC**, la primera que la alcanzó:

```
prat | herramientas-y-maquinarias | ok | items_seen=1089 | items_ok=1089
prat | jardin                     | ok | items_seen=  49 | items_ok=  49
```

1.089 clavado contra lo que la migración predijo, y `ok` en el canario. La llave
vieja no volvió a aparecer.

**Dos supuestos que este caso rompió, y valen para cualquier tienda:**

1. **Las colecciones no son necesariamente jerárquicas.** La migración 15 asumió
   paraguas ⊇ hojas. En Prat, `herramientas-electricas` tenía solo **71 de sus
   131** SKUs dentro de `herramientas-y-maquinarias`. Hay que verificarlo sobre
   SKUs, no deducirlo del nombre.
2. **El canario se calla solo ante un cambio de nivel, en ~4 corridas.** Con
   `CANARY_WINDOW=7`, cuatro corridas al nivel nuevo vuelven la mediana el nivel
   nuevo. Es deliberado (así sigue a un catálogo que cambia de verdad), pero
   significa que el `partial` dura ~2 días y después **no queda ninguna alarma**.
   Un `ok` posterior NO dice que se haya resuelto. Si una tienda cae de nivel, el
   diagnóstico se hace en esa ventana o no se hace.

⚠️ Dos cosas que NO hay que hacer con esta tienda:
`accesorios-herramientas-electricas` está contenida al 100% en el paraguas y
duplicaría observaciones; y el `products_count` de `collections.json` **no sirve**
como total declarado para un `CountingAdapter`, porque cuenta productos no
publicados en el canal online (150 vs 131 servidos, 1.123 vs 1.089 en el
paraguas) y dejaría el canario en `partial` para siempre.

### La pasada del 2026-09-29 03:16 UTC perdió 62 de 129 objetivos

El día quedó con **1.481 `price_points`** contra los ~33.000 de un día normal
(**4%**) y **una sola de las 13 tiendas** con datos. Ninguna alerta salió.

**Qué pasó, en orden:**

1. Fallos de DNS **intermitentes desde el primer objetivo** — `andesgear/hombre/calzado`
   a las 03:16:08 ya salió `failed` con `FetchError: Temporary failure in name
   resolution`, y de ahí en más `ok` y `failed` intercalados. No fue una caída
   limpia: fue el enlace perdiendo paquetes a ráfagas.
2. El host **rebooteó a las 03:58 UTC** (00:58 local) — un apagado ordenado
   (`systemd-poweroff`, boot 25 s después), no un corte. Eso cortó la pasada en
   medio de Ferretek. Las 8 tiendas que venían después en el orden alfabético
   —kruuse, kupfer, paris, pcfactory, prat, sodimac, spdigital, urban— **nunca
   corrieron**, así que no dejaron ni una fila en `scrape_runs`.
3. El proceso murió dentro de `run_once`, o sea **antes** de `run_pricing` y de
   `send_alert` (`runner.py:445-462`). Por eso `deal_candidates` y
   `listing_baselines` no tienen una sola fila del 29-sep, y por eso el arreglo
   del 19-ago —leer el agujero del Postgres local, que sobrevive a la caída de
   red— **no sirvió acá**: nunca llegó a ejecutarse.
4. Docker lo reinició (`restart: unless-stopped`), el proceso nuevo falló otra vez
   en `db.create_pool` porque el DNS tampoco resolvía `postgres`, y el tercer
   intento a las 03:58:53 arrancó bien. `espera_hasta_proxima` ancló al
   `MIN(started_at)` de la pasada muerta (03:16) y durmió 11,3 h, que es el
   comportamiento correcto: el reinicio no metió una pasada extra.

**La causa raíz no está en el repo.** `dockerd` loguea los timeouts contra el
resolver de la LAN:

```
[resolver] failed to query external DNS server dns-server="udp:192.168.1.254:53"
    error="read udp ...->192.168.1.254:53: i/o timeout" question="api.telegram.org"
```

El host sale por un **adaptador WiFi USB** (`wlp0s20f0u8`): señal buena (−49 dBm)
y **3.774 beacons perdidos**. En las 2 h previas a mediodía del 29-sep hubo 350
fallos de DNS para `api.telegram.org`, 98 para `data.tradingview.com`, 856 para
`api.bitget.com` (eso es signalsTrading) y 23 para `argotunnel.com` —cloudflared
reconectando—. Medido en ese momento, el router y 1.1.1.1 y 8.8.8.8 resolvían
**10/10**: los fallos son a ráfagas, así que **cambiar de resolver no arregla
nada**. Es distinto de la degradación del resolver de Docker en contenedores de
larga vida que está anotada más abajo: ahí el contenedor viejo era el problema,
acá el contenedor tenía 13 h y el que no contesta es el router.

**Y ninguna de las tres guardas lo vio. Cada una mira algo que no era esto:**

| guarda | por qué no disparó |
|---|---|
| `db.dias_sin_observaciones` | solo detecta días **completamente** vacíos. Un día al 4% de su volumen pasa como sano |
| `GAP_LOOKBACK_DAYS = 3` (`db.py:255`) | la ventana es de 3 días, así que el agujero del 18-19 de septiembre **ya es invisible** para la alerta |
| el canario de `runner.py` | compara `items_seen` contra la mediana de las últimas 7 corridas **de esa llave**. Los 62 objetivos que nunca corrieron no dejan fila, y sin fila no hay nada que comparar |

Lo que falta es una guarda **por volumen de pasada**: comparar el total de
observaciones de la pasada contra la mediana de las últimas N, y subir
`GAP_LOOKBACK_DAYS`. Sin eso, el modo de falla "la pasada corrió a medias" no
tiene alarma — y ya pasó tres veces (19-ago, 18-20-sep, 29-sep).

**La pasada siguiente lo demostró.** La de las 15:16 UTC corrió entera —129 de 129,
127 `ok` y 2 `partial` de paginación de Andesgear— y su alerta salió bien, con el
texto "2 degradadas de 129". De la pasada de las 03:16, que había perdido 62
objetivos ocho horas antes, **no dijo una palabra**: `gap_days` mira 09-26, 09-27 y
09-28, los tres con datos, así que volvió vacío. El incidente se cerró sin que
ninguna alerta lo nombrara nunca.

**Estado del día tras la recuperación** (las dos pasadas juntas):

```
2026-09-27   32.050 puntos | 17.213 listings
2026-09-28   33.136 puntos | 17.032 listings
2026-09-29   19.361 puntos | 17.585 listings   ← una pasada y media, no dos
```

Menos puntos (se perdió media pasada, y eso no se recupera) pero **más listings que
ningún día anterior**: son los ~1.089 de la llave nueva de Prat entrando. El
pipeline corrió completo a las 15:41-15:42: 26.151 baselines escritas, 9.593 con
historia suficiente, 17.367 evaluados por el detector con 68 aceptados, e
identidad vinculando 15 listings (ya convergió).


## La guarda por volumen de pasada (2026-10-01)

**Escrita, con tests, y verificada contra la DB de producción.** Es la que
faltaba: el modo de falla "la pasada corrió a medias" ya había pasado tres veces
(19-ago, 18-20-sep, 29-sep) y no lo veía **ninguna** de las tres guardas
existentes. Eso estaba demostrado, no supuesto — la alerta del 29-sep a las 15:16
salió bien y dijo "2 degradadas de 129", de la pasada que ocho horas antes había
perdido 62 objetivos no dijo una palabra.

Por qué cada guarda era ciega:

| guarda | por qué no disparó |
|---|---|
| `db.dias_sin_observaciones` | solo ve días **completamente** vacíos; el 29-sep tenía 19.361 puntos y pasó como sano |
| `runner.canary_verdict` | compara cada target contra su propia historia: los 62 objetivos que nunca corrieron no dejaron fila, y los 67 que sí corrieron salieron `ok` porque individualmente estaban bien |
| los `outcomes` de la pasada | el proceso murió **dentro** de `run_once`, o sea antes de `run_pricing` y de `send_alert`: nunca llegaron al mensaje |

Qué se escribió:

- **`db.volumen_por_pasada(conn, limite=N)`** → `[(inicio, items_ok), …]` de la
  más nueva a la más vieja. Reconstruye la pasada agrupando por el hueco: dos
  corridas separadas por más de `PASS_WINDOW` son de pasadas distintas, el mismo
  criterio que `ultima_pasada` y por el mismo motivo (`scrape_runs` tiene una fila
  por (tienda, llave), no una por pasada). Suma **`items_ok`, no `items_seen`**:
  lo que la guarda vigila es cuánta serie entró, y un target que enumera 900 y no
  persiste ninguno no se nota en `items_seen`.
- **`runner.pasadas_flacas(volumenes)`** → `[PasadaFlaca, …]`, pura y testeable
  sin DB. Mediana de las últimas 7, dispara por debajo del 60%.
- **`alerts.format_summary(outcomes, gap_days, flacas)`** — tercera sección del
  mismo mensaje, ordenada de lo más viejo y grave a lo más nuevo: agujero →
  pasada flaca → targets degradados de ahora.
- **`db.GAP_LOOKBACK_DAYS` subió de 3 a 7.** Con 3 días, el agujero del 18-19-sep
  —descubierto cinco días después— ya era invisible: una caída de viernes a la
  que se llega el lunes caía afuera de la ventana y no se reportaba **nunca**. El
  ciclo real de atención es el fin de semana.

**Calibración, medida y no a ojo.** Sobre las 113 pasadas del 4-ago al 29-sep:
la pasada sana más flaca quedó en **0,89** de su mediana móvil y los ocho
incidentes reales entre **0,00 y 0,09**. Entre 0,89 y 0,09 no hay nada, así que
el umbral exacto no es delicado —cualquier valor del medio da los mismos 8
aciertos y 0 falsos positivos— y por eso quedó en 0,40, el mismo
`CANARY_DROP_RATIO` que ya existía, para no agregar un número más que justificar.
Hay un test que fija justamente eso (`test_el_umbral_exacto_no_es_delicado`).

**El falso positivo que importaba descartar**: apagar una tienda con
`stores.is_active = false` baja el volumen de golpe. Medido, la más grande
(Falabella, 25,3% del volumen) deja el ratio en **0,75 — no dispara**. Hace falta
apagar dos tiendas grandes a la vez, y eso merece un aviso. Kruuse, la candidata
real a apagarse el 26-oct, es el 3,7%.

**Verificado contra prod** (no solo en tests): corriendo la guarda sobre las 21
pasadas reales del 22-sep al 1-oct detecta **exactamente una**, la del 29-sep
03:16 (1.481 obs vs mediana 16.509, 91% menos), y ninguna otra.

**Lo que hereda del canario y hay que saber**: el autoapagado. Con la ventana
entera en cero ya no hay vara contra la cual comparar, así que una racha larga
deja de avisar **a la quinta pasada**. Las 48 h del 18-sep son exactamente 4
pasadas caídas, o sea el límite. Ahí la que cubre es la de agujero, que un día
vacío no se autoanestesia. Está en un test con ese nombre.

**Tests**: `tests/test_guarda_volumen.py` (12 puros + 7 contra DB) y 7 nuevos en
`tests/test_alerts.py`. Suite entera: **603 passed con DB** (4:03), 510 passed /
92 skipped sin DB (2,5 s).

⚠️ **Falta desplegarla**: el Dockerfile **copia** las fuentes, así que el cambio
no llega al scraper que está corriendo. Es `docker compose up -d --build scraper`
y **no dispara una pasada extra** (`espera_hasta_proxima` ancla al
`MIN(started_at)` de la última). No se hizo en esta sesión porque nadie lo pidió.

### Efecto colateral en los tests de agujero

Subir `GAP_LOOKBACK_DAYS` rompió 3 tests de `test_deteccion_agujero.py`, y el
diagnóstico importa: **no era un cambio de comportamiento**, era que esos tests
sembraban 4 días fijos y asumían la ventana de 3, así que los días de más
quedaban sin sembrar y se reportaban como agujeros legítimos. Se los desacopló de
la constante (`_serie_completa` siembra la ventana entera y saca los días que el
test quiere ver faltando) y se agregó
`test_la_ventana_llega_a_una_caida_de_hace_cinco_dias`, que es el que ahora sujeta
el valor nuevo y explica por qué.

## Dos cosas nuevas que salieron al verificar el estado (2026-10-01)

Ninguna es del trabajo de esta sesión; salieron de mirar la DB antes de escribir
este handoff. **Ninguna se tocó.**

1. **Andesgear pasó de 1-2 `partial` por pasada a 15 de 25, y es un escalón, no
   ruido**: 1-2 del 26 al 29-sep, **10** el 30-sep 03h, **15** el 30-sep 15h,
   **15** el 1-oct 03h. Todas son del chequeo exacto de `CountingAdapter`
   ("226 de 245 que declara la tienda"), con faltantes chicos (2 a 28 items) en
   casi todas sus llaves a la vez. Ojo con una diferencia que no es obvia: este
   canario **no se autoanestesia** —es exacto, no estadístico—, así que los 15 van
   a seguir ahí hasta que alguien los mire. Y Andesgear es justo la tienda cuyas
   baselines maduran el **2026-10-26**, la misma fecha de la decisión de
   liquidación de temporada.
2. **Prat falló 3 de sus últimas 4 pasadas** (30-sep 15:36 y 1-oct 03:44, las dos
   categorías, `FetchError: agotados 3 reintentos` en la **página 1**). En esas
   mismas pasadas las otras 12 tiendas anduvieron, así que no es una caída general
   del host. Probado a mano el 1-oct, su `/products.json` responde **HTTP 200 con
   250 productos, con y sin User-Agent**: la tienda está sana y los fallos fueron
   transitorios, consistentes con las ráfagas de DNS ya documentadas (que no se
   arreglan desde el repo). **Por qué igual importa**: el reloj de `MIN_DAYS` de
   Prat arrancó de cero el 29-sep con la llave nueva y su aceptación se evalúa el
   **2026-10-28**; cada pasada que Prat pierde es un día que no cuenta. Vale
   mirarlo en la próxima sesión, y la guarda nueva **no** lo va a reportar: Prat
   es el 2,3% del volumen.


## La liquidación de temporada, decidida (2026-10-01)

**Decisión de producto tomada: la liquidación es una oferta y va al canal.** El
precio baja de verdad, el suscriptor compra barato algo que estaba caro. Cierra
la pregunta que PLAN_TIENDAS §1.3 dejaba abierta y que tenía fecha límite 26-oct
por Andesgear.

**El detector no había que tocarlo** — ya las aceptaba: `detect_ramp` exige un
alza sostenida ANTES de la baja y una liquidación baja sin haber subido, así que
`ramp_flag` queda en False. Lo que estaba mal era la **medición**, y por eso
importaba antes de calibrar: como θ sale del backtest, etiquetar `fake` una
liquidación empujaba θ hacia arriba hasta dejar afuera justo las mejores ofertas
de vestuario y calzado. Se iba a calibrar en contra de lo que el canal quiere
publicar.

La corrección es `LABEL_LIQUIDATION`, con el discriminante mirando el **pasado**:

```
el pozo se quedó abajo (no se recuperó ≥10% en 30 días):
    price <  piso de 60 días  → liquidación: precio nunca visto     → ACIERTO
    price >= piso de 60 días  → inflado que volvió a su nivel real  → falso
```

Dos razones que lo hacen defendible y no un relajo del criterio. Una: un
candidato **aceptado** ya pasó la guarda 3 del detector (`ramp_flag` →
`reject_reason = 'ramp'`), que es la que caza el "subo y después descuento", así
que entre los aceptados el inflado ya se filtró. Dos: el inflado-normalizado
vuelve a un nivel que **ya existía** en la ventana; la liquidación va por debajo
de todo lo observado.

⚠️ **El detalle que costó un test y no es obvio**: el piso se calcula con la serie
**hasta ayer** (`backtest.piso_previo`), NO con el `min_60d` de la baseline. La
pasada de la mañana ya trae el precio nuevo, así que ese `min_60d` —que es la
historia hasta la observación de la tarde— ya incluye la bajada y
`price < min_60d` **nunca se cumple**. Con el `min_60d` la etiqueta nueva no
servía para nada: una liquidación de libro seguía saliendo `fake`. Mirar menos
datos no es look-ahead, es la versión conservadora. Hay cuatro tests sobre
`piso_previo`, uno de ellos específicamente sobre este corte.

La liquidación **cuenta como acierto en `precision`** y lleva **columna propia en
el reporte**, con un aviso cuando pasa la mitad de los aciertos: un canal cuya
precisión viene toda de liquidación es un outlet, no un canal de ofertas, y eso
hay que verlo ANTES de fijar θ.

**Un test viejo cambió de expectativa, y está bien**:
`test_replay_respeta_el_cooldown` afirmaba `label == fake` sobre una baja
sostenida — que es exactamente la forma de una liquidación. Ahora afirma
`LABEL_LIQUIDATION`. Lo que ese test prueba es el cooldown y eso no cambió; la
aserción de etiqueta era incidental. El inflado que vuelve a su nivel sigue
saliendo `fake` y tiene su propio test.

## El backtest ya sabe excluir días degradados (2026-10-01)

Era condición para que la calibración de mañana valga algo, y no existía.

`backtest.DIAS_DEGRADADOS` documenta los tres (18, 19 y 29 de septiembre) y
`--exclude-day` es repetible. **El daño no estaba donde parecía**: `replay_listing`
ya salteaba los días sin observaciones, así que un día vacío nunca emitió
señales — pero sí contaba en el **divisor** de señales/día, que es la mitad del
gate de F1. El numerador pierde las señales y el denominador igual cuenta el día:
sobre 30 días con los tres adentro, el volumen sale 10% abajo.

Sobre el 29-sep hay un matiz que conviene saber: su **pasada de la tarde sí
corrió**, y `replay_listing` toma la última observación del día igual que
producción, así que la emisión de ese día es legítima. Lo que distorsiona es el
**peso en el p50**, porque `percentile` corre sobre los puntos crudos y casi todos
los listings tienen 1 punto en vez de 2. Es menos grave que los otros dos.

Decisiones tomadas acá:

- **No se excluyen solos.** Cambiar el divisor del gate en silencio sería peor que
  el problema. Pero el comando **avisa** si el rango toca uno sin excluirlo, y el
  reporte declara al pie qué días se excluyeron — un divisor del gate que se mueve
  sin decirlo no se puede auditar después.
- **Los días excluidos siguen alimentando la baseline.** Borrarles los puntos
  sería la segunda implementación divergente que la regla de no-look-ahead
  prohíbe. Lo que un día degradado invalida no es la historia —la historia es la
  que hubo— sino su derecho a contar como día de mercado.

**Verificado contra prod**, las dos mitades:

```
--from 2026-09-28 --to 2026-09-30                    → WARNING: incluye 2026-09-29 sin excluir
                                                       3 días de mercado, 0 excluidos
--from 2026-09-28 --to 2026-09-30 --exclude-day 2026-09-29
                                                     → 2 días de mercado, 1 excluidos
```

Y un smoke test del camino entero sobre `tecno-tv` (1.216 listings, 09-01→09-05):
corre, las columnas nuevas renderizan, y **todas las señales salen `s/madurar`** —
que es la confirmación de por qué la calibración es desde el 2026-10-02 y no hoy:
una señal del 1-sep necesita hasta el 1-oct 23:59 para etiquetarse.

**Tests**: 13 nuevos en `tests/test_backtest.py` (9 de liquidación + 4 de
`piso_previo`) más los 9 de exclusión de días. Suite entera: **624 passed con DB**
(4:09), 531 passed / 93 skipped sin DB.

## Las tres del producto, agregadas al plan (2026-10-01)

Vienen de una observación contra los datos y era correcta: **el canal no saca
ofertas de ropa, zapatillas ni cosas chicas**. Las 63 ofertas publicadas tienen
ticket p50 **$279.990** y solo 12 por debajo de $50.000; el p50 de `tecno-tv` es
$1.579.990.

**El ranker NO es la causa** — se verificó antes de tocar nada.
`detector.compute_score` excluye el precio absoluto a propósito ("ponderar por
ticket inundaría los canales de electrónica cara") y está bien así. La causa es la
composición del catálogo: de 9.729 baselines maduras, **72% está sobre $150.000** y
solo 12% bajo $50.000. El detector sí acepta barato (448 aceptados bajo $50.000)
pero el pool viene 6:1 en contra.

Quedó en PLAN_TIENDAS §4bis:

1. **Fase 3 — Ropa: DESBLOQUEADA.** Estaba trabada por la decisión de liquidación.
   Las 5 tiendas y su orden no cambian (Colloky → Hites → La Polar → Tricot →
   ABCDin).
2. **Fase 3b — Calzado urbano 🆕.** Hoy hay Andesgear y nada más: 393 listings y es
   calzado **outdoor**, no hay zapatilla urbana en el sistema. Sparta primero (ya
   auditada: 1.080 en `zapatillas.html`, ~200 llaves de facetas porque su robots
   prohíbe query strings), después Decathlon/Nike/Adidas, que son el mismo patrón
   de bloqueo 403. **Decidir al conectar** si reusa `deporte-calzado` o abre
   `ropa-calzado`: reusar evita un θ nuevo sin calibrar y 30 días más de espera.
3. **Fase 3c — Audio y accesorios 🆕 — era un HUECO del plan, no un pendiente.**
   Audio y accesorios no se mencionaban en ninguna fase de PLAN_TIENDAS. Hoy hay
   **47 audífonos, 19 con baseline madura, 0 publicados**, y son residuo
   incidental de `tecno-celulares` de Falabella y Paris. Es la fase **más barata
   de todo el plan**: no necesita adaptador nuevo —Falabella, Paris, PC Factory y
   SP Digital ya tienen audio y sus cuatro familias ya están escritas—, solo una
   migración con la categoría y llaves nuevas. Recomendado `tecno-audio` sola
   antes que `tecno-accesorios` ancha: un θ porcentual único sobre cosas de $8.000
   y de $400.000 no significa nada. ⚠️ Las llaves nuevas tienen que ser
   **disjuntas** de `tecno-celulares` sobre SKUs reales: hoy los 47 audífonos
   entran por ahí.

**Estado de tiendas del plan: 13 conectadas de ~27.** Falta completa la Fase 3
(0 de 5), Ripley, Fase 5 (Winpy, MacOnline) y las 7 bloqueadas por 403 de la
Fase 6.

## Desplegado y aplicado el 2026-10-01

**1. La guarda por volumen está en producción y disparó bien.** Rebuild a las
14:27; el log dijo `última pasada hace poco; la próxima en 0.8 h`, o sea que el
ancla al `MIN(started_at)` hizo lo suyo y **no metió pasada extra**. La pasada de
las 15:16 cerró con 129 corridas / 16.724 obs y la guarda reportó exactamente un
incidente, el real:

```
📉 OfertasCL — 1 pasada(s) a medias:
  2026-09-29 03:16 UTC — 1.481 obs vs mediana 16.509 (91% menos)
```

Tres veces había pasado ese modo de falla sin una sola alarma (19-ago, 18-20-sep,
29-sep). Ahora tiene una.

**2. Migración 23 — `tecno-audio`** (θ 0.200, 11 llaves, 4 tiendas ya conectadas,
cero adaptadores nuevos).

**3. Migración 24 — `ropa-calzado`** (θ 0.350, 2 llaves de Falabella). Zapatilla
urbana sin esperar a Sparta ni a Decathlon: Falabella ya la tenía.

Estado: **24 migraciones, 12 categorías, 142 objetivos activos** (eran 10 y 129).
Las 13 llaves nuevas corren en la pasada del **2026-10-02 03:16** — los targets se
cargan una vez al arrancar la pasada. Las dos categorías se evalúan el
**2026-10-31**.

⚠️ **Pisé una trampa que ya estaba documentada y vale repetirla**: el primer
`docker compose run --rm db-migrate` dijo *"0 migración(es) aplicada(s)"*. La
imagen de `db-migrate` se había construido a las 14:27 y la migración se escribió
a las 14:40 — **el Dockerfile copia las fuentes**. Con migraciones es más
engañoso que con código, porque no falla: dice que no hay nada que aplicar. Va
`docker compose run --rm --build db-migrate`.

### Lo que se verificó antes de cada migración, y lo que casi se cuela

Todas las llaves se verificaron **por contenido con su propio adaptador**, no por
HTTP 200, y todas por **disjunción sobre SKUs reales**. Dos hallazgos que valen:

- **Falabella miente de una forma que la guarda del adaptador no ve.**
  `cat2049/Audifonos`, `cat1012/Audio` y `cat70028/Audio` devuelven 200, 60
  productos y **pasan `NotAListingPage`** — con impresoras, soportes de TV y
  cámaras. Si una entraba, 30 días de serie de precios de impresoras bajo
  `tecno-audio`. El tamiz que las separó fue contar qué fracción de los nombres
  coincide con la categoría (la buena: 99%; esas tres: ~0%). Está en CLAUDE.md.
- **`FalabellaAdapter` no deduplica entre categorías.** `cat2083/Zapatillas` es el
  paraguas de `Zapatillas-Hombre`/`-Mujer` (solapa 7% y 20%) y esas dos solapan 4%
  entre sí. En Andesgear eso lo salva `dedupe_across_categories`; acá no existe,
  así que entró solo el paraguas.
- **Un bug de mi propio clasificador**: "Botines-Mujer = 32% calzado" era el
  patrón `botin` contra nombres que dicen "Botín". Normalizar tildes antes de
  comparar no es cosmético. Con tildes normalizadas da 99%.

### Decisiones tomadas por cuenta propia

- **`tecno-audio` acotada a audio**, no `tecno-accesorios` ancha: un θ porcentual
  único sobre cosas de $8.000 y de $400.000 no significa nada. Aprobada.
- **`ropa-calzado` nueva en vez de reusar `deporte-calzado`**, y se midió para
  decidirlo: 66%/60% moda-urbano contra 22%/1% deportivo. `deporte-calzado` se
  llama "Calzado outdoor" y su θ=0.30 se eligió para ese comportamiento.
- **θ 0.350 medido, no copiado**: el 56-58% del catálogo de calzado Falabella ya
  declara ≥30% de descuento, así que a 0.30 el umbral no filtra nada. Es el mismo
  argumento con el que la migración 21 puso `deporte-vestuario` en 0.35.
- **SP Digital: las 4 hojas, no el padre `Audio`** (3.622 declarados, pero es
  padre de 8 hojas e incluye cables y grabadoras; con filtro de stock las hojas
  suman 55).

### Lo que esto le hace al ticket del canal

El problema medido era que el 72% de las baselines maduras está sobre $150.000 y
lo publicado tiene ticket p50 $279.990. Lo nuevo:

```
cat2083/Zapatillas       ticket p50 $48.990   mínimo  $9.990
cat690245/Botines-Mujer  ticket p50 $41.990   mínimo  $7.990
```

Recién se nota el **2026-10-31**, cuando esas baselines maduren.

## Prat estaba caído por User-Agent, arreglado y desplegado (2026-10-01)

**Esto era un apagón real y yo lo había llamado transitorio. Me equivoqué.** En la
sesión anterior reporté los fallos de Prat como ráfagas de DNS porque probándolo a
mano con `httpx` respondía 200. Lo que no hice fue probarlo **con su adaptador**.

Prat acumuló **6 corridas fallidas seguidas** (3 pasadas completas, 30-sep 15:36 →
1-oct 15:37, las dos categorías) sin una sola observación. Causa real: **HTTP 429
por User-Agent**. Aislado el 2026-10-01 con 4 intentos de cada uno contra la misma
URL:

```
DEFAULT_USER_AGENT  (termina en "(+ofertascl-bot)")  → HTTP 429  × 4
BROWSER_USER_AGENT  (idéntico, sin ese sufijo)       → HTTP 200  × 4
```

**El 429 es lo que lo hizo caro**: parece límite de tasa legítimo, así que la
reacción natural es bajar `rate_limit_rps` — y eso no lo arregla nunca. Es el mismo
caso que el Varnish de Ferretek y el UA-sniffing de Easy, con otro código.

Fix: `PratAdapter._headers = {"User-Agent": BROWSER_USER_AGENT}`, el patrón que ya
usaban Easy y Ferretek. Se agregó `_headers` a `_ShopifyFamilyAdapter` (default
`None`, o sea que la familia **no** pierde el token de bot: solo lo sobreescribe
quien lo necesita) y se pasa en el `get_text`. Verificado contra la tienda real:
`jardin` 49 productos (lo mismo que antes del apagón) y
`herramientas-y-maquinarias` 300+ (son 1.089). 3 tests nuevos, incluido uno que
prueba la cadena entera — si `_headers` no llega al `get_text`, el fix no sirve.

Desplegado con rebuild del scraper; el log confirma `la próxima en 11.1 h`, o sea
sin pasada extra. **Costo real**: Prat perdió 3 pasadas de serie que no se
recuperan, con su reloj de `MIN_DAYS` arrancado de cero el 29-sep. Su evaluación
sigue siendo el 2026-10-28, pero con tres pasadas menos de las esperadas.

## Andesgear: diagnosticado, y la conclusión es NO tocar nada (2026-10-01)

También acá corrijo lo que dije antes. Reporté los 15 `partial` como "un escalón,
no ruido" que "va a seguir ahí hasta que alguien lo mire". **Las dos cosas estaban
mal**: fue una ráfaga de 3 pasadas (10, 15, 15) y **se resolvió sola** — la pasada
del 1-oct 15:16 volvió a 2.

Diagnóstico definitivo, recorriendo `hombre/top` página por página el 2026-10-01:

```
toolbar-number declara: 518      #am-page-count: 22      24 filas por página
22 × 24 = 528 ≥ 518 ✓            duplicados: 0           deriva: 0
```

O sea que **el adaptador está correcto** y la paginación es estable cuando el
catálogo está quieto. Los faltantes de 1 a 9 ítems son deriva: el total se lee en
la página 1 y no se vuelve a mirar (decisión deliberada, está en el código), así
que un producto insertado mientras paginamos se escapa. La ráfaga coincidió
exactamente con la ventana en que los totales declarados crecían más rápido
(`hombre/top` 502→515→515→518, `mujer/top` 241→250→252): Andesgear estaba
actualizando catálogo.

También se descartó la hipótesis del corte temprano: **cero** warnings
`pagina_repetida` en el log.

**Por qué NO se le pone una tolerancia al chequeo exacto**, aunque era lo primero
que iba a hacer: la distribución medida sobre las 50 corridas históricas es un
continuo de **0,771 a 0,998** (p50 0,976), sin hueco. A diferencia de la guarda por
volumen —donde las sanas daban 0,89 y los incidentes 0,09, con un abismo en medio—
acá cualquier umbral sería inventado. Y taparía el único caso que sí informa:
`mujer/calzado` 162 de 210, que son **dos páginas enteras** perdidas.

Impacto real en la serie: nulo. Perder 1-9 observaciones de 518 en una pasada no
mueve un p50 que pide `MIN_POINTS=30` sobre 30 días.

## Nike conectada y la familia VTEX escrita (2026-10-01, migración 25)

Salió de la Fase 6: el 403 de Nike era **solo por headers**. Con
`http.BROWSER_HEADERS` su API pública de catálogo VTEX está abierta.

**Se escribió la familia, no un adaptador suelto** — `scrapers/stores/vtex_family.py`.
VTEX es la plataforma de buena parte del retail chileno y el plan ya la quería para
Colloky y la Fase 3, así que ese trabajo queda hecho.

Por qué Nike es la mejor relación costo/valor del plan:

- **2.554 productos en ~57 requests por pasada.** La pasada entera son ~2.900.
- **100% de cobertura de EAN** en las 6 subcategorías. Es lo más valioso:
  CLAUDE.md registra que de 3.357 `products` solo **11** tienen 2+ tiendas porque
  las tiendas con GTIN casi no se solapan.
- **Es zapatilla urbana de marca**, lo que la Fase 3b quería de Sparta (~200 llaves
  de facetas) y Decathlon (bloqueada de verdad).

### Dos arreglos en infraestructura compartida que cualquier VTEX futura necesita

1. **`http.SUCCESS_STATUS = {200, 206}`.** VTEX contesta **206 siempre** (el rango
   de `_from`/`_to` es parcial respecto del total). `_request` solo aceptaba 200, así
   que el primer fetch moría con `FetchError: HTTP 206`. Se listan los códigos uno
   por uno y no "todo 2xx": un 204 sin cuerpo devolvería `""` y el parser lo leería
   como catálogo vacío.
2. **`HttpClient.get_with_headers`.** El total de la categoría viene en el header
   `Resources: 0-49/2546`, no en el cuerpo, y es la fuente del canario **exacto**.
   `get_text` sigue con la misma firma: nada existente cambió (561 tests en verde).

### Decisiones de diseño del adaptador

- **Uno por producto, no uno por talle.** VTEX da un `product` con N `items` y los
  items son los talles, todos al mismo precio. El talle que da el precio es el
  **disponible más barato**; `in_stock` mira todos.
- **Llaves = subcategorías, no la raíz.** VTEX corta la paginación en ~2.500 y la
  raíz `nike` declara 2.389. El adaptador avisa cuando una llave supera el tope.
- **Disjunción verificada, y era la pregunta correcta**: `snkrs` podía ser paraguas
  de `nike` (la trampa de `cat2083/Zapatillas` en la migración 24). Intersección
  **0** sobre itemIds en los dos pares (calzado 5.916 vs 1.858; ropa 2.445 vs 232).
- **Mapeo**: calzado → `ropa-calzado` (θ 0.350, misma cosa que trae Falabella);
  ropa → `deporte-vestuario` (θ 0.350, muestreado: poleras, pantalones, polerones,
  chaquetas = sportswear). Reusar evita un θ nuevo sin calibrar.

⚠️ **`nike/accesorios` (272 SKUs) quedó AFUERA a propósito y es decisión pendiente.**
Son **gorros y calcetines**: no son `deporte-equipamiento` (θ 0.250: carpas,
mochilas, escalada) y meterlos en `deporte-vestuario` haría que el nombre mienta.
Son ticket bajo ($14.990 un pack), justo lo que al canal le falta, así que vale
resolverlo — con una categoría `ropa-accesorios` propia, no colándolos.

⚠️ **SNKRS tiene poco stock y es esperable**: son lanzamientos limitados, 11 de 119
en calzado y 10 de 45 en ropa disponibles. Se conectaron porque cuestan 4 requests,
pero no esperes volumen publicable de ahí.

**Estado: 25 migraciones, 14 tiendas activas, 146 objetivos, 12 categorías.** Las 4
llaves nuevas corren en la pasada del 2026-10-02 03:16. Se evalúa el 2026-10-31.
Desplegado con rebuild; el log confirma `la próxima en 9.7 h`, sin pasada extra.

**Tests**: `tests/test_vtex_family.py`, 23 nuevos contra el fixture real
(`tests/fixtures/nike_catalog_calzado.json`). Suite: **561 passed**.

## Segunda sesión del 2026-10-01: el grupo con temas y Tottus

### θ: medido que HOY no se puede, y por qué

El backtest corrió completo (`--from 2026-09-01 --to 2026-10-01` con los 3 días
degradados excluidos, 27.235 listings, 28 días de mercado) y **todas las señales
salieron `unknown`**: precisión `—` en las 7 categorías con historia. La razón es
exacta y no es una estimación: las primeras baselines maduran el **2026-09-01**
(5.310 de golpe) y `label_outcome` exige `series_end ≥ día + 30d 23:59:59`. Para
la señal del 1-sep eso es el 1-oct a las 23:59, y la última observación era de las
15:40.

**Desde el 2026-10-02 se puede, pero con un solo día de señales etiquetadas (~12
en el canal, ~2 por categoría).** Para mover θ por categoría con evidencia hacen
falta 14-30 días etiquetados, o sea **mediados y fin de octubre** — justo cuando
caen las evaluaciones de tienda.

Lo que **sí** quedó medido es la otra mitad del gate, el volumen, y conviene
fijarlo porque cambia la lectura: **ninguna categoría llega sola a 3 ofertas/día a
su θ de partida**, pero el gate es por canal y `vip` suma **~12/día**:

    tecno-componentes  0.150 → 2,8/día     hogar-electro       0.200 → 1,7/día
    tecno-notebooks    0.150 → 2,1/día     ferre-herramientas  0.250 → 1,2/día
    tecno-celulares    0.150 → 2,0/día     ferre-jardin        0.250 → 0,3/día
    tecno-tv           0.180 → ~1,9/día

El tier `ferre` solo sumaría 1,5/día y no pasaría, pero está `is_active=false`,
`gate_enabled=false` y sin `telegram_channel_id`, así que hoy no es un problema.

### El grupo con temas (migración 26)

El destino dejó de ser "un canal por tier" y pasó a ser **(chat, tema)**. Siete
temas en el tier `vip`: Tecnología (5 categorías, cuota 3), Hogar (1, cuota 1),
Vestuario (ropa-calzado + ropa-accesorios, cuota 2), Deporte (3, cuota 2),
S.Mercado (supermercado, cuota 2), Ferretería (2, cuota 1) y Viajes (0, cuota 1).

- **La cuota es del tema**, no del canal: 11/día en total contra las 6 de antes.
  Con techo global el tema con volumen se come los lugares de los demás.
- **Un mensaje por vuelta en todo el chat**, con el turno rotando por tema
  (`load_active_topics` ordena por último post, NULLS FIRST). Sin el corte, siete
  temas publicando uno cada uno son siete notificaciones juntas; sin la rotación,
  Tecnología deja a Ferretería muda para siempre.
- **Falta lo único que no se puede sacar desde acá: los `message_thread_id`.**
  Hay que agregar `@Ofertoon_bot` como administrador del grupo (con permiso de
  publicar y administrar temas) y leer el `chat_id` y el thread de cada tema del
  link de un mensaje suyo (`https://t.me/c/<chat>/<thread>/<msg>`). **No se puede
  con `getUpdates`**: `ofertascl-bot` corre con long polling y una llamada externa
  le robaría los updates de onboarding.
- Mientras no estén cableados **el publisher sigue publicando al canal viejo, sin
  thread**, y eso está verificado: los 6 posts de hoy tienen `topic_id` NULL.

### Tottus conectada (migración 27) — estaba descartada por un diagnóstico mío

El plan la tenía como "el borde pasa, el ORIGEN falla". Era falso y el error era
de método: **Tottus no es VTEX**, corre la plataforma de Falabella, así que el 503
de su "API VTEX" era la respuesta a una ruta inexistente y el 526 un `store_key`
inventado (`/category/` en vez de `/lista/`). `parse_listing` de
`falabella_family` la parsea **sin una línea nueva**.

- 5 paraguas no perecederos, **5.419 listings y 5.515 observaciones** en la
  primera pasada, cobertura 0,966-0,991 por llave, cero duplicados.
- **`sortBy=derived.currentPrice,asc` es lo que hace confiable su serie**: su
  default `_score,desc` cambia entre requests y da 0,911 de cobertura (dos
  recorridos del mismo día dieron 326 y 389 únicos de 427); con precio ascendente,
  0,988. Un SKU intermitente nunca llega a `MIN_DAYS` y por lo tanto nunca da
  baseline.
- **Frutas-y-Verduras y Carnes quedaron afuera** por precio estacional, no por
  tamaño. **Cervezas y Vinos** afuera porque publicar alcohol es una decisión que
  nadie tomó — quedan 2.217 SKUs ahí si se decide que sí.
- ⚠️ **El ticket es de otro orden**: p50 $1.570-$9.390 contra los $279.990 de las
  66 ofertas publicadas. Un 25% sobre $1.570 son $390. El backtest no responde si
  eso vale un mensaje — un descuento del 25% es igual de real a cualquier precio.
- **Esto reemplaza a Lider**, que seguía pendiente de "elegir la tajada": mismo
  rubro, API limpia, sin los 73,8 GB/pasada. Si igual se quiere Lider, la vía
  verificada son las fichas `/ip/<cat>/<slug>/<ean>`.

### `ropa-accesorios` (migración 28)

Los 272 SKUs de `nike/accesorios` que la migración 25 dejó sin casa. Disjunta de
`2/3` y `2/4` sobre los catálogos completos. Dos correcciones al handoff anterior:
el **ticket es $26.990, no $14.990**, y **θ 0.350 es copiado sin evidencia
propia** porque Nike no declara `price_normal` en ninguna llave (`con_dto = 0%` en
las cuatro) — el método de la migración 24 no se puede aplicar ahí.

### Tests

**680 passed con DB** (4:48), 0 failed, 0 skipped. Antes de esta sesión eran 654.
Los 26 nuevos: 13 del grupo con temas (4 puros de cuota + 9 con DB de ruteo,
rotación, fallback y el UNIQUE de thread repetido) y 13 de Tottus.

Una vez la suite murió con **exit 137** (SIGKILL del OOM killer, 818 MB libres),
no por un test. Reintentar antes de diagnosticar.

## 2026-10-02: el primer backtest CON etiquetas, y por qué todavía no fija θ

Hoy el backtest produjo precisión por primera vez (ayer era `—` en todo). Rango
`2026-09-01 → 2026-10-02`, 42.821 listings, 29 días de mercado, los 3 degradados
excluidos.

**La mecánica funciona end-to-end y el patrón es el correcto**: la precisión SUBE
con θ en casi todas las categorías, que es exactamente lo que tiene que pasar si
el detector discrimina.

    ferre-herramientas   0.10 → 58%    0.15 → 89%    0.20 → 100%
    tecno-componentes    0.10 → 75%    0.15 → 80%    0.20 → 100%
    hogar-electro        0.10 → 25%    0.15 → 40%    0.20 → 67%    0.25 → 100%
    tecno-notebooks      0.10 → 78%    0.15 → 90%    0.20 → 100%
    tecno-tv             0.10 → 76%    0.15 → 70%    0.20 → 75%    0.30 → 100%

Dos filas pasan el gate (≥80% con ≥3/día): `ferre-herramientas` θ 0.15 (88,9%,
3,8/día) y `tecno-componentes` θ 0.15 (80,0%, 3,0/día).

⚠️ **Y no alcanza para fijar θ, por un margen grande.** Ese 88,9% son **8 aciertos
sobre 9 etiquetadas** y el 80,0% son **4 sobre 5**. De las 110 señales de
ferre-herramientas, **101 siguen `s/madurar`**: solo las del 1 y 2 de septiembre
tienen sus 30 días de futuro. El IC95% de 8/9 va de ~52% a 100%, o sea no
distingue un canal que cumple el gate de uno que no. **La fecha con evidencia
sigue siendo fin de octubre**, cuando haya 14-30 días etiquetados.

Dos lecturas que sí se sostienen hoy:

- `ferre-jardin` es la única que va **al revés** (50% → 50% → 37% → 20% → 0%), con
  14 etiquetadas. Si el patrón aguanta con más datos, es la primera candidata a
  revisar en serio.
- `liquid.` es 0 en todo salvo `tecno-celulares` (3 y 1). Lógico: septiembre no es
  temporada de liquidación y las categorías de vestuario todavía no tienen datos.
  Quiere decir que `LABEL_LIQUIDATION` **no está probado contra datos reales
  todavía**, solo contra sus tests.

### La guarda de volumen tenía un falso positivo, y era mío

Las corridas manuales de ayer (`--once --store tottus`, etc.) quedaron en
`scrape_runs` separadas de la pasada anterior por más de `PASS_WINDOW`, así que la
guarda las leyó como **una pasada entera que escribió muy poco**: 13 corridas,
9.476 observaciones, ratio 0,57, reportadas al lado del incidente real del 29-sep.
Arreglado con `scrape_runs.is_partial_run` (migración 29), que el runner deriva de
`bool(only_store or only_category)`. Verificado: la guarda volvió a reportar 1 sola
flaca. **El ruido aparecía exactamente cuando la guarda tiene que estar limpia**,
porque uno corre pasadas parciales justo mientras diagnostica.

### La pasada ya es el doble de grande

Las dos pasadas del 2-oct: **152 corridas y ~31.300 observaciones** contra las 129
y ~16.700 de antes, por Tottus (5.496), Nike (2.554) y Prat recuperado (1.135).
Un solo `partial` (Andesgear `mujer/top`, 249 de 251 — la deriva de catálogo ya
documentada). Ojo con la guarda de volumen en los próximos días: su mediana móvil
tiene pasadas de 16.700 y de 31.000 mezcladas, y tarda ~4 pasadas en asentarse en
el nivel nuevo.

## 2026-10-02 (cont.): stock del candidato, y un bug de compresión

### `publisher/stock.py` — no publicar lo que no se puede comprar

Punto 8 del handoff, cerrado para tres de las cuatro tiendas ciegas. Antes de
publicar se abre la ficha del candidato y se lee su disponibilidad; el resultado
queda en `deal_candidates.stock_ok` (migración 30).

- **Medido antes de construirlo: 2,5%.** De los 40 candidatos aceptados más
  recientes de Falabella y Sodimac, 39 disponibles y 1 agotado. Es un pulido de ~1
  oferta cada cinco días, **no un salto de precisión** — el detector ya acierta en
  el 97,5% por este eje y el backtest no va a moverse.
- ⚠️ **El lector tuvo un agujero exactamente donde importaba.** `isOutOfStock` está
  en `pageProps` en algunas fichas y en `pageProps.productData` en otras; mirando
  solo la primera, 2 de 14 fichas quedaban sin señal **y las dos estaban
  agotadas**. Las que anidan el dato son justamente las que no traen `availability`
  en el JSON-LD. Apareció al probar en vivo, no en los tests: **un lector de ficha
  hay que probarlo contra fichas agotadas**. Con las dos ubicaciones, cobertura
  100% sobre 18 fichas frescas (13 disponibles, 5 agotados, 0 sin señal).
- **Paris queda afuera**: su ficha trae JSON-LD de Product pero sin
  `offers.availability`. Devuelve `None`, que no bloquea.
- La verificación en vivo del camino completo **se ejercita en la primera
  publicación del 3-oct**: la cuota del 2 ya estaba agotada (6 posts) cuando se
  desplegó, así que el ranker no devolvía candidatos y `stock_checked_at` sigue en 0.
  Está cubierta por 16 tests y por la prueba contra fichas reales.

### Un bug de compresión que no estaba haciendo daño todavía

`BROWSER_HEADERS` pedía `Accept-Encoding: gzip, deflate, br` y **brotli no está
instalado**: httpx no podía descomprimir lo que ofrecíamos. Una tienda que elige
`br` devuelve un cuerpo binario con HTTP 200 y el parser lo lee como página sin
productos — un `failed` cuyo síntoma aparenta "la tienda cambió de formato".

Medido contra Falabella, que sí responde `br`: 190 KB ilegibles contra 1.068 KB de
HTML. **No había daño porque las dos tiendas que mandan estos headers (Tottus,
Nike) responden `gzip` por elección del servidor** — funcionaban por suerte, y el
día que su CDN cambiara fallaban las dos a la vez. Ahora el header se deriva de los
codecs presentes, así que no puede volver a desincronizarse.

Lo encontré de casualidad, investigando la ficha de Falabella para el verificador
de stock: su cuerpo llegaba binario.

## 2026-10-12: diez días sin supervisión, y lo que apareció

El sistema siguió sano solo: 152 corridas por pasada, ~29.000 observaciones,
**6 posts/día sin interrumpirse en diez días**, 0 migraciones pendientes. Y cuatro
cosas que nadie había visto.

### Tres hallazgos con arreglo aplicado

1. **`max_pages` recortaba la familia Falabella en silencio.** 960 productos por
   llave contra los 18.412 que declara `cat2083/Zapatillas`. El canario estadístico
   no podía verlo —960 de 18.412 se ve igual de sano que 960 de 1.000 cuando se
   compara contra la propia historia— y el daño era sobre la baseline: de los 3.363
   SKUs que `ropa-calzado` vio el 2-oct, solo **107 (3%)** seguían en la ventana
   diez días después. Ahora son 2.640 por llave y 19 de las 21 llaves activas entran
   completas; `ropa-calzado` pasó de ~1.920 observaciones por pasada a ~4.775.
   Costo medido: +150 requests, de 10 a 15 min para las tres tiendas.
2. **El producto reacondicionado no es una oferta** (`REJECT_REFURBISHED`). Era la
   causa del patrón invertido de `tecno-celulares`: 44% de los aceptados con ≥30% de
   descuento eran reacondicionados contra 8% de los de menos. Excluirlos sube la
   precisión 10-30 puntos según θ y aplana el patrón. **8 de las 132 ofertas ya
   publicadas eran reacondicionados.**
3. **SP Digital vació dos categorías** (`Category:1293` y `Category:1493`):
   devuelven cero productos, una desde antes del 5-oct y la otra desde el 9-oct, 20
   corridas `failed` en total. Apagadas en la migración 31. El sistema **sí avisó**
   —cada pasada las reportó— y nadie leyó la alerta en diez días; eso no es un
   agujero de código.

### El Cyber Monday quedó capturado

El 5, 6 y 7 de octubre el detector aceptó ~1.000 candidatos/día contra los ~150
normales, con 33% de descuento promedio en ferretería y 884 aceptados solo en
celulares. El publisher publicó sus 6/día por cuota. **Esas señales se etiquetan
desde el 5 de noviembre** y van a ser la mejor evidencia que tengamos para θ: es el
único evento de descuentos masivos reales en la serie.

### θ: hay señal direccional, NO calibración — y corrijo un error mío

⚠️ El 12-oct reporté denominadores de 437, 278 y 154 señales etiquetadas. **Estaba
mal**: sumé la columna `s/madurar`, que es justamente lo que todavía no tiene
etiqueta. Los denominadores reales son mucho más chicos:

    ferre-herramientas  θ 0.15   92,5%   n=40     ← el mejor dato que hay
    hogar-electro       θ 0.15   81,1%   n=37
    tecno-celulares     θ 0.10   67,4%   n=43
    tecno-componentes   θ 0.10   84,8%   n=33
    tecno-notebooks     θ 0.10   82,1%   n=28
    hogar-electro       θ 0.20   87,5%   n=24
    tecno-tv            θ 0.20   81,2%   n=16

Con n entre 16 y 43, lo que hay es **señal direccional**: los θ de partida apuntan
al lugar correcto y la precisión sube con θ como debe. Pero no alcanza para fijar
ninguno, y **no se cambió ningún θ**. El dato que lo va a resolver es el Cyber
Monday a partir del 5-nov.

## 2026-10-12 (cont.): la precisión medida subestima al detector

Investigando el patrón invertido de `ferre-jardin` apareció algo más grande, y
cambia cómo hay que leer el gate de F1.

**El 89% de lo que el backtest llama `fake` no es un precio inflado.** Clasifiqué
los 19 `fake` de las 7 categorías con datos, a sus θ vigentes, según la forma del
futuro de cada señal:

    SIGUE_BAJO    13 (68%)   el precio bajó TODAVÍA MÁS después de la señal
    PLANO          4 (21%)   se quedó exactamente en el precio publicado
    REBOTA_POCO    2 (10%)   subió algo, sin llegar al umbral de recuperación

`label_outcome` usa "¿el precio volvió a subir?" como proxy de "¿era una oferta
real?". Ese proxy falla en toda categoría con tendencia descendente de precio, o
sea en toda la tecnología: en `tecno-celulares` el 75% de los `fake` son
`SIGUE_BAJO`. Y los dos primeros casos **no son fallas del detector**: si se
publica a $99.990 algo cuyo p50 era $134.990 y después baja a $79.990, la oferta
fue real — que siga bajando la vuelve "no era el fondo", no falsa.

Es el mismo mecanismo que motivó `LABEL_LIQUIDATION` (§1.3) un nivel más abajo: el
discriminante del piso solo rescata los que bajan a un precio **nunca visto**, así
que uno que baja a un nivel donde ya había estado queda `fake` aunque después siga
bajando. Y tiene la misma consecuencia: **θ calibrado contra esta métrica queda más
alto de lo necesario**, dejando afuera ofertas buenas.

⚠️ **No toqué el etiquetado.** Son 19 muestras y cambiar `label_outcome` es cambiar
el gate. La decisión tiene que esperar al 5 de noviembre, cuando el Cyber Monday
(~1.000 señales/día el 5, 6 y 7 de octubre) se pueda etiquetar: ahí habrá miles de
casos para decidir con evidencia si `SIGUE_BAJO` cuenta como acierto.

**Y una corrección sobre `ferre-jardin`**: el "patrón invertido" que reporté no
existe, es ruido. Está construido sobre 6 a 14 señales etiquetadas (a θ 0.25 son 3
`real` y 3 `fake`). No es comparable con celulares, donde el mecanismo quedó
demostrado.

### El incidente del reinicio

El host se reinició a las 19:36 UTC y **Ofertoon quedó caído**: Postgres volvió
solo por su `restart: unless-stopped`, pero a las 19:42 algo detuvo los
contenedores explícitamente (`shutdown_signal received` en publisher y gate), y esa
política no revive lo que se paró a mano. signalsTrading volvió entero y siguió
arriba todo el tiempo. Levantado a las 21:56 con `docker compose up -d`, todo
healthy y sin pérdida: la pasada de las 15:16 había corrido antes del reinicio y la
siguiente era a las 03:16.

**Lo que conviene saber para la próxima**: `unless-stopped` no protege de esto. Si
el apagado no fue deliberado, vale revisar qué paró los contenedores cinco minutos
después del boot.

## 2026-10-12 (cierre): salud del sistema, medida por primera vez completa

### El criterio de aceptación nunca se había corrido sobre las tiendas viejas

`scripts.aceptacion_tienda` estaba agendado solo para las nuevas. Corrido sobre
todas las evaluables, **todas pasan** y ninguna se acerca al umbral del 40%:

    easy        1.906 cohorte  1.524 maduros   80%
    sodimac     1.906           1.333          70%
    pcfactory     560             369          66%
    paris       4.485           2.915          65%
    spdigital     620             308          50%
    falabella   8.542           4.191          49%   ← la peor, igual sobre el umbral

Las siete nuevas (ferretek, urban, kupfer, construmart, kruuse, andesgear, prat)
siguen EN ESPERA: les faltan 11-14 días.

⚠️ **Y esto corrige una alarma mía**: me preocupó que "de 62.286 listings solo
10.640 maduran (17%)". Ese es exactamente el error transversal que el script existe
para evitar — Falabella tiene 23.195 listings de menos de 30 días (el 80% de su
catálogo) porque creció de 35k a 62k en diez días con las llaves nuevas y la
ventana de 2.640. Por cohorte la salud es 49-80%, no 17%.

### Nike: por qué falla, y por qué no hay nada que arreglar en el adaptador

Sus `FetchError` (10 de 70 corridas en 7 días) **no son de tamaño**: sus páginas
pesan 1,2-5,8 MB (174 MB por pasada, 0,35 GB/día) y tardan 0,6-2,0 s contra un
timeout de 30 s. Los offsets que fallaron responden `206` perfecto al reintentarlos
a mano. Es la red del host — el WiFi USB con fallos de DNS a ráfagas que CLAUDE.md
ya documenta como no arreglable desde el repo.

Lo que sí se arregló es la **clasificación**: siete de esas diez corridas habían
persistido contenido (350, 800, 749, 398, 300, 200 y 50 observaciones de las ~1.038
de una corrida sana) y quedaban marcadas `failed`, que es el único status que el
canario descarta de su historia de volumen. Ahora `partial` si vio algo, `failed`
solo si no vio nada.

### El verificador de stock funciona, y sus números cierran exactos

33 verificaciones acumuladas, 3-4 por día todos los días desde el 3-oct, **cero
agotados**. Y el total cuadra: son exactamente los 18 posts de Sodimac + 15 de
Falabella. Paris (15 posts) y Easy (12) dan cero porque no tienen lector, que es lo
correcto. Con el 2,5% medido, lo esperado en 33 era 0,8 agotados.

### Revisión de llaves: nada nuevo roto

Barrido de las 150 llaves activas: fuera de SP Digital (apagada hoy), Nike (red) y
los `partial` de Andesgear (deriva de catálogo, documentada y sin tolerancia a
propósito), **ninguna tienda llevaba más de 48 h sin observar**.

## 2026-10-19: cinco días caído, y la cuota abierta a las catorce categorías

### El agujero: 14 al 18 de octubre, cero observaciones

**Segunda vez en una semana y por la misma causa.** Los contenedores de Ofertoon
quedaron detenidos el 13-oct y el reinicio del host del 14-oct **no los revivió**:
`restart: unless-stopped` no levanta lo que fue parado a mano. signalsTrading, en el
mismo host, volvió entero — su política sí lo revive porque nunca fue detenido así.

Descubierto el 19-oct al ir a consultar la base. Cinco días sin una sola
observación para 62.286 listings. **No se recupera**: la serie no tiene relleno
hacia atrás. Levantado, y el scraper corrió una pasada al arrancar solo (el
intervalo estaba vencido desde el 13).

Consecuencias concretas:
- Los cinco días entran en `backtest.DIAS_DEGRADADOS`, que pasó de 3 a 8 días.
- **Las fechas de madurez corren ~5 días.** Medido por días calendario distintos de
  historia, no por fecha de conexión:

        deporte-calzado, deporte-equipamiento   19 días  → madura ~30-oct
        deporte-vestuario                       18       → ~31-oct
        ropa-calzado, ropa-accesorios, super.   13       → ~5-nov
        tecno-audio                             12       → ~6-nov

- El Cyber Monday (5-7 oct) sigue etiquetable desde el 5-nov, pero su ventana de 30
  días ahora tiene cinco días sin datos en el medio. `label_outcome` busca el máximo
  del futuro, así que con menos muestras es **menos probable detectar la
  recuperación**: sesga hacia `fake`. Hay que tenerlo en cuenta al leer esa
  calibración.

### La cuota: de 6 a 14 ofertas/día

Decidido el 2026-10-19: todo sigue al canal actual (`-1003914468578`), los temas del
grupo quedan sin cablear, y la precisión sin calibrar no bloquea porque el canal no
tiene usuarios.

**Las catorce categorías ya estaban ruteadas al canal** — no había nada que
"activar" ahí. Lo que sí era un freno es la cuota: con `MAX_PER_DAY = 6` y el tope
de 2 por categoría, **solo tres de las catorce aparecían por día**.

    MAX_PER_DAY            6 → 14   una por categoría en promedio
    MAX_PER_STORE_PER_DAY  2 → 3    porque 6 tiendas maduras × 2 = 12 < 14
    MAX_PER_CATEGORY       2        sin cambios: fuerza siete categorías por día

El tope por tienda en proporción es **más** estricto que antes: 3 de 14 es un techo
del 21% contra el 33% de 2 de 6.

⚠️ **Lo que NO se tocó, y no se debe tocar: `MIN_POINTS`/`MIN_DAYS`.** Las siete
categorías nuevas no publican porque todavía no tienen baseline, y eso es distinto
de la precisión sin calibrar: con θ de partida el descuento se mide mal, pero sin
baseline madura **no hay contra qué medirlo** — el p50 de tres días es ruido y el
"descuento" sería inventado. Es la regla que hace que el producto sea lo que dice
ser.

### Un dato nuevo sobre la cuota: la ventana puede cortar antes

Desde las 13:00 hasta que la ventana cierra a las 22:00, con 45 min de espaciado,
caben **12** publicaciones. La cuota de 14 se alcanza solo arrancando cerca del
inicio de la ventana (13 h dan 17 espacios). Salió de arreglar el test de cuota, que
pasaba por la razón equivocada.

## ⚠️ PENDIENTE CON FECHA: revertir `min_history_days` el 2026-11-06

Lo primero que hay que mirar al abrir este handoff si la fecha ya pasó:

    UPDATE categories SET min_history_days = 30;

Desde el 2026-10-19 las siete categorías conectadas en octubre tienen
`min_history_days = 10` en vez de 30 (migración 32), por decisión explícita del
dueño del producto: no publicaban nada porque les faltaban 11-18 días de historia,
y se aceptó que publiquen con descuentos mal calculados porque el canal no tiene
usuarios y se corrigen solas al madurar.

Cada una llega a los 30 días por su cuenta en estas fechas, medidas por días
calendario distintos de historia y ya con el agujero del 14-18 de octubre
descontado:

    deporte-calzado, deporte-equipamiento   ~30-oct
    deporte-vestuario                       ~31-oct
    ropa-accesorios, ropa-calzado, super.   ~5-nov
    tecno-audio                             ~6-nov

**Dejarlo puesto después del 6 de noviembre es peor que no haberlo puesto**: el
canal publicaría contra un p50 de dos semanas cuando ya existe uno de ocho.

Lo que el backtest NO ve: `replay_listing` sigue midiendo con 30 a propósito, así
que la calibración de las siete categorías viejas —y el Cyber Monday del 5-nov—
quedan intactas. Esa fue la razón de hacerlo por categoría y no bajando
`baselines.MIN_DAYS`, que es la misma función en producción y en el backtest.

Verificado el día que se puso: 23 candidatos aceptados en categorías que daban
cero (21 en deporte-equipamiento, 2 en tecno-audio) y el publisher posteó al canal.
Un ejemplo de lo que esto acepta: "Banano Jester Lumbar, p50 $29.990 → $20.990,
−30%" es un producto con dos precios en diez días, indistinguible de una oferta
real con esa historia.

## Lo que sigue, en orden

0. **La guarda por volumen quedó cerrada** (ver la sección de arriba). Lo único
   que le falta es el `docker compose up -d --build scraper`.
1. **Calibrar θ** es lo próximo que mueve la aguja, y no antes del 2026-10-02
   (con volumen, ~mediados de octubre). El output de `pricing/backtest.py` **es**
   el gate: precisión ≥80% con ≥3 ofertas/día. Los θ de
   `categories.discount_threshold` son valores de partida del plan, **no** están
   calibrados. Ninguna de las cuatro tiendas conectadas esta semana participa
   (Kupfer 24-sep; Construmart, Kruuse y Andesgear 26-sep): les faltan 30 días y
   se evalúan el 24 y el 26 de octubre.
2. **De las tres decisiones que estaban sobre la mesa quedan menos.**
   `assign_products` se wireó el 28-sep y la liquidación se decidió el 1-oct
   (§1.3: es una oferta, va al canal). Sigue abierta **Sparta** —~200 llaves de
   facetas— y ahora tiene un motivo de producto para resolverse: es la única
   fuente de zapatilla urbana del plan (Fase 3b).
3. **Probar el funnel con un pago real.** Lo verificado es el trial: PayPal creó
   la suscripción y mandó el `CREATED` con firma válida, pero nadie pagó, así que
   `PAYMENT.SALE.COMPLETED` —el evento que valida los 6.00 contra `price_usd`—
   nunca corrió. **Es el único eslabón sin verificar entre acá y cobrar.** Hoy
   hay 1 membresía (`vip`, `expired`/`kicked`, la del owner) y el plan vivo es
   `P-8TJ137481H7582421NJYMG5A` a 6.00 USD.
4. **Re-evaluar lo que el publisher ya está sacando.** Se prendió el 2026-09-21
   (`PUBLISHER_ENABLED=true`), **antes** del backtest y a propósito: el `.env` de
   prod lo tiene en `true` y el daemon arranca con `enabled=True`. Ver DEPLOY.md
   §10 para el apagado de urgencia. Lo pendiente ya no es prenderlo, es medir con
   el backtest cuántas de esas ofertas aguantan θ calibrado — y decidir si el
   canal sigue publicando mientras tanto.
5. **Verificar `in_stock` en la ficha** solo para el candidato (10–30
   fetches/día, no 2.898). Hoy Paris y Falabella lo asumen `True` y la guarda de
   stock es ciega. Quedó fuera de F3.
6. **Llevar el chequeo de completitud a las demás tiendas.** Paris ya parsea un
   `total` de ítems (`paris.py:148`) y PC Factory un `totalPages`
   (`pcfactory.py:117`); hoy solo SP Digital implementa `CountingAdapter`. Es la
   guarda más barata y exacta que tiene el runner.
7. **F4 — lanzamiento**, **F5 — expansión**.

## Decisiones tomadas que conviene no re-litigar

- **La fase de pricing corre dentro del ciclo del scraper**, no como servicio
  aparte (`scrapers/runner.py:run_pricing` → `pricing/pipeline.py`). El trigger
  correcto de una baseline es "llegaron observaciones nuevas", y el runner es el
  único que sabe cuándo pasó eso; un cron propio se desincroniza y termina
  evaluando medio catálogo contra la foto de hace 12 h. Va envuelta en
  `try/except`: la ingesta es lo irreversible, una corrida de pricing salteada
  se rehace sola. Cuesta **11 s** sobre ~10.700 listings.
- **El publisher SÍ es servicio aparte** (`publisher/daemon.py`), porque
  *cuándo llega el dato* y *cuándo conviene publicar* son preguntas distintas.
  Pegado al scraper, la cuota entera saldría de golpe a la hora en que se haya
  levantado el contenedor.
- **Los rechazos por `history` no se persisten** (`detector.UNPERSISTED_REJECTS`).
  Son ~10.700 filas por corrida (650k/mes) que no calibran nada; se cuentan en
  las stats. Todo rechazo que sí discrimina (rampa, umbral, piso, cooldown) se
  guarda entero. **Consecuencia operativa:** una `deal_candidates` vacía NO
  prueba que el job no corrió. Hay que mirar la línea `pipeline:` del log.
- **La cuota diaria por canal no está en el detector** aunque el plan la liste
  entre las guardas: es curación (cuántos aceptados se publican), no detección
  (si esto es una oferta real). Vive en `curation/ranker.py`. Son constantes del
  módulo y no env vars a propósito: son decisiones de producto y cambiarlas
  debería quedar en el historial de git.
- **`detected_at` es el `observed_at` de la observación**, no la hora del job
  (migración 14 + `UNIQUE(listing_id, detected_at)`). Sin eso el job programado
  duplicaba candidatos en cada corrida.
- **El publisher reserva la fila de `deal_posts` ANTES de enviar** y la borra si
  el envío falla. El orden inverso publica dos veces cuando el proceso muere en
  el momento justo, y eso no se deshace. El costo es poder *perder* una oferta:
  es la dirección correcta para equivocarse.
- **`min_60d` de la baseline no sirve para decir "el más barato en 60 días"**:
  las baselines se recomputan ANTES del detector, así que ese mínimo ya incluye
  el precio de la oferta y la afirmación sería cierta para todo aceptado que sea
  mínimo. El ranker calcula `min_prior` con un subselect que excluye la
  observación evaluada.
- **El fuzzy sobre nombres quedó afuera de `catalog/identity.py`** a propósito:
  solo agregaría los matches dudosos, que son los que rompen el copy. Por eso
  solo 875 listings tienen identidad (GTIN → marca+modelo → nada).

## Gotchas que ya costaron tiempo — no repetirlos

- **Una imagen desincronizada tumba el ciclo entero, y el `try/except` de
  `run_pricing` NO protegía de eso.** El import de `pricing.pipeline` estaba
  *afuera* del `try`, así que un `ModuleNotFoundError` escapaba la guarda que el
  docstring promete ("un bug en el detector NO puede tumbar el scraper").
  Corregido el 2026-08-17 moviendo el import adentro. Sin ese arreglo, cualquier
  build desfasado repite los 178 reinicios.
- **El resolver DNS de Docker se degrada en contenedores de larga vida.** Tras
  ~28 h, `gate` y `publisher` fallaban con `Temporary failure in name
  resolution` contra `api.telegram.org` mientras la conexión TCP directa a la IP
  funcionaba y un contenedor recién creado en la misma red resolvía bien. Se lee
  como "Telegram caído" o "token mal" y no lo es. Se arregla con
  `docker compose up -d --force-recreate <svc>`; no hace falta tocar el daemon.
- **El gate no puede expulsar al owner del canal y cicla para siempre.** Si la
  cuenta dueña del canal tiene fila en `telegram_memberships` y esa membresía
  expira, `banChatMember` devuelve `400 can't remove chat owner`,
  `_apply_revoke` no persiste `channel_state` y reintenta cada
  `GATE_POLL_SECONDS` indefinidamente (pasó del 14 al 17 de agosto, ~2 días a 30
  s). No expulsa a nadie ni bloquea otras filas, pero entierra los errores
  reales del log. Se cierra por datos:
  `UPDATE telegram_memberships SET channel_state='kicked' …` para esa fila —
  `'kicked'` acá significa "el gate no le otorgó acceso", no "lo expulsé".
  **No suscribas la cuenta owner a sus propios canales.**
- **`percentile()` corre sobre los puntos crudos, no sobre los diarios.** Si la
  frecuencia de muestreo cambia, el p50 cambia aunque los precios no se muevan.
  Es la trampa que convirtió el incidente del scraper en un problema de señal y
  no de espacio en disco. Los datos ya se repararon, pero **la propiedad sigue
  ahí**: cualquier corrida anómala del scraper vuelve a envenenar la baseline.
  Si vuelve a pasar, el remedio está escrito en `scripts/repair_oversampling.py`.
- **Una alarma que no se apaga tapa las que importan.** Pasó dos veces con la
  misma forma: el gate ciclando contra el owner del canal (agosto) y el canario
  enclavado en SP Digital (septiembre). Las dos veces el síntoma fue ruido
  constante en el log y las dos veces el bug real era que el estado degradado no
  tenía forma de volver a normal. Cuando escribas una guarda, preguntate cómo
  sale del estado en que entra.
- **Los tests con serie sintética se anclan a `datetime.now()`, no a una fecha
  literal.** `pricing/detector.py` descarta las observaciones de más de
  `PRICE_MAX_AGE_HOURS` (26 h) **contra el reloj del servidor**, y
  `baselines.py` hace lo mismo con su ventana de 60 días. Un test que siembra
  `price_points` en una fecha fija funciona el día que se escribe y se apaga
  solo a las 48 h: el detector evalúa 0 filas, no acepta nada y se cae todo lo
  que dependa de un aceptado. Pasó con `tests/test_f3_end_to_end.py` —escrito el
  04/08, el 06/08 fallaban 12 de 17— y el modo de falla es caro porque la suite
  queda roja sin que nadie haya tocado código. Auditado el resto de la suite: es
  el único archivo afectado. `test_baselines.py` y `test_detector.py` usan
  fechas literales pero son puros y reciben `now` inyectado; el test de
  `fetch_tier_stat_rows` siembra con `NOW() - INTERVAL`, que es la forma
  correcta cuando el dato va a la DB.
- **Conexión a la DB**: `psql` falla por autenticación. El `.env` trae el DSN de
  la red Docker (`@postgres:5432`); desde el host hay que reescribirlo a
  `@localhost:5436`:
  ```bash
  cd ~/servicios/ofertoon && set -a && . ./.env && set +a && \
  export DATABASE_URL="${DATABASE_URL/@postgres:5432/@localhost:5436}" && \
  .venv/bin/python -c '...'   # asyncpg
  ```
  En el host nuevo **no hay `.venv`** (ni pytest instalado). La vía más corta es
  correr el script adentro de un contenedor, que ya trae asyncpg y el DSN bueno:
  ```bash
  docker compose cp script.py scraper:/tmp/ && docker compose exec -T scraper python /tmp/script.py
  ```
  Para la suite, un contenedor efímero con el repo montado:
  ```bash
  docker run --rm -v "$(pwd)":/app -w /app ofertoon-scraper \
    sh -c "pip install -q pytest pytest-asyncio && python -m pytest -q"
  ```
- **Después de tocar el código hay que reconstruir el contenedor**
  (`docker compose up -d --build <svc>`): el Dockerfile copia las fuentes, no
  las monta, así que un cambio en el host no llega al servicio que está
  corriendo.
- **`data/postgres` es del uid 70** (postgres de alpine). NUNCA correrle
  `chown -R` con otro usuario: rompe la DB entera. Ya pasó una vez.
- **`docker build` falla sin `.dockerignore`**: `./data/postgres` es el bind
  mount de Postgres y es de root (`can't stat`). Ya está resuelto, no lo borres.
- **El gate expulsa gente de los canales y eso NO se deshace.** `GATE_ENABLED` y
  `telegram_tiers.gate_enabled` están **los dos en true** para `vip` (`ferre`
  tiene `gate_enabled=false` y `telegram_channel_id` sin cargar); el efectivo es
  el AND. Hoy es inofensivo porque hay una sola membresía (la del owner,
  `expired`/`kicked`), pero antes de tocar `telegram_memberships`,
  `telegram_tiers` o `subscriptions/`, pensá a quién puede echar. Apagado de
  emergencia: `GATE_ENABLED=false` + `docker compose up -d gate`.
- **La API de Paris es 1-indexada**: `page=0` devuelve HTTP 500. Costó dos
  diagnósticos falsos de "anti-bot".
- **Paris solo trae EAN para los primeros ~60 productos** del ranking de cada
  categoría (pág. 1 → 38/40; pág. 5 → 0/40; con `pageSize=100` → 62/100: el corte
  es por posición absoluta, no por página). El fixture es la página 1 y **engaña**.
  La cobertura se acumula sola entre pasadas porque el upsert usa `COALESCE` y el
  orden `relevance` rota.
- **Falabella, Sodimac, Easy y PC Factory NO exponen GTIN ni modelo en el
  listado** — auditado contra payload real. Habría que abrir fichas.
- **Silent degradation por tienda**: Easy hace UA-sniffing (HTTP 200 + home),
  PC Factory acepta solo nombres en `categorias`, Paris ignora los parámetros de
  paginación del SSR (por eso el adaptador va contra el microservicio de
  catálogo), SP Digital devuelve `edges: []` con HTTP 200 si el id de categoría
  no existe. Un HTTP 200 no significa que el adaptador funcione.
- **SP Digital declara `Crawl-delay: 5`** en su `robots.txt` y el adaptador lo
  respeta con `rate_limit_rps = 0.2`. No subirlo sin releer el robots.
- **`scrape_runs` no tiene columna `items_found`** sino `items_seen` / `items_ok`,
  y el mensaje de error está en `error`, no `error_message`.

## Verificación rápida al arrancar

```bash
cd ~/servicios/ofertoon
docker compose ps                                          # postgres healthy + 7 servicios up
docker compose logs scraper | grep "pipeline:" | tail -3    # el job de pricing corrió
docker compose logs --since 5m gate | grep -c telegram_     # tiene que dar 0
git status --short                                          # hay cambios sin commitear, ver §Estado real
```

Y lo que el incidente del 17 dejó como lección: **verificar que el contenedor
corre la imagen que creés**, porque un desfase acá no da error hasta que es
tarde.

```bash
for c in scraper bot gate publisher paypal-webhook; do
  cid=$(docker compose ps -q $c)
  [ "$(docker inspect -f '{{.Image}}' $cid)" = "$(docker image inspect -f '{{.Id}}' ofertoon-$c)" ] \
    && echo "$c: OK" || echo "$c: DESFASADO"
done
```
