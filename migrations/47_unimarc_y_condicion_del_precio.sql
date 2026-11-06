-- =============================================================================
-- MIGRATION 47 — Unimarc, y la condición que viaja con el precio
-- =============================================================================
-- Dos cosas que son una sola: la tienda que motivó la promoción de multicompra
-- (migración 46) y el campo que le faltaba para poder publicarla sin mentir.
--
-- Investigación completa y reproducible en
-- `research/2026-11-06/INVESTIGACION_unimarc.md` + `unimarc_llaves.py`.
--
-- -----------------------------------------------------------------------------
-- 1. EL CANAL DE VENTA ES PARTE DE LA SERIE (el caso Construmart otra vez)
-- -----------------------------------------------------------------------------
-- Unimarc cotiza por `salesChannel`, y el canal sale de la dirección que el
-- cliente eligió. Un visitante anónimo recibe el **39**: lo declara la home en
-- `pageProps.salesChannel` y lo pone el SSR por default.
--
-- Medido el 2026-11-06 sobre `leches-blancas` (33 SKUs), pidiendo la MISMA URL
-- con distintas cookies `co_sc`:
--
--     sin cookie   33 SKUs   (referencia)
--     co_sc=39     33 SKUs   0 precios distintos  -> es el default, confirmado
--     co_sc=1      33 SKUs   1 precio distinto    ($1.000 vs $1.190)
--     co_sc=2      33 SKUs   2 precios distintos
--     co_sc=40     35 SKUs   cambia el SURTIDO, no solo el precio
--     co_sc=99999  (control) el payload ni se arma
--
-- O sea el canal cambia precio **y** catálogo. `UnimarcAdapter.SALES_CHANNEL`
-- manda el 39 explícito en toda request en vez de confiar en el default del
-- servidor, y **cambiar ese número invalida el histórico entero de la tienda**:
-- el p50 de un SKU quedaría mezclando dos canales. Igual que
-- `ConstrumartAdapter.CUSTOMER_GROUP_ID`.
--
-- Lo que NO está resuelto y conviene no afirmar: qué sucursal física es el 39.
-- El endpoint que lo traduce (`/address/validate-sc`) exige sesión, y este
-- proyecto no abre navegador. La serie es "la del canal 39", que es una
-- afirmación verificable; "cobertura nacional" no lo es.
--
-- -----------------------------------------------------------------------------
-- 2. POR QUÉ HACE FALTA `price_condition`
-- -----------------------------------------------------------------------------
-- Decisión del dueño del 2026-11-05: **el precio Club Unimarc cuenta como
-- oferta**, porque ser Club es solo dar el RUT y cualquiera puede. Entonces ese
-- precio es `price_effective` y no `price_card` — no es una tarjeta de la casa.
--
-- Pero el 32% del catálogo medido (2.615 de 8.213 entradas) tiene precio Club, y
-- publicar su porcentaje **sin decir que hay que ser Club** sería anunciar un
-- precio que el suscriptor no paga si llega a la caja sin RUT. Eso es la oferta
-- falsa que este proyecto existe para no ser, con otro disfraz.
--
-- `promo_label` (migración 46) no alcanzaba: cubre las 693 promociones de
-- multicompra, no las 1.989 ofertas Club de precio unitario. Son dos cosas
-- ortogonales y el mensaje tiene que poder decir las dos:
--
--     "4 x $1.150"     -> cuánto se ahorra, y bajo qué cantidad   (promo_label)
--     "Club Unimarc"   -> quién puede pagarlo                     (price_condition)
--
-- Va **verbatim**, igual que `promo_label` y `pum_label`, y por la misma razón:
-- es la condición que el suscriptor tiene que leer, no un número a reformatear.
--
-- ⚠️ Y no se emite por el solo hecho de que la tienda ponga una etiqueta.
-- `promotionalTag` es el espacio de marketing del tile: de las cuatro etiquetas
-- que aparecen en las 8.213 entradas, solo dos son condiciones de compra.
--
--     Club Unimarc        2.615   siempre con precio < lista (2.007) o promo (608)
--     Exclusivo .cl         220   siempre con precio < lista (194)   o promo (26)
--     Diamante                5   precio == lista, sin promo -> sello de vino
--     Pronto disponible      15   los 15 agotados, 14 con precio 0 -> es STOCK
--
-- El adaptador emite la condición solo cuando hay un precio condicionado (precio
-- menor al de lista, o una promoción de multicompra). Ese filtro clasifica bien
-- las 8.213: de las Club y las Exclusivo **ninguna** tiene precio igual al de
-- lista sin promo, y Diamante y Pronto disponible no pasan nunca. Es una regla de
-- dominio y no una lista de nombres a mantener — "Requiere Diamante" sobre un
-- vino que cuesta lo de siempre sería inventar letra chica, que es el error
-- simétrico de callar el Club.
--
-- -----------------------------------------------------------------------------
-- 3. LAS LLAVES
-- -----------------------------------------------------------------------------
-- Son los ocho departamentos de primer nivel del árbol vigente de la tienda
-- (`/api/catalog_system/pub/category/tree/1` de su backend VTEX), no del
-- sitemap: Unimarc no tiene sitemap ni robots, los dos responden 404.
--
-- Recorrido completo del 2026-11-06, 169 requests, con `co_sc=39` fijo:
--
--     despensa                        1.680 / 1.681   34 págs
--     bebidas-y-licores               1.588 / 1.588   32 págs
--     perfumeria                      1.353 / 1.353   28 págs   -> belleza
--     desayuno-y-dulces               1.314 / 1.315   27 págs
--     limpieza                          810 /   811   17 págs
--     lacteos-huevos-y-refrigerados     719 /   719   15 págs
--     congelados                        508 /   508   11 págs
--     mascotas                          241 /   241    5 págs
--                                     -----
--                                     8.213 filas -> 8.212 SKUs únicos
--
-- **Disjuntas sobre SKUs reales**: un solo solapado en los 28 pares, un
-- espumador de leche (`97701`) que vive en `desayuno-y-dulces` y aparece
-- cross-listado en `lacteos-huevos-y-refrigerados`. Su efecto es pesar doble en
-- su propio p50, sobre 1 listing de 8.212, y por eso el adaptador NO deduplica
-- entre llaves: hacerlo traería el riesgo que `cencosud_family` documenta —gana
-- la primera llave del orden de `db.load_store_targets`— y acá `perfumeria` mapea
-- a `belleza` mientras las otras siete mapean a `supermercado`, así que un
-- solapamiento futuro con perfumería mediría un producto de belleza con el θ de
-- supermercado **en silencio**. Por un listing de 8.212 no vale pagar eso.
--
-- Qué quedó AFUERA y por qué, para que nadie lo agregue sin releer esto:
--
--   * `carnes`, `frutas-y-verduras`, `quesos-y-fiambres`,
--     `panaderia-y-pasteleria`: precio estacional o de peso variable. El p50 de
--     60 días de un tomate no es una baseline, es el promedio de dos temporadas,
--     y el detector marcaría "oferta real" cada vez que baja la estacionalidad.
--     Mismo criterio que excluyó `Frutas-y-Verduras` y `Carnes` de Tottus.
--   * `veganos-y-vegetarianos`: es una vitrina transversal, cross-lista
--     despensa, lácteos y congelados.
--   * `hogar` y `bebes-y-ninos`: no mapean limpio a ninguna categoría interna.
--     Meterlos en `supermercado` mezclaría dos distribuciones de precio bajo un
--     θ calibrado para una. Se evalúan aparte.
--   * `store-locator`: no es catálogo.
--
-- ⚠️ `fiestas-patrias` **no es una llave y no debe serlo**, pero existe y hay que
-- conocerla: es una vitrina estacional que cross-lista catálogo, y es el
-- `categorySlug` de 32 de las 50 entradas de la página 1 de `bebidas-y-licores`
-- (Coca-Colas, cervezas, vinos). O sea el `categorySlug` de un producto NO sirve
-- para verificar que una llave trae lo que dice: mide la categoría principal que
-- la tienda le asignó, que puede ser una vitrina. El tamiz de contenido hay que
-- hacerlo sobre el nombre o sobre `categories[]`.
--
-- -----------------------------------------------------------------------------
-- 4. CUOTAS: ESTA MIGRACIÓN NO MUEVE NINGUNA, Y HAY QUE MIRARLAS
-- -----------------------------------------------------------------------------
-- Unimarc entra a dos temas que ya están cableados (migraciones 27, 35 y 38), así
-- que no hay nada que rutear acá. Pero suma una tienda al pool y eso cambia qué
-- limita:
--
--   * tema `supermercado`: cuota 5, **una sola** categoría ruteada, y
--     `MAX_PER_CATEGORY_PER_DAY = 3`. El tope fino deja **dos lugares
--     inalcanzables** y ya se materializó (el 5-nov publicó 3 de 5). Unimarc no
--     lo arregla: el limitante es la categoría, no la tienda.
--   * tema `belleza`: cuota 3, una categoría, mismo tope de 3. Entra justo.
--
-- Mover una cuota o un tope es una decisión de producto y la toma el dueño.
--
-- -----------------------------------------------------------------------------
-- 5. FECHAS
-- -----------------------------------------------------------------------------
-- Conexión: 2026-11-06. Evaluación: **2026-12-06**, no antes
-- (`python -m scripts.aceptacion_tienda --store unimarc`).
--
-- θ de partida: los de `supermercado` (0.250) y `belleza` (0.250) que ya existen.
-- Ninguna categoría nueva, así que no hay θ sin calibrar que declarar acá.
-- =============================================================================

