-- =============================================================================
-- MIGRATION 21 — Deportes y outdoor: 3 categorías nuevas + Andesgear
-- =============================================================================
-- Primera fase del plan que agrega TAXONOMÍA y no solo un adaptador. Hasta acá
-- las 7 categorías eran tecno / ferretería / hogar; estas 3 son las primeras de
-- vestuario y calzado, con todo lo que PLAN_TIENDAS §1.3 advierte que eso trae.
--
-- 1. LA LIQUIDACIÓN DE TEMPORADA: QUÉ PASA EXACTAMENTE, MEDIDO
-- §1.3 dice que "la liquidación de fin de temporada es un descuento real que se
-- ve exactamente como un escalón permanente, que es justo el patrón que
-- backtest.py etiqueta como fake", y que eso se decide antes de escribir una
-- línea de ropa. Se revisó el código antes de esta migración, y el efecto NO
-- está donde la advertencia sugiere:
--
--   * **La ingesta no se entera.** Guarda precios; no opina.
--   * **El detector NO rechaza una liquidación.** `detect_ramp` exige un alza
--     sostenida (≥15% sobre el p50 durante ≥5 días entre d−21 y d−3) ANTES de la
--     baja. Una liquidación baja sin haber subido, así que `ramp_flag` queda en
--     False y la oferta se acepta como candidata.
--   * **Donde sí pega es en el backtest, o sea en la calibración de θ.**
--     `label_outcome` marca `real` cuando el precio vuelve a subir hacia el p50 y
--     `fake` cuando se queda abajo. Una liquidación se queda abajo → `fake` → la
--     precisión medida de estas 3 categorías va a verse mal y la calibración
--     empujaría sus θ hacia arriba hasta excluirlas.
--
-- O sea que la decisión de §1.3 es **de calibración y se toma con datos**, no un
-- prerrequisito para conectar: aceptar que las liquidaciones se filtren, o
-- agregarle al backtest una etiqueta para "se quedó abajo pero fue una ganga
-- real". Mientras eso no se decida, nada se publica igual
-- (`PUBLISHER_ENABLED=false`) y la serie se acumula, que es lo único que no se
-- puede recuperar después.
--
-- 2. LOS θ SON DE PARTIDA Y NO ESTÁN CALIBRADOS — igual que los 7 existentes
-- Se eligieron más altos que los de ferretería a propósito, porque en vestuario
-- un 25% de descuento es precio de lista de cualquier martes y no es noticia:
--
--   deporte-vestuario    0.350   ropa: descuenta seguido y profundo
--   deporte-calzado      0.300   calzado: descuenta profundo, menos seguido
--   deporte-equipamiento 0.250   bienes durables, poco estacionales → igual que ferre
--
-- Los tres van al canal `vip`, que hoy es el único vivo.
--
-- 3. ANDESGEAR CROSS-LISTA EL MISMO SKU EN VARIAS CATEGORÍAS
-- Medido el 2026-09-26 sobre la primera página de 25 categorías: el árbol
-- `montana-nieve/*` re-lista productos de `hombre/*`, `mujer/*` y `escalada/*`, y
-- el calzado unisex aparece en `hombre/calzado` y en `mujer/calzado`. Con muestras
-- de 24 productos ya aparecieron **13 pares solapados**, así que el catálogo real
-- solapa más.
--
-- Eso normalmente descalificaría las llaves (CLAUDE.md: dos llaves solapadas
-- escriben dos `price_points` del mismo listing por pasada). Acá se resuelve en el
-- adaptador —`dedupe_across_categories`, el SKU se emite UNA vez por pasada— y lo
-- que hace inocua la decisión es que **los 13 pares caen dentro de la misma
-- categoría interna**: montana-nieve/vestuario con hombre y mujer son todos
-- `deporte-vestuario`, el calzado unisex es todo `deporte-calzado`. Cuál llave
-- gana no cambia el θ contra el que se mide el producto.
--
-- ⚠️ Si alguna vez se agrega a esta tienda una llave que cruce DOS categorías
-- internas, esto deja de ser inocuo y hay que volver a pensarlo.
--
-- 4. LAS 25 LLAVES
-- Cuenta declarada por la tienda el 2026-09-26 (`toolbar-amount`), ~140 páginas de
-- 24 por pasada a `rate_limit_rps = 0.33` (su `Crawl-delay: 3`) ≈ 7 min:
--   deporte-equipamiento (1.033): hidratacion 318, mochilas 300, cocina 114,
--     sacos-de-dormir 74, equipo-escalada 66, carpas 44, trekking 34,
--     campamento 32, equipo-para-la-nieve 21, colchonetas 16, skis-tablas 8, hielo 6
--   deporte-vestuario (1.495): hombre/top 521, mujer/top 247, hombre/chaquetas 245,
--     mujer/chaquetas 174, hombre/bottom 107, mujer/bottoms 66,
--     montana-nieve/vestuario 60, ninos/chaquetas 45, ninos/top 30
--   deporte-calzado (514): hombre/calzado 247, mujer/calzado 224,
--     montana-nieve/calzado 30, ninos/calzado 13
--
-- QUEDA AFUERA, A PROPÓSITO:
--   * **Las 4 ramas `accesorios`** (`hombre/accesorios` 662, `mujer/accesorios`
--     642, `montana-nieve/accesorios` 140, `ninos/accesorios` 4) y
--     `escalada/accesorios-de-escalada` 34: calcetines, gorros, guantes, magnesio.
--     Mismo criterio que las migraciones 17, 19 y 20 con los consumibles, y de
--     paso se ahorran ~55 páginas por pasada.
--   * **Las vitrinas** `sale`, `novedades`, `marcas` y `nuestras-marcas`: repiten
--     el catálogo. Con el dedupe no duplicarían observaciones, pero mezclan
--     productos de las 3 categorías internas en una sola llave, que es justo el
--     caso que el punto 3 marca como NO inocuo.
--   * `montana-nieve/nieve-avalanchas` y `ninos/bottoms`: no existen como
--     categoría de 2º nivel (FetchError); sus hojas sí. Si se quieren, van por
--     hoja.
--   * **Sparta**: no entra. Su `robots.txt` prohíbe toda URL con query string
--     (`Disallow: /*?`), así que no se puede paginar: su categoría `zapatillas.html`
--     declara 1.080 productos y una request trae 36. Las únicas tajadas disjuntas
--     que ofrece son sus facetas de marca (`/zapatillas/filtro/adidas.html`), que
--     son ~200 llaves para cubrir un árbol. Es una decisión aparte, no un olvido.
--
-- IMPORTANT: idempotente. Segura de re-ejecutar.
-- =============================================================================

