-- =============================================================================
-- MIGRATION 25 — Nike: la familia VTEX, y zapatilla urbana de marca con GTIN
-- =============================================================================
-- Sale de la Fase 6 (PLAN_TIENDAS): Nike estaba en la lista de "bloqueadas por
-- 403" y resultó que el 403 era **solo por headers**. Con el juego completo de
-- `http.BROWSER_HEADERS` su API pública de catálogo VTEX está **abierta**.
--
-- 1. POR QUÉ ES LA MEJOR RELACIÓN COSTO/VALOR DEL PLAN
--
--   * **2.554 productos en ~57 requests por pasada.** Nada: la pasada entera hoy
--     son ~2.900 listings.
--   * **100% de cobertura de EAN**, medido sobre las 6 subcategorías. Eso es lo
--     más valioso: CLAUDE.md registra que de 3.357 `products` solo **11** tienen
--     2+ tiendas porque las tiendas con GTIN casi no se solapan. Nike sola mueve
--     esa aguja.
--   * **Es zapatilla urbana de marca**, que es lo que la Fase 3b quería sacar de
--     Sparta (~200 llaves de facetas) y Decathlon (bloqueada de verdad).
--
-- 2. SE ESCRIBIÓ LA FAMILIA, NO UN ADAPTADOR SUELTO
-- `scrapers/stores/vtex_family.py`. VTEX es la plataforma de buena parte del
-- retail chileno y el plan ya la quería para Colloky y la Fase 3 entera, así que
-- el trabajo queda hecho para esas también.
--
-- Dos cosas que hubo que arreglar en la infraestructura compartida y que
-- cualquier tienda VTEX futura necesita:
--
--   * **VTEX contesta `206 Partial Content`, siempre** (el rango de `_from`/`_to`
--     es parcial respecto del total). `http._request` solo aceptaba 200, así que
--     el primer fetch moría con `FetchError: HTTP 206`. Ahora hay
--     `http.SUCCESS_STATUS = {200, 206}`. Se listan los códigos uno por uno y no
--     "todo 2xx" a propósito: un 204 sin cuerpo devolvería `""` y el parser lo
--     leería como catálogo vacío — el fallo silencioso que `NotAListingPage`
--     existe para evitar.
--   * **El total de la categoría viene en un HEADER**, `Resources: 0-49/2546`, no
--     en el cuerpo. De ahí sale `completeness()`, o sea el canario **exacto** del
--     runner. Para leerlo se agregó `HttpClient.get_with_headers`.
--
-- 3. UN PRODUCTO POR PRODUCTO, NO UNO POR TALLE
-- VTEX devuelve un `product` con N `items`, y los items son los talles: un zapato
-- son ~10 items al mismo precio. Emitir uno por talle multiplicaría los listings
-- por 10 con series idénticas. Se emite uno por producto, y el talle que da el
-- precio es **el disponible más barato** — tomar el de un talle agotado publicaría
-- un precio que nadie puede pagar. `in_stock` mira TODOS los talles: el producto
-- es comprable si alguno lo está.
--
-- 4. LAS LLAVES SON LAS SUBCATEGORÍAS, Y ESO NO ES OPCIONAL
-- VTEX corta la paginación profunda en ~2.500 (`_from` más alto da error). La raíz
-- `nike` (id 2) declara 2.389 y `snkrs` 165: la raíz sola ya roza el tope y no se
-- podría enumerar completa. Totales medidos el 2026-10-01:
--
--   nike/calzado      2/3    1.188      snkrs/calzado    6/27    119
--   nike/ropa         2/4      929      snkrs/ropa       6/22     45
--   nike/accesorios   2/5      272      snkrs/accesorios 6/38      1
--
-- 5. DISJUNCIÓN VERIFICADA — y era la pregunta correcta
-- `snkrs` podría haber sido un paraguas de `nike`, que es la trampa que ya pasó
-- con `cat2083/Zapatillas` en Falabella (migración 24). Medido sobre los itemIds:
--
--   nike/calzado (5.916 items) vs snkrs/calzado (1.858)  → intersección 0 ✓
--   nike/ropa    (2.445 items) vs snkrs/ropa    (232)    → intersección 0 ✓
--
-- Contra las llaves de Falabella en `ropa-calzado` no hay riesgo: el unique es
-- `(store_id, store_sku)` y el store_id es distinto.
--
-- 6. MAPEO DE CATEGORÍAS, decidido mirando el contenido
--
--   * **calzado → `ropa-calzado`** (θ 0.350, creada en la migración 24). Es
--     exactamente lo mismo que trae Falabella ahí: zapatilla urbana.
--   * **ropa → `deporte-vestuario`** (θ 0.350). Muestreado: poleras, pantalones,
--     polerones y chaquetas, o sea sportswear. Reusar evita un θ nuevo sin
--     calibrar, y el θ de vestuario es el mismo 0.350 que correspondería. El
--     nombre de la categoría dice "Vestuario outdoor" y queda un poco corto, pero
--     el comportamiento de precio —descuenta profundo y seguido— es el mismo, que
--     es lo que el θ modela.
--
-- ⚠️ **`nike/accesorios` (272) queda AFUERA a propósito, y es una decisión
-- pendiente, no un olvido.** Muestreado, son **gorros y calcetines**. No son
-- `deporte-equipamiento` (θ 0.250: carpas, mochilas, equipo de escalada) y
-- meterlos en `deporte-vestuario` haría que el nombre mienta. Son 272 SKUs de
-- ticket bajo ($14.990 un pack de calcetines), justo lo que al canal le falta, así
-- que vale resolverlo — pero con una categoría propia (`ropa-accesorios`) o una
-- decisión explícita, no colándolos acá.
--
-- ⚠️ **SNKRS tiene poco stock y es esperable**: son lanzamientos limitados. Medido,
-- 11 de 119 en calzado y 10 de 45 en ropa están disponibles. Se conectan igual
-- porque cuestan 4 requests, pero no esperes volumen publicable de ahí.
--
-- 7. QUÉ ESPERAR, Y CUÁNDO
-- ~2.282 listings nuevos. **No publica nada durante 30 días**
-- (`MIN_POINTS`/`MIN_DAYS` son un rechazo, no un default). Fecha de conexión
-- 2026-10-01 → se evalúa el **2026-10-31** con
-- `python -m scripts.aceptacion_tienda --store nike`.
--
-- Las llaves nuevas solo tienen efecto en la pasada SIGUIENTE: los targets se
-- cargan una vez al arrancar la pasada.
-- =============================================================================

