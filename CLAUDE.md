# CLAUDE.md — OfertasCL

Canales VIP de Telegram con **ofertas reales** de retail chileno, por suscripción.

El diferenciador es esa palabra: **reales**. La estafa estándar del rubro es
inflar el precio semanas antes para después "descontarlo" contra el
`price_normal` que declara la tienda. Acá el descuento se mide contra lo que ese
SKU **costó de verdad las últimas 8 semanas**. Eso convierte el proyecto en un
problema de **series de precios**, no de scraping: el scraping es la parte
mecánica, el valor está en el detector.

Repo remoto: `hapcosa/ofertoon`. **No es signalsTrading** — ver §Aislamiento.

---

## Este archivo es la puerta, no el manual

Lo que necesitás leer depende de lo que vas a hacer. **No leas todo.**

| Si vas a… | Leé |
|---|---|
| cualquier cosa | las §Reglas y §Pasos de acá abajo |
| conectar o investigar una tienda | §Pasos 1, §Investigación, [`PLAN_TIENDAS.md`](PLAN_TIENDAS.md) §5, y de [`TRAMPAS.md`](TRAMPAS.md) las secciones **A, B, C, D** |
| tocar el detector, θ o el backtest | §Pasos 2 y de [`TRAMPAS.md`](TRAMPAS.md) la sección **G** |
| tocar el publisher, cuotas o temas | §Pasos 2, §Estado y [`TRAMPAS.md`](TRAMPAS.md) **G** |
| aplicar migraciones o desplegar | §Pasos 3 y 4, [`DEPLOY.md`](DEPLOY.md) y [`TRAMPAS.md`](TRAMPAS.md) **F** |
| entender por qué una guarda existe | [`TRAMPAS.md`](TRAMPAS.md) **E** |
| expandir a verticales nuevas | [`PLAN_EXPANSION.md`](PLAN_EXPANSION.md) |
| supermercado y belleza | [`PLAN_SUPERMERCADO.md`](PLAN_SUPERMERCADO.md) |
| retomar una sesión | [`HANDOFF.md`](HANDOFF.md) · [`HANDOFF_MERCADOPAGO.md`](HANDOFF_MERCADOPAGO.md) |
| saber qué está LOCKED | `~/.claude/plans/aprovechancho-el-sistema-de-toasty-squid.md` — **fuera del repo** |

[`TRAMPAS.md`](TRAMPAS.md) son **67 trampas verificadas contra producción**,
agrupadas por situación. Cada una existe porque alguien ya probó el camino obvio
y perdió tiempo. Buscá tu sección, no leas el archivo.

**El "por qué" de cada decisión vive en el header de su migración**, no acá. Si
algo en la base te sorprende, `grep` en `migrations/`.

---

## Las reglas que no se pueden violar

Romperlas produce un sistema que publica ofertas falsas — que es exactamente el
producto que este proyecto existe para no ser.

1. **El descuento se mide contra la baseline propia, nunca contra el
   `price_normal` de la tienda.** Ese número es el que inflan. La señal es una
   sola línea: `discount_real = 1 − price_today / p50_60d`. Todo lo demás son
   guardas.
2. **Nada de look-ahead.** `pricing/backtest.py` hace replay día a día
   recomputando la baseline *como se veía el día t*. Por eso `compute_baseline`
   es **pura en Python, no SQL**: dos implementaciones del p50 divergirían y el
   backtest mentiría. No muevas esa lógica a SQL.
3. **Precios en CLP enteros.** Nunca `float` para dinero, en ninguna capa.
4. **Techo de plausibilidad `MAX_PLAUSIBLE_CLP = 100.000.000`**
   (`scrapers/base.py`). Falabella publica centinelas de $99.999.999.999: un
   valor así **envenena la baseline del SKU para siempre**. No es un precio, es
   un placeholder.
5. **Cold-start es un rechazo, no un default.** Sin `MIN_POINTS=30` y
   `MIN_DAYS=30` el p50 es una opinión. Un SKU nuevo cuyo precio de lanzamiento
   se "descuenta" a los 10 días no tiene contra qué contrastarse → `history`.
   ⚠️ **Excepción vigente y temporal**: `categories.min_history_days` (migración
   32) permite bajarlo por categoría y está en **10** para las siete conectadas en
   octubre, por decisión explícita del dueño. **Revertir con
   `UPDATE categories SET min_history_days = 30` el 2026-11-06.** Si leés esto
   después de esa fecha y la columna sigue en 10, es un olvido: el canal publica
   contra un p50 de dos semanas teniendo uno de ocho, que es **peor** que el
   estado de partida.
