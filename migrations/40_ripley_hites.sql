-- Catálogos públicos de Ripley, Hites y PC Express. Solo venta directa en
-- Ripley: un seller marketplace que rota no puede construir una baseline de
-- «Ripley». PC Express usa precio de transferencia para cualquiera, no el
-- precio tachado ni el recargo por otros medios.
--
-- Decisión del dueño 2026-11-06: empezar a acumular historial incluso en
-- Ripley, aunque su recorrido sea parcial (el canario lo reporta). La
-- publicación se separa de la ingesta: Ripley necesita estabilizar cobertura
-- y PC Express necesita validar stock en una ficha agotada. publish_enabled
-- bloquea ambas en detector Y curación mientras sus price_points se acumulan.
-- Hites puede publicar tras madurar. El default TRUE preserva las tiendas
-- existentes y las migraciones 41-45.
--
-- La fecha de conexión es la PRIMERA INGESTA, no esta migración. Evaluar cada
-- tienda 30 días observados después de esa fecha, antes de abrir el gate.
BEGIN;
ALTER TABLE stores
    ADD COLUMN IF NOT EXISTS publish_enabled BOOLEAN NOT NULL DEFAULT TRUE;

INSERT INTO stores (slug, name, base_url, adapter, rate_limit_rps, is_active, publish_enabled) VALUES
    -- Parcial no significa cero: se guardan los SKU recuperados y el canario
    -- sigue mostrando la brecha contra el total.
    ('ripley', 'Ripley', 'https://simple.ripley.cl',
     'scrapers.stores.ripley:RipleyAdapter', 0.5, TRUE, FALSE),
    ('hites', 'Hites', 'https://www.hites.com',
     'scrapers.stores.hites:HitesAdapter', 0.5, TRUE, TRUE),
    ('pc-express', 'PC Express (transferencia/efectivo)',
     'https://tienda.pc-express.cl',
     'scrapers.stores.pc_express:PcExpressAdapter', 0.4, TRUE, FALSE)
ON CONFLICT (slug) DO UPDATE SET
    name = EXCLUDED.name, base_url = EXCLUDED.base_url,
    adapter = EXCLUDED.adapter, rate_limit_rps = EXCLUDED.rate_limit_rps,
    is_active = EXCLUDED.is_active, publish_enabled = EXCLUDED.publish_enabled;

INSERT INTO store_categories (store_id, category_id, store_key)
SELECT s.id, c.id, v.store_key
FROM (VALUES
    ('ripley',     'tecno-notebooks',   'tecno/computacion/notebooks'),
    ('hites',      'tecno-notebooks',   'tecnologia/computacion/notebook'),
    ('pc-express', 'tecno-componentes', '460_475'),     -- video, con accesorios
    ('pc-express', 'tecno-componentes', '460_473'),     -- procesadores
    ('pc-express', 'tecno-componentes', '62_331_408'),  -- SSD NVME
    ('pc-express', 'tecno-componentes', '460_461'),     -- fuentes
    ('pc-express', 'tecno-componentes', '460_472'),     -- placas madres
    ('pc-express', 'tecno-componentes', '72_126'),      -- RAM
    ('pc-express', 'tecno-notebooks',   '476_136'),     -- notebooks comerciales
    ('pc-express', 'tecno-notebooks',   '476_479')      -- notebooks gamer
) AS v(store_slug, category_slug, store_key)
JOIN stores s ON s.slug = v.store_slug
JOIN categories c ON c.slug = v.category_slug
ON CONFLICT (store_id, category_id, store_key) DO NOTHING;
COMMIT;
