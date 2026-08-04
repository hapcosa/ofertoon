# CLAUDE.md — OfertasCL

Contexto e instrucciones para agentes trabajando en este repo.
Si lo que vas a hacer no encaja con lo descrito acá, **preguntá antes de actuar**.

## Qué es OfertasCL

Canales VIP de Telegram con **ofertas reales** de retail chileno, por suscripción.

El diferenciador es esa palabra: **reales**. La estafa estándar del rubro es
inflar el precio semanas antes para después "descontarlo" contra el
`price_normal` que declara la tienda. Acá el descuento se mide contra lo que ese
SKU **costó de verdad las últimas 8 semanas**.

Eso convierte el proyecto en un problema de **series de precios**, no de
scraping. El scraping es la parte mecánica; el valor está en el detector.

Repo remoto: `hapcosa/ofertoon`. **No es signalsTrading** — ver §Aislamiento.

**Estado:** F0 (scraping) cerrado. F1 (identidad/baseline/detector) escrito,
falta calibrar θ (necesita ≥45 días de historia: mediados de septiembre 2026).
F2 (suscripciones, PayPal) y F3 (MercadoPago) con código completo y **sin
configurar externamente**. Falta el publisher (`curation/ranker.py`,
`publisher/*`, `daemon.py`).

Runbooks vivos: [`HANDOFF.md`](HANDOFF.md) (estado y traspaso de sesión),
[`DEPLOY.md`](DEPLOY.md) (puesta en producción),
[`HANDOFF_MERCADOPAGO.md`](HANDOFF_MERCADOPAGO.md).
El plan con las decisiones LOCKED vive fuera del repo, en
`~/.claude/plans/aprovechancho-el-sistema-de-toasty-squid.md`.

## Reglas de dominio que NO se pueden violar

Romperlas produce un sistema que publica ofertas falsas — que es exactamente el
producto que este proyecto existe para no ser.

1. **El descuento se mide contra la baseline propia, nunca contra el
   `price_normal` de la tienda.** Ese número es el que inflan. La señal es una
   sola línea: `discount_real = 1 − price_today / p50_60d`. Todo lo demás son
   guardas.
2. **Nada de look-ahead.** `pricing/backtest.py` hace replay día a día
   recomputando la baseline *como se veía el día t*. Por eso `compute_baseline`
   es **pura en Python, no SQL**: si el job diario usara un `percentile_cont` y
   el backtest otra cosa, habría dos implementaciones divergiendo y el backtest
   mentiría. No muevas esa lógica a SQL.
3. **Precios en CLP enteros.** Nunca `float` para dinero, en ninguna capa.
4. **Techo de plausibilidad `MAX_PLAUSIBLE_CLP = 100.000.000`**
   (`scrapers/base.py`). Falabella publica centinelas de $99.999.999.999 para
   productos sin precio real. Un valor así **envenena la baseline del SKU de
   forma permanente**. No es un precio: es un placeholder.
5. **Cold-start es un rechazo, no un default.** Sin `MIN_POINTS=30` y
   `MIN_DAYS=30` el p50 es una opinión. Un SKU nuevo cuyo precio de lanzamiento
   se "descuenta" a los 10 días no tiene contra qué contrastarse → `history`.
6. **Ante la duda, no se agrupa.** La identidad de producto
   (`catalog/identity.py`) es GTIN → (marca, modelo) → nada. No alimenta al
   detector: un match malo solo degrada el copy ("más barato que en Paris"),
   nunca la señal. Por eso se puede ser agresivo descartando. El fuzzy sobre
   nombres está **deliberadamente afuera**: solo agregaría los matches dudosos.
7. **Todo candidato se persiste con su motivo**, aceptado o rechazado. Ese
   dataset es lo que permite mover un umbral con evidencia en vez de a ojo.
   Los valores de `reject_reason` (`out_of_stock`, `history`, `ramp`,
   `threshold`, `above_floor`, `cooldown`) son `VARCHAR(32)` y **cambiarlos
   rompe la comparabilidad del histórico**. Única excepción:
   `detector.UNPERSISTED_REJECTS` (los ~10.800 rechazos por `history` por
   corrida, que no calibran nada).
