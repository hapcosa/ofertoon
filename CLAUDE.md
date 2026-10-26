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
falta calibrar θ (no antes del 2026-10-02: la baseline necesita 30 días y el
etiquetado del backtest otros 30 — ver HANDOFF.md).
F2 (suscripciones, PayPal) y F3 (MercadoPago) con código completo y **sin
configurar externamente**. El publisher (`curation/ranker.py`, `publisher/*`)
está desplegado y **encendido desde el 2026-09-21** (`PUBLISHER_ENABLED=true`),
adelantándose a propósito al backtest: publica contra los θ de partida, **sin
calibrar**. Es una prueba en vivo del canal, no el producto — las ofertas que salen
no pasaron el gate de precisión ≥80% porque ese gate todavía no se puede correr.
Decidido el 2026-10-19: mientras el canal no tenga usuarios, eso no bloquea.
La cuota pasó de 6 a 14 ese mismo día (con 6 y el tope de 2 por categoría solo
tres de las catorce categorías aparecían por día) y a **30 ofertas/día el
2026-10-21**, con espaciado de 30 min y ventana de 15 h (8-23). Los tres números
son el mismo: **15 h × 2 por hora = 30**, o sea la cuota quedó exactamente en el
techo físico. ⚠️ Eso cruza el umbral que el docstring del ranker llama "un feed
que el suscriptor mutea" — se tomó con el canal sin usuarios y es el primer número
a revisar cuando los haya.

**El destino pasa a ser (chat, tema).** Desde la migración 26 el canal es un
grupo-foro con siete temas —Tecnología, Hogar, Vestuario, Deporte, S.Mercado,
Ferretería, Viajes— y el tema lo elige la categoría del candidato
(`telegram_tier_categories.topic_id`). La cuota es **de cada tema**
(`telegram_topics.daily_quota`, 11/día en total) y no del canal, porque con un
techo global el tema con volumen se come los lugares de los demás: medido,
Tecnología produce ~8,8 señales/día contra ~1,5 de Ferretería. Un tema sin
`message_thread_id` no es un destino, y mientras ningún tema esté cableado el
poster publica al chat plano como antes — por eso la migración se pudo aplicar con
el publisher encendido. **Al 2026-10-01 los `message_thread_id` NO están
cableados**: salen del grupo ya creado y hay que leerlos del link de un mensaje de
cada tema.

Runbooks vivos: [`HANDOFF.md`](HANDOFF.md) (estado y traspaso de sesión),
[`DEPLOY.md`](DEPLOY.md) (puesta en producción),
[`HANDOFF_MERCADOPAGO.md`](HANDOFF_MERCADOPAGO.md).
Planes: [`PLAN_TIENDAS.md`](PLAN_TIENDAS.md) y
[`PLAN_SUPERMERCADO.md`](PLAN_SUPERMERCADO.md) — el supermercado va aparte porque
rompe dos supuestos del sistema (el rango de ticket y la unidad de compra), no
porque sea una fase más de conexión.
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
   ⚠️ **Excepción vigente y temporal**: `categories.min_history_days` (migración
   32) permite bajarlo por categoría, y desde el 2026-10-19 está en **10** para las
   siete conectadas en octubre, por decisión explícita del dueño del producto — el
   canal no tiene usuarios y se asumió publicar descuentos numéricamente falsos
   hasta que maduren. **Revertir con `UPDATE categories SET min_history_days = 30`
   el 2026-11-06.** Si estás leyendo esto después de esa fecha y la columna sigue
   en 10, es un olvido: el canal está publicando contra un p50 de dos semanas
   teniendo uno de ocho, que es peor que el estado de partida.
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

El checklist completo —incluido de dónde sale el `rate_limit_rps`, el engaño de
la página 1 en el fixture y la verificación de centinelas— está en
[`PLAN_TIENDAS.md`](PLAN_TIENDAS.md) §5. Tres cosas que no son obvias:

- **Anotar la fecha de conexión.** Una tienda nueva no publica nada durante 30
  días (`MIN_POINTS`/`MIN_DAYS` son un rechazo, no un default), así que se
  evalúa 30 días después de esa fecha, nunca antes.
- **El criterio de aceptación es una consulta, no una impresión**:
  `python -m scripts.aceptacion_tienda --store <slug>`. Mide, **sobre la cohorte
  de listings que tuvieron la oportunidad de madurar**, qué fracción llega a
  `MIN_DAYS`; por debajo del 40% la tienda rota demasiado catálogo y se apaga con
  `stores.is_active = false`. Esa espera de 30 días **es** el test de
  estabilidad: no hace falta estudiarla antes de conectarla. Medido
  transversalmente contra los listings vivos el número **miente**: mete a los
  SKUs recién llegados en el denominador y hace ver igual a la tienda que crece
  su catálogo y a la que lo rota (Easy: 34% transversal, 96% por cohorte).
- **Verificar cómo señala la tienda el final de la paginación.** No todas
  devuelven una lista vacía: Easy responde HTTP 404 y Falabella/Easy sirven la
  página sin el bloque de productos. Si el adaptador no lo distingue de un error
  real, el runner marca `failed` la categoría entera.

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
  listado** (auditado contra payload real). Habría que abrir fichas (F3).
