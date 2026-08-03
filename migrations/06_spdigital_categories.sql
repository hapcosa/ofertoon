-- =============================================================================
-- MIGRATION 06 — SP Digital: activación + llaves de categoría
-- =============================================================================
-- SP Digital corre Saleor. El `store_key` es el **id Saleor de la categoría en
-- base64** (`Q2F0ZWdvcnk6MTIzOA==` = `Category:1238`), tal como la tienda lo
-- publica en `defaultCategoryNameToIDMapping` de su `page-data.json`.
--
-- Un id inexistente devuelve `edges: []` con HTTP 200 y sin `errors`, así que
-- las 13 llaves de acá están verificadas una por una contra producción
-- (2026-07-31). El volumen es el de productos **con stock**, que es lo que el
-- adaptador pide (`stockAvailability: IN_STOCK`):
--
--     notebooks                 86      tarjeta-video-nvidia      39
--     memoria-ram-pc            55      procesador-intel          32
--     placa-amd                 46      pendrive                  29
--     ssd-unidad-estado-solido  43      memoria-ram-notebook      21
--     procesador-amd            21      placa-intel               19
--     hdd-disco-duro-mecanico   11      notebook-gamer             7
--     tarjeta-video-amd          7
--
-- Quedan FUERA a propósito:
--
--   * `iphone` (1 producto con stock) — por debajo del canario del runner
--     (CANARY_MIN_ITEMS = 5), marcaría la corrida como `partial` en cada pasada.
--     SP Digital no es una tienda de celulares.
--   * `monitor` (67) y `monitor-gamer` (52) — mismo criterio que en PC Factory y
--     Paris: un monitor no es un televisor ni un componente, y sin categoría
--     propia le tocaría un umbral de descuento equivocado.
--
-- OJO con el rate limit: el `robots.txt` de la tienda declara `Crawl-delay: 5`,
-- y el adaptador lo respeta con `rate_limit_rps = 0.2`. Son ~400 productos en 13
-- categorías: unos 3 minutos por pasada. No subir sin releer el robots.
--
-- IMPORTANT: idempotente. Segura de re-ejecutar.
-- =============================================================================

BEGIN;

INSERT INTO store_categories (store_id, category_id, store_key)
SELECT s.id, c.id, v.store_key
  FROM (VALUES
        -- Notebooks
        ('spdigital', 'tecno-notebooks',   'Q2F0ZWdvcnk6MTIzOA=='),  -- notebooks
        ('spdigital', 'tecno-notebooks',   'Q2F0ZWdvcnk6MTIyNA=='),  -- notebook-gamer
        -- Componentes
        ('spdigital', 'tecno-componentes', 'Q2F0ZWdvcnk6MTI5NA=='),  -- ssd
        ('spdigital', 'tecno-componentes', 'Q2F0ZWdvcnk6MTI5Mw=='),  -- hdd
        ('spdigital', 'tecno-componentes', 'Q2F0ZWdvcnk6MTI5MA=='),  -- memoria-ram-pc
        ('spdigital', 'tecno-componentes', 'Q2F0ZWdvcnk6MTI5MQ=='),  -- memoria-ram-notebook
        ('spdigital', 'tecno-componentes', 'Q2F0ZWdvcnk6MTI5Ng=='),  -- tarjeta-video-nvidia
        ('spdigital', 'tecno-componentes', 'Q2F0ZWdvcnk6MTI5Nw=='),  -- tarjeta-video-amd
        ('spdigital', 'tecno-componentes', 'Q2F0ZWdvcnk6MTI2Ng=='),  -- pendrive
        ('spdigital', 'tecno-componentes', 'Q2F0ZWdvcnk6MTI4Mw=='),  -- procesador-intel
        ('spdigital', 'tecno-componentes', 'Q2F0ZWdvcnk6MTI4NA=='),  -- procesador-amd
        ('spdigital', 'tecno-componentes', 'Q2F0ZWdvcnk6MTI4Ng=='),  -- placa-intel
        ('spdigital', 'tecno-componentes', 'Q2F0ZWdvcnk6MTI4Nw==')   -- placa-amd
       ) AS v(store_slug, category_slug, store_key)
  JOIN stores     s ON s.slug = v.store_slug
  JOIN categories c ON c.slug = v.category_slug
ON CONFLICT (store_id, category_id, store_key) DO NOTHING;

-- El adaptador pasó su contract test y la validación en vivo: se activa.
UPDATE stores SET is_active = TRUE WHERE slug = 'spdigital';

COMMIT;