6. **Ante la duda, no se agrupa.** La identidad de producto
   (`catalog/identity.py`) es
   GTIN → (marca, modelo) → nada. No alimenta al detector, así que se puede ser
   agresivo descartando. El fuzzy sobre nombres está deliberadamente afuera.
7. **Todo candidato se persiste con su motivo**, aceptado o rechazado: ese
   dataset es lo que permite mover un umbral con evidencia en vez de a ojo. Los
   valores de `reject_reason` —`out_of_stock`, `history`, `ramp`, `threshold`,
   `above_floor`, `cooldown`— son `VARCHAR(32)` y **cambiarlos rompe la
   comparabilidad del histórico**. Única excepción:
   `detector.UNPERSISTED_REJECTS` (los ~10.800 rechazos por `history` por corrida,
   que no calibran nada).
8. **El gate se prende último y su default es apagado.** Gate efectivo =
   `AND(env GATE_ENABLED, telegram_tiers.gate_enabled)`. Un gate encendido contra
   tiers mal configurados **expulsa gente, y eso no se deshace con un git revert**.
9. **El webhook y el bot solo escriben DB.** El efecto sobre Telegram (invite /
   kick) lo ejecuta únicamente `gate_daemon`, idempotente y reintentable. Un fallo
   de Bot API no persiste `channel_state`.
10. **Sin ORMs.** SQL puro con asyncpg. Migraciones idempotentes numeradas.
11. **Nunca editar una migración ya aplicada.** `migrate.py` guarda checksum y
    grita `checksum_mismatch`. Si hay que corregir, se escribe una nueva.
12. **No commitees ni pushees salvo que te lo pidan.**

---

## Los pasos

### 1. Conectar una tienda

En este orden. Saltearse el 1 es el error más caro del repo.

1. **Investigar exhaustivamente** (§Investigación). Sin las doce respuestas no se
   escribe código.
2. **Elegir las llaves**: ¿catálogo o vitrina? ¿disjuntas sobre SKUs reales?
   → [`TRAMPAS.md`](TRAMPAS.md) **B**.
3. **Escribir el adaptador** en `scrapers/stores/` implementando `StoreAdapter`.
   **Nada más se toca**: el runner, la persistencia y el detector solo conocen
   `RawProduct`.
   Si la familia ya existe (`vtex_family`, `magento_html`, `shopify_family`,
   `woo_family`, `falabella_family`, `cencosud_family`), **no se escribe código**:
   solo la fila.
4. **Fixture con payload real** en `tests/fixtures/`, recortado, con un
   comentario que diga de qué URL salió, en qué fecha y qué se podó. Si la tienda
   tiene stock en el listado, **el fixture tiene que incluir productos agotados**:
   el camino feliz no ejercita la guarda.
5. **Tests de contrato.**
6. **Migración numerada** con la fila en `stores`, sus `store_categories`
   mapeadas a la taxonomía, la **fecha de conexión anotada** y la fecha de
   evaluación = conexión + 30 días. Categoría nueva → θ de partida explícito y
   anotado como **no calibrado**.
7. **Construir la imagen ANTES de migrar.** Si `stores.adapter` nombra un módulo
   que la imagen no tiene, `resolve_adapter` falla y las llaves quedan `failed`.
8. **Verificar el efecto, no el mensaje** (§Paso 4).
9. **Evaluar a los 30 días**, nunca antes:
   `python -m scripts.aceptacion_tienda --store <slug>`.

### 2. Tocar el detector, θ, el publisher o las cuotas

**Cómo llega una oferta a un tema**, que son tres tablas y conviene saberlo antes
de tocar nada: la categoría del listing se rutea a un tema por
`telegram_tier_categories.topic_id`; la cuota diaria es **de cada tema**
(`telegram_topics.daily_quota`), no del chat; y un tema sin `message_thread_id` no
es un destino. Los `message_thread_id` salen del link de un mensaje del tema
(`t.me/c/<chat>/<thread_id>/<message_id>`) — una migración no los puede inventar,
los tiene que leer el dueño. El por qué de cada número está en los headers de las
migraciones 26, 35 y 38.

