# Handoff OfertasCL — estado al 2026-08-03

Pegá el bloque de abajo como primer mensaje de la próxima sesión.

---

Vengo a seguir con **OfertasCL**, en `/home/obrero/programacion/ofertasCL`
(repo propio, **no** es signalsTrading). El plan aprobado está en
`/home/obrero/.claude/plans/aprovechancho-el-sistema-de-toasty-squid.md` — leelo
antes de tocar nada, ahí están las 4 decisiones LOCKED.

## Qué es

Canales VIP de Telegram con **ofertas reales** de retail chileno. El
diferenciador es que sean reales: nada de precios inflados semanas antes para
después "descontarlos". Eso convierte el proyecto en un problema de **series de
precios**, no de scraping — el scraping es la parte mecánica, el valor está en
el detector. Reusa la maquinaria de suscripción de signalsTrading (bot,
membresías, PayPal), pero con repo, Postgres (`:5436`) y marca separados.

## Reglas que aplican

- Respondé **siempre en español**, directo y sin preámbulo.
- signalsTrading corre en **producción con dinero real**. OfertasCL no lo toca:
  no se modifica nada de `KryptoLab/`, `PySignalGenerator/`, `reconcile_daemon/`
  ni el Postgres `:5434`. De signalsTrading solo se **lee** para portar.
- SQL puro con asyncpg, **sin ORMs**. Migraciones idempotentes numeradas.
- **Avisá cualquier decisión que tomes por tu cuenta**, por chica que parezca.
- Honestidad 100%, cero condescendencia. Si algo falla, decilo con el output.
- **No commitees ni pushees salvo que te lo pida.**

## Estado real (verificado, no supuesto)

**F0 cerrado**, **F1 escrito** (falta calibrar, que es tiempo de calendario) y
**F2 portado** (falta la configuración externa: BotFather, canales, PayPal).

**~11.000 listings**, 6 tiendas, la última pasada cerró **113 corridas, todas
`ok`**. **345 tests passed** (291 + 54 que necesitan `TEST_DATABASE_URL`). El
servicio `scraper` corre en Docker en loop de 12h. **F1 se puede calibrar desde
mediados de septiembre 2026** (≥45 días).

Los 54 tests que tocan DB piden `TEST_DATABASE_URL` apuntando a una base
**descartable** (el setup hace `DROP SCHEMA public CASCADE`). Sin la variable se
saltean y la suite igual queda verde:
```bash
export TEST_DATABASE_URL="postgresql://ofertas:$POSTGRES_PASSWORD@localhost:5436/ofertas_test"
.venv/bin/python -m pytest tests/ -q
```

**NADA ESTÁ COMMITEADO.** Un `git status` muestra un solo commit en `main`
(`2fbc556`) y todo lo demás sin trackear. Es lo esperado.

### Lo que se cerró el 2026-08-03

**Canario relativo + alerta** (punto 1 del handoff anterior):
- `scrapers/runner.py:canary_verdict()` — piso absoluto de 5 items **más** caída
  >40% contra la mediana de las últimas 7 corridas `ok` del mismo target. Con
  menos de 3 corridas de historia solo rige el piso.
- **Migración 08**: `scrape_runs.store_key`. Sin ella la mediana mezclaba
  targets incomparables — hay **11 pares (tienda, categoría) con más de una
  store_key**, y en SP Digital categoría 1 una devuelve 88 items y otra 7. Las
  158 corridas anteriores quedaron con `store_key` NULL y **no se pueden
  reparar hacia atrás**.
- `alerts.py` — resumen post-pasada de `failed`/`partial` por Telegram.
  **Silencio = todo verde**, a propósito. Sin `ALERT_BOT_TOKEN`/`ALERT_CHAT_ID`
  (hoy vacías) el resumen queda solo en el log.
- `subscriptions/telegram_client.py` — port de signalsTrading **sin tocar la
  lógica** (solo logger y nombre de la env var), para que F2 lo copie igual.
  Trajo `aiohttp` como dependencia nueva.

**F1 completo, código** (schema ya existía entero en `01_core.sql`):
- `catalog/identity.py` — `canonical_key` (GTIN → marca+modelo → nada) y
  `assign_products()`. Corrido contra datos reales: **875 listings vinculados,
  862 productos, 4 cross-store** — los mismos 4 matches Paris ↔ SP Digital que
  ya se habían visto a mano. El fuzzy sobre nombres se dejó **afuera** a
  propósito: solo agregaría los matches dudosos, que son los que rompen el copy.
- `pricing/baselines.py` — p50/p10/min sobre 60d con stock + `ramp_flag`. Toda
  la lógica es **pura en Python, no SQL**, porque el backtest necesita
  recomputar la baseline "como se veía el día t" y dos implementaciones
  divergirían. Corrido real: **10.798 baselines escritas, 0 publicables** (solo
  hay 3 días de historia — es lo esperado).
- `pricing/detector.py` — señal + guardas en orden: stock → historia → rampa →
  umbral → piso → cooldown. Corrido real: **10.796 rechazos por `history`,
  2 por `out_of_stock`, 0 aceptados**. Cold-start funcionando como debe.
- `pricing/backtest.py` — replay día a día **sin look-ahead**, etiquetado +30d
  (`real` = el precio vuelve a subir ≥10%; `fake` = escalón permanente;
  `unknown` = todavía no maduró) y curva precisión-volumen por θ. El CLI corre:
  `python -m pricing.backtest --from 2026-07-31 --to 2026-08-03 --report`.