- **La identidad ya corre, pero el copy cross-store todavía no existe.**
  `catalog/identity.assign_products()` estuvo escrita y **sin llamador** hasta el
  2026-09-28 (`products` en 0 con 3.216 `gtin_raw` guardados); ahora la invoca
  `pricing/pipeline.py`, última y aislada en su propio `try`, porque no alimenta
  al detector y un fallo suyo no puede costar la corrida de la señal. Lo que
  **sigue faltando** es el consumidor: `cross_store_prices()` no lo llama nadie y
  `publisher/formatter.py` solo produce "El más barato en 60 días", que sale de
  la historia propia del listing. O sea que poblar `products` es condición
  necesaria y no suficiente: **ninguna oferta dice todavía "más barato que en
  Paris"**.

  ⚠️ **Y no hay que escribir ese consumidor: está medido que daría cero mensajes.**
  El 2026-10-12, con `products` ya en 6.871 (de 3.357): solo **12 tienen 2+
  tiendas** (8 paris+spdigital, 4 ferretek+urban) y —lo que decide— de **10.484
  candidatos aceptados, CERO** tienen el mismo producto en otra tienda. Nike sumó
  2.554 products con EAN al 100% y no movió el número, porque nadie más vende Nike
  con GTIN en este catálogo.
  O sea el cuello de botella **no es el consumidor, es la cobertura de GTIN**: las
  tiendas que lo exponen (Paris parcial, SP Digital, Ferretek, Urban, Nike) casi no
  se solapan entre sí, y las grandes (Falabella, Sodimac, Tottus, Easy, PC Factory)
  no lo exponen en el listado. Para desbloquearlo hay que abrir fichas de esas
  grandes (~22.000 por pasada) o aflojar la identidad a (marca, modelo), que es
  justo lo que la regla 6 mantiene afuera. Hasta entonces, escribir el copy es
  trabajo con resultado medido en cero.
- **Una tienda repite el mismo GTIN en dos listings propios.** Paris publica el
  mismo SKU con `store_sku` numérico y alfanumérico (13 GTIN así; 13 en Ferretek,
  1 en SP Digital). Comparten `product_id`, que es correcto, pero por eso
  `cross_store_prices()` filtra `o.store_id <> l.store_id`: sin eso el copy diría
  "más barato que en Paris" sobre una oferta **de Paris**.
- **VTEX contesta `206 Partial Content` y eso NO es un error.** El rango que se
  pide con `_from`/`_to` es parcial respecto del total, así que 206 es la respuesta
  normal y completa. `http.SUCCESS_STATUS = {200, 206}` lo cubre; antes el primer
  fetch de cualquier tienda VTEX moría con `FetchError: HTTP 206`. Se listan los
  códigos uno por uno y no "todo 2xx" a propósito: un 204 sin cuerpo devolvería
  `""` y el parser lo leería como catálogo vacío, que es el fallo silencioso que
  `NotAListingPage` existe para evitar.
- **El total de una categoría VTEX viene en un HEADER, no en el cuerpo**:
  `Resources: 0-49/2546`. Es la fuente de `completeness()`, o sea del canario
  **exacto**, y para leerlo está `HttpClient.get_with_headers`. Si el header falta
  se devuelve `None` y el runner cae al canario estadístico: degradar a la guarda
  más débil es correcto, inventar un total no.
- **VTEX corta la paginación profunda en ~2.500** (`_from` más alto da error), así
  que **las llaves son las subcategorías, nunca la raíz**. En Nike la raíz declara
  2.389 y ya roza el tope. `vtex_family.MAX_OFFSET` lo documenta y el adaptador
  avisa (`categoria_mas_grande_que_el_tope`) cuando una llave no se puede enumerar
  completa.
- **En VTEX un producto tiene N items y los items son los talles.** Un zapato son
  ~10 items al mismo precio: emitir uno por talle multiplicaría los listings por 10
  con series idénticas. Se emite **uno por producto**, y el talle que da el precio
  es el **disponible más barato** —tomar el de un talle agotado publica un precio
  que nadie puede pagar—. `in_stock` mira todos los talles: el producto es
  comprable si alguno lo está.
- **Prat también bloquea por User-Agent, pero responde 429 y eso cuesta más
  caro.** Verificado el 2026-10-01 aislando la variable, 4 intentos de cada uno
  contra la misma URL: con `DEFAULT_USER_AGENT` da **HTTP 429 las 4 veces**, con
  `BROWSER_USER_AGENT` **HTTP 200 las 4 veces**. Los dos UA son idénticos salvo el
  sufijo `(+ofertascl-bot)`: lo que bloquea es ese token, no la tasa. **El 429 es
  la trampa**, porque parece un límite de tasa legítimo y la reacción natural
  —bajar `rate_limit_rps`— no lo arregla nunca. Costó tres pasadas completas
  (30-sep 15:36 → 1-oct 15:37, 6 corridas, las dos categorías, `FetchError:
  agotados 3 reintentos`) sin una sola observación de la tienda, justo cuando su
  reloj de `MIN_DAYS` había arrancado de cero con la migración 22. Regla general:
  **ante un 429 persistente, probar `BROWSER_USER_AGENT` ANTES de tocar el rps.**
- **Los `partial` de Andesgear por completitud son deriva de catálogo, no un bug
  del adaptador — y no hay que "arreglarlos".** Verificado el 2026-10-01 recorriendo
  `hombre/top` página por página: la tienda sirve **24 productos por página**,
  declara **22 páginas** (22×24 = 528 ≥ 518 declarados), y el recorrido dio 24 filas
  exactas por página, **cero duplicados y cero deriva**. El adaptador está bien. Los
  faltantes de 1 a 9 ítems aparecen cuando el catálogo se mueve mientras paginamos
  —el total se lee en la página 1 y no se vuelve a mirar, a propósito— y la ráfaga
  del 30-sep al 1-oct (10, 15 y 15 `partial` de 25) coincidió exactamente con la
  ventana en que los totales declarados crecían (`hombre/top` 502→518, `mujer/top`
  241→252). **Se resolvió sola**: la pasada del 1-oct 15:16 volvió a 2.
  ⚠️ No le pongas una tolerancia al chequeo exacto: la distribución medida sobre 50
  corridas es un **continuo de 0,771 a 0,998** (p50 0,976) sin hueco, así que
  cualquier umbral es inventado, y taparía el único caso informativo —
  `mujer/calzado` 162 de 210, que son **dos páginas enteras** perdidas—.
- **Ferretek bloquea por User-Agent.** El Varnish que tiene adelante responde
  `403 Empty UA blocked` a cualquier cosa que no parezca un navegador —el
  `robots.txt` incluido—, así que su adaptador manda `BROWSER_USER_AGENT`. Es el
  mismo caso que el UA-sniffing de Easy: un 403 acá no es anti-bot serio.
