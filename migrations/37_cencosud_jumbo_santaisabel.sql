-- =============================================================================
-- MIGRATION 37 — Jumbo y Santa Isabel: la Fase 4 del supermercado
-- =============================================================================
-- PLAN_SUPERMERCADO §5 Fase 4. Con la Fase 1 cerrada (el `pum` se persiste desde
-- la migración 34 y el tema S.Mercado quedó cableado en la 35), lo que falta para
-- que el supermercado sea un producto y no una tienda es más de una cadena sobre
-- la misma canasta. Las dos entran con **un solo adaptador**
-- (`scrapers.stores.cencosud_family`): corren el mismo front y el mismo código
-- —el sitemap de Santa Isabel todavía lista `/compromisos-jumbo`—.
--
-- 1. EL PLAN DECÍA QUE NO PAGINAN. SÍ PAGINAN, Y ESO CAMBIA LA ESTRATEGIA ENTERA
-- PLAN_SUPERMERCADO §4 cerró con "probadas ocho variantes, las ocho devuelven los
-- mismos 40 primeros", y de ahí salía la estrategia obligada: **hojas elegidas a
-- mano de ≤40 productos**, de las cuales solo 6 de 14 muestreadas entraban.
--
-- Medido el 2026-11-04 con `?page=N`, recorrido completo:
--
--   llave                                      págs   filas        declarado
--   jumbo/lacteos-huevos-y-congelados/leches      8   7×40+18 =  298   298
--   jumbo/despensa                               83  82×40+19 = 3.299  3.299
--   santaisabel/limpieza                         19              724    724
--
-- y la página siguiente a la última contesta **HTTP 404**, igual que Easy. **No
-- hay tope de paginación profunda** —a diferencia de VTEX, que corta en ~2.500—:
-- la página 83 de `despensa` sirve sus 19 productos finales.
--
-- O sea el plan sobreestimaba el costo y subestimaba el alcance: no hay que
-- elegir 771 hojas a mano, alcanzan los **departamentos**. Qué cambió entre una
-- medición y la otra: la tienda **reorganizó su taxonomía** y las URLs del plan
-- ahora responden 301. La redirección conserva el query string (verificado), así
-- que no es la explicación de la medición vieja; lo que importa es que hoy pagina.
--
-- ⚠️ **La taxonomía vieja quedó como una trampa de solapamiento.** `desayuno` y
-- `congelados` ya no existen: redirigen a `/despensa` y a
-- `/lacteos-huevos-y-congelados`. Dos `store_key` que caen en el mismo destino
-- escriben dos `price_points` del mismo listing por pasada y lo hacen pesar el
-- doble en su propio p50. **Las llaves de abajo son los paths VIGENTES**, leídos
-- de la navegación de la tienda y NO de su sitemap, que quedó viejo.
--
-- 2. LAS TRES COSAS QUE EL PLAN PEDÍA MEDIR ANTES DE CONECTAR
--
-- a) **Estabilidad del orden** (la lección de Tottus: un orden inestable deja
--    SKUs sin ver nunca y nada madura). Tres requests idénticas a `leches`
--    devolvieron **el mismo orden y el mismo conjunto** de 40, y el recorrido
--    completo de 8 páginas dio 298 filas con solo 4 repetidos. No hace falta
--    buscar un orden determinista: el default lo es. Los parámetros de orden de
--    VTEX (`?O=OrderByPriceASC`, `DESC`, `NameASC`) se **ignoran** —devuelven el
--    mismo orden— así que tampoco hay alternativa que elegir.
--
-- b) **`rate_limit_rps`**. Santa Isabel declara `Crawl-delay: 1` y prohíbe
--    `/api/`, `/_next/`, `/admin/`, `/private/`; Jumbo no declara `Crawl-delay` y
--    solo prohíbe filtros facetados (`*?map=`, `*?PS=`, `*sc=*`) y el checkout.
--    Los dos **habilitan a ClaudeBot por nombre**. Queda en **0,5** para las dos:
--    es el default conservador del repo y la mitad de lo que Santa Isabel
--    permitiría. El sistema hace dos pasadas diarias, no necesita velocidad.
--    Tampoco hace falta disfrazar el User-Agent: `DEFAULT_USER_AGENT` devuelve el
--    listado completo en las dos (nada de UA-sniffing como Easy ni de
--    `BROWSER_HEADERS` como Tottus).
--
-- c) **`availability` es señal de verdad, y no la trampa de Tottus** (cuyo
--    `availability` del listado habla de modos de envío). Lo que lo prueba es
--    dónde caen los agotados: el orden por defecto los manda al final.
--
--        jumbo/despensa  páginas 1, 2, 20, 41   100% InStock
--        jumbo/despensa  páginas 81, 82, 83     100% OutOfStock (99 productos)
--
--    Sobre la pasada completa de las 10 llaves, 3,2% a 9,6% del catálogo de Jumbo
--    viene agotado y 0% a 2,1% del de Santa Isabel. ⚠️ Medido **solo sobre la
--    página 1** el número da 0,8%: es otra vez el engaño de la página 1.
--    Serían las **primeras tiendas de supermercado del sistema con stock real en
--    el listado** — en Tottus, Falabella y Paris se asume `True` a ciegas.
--
--    **La ficha no sirve para cruzar ese dato**: ocho fichas abiertas a mano
--    —tres que el listado daba `OutOfStock` y cinco `InStock`— devolvieron las
--    ocho `schema.org/InStock`. No construir un lector de `publisher/stock.py`
--    sobre ella.
--
-- 3. LAS DIEZ LLAVES, Y QUÉ QUEDA AFUERA
-- La tajada es **la misma canasta que ya tiene Tottus** (migraciones 27 y 33), que
-- es lo que hace comparables las tres cadenas. Recorrido completo el 2026-11-04:
--
--   tienda       llave                         declarado  listings  págs  agotados
--   jumbo        despensa                          3.303     3.286    83     8,0%
--   jumbo        licores-bebidas-y-aguas           3.209     3.202    81     3,2%
--   jumbo        chocolates-galletas-y-snacks      1.873     1.824    47     9,6%
--   jumbo        limpieza                          1.542     1.538    39     4,4%
--   jumbo        mascotas                            848       844    22     5,5%
--   santaisabel  despensa                          1.601     1.591    41     2,1%
--   santaisabel  botilleria                        1.453     1.408    37     0,1%
--   santaisabel  chocolates-galletas-y-snacks      1.083     1.066    28     1,0%
--   santaisabel  limpieza                            723       723    19     0,3%
--   santaisabel  mascotas                            188       186     5     0,0%
--                                                 ------    ------   ---
--                                                 15.823    15.668   402 requests/pasada
--
-- `listings` es lo que el adaptador emite, o sea después de descontar las filas
-- duplicadas del bloque patrocinado (ver §4). Jumbo aporta 10.694 SKUs únicos y
-- Santa Isabel 4.974.
--
-- Queda afuera, por tres razones distintas:
--
--   * **Perecederos y precio estacional** — `frutas-y-verduras`,
--     `carnes-y-pescados`, `panaderia-y-pasteleria`, `quesos-y-fiambres`,
--     `comidas-preparadas`. Es la regla que CLAUDE.md no revisa: el p50 de 60 días
--     de un tomate es el promedio de dos temporadas y el detector marcaría "oferta
--     real" cada vez que baja la estacionalidad. Y lo que no se puede guardar no se
--     compra en cantidad, así que no participa del mecanismo que hace valer una
--     oferta de ticket bajo (PLAN_SUPERMERCADO §2).
--   * **`lacteos-huevos-y-congelados` queda afuera, y es una decisión tomada acá.**
--     Tottus tiene un paraguas `Congelados` limpio; Cencosud **no**: fusionó
--     lácteos, huevos y congelados en un departamento donde conviven
--     `comidas-congeladas` y `verduras-congeladas` (almacenables) con `yoghurt`,
--     `postres-refrigerados` y `churrascos-lomitos-y-otros` (refrigerados de
--     vida corta). Tomar la raíz mete perecederos; tomar las cinco hojas
--     congeladas son 10 llaves más y una decisión de producto sobre qué cuenta
--     como almacenable. Son 1.697 SKUs en Jumbo y 1.000 en Santa Isabel, y entran
--     el día que alguien decida esa lista.
--   * **Las vitrinas** — `marcas-exclusivas`, `prime`, `experiencias-jumbo`,
--     `libres-de`, `productos-importados`, `exclusivo-en-santa-isabel`,
--     `jumbo-ofertas`. Re-listan el catálogo, así que solapan por definición. Es
--     el caso Prat del 2026-09-25: una colección curada a mano se ve igual que un
--     catálogo hasta que el comerciante la reedita y mata 240 series de productos
--     que seguían a la venta.
--   * **`belleza-y-cuidado-personal` (Jumbo) y `cuidado-personal-y-bebe` (Santa
--     Isabel)** quedan afuera de esta migración aunque la 36 acabe de crear
--     `belleza`: el de Jumbo mete farmacia (`accesorios-medicos`,
--     `primeros-auxilios`, `suplementos-y-vitaminas`) y el de Santa Isabel mete
--     `bebe`. Mapear eso a `belleza` es una decisión de producto, no una traducción.
--     ⚠️ Y hay una razón técnica para no hacerlo a la ligera: el adaptador
--     deduplica entre llaves y la que gana es la primera del orden de
--     `db.load_store_targets` (`store_slug, category_slug, store_key`).
--     `belleza` ordena ANTES que `supermercado`, así que un SKU que estuviera en
--     `limpieza` y en `belleza-y-cuidado-personal` se le asignaría a belleza y
--     desaparecería de la serie de supermercado.
--
-- 4. SOLAPAMIENTO: MEDIDO, Y EL ADAPTADOR LO DEDUPLICA
-- Dos solapamientos distintos, los dos medidos el 2026-11-04:
--
--   * **El bloque patrocinado se sirve además de su posición natural.** `leches`
--     298 filas → 294 únicos; `jumbo/chocolates-galletas-y-snacks` 1.873 → 1.824.
--   * **Dos departamentos cross-listan el mismo SKU**: sobre 800 SKUs muestreados
--     de las cinco llaves de Jumbo, `despensa` ∩ `chocolates-galletas-y-snacks` =
--     2 (galletas Club Social y un pack Colac). Las otras nueve combinaciones son
--     disjuntas, y las cinco de Santa Isabel lo son entre sí sobre 760 SKUs.
--
-- A diferencia de Tottus —donde la migración 27 §6 aceptó un 2% de solape porque
-- `FalabellaAdapter` no deduplica—, acá el adaptador emite cada SKU **una vez por
-- pasada**, como `AndesgearAdapter`. Es inocuo porque las diez llaves mapean a la
-- misma categoría interna; ver el ⚠️ de la §3 sobre el día que eso cambie.
--
-- 5. θ: VAN A `supermercado`, Y NO SE PUEDE MEDIR
-- Las dos entran a `supermercado` (θ 0.250, sin calibrar) y no a una categoría
-- nueva: es la misma canasta y el mismo rango de ticket que las siete llaves de
-- Tottus, así que separarlas sería partir en dos la serie de una sola categoría.
--
-- ⚠️ **El método de la migración 24 para fijar un θ de partida no se puede aplicar
-- acá**: su `offers` trae UN precio, sin "antes" tachado, así que no hay descuento
-- declarado que medir. Es el caso de Nike —el θ de `ropa-accesorios` también es
-- herencia de sus vecinos, no una medición— con su mismo lateral bueno: acá no hay
-- número de la tienda que inflar, el descuento sale entero de nuestra baseline.
--
-- 6. QUÉ NO RESUELVEN, PARA QUE NADIE LO ESPERE
-- **No traen GTIN.** Las claves del item del JSON-LD son `@type, brand, image,
-- name, offers, url` y nada más. Así que **no** habilitan el "más barato que en
-- Jumbo": el cross-store sigue dando cero y seguiría dándolo con estas dos
-- adentro. El cuello de botella es la cobertura de GTIN, no el consumidor.
--
-- **Tampoco traen el `pum` por la vía que leemos.** El `ppumPrice` y su unidad
-- existen, pero en el payload RSC de la página (formato de flight de React), no
-- en el JSON-LD. Sus ofertas van a salir sin la línea del precio por kilo que la
-- Fase 1 construyó, igual que las 8 de 24 de Tottus que no tienen unidad de
-- medida. Está en el docstring del adaptador: leerlo es una decisión de producto
-- con un costo de fragilidad, no una tarea pendiente.
--
-- 7. QUÉ ESPERAR, Y CUÁNDO
-- **No publican nada durante 30 días.** Fecha de conexión **2026-11-04** → se
-- evalúan el **2026-12-04** con `python -m scripts.aceptacion_tienda --store jumbo`
-- (ídem `santaisabel`), ≥40% de la **cohorte** con `n_days >= 30`.
--
-- ⚠️ El 3-10% de catálogo permanentemente agotado de Jumbo **no madura nunca**:
-- `compute_baseline` filtra `if in_stock`, así que un listing sin una observación
-- con stock no tiene baseline ni `n_days`. Es el mecanismo de Kruuse, y es
-- exactamente lo que `scripts.aceptacion_tienda` descuenta del denominador desde
-- el 2026-11-04. Sin esa corrección, esa cola hundiría la estabilidad medida de
-- estas dos tiendas y mandaría apagarlas por una razón que no es rotación.
--
-- **El costo de volumen es grande y hay que mirarlo**: 15.668 listings nuevos son
-- ~31.600 observaciones/día sobre las ~74.000 de hoy (**+43%**), y 402 requests
-- por pasada a 2,0-2,4 MB por página son ~0,9 GB por pasada. La guarda de volumen
-- (`runner.pasadas_flacas`) compara contra la mediana de las últimas 7 pasadas, así
-- que el salto se absorbe solo en ~4 pasadas; lo que conviene no perder de vista es
-- que después de esto una caída de Jumbo sola pesa el 13% del volumen del sistema.
--
-- Las llaves nuevas solo tienen efecto en la pasada SIGUIENTE: los targets se
-- cargan una vez al arrancar la pasada. Y hay que **reconstruir el contenedor**
-- (`docker compose up -d --build scraper`): el Dockerfile copia las fuentes, y el
-- adaptador es código nuevo.
-- =============================================================================