- **θ sale del backtest, no del criterio.** El gate de F1 es
  `python -m pricing.backtest --from AAAA-MM-DD --to AAAA-MM-DD`: precisión ≥80%
  con ≥3 ofertas/día. Excluí los días degradados que el comando te avise
  (`--exclude-day`) o el volumen sale subestimado.
- **Una categoría solo se puede calibrar cuando tiene 30 días de serie + 30 de
  futuro para etiquetar.** Antes de eso, un 0 no significa nada.
- **Al mover una cuota hay que recalcular los topes finos**, o el limitante pasa
  a ser el tope: `categorías × MAX_PER_CATEGORY_PER_DAY ≥ cuota` y
  `tiendas_maduras × MAX_PER_STORE_PER_DAY ≥ cuota`.
- Un cambio de θ, de cuota o de umbral **es una decisión de producto**: se mide,
  se reporta y la toma el dueño.

### 3. Aplicar una migración

```bash
docker compose build db-migrate     # SIN esto, una migración nueva no está en la imagen
docker compose run --rm db-migrate
```

- **Aplicar siempre desde un checkout con la secuencia completa.** `migrate.py`
  aplica lo que su `glob` encuentre: no detecta huecos. Con migraciones
  repartidas en dos worktrees, correr desde uno **saltea las del otro en
  silencio**.
- `listo — 0 migración(es) aplicada(s)` es **a la vez** el mensaje de una corrida
  sana y el de "tu migración no está en esta imagen". Verificá la columna en la
  base.

### 4. Verificar: el efecto, nunca el mensaje

Es la regla que más veces se violó, y siempre por lo mismo: el mensaje de éxito y
el de "no hizo nada" son idénticos.

- **`--dry-run` NO ejercita el INSERT.** Reporta "N observaciones nuevas" sin
  tocar la base. Un adaptador nuevo se prueba con una corrida que **escriba** —
  contra `TEST_DATABASE_URL`, que es una base descartable — o mirando
  `scrape_runs.status` después de la primera pasada real.
- **`docker ps` puede decir `Up` de un contenedor VACÍO.** Verificá con
  `ps -eo etime,cmd | grep -E 'scrapers\.|publisher\.'` desde el host.
- **Una prueba sin caso de control es un falso verde.** Si verificás un límite,
  incluí el caso que *tiene* que fallar.

```bash
set -a && . ./.env && set +a && \
export TEST_DATABASE_URL="postgresql://ofertas:$POSTGRES_PASSWORD@localhost:5436/ofertas_test" && \
.venv/bin/python -m pytest -q
```

Sin `TEST_DATABASE_URL` saltea los 54 tests de DB y **parece verde**: no vale.
El setup hace `DROP SCHEMA public CASCADE` — nunca apuntarlo a la base real.

---

## La investigación es exhaustiva, y un veredicto viejo no es evidencia

**Este repo declaró cuatro tiendas inaccesibles y las cuatro eran accesibles.**
Medido el 2026-11-05 con los headers que el proyecto ya usa, sin navegador:

```
Unimarc     "bloqueada de verdad, 403 en todo, solo quedaría evasión"
            → catálogo Next.js paginado, 719 de 719 SKUs
PC Express  "403"  → era el host equivocado: tienda.pc-express.cl sirve todo
Imperial    "403 de Akamai, es bloqueo no caída"  → inestabilidad, no bloqueo
Ripley      "el hueco más grande, sin API pública"  → __NEXT_DATA__, 907/917
```

De ahí salen las reglas, y no son opinables:

1. **Probar la portada y el `robots.txt` de un dominio NO es investigar una
   tienda.** Hay que buscar subdominios de tienda, el sitemap, las fichas, la
   plataforma real y su API.
2. **Un 403 tiene fecha.** Un veredicto de hace dos semanas se vuelve a medir
   antes de citarlo. Lo mismo vale para cualquier medición: PLAN_SUPERMERCADO
   decía que Jumbo "no pagina" y paginaba.