BEGIN;

INSERT INTO stores (slug, name, base_url, adapter, rate_limit_rps, is_active) VALUES
    -- Su robots.txt no declara `Crawl-delay`; el default conservador alcanza de
    -- sobra para ~57 requests por pasada.
    ('nike', 'Nike', 'https://www.nike.cl',
     'scrapers.stores.vtex_family:NikeAdapter', 0.5, TRUE)
ON CONFLICT (slug) DO UPDATE
    SET name           = EXCLUDED.name,
        base_url       = EXCLUDED.base_url,
        adapter        = EXCLUDED.adapter,
        rate_limit_rps = EXCLUDED.rate_limit_rps;

INSERT INTO store_categories (store_id, category_id, store_key)
SELECT s.id, c.id, v.store_key
  FROM (VALUES
        -- Zapatilla urbana de marca. 1.188 + 119.
        ('nike', 'ropa-calzado',      '2/3'),
        ('nike', 'ropa-calzado',      '6/27'),
        -- Sportswear: poleras, pantalones, polerones, chaquetas. 929 + 45.
        ('nike', 'deporte-vestuario', '2/4'),
        ('nike', 'deporte-vestuario', '6/22')
        -- `2/5` y `6/38` (accesorios: gorros y calcetines) NO entran: ver §6.
       ) AS v(store_slug, category_slug, store_key)
  JOIN stores     s ON s.slug = v.store_slug
  JOIN categories c ON c.slug = v.category_slug
ON CONFLICT (store_id, category_id, store_key) DO NOTHING;

COMMIT;

-- Fecha de conexión: 2026-10-01 → se evalúa el 2026-10-31.
