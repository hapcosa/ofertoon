# Handoff Ofertoon — estado al 2026-08-06

Pegá el bloque de abajo como primer mensaje de la próxima sesión.

---

Vengo a seguir con **Ofertoon** (antes OfertasCL), en `/mnt/datos/ofertoon`
(repo propio, **no** es signalsTrading). Rama `main`, git user `hapcosa`.

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

**F0, F1, F2 y F3 cerrados en código y desplegados.** Lo que falta es tiempo de
calendario, no trabajo: el detector no puede aceptar nada hasta que el catálogo
tenga 30 días de historia.

- **11.753 listings**, todos activos, 6 tiendas. Última pasada: 49 `ok`, 1
  `failed` — Easy refrigeradores, `HTTP 404` al pedir `?page=4` después de haber
  visto 119 items. Es paginar más allá de la última página, y la degradación por
  tienda hizo lo suyo: se perdió esa categoría, no la pasada. Vale revisar si el
  adaptador de Easy debería tratar el 404 de paginación como fin de resultados
  en vez de como error.
- **412 tests verdes** con `TEST_DATABASE_URL` seteada. La suite completa tarda
  **~40 minutos** — casi todo es el `TRUNCATE` de `price_points` y sus
  particiones en el fixture. No es un cuelgue; dejala correr.
- **Migraciones 01..14 aplicadas.**
- **5 commits en `main`**, el último `21af681`. **F3 entero está sin commitear**
  (working tree): `pricing/pipeline.py`, `curation/ranker.py`, `publisher/`,
  `migrations/14`, los tests nuevos y los cambios a `detector.py`,
  `runner.py`, `docker-compose.yml`, `telegram_client.py`.
- Servicios arriba: `postgres` (healthy), `scraper`, `bot`, `gate`,
  `paypal-webhook`, `publisher`, `cloudflared`.

Los tests que tocan DB piden `TEST_DATABASE_URL` apuntando a una base
**descartable** (el setup hace `DROP SCHEMA public CASCADE`). Sin la variable se
saltean y la suite igual queda verde — un "412 passed" sin ella no prueba lo que
creés:
```bash
cd /mnt/datos/ofertoon && set -a && . ./.env && set +a && \
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

**El cold-start es el estado correcto hoy.** Máximo 4 días calendario distintos
por listing contra los 30 que exige `baselines.py`, así que 0 baselines
publicables y 0 aceptados. El log del scraper lo dice:
```
pipeline: baselines[11753 listings, 11753 escritas, 0 con historia suficiente, 0 con rampa]
          detector[10674 evaluados, 0 aceptados (history=10672, out_of_stock=2)]
```
`deal_candidates` tiene 8 filas, todas `out_of_stock`. Los rechazos por
`history` no dejan fila (ver más abajo).

## Lo que sigue, en orden

1. **Commitear F3.** Está andando en producción y sigue sin trackear.
2. **Calibrar θ** (mediados de septiembre, con ≥45 días). El output de
   `pricing/backtest.py` **es** el gate: precisión ≥80% con ≥3 ofertas/día.
   Los θ de `categories.discount_threshold` son valores de partida del plan,
   **no** están calibrados.
3. **Probar el funnel con un pago real.** Lo verificado es el trial: PayPal creó
   la suscripción y mandó el `CREATED` con firma válida, pero nadie pagó, así que
   `PAYMENT.SALE.COMPLETED` —el evento que valida los 6.00 contra `price_usd`—
   nunca corrió. **Es el único eslabón sin verificar entre acá y cobrar.** Hoy
   hay 1 membresía (`vip`, `trialing`, la del owner) y el plan vivo es
   `P-8TJ137481H7582421NJYMG5A` a 6.00 USD.
4. **Prender el publisher** (`PUBLISHER_ENABLED=true`), **no antes de
   ~2026-09-02**. Ver DEPLOY.md §10.
5. **Verificar `in_stock` en la ficha** solo para el candidato (10–30
   fetches/día, no 2.898). Hoy Paris y Falabella lo asumen `True` y la guarda de
   stock es ciega. Quedó fuera de F3.
6. **F4 — lanzamiento**, **F5 — expansión**.

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
- **Conexión a la DB**: `psql` falla por autenticación. Lo que funciona:
  ```bash
  cd /mnt/datos/ofertoon && set -a && . ./.env && set +a && \
  export DATABASE_URL="${DATABASE_URL/@postgres:5432/@localhost:5436}" && \
  .venv/bin/python -c '...'   # asyncpg
  ```
  El `.env` trae el DSN de la red Docker (`@postgres:5432`); desde el host hay
  que reescribirlo a `@localhost:5436`.
- **Después de tocar el código hay que reconstruir el contenedor**
  (`docker compose up -d --build <svc>`): el Dockerfile copia las fuentes, no
  las monta, así que un cambio en el host no llega al servicio que está
  corriendo.
- **`data/postgres` es del uid 70** (postgres de alpine). NUNCA correrle
  `chown -R` con otro usuario: rompe la DB entera. Ya pasó una vez.
- **`docker build` falla sin `.dockerignore`**: `./data/postgres` es el bind
  mount de Postgres y es de root (`can't stat`). Ya está resuelto, no lo borres.
- **El gate expulsa gente de los canales y eso NO se deshace.** `GATE_ENABLED` y
  `telegram_tiers.gate_enabled` están **los dos en true** para `vip`; el
  efectivo es el AND. Hoy es inofensivo porque hay una sola membresía (la del
  owner, en trial), pero antes de tocar `telegram_memberships`,
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
cd /mnt/datos/ofertoon
docker compose ps                                    # postgres healthy + 6 servicios up
docker compose logs scraper | grep "pipeline:" | tail -3   # el job de pricing corrió
git status --short                                   # F3 sin commitear, es lo esperado
```
