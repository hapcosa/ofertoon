-- =============================================================================
-- MIGRATION 22 — Prat: `herramientas-electricas` → `herramientas-y-maquinarias`
-- =============================================================================
-- La migración 15 eligió `herramientas-electricas` creyendo que era un paraguas.
-- No lo era: es una **vitrina curada a mano**, y el 2026-09-25 a las 16:28 (-03)
-- la tienda la reeditó. El efecto, medido el 2026-09-28 contra el catálogo real:
--
--   09-23..24   345-346 items     09-25   121-134     09-26..28   131 exacto
--
--   listings que la colección dejó de mostrar   246
--     …que SIGUEN a la venta en la tienda       240  (98%)
--     …borrados de verdad del catálogo            6
--
-- O sea que 240 series murieron por una decisión editorial del comerciante, no
-- porque los productos dejaran de existir. Verificado bajando el catálogo
-- completo (`/products.json`, 39 páginas, 9.466 variantes) y cruzando los SKUs.
--
-- NO FUE UN BUG DEL ADAPTADOR. Comprobado en vivo: `?limit=250&page=1` devuelve
-- 131 productos y `page=2` devuelve 0 — fin legítimo de catálogo, no tope de
-- paginación. El `updated_at` que la tienda publica en `collections.json` cae
-- exactamente en la corrida que se cayó.
--
-- LAS COLECCIONES DE PRAT NO SON JERÁRQUICAS, Y ESO IMPORTA
-- La migración 15 asumió el patrón habitual (paraguas ⊇ hojas). Acá no vale:
-- `herramientas-electricas` NO está contenida en `herramientas-y-maquinarias`
-- (solo 71 de sus 131 SKUs). Cualquier llave nueva de esta tienda hay que
-- verificarla sobre SKUs reales, no deducirla del nombre.
--
-- POR QUÉ EL PARAGUAS, MEDIDO
--
--   colección                     variantes   con stock
--   jardin (llave actual)                49    49 (100%)
--   herramientas-electricas             131    71  (54%)
--   herramientas-y-maquinarias        1.089 1.088 (100%)
--   catálogo completo de la tienda    9.466 6.698  (71%)
--
-- `jardin` y `herramientas-y-maquinarias` están **filtradas por disponibilidad**;
-- `herramientas-electricas` no. Eso explica la anomalía de Prat que estaba
-- anotada y sin medir: de sus 430 listings, los 204 sin baseline son EXACTAMENTE
-- los que nunca se observaron con stock, y los 204 caen en `ferre-herramientas`.
-- `ferre-jardin` tiene 49 de 49 con baseline. La llave sana ya estaba de ejemplo.
--
-- Consecuencias del cambio, todas verificadas el 2026-09-28:
--
--   * Pasa a observar 1.089 listings en vez de 131 (5 requests/pasada a 0,5 rps).
--   * Recupera 101 de los 240 SKUs vivos que la vitrina dejó de mostrar.
--   * Es disjunta de `jardin` (intersección: 0 SKUs) → no viola la regla de
--     solapamiento de CLAUDE.md.
--   * De los 131 actuales deja de observar 60, y son **exactamente los 60
--     agotados**: los 71 con stock están los 71 dentro del paraguas. No se pierde
--     ni una serie viva.
--   * Las series NO se reinician: `listings` es único por `(store_id, store_sku)`
--     y la llave no entra en esa identidad.
--
-- ⚠️ NO agregar `accesorios-herramientas-electricas` al lado de esta llave: está
-- contenida al 100% en el paraguas y duplicaría observaciones.
--
-- ⚠️ El `products_count` de `collections.json` NO sirve como total declarado para
-- un `CountingAdapter`: cuenta productos que no están publicados en el canal
-- online (150 declarados vs 131 servidos; 1.123 vs 1.089 en el paraguas). Usarlo
-- dejaría el canario en `partial` para siempre.
--
-- La llave vieja se desactiva en vez de borrarse: `scrape_runs` tiene 11 corridas
-- que la referencian por texto y el histórico tiene que seguir siendo legible.
--
-- IMPORTANT: idempotente. Segura de re-ejecutar.
-- =============================================================================

BEGIN;

UPDATE store_categories sc
   SET is_active = FALSE
  FROM stores s, categories c
 WHERE sc.store_id = s.id
   AND sc.category_id = c.id
   AND s.slug = 'prat'
   AND c.slug = 'ferre-herramientas'
   AND sc.store_key = 'herramientas-electricas';

INSERT INTO store_categories (store_id, category_id, store_key)
SELECT s.id, c.id, v.store_key
  FROM (VALUES
        ('prat', 'ferre-herramientas', 'herramientas-y-maquinarias')
       ) AS v(store_slug, category_slug, store_key)
  JOIN stores     s ON s.slug = v.store_slug
  JOIN categories c ON c.slug = v.category_slug
ON CONFLICT (store_id, category_id, store_key) DO UPDATE
    SET is_active = TRUE;

COMMIT;

-- El reloj de MIN_DAYS arranca de cero para los ~1.000 SKUs que entran hoy, así
-- que `python -m scripts.aceptacion_tienda --store prat` se evalúa a partir del
-- **2026-10-28**, no del 2026-10-23 que fijó la migración 15.
