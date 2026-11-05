-- =============================================================================
-- MIGRATION 44 — Seis tiendas Magento de deporte y outdoor
-- =============================================================================
-- `INVESTIGACION_TANDA2.md`. Las seis entran con **cero líneas de adaptador
-- nuevo**: `magento_html` las cubre, en dos configuraciones que la familia ya
-- tenía. Lo único que se agregó al módulo fueron tres selectores por tienda
-- (`name_selector`, `url_selector`, `sku_selector`), con los defaults intactos.
--
-- 1. DOS CONFIGURACIONES, Y LAS DECIDE EL ROBOTS
--
-- a) **Plantilla de Sparta** — `speedo`, `trekbikeschile`, `newbalance`: su
--    `robots.txt` es **idéntico al de Sparta carácter por carácter** (87
--    `Disallow`, `Crawl-delay: 1`, y entre ellos `/*?`, `/?`, `/*?*`, `/*&*`,
--    `/*product_list_limit=`). Ninguna query string permitida ⇒ `paginates =
--    False`, `page_size = None`, una request por llave.
--
-- b) **Plantilla de Andesgear** — `thenorthface`, `mammut`, `marmot`: 17
--    `Disallow`, `Crawl-delay: 3`, nada que prohíba `?p=` ⇒ `paginates = True` a
--    0,33 rps.
--
-- ⚠️ Las tres de (b) y Kliper **son el mismo operador**: Kliper es el multimarca
-- y su menú enlaza `/marcas/the-north-face`, `/marcas/marmot`, `/marcas/mammut` y
-- **`/marcas/andesgear`** — una tienda ya conectada. El mismo producto va a
-- existir como listing en varias; para la serie no es problema (`store_id`
-- distintos, cada uno con su p50) pero el **canal** puede publicar la misma
-- oferta dos veces con dos precios, y eso lo acota `MAX_PER_STORE_PER_DAY`.
--
-- 2. ⚠️ KLIPER QUEDA AFUERA, Y EL MOTIVO ES PRESUPUESTO
--
-- Kliper sola cuesta **706 requests / 35,7 min** por pasada —el 63% del lote— y
-- con ella la pasada iría de los ~57 min actuales a **~114 de los 120 de
-- `db.PASS_WINDOW`**. Una pasada que cruza esa ventana **se parte en dos** para
-- `runner.pasadas_flacas`, y eso convierte la guarda de volumen en una fuente de
-- falsos positivos. Sin ella el lote son **461 requests / 17,7 min** y la pasada
-- queda en **~75 min**.
--
-- (Kliper tenía además una decisión abierta: 886 de sus 2.462 SKUs —36%— solo
-- son alcanzables por su eje `marcas`, que no es una vitrina de promoción sino la
-- forma natural de navegar un multimarca. El presupuesto la resuelve por ahora.)
--
-- 3. LAS LLAVES SALEN DE UN BARRIDO CON EL PARSER DE PRODUCCIÓN
--
-- Barrí **1.308 hojas de las 7 tiendas, 722 MB**, enumerando la página 1 de cada
-- una con `magento_html.parse_listing` y cruzando los `store_sku`. De ahí salen
-- las 436 llaves de abajo. Tres filtros, en este orden:
--
-- a) **Fuera las vitrinas.** Que lo son lo dice la medición y no el nombre:
--    `destacado` solapa 36-55% con **todos** los demás ejes de Speedo, y en Trek
--    `destacado × ninos` y `cyber × accesorios-ciclismo` dan **100%**. Lo
--    descartado aporta 10 a 58 SKUs exclusivos en cuatro de las seis tiendas.
--    ⚠️ Excepción decidida por el dueño el 2026-11-05: en **New Balance** las
--    vitrinas tienen **499 SKUs exclusivos (35%)** y **se excluyen igual** — no es
--    un faltante de cobertura, es la decisión de no construir series sobre algo
--    que el comerciante reedita (el caso Prat: 240 listings muertos de golpe, y
--    el canario callado a las 4 corridas).
--
-- b) **Fuera los ejes que mezclan categorías internas.** Una llave cuyo contenido
--    span calzado + vestuario + equipamiento **no puede llevar un solo θ**, que es
--    la misma razón por la que no se conectan los catch-all `Varios` y `Otros` de
--    la migración 41. Quedaron afuera `/hombre/actividad/*` y `/hombre/coleccion/*`
--    (Speedo y TNF), `/deportes/deportes/*` (New Balance), `/ninos/por-edad/*`
--    (Trek) y `newarrivals` (Marmot). Cuesta entre 0% y 6,5% de cobertura.
--    En Trek **no se excluyó nada por eso**: su catálogo entero es ciclismo, así
--    que la raíz ya determina la categoría y sus ejes `por-modelo` / `por-familia`
--    son todos `deporte-equipamiento`.
--
-- c) **Fuera los padres cuyas hijas también entran.** Acá la regla de Falabella
--    (`cat2083/Zapatillas`: entra el paraguas, no la hoja) **se invierte**, y vale
--    decir por qué: en Falabella el paraguas pagina y cubre el subárbol entero;
--    en la plantilla de Sparta el paraguas está **topeado en una página de 36**
--    mientras sus hijas juntas dan 124-152 SKUs. Medido: 32 padres solapaban
--    69-100% con sus hijas. Se quedan las hijas; soltar los padres costó 5, 3 y
--    27 SKUs.
--
-- 4. COBERTURA Y COSTO, POR TIENDA
--
--   tienda            llaves   SKUs   requests   min    canario
--   speedo                39    353         39   0,7    estadístico
--   trekbikeschile        71    510         71   1,2    estadístico
--   newbalance            54    828         54   0,9    estadístico
--   thenorthface         100  1.201        119   6,0    estadístico
--   mammut                97    465        100   5,1    estadístico
--   marmot                75    296         78   3,9    estadístico
--   ---------------------------------------------------------------
--   TOTAL                436  3.653        461  17,7
--
-- ⚠️ Los SKUs de las tres que paginan son **de la página 1** y NO son su techo:
-- en producción recolectan más. De esta medición se lee **qué llaves usar**, no
-- cuánto se alcanza.
--
-- **Canario estadístico en las seis.** Ninguna sostiene el exacto: el conjunto
-- elegido deja fuera a los padres, así que `enumerado < declarado` por diseño en
-- cualquier llave que tenga hijas. Queda el canario de `runner.canary_verdict`
-- contra su propia historia, más `catalogo_mas_grande_que_la_ventana`.
--
-- 5. θ: SE USA EL VIGENTE Y SE PUEDE MEDIR DESPUÉS
--
-- Las tres categorías ya existen —`deporte-calzado` 0.300, `deporte-vestuario`
-- 0.350, `deporte-equipamiento` 0.250— y van al tema `deporte`. **No se toca
-- ninguna.** Dato para cuando se calibre: las seis declaran `price_normal` entre
-- el **36,5% y el 64,8%** de sus filas (thenorthface 36,5%, newbalance 39,5%,
-- speedo 41,5%, trek 42,4%, mammut 55,3%, marmot 64,8%), así que ahí θ **sí se
-- puede fijar midiendo** — a diferencia de Nike, que no declara ninguno.
--
-- Aritmética de `CLAUDE.md`: el tema `deporte` tiene `daily_quota = 5` y ya tiene
-- las 3 categorías ruteadas, así que 3 × `MAX_PER_CATEGORY_PER_DAY` = 9 ≥ 5. Y
-- `tiendas_con_baseline_madura × MAX_PER_STORE_PER_DAY ≥ cuota` pasa a estar
-- holgado: hoy el tema lo alimentan Andesgear y Nike, y suma seis más.
--
-- 6. LO QUE HAY QUE SABER Y NO BLOQUEA
--
-- 🔴 **`sin_stock = 0` en las seis**, sobre 14.000+ filas: ninguna trae señal de
-- stock en el grid, y `publisher/stock.py` solo sabe leer la familia Falabella.
-- Hay que verificar si ocultan el agotado (como Sparta y Colloky, y entonces no
-- cuesta nada) o lo listan como disponible (como Paris, y entonces engaña).
--
-- ⚠️ **`thenorthface` tiene un precio máximo de .999.990**, muy por encima del
-- resto del outdoor (,0M a ,8M). **Mirar qué es antes de la primera pasada**:
-- o es equipamiento de expedición legítimo, o es un centinela — y un centinela
-- **envenena la baseline de ese SKU de forma permanente**.
--
-- ⚠️ **`trekbikeschile` llega a .990.000** (bicicleta de ruta). `compute_score`
-- no mira el precio absoluto a propósito, así que un 30% ahí son ,3M de ahorro
-- puntuando igual que un 30% sobre unos anteojos de .990. Mismo choque de
-- rango que el supermercado; la respuesta por precedente no es tocar el score.
--
-- 7. FECHAS
--
-- Conexión **2026-11-05**. Ninguna publica hasta el **2026-12-05**, y se evalúan
-- con `python -m scripts.aceptacion_tienda --store <slug>` ese día, contra días
-- **observados** y no calendario.
--
-- ⚠️ **Conectar por tandas y medir la pasada después de cada una.** El runner es
-- secuencial: 461 requests nuevos son 17,7 min sobre los ~57 actuales. Si la
-- pasada se acerca a los 120 de `PASS_WINDOW`, hay que parar antes de sumar
-- Kliper, Sparta o Lippi.
-- =============================================================================

