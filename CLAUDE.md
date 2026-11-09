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
| trabajar en paralelo con otro agente | §Trabajo multi-agente — **antes de crear el worktree**, no después |
| expandir a verticales nuevas | [`PLAN_EXPANSION.md`](PLAN_EXPANSION.md) |
| supermercado y belleza | [`PLAN_SUPERMERCADO.md`](PLAN_SUPERMERCADO.md) |
| retomar una sesión | [`HANDOFF.md`](HANDOFF.md) · [`HANDOFF_MERCADOPAGO.md`](HANDOFF_MERCADOPAGO.md) |
| saber qué está LOCKED | `~/.claude/plans/aprovechancho-el-sistema-de-toasty-squid.md` — **fuera del repo** |

[`TRAMPAS.md`](TRAMPAS.md) son **85 trampas verificadas contra producción**,
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
   El piso efectivo lo pone `categories.min_history_days` (migración 32) y desde
   la **migración 53 es 10 en las 17 categorías**. Pasó por 20 en la 48 y antes
   por una excepción de 10 en siete categorías (la 32), así que si un documento
   te dice otro número, mirá la columna.
   ⚠️ **Los 10 días son una concesión explícita de período de prueba, no el
   criterio del producto.** Decisión del dueño del 2026-11-07: el servicio no se
   ofrece a nadie todavía —cero suscriptores activos—, así que lo que el canal
   publica es material de observación, y las series maduran solas sin que nadie
   toque nada. El costo está medido en el header de la 53: con el piso en 10,
   entre 5 y 11 publicaciones por día se miden contra un p50 de unas 20
   observaciones. **Es la primera migración a revertir el día que el canal se
   ofrezca**, y la reversión es una línea:
   `UPDATE categories SET min_history_days = 20;`
   ⚠️ Eso dejó un **desfase permanente con el backtest**, que sigue midiendo con
   30: `replay_listing` llama a `evaluate` sin `min_history_days` y cae en el
   `MIN_DAYS` de `baselines.py`. O sea **el θ que sale del backtest describe un
   detector que no es el que corre**. Era un desfase temporal por diseño —la
   migración 32 contaba con que la columna volviera a 30— y con los 20
   permanentes ese supuesto se cayó. Todavía no tiene consecuencia medible: en el
   rango medible las categorías afectadas ni aparecen, porque no tienen 30 días de
   futuro para etiquetar. El cambio, con su costo declarado, está en
   `research/2026-11-06/BACKTEST_theta.md` — no lo toques sin leerlo.
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
13. **Un agente, una rama, un worktree.** Nunca dos agentes sobre el mismo
    árbol. Ver §Trabajo multi-agente: no es una convención de orden, es que las
    tres formas de pisarse que ya ocurrieron **no fallan ruidosamente**.

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
   La fila nace con **`publish_enabled = FALSE`** y la columna queda **afuera del
   `ON CONFLICT DO UPDATE`**. El default es `TRUE`, así que una tienda nueva
   publica salvo que diga lo contrario — y con el piso de historia en 20 días
   acumula baseline diez días antes de su propia evaluación: la fecha del header
   no se hace cumplir sola. Ingesta desde el día uno, canal recién cuando el dueño
   la abra a mano después de la aceptación. Ver [`TRAMPAS.md`](TRAMPAS.md) **G**.
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
  Desde la **migración 55** (2026-11-07) los tres números son **20**: cuota de
  cada tema, tope por tienda y tope por categoría. Así la cuota decide sola y el
  techo del canal son **8 temas × 20 = 160/día**. ⚠️ El precio es que **una sola
  tienda o categoría puede llenar un tema**: se aceptó a propósito con el canal
  sin suscriptores, y es el primer número a revisar cuando los haya. Bajar
  cualquiera de los dos topes por debajo de la cuota devuelve la variedad, y hay
  un test que falla si alguien lo hace sin querer.
  **Y la mitad de ese cambio es código**, así que mover una cuota puede necesitar
  rebuild del publisher: los topes viven en `curation/ranker.py`, la cuota en la
  base.
- Un cambio de θ, de cuota o de umbral **es una decisión de producto**: se mide,
  se reporta y la toma el dueño.

### 3. Aplicar una migración

```bash
docker compose build db-migrate     # SIN esto, una migración nueva no está en la imagen
docker compose run --rm db-migrate
```

