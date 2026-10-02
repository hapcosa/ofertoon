-- =============================================================================
-- MIGRATION 29 — Distinguir la corrida manual de la pasada programada
-- =============================================================================
-- La guarda de volumen (`runner.pasadas_flacas`, migración de código del
-- 2026-09-29) reconstruye "la pasada" agrupando `scrape_runs` por el hueco entre
-- corridas. Eso funciona para el loop del scraper, que corre todos los objetivos
-- cada 12 h, y **falla para una corrida manual**: un
-- `python -m scrapers.runner --once --store tottus` escribe 5 filas separadas de
-- la pasada anterior por más de `PASS_WINDOW`, así que la guarda las lee como una
-- pasada entera que escribió muy poco.
--
-- Pasó el 2026-10-01: diagnosticando Tottus, Nike y Prat a mano quedaron 13
-- corridas con 9.476 observaciones, y la guarda las reportó como pasada flaca
-- (ratio 0,57 contra una mediana de 16.750) junto al incidente real del 29-sep.
--
-- **El ruido aparece exactamente cuando la guarda tiene que estar limpia.** Uno
-- corre pasadas parciales a mano justo cuando está diagnosticando un problema, o
-- sea cuando va a leer esa alerta con atención; y el `PASS_VOLUME_LOOKBACK` de 14
-- pasadas hace que el falso positivo sobreviva una semana.
--
-- 1. POR QUÉ UNA COLUMNA Y NO UN UMBRAL
-- La alternativa era descartar las "pasadas" con pocas corridas: 13 de 152 no es
-- una pasada. Pero eso es un umbral inventado y, peor, apuntado al mismo lugar que
-- la guarda vigila: el modo de falla que la justificó fue una pasada que corrió
-- **67 de 129 objetivos**. Cualquier umbral que filtre 13 de 152 está a un cambio
-- de catálogo de filtrar también el incidente que hay que ver.
--
-- El runner, en cambio, **sabe con certeza** si corrió el universo completo o un
-- subconjunto: es `bool(only_store or only_category)`. Registrar ese hecho es
-- exacto y no hay nada que calibrar.
--
-- 2. LAS CORRIDAS PARCIALES SE EXCLUYEN ANTES DE AGRUPAR
-- `volumen_por_pasada` las filtra en el `WHERE`, no después: así una corrida
-- manual en el medio de la tarde no parte en dos la pasada programada que la
-- rodea. Lo que la guarda vigila es el volumen del loop contra sí mismo.
--
-- 3. SE MARCAN LAS 13 CORRIDAS MANUALES DEL 2026-10-01
-- No es reescribir historia por gusto: ese falso positivo está **vivo** en la
-- ventana de 14 pasadas y va a seguir reportándose hasta el 2026-10-08. La
-- ventana es la de las corridas manuales de esa sesión (20:30–21:00 UTC), que son
-- identificables sin ambigüedad: la pasada programada de ese día arrancó 15:16 y
-- la siguiente 03:16 del día 2.
-- =============================================================================

BEGIN;

ALTER TABLE scrape_runs
    ADD COLUMN IF NOT EXISTS is_partial_run BOOLEAN NOT NULL DEFAULT FALSE;

COMMENT ON COLUMN scrape_runs.is_partial_run IS
    'TRUE si la corrida vino de --store/--category y NO del universo completo. '
    'La guarda de volumen las excluye: no son pasadas.';

-- Las corridas manuales del 2026-10-01 (diagnóstico de Tottus, Nike y Prat).
-- Ver §3. Idempotente: re-correr no cambia nada.
UPDATE scrape_runs
   SET is_partial_run = TRUE
 WHERE started_at >= TIMESTAMPTZ '2026-10-01 20:30:00+00'
   AND started_at <  TIMESTAMPTZ '2026-10-01 21:00:00+00'
   AND NOT is_partial_run;

COMMIT;