3. **Distinguir bloqueo de inestabilidad.** Un 520 que vuelve al repetir la misma
   URL es un origen inestable y se trata distinto que un WAF.
4. **Identificar la plataforma de verdad antes de declarar roto un origen.**
   Tottus estuvo descartada semanas porque su API VTEX daba 503 — y Tottus no es
   VTEX.
5. **Que el `robots.txt` responda 200 no significa que el catálogo esté
   accesible** (Adidas), y un 403 en el robots no significa que la tienda esté
   cerrada (Ferretek).
6. **El límite sigue siendo el mismo**: con los headers del proyecto se llega
   hasta donde se llega. **Sin fingerprint de TLS y sin navegador headless.** Una
   tienda que de verdad no nos quiere, no nos tiene — y para esos casos lo que
   corresponde es pedir un feed o una API, no escalar.

Las doce preguntas que una investigación tiene que contestar antes de escribir
una línea están en [`PLAN_EXPANSION.md`](PLAN_EXPANSION.md) §1, cada una con la
trampa que la justifica.

### Los cinco estados de una tienda, que no son lo mismo

Los planes viejos los mezclan y por eso se contradicen entre sí. Al reportar,
decir en cuál está:

1. **investigada** — se midió, hay evidencia escrita
2. **fuente comprobada** — se recorrió el catálogo y se obtuvieron precios
3. **adaptador probado** — hay módulo, fixture y tests que pasan
4. **ingesta activa** — la migración está aplicada y hay `price_points` entrando
5. **catálogo completo** — todas sus llaves, no solo la tajada inicial

---

## Estado — 2026-11-05

| | |
|---|---|
| Tiendas activas / targets / categorías | 17 / 165 / 15 |
| Observaciones por pasada | ~59.000, dos pasadas diarias |
| Publisher y gate | **encendidos**, cero suscriptores activos |
| Destino | grupo-foro `-1003735174401`, **8 temas** cableados, cuota 33/día |
| θ | calibrados contra el backtest el 5-nov: el gate se cumple en 6 de las 7 categorías medibles |

**Decisiones del dueño abiertas** (ninguna la toma un agente):

- **`ferre-jardin` θ 0.250 → 0.200**: a 0.250 produce 1,7 ofertas/día contra el
  mínimo de 3 del gate. Es el único θ que el gate obliga a mover.
- **`min_history_days = 30`** — reversión de la excepción de la migración 32,
  **vence el 2026-11-06**. Si lo leés después de esa fecha y siguen 7 categorías
  en 10, es un olvido: el canal publica contra un p50 de dos semanas teniendo uno
  de ocho.
- **El tema `supermercado` tiene cuota 5 y una sola categoría ruteada**, así que
  `MAX_PER_CATEGORY_PER_DAY = 3` le deja **dos lugares inalcanzables**. Ya se
  materializó: el 5-nov publicó 3 de 5.
- **El ritmo del chat**: `MIN_MINUTES_BETWEEN = 30` es por destino, así que con 8
  temas el chat puede recibir hasta 13 mensajes/hora y agotar la cuota en ~2,5 h.
- **`UMBRAL_ESTABILIDAD = 0.40` manda apagar Falabella (8%) y Paris (15%)**, que
  son el 46% del canal. No está calibrado.
- **Nike da 30%**, pero medido el día en que madurar exige no faltar ni una vez:
  tiene 21% de sus listings a uno o dos días. Re-medir ~2026-11-10.

**Fechas que no se adelantan**: Jumbo y Santa Isabel se evalúan el **2026-12-04**;
`belleza` puede dar su primer candidato el **2026-12-04**; las siete categorías de
octubre se pueden calibrar ~**2026-12-05**.

---

## Aislamiento de signalsTrading

**signalsTrading corre en producción con dinero real. OfertasCL no lo toca.**
No se modifica nada de `KryptoLab/`, `PySignalGenerator/`, `reconcile_daemon/` ni
el Postgres `:5434`. Lo portado (`subscriptions/gate.py`, `telegram_client.py`,
`paypal/`) conserva la lógica **intacta** — cambia el logger y el nombre del env
var, nada más. Si tenés que corregir un bug de paridad con el original, decilo
explícitamente en el PR.

## Stack y layout

