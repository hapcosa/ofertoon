-- =============================================================================
-- MIGRATION 31 — Apagar dos llaves de SP Digital que la tienda vació
-- =============================================================================
-- `Category:1293` (tecno-componentes) y `Category:1493` (tecno-audio) devuelven
-- **cero productos** desde su API. Verificado el 2026-10-12 con el adaptador real:
-- las dos lanzan `NotAListingPage` y una llave de control (`Category:1284`) trae
-- sus 9 productos sin problema, así que no es la tienda caída ni el adaptador.
--
-- 1. CUÁNTO LLEVABAN ASÍ
--
--     Category:1293   0 ok / 14 failed en 7 días   nunca funcionó en la ventana
--     Category:1493   8 ok /  6 failed             último ok: 2026-10-09 15:42
--
-- O sea 1293 está rota desde antes de la ventana de observación y 1493 se cayó el
-- 9 de octubre. Las dos estuvieron fallando en **todas** las pasadas desde
-- entonces, dos veces por día.
--
-- 2. POR QUÉ APAGARLAS Y NO BUSCARLES EL ID NUEVO
-- Podría ser que la tienda renombrara la categoría y el id cambiara. No se
-- investiga porque no vale lo que cuesta: quedan 10 llaves sanas de
-- `tecno-componentes` y 3 de `tecno-audio` en esta tienda, así que el catálogo
-- perdido es marginal. Si la tienda las repuebla, el `is_active = true` las
-- devuelve sin más.
--
-- 3. LO QUE ESTO NO ARREGLA
-- El sistema **sí avisó**: el runner marcó `failed` las 20 corridas y la alerta de
-- la pasada las reportó cada vez. Nadie las leyó en diez días. Eso no es un
-- agujero de código y no se arregla con una guarda nueva — una llave que falla
-- siempre ya aparece en el resumen de cada pasada.
-- =============================================================================

BEGIN;

UPDATE store_categories sc
   SET is_active = FALSE
  FROM stores s
 WHERE s.id = sc.store_id
   AND s.slug = 'spdigital'
   AND sc.store_key IN (
        'Q2F0ZWdvcnk6MTI5Mw==',  -- Category:1293, tecno-componentes
        'Q2F0ZWdvcnk6MTQ5Mw=='   -- Category:1493, tecno-audio
       )
   AND sc.is_active;

COMMIT;

-- Para reactivarlas cuando la tienda vuelva a poblarlas:
--   UPDATE store_categories SET is_active = TRUE WHERE store_key IN (...);
-- Y recordar que su reloj de MIN_DAYS arranca de cero: los listings viejos de
-- esas categorías llevan días sin observarse.
