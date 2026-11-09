-- =============================================================================
-- MIGRATION 55 — Cuota 20 en los ocho temas, y los topes finos dejan de decidir
-- =============================================================================
-- Decisión del dueño del 2026-11-07, textual: **"no importa el spam, lo que
-- importa son las ofertas"**. Se eligió entre tres alternativas planteadas con
-- la aritmética delante, y la elegida es la que deja la cuota del tema como
-- ÚNICO limitante.
--
-- -----------------------------------------------------------------------------
-- 1. QUÉ ESTABA LIMITANDO, MEDIDO
-- -----------------------------------------------------------------------------
-- El canal publicaba 22-25 por día contra una cuota total de 33, y **lo que
-- sobraba no lo limitaba el detector**. Medido el 2026-11-07 por tema:
--
--     Tecnología            8 de 8   LLENO
--     Hogar                 3 de 3   LLENO
--     Vestuario             0 de 5   5 sin usar
--     Deporte               5 de 5   LLENO
--     S.Mercado             3 de 5   2 sin usar
--     Ferretería            3 de 3   LLENO
--     Viajes                0 de 1   1 sin usar
--     Belleza y Farmacia    0 de 3   3 sin usar
--                          --------
--                          22 de 33
--
-- Cinco temas llenos a su cuota, y los 11 lugares libres repartidos en temas sin
-- candidatos maduros. Dentro de Tecnología, `tecno-audio` y `tecno-tv` estaban
-- los dos en 3 de 3 por `MAX_PER_CATEGORY_PER_DAY`.
--
-- -----------------------------------------------------------------------------
-- 2. LA ARITMÉTICA, QUE ES LA MITAD DEL CAMBIO
-- -----------------------------------------------------------------------------
-- CLAUDE.md §Pasos 2 obliga a recalcular los topes finos al mover una cuota:
-- `categorías × MAX_PER_CATEGORY_PER_DAY ≥ cuota` y
-- `tiendas_maduras × MAX_PER_STORE_PER_DAY ≥ cuota`. Con la cuota en 20 y los
-- topes viejos, el techo real habría quedado MUY por debajo:
--
--     por categoría:  Hogar, S.Mercado, Viajes y Belleza tienen UNA categoría
--                     ruteada, así que 1 × 3 = 3 contra una cuota de 20
--     por tienda:     8 tiendas producen aceptados hoy, así que 8 × 5 = 40
--                     contra una cuota total de 160
--
-- O sea subir solo la cuota no habría cambiado casi nada y el síntoma habría
-- quedado escondido. Por eso **los dos topes van a 20 en el mismo cambio**
-- (`curation/ranker.py`, que es código y no esta migración). Con los tres
-- números iguales, la cuota del tema decide sola: **8 × 20 = 160 por día**.
--
-- El otro techo, que no hace falta tocar: `MIN_MINUTES_BETWEEN = 30` es POR
-- DESTINO, y la ventana de 08:00-23:00 de Santiago son 15 h ⇒ 30 posts posibles
-- por tema. Una cuota de 20 entra con margen. El chat puede recibir hasta 160
-- mensajes por día y eso es aceptado explícitamente.
--
-- -----------------------------------------------------------------------------
-- 3. LO QUE SE ABANDONA A PROPÓSITO
-- -----------------------------------------------------------------------------
-- ⚠️ Con los topes iguales a la cuota, **una sola tienda o una sola categoría
-- puede llenar un tema entero**. Antes estaba prohibido por diseño: el docstring
-- de `ranker` decía "seis ofertas de Falabella no son un canal curado, son un
-- feed de Falabella". Falabella es el 46% del canal y tiene 64 mil listings, así
-- que un tema monotienda es el resultado probable y no el extremo.
--
-- Se acepta porque el canal **no tiene suscriptores** y lo que se busca hoy es
-- volumen de señal para observar, no un canal curado para vender. Es el primer
-- número a revisar cuando haya gente pagando, y revertirlo es bajar cualquiera
-- de los dos topes por debajo de la cuota — hay un test que falla si alguien lo
-- hace sin querer (`test_una_sola_tienda_puede_llenar_un_tema`).
--
-- -----------------------------------------------------------------------------
-- 4. ESTA MIGRACIÓN NECESITA REBUILD, Y LA ANTERIOR NO NECESITABA
-- -----------------------------------------------------------------------------
-- La 35 solo cambiaba datos y `load_active_topics` los relee cada 300 s. Esta
-- vez **la mitad del cambio es código** (`MAX_PER_STORE_PER_DAY` y
-- `MAX_PER_CATEGORY_PER_DAY` en `curation/ranker.py`), así que hay que
-- reconstruir y recrear el `publisher`. Y al recrear el scraper, acordarse del
-- `--once`: ver CLAUDE.md §Paso 4.
--
-- Aplicar los datos sin el código deja la cuota en 20 con los topes en 3 y 5, o
-- sea el estado inútil del §2. Desplegar el código sin los datos deja los topes
-- en 20 con la cuota en 8, que no cambia nada. **Van juntos.**
-- =============================================================================

BEGIN;

-- 20 es el máximo que admite el CHECK de la migración 26
-- (`daily_quota BETWEEN 0 AND 20`), así que esto es el techo del esquema.
UPDATE telegram_topics SET daily_quota = 20 WHERE daily_quota <> 20;

-- Verificación dentro de la transacción: `migrate.py` dice "aplicada" con que el
-- SQL no lance, así que el efecto se comprueba acá o no se comprueba.
DO $$
DECLARE
    fuera INTEGER;
    suma  INTEGER;
BEGIN
    SELECT count(*) INTO fuera FROM telegram_topics WHERE daily_quota <> 20;
    IF fuera > 0 THEN
        RAISE EXCEPTION 'migración 55: % temas no quedaron en 20', fuera;
    END IF;

    SELECT coalesce(sum(daily_quota), 0) INTO suma
      FROM telegram_topics WHERE is_active AND message_thread_id IS NOT NULL;
    IF suma <> 160 THEN
        RAISE EXCEPTION
            'migración 55: la cuota de los temas cableados suma % y se esperaban 160 '
            '(¿cambió la cantidad de temas?)', suma;
    END IF;
END $$;

COMMIT;
