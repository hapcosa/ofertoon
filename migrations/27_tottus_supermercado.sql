-- =============================================================================
-- MIGRATION 27 — Tottus: el supermercado que llena el tema S.Mercado
-- =============================================================================
-- El grupo nuevo (migración 26) tiene un tema `supermercado` y no había con qué
-- llenarlo: ninguna tienda de súper estaba conectada, y la aprobada —Lider— no
-- es viable por volumen (102.880 SKUs × 752 KB = 73,8 GB por pasada sobre el
-- WiFi USB del host).
--
-- 1. TOTTUS ESTABA DESCARTADA POR UN DIAGNÓSTICO EQUIVOCADO, Y ERA MÍO
-- PLAN_TIENDAS Fase 6 la tenía como "el borde pasa, el ORIGEN falla": API VTEX
-- 503, categoría y búsqueda 526. Las dos observaciones son ciertas y ninguna
-- significa lo que parecía.
--
--   * **Tottus no es VTEX.** Corre la plataforma de Falabella — `__NEXT_DATA__`,
--     641 menciones de `falabella` en su home, cero de `vtex`. Nunca tuvo una API
--     VTEX: el 503 (`no healthy upstream`) es lo que contesta cuando se le pide
--     una ruta que no existe.
--   * **El 526 era un `store_key` inventado.** Probé `/category/CATG16439/...` y
--     su path de listado es `/lista/`, como Sodimac. Con la llave real que publica
--     su propio sitemap: **HTTP 200**.
--   * **El 200 de la home no probaba nada**: venía con `cf-cache-status: HIT` y
--     `age: 2381`, o sea de la cache de Cloudflare y no del origen.
--
-- Lección transferible: antes de declarar roto un origen, verificar que la ruta
-- probada EXISTA en la plataforma que la tienda realmente usa.
--
-- 2. CERO ADAPTADOR NUEVO
-- `parse_listing` de `falabella_family` parsea su payload sin una línea nueva
-- (verificado contra producción el 2026-10-01). `TottusAdapter` fija slug, host,
-- `listing_path` y dos cosas medidas:
--
--   * **`BROWSER_HEADERS`**, porque exige el juego completo y no solo el UA.
--     Aislado con 3 intentos de cada uno: `DEFAULT_USER_AGENT` 403×3,
--     `BROWSER_USER_AGENT` 403×3, `BROWSER_HEADERS` 200×3.
--   * **`max_pages = 45`**, porque Despensa declara 2.060 productos a 48 por
--     página = 43. Con el default de 20 se perdería más de la mitad del catálogo
--     **sin un solo error**: el corte por `max_pages` es silencioso.
--   * **`sortBy=derived.currentPrice,asc`**, y esto es lo que hace confiable su
--     serie. Su orden default es `_score,desc` ("Recomendados"), un ranking de
--     relevancia con boost de publicidad que cambia entre requests: paginarlo
--     devuelve repetidos en el medio del catálogo y deja otros sin ver nunca.
--     Medido sobre `Mascotas` (427 declarados, 9 páginas), recorrido completo:
--
--         sin sortBy / _score,desc    435 filas → 389 únicos   cobertura 0,911
--         currentPrice,asc            427 filas → 422 únicos   cobertura 0,988
--
--     Y el default no es estable ni entre corridas del mismo día: dos recorridos
--     dieron 326 y 389 únicos. Lo que se gana no es cobertura por la cobertura —
--     un SKU que aparece de forma intermitente no acumula observaciones, nunca
--     llega a `MIN_DAYS` y por lo tanto **nunca produce una baseline**.
--
-- 3. UNA SOLA CATEGORÍA, Y LA PRIMERA MEDICIÓN DECÍA DOS
-- Mirando solo la página 1, `Aseo-y-Limpieza` declaraba descuento en el 79% del
-- catálogo contra el 22% de `Desayuno-y-Dulces`: dos comportamientos de precio,
-- o sea dos categorías con θ distinto. **Era artefacto de la página 1**, que la
-- tienda ordena por promoción — el mismo engaño que el fixture de Paris.
--
-- Con 4 páginas (~200 SKUs) por llave la distribución es una sola:
--
--   llave                 con dto.  p50 dto.  declara >=25%  >=30%  >=35%
--   Despensa                 23%      19%          3%          0%     0%
--   Desayuno-y-Dulces        25%      20%          6%          4%     3%
--   Congelados               31%      18%          7%          5%     0%
--   Aseo-y-Limpieza          43%      20%         14%          9%     2%
--   Mascotas                 17%      22%          4%          3%     0%
--
-- Un solo comportamiento → una sola categoría. Es la regla de la migración 24
-- aplicada al revés: ahí la medición mandó separar, acá manda no separar.
--
-- 4. θ = 0.250 DE PARTIDA, SIN CALIBRAR
-- El supermercado descuenta poco y plano: el descuento que la tienda DECLARA
-- tiene p50 ~20% y solo el 0-9% del catálogo llega a declarar 30%. Un θ de 0.35
-- como el de vestuario no dejaría pasar casi nada; 0.250 queda arriba del ruido
-- de promoción habitual y abajo del techo de lo que la tienda mueve. Sale del
-- backtest, no de acá.
--
-- 5. LA TAJADA: CINCO PARAGUAS NO PERECEDEROS
-- `Frutas-y-Verduras` (167 SKUs) y `Carnes` (240) quedan AFUERA a propósito, y no
-- por tamaño: son perecederos de precio estacional. El p50 de 60 días de un tomate
-- no es una baseline, es el promedio de dos temporadas distintas — el detector
-- marcaría "oferta real" cada vez que baja la estacionalidad. Es el mismo
-- razonamiento que excluye los días degradados del backtest: mejor no medir que
-- medir algo que no significa lo que dice.
--
-- `Cervezas` (209) y `Vinos-y-licores` (2.008) también quedan afuera, por una
-- razón distinta: son no perecederos y tienen ticket, pero publicar alcohol en el
-- canal es una decisión de producto que nadie tomó.
--
--   llave                    SKUs   págs   ticket p50
--   Despensa                 2.060    43     $1.570
--   Desayuno-y-Dulces        1.506    32     $1.570
--   Aseo-y-Limpieza          1.162    25     $2.511
--   Congelados                 482    11     $2.890
--   Mascotas                   427     9     $9.390
--                            -----   ---
--                            5.637   120 requests/pasada ≈ 4 min a 0,5 rps
--
-- ⚠️ **El ticket es de otro orden que el del canal.** Las 66 ofertas publicadas
-- tienen p50 $279.990 y acá el p50 es $1.570. Un 25% de descuento sobre $1.570
-- son $390. Eso puede estar bien —el canal necesitaba bajar el ticket— pero es
-- una pregunta de producto que el backtest NO responde: un descuento del 25% es
-- igual de real a cualquier precio.
--
-- 6. SOLAPAMIENTO: 2% ENTRE DOS LLAVES, Y SE ACEPTA
-- Medido con ~200 SKUs por llave: `Despensa` vs `Desayuno-y-Dulces` comparten 4
-- de 200 (2%); las otras ocho combinaciones son disjuntas. `FalabellaAdapter` no
-- deduplica entre categorías, así que esos SKUs escriben dos `price_points` por
-- pasada.
--
-- Se acepta, a diferencia del 7% y 20% que la migración 24 rechazó, porque el
-- daño concreto no se materializa: las dos observaciones son el mismo precio del
-- mismo día, así que el p50 no se desplaza, y `MIN_DAYS` cuenta **días
-- calendario distintos**, así que el duplicado no acelera el cold-start. Si en
-- vez de 2% fuera 20%, la mitad del peso del p50 de esos SKUs vendría de una
-- llave: ahí sí habría que elegir una.
--
-- 7. QUÉ ESPERAR, Y CUÁNDO
-- **No publica nada durante 30 días.** Fecha de conexión 2026-10-01 → se evalúa el
-- **2026-10-31** con `python -m scripts.aceptacion_tienda --store tottus`, ≥40% de
-- la **cohorte** con `n_days >= 30`, nunca transversalmente. El supermercado rota
-- catálogo más que la ferretería, así que este es el número a mirar de verdad.
--
-- ⚠️ `in_stock` es ciego acá, como en Falabella y Paris: su `availability` habla
-- de modos de envío, no de stock. La guarda de stock del detector no protege
-- nada en esta tienda hasta que se verifique la ficha del candidato.
--
-- Las llaves nuevas solo tienen efecto en la pasada SIGUIENTE: los targets se
-- cargan una vez al arrancar la pasada.
-- =============================================================================

