-- =============================================================================
-- MIGRATION 42 — Colloky, y la categoría `ropa-vestuario` que faltaba
-- =============================================================================
-- `INVESTIGACION_ropa.md`. Colloky es la tienda **mejor medida de toda la Fase 0**
-- y entra con **cero líneas de adaptador**: `vtex_family` la cubre tal cual.
--
-- 1. POR QUÉ HAY QUE CREAR UNA CATEGORÍA PARA PODER CONECTARLA
--
-- Las 15 categorías del sistema tienen `ropa-calzado` y `ropa-accesorios`, y
-- **ninguna de vestuario**. La única de prendas es `deporte-vestuario`, y meter
-- ahí poleras y pantalones de niño mezclaría dos comportamientos de precio en un
-- solo θ — justo lo que la migración 24 manda separar.
--
-- Y no es un detalle: **`Ropa` es la raíz más grande de Colloky** (1.449 de sus
-- 3.530 SKUs). Sin la categoría nueva se conecta el 59% de la tienda.
--
-- θ de partida **0.350, heredado de `ropa-calzado` y `ropa-accesorios`** (las dos
-- en 0.350) y anotado como **herencia, no medición**. Se puede medir después:
-- Colloky declara `ListPrice > Price` en el **57,5%** de sus productos, así que
-- cuando se corra el backtest hay con qué. `min_history_days = 30`, el valor
-- correcto; **no se le pone la excepción de 10** que arrastran las siete
-- categorías de octubre.
--
-- ⚠️ **La alternativa que NO se tomó, para que quede el por qué.** Colloky es
-- íntegramente infantil y su ticket máximo es **$49.990**, así que se podría
-- haber creado `ropa-infantil` —una categoría por tienda, con su propio θ— en vez
-- de una de vestuario genérica. Se eligió `ropa-vestuario` porque:
--   a) una categoría que es "la tienda X" no escala: la próxima tienda de ropa de
--      niño tendría que entrar ahí o crear otra;
--   b) el rango de ticket difiere ~3× contra `ropa-calzado`, no 100× como pasó
--      con el supermercado, que es el precedente que justificó destino propio.
-- ⚠️ Lo que ese ticket chico **sí** deja abierto es el score: `compute_score` es
-- `discount_real*100 + below_floor*50` y no mira el precio absoluto, así que un
-- 30% sobre unas zapatillas de niño de $25.990 ($7.800 de ahorro) puntúa igual
-- que un 30% sobre un notebook. Es decisión de producto y no se toca el score.
--
-- 2. LAS LLAVES: SEIS, Y SON UNA PARTICIÓN DE VERDAD
--
-- Enumeré **el catálogo completo** (120 requests) y crucé los `productId`:
--
--   raíz             declarado  enumerado único
--   1  Calzado          1.273      1.273
--   2  Escolar            181        181
--   3  Ropa             1.449      1.449
--   4  Accesorios         627        627
--   5  Outlet           2.370      2.368
--
-- Las cuatro primeras tienen **cero solape entre sí** y suman **3.530**, que es
-- exactamente la unión. El árbol de Colloky es una partición real.
--
-- 🔴 **`Outlet` NO entra.** Sus 2.368 SKUs están **100% contenidos** en las otras
-- cuatro raíces: **cero exclusivos**. Solapa 76% con Calzado, 67% con Ropa, 61%
-- con Escolar y 52% con Accesorios. Conectarla haría pesar el doble a 2.368
-- listings —el 67% del catálogo— en su propio p50.
--
-- **`Escolar` entra por sus tres hijos y no por la raíz**, porque la raíz mezcla
-- tres categorías internas. Medido el 2026-11-05: los hijos son una **partición
-- perfecta** de la raíz —59 + 56 + 66 = 181 exacto, cero solape entre los tres y
-- cero productos fuera de ellos— así que partirla no pierde ni duplica nada.
--
-- 3. LO QUE YA ESTÁ VERIFICADO Y NO HACE FALTA VOLVER A MEDIR
--
-- a) **Orden estable**: dos recorridos completos de `Calzado` separados por 30 s
--    dieron **Jaccard = 1,0000** — 1.331 filas → 1.331 únicos en los dos, cero
--    duplicados internos y cero SKUs exclusivos de uno u otro.
-- b) **Canario exacto viable**: el total viene en el header `Resources` y
--    coincidió exacto en las cuatro raíces. Y sigue la deriva: el catálogo creció
--    de 1.273 a 1.331 en un día y el declarado lo acompañó, que es justo lo que
--    descalifica al canario exacto en Cencosud y en la familia Falabella.
-- c) **`MAX_OFFSET` no es problema**: ningún nodo del árbol pasa los 2.500 de
--    VTEX (el mayor era Outlet con 2.370, y queda afuera). No hay que bajar a
--    subcategorías como en Nike.
-- d) **`rate_limit_rps = 0.5`**: su `robots.txt` tiene 7 `Disallow`, sin
--    `Crawl-delay`, y **ninguno toca `/api/catalog_system/`**. 256 requests entre
--    las dos corridas, cero 403 y cero 429.
--
-- 4. DOS COSAS QUE HAY QUE SABER Y NO SON BLOQUEANTES
--
-- ⚠️ **GTIN al 99,8%** (3.174 de 3.180 productos muestreados), la cobertura más
-- alta de cualquier tienda del sistema. **No esperar que desbloquee el copy
-- cross-store**: está medido que el cuello no es la cobertura sino el
-- solapamiento, y Colloky es ropa y calzado **infantil** — las grandes que
-- venderían lo mismo (Falabella, Paris) no exponen GTIN en el listado. Lo más
-- probable es que siga dando cero mensajes.
--
-- ⚠️ **`in_stock` es una constante, no una señal**: `AvailableQuantity > 0` en el
-- **100%** de los 3.180 productos. La API no devuelve agotados: desaparecen del
-- listado en vez de marcarse. Para la serie es benigno (queda un hueco, y
-- `compute_baseline` filtra `if in_stock`), pero la guarda de stock del detector
-- **no protege nada** acá, igual que en Sparta.
--
-- 5. FECHAS
--
-- Conexión **2026-11-05**. No publica nada hasta el **2026-12-05**, y se evalúa
-- con `python -m scripts.aceptacion_tienda --store colloky` **el 2026-12-05**,
-- nunca antes — y contra días **observados**, no calendario.
--
-- Costo por pasada: **71 requests, ~200 MB, ~145 s**. Pesada en bytes (VTEX sirve
-- ~2,8 MB por página de 50) y la más barata en requests de la tanda.
-- =============================================================================