- ⚠️ **`docker compose up` de `scraper` o `publisher` también aplica
  migraciones**: las dos declaran `depends_on: db-migrate`. Así que el `build` no
  es un paso previo al `run db-migrate`, es previo a **cualquier** `up` — recrear
  con una imagen vieja aplica el juego de migraciones de esa imagen en silencio.
  Y un `0 aplicadas` después de un `up` puede significar "ya se aplicó recién".
  Ver [`TRAMPAS.md`](TRAMPAS.md) **F**.
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
- 🔴 **Después de un despliegue que reinicie el scraper, disparar la pasada a
  mano**: `docker compose exec scraper python -m scrapers.runner --once`. Sin eso
  el runner duerme hasta que toque el ciclo de 12 h, el pipeline no corre —viaja
  dentro del loop—, los candidatos vencen a las 13 h y **el canal se queda mudo
  hasta que termine la pasada siguiente, sin un solo error**. Medido el
  2026-11-06: cero publicaciones durante 6 h 18 min de ventana (primer post
  17:18 UTC contra las 11:00 de todos los días), y 23 en vez de 25 porque la
  pasada alcanzó a cerrar con 8 h de ventana por delante. **Si el reinicio cae de
  modo que la pasada termine después del cierre, el día entero es cero.**
  Ver [`TRAMPAS.md`](TRAMPAS.md) **F**.
- **Hay filas que ningún test puede ver.** El `_truncate_state` del conftest
  preserva solo `categories`, `stores` y `schema_migrations`, así que las
  `store_categories` que inserta una migración **no están** cuando corre el
  primer test: una suite en verde no dice nada sobre si las llaves de una tienda
  nueva quedaron bien mapeadas. Se miran en la base, o se aplica la secuencia
  completa sobre una base descartable propia y se mira ahí.

```bash
set -a && . ./.env && set +a && \
export TEST_DATABASE_URL="postgresql://ofertas:$POSTGRES_PASSWORD@localhost:5436/ofertas_test" && \
.venv/bin/python -m pytest -q
```

Sin `TEST_DATABASE_URL` saltea los 54 tests de DB y **parece verde**: no vale.
El setup hace `DROP SCHEMA public CASCADE` — nunca apuntarlo a la base real.

---

## Trabajo multi-agente: cómo no pisarse

Varios agentes trabajan este repo a la vez. Las cinco colisiones de abajo **ya
pasaron**, y ninguna falló ruidosamente: en todos los casos el trabajo se perdió,
se corrompió o quedó sin poder desplegarse sin un solo error en pantalla.

```bash
cd ~/servicios/ofertoon
git worktree add ../ofertoon-<tema> -b feat/<tema>
cd ../ofertoon-<tema>
```

### 1. Antes de crear un worktree, commiteá

**Un worktree nace del último COMMIT, no del árbol de trabajo.** Si hay trabajo
sin commitear, el worktree nuevo **no lo ve** — y el agente que lo use va a
reescribir lo que ya existe creyendo que no existe.

Pasó el 4-nov: el adaptador de Cencosud y las migraciones 36-39 estaban sin
commitear, y un worktree creado en ese momento habría numerado su primera
migración como 36.

```bash
ls migrations/ | tail -3      # ¿están las últimas?
git log --oneline -1          # ¿las incluye el último commit?
```

### 2. Reservá el número de migración ANTES de escribirla

**Dos agentes escribieron una `40_` el mismo día** (una de Ripley/Hites, otra de
WooCommerce) y las dos quedaron sin commitear en árboles distintos, así que
ninguno vio la del otro. Dos migraciones con el mismo número son un
`checksum_mismatch` en cuanto una se aplica — y arreglarlo después obliga a
renumerar y a corregir todas las referencias cruzadas de los headers.

El número libre **no es** `ls migrations/ | tail -1` de tu árbol: es el mayor de
**todas** las ramas.

```bash
git fetch --all 2>/dev/null
git branch -a --format='%(refname:short)' | while read r; do
  git ls-tree --name-only "$r" migrations/ 2>/dev/null
done | sed 's|.*/||' | grep -oE '^[0-9]+' | sort -n | tail -1
```

(El `sed` no es adorno: `git ls-tree` devuelve `migrations/46_...`, así que sin
él el `grep` anclado en `^` no matchea nada y el comando contesta **vacío** — que
se lee igual que "no hay migraciones" y te deja escribir la 40 otra vez.)

### 3. Un cambio no se parte entre dos árboles

Si el código va en una rama y su migración en otra, los tests pasan en las dos y
el sistema está roto en las dos. Pasó en esta sesión: el código de la promoción de
multicompra quedó en `main` y su migración 46 en el worktree.

