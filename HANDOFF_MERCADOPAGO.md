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
> | §2.6 | `POST /webhook/mercadopago` hoy, antes del deploy | **404** — o sea la prueba discrimina: ese 404 es el «antes» y tiene que volverse 401 después |
> | §2.8 | columnas `event_type`, `processing_status`, `processing_error`, `received_at` y los cuatro estados del CHECK | **existen en la 51**, los nombres del runbook son correctos |
> | §2.8 | `telegram_memberships.payment_provider`, `channel_state`, `status` | **existen en producción** |
>
> Lo único **no** verificable sin credenciales es el ida y vuelta real con
> MercadoPago (§2.1, §2.2, §2.7): eso recién se puede probar cuando el dueño
> cargue el token.

## 1. Qué está hecho y qué falta

**Hecho y probado** (936 tests, 0 fallos, contra `ofertas_test_mercadopago`):

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
4. Aplicar la migración 51 (junto con las de las otras ramas — ver §4).
5. Reconstruir y recrear el servicio del webhook.
6. Registrar la URL de notificación en MercadoPago.
7. Verificar en la base, no en el log.

## 2. Runbook de activación

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

### 2.4 Aplicar la migración

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

### 2.5 Reconstruir y recrear el webhook

El `command` de `docker-compose.yml` para el servicio `paypal-webhook` cambió
de `subscriptions.paypal.webhook` a `subscriptions.webhooks` (el entrypoint
combinado). Eso **recrea el contenedor**, no solo lo reinicia:

```bash
docker compose build paypal-webhook
docker compose up -d paypal-webhook
curl -s http://localhost:8086/health   # {"status": "ok"}
```

### 2.6 🔴 El caso de control — verificar esto ANTES de seguir

**No alcanza con que `/webhook/mercadopago` responda.** El riesgo real del
cambio de `command` es silencioso del otro lado: que `/webhook/paypal` se haya
roto al recrear el contenedor. Es el único endpoint que cobra de verdad hoy
(tier `vip` mensual USD 6,00, `paypal_plan_id` real, ya recibió un evento), y
si se rompe, PayPal reintenta en segundo plano — el síntoma aparece horas
después, no en este momento.

```bash
curl -i -X POST http://localhost:8086/webhook/paypal -d '{}'
```

**Correcto**: `401 Unauthorized` (firma inválida — el endpoint existe y la
verificación corre). **Mal**: `404 Not Found` (la ruta desapareció — el
`command` no apunta donde creés, o la imagen no se reconstruyó). Un `000` o
timeout también es mal: el contenedor no levantó.

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
- **La firma HMAC del webhook está escrita según el esquema que MercadoPago
  documenta, pero no se probó contra una entrega real de su sandbox** (no hay
  `MERCADOPAGO_ACCESS_TOKEN` configurado en este repo todavía). Antes de
  confiar en ella con dinero real: dar de alta un webhook de prueba, mirar un
  payload real con sus headers `x-signature`/`x-request-id`, y confirmar que
  verifica. Los 11 tests de `tests/test_mercadopago_webhook.py` prueban la
  lógica con firmas que yo mismo construyo — no reemplazan esa prueba contra
  MercadoPago de verdad.
- **Esta migración (51) no es desplegable sola** — ver §2.4. Al momento de
  escribir esto, `main` tiene `feat/unimarc` mergeada (migración 47, hasta la
  48) pero NO tiene `feat/tiendas-bloqueadas` (50, 52) ni esta rama (51).
