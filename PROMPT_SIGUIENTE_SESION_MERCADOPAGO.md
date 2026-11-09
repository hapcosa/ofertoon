# Prompt de traspaso — rama `feat/mercadopago`, escrito el 2026-11-06

Pegá lo que está dentro del bloque.

---

```
Seguís en `feat/mercadopago` de OfertasCL (worktree
`~/servicios/ofertoon-mercadopago`). Tu trabajo está commiteado en `b1bc552` y
revisado: migración 51, cliente/eventos/webhook de MercadoPago,
`subscriptions/webhooks.py` como entrypoint combinado, el paso "¿cómo pagás?" en
el bot, y el `command` de compose ya apuntando a `subscriptions.webhooks`.
936 tests en verde.

Lo que sigue NO es más código de pago: es cerrar lo que impide que esto se
active, y escribir lo que falta para que el dueño pueda hacerlo sin vos.

PRIMERO
Leé CLAUDE.md. Cambió hoy y te toca: §Paso 4 tiene una viñeta nueva con 🔴 sobre
reiniciar el scraper, §Trabajo multi-agente tiene seis subsecciones (la §5 es
nueva), y son 81 trampas, no 72.

ESTADO REAL, MEDIDO EN LA BASE EL 2026-11-06 — no lo heredes de ningún documento
  - **`main` avanzó y ya tiene `feat/unimarc` mergeada** (`1a44c0f`). Tu rama
    nació de un `main` anterior, así que **no tiene las migraciones 47 ni 48** ni
    `price_points.price_condition`. Tu base de test tampoco. No es un fallo tuyo.
  - Producción: **47 migraciones aplicadas, 01-46 y 48 — falta la 47**. Sí, hay
    un hueco. Desde un árbol que no tenga esos archivos, `migrate.py --status`
    contesta "sin pendientes" **y es falso**: la verdad está en
    `SELECT filename FROM schema_migrations`.
  - **Los números de migración ya están repartidos y sin colisiones**: 47
    (unimarc, en `main`), 50 y 52 (Rockford y Sparta, en `feat/tiendas-bloqueadas`),
    **51 tuya**. La 49 nunca se escribió y queda muerta. Si necesitás otra, la
    **53** es la primera libre — verificalo igual, con esto y no con `ls` de tu
    árbol:

        for d in ~/servicios/ofertoon*; do
          find "$d/migrations" -maxdepth 1 -name '*.sql' -printf '%f\n' 2>/dev/null
        done | grep -oE '^[0-9]+' | sort -n | tail -1

  - **La secuencia combinada 01-52 de las cuatro ramas ya fue probada el 6-nov**
    sobre bases descartables, en los dos órdenes: desde cero (51 migraciones) y
    replicando producción —01-46 y 48 primero, las cuatro pendientes después—,
    que es el caso real. Las dos limpias, con reaplicación idempotente dando 0, y
    los 34 adapters resolviendo. **No hace falta que lo repitas.**
  - Tu 51 quedó verificada en ese combinado: `telegram_tier_plans.price_clp`
    (INTEGER, con CHECK > 0) y `mercadopago_plan_id` existen, y
    `mercadopago_webhook_events` se crea.
  - 🔴 **GATE_ENABLED=true + `vip.gate_enabled=true` + canal `-1003735174401`
    cargado.** Hoy es inofensivo (1 suscriptor, 1 membresía `expired`), pero el
    primer pago real dispara invite de inmediato. **Ninguna variable
    `MERCADOPAGO_*` está cargada en el `.env` de producción** — las tres están en
    `.env.example` y vacías, así que hoy tu webhook contesta 503 y eso es
    correcto.

LO QUE YA REVISÉ DE TU CÓDIGO Y ESTÁ BIEN — no lo retoques
Lo digo para que no gastes la sesión re-verificando: la firma HMAC-SHA256 se
verifica y un `x-signature` inválido es 401; está manejada la sutileza de que la
firma cubre el `data.id` del QUERY y no el body, con el chequeo de desalineación
entre los dos; hay límite de body; y `fetch_active_plans` exige `t.is_active`
más, por proveedor, id no vacío **y** precio > 0 — que es justo lo que neutraliza
la incoherencia del tier `ferre` (tier inactivo, sin `telegram_channel_id`, sin
`paypal_plan_id`, pero con su plan mensual marcado activo a USD 3,99).

TU TRABAJO, EN ORDEN

1. **ESCRIBÍ `HANDOFF_MERCADOPAGO.md`, QUE NO EXISTE Y CLAUDE.MD YA LO
   REFERENCIA.** La tabla de la §"Este archivo es la puerta" lo lista para
   "retomar una sesión" y el archivo no está: es un puntero roto hoy. Tiene que
   contestar, sin que el lector abra tu código:
     - qué está hecho y qué falta;
     - **el runbook de activación**, que es lo único que bloquea todo: qué
       credenciales hace falta crear en MercadoPago, qué va en cada una de las
       tres variables (`MERCADOPAGO_ACCESS_TOKEN`,
       `MERCADOPAGO_WEBHOOK_SECRET`, `ONBOARDING_MERCADOPAGO_RETURN_URL`), qué
       URL registrar como notificación (`/webhook/mercadopago` sobre
       `sendtelegram.budaicapital.com`, que ya tunelea por hostname sin path, así
       que no hay nada que pedirle al dueño ahí), y el `UPDATE` exacto que carga
       `price_clp` y `mercadopago_plan_id`;
     - **qué mirar para confirmar que funcionó, en la base y no en un log**;
     - y el aviso de que el gate está encendido, así que el primer pago real
       invita de inmediato: no hay ensayo intermedio.

2. **EL CASO DE CONTROL DEL DESPLIEGUE, ESCRITO COMO PASO.** Cambiar el `command`
   de compose **recrea** el contenedor, y lo que hay que verificar después no es
   que `/webhook/mercadopago` responda: es que **`/webhook/paypal` SIGA
   respondiendo**. Es el único endpoint que cobra de verdad hoy (tier `vip`
   mensual USD 6,00 con `paypal_plan_id` real y un evento ya recibido), y una
   regresión ahí es silenciosa porque PayPal reintenta y el síntoma aparece
   horas después. Una prueba sin caso de control es un falso verde.

3. **MERGEÁ `main` A TU RAMA Y RE-CORRÉ LA SUITE.** `main` ya tiene unimarc, así
   que tu árbol va a recibir la 47, la 48, `price_condition` y sus tests. Es la
   única forma de saber que tu `build_app` combinado y tu wiring del bot no
   chocan con el `price_condition` que entró al SELECT de `curation/ranker.py` y
   al `publisher/formatter.py`. **Verificá el merge, no lo asumas**, y usá tu
   propia base (`ofertas_test_mercadopago`). El número a batir es **954** en
   `main`; con tus 24, esperá ~978.

4. **SI QUEDA SESIÓN: una guarda que falta y es de tu lado del sistema.**
   Medido hoy: el 6-nov el canal publicó **CERO** ofertas, contra 21-34 diarias la
   semana anterior, **sin un solo error y con todos los servicios en `Up`**. La
   causa está en `research/2026-11-06/INCIDENTE_canal_mudo.md` y ya está
   documentada; lo que **no** existe es nada que lo reporte:
   `runner.pasadas_flacas` y el canario viven los dos del lado de la ingesta, y
   ninguno mira el canal. Un día en cero con todo sano no dispara nada.
   Hay un `alerts.py` en la raíz del repo: mirá qué ofrece antes de escribir algo
   nuevo. La guarda es de una tercera altura —no "entró poco" ni "esta llave trae
   menos", sino "el producto no salió"— y se vuelve crítica justo cuando tu
   trabajo empiece a cobrar, porque ahí un día sin publicar es un día de servicio
   no entregado. **Proponé y medí; prender una alerta es decisión del dueño.**
   Si la escribís, el número que define el umbral no lo inventes: los posts por
   día de los últimos 7 días están en `deal_posts`.

QUÉ NO TOCAR
  - `migrations/47`, `scrapers/stores/unimarc.py`, `publisher/formatter.py`, el
    `price_condition` de `scrapers/base.py`, `db.py` y del SELECT de
    `curation/ranker.py` → son de `feat/unimarc`, ya en `main`.
  - `migrations/50` y `52`, `scrapers/stores/{pc_express,rockford}.py`,
    `TIENDAS_PROHIBIDAS.md`, `research/2026-11-07/` → de
    `feat/tiendas-bloqueadas`.
  - 🔴 **Nunca `docker compose run db-migrate` ni reiniciar scraper/publisher
    desde un worktree.** Aplicar es acción del dueño, desde
    `~/servicios/ofertoon` con la secuencia completa.
  - En los `.md` compartidos: **agregá, nunca reordenes**. `HANDOFF_MERCADOPAGO.md`
    es nuevo y entero tuyo, así que ahí no hay riesgo.

CÓMO SE TRABAJA ACÁ, EN CORTO
  - **Verificá el efecto, nunca el mensaje.** `listo — 0 migración(es)
    aplicada(s)` es a la vez el mensaje de una corrida sana y el de "tu migración
    no está en esta imagen".
  - **Una prueba sin caso de control es un falso verde.**
  - **Un pytest a la vez por base.** Y avisá antes de una corrida larga: hay dos
    agentes más sobre el mismo Postgres `:5436`, que además sirve producción.
  - **No commitees ni pushees salvo que te lo pidan.**
  - **Avisá cualquier decisión que tomes por tu cuenta**, por chica que parezca.
    Honestidad 100%, cero condescendencia: si algo falla, decilo con el output.
```