- **Las categorías de una tienda se solapan, y eso duplica observaciones.** Las
  vitrinas (`Ofertas`, `Outlet`, `Marcas`, `Despacho Gratis`) repiten los
  productos del catálogo, y las hojas suelen estar contenidas en su paraguas.
  Dos `store_key` solapados escriben dos `price_points` del mismo listing por
  pasada y lo hacen pesar el doble en su propio p50. Verificá que toda llave
  nueva sea disjunta **sobre SKUs reales** antes de meterla en la migración.
- **Una llave puede ser una vitrina curada a mano y no un catálogo — y cuando el
  comerciante la reedita, mata series sin avisar.** Prat cambió
  `herramientas-electricas` el 2026-09-25: de 345 items a 131, y **240 de los 246
  listings que dejó de mostrar seguían a la venta** (verificado contra las 39
  páginas de su `/products.json`). No fue rotación de catálogo ni un bug del
  adaptador. El tamiz que las separa es el stock: las colecciones que son
  catálogo vienen filtradas por disponibilidad (`jardin` y
  `herramientas-y-maquinarias` traen 100% con stock, el catálogo entero 71%), las
  vitrinas no (`herramientas-electricas`: 54%). Y **no asumas jerarquía**: esa
  vitrina tenía solo 71 de sus 131 SKUs dentro del paraguas homónimo. Ver la
  migración 22.
- **El canario se calla solo ante un cambio de nivel, en ~4 corridas.** Con
  `CANARY_WINDOW=7`, cuatro corridas al nivel nuevo vuelven la mediana el nivel
  nuevo y el verdict pasa a `ok`. Es deliberado —así sigue a un catálogo que
  cambia de verdad— pero significa que **el `partial` dura ~2 días y después no
  queda alarma**: si una tienda cae de nivel, el diagnóstico se hace en esa
  ventana o no se hace. Un `ok` posterior no dice que se haya resuelto.
- **SP Digital declara `Crawl-delay: 5`** en su `robots.txt` y el adaptador lo
  respeta con `rate_limit_rps = 0.2`. No lo subas sin releer el robots.
- **`docker build` falla sin `.dockerignore`**: `data/postgres` es el bind mount
  de Postgres y es de root (`can't stat`). Ya está resuelto — no lo borres.
- **Después de tocar el código hay que reconstruir el contenedor.** El
  Dockerfile copia las fuentes, no las monta: un cambio en el host no llega al
  scraper que ya está corriendo.
- **Eso vale también para `db-migrate`, y ahí el fallo es SILENCIOSO.** Una
  migración nueva no está en la imagen vieja, así que
  `docker compose run --rm db-migrate` contesta `listo — 0 migración(es)
  aplicada(s)` — que es **exactamente** lo que contesta una corrida idempotente
  sana, o sea el mensaje de éxito y el de "tu migración no existe acá" son el
  mismo. Pasó el 2026-10-26 con la 34. Es `docker compose build db-migrate`
  primero, o `--build` en el `run`; y verificar la columna en la base, no el
  mensaje.
- **`restart: unless-stopped` NO protege de un apagado manual, y eso ya costó
  dos agujeros.** Si los contenedores se detienen explícitamente (`docker compose
  stop/down`), Docker recuerda ese estado y **no los levanta** cuando el host
  reinicia. Pasó dos veces en octubre de 2026: el 12-oct (2 h, sin pérdida de
  pasadas) y del 13 al 19-oct, que dejó **cinco días sin una sola observación** para
  62.286 listings — el agujero más largo de la serie. La pista que lo delata es que
  signalsTrading, en el mismo host, vuelve entero: su política sí lo revive porque
  nunca fue detenido a mano. Verificar con `docker ps -a | grep oferta`: un
  `Exited (0)` de hace días con el host arriba es esto, no un crash.
  El daño no se recupera —la serie no tiene relleno hacia atrás— y corre las fechas
  de madurez: las siete categorías conectadas en octubre pasaron de madurar el
  31-oct a hacerlo entre el 30-oct y el 6-nov.
- **Docker puede reportar `Up` un contenedor VACÍO, y eso no lo ve ninguna guarda.**
  El 2026-10-21 el host reinició y dejó `ofertascl-scraper` y `ofertascl-publisher`
  en `Up 13 minutes` **sin un solo proceso adentro**: `docker ps` verde, cero líneas
  de log, `docker logs` y `docker exec` devolviendo vacío. El shim de containerd
  murió con el host y el daemon quedó sin forma de hablarle al contenedor; por eso
  `docker stop` y `docker rm -f` **cuelgan** sobre ellos y `compose up` falla con
  `Conflict. The container name is already in use`. Es peor que un `Exited`: un
  contenedor detenido se ve, y este miente.
  **Cómo verificarlo de verdad**: `ps -eo etime,cmd | grep -E 'scrapers\.|publisher\.'`
  desde el host. Si no aparece `python -m scrapers.runner`, el contenedor está vacío
  por más que `docker ps` diga `Up`.
  **Cómo se recuperó, en dos tiempos.** Para volver al aire sin tocar nada global:
  `compose up` deja contenedores nuevos en `Created` con nombre prefijado y se
  arrancan por ID con `docker start <id>`. Eso devuelve el servicio, pero **no
  alcanza**: el nombre canónico sigue tomado, así que ni `compose up` ni un script de
  deploy pueden recrear ese servicio nunca más — el `deploy-production.sh` de
  signalsTrading construyó sus 19 imágenes y murió en ese punto exacto.
  Lo único que lo arregla es `sudo systemctl restart docker`, y antes hay que matar
  los shims colgados (`ps -eo pid,cmd | grep containerd-shim`, cruzando el `-id` con
  el ID del contenedor). ⚠️ El reinicio del daemon relevanta los ~50 contenedores del
  host, signalsTrading incluido: **no se hace sin autorización explícita del dueño**.
  Dos cosas que ahorran dolor cuando se llega a ese punto:
  **`docker rename` funciona en caliente** — una vez muerto el fantasma, el
  reemplazo prefijado toma el nombre canónico sin cortar el servicio, y ahí el deploy
  vuelve a funcionar; y **al reiniciar el daemon pueden quedar dos instancias vivas
  del mismo servicio** (el fantasma revive de verdad junto a su reemplazo), que para
  el publisher sería cuota doble y para el scraper una observación duplicada que hace
  pesar el doble a un listing en su propio p50. Verificar siempre con
  `docker ps --format '{{.Label "com.docker.compose.project"}}/{{.Label "com.docker.compose.service"}}' | sort | uniq -c | awk '$1>1'`.
  En el mismo reinicio, `postgres` y `bot` quedaron en `Exited (137)` —el SIGKILL
  del apagado, no un OOM: `free` mostraba 13 GB libres y el kernel no registró
  ningún `oom-kill`— y `gate` y `paypal-webhook` en loop de reinicio con
  `socket.gaierror: Name or service not known`, que es simplemente que no estaba el
  Postgres al que resolverle el nombre: los dos se recuperaron solos al levantarlo.
  O sea el diagnóstico correcto fue de abajo hacia arriba — **el `gaierror` de un
  servicio no es un problema de red, es que el contenedor de la base no está**.
