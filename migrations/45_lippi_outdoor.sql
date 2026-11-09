-- =============================================================================
-- MIGRATION 45 — Lippi Outdoor: la primera tienda que emite por producto
-- =============================================================================
-- `INVESTIGACION_deporte_outdoor.md`. Entra con `shopify_family`, que ya existe
-- y ya está conectada a Ferretería Prat — pero con **dos flags nuevos** que esta
-- tienda motivó, los dos con el default intacto para Prat.
--
-- 1. `emitir_por_producto`: EN VESTUARIO LA VARIANTE ES EL TALLE
--
-- `shopify_family` emitía **una fila por variante**, y en ferretería eso es
-- correcto: una variante de Prat es otro litraje, con su propio precio y stock.
-- En Lippi la variante es el **talle**. Medido sobre el catálogo completo (19.297
-- filas de 117 colecciones):
--
--   **5,18 variantes por producto**, y de las 19.297 filas **solo 72 (0,37%)**
--   tienen precios distintos entre las variantes de su producto.
--
-- O sea el 99,63% de los productos tiene **un** precio para todos sus talles.
-- Emitir por variante crearía ~5,2 series **idénticas** por producto y lo haría
-- pesar cinco veces en cualquier agregado. Es la misma pregunta que
-- `vtex_family` ya había resuelto —ahí los `items` son los talles y se emite uno
-- por producto— y la regla de qué variante representa al producto se portó de
-- ahí: **la disponible más barata** (`_elegir_variante`).
--
-- ⚠️ El flag es **por tienda** y su default es `False`: cambiárselo a una tienda
-- ya conectada le cambia el `store_sku` a todos sus listings, o sea reinicia su
-- reloj de `MIN_DAYS` y tira su histórico. Prat sigue en el default.
--
-- 🟢 Y queda **confirmado sobre 19.297 filas que Lippi nunca muestra un producto
-- con todos los talles agotados** (`sin_ninguna_disponible = 0`): los oculta. Así
-- que con `emitir_por_producto`, `in_stock` **nunca va a dar `False`** acá, y por
-- eso esa rama de `_elegir_variante` se testea sintética.
--
-- 2. `dedupe_across_categories`: Y ES SEGURO POR UNA RAZÓN MEDIDA
--
-- Las 76 llaves de abajo dan **4.481 filas → 3.418 productos únicos (1,311×)**,
-- o sea no son disjuntas. Sin dedupe, el 31% de los listings escribiría **dos
-- `price_points` por pasada** y pesaría el doble en su propio p50.
--
-- Lo que hace seguro deduplicar es **dónde** cae ese solapamiento: de las 1.191
-- coincidencias medidas, **las 1.191 caen dentro de la misma categoría interna y
-- CERO cruzan categorías**. Cuál llave gana no cambia el θ contra el que se mide
-- el producto — la condición exacta que el precedente de Andesgear exige.
-- ⚠️ Si alguna vez se le agrega una llave que cruce dos categorías internas, esto
-- deja de ser inocuo.
--
-- 3. ⚠️ EL 429 DE ESTA TIENDA ES POR HEADERS, NO POR TASA
--
-- Es el **inverso exacto de Prat**, y me costó dos corridas descubrirlo.
-- Verificado aislando la variable, 4 intentos de cada juego:
--
--   DEFAULT_USER_AGENT      200, 200, 200, 200
--   BROWSER_USER_AGENT      200, 200, 429, 200
--   BROWSER_HEADERS         403, 403, 403, 403
--   BROWSER_HEADERS_JSON    429, 429, 429, 429
--
-- O sea **pasa el UA identificable con el sufijo `(+ofertascl-bot)`** y lo que
-- bloquea es parecerse a un navegador. Persiguiendo el 429 bajé el rps de 0,5 a
-- 0,33 y después a 0,08 y el 429 seguía (44 veces en una corrida), porque mis
-- barridos mandaban `BROWSER_USER_AGENT`. Con el UA correcto a **0,5 rps**: 117
-- colecciones, 161 requests, **0 errores**.
--
-- `LippiAdapter` **no define `_headers`** a propósito: hereda el `None` de la
-- familia. **No copiarle el `_headers` de `PratAdapter`** — en Prat es al revés y
-- copiarlo trae el 429 de vuelta. Su `robots.txt` además es permisivo
-- (`Allow: /`, 41 `Disallow` todos de carrito y filtros) y no declara
-- `Crawl-delay`.
--
-- 4. LAS LLAVES: LAS 76 HOJAS DE TIPO DE PRODUCTO
--
-- La navegación de Lippi tiene 117 colecciones en **tres ejes que se cruzan**:
-- segmento (hombre/mujer/niños + accesorios unisex), tipo de producto, y
-- actividad. Medido:
--
--   eje                  n   productos únicos        dup
--   hojas de tipo       76   **3.418 (95,4%)**     1,31×
--   actividad           20      2.807               1,72×
--   paraguas            21      3.570               2,80×
--
-- 🔴 **El eje de actividad NO entra**: 2.725 de sus 2.807 productos (**97,1%**) ya
-- están en las hojas de tipo. Aporta **82 productos exclusivos** y a cambio
-- duplicaría 2.725 series. Los paraguas tampoco (95,4% contenidos).
--
-- ⚠️ Y una corrección que vale para cualquiera que dimensione esta tienda:
-- **`products_count` de Shopify cuenta VARIANTES, no productos**. La colección
-- `poleras` declara 1.746 y enumerada da **342 productos**. El `all` de Lippi son
-- 16.406 **variantes** ≈ 3.100 productos, no 16.406.
--
-- 5. θ, STOCK Y COSTO
--
-- Las tres categorías ya existen y van al tema `deporte`. **No se toca θ.** Dato
-- para la calibración: 9.745 de 9.773 variantes traen `compare_at_price` pero
-- **solo 1.136 (11,6%) tienen `compare_at > price`**, y su distribución es un
-- abanico de tramos redondos —0,6 (32%), 0,7 (16%), 0,8 (11%), 0,9 (9%)—, o sea
-- promociones reales y **no** el `price/0.9` constante de Prat. θ se puede medir.
--
-- 🟢 **Stock real**: `available` por variante, 7.306 de 9.773 (74,8%) disponibles.
-- Es una de las pocas tiendas del sistema con señal de stock de verdad en el
-- listado.
--
-- 🔴 **GTIN: 0 de 9.773 variantes** traen `barcode`, consistente con Prat y Doite.
--
-- Costo: **~105 requests, ~3,5 min** por pasada (1,38 requests por colección
-- medido). Con las migraciones 41-44 la pasada queda en ~75 min; esta la lleva a
-- **~79 de los 120** de `db.PASS_WINDOW`.
--
-- 6. FECHAS
--
-- Conexión **2026-11-05**. No publica hasta el **2026-12-05**; se evalúa con
-- `python -m scripts.aceptacion_tienda --store lippi` ese día, contra días
-- **observados**.
-- =============================================================================

