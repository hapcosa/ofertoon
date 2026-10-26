-- =============================================================================
-- MIGRATION 19 — Construmart: alta de tienda (familia Magento HTML, por sucursal)
-- =============================================================================
-- La cadena nacional más grande de las que faltaban. Magento 2 con la REST
-- cerrada (401 `consumer isn't authorized`), así que va por el grid HTML de la
-- familia `magento_html`, igual que Kupfer pero con dos diferencias que su propio
-- sitio impone.
--
-- 1. LOS PRECIOS SON POR SUCURSAL, Y ESO DEFINE QUÉ SIGNIFICA ESTA SERIE
-- Cada sucursal es un `customer_group_id` de Magento (el módulo se llama
-- `Construmart_CatalogPriceByGroup`). Un visitante que no eligió sucursal no ve
-- **ningún** precio: el listado entero sale "Sin Stock". No es un bloqueo, es el
-- sitio funcionando como está diseñado — su popup dice "Para ver los precios y
-- stock, selecciona la región y tienda".
--
-- El adaptador manda la misma cookie que escribe su front
-- (`persistent_customer_group_id`) fijada en **35 = DEPARTAMENTAL** (Av.
-- Departamental 541, Santiago), elegida sobre Las Condes y Las Rejas para no
-- tomar ni el extremo caro ni el barato del abanico de la cadena.
--
-- Consecuencia que hay que tener presente al leer cualquier oferta de esta
-- tienda: **el precio de un SKU es el de esa sucursal**. La señal es correcta
-- porque la baseline y el precio de hoy salen del mismo grupo —que es lo que pide
-- la regla 1—, pero la oferta vale ahí. Cambiar `CUSTOMER_GROUP_ID` invalida el
-- histórico entero de la tienda: el p50 de un SKU quedaría mezclando dos
-- sucursales.
--
-- 2. ACÁ SÍ SE PAGINA
-- Su `robots.txt` no prohíbe `?p=` (prohíbe `?limit=`, `?mode=`, `?dir=` y
-- `?order=`), al revés que Kupfer. Se pagina con el tamaño por defecto (20, que
-- además es el máximo que ofrece su limiter: 4/5/10/20), así que la URL no lleva
-- `product_list_limit` y no toca ningún parámetro que su robots discuta. El corte
-- es `#am-page-count`, que declara cuántas páginas hay: nunca se pide una URL
-- pasada del final.
--
-- LAS 19 LLAVES: hojas de herramientas eléctricas y maquinaria, **verificadas
-- disjuntas sobre los SKUs legibles del grid** (290 distintos, 0 compartidos,
-- bajando todas las páginas de cada una el 2026-09-24).
--
-- Cuenta declarada por la tienda ese día, para detectar después si el catálogo se
-- mueve (`span.toolbar-number` cuenta FILAS del grid, no productos vendibles:
-- coincide con lo enumerado categoría por categoría, verificado 18=18, 18=18,
-- 12=12 y 20+3=23):
--   ferre-herramientas (173): taladros 23, esmeriles 18, sierras-electricas 18,
--     lijadoras 11, rotomartillos 8, fresadoras 9, pistolas-de-calor 5,
--     tronzadoras 2, cepillos-electricos 2, cepilladoras-de-banco 1,
--     soldadoras 53, generadores 12, compresores 11
--   ferre-jardin (129): corte-y-poda 51, orilladoras 24, motosierras 20,
--     cortacesped 15, hidrolavadoras 12, sopladores 7
--
-- De esas 302 filas, ~217 traían precio en la sucursal 35. El resto son "Sin
-- Stock" y el adaptador las enumera pero no las emite: la serie de un SKU que esa
-- sucursal no tiene queda con un hueco, no con un precio inventado. Es normal que
-- `items_seen` sea bastante mayor que `items_ok` en esta tienda.
--
-- QUEDA AFUERA, A PROPÓSITO:
--   * Las vitrinas de marca (`herramientas/bosch`, `/makita`, `/erboc`,
--     `jardin/black-decker`, `/wulkan`) — NO son categorías de catálogo: repiten
--     los productos de las de arriba. Conectarlas duplicaría observaciones del
--     mismo listing en una misma pasada y ese SKU pesaría el doble en su propia
--     mediana (ver la nota extendida en `15_prat_tienda.sql`).
--   * `accesorios-de-herramientas/*` (brocas, discos, accesorios) — consumibles,
--     mismo criterio que la migración 17: precio unitario bajo, donde un 25% de
--     descuento son unos pocos miles de pesos y el ranker todavía no tiene piso
--     absoluto de ahorro en CLP.
--   * `herramientas-manuales/*`, `herramientas-y-maquinarias-de-construccion/*`,
--     `automovil/*`, `jardin/{insumos,riego,piscina,maceteros-y-deco,equipamiento}/*`
--     — no hay categoría interna a la que mapearlos sin inventar un θ sin calibrar.
--   * `herramientas-electricas-e-inalambricas/herramientas-multiproposito` — la
--     categoría existe y está vacía (0 filas). Conectarla sería un `partial` por
--     pasada para siempre.
--
-- IMPORTANT: idempotente. Segura de re-ejecutar.
-- =============================================================================