**Una unidad de trabajo —adaptador + fixture + tests + migración— vive entera en
un solo árbol.**

### 4. Los recursos compartidos no están aislados

El worktree comparte **el Postgres `:5436` y el proyecto Docker** con producción,
que está encendida.

- 🔴 **Nunca `docker compose run db-migrate` desde un worktree.** Escribe en la
  base real, y además aplica solo las migraciones que *su* `glob` encuentra: con
  la secuencia repartida en dos árboles, **saltea las del otro en silencio** (ver
  §Paso 3). Las migraciones se **escriben** en la rama; aplicarlas es una acción
  del dueño, desde un checkout con la secuencia completa.
- 🔴 **Nunca reiniciar el scraper ni el publisher desde un worktree.** Matás una
  pasada a medias, que es el modo de falla que `runner.pasadas_flacas` vigila.
- ⚠️ **Las bases descartables de prueba necesitan nombre propio por rama**
  (`ofertas_test_<tema>`). Dos agentes con el mismo nombre se borran la base
  mutuamente a mitad de una corrida, y el síntoma es un test que falla por una
  tabla que "no existe".
- ⚠️ **No pegarle a la misma tienda desde dos procesos.** El `RateLimiter` es por
  proceso, así que dos agentes a 0,33 rps le pegan a 0,66 y la tienda contesta
  429. Perdí dos corridas de Lippi así, y encima me llevó a bajar el rps
  persiguiendo un fantasma: el 429 era por headers.

### 5. Dos ramas pueden ser interdependientes A TRAVÉS DE LA BASE

Y entonces **ninguna de las dos se puede desplegar sola**, aunque no compartan un
solo archivo. Pasó el 2026-11-06: aplicar la migración de Unimarc sin su código
deja sus 8 llaves en `failed` cada pasada, y desplegar su código sin el del otro
agente rompe `pc-express`, que **ya está en la base** apuntando a un módulo que
esa rama no tiene. Las suites de los dos árboles pasan en verde.

La salida es integrar primero y desplegar una vez: merge → **una** build → **una**
aplicación. Y el merge **se verifica**, no se asume — se puede simular sin tocar
el árbol del otro agente ni su trabajo sin commitear, con un `GIT_INDEX_FILE`
temporal y `git merge-tree`. El cómo está en [`TRAMPAS.md`](TRAMPAS.md) **F**.

### 6. Al terminar

Commiteá en tu rama, mergeá a `main` y **recién entonces** borrá el worktree
(`git worktree remove`). Un worktree abandonado con trabajo sin commitear es
trabajo que el próximo agente no va a encontrar.

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

## Estado — 2026-11-06

Todo lo de esta tabla está **medido contra la base**, no heredado de un
documento. Si vas a citarlo mañana, volvé a medirlo: lo que más veces se
desactualizó de este archivo es justo esta sección.

| | |
|---|---|
| Tiendas activas / llaves / categorías | **31** / **727** activas (730 filas, 3 desactivadas) / **17** |
| Tiendas que publican | **29** — `ripley` y `pc-express` con `publish_enabled=false`; `unimarc` entra igual cuando se aplique la 47 |
| Listings activos | 135.880 |
| Observaciones por pasada | **~73.000** (pasada del 5-nov 17:00 al 6-nov 04:00 UTC: 727 corridas, 606 `ok`, 115 `partial`, 6 `failed`) |
| Migraciones aplicadas | **47: 01-46 y 48 — falta la 47**, que está escrita en `feat/unimarc` y sin aplicar |
| Historia mínima | **20 días en las 17 categorías** (migración 48, aplicada el 6-nov 13:52 UTC) |
| Publisher y gate | **encendidos**, 7 servicios `running`, cero suscriptores activos (1 membresía `expired`) |
| Destino | grupo-foro `-1003735174401`, **8 temas** cableados, cuota 33/día |
| θ | re-medidos el 6-nov: el gate se cumple en **2 de las 7** categorías medibles, y el limitante es el volumen |

**El piso de 20 días ya corrió, medido el 2026-11-07.** Tres corridas del
detector con él puesto: 349 aceptados (6-nov 17:13), 332 (7-nov madrugada) y 249
(7-nov tarde). De los 249 de la última, **23 vienen de la cohorte de 20-29 días
de historia** y 226 de 30 o más — o sea el piso aporta un 9% de los aceptados.
En lo publicado: **4 de 23 posts el 6-nov y 4 de 22 el 7-nov** salen de esa
cohorte.