INSERT INTO stores (slug, name, base_url, adapter, rate_limit_rps, is_active) VALUES
    ('lippi', 'Lippi Outdoor', 'https://www.lippioutdoor.com',
     'scrapers.stores.shopify_family:LippiAdapter', 0.5, TRUE)
ON CONFLICT (slug) DO UPDATE
    SET name     = EXCLUDED.name,
        base_url = EXCLUDED.base_url,
        adapter  = EXCLUDED.adapter;

INSERT INTO store_categories (store_id, category_id, store_key)
SELECT s.id, c.id, v.store_key
  FROM (VALUES
        -- `store_key` = el handle de la colección. Son las 76 hojas de tipo de
        -- producto de su navegación vigente; el eje de actividad y los paraguas
        -- quedan afuera por contención (97,1% y 95,4%).
        ('lippi', 'deporte-calzado', 'botas'),                        --   19 prod
        ('lippi', 'deporte-calzado', 'botas-mujer'),                  --   17 prod
        ('lippi', 'deporte-calzado', 'botines'),                      --  297 prod
        ('lippi', 'deporte-calzado', 'botines-hombre'),               --  114 prod
        ('lippi', 'deporte-calzado', 'botines-mujer'),                --  112 prod
        ('lippi', 'deporte-calzado', 'botines-ninos'),                --   41 prod
        ('lippi', 'deporte-calzado', 'sandalias'),                    --   98 prod
        ('lippi', 'deporte-calzado', 'sandalias-hombre'),             --   39 prod
        ('lippi', 'deporte-calzado', 'sandalias-mujer'),              --   29 prod
        ('lippi', 'deporte-calzado', 'sandalias-ninos'),              --   30 prod
        ('lippi', 'deporte-calzado', 'zapatilla-hombre'),             --  134 prod
        ('lippi', 'deporte-calzado', 'zapatilla-mujer'),              --  122 prod
        ('lippi', 'deporte-calzado', 'zapatillas'),                   --  325 prod
        ('lippi', 'deporte-calzado', 'zapatillas-ninos'),             --   66 prod
        ('lippi', 'deporte-calzado', 'zapato-hombre'),                --   14 prod
        ('lippi', 'deporte-calzado', 'zapato-mujer'),                 --   23 prod
        ('lippi', 'deporte-calzado', 'zapatos'),                      --   51 prod
        ('lippi', 'deporte-calzado', 'zapatos-ninos'),                --   14 prod
        ('lippi', 'deporte-equipamiento', 'bananos'),                 --   11 prod
        ('lippi', 'deporte-equipamiento', 'bastones'),                --    1 prod
        ('lippi', 'deporte-equipamiento', 'bolsos'),                  --   23 prod
        ('lippi', 'deporte-equipamiento', 'carpas'),                  --   10 prod
        ('lippi', 'deporte-equipamiento', 'gorros'),                  --   33 prod
        ('lippi', 'deporte-equipamiento', 'guantes'),                 --   35 prod
        ('lippi', 'deporte-equipamiento', 'headex'),                  --   31 prod
        ('lippi', 'deporte-equipamiento', 'hidratacion'),             --   49 prod
        ('lippi', 'deporte-equipamiento', 'jockeys'),                 --   27 prod
        ('lippi', 'deporte-equipamiento', 'mochilas-trekking'),       --   28 prod
        ('lippi', 'deporte-equipamiento', 'mochilas-urbanas'),        --   57 prod
        ('lippi', 'deporte-equipamiento', 'otros-equipamientos'),     --    8 prod
        ('lippi', 'deporte-equipamiento', 'sacos-de-dormir-y-colchonetas'), --   14 prod
        ('lippi', 'deporte-equipamiento', 'toallas'),                 --    9 prod
        ('lippi', 'deporte-vestuario', '3-en-1-hombre'),              --   31 prod
        ('lippi', 'deporte-vestuario', '3-en-1-mujer'),               --   33 prod
        ('lippi', 'deporte-vestuario', '3-en-1-ninos'),               --   10 prod
        ('lippi', 'deporte-vestuario', 'calcetines'),                 --  159 prod
        ('lippi', 'deporte-vestuario', 'calzas-mujer'),               --   34 prod
        ('lippi', 'deporte-vestuario', 'camisas-hombre'),             --   59 prod
        ('lippi', 'deporte-vestuario', 'camisas-mujer'),              --   16 prod
        ('lippi', 'deporte-vestuario', 'chaquetas-unisex-kids'),      --  210 prod
        ('lippi', 'deporte-vestuario', 'cortaviento-hombre'),         --   36 prod
        ('lippi', 'deporte-vestuario', 'cortaviento-mujer'),          --   47 prod
        ('lippi', 'deporte-vestuario', 'cortavientos-kids'),          --    0 prod
        ('lippi', 'deporte-vestuario', 'impermeables-hombre'),        --  101 prod
        ('lippi', 'deporte-vestuario', 'impermeables-mujer'),         --   88 prod
        ('lippi', 'deporte-vestuario', 'impermeables-ninos'),         --   87 prod
        ('lippi', 'deporte-vestuario', 'insulados-hombre'),           --   48 prod
        ('lippi', 'deporte-vestuario', 'insulados-mujer'),            --   56 prod
        ('lippi', 'deporte-vestuario', 'insulados-ninos'),            --   48 prod
        ('lippi', 'deporte-vestuario', 'pantalones-hombre'),          --   62 prod
        ('lippi', 'deporte-vestuario', 'pantalones-mujer'),           --   59 prod
        ('lippi', 'deporte-vestuario', 'pantalones-ninos'),           --   26 prod
        ('lippi', 'deporte-vestuario', 'petos-mujer'),                --   22 prod
        ('lippi', 'deporte-vestuario', 'plumas-hombre'),              --   40 prod
        ('lippi', 'deporte-vestuario', 'plumas-mujer'),               --   34 prod
        ('lippi', 'deporte-vestuario', 'polar-y-chiporros-hombre'),   --  165 prod
        ('lippi', 'deporte-vestuario', 'polar-y-chiporros-mujer'),    --  164 prod
        ('lippi', 'deporte-vestuario', 'polar-y-chiporros-ninos'),    --  103 prod
        ('lippi', 'deporte-vestuario', 'poleras-hombre'),             --  180 prod
        ('lippi', 'deporte-vestuario', 'poleras-mujer'),              --  129 prod
        ('lippi', 'deporte-vestuario', 'poleras-ninos'),              --   33 prod
        ('lippi', 'deporte-vestuario', 'polerones-hombre'),           --  150 prod
        ('lippi', 'deporte-vestuario', 'polerones-mujer'),            --  119 prod
        ('lippi', 'deporte-vestuario', 'polerones-ninos'),            --   38 prod
        ('lippi', 'deporte-vestuario', 'primeras-capas-bottom-hombre'), --   25 prod
        ('lippi', 'deporte-vestuario', 'primeras-capas-bottom-mujer'), --   14 prod
        ('lippi', 'deporte-vestuario', 'primeras-capas-ninos'),       --    5 prod
        ('lippi', 'deporte-vestuario', 'primeras-capas-top-hombre'),  --   22 prod
        ('lippi', 'deporte-vestuario', 'primeras-capas-top-mujer'),   --   17 prod
        ('lippi', 'deporte-vestuario', 'shorts-hombre'),              --   31 prod
        ('lippi', 'deporte-vestuario', 'shorts-mujer'),               --   38 prod
        ('lippi', 'deporte-vestuario', 'shorts-ninos'),               --   14 prod
        ('lippi', 'deporte-vestuario', 'softshell-hombre'),           --   13 prod
        ('lippi', 'deporte-vestuario', 'trajes-de-bano-hombre'),      --    8 prod
        ('lippi', 'deporte-vestuario', 'trajes-de-bano-mujer'),       --   21 prod
        ('lippi', 'deporte-vestuario', 'trajes-de-bano-ninos')       --    5 prod
       ) AS v(store_slug, category_slug, store_key)
  JOIN stores     s ON s.slug = v.store_slug
  JOIN categories c ON c.slug = v.category_slug
ON CONFLICT (store_id, category_id, store_key) DO NOTHING;
