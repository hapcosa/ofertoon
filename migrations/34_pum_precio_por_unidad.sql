-- =============================================================================
-- MIGRATION 34 — El precio por unidad de medida (`pum`) en la serie
-- =============================================================================
-- Fase 1 de PLAN_SUPERMERCADO §2bis. El dato ya llega en el payload que
-- parseamos y hasta hoy se tiraba.
--
-- 1. POR QUÉ SE GUARDA
-- El supermercado rompe el supuesto de ticket del canal: su ahorro p50 proyectado
-- es ~$670 contra los $12.000-$220.000 del resto. La decisión del dueño del
-- producto (2026-10-19) fue que ese ahorro **sí vale**, porque son productos que
-- se compran por varias unidades y se pueden guardar. Lo que sostiene ese
-- argumento en el mensaje es el precio por unidad de medida: "el KG a $3.242
-- contra $4.600 habitual" es una decisión de stockear; "−30%" no lo es.
--
-- Es para el COPY, no para la señal. `discount_real` sigue saliendo de
-- `1 − price_today / p50_60d` y nada más: ni el detector ni el score ni las
-- baselines miran estas dos columnas (regla 1 del CLAUDE.md).
--
-- 2. CUÁNTO HAY, MEDIDO
-- Sobre 144 productos de tres llaves de Tottus (2026-10-19):
--
--     Despensa          48/48  con pum (100%)
--     Mascotas          48/48  (100%)
--     Aseo-y-Limpieza   42/48  (87%)
--     ─────────────────────────────────
--     TOTAL            138/144 (95%)
--
--     unidades: KG 72 · 10GR 32 · UN 17 · LT 11 · MT 4 · 100UN 1 · MR 1
--
-- Y en el alcohol de la migración 33: 84% de los vinos, 98% de las cervezas.
--
-- 3. DOS COLUMNAS Y NO UNA, Y LAS DOS JUNTAS O NINGUNA
-- `10GR` y `100UN` **no son errores**: la tienda elige la base para que el número
-- sea legible. O sea el número no significa nada sin su unidad, y dos `pum` de
-- bases distintas NO se comparan entre sí sin normalizar a una unidad común. De
-- ahí el CHECK: una fila con precio y sin etiqueta sería un número que nadie
-- puede interpretar, y una con etiqueta y sin precio no es nada.
--
-- 4. EL TECHO DE PLAUSIBILIDAD NO APLICA ACÁ, A PROPÓSITO
-- `MAX_PLAUSIBLE_CLP` protege la baseline del centinela de $99.999.999.999. El
-- `pum` no es un precio que alguien pague: es una normalización a una base que
-- puede ser más grande que el envase —un producto de una unidad con base `100UN`
-- da un `pum` cien veces su precio—, así que el mismo techo rechazaría datos
-- correctos. El centinela igual no entra: `price_effective` se descarta antes de
-- construir la observación, y con él su `pum`.
--
-- 5. COSTO DE APLICARLA
-- `ADD COLUMN` nullable sobre una tabla particionada es metadato (instantáneo) en
-- las 2.120.358 filas actuales. El CHECK sí recorre las particiones una vez;
-- todas las filas existentes tienen las dos columnas en NULL, así que pasa sin
-- excepciones — son unos segundos de ACCESS EXCLUSIVE y se aplica con el scraper
-- encendido sin más consecuencia que un lote que reintenta.
-- =============================================================================

BEGIN;

ALTER TABLE price_points
    ADD COLUMN IF NOT EXISTS pum_price NUMERIC(12,2),
    ADD COLUMN IF NOT EXISTS pum_label VARCHAR(16);

COMMENT ON COLUMN price_points.pum_price IS
    'Precio por unidad de medida que declara la tienda, en CLP enteros. Es para '
    'el copy del canal, NUNCA para la señal: discount_real sale solo de '
    'price_effective contra el p50. Sin sentido sin pum_label. Ver migración 34.';

COMMENT ON COLUMN price_points.pum_label IS
    'La base de medida que eligió la tienda (KG, LT, UN, 10GR, 100UN...). No es '
    'normalizable: dos pum de bases distintas no se comparan entre sí. '
    'Ver migración 34.';

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'price_points_pum_check'
    ) THEN
        ALTER TABLE price_points
            ADD CONSTRAINT price_points_pum_check
            CHECK ((pum_price IS NULL) = (pum_label IS NULL)
                   AND (pum_price IS NULL OR pum_price > 0));
    END IF;
END $$;

COMMIT;
