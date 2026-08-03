-- =============================================================================
-- MIGRATION 09 — Suscripciones Telegram (port de signalsTrading 64/67/70/72)
-- =============================================================================
-- Port del schema de membresías de signalsTrading. Los nombres de tabla y de
-- columna se mantienen IDÉNTICOS a propósito: así los ~2.000 renglones del bot
-- de onboarding, el gate de canal y los webhooks de PayPal se copian sin editar
-- la lógica, solo cambiando el import path y el DATABASE_URL. Cualquier renombre
-- "más lindo" acá se paga con una auditoría línea por línea allá.
--
-- Qué NO se porta y por qué:
--
--   * `telegram_signal_posts` — su equivalente en este repo es `deal_posts`
--     (01_core.sql), que ya existe y apunta a `deal_candidates`. La tabla origen
--     referencia `paper_trades`, que es trading y acá no existe.
--   * `telegram_tier_strategies` — se reemplaza por `telegram_tier_categories`:
--     el fan-out de OfertasCL es por categoría de producto (tecno, ferretería),
--     no por estrategia de trading. Es la única tabla cuyo nombre cambia.
--   * `strategies.telegram_enabled` — no hay tabla `strategies`.
--   * `telegram_subscribers.web_user_id` — referencia `users(id)`, que no existe
--     acá (no hay dashboard web). El checkout web de signalsTrading queda fuera
--     del port; el funnel de OfertasCL entra por el bot.
--   * Las columnas POR-TIER viejas de `telegram_subscribers` (tier_id, status,
--     paypal_*, channel_state, invite_*, …). En origen quedaron deprecadas por
--     la migración 70 y ningún consumidor las lee — auditado sobre el código que
--     se porta. Se nace directamente con el split identidad/membresía en vez de
--     arrastrar la deuda.
--
-- Diferencia deliberada con el origen: el CHECK de `period` acepta 'weekly'.
-- `onboarding_bot/db.py:fetch_active_plans` ya ordena por 'weekly' y
-- `payments.py` lo etiqueta, pero el CHECK de la migración 64 no lo permite —
-- una fila así reventaría al insertarla. Acá se permite.
--
-- IMPORTANT: idempotente. Segura de re-ejecutar.
-- =============================================================================

BEGIN;