-- La categoría nueva. θ heredado de sus vecinas y anotado como tal.
INSERT INTO categories (slug, name, discount_threshold, min_history_days) VALUES
    ('ropa-vestuario', 'Ropa y Vestuario', 0.350, 30)
ON CONFLICT (slug) DO NOTHING;

-- Al tema Vestuario, donde ya van `ropa-calzado` y `ropa-accesorios`.
-- Aritmética de `CLAUDE.md`: el tema tiene `daily_quota = 5` y pasa de 2 a 3
-- categorías ruteadas, así que `categorías × MAX_PER_CATEGORY_PER_DAY` sube de
-- 2×3=6 a 3×3=9, holgado sobre la cuota. No hace falta tocar la cuota.
INSERT INTO telegram_tier_categories (tier_id, category_id, topic_id)
SELECT t.id, c.id, tp.id
  FROM telegram_tiers t
  JOIN categories c      ON c.slug = 'ropa-vestuario'
  JOIN telegram_topics tp ON tp.slug = 'vestuario' AND tp.tier_id = t.id
 WHERE t.id = 1
ON CONFLICT (tier_id, category_id) DO NOTHING;

INSERT INTO stores (slug, name, base_url, adapter, rate_limit_rps, is_active) VALUES
    ('colloky', 'Colloky', 'https://www.colloky.cl',
     'scrapers.stores.vtex_family:CollokyAdapter', 0.5, TRUE)
ON CONFLICT (slug) DO UPDATE
    SET name     = EXCLUDED.name,
        base_url = EXCLUDED.base_url,
        adapter  = EXCLUDED.adapter;

INSERT INTO store_categories (store_id, category_id, store_key)
SELECT s.id, c.id, v.store_key
  FROM (VALUES
        -- `store_key` = el path de ids de VTEX sin barras de los extremos.
        -- Partición verificada sobre el catálogo completo: cero solape.
        ('colloky', 'ropa-calzado',    '1'),      -- Calzado              1.273
        ('colloky', 'ropa-vestuario',  '3'),      -- Ropa                 1.449
        ('colloky', 'ropa-accesorios', '4'),      -- Accesorios             627
        -- Escolar entra por sus tres hijos: la raíz mezcla tres categorías
        -- internas y los hijos son partición perfecta de ella (59+56+66=181).
        ('colloky', 'ropa-accesorios', '2/8'),    -- Accesorios escolares    59
        ('colloky', 'ropa-vestuario',  '2/9'),    -- Ropa escolar            56
        ('colloky', 'ropa-calzado',    '2/10')    -- Zapatos escolares       66
        -- `5` Outlet (2.370) NO entra: 100% contenido en las otras raíces.
       ) AS v(store_slug, category_slug, store_key)
  JOIN stores     s ON s.slug = v.store_slug
  JOIN categories c ON c.slug = v.category_slug
ON CONFLICT (store_id, category_id, store_key) DO NOTHING;