- **Una caída de red saliente silencia su propia alerta.** El aviso de
  `alerts.py` viaja por `api.telegram.org`: cuando el host pierde la salida,
  fallan todas las tiendas Y el mensaje que avisaría de eso. Pasó el 19-ago y
  otra vez del 18 al 20-sep de 2026 (48 h, 562 corridas `failed`, cero avisos,
  descubierto cinco días después). Por eso el agujero se detecta leyendo el
  Postgres **local** (`db.dias_sin_observaciones`) y se reporta en la primera
  pasada que vuelve a alcanzar Telegram, aunque esa pasada esté verde. Para
  mirarlo a mano: `python -m scripts.salud_serie`.
- **Las tres guardas son tres alturas distintas, y hubo un modo de falla que no
  veía ninguna.** El canario (`runner.canary_verdict`) mira un target contra su
  propia historia; el agujero (`db.dias_sin_observaciones`) mira días
  completamente vacíos; la guarda de volumen (`runner.pasadas_flacas`) mira la
  pasada entera contra la mediana de las últimas 7. La tercera se escribió el
  2026-09-29, después de que una pasada perdiera 62 de 129 objetivos y escribiera
  1.481 observaciones contra ~16.500 **sin una sola alerta**: el día no quedó
  vacío, los objetivos que nunca corrieron no dejaron fila que comparar, y el
  proceso murió dentro de `run_once` —antes de `run_pricing` y de `send_alert`—
  así que sus propios `outcomes` nunca llegaron al mensaje. Es el modo de falla
  "la pasada corrió a medias" y ya había pasado tres veces (19-ago, 18-20-sep,
  29-sep). Al escribirla se subió `GAP_LOOKBACK_DAYS` de 3 a 7 por la misma
  razón: con 3 días, una caída de viernes a la que se llega el lunes caía afuera
  de la ventana y no se reportaba nunca.
- **Una corrida manual no es una pasada, y ensuciaba la guarda de volumen.** Un
  `--once --store X` escribe filas separadas de la pasada anterior por más de
  `PASS_WINDOW`, así que `pasadas_flacas` las leía como una pasada entera que
  escribió muy poco: el 2026-10-01, 13 corridas de diagnóstico (9.476 obs, ratio
  0,57) se reportaron al lado del incidente real del 29-sep. Lo arregla
  `scrape_runs.is_partial_run` (migración 29), que el runner deriva de
  `bool(only_store or only_category)` y `volumen_por_pasada` excluye **en el
  `WHERE`, antes de agrupar** —filtrarlas después del `LAG` partiría en dos una
  pasada sana—. Es una columna y no un umbral a propósito: "13 de 152 no es una
  pasada" apunta al mismo lugar que la guarda vigila (el incidente que la justificó
  corrió 67 de 129 objetivos), así que cualquier vara así está a un cambio de
  catálogo de tapar el caso real.
- **La guarda de volumen suma `items_ok`, no `items_seen`.** Lo que vigila es
  cuánta serie ENTRÓ: un target que enumera 900 productos y no persiste ninguno
  es exactamente el agujero que hay que ver, y en `items_seen` no se nota. Dos
  cosas medidas que la hacen defendible: sobre las 113 pasadas del 4-ago al
  29-sep, la pasada sana más flaca quedó en 0,89 de su mediana móvil y los ocho
  incidentes reales entre 0,00 y 0,09 —entre 0,89 y 0,09 no hay nada, así que el
  umbral no es delicado—, y apagar la tienda más grande (`is_active = false` en
  Falabella, 25,3% del volumen) deja el ratio en 0,75, **sin disparar**. Hace
  falta apagar dos tiendas grandes a la vez para que avise, y eso merece un
  aviso. Lo que sí hereda del canario es el autoapagado: con la ventana entera en
  cero ya no hay vara, así que una racha larga deja de avisar a la quinta pasada
  —ahí la que cubre es la de agujero, que un día vacío no se autoanestesia—.
- **En Falabella, una llave puede devolver la página correcta con el contenido
  equivocado, y la guarda del adaptador NO lo ve.** `cat2049/Audifonos`,
  `cat1012/Audio` y `cat70028/Audio` devuelven HTTP 200, 60 productos y **pasan
  `NotAListingPage`** — pero el contenido es impresoras, soportes de TV y cámaras.
  La guarda detecta la página con la *forma* equivocada, no la que tiene forma
  correcta y *contenido* equivocado. Si una de esas entra en una migración, el
  sistema construye 30 días de serie de precios de impresoras bajo `tecno-audio`
  antes de que alguien lo note. El tamiz es **contar qué fracción de los nombres
  coincide con la categoría**: la llave buena da 99%, esas tres ~0%. Hacelo con
  tildes normalizadas — medir "Botines-Mujer" con el patrón `botin` dio 32% y era
  un bug del clasificador, no de la llave. La llave correcta sale de la navegación
  propia de la tienda (buscar el término y leer los `/category/catNNN/Nombre` que
  ella misma enlaza), no de adivinar el id. Ver migraciones 23 §5 y 24 §7.