BEGIN;

-- -----------------------------------------------------------------------------
-- La condición del precio
-- -----------------------------------------------------------------------------
ALTER TABLE price_points
    ADD COLUMN IF NOT EXISTS price_condition VARCHAR(48);

COMMENT ON COLUMN price_points.price_condition IS
    'Condición que hay que cumplir para pagar price_effective, verbatim de la '
    'tienda ("Club Unimarc"). NULL = sin condición. NO es price_card: la '
    'distinción es si el precio exige un MEDIO DE PAGO (eso es price_card, se '
    'muestra y no se compara) o solo un trámite que cualquiera puede hacer. El '
    'copy la imprime siempre que viene. Ver la migración 47.';

-- Una condición vacía no es una condición: o hay texto o es NULL. Sin esto un
-- '' llegaría al formatter y produciría "Requiere " sobre una oferta sin letra
-- chica.
ALTER TABLE price_points
    DROP CONSTRAINT IF EXISTS price_points_condition_check;
ALTER TABLE price_points
    ADD CONSTRAINT price_points_condition_check
        CHECK (price_condition IS NULL OR length(btrim(price_condition)) > 0);

-- -----------------------------------------------------------------------------
-- La tienda
-- -----------------------------------------------------------------------------
INSERT INTO stores (slug, name, base_url, adapter, rate_limit_rps, is_active) VALUES
    ('unimarc', 'Unimarc', 'https://www.unimarc.cl',
     'scrapers.stores.unimarc:UnimarcAdapter', 0.4, TRUE)
