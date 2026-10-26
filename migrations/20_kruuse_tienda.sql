-- =============================================================================
-- MIGRATION 20 — Kruuse: alta de tienda (feed JSON propio sobre Medusa)
-- =============================================================================
-- Importador de Scheppach, Holzstar, Optimum y Metallkraft. Corre Medusa detrás
-- de un Next App Router y publica su catálogo entero en `/cl/product-feed.json`.
--
-- No es un endpoint que haya que descubrir: su `llms.txt` lo ofrece
-- explícitamente para "catalog discovery / indexing" y su `robots.txt` tiene un
-- grupo que PERMITE a los bots de agente (GPTBot, ClaudeBot, PerplexityBot,
-- CCBot) sobre `/cl/product-feed.json`, `/cl/products/` y `/cl/categories/`. Por
-- eso no se parsea el payload RSC de las páginas de categoría, que era el plan
-- original de PLAN_TIENDAS: frágil y sin necesidad.
--
-- LO QUE ESTA TIENDA APORTA, Y LO QUE NO
-- Aporta **identidad**: GTIN-13 en 3.728 de 3.772 productos (99%), marca en el
-- 100%. Con Ferretek (97%) son las dos fuentes que sostienen el matching
-- cross-store de todo el sistema, que es lo que permite el copy "más barato que
-- en Paris". El sistema tenía identidad para ~875 de sus ~11.000 listings.
--
-- **No** aporta volumen de publicación: 3.467 de los 3.772 productos están en
-- `backorder` (236 `in_stock`, 59 `out_of_stock`, 10 `preorder`). Kruuse vende
-- máquinas a pedido. El adaptador marca `in_stock` solo para `in_stock`, así que
-- la guarda de stock del detector va a rechazar casi todo lo de esta tienda —
-- correctamente: una oferta de algo que no se puede comprar hoy no es una oferta.
-- La serie se construye igual y queda lista para cuando un SKU entre en stock.
--
-- Esto hay que tenerlo presente al evaluarla a los 30 días: el criterio de
-- PLAN_TIENDAS pide ≥1 candidato aceptado propio, y esta tienda puede no llegar
-- por una razón que no es inestabilidad de catálogo. Si pasa, la decisión es de
-- producto (¿vale mantenerla solo por identidad?), no automática.
--
-- LAS 24 LLAVES
-- El `store_key` es el **nombre de la categoría tal como lo escribe la tienda**:
-- el feed es plano y no acepta filtro (`?category=` devuelve el catálogo entero),
-- así que el filtrado es del adaptador. La pasada baja el feed UNA vez (38
-- requests con `limit=100`) y las 24 llaves se sirven de esa copia.
--
-- **Son disjuntas por construcción**: el feed da exactamente una `category` por
-- producto, así que ninguna entrada puede caer en dos llaves (3.772 productos,
-- 3.772 SKUs únicos). Es la primera tienda donde la verificación de disjunción
-- que pide CLAUDE.md no hace falta hacer a mano.
--
-- Cuenta del 2026-09-26, para detectar después si el catálogo se mueve:
--   ferre-herramientas (547): Compresores 122, Esmeriles/Afiladoras/Lijadoras de
--     Banco 54, Taladros de Columna 35, Sierras Huincha para Metal 33,
--     Cepilladoras Canteadoras 31, Taladros para metal 29, Lijadoras para metal
--     28, Sierras de huincha para madera 27, Generadores 26, Equipos de soldadura
--     y plasma 21, Tornos para Madera 20, Sierras Circulares 18, Lijadoras 16,
--     Taladros Magnéticos 16, Sierras circulares para metal 9, Sierras de Banco 8,
--     Sierras Ingleteadoras 6, Taladros y Atornilladores Inalámbricos 4, Sierras
--     Inalámbricas 4
--   ferre-jardin (122): Hidrolavadoras 75, Procesamiento de Leña 23, Corte y Poda
--     14, Cuidado del Césped 6, Herramientas de Jardín Inalámbricas 4
--
-- Las dos llaves de 4 productos van a salir `partial` en sus primeras 3 corridas
-- por el piso absoluto del canario (`CANARY_MIN_ITEMS = 5`, que rige mientras no
-- haya `CANARY_MIN_HISTORY = 3` corridas con las que comparar). Entran igual
-- porque un taladro atornillador inalámbrico es exactamente lo que el canal
-- quiere, y a la cuarta pasada la mediana toma el control.
--
-- QUEDA AFUERA, A PROPÓSITO:
--   * **Accesorios y consumibles** (~1.100 productos): las 8 categorías
--     "Accesorios para ...", `Consumibles para soldadura`, `Repuestos (Cuchillas)`,
--     `Brocas`, `Discos de Corte`, `Baterías y Cargadores`, `Alimentadores para
--     carpintería`, `Prensas para carpintería`, `Accesorios Tiger`. Mismo criterio
--     que las migraciones 17 y 19: precio unitario bajo, donde un 25% de descuento
--     son unos pocos miles de pesos, y el ranker todavía no tiene piso absoluto de
--     ahorro en CLP.
--   * **Maquinaria de taller metalmecánico** (~500): Plegadoras 154, Tornos para
--     Metal 137, Fresadoras para Metal 70, Equipos de Inducción 45, Curvadoras 24,
--     Prensas Hidráulicas 20, Roscadoras 14, Cizallas 12 y el resto. No hay
--     categoría interna a la que mapearlas sin inventar un θ sin calibrar, y no es
--     el público de los canales.
--   * **Aseo, aspiración y clima** (~100): Fregadoras de Piso, Aspiradoras,
--     Colectores de Polvo, Tratamiento de aire comprimido, Deshumidificadores.
--     Mismo motivo.
--   * **`Outlet` (19)**. Ojo con el motivo, porque NO es el de las vitrinas de
--     Magento: en este feed cada producto declara UNA sola categoría, así que
--     `Outlet` no duplicaría observaciones de nadie. Queda afuera porque es una
--     etiqueta de liquidación y no un tipo de producto: su contenido es
--     heterogéneo y un θ único sobre esa mezcla no significa nada.
--   * **Los 1.307 productos sin `category`** (35% del catálogo): ninguna llave
--     los alcanza. Es el límite del diseño y está asumido.
--
-- IMPORTANT: idempotente. Segura de re-ejecutar.
-- =============================================================================

