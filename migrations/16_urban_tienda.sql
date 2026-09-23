-- =============================================================================
-- MIGRATION 16 — Urban Comercial: alta de tienda + llave de categoría
-- =============================================================================
-- Primera tienda de la familia WooCommerce (`scrapers/stores/woo_family.py`),
-- que consume la Store API pública (`/wp-json/wc/store/v1/products`). El
-- `store_key` es el **id numérico** de la categoría, no el slug.
--
-- Es la primera tienda nueva que aporta identidad de producto: `attributes`
-- trae `EAN` y `Marca` cuando el comerciante los cargó. Medido en vivo el
-- 2026-09-23 sobre la categoría 27: 15 de 223 con EAN y 38 con marca. Poco,
-- pero más que la familia Shopify, que no expone `barcode` en absoluto.
--
-- POR QUÉ UNA SOLA CATEGORÍA
-- La taxonomía de esta tienda mezcla categorías reales con marcas (`einhell`
-- 195, `dewalt` 135) y promociones (`10off` 18), que contienen los MISMOS
-- productos que las de catálogo. Conectar dos categorías que se solapan produce
-- dos `price_points` por pasada para el mismo listing y lo hace pesar doble en
-- su propio p50 — ver la nota extendida en `15_prat_tienda.sql`.
--
-- La candidata que quedó afuera es `accesorios-herramientas` (id 36, 274
-- productos): comparte 5 de cada 100 SKUs con la 27, y además son consumibles
-- (discos, brocas, puntas) de precio unitario bajo, donde un 25% de descuento
-- son unos pocos miles de pesos. El ranker todavía no tiene piso absoluto de
-- ahorro en CLP, así que los ordenaría por encima de ofertas que ahorran diez
-- veces más. Si se conecta más adelante, hay que resolver antes el solapamiento.
--
-- IMPORTANT: idempotente. Segura de re-ejecutar.
-- =============================================================================

BEGIN;

INSERT INTO stores (slug, name, base_url, adapter, rate_limit_rps, is_active) VALUES
    ('urban', 'Urban Comercial', 'https://urbancomercial.cl',
     'scrapers.stores.woo_family:UrbanAdapter', 0.5, TRUE)
ON CONFLICT (slug) DO UPDATE
    SET name     = EXCLUDED.name,
        base_url = EXCLUDED.base_url,
        adapter  = EXCLUDED.adapter;

INSERT INTO store_categories (store_id, category_id, store_key)
SELECT s.id, c.id, v.store_key
  FROM (VALUES
        ('urban', 'ferre-herramientas', '27')
       ) AS v(store_slug, category_slug, store_key)
  JOIN stores     s ON s.slug = v.store_slug
  JOIN categories c ON c.slug = v.category_slug
ON CONFLICT (store_id, category_id, store_key) DO NOTHING;

COMMIT;

-- Esta tienda no tiene catálogo de jardín: la única categoría del rubro es
-- `desbrozadora`, con 1 producto. Urban alimenta solo `ferre-herramientas`.
--
-- Fecha de conexión: 2026-09-23 → se evalúa el 2026-10-23.