Python 3.12 · PostgreSQL 16 (host `:5436`, `price_points` particionada por mes) ·
asyncpg con SQL puro, **sin ORM** · httpx + selectolax, parseo posicional **sin
browser** · aiogram 3 · PayPal (USD) + MercadoPago (CLP) · Resend · Docker
Compose, sin Kubernetes · pytest + pytest-asyncio · GitHub Actions.

```
scrapers/          Adaptadores por tienda + runner con canario
  stores/          Uno por tienda; todo lo específico vive acá
catalog/           Normalización e identidad de producto (GTIN / marca+modelo)
pricing/           baselines.py, detector.py, backtest.py, pipeline.py
curation/          Ranker y cuota diaria por tema
publisher/         Publicación a los temas del grupo
subscriptions/     Bot de onboarding, gate, PayPal, MercadoPago, webhooks
scripts/           Diagnóstico: aceptacion_tienda, salud_serie, precios_tienda
migrations/        SQL idempotente numerado NN_
research/          Evidencia de investigación, por fecha
data/              Bind mount de Postgres — root-owned, en .gitignore
```

Servicios: `postgres` · `db-migrate` (one-shot) · `scraper` (loop de 12 h) ·
`bot` · `gate` · `webhooks`.

```bash
docker compose up -d postgres
python migrate.py --status                  # lista pendientes sin tocar nada
docker compose up -d --build scraper        # el Dockerfile COPIA las fuentes
python -m pricing.backtest --from AAAA-MM-DD --to AAAA-MM-DD
python -m scripts.aceptacion_tienda --store <slug>
python -m scripts.salud_serie
```

⚠️ **Conexión a la DB desde el host**: el `.env` trae el DSN de la red Docker
(`@postgres:5432`); desde el host hay que reescribirlo a `@localhost:5436`.
`psql` falla por autenticación — usá asyncpg.

## Convenciones

- **Idioma**: el agente responde siempre en **español**, directo y sin
  preámbulos. Docs y comentarios en español; identificadores en inglés salvo
  nombres del dominio.
- **Secretos**: `.env` está en `.gitignore` y nunca se commitea; `.env.example`
  documenta cada variable. Tokens de BotFather, PayPal, MercadoPago y Resend
  jamás en el repo ni en un log.
- **Migraciones** idempotentes (`IF NOT EXISTS` / `ON CONFLICT`), numeradas
  `NN_descripcion.sql`, una por PR cuando se pueda.
- **Comentarios**: solo donde el *por qué* no es evidente. El código de este repo
  documenta decisiones, no mecánica — mantené ese estándar.
- **Sin features especulativas.** No agregues abstracciones para necesidades
  hipotéticas.
- **Commits** convencionales (`feat:`, `fix:`, `docs:`).
- **Avisá cualquier decisión que tomes por tu cuenta**, por chica que parezca.
  Honestidad 100%, cero condescendencia: si algo falla, decilo con el output.
- **Varios agentes trabajan sobre este repo a la vez.** Antes de tomar un número
  de migración, mirá `migrations/` en **todos** los worktrees (`git worktree
  list`). Y no asumas que el árbol que ves es el que se desplegó.

## Qué NO hacer

- No publicar una oferta sin baseline con historia mínima.
- No prender el gate sin `telegram_channel_id` y planes cargados.
- No editar migraciones aplicadas.
- No commitear `.env`, tokens ni `data/`.
- No tocar signalsTrading desde acá.
- No declarar una tienda inaccesible sin haber hecho la investigación completa.

## Infraestructura

**Producción = `10.244.117.161`** (migrado el 2026-08-14). El host anterior
`10.244.19.205` (`traderbot`) es el entorno de **test**.

- El repo vive en `~/servicios/ofertoon`. Postgres usa el bind mount
  `./data/postgres` (root-owned, en `.gitignore`).
- Puerto host de Postgres: `${POSTGRES_HOST_PORT:-5436}`.
- El túnel Cloudflare (`sendtelegram.budaicapital.com` → `paypal-webhook:8080`)
  vive en `docker-compose.override.yml`, **fuera del repo**, detrás del profile
  `tunnel`: `docker compose --profile tunnel up -d cloudflared`.
- ⚠️ **Nunca correr dos `cloudflared` con el mismo token a la vez** — Cloudflare
  reparte el tráfico entre ambas máquinas.
