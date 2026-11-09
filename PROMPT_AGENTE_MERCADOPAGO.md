# Prompt — agente de pagos, rama `feat/mercadopago`

Pegá lo que está dentro del bloque.

---

```
Seguís en `feat/mercadopago` (worktree `~/servicios/ofertoon-mercadopago`). Tu
trabajo está integrado a `main`: migración 51, cliente/eventos/webhook,
`subscriptions/webhooks.py` como entrypoint combinado, el paso "¿cómo pagás?" en
el bot, y el `command` de compose apuntando al módulo nuevo. Tu rama no tiene
commits que `main` no tenga.

Lo que sigue NO es más código de pago: es cerrar lo que impide activarlo y lo
que el sistema todavía no vigila.

PRIMERO
Leé CLAUDE.md: la regla 5 cambió (el piso de historia es **10**), el §Paso 4
tiene una viñeta 🔴 sobre reiniciar el scraper, y §Trabajo multi-agente tiene
seis subsecciones. Mergeá `main` antes de tocar nada.

ESTADO REAL, MEDIDO EN LA BASE EL 2026-11-07
  - **47 migraciones aplicadas: 01-46 y 48. Pendientes la 47, 50, 51, 52 y 53** —
    tu 51 incluida. Desde un árbol que no tenga esos archivos,
    `migrate.py --status` contesta "sin pendientes" **y es falso**.
  - **Ninguna variable `MERCADOPAGO_*` está cargada en el `.env` de producción.**
    Las tres están en `.env.example` y vacías, así que tu webhook contesta 503 —
    y eso es correcto.
  - 🔴 **GATE_ENABLED=true + `vip.gate_enabled=true` + canal `-1003735174401`
    cargado.** Hoy es inofensivo (1 suscriptor, 1 membresía `expired`), pero el
    primer pago real dispara invite de inmediato. No hay ensayo intermedio.
  - Planes: tier `vip` mensual **USD 6,00** con `paypal_plan_id` real y 1 evento
    recibido; el anual (USD 49) inactivo y sin id; tier `ferre` con el tier en
    `is_active=false`, sin canal y sin ids. `price_clp` y `mercadopago_plan_id`
    existen (tu 51) pero **sin valores**.
  - El canal publica 22-25 por día contra cuota 33.

TU TRABAJO, EN ORDEN

1. **`HANDOFF_MERCADOPAGO.md`, QUE SIGUE SIN EXISTIR Y CLAUDE.MD YA LO
   REFERENCIA.** La tabla de la §"Este archivo es la puerta" lo lista para
   "retomar una sesión": hoy es un puntero roto. Verificado el 2026-11-07, el
   archivo no está en `main`. Tiene que contestar, sin que el lector abra tu
   código:
     - qué está hecho y qué falta;
     - **el runbook de activación**, que es lo único que bloquea todo: qué crear
       en MercadoPago, qué va en `MERCADOPAGO_ACCESS_TOKEN`,
       `MERCADOPAGO_WEBHOOK_SECRET` y `ONBOARDING_MERCADOPAGO_RETURN_URL`, qué
       URL registrar como notificación (`/webhook/mercadopago` sobre
       `sendtelegram.budaicapital.com`, que tunelea por hostname sin path, así
       que no hay nada que pedir ahí), y el `UPDATE` exacto que carga `price_clp`
       y `mercadopago_plan_id`;
     - **qué mirar en la base para confirmar que funcionó**, no en un log;
     - el aviso del gate encendido y el del túnel: **nunca dos `cloudflared` con
       el mismo token**, porque Cloudflare reparte el tráfico y con MercadoPago
       eso es un cobro cuyo aviso nunca llega al proceso que da el acceso.

2. **EL CASO DE CONTROL DEL DESPLIEGUE, ESCRITO COMO PASO.** Cambiar el `command`
   de compose **recrea** el contenedor, y lo que hay que verificar después no es
   que `/webhook/mercadopago` responda: es que **`/webhook/paypal` SIGA
   respondiendo**. Es el único endpoint que cobra de verdad hoy, y una regresión
   ahí es silenciosa porque PayPal reintenta y el síntoma aparece horas después.

3. **LA GUARDA DEL CANAL — terminá lo que empezaste con `alerts.py`.** El 6-nov
   el canal estuvo 6 h 18 min sin publicar en plena ventana, con todos los
   servicios en `Up` y sin un solo error. `runner.pasadas_flacas` y el canario
   viven los dos del lado de la ingesta: **ninguno mira el canal**. Verificado el
   7-nov: `alerts.py` tiene `format_summary` y `send_alert`, pero nada que
   pregunte "¿publicó algo hoy?".
   Lo que falta es de una tercera altura: no "entró poco" ni "esta llave trae
   menos", sino **"el producto no salió"**. El umbral no lo inventes: los posts
   por día de la última semana están en `deal_posts` (22, 23, 25, 34, 25, 21, 24)
   y la ventana es 08:00-23:00 de Santiago (`ranker.WINDOW_START_HOUR`).
   Se vuelve crítica justo cuando tu trabajo empiece a cobrar, porque ahí un día
   sin publicar es un día de servicio no entregado. **Proponé y medí; prender una
   alerta es decisión del dueño.**

NÚMEROS DE MIGRACIÓN
La **54** es la primera libre, y es del agente de tiendas si la toma para la
terna Salesforce. Si necesitás una, **tomá la 55 y avisá**. Verificalo con esto
y no con `ls` de tu árbol:

    for d in ~/servicios/ofertoon*; do
      find "$d/migrations" -maxdepth 1 -name '*.sql' -printf '%f\n' 2>/dev/null
    done | grep -oE '^[0-9]+' | sort -n | tail -1

QUÉ NO TOCAR
  - `scrapers/`, `migrations/47`, `50`, `52`, `54` → del agente de tiendas.
  - `migrations/53` y la regla 5 de CLAUDE.md → de `feat/piso-diez`.
  - 🔴 **Nunca aplicar migraciones ni reiniciar scraper/publisher.** Es acción del
    dueño, desde `~/servicios/ofertoon` con la secuencia completa.
  - En los `.md` compartidos: **agregá, nunca reordenes**.
    `HANDOFF_MERCADOPAGO.md` es nuevo y entero tuyo.

CÓMO SE TRABAJA ACÁ
  - **Verificá el efecto, nunca el mensaje.**
  - **Una prueba sin caso de control es un falso verde.**
  - **Un pytest a la vez por base** (`ofertas_test_mercadopago`), y avisá antes de
    una corrida larga: hay tres agentes sobre el mismo Postgres `:5436`.
  - **No commitees ni pushees salvo que te lo pidan.**
  - **Avisá cualquier decisión que tomes por tu cuenta.** Honestidad 100%: si
    algo falla, decilo con el output.
```
