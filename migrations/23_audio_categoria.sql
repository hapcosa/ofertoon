-- =============================================================================
-- MIGRATION 23 — `tecno-audio`: la categoría que faltaba en el plan
-- =============================================================================
-- No es una fase postergada: audio, audífonos y accesorios **no se mencionaban
-- en ninguna fase de PLAN_TIENDAS**. Era un hueco, y se detectó el 2026-10-01 a
-- partir de una observación de producto ("el canal no da ofertas de cosas chicas
-- como audífonos") que resultó exacta.
--
-- 1. QUÉ HABÍA ANTES, MEDIDO
-- 47 audífonos en 25.429 listings, 19 con baseline madura, **0 publicados**. Son
-- residuo incidental de `tecno-celulares` de Falabella y Paris: nadie los
-- scrapeaba a propósito. Con esa densidad no salen ni por casualidad.
--
-- Y el problema de fondo que esto corrige es de composición de catálogo, no de
-- ranking: de 9.729 baselines maduras, **72% está sobre $150.000** y solo 12% bajo
-- $50.000. Las 63 ofertas publicadas tienen ticket p50 $279.990.
-- `detector.compute_score` NO pondera por precio absoluto y está bien así
-- ("ponderar por ticket inundaría los canales de electrónica cara"): el pool
-- viene 6:1 en contra y eso se arregla con catálogo.
--
-- 2. ES LA FASE MÁS BARATA DEL PLAN: CERO ADAPTADORES NUEVOS
-- Las cuatro tiendas ya están conectadas y sus cuatro familias ya están
-- escritas. Esta migración es solo taxonomía + llaves.
--
-- 3. θ DE PARTIDA 0.20, SIN CALIBRAR — igual que los 10 existentes
-- Audio de consumo descuenta seguido, pero menos profundo que vestuario. Se
-- elige 0.20 (el de `hogar-electro`) y no 0.15 (tecno) porque el audífono
-- bluetooth de marca propia descuenta 15% cualquier martes. Sale del backtest, no
-- de acá.
--
-- ⚠️ Se eligió `tecno-audio` ACOTADA a audio y no una `tecno-accesorios` ancha
-- (teclado, mouse, cargador, powerbank) a propósito: un θ porcentual único sobre
-- cosas de $8.000 y de $400.000 no significa nada. Si se quiere accesorios, va
-- en su propia categoría con su propio θ.
--
-- 4. CADA LLAVE SE VERIFICÓ CONTRA PAYLOAD REAL CON SU PROPIO ADAPTADOR
-- No contra un HTTP 200, que en este plan ya engañó cuatro veces. Totales
-- medidos el 2026-10-01:
--
--   falabella  cat1640002/Audifonos          120 muestreados, 119 son audífonos (99%)
--   paris      elcAudAudifonos               60+ ("Audífonos Bluetooth Redmi Buds 6")
--   paris      elcAudParlantes               60+ ("Parlante Portatil Bluetooth Aiwa")
--   pcfactory  Audífonos In Ear              53
--   pcfactory  Audífonos Headset             42
--   pcfactory  Parlantes Portátiles          40
--   pcfactory  Parlantes PC                  11
--   spdigital  Audífonos          (1404)      7  con stock
--   spdigital  Audífonos Bluetooth(1405)     20  con stock
--   spdigital  Parlante Portátil  (1406)     25  con stock
--   spdigital  Barra y Sistema de Sonido(1493) 3 con stock
--
-- 5. ⚠️ FALABELLA MIENTE DE UNA FORMA NUEVA, Y CASI ENTRA ACÁ UNA LLAVE PODRIDA
-- `cat2049/Audifonos`, `cat1012/Audio` y `cat70028/Audio` devuelven **HTTP 200,
-- 60 productos, y pasan la validación `NotAListingPage` del adaptador** — pero el
-- contenido es *impresoras*, *soportes de TV* y *cámaras*. O sea: la guarda del
-- adaptador detecta la página con la forma equivocada, NO la página con la forma
-- correcta y el contenido equivocado. Si una de esas tres hubiera entrado, el
-- sistema habría construido series de precios de impresoras bajo `tecno-audio`
-- durante 30 días antes de que alguien lo notara.
--
-- El tamiz que las separó: contar qué fracción de los nombres coincide con la
-- categoría. La llave buena da 99%, estas tres ~0%, y el control
-- (`cat2083/Zapatillas`) da 0% como corresponde. **Hacer esa cuenta debería ser
-- parte del checklist de toda llave nueva**, no solo de las de audio.
--
-- La llave correcta salió de la navegación propia de la tienda (buscar
-- "audifonos" y leer los `/category/catNNN/Nombre` que ella misma enlaza), no de
-- adivinar el id.
--
-- 6. SP DIGITAL: SE USAN LAS HOJAS, NO EL PADRE
-- `Audio` (Category:1403) declara 3.622 productos, pero es el **padre** de 8
-- hojas e incluye cables, accesorios de micrófono y grabadoras. Se conectan solo
-- las 4 hojas de audio de consumo. Verificado que `Audio`, `Audio Profesional` y
-- `Mixers y Mesas de Sonido` son **hermanas level=1 bajo "Audio y Video"** (no
-- anidadas entre sí), y que las hojas son level=2 bajo `Audio`. Meter padre e
-- hijas a la vez habría escrito dos `price_points` del mismo listing por pasada.
--
-- Ojo con el número: 3.622 es SIN filtro de stock. El adaptador filtra
-- `stockAvailability: IN_STOCK`, y con eso las 4 hojas suman 55.
--
-- 7. DISJUNCIÓN VERIFICADA SOBRE SKUs REALES
-- Era obligatorio y el riesgo era concreto: los 47 audífonos que ya existían
-- entraron por `tecno-celulares`. Medido con 200 SKUs por llave,
-- `cat1640002/Audifonos` tiene **intersección 0** contra las 5 llaves activas de
-- Falabella (`Smartphones`, `Almacenamiento`, `Notebooks`, `Smart-TV`,
-- `Tarjetas-de-Memoria`).
--
-- 8. QUÉ ESPERAR, Y CUÁNDO
-- ~340 listings nuevos. **No publica nada durante 30 días**: `MIN_POINTS=30` y
-- `MIN_DAYS=30` son un rechazo, no un default. Fecha de conexión 2026-10-01 → se
-- evalúa el **2026-10-31** con `python -m scripts.aceptacion_tienda`, y su primera
-- oferta posible es de esa fecha en adelante.
--
-- Las llaves nuevas solo tienen efecto en la pasada SIGUIENTE: los targets se
-- cargan una vez al arrancar la pasada.
-- =============================================================================

BEGIN;

INSERT INTO categories (slug, name, discount_threshold) VALUES
    ('tecno-audio', 'Audio y audífonos', 0.200)
ON CONFLICT (slug) DO UPDATE
    SET name = EXCLUDED.name;
    -- El θ NO se sobreescribe al re-correr: si alguien lo calibró, esta
    -- migración no puede pisarlo.

-- Al canal VIP, que hoy es el único con `telegram_channel_id`.
INSERT INTO telegram_tier_categories (tier_id, category_id)
SELECT t.id, c.id
  FROM telegram_tiers t
  JOIN categories c ON c.slug = 'tecno-audio'
 WHERE t.slug = 'vip'
ON CONFLICT DO NOTHING;

-- Ninguna tienda nueva: las cuatro ya están activas con su adaptador.
INSERT INTO store_categories (store_id, category_id, store_key)
SELECT s.id, c.id, v.store_key
  FROM (VALUES
        -- Verificada 119/120 (99%). NO usar cat2049, cat1012 ni cat70028: ver §5.
        ('falabella', 'tecno-audio', 'cat1640002/Audifonos'),

        ('paris',     'tecno-audio', 'elcAudAudifonos'),
        ('paris',     'tecno-audio', 'elcAudParlantes'),

        -- PC Factory filtra por NOMBRE exacto de categoría, con tilde incluida.
        -- Un nombre que no existe devuelve HTTP 200 con totalElements=0.
        ('pcfactory', 'tecno-audio', 'Audífonos In Ear'),
        ('pcfactory', 'tecno-audio', 'Audífonos Headset'),
        ('pcfactory', 'tecno-audio', 'Parlantes Portátiles'),
        ('pcfactory', 'tecno-audio', 'Parlantes PC'),

        -- Hojas level=2 bajo `Audio`, nunca el padre (Category:1403): ver §6.
        ('spdigital', 'tecno-audio', 'Q2F0ZWdvcnk6MTQwNA=='),  -- Audífonos
        ('spdigital', 'tecno-audio', 'Q2F0ZWdvcnk6MTQwNQ=='),  -- Audífonos Bluetooth
        ('spdigital', 'tecno-audio', 'Q2F0ZWdvcnk6MTQwNg=='),  -- Parlante Portátil
        ('spdigital', 'tecno-audio', 'Q2F0ZWdvcnk6MTQ5Mw==')   -- Barra y Sistema de Sonido
       ) AS v(store_slug, category_slug, store_key)
  JOIN stores     s ON s.slug = v.store_slug
  JOIN categories c ON c.slug = v.category_slug
ON CONFLICT (store_id, category_id, store_key) DO NOTHING;

COMMIT;

-- Fecha de conexión: 2026-10-01 → se evalúa el 2026-10-31.
