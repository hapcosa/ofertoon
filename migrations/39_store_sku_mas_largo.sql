-- =============================================================================
-- MIGRATION 39 — `listings.store_sku` de VARCHAR(64) a VARCHAR(255)
-- =============================================================================
-- **Arregla una falla en producción del 2026-11-04**, de la pasada de las 18:11:
-- las cinco llaves de Jumbo quedaron `failed` con `items_ok = 0` y este error:
--
--     StringDataRightTruncationError: value too long for type character varying(64)
--
-- La identidad de un producto de Cencosud es el **slug de su ficha** —su JSON-LD
-- no trae GTIN ni el `productId` interno, así que el slug es lo único estable que
-- queda— y los slugs de esa tienda son descriptivos y largos:
--
--     acondicionador-para-bebes-y-ninos-babyland-410-cc-manzanilla-extra-suave-
--     hipoalergenico-evita-lagrimas-para-cabellos-claros-272877      → 130 chars
--
-- Medido sobre los 4.816 SKUs de sus dos llaves de belleza:
--
--     largo máximo  130        sobre 64 chars   125 (2,6%)
--     p99            73        sobre 100          4
--     p50            41
--
-- 255 deja casi el doble de margen sobre el máximo observado. **Ensanchar un
-- `varchar` es un cambio de metadata en Postgres**: no reescribe la tabla ni
-- reconstruye el índice, así que es seguro de aplicar con el scraper corriendo —
-- que es justo lo que se hizo, para que Santa Isabel (que corría 13 minutos
-- después de Jumbo en la misma pasada) no fallara igual.
--
-- ⚠️ POR QUÉ NO LO ATRAPÓ LA VALIDACIÓN PREVIA, QUE ES LA LECCIÓN TRANSFERIBLE
-- El adaptador se validó con `python -m scrapers.runner --once --dry-run`, que
-- recorrió las llaves, parseó 186 productos y reportó "186 observaciones nuevas".
-- **`--dry-run` no escribe en la base**: `persist_batch` sale antes del INSERT. O
-- sea el camino que falló es exactamente el único que el dry-run no ejercita, y el
-- mensaje de éxito era idéntico al de una corrida que sí hubiera escrito.
--
-- Es el mismo patrón que la trampa de `db-migrate` sobre una imagen vieja
-- —"0 migración(es) aplicada(s)" es a la vez el mensaje de éxito y el de "tu
-- migración no existe acá"— y la contramedida es la misma: **verificar el efecto,
-- no el mensaje**. Para un adaptador nuevo eso significa una corrida que escriba
-- de verdad contra una base descartable, o mirar `scrape_runs.status` después de
-- la primera pasada real.
--
-- El daño de esta clase de error es desproporcionado y conviene saberlo:
-- `runner.BATCH_SIZE` es 100, así que el primer flush se lleva la categoría
-- entera a `failed` y **se pierde todo lo ya scrapeado de esa llave**, no solo el
-- producto del slug largo. Cinco llaves × ~3.300 productos quedaron sin una
-- observación por 2 caracteres de más.
--
-- No se le pone un guard de largo a `RawProduct` (como el que `Pum` tiene para su
-- etiqueta): con 255 contra un máximo medido de 130 el margen es amplio, y un
-- guard que rechazara el producto cambiaría una falla ruidosa por una pérdida
-- silenciosa, que es peor.
-- =============================================================================

BEGIN;

-- Metadata-only: no rewrite, no reindex. `listings_store_sku_unique`
-- (store_id, store_sku) sigue valiendo igual.
ALTER TABLE listings
    ALTER COLUMN store_sku TYPE VARCHAR(255);

COMMENT ON COLUMN listings.store_sku IS
    'Identidad del producto en la tienda. Para la familia Cencosud es el slug de '
    'la ficha, que es lo único estable que publican (sin GTIN ni id interno) y '
    'llega a 130 caracteres — de ahí los 255. Ver migración 39.';

COMMIT;