8. **El gate se prende último y su default es apagado.** Gate efectivo =
   `AND(env GATE_ENABLED, telegram_tiers.gate_enabled)`. El env es el
   master-switch de seguridad; la columna es el control por-canal. Un gate
   encendido contra tiers mal configurados **expulsa gente de los canales, y eso
   no se deshace con un `git revert`**.
9. **El webhook y el bot solo escriben DB.** El efecto sobre Telegram (invite /
   kick) lo ejecuta únicamente `gate_daemon`, de forma idempotente y
   reintentable. Un fallo de Bot API no persiste `channel_state`.
10. **Sin ORMs.** SQL puro con asyncpg. Migraciones idempotentes numeradas.

## Aislamiento de signalsTrading

**signalsTrading corre en producción con dinero real. OfertasCL no lo toca.**

- No se modifica nada de `KryptoLab/`, `PySignalGenerator/`, `reconcile_daemon/`
  ni el Postgres `:5434`. De signalsTrading solo se **lee**, para portar.
- Lo portado (`subscriptions/gate.py`, `telegram_client.py`, `paypal/`) conserva
  la lógica **intacta** — cambia el logger y el nombre del env var, nada más. Es
  código que ya sobrevivió a fallos de Bot API, dobles réplicas y
  reactivaciones. Si tenés que corregir un bug de paridad con el original,
  decilo explícitamente en el PR.

## Stack

| Capa | Tecnología | Por qué |
|---|---|---|
| Lenguaje | Python 3.12 | |
| BD | PostgreSQL 16 (host `:5436`) | `price_points` particionada por mes |
| Acceso a datos | asyncpg, SQL puro | **Sin ORM** |
| HTTP scraping | httpx + selectolax | Parseo posicional, sin browser |
| Bot | aiogram 3 | |
| Pagos | PayPal (USD) + MercadoPago (CLP) | Un solo proceso de webhooks |
| Email | Resend | Verificación de trial |
| Contenedores | Docker Compose | Sin Kubernetes |
| Tests | pytest + pytest-asyncio | |
| CI | GitHub Actions (`.github/workflows/ci.yml`) | |

## Layout

```
scrapers/          Adaptadores por tienda + runner con canario
  stores/          Uno por tienda; todo lo específico vive acá
catalog/           Normalización e identidad de producto (GTIN / marca+modelo)
pricing/           baselines.py (p50/p10/min + rampa), detector.py, backtest.py
curation/          Ranker y cuota diaria por canal (F3, vacío)
publisher/         Publicación a los canales (F3, vacío)
subscriptions/     Bot de onboarding, gate, PayPal, MercadoPago, webhooks
migrations/        SQL idempotente numerado NN_
tests/             pytest + fixtures HTML/JSON de payloads reales
data/              Bind mount de Postgres — root-owned, en .gitignore
```

## Servicios (docker-compose.yml)

`postgres` · `db-migrate` (one-shot) · `scraper` (loop de 12h) · `bot` ·
`gate` · `webhooks` (PayPal + MercadoPago en un puerto, ruta por proveedor).

## Comandos

```bash
docker compose up -d postgres
docker compose run --rm db-migrate          # idempotente, re-correr es no-op
python migrate.py --status                  # lista pendientes sin tocar nada
docker compose up -d --build scraper        # OJO: el Dockerfile COPIA las fuentes
.venv/bin/python -m pytest -q               # sin TEST_DATABASE_URL saltea los de DB
python -m pricing.backtest --from AAAA-MM-DD --to AAAA-MM-DD --report
```

Los 54 tests que tocan DB piden `TEST_DATABASE_URL` apuntando a una base
**descartable**: el setup hace `DROP SCHEMA public CASCADE`. Nunca la apuntes a
la base de desarrollo.

## Agregar una tienda

Un módulo en `scrapers/stores/` que implemente `StoreAdapter` + un fixture en
`tests/fixtures/` con payload real + una fila en la tabla `stores`. **Nada más
se toca**: el runner, la persistencia y el detector solo conocen `RawProduct`.

