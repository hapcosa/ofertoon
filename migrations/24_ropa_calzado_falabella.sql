-- =============================================================================
-- MIGRATION 24 — `ropa-calzado`: zapatilla urbana, en una tienda ya conectada
-- =============================================================================
-- Fase 3b del plan (PLAN_TIENDAS §4bis). Viene de la misma observación de
-- producto del 2026-10-01 que la migración 23: el canal no daba ofertas de ropa,
-- zapatillas ni cosas chicas.
--
-- 1. LO QUE HABÍA: CALZADO OUTDOOR Y NADA MÁS
-- `deporte-calzado` tenía 393 listings de **una** tienda (Andesgear) y es calzado
-- outdoor. Zapatilla urbana no existía en el sistema. El plan la mandaba a Sparta
-- (~200 llaves de facetas porque su robots prohíbe query strings) y a
-- Decathlon/Nike/Adidas (403 hoy) — o sea, lejos y caro.
--
-- Resulta que **Falabella ya la tenía**, y Falabella ya está conectada. Cero
-- adaptadores nuevos, cero tiendas nuevas: igual que la 23.
--
-- 2. POR QUÉ CATEGORÍA NUEVA Y NO REUSAR `deporte-calzado`
-- PLAN_TIENDAS §4bis dice "decidir al conectar, no antes: si trae mayormente
-- zapatilla deportiva, reusar la categoría existente evita un θ nuevo sin
-- calibrar". Se midió, y la respuesta es que NO es deportiva. Sobre 250 productos
-- por llave, con tildes normalizadas:
--
--   cat2083/Zapatillas      100% calzado   66% moda/urbano   22% deportivo
--   cat690245/Botines-Mujer  99% calzado   60% moda/urbano    1% deportivo
--
-- `deporte-calzado` se llama "Calzado outdoor" y su θ=0.30 se eligió para ese
-- comportamiento. Meter acá zapatilla urbana y botín de vestir haría que el
-- nombre mienta y que un solo θ cubra dos comportamientos de precio distintos.
-- Va a `ropa-calzado`, que además abre el prefijo `ropa-*` que la Fase 3 ya
-- necesita.
--
-- 3. θ = 0.350 DE PARTIDA, SIN CALIBRAR — y no es un número copiado
-- Medido sobre el descuento que **declara la tienda** (no nuestra baseline; mide
-- con qué frecuencia pone el calzado "en oferta"):
--
--                        con dto.  p50   declaran >=30%   declaran >=35%
--   cat2083/Zapatillas      59%    30%    56% del catálogo   18%
--   cat690245/Botines       77%    38%    58% del catálogo   45%
--
-- O sea: **un 30% en calzado Falabella es precio de lista de cualquier martes**,
-- exactamente el argumento con el que la migración 21 puso `deporte-vestuario` en
-- 0.35. A 0.30 el umbral no filtraría nada. Sale del backtest, no de acá.
--
-- 4. DOS LLAVES, Y LAS OTRAS DOS SE DESCARTARON POR SOLAPAMIENTO
-- La tienda enlaza cuatro candidatas. Medido con 250 SKUs por llave:
--
--   cat2083/Zapatillas       vs Zapatillas-Hombre   19 SKUs en común  ( 7%)
--   cat2083/Zapatillas       vs Zapatillas-Mujer    52 SKUs en común  (20%)
--   Zapatillas-Hombre        vs Zapatillas-Mujer    12 SKUs en común  ( 4%)
--   cat2083/Zapatillas       vs Botines-Mujer        0                ✓
--
-- `cat2083/Zapatillas` **es el paraguas** de Hombre y Mujer, así que entra el
-- paraguas y no las hojas. Y Hombre/Mujer solapan entre sí (zapatilla unisex
-- listada en los dos árboles, igual que en Andesgear) — pero acá eso NO es
-- inocuo: `FalabellaAdapter` **no tiene `dedupe_across_categories`**, eso es del
-- adaptador Magento de Andesgear. Con las dos llaves, 12 SKUs escribirían dos
-- `price_points` por pasada y pesarían el doble en su propio p50.
--
-- 5. DISJUNCIÓN CONTRA LO YA ACTIVO: VERIFICADA
-- `cat2083/Zapatillas` con 200 SKUs tiene intersección **0** contra las 6 llaves
-- activas de Falabella (`Smartphones`, `Audifonos` de la migración 23,
-- `Notebooks`, `Smart-TV`, `Almacenamiento`, `Refrigeradores`).
--
-- 6. ESTO ES LO QUE BAJA EL TICKET DEL CANAL
-- El problema medido era que de 9.729 baselines maduras el 72% está sobre
-- $150.000, y las 63 ofertas publicadas tienen ticket p50 $279.990. Estas dos
-- llaves traen:
--
--   cat2083/Zapatillas       ticket p50 $48.990   mínimo $9.990
--   cat690245/Botines-Mujer  ticket p50 $41.990   mínimo $7.990
--
-- 7. ⚠️ LA TRAMPA DE FALABELLA QUE LA MIGRACIÓN 23 DOCUMENTÓ APLICA ACÁ TAMBIÉN
-- Una llave con par id/nombre verosímil puede devolver HTTP 200, 60 productos, y
-- pasar la validación `NotAListingPage` con contenido de otra categoría (ver
-- migración 23 §5: `cat2049/Audifonos` devolvía impresoras). Por eso las dos
-- llaves de acá se verificaron **por contenido** —qué fracción de los nombres es
-- calzado— y no por status HTTP. El control negativo fue `cat1640002/Audifonos`:
-- 0% de calzado, como corresponde.
--
-- ⚠️ Y una advertencia sobre mi propio tamiz: la primera medición dio
-- "Botines-Mujer = 32% calzado" y era **un bug del clasificador**, no de la
-- llave: el patrón decía `botin` y los nombres son "Botín". Normalizar tildes
-- antes de comparar no es cosmético.
--
-- 8. QUÉ ESPERAR, Y CUÁNDO
-- **No publica nada durante 30 días** (`MIN_POINTS=30`/`MIN_DAYS=30` son un
-- rechazo, no un default). Fecha de conexión 2026-10-01 → se evalúa el
-- **2026-10-31** con `python -m scripts.aceptacion_tienda --store falabella`.
--
-- Las llaves nuevas solo tienen efecto en la pasada SIGUIENTE: los targets se
-- cargan una vez al arrancar la pasada.
--
-- ⚠️ Y acá la liquidación de temporada importa de verdad, no en abstracto: es
-- calzado de moda. Por suerte la decisión ya está tomada (§1.3, 2026-10-01: la
-- liquidación es una oferta y va al canal) y el backtest ya tiene
-- `LABEL_LIQUIDATION`, así que estas llaves nacen con el etiquetado correcto.
-- =============================================================================