- **`FalabellaAdapter` no deduplica entre categorías**, a diferencia del Magento de
  Andesgear (`dedupe_across_categories`). Por eso en Falabella el solapamiento
  entre llaves **no es inocuo** y hay que elegir: `cat2083/Zapatillas` es el
  paraguas de `Zapatillas-Hombre` y `Zapatillas-Mujer` (solapa 7% y 20%), y esas
  dos solapan 4% entre sí. Entra el paraguas, no las hojas.
- **El loop del scraper no corre una pasada al arrancar.** `espera_hasta_proxima`
  la ancla al arranque de la última pasada registrada, así un despliegue o un
  reinicio del daemon de Docker no meten una pasada extra. Si necesitás una
  pasada ya, es `--once` (o `--dry-run`), que la saltean a propósito. Ojo al
  tocar `db.ultima_pasada`: `scrape_runs` tiene una fila por (tienda, llave) y
  arrancan escalonadas ~13 min, así que el ancla es el `MIN(started_at)` del
  grupo. Un `MAX` devuelve el arranque de la última tienda y le suma esos
  minutos a cada ciclo — que es justo la deriva que el ancla elimina.
- **`product_list_limit` de Magento solo acepta los valores que el sitio ofrece.**
  Con `=96`, Kupfer responde **HTTP 200 y sirve 12 productos** —su default—: no
  clampea al máximo, ignora el parámetro. Por eso `magento_html.PAGE_SIZE` es 36
  (lo que lista su `<select id="limiter">`) y por eso subirlo a ojo reduciría el
  alcance a un cuarto sin un solo error.
- **Que una tienda de `magento_html` pagine o no lo decide su `robots.txt`.**
  Kupfer prohíbe `/*?p=`, así que trae cada categoría en **una** request y reporta
  lo que no entró vía `CountingAdapter` (`paginates = False`). Construmart no lo
  prohíbe, así que pagina con el tamaño por defecto —sin mandar
  `product_list_limit`, que roza su `Disallow: /*?limit=`— y corta en el
  `#am-page-count` que la tienda declara, sin probar nunca una página pasada del
  final.
- **Construmart cotiza por sucursal.** Cada sucursal es un `customer_group_id`;
  para un anónimo el HTML del listado no trae un solo `$` y todas las filas salen
  "Sin Stock" (su `products-render-info` contesta sin token pero devuelve
  `final_price: 0`). El adaptador manda la misma cookie que escribe su front,
  `persistent_customer_group_id=35` (DEPARTAMENTAL, Santiago). **Su serie es la de
  esa sucursal**: cambiar `ConstrumartAdapter.CUSTOMER_GROUP_ID` invalida el
  histórico entero de la tienda, porque el p50 de un SKU quedaría mezclando dos
  sucursales.
- **El total declarado de Magento es el ÚLTIMO número del `toolbar-amount`, no el
  primero.** Sparta escribe "Artículos 1-36 de 1080" en **tres**
  `span.toolbar-number`; quedarse con el primero daba 1 para una categoría de
  1.080 y —lo peor— no fallaba ruidosamente: `canary_verdict` solo marca `partial`
  cuando lo enumerado es MENOR que lo declarado, así que 36 contra 1 pasaba `ok` y
  la guarda exacta quedaba anulada en silencio.
- **Un `span.price-label` no es una señal de stock salvo que hable de stock.**
  Kupfer pone ahí "Disponible para compra online", pero Sparta pone "Precio
  habitual" como rótulo del precio tachado: leerlo como disponibilidad marcaba
  agotados justo a los 14 de 36 productos CON descuento, o sea a los únicos
  publicables. `_STOCK_WORDS` es el filtro.
- **Andesgear cross-lista el mismo SKU en varias categorías** (`montana-nieve/*`
  re-lista lo de `hombre/*`, `mujer/*` y `escalada/*`; el calzado unisex está en
  hombre y en mujer). Por eso su adaptador tiene `dedupe_across_categories`: el
  SKU se emite una vez por pasada y gana la primera llave del orden de
  `db.load_store_targets` —que por eso ordena también por `store_key`—. Es inocuo
  **solo porque los solapamientos medidos caen dentro de la misma categoría
  interna**; una llave que cruce dos categorías internas rompe el supuesto.
- **En Construmart, `items_seen` es bastante mayor que `items_ok`, y está bien.**
  Las filas "Sin Stock" de la sucursal vienen sin precio ni SKU: se enumeran
  (cuentan para el total declarado, que el canario compara) y no se emiten. De 302
  filas conectadas, ~217 traían precio.
- **`in_stock` sigue ciego en la INGESTA de Paris, Falabella, Sodimac y Tottus**
  —lo asumen `True`, así que la guarda del detector no protege nada ahí— pero desde
  el 2026-10-02 **el candidato se verifica en su ficha antes de publicar**
  (`publisher/stock.py`, migración 30). En Tottus el campo `availability` del
  LISTADO es una trampa: habla de modos de envío (`expressShipping`,
  `pickUpFromStoreShipping`), no de stock.
  Cuánto arreglaba, medido antes de construirlo: de los 40 candidatos aceptados más
  recientes de Falabella y Sodimac, **39 disponibles y 1 agotado (2,5%)**. Es un
  pulido de ~1 oferta cada cinco días, no un salto de precisión — no esperes ver el
  efecto en el backtest.
  **Paris queda afuera del verificador y no por falta de intentos** — buscado a
  fondo el 2026-10-12, para que nadie repita el camino: su ficha trae JSON-LD de
  Product **sin** `offers.availability`, no tiene `__NEXT_DATA__` ni
  `__APOLLO_STATE__`, y en 2 MB de HTML no aparece ni una vez `stock`, `agotado` ni
  `no disponible`. Su API de catálogo es **commercetools** y tampoco lo trae: las
  claves de producto, `masterVariant` y las 19 variantes son `assets, attributes,
  collections, ean, id, images, isMatchingVariant, key, prices, sellersSKU, sku` —
  cero inventario (`published` es flag de publicación, no de stock, como ya dice el
  adaptador). Filtrar esa API por `partNumber` o `sku` devuelve HTTP 500. Y el HTML
  de la ficha no menciona ningún host de API ni ruta de inventario: el front pide
  el stock desde sus bundles JS minificados. Perseguir eso es frágil y
  desproporcionado para una guarda que corrige el 2,5%.
