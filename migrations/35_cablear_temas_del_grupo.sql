-- =============================================================================
-- MIGRATION 35 — Cablear el grupo-foro: chat nuevo y los siete temas
-- =============================================================================
-- Lo que la migración 26 dejó pendiente desde el 1-oct, y que no se podía hacer
-- desde acá porque los `message_thread_id` salen del grupo ya creado.
--
-- 1. EL DESTINO VIEJO ERA UN CANAL, NO UN GRUPO-FORO
-- Verificado el 2026-11-04 contra la Bot API: el `telegram_channel_id` anterior
-- (-1003914468578, "Ofertoon Vip") respondía `type=channel`, `is_forum=None`. Los
-- canales **no soportan temas**, así que el bloqueo nunca fue "leer los
-- `message_thread_id`": era que no había grupo donde leerlos. Por eso los siete
-- estuvieron en NULL cinco semanas y el poster publicó al chat plano todo ese
-- tiempo — que es el fallback correcto y la razón por la que no se notó.
--
-- El grupo nuevo, verificado el mismo día antes de escribir esto:
--
--     getChat(-1003735174401)  → type=supergroup  is_forum=TRUE  "Ofertooncl"
--     getChatMember(@Ofertoon_bot) → status=administrator  can_manage_topics=TRUE
--     getChatMemberCount           → 6
--
-- 2. COSTO DE MOVER EL DESTINO: CERO SUSCRIPTORES
-- Medido antes de aplicar: `telegram_memberships` tiene **una** fila, `expired` y
-- ya `kicked`. O sea mover el destino no mueve a nadie. Es deliberado hacerlo
-- ahora y no después: el gate está ENCENDIDO (`GATE_ENABLED=true` y
-- `telegram_tiers.gate_enabled`), así que a partir de esta migración el
-- `gate_daemon` invita y expulsa sobre el chat nuevo. Con el canal poblado, esto
-- habría sido una migración de membresías y no un UPDATE.
--
-- ⚠️ El canal viejo queda huérfano: nadie publica ahí y el gate deja de
-- administrarlo. No se borra nada — si hay que volver, es el UPDATE inverso.
--
-- 3. LAS CUOTAS SE ESCALAN ×2,5, Y ES APLICAR UNA DECISIÓN YA TOMADA
-- Las siete `daily_quota` de la migración 26 suman 12 y fueron dimensionadas
-- cuando la cuota global era **6**. El 2026-10-21 el dueño del producto la subió a
-- **30**, pero las cuotas por tema no se recalcularon porque ningún tema estaba
-- activo: quedaron como un remanente de la decisión anterior. Cablear sin tocarlas
-- bajaría el canal de los 21-25 posts/día que publica hoy a 12 — o sea cambiaría
-- el destino **y** el volumen en el mismo movimiento, revirtiendo en silencio una
-- decisión de hace dos semanas.
--
-- Se escala el vector original por 2,5 en vez de inventar un reparto nuevo: así se
-- preservan las proporciones que la migración 26 eligió a mano Y el volumen que el
-- dueño fijó el 21-oct. Decisión confirmada por el dueño el 2026-11-04.
--
--     tema          antes  ahora
--     tecnologia        3      8
--     vestuario         2      5
--     deporte           2      5
--     supermercado      2      5
--     hogar             1      3
--     ferreteria        1      3
--     viajes            1      1
--     ─────────────────────────────
--                      12     30
--
-- NO se reparte proporcional al volumen medido (Tecnología ~8,8 señales/día contra
-- ~1,5 de Ferretería), que fue la otra opción sobre la mesa: eso es exactamente el
-- efecto que la cuota-por-tema existe para evitar — que el tema con volumen se
-- coma los lugares de los demás.
--
-- El espaciado de 30 min es POR DESTINO (`load_posted_today` filtra por
-- `topic_id`), así que siete temas × 30 posts es el techo físico y una suma de 30
-- no roza ningún límite. La cuota es un techo, no un piso: Ferretería con 3 no la
-- va a llenar y eso está bien.
--
-- 4. VIAJES SE CABLEA Y VA A QUEDAR MUDO
-- Tiene su `message_thread_id` pero **cero categorías** en
-- `telegram_tier_categories`: no hay tienda de viajes conectada. Un tema sin
-- categorías simplemente no recibe candidatos — no es un error ni dispara el aviso
-- de `warn_categories_without_topic`, que vigila lo contrario (categorías sin
-- tema). Se cablea igual porque el thread ya existe y cuesta cero.
--
-- 5. ESTA MIGRACIÓN NO NECESITA REBUILD
-- El código de temas está desplegado desde la migración 26 y solo lee datos:
-- `load_active_topics` filtra `message_thread_id IS NOT NULL` en cada vuelta del
-- daemon (cada 300 s). O sea el efecto es inmediato al commitear, sin tocar
-- contenedores. ⚠️ Pero `db-migrate` SÍ necesita rebuild para ver este archivo:
-- su imagen copia las fuentes y un `run` sobre la imagen vieja contesta
-- "0 migración(es) aplicada(s)", que es idéntico al mensaje de éxito.
-- =============================================================================

BEGIN;

-- El chat nuevo. Los `message_thread_id` de abajo solo son válidos para ESTE
-- chat, así que las dos cosas van en la misma transacción a propósito: un tema
-- apuntando a un thread de otro chat haría fallar cada envío con
-- "message thread not found".
UPDATE telegram_tiers
   SET telegram_channel_id = -1003735174401
 WHERE slug = 'vip';

-- Los siete, leídos del link de un mensaje de cada tema
-- (https://t.me/c/3735174401/<message_thread_id>/<message_id>).
UPDATE telegram_topics AS t
   SET message_thread_id = v.thread_id,
       daily_quota       = v.quota
  FROM (VALUES
        ('tecnologia',   20541, 8),
        ('hogar',        20557, 3),
        ('vestuario',    20543, 5),
        ('deporte',      20560, 5),
        ('supermercado', 20549, 5),
        ('ferreteria',   20545, 3),
        -- Sin categorías ruteadas: queda mudo hasta que haya tienda de viajes.
        ('viajes',       20547, 1)
       ) AS v(slug, thread_id, quota)
 WHERE t.slug = v.slug
   AND t.tier_id = (SELECT id FROM telegram_tiers WHERE slug = 'vip');

COMMIT;

-- Verificación (debe devolver 7 filas, ninguna con message_thread_id NULL, y
-- SUM(daily_quota) = 30):
--   SELECT slug, message_thread_id, daily_quota FROM telegram_topics
--    WHERE is_active ORDER BY id;
