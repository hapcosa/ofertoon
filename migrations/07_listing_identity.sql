-- =============================================================================
-- MIGRATION 07 — Identidad cruda en `listings`: `gtin_raw` y `model_raw`
-- =============================================================================
-- Los adaptadores ya extraen GTIN y modelo (SP Digital del `metadata` de Saleor,
-- Paris del `masterVariant.ean`), pero no había dónde guardarlos: `products`
-- —que sí tiene las columnas— se puebla recién en F1 con `catalog/identity.py`,
-- y hasta entonces todos los `listings.product_id` son NULL.
--
-- El efecto era que en CADA pasada se descartaba el mejor insumo de matching
-- cross-store que existe, y a diferencia de un precio, el GTIN no se puede
-- recuperar hacia atrás: la serie histórica quedaría sin él para siempre.
--
-- Por eso van acá, en `listings`, y no se espera a F1. El sufijo `_raw` es
-- deliberado y sigue a `name_raw`/`brand_raw`: es lo que declaró la tienda, sin
-- normalizar. F1 los lee para construir `products.canonical_key`; el detector
-- no los mira nunca (usa la historia propia de cada listing).
--
-- IMPORTANT: idempotente. Segura de re-ejecutar.
-- =============================================================================

BEGIN;

-- VARCHAR(14) = el GTIN más largo que existe (GTIN-14). Cubre también EAN-13,
-- UPC-12 y EAN-8. Se guarda como texto, no numérico: los ceros a la izquierda
-- son significativos en un código de barras.
ALTER TABLE listings ADD COLUMN IF NOT EXISTS gtin_raw  VARCHAR(14);
ALTER TABLE listings ADD COLUMN IF NOT EXISTS model_raw VARCHAR(120);

-- El índice de GTIN es el que hace barato el matching cross-store de F1: la
-- pregunta es siempre "¿qué otras tiendas venden este mismo código?".
CREATE INDEX IF NOT EXISTS idx_listings_gtin_raw
    ON listings(gtin_raw) WHERE gtin_raw IS NOT NULL;

-- El fallback cuando no hay GTIN es (marca, modelo), igual que en `products`.
CREATE INDEX IF NOT EXISTS idx_listings_brand_model_raw
    ON listings(brand_raw, model_raw)
    WHERE brand_raw IS NOT NULL AND model_raw IS NOT NULL;

COMMIT;
