-- =============================================================================
-- MIGRATION 38 — `belleza` pasa a ser Belleza y Farmacia, con tema propio
-- =============================================================================
-- Decisión del dueño del producto del 2026-11-04, la segunda del día sobre esta
-- categoría: la migración 36 la creó con la sola llave `Belleza` de Tottus y dejó
-- afuera las raíces de Jumbo y Santa Isabel porque mezclaban farmacia y bebé.
-- La respuesta fue **ampliar la categoría en vez de recortar las llaves**:
--
--   «podríamos cambiar belleza por belleza y farmacia y meter todo ahí»
--
-- Y creó el tema en el grupo, que es lo que la 36 no podía hacer sola: el
-- `message_thread_id` sale del link de un mensaje real
-- (`t.me/c/3735174401/20595/20596` → chat `-1003735174401`, thread **20595**).
--
-- 1. QUÉ ES "TODO", MEDIDO
--
--   tienda       llave                         declarado  de eso…
--   jumbo        belleza-y-cuidado-personal        3.519   313 de farmacia (9%)
--   santaisabel  cuidado-personal-y-bebe           1.305   15 farmacia + 220 bebé
--   tottus       CATG27076/Belleza (ya estaba)     1.039   ya incluía farmacia
--
-- Los 17 hijos de la raíz de Jumbo son exactamente belleza + farmacia:
-- `suplementos-y-vitaminas` (143), `incontinencia-y-panales-adulto` (78),
-- `accesorios-medicos` (53) y `primeros-auxilios` (39) junto a maquillaje,
-- cuidado capilar/facial/corporal, jabones, desodorantes, depilación, higiene
-- bucal y protección femenina. **No tiene bebé.**
--
-- El rename no inventa nada para Tottus: su `Belleza` **ya** colgaba `Salud`,
-- `Articulos-de-Botiquin`, `Multivitaminicos` e `Incontinencia-y-Panales-Adulto`.
-- O sea el nombre viejo describía mal lo que la categoría ya contenía.
--
-- ⚠️ **Santa Isabel mete 220 SKUs de bebé (17% de su raíz) y no hay forma de
-- sacarlos sin partir la llave en 14.** Su árbol fusiona `bebe` con el cuidado
-- personal; separarlo serían 14 `store_key` de nivel 2 por tienda. Entra, porque
-- "todo" fue la decisión, pero queda anotado: **pañales, fórmulas y toallitas de
-- bebé van a puntuar con el θ de belleza**, y la categoría queda asimétrica entre
-- cadenas — el bebé de Jumbo (bajo `bebe-y-jugueteria`) y el `Mundo-Bebe` de
-- Tottus siguen afuera. Si eso molesta, lo que corresponde es una categoría
-- `bebe` propia, no recortar esta llave.
--
-- 2. LAS DOS LLAVES `farmacia` QUE PARECEN OBVIAS Y NO SE PUEDEN USAR
--
--   * **`jumbo.cl/farmacia` ya no existe: redirige a `/bebe-y-jugueteria`.** Una
--     llave con ese nombre ingeriría **juguetes y artículos de bebé bajo belleza**
--     con HTTP 200 y sin un solo error — el adaptador ve un listado válido porque
--     lo es. Es la trampa del sitemap viejo de la migración 37 §1, ahora con el
--     daño apuntando a esta categoría. El `farmacia` que el sitemap lista es de
--     una taxonomía que la tienda ya reorganizó.
--   * **`santaisabel.cl/farmacia` es un hijo de su propia raíz**
--     (`/cuidado-personal-y-bebe/farmacia`, 15 SKUs): conectarla además de la raíz
--     escribiría dos `price_points` del mismo listing por pasada. Ya entra con el
--     padre.
--
-- 3. LA CUOTA DEL TEMA ES 3, Y NO ES UN NÚMERO LIBRE
-- `ranker.MAX_PER_CATEGORY_PER_DAY = 3` acota cuánto se lleva una categoría por
-- día. `belleza` es **una sola** categoría ruteada a este tema, así que su techo
-- real es 3 pase lo que pase: una `daily_quota` mayor sería inalcanzable y el
-- limitante pasaría a ser el tope, que es justo lo que un tope no tiene que
-- decidir (la cuenta de CLAUDE.md es `categorías × tope >= cuota`). Con 3 = 3 los
-- dos se tocan y ninguno manda sobre el otro. Es la misma cuota que `hogar`, que
-- también tiene una sola categoría.
--
-- El chat pasa de **30 a 33** posts/día repartidos en ocho temas. No se rescala
-- el vector de la migración 35: esos siete números son una decisión del dueño de
-- hoy mismo, y `belleza` no puede producir un candidato antes del 2026-12-04, así
-- que su cuota es teórica por un mes.
--
-- ⚠️ Y empeora en un paso la decisión abierta sobre el ritmo del chat:
-- `MIN_MINUTES_BETWEEN` es un espaciado **por destino**, así que el daemon puede
-- poner **uno por tema por vuelta** — con siete temas eso ya daba hasta 12/hora
-- (medido el 4-nov), y con ocho da hasta 13. No se toca nada acá: el efecto es
-- nulo hasta diciembre, pero el número de temas es una de las variables de esa
-- decisión y conviene no perderla de vista.
--
-- ⚠️ **Hallazgo colateral que NO se toca acá**: el tema `supermercado` tiene
-- `daily_quota = 5` y una sola categoría ruteada, así que su techo real también es
-- 3 — **dos de sus cinco lugares son inalcanzables**. Es exactamente la aritmética
-- que CLAUDE.md manda rehacer al mover una cuota y que quedó sin hacer cuando las
-- cuotas se escalaron ×2,5 el 2026-11-04. Arreglarlo es subir el tope o bajar esa
-- cuota, y las dos son decisiones de producto.
--
-- 4. EL DEDUPE AHORA IMPORTA EN LA DIRECCIÓN CONTRARIA
-- `cencosud_family` emite cada SKU una vez por pasada y la llave que gana es la
-- primera del orden de `db.load_store_targets` (`store_slug, category_slug,
-- store_key`). **`belleza` ordena antes que `supermercado`**, así que un SKU que
-- esté en las dos se lo queda belleza — y la migración 37 avisaba de esto
-- justamente para este momento. El candidato no se duplica (que es lo que
-- protegería el p50) pero sí cambia de tema y de θ.
--
-- Lo que importa es la magnitud, y está medida sobre el catálogo **completo** de
-- las cuatro llaves, no por muestra. El par plausible es `jabones`, que existe en
-- las dos ramas (191 SKUs en la belleza de Jumbo, 76 en la de Santa Isabel), así
-- que se cruzó belleza entera contra `limpieza` entera:
--
--     jumbo        limpieza 1.536 ∩ belleza 3.514 = 0   (0,00%)
--     santaisabel  limpieza   724 ∩ belleza 1.302 = 0   (0,00%)
--
-- **Cero**: el árbol de Cencosud es disjunto entre departamentos y el jabón de
-- tocador no es el jabón de lavar. O sea el dedupe no le quita un solo SKU a
-- supermercado y la advertencia de la migración 37 queda sin materializarse — lo
-- cual no la invalida para la próxima llave que se agregue, porque lo que la hace
-- inocua es la medición, no el diseño.
--
-- El recorrido completo de las dos llaves nuevas, de paso:
--
--     jumbo/belleza-y-cuidado-personal   3.514 de 3.519 declarados   1,9% agotados
--     santaisabel/cuidado-personal-y-bebe 1.302 de 1.305             1,3% agotados
--
-- Precio máximo observado $119.990, o sea muy lejos de `MAX_PLAUSIBLE_CLP`: estas
-- llaves tampoco usan centinelas.
--
-- 5. `max_pages` SUBIÓ A 110 EN EL ADAPTADOR
-- La raíz de Jumbo son 3.519 productos = **88 páginas**, contra el techo de 90 que
-- la migración 37 dimensionó para `despensa` (83). Dos páginas de margen es nada:
-- un 3% de crecimiento de catálogo y la llave se recorta en silencio, que es el
-- fallo que costó diez días en la familia Falabella. 110 × 40 = 4.400.
--
-- 6. QUÉ ESPERAR, Y CUÁNDO
-- Llaves conectadas el **2026-11-04** → primeros candidatos posibles el
-- **2026-12-04** (`belleza.min_history_days = 30`, sin la excepción de la
-- migración 32). Hasta entonces el tema queda vacío y eso es el reloj, no un
-- problema. `formatter.PUM_CATEGORIES` sigue limitado a `supermercado`: estas
-- ofertas **no** muestran precio por unidad de medida, aunque Tottus lo traiga en
-- el 84% de su Belleza.
--
-- Las llaves nuevas solo tienen efecto en la pasada SIGUIENTE.
-- =============================================================================

