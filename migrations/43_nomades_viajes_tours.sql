-- =============================================================================
-- MIGRATION 43 — Nomades: el tema `viajes` deja de estar mudo
-- =============================================================================
-- `INVESTIGACION_viajes.md`. El tema `viajes` existe desde la migración 26
-- (`message_thread_id = 20547`, `daily_quota = 1`) y **tiene cero categorías
-- ruteadas**, así que no publica nada desde que se creó. Esta migración lo abre.
--
-- 1. POR QUÉ TOURS Y NO UNA AGENCIA DE VIAJES
--
-- `PLAN_EXPANSION.md` §6 explica que la mayor parte de "viajes" **no entra**, y el
-- motivo no es el acceso sino el detector: un pasaje o una noche de hotel no
-- tienen *un* precio, tienen un precio **por fecha de viaje**, así que el p50 de
-- 60 días mezclaría 60 fechas de salida distintas.
--
-- Los tours y actividades son la excepción: un transfer al aeropuerto o un tour a
-- los geysers tiene **precio por producto, sin fecha dentro del precio**, igual
-- que un televisor. Y es la razón de empezar por acá y no por los packs de Cocha
-- o Travel Security: un pack con salida fija **desaparece cuando se agota o
-- cuando pasa la fecha**, y su vida puede ser más corta que `MIN_DAYS`.
--
-- 2. EL PAYLOAD ES JSON-LD Y REGALA EL CANARIO EXACTO
--
-- La página de destino trae el catálogo completo en el `__NEXT_DATA__` como
-- schema.org: un `ItemList` cuyos `item` son `Product` con `sku`, `name`, `url`
-- y un `offers` con `price`, `priceCurrency` y `availability`.
--
-- - **`ItemList.numberOfItems` coincide exacto** con los items servidos (43 y 43
--   en `/santiago`) ⇒ canario exacto, gratis.
-- - **`sku` poblado al 100%** y coincide con el `-id<N>` del final de la URL en
--   los 99 productos medidos sobre tres destinos. Se usa el campo, no el sufijo:
--   el slug lo reescribe el comerciante, el id no.
-- - **NO pagina**: `?page=2` devuelve **los mismos 43 productos**. Es la trampa
--   del SSR de Paris, y el adaptador **no implementa paginación** a propósito —
--   "paginar" acá recolectaría el mismo producto N veces.
--
-- 3. ⚠️ LA MONEDA ES DEL PRODUCTO, Y POR ESO LAS LLAVES NO SON "LOS DESTINOS
--    CHILENOS"
--
-- Barridos **los 160 destinos**: conviven **9 monedas** —USD 408, **CLP 282**,
-- EUR 260, PEN 136, COP 119, BRL 110, ARS 62, MXN 51, GBP 12—. Y no alcanza con
-- elegir destinos de Chile:
--
--   `madrid` y `roma` cotizan en **CLP** (se venden al viajero chileno),
--   `bariloche` sirve **USD y ARS en la misma página** (10 y 9 ofertas),
--   `cancun` mezcla **USD y MXN**, `roma` mezcla **EUR, CLP y USD**,
--   y `san-pedro-de-atacama` —destino chileno— trae **1 oferta en USD** de 34.
--
-- O sea no existe "la moneda de la tienda" ni "la moneda del destino". Por eso
-- **el filtro vive en el adaptador y es por oferta** (`nomades.MONEDA`), no en
-- esta lista de llaves. Las 24 de abajo son los destinos que **hoy** tienen al
-- menos una oferta en CLP; si mañana uno deja de tenerlas, el adaptador no emite
-- nada de ahí y no pasa nada. Lo que **no** hay que hacer es escribir la lista
-- como si fuera la verdad: es una conveniencia para no gastar 136 requests en
-- destinos que hoy no aportan.
--
-- ⚠️ Tres de las 24 aportan **una sola oferta CLP** (`el-calafate` 1 de 28,
-- `madrid` 1 de 13, `roma` 1 de 9). Entran porque cuestan 1 request cada una, y
-- porque el día que haya soporte de moneda pasan a aportar 28, 13 y 9.
--
-- 4. LA CATEGORÍA NUEVA
--
-- No hay ninguna de viajes. θ de partida **0.250** — **herencia, no medición**:
-- es el valor de `belleza`, `supermercado`, `ferre-*` y `deporte-equipamiento`,
-- o sea el θ por defecto del repo para una categoría sin calibrar. Y acá θ **no
-- se puede medir todavía**: la agencia **no declara un "antes" tachado** en el
-- listado, el caso Nike. `min_history_days = 30`, el valor correcto.
--
-- Aritmética de `CLAUDE.md`: el tema `viajes` tiene `daily_quota = 1` y pasa a
-- tener **1** categoría ruteada, así que `categorías × MAX_PER_CATEGORY_PER_DAY`
-- = 1×3 = 3 ≥ 1. No hace falta tocar la cuota, y **no conviene subirla**: con una
-- sola categoría el tope de 3 por categoría sería el limitante y la cuota dejaría
-- de decidir — el error que la migración 35 dejó en `supermercado` (cuota 5 con
-- una categoría, o sea dos lugares inalcanzables).
--
-- 5. FECHAS Y COSTO
--
-- Conexión **2026-11-05**. No publica hasta el **2026-12-05**; se evalúa con
-- `scripts.aceptacion_tienda --store nomades` ese día, contra días observados.
--
-- **24 requests por pasada** — la tienda más barata de todo el plan. Con 282 SKUs
-- maduros y una cuota de 1 por día, el catálogo no va a ser el cuello.
--
-- ⚠️ Lo que hay que mirar el 2026-12-05 y es el riesgo real de esta vertical: **si
-- el SKU de un tour sobrevive 30 días**. Un tour regular debería (es catálogo
-- permanente, no una salida con fecha), pero es exactamente lo que
-- `aceptacion_tienda` mide y lo que decide si la vertical funciona.
-- =============================================================================

