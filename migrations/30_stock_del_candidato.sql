-- =============================================================================
-- MIGRATION 30 — Verificación de stock del candidato, antes de publicar
-- =============================================================================
-- `in_stock` es ciego en Paris, Falabella, Sodimac y Tottus: el listado no dice
-- nada de disponibilidad y el adaptador lo asume `True`. La guarda de stock del
-- detector (`reject_reason = 'out_of_stock'`) no protege nada en esas cuatro, que
-- son 22.000 de los 35.000 listings.
--
-- La ficha SÍ lo dice, y verificarla solo para el candidato cuesta 10-30 fetches
-- por día en vez de los 22.000 que costaría en la ingesta.
--
-- 1. CUÁNTO DEL PROBLEMA ES REAL: 2,5%
-- Medido el 2026-10-02 sobre los 40 candidatos aceptados más recientes de
-- Falabella y Sodimac, abriendo la ficha de cada uno: **39 disponibles, 1
-- agotado**, y señal legible en los 40 (ninguna ficha sin dato).
--
-- O sea esto no tapa un agujero masivo: es un pulido de ~1 oferta cada 5 días a
-- la cuota actual. Se hace igual porque lo que el canal vende es que la oferta sea
-- real, y una oferta que no se puede comprar es el peor error posible justo en esa
-- promesa. Pero la expectativa queda escrita para que nadie espere un salto de
-- precisión en el backtest: **el detector ya acierta en el 97,5% de los casos por
-- este eje**.
--
-- 2. POR QUÉ SE PERSISTE Y NO SE VERIFICA AL VUELO
-- El daemon despierta cada 300 s y un candidato vive hasta 13 h
-- (`ranker.MAX_AGE_HOURS`). Sin registrar el resultado, un candidato agotado se
-- re-verificaría en cada vuelta: ~150 fetches de la misma ficha, que es seis veces
-- el presupuesto diario entero. Con estas dos columnas se verifica **una vez por
-- candidato**.
--
-- Y de paso queda el dataset, que es la regla 7 del CLAUDE.md aplicada a esto:
-- cuántos aceptados estaban agotados es medible a posteriori, por tienda y por
-- categoría, en vez de ser una impresión.
--
-- 3. NO SE TOCA `verdict` NI `reject_reason`
-- El candidato **fue** aceptado por el detector: eso es un hecho del histórico y
-- cambiarlo rompería la comparabilidad que la regla 7 protege, además de mover el
-- numerador del backtest por una razón que no es la señal. La disponibilidad es
-- una capa de publicación, no una corrección de la detección.
--
-- 4. `NULL` NO BLOQUEA
-- Tres estados distintos y a propósito:
--
--     NULL   no se verificó, o la tienda no tiene verificador, o falló la red
--     TRUE   la ficha dice que hay stock
--     FALSE  la ficha dice que está agotado
--
-- Solo `FALSE` impide publicar. Un fallo de red o una tienda sin verificador NO
-- pueden silenciar el canal: el costo de publicar una oferta agotada es menor que
-- el de dejar de publicar porque una ficha no respondió. `stock_checked_at`
-- distingue "no se intentó" de "se intentó y no se supo".
-- =============================================================================

BEGIN;

ALTER TABLE deal_candidates
    ADD COLUMN IF NOT EXISTS stock_ok BOOLEAN,
    ADD COLUMN IF NOT EXISTS stock_checked_at TIMESTAMPTZ;

COMMENT ON COLUMN deal_candidates.stock_ok IS
    'Disponibilidad leída de la ficha antes de publicar. NULL = no se sabe (no se '
    'verificó, sin verificador para la tienda, o falló la red) y NO bloquea. '
    'Solo FALSE impide publicar. Ver la migración 30.';

-- Para que el ranker descarte los agotados sin escanear la tabla: son pocos y
-- la query los filtra en cada vuelta del daemon.
CREATE INDEX IF NOT EXISTS idx_deal_candidates_sin_stock
    ON deal_candidates (listing_id) WHERE stock_ok IS FALSE;

COMMIT;