## Migraciones

- Idempotentes (`IF NOT EXISTS` / `ON CONFLICT`), numeradas `NN_descripcion.sql`.
- Una por PR cuando se pueda.
- **Nunca editar una migración ya aplicada.** `migrate.py` guarda checksum y
  grita `checksum_mismatch`: lo que corrió en prod dejó de existir en el repo.
  Si hay que corregir, se escribe una migración nueva.

## Trampas conocidas — ya costaron tiempo

- **Conexión a la DB desde el host**: el `.env` trae el DSN de la red Docker
  (`@postgres:5432`); desde el host hay que reescribirlo a `@localhost:5436`.
  `psql` falla por autenticación; usá asyncpg.
- **Un HTTP 200 no significa que el adaptador funcione.** Easy hace UA-sniffing
  (200 + home), PC Factory acepta solo nombres en `categorias`, Paris ignora los
  parámetros de paginación del SSR (por eso el adaptador va contra el
  microservicio de catálogo), SP Digital devuelve `edges: []` con 200 si el id
  de categoría no existe. Eso es lo que el canario de `runner.py` vigila.
- **La API de Paris es 1-indexada**: `page=0` devuelve HTTP 500. Costó dos
  diagnósticos falsos de "anti-bot".
- **Paris solo trae EAN para los primeros ~60 productos** del ranking de cada
  categoría; el corte es por posición absoluta, no por página. El fixture es la
  página 1 y **engaña**. La cobertura se acumula sola entre pasadas porque el
  upsert usa `COALESCE`.
- **Falabella, Sodimac, Easy y PC Factory NO exponen GTIN ni modelo en el
  listado** (auditado contra payload real). Por eso solo ~875 de ~11.000
  listings tienen identidad. Habría que abrir fichas (F3).
- **SP Digital declara `Crawl-delay: 5`** en su `robots.txt` y el adaptador lo
  respeta con `rate_limit_rps = 0.2`. No lo subas sin releer el robots.
- **`docker build` falla sin `.dockerignore`**: `data/postgres` es el bind mount
  de Postgres y es de root (`can't stat`). Ya está resuelto — no lo borres.
- **Después de tocar el código hay que reconstruir el contenedor.** El
  Dockerfile copia las fuentes, no las monta: un cambio en el host no llega al
  scraper que ya está corriendo.
- **`in_stock` es ciego en Paris y Falabella**: hoy lo asumen `True`, así que la
  guarda de stock del detector no protege nada ahí. Se arregla en F3
  verificando la ficha solo del candidato (10–30 fetches/día, no 2.898).
- **Los θ de `categories.discount_threshold` NO están calibrados.** Son valores
  de partida del plan. El gate de F1 es el output de `pricing/backtest.py`:
  precisión ≥80% con ≥3 ofertas/día/canal.

## Convenciones

- **Idioma**: el agente responde siempre en **español**, directo y sin
  preámbulos. Docs y comentarios en español; identificadores en inglés salvo
  nombres del dominio.
- **Secretos**: `.env` está en `.gitignore` y nunca se commitea. `.env.example`
  documenta cada variable. Tokens de BotFather, PayPal, MercadoPago y Resend
  jamás en el repo ni en un log.
- **Comentarios**: solo donde el *por qué* no es evidente. El código de este
  repo documenta decisiones, no mecánica — mantené ese estándar.
- **Sin features especulativas.** No agregues abstracciones para necesidades
  hipotéticas.
- **Commits**: convencionales (`feat:`, `fix:`, `docs:`, `chore:`).
- **Avisá cualquier decisión que tomes por tu cuenta**, por chica que parezca.
  Honestidad 100%, cero condescendencia: si algo falla, decilo con el output.

## Qué NO hacer

- No publicar una oferta sin baseline con historia mínima.
- No prender el gate sin `telegram_channel_id` y planes cargados.
- No editar migraciones aplicadas.
- No commitear `.env`, tokens ni `data/`.
- No tocar signalsTrading desde acá.
- **No commitees ni pushees salvo que te lo pidan.**