INSERT INTO stores (slug, name, base_url, adapter, rate_limit_rps, is_active) VALUES
    ('speedo', 'Speedo Chile', 'https://speedo.cl',
     'scrapers.stores.magento_html:SpeedoAdapter', 1.0, TRUE),
    ('trekbikeschile', 'Trek Chile', 'https://trekbikeschile.com',
     'scrapers.stores.magento_html:TrekChileAdapter', 1.0, TRUE),
    ('newbalance', 'New Balance Chile', 'https://newbalance.cl',
     'scrapers.stores.magento_html:NewBalanceChileAdapter', 1.0, TRUE),
    ('thenorthface', 'The North Face Chile', 'https://www.thenorthface.cl',
     'scrapers.stores.magento_html:TheNorthFaceAdapter', 0.33, TRUE),
    ('mammut', 'Mammut Chile', 'https://www.mammut.cl',
     'scrapers.stores.magento_html:MammutAdapter', 0.33, TRUE),
    ('marmot', 'Marmot Chile', 'https://www.marmot.cl',
     'scrapers.stores.magento_html:MarmotAdapter', 0.33, TRUE)
ON CONFLICT (slug) DO UPDATE
    SET name     = EXCLUDED.name,
        base_url = EXCLUDED.base_url,
        adapter  = EXCLUDED.adapter;