**F2 — suscripciones portadas de signalsTrading** (código completo, sin config):
- **Migración 09**: `telegram_tiers`, `telegram_tier_plans`,
  `telegram_tier_categories`, `telegram_subscribers` (identidad),
  `telegram_memberships` (estado de cobro por tier), `telegram_email_verifications`.
  Consolida las 64/67/70/72/73 del fuente. **Migración 10**:
  `paypal_webhook_events`. **Migración 11**: seed de los dos canales.
- `subscriptions/bot/` — bot aiogram: menú de canales, trial con verificación de
  email, checkout PayPal, entrega de invites por DM, `/stats` para admins.
- `subscriptions/gate.py` + `gate_daemon.py` — reconciliador de canales.
  **Arranca inerte**: `GATE_ENABLED=false` y `telegram_tiers.gate_enabled=FALSE`
  (el efectivo es el AND de los dos).
- `subscriptions/paypal/` — cliente, aplicación de eventos y webhook firmado.
- Servicios `bot`, `gate` y `paypal-webhook` en `docker-compose.yml`.

**Lo que falta de F2 es configuración externa, no código:** crear el bot en
BotFather, los dos canales privados, cargar `telegram_tiers.telegram_channel_id`,
crear productos y planes en PayPal y cargar `telegram_tier_plans.paypal_plan_id`,
registrar la URL del webhook y guardar `PAYPAL_WEBHOOK_ID`. Recién ahí tiene
sentido el test end-to-end del funnel y prender el gate.

## Lo que sigue, en orden

1. **Calibrar θ** (mediados de septiembre, cuando haya ≥45 días). El comando ya
   está: el output de `pricing/backtest.py` **es** el gate de F1 — precisión
   ≥80% con ≥3 ofertas/día/canal. Los θ actuales en `categories.discount_threshold`
   son valores de partida del plan, **no** están calibrados.
2. **Configurar F2** (BotFather, canales, PayPal) y probar el funnel completo
   con el gate todavía apagado.
3. **F3 — publisher** (`curation/ranker.py`, `publisher/*`, `daemon.py`) +
   **verificar `in_stock` en la ficha** solo para el candidato (10–30
   fetches/día, no 2.898). Hoy Paris y Falabella lo asumen `True` y la guarda de
   stock es ciega.
4. **F4 — lanzamiento**, **F5 — expansión**.

## Decisiones tomadas que conviene no re-litigar

- **`daemon.py` no existe todavía** (es F3). F1 se corre a mano; no hay cron que
  ejecute identity/baselines/detector. **No hace falta**: el backtest reconstruye
  los candidatos históricos sin look-ahead a partir de `price_points`, así que
  no se pierde nada por no haberlos persistido día a día.
- **Los rechazos por `history` no se persisten** (`detector.UNPERSISTED_REJECTS`).
  Son ~10.800 filas por corrida (650k/mes) que no calibran nada; se cuentan en
  las stats. Todo rechazo que sí discrimina (rampa, umbral, piso, cooldown) se
  guarda entero.
- **La cuota diaria por canal no está en el detector** aunque el plan la liste
  entre las guardas: es curación (cuántos aceptados se publican), no detección
  (si esto es una oferta real). Va en `curation/ranker.py`, F3.

## Gotchas que ya costaron tiempo — no repetirlos

- **Conexión a la DB**: `psql` falla por autenticación. Lo que funciona:
  ```bash
  cd /home/obrero/programacion/ofertasCL && set -a && . ./.env && set +a && \
  export DATABASE_URL="${DATABASE_URL/@postgres:5432/@localhost:5436}" && \
  .venv/bin/python -c '...'   # asyncpg
  ```
  El `.env` trae el DSN de la red Docker (`@postgres:5432`); desde el host hay
  que reescribirlo a `@localhost:5436`.
- **La API de Paris es 1-indexada**: `page=0` devuelve HTTP 500. Costó dos
  diagnósticos falsos de "anti-bot".
- **Paris solo trae EAN para los primeros ~60 productos** del ranking de cada
  categoría (pág. 1 → 38/40; pág. 5 → 0/40; con `pageSize=100` → 62/100: el corte
  es por posición absoluta, no por página). El fixture es la página 1 y **engaña**.
  La cobertura se acumula sola entre pasadas porque el upsert usa `COALESCE` y el
  orden `relevance` rota.
- **Falabella, Sodimac, Easy y PC Factory NO exponen GTIN ni modelo en el
  listado** — auditado contra payload real. Por eso solo 875 de ~11.000 listings
  tienen identidad. Habría que abrir fichas (F3).
- **`docker build` falla sin `.dockerignore`**: `./data/postgres` es el bind
  mount de Postgres y es de root (`can't stat`). Ya está resuelto, no lo borres.
- **Silent degradation por tienda**: Easy hace UA-sniffing (HTTP 200 + home),
  PC Factory acepta solo nombres en `categorias`, Paris ignora los parámetros de
  paginación del SSR (por eso el adaptador va contra el microservicio de
  catálogo), SP Digital devuelve `edges: []` con HTTP 200 si el id de categoría
  no existe. Un HTTP 200 no significa que el adaptador funcione.
- **SP Digital declara `Crawl-delay: 5`** en su `robots.txt` y el adaptador lo
  respeta con `rate_limit_rps = 0.2`. No subirlo sin releer el robots.
- **Después de tocar el código hay que reconstruir el contenedor**
  (`docker compose up -d --build scraper`): el Dockerfile copia las fuentes, no
  las monta, así que un cambio en el host no llega al scraper que está corriendo.

## Verificación rápida al arrancar

```bash
cd /home/obrero/programacion/ofertasCL
.venv/bin/python -m pytest -q          # esperado: 199 passed
docker compose ps                       # postgres healthy + scraper up
git status --short                      # todo sin commitear, es lo esperado
```
