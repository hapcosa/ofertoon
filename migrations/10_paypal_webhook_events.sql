-- =============================================================================
-- MIGRATION 10 — Inbox de webhooks de PayPal (port de signalsTrading 65)
-- =============================================================================
-- Auditoría durable e idempotente de los eventos firmados de PayPal. La PK es
-- el `event_id` de PayPal: eso es lo que hace que un reintento de PayPal —que
-- ocurre siempre que la respuesta se demora— no pueda aplicar dos veces la
-- misma transición de suscripción. El payload crudo se guarda entero porque
-- cuando un cobro sale mal lo único confiable es lo que PayPal mandó, no lo que
-- nosotros interpretamos.
--
-- IMPORTANT: idempotente. Segura de re-ejecutar.
-- =============================================================================

BEGIN;

CREATE TABLE IF NOT EXISTS paypal_webhook_events (
    event_id           VARCHAR(96) PRIMARY KEY,
    event_type         VARCHAR(96) NOT NULL,
    resource_id        VARCHAR(128),
    payload            JSONB NOT NULL,
    processing_status  VARCHAR(16) NOT NULL DEFAULT 'received',
    processing_error   TEXT,
    received_at        TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    processed_at       TIMESTAMP WITH TIME ZONE,
    CONSTRAINT paypal_webhook_events_status_check
        CHECK (processing_status IN ('received', 'processed', 'ignored', 'rejected'))
);

CREATE INDEX IF NOT EXISTS idx_paypal_webhook_events_type_received
    ON paypal_webhook_events(event_type, received_at DESC);
CREATE INDEX IF NOT EXISTS idx_paypal_webhook_events_status_received
    ON paypal_webhook_events(processing_status, received_at)
    WHERE processing_status <> 'processed';

COMMIT;