- **`isOutOfStock` cambia de lugar entre fichas de la familia Falabella, y el
  agujero cae justo donde importa.** Está en `pageProps.isOutOfStock` en algunas
  fichas y en `pageProps.productData.isOutOfStock` en otras. Mirando solo la
  primera, 2 de 14 fichas reales quedaban sin señal **y las dos estaban agotadas**:
  las fichas que anidan el dato son justamente las que no traen `availability` en su
  JSON-LD, así que el fallback "no sé, publico" se activaba en el único caso que la
  guarda existe para atajar. Con las dos ubicaciones la cobertura es 100% sobre 18
  fichas frescas de las tres tiendas. Moraleja general: **un lector de ficha hay que
  probarlo contra fichas agotadas, no contra las que están a la venta** — el camino
  feliz no ejercita la guarda.
- **En la publicación, la duda no bloquea.** `publisher/stock.py` devuelve `None`
  ante una tienda sin lector, una ficha que no responde o un formato cambiado, y
  `None` publica: callar el canal es peor que una oferta agotada. Solo un `False`
  explícito frena. El resultado se persiste (`deal_candidates.stock_ok`) porque un
  candidato vive 13 h y el daemon despierta cada 300 s: sin eso serían ~150 fetches
  de la misma ficha contra un presupuesto diario de 10-30.
- **Un 503 de una API que la tienda NO USA no dice nada del origen.** Tottus
  estuvo descartada semanas como "el borde pasa, el origen falla" porque su API
  VTEX contesta 503 y sus rutas 526. Las dos cosas son ciertas y ninguna
  significaba eso: Tottus **no es VTEX**, corre la plataforma de Falabella
  (`__NEXT_DATA__`, 641 menciones de `falabella` en su home, cero de `vtex`), así
  que el 503 `no healthy upstream` era la respuesta a una ruta inexistente y el
  526 un `store_key` inventado (`/category/` en vez de `/lista/`). Antes de
  declarar roto un origen, **verificar qué plataforma usa la tienda de verdad**.
  Y el 200 de su home no probaba nada: venía con `cf-cache-status: HIT` y `age:
  2381`, o sea de la cache de Cloudflare y no del origen.
- **El orden por defecto de un listado puede ser inestable, y eso mata la serie
  en silencio.** Tottus ordena por `_score,desc` ("Recomendados"), un ranking de
  relevancia con boost de publicidad que cambia entre requests: paginarlo devuelve
  repetidos en el medio del catálogo y deja otros SKUs sin ver nunca. Medido sobre
  `Mascotas` (427 declarados): sin `sortBy` 435 filas → 389 únicos (0,911) y dos
  recorridos del mismo día dieron 326 y 389; con
  `sortBy=derived.currentPrice,asc`, 427 filas → 422 únicos (**0,988**). Lo que
  importa no es la cobertura por la cobertura: **un SKU que aparece de forma
  intermitente no acumula observaciones, nunca llega a `MIN_DAYS` y por lo tanto
  nunca produce una baseline**. Ante una cobertura que no cierra, mirar si la
  tienda ofrece un orden determinista antes de dar el faltante por perdido.
- **No se conectan categorías de precio estacional.** `Frutas-y-Verduras` y
  `Carnes` de Tottus quedaron afuera a propósito, y no por tamaño: el p50 de 60
  días de un tomate no es una baseline, es el promedio de dos temporadas
  distintas, y el detector marcaría "oferta real" cada vez que baja la
  estacionalidad. Es el mismo criterio que excluye los días degradados del
  backtest — mejor no medir que medir algo que no significa lo que dice.
- **Medir sobre la página 1 miente, y no solo para los GTIN de Paris.** La
  página 1 de un listado suele venir ordenada por promoción: en Tottus,
  `Aseo-y-Limpieza` declaraba descuento en el **79%** del catálogo mirando 48
  productos y en el **43%** mirando 192. Esa diferencia alcanzaba para concluir
  que había dos comportamientos de precio y crear dos categorías con θ distinto,
  cuando con 4 páginas por llave la distribución es una sola (p50 del descuento
  declarado 18-22% en las cinco). **Cualquier fracción medida sobre una sola
  página no sirve para decidir una categoría.**
- **Nike no declara `price_normal`, así que ahí θ no se puede fijar midiendo.**
  `con_dto = 0%` en las cuatro llaves medidas: su API nunca manda un "antes"
  tachado. El método de la migración 24 —"si un 30% es precio de lista de
  cualquier martes, θ va más arriba"— no se puede aplicar, y el θ de
  `ropa-accesorios` es herencia de sus vecinos, no una medición. Lateral bueno
  para el producto: en Nike no hay número de la tienda que inflar, el descuento
  sale entero de nuestra baseline.
- **El producto reacondicionado no es una oferta, y envenenaba la calibración.**
  Un reacondicionado baja de precio y **se queda abajo**: su precio sigue la
  depreciación y el grado del equipo, no una promoción, así que `label_outcome` lo
  marca `fake` con razón. Medido el 2026-10-12 sobre `tecno-celulares` corriendo el
  backtest real con y sin ellos: la precisión sube de 67,4% a 78,1% (θ 0.10) y de
  41,7% a 71,4% (θ 0.20), y **desaparece el patrón invertido** que tenía la
  categoría —un descuento más grande predecía peor—, porque entre los aceptados con
  ≥30% el **44%** eran reacondicionados contra el **8%** entre los de menos de 30%.
  Era además un problema de producto ya materializado: **8 de las 132 ofertas
  publicadas eran reacondicionados**. Lo rechaza `detector.REJECT_REFURBISHED` vía
  `catalog.normalize.es_segunda_mano`, que mira el nombre (ninguna tienda expone la
  condición en un campo aparte) con tildes normalizadas. Alcance: 46% del catálogo
  de celulares y 29% del de notebooks; ~0% en el resto.
