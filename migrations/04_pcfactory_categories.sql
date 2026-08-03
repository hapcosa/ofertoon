-- =============================================================================
-- MIGRATION 04 — PC Factory: activación + llaves de categoría
-- =============================================================================
-- PC Factory se lee por su API JSON pública. El `store_key` es el **nombre** de
-- la categoría tal cual lo publica la tienda: el parámetro `categorias` del
-- endpoint filtra por nombre, no por id ni por slug.
--
-- Eso lo vuelve frágil de una forma específica: un nombre mal escrito (o una
-- categoría que la tienda renombra) devuelve **0 resultados con HTTP 200**, sin
-- error. Por eso las 8 llaves de acá están verificadas una por una contra
-- producción (2026-07-31), con su volumen:
--
--     Notebooks                 133      Discos Internos SSD        65
--     Monitores  (ver abajo)     87      Tarjetas Gráficas NVIDIA   45
--     Smartphones                38      Memorias PC                33
--     Memorias Flash             28      Smart TV                   25
--     Tarjetas Gráficas AMD       6
--
-- NO se siembran los nodos intermedios del menú, que existen pero listan cero
-- productos: `Notebooks Gamer`, `Notebooks Corporativos`, `Procesadores`,
-- `Placas Madres`, `Tarjetas Gráficas`, `Memorias`, `Audífonos`. Son agrupadores
-- de navegación; los productos cuelgan solo de las hojas.
--
-- `Monitores` (87 productos) queda FUERA a propósito: no es un televisor —no le
-- corresponde el umbral 0.18 de `tecno-tv`— ni un componente de PC. Clasificarlo
-- mal le daría el umbral equivocado al detector. Entra cuando exista una
-- categoría propia.
--
-- IMPORTANT: idempotente. Segura de re-ejecutar.
-- =============================================================================

BEGIN;

INSERT INTO store_categories (store_id, category_id, store_key)
SELECT s.id, c.id, v.store_key
  FROM (VALUES
        ('pcfactory', 'tecno-notebooks',   'Notebooks'),
        ('pcfactory', 'tecno-celulares',   'Smartphones'),
        ('pcfactory', 'tecno-tv',          'Smart TV'),
        ('pcfactory', 'tecno-componentes', 'Discos Internos SSD'),
        ('pcfactory', 'tecno-componentes', 'Memorias PC'),
        ('pcfactory', 'tecno-componentes', 'Memorias Flash'),
        ('pcfactory', 'tecno-componentes', 'Tarjetas Gráficas NVIDIA'),
        ('pcfactory', 'tecno-componentes', 'Tarjetas Gráficas AMD')
       ) AS v(store_slug, category_slug, store_key)
  JOIN stores     s ON s.slug = v.store_slug
  JOIN categories c ON c.slug = v.category_slug
ON CONFLICT (store_id, category_id, store_key) DO NOTHING;

-- El adaptador pasó su contract test y la validación en vivo: se activa.
UPDATE stores SET is_active = TRUE WHERE slug = 'pcfactory';

COMMIT;
