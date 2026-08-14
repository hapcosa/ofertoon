# OfertasCL — puesta en producción

Runbook del despliegue en la máquina 24/7. Todo lo que sigue está verificado en
desarrollo; lo que **no** está verificado es la configuración externa (BotFather,
canales de Telegram, PayPal), que es justamente lo que se hace acá.

El orden importa: **el gate se prende último**. Un gate encendido contra tiers
mal configurados expulsa gente de los canales, y eso no se deshace con un
`git revert`.

---

## 0. Requisitos de la máquina

- Docker + Docker Compose v2 (`docker compose version`).
- Puertos libres: `5436` (Postgres) y el que se elija para el webhook (`8086` por
  defecto). El de Postgres **no** debe exponerse a internet.
- Un dominio o túnel con HTTPS apuntando al webhook. PayPal firma cada evento y
  exige HTTPS; sin esto no hay cobros.
- Python 3.12 + `.venv` solo si se quieren correr los tests o `migrate.py` desde
  el host. Los servicios no lo necesitan: corren en la imagen.

## 1. Clonar y configurar

```bash
git clone https://github.com/hapcosa/ofertoon.git
cd ofertoon
cp .env.example .env
```

Editar `.env`. Lo mínimo para que el stack **arranque** (sin cobros todavía):

| Variable | Qué poner |
|---|---|
| `POSTGRES_PASSWORD` | Una contraseña nueva, no la de desarrollo. |
| `DATABASE_URL` | El mismo usuario/contraseña, host `postgres`, puerto `5432` (es la red interna de Docker, no el `5436` del host). |
| `ONBOARDING_BOT_TOKEN` | Token de BotFather (paso 3). |
| `GATE_ENABLED` | **`false`**. Se prende en el paso 8, no antes. |

El resto (`PAYPAL_*`, `RESEND_API_KEY`) puede quedar vacío en el primer
arranque: el bot levanta igual y el checkout falla de forma explícita en vez de
conceder acceso gratis.

## 2. Levantar Postgres y migrar

```bash
docker compose up -d postgres
docker compose run --rm db-migrate
```

`db-migrate` aplica las 11 migraciones y sale. Son idempotentes: se puede
re-correr sin miedo. Verificar que la seed quedó:

```bash
docker compose exec postgres psql -U ofertas -d ofertas \
  -c "SELECT slug, is_active, gate_enabled, telegram_channel_id FROM telegram_tiers"
```

Deben aparecer `tecno` y `ferre`, con `gate_enabled = f` y `telegram_channel_id`
NULL. Eso es lo correcto en este punto.

## 3. Bot de Telegram