- **`max_pages` recorta el catálogo en silencio, y en la familia Falabella estuvo
  recortando diez días.** Eran 20 páginas × 48 = 960 productos por llave, contra
  `cat2083/Zapatillas` que declara **18.412**. El canario estadístico no puede
  verlo: el volumen enumerado es estable corrida a corrida, así que 960 de 18.412
  se ve igual de sano que 960 de 1.000 comparado contra su propia historia. El daño
  es sobre la baseline y es proporcional al exceso — la ventana se reposiciona
  entre días, así que de los 3.363 SKUs que `ropa-calzado` vio el 2-oct solo **107
  (3%)** seguían en la ventana diez días después, con 2,1 días observados de 8.
  Ahora son 55 páginas (2.640) y hay un aviso explícito
  `catalogo_mas_grande_que_la_ventana`. Al subirlo, 19 de las 21 llaves activas de
  la familia entran completas; solo Zapatillas (384 págs) y Audífonos (177) exceden.
- **La familia Falabella NO puede sostener un canario exacto, y conviene no volver
  a intentarlo** — a diferencia de `vtex_family`, `magento_html`, `ferretek` y
  `spdigital`, que sí lo implementan. Lo probé el 2026-10-12: la tienda **repite productos cuanto más
  profundo se pagina**, así que lo enumerado nunca alcanza lo declarado y el gap es
  función de la profundidad (Lavadoras 5 págs → 100%; Refrigeradores 8 → 99,7%;
  Notebooks 26 → 84%; Almacenamiento 37 → 77%; Smartphones 43 → 83%). Con el
  canario exacto encendido quedaban **19 llaves en `partial` permanente**, una de
  ellas por UN producto de 352 — y una alarma que suena siempre es una alarma
  apagada. `completeness()` devuelve `None` a propósito y la medición está en su
  docstring. Lo que sí hacía falta era conocer el total, y para eso alcanza el log.
- **Al cambiar la cuota hay que recalcular los topes finos, o el limitante pasa a
  ser el tope.** `MAX_PER_STORE_PER_DAY` y `MAX_PER_CATEGORY_PER_DAY` acotan cuánto
  se lleva una tienda o una categoría por día, y si quedan bajos cortan antes que
  la cuota — que es justo lo que un tope no tiene que decidir. Pasó dos veces en
  tres días: al subir la cuota a 14, seis tiendas maduras × tope 2 daban un techo
  real de 12; al subirla a 30, 6 × 3 = 18 y 14 categorías × 2 = 28, las dos por
  debajo. La cuenta es `tiendas_con_baseline_madura × tope ≥ cuota` y
  `categorías × tope ≥ cuota`. Hoy: 6 tiendas × 5 = 30 y 14 categorías × 3 = 42.
- **El canal publica hardware de servidor si no se lo frena.** El 2026-10-20 salieron
  dos discos HPE de $5.989.990 y $7.789.990 que se llevaron **2 de los 14 lugares
  del día**. Lo rechaza `detector.REJECT_SERVER_HW` vía
  `catalog.normalize.es_hardware_servidor`, y **no es un techo de precio** a
  propósito: un televisor de 85" cuesta $1,9M y es consumo legítimo (14 aceptados en
  esa semana). Lo que descalifica al disco es qué es, no cuánto vale — también se
  filtra una memoria ECC de servidor de $16.990.
  Son 14 listings de los 847 de PC Factory (1,7%) y **no hay una llave que
  desactivar**: vienen mezclados en `Discos Internos SSD` y `Memorias PC`, que son
  llaves legítimas. Sobre el histórico, el filtro rechaza 5 de 11.485 aceptados
  (0,04%).
  ⚠️ Dos patrones que parecían obvios quedaron AFUERA porque filtraban consumo, y
  están en el docstring para que no vuelvan: **`rack`** atrapaba el "Nike Squat
  Rack" de $449.990 y un "Rack Para Lavadora", y **`SFF`/`BC`** atrapaban una
  "Torta Red Velvet Bc" de Tottus de $4.590.
- **El `pum` (precio por unidad de medida) cuelga de UNA entrada de `prices`, no
  del producto.** Cada entrada trae el suyo, así que `resolve_prices` devuelve el
  de la entrada que ganó el precio efectivo: el del `normalPrice` tachado es el
  precio por kilo de un precio que ya no existe y el del `cmrPrice` es el de un
  precio que exige tarjeta de la casa. Se persiste desde la migración 34
  (`price_points.pum_price` + `pum_label`, las dos juntas o ninguna) y es **copy,
  no señal**: `discount_real` sigue saliendo solo de `1 − price_today / p50_60d`.
  El "antes real" por unidad del mensaje se **deriva** del p50
  (`p50 × pum_hoy / price_hoy`) y no tiene baseline propia — una segunda serie con
  su propio p50 sería la implementación divergente que la regla 2 prohíbe. Y la
  etiqueta va verbatim: `10GR` y `100UN` no son errores, son la base que elige la
  tienda, y dos `pum` de bases distintas no se comparan sin normalizar.
- **Los θ de `categories.discount_threshold` NO están calibrados.** Son valores
  de partida del plan. El gate de F1 es el output de `pricing/backtest.py`:
  precisión ≥80% con ≥3 ofertas/día/canal.
