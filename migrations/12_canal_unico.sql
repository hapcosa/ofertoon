-- =============================================================================
-- MIGRATION 12 — Un solo canal con todas las ofertas
-- =============================================================================
-- Decisión de producto que reemplaza el corte TECNO/FERRE de la 11: un único
-- canal VIP que recibe las 7 categorías. Se hace como migración y no con
-- UPDATEs sueltos para que una DB nueva termine en el mismo estado que ésta.
--
-- Se REUSA el tier 'tecno' en vez de crear uno nuevo: ya tiene el plan mensual
-- con `paypal_plan_id` cargado, y los planes cuelgan de `tier_id`. Crear un tier
-- nuevo obligaría a recrear el plan en PayPal.
--
-- 'ferre' queda `is_active = FALSE`, no borrado: borrarlo se llevaría por
-- delante cualquier membresía histórica que lo referencie. Un tier inactivo no
-- aparece en el menú del bot.
--
-- El slug se muestra al cliente (`delivery.py` arma "Tu acceso a <slug>"), por
-- eso pasa a 'vip' y no queda como 'tecno'.
--
-- IMPORTANT: idempotente. El UPDATE por slug no encuentra nada en la segunda
-- corrida y el INSERT de categorías es ON CONFLICT DO NOTHING.
-- =============================================================================

BEGIN;

UPDATE telegram_tiers
   SET name = 'Ofertoon VIP',
       slug = 'vip',
       description = 'Ofertas reales de retail chileno: tecno, hogar y ferretería.'
 WHERE slug = 'tecno';

UPDATE telegram_tiers
   SET is_active = FALSE
 WHERE slug = 'ferre';

-- Todas las categorías al canal único. El publisher (F3) lee esta tabla para
-- decidir dónde va cada candidato aceptado; sin estas filas el canal quedaría
-- sin nada que publicar.
INSERT INTO telegram_tier_categories (tier_id, category_id)
SELECT t.id, c.id
  FROM telegram_tiers AS t
  CROSS JOIN categories AS c
 WHERE t.slug = 'vip'
ON CONFLICT (tier_id, category_id) DO NOTHING;

COMMIT;
