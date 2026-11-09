-- =============================================================================
-- MIGRATION 52 — Sparta, primera tajada de catálogo sin cruces de θ
-- =============================================================================
-- Fuente: INVESTIGACION_deporte_outdoor.md §1 y
-- research/2026-11-07/sparta_barrido_2026-11-04.json (545 hojas medidas
-- el 2026-11-04). El adaptador, fixture y tests ya existen en magento_html.
--
-- Sparta prohíbe toda query string en robots.txt (Disallow: /*?) y declara
-- Crawl-delay: 1. Por eso SpartaAdapter no pagina, no agrega parámetros y
-- usa 1,0 rps. La página por hoja muestra hasta 36 productos. El techo
-- global medido fue 3.615 SKUs alcanzables de 13.448 fichas (26,9%).
--
-- Las nueve raíces de producto propuestas por la investigación sumaban
-- 340 hojas y 3.157 SKUs, pero 1,72× de duplicación residual. Peor: un SKU
-- compartido entre deporte-vestuario y deporte-equipamiento gana la
-- categoría alfabéticamente anterior en db.load_store_targets, y entonces
-- puede puntuarse con θ=0,250 de equipamiento en vez del 0,350 de vestuario.
-- No se cambia ese ORDER BY: también gobierna Andesgear.
--
-- Esta primera tajada elige 19 hojas de calzado, 34 de vestuario y 10 de
-- máquinas de ejercicio. Se excluyen ejes por actividad que mezclan rubros,
-- vitrinas y hojas de accesorios ambiguas. Se excluye vestuario-deportivo/ninos:
-- comparte el SKU 240000SPCOUNN05119 con dos hojas de zapatillas. Sobre los
-- IDs medidos el 2026-11-04: 1.441 filas, 1.157 SKUs únicos, CERO
-- intersecciones entre las tres categorías internas. Re-medido en vivo el
-- 2026-11-06 16:21 UTC: 1.208 SKUs únicos (407 calzado, 762 vestuario,
-- 39 equipamiento), otra vez CERO cruces entre categorías. El dedupe
-- residual ocurre dentro de cada una. La cobertura medida originalmente
-- era 32,0% de los 3.615 alcanzables (8,6% del sitemap total).
-- Se prefirió una primera serie con θ correcto a incorporar ejes cruzados.
--
-- Costo re-medido: 63 requests, 37.093.957 bytes de HTML descomprimido
-- (37,09 MB), ~2,3 min de pared con límite de 1 rps, hasta 1.208
-- observaciones. 29 de las 63
-- hojas declaran más de 36 productos y el canario exacto las marcará
-- partial por el techo de paginación: es una limitación conocida, no una
-- señal para subir el límite contra robots. No se inventa cobertura total.
--
-- La fecha de conexión será la primera ingesta real registrada en scrape_runs.
-- Evaluar 30 días observados después con
--   python -m scripts.aceptacion_tienda --store sparta
-- publish_enabled=false desde el INSERT: no publicar antes de aceptación.
-- La columna no participa en ON CONFLICT para no volver a cerrar una tienda
-- que el dueño ya abrió. Requiere la migración 40 aplicada.
-- =============================================================================

BEGIN;

INSERT INTO stores
    (slug, name, base_url, adapter, rate_limit_rps, is_active, publish_enabled)
VALUES
    ('sparta', 'Sparta', 'https://sparta.cl',
     'scrapers.stores.magento_html:SpartaAdapter', 1.0, TRUE, FALSE)
ON CONFLICT (slug) DO UPDATE SET
    name = EXCLUDED.name,
    base_url = EXCLUDED.base_url,
    adapter = EXCLUDED.adapter,
    rate_limit_rps = EXCLUDED.rate_limit_rps,
    is_active = EXCLUDED.is_active;

INSERT INTO store_categories (store_id, category_id, store_key)
SELECT s.id, c.id, v.store_key
FROM (VALUES
    ('deporte-calzado', 'zapatillas/zapatillas-atletismo.html'),
    ('deporte-calzado', 'zapatillas/zapatillas-basquetbol.html'),
    ('deporte-calzado', 'zapatillas/zapatillas-boxeo.html'),
    ('deporte-calzado', 'zapatillas/zapatillas-ciclismo.html'),
    ('deporte-calzado', 'zapatillas/zapatillas-escolares.html'),
    ('deporte-calzado', 'zapatillas/zapatillas-futbol-futbolito.html'),
    ('deporte-calzado', 'zapatillas/zapatillas-gravel-running.html'),
    ('deporte-calzado', 'zapatillas/zapatillas-hyrox.html'),
    ('deporte-calzado', 'zapatillas/zapatillas-outdoor.html'),
    ('deporte-calzado', 'zapatillas/zapatillas-padel.html'),
    ('deporte-calzado', 'zapatillas/zapatillas-placa-carbono.html'),
    ('deporte-calzado', 'zapatillas/zapatillas-running.html'),
    ('deporte-calzado', 'zapatillas/zapatillas-tenis.html'),
    ('deporte-calzado', 'zapatillas/zapatillas-trail-running.html'),
    ('deporte-calzado', 'zapatillas/zapatillas-training.html'),
    ('deporte-calzado', 'zapatillas/zapatillas-trekking-hiking.html'),
    ('deporte-calzado', 'zapatillas/zapatillas-urbanas.html'),
    ('deporte-calzado', 'zapatillas/zapatillas-voleibol.html'),
    ('deporte-calzado', 'zapatillas/zapatos-rugby.html'),
    ('deporte-vestuario', 'vestuario-deportivo/hombre/calcetines.html'),
    ('deporte-vestuario', 'vestuario-deportivo/hombre/camisas.html'),
    ('deporte-vestuario', 'vestuario-deportivo/hombre/cortavientos.html'),
    ('deporte-vestuario', 'vestuario-deportivo/hombre/guantes.html'),
    ('deporte-vestuario', 'vestuario-deportivo/hombre/jockeys.html'),
    ('deporte-vestuario', 'vestuario-deportivo/hombre/pantalones.html'),
    ('deporte-vestuario', 'vestuario-deportivo/hombre/parkas.html'),
    ('deporte-vestuario', 'vestuario-deportivo/hombre/poleras.html'),
    ('deporte-vestuario', 'vestuario-deportivo/hombre/polerones.html'),
    ('deporte-vestuario', 'vestuario-deportivo/hombre/primera-capa.html'),
    ('deporte-vestuario', 'vestuario-deportivo/hombre/shorts.html'),
    ('deporte-vestuario', 'vestuario-deportivo/mujer/calcetines.html'),
    ('deporte-vestuario', 'vestuario-deportivo/mujer/calzas.html'),
    ('deporte-vestuario', 'vestuario-deportivo/mujer/cortavientos.html'),
    ('deporte-vestuario', 'vestuario-deportivo/mujer/guantes.html'),
    ('deporte-vestuario', 'vestuario-deportivo/mujer/jockey.html'),
    ('deporte-vestuario', 'vestuario-deportivo/mujer/pantalon.html'),
    ('deporte-vestuario', 'vestuario-deportivo/mujer/parkas.html'),
    ('deporte-vestuario', 'vestuario-deportivo/mujer/petos.html'),
    ('deporte-vestuario', 'vestuario-deportivo/mujer/poleras.html'),
    ('deporte-vestuario', 'vestuario-deportivo/mujer/polerones.html'),
    ('deporte-vestuario', 'vestuario-deportivo/mujer/primera-capa.html'),
    ('deporte-vestuario', 'vestuario-deportivo/mujer/shorts.html'),
    ('deporte-vestuario', 'vestuario-deportivo/poleras-y-shorts.html'),
    ('deporte-vestuario', 'vestuario-deportivo/polerones-y-polar.html'),
    ('deporte-vestuario', 'vestuario-deportivo/traje-de-bano.html'),
    ('deporte-vestuario', 'vestuario-deportivo/vestuario-basquetbol.html'),
    ('deporte-vestuario', 'vestuario-deportivo/vestuario-beisbol.html'),
    ('deporte-vestuario', 'vestuario-deportivo/vestuario-ciclismo.html'),
    ('deporte-vestuario', 'vestuario-deportivo/vestuario-futbol.html'),
    ('deporte-vestuario', 'vestuario-deportivo/vestuario-moda.html'),
    ('deporte-vestuario', 'vestuario-deportivo/vestuario-outdoor.html'),
    ('deporte-vestuario', 'vestuario-deportivo/vestuario-running.html'),
    ('deporte-vestuario', 'vestuario-deportivo/vestuario-tenis.html'),
    ('deporte-equipamiento', 'maquinas-de-ejercicios/cardio/bicicletas-estaticas-y-spinning.html'),
    ('deporte-equipamiento', 'maquinas-de-ejercicios/cardio/bogadoras.html'),
    ('deporte-equipamiento', 'maquinas-de-ejercicios/cardio/elipticas.html'),
    ('deporte-equipamiento', 'maquinas-de-ejercicios/cardio/trotadoras-caminadoras.html'),
    ('deporte-equipamiento', 'maquinas-de-ejercicios/fuerza/abdominales-y-bancas.html'),
    ('deporte-equipamiento', 'maquinas-de-ejercicios/fuerza/home-gym.html'),
    ('deporte-equipamiento', 'maquinas-de-ejercicios/smart-fitness/smart-bicicletas-estaticas.html'),
    ('deporte-equipamiento', 'maquinas-de-ejercicios/smart-fitness/smart-bogadoras.html'),
    ('deporte-equipamiento', 'maquinas-de-ejercicios/smart-fitness/smart-spinning.html'),
    ('deporte-equipamiento', 'maquinas-de-ejercicios/smart-fitness/smart-trotadoras.html')
) AS v(category_slug, store_key)
JOIN stores s ON s.slug = 'sparta'
JOIN categories c ON c.slug = v.category_slug
ON CONFLICT (store_id, category_id, store_key) DO NOTHING;

COMMIT;
