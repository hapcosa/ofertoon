# Handoff Ofertoon — estado al 2026-09-01

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
necesita ≥45 días (~17 de septiembre).

- **15.475 listings**, 6 tiendas. Última pasada del pipeline (1-sep 18:13, ya
  con los datos reparados):
  `baselines[15475 listings, 15475 escritas, 5227 con historia suficiente, 190
  con rampa] detector[10005 evaluados, 42 aceptados (above_floor=12,
  history=4778, ramp=88, threshold=5085)]`.
- **420 tests**; sin `TEST_DATABASE_URL` corren 350 y se saltean 70 en ~3 s. Con
  la variable seteada la suite tarda **~40 minutos** — casi todo es el `TRUNCATE`
  de `price_points` y sus particiones en el fixture. No es un cuelgue.
- **Migraciones 01..14 aplicadas**, 0 pendientes.
- **7 commits**, el último `0ab6148` (F3 ya commiteado). En el working tree
  quedan `scrapers/runner.py` (ver incidente 2026-08-17), los tres arreglos del
  canario del 1-sep (`scrapers/base.py`, `scrapers/stores/spdigital.py`,
  `db.py`, `tests/`) y `scripts/repair_oversampling.py`. **Nada commiteado.**
- Servicios arriba: `postgres` (healthy), `scraper`, `bot`, `gate`,
  `paypal-webhook`, `publisher`, `cloudflared`. Los 5 servicios propios corren
  la imagen reconstruida el 2026-09-01 18:20, verificada sin desfase.

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
  confirma) y `formatter.py` (el mensaje). **Levantado e inerte**:
  `PUBLISHER_ENABLED=false`. `deal_posts` está vacía.
- **Migración 14** — `detected_at` pasa a ser el `observed_at` de la observación
  y `UNIQUE(listing_id, detected_at)` hace el job re-ejecutable.

**El cold-start terminó el 2026-09-01.** El binding era `MIN_DAYS = 30`
(`MIN_POINTS = 30` se cumplía de sobra). La serie arranca el **2026-08-03**, así
que el día 30 cayó el 1-sep y **5.227 listings** cruzaron el umbral en la pasada
de las 07:54. `deal_candidates` pasó de 17 filas (todas `out_of_stock`) a 5.255.
Los rechazos por `history` siguen sin dejar fila (ver más abajo).

### Cuándo empiezan a salir ofertas

| Hito | Fecha | Estado |
|---|---|---|
| Historia suficiente | **2026-09-01** | ✅ hecho. 5.227 baselines publicables, 42 aceptados |
| Backtest con ≥45 días | **~2026-09-17** | pendiente. Recién ahí `pricing/backtest.py` tiene con qué calibrar θ (precisión ≥80 % con ≥3 ofertas/día) |
| `PUBLISHER_ENABLED=true` | después del backtest | pendiente. Antes de eso el canal recibiría ofertas medidas contra θ sin calibrar |

Entre el 1 y el 17 de septiembre el detector va a producir candidatos que **no
hay que publicar todavía**: son la materia prima del backtest. Con la baseline ya
reparada, los que se acumulen desde el 1-sep 18:13 sí son dataset limpio.

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

## Lo que sigue, en orden

1. **Commitear lo que está en el working tree.** Son tres cosas independientes y
   dan para tres commits: el import dentro del `try` de `scrapers/runner.py`
   (`fix:`), los arreglos del canario (`fix:`) y `scripts/repair_oversampling.py`
   + este handoff (`chore:`/`docs:`).
2. **Calibrar θ** (~2026-09-17, con ≥45 días). El output de
   `pricing/backtest.py` **es** el gate: precisión ≥80% con ≥3 ofertas/día.
   Los θ de `categories.discount_threshold` son valores de partida del plan,
   **no** están calibrados.
3. **Probar el funnel con un pago real.** Lo verificado es el trial: PayPal creó
   la suscripción y mandó el `CREATED` con firma válida, pero nadie pagó, así que
   `PAYMENT.SALE.COMPLETED` —el evento que valida los 6.00 contra `price_usd`—
   nunca corrió. **Es el único eslabón sin verificar entre acá y cobrar.** Hoy
   hay 1 membresía (`vip`, `expired`/`kicked`, la del owner) y el plan vivo es
   `P-8TJ137481H7582421NJYMG5A` a 6.00 USD.
4. **Prender el publisher** (`PUBLISHER_ENABLED=true`), **después del backtest**,
   no solo después del 1-sep. Ver DEPLOY.md §10. Hoy la variable no está ni
   definida en `.env` y el daemon arranca con `enabled=False`, que es lo correcto.
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