BEGIN;

INSERT INTO categories (slug, name, discount_threshold) VALUES
    ('deporte-vestuario',    'Vestuario outdoor',   0.350),
    ('deporte-calzado',      'Calzado outdoor',     0.300),
    ('deporte-equipamiento', 'Equipamiento outdoor', 0.250)
ON CONFLICT (slug) DO UPDATE
    SET name = EXCLUDED.name;
    -- El θ NO se sobreescribe al re-correr: si alguien lo calibró, esta migración
    -- no puede pisarlo.

-- Al canal VIP, que hoy es el único con `telegram_channel_id`.
INSERT INTO telegram_tier_categories (tier_id, category_id)
SELECT t.id, c.id
  FROM telegram_tiers t
  JOIN categories c ON c.slug IN
       ('deporte-vestuario', 'deporte-calzado', 'deporte-equipamiento')
 WHERE t.slug = 'vip'
ON CONFLICT DO NOTHING;

INSERT INTO stores (slug, name, base_url, adapter, rate_limit_rps, is_active) VALUES
    -- `Crawl-delay: 3` en su robots.txt → 0.33 rps.
    ('andesgear', 'Andesgear', 'https://www.andesgear.cl',
     'scrapers.stores.magento_html:AndesgearAdapter', 0.33, TRUE)
ON CONFLICT (slug) DO UPDATE
    SET name           = EXCLUDED.name,
        base_url       = EXCLUDED.base_url,
        adapter        = EXCLUDED.adapter,
        rate_limit_rps = EXCLUDED.rate_limit_rps;

INSERT INTO store_categories (store_id, category_id, store_key)
SELECT s.id, c.id, v.store_key
  FROM (VALUES
        ('andesgear', 'deporte-equipamiento', 'camping-trekking/hidratacion'),
        ('andesgear', 'deporte-equipamiento', 'camping-trekking/mochilas'),
        ('andesgear', 'deporte-equipamiento', 'camping-trekking/cocina'),
        ('andesgear', 'deporte-equipamiento', 'camping-trekking/sacos-de-dormir'),
        ('andesgear', 'deporte-equipamiento', 'escalada/equipo-escalada'),
        ('andesgear', 'deporte-equipamiento', 'camping-trekking/carpas'),
        ('andesgear', 'deporte-equipamiento', 'camping-trekking/trekking'),
        ('andesgear', 'deporte-equipamiento', 'camping-trekking/campamento'),
        ('andesgear', 'deporte-equipamiento', 'montana-nieve/equipo-para-la-nieve'),
        ('andesgear', 'deporte-equipamiento', 'camping-trekking/colchonetas'),
        ('andesgear', 'deporte-equipamiento', 'montana-nieve/skis-tablas'),
        ('andesgear', 'deporte-equipamiento', 'montana-nieve/hielo'),
        ('andesgear', 'deporte-vestuario',    'hombre/top'),
        ('andesgear', 'deporte-vestuario',    'mujer/top'),
        ('andesgear', 'deporte-vestuario',    'hombre/chaquetas'),
        ('andesgear', 'deporte-vestuario',    'mujer/chaquetas'),
        ('andesgear', 'deporte-vestuario',    'hombre/bottom'),
        ('andesgear', 'deporte-vestuario',    'mujer/bottoms'),
        ('andesgear', 'deporte-vestuario',    'montana-nieve/vestuario'),
        ('andesgear', 'deporte-vestuario',    'ninos/chaquetas'),
        ('andesgear', 'deporte-vestuario',    'ninos/top'),
        ('andesgear', 'deporte-calzado',      'hombre/calzado'),
        ('andesgear', 'deporte-calzado',      'mujer/calzado'),
        ('andesgear', 'deporte-calzado',      'montana-nieve/calzado'),
        ('andesgear', 'deporte-calzado',      'ninos/calzado')
       ) AS v(store_slug, category_slug, store_key)
  JOIN stores     s ON s.slug = v.store_slug
  JOIN categories c ON c.slug = v.category_slug
ON CONFLICT (store_id, category_id, store_key) DO NOTHING;

COMMIT;

-- Fecha de conexión: 2026-09-26 → se evalúa el 2026-10-26.
