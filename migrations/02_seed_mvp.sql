-- =============================================================================
-- MIGRATION 02 — Seed del MVP: 6 tiendas, taxonomía y llaves de categoría
-- =============================================================================
-- Solo `falabella` y `sodimac` arrancan activas: son las dos con adaptador
-- verificado contra producción. Las otras cuatro quedan registradas pero
-- `is_active = FALSE` hasta que su adaptador pase el contract test.
--
-- Los umbrales de descuento son valores DE PARTIDA. Se recalibran en F1 contra
-- la curva precisión-volumen de pricing/backtest.py.
--
-- IMPORTANT: idempotente (ON CONFLICT DO UPDATE). Segura de re-ejecutar.
-- =============================================================================

BEGIN;

INSERT INTO stores (slug, name, base_url, adapter, rate_limit_rps, is_active) VALUES
    ('falabella', 'Falabella',  'https://www.falabella.com',
     'scrapers.stores.falabella_family:FalabellaAdapter', 0.5, TRUE),
    ('sodimac',   'Sodimac',    'https://www.sodimac.cl',
     'scrapers.stores.falabella_family:SodimacAdapter',   0.5, TRUE),
    ('paris',     'Paris',      'https://www.paris.cl',
     'scrapers.stores.paris:ParisAdapter',                0.5, FALSE),
    ('easy',      'Easy',       'https://www.easy.cl',
     'scrapers.stores.easy:EasyAdapter',                  0.5, FALSE),
    ('pcfactory', 'PC Factory', 'https://www.pcfactory.cl',
     'scrapers.stores.pcfactory:PcFactoryAdapter',        0.5, FALSE),
    ('spdigital', 'SP Digital', 'https://www.spdigital.cl',
     'scrapers.stores.spdigital:SpDigitalAdapter',        0.5, FALSE)
ON CONFLICT (slug) DO UPDATE
    SET name = EXCLUDED.name,
        base_url = EXCLUDED.base_url,
        adapter = EXCLUDED.adapter;

-- Taxonomía interna. Los umbrales reflejan cuánto se mueve normalmente el precio
-- en cada rubro: la tecnología baja de a poco y de forma sostenida, la moda hace
-- saltos grandes, así que exigirle 15% a moda sería puro ruido.
INSERT INTO categories (slug, name, discount_threshold) VALUES
    ('tecno-notebooks',   'Notebooks',              0.15),
    ('tecno-celulares',   'Celulares',              0.15),
    ('tecno-componentes', 'Componentes PC',         0.15),
    ('tecno-tv',          'Televisores',            0.18),
    ('ferre-herramientas','Herramientas eléctricas',0.25),
    ('ferre-jardin',      'Jardín',                 0.25),
    ('hogar-electro',     'Electrodomésticos',      0.20)
ON CONFLICT (slug) DO UPDATE
    SET name = EXCLUDED.name;

-- -----------------------------------------------------------------------------
-- Llaves por tienda: SIEMPRE paths de categoría, nunca términos de búsqueda.
-- -----------------------------------------------------------------------------
-- El buscador de Falabella pagina bien pero clasifica mal ("celular" traía ~940
-- items con accesorios, fundas y televisores mezclados). Importa porque el
-- umbral de descuento del detector se aplica POR CATEGORÍA: un SKU mal
-- clasificado recibe el umbral equivocado, y termina siendo un falso positivo o
-- una oferta real que nunca se publica. El path es la clasificación de la propia
-- tienda. En Sodimac además el buscador no es opción: /search 301-redirige y
-- descarta el query string, con lo que `page` se pierde.
--
-- Cada `store_key` está verificado uno por uno contra la tienda: devuelve
-- `results` no vacío, `pagination.currentPage` honesto, y es una hoja. Las
-- categorías de nivel alto son listados válidos pero inútiles acá
-- (`cat7090034/Tecnologia` trae 201.124 productos bajo un mismo umbral).
--
-- El par id/nombre debe ser EXACTO: si no coincide, la tienda sirve una landing
-- de CMS sin `results` y el adaptador falla con NotAListingPage.
INSERT INTO store_categories (store_id, category_id, store_key)
SELECT s.id, c.id, v.store_key
  FROM (VALUES
        ('falabella', 'tecno-notebooks',    'cat70057/Notebooks'),
        ('falabella', 'tecno-celulares',    'cat720161/Smartphones'),
        ('falabella', 'tecno-tv',           'cat7190148/Smart-TV'),
        ('falabella', 'tecno-componentes',  'cat2003/Almacenamiento'),
        ('falabella', 'tecno-componentes',  'cat70037/Tarjetas-de-Memoria'),
        ('falabella', 'hogar-electro',      'cat3205/Refrigeradores'),
        ('falabella', 'hogar-electro',      'cat4060/Lavadoras'),
        ('falabella', 'hogar-electro',      'cat3151/Microondas'),
        ('sodimac',   'ferre-herramientas', 'cat14080023/Taladros'),
        ('sodimac',   'ferre-herramientas', 'cat18380029/Esmeriles'),
        ('sodimac',   'ferre-herramientas', 'cat14090005/Sierras'),
        ('sodimac',   'ferre-jardin',       'cat14080024/Cortadoras-de-pasto'),
        ('sodimac',   'ferre-jardin',       'cat18380033/Motosierras')
       ) AS v(store_slug, category_slug, store_key)
  JOIN stores     s ON s.slug = v.store_slug
  JOIN categories c ON c.slug = v.category_slug
ON CONFLICT (store_id, category_id, store_key) DO NOTHING;

COMMIT;
