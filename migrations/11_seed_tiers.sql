-- =============================================================================
-- MIGRATION 11 — Seed de los canales VIP: tiers, planes y categorías por tier
-- =============================================================================
-- Dos canales, partidos por lo que la gente realmente persigue: TECNO (notebooks,
-- celulares, componentes, TVs) y FERRE (herramientas, jardín). Electrodomésticos
-- va a TECNO porque es la categoría puente: quien caza un TV también caza un
-- refrigerador, y no da para un tercer canal con dos categorías.
--
-- Los ids de canal (`telegram_channel_id`) quedan NULL: se cargan cuando los
-- canales existen en Telegram y el bot es admin de ambos. Un tier sin canal es
-- no-op para el gate, así que la seed no puede romper nada.
--
-- `gate_enabled = FALSE` en ambos: el interruptor fino por canal arranca
-- apagado y se prende recién con los canales verificados. El efectivo es el AND
-- con la env `GATE_ENABLED`, que también arranca en false.
--
-- Los `paypal_plan_id` quedan NULL hasta crear los planes en PayPal; un plan sin
-- ese id no puede cobrar (el webhook resuelve el tier POR el plan), pero tampoco
-- rompe: el checkout falla explícito en vez de conceder acceso.
--
-- IMPORTANT: idempotente (ON CONFLICT DO UPDATE / DO NOTHING). Segura de
-- re-ejecutar: no pisa `telegram_channel_id`, `paypal_plan_id` ni `gate_enabled`,
-- que son lo único que se configura a mano después.
-- =============================================================================

BEGIN;

INSERT INTO telegram_tiers (name, slug, description, is_active, gate_enabled) VALUES
    ('OfertasCL TECNO', 'tecno',
     'Ofertas reales de notebooks, celulares, componentes, TVs y electro.',
     TRUE, FALSE),
    ('OfertasCL FERRE', 'ferre',
     'Ofertas reales de herramientas eléctricas y jardín.',
     TRUE, FALSE)
ON CONFLICT (slug) DO UPDATE
    SET name = EXCLUDED.name,
        description = EXCLUDED.description,
        is_active = EXCLUDED.is_active;

-- Un tier no puede tener dos planes del mismo período: la 09 no lo declaraba
-- (el esquema original de signalsTrading tampoco) y sin eso esta seed no sería
-- re-ejecutable — cada corrida duplicaría los planes y el menú mostraría el
-- mismo precio dos veces.
CREATE UNIQUE INDEX IF NOT EXISTS idx_telegram_tier_plans_tier_period
    ON telegram_tier_plans(tier_id, period);

-- Precios de partida en USD (PayPal cobra en USD). El mensual es el ancla; el
-- anual se sostiene solo si el canal ya tiene track record, así que arranca
-- inactivo y se prende cuando haya 90d de ofertas publicadas para mostrar.
INSERT INTO telegram_tier_plans (tier_id, period, price_usdt, price_usd, is_active)
SELECT t.id, v.period, v.price, v.price, v.is_active
  FROM telegram_tiers AS t
  JOIN (VALUES
        ('tecno', 'monthly', 4.99, TRUE),
        ('tecno', 'annual', 49.00, FALSE),
        ('ferre', 'monthly', 3.99, TRUE),
        ('ferre', 'annual', 39.00, FALSE)
       ) AS v(tier_slug, period, price, is_active)
    ON v.tier_slug = t.slug
ON CONFLICT (tier_id, period) DO UPDATE
    SET price_usdt = EXCLUDED.price_usdt,
        price_usd = EXCLUDED.price_usd;

-- Qué categorías alimentan cada canal. Es lo que el publisher (F3) va a leer
-- para decidir dónde publica cada `deal_candidate` aceptado.
INSERT INTO telegram_tier_categories (tier_id, category_id)
SELECT t.id, c.id
  FROM telegram_tiers AS t
  JOIN (VALUES
        ('tecno', 'tecno-notebooks'),
        ('tecno', 'tecno-celulares'),
        ('tecno', 'tecno-componentes'),
        ('tecno', 'tecno-tv'),
        ('tecno', 'hogar-electro'),
        ('ferre', 'ferre-herramientas'),
        ('ferre', 'ferre-jardin')
       ) AS v(tier_slug, category_slug)
    ON v.tier_slug = t.slug
  JOIN categories AS c ON c.slug = v.category_slug
ON CONFLICT (tier_id, category_id) DO NOTHING;

COMMIT;
