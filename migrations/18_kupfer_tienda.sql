-- =============================================================================
-- MIGRATION 18 — Kupfer: alta de tienda (familia Magento HTML)
-- =============================================================================
-- Magento 2 con la REST cerrada: `/rest/V1/products` y `/rest/V1/categories`
-- responden HTTP 401 `The consumer isn't authorized` (verificado el
-- 2026-09-24). Lo público es el grid HTML renderizado server-side, que trae todo
-- lo que el detector necesita: `data-price-amount` y el SKU propio de la tienda.
--
-- LA FAMILIA NO PAGINA, Y ESO DECIDE QUÉ SE PUEDE CONECTAR
-- El `robots.txt` de Kupfer prohíbe `Disallow: /*?p=`, que es el parámetro de
-- paginación de Magento. `product_list_limit` no está prohibido, así que cada
-- categoría se trae en UNA request de 36 productos y lo que no entra no se va a
-- buscar: `scrapers/stores/magento_html.py` compara lo enumerado contra el total
-- que la tienda declara y el runner marca `partial`.
--
-- Por eso solo se conecta una llave. `herramientas-manuales` (≈145) y
-- `mantencion-industrial` (118) no entran en una página, y `herramientas-manuales`
-- además no es "herramientas eléctricas".
--
-- EL CATÁLOGO ÚTIL ES CHICO, Y ESO ESTÁ ASUMIDO
-- Kupfer es una ferretería industrial: su catálogo es amarre, cadenas, cabos y
-- mantención. La rama que mapea a nuestra taxonomía —herramientas eléctricas—
-- declara 24 productos, y sus hojas están casi vacías (7 de 10 con cero: los
-- productos están asignados al padre). Se conecta el padre, que es anchor y los
-- contiene a todos.
--
-- 24 listings no van a mover el volumen del canal. Entra porque cuesta una
-- request por pasada y porque es el primer caso de la familia `magento_html`, que
-- Sparta y Andesgear reusan en la Fase 2 sin escribir código. Si a los 30 días no
-- deja un candidato aceptado propio, el criterio de PLAN_TIENDAS §Fase 1 la
-- apaga: `UPDATE stores SET is_active = false WHERE slug = 'kupfer'`.
--
-- Cuenta declarada por la tienda el 2026-09-24, para detectar después si el
-- catálogo se mueve:
--   equipos-herramientas-y-maquinarias-industriales/herramientas-electricas = 24
--
-- CONSTRUMART NO ENTRA EN ESTA MIGRACIÓN, y no es un olvido: sus precios son por
-- sucursal. El sitio lo dice él mismo ("Para ver los precios y stock, selecciona
-- la región y tienda"), cada sucursal es un `customer_group_id`, y para un
-- visitante anónimo el HTML no trae un solo precio y las 20 filas del grid salen
-- "Sin Stock". Su `/rest/default/V1/products-render-info` sí contesta sin token,
-- pero devuelve `final_price: 0` e `is_salable: ""` en los 20. Conectarla exige
-- sostener una sesión por sucursal y aceptar que la serie de un SKU es la de ESA
-- sucursal — una decisión de modelo, no un adaptador más. Ver HANDOFF.md.
--
-- IMPORTANT: idempotente. Segura de re-ejecutar.
-- =============================================================================

BEGIN;

INSERT INTO stores (slug, name, base_url, adapter, rate_limit_rps, is_active) VALUES
    -- `robots.txt` sin `Crawl-delay`: rige el default conservador de la familia.
    ('kupfer', 'Kupfer', 'https://kupfer.cl',
     'scrapers.stores.magento_html:KupferAdapter', 0.5, TRUE)
ON CONFLICT (slug) DO UPDATE
    SET name     = EXCLUDED.name,
        base_url = EXCLUDED.base_url,
        adapter  = EXCLUDED.adapter;

-- El `store_key` es el path de la categoría con `.html`, tal como lo publica el
-- sitemap de la tienda. Sin barra inicial: el adaptador la agrega.
INSERT INTO store_categories (store_id, category_id, store_key)
SELECT s.id, c.id, v.store_key
  FROM (VALUES
        ('kupfer', 'ferre-herramientas',
         'equipos-herramientas-y-maquinarias-industriales/herramientas-electricas.html')
       ) AS v(store_slug, category_slug, store_key)
  JOIN stores     s ON s.slug = v.store_slug
  JOIN categories c ON c.slug = v.category_slug
ON CONFLICT (store_id, category_id, store_key) DO NOTHING;

COMMIT;

-- Fecha de conexión: 2026-09-24 → se evalúa el 2026-10-24.
