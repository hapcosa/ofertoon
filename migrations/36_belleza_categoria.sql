-- =============================================================================
-- MIGRATION 36 — `belleza` como categoría propia (decisión del 2026-10-19)
-- =============================================================================
-- PLAN_SUPERMERCADO §6, decisión 2 del dueño del producto: **Belleza va aparte**,
-- con su propio θ, y no dentro de `supermercado`. Es cero código: la llave ya
-- existe en Tottus y el adaptador que la lee es el mismo.
--
-- 1. POR QUÉ APARTE, SI LA MEDICIÓN DICE QUE SE COMPORTA IGUAL
-- Medido el 2026-11-04 sobre 5 páginas (232 SKUs) de `CATG27076/Belleza`, contra
-- la llave de supermercado más parecida:
--
--   llave                 con dto.  p50 dto.  >=25%  >=30%  >=35%  ticket p50
--   Belleza                  40%      18%      14%    12%     2%     $2.590
--   Aseo-y-Limpieza (super)  32%      20%      13%     9%     7%     $1.450
--
-- O sea por la regla de la migración 27 —un solo comportamiento de precio, una
-- sola categoría— **esto no justificaría separarlas**. Se separa igual, y la
-- razón no es el precio: es que `belleza` es la categoría que habilita Preunic,
-- Salcobrand y Maicao (PLAN_TIENDAS §2.6, sin auditar), cuyo catálogo no tiene
-- nada que ver con el de un supermercado. Meterlas en `supermercado` sería
-- mezclar dos canastas en un p50 de categoría y en un θ.
--
-- 2. θ = 0.250 DE PARTIDA, SIN CALIBRAR
-- Es el de `supermercado`, y por lo único que se puede justificar hoy: la
-- distribución medida arriba es la misma. No sale de un backtest —`belleza` no
-- tiene una sola observación todavía— así que vale lo mismo que los otros 14 θ
-- del sistema: un valor de partida. Sale del backtest cuando tenga 30 días de
-- serie y 30 de futuro para etiquetar.
--
-- `min_history_days` queda en el default de 30 **a propósito**. Las siete
-- categorías de octubre están en 10 por la excepción temporal de la migración 32,
-- que se revierte el 2026-11-06: una categoría que nace hoy no tiene por qué
-- heredar una excepción que vence pasado mañana.
--
-- 3. NACE SIN TEMA, Y ESO ES RUIDOSO A PROPÓSITO
-- La fila en `telegram_tier_categories` se inserta con `topic_id = NULL`. Con
-- eso la categoría **no publica en ningún tema** —el INNER JOIN de
-- `ranker._CANDIDATES_SQL` la deja afuera de toda query de tema— y
-- `poster.warn_categories_without_topic` lo grita en cada vuelta del daemon.
--
-- Es deliberado no inventarle un tema: el `message_thread_id` de un tema sale del
-- link de un mensaje real del grupo (es cómo se obtuvieron los siete de la
-- migración 35), así que crear el tema es una acción del dueño en Telegram y no
-- algo que una migración pueda hacer. Y es deliberado insertar la fila en vez de
-- omitirla: sin fila, la categoría quedaría muda **en silencio**, que es
-- exactamente el síntoma indistinguible que esa guarda existe para evitar.
--
-- Ninguno de los siete temas de hoy sirve: Belleza no es tecnología, hogar,
-- vestuario, deporte, supermercado, ferretería ni viajes.
--
-- 4. QUÉ ESPERAR, Y CUÁNDO
-- La llave ya la sirve `TottusAdapter` (mismo `parse_listing`, ninguna línea
-- nueva) y declara **1.039 SKUs**, que entran en su `max_pages = 45` (2.160).
-- No es una tienda nueva, así que el reloj que corre no es el de la tienda sino
-- el de los listings: 30 días de serie desde la primera pasada que la recolecte.
--
-- Fecha de conexión de la llave: **2026-11-04** → la categoría puede producir
-- candidatos recién a partir del **2026-12-04**, y antes de eso un 0 no significa
-- nada. El `pum` viene en el 84% de sus SKUs, pero `formatter.PUM_CATEGORIES`
-- limita esa línea a `supermercado`: hoy `belleza` NO la muestra, y si se la
-- quiere hay que agregarla ahí.
--
-- Las llaves nuevas solo tienen efecto en la pasada SIGUIENTE: los targets se
-- cargan una vez al arrancar la pasada.
-- =============================================================================

BEGIN;

INSERT INTO categories (slug, name, discount_threshold) VALUES
    ('belleza', 'Belleza y cuidado personal', 0.250)
ON CONFLICT (slug) DO UPDATE
    SET name = EXCLUDED.name;
    -- El θ NO se sobreescribe al re-correr: si alguien lo calibró, esta
    -- migración no puede pisarlo. Mismo criterio que la 27.

-- Al canal VIP y SIN tema: ver §3. El `COALESCE` del UPDATE es para que
-- re-correr esta migración no borre un `topic_id` que ya se haya cableado.
INSERT INTO telegram_tier_categories (tier_id, category_id, topic_id)
SELECT t.id, c.id, NULL
  FROM telegram_tiers t
  JOIN categories     c ON c.slug = 'belleza'
 WHERE t.slug = 'vip'
ON CONFLICT (tier_id, category_id) DO UPDATE
    SET topic_id = COALESCE(EXCLUDED.topic_id, telegram_tier_categories.topic_id);

INSERT INTO store_categories (store_id, category_id, store_key)
SELECT s.id, c.id, v.store_key
  FROM (VALUES
        -- El par id/nombre es el EXACTO que publica la navegación de Tottus: si
        -- el nombre no corresponde al id, la plataforma sirve una landing de CMS
        -- sin `results` y el adaptador lo rechaza con `NotAListingPage`.
        ('tottus', 'belleza', 'CATG27076/Belleza')
       ) AS v(store_slug, category_slug, store_key)
  JOIN stores     s ON s.slug = v.store_slug
  JOIN categories c ON c.slug = v.category_slug
ON CONFLICT (store_id, category_id, store_key) DO NOTHING;

COMMIT;

-- Fecha de conexión de la llave: 2026-11-04 → primeros candidatos posibles el
-- 2026-12-04 (30 días de serie por listing, `min_history_days = 30`).
