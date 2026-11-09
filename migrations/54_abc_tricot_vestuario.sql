-- =============================================================================
-- MIGRATION 54 — ABC y Tricot, tajadas medidas de vestuario
-- =============================================================================
-- Investigación y comandos: research/2026-11-07/salesforce.md, sección
-- 2026-11-09. Este archivo se escribe sin aplicarse. Requiere la columna
-- publish_enabled creada por la versión APLICADA de la migración 40 y la
-- secuencia integrada completa; no correr migrate.py desde un worktree aislado
-- que carezca de 53/55 u otras ramas. El 49 está reservado sin archivo.
--
-- ABC: solo /mujer/ropa-mujer, con zona de inventario Metropolitana fija
-- inventory_LaPolar_whven|t_ecom_metropolitana. Robots permite zone/start/sz
-- sobre la categoría. El 2026-11-07 se enumeraron 824/824 IDs, dos pasadas
-- idénticas. El 2026-11-09, 820/820 en 23 páginas con datos y una final vacía;
-- hubo siete bajas y tres altas frente al 7-nov. Una ficha 200 de ropa mujer
-- (611179) mostró botón Agotado deshabilitado y no apareció en los 820 IDs;
-- una ficha listada (635116) tuvo Agregar a la bolsa habilitado. Los tiles
-- carecen de señal de stock: la evidencia apunta a que el listado oculta los
-- agotados. No se usa el precio Normal como baseline; Internet es el efectivo.
-- Costo medido de la hoja: 24 requests, ~45,31 MB de HTML descomprimido,
-- hasta 824 productos en la medición del 7-nov (820 el 9-nov).
--
-- Tricot: robots.txt del 2026-11-09 prohíbe ?start; el adaptador nunca agrega
-- parámetros. Dos instantáneas de nueve hojas separadas 15 min 08 s dieron
-- Jaccard 1,0000 en cada una: 465 IDs de primera página, todos disjuntos.
-- Las hojas declaran 1.122 productos en total, techo alcanzable 465/1.122
-- (41,4%) el 9-nov. Seis hojas son parciales y completeness() lo reportará
-- como tal; no se inventa paginación. Las tres hojas completas fueron bananos
-- 10/10, zapatillas mujer 56/56 y jeans hombre 39/39. En bananos y jeans,
-- 49/49 fichas listadas dieron InStock; una ficha de jeans agotada
-- (540141) seguía accesible pero no figuraba entre los 39/39 del listado.
-- Eso respalda el filtro de agotados; mantenerlo bajo observación en las
-- primeras ingestas. Ninguno de los 465 tiles tuvo GTIN o señal de agotado;
-- todos dieron precio efectivo y Normal. Rango efectivo $490-$16.990.
-- Costo por pasada: 9 requests, 12,34 MB de HTML descomprimido, 465 tiles.
--
-- La coincidencia ABC ropa/calzado (2 IDs medidos el 7-nov) se evita aquí al
-- conectar solo ropa. Antes de agregar calzado ABC, decidir explícitamente el
-- solape entre categorías internas. No se extrapola que el resto de las 426
-- categorías Tricot o el resto de ABC estén cubiertos.
--
-- Fecha de conexión: primera ingesta real de cada tienda en scrape_runs.
-- Evaluar 30 días observados después de esa fecha con
--   python -m scripts.aceptacion_tienda --store abc
--   python -m scripts.aceptacion_tienda --store tricot
-- Hasta entonces publish_enabled=false impide mensajes. ON CONFLICT no modifica
-- publish_enabled, para no volver a cerrar una tienda abierta por el dueño.
-- =============================================================================

BEGIN;

INSERT INTO stores
    (slug, name, base_url, adapter, rate_limit_rps, is_active, publish_enabled)
VALUES
    ('abc', 'ABC', 'https://www.abc.cl',
     'scrapers.stores.salesforce_family:ABCAdapter', 0.5, TRUE, FALSE),
    ('tricot', 'Tricot', 'https://www.tricot.cl',
     'scrapers.stores.salesforce_family:TricotAdapter', 0.5, TRUE, FALSE)
ON CONFLICT (slug) DO UPDATE SET
    name = EXCLUDED.name,
    base_url = EXCLUDED.base_url,
    adapter = EXCLUDED.adapter,
    rate_limit_rps = EXCLUDED.rate_limit_rps,
    is_active = EXCLUDED.is_active;

INSERT INTO store_categories (store_id, category_id, store_key)
SELECT s.id, c.id, v.store_key
FROM (VALUES
    ('abc',    'ropa-vestuario',  'mujer/ropa-mujer'),
    ('tricot', 'ropa-accesorios', 'accesorios/mujer/bananos'),
    ('tricot', 'ropa-vestuario',  'hombre/pijamas'),
    ('tricot', 'ropa-vestuario',  'mujer/poleras'),
    ('tricot', 'ropa-calzado',    'calzado/mujer/zapatillas'),
    ('tricot', 'ropa-vestuario',  'mujer/jeans'),
    ('tricot', 'ropa-vestuario',  'hombre/jeans'),
    ('tricot', 'ropa-vestuario',  'infantil/ninas/poleras'),
    ('tricot', 'ropa-vestuario',  'mujer/ropa-interior/calzones'),
    ('tricot', 'ropa-vestuario',  'hombre/camisas')
) AS v(store_slug, category_slug, store_key)
JOIN stores s ON s.slug = v.store_slug
JOIN categories c ON c.slug = v.category_slug
ON CONFLICT (store_id, category_id, store_key) DO NOTHING;

COMMIT;