BEGIN;

INSERT INTO stores (slug, name, base_url, adapter, rate_limit_rps, is_active) VALUES
    ('jumbo', 'Jumbo', 'https://www.jumbo.cl',
     'scrapers.stores.cencosud_family:JumboAdapter', 0.5, TRUE),
    ('santaisabel', 'Santa Isabel', 'https://www.santaisabel.cl',
     'scrapers.stores.cencosud_family:SantaIsabelAdapter', 0.5, TRUE)
ON CONFLICT (slug) DO UPDATE
    SET name     = EXCLUDED.name,
        base_url = EXCLUDED.base_url,
        adapter  = EXCLUDED.adapter;

INSERT INTO store_categories (store_id, category_id, store_key)
SELECT s.id, c.id, v.store_key
  FROM (VALUES
        -- Paths VIGENTES de la navegación de cada tienda, no del sitemap: ver §1.
        -- Los departamentos no se llaman igual en las dos (`botilleria` contra
        -- `licores-bebidas-y-aguas`), así que las llaves no se copian de una a la
        -- otra.
        ('jumbo',       'supermercado', 'despensa'),
        ('jumbo',       'supermercado', 'limpieza'),
        ('jumbo',       'supermercado', 'mascotas'),
        ('jumbo',       'supermercado', 'chocolates-galletas-y-snacks'),
        ('jumbo',       'supermercado', 'licores-bebidas-y-aguas'),
        ('santaisabel', 'supermercado', 'despensa'),
        ('santaisabel', 'supermercado', 'limpieza'),
        ('santaisabel', 'supermercado', 'mascotas'),
        ('santaisabel', 'supermercado', 'chocolates-galletas-y-snacks'),
        ('santaisabel', 'supermercado', 'botilleria')
       ) AS v(store_slug, category_slug, store_key)
  JOIN stores     s ON s.slug = v.store_slug
  JOIN categories c ON c.slug = v.category_slug
ON CONFLICT (store_id, category_id, store_key) DO NOTHING;

COMMIT;

-- `supermercado` ya está ruteada al tema S.Mercado (`message_thread_id = 20549`,
-- cuota 5) desde las migraciones 27 y 35: no hay nada que cablear acá.
--
-- Fecha de conexión: 2026-11-04 → se evalúan el 2026-12-04.