INSERT INTO categories (slug, name, discount_threshold, min_history_days) VALUES
    ('viajes-tours', 'Viajes: Tours y Actividades', 0.250, 30)
ON CONFLICT (slug) DO NOTHING;

-- Al tema `viajes`, que hasta ahora no tenía ninguna categoría ruteada.
INSERT INTO telegram_tier_categories (tier_id, category_id, topic_id)
SELECT t.id, c.id, tp.id
  FROM telegram_tiers t
  JOIN categories c       ON c.slug = 'viajes-tours'
  JOIN telegram_topics tp ON tp.slug = 'viajes' AND tp.tier_id = t.id
 WHERE t.id = 1
ON CONFLICT (tier_id, category_id) DO NOTHING;

INSERT INTO stores (slug, name, base_url, adapter, rate_limit_rps, is_active) VALUES
    ('nomades', 'Nomades', 'https://www.nomades.com',
     'scrapers.stores.nomades:NomadesAdapter', 0.5, TRUE)
ON CONFLICT (slug) DO UPDATE
    SET name     = EXCLUDED.name,
        base_url = EXCLUDED.base_url,
        adapter  = EXCLUDED.adapter;

INSERT INTO store_categories (store_id, category_id, store_key)
SELECT s.id, c.id, v.store_key
  FROM (VALUES
        -- `store_key` = el slug del destino, **sin prefijo de idioma**: el
        -- sitemap trae cada uno tres veces (`/x`, `/en/x`, `/pt/x`) y son el
        -- mismo catálogo traducido. Conectar los tres haría pesar el triple a
        -- cada listing en su propio p50.
        ('nomades', 'viajes-tours', 'antofagasta'),   --   3 ofertas CLP de 3
        ('nomades', 'viajes-tours', 'arica'),   --   3 ofertas CLP de 3
        ('nomades', 'viajes-tours', 'caleta-tortel'),   --   4 ofertas CLP de 4
        ('nomades', 'viajes-tours', 'castro'),   --   7 ofertas CLP de 7
        ('nomades', 'viajes-tours', 'copiapo'),   --   6 ofertas CLP de 6
        ('nomades', 'viajes-tours', 'coyhaique'),   --  11 ofertas CLP de 11
        ('nomades', 'viajes-tours', 'el-calafate'),   --   1 ofertas CLP de 28
        ('nomades', 'viajes-tours', 'iquique'),   --  10 ofertas CLP de 10
        ('nomades', 'viajes-tours', 'isla-de-pascua'),   --  13 ofertas CLP de 13
        ('nomades', 'viajes-tours', 'la-serena'),   --  10 ofertas CLP de 10
        ('nomades', 'viajes-tours', 'madrid'),   --   1 ofertas CLP de 13
        ('nomades', 'viajes-tours', 'melipeuco'),   --   7 ofertas CLP de 7
        ('nomades', 'viajes-tours', 'pucon'),   --  22 ofertas CLP de 22
        ('nomades', 'viajes-tours', 'puerto-montt'),   --   9 ofertas CLP de 9
        ('nomades', 'viajes-tours', 'puerto-natales'),   --  42 ofertas CLP de 42
        ('nomades', 'viajes-tours', 'puerto-rio-tranquilo'),   --   5 ofertas CLP de 5
        ('nomades', 'viajes-tours', 'puerto-varas'),   --  12 ofertas CLP de 13
        ('nomades', 'viajes-tours', 'puerto-williams'),   --   5 ofertas CLP de 5
        ('nomades', 'viajes-tours', 'punta-arenas'),   --  25 ofertas CLP de 25
        ('nomades', 'viajes-tours', 'roma'),   --   1 ofertas CLP de 9
        ('nomades', 'viajes-tours', 'san-pedro-de-atacama'),   --  33 ofertas CLP de 34
        ('nomades', 'viajes-tours', 'santiago'),   --  42 ofertas CLP de 43
        ('nomades', 'viajes-tours', 'valdivia'),   --   9 ofertas CLP de 9
        ('nomades', 'viajes-tours', 'villa-cerro-castillo')    --   1 ofertas CLP de 1
       ) AS v(store_slug, category_slug, store_key)
  JOIN stores     s ON s.slug = v.store_slug
  JOIN categories c ON c.slug = v.category_slug
ON CONFLICT (store_id, category_id, store_key) DO NOTHING;
