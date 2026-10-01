-- =============================================================================
-- MIGRATION 26 — Temas del grupo: un destino por rubro dentro del mismo chat
-- =============================================================================
-- Hasta acá el destino era un canal por tier: `telegram_tiers.telegram_channel_id`
-- y todas las categorías del tier mezcladas en un solo flujo. El grupo nuevo de
-- Ofertoon es un **foro** (supergrupo con temas), así que el destino pasa a ser
-- el par (chat, tema): el chat sigue siendo del tier, y el tema lo elige la
-- categoría del candidato.
--
-- 1. POR QUÉ UNA TABLA Y NO UNA COLUMNA EN `telegram_tier_categories`
-- Un `message_thread_id` en esa tabla alcanzaría para rutear, pero un tema tiene
-- identidad propia: nombre, cuota y —el caso que decide— **existencia sin
-- categorías**. `viajes` es un tema real del grupo y hoy no tiene ni una
-- categoría ni una tienda que lo alimente; `supermercado` está igual hasta que
-- entre Tottus. Con la columna, un tema sin categorías no se puede representar:
-- no hay fila donde ponerlo.
--
-- 2. `message_thread_id` NULLABLE, Y ESO ES LO QUE HACE SEGURA ESTA MIGRACIÓN
-- El publisher está ENCENDIDO (`PUBLISHER_ENABLED=true`, 6 ofertas/día desde el
-- 2026-09-21). Los `message_thread_id` todavía no se conocen: salen del grupo ya
-- creado, y para leerlos hace falta el link de un mensaje de cada tema (el bot
-- corre con long polling, así que `getUpdates` desde afuera le robaría los
-- updates de onboarding).
--
-- Un tema sin `message_thread_id` NO es un destino, y cuando el tier no tiene
-- ningún tema cableado el poster **sigue publicando como hoy**, al chat y sin
-- thread. O sea: aplicar esta migración no cambia nada del comportamiento vivo.
-- El corte se hace al cablear los ids, no acá.
--
-- 3. LA CUOTA PASA A SER POR TEMA, Y EL TOTAL SUBE
-- Decidido el 2026-10-01. `ranker.MAX_PER_DAY = 6` era el techo del canal
-- entero; con siete temas, un techo global hace que el tema con volumen se coma
-- los lugares de los demás — y el volumen está medidísimo: a los θ de partida
-- Tecnología produce ~8,8 señales/día y Ferretería ~1,5. Con cuota global de 6,
-- Ferretería no gana un lugar casi nunca.
--
-- Las cuotas de abajo suman 11/día contra las 6 de hoy. Es a propósito y es la
-- consecuencia de la decisión: son 11 repartidas en siete conversaciones
-- separadas, ninguna con más de 3. El criterio del docstring del ranker ("seis
-- mensajes se leen, treinta son un feed") se aplica ahora POR TEMA, que es la
-- unidad que el suscriptor realmente lee —y puede mutear— por separado.
--
-- 4. EL REPARTO: SIETE TEMAS, Y DOS NACEN VACÍOS
-- Medido el 2026-10-01 con el backtest sobre 27.235 listings:
--
--   tema          categorías                                    señales/día hoy
--   Tecnología    tecno-{celulares,componentes,notebooks,tv,audio}   ~8,8
--   Ferretería    ferre-{herramientas,jardin}                        ~1,5
--   Hogar         hogar-electro                                       1,7
--   Vestuario     ropa-calzado                                        0  (al 31-oct)
--   Deporte       deporte-{calzado,vestuario,equipamiento}            0  (al 31-oct)
--   S.Mercado     —                                                  0  (falta Tottus)
--   Viajes        —                                                  0  (sin decidir)
--
-- `hogar-electro` y las tres de deporte son temas propios por decisión explícita
-- del 2026-10-01: línea blanca tiene un ticket de otro orden ($300.000+) que el
-- resto de "tecno", y `deporte-equipamiento` son carpas y mochilas, que en un
-- tema llamado Vestuario mentirían.
--
-- Los dos vacíos no molestan: un tema sin categorías no tiene candidatos y el
-- ranker devuelve [] — no hay mensaje, ni error, ni fila.
--
-- 5. `deal_posts.topic_id` ES AUDITORÍA, NO LLAVE
-- El UNIQUE sigue siendo (candidate_id, tier_id) y no se toca: un candidato
-- tiene UNA categoría, que tiene UN tema, así que no puede ir a dos temas del
-- mismo tier. Agregar el tema a la llave no prevendría ningún duplicado y sí
-- abriría la puerta a publicar lo mismo en dos temas si alguien dupliquara el
-- mapeo. La columna sirve para responder "qué se publicó en Ferretería" sin
-- reconstruirlo por join a través de la categoría del listing.
-- =============================================================================

BEGIN;

CREATE TABLE IF NOT EXISTS telegram_topics (
    id                SERIAL PRIMARY KEY,
    tier_id           INTEGER     NOT NULL REFERENCES telegram_tiers(id) ON DELETE CASCADE,
    slug              VARCHAR(32) NOT NULL,
    name              VARCHAR(64) NOT NULL,
    -- NULL = el tema existe pero todavía no tiene destino. Ver §2.
    message_thread_id BIGINT,
    daily_quota       SMALLINT    NOT NULL DEFAULT 2,
    is_active         BOOLEAN     NOT NULL DEFAULT TRUE,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT telegram_topics_tier_slug_unique UNIQUE (tier_id, slug),
    -- Dos temas del mismo chat con el mismo thread es un error de cableado que
    -- publicaría en el tema equivocado sin fallar. Se atrapa acá.
    CONSTRAINT telegram_topics_tier_thread_unique UNIQUE (tier_id, message_thread_id),
    CONSTRAINT telegram_topics_quota_sane CHECK (daily_quota BETWEEN 0 AND 20)
);

-- El ruteo categoría → tema. NULL = la categoría está en el tier pero no tiene
-- tema asignado: no se publica en ningún tema. El poster lo avisa por log en vez
-- de callarse, porque una categoría muda es indistinguible de una sin ofertas.
ALTER TABLE telegram_tier_categories
    ADD COLUMN IF NOT EXISTS topic_id INTEGER
        REFERENCES telegram_topics(id) ON DELETE SET NULL;

ALTER TABLE deal_posts
    ADD COLUMN IF NOT EXISTS topic_id INTEGER
        REFERENCES telegram_topics(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS idx_telegram_topics_tier
    ON telegram_topics (tier_id) WHERE is_active;

-- -----------------------------------------------------------------------------
-- Los siete temas del grupo, sin `message_thread_id`: se cablean después.
-- -----------------------------------------------------------------------------
INSERT INTO telegram_topics (tier_id, slug, name, daily_quota)
SELECT t.id, v.slug, v.name, v.quota
  FROM (VALUES
        -- ~8,8 señales/día medidas: es el único tema que hoy llena su cuota.
        ('tecnologia',   'Tecnología', 3::smallint),
        -- 1,7/día. Cuota 1 para que no se lea como un canal de refrigeradores.
        ('hogar',        'Hogar',      1::smallint),
        -- 0 hasta el 31-oct (ropa-calzado se conectó el 2026-10-01).
        ('vestuario',    'Vestuario',  2::smallint),
        -- 0 hasta el 31-oct (Andesgear y Nike).
        ('deporte',      'Deporte',    2::smallint),
        -- 0 hasta que Tottus cumpla sus 30 días.
        ('supermercado', 'S.Mercado',  2::smallint),
        -- 1,5/día entre sus dos categorías.
        ('ferreteria',   'Ferretería', 1::smallint),
        -- Sin categorías ni tiendas: existe para que el grupo lo tenga, y no
        -- postea nada hasta que se decida de dónde sale una oferta de viaje.
        ('viajes',       'Viajes',     1::smallint)
       ) AS v(slug, name, quota)
  JOIN telegram_tiers t ON t.slug = 'vip'
ON CONFLICT (tier_id, slug) DO UPDATE
    SET name = EXCLUDED.name;
    -- `daily_quota` y `message_thread_id` NO se sobreescriben: si alguien ajustó
    -- la cuota o cableó el thread, re-correr la migración no puede pisarlo.

-- -----------------------------------------------------------------------------
-- El mapeo categoría → tema.
-- -----------------------------------------------------------------------------
UPDATE telegram_tier_categories AS tc
   SET topic_id = top.id
  FROM telegram_tiers t, categories c, telegram_topics top,
       (VALUES
        ('tecno-celulares',      'tecnologia'),
        ('tecno-componentes',    'tecnologia'),
        ('tecno-notebooks',      'tecnologia'),
        ('tecno-tv',             'tecnologia'),
        ('tecno-audio',          'tecnologia'),
        ('hogar-electro',        'hogar'),
        ('ropa-calzado',         'vestuario'),
        ('deporte-calzado',      'deporte'),
        ('deporte-vestuario',    'deporte'),
        ('deporte-equipamiento', 'deporte'),
        ('ferre-herramientas',   'ferreteria'),
        ('ferre-jardin',         'ferreteria')
       ) AS v(category_slug, topic_slug)
 WHERE t.slug = 'vip'
   AND tc.tier_id = t.id
   AND c.slug = v.category_slug
   AND tc.category_id = c.id
   AND top.tier_id = t.id
   AND top.slug = v.topic_slug
   AND tc.topic_id IS DISTINCT FROM top.id;

COMMIT;

-- Qué falta para que esto tenga efecto, en orden:
--   1. @Ofertoon_bot administrador del grupo, con permiso de publicar y de
--      administrar temas.
--   2. Cablear `telegram_tiers.telegram_channel_id` al chat del grupo y
--      `telegram_topics.message_thread_id` de cada tema. Hasta entonces el
--      publisher sigue posteando al canal viejo, sin thread.
--   3. Las categorías sin tema quedan mudas: hoy no hay ninguna, pero una
--      categoría nueva nace sin `topic_id` y hay que asignárselo.