⚠️ **Pero esos números no significan lo que parecen, y la cuenta que importa es
otra.** `listing_baselines.n_days` se sobreescribe en cada corrida y cuenta días
dentro de los últimos 60, así que **se mueve** — leerlo hoy no dice con cuánta
historia se detectó una oferta de anteayer. La forma correcta es recomputarlo
desde `price_points`, que guarda la serie cruda: días distintos **con stock** en
los 60 previos a `detected_at`. Hecho así, lo que se ve es que la 48 **apretó**
el piso (ver la §Corrección de `research/2026-11-06/BACKTEST_theta.md`), no que
lo aflojó.
**La regla que dejó**: el estado anterior de una columna derivada no se deduce
del código ni se lee en la columna de hoy — se mide en lo que el sistema ya
produjo. `price_points` y `deal_posts` lo tienen escrito.

**Decisiones del dueño abiertas** (ninguna la toma un agente):

- **Los θ.** Tabla medida en `research/2026-11-06/BACKTEST_theta.md` (rango
  2026-08-15 → 2026-10-07, 51 días de mercado). Solo 7 de las 17 categorías son
  medibles; **la precisión va de 90% a 97% contra el 80% que pide el gate**, y lo
  que falta son las 3 ofertas/día: 5 categorías no llegan. O sea hay margen para
  bajar θ sin romper la promesa del canal, que es lo contrario de lo que sugiere
  la intuición. `ferre-jardin` es el caso extremo: 1,2 ofertas/día a θ 0.250.
- **Abrir Unimarc al canal** después de su aceptación del **2026-12-06**:
  `UPDATE stores SET publish_enabled = TRUE WHERE slug = 'unimarc'`. Lo mismo
  para `ripley` y `pc-express` cuando les toque.
- **El desfase 20/30 entre producción y backtest** (regla 5). Permanente desde
  la 48, sin consecuencia medible hasta ~diciembre, y con el cambio y su costo ya
  escritos.
- **El tema `supermercado` tiene cuota 5 y una sola categoría ruteada**, así que
  `MAX_PER_CATEGORY_PER_DAY = 3` le deja **dos lugares inalcanzables**. Ya se
  materializó: el 5-nov publicó 3 de 5.
  ⚠️ Y medido el 6-nov simulando la curación entera, **no es un caso aislado: se
  publican 25 de los 33 de cuota**. Los 8 que faltan son 3 de `belleza` (su primer
  candidato posible es el 2026-12-04), 2 de `supermercado`, 2 de `ropa` por el
  mismo tope de 3, y 1 de `viajes-tours`. No los limita el detector: los limitan
  los topes finos y las categorías sin candidatos maduros. Ver
  `research/2026-11-06/BACKTEST_theta.md`.
- ~~**El piso de 20 días no agrega ofertas publicadas: desplaza un tercio del
  canal.**~~ **Falso, corregido el 2026-11-07 y ya no es una decisión abierta.**
  Ese análisis comparó 20 contra 30, y **el 30 existió unas horas sin producir un
  solo post**: el contrafáctico real era **10**, el que la migración 32 había
  dejado en siete categorías. Medido en lo publicado, con la historia que cada
  oferta tenía al detectarse: hasta el 5-nov el canal publicaba contra baselines
  de **10 u 11 días** (5 a 11 posts diarios por debajo de 21), y desde el 48 el
  mínimo es 20 y la cola corta desaparece — la fracción medida contra menos de 30
  días cae de **44-56% a 23-30%**. **La 48 fue un apriete, no un aflojamiento.**
  Detalle en `research/2026-11-06/BACKTEST_theta.md` §Corrección.
- **El ritmo del chat**: `MIN_MINUTES_BETWEEN = 30` es por destino, así que con 8
  temas el chat puede recibir hasta 13 mensajes/hora y agotar la cuota en ~2,5 h.
- **`UMBRAL_ESTABILIDAD = 0.40` manda apagar Falabella (8%) y Paris (15%)**, que
  son el 46% del canal. No está calibrado.
- **Nike da 30%**, pero medido el día en que madurar exige no faltar ni una vez:
  tiene 21% de sus listings a uno o dos días. Re-medir ~2026-11-10.

**Fechas que no se adelantan**: Unimarc se evalúa el **2026-12-06**; Jumbo y
Santa Isabel el **2026-12-04**; `belleza` puede dar su primer candidato el
**2026-12-04**; las siete categorías de octubre se pueden calibrar ~**2026-12-05**.

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
