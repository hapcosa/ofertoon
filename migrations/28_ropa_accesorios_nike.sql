-- =============================================================================
-- MIGRATION 28 — `ropa-accesorios`: los 272 SKUs de Nike que quedaron sin casa
-- =============================================================================
-- Pendiente explícito desde la migración 25 (Nike): `nike/accesorios` quedó
-- afuera porque no encajaba en ninguna categoría existente y meterla a la fuerza
-- habría hecho mentir a un nombre o a un θ.
--
--   * `deporte-equipamiento` (θ 0.250) son carpas, mochilas de trekking y
--     bastones. Un gorro no se comporta como una carpa.
--   * `deporte-vestuario` (θ 0.350) es ropa deportiva, y un calcetín o una
--     riñonera no son vestuario: el nombre de la categoría aparece en el copy.
--
-- Decidido el 2026-10-01: categoría propia, en el prefijo `ropa-*` que la
-- migración 24 abrió.
--
-- 1. LO MEDIDO EL 2026-10-01 CON EL ADAPTADOR REAL
--
--   llave  qué es              SKUs   ticket p50   mínimo    completitud
--   2/5    nike/accesorios      272     $26.990    $ 9.990    272/272  (exacta)
--   2/3    nike/calzado       1.188    $106.990    $34.990   1188/1188 (ya activa)
--   2/4    nike/ropa            930     $56.990    $19.990    930/930  (ya activa)
--
-- **Disjunta de las dos llaves ya activas**, verificado sobre los SKUs reales de
-- las tres (intersección 0, no muestreada: son los catálogos completos). Importa
-- porque `vtex_family` emite un listing por producto y dos llaves solapadas
-- escribirían dos `price_points` del mismo listing por pasada.
--
-- `6/29` (snkrs/accesorios) NO existe: devuelve cero productos y el adaptador lo
-- rechaza con `NotAListingPage`, que es exactamente lo que debe hacer. Solo entra
-- `2/5`.
--
-- 2. EL TICKET ES $26.990, NO $14.990 — EL HANDOFF ESTABA MAL
-- La nota que dejó este pendiente decía "ticket $14.990 — justo lo que al canal le
-- falta". Medido sobre los 272 SKUs, el p50 es **$26.990** y el mínimo $9.990. El
-- argumento de bajar el ticket sigue siendo válido (las 66 ofertas publicadas
-- tienen p50 $279.990) pero es menos espectacular de lo que decía la nota.
--
-- 3. θ = 0.350, COPIADO Y SIN EVIDENCIA PROPIA — Y HAY QUE DECIRLO ASÍ
-- La migración 24 fijó θ midiendo **el descuento que declara la tienda**: si un
-- 30% es precio de lista de cualquier martes, θ tiene que estar más arriba.
--
-- Ese método **no se puede aplicar acá**: Nike no declara `price_normal` en su
-- API. Medido sobre las cuatro llaves (accesorios, calzado, ropa y la raíz),
-- `con_dto = 0%` en todas: nunca manda un "antes" tachado.
--
-- Así que θ 0.350 es herencia de sus vecinos del prefijo (`ropa-calzado` y
-- `deporte-vestuario`) y no una medición. Queda explícito para que nadie lo lea
-- como calibrado: sale del backtest, igual que los otros doce.
--
-- Nota lateral que vale para el producto: que Nike no declare "antes" significa
-- que en esa tienda **no hay número de la tienda que contrastar**, o sea nada que
-- inflar. El descuento que publiquemos de Nike sale entero de nuestra baseline,
-- que es exactamente lo que el canal promete.
--
-- 4. VA AL TEMA `vestuario`
-- La migración 26 creó el tema Vestuario con `ropa-calzado` sola. Accesorios es
-- ropa, así que comparte tema y no suma uno nuevo. El tema sigue con cuota 2.
--
-- 5. QUÉ ESPERAR, Y CUÁNDO
-- No publica nada durante 30 días. Fecha de conexión 2026-10-01 (la misma que el
-- resto de Nike) → se evalúa el **2026-10-31** junto con las otras llaves de la
-- tienda, con `python -m scripts.aceptacion_tienda --store nike`.
--
-- Las llaves nuevas solo tienen efecto en la pasada SIGUIENTE: los targets se
-- cargan una vez al arrancar la pasada.
-- =============================================================================

BEGIN;

INSERT INTO categories (slug, name, discount_threshold) VALUES
    ('ropa-accesorios', 'Accesorios de vestir', 0.350)
ON CONFLICT (slug) DO UPDATE
    SET name = EXCLUDED.name;
    -- El θ NO se sobreescribe al re-correr: si alguien lo calibró, esta
    -- migración no puede pisarlo.

-- Al canal VIP y al tema Vestuario, donde ya vive `ropa-calzado`.
INSERT INTO telegram_tier_categories (tier_id, category_id, topic_id)
SELECT t.id, c.id, top.id
  FROM telegram_tiers t
  JOIN categories     c   ON c.slug = 'ropa-accesorios'
  LEFT JOIN telegram_topics top ON top.tier_id = t.id AND top.slug = 'vestuario'
 WHERE t.slug = 'vip'
ON CONFLICT (tier_id, category_id) DO UPDATE
    SET topic_id = COALESCE(EXCLUDED.topic_id, telegram_tier_categories.topic_id);

-- Ninguna tienda nueva: Nike ya está activa desde la migración 25.
INSERT INTO store_categories (store_id, category_id, store_key)
SELECT s.id, c.id, v.store_key
  FROM (VALUES
        -- nike/accesorios. Disjunta de `2/3` y `2/4`, verificado sobre los
        -- catálogos completos. `6/29` no existe y no entra.
        ('nike', 'ropa-accesorios', '2/5')
       ) AS v(store_slug, category_slug, store_key)
  JOIN stores     s ON s.slug = v.store_slug
  JOIN categories c ON c.slug = v.category_slug
ON CONFLICT (store_id, category_id, store_key) DO NOTHING;

COMMIT;

-- Fecha de conexión: 2026-10-01 → se evalúa el 2026-10-31.
