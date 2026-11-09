# HANDOFF_MERCADOPAGO.md — activar MercadoPago como segundo proveedor

Escrito el 2026-11-07, rama `feat/mercadopago` (commit `b1bc552`), para que el
dueño pueda activar MercadoPago sin abrir el código. Si volvés a esto en varias
semanas, revalidá los números (θ, cuotas, estado de servicios) contra la base:
este documento describe el **mecanismo**, no el estado del canal en una fecha.

> ✅ **Runbook verificado contra producción el 2026-11-07**, porque un runbook
> con un dato mal se ejecuta con dinero real. Lo que se comprobó, y no se dedujo:
>
> | paso | comprobación | resultado |
> |---|---|---|
> | §2.3, §2.8 | `docker compose exec postgres psql -U ofertas -d ofertas` | **funciona**. Ojo: CLAUDE.md advierte que «`psql` falla por autenticación», y eso vale **desde el host** —donde el DSN apunta a `@postgres:5432`—, no dentro del contenedor. Este runbook usa la ruta que sí anda |
> | §2.3 | a cuántas filas apunta el `WHERE` del `UPDATE` | **exactamente 1** (`id=2`, `monthly`, USD 6,00) |
> | §2.6 | `POST /webhook/paypal` contra el contenedor vivo | **401 Unauthorized**, como dice el paso |
> | §2.6 | `POST /webhook/mercadopago` hoy, antes del deploy | **404** — o sea la prueba discrimina: ese 404 es el «antes». ⚠️ **Corregido el 2026-11-09**: el «después» NO es 401 sino **503**, porque sin `MERCADOPAGO_*` el endpoint existe pero se niega a aceptar eventos que no puede verificar. 401 recién aparece con el secreto cargado (§2.6) |
> | §2.8 | columnas `event_type`, `processing_status`, `processing_error`, `received_at` y los cuatro estados del CHECK | **existen en la 51**, los nombres del runbook son correctos |
> | §2.8 | `telegram_memberships.payment_provider`, `channel_state`, `status` | **existen en producción** |
>
> Lo único **no** verificable sin credenciales es el ida y vuelta real con
> MercadoPago (§2.1, §2.2, §2.7): eso recién se puede probar cuando el dueño
> cargue el token.

## 1. Qué está hecho y qué falta

**Hecho y probado** (936 tests el 2026-11-07; **1.012 el 2026-11-09**, 0 fallos
en 18 min contra `ofertas_test_mercadopago`, con `main` mergeada —hasta la
migración 54 y `salesforce_family`—, la guarda del §5 y los cinco tests nuevos
de la firma del §4 adentro):

- Cliente de MercadoPago Suscripciones (`subscriptions/mercadopago/client.py`):
  crea la *preapproval* (equivalente a una suscripción de PayPal) y valida que
  el `init_point` que devuelve MercadoPago sea un dominio real de MercadoPago,
  no uno inventado.
- Aplicación idempotente de eventos (`subscriptions/mercadopago/events.py`): a
  diferencia de PayPal, la notificación de MercadoPago **no trae el recurso**,
  solo un id — así que siempre se busca el recurso autoritativo en la API antes
  de decidir nada. Mismo modelo de estados que PayPal sobre
  `telegram_memberships` (reutiliza `status`/`channel_state`; el gate no
  distingue de qué proveedor viene un pago).
- Webhook con verificación de firma local (`subscriptions/mercadopago/webhook.py`)
  y un entrypoint combinado (`subscriptions/webhooks.py`) que sirve
  `/webhook/paypal` y `/webhook/mercadopago` **en el mismo proceso y puerto**
  que ya usa `paypal-webhook` — a propósito, para no pedirte un segundo
  hostname en el túnel Cloudflare.
- Bot: paso nuevo "¿cómo querés pagar?" cuando un plan tiene los dos
  proveedores cargados; si tiene uno solo, lo salta (igual que ya hace con el
  período).
- Migración 51: columnas `price_clp` (INTEGER, `CHECK > 0` — nunca float para
  CLP) y `mercadopago_plan_id` en `telegram_tier_plans`; `mercadopago_*` en
  `telegram_memberships`; tabla `mercadopago_webhook_events`.