BEGIN;

INSERT INTO stores (slug, name, base_url, adapter, rate_limit_rps, is_active) VALUES
    -- `robots.txt` sin `Crawl-delay`: rige el default conservador.
    ('kruuse', 'Kruuse', 'https://kruuse.cl',
     'scrapers.stores.kruuse:KruuseAdapter', 0.5, TRUE)
ON CONFLICT (slug) DO UPDATE
    SET name     = EXCLUDED.name,
        base_url = EXCLUDED.base_url,
        adapter  = EXCLUDED.adapter;

INSERT INTO store_categories (store_id, category_id, store_key)
SELECT s.id, c.id, v.store_key
  FROM (VALUES
        ('kruuse', 'ferre-herramientas', 'Compresores'),
        ('kruuse', 'ferre-herramientas', 'Esmeriles, Afiladoras y Lijadoras de Banco'),
        ('kruuse', 'ferre-herramientas', 'Taladros de Columna'),
        ('kruuse', 'ferre-herramientas', 'Sierras Huincha para Metal'),
        ('kruuse', 'ferre-herramientas', 'Cepilladoras Canteadoras'),
        ('kruuse', 'ferre-herramientas', 'Taladros para metal'),
        ('kruuse', 'ferre-herramientas', 'Lijadoras para metal'),
        ('kruuse', 'ferre-herramientas', 'Sierras de huincha para madera'),
        ('kruuse', 'ferre-herramientas', 'Generadores'),
        ('kruuse', 'ferre-herramientas', 'Equipos de soldadura y plasma'),
        ('kruuse', 'ferre-herramientas', 'Tornos para Madera'),
        ('kruuse', 'ferre-herramientas', 'Sierras Circulares'),
        ('kruuse', 'ferre-herramientas', 'Lijadoras'),
        ('kruuse', 'ferre-herramientas', 'Taladros Magnéticos'),
        ('kruuse', 'ferre-herramientas', 'Sierras circulares para metal'),
        ('kruuse', 'ferre-herramientas', 'Sierras de Banco'),
        ('kruuse', 'ferre-herramientas', 'Sierras Ingleteadoras'),
        ('kruuse', 'ferre-herramientas', 'Taladros y Atornilladores Inalámbricos'),
        ('kruuse', 'ferre-herramientas', 'Sierras Inalámbricas'),
        ('kruuse', 'ferre-jardin',       'Hidrolavadoras'),
        ('kruuse', 'ferre-jardin',       'Procesamiento de Leña'),
        ('kruuse', 'ferre-jardin',       'Corte y Poda'),
        ('kruuse', 'ferre-jardin',       'Cuidado del Césped'),
        ('kruuse', 'ferre-jardin',       'Herramientas de Jardín Inalámbricas')
       ) AS v(store_slug, category_slug, store_key)
  JOIN stores     s ON s.slug = v.store_slug
  JOIN categories c ON c.slug = v.category_slug
ON CONFLICT (store_id, category_id, store_key) DO NOTHING;

COMMIT;

-- Fecha de conexión: 2026-09-26 → se evalúa el 2026-10-26.
