-- =============================================================================
-- MIGRATION 05 — Paris: activación + llaves de categoría
-- =============================================================================
-- Paris se lee por el microservicio de catálogo que usa su propio front
-- (`POST .../products/`), no por el HTML: el SSR ignora todo parámetro de
-- paginación y devuelve siempre los mismos 30 productos (ver el docstring de
-- `scrapers/stores/paris.py`).
--
-- El `store_key` es el **id de grupo** (`group_id`) de la categoría, no un path
-- ni un slug. Se resolvió pidiendo cada PLP con el header `RSC: 1` y leyendo el
-- `"category"` que el propio front manda en el filtro. Las 8 llaves de acá están
-- verificadas una por una contra producción (2026-07-31), con su volumen:
--
--     tecCelSmartphones        1108      lblRfrRefrigeradores      187
--     tecCompNotebooks          972      lblElcMicroondas          133
--     elcTvSmartTV              257      tecAccompDiscosDuros      126
--     lblLvsLavadorasSuperior    79      lblLvsLavadorasFrontal     42
--
-- Un `group_id` mal escrito devuelve `results: []` con HTTP 200 — por eso el
-- adaptador levanta `NotAListingPage` cuando la página 1 viene vacía: una
-- categoría inexistente no puede verse igual que una categoría sin ofertas.
--
-- Quedan FUERA a propósito:
--
--   * `elcTVLED` (111) — se superpone con `elcTvSmartTV`. Sembrar las dos
--     duplicaría observaciones del mismo listing en la misma pasada, y las
--     baselines (percentiles sobre 60 días) le darían doble peso a esos SKU.
--   * `lblRefrigeracion` (381) y `lblLavadosecado` (322) — son los nodos padre
--     de las hojas ya sembradas; mismo problema de superposición.
--   * `tecAccompMonitorGamer` (431) — un monitor no es un televisor (no le toca
--     el umbral 0.18 de `tecno-tv`) ni un componente de PC. Mismo criterio que
--     `Monitores` en PC Factory: entra cuando exista categoría propia.
--   * `tecCompTablet` (345) — sin categoría con umbral propio.
--
-- IMPORTANT: idempotente. Segura de re-ejecutar.
-- =============================================================================

BEGIN;

INSERT INTO store_categories (store_id, category_id, store_key)
SELECT s.id, c.id, v.store_key
  FROM (VALUES
        ('paris', 'tecno-notebooks',   'tecCompNotebooks'),
        ('paris', 'tecno-celulares',   'tecCelSmartphones'),
        ('paris', 'tecno-tv',          'elcTvSmartTV'),
        ('paris', 'tecno-componentes', 'tecAccompDiscosDuros'),
        ('paris', 'hogar-electro',     'lblRfrRefrigeradores'),
        ('paris', 'hogar-electro',     'lblLvsLavadorasFrontal'),
        ('paris', 'hogar-electro',     'lblLvsLavadorasSuperior'),
        ('paris', 'hogar-electro',     'lblElcMicroondas')
       ) AS v(store_slug, category_slug, store_key)
  JOIN stores     s ON s.slug = v.store_slug
  JOIN categories c ON c.slug = v.category_slug
ON CONFLICT (store_id, category_id, store_key) DO NOTHING;

-- El adaptador pasó su contract test y la validación en vivo: se activa.
UPDATE stores SET is_active = TRUE WHERE slug = 'paris';

COMMIT;