**Falta, y es todo configuración externa, no código** — la sección 2 es
exactamente esto, en orden:

1. Credenciales reales de MercadoPago.
2. Un plan de suscripción (`preapproval_plan`) creado en MercadoPago.
3. Cargar ese plan y su precio CLP en la base.
4. ~~Aplicar la migración 51~~ — **hecho el 2026-11-09**, ver el box de §2.
5. ~~Reconstruir y recrear el servicio del webhook~~ — **hecho el 2026-11-09**.
6. Registrar la URL de notificación en MercadoPago.
7. Verificar en la base, no en el log.

Y desde el 2026-11-09 hay una pieza más en este repo que no es de MercadoPago
pero sí de este agente: **la guarda del canal mudo**, escrita, probada y
apagada. Su interruptor está en §5.

## 2. Runbook de activación

> ### 🔄 Estado del runbook al 2026-11-09 — **los pasos 2.4 y 2.5 ya están hechos**
>
> El despliegue conjunto de las seis migraciones pendientes (47, 50, 51, 52, 53
> y 55) se aplicó hoy a las **~04:53 UTC**, con una sola build y una sola
> aplicación, tal como pedía §2.4. Medido contra la base y contra el contenedor,
> no leído de un log:
>
> | paso | estado | evidencia medida el 2026-11-09 |
> |---|---|---|
> | 2.1 credenciales | ⬜ **pendiente** | ninguna variable `MERCADOPAGO_*` cargada; `/webhook/mercadopago` contesta **503 "not configured"** |
> | 2.2 crear el plan | ⬜ **pendiente** | — |
> | 2.3 cargar plan y `price_clp` | ⬜ **pendiente** | `telegram_tier_plans` id 2 (vip/monthly): `price_clp = NULL`, `mercadopago_plan_id = NULL` |
> | 2.4 aplicar la migración | ✅ **hecho** | `schema_migrations` tiene 53 filas, `51_mercadopago_suscripciones.sql` entre ellas |
> | 2.5 recrear el webhook | ✅ **hecho** | contenedor creado 04:53:08 UTC con `Cmd = ["python","-m","subscriptions.webhooks"]` |
> | 2.6 caso de control | ✅ **corrido hoy, pasa** | ver el paso: `/webhook/paypal` → **401**, o sea la ruta que cobra sigue viva |
> | 2.7 registrar la URL | ⬜ **pendiente** | — |
> | 2.8 verificar un pago | ⬜ **pendiente** | `mercadopago_webhook_events` existe y está vacía; la 51 dejó `price_clp`/`mercadopago_plan_id` en `telegram_tier_plans` y las cuatro `mercadopago_*` en `telegram_memberships` |
> | §2.3, re-verificado | ✅ | el `WHERE` del `UPDATE` sigue apuntando a **exactamente 1 fila** (`id=2`, `monthly`, USD 6,00, activa). Lo midió el 7-nov y lo volví a medir hoy después del despliegue: un veredicto tiene fecha |
>
> **O sea: el runbook arranca en 2.1 y sigue en 2.2, 2.3, 2.7 y 2.8.** Los pasos
> 2.4 y 2.5 quedan escritos porque documentan qué se hizo y cómo verificarlo, no
> porque haya algo que ejecutar.


### 2.1 Credenciales