BEGIN;

INSERT INTO categories (slug, name, discount_threshold) VALUES
    ('supermercado', 'Supermercado', 0.250)
ON CONFLICT (slug) DO UPDATE
    SET name = EXCLUDED.name;
    -- El θ NO se sobreescribe al re-correr: si alguien lo calibró, esta
    -- migración no puede pisarlo.

-- Al canal VIP, y al tema `supermercado` que la migración 26 creó vacío a la
-- espera de esto.
INSERT INTO telegram_tier_categories (tier_id, category_id, topic_id)
SELECT t.id, c.id, top.id
  FROM telegram_tiers t
  JOIN categories     c   ON c.slug = 'supermercado'
  LEFT JOIN telegram_topics top ON top.tier_id = t.id AND top.slug = 'supermercado'
 WHERE t.slug = 'vip'
ON CONFLICT (tier_id, category_id) DO UPDATE
    SET topic_id = COALESCE(EXCLUDED.topic_id, telegram_tier_categories.topic_id);

INSERT INTO stores (slug, name, base_url, adapter, rate_limit_rps, is_active) VALUES
    -- Su `robots.txt` no declara `Crawl-delay` (solo prohíbe basket, myaccount,
    -- checkout y orders): rige el default conservador de la familia.
    ('tottus', 'Tottus', 'https://www.tottus.cl',
     'scrapers.stores.falabella_family:TottusAdapter', 0.5, TRUE)
ON CONFLICT (slug) DO UPDATE
    SET name     = EXCLUDED.name,
        base_url = EXCLUDED.base_url,
        adapter  = EXCLUDED.adapter;

INSERT INTO store_categories (store_id, category_id, store_key)
SELECT s.id, c.id, v.store_key
  FROM (VALUES
        -- Los cinco paraguas de nivel 1 no perecederos. El par id/nombre es el
        -- EXACTO que publica su sitemap: si el nombre no corresponde al id, la
        -- plataforma sirve una landing de CMS sin `results` y el adaptador lo
        -- rechaza con `NotAListingPage` (ver `FalabellaAdapter`).
        ('tottus', 'supermercado', 'CATG27055/Despensa'),
        ('tottus', 'supermercado', 'CATG27072/Desayuno-y-Dulces'),
        ('tottus', 'supermercado', 'CATG27074/Aseo-y-Limpieza'),
        ('tottus', 'supermercado', 'CATG27073/Congelados'),
        ('tottus', 'supermercado', 'CATG27078/Mascotas')
       ) AS v(store_slug, category_slug, store_key)
  JOIN stores     s ON s.slug = v.store_slug
  JOIN categories c ON c.slug = v.category_slug
ON CONFLICT (store_id, category_id, store_key) DO NOTHING;

COMMIT;

-- Fecha de conexión: 2026-10-01 → se evalúa el 2026-10-31.
