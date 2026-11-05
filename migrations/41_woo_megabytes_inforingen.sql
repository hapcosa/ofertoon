-- =============================================================================
-- MIGRATION 41 — Megabytes e Infor-Ingen: hardware sobre `woo_family`
-- =============================================================================
-- `INVESTIGACION_hardware.md`. Las dos entran con **cero líneas de adaptador**:
-- responden la Store API pública de WooCommerce
-- (`/wp-json/wc/store/v1/products?per_page=100&page=N&category={id}`), que es el
-- mismo endpoint con el que ya está conectada Urban Comercial.
--
-- 1. POR QUÉ HARDWARE, SI EL PLAN DECÍA QUE ERA EL MARGEN MÁS BAJO
--
-- `PLAN_TIENDAS.md` §2.3 daba la vertical por saturada: SP Digital y PC Factory
-- ya la cubren. `PLAN_EXPANSION.md` §2.2 da vuelta el argumento con el dato de
-- estabilidad de cohorte: **`spdigital` 4% y `pcfactory` 39%**, las dos por
-- debajo de `UMBRAL_ESTABILIDAD = 0.40`. O sea la categoría **no necesita más
-- catálogo, necesita tiendas que acumulen serie**.
--
-- Y eso es exactamente lo que estas dos miden. Dos recorridos completos de su
-- categoría más grande, comparando conjuntos de ids:
--
--   megabytes    `Componentes PC` (153 productos)   Jaccard = 1,0000
--   infor-ingen  `Placas Madres`  (320 productos)   Jaccard = 1,0000
--
-- Sus catálogos son chicos (327 y 1.615 productos) y **eso no es un defecto para
-- este propósito**: un catálogo chico y estable produce baselines, uno grande que
-- rota no.
--
-- 2. LAS LLAVES SON LOS PADRES, Y EL SOLAPAMIENTO ES JERARQUÍA PURA
--
-- Enumeré **todas** las categorías de cada tienda y crucé los ids de producto:
--
--                     categorías  suma enumerados  unión única  factor
--   megabytes             28            623            327       1,91×
--   infor-ingen           58          3.431          1.615       2,12×
--
-- La duplicación no es desorden: las contenciones dan **100% exacto** (16 pares
-- en Megabytes, 60 en Infor-Ingen). `Ventilación` ⊂ `Componentes PC`,
-- `Gabinetes s/Fuente` ⊂ `Gabinetes`, `AM5` ⊂ `Placas Madres`,
-- `Memorias Ram Pc` ⊂ `Memorias`, `Discos Duros SSD` ⊂ `Almacenamiento`… O sea
-- **entra el paraguas y no la hoja**, el mismo criterio que `cat2083/Zapatillas`
-- en Falabella.
--
-- 3. ⚠️ SOLO ENTRA LO QUE MAPEA LIMPIO, Y ESO DEJA AFUERA MÁS DE LO ESPERADO
--
-- Las llaves-padre son 9 en Megabytes y 14 en Infor-Ingen, y **no todas tienen
-- categoría interna donde caer**. La taxonomía del sistema tiene `tecno-audio`,
-- `tecno-celulares`, `tecno-componentes`, `tecno-notebooks` y `tecno-tv`: **no
-- hay categoría para periféricos, monitores ni redes**, que en una tienda de
-- hardware es un pedazo grande.
--
-- Decisión tomada acá, y es la conservadora: **se conectan solo las llaves cuyo
-- contenido mapea sin ambigüedad**, y el resto queda afuera con su razón escrita.
-- Es la regla 6 del CLAUDE.md aplicada a categorías en vez de a identidad: ante
-- la duda, no se agrupa. Lo que entra:
--
--   infor-ingen → tecno-componentes   7 llaves   1.325 de 1.615 SKUs (82%)
--   megabytes   → tecno-componentes   1 llave      153 de  327 SKUs
--   megabytes   → tecno-notebooks     2 llaves       6 SKUs
--
-- Lo que queda afuera y por qué:
--
--   ⚠️ CATCH-ALL — no se pueden conectar nunca sin romper el θ de su categoría,
--      porque su contenido es impredecible y el θ es una propiedad del
--      comportamiento de precio de **un** tipo de producto:
--        infor-ingen  id=78  `Varios`           154 SKUs
--        infor-ingen  id=133 `Sin categoría`      4 SKUs
--        megabytes    id=17  `Otros`             38 SKUs
--        megabytes    id=976 `Servicios técnicos`  8 SKUs  (servicios, no productos)
--
--   🟡 FALTA CATEGORÍA — mapean limpio a algo que el sistema no tiene todavía:
--        infor-ingen  id=75  `Teclados y Mouse`   97   → periféricos
--        infor-ingen  id=74  `Monitores`          91   → monitores (NO es `tecno-tv`)
--        infor-ingen  id=220 `WIFI`                2   → redes
--        infor-ingen  id=186 `Escritorios Gamer`   5   → mobiliario
--        infor-ingen  id=180 `Computadores`       15   → desktops (NO es notebooks)
--        megabytes    id=97  `Accesorios`        133   → periféricos
--        megabytes    id=960 `Seguridad`          23   → cámaras/vigilancia
--        megabytes    id=978 `cámara de seguridad`  8   → idem (hija de 960)
--        megabytes    id=89  `PC armados`          7   → desktops
--
-- ⇒ **Crear `tecno-perifericos` y `tecno-monitores` recuperaría ~330 SKUs** entre
-- las dos tiendas (el 20% de Infor-Ingen y el 48% de Megabytes). Es una decisión
-- de producto y no se toma acá: una categoría nueva necesita su propio θ, y hoy
-- θ **no está calibrado en ninguna** (el gate de F1 sigue pendiente).
--
-- 4. ⚠️ MEGABYTES SOLO RESPONDE AL USER-AGENT IDENTIFICABLE
--
-- Verificado aislando la variable, 4 intentos de cada juego contra su home:
--
--   DEFAULT_USER_AGENT   200, 200, 200, 200
--   BROWSER_USER_AGENT   RemoteProtocolError ×4
--   BROWSER_HEADERS      RemoteProtocolError ×4
--
-- Es el **patrón inverso** al de Prat y al de Easy: acá lo que rompe es parecerse
-- a un navegador, no el token `(+ofertascl-bot)`. El servidor corta la conexión.
-- `woo_family` manda el UA del `HttpClient` por defecto, que es el correcto, así
-- que no hay nada que configurar — pero **no le agreguen un `_headers` de
-- navegador "para que funcione mejor"**: lo rompe.
--
-- 5. EL CANARIO: EXACTO EN UNA, ESTADÍSTICO EN LA OTRA
--
-- `infor-ingen` declara el `count` por categoría y **coincide con lo enumerado en
-- las 58**, así que sostiene el canario exacto.
--
-- `megabytes` **no**: 8 de sus 28 categorías no calzan, y **5 declaran productos
-- y devuelven cero** (`Gabinetes` count=18, `Más accesorios` count=28,
-- `Monitores` count=6, `MegaDays` count=1, `Memorias Ram` count=1). Eso explica
-- también por qué su unión da 327 cuando `X-WP-Total` declara 336: los 9 que
-- faltan solo cuelgan de esas categorías huérfanas. No es un bug del adaptador
-- —la Store API contesta 200 con lista vacía— sino `count` desactualizado del
-- lado de la tienda. Con el canario exacto encendido serían 5 llaves en `partial`
-- permanente, o sea la alarma que suena siempre. Ninguna de las dos llaves
-- huérfanas que importan entra en esta migración, pero el criterio queda escrito.
--
-- 6. FECHAS
--
-- Conexión: **2026-11-05**. `MIN_POINTS`/`MIN_DAYS` son un rechazo y no un
-- default, así que **no publican nada hasta el 2026-12-05**, y se evalúan con
-- `python -m scripts.aceptacion_tienda --store {megabytes,infor-ingen}` **el
-- 2026-12-05**, nunca antes. Y los días que cuentan son los **observados**, no
-- los calendario: un agujero de infraestructura corre esa fecha.
--
-- Costo por pasada: con `per_page=100`, megabytes son ~4 requests e infor-ingen
-- ~17 por el catálogo completo. Las dos juntas son **ruido** contra los ~57 min
-- que ya ocupa la pasada.
--
-- 7. θ: SE HEREDA EN UNA Y SE PUEDE MEDIR EN LA OTRA
--
-- `tecno-componentes` ya existe con θ 0.150 y `min_history_days = 30`, así que
-- estas dos entran con el θ vigente y **no se toca nada**. Dato para cuando se
-- calibre: en la muestra de 100 productos, infor-ingen declara un "antes" en
-- **100** y megabytes en **91**, así que ahí θ se puede fijar midiendo — a
-- diferencia de TecnoPlaza, que declara 0 (y que además quedó fuera de esta
-- migración porque su endpoint de categorías agotó 3 reintentos con ReadTimeout).
-- =============================================================================