En el panel de MercadoPago ([mercadopago.cl/developers](https://www.mercadopago.cl/developers)),
con la cuenta real del negocio:

1. Crear una aplicación → copiar el **Access Token**. Empieza con `TEST-` en
   modo prueba o `APP_USR-` en producción; el cliente (`client.py`) no fuerza
   uno sobre otro, así que probar primero con `TEST-` es seguro.
2. En **Tus integraciones → Webhooks**, configurar un secreto de firma (lo
   genera el panel). Sin esto el webhook de MercadoPago contesta `503` a todo
   — no acepta eventos que no puede verificar, igual que PayPal sin
   `PAYPAL_WEBHOOK_ID`.
3. Cargar en `.env`:

   ```
   MERCADOPAGO_ACCESS_TOKEN=TEST-xxxxxxxx-xxxxxxxx-xxxxxxxx-xxxxxxxx-xxxxxxxx
   MERCADOPAGO_WEBHOOK_SECRET=<el secreto del paso 2>
   ONBOARDING_MERCADOPAGO_RETURN_URL=https://t.me/<ONBOARDING_BOT_USERNAME>?start=mercadopago_approved
   ```

   La tercera es opcional: si se deja vacía, el bot cae al `ONBOARDING_PAYPAL_RETURN_URL`
   si existe, o a un deep-link al bot armado solo con `ONBOARDING_BOT_USERNAME`.

### 2.2 Crear el plan (preapproval_plan)

Es el equivalente de crear un plan de suscripción en PayPal. Se hace con una
request a la API (no hay botón en el panel para esto todavía):

```bash
curl -X POST https://api.mercadopago.com/preapproval_plan \
  -H "Authorization: Bearer $MERCADOPAGO_ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "reason": "Ofertoon VIP",
    "auto_recurring": {
      "frequency": 1,
      "frequency_type": "months",
      "transaction_amount": 6000,
      "currency_id": "CLP"
    },
    "back_url": "https://t.me/<ONBOARDING_BOT_USERNAME>?start=mercadopago_approved"
  }'
```

`transaction_amount: 6000` es un valor de ejemplo, **no una recomendación**: el
plan mensual actual cobra USD 6,00 por PayPal, y cuánto cobrar en CLP es una
decisión de precio, no algo que este documento puede fijar por vos (tipo de
cambio, redondeo comercial, paridad real con lo que paga un suscriptor chileno
por tarjeta). Elegilo y seguí; `client.get_monthly_plan` rechaza cualquier
monto que no sea un entero positivo en CLP, mensual, y con el plan en estado
`active` — si algo de eso falla, el checkout no se ofrece y no revienta.

La respuesta trae un `id` (algo como `2c9380848efa0abc018efa...`). Guardalo.

### 2.3 Cargar el plan en la base

```bash
docker compose exec postgres psql -U ofertas -d ofertas -c \
  "UPDATE telegram_tier_plans p
      SET mercadopago_plan_id = '2c9380848efa0abc018efa...',
          price_clp = 6000
    FROM telegram_tiers t
   WHERE t.id = p.tier_id AND t.slug = 'vip' AND p.period = 'monthly'"
```

Verificar que quedó (esto es parte del runbook, no un paso aparte — sin esto
`fetch_active_plans` no va a ofrecer el botón):

```bash
docker compose exec postgres psql -U ofertas -d ofertas -c \
  "SELECT period, price_usd, paypal_plan_id, price_clp, mercadopago_plan_id
     FROM telegram_tier_plans p JOIN telegram_tiers t ON t.id = p.tier_id
    WHERE t.slug = 'vip'"
```

Con los dos proveedores cargados en la misma fila, el bot va a mostrar el paso
de elección. Si por ahora solo querés MercadoPago activo y PayPal tal como
está, no hace falta tocar nada más: conviven.

### 2.4 Aplicar la migración — ✅ hecho el 2026-11-09 04:53 UTC

> Se aplicó en el despliegue conjunto, con las 47, 50, 52, 53 y 55. Verificado:
> `SELECT count(*) FROM schema_migrations` → **53**, y la fila
> `51_mercadopago_suscripciones.sql` está. Lo que sigue es la descripción de lo
> que se hizo; no hay nada que ejecutar acá.

⚠️ **La 51 no se aplica sola.** Al momento de escribir esto hay tres ramas con
migraciones sin integrar a `main` (`feat/unimarc` → 47, `feat/tiendas-bloqueadas`
→ 50 y 52, y esta → 51). Es exactamente el caso de la §5 de "Trabajo
multi-agente" en `CLAUDE.md`: están interdependientes a través de la base
aunque no compartan un archivo, y las cuatro suites pasan en verde por
separado. **Integrar primero, una build, una aplicación**, desde
`~/servicios/ofertoon` con la secuencia completa:

```bash
docker compose build db-migrate
docker compose run --rm db-migrate
```

Verificar la columna, no el mensaje — `listo — 0 migración(es) aplicada(s)` es
el mensaje tanto de una corrida sana como de una migración que no está en la
imagen:

```bash
docker compose exec postgres psql -U ofertas -d ofertas -c \
  "SELECT filename FROM schema_migrations WHERE filename LIKE '51_%'"
```

### 2.5 Reconstruir y recrear el webhook — ✅ hecho el 2026-11-09 04:53 UTC

> Verificado con `docker inspect ofertascl-paypal-webhook`: creado 04:53:08 UTC,
> `Cmd = ["python","-m","subscriptions.webhooks"]` — el entrypoint combinado, no
> el viejo `subscriptions.paypal.webhook`. `/health` → 200. Antes del
> despliegue el contenedor seguía siendo el del 2026-09-01, así que esta
> verificación no es decorativa: discrimina.


El `command` de `docker-compose.yml` para el servicio `paypal-webhook` cambió
de `subscriptions.paypal.webhook` a `subscriptions.webhooks` (el entrypoint
combinado). Eso **recrea el contenedor**, no solo lo reinicia:

```bash
docker compose build paypal-webhook
docker compose up -d paypal-webhook
curl -s http://localhost:8086/health   # {"status": "ok"}
```

### 2.6 🔴 El caso de control — ✅ corrido el 2026-11-09, pasa

> **Resultado, contra el contenedor recreado a las 04:53 UTC:**
>
> | | antes del deploy | ahora | lectura |
> |---|---|---|---|
> | `POST /webhook/paypal` | 401 | **401** | ✅ la ruta que cobra sigue viva |
> | `POST /webhook/mercadopago` | 404 | **503** | ✅ la ruta nueva existe y se niega a aceptar lo que no puede verificar |
> | `GET /health` | 200 | **200** | ✅ |
>
> ⚠️ **Y acá este runbook se equivocaba**: decía que el 404 "tiene que volverse
> 401". No: sin `MERCADOPAGO_ACCESS_TOKEN`/`MERCADOPAGO_WEBHOOK_SECRET` el
> endpoint contesta **503 "MercadoPago is not configured"**
> (`subscriptions/webhooks.py` arranca igual a propósito, para que PayPal no
> dependa de que MercadoPago esté configurado). El **401** aparece recién cuando
> el secreto está cargado y la firma no valida. Un 401 en esta etapa sería la
> señal de que alguien cargó credenciales; un 404, de que el `command` no apuntó
> donde se creía.

**No alcanza con que `/webhook/mercadopago` responda.** El riesgo real del
cambio de `command` es silencioso del otro lado: que `/webhook/paypal` se haya
roto al recrear el contenedor. Es el único endpoint que cobra de verdad hoy
(tier `vip` mensual USD 6,00, `paypal_plan_id` real, ya recibió un evento), y
si se rompe, PayPal reintenta en segundo plano — el síntoma aparece horas
después, no en este momento.

```bash
curl -s -o /dev/null -w '%{http_code}\n' -X POST http://localhost:8086/webhook/paypal -d '{}'
curl -s -o /dev/null -w '%{http_code}\n' -X POST http://localhost:8086/webhook/mercadopago -d '{}'
curl -s -o /dev/null -w '%{http_code}\n' http://localhost:8086/health
```

**Correcto**: `401` en PayPal (firma inválida — el endpoint existe y la
verificación corre), `503` en MercadoPago mientras no haya credenciales, `200`
en `/health`. **Mal**: `404 Not Found` en cualquiera de los dos webhooks (la
ruta desapareció — el `command` no apunta donde creés, o la imagen no se
reconstruyó). Un `000` o timeout también es mal: el contenedor no levantó.

### 2.7 Registrar la notificación en MercadoPago

En **Tus integraciones → Webhooks**, URL de notificación:

```
https://sendtelegram.budaicapital.com/webhook/mercadopago
```

El túnel Cloudflare ya existente rutea por **hostname**, sin mirar el path
(`{"hostname": "sendtelegram.budaicapital.com", "service": "http://paypal-webhook:8080"}`
+ catch-all 404) — verificado contra la config real. No hay nada que pedirle
al dueño del túnel; esa URL ya es alcanzable en cuanto el paso 2.5 terminó.

Suscribir a `subscription_preapproval` y `subscription_authorized_payment` (son
los dos únicos tipos de evento que `apply_mercadopago_event` entiende; cualquier
otro se audita como `ignored` y no hace nada).

### 2.8 Verificar que un pago real entra — en la base, no en el log

```bash
docker compose exec postgres psql -U ofertas -d ofertas -c \
  "SELECT event_type, processing_status, processing_error, received_at
     FROM mercadopago_webhook_events ORDER BY received_at DESC LIMIT 10"
```

`processing_status` esperado: `processed` o `ignored` (tipo de evento que no
usamos). Un `rejected` no es un bug del webhook: es un evento auténtico pero
inconsistente — el motivo está en `processing_error` (plan desconocido, monto
que no coincide, `external_reference` que choca con otra suscripción).

```bash
docker compose exec postgres psql -U ofertas -d ofertas -c \
  "SELECT telegram_user_id, payment_provider, mercadopago_preapproval_id,
          status, channel_state
     FROM telegram_memberships WHERE payment_provider = 'mercadopago'"
```

`status = 'active'` y, poco después (lo hace `gate_daemon`, no el webhook),
`channel_state` pasando de `none` a `invited`.

## 3. 🔴 El gate ya está encendido — no hay ensayo intermedio

`GATE_ENABLED=true` + `telegram_tiers.gate_enabled=true` para `vip`, con
`telegram_channel_id` cargado, **en producción, ahora**. Hoy es inofensivo (1
suscriptor, 1 membresía `expired`) porque ninguna variable `MERCADOPAGO_*`
está cargada — las tres están vacías en `.env.example`, así que el webhook de
MercadoPago contesta `503` a cualquier cosa y no hay forma de que un evento
llegue a aplicarse. **En cuanto completes la sección 2, el primer pago real
dispara un invite de Telegram de inmediato.** No hay un modo de prueba que
mida sin invitar: si querés probar el checkout sin dar acceso real, hacelo con
`MERCADOPAGO_ACCESS_TOKEN` en modo `TEST-` (sandbox de MercadoPago, tarjetas de
prueba) antes de pasar a `APP_USR-`.

## 4. Riesgos de infraestructura compartida (no son de este código, pero lo afectan)

- **El túnel Cloudflare no puede correr en dos hosts a la vez.** Si el mismo
  token de `cloudflared` corre en producción (`10.244.117.161`) y en el host
  de test (`10.244.19.205`) simultáneamente, Cloudflare reparte el tráfico
  entre los dos — con MercadoPago eso significa un cobro real cuyo aviso nunca
  llega al proceso que da el acceso.
- 🔴 **La firma HMAC del webhook tenía un bug que rechazaba el 100% de las
  notificaciones reales. Corregido el 2026-11-09.** Este riesgo estaba escrito
  acá como "no se probó contra una entrega real"; al ir a verificarlo contra el
  SDK oficial de MercadoPago (`github.com/mercadopago/sdk-go`,
  `pkg/webhook/webhook.go`) apareció el bug concreto: **el `ts` de la firma
  viene en milisegundos** y se comparaba contra `time.time()`, que son
  segundos. `abs(1,76e9 − 1,76e12)` no entra en ninguna ventana de tolerancia,
  así que todo evento auténtico habría salido **401** — y con PayPal cobrando
  normal, el síntoma habría sido "las suscripciones de MercadoPago nunca se
  activan", sin un error que apunte a la causa. El header de ejemplo de su
  propia documentación lo delata a simple vista: `ts=1742505638683`, 13
  dígitos.
  De paso aparecieron dos divergencias menores, también corregidas: el
  manifiesto **omite los pares vacíos** (sin `x-request-id` MercadoPago firma
  `id:X;ts:Y;`, no `id:X;request-id:;ts:Y;`, así que exigir ese header
  rechazaba notificaciones legítimas), y la clave del header se compara en
  minúsculas.
  **Por qué ninguno de los 11 tests lo vio**: construían el `ts` en segundos y
  se lo pasaban a un `now` también en segundos, o sea medían la implementación
  contra sí misma. Hoy son 16, con el `ts` siempre en milisegundos, un test que
  compara el manifiesto contra el formato literal del SDK y otro que rechaza
  explícitamente el `ts` de 10 dígitos. Verificado por mutación: reponer el bug
  pone 4 tests en rojo.
  ⚠️ **Lo que sigue pendiente es la prueba contra una entrega real del
  sandbox** (no hay `MERCADOPAGO_ACCESS_TOKEN` en este repo), y este bug es la
  razón por la que no es opcional: dar de alta un webhook de prueba, mirar un
  payload real con sus headers `x-signature`/`x-request-id` y confirmar que
  `_build_manifest` reproduce el hash.
- ~~**Esta migración (51) no es desplegable sola**~~ — ya no aplica: se aplicó
  el 2026-11-09 en el despliegue conjunto con las 47, 50, 52, 53 y 55. Queda
  escrito porque la regla que lo explicaba sigue viva (§Trabajo multi-agente 5
  de `CLAUDE.md`), no porque haya algo pendiente.

## 5. La guarda del canal mudo — escrita, probada y **apagada**

Agregado el 2026-11-09. No es de MercadoPago, pero es del mismo lado del
sistema: una vez que alguien pague, un día sin publicar es un día de servicio
no entregado. Evidencia, backtest y las opciones de umbral:
[`research/2026-11-09/GUARDA_canal_mudo.md`](research/2026-11-09/GUARDA_canal_mudo.md).

**Qué hace**: en cada vuelta del publisher pregunta si ya salió el **primer**
post del día (día calendario de Santiago, el mismo que usa el ranker). Si pasó
el deadline, la ventana está abierta, hoy no salió ninguno y **ayer sí hubo**,
manda un aviso por `alerts.send_alert` con la línea de mitigación adentro. Un
aviso por día: la condición queda prendida diez horas y sin memoria serían ~120
mensajes.

**Por qué el primer post y no el total**: el 6-nov el canal terminó con 23
posts, un total sano, habiendo perdido 6 h 18 min de ventana. Un chequeo de
total diario no lo ve nunca.

### 5.1 El interruptor

`ALERT_BOT_TOKEN` y `ALERT_CHAT_ID` **ya están cargadas** en el `.env` de
producción (las usa el scraper para su resumen de pasada), así que prenderla es
una línea más un recreate:

```bash
# 1. en .env
PUBLISHER_ALERTA_CANAL_MUDO=true

# 2. el publisher necesita la imagen nueva (el Dockerfile COPIA las fuentes) y
#    las variables nuevas que docker-compose.yml le pasa
docker compose build publisher
docker compose up -d publisher
```

**Verificar el efecto, no el mensaje.** El log de arranque dice si quedó
prendida — `guarda=True` es lo que hay que ver, y `guarda=False` es el mismo
arranque "exitoso" sin guarda:

```bash
docker compose logs publisher --tail 20 | grep publisher_daemon_started
# publisher_daemon_started poll_seconds=300.0 enabled=True bot_token=True guarda=True
```

Y para ver que la condición lee bien la base de verdad (no hace falta esperar un
día malo — esto evalúa la guarda contra el estado de ahora):

```bash
docker compose exec publisher python -c "
import asyncio, os
from datetime import datetime, timezone
import asyncpg
from publisher.guarda_canal import canal_mudo_hoy, posts_hoy_y_ayer
async def main():
    c = await asyncpg.connect(os.environ['DATABASE_URL'])
    hoy, ayer = await posts_hoy_y_ayer(c, ahora=datetime.now(timezone.utc))
    print('hoy', hoy, 'ayer', ayer)
    print(canal_mudo_hoy(posts_hoy=hoy, posts_ayer=ayer, ahora=datetime.now(timezone.utc)))
    await c.close()
asyncio.run(main())"
```

Un día sano contesta `None`, que es el caso de control. **Corrido contra
producción el 2026-11-09 05:18 UTC** (desde el host, con el DSN reescrito a
`@localhost:5436`, sin escribir nada):

```
ahora UTC 2026-11-09 05:18 | hoy 0 | ayer 23
veredicto: None
```

Cero posts hoy y la guarda calla, que es lo correcto: a las 02:18 de Santiago la
ventana no abrió. Es el caso de control de "no dispara fuera de la ventana",
medido contra la base real y no solo en un test.

**Apagarla** es la misma línea en `false` y otro `up -d publisher`. No hay
estado persistido que limpiar: la memoria del aviso vive en el proceso.

### 5.2 El deadline, que es tuyo

Default **13:00 UTC**, que es lo que el backtest sostiene: 3 disparos en los 49
días de historia del canal y los 3 son incidentes diagnosticados. Para moverlo:

```bash
# en .env — y después docker compose up -d publisher
PUBLISHER_ALERTA_DEADLINE_HOUR_UTC=12
```

🔴 **Antes de poner 12, leé el backtest.** Con ese valor la guarda habría
disparado en falso **23 días seguidos** en el régimen de ventana anterior
(`WINDOW_START_HOUR = 9`, hasta el 2026-10-21), y vuelve a ser inservible el
**2027-04-04**, cuando Santiago pase a UTC-4 y 08:00 local sean las 12:00 UTC.
Lo que compra es avisar de retrasos de una hora; lo que cuesta es la alerta
entera el día que la ventana se mueva. Hay una tercera opción —atar el deadline
a `ranker.WINDOW_START_HOUR` en vez de a UTC— que sobrevive a los dos cambios y
que **no implementé porque la decisión pedida era el número, no la forma**: son
~5 líneas y el backtest se vuelve a correr tal como está.

## 6. El tier `ferre` es una fila que miente (medido el 2026-11-09)

No lo toqué: es una decisión de producto. Lo que **medí**, contra la base:

| | |
|---|---|
| `telegram_tiers` id 2 `ferre` | `is_active=false`, `gate_enabled=false`, `telegram_channel_id=NULL` |
| planes del tier | id 3 anual USD 39,00 **inactivo** · id 4 mensual USD 3,99 **`is_active=TRUE`** |
| ids de cobro del plan 4 | `paypal_plan_id=NULL`, `mercadopago_plan_id=NULL`, `price_clp=NULL` |
| membresías | **0** |
| temas | **0** |
| `telegram_tier_categories` | **2** (`ferre-herramientas`, `ferre-jardin`), las dos con `topic_id=NULL` |

**Hoy es inofensivo, y por dos candados, no por uno.** Los tres lugares que leen
planes —`bot/db.fetch_active_plans`, `paypal/events` y `mercadopago/events`—
exigen `t.is_active = TRUE`, así que con el tier apagado el plan no existe para
nadie. Y `poster.load_active_tiers` exige además `telegram_channel_id IS NOT
NULL`, que es lo que evita que las dos categorías de ferretería se publiquen dos
veces (ya está documentado en su docstring).

**Pero el riesgo no es el que parece, y lo medí en vez de suponerlo.** Simulé
—con un `SELECT`, sin escribir— la query de `fetch_active_plans` con el tier
activado: devuelve **cero filas**, porque el plan 4 no tiene ningún id de
proveedor. O sea el día que alguien active `ferre` **no va a ofrecer un plan que
no se puede cobrar: no va a ofrecer nada**, y el usuario ve un tier sin forma de
pagar. Un callejón sin salida, no un cobro imposible. Igual es una fila que
miente, y el día que se complete a medias el error va a ser silencioso.

**Las dos salidas, y la decisión es del dueño:**

```sql
-- A) desactivar el plan, que es lo que la realidad ya dice (el anual ya está así)
UPDATE telegram_tier_plans SET is_active = FALSE
 WHERE tier_id = (SELECT id FROM telegram_tiers WHERE slug = 'ferre');

-- B) completarlo de verdad: canal + ids + precios + temas, y recién después
--    activar el tier. Todo lo que falta, en orden:
--      telegram_tiers.telegram_channel_id   (hoy NULL — sin esto no hay destino)
--      telegram_tier_plans.paypal_plan_id   y/o  mercadopago_plan_id + price_clp
--      telegram_topics del tier             (hoy 0 — sin esto cae al canal plano)
--      telegram_tiers.is_active             (último, cuando lo de arriba esté)
--      telegram_tiers.gate_enabled          (último de todos, regla 8)
```

Recomiendo **A** mientras `ferre` no sea un producto: una fila consistente que
dice "no se vende" es más barata que una a medio completar. Pero es un cambio de
producto y no lo aplico.
