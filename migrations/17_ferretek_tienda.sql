-- =============================================================================
-- MIGRATION 17 — Ferretek: alta de tienda + recorte de categorías
-- =============================================================================
-- Magento 2 con la REST de catálogo ABIERTA sin token, que es la excepción:
-- Construmart, Kupfer, Sparta y Andesgear corren el mismo Magento y responden
-- `consumer isn't authorized`. El `store_key` es el id numérico de la categoría
-- del árbol que publica `/rest/V1/categories`.
--
-- Es la mejor fuente de identidad conectada hasta hoy: GTIN en el 97% de los
-- productos y marca en el 100% (medido en vivo el 2026-09-23 sobre la categoría
-- 738). El sistema entero tiene identidad para ~875 de sus ~11.000 listings.
--
-- EL RECORTE, QUE ES LA DECISIÓN DE ESTA MIGRACIÓN
-- El plan de expansión anotaba 48.454 productos —2,5× todo el catálogo actual—
-- y la instrucción de no conectarla entera. Ese número es el total de la tabla
-- de productos, no el catálogo navegable: el árbol de categorías declara 10.333
-- bajo la raíz `Herramientas`, y el resto son repuestos de maquinaria (Stens,
-- Oregon, Rotary) sin categoría visible.
--
-- De esos 10.333 se conectan 3.302, eligiendo las hojas que mapean a la
-- taxonomía existente. Queda afuera, a propósito:
--
--   * `Insumos y Accesorios` (5.402) — consumibles: brocas, discos, abrasivos.
--     Precio unitario bajo, donde un 25% de descuento son unos pocos miles de
--     pesos. El ranker no tiene piso absoluto de ahorro en CLP todavía, así que
--     los ordenaría por encima de ofertas que ahorran diez veces más.
--   * `Marcas` (10.081), `Ofertas` (606), `Despacho Gratis` (3.369), `Outlet`
--     (1.152) y las demás vitrinas — NO son categorías de catálogo: contienen
--     los mismos productos que las de arriba. Conectarlas duplicaría
--     observaciones del mismo listing en una misma pasada, y como
--     `compute_baseline` saca el p50 de los puntos crudos, ese SKU pesaría el
--     doble en su propia mediana (ver la nota extendida en `15_prat_tienda.sql`).
--   * `Pintura` (559) y `Equipos de Industria y Taller` (573) — no hay categoría
--     interna a la que mapearlos sin inventar θ sin calibrar.
--
-- Las 7 llaves elegidas están verificadas disjuntas entre sí sobre los SKUs
-- reales (0 compartidos). `Hidrolavadoras` (35) quedó afuera por eso: comparte
-- 28 de sus 35 SKUs con la 828.
--
-- Cuenta declarada por la tienda el 2026-09-23, para poder detectar después si
-- el catálogo se mueve:
--   768=885  738=801  735=1209  819=170   → ferre-herramientas (3.065)
--   747=73   828=109  786=55              → ferre-jardin          (237)
--
-- Ojo al leer `scrape_runs`: el adaptador descarta los productos con
-- `status = 2` (no publicados — su ficha devuelve HTTP 404), que son ~55% del
-- catálogo. `items_seen` va a ser bastante mayor que `items_ok` en esta tienda,
-- y eso es correcto, no una falla.
--
-- IMPORTANT: idempotente. Segura de re-ejecutar.
-- =============================================================================

BEGIN;

INSERT INTO stores (slug, name, base_url, adapter, rate_limit_rps, is_active) VALUES
    ('ferretek', 'Ferretek', 'https://ferretek.cl',
     'scrapers.stores.ferretek:FerretekAdapter', 0.5, TRUE)
ON CONFLICT (slug) DO UPDATE
    SET name     = EXCLUDED.name,
        base_url = EXCLUDED.base_url,
        adapter  = EXCLUDED.adapter;

INSERT INTO store_categories (store_id, category_id, store_key)
SELECT s.id, c.id, v.store_key
  FROM (VALUES
        -- Herramientas de Construcción (732)
        ('ferretek', 'ferre-herramientas', '768'),  -- Inalámbricas
        ('ferretek', 'ferre-herramientas', '738'),  -- Eléctricas
        ('ferretek', 'ferre-herramientas', '735'),  -- Manuales
        ('ferretek', 'ferre-herramientas', '819'),  -- Medición y Nivelación
        -- Aseo y Jardín (744)
        ('ferretek', 'ferre-jardin',       '747'),  -- Inalámbricas
        ('ferretek', 'ferre-jardin',       '828'),  -- Eléctricas
        ('ferretek', 'ferre-jardin',       '786')   -- Manuales
       ) AS v(store_slug, category_slug, store_key)
  JOIN stores     s ON s.slug = v.store_slug
  JOIN categories c ON c.slug = v.category_slug
ON CONFLICT (store_id, category_id, store_key) DO NOTHING;

COMMIT;

-- Fecha de conexión: 2026-09-23 → se evalúa el 2026-10-23.