INSERT INTO store_categories (store_id, category_id, store_key)
SELECT s.id, c.id, v.store_key
  FROM (VALUES
        ('speedo', 'deporte-calzado', 'hombre/calzado/sandalias.html'),
        ('speedo', 'deporte-calzado', 'hombre/calzado/zapatos-de-agua.html'),
        ('speedo', 'deporte-calzado', 'mujer/calzado/sandalias.html'),
        ('speedo', 'deporte-calzado', 'mujer/calzado/zapatos-de-agua.html'),
        ('speedo', 'deporte-calzado', 'ninos/calzado/sandalias.html'),
        ('speedo', 'deporte-equipamiento', 'equipamiento/genero/hombre.html'),
        ('speedo', 'deporte-equipamiento', 'equipamiento/genero/mujer.html'),
        ('speedo', 'deporte-equipamiento', 'equipamiento/genero/ninos.html'),
        ('speedo', 'deporte-equipamiento', 'equipamiento/tipo/aletas-y-paddles.html'),
        ('speedo', 'deporte-equipamiento', 'equipamiento/tipo/anteojos.html'),
        ('speedo', 'deporte-equipamiento', 'equipamiento/tipo/aprendizaje.html'),
        ('speedo', 'deporte-equipamiento', 'equipamiento/tipo/bolsos-y-mochilas.html'),
        ('speedo', 'deporte-equipamiento', 'equipamiento/tipo/botellas.html'),
        ('speedo', 'deporte-equipamiento', 'equipamiento/tipo/entrenamiento.html'),
        ('speedo', 'deporte-equipamiento', 'equipamiento/tipo/gorros.html'),
        ('speedo', 'deporte-equipamiento', 'equipamiento/tipo/snorkel.html'),
        ('speedo', 'deporte-equipamiento', 'equipamiento/tipo/tablas-y-pull-buoy.html'),
        ('speedo', 'deporte-equipamiento', 'equipamiento/tipo/tapones-y-nariceras.html'),
        ('speedo', 'deporte-equipamiento', 'lentes/coleccion/biofuse.html'),
        ('speedo', 'deporte-equipamiento', 'lentes/coleccion/jet.html'),
        ('speedo', 'deporte-equipamiento', 'lentes/coleccion/vanquisher.html'),
        ('speedo', 'deporte-equipamiento', 'lentes/genero/hombre.html'),
        ('speedo', 'deporte-equipamiento', 'lentes/genero/mujer.html'),
        ('speedo', 'deporte-equipamiento', 'lentes/genero/ninos.html'),
        ('speedo', 'deporte-equipamiento', 'lentes/tipo/competicion.html'),
        ('speedo', 'deporte-equipamiento', 'lentes/tipo/entrenamiento.html'),
        ('speedo', 'deporte-equipamiento', 'lentes/tipo/recreacion.html'),
        ('speedo', 'deporte-equipamiento', 'lentes/tipo/snorkelling.html'),
        ('speedo', 'deporte-vestuario', 'hombre/trajes-de-bano/aquashort.html'),
        ('speedo', 'deporte-vestuario', 'hombre/trajes-de-bano/brief.html'),
        ('speedo', 'deporte-vestuario', 'hombre/trajes-de-bano/jammer.html'),
        ('speedo', 'deporte-vestuario', 'hombre/trajes-de-bano/poleras-uv.html'),
        ('speedo', 'deporte-vestuario', 'hombre/trajes-de-bano/trajes-de-bano.html'),
        ('speedo', 'deporte-vestuario', 'mujer/trajes-de-bano/bikini.html'),
        ('speedo', 'deporte-vestuario', 'mujer/trajes-de-bano/entero.html'),
        ('speedo', 'deporte-vestuario', 'mujer/trajes-de-bano/poleras-uv-y-shorts.html'),
        ('speedo', 'deporte-vestuario', 'ninos/trajes-de-bano/competicion.html'),
        ('speedo', 'deporte-vestuario', 'ninos/trajes-de-bano/entrenamiento.html'),
        ('speedo', 'deporte-vestuario', 'ninos/trajes-de-bano/recreacion.html'),
        ('trekbikeschile', 'deporte-equipamiento', 'accesorios-ciclismo/por-modelo/marlin.html'),
        ('trekbikeschile', 'deporte-equipamiento', 'accesorios-ciclismo/por-modelo/slash.html'),
        ('trekbikeschile', 'deporte-equipamiento', 'bicicletas-electricas/por-categoria/montana.html'),
        ('trekbikeschile', 'deporte-equipamiento', 'bicicletas-electricas/por-modelo/powerfly.html'),
        ('trekbikeschile', 'deporte-equipamiento', 'bicicletas-electricas/por-modelo/rail.html'),
        ('trekbikeschile', 'deporte-equipamiento', 'bicicletas-electricas/precios-especiales-ebikes.html'),
        ('trekbikeschile', 'deporte-equipamiento', 'equipamiento/accesorios/bolsos.html'),
        ('trekbikeschile', 'deporte-equipamiento', 'equipamiento/accesorios/bombines.html'),
        ('trekbikeschile', 'deporte-equipamiento', 'equipamiento/accesorios/candados-porta-bebes-y-porta-bicicletas.html'),
        ('trekbikeschile', 'deporte-equipamiento', 'equipamiento/accesorios/candados.html'),
        ('trekbikeschile', 'deporte-equipamiento', 'equipamiento/accesorios/caramagiolas-y-porta-caramagiolas.html'),
        ('trekbikeschile', 'deporte-equipamiento', 'equipamiento/accesorios/cascos.html'),
        ('trekbikeschile', 'deporte-equipamiento', 'equipamiento/accesorios/ciclo-computadores.html'),
        ('trekbikeschile', 'deporte-equipamiento', 'equipamiento/accesorios/guantes.html'),
        ('trekbikeschile', 'deporte-equipamiento', 'equipamiento/accesorios/herramientas.html'),
        ('trekbikeschile', 'deporte-equipamiento', 'equipamiento/accesorios/lubricantes-y-mantenimiento.html'),
        ('trekbikeschile', 'deporte-equipamiento', 'equipamiento/accesorios/luces.html'),
        ('trekbikeschile', 'deporte-equipamiento', 'equipamiento/accesorios/portabicicletas.html'),
        ('trekbikeschile', 'deporte-equipamiento', 'equipamiento/accesorios/rodillos.html'),
        ('trekbikeschile', 'deporte-equipamiento', 'equipamiento/accesorios/sillas-porta-bebes.html'),
        ('trekbikeschile', 'deporte-equipamiento', 'equipamiento/accesorios/zapatos.html'),
        ('trekbikeschile', 'deporte-equipamiento', 'equipamiento/componentes/asientos.html'),
        ('trekbikeschile', 'deporte-equipamiento', 'equipamiento/componentes/camaras-y-accesorios.html'),
        ('trekbikeschile', 'deporte-equipamiento', 'equipamiento/componentes/frenos.html'),
        ('trekbikeschile', 'deporte-equipamiento', 'equipamiento/componentes/grip-y-cinta-de-manubrio.html'),
        ('trekbikeschile', 'deporte-equipamiento', 'equipamiento/componentes/manubrios.html'),
        ('trekbikeschile', 'deporte-equipamiento', 'equipamiento/componentes/neumaticos.html'),
        ('trekbikeschile', 'deporte-equipamiento', 'equipamiento/componentes/pedales.html'),
        ('trekbikeschile', 'deporte-equipamiento', 'equipamiento/componentes/transmision.html'),
        ('trekbikeschile', 'deporte-equipamiento', 'equipamiento/componentes/tubos-de-asientos.html'),
        ('trekbikeschile', 'deporte-equipamiento', 'equipamiento/tecnologia/banda-cardiaca.html'),
        ('trekbikeschile', 'deporte-equipamiento', 'equipamiento/tecnologia/ciclo-computadores.html'),
        ('trekbikeschile', 'deporte-equipamiento', 'equipamiento/tecnologia/relojes.html'),
        ('trekbikeschile', 'deporte-equipamiento', 'equipamiento/vestuario-ciclismo/ropa-para-hombres.html'),
        ('trekbikeschile', 'deporte-equipamiento', 'equipamiento/vestuario-ciclismo/ropa-para-mujeres.html'),
        ('trekbikeschile', 'deporte-equipamiento', 'equipamiento/vestuario-ciclismo/zapatos-para-hombres.html'),
        ('trekbikeschile', 'deporte-equipamiento', 'equipamiento/vestuario-ciclismo/zapatos-para-mujeres.html'),
        ('trekbikeschile', 'deporte-equipamiento', 'gravel/por-familia/checkpoint.html'),
        ('trekbikeschile', 'deporte-equipamiento', 'gravel/por-familia/domane.html'),
        ('trekbikeschile', 'deporte-equipamiento', 'montana/familias-doble-suspension/fuel-ex.html'),
        ('trekbikeschile', 'deporte-equipamiento', 'montana/familias-doble-suspension/fuel-exe.html'),
        ('trekbikeschile', 'deporte-equipamiento', 'montana/familias-doble-suspension/powerfly-fs.html'),
        ('trekbikeschile', 'deporte-equipamiento', 'montana/familias-doble-suspension/rail.html'),
        ('trekbikeschile', 'deporte-equipamiento', 'montana/familias-doble-suspension/slash.html'),
        ('trekbikeschile', 'deporte-equipamiento', 'montana/familias-doble-suspension/supercaliber.html'),
        ('trekbikeschile', 'deporte-equipamiento', 'montana/familias-doble-suspension/top-fuel.html'),
        ('trekbikeschile', 'deporte-equipamiento', 'montana/familias-rigidas/marlin.html'),
        ('trekbikeschile', 'deporte-equipamiento', 'montana/familias-rigidas/procaliber.html'),
        ('trekbikeschile', 'deporte-equipamiento', 'montana/familias-rigidas/x-caliber.html'),
        ('trekbikeschile', 'deporte-equipamiento', 'montana/por-categoria/cross-country.html'),
        ('trekbikeschile', 'deporte-equipamiento', 'montana/por-categoria/doble-suspension.html'),
        ('trekbikeschile', 'deporte-equipamiento', 'montana/por-categoria/enduro.html'),
        ('trekbikeschile', 'deporte-equipamiento', 'montana/por-categoria/montana-electricas.html'),
        ('trekbikeschile', 'deporte-equipamiento', 'montana/por-categoria/rigidas.html'),
        ('trekbikeschile', 'deporte-equipamiento', 'ninos/cascos.html'),
        ('trekbikeschile', 'deporte-equipamiento', 'ninos/por-altura/114-cm-121-cm-24-rueda.html'),
        ('trekbikeschile', 'deporte-equipamiento', 'ninos/por-altura/76-cm-88-cm-12-rueda.html'),
        ('trekbikeschile', 'deporte-equipamiento', 'ninos/por-altura/89-cm-101-cm-16-rueda.html'),
        ('trekbikeschile', 'deporte-equipamiento', 'ninos/por-altura/99-cm-116-cm-20-rueda.html'),
        ('trekbikeschile', 'deporte-equipamiento', 'ninos/por-coleccion/bicicletas-para-ninos.html'),
        ('trekbikeschile', 'deporte-equipamiento', 'ruta/por-categoria/gravel.html'),
        ('trekbikeschile', 'deporte-equipamiento', 'ruta/por-categoria/ruta.html'),
        ('trekbikeschile', 'deporte-equipamiento', 'ruta/por-categoria/triatlon.html'),
        ('trekbikeschile', 'deporte-equipamiento', 'ruta/por-coleccion/bicicletas-de-ruta-de-aluminio.html'),
        ('trekbikeschile', 'deporte-equipamiento', 'ruta/por-coleccion/bicicletas-de-ruta-de-carbono.html'),
        ('trekbikeschile', 'deporte-equipamiento', 'ruta/por-modelo/checkpoint.html'),
        ('trekbikeschile', 'deporte-equipamiento', 'ruta/por-modelo/domane.html'),
        ('trekbikeschile', 'deporte-equipamiento', 'ruta/por-modelo/madone.html'),
        ('trekbikeschile', 'deporte-equipamiento', 'ruta/por-modelo/speed-concept.html'),
        ('trekbikeschile', 'deporte-equipamiento', 'urbana/por-categoria/hibridas-y-urbanas.html'),
        ('trekbikeschile', 'deporte-equipamiento', 'urbana/por-modelo/fx.html'),
        ('newbalance', 'deporte-calzado', 'hombre/zapatillas/zapatillas-atletismo-1.html'),
        ('newbalance', 'deporte-calzado', 'hombre/zapatillas/zapatillas-basquetbol.html'),
        ('newbalance', 'deporte-calzado', 'hombre/zapatillas/zapatillas-futbol.html'),
        ('newbalance', 'deporte-calzado', 'hombre/zapatillas/zapatillas-running.html'),
        ('newbalance', 'deporte-calzado', 'hombre/zapatillas/zapatillas-skateboarding.html'),
        ('newbalance', 'deporte-calzado', 'hombre/zapatillas/zapatillas-tenis.html'),
        ('newbalance', 'deporte-calzado', 'hombre/zapatillas/zapatillas-trail-running.html'),
        ('newbalance', 'deporte-calzado', 'hombre/zapatillas/zapatillas-urbanas.html'),
        ('newbalance', 'deporte-calzado', 'mujer/zapatillas/zapatillas-atletismo.html'),
        ('newbalance', 'deporte-calzado', 'mujer/zapatillas/zapatillas-running.html'),
        ('newbalance', 'deporte-calzado', 'mujer/zapatillas/zapatillas-tenis.html'),
        ('newbalance', 'deporte-calzado', 'mujer/zapatillas/zapatillas-trail-running.html'),
        ('newbalance', 'deporte-calzado', 'mujer/zapatillas/zapatillas-urbanas-lifestyle.html'),
        ('newbalance', 'deporte-calzado', 'ninos/ninos/zapatillas.html'),
        ('newbalance', 'deporte-calzado', 'zapatillas/zapatillas-ni-os.html'),
        ('newbalance', 'deporte-calzado', 'zapatillas/zapatillas-tenis.html'),
        ('newbalance', 'deporte-calzado', 'zapatillas/zapatillas-trail-running.html'),
        ('newbalance', 'deporte-calzado', 'zapatillas/zapatillas-urbanas.html'),
        ('newbalance', 'deporte-calzado', 'zapatillas/zapatos-futbol.html'),
        ('newbalance', 'deporte-equipamiento', 'hombre/accesorios/accesorios-de-futbol.html'),
        ('newbalance', 'deporte-equipamiento', 'hombre/accesorios/accesorios-de-running.html'),
        ('newbalance', 'deporte-equipamiento', 'hombre/accesorios/jockeys.html'),
        ('newbalance', 'deporte-equipamiento', 'hombre/accesorios/mochilas-y-bolsos.html'),
        ('newbalance', 'deporte-equipamiento', 'mujer/accesorios/accesorios-de-futbol.html'),
        ('newbalance', 'deporte-equipamiento', 'mujer/accesorios/accesorios-de-running.html'),
        ('newbalance', 'deporte-equipamiento', 'mujer/accesorios/jockeys-y-cintillos.html'),
        ('newbalance', 'deporte-equipamiento', 'mujer/accesorios/mochilas-y-bolsos.html'),
        ('newbalance', 'deporte-equipamiento', 'ninos/ninos/accesorios.html'),
        ('newbalance', 'deporte-vestuario', 'hombre/accesorios/calcetines-y-guantes.html'),
        ('newbalance', 'deporte-vestuario', 'hombre/ropa/calzas.html'),
        ('newbalance', 'deporte-vestuario', 'hombre/ropa/cortavientos.html'),
        ('newbalance', 'deporte-vestuario', 'hombre/ropa/pantalones.html'),
        ('newbalance', 'deporte-vestuario', 'hombre/ropa/parkas-y-chaquetas.html'),
        ('newbalance', 'deporte-vestuario', 'hombre/ropa/poleras.html'),
        ('newbalance', 'deporte-vestuario', 'hombre/ropa/polerones.html'),
        ('newbalance', 'deporte-vestuario', 'hombre/ropa/shorts.html'),
        ('newbalance', 'deporte-vestuario', 'mujer/accesorios/calcetines-y-guantes.html'),
        ('newbalance', 'deporte-vestuario', 'mujer/ropa/calzas.html'),
        ('newbalance', 'deporte-vestuario', 'mujer/ropa/chaquetas-y-polerones.html'),
        ('newbalance', 'deporte-vestuario', 'mujer/ropa/cortavientos.html'),
        ('newbalance', 'deporte-vestuario', 'mujer/ropa/pantalones.html'),
        ('newbalance', 'deporte-vestuario', 'mujer/ropa/parkas-y-chaquetas.html'),
        ('newbalance', 'deporte-vestuario', 'mujer/ropa/petos.html'),
        ('newbalance', 'deporte-vestuario', 'mujer/ropa/poleras.html'),
        ('newbalance', 'deporte-vestuario', 'mujer/ropa/shorts.html'),
        ('newbalance', 'deporte-vestuario', 'ropa/pantalones.html'),
        ('newbalance', 'deporte-vestuario', 'ropa/poleras.html'),
        ('newbalance', 'deporte-vestuario', 'ropa/polerones.html'),
        ('newbalance', 'deporte-vestuario', 'ropa/ropa-urbana/pantalones.html'),
        ('newbalance', 'deporte-vestuario', 'ropa/ropa-urbana/poleras.html'),
        ('newbalance', 'deporte-vestuario', 'ropa/ropa-urbana/polerones.html'),
        ('newbalance', 'deporte-vestuario', 'ropa/ropa-urbana/shorts.html'),
        ('newbalance', 'deporte-vestuario', 'ropa/ropa-y-accesorios-tenis.html'),
        ('newbalance', 'deporte-vestuario', 'ropa/shorts.html'),
        ('thenorthface', 'deporte-calzado', 'hombre/zapatos/botas-invernales'),
        ('thenorthface', 'deporte-calzado', 'hombre/zapatos/casuales'),
        ('thenorthface', 'deporte-calzado', 'hombre/zapatos/pantuflas'),
        ('thenorthface', 'deporte-calzado', 'hombre/zapatos/sandalias'),
        ('thenorthface', 'deporte-calzado', 'hombre/zapatos/trail-running'),
        ('thenorthface', 'deporte-calzado', 'hombre/zapatos/trekking'),
        ('thenorthface', 'deporte-calzado', 'mujer/zapatos/botas-invernales'),
        ('thenorthface', 'deporte-calzado', 'mujer/zapatos/casuales'),
        ('thenorthface', 'deporte-calzado', 'mujer/zapatos/pantuflas'),
        ('thenorthface', 'deporte-calzado', 'mujer/zapatos/sandalias'),
        ('thenorthface', 'deporte-calzado', 'mujer/zapatos/trail-running'),
        ('thenorthface', 'deporte-calzado', 'mujer/zapatos/trekking'),
        ('thenorthface', 'deporte-calzado', 'ni-os/zapatos/ni-as'),
        ('thenorthface', 'deporte-calzado', 'ni-os/zapatos/ni-os'),
        ('thenorthface', 'deporte-calzado', 'zapatos/hombre/botas-invernales'),
        ('thenorthface', 'deporte-calzado', 'zapatos/hombre/casuales'),
        ('thenorthface', 'deporte-calzado', 'zapatos/hombre/pantuflas'),
        ('thenorthface', 'deporte-calzado', 'zapatos/hombre/sandalias'),
        ('thenorthface', 'deporte-calzado', 'zapatos/hombre/trail-running'),
        ('thenorthface', 'deporte-calzado', 'zapatos/hombre/trekking'),
        ('thenorthface', 'deporte-calzado', 'zapatos/mujer/botas-invernales'),
        ('thenorthface', 'deporte-calzado', 'zapatos/mujer/casuales'),
        ('thenorthface', 'deporte-calzado', 'zapatos/mujer/pantuflas'),
        ('thenorthface', 'deporte-calzado', 'zapatos/mujer/sandalias'),
        ('thenorthface', 'deporte-calzado', 'zapatos/mujer/trail-running'),
        ('thenorthface', 'deporte-calzado', 'zapatos/mujer/trekking'),
        ('thenorthface', 'deporte-calzado', 'zapatos/ni-os/ni-as'),
        ('thenorthface', 'deporte-calzado', 'zapatos/ni-os/ni-os'),
        ('thenorthface', 'deporte-equipamiento', 'equipamiento/bolsos-y-maletas/accesorios-de-viaje'),
        ('thenorthface', 'deporte-equipamiento', 'equipamiento/bolsos-y-maletas/bananos'),
        ('thenorthface', 'deporte-equipamiento', 'equipamiento/bolsos-y-maletas/bolsos'),
        ('thenorthface', 'deporte-equipamiento', 'equipamiento/bolsos-y-maletas/maletas'),
        ('thenorthface', 'deporte-equipamiento', 'equipamiento/carpas/3-estaciones-camping'),
        ('thenorthface', 'deporte-equipamiento', 'equipamiento/carpas/4-estaciones-expedicion'),
        ('thenorthface', 'deporte-equipamiento', 'equipamiento/carpas/accesorios'),
        ('thenorthface', 'deporte-equipamiento', 'equipamiento/mochilas-casuales/hombre'),
        ('thenorthface', 'deporte-equipamiento', 'equipamiento/mochilas-casuales/mujer'),
        ('thenorthface', 'deporte-equipamiento', 'equipamiento/mochilas-casuales/ni-os'),
        ('thenorthface', 'deporte-equipamiento', 'equipamiento/mochilas-tecnicas/accesorios'),
        ('thenorthface', 'deporte-equipamiento', 'equipamiento/mochilas-tecnicas/escalada-monta-a'),
        ('thenorthface', 'deporte-equipamiento', 'equipamiento/mochilas-tecnicas/ski-snowboard'),
        ('thenorthface', 'deporte-equipamiento', 'equipamiento/mochilas-tecnicas/trail-running'),
        ('thenorthface', 'deporte-equipamiento', 'equipamiento/mochilas-tecnicas/trekking'),
        ('thenorthface', 'deporte-equipamiento', 'equipamiento/sacos-de-dormir/plumas'),
        ('thenorthface', 'deporte-equipamiento', 'equipamiento/sacos-de-dormir/rango-t-20-c-a-0-c'),
        ('thenorthface', 'deporte-equipamiento', 'equipamiento/sacos-de-dormir/sinteticos'),
        ('thenorthface', 'deporte-equipamiento', 'hombre/accesorios/cuellos'),
        ('thenorthface', 'deporte-equipamiento', 'hombre/accesorios/jockeys-sombreros'),
        ('thenorthface', 'deporte-equipamiento', 'hombre/accesorios/jockeys-y-sombreros'),
        ('thenorthface', 'deporte-equipamiento', 'mujer/accesorios/cuellos'),
        ('thenorthface', 'deporte-equipamiento', 'mujer/accesorios/jockeys-y-sombreros'),
        ('thenorthface', 'deporte-vestuario', 'hombre/accesorios/calcetines'),
        ('thenorthface', 'deporte-vestuario', 'hombre/accesorios/gorros'),
        ('thenorthface', 'deporte-vestuario', 'hombre/accesorios/gorros-jockeys'),
        ('thenorthface', 'deporte-vestuario', 'hombre/accesorios/guantes'),
        ('thenorthface', 'deporte-vestuario', 'hombre/chaquetas/chaquetas-3-en-1'),
        ('thenorthface', 'deporte-vestuario', 'hombre/chaquetas/cortaviento'),
        ('thenorthface', 'deporte-vestuario', 'hombre/chaquetas/impermeables'),
        ('thenorthface', 'deporte-vestuario', 'hombre/chaquetas/ski-snowboard'),
        ('thenorthface', 'deporte-vestuario', 'hombre/chaquetas/termicas'),
        ('thenorthface', 'deporte-vestuario', 'hombre/chaquetas/vests'),
        ('thenorthface', 'deporte-vestuario', 'hombre/polar/clasico'),
        ('thenorthface', 'deporte-vestuario', 'hombre/polar/sherpa'),
        ('thenorthface', 'deporte-vestuario', 'hombre/polar/sweater'),
        ('thenorthface', 'deporte-vestuario', 'hombre/polar/tecnico'),
        ('thenorthface', 'deporte-vestuario', 'hombre/poleras-polerones/camisas'),
        ('thenorthface', 'deporte-vestuario', 'hombre/poleras-polerones/poleras'),
        ('thenorthface', 'deporte-vestuario', 'hombre/poleras-polerones/polerones'),
        ('thenorthface', 'deporte-vestuario', 'hombre/poleras-polerones/primeras-capas'),
        ('thenorthface', 'deporte-vestuario', 'hombre/shorts-pantalones/pantalones'),
        ('thenorthface', 'deporte-vestuario', 'hombre/shorts-pantalones/primeras-capas'),
        ('thenorthface', 'deporte-vestuario', 'hombre/shorts-pantalones/shorts'),
        ('thenorthface', 'deporte-vestuario', 'hombre/shorts-pantalones/trajes-de-ba-o'),
        ('thenorthface', 'deporte-vestuario', 'mujer/accesorios/calcetines'),
        ('thenorthface', 'deporte-vestuario', 'mujer/accesorios/gorros'),
        ('thenorthface', 'deporte-vestuario', 'mujer/accesorios/gorros-jockeys'),
        ('thenorthface', 'deporte-vestuario', 'mujer/accesorios/guantes'),
        ('thenorthface', 'deporte-vestuario', 'mujer/chaquetas/chaquetas-3-en-1'),
        ('thenorthface', 'deporte-vestuario', 'mujer/chaquetas/cortaviento'),
        ('thenorthface', 'deporte-vestuario', 'mujer/chaquetas/impermeables'),
        ('thenorthface', 'deporte-vestuario', 'mujer/chaquetas/ski-snowboard'),
        ('thenorthface', 'deporte-vestuario', 'mujer/chaquetas/termicas'),
        ('thenorthface', 'deporte-vestuario', 'mujer/chaquetas/vests'),
        ('thenorthface', 'deporte-vestuario', 'mujer/polar/clasico'),
        ('thenorthface', 'deporte-vestuario', 'mujer/polar/sherpa'),
        ('thenorthface', 'deporte-vestuario', 'mujer/polar/sweater'),
        ('thenorthface', 'deporte-vestuario', 'mujer/polar/tecnico'),
        ('thenorthface', 'deporte-vestuario', 'mujer/poleras-polerones/poleras-petos'),
        ('thenorthface', 'deporte-vestuario', 'mujer/poleras-polerones/polerones'),
        ('thenorthface', 'deporte-vestuario', 'mujer/poleras-polerones/primeras-capas'),
        ('thenorthface', 'deporte-vestuario', 'mujer/shorts-pantalones/pantalones-calzas'),
        ('thenorthface', 'deporte-vestuario', 'mujer/shorts-pantalones/primeras-capas'),
        ('thenorthface', 'deporte-vestuario', 'mujer/shorts-pantalones/shorts'),
        ('thenorthface', 'deporte-vestuario', 'ni-os/accesorios/guantes'),
        ('thenorthface', 'deporte-vestuario', 'ni-os/chaquetas/impermeables'),
        ('thenorthface', 'deporte-vestuario', 'ni-os/chaquetas/plumas'),
        ('thenorthface', 'deporte-vestuario', 'ni-os/chaquetas/ski-snowboard'),
        ('thenorthface', 'deporte-vestuario', 'ni-os/vestuario/pantalones-shorts'),
        ('thenorthface', 'deporte-vestuario', 'ni-os/vestuario/polar'),
        ('thenorthface', 'deporte-vestuario', 'ni-os/vestuario/polerones-y-poleras'),
        ('mammut', 'deporte-calzado', 'calzado/aproximacion'),
        ('mammut', 'deporte-calzado', 'calzado/hombre/alta-montana'),
        ('mammut', 'deporte-calzado', 'calzado/hombre/aproximacion'),
        ('mammut', 'deporte-calzado', 'calzado/hombre/media-montana'),
        ('mammut', 'deporte-calzado', 'calzado/hombre/montana'),
        ('mammut', 'deporte-calzado', 'calzado/hombre/trail-running'),
        ('mammut', 'deporte-calzado', 'calzado/hombre/trekking'),
        ('mammut', 'deporte-calzado', 'calzado/montana'),
        ('mammut', 'deporte-calzado', 'calzado/mujer/alta-montana'),
        ('mammut', 'deporte-calzado', 'calzado/mujer/aproximacion'),
        ('mammut', 'deporte-calzado', 'calzado/mujer/media-montana'),
        ('mammut', 'deporte-calzado', 'calzado/mujer/montana'),
        ('mammut', 'deporte-calzado', 'calzado/mujer/trail-running'),
        ('mammut', 'deporte-calzado', 'calzado/mujer/trekking'),
        ('mammut', 'deporte-calzado', 'calzado/trail-running'),
        ('mammut', 'deporte-calzado', 'calzado/trekking'),
        ('mammut', 'deporte-calzado', 'hombre/calzado/alta-monta-a'),
        ('mammut', 'deporte-calzado', 'hombre/calzado/aproximacion'),
        ('mammut', 'deporte-calzado', 'hombre/calzado/casuales'),
        ('mammut', 'deporte-calzado', 'hombre/calzado/montana'),
        ('mammut', 'deporte-calzado', 'hombre/calzado/trail-running'),
        ('mammut', 'deporte-calzado', 'hombre/calzado/trekking'),
        ('mammut', 'deporte-calzado', 'mujer/calzado/alta-monta-a'),
        ('mammut', 'deporte-calzado', 'mujer/calzado/aproximacion'),
        ('mammut', 'deporte-calzado', 'mujer/calzado/casuales'),
        ('mammut', 'deporte-calzado', 'mujer/calzado/montana'),
        ('mammut', 'deporte-calzado', 'mujer/calzado/trail-running'),
        ('mammut', 'deporte-calzado', 'mujer/calzado/trekking'),
        ('mammut', 'deporte-equipamiento', 'accesorios/bananos'),
        ('mammut', 'deporte-equipamiento', 'accesorios/billeteras'),
        ('mammut', 'deporte-equipamiento', 'accesorios/cuellos-y-balaclavas'),
        ('mammut', 'deporte-equipamiento', 'accesorios/guantes'),
        ('mammut', 'deporte-equipamiento', 'accesorios/jockeys-y-gorros'),
        ('mammut', 'deporte-equipamiento', 'equipamiento-mammut/equipo-de-escalada/accesorios-de-escalada'),
        ('mammut', 'deporte-equipamiento', 'equipamiento-mammut/equipo-de-escalada/arneses'),
        ('mammut', 'deporte-equipamiento', 'equipamiento-mammut/equipo-de-escalada/aseguradores'),
        ('mammut', 'deporte-equipamiento', 'equipamiento-mammut/equipo-de-escalada/cascos'),
        ('mammut', 'deporte-equipamiento', 'equipamiento-mammut/equipo-de-escalada/cintas'),
        ('mammut', 'deporte-equipamiento', 'equipamiento-mammut/equipo-de-escalada/cuerdas'),
        ('mammut', 'deporte-equipamiento', 'equipamiento-mammut/equipo-de-escalada/magnesio-y-magneseras'),
        ('mammut', 'deporte-equipamiento', 'equipamiento-mammut/equipo-de-escalada/mochilas-escalada'),
        ('mammut', 'deporte-equipamiento', 'equipamiento-mammut/equipo-de-escalada/mosquetones-y-cintas-express'),
        ('mammut', 'deporte-equipamiento', 'equipamiento-mammut/escalada'),
        ('mammut', 'deporte-equipamiento', 'equipamiento-mammut/mochilas-y-bolsos/accesorios-y-viajes'),
        ('mammut', 'deporte-equipamiento', 'equipamiento-mammut/mochilas-y-bolsos/bolsos'),
        ('mammut', 'deporte-equipamiento', 'equipamiento-mammut/mochilas-y-bolsos/mochilas-de-uso-diario'),
        ('mammut', 'deporte-equipamiento', 'equipamiento-mammut/mochilas-y-bolsos/mochilas-escalada'),
        ('mammut', 'deporte-equipamiento', 'equipamiento-mammut/mochilas-y-bolsos/mochilas-monta-a'),
        ('mammut', 'deporte-equipamiento', 'equipamiento-mammut/mochilas-y-bolsos/mochilas-nieve'),
        ('mammut', 'deporte-equipamiento', 'equipamiento-mammut/mochilas-y-bolsos/mochilas-trail-running'),
        ('mammut', 'deporte-equipamiento', 'equipamiento-mammut/mochilas-y-bolsos/mochilas-trekking'),
        ('mammut', 'deporte-equipamiento', 'equipamiento-mammut/mochilas-y-bolsos/mochilas-urbanas'),
        ('mammut', 'deporte-equipamiento', 'equipamiento-mammut/monta-ismo'),
        ('mammut', 'deporte-equipamiento', 'equipamiento-mammut/sacos-de-dormir/pluma'),
        ('mammut', 'deporte-equipamiento', 'equipamiento-mammut/sacos-de-dormir/sinteticos'),
        ('mammut', 'deporte-equipamiento', 'equipamiento-mammut/seguridad-avalanchas/airbags'),
        ('mammut', 'deporte-equipamiento', 'equipamiento-mammut/seguridad-avalanchas/arvas'),
        ('mammut', 'deporte-equipamiento', 'equipamiento-mammut/seguridad-avalanchas/mochilas-nieve'),
        ('mammut', 'deporte-equipamiento', 'equipamiento-mammut/seguridad-avalanchas/palas-y-sondas'),
        ('mammut', 'deporte-equipamiento', 'equipamiento-mammut/ski'),
        ('mammut', 'deporte-equipamiento', 'equipamiento-mammut/trail-running'),
        ('mammut', 'deporte-equipamiento', 'equipamiento-mammut/trekking'),
        ('mammut', 'deporte-equipamiento', 'hombre/accesorios/cuellos-y-balaclavas'),
        ('mammut', 'deporte-equipamiento', 'hombre/accesorios/jockeys-y-sombreros'),
        ('mammut', 'deporte-equipamiento', 'hombre/vestuario/accesorios'),
        ('mammut', 'deporte-equipamiento', 'mujer/accesorios/cinturones'),
        ('mammut', 'deporte-equipamiento', 'mujer/accesorios/cuellos-y-balaclavas'),
        ('mammut', 'deporte-equipamiento', 'mujer/accesorios/jockeys'),
        ('mammut', 'deporte-vestuario', 'hombre/accesorios/calcetines'),
        ('mammut', 'deporte-vestuario', 'hombre/accesorios/gorros'),
        ('mammut', 'deporte-vestuario', 'hombre/accesorios/guantes'),
        ('mammut', 'deporte-vestuario', 'hombre/chaquetas/3-en-1'),
        ('mammut', 'deporte-vestuario', 'hombre/chaquetas/componentes-3-en-1'),
        ('mammut', 'deporte-vestuario', 'hombre/chaquetas/cortavientos'),
        ('mammut', 'deporte-vestuario', 'hombre/chaquetas/impermeables'),
        ('mammut', 'deporte-vestuario', 'hombre/chaquetas/impermeables-y-cortavientos'),
        ('mammut', 'deporte-vestuario', 'hombre/chaquetas/pluma'),
        ('mammut', 'deporte-vestuario', 'hombre/chaquetas/sinteticas'),
        ('mammut', 'deporte-vestuario', 'hombre/vestuario/camisas'),
        ('mammut', 'deporte-vestuario', 'hombre/vestuario/pantalones-y-shorts'),
        ('mammut', 'deporte-vestuario', 'hombre/vestuario/polar-y-polerones'),
        ('mammut', 'deporte-vestuario', 'hombre/vestuario/poleras'),
        ('mammut', 'deporte-vestuario', 'hombre/vestuario/poleras-y-camisas'),
        ('mammut', 'deporte-vestuario', 'hombre/vestuario/primeras-capas'),
        ('mammut', 'deporte-vestuario', 'mujer/accesorios/calcetines'),
        ('mammut', 'deporte-vestuario', 'mujer/accesorios/gorros'),
        ('mammut', 'deporte-vestuario', 'mujer/accesorios/guantes'),
        ('mammut', 'deporte-vestuario', 'mujer/chaquetas/3-en-1'),
        ('mammut', 'deporte-vestuario', 'mujer/chaquetas/cortavientos'),
        ('mammut', 'deporte-vestuario', 'mujer/chaquetas/impermeables'),
        ('mammut', 'deporte-vestuario', 'mujer/chaquetas/impermeables-y-cortavientos'),
        ('mammut', 'deporte-vestuario', 'mujer/chaquetas/pluma'),
        ('mammut', 'deporte-vestuario', 'mujer/chaquetas/sinteticas'),
        ('mammut', 'deporte-vestuario', 'mujer/vestuario/pantalones-y-shorts'),
        ('mammut', 'deporte-vestuario', 'mujer/vestuario/polar-y-polerones'),
        ('mammut', 'deporte-vestuario', 'mujer/vestuario/poleras-y-camisas'),
        ('mammut', 'deporte-vestuario', 'mujer/vestuario/primeras-capas'),
        ('marmot', 'deporte-calzado', 'calzado/hombre'),
        ('marmot', 'deporte-calzado', 'calzado/mujer'),
        ('marmot', 'deporte-calzado', 'hombre/calzado'),
        ('marmot', 'deporte-calzado', 'mujer/calzado'),
        ('marmot', 'deporte-equipamiento', 'accesorios/balaclavas'),
        ('marmot', 'deporte-equipamiento', 'accesorios/bananos'),
        ('marmot', 'deporte-equipamiento', 'accesorios/cinturones'),
        ('marmot', 'deporte-equipamiento', 'accesorios/gorros'),
        ('marmot', 'deporte-equipamiento', 'accesorios/guantes'),
        ('marmot', 'deporte-equipamiento', 'accesorios/jockeys'),
        ('marmot', 'deporte-equipamiento', 'accesorios/neceseres'),
        ('marmot', 'deporte-equipamiento', 'equipamiento/carpas/familiares'),
        ('marmot', 'deporte-equipamiento', 'equipamiento/carpas/monta-a-y-expedicion'),
        ('marmot', 'deporte-equipamiento', 'equipamiento/carpas/trekking'),
        ('marmot', 'deporte-equipamiento', 'equipamiento/carpas/ultraligeras'),
        ('marmot', 'deporte-equipamiento', 'equipamiento/maletas-y-bolsos/duffle-bags'),
        ('marmot', 'deporte-equipamiento', 'equipamiento/maletas-y-bolsos/neceseres'),
        ('marmot', 'deporte-equipamiento', 'equipamiento/mochilas/backpacking'),
        ('marmot', 'deporte-equipamiento', 'equipamiento/mochilas/escalada-y-nieve'),
        ('marmot', 'deporte-equipamiento', 'equipamiento/mochilas/mochilas-para-ni-os'),
        ('marmot', 'deporte-equipamiento', 'equipamiento/mochilas/trekking'),
        ('marmot', 'deporte-equipamiento', 'equipamiento/mochilas/urbanas'),
        ('marmot', 'deporte-equipamiento', 'equipamiento/newarrivals'),
        ('marmot', 'deporte-equipamiento', 'equipamiento/sacos-de-dormir/accesorios'),
        ('marmot', 'deporte-equipamiento', 'equipamiento/sacos-de-dormir/plumas'),
        ('marmot', 'deporte-equipamiento', 'equipamiento/sacos-de-dormir/sacos-de-pluma'),
        ('marmot', 'deporte-equipamiento', 'equipamiento/sacos-de-dormir/sacos-para-mujer'),
        ('marmot', 'deporte-equipamiento', 'equipamiento/sacos-de-dormir/sacos-para-ni-os'),
        ('marmot', 'deporte-equipamiento', 'equipamiento/sacos-de-dormir/sacos-sinteticos'),
        ('marmot', 'deporte-equipamiento', 'equipamiento/sacos-de-dormir/sinteticos'),
        ('marmot', 'deporte-equipamiento', 'hombre/accesorios/jockeys-y-sombreros'),
        ('marmot', 'deporte-equipamiento', 'mujer/accesorios/jockeys-y-sombreros'),
        ('marmot', 'deporte-equipamiento', 'ni-os/equipo-y-accesorios/mochilas'),
        ('marmot', 'deporte-equipamiento', 'ni-os/equipo-y-accesorios/sacos-de-dormir'),
        ('marmot', 'deporte-vestuario', 'hombre/accesorios/gorros'),
        ('marmot', 'deporte-vestuario', 'hombre/accesorios/guantes'),
        ('marmot', 'deporte-vestuario', 'hombre/chaquetas/componentes'),
        ('marmot', 'deporte-vestuario', 'hombre/chaquetas/impermeables-cortavientos'),
        ('marmot', 'deporte-vestuario', 'hombre/chaquetas/nieve'),
        ('marmot', 'deporte-vestuario', 'hombre/chaquetas/pluma'),
        ('marmot', 'deporte-vestuario', 'hombre/chaquetas/relleno-sintetico'),
        ('marmot', 'deporte-vestuario', 'hombre/vestuario/camisas'),
        ('marmot', 'deporte-vestuario', 'hombre/vestuario/pantalones'),
        ('marmot', 'deporte-vestuario', 'hombre/vestuario/polar'),
        ('marmot', 'deporte-vestuario', 'hombre/vestuario/poleras'),
        ('marmot', 'deporte-vestuario', 'hombre/vestuario/polerones'),
        ('marmot', 'deporte-vestuario', 'hombre/vestuario/primeras-capas'),
        ('marmot', 'deporte-vestuario', 'hombre/vestuario/shorts'),
        ('marmot', 'deporte-vestuario', 'mujer/accesorios/gorros'),
        ('marmot', 'deporte-vestuario', 'mujer/accesorios/guantes'),
        ('marmot', 'deporte-vestuario', 'mujer/chaquetas/impermeables-cortavientos'),
        ('marmot', 'deporte-vestuario', 'mujer/chaquetas/nieve'),
        ('marmot', 'deporte-vestuario', 'mujer/chaquetas/pluma'),
        ('marmot', 'deporte-vestuario', 'mujer/chaquetas/relleno-sintetico'),
        ('marmot', 'deporte-vestuario', 'mujer/chaquetas/ski'),
        ('marmot', 'deporte-vestuario', 'mujer/vestuario/camisas'),
        ('marmot', 'deporte-vestuario', 'mujer/vestuario/pantalones'),
        ('marmot', 'deporte-vestuario', 'mujer/vestuario/polar'),
        ('marmot', 'deporte-vestuario', 'mujer/vestuario/poleras'),
        ('marmot', 'deporte-vestuario', 'mujer/vestuario/polerones'),
        ('marmot', 'deporte-vestuario', 'ni-os/equipo-y-accesorios/gorros'),
        ('marmot', 'deporte-vestuario', 'ni-os/equipo-y-accesorios/guantes'),
        ('marmot', 'deporte-vestuario', 'ni-os/vestuario-ni-os/chaquetas-impermeables'),
        ('marmot', 'deporte-vestuario', 'ni-os/vestuario-ni-os/chaquetas-sinteticas-y-de-pluma'),
        ('marmot', 'deporte-vestuario', 'ni-os/vestuario-ni-os/pantalones-y-shorts'),
        ('marmot', 'deporte-vestuario', 'ni-os/vestuario-ni-os/polars-y-polerones'),
        ('marmot', 'deporte-vestuario', 'ni-os/vestuario-ni-os/poleras-y-camisas'),
        ('marmot', 'deporte-vestuario', 'ni-os/vestuario-ni-os/primeras-capas'),
        ('marmot', 'deporte-vestuario', 'ni-os/vestuario-ni-os/ropa-de-ski'),
        ('marmot', 'deporte-vestuario', 'ni-os/vestuario/chaquetas'),
        ('marmot', 'deporte-vestuario', 'ni-os/vestuario/nieve'),
        ('marmot', 'deporte-vestuario', 'ni-os/vestuario/pantalones-y-shorts'),
        ('marmot', 'deporte-vestuario', 'ni-os/vestuario/polar-y-polerones'),
        ('marmot', 'deporte-vestuario', 'ni-os/vestuario/poleras'),
        ('marmot', 'deporte-vestuario', 'ni-os/vestuario/primeras-capas')
       ) AS v(store_slug, category_slug, store_key)
  JOIN stores     s ON s.slug = v.store_slug
  JOIN categories c ON c.slug = v.category_slug
ON CONFLICT (store_id, category_id, store_key) DO NOTHING;
