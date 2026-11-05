-- =============================================================================
-- MIGRATION 46 — La promoción de multicompra, persistida
-- =============================================================================
-- Decisión del dueño del 2026-11-05: **las promociones de más de un producto sí
-- van al canal, y el mensaje tiene que dejar claro que el ahorro es por cantidad
-- y no una rebaja por unidad.**
--
-- 1. POR QUÉ NO ALCANZABA CON PONERLO EN EL COPY
--
-- Medido sobre las **107 promociones de multicompra** de una raíz de Unimarc
-- (`research/2026-11-05/unimarc_precios.csv`): **en las 107 el precio unitario
-- publicado es IGUAL al de lista**. No hay descuento si compras una; el ahorro
-- de 13-20% existe solo comprando N:
--
--   2 x $1.000   unidad promo $500  vs publicado $600   -> 16,7% comprando 2
--   4 x $1.150   unidad promo $288  vs publicado $360   -> 20,1% comprando 4
--   3 x $1.000   unidad promo $333  vs publicado $390   -> 14,5% comprando 3
--
-- O sea con el numerador sin condición `discount_real ≈ 0` en las 107 y **ninguna
-- llegaría nunca a ser candidato**. Llevar la condición solo como texto del
-- mensaje no las hace publicables, porque el mensaje nunca se genera.
--
-- 2. QUÉ CAMBIA Y QUÉ NO
--
-- **No cambia la serie.** `price_effective` sigue siendo el precio unitario sin
-- condición, así que el `p50` se construye con precios comparables entre sí. Esto
-- es lo que mantiene la regla 1 intacta: la baseline sigue siendo nuestra propia
-- medición del precio de verdad.
--
-- **Cambia el numerador del descuento.** `pricing.detector.evaluate` compara
-- `promo.unitario` contra ese mismo `p50`, y el resultado significa "cuánto
-- ahorrás por unidad **si compras N** contra lo que esa unidad costó de verdad".
-- Las guardas de piso (`p10`) y de cooldown miran el mismo número, porque si el
-- ahorro se anuncia por unidad bajo promo, esas guardas tienen que juzgar ese
-- número y no otro.
--
-- ⚠️ **El numerador es condicionado y el denominador no**, así que este
-- `discount_real` **no es la misma métrica** que el del resto del canal. Entra al
-- mismo pool con el mismo θ por decisión del dueño, **y el copy declara la
-- condición**: eso no es cosmético, es lo que separa "4 x $1.000" de anunciar un
-- −17% que no existe comprando una unidad. Lo transporta
-- `Decision.por_cantidad` hasta `publisher/formatter.py`.
--
-- 3. POR QUÉ `qty` Y `total`, Y NO EL UNITARIO
--
-- `4 x $1.150` da **287,5** por unidad, y la regla 3 es CLP entero en todas las
-- capas. Se guardan los dos enteros que la tienda publica —la cantidad y lo que
-- se paga por ella— y el unitario queda **derivado** en
-- `scrapers.base.PromoCantidad.unitario`.
--
-- Es la misma naturaleza que el `pum` de la migración 34: una normalización a una
-- base para poder comparar, no un precio que alguien pague. Nadie paga $287,5.
-- Y por la misma razón no se redondea: redondear arriba o abajo cambiaría el
-- descuento que se publica.
--
-- 4. LOS TRES JUNTOS O NINGUNO
--
-- Mismo `CHECK` que el `pum`, y por el mismo motivo: una cantidad sin su total es
-- una condición sin precio, y un total sin su etiqueta es un número que el
-- suscriptor no puede interpretar. La etiqueta va **verbatim** (`"4 x $1.000"`)
-- porque es la condición que hay que leer, no un número a reformatear.
-- =============================================================================

ALTER TABLE price_points
    ADD COLUMN IF NOT EXISTS promo_qty   SMALLINT,
    ADD COLUMN IF NOT EXISTS promo_total NUMERIC(12, 0),
    ADD COLUMN IF NOT EXISTS promo_label VARCHAR(48);

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'price_points_promo_completa'
    ) THEN
        ALTER TABLE price_points
            ADD CONSTRAINT price_points_promo_completa CHECK (
                (promo_qty IS NULL AND promo_total IS NULL AND promo_label IS NULL)
             OR (promo_qty IS NOT NULL AND promo_total IS NOT NULL
                 AND promo_label IS NOT NULL AND promo_qty >= 2 AND promo_total > 0)
            );
    END IF;
END $$;

COMMENT ON COLUMN price_points.promo_qty IS
    'Unidades que exige la promoción de multicompra (>= 2). El ahorro es por '
    'cantidad y NO es rebaja unitaria: ver la migración 46.';
COMMENT ON COLUMN price_points.promo_total IS
    'CLP que se pagan por `promo_qty` unidades. El unitario es derivado y no se '
    'guarda: 4 x $1.150 da 287,5 y nadie paga eso.';
COMMENT ON COLUMN price_points.promo_label IS
    'La condición tal como la publica la tienda ("4 x $1.000"), verbatim. El copy '
    'la imprime siempre: sin ella el porcentaje sería una rebaja que no existe.';
