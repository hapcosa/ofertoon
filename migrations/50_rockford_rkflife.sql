-- =============================================================================
-- MIGRATION 50 — Rockford, catálogo Shopify oficial en rkflife.com
-- =============================================================================
-- Investigación y comandos reproducibles: research/2026-11-07/rockford.md.
-- Medición 2026-11-06. `rockford.cl` todavía falla verificación TLS, pero
-- `www.rkflife.com` tiene TLS válido y sirve el catálogo público Rockford.
-- No se desactiva TLS ni se usa evasión: cuatro solicitudes con el User-Agent
-- identificable del proyecto dieron 200/200/200/200 en la misma URL.
--
-- Cuatro raíces de navegación, todas recorridas hasta el final:
--   hombre-vestuario  1090 productos / 5184 variantes
--   mujer-vestuario    708 productos / 3355 variantes
--   calzado-hombre     530 productos / 4251 variantes
--   calzado-mujer      606 productos / 4172 variantes
--   total             2933 productos únicos / 16962 variantes
-- Solo un ID aparece dos veces, dentro de `ropa-vestuario`; ninguno cruza
-- categorías. `dedupe_across_categories` elimina esa doble observación.
-- Ningún producto tuvo diferencias de precio entre talles: una serie por
-- producto. `available` varía por talle y el fixture incluye uno enteramente
-- agotado; el parser emite `in_stock=false` para él. El 403 de Rockford no
-- describía la tienda vigente, sino un dominio viejo con TLS defectuoso.
--
-- No se usa `compare_at_price` como baseline. El detector compara solo contra
-- su propia serie de 60 días. El `vendor=rockfordcl` aparece incluso en una
-- prenda Columbia, así que el adaptador no lo trata como marca. No hay barcode
-- en las 16.962 variantes observadas: GTIN queda vacío.
--
-- El catálogo completo de rkflife.com puede incluir accesorios y otras líneas;
-- esta migración conecta solo estas cuatro raíces verificadas. Coste estimado
-- por pasada: 14 páginas con productos + 4 finales vacíos = 18 requests,
-- 18.256.001 bytes de JSON descomprimido (18,26 MB), ~36 s a 0,5 rps,
-- ~2.933 listings. Medido en otro recorrido completo el 2026-11-06.
--
-- La conexión NO ocurre al aplicar este archivo: la fecha de conexión es la
-- primera ingesta real de Rockford. Registrar esa fecha desde `scrape_runs` y
-- evaluar 30 días observados después con:
--   python -m scripts.aceptacion_tienda --store rockford
-- Hasta entonces `publish_enabled=false` deja acumular historial sin mensajes.
-- No se actualiza `publish_enabled` en el ON CONFLICT: una reaplicación no
-- puede volver a cerrar una tienda que el dueño abrió tras la aceptación.
-- Requiere la versión APLICADA de la migración 40 que crea esa columna. Este
-- worktree nace de main, cuyo archivo 40 está desactualizado: no ejecutar
-- `migrate.py` desde aquí ni desde un checkout sin la secuencia 47-49 completa.
-- =============================================================================

BEGIN;

INSERT INTO stores
    (slug, name, base_url, adapter, rate_limit_rps, is_active, publish_enabled)
VALUES
    ('rockford', 'Rockford (RKF Life)', 'https://www.rkflife.com',
     'scrapers.stores.rockford:RockfordAdapter', 0.5, TRUE, FALSE)
ON CONFLICT (slug) DO UPDATE SET
    name = EXCLUDED.name,
    base_url = EXCLUDED.base_url,
    adapter = EXCLUDED.adapter,
    rate_limit_rps = EXCLUDED.rate_limit_rps,
    is_active = EXCLUDED.is_active;

INSERT INTO store_categories (store_id, category_id, store_key)
SELECT s.id, c.id, v.store_key
FROM (VALUES
    ('rockford', 'ropa-vestuario', 'hombre-vestuario'),
    ('rockford', 'ropa-vestuario', 'mujer-vestuario'),
    ('rockford', 'ropa-calzado',   'calzado-hombre'),
    ('rockford', 'ropa-calzado',   'calzado-mujer')
) AS v(store_slug, category_slug, store_key)
JOIN stores s ON s.slug = v.store_slug
JOIN categories c ON c.slug = v.category_slug
ON CONFLICT (store_id, category_id, store_key) DO NOTHING;

COMMIT;
