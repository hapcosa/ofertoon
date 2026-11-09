-- =============================================================================
-- MIGRATION 53 — Piso de historia en 10 días, y las cinco tiendas al canal
-- =============================================================================
-- Decisión del dueño del 2026-11-07, con los números de la 48 y los de
-- `research/2026-11-06/BACKTEST_theta.md` delante: **`min_history_days = 10`
-- para las 17 categorías**, y **abrir al canal las cinco tiendas que estaban
-- acumulando historial sin publicar**.
--
-- El razonamiento es de período de prueba y conviene dejarlo escrito, porque la
-- regla 5 de CLAUDE.md dice lo contrario y hay que saber por qué se acepta:
-- **el servicio todavía no se ofrece a nadie** (cero suscriptores activos, una
-- sola membresía `expired`), así que lo que el canal publica hoy es material de
-- observación, no producto vendido. Y las series maduran solas: cada día que
-- pasa, el mismo listing se mide contra una baseline más larga sin que nadie
-- toque nada.
--
-- -----------------------------------------------------------------------------
-- 1. QUÉ CUESTA, MEDIDO Y NO SUPUESTO
-- -----------------------------------------------------------------------------
-- Esto ya pasó y está medido: la excepción de la migración 32 tuvo siete
-- categorías en 10 durante octubre, y lo que el canal publicó en esos días se
-- puede contar. Días distintos **con stock** en los 60 previos a `detected_at`,
-- que es lo que cuenta `compute_baseline`:
--
--     fecha        posts   n_days < 21   n_days < 30   n_days mínimo
--     2026-11-01      22         9            12            10
--     2026-11-03      25         9            12            10
--     2026-11-05      25         6            11            11
--     ---- migración 48: el piso pasa a 20 ----
--     2026-11-06      23         0             7            24
--     2026-11-07      22         2             5            20
--
-- O sea con el piso en 10, entre **5 y 11 publicaciones por día** se miden
-- contra un p50 de 10 u 11 días: unas 20 observaciones. La regla 5 lo llama
-- "una opinión" y no es una exageración — un SKU cuyo precio de lanzamiento se
-- "descuenta" a los diez días no tiene contra qué contrastarse.
--
-- Lo que esta migración acepta explícitamente es **volver a ese estado**, por
-- las dos razones de arriba. No es un descubrimiento nuevo ni una mejora: es
-- una concesión de volumen contra calidad de baseline, tomada a ojos abiertos
-- mientras no haya nadie pagando.
--
-- ⚠️ **Y por eso esta migración es la primera candidata a revertirse el día que
-- el canal se ofrezca.** La reversión es una línea:
--
--     UPDATE categories SET min_history_days = 20;
--
-- -----------------------------------------------------------------------------
-- 2. LAS CINCO TIENDAS, Y QUÉ ESPERABA CADA UNA
-- -----------------------------------------------------------------------------
-- `publish_enabled = FALSE` no era una sola cosa: cada tienda lo tenía por un
-- motivo distinto, y no todos los motivos son "le falta historia". Al abrirlas
-- se asume cada uno:
--
--   * `ripley`      — su recorrido es PARCIAL (907 de 917 medidos, y el canario
--                     reporta la brecha cada pasada). Su baseline va a tener
--                     huecos, y un hueco no es lo mismo que una serie corta.
--   * `pc-express`  — esperaba **validar stock en una ficha agotada**. Eso no se
--                     hizo. Ver el ⚠️ de abajo.
--   * `unimarc`     — conectada el 6-nov (migración 47), evaluación 2026-12-06.
--   * `rockford`    — conectada por la migración 50, tajada de cuatro raíces.
--   * `sparta`      — conectada por la migración 52, con techo de catálogo del
--                     24-27% porque su robots prohíbe paginar.
--
-- ⚠️ **Ninguna de las cinco tiene verificador de stock.** `publisher.stock.sabe_leer`
-- devuelve `True` solo para `FAMILIA_FALABELLA`, así que para estas cinco
-- `verificar` devuelve `None` — y "no saber no bloquea" (migración 30). El
-- `in_stock` que las protege es el que su propio adaptador lee del listado: si
-- lo lee mal, el canal publica un agotado y nada lo intercepta. Es el riesgo
-- que `pc-express` estaba esperando resolver.
--
-- -----------------------------------------------------------------------------
-- 3. LO QUE ESTA MIGRACIÓN NO CAMBIA
-- -----------------------------------------------------------------------------
--   * **Las fechas de aceptación siguen en pie como MEDICIÓN**, no como permiso:
--     `python -m scripts.aceptacion_tienda --store <slug>` el 2026-12-06 para
--     Unimarc y a los 30 días de la primera ingesta para Rockford y Sparta. Que
--     una tienda publique antes no vuelve informativo su resultado antes.
--   * **El default de `stores.publish_enabled` sigue siendo TRUE y las tiendas
--     nuevas siguen naciendo FALSE** (CLAUDE.md §Pasos 1 paso 6). Esta migración
--     abre cinco tiendas por nombre, no cambia la regla: una tienda conectada
--     mañana sigue necesitando que el dueño la abra a mano.
--   * **El backtest sigue midiendo con `MIN_DAYS = 30`**, así que el desfase con
--     producción pasa de 10 días a 20. Sigue sin tener consecuencia medible
--     hasta que las categorías tengan 30 días de futuro para etiquetar, pero el
--     signo importa y está escrito en la regla 5: el backtest es **más
--     exigente** que el detector, así que subestima el volumen que θ produce.
-- =============================================================================

BEGIN;

-- -----------------------------------------------------------------------------
-- El piso
-- -----------------------------------------------------------------------------
UPDATE categories SET min_history_days = 10 WHERE min_history_days <> 10;

-- -----------------------------------------------------------------------------
-- Las cinco tiendas, por nombre y nunca por barrido
-- -----------------------------------------------------------------------------
-- Por nombre a propósito: un `UPDATE stores SET publish_enabled = TRUE` sin
-- WHERE abriría también la próxima tienda que alguien conecte con FALSE a
-- propósito, y lo haría en silencio.
UPDATE stores
   SET publish_enabled = TRUE
 WHERE slug IN ('ripley', 'pc-express', 'unimarc', 'rockford', 'sparta')
   AND NOT publish_enabled;

-- -----------------------------------------------------------------------------
-- Verificación dentro de la transacción: el efecto, no el mensaje
-- -----------------------------------------------------------------------------
-- `migrate.py` dice "aplicada" con que el SQL no lance. Estas dos guardas
-- fallan la transacción si el efecto no es el esperado, que es la única forma
-- de que el mensaje signifique algo.
DO $$
DECLARE
    fuera   INTEGER;
    cerradas TEXT;
BEGIN
    SELECT count(*) INTO fuera FROM categories WHERE min_history_days <> 10;
    IF fuera > 0 THEN
        RAISE EXCEPTION 'migración 53: % categorías no quedaron en 10', fuera;
    END IF;

    SELECT string_agg(slug, ', ' ORDER BY slug) INTO cerradas
      FROM stores
     WHERE NOT publish_enabled
       AND slug IN ('ripley', 'pc-express', 'unimarc', 'rockford', 'sparta');
    IF cerradas IS NOT NULL THEN
        RAISE EXCEPTION 'migración 53: siguen sin publicar: %', cerradas;
    END IF;
END $$;

COMMIT;