INSERT INTO stores (slug, name, base_url, adapter, rate_limit_rps, is_active) VALUES
    ('megabytes', 'MegaBytes', 'https://www.megabytes.cl',
     'scrapers.stores.woo_family:MegabytesAdapter', 0.5, TRUE),
    ('inforingen', 'Infor-Ingen', 'https://store.infor-ingen.com',
     'scrapers.stores.woo_family:InforIngenAdapter', 0.5, TRUE)
ON CONFLICT (slug) DO UPDATE
    SET name     = EXCLUDED.name,
        base_url = EXCLUDED.base_url,
        adapter  = EXCLUDED.adapter;

INSERT INTO store_categories (store_id, category_id, store_key)
SELECT s.id, c.id, v.store_key
  FROM (VALUES
        -- El `store_key` es el **id numérico** de la categoría de WooCommerce,
        -- no su slug: es lo que la Store API acepta en `?category=`.
        --
        -- infor-ingen → tecno-componentes (7 llaves, 1.325 SKUs). Son los
        -- paraguas; sus hijas (`AM5` ⊂ `Placas Madres`, `Memorias Ram Pc` ⊂
        -- `Memorias`, `Discos Duros SSD` ⊂ `Almacenamiento`…) están contenidas
        -- al 100% y NO entran.
        ('inforingen', 'tecno-componentes', '51'),   -- Placas Madres    320
        ('inforingen', 'tecno-componentes', '71'),   -- Gabinetes        291
        ('inforingen', 'tecno-componentes', '73'),   -- Refrigeracion    205
        ('inforingen', 'tecno-componentes', '66'),   -- Memorias         161
        ('inforingen', 'tecno-componentes', '70'),   -- Video            134
        ('inforingen', 'tecno-componentes', '68'),   -- Almacenamiento   116
        ('inforingen', 'tecno-componentes', '15'),   -- Procesadores      98
        -- megabytes → tecno-componentes (1 llave, 153 SKUs)
        ('megabytes',  'tecno-componentes', '273'),  -- Componentes PC   153
        -- megabytes → tecno-notebooks (2 llaves, 6 SKUs). Entran por
        -- completitud: son pocas, pero mapean sin ambigüedad.
        ('megabytes',  'tecno-notebooks',   '277'),  -- Notebooks          5
        ('megabytes',  'tecno-notebooks',   '538')   -- All in One         1
       ) AS v(store_slug, category_slug, store_key)
  JOIN stores s     ON s.slug = v.store_slug
  JOIN categories c ON c.slug = v.category_slug
ON CONFLICT (store_id, category_id, store_key) DO NOTHING;
