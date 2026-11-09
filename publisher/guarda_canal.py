"""Guarda de "el canal no publicó": mira el PRIMER post del día, no el total.

Existe porque el 2026-11-06 el canal quedó mudo 6 h 18 min —primer post 17:18
UTC contra las 11:00 de todos los días— con los siete servicios `Up` y sin un
solo error en pantalla. Ninguna guarda del repo lo vio, y no por descuido: las
tres que había (`db.dias_sin_observaciones`, `runner.canary_verdict`,
`runner.pasadas_flacas`) miran la INGESTA, y ese día la ingesta estaba sana —
lo que se había reagendado era el ciclo de 12 h del scraper, con el pipeline a
bordo. Diagnóstico completo en `research/2026-11-06/INCIDENTE_canal_mudo.md`.

**Por qué el primer post y no el total.** Un chequeo de "cuántos posteé hoy"
solo puede hablar al final del día, cuando ya no hay nada que hacer, y encima
ese día **no lo habría visto nunca**: el 6-nov terminó con 23 posts, un total
perfectamente sano. La falla fue el arranque, no el volumen, y son dos fallas
distintas: "no arrancó" se arregla hoy (`scrapers.runner --once` y la ventana
alcanza), "publicó poco" es calibración de θ y cuotas, que no es una alerta.

**Por qué no dispara fuera de la ventana.** Antes de que abra
(`ranker.WINDOW_START_HOUR`, 08:00 de Santiago) no hay nada que reportar: cero
posts a las 4 de la mañana es el estado correcto del sistema. Después de que
cierra tampoco —a esa hora ya no queda jornada que salvar, y del día mudo ya
avisó a la mañana—. La ventana y el día calendario se **importan** de
`curation/ranker.py` y no se copian acá: son los números que mandan de verdad
—el ranker los usa para la cuota— y una copia queda vieja en silencio el día
que cambien.

El `deadline` es un parámetro y no una constante enterrada porque es un umbral,
y los umbrales los decide el dueño. El default de 13:00 UTC es el que el
backtest sostiene; el costo de cada valor está medido en
`research/2026-11-09/GUARDA_canal_mudo.md`.
"""
from __future__ import annotations

from datetime import datetime, time, timedelta, timezone

import asyncpg

from curation import ranker

#: Hora UTC a partir de la cual "todavía no publicó nada" es una falla y no una
#: mañana normal. Medido sobre los 49 días de historia del canal: el primer post
#: sale 12:00-12:04 UTC con la ventana vieja (abría 09:00 de Santiago, hasta el
#: 2026-10-21) y 11:00-11:04 con la actual, así que 13:00 deja ~1 h de holgura
#: sobre el más tardío de los dos regímenes y 9 h de ventana para reaccionar.
#: Dispara 3 veces en 49 días y las 3 son incidentes diagnosticados.
#:
#: ⚠️ **Un deadline en hora UTC absoluta solo vale para la ventana que lo
#: produjo.** Con 12:00 esta guarda habría disparado en falso los 23 días de la
#: ventana vieja. Y Santiago pasa a UTC-4 el 2027-04-04: ahí 08:00 local son las
#: 12:00 UTC y la holgura de este default baja de 2 h a 1 h. Si alguien mueve
#: `ranker.WINDOW_START_HOUR`, este número hay que volver a medirlo — el
#: backtest de `tests/test_guarda_canal.py` es el que lo dice.
DEADLINE_HOUR_UTC = 13


def canal_mudo_hoy(
    *,
    posts_hoy: int,
    posts_ayer: int,
    ahora: datetime,
    deadline_hour_utc: int = DEADLINE_HOUR_UTC,
) -> str | None:
    """El aviso, o `None` si no hay nada que reportar.

    Mismo contrato que `alerts.format_summary`: función pura, `None` cuando
    callar es lo correcto, y el silencio es el caso normal.

    Los dos días son días calendario **de Santiago** (`ranker.local_day_bounds`),
    que es la unidad en la que el ranker cuenta la cuota. No es un detalle de
    presentación: la ventana termina a las 23:00 de Santiago, o sea 02:00 UTC del
    día siguiente, así que agrupar por fecha UTC partiría la cola de cada día.

    `posts_ayer == 0` calla a propósito. Si ayer tampoco se publicó nada, esto no
    es una caída nueva —es un canal que ya viene mudo, por una razón que esta
    alerta no puede diagnosticar y sobre la que ya habló ayer— y repetir el aviso
    todos los días hasta que alguien lo mute es la forma más segura de perder la
    alerta para cuando importe.
    """
    if posts_hoy > 0:
        return None
    if not ranker.within_window(ahora):
        return None

    inicio_local, _ = ranker.local_day_bounds(ahora)
    dia = inicio_local.date()
    deadline = datetime.combine(dia, time(hour=deadline_hour_utc), tzinfo=timezone.utc)
    if ahora < deadline:
        return None

    if posts_ayer == 0:
        return None

    # La hora de apertura se calcula, no se escribe: es la que mueve el umbral
    # cuando alguien toca `WINDOW_START_HOUR` o cuando Santiago cambia de offset,
    # y un mensaje con la hora vieja hace perder el tiempo justo el día malo.
    apertura = inicio_local.replace(hour=ranker.WINDOW_START_HOUR)
    return (
        f"🔇 OfertasCL — el canal no publicó NADA hoy ({dia.isoformat()}, día de "
        f"Santiago) y ya son las {ahora.astimezone(timezone.utc):%H:%M} UTC. "
        f"La ventana abrió {apertura.astimezone(timezone.utc):%H:%M} UTC y el "
        f"primer post sale siempre en los primeros minutos; el deadline de esta "
        f"guarda son las {deadline_hour_utc:02d}:00 UTC. Ayer publicó {posts_ayer}.\n"
        "Lo más probable es una pasada del scraper reagendada: el pipeline viaja "
        "dentro de ella y los candidatos vencen a las 13 h. Mirá `scrape_runs` y, "
        "si la pasada no está corriendo, disparala a mano:\n"
        "  docker compose exec scraper python -m scrapers.runner --once"
    )


async def posts_hoy_y_ayer(
    conn: asyncpg.Connection, *, ahora: datetime
) -> tuple[int, int]:
    """Posts publicados hoy y ayer, por día calendario de Santiago.

    Cuenta solo filas con `telegram_message_id`: una fila sin él es una reserva
    en vuelo (`poster._reserve`), que se borra si el envío falla. Contarla haría
    que la guarda se calle por un mensaje que no llegó al canal — exactamente el
    falso negativo que esta guarda existe para no tener.
    """
    inicio, fin = ranker.local_day_bounds(ahora)
    ayer = inicio - timedelta(days=1)
    row = await conn.fetchrow(
        """
        SELECT
            count(*) FILTER (WHERE posted_at >= $2) AS hoy,
            count(*) FILTER (WHERE posted_at <  $2) AS ayer
          FROM deal_posts
         WHERE posted_at >= $1
           AND posted_at <  $3
           AND telegram_message_id IS NOT NULL
        """,
        ayer,
        inicio,
        fin,
    )
    return int(row["hoy"]), int(row["ayer"])