En [@BotFather](https://t.me/BotFather): `/newbot`, nombre y username. Guardar el
token en `ONBOARDING_BOT_TOKEN` y el username (sin `@`) en
`ONBOARDING_BOT_USERNAME` — este último arma los deep links de referidos y el
`return_url` de PayPal.

Recomendado: `/setprivacy` → `Disable` no hace falta (el bot solo lee DMs), pero
sí conviene `/setdescription` y `/setcommands` con `start`, `menu`.

## 4. Canales privados

Crear **dos canales privados** (uno por tier: TECNO y FERRE). En cada uno:

1. Agregar el bot como **administrador** con permisos de *Invitar usuarios* y
   *Banear usuarios*. Sin ambos el gate no puede ni invitar ni expulsar.
2. Obtener el `chat_id` (empieza con `-100…`). La forma directa: reenviar un
   mensaje del canal a [@userinfobot](https://t.me/userinfobot), o mirar el log
   del bot.
3. Cargarlo en la DB:

```bash
docker compose exec postgres psql -U ofertas -d ofertas -c \
  "UPDATE telegram_tiers SET telegram_channel_id = -1001111111111 WHERE slug = 'tecno'"
docker compose exec postgres psql -U ofertas -d ofertas -c \
  "UPDATE telegram_tiers SET telegram_channel_id = -1002222222222 WHERE slug = 'ferre'"
```

## 5. Arrancar bot y gate

```bash
docker compose up -d bot gate
docker compose logs -f bot
```

El log debe decir que el bot arrancó y quedar en polling. Probar en Telegram:
`/start` → tiene que aparecer el menú con los dos canales y el botón de trial.

El gate arranca **inerte** (`gate_daemon_started gate_enabled=False`). Es lo
esperado.

## 6. PayPal

En el dashboard de PayPal (empezar en **sandbox**, `PAYPAL_ENV=sandbox`):

1. Crear la app REST → copiar `PAYPAL_CLIENT_ID` y `PAYPAL_CLIENT_SECRET`.
2. Crear un **producto** y, dentro, un **plan de suscripción mensual en USD** por
   cada tier. Los precios sembrados son `4.99` (TECNO) y `3.99` (FERRE); si se
   cambian en PayPal hay que cambiarlos también en `telegram_tier_plans` —
   el webhook **rechaza** un pago cuyo monto no coincide exactamente.
3. Cargar los `plan_id` (empiezan con `P-`):

```bash
docker compose exec postgres psql -U ofertas -d ofertas -c \
  "UPDATE telegram_tier_plans p SET paypal_plan_id = 'P-XXXXTECNO'
     FROM telegram_tiers t
    WHERE t.id = p.tier_id AND t.slug = 'tecno' AND p.period = 'monthly'"
```

(ídem para `ferre`.)

4. Definir `ONBOARDING_PAYPAL_RETURN_URL` y `ONBOARDING_PAYPAL_CANCEL_URL`
   apuntando al bot: `https://t.me/<username>?start=paypal_approved` y
   `…?start=paypal_cancelled`.

## 7. Webhook

```bash
docker compose up -d paypal-webhook
curl -s http://localhost:8086/health   # {"status": "ok"}
```

Exponerlo por HTTPS (Cloudflare Tunnel es lo más simple: no abre puertos ni pide
certificados). Después, en PayPal → *Webhooks*, registrar
`https://<dominio>/webhook/paypal` suscrito al menos a:

- `BILLING.SUBSCRIPTION.ACTIVATED`
- `BILLING.SUBSCRIPTION.UPDATED`
- `BILLING.SUBSCRIPTION.SUSPENDED`
- `BILLING.SUBSCRIPTION.CANCELLED`
- `BILLING.SUBSCRIPTION.EXPIRED`
- `BILLING.SUBSCRIPTION.PAYMENT.FAILED`
- `PAYMENT.SALE.COMPLETED`
- `PAYMENT.SALE.REFUNDED`
- `PAYMENT.SALE.REVERSED`

Copiar el **Webhook ID** a `PAYPAL_WEBHOOK_ID` y reiniciar:
`docker compose up -d paypal-webhook`.

Sin esa variable el endpoint responde `503` a todo — no acepta eventos que no
puede verificar. Es deliberado.

Verificar que un evento entra:

```bash
docker compose exec postgres psql -U ofertas -d ofertas -c \
  "SELECT event_type, processing_status, processing_error, received_at
     FROM paypal_webhook_events ORDER BY received_at DESC LIMIT 10"
```

`processing_status` esperado: `processed` (aplicado) o `ignored` (tipo de evento
que no usamos). Un `rejected` **no es un bug del webhook**: es un evento
auténtico pero inconsistente (plan desconocido, monto que no coincide,
`custom_id` que choca con otra suscripción). El motivo está en
`processing_error`.

## 8. Prender el gate — último paso

Recién cuando el funnel completo esté probado (trial → invite por DM → pago →
membresía `active`):

```bash
# Interruptor por canal
docker compose exec postgres psql -U ofertas -d ofertas -c \
  "UPDATE telegram_tiers SET gate_enabled = TRUE WHERE slug IN ('tecno','ferre')"
# Interruptor global
sed -i 's/^GATE_ENABLED=false/GATE_ENABLED=true/' .env
docker compose up -d gate
docker compose logs -f gate
```

El gate efectivo es el **AND** de los dos. Para apagarlo de urgencia alcanza con
`GATE_ENABLED=false` + `docker compose up -d gate`: deja de invitar y de
expulsar, sin tocar la DB.

## 9. Scraper

```bash
docker compose up -d scraper
```

Corre en loop de 12h. Si en la máquina de desarrollo ya había historia de
precios y se la quiere conservar, hay que migrar el volumen de Postgres
(`pg_dump` / `pg_restore`); si no, la historia arranca de cero y **F1 no se
puede calibrar hasta 45 días después** de la primera pasada.

Cerrada cada pasada, el mismo proceso corre la **fase de pricing** (baselines +
detector). No es un servicio aparte a propósito: el trigger de una baseline es
"llegaron observaciones nuevas", y este proceso es el único que sabe cuándo pasó
eso. Se ve en el log como una línea por pasada:

```
docker compose logs scraper | grep "pipeline:"
# pipeline: baselines[10697 listings, 10697 baselines escritas, 0 con historia
#           suficiente, 0 con rampa] detector[0 evaluados, 0 aceptados (…)]
```

**Esa línea es la que hay que mirar durante el cold-start.** Hasta que el
catálogo tenga 30 días calendario de historia, el detector rechaza el 100% por
`history` y esos rechazos NO se persisten — o sea que una `deal_candidates`
vacía no distingue "el job no corrió" de "corrió y descartó todo". El log sí.

Para correr la fase a mano sin esperar la pasada:
`docker compose exec scraper python -m pricing.pipeline`.

## 10. Publisher — se prende cuando haya qué publicar

```bash
docker compose up -d publisher      # arranca inerte
```

Igual que el gate, nace apagado (`PUBLISHER_ENABLED=false`) porque publicar en
un canal es irreversible. Postea con `GATE_BOT_TOKEN`, que ya es administrator
con `can_post_messages`.

La política de publicación —cuota diaria, topes por tienda y categoría,
espaciado y ventana horaria— vive entera en `curation/ranker.py`, no en env
vars: son decisiones de producto y cambiarlas debería quedar en el historial de
git, no en un `.env` que nadie revisa. Los valores están en las constantes del
módulo.

Prenderlo **no tiene sentido antes de ~2026-09-02**: hasta entonces no hay
baselines con historia suficiente y el ranker no va a tener nada que elegir.
Cuando llegue el momento:

```bash
# .env → PUBLISHER_ENABLED=true
docker compose up -d publisher
docker compose logs -f publisher
```

Apagado de urgencia: `PUBLISHER_ENABLED=false` + `docker compose up -d
publisher`. Los mensajes ya publicados quedan; se dejan de emitir nuevos.

---

## Verificación final

```bash
docker compose ps                    # todos up salvo db-migrate (exited 0)
docker compose logs --tail=50 bot gate paypal-webhook scraper
```

Checklist:

- [ ] `/start` en el bot muestra los dos canales.
- [ ] El trial entrega un invite link por DM y entra al canal.
- [ ] `telegram_tiers.telegram_channel_id` cargado en los dos tiers.
- [ ] `telegram_tier_plans.paypal_plan_id` cargado en los dos planes mensuales.
- [ ] Un pago sandbox deja la membresía en `active` y el evento en `processed`.
- [ ] Cancelar la suscripción en PayPal expulsa del canal (con el gate prendido).
- [ ] `GATE_ENABLED=true` **y** `gate_enabled = TRUE` solo después de todo lo anterior.

## Backups

El único estado irrecuperable es Postgres: la historia de precios no se puede
reconstruir hacia atrás. Un `pg_dump` diario alcanza:

```bash
docker compose exec -T postgres pg_dump -U ofertas ofertas | gzip > backup-$(date +%F).sql.gz
```
