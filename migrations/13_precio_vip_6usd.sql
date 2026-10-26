-- =============================================================================
-- MIGRATION 13 — Precio del plan mensual VIP a 6.00 USD
-- =============================================================================
-- El precio manda desde PayPal, no desde acá: el plan
-- P-8TJ137481H7582421NJYMG5A cobra 6.00 USD, y `_payment_completed`
-- (subscriptions/paypal/events.py) rechaza el evento si el monto cobrado no
-- coincide EXACTO con `price_usd`:
--
--     if currency != "USD" or amount != expected:
--         raise RejectedPayPalEvent("payment amount or currency mismatch")
--
-- La 11 sembró 4.99 (precio tentativo, anterior a crear el plan en PayPal). En
-- esta máquina se corrigió a mano, así que la DB y el repo dejaron de decir lo
-- mismo: una instalación nueva arrancaría en 4.99 y rechazaría todos los pagos.
-- Esta migración cierra esa brecha.
--
-- `price_usdt` va al mismo valor: es herencia del port de signalsTrading (allá
-- se cobraba en cripto) y ningún código de OfertasCL la lee, pero dejarla en
-- 4.99 al lado de un price_usd de 6.00 es una trampa para el próximo que mire
-- la tabla.
--
-- Se filtra por period = 'monthly': el anual sigue inactivo y sin plan creado
-- en PayPal, así que su precio es letra muerta hasta que se decida.
--
-- IMPORTANT: idempotente. Correrla dos veces deja el mismo valor.
-- =============================================================================

BEGIN;

UPDATE telegram_tier_plans AS p
   SET price_usd = 6.00,
       price_usdt = 6.00,
       updated_at = NOW()
  FROM telegram_tiers AS t
 WHERE t.id = p.tier_id
   AND t.slug = 'vip'
   AND p.period = 'monthly'
   AND (p.price_usd, p.price_usdt) IS DISTINCT FROM (6.00, 6.00);

COMMIT;
