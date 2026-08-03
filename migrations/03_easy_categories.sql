-- =============================================================================
-- MIGRATION 03 — Easy: activación + llaves de categoría
-- =============================================================================
-- Easy (Cencosud) corre Next.js sobre VTEX. El `store_key` es un path del árbol
-- que la propia tienda publica en `pageProps.categoriesData`.
--
-- Las 8 llaves de acá están verificadas una por una contra producción
-- (2026-07-31): todas devuelven `serverProductsResponse` con 40 productos en la
-- página 1 y un `recordsFiltered` entre 47 y 140. Se eligieron espejando las
-- categorías que ya tienen Sodimac y Falabella, para que el matching cross-store
-- de F1 tenga contra qué comparar.
--
-- Se usan HOJAS del árbol. Un departamento de primer nivel (`herramientas`)
-- renderiza el template `/[department]`, que es CMS y no lista productos — el
-- adaptador lo rechaza con NotAListingPage.
--
-- IMPORTANT: idempotente. Segura de re-ejecutar.
-- =============================================================================

BEGIN;

INSERT INTO store_categories (store_id, category_id, store_key)
SELECT s.id, c.id, v.store_key
  FROM (VALUES
        ('easy', 'ferre-herramientas',
         'herramientas/herramientas-electricas/taladros-y-atornilladores'),
        ('easy', 'ferre-herramientas',
         'herramientas/herramientas-electricas/esmeriles'),
        ('easy', 'ferre-herramientas',
         'herramientas/herramientas-electricas/sierras-electricas'),
        ('easy', 'ferre-jardin',
         'herramientas/maquinaria-de-jardin/cortadoras-de-pasto'),
        ('easy', 'ferre-jardin',
         'herramientas/maquinaria-de-jardin/motosierras'),
        ('easy', 'hogar-electro',
         'electrohogar-y-climatizacion/refrigeracion/refrigeradores'),
        ('easy', 'hogar-electro',
         'electrohogar-y-climatizacion/lavado-y-planchado/lavadoras'),
        ('easy', 'hogar-electro',
         'electrohogar-y-climatizacion/electrodomesticos/microondas')
       ) AS v(store_slug, category_slug, store_key)
  JOIN stores     s ON s.slug = v.store_slug
  JOIN categories c ON c.slug = v.category_slug
ON CONFLICT (store_id, category_id, store_key) DO NOTHING;

-- El adaptador pasó su contract test y la validación en vivo: se activa.
UPDATE stores SET is_active = TRUE WHERE slug = 'easy';

COMMIT;
