-- =============================================================================
-- MIGRATION 15 — Ferretería Prat: alta de tienda + llaves de colección
-- =============================================================================
-- Primera tienda de la familia Shopify (`scrapers/stores/shopify_family.py`) y
-- la primera del sistema con **stock real**: `variants[].available` viene en el
-- payload, así que la guarda de stock del detector por fin protege algo. En
-- Paris y Falabella `in_stock` se asume TRUE a ciegas.
--
-- El `store_key` es el handle de colección, el mismo que la tienda usa en su URL
-- (`/collections/herramientas-electricas`). Las dos llaves están verificadas
-- contra producción el 2026-09-23: 396 y 50 productos respectivamente.
--
-- POR QUÉ SOLO DOS COLECCIONES, DE LAS 247 QUE PUBLICA LA TIENDA
-- Las colecciones de Shopify se anidan y **se solapan**: medido sobre los SKUs
-- reales, `taladros` (22) y `sierras-electricas` (17) están contenidas por
-- completo en `herramientas-electricas`, y `piscinas-y-jardin` comparte 47 de
-- sus 49 SKUs con `jardin`.
--
-- Conectar dos colecciones que se solapan NO es redundancia inocua: el mismo
-- listing recibiría dos `price_points` por pasada (la PK es
-- `(listing_id, observed_at)` y cada categoría se scrapea en un instante
-- distinto), y `compute_baseline` saca el p50 de los puntos **crudos**. O sea
-- que el SKU duplicado pesaría el doble en su propia mediana — el mismo daño
-- que arregló `scripts/repair_oversampling.py` para el incidente de agosto.
--
-- Por eso las llaves elegidas son disjuntas entre sí (verificado: 0 SKUs
-- compartidos) y son los paraguas, no las hojas: cubren más catálogo sin
-- superponerse.
--
-- IMPORTANT: idempotente. Segura de re-ejecutar.
-- =============================================================================

BEGIN;

INSERT INTO stores (slug, name, base_url, adapter, rate_limit_rps, is_active) VALUES
    ('prat', 'Ferretería Prat', 'https://ferreteriaprat.cl',
     'scrapers.stores.shopify_family:PratAdapter', 0.5, TRUE)
ON CONFLICT (slug) DO UPDATE
    SET name     = EXCLUDED.name,
        base_url = EXCLUDED.base_url,
        adapter  = EXCLUDED.adapter;

INSERT INTO store_categories (store_id, category_id, store_key)
SELECT s.id, c.id, v.store_key
  FROM (VALUES
        ('prat', 'ferre-herramientas', 'herramientas-electricas'),
        ('prat', 'ferre-jardin',       'jardin')
       ) AS v(store_slug, category_slug, store_key)
  JOIN stores     s ON s.slug = v.store_slug
  JOIN categories c ON c.slug = v.category_slug
ON CONFLICT (store_id, category_id, store_key) DO NOTHING;

COMMIT;

-- Fecha de conexión: 2026-09-23. El criterio de aceptación
-- (`python -m scripts.aceptacion_tienda --store prat`) se evalúa a partir del
-- 2026-10-23, no antes: MIN_DAYS es un rechazo, no un default, y hasta esa
-- fecha la tienda da 0% por construcción.
