-- =============================================================================
-- MIGRATION 14 — Idempotencia del detector: un candidato por observación
-- =============================================================================
-- F3 convierte al detector en un job programado, y un job programado se corre
-- dos veces. Hasta ahora nada impedía que la misma observación produjera dos
-- filas: `detected_at` guardaba el momento en que corrió el job, así que dos
-- corridas seguidas sobre el mismo `price_point` insertaban dos candidatos
-- idénticos con timestamps distintos.
--
-- El arreglo es semántico antes que técnico: `detected_at` pasa a ser el
-- `observed_at` de la observación evaluada — cuándo se vio ese precio, no
-- cuándo lo miramos. Con eso (listing_id, detected_at) identifica de verdad a
-- la unidad de decisión y el UNIQUE la protege.
--
-- Es el momento barato para hacerlo: `deal_candidates` está vacía. Si tuviera
-- historia con `detected_at` = hora del job, el índice podría fallar y habría
-- que decidir con qué fila quedarse.
--
-- Efecto secundario buscado: el detector puede usar `ON CONFLICT DO NOTHING` y
-- volverse re-ejecutable sin pensar. Correrlo dos veces después de una pasada
-- no duplica nada.
--
-- IMPORTANT: idempotente. Segura de re-ejecutar.
-- =============================================================================

BEGIN;

-- Se limpia primero cualquier duplicado preexistente para que la migración no
-- pueda fallar a mitad de camino en una base que sí tenga datos. Hoy no hay
-- ninguno; el DELETE es la red por si esta migración corre sobre una base que
-- estuvo escribiendo candidatos con el esquema viejo.
DELETE FROM deal_candidates AS dc
 WHERE EXISTS (
       SELECT 1 FROM deal_candidates AS other
        WHERE other.listing_id  = dc.listing_id
          AND other.detected_at = dc.detected_at
          AND other.id          > dc.id
 );

CREATE UNIQUE INDEX IF NOT EXISTS idx_deal_candidates_listing_detected
    ON deal_candidates(listing_id, detected_at);

COMMIT;