-- -----------------------------------------------------------------------------
-- telegram_tiers — un tier = un canal privado de Telegram.
-- Las columnas whop_/stripe_ se conservan (inactivas, como en origen) para que
-- el código portado que las menciona no necesite edición.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS telegram_tiers (
    id                  SERIAL PRIMARY KEY,
    name                VARCHAR(60)  NOT NULL,
    slug                VARCHAR(60)  NOT NULL UNIQUE,
    description         TEXT,
    whop_product_id     VARCHAR(64),
    stripe_product_id   VARCHAR(64),
    paypal_product_id   VARCHAR(64),
    telegram_channel_id BIGINT,
    results_channel_id  BIGINT,
    is_active           BOOLEAN NOT NULL DEFAULT TRUE,
    -- Control fino del gate por canal (migración 73 del origen). El gate
    -- efectivo es AND(env GATE_ENABLED, tier.gate_enabled): el env es el
    -- master-switch de seguridad, esta columna enciende un canal a la vez.
    -- DEFAULT FALSE: una base recién migrada queda inerte, no invita ni expulsa.
    gate_enabled        BOOLEAN NOT NULL DEFAULT FALSE,
    created_at          TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

ALTER TABLE telegram_tiers
    ADD COLUMN IF NOT EXISTS gate_enabled BOOLEAN NOT NULL DEFAULT FALSE;

CREATE INDEX IF NOT EXISTS idx_telegram_tiers_active
    ON telegram_tiers(is_active)
    WHERE is_active = TRUE;
CREATE INDEX IF NOT EXISTS idx_telegram_tiers_gate_enabled
    ON telegram_tiers(gate_enabled)
    WHERE gate_enabled = TRUE;

-- -----------------------------------------------------------------------------
-- telegram_tier_plans — precio fiat (USD/PayPal) y cripto (USDT) por período.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS telegram_tier_plans (
    id              SERIAL PRIMARY KEY,
    tier_id         INTEGER NOT NULL REFERENCES telegram_tiers(id) ON DELETE CASCADE,
    period          VARCHAR(12) NOT NULL,
    price_usdt      DECIMAL(10, 2) NOT NULL,
    price_usd       DECIMAL(10, 2),
    whop_plan_id    VARCHAR(64),
    stripe_price_id VARCHAR(64),
    paypal_plan_id  VARCHAR(64),
    is_active       BOOLEAN NOT NULL DEFAULT TRUE,
    updated_at      TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

ALTER TABLE telegram_tier_plans
    DROP CONSTRAINT IF EXISTS telegram_tier_plans_period_check;
ALTER TABLE telegram_tier_plans
    ADD CONSTRAINT telegram_tier_plans_period_check
        CHECK (period IN ('weekly', 'monthly', 'quarterly', 'semiannual', 'annual'));

ALTER TABLE telegram_tier_plans
    DROP CONSTRAINT IF EXISTS telegram_tier_plans_price_usd_check;
ALTER TABLE telegram_tier_plans
    ADD CONSTRAINT telegram_tier_plans_price_usd_check
        CHECK (price_usd IS NULL OR price_usd > 0);

CREATE INDEX IF NOT EXISTS idx_telegram_tier_plans_tier
    ON telegram_tier_plans(tier_id);
CREATE INDEX IF NOT EXISTS idx_telegram_tier_plans_active
    ON telegram_tier_plans(tier_id, is_active)
    WHERE is_active = TRUE;
CREATE UNIQUE INDEX IF NOT EXISTS idx_telegram_tier_plans_paypal_plan
    ON telegram_tier_plans(paypal_plan_id)
    WHERE paypal_plan_id IS NOT NULL;

-- -----------------------------------------------------------------------------
-- telegram_tier_categories — fan-out: qué categorías se publican en qué canal.
-- Reemplaza `telegram_tier_strategies` del origen. Es N:M: una categoría puede
-- ir a más de un tier (p. ej. un canal "todo" que agregue tecno y ferretería).
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS telegram_tier_categories (
    tier_id     INTEGER NOT NULL REFERENCES telegram_tiers(id) ON DELETE CASCADE,
    category_id INTEGER NOT NULL REFERENCES categories(id)     ON DELETE CASCADE,
    created_at  TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    PRIMARY KEY (tier_id, category_id)
);

CREATE INDEX IF NOT EXISTS idx_telegram_tier_categories_category
    ON telegram_tier_categories(category_id);

-- -----------------------------------------------------------------------------
-- telegram_subscribers — IDENTIDAD: una fila por persona. PK telegram_user_id.
-- Todo lo que es por-tier vive en telegram_memberships.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS telegram_subscribers (
    telegram_user_id  BIGINT PRIMARY KEY,
    telegram_username VARCHAR(64),
    email             VARCHAR(255),
    email_normalized  VARCHAR(255),
    email_verified_at TIMESTAMP WITH TIME ZONE,
    trial_used_at     TIMESTAMP WITH TIME ZONE,
    source_ref        TEXT,
    created_at        TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at        TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

-- Dedup anti-abuso del trial libre: una persona = un email normalizado.
CREATE INDEX IF NOT EXISTS idx_telegram_subscribers_email_normalized
    ON telegram_subscribers(email_normalized)
    WHERE email_normalized IS NOT NULL;

-- -----------------------------------------------------------------------------
-- telegram_memberships — estado por (persona, tier). PK compuesta = una persona
-- puede estar en varios canales a la vez.
--
-- `status` es el estado DESEADO (lo que dice el cobro); `channel_state` es el
-- estado APLICADO en Telegram. El gate concilia la brecha entre los dos; que
-- sean dos columnas distintas es lo que hace que un fallo de la API de Telegram
-- sea reintentable en vez de una membresía cobrada y sin acceso.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS telegram_memberships (
    telegram_user_id        BIGINT  NOT NULL
        REFERENCES telegram_subscribers(telegram_user_id) ON DELETE CASCADE,
    tier_id                 INTEGER NOT NULL
        REFERENCES telegram_tiers(id) ON DELETE CASCADE,
    tier_plan_id            INTEGER
        REFERENCES telegram_tier_plans(id) ON DELETE SET NULL,
    status                  VARCHAR(16) NOT NULL DEFAULT 'pending',
    channel_state           VARCHAR(12) NOT NULL DEFAULT 'none',
    payment_provider        VARCHAR(16),
    paypal_payer_id         VARCHAR(64),
    paypal_subscription_id  VARCHAR(64),
    paypal_last_event_at    TIMESTAMP WITH TIME ZONE,
    paypal_last_payment_at  TIMESTAMP WITH TIME ZONE,
    current_period_end      TIMESTAMP WITH TIME ZONE,
    trial_ends_at           TIMESTAMP WITH TIME ZONE,
    invite_link             TEXT,
    invite_expires_at       TIMESTAMP WITH TIME ZONE,
    invite_delivered_at     TIMESTAMP WITH TIME ZONE,
    access_granted_at       TIMESTAMP WITH TIME ZONE,
    access_revoked_at       TIMESTAMP WITH TIME ZONE,
    grace_until             TIMESTAMP WITH TIME ZONE,
    gate_last_error         TEXT,
    reminder_sent_at        TIMESTAMP WITH TIME ZONE,
    source_ref              TEXT,
    created_at              TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at              TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    PRIMARY KEY (telegram_user_id, tier_id),
    CONSTRAINT telegram_memberships_status_check
        CHECK (status IN ('pending', 'trialing', 'active', 'past_due',
                          'grace', 'canceled', 'expired')),
    CONSTRAINT telegram_memberships_channel_state_check
        CHECK (channel_state IN ('none', 'invited', 'member', 'kicked')),
    CONSTRAINT telegram_memberships_payment_provider_check
        CHECK (payment_provider IS NULL OR payment_provider IN
               ('paypal', 'ton', 'stripe', 'wallet_pay', 'whop'))
);

-- Barrido del gate: membresías que todavía no se asentaron en su canal.
CREATE INDEX IF NOT EXISTS idx_telegram_memberships_channel_state
    ON telegram_memberships(channel_state)
    WHERE channel_state <> 'none';
-- Lookup del webhook de PayPal por subscription id (único a nivel global).
CREATE UNIQUE INDEX IF NOT EXISTS idx_telegram_memberships_paypal_sub
    ON telegram_memberships(paypal_subscription_id)
    WHERE paypal_subscription_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_telegram_memberships_tier
    ON telegram_memberships(tier_id);
CREATE INDEX IF NOT EXISTS idx_telegram_memberships_tier_plan
    ON telegram_memberships(tier_plan_id)
    WHERE tier_plan_id IS NOT NULL;
-- Sweeper de expiración del trial.
CREATE INDEX IF NOT EXISTS idx_telegram_memberships_trial_ends
    ON telegram_memberships(trial_ends_at)
    WHERE status = 'trialing' AND trial_ends_at IS NOT NULL;

-- -----------------------------------------------------------------------------
-- telegram_email_verifications — código de verificación por email (opt-in).
-- El código NUNCA se guarda en claro: solo su SHA-256, con TTL, intentos y
-- consumo único.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS telegram_email_verifications (
    telegram_user_id BIGINT PRIMARY KEY
        REFERENCES telegram_subscribers(telegram_user_id) ON DELETE CASCADE,
    email_normalized VARCHAR(255) NOT NULL,
    code_hash        CHAR(64) NOT NULL,
    expires_at       TIMESTAMP WITH TIME ZONE NOT NULL,
    attempts         INTEGER NOT NULL DEFAULT 0 CHECK (attempts >= 0),
    created_at       TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    consumed_at      TIMESTAMP WITH TIME ZONE
);

-- -----------------------------------------------------------------------------
-- `deal_posts.tier_id` nació en 01_core.sql como INTEGER suelto porque
-- `telegram_tiers` todavía no existía. Ahora existe: se cierra la referencia.
-- -----------------------------------------------------------------------------
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'deal_posts_tier_id_fkey'
    ) THEN
        ALTER TABLE deal_posts
            ADD CONSTRAINT deal_posts_tier_id_fkey
            FOREIGN KEY (tier_id) REFERENCES telegram_tiers(id) ON DELETE CASCADE;
    END IF;
END $$;

COMMIT;