BEGIN;

-- El nombre describe lo que la categoría ya contenía (ver §1). El θ no se toca:
-- sigue siendo 0.250 de partida, sin calibrar.
UPDATE categories
   SET name = 'Belleza y farmacia'
 WHERE slug = 'belleza';

-- El tema del grupo-foro. `message_thread_id` del link del dueño (§1).
INSERT INTO telegram_topics (tier_id, slug, name, message_thread_id, daily_quota)
SELECT t.id, 'belleza', 'Belleza y Farmacia', 20595, 3
  FROM telegram_tiers t
 WHERE t.slug = 'vip'
ON CONFLICT (tier_id, slug) DO UPDATE
    SET name              = EXCLUDED.name,
        message_thread_id = EXCLUDED.message_thread_id,
        daily_quota       = EXCLUDED.daily_quota;

-- Y se rutea la categoría, que la migración 36 dejó con `topic_id = NULL` porque
-- el tema no existía todavía. Esto apaga el aviso de
-- `poster.warn_categories_without_topic`.
UPDATE telegram_tier_categories AS tc
   SET topic_id = top.id
  FROM categories AS c, telegram_topics AS top
 WHERE tc.category_id = c.id
   AND c.slug = 'belleza'
   AND top.tier_id = tc.tier_id
   AND top.slug = 'belleza';

INSERT INTO store_categories (store_id, category_id, store_key)
SELECT s.id, c.id, v.store_key
  FROM (VALUES
        -- Paths vigentes de la navegación de cada tienda. Ver §2 para las dos
        -- llaves `farmacia` que parecen obvias y están vedadas.
        ('jumbo',       'belleza', 'belleza-y-cuidado-personal'),
        ('santaisabel', 'belleza', 'cuidado-personal-y-bebe')
       ) AS v(store_slug, category_slug, store_key)
  JOIN stores     s ON s.slug = v.store_slug
  JOIN categories c ON c.slug = v.category_slug
ON CONFLICT (store_id, category_id, store_key) DO NOTHING;

COMMIT;

-- Fecha de conexión de las llaves: 2026-11-04 → primeros candidatos el 2026-12-04.
