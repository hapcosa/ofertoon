-- =============================================================================
-- MIGRATION 33 — Alcohol de Tottus: vinos, licores y cervezas
-- =============================================================================
-- **Decisión del dueño del producto, 2026-10-19**: el canal publica alcohol. Era
-- la última pregunta abierta para completar Tottus (PLAN_SUPERMERCADO §6) y la
-- única razón por la que estas dos llaves estaban afuera — nunca fue un problema
-- técnico.
--
-- 1. VAN A `supermercado` Y NO A UNA CATEGORÍA NUEVA, Y ESTÁ MEDIDO
-- Mismo criterio que la migración 27: **una distribución de precio = una
-- categoría**. Medido el 2026-10-19 con 4 páginas por llave (~190 SKUs cada una,
-- porque la página 1 engaña):
--
--   llave               declara  ticket p50  con dto.  p50 dto.  declara >=25%
--   Vinos-y-licores      1.650     $1.875      33%       18%          13%
--   Cervezas               180     $5.490      54%       17%           7%
--   ── las 5 ya conectadas ──────────────────────────────────────────────────
--   Despensa             1.896     $2.690      23%       19%           3%
--   Aseo-y-Limpieza      1.073         —       43%       20%          14%
--   Mascotas               419         —       17%       22%           4%
--
-- El comportamiento es el mismo: descuento declarado con p50 17-20% y un 3-14% del
-- catálogo llegando a 25%. No hay dos poblaciones, así que θ 0.250 sirve igual y no
-- se crea un θ más sin calibrar.
--
-- 2. ENCAJA CON EL ARGUMENTO QUE JUSTIFICA EL SUPERMERCADO
-- La decisión de publicar ofertas de ticket bajo (PLAN_SUPERMERCADO §2) se apoya en
-- que son productos que se compran por varias unidades y se pueden guardar. El
-- alcohol es el caso extremo favorable: no se vence, se compra por caja, y el
-- `pum` viene en el 84% de los vinos y el **98%** de las cervezas — o sea el precio
-- por litro, que es exactamente la comparación que el comprador hace.
--
-- 3. COSTO
-- Vinos 1.650 → 35 páginas; Cervezas 180 → 4. Son **+39 requests por pasada**
-- sobre las ~452 actuales de la familia Falabella, y las dos entran completas en
-- `max_pages = 55`, así que llevan canario exacto por total declarado.
--
-- 4. QUÉ ESPERAR
-- Reloj de madurez desde HOY: estas dos llaves no publican nada hasta ~18 de
-- noviembre con `MIN_DAYS = 30`. La excepción `min_history_days = 10` de la
-- migración 32 aplica a `supermercado`, así que podrían aparecer antes — pero esa
-- excepción se revierte el 2026-11-06, antes de que estas llaves lleguen a 10 días
-- de historia con 10 observaciones. En la práctica: **empiezan a publicar a mediados
-- de noviembre**, no ahora.
--
-- Las llaves nuevas solo tienen efecto en la pasada SIGUIENTE.
-- =============================================================================

BEGIN;

INSERT INTO store_categories (store_id, category_id, store_key)
SELECT s.id, c.id, v.store_key
  FROM (VALUES
        -- 1.650 SKUs, ticket p50 $1.875. Es la llave más grande de Tottus después
        -- de Despensa; entra completa en la ventana (35 páginas de 55).
        ('tottus', 'supermercado', 'CATG27084/Vinos-y-licores'),
        -- 180 SKUs, ticket p50 $5.490 — el más alto del supermercado conectado.
        ('tottus', 'supermercado', 'CATG27083/Cervezas')
       ) AS v(store_slug, category_slug, store_key)
  JOIN stores     s ON s.slug = v.store_slug
  JOIN categories c ON c.slug = v.category_slug
ON CONFLICT (store_id, category_id, store_key) DO NOTHING;

COMMIT;

-- Fecha de conexión: 2026-10-19 → maduran ~2026-11-18.
