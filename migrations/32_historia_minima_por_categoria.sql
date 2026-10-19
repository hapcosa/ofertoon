-- =============================================================================
-- MIGRATION 32 — Historia mínima por categoría, para no esperar los 30 días
-- =============================================================================
-- **Decisión del dueño del producto, 2026-10-19.** Las siete categorías conectadas
-- en octubre no publican nada porque no llegan a `MIN_DAYS = 30`, y faltan entre 11
-- y 18 días de pasadas. La instrucción fue explícita: que publiquen ya, aceptando
-- que los descuentos salgan mal calculados, porque el canal no tiene usuarios y
-- "se arreglarán solas una vez estén en su fecha de maduración".
--
-- ⚠️ **QUÉ SE ESTÁ ACEPTANDO, PARA QUE NADIE LO LEA COMO UN DEFAULT RAZONABLE**
-- `MIN_POINTS`/`MIN_DAYS` no son un umbral de calidad ajustable: son la diferencia
-- entre medir y no medir. Con 10 días de historia el p50 se calcula sobre ~20
-- puntos de dos semanas, así que:
--
--   * un SKU cuyo precio de lanzamiento se "descuenta" a los 10 días se publica
--     como oferta, que es el caso que la regla 5 del CLAUDE.md existe para atajar;
--   * la liquidación y el inflado son indistinguibles — no hay 60 días de piso
--     contra los que comparar;
--   * `discount_real` sigue siendo `1 − price/p50`, pero ese p50 es una opinión.
--
-- O sea el canal va a publicar descuentos **numéricamente falsos** durante unas
-- dos semanas. Está asumido y es reversible: nada se corrompe de forma permanente
-- porque la serie sigue acumulándose igual y los candidatos quedan en
-- `deal_candidates` con su motivo, así que el histórico se puede releer después.
--
-- 1. POR CATEGORÍA Y NO GLOBAL — y esto no es cosmético
-- Bajar `baselines.MIN_DAYS` habría sido una línea, y habría contaminado la única
-- medición que de verdad importa: `compute_baseline` es la MISMA función en el job
-- diario y en `pricing/backtest.py` (regla 2, no-look-ahead), así que el backtest
-- recalcularía las baselines de **todas** las categorías con 10 días. El Cyber
-- Monday del 5-7 de octubre se puede etiquetar desde el 5 de noviembre y es el
-- único evento de descuentos masivos reales de la serie; medirlo contra baselines
-- de dos semanas lo arruinaría.
--
-- Con la columna, las siete categorías viejas siguen en 30 y su calibración queda
-- intacta.
--
-- 2. EL BACKTEST SIGUE MIDIENDO CON 30, A PROPÓSITO
-- `replay_listing` no lee esta columna. No es un olvido: las categorías nuevas no
-- tienen 30 días de futuro para etiquetar, así que el backtest sobre ellas no
-- produce nada medible de todos modos. Cuando maduren y esto vuelva a 30,
-- producción y backtest coinciden otra vez sin tocar nada.
--
-- 3. UNA SOLA PALANCA: DÍAS
-- Se exige el mismo número de puntos que de días (1 observación/día mínimo), igual
-- que el default de 30/30. Con 2 pasadas diarias, 10 días son ~20 puntos.
--
-- 4. CUÁNDO REVERTIR — cada categoría alcanza los 30 días por su cuenta
-- Medido el 2026-10-19 por días calendario distintos de historia, ya descontado el
-- agujero del 14 al 18 de octubre:
--
--     deporte-calzado         19 días  → 30 días ~30-oct
--     deporte-equipamiento    19       → ~30-oct
--     deporte-vestuario       18       → ~31-oct
--     ropa-accesorios         13       → ~5-nov
--     ropa-calzado            13       → ~5-nov
--     supermercado            13       → ~5-nov
--     tecno-audio             12       → ~6-nov
--
-- Dejar esto puesto después de esas fechas no "mantiene el canal activo": lo deja
-- publicando contra un p50 de dos semanas cuando ya hay uno de ocho, que es peor
-- que el estado de partida. La reversión es:
--
--     UPDATE categories SET min_history_days = 30;
--
-- y conviene hacerla toda junta el 2026-11-06, cuando la última llegue.
-- =============================================================================

BEGIN;

ALTER TABLE categories
    ADD COLUMN IF NOT EXISTS min_history_days SMALLINT NOT NULL DEFAULT 30;

COMMENT ON COLUMN categories.min_history_days IS
    'Días calendario distintos de historia que exige el detector para aceptar en '
    'esta categoría (y la misma cifra de observaciones). Default 30 = '
    'baselines.MIN_DAYS. Bajarlo hace que el descuento se mida contra un p50 que '
    'no significa nada: es una palanca temporal, no un ajuste de calidad. '
    'Ver la migración 32.';

ALTER TABLE categories
    ADD CONSTRAINT categories_min_history_sane
    CHECK (min_history_days BETWEEN 5 AND 60);

-- Las siete conectadas en octubre. 10 días es lo que hace que la mayoría de sus
-- listings tenga algo: medido, van de 12 a 19 días de historia máxima.
UPDATE categories SET min_history_days = 10
 WHERE slug IN (
        'tecno-audio',
        'ropa-calzado',
        'ropa-accesorios',
        'supermercado',
        'deporte-calzado',
        'deporte-vestuario',
        'deporte-equipamiento'
       );

COMMIT;

-- Reversión, toda junta, el 2026-11-06:
--   UPDATE categories SET min_history_days = 30;