- **La liquidación de temporada es una oferta y va al canal** (decidido el
  2026-10-01, PLAN_TIENDAS §1.3). El detector nunca la rechazó: `detect_ramp`
  exige un alza sostenida (≥15% sobre el p50 por ≥5 días entre d−21 y d−3) ANTES
  de la baja, y una liquidación baja sin haber subido, así que `ramp_flag` queda
  en False y se acepta. Lo que estaba mal era la **medición**: `label_outcome`
  marcaba `fake` todo pozo que se queda abajo, y como θ sale del backtest, eso
  empujaba θ hacia arriba hasta dejar afuera justo las mejores ofertas de
  vestuario y calzado. La corrección es `LABEL_LIQUIDATION`, y el discriminante
  mira el pasado: `price < piso de 60 días` es liquidación (precio nunca visto),
  `price >= piso` es el inflado volviendo a un nivel que ya existía. Cuenta como
  acierto en `precision` y lleva columna propia en el reporte, con aviso cuando
  pasa la mitad de los aciertos — un canal cuya precisión es toda liquidación es
  un outlet, no un canal de ofertas.
- **El 89% de lo que el backtest llama `fake` NO es un precio inflado, y eso hace
  que la precisión medida subestime al detector.** `label_outcome` usa "¿el precio
  volvió a subir?" como proxy de "¿era una oferta real?", y ese proxy falla en toda
  categoría con tendencia descendente de precio — o sea en toda la tecnología.
  Clasificados los 19 `fake` de las 7 categorías con datos, a sus θ vigentes
  (2026-10-12), según la forma del futuro de la señal:

        SIGUE_BAJO    13 (68%)   el precio bajó TODAVÍA MÁS después de la señal
        PLANO          4 (21%)   se quedó exactamente en el precio publicado
        REBOTA_POCO    2 (10%)   subió algo, sin llegar al umbral de recuperación

  Los dos primeros no son fallas: si se publica a $99.990 un producto cuyo p50 era
  $134.990 y después baja a $79.990, **la oferta fue real** —el descuento existía y
  quien compró obtuvo un precio genuino—; que siga bajando no la vuelve falsa, la
  vuelve "no era el fondo". `PLANO` es un cambio de precio de lista, tampoco un
  inflado. En `tecno-celulares` el 75% de los `fake` son `SIGUE_BAJO`, que es la
  misma raíz del caso reacondicionado pero más general: los productos de tecnología
  bajan de precio por ciclo de producto, no por promoción.
  Es exactamente el mecanismo que motivó `LABEL_LIQUIDATION` (§1.3), un nivel más
  abajo: el discriminante del piso solo rescata los que bajan a un precio **nunca
  visto**, así que uno que baja a un nivel donde ya había estado queda `fake`
  aunque después siga bajando.
  ⚠️ **No se tocó el etiquetado**, y a propósito: son 19 muestras. El Cyber Monday
  del 5-7 de octubre aportó ~1.000 señales/día y se puede etiquetar desde el 5 de
  noviembre — recién ahí hay evidencia para decidir si `SIGUE_BAJO` cuenta como
  acierto, y mover el gate con 19 casos sería calibrar a ojo.
- **El "patrón invertido" de `ferre-jardin` NO existe: es ruido de muestra chica.**
  La precisión que cae de 76,5% a 50% y 0% al subir θ está construida sobre **6 a
  14 señales etiquetadas** (a θ 0.25 son 3 `real` y 3 `fake`). No confundirlo con
  `tecno-celulares`, donde el mecanismo sí quedó demostrado por los
  reacondicionados. Mirar los tres `fake` de jardín igual sirvió: son motosierras
  y cortadoras que bajaron de nivel y se quedaron, lo que llevó al hallazgo de
  arriba.
- **El piso de la liquidación se calcula hasta AYER, no con `min_60d`.**
  `backtest.piso_previo` corta en el comienzo del día a propósito: la pasada de la
  mañana ya trae el precio nuevo, así que el `min_60d` de la baseline con la que
  el detector acepta (que es la historia hasta la observación de la tarde) ya
  incluye la bajada, y `price < min_60d` **nunca se cumple**. Con eso, una
  liquidación de libro quedaba etiquetada `fake` igual que antes y la etiqueta
  nueva no servía para nada. Mirar menos datos no es look-ahead: es la versión
  conservadora.
- **Hay días que no se pueden replayear como días de mercado**
  (`backtest.DIAS_DEGRADADOS`, `--exclude-day`). El 18 y 19 de septiembre de 2026
  no tuvieron una sola observación; el 29 tuvo 19.361 puntos contra ~33.000. El
  daño no está donde parece: `replay_listing` ya salteaba los días sin
  observaciones, así que no emitían señales — pero sí contaban en el **divisor**
  de señales/día, que es la mitad del gate de F1. El numerador pierde las señales
  y el denominador igual cuenta el día: sobre 30 días con los tres adentro, el
  volumen sale 10% abajo. No se excluyen solos (cambiar el divisor del gate en
  silencio sería peor), pero el comando avisa si el rango los toca. Los días
  excluidos **siguen alimentando la baseline**: borrarles puntos sería la segunda
  implementación divergente que la regla de no-look-ahead prohíbe.

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

## Infraestructura: dónde corre esto

**Producción = `10.244.117.161`** (migrado el 2026-08-14). El host anterior
`10.244.19.205` (`traderbot`) pasó a ser el entorno de **test**, donde se montan
los cambios antes de subirlos.

- El repo vive en `~/servicios/ofertoon`. Postgres usa el bind mount
  `./data/postgres` (root-owned, en `.gitignore`).
- Puerto host de Postgres: `${POSTGRES_HOST_PORT:-5436}`.
- El túnel Cloudflare (`sendtelegram.budaicapital.com` → `paypal-webhook:8080`)
  vive en `docker-compose.override.yml`, **fuera del repo**, detrás del profile
  `tunnel`. Un `docker compose up -d` normal no lo levanta:
  `docker compose --profile tunnel up -d cloudflared`.
- ⚠️ **Nunca correr dos `cloudflared` con el mismo token a la vez** — Cloudflare
  ve dos conectores y reparte el tráfico entre ambas máquinas.
