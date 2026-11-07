-- =============================================================================
-- MIGRATION 51 — MercadoPago (CLP) como segundo proveedor de pago
-- =============================================================================
-- Hasta acá `telegram_tier_plans` y `telegram_memberships` solo sabían de
-- PayPal (migración 09). Este archivo agrega las columnas espejo para
-- MercadoPago sin tocar una sola columna de PayPal: un plan puede tener
-- `paypal_plan_id`, `mercadopago_plan_id`, ninguno o ambos a la vez, y el bot
-- (subscriptions/bot/payments.py) decide con cuáles mostrar botón.
--
-- `price_clp` es INTEGER, nunca NUMERIC/DECIMAL: la regla del proyecto es CLP
-- entero en todas las capas (CLAUDE.md regla 3). `price_usd` sigue en
-- NUMERIC(10,2) porque esa columna es de PayPal y no se toca.
--
-- `mercadopago_plan_id` es el id de un `preapproval_plan` ya creado en
-- MercadoPago (POST /preapproval_plan), exactamente el mismo patrón que
-- `paypal_plan_id`: un plan sin ese id no puede cobrar, pero no rompe nada —
-- el checkout falla explícito. Queda NULL hasta que el dueño lo cree a mano,
-- igual que pasó con `paypal_plan_id` en la migración 11.
--
-- `mercadopago_preapproval_id` en `telegram_memberships` es el equivalente de
-- `paypal_subscription_id`: identifica la suscripción (preapproval) del lado
-- de MercadoPago. `mercadopago_last_event_at` / `mercadopago_last_payment_at`
-- replican el mismo mecanismo anti-fuera-de-orden que ya usa PayPal
-- (subscriptions/paypal/events.py): un evento más viejo que el último
-- aplicado nunca puede pisar un estado más nuevo.
--
-- `mercadopago_webhook_events` es el espejo exacto de `paypal_webhook_events`
-- (migración 10): persistencia idempotente por `event_id` ANTES de aplicar,
-- para que un reintento de MercadoPago nunca duplique un efecto.
--
-- Por qué el webhook de MercadoPago necesita una tabla propia y no alcanza con
-- leer `payload`: a diferencia de PayPal, la notificación de MercadoPago NO
-- trae el recurso completo (solo `{type, data:{id}}`); el recurso real se pide
-- después a la API con el access token. El `payload` que se persiste acá es
-- la notificación cruda, no el recurso — eso vive solo en el momento de
-- aplicar el evento y no se guarda aparte.
--
-- IMPORTANT: idempotente. Segura de re-ejecutar.
-- =============================================================================

BEGIN;

ALTER TABLE telegram_tier_plans
    ADD COLUMN IF NOT EXISTS price_clp INTEGER,
    ADD COLUMN IF NOT EXISTS mercadopago_plan_id VARCHAR(64);

ALTER TABLE telegram_tier_plans
    DROP CONSTRAINT IF EXISTS telegram_tier_plans_price_clp_check;
ALTER TABLE telegram_tier_plans
    ADD CONSTRAINT telegram_tier_plans_price_clp_check
        CHECK (price_clp IS NULL OR price_clp > 0);

CREATE UNIQUE INDEX IF NOT EXISTS idx_telegram_tier_plans_mercadopago_plan
    ON telegram_tier_plans(mercadopago_plan_id)
    WHERE mercadopago_plan_id IS NOT NULL;

ALTER TABLE telegram_memberships
    ADD COLUMN IF NOT EXISTS mercadopago_payer_id        VARCHAR(64),
    ADD COLUMN IF NOT EXISTS mercadopago_preapproval_id  VARCHAR(64),
    ADD COLUMN IF NOT EXISTS mercadopago_last_event_at   TIMESTAMP WITH TIME ZONE,
    ADD COLUMN IF NOT EXISTS mercadopago_last_payment_at TIMESTAMP WITH TIME ZONE;

CREATE UNIQUE INDEX IF NOT EXISTS idx_telegram_memberships_mercadopago_sub
    ON telegram_memberships(mercadopago_preapproval_id)
    WHERE mercadopago_preapproval_id IS NOT NULL;

ALTER TABLE telegram_memberships
    DROP CONSTRAINT IF EXISTS telegram_memberships_payment_provider_check;
ALTER TABLE telegram_memberships
    ADD CONSTRAINT telegram_memberships_payment_provider_check
        CHECK (payment_provider IS NULL OR payment_provider IN
               ('paypal', 'mercadopago', 'ton', 'stripe', 'wallet_pay', 'whop'));

-- Espejo de paypal_webhook_events (migración 10): idempotencia por event_id
-- ANTES de aplicar, mismo CHECK de processing_status.
CREATE TABLE IF NOT EXISTS mercadopago_webhook_events (
    event_id           VARCHAR(96) PRIMARY KEY,
    event_type         VARCHAR(96) NOT NULL,
    resource_id        VARCHAR(128),
    payload            JSONB NOT NULL,
    processing_status  VARCHAR(16) NOT NULL DEFAULT 'received',
    processing_error   TEXT,
    received_at        TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    processed_at       TIMESTAMP WITH TIME ZONE,
    CONSTRAINT mercadopago_webhook_events_status_check
        CHECK (processing_status IN ('received', 'processed', 'ignored', 'rejected'))
);

CREATE INDEX IF NOT EXISTS idx_mercadopago_webhook_events_type_received
    ON mercadopago_webhook_events(event_type, received_at DESC);
CREATE INDEX IF NOT EXISTS idx_mercadopago_webhook_events_status_received
    ON mercadopago_webhook_events(processing_status, received_at)
    WHERE processing_status <> 'processed';

COMMIT;