BEGIN;

INSERT INTO stores (slug, name, base_url, adapter, rate_limit_rps, is_active) VALUES
    -- `robots.txt` sin `Crawl-delay`: rige el default conservador de la familia.
    ('construmart', 'Construmart', 'https://www.construmart.cl',
     'scrapers.stores.magento_html:ConstrumartAdapter', 0.5, TRUE)
ON CONFLICT (slug) DO UPDATE
    SET name     = EXCLUDED.name,
        base_url = EXCLUDED.base_url,
        adapter  = EXCLUDED.adapter;

-- El `store_key` es el path de la categoría, sin barra inicial y sin `.html`
-- (Construmart no usa sufijo, al revés que Kupfer).
INSERT INTO store_categories (store_id, category_id, store_key)
SELECT s.id, c.id, v.store_key
  FROM (VALUES
        -- Herramientas eléctricas e inalámbricas
        ('construmart', 'ferre-herramientas', 'herramientas/herramientas-electricas-e-inalambricas/taladros-y-atornilladores'),
        ('construmart', 'ferre-herramientas', 'herramientas/herramientas-electricas-e-inalambricas/esmeriles'),
        ('construmart', 'ferre-herramientas', 'herramientas/herramientas-electricas-e-inalambricas/sierras-electricas'),
        ('construmart', 'ferre-herramientas', 'herramientas/herramientas-electricas-e-inalambricas/lijadoras'),
        ('construmart', 'ferre-herramientas', 'herramientas/herramientas-electricas-e-inalambricas/rotomartillos-y-demoledores'),
        ('construmart', 'ferre-herramientas', 'herramientas/herramientas-electricas-e-inalambricas/fresadoras'),
        ('construmart', 'ferre-herramientas', 'herramientas/herramientas-electricas-e-inalambricas/pistolas-de-calor'),
        ('construmart', 'ferre-herramientas', 'herramientas/herramientas-electricas-e-inalambricas/tronzadoras'),
        ('construmart', 'ferre-herramientas', 'herramientas/herramientas-electricas-e-inalambricas/cepillos-electricos'),
        ('construmart', 'ferre-herramientas', 'herramientas/herramientas-electricas-e-inalambricas/cepilladoras-de-banco'),
        -- Maquinaria: son herramientas eléctricas grandes, mismo θ
        ('construmart', 'ferre-herramientas', 'herramientas/maquinarias/soldadoras-y-complementos'),
        ('construmart', 'ferre-herramientas', 'herramientas/maquinarias/generadores-y-complementos'),
        ('construmart', 'ferre-herramientas', 'herramientas/maquinarias/compresores-y-complementos'),
        -- Jardín. La hidrolavadora vive en el árbol de maquinarias de la tienda
        -- pero es de uso de patio: va al canal de jardín.
        ('construmart', 'ferre-jardin',       'herramientas/maquinarias/hidrolavadoras-y-accesorios'),
        ('construmart', 'ferre-jardin',       'jardin/herramientas-de-jardin/herramientas-de-corte-y-poda'),
        ('construmart', 'ferre-jardin',       'jardin/maquinarias-de-jardin/orilladoras-y-desmalezadoras'),
        ('construmart', 'ferre-jardin',       'jardin/maquinarias-de-jardin/motosierras-y-cortasetos'),
        ('construmart', 'ferre-jardin',       'jardin/maquinarias-de-jardin/cortacesped'),
        ('construmart', 'ferre-jardin',       'jardin/maquinarias-de-jardin/sopladores')
       ) AS v(store_slug, category_slug, store_key)
  JOIN stores     s ON s.slug = v.store_slug
  JOIN categories c ON c.slug = v.category_slug
ON CONFLICT (store_id, category_id, store_key) DO NOTHING;

COMMIT;

-- Fecha de conexión: 2026-09-26 → se evalúa el 2026-10-26.
