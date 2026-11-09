-- =============================================================================
-- MIGRATION 48 — Un solo piso de historia mínima: 20 días
-- =============================================================================
-- Decisión del dueño del 2026-11-06: **`min_history_days = 20` para TODAS las
-- categorías**, elegida explícitamente sobre dos alternativas que se le
-- plantearon con los números a la vista (dejarlas en 30, o bajar solo las de
-- tiendas recién conectadas).
--
-- 1. QUÉ ESTABA PASANDO, Y POR QUÉ NO ES LO QUE PARECÍA
--
-- La excepción de la migración 32 puso siete categorías en `10` por decisión del
-- dueño en octubre, con reversión comprometida para el 2026-11-06. **Esa
-- reversión ya se hizo, a mano y sin migración**: medido el 2026-11-06, las 17
-- categorías estaban en 30 y ninguna migración aplicada las había movido (la 32
-- las deja en 10). O sea el `UPDATE categories SET min_history_days = 30` que
-- CLAUDE.md pedía se corrió por fuera.
--
-- Por eso esta migración **no sube ningún piso: baja los 17**. Es importante no
-- confundirla con la reversión de la 32, que ya ocurrió.
--
-- 2. QUÉ CAMBIA — las 17, todas de 30 a 20
--
--   belleza               30 -> 20     ropa-vestuario        30 -> 20
--   deporte-calzado       30 -> 20     supermercado          30 -> 20
--   deporte-equipamiento  30 -> 20     tecno-audio           30 -> 20
--   deporte-vestuario     30 -> 20     tecno-celulares       30 -> 20
--   ferre-herramientas    30 -> 20     tecno-componentes     30 -> 20
--   ferre-jardin          30 -> 20     tecno-notebooks       30 -> 20
--   hogar-electro         30 -> 20     tecno-tv              30 -> 20
--   ropa-accesorios       30 -> 20     viajes-tours          30 -> 20
--   ropa-calzado          30 -> 20
--
-- 3. LO QUE ESTO CUESTA, EXPLÍCITO
--
-- ⚠️ **Los θ dejan de tener respaldo medido.** Se calibraron contra el backtest
-- del 5-nov **con 30 días de historia mínima**, así que la precisión que se midió
-- entonces ya no describe lo que el detector hace con 20. Hay que volver a
-- correr el gate de F1 (precisión ≥80% con ≥3 ofertas/día) para saber dónde quedó
-- cada uno:
--
--     python -m pricing.backtest --from AAAA-MM-DD --to AAAA-MM-DD
--
-- El efecto esperado es **más volumen y algo menos de precisión**: con 20 días
-- más listings alcanzan el mínimo, y cada p50 descansa en menos observaciones.
-- Cuánto, se mide; acá no se supone.
--
-- Lo que NO cambia es la regla 1: un p50 de 20 días sigue siendo **nuestra**
-- medición del precio real del SKU, no el `price_normal` que declara la tienda.
-- Se acorta la ventana, no se cambia la fuente.
--
-- Las categorías con más llaves son las que más se mueven —`deporte-equipamiento`
-- (222), `deporte-vestuario` (211), `deporte-calzado` (106)— y son justamente las
-- de las tiendas conectadas en noviembre, que con 30 no habrían producido una
-- oferta hasta diciembre.
--
-- 4. POR QUÉ UNA MIGRACIÓN Y NO UN UPDATE A MANO
--
-- Porque esta columna decide si una oferta se publica, y un número así necesita
-- su por qué escrito y su fecha — que es exactamente lo que faltó en la
-- reversión del punto 1, y por lo que hubo que ir a medir la base para saber
-- cuál era el estado real. La 32 no se edita: ya está aplicada y `migrate.py`
-- guarda su checksum (regla 11).
--
-- `MIN_POINTS` y la constante `MIN_DAYS` del detector NO se tocan: esta columna
-- es la que manda por categoría y la que el detector lee.
-- =============================================================================

BEGIN;

UPDATE categories SET min_history_days = 20 WHERE min_history_days <> 20;

-- Guarda, no adorno: si mañana alguien agrega una categoría con otro default y
-- no lo piensa, que falle acá y no en el canal. El detector no tiene forma de
-- avisar que un p50 de cinco días es una opinión.
DO $$
DECLARE fuera INTEGER;
BEGIN
    SELECT count(*) INTO fuera FROM categories WHERE min_history_days <> 20;
    IF fuera > 0 THEN
        RAISE EXCEPTION 'quedaron % categoría(s) fuera de los 20 días', fuera;
    END IF;
END $$;

COMMIT;
