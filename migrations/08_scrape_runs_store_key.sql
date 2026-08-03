-- =============================================================================
-- MIGRATION 08 — `scrape_runs.store_key`: la unidad real de una corrida
-- =============================================================================
-- El runner ya abre una corrida por (tienda, categoría, store_key) —
-- `load_store_targets` devuelve una fila por `store_categories.store_key`— pero
-- `scrape_runs` solo guardaba (store_id, category_id). Con eso, corridas de
-- volúmenes incomparables quedaban indistinguibles: SP Digital / categoría 1
-- tiene una store_key que devuelve 88 items y otra que devuelve 7. Hay 11 pares
-- (tienda, categoría) con más de una store_key.
--
-- El canario relativo compara `items_seen` contra la mediana de las últimas
-- corridas del MISMO target; sin esta columna esa mediana mezclaría peras con
-- manzanas y el canario sería peor que inútil (marcaría `partial` lo sano y
-- dejaría pasar lo roto).
--
-- Las corridas anteriores quedan con `store_key` NULL y no se pueden reparar
-- hacia atrás: no hay registro de cuál de las store_keys fue cada una. La
-- baseline arranca de cero y se llena sola en ~1,5 días (2 pasadas/día).
--
-- IMPORTANT: idempotente. Segura de re-ejecutar.
-- =============================================================================

BEGIN;

ALTER TABLE scrape_runs ADD COLUMN IF NOT EXISTS store_key TEXT;

-- El índice sirve exactamente a la query del canario: últimas N corridas sanas
-- de un target, en orden descendente. Parcial en `status='ok'` porque una
-- corrida rota no puede ser referencia de volumen normal.
CREATE INDEX IF NOT EXISTS idx_scrape_runs_target_recent
    ON scrape_runs(store_id, category_id, store_key, started_at DESC)
    WHERE status = 'ok';

COMMIT;