BEGIN;

INSERT INTO categories (slug, name, discount_threshold) VALUES
    ('ropa-calzado', 'Calzado urbano y de vestir', 0.350)
ON CONFLICT (slug) DO UPDATE
    SET name = EXCLUDED.name;
    -- El θ NO se sobreescribe al re-correr: si alguien lo calibró, esta
    -- migración no puede pisarlo.

-- Al canal VIP, que hoy es el único con `telegram_channel_id`.
INSERT INTO telegram_tier_categories (tier_id, category_id)
SELECT t.id, c.id
  FROM telegram_tiers t
  JOIN categories c ON c.slug = 'ropa-calzado'
 WHERE t.slug = 'vip'
ON CONFLICT DO NOTHING;

-- Ninguna tienda nueva: Falabella ya está activa con su adaptador.
INSERT INTO store_categories (store_id, category_id, store_key)
SELECT s.id, c.id, v.store_key
  FROM (VALUES
        -- Paraguas de Zapatillas-Hombre y Zapatillas-Mujer: entra este y NO las
        -- hojas, que solapan con él y entre sí. Ver §4.
        ('falabella', 'ropa-calzado', 'cat2083/Zapatillas'),
        -- Disjunta de la anterior (0 de 250). Botín casual y de vestir.
        ('falabella', 'ropa-calzado', 'cat690245/Botines-Mujer')
       ) AS v(store_slug, category_slug, store_key)
  JOIN stores     s ON s.slug = v.store_slug
  JOIN categories c ON c.slug = v.category_slug
ON CONFLICT (store_id, category_id, store_key) DO NOTHING;

COMMIT;

-- Fecha de conexión: 2026-10-01 → se evalúa el 2026-10-31.