ON CONFLICT (slug) DO UPDATE
    SET name     = EXCLUDED.name,
        base_url = EXCLUDED.base_url,
        adapter  = EXCLUDED.adapter;

INSERT INTO store_categories (store_id, category_id, store_key)
SELECT s.id, c.id, v.store_key
  FROM (VALUES
        -- Departamentos del árbol VIGENTE de la tienda. Verificados disjuntos
        -- sobre SKUs reales en el recorrido completo del 2026-11-06 (§3).
        ('unimarc', 'supermercado', 'despensa'),
        ('unimarc', 'supermercado', 'desayuno-y-dulces'),
        ('unimarc', 'supermercado', 'bebidas-y-licores'),
        ('unimarc', 'supermercado', 'limpieza'),
        ('unimarc', 'supermercado', 'mascotas'),
        ('unimarc', 'supermercado', 'lacteos-huevos-y-refrigerados'),
        ('unimarc', 'supermercado', 'congelados'),
        -- Perfumería es la única que NO va a `supermercado`. Es la razón por la
        -- que el adaptador no deduplica entre llaves: ver §3.
        ('unimarc', 'belleza',      'perfumeria')
       ) AS v(store_slug, category_slug, store_key)
  JOIN stores     s ON s.slug = v.store_slug
  JOIN categories c ON c.slug = v.category_slug
ON CONFLICT (store_id, category_id, store_key) DO NOTHING;

COMMIT;
