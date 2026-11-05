-- Catálogos públicos verificados el 2026-11-05. Solo venta directa.
-- Inicio acotado a notebooks: categoría existente, sin alterar sus umbrales.
-- La fecha de conexión será la primera ingesta; no la fecha de esta migración.
BEGIN;
INSERT INTO stores (slug, name, base_url, adapter, rate_limit_rps, is_active) VALUES
    -- Preparada pero inactiva: el catálogo repite SKUs entre páginas y no
    -- alcanza el total declarado. No convertir una prueba parcial en cobertura.
    ('ripley', 'Ripley', 'https://simple.ripley.cl',
     'scrapers.stores.ripley:RipleyAdapter', 0.5, FALSE),
    ('hites', 'Hites', 'https://www.hites.com',
     'scrapers.stores.hites:HitesAdapter', 0.5, TRUE)
ON CONFLICT (slug) DO UPDATE SET
    name = EXCLUDED.name, base_url = EXCLUDED.base_url,
    adapter = EXCLUDED.adapter, rate_limit_rps = EXCLUDED.rate_limit_rps;

INSERT INTO store_categories (store_id, category_id, store_key)
SELECT s.id, c.id, v.store_key
FROM (VALUES
    ('ripley', 'tecno/computacion/notebooks'),
    ('hites', 'tecnologia/computacion/notebook')
) AS v(store_slug, store_key)
JOIN stores s ON s.slug = v.store_slug
JOIN categories c ON c.slug = 'tecno-notebooks'
ON CONFLICT (store_id, category_id, store_key) DO NOTHING;
COMMIT;
