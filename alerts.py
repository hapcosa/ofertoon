"""Aviso post-pasada: qué targets fallaron o quedaron degradados.

El canario deja la evidencia en `scrape_runs`, pero una fila en una tabla que
nadie mira no es una alerta. Esto cierra el lazo: después de cada pasada manda
un mensaje con las corridas `failed` y `partial`.

Silencio = todo verde, a propósito. Si cada pasada mandara un "OK", en una
semana el mensaje sería ruido y el primer `partial` real pasaría de largo.

**El aviso de agujero es distinto y por eso existe aparte** (ver `gap_days`).
Una alerta viaja por `api.telegram.org`, o sea por la misma red saliente que el
scraper usa para las tiendas: cuando esa red se cae, las seis tiendas fallan al
100 % y el mensaje que avisaría de eso tampoco sale. Pasó del 18 al 20 de
septiembre de 2026 — 48 h sin una sola observación, 562 corridas `failed`, cero
alertas — y se descubrió cinco días después mirando `price_points` a mano. El
estado que sobrevive a esa caída es la serie misma, que vive en el Postgres
local: por eso el agujero se detecta leyendo la DB y se reporta en la primera
pasada que SÍ logra hablar con Telegram.

**La pasada a medias es un tercer caso, y no lo veía ninguna de las dos guardas
anteriores** (ver `flacas`). El 29 de septiembre de 2026 una pasada perdió 62 de
129 objetivos y escribió 1.481 observaciones contra las ~16.500 de siempre. No
hubo alerta: el día no quedó vacío —así que `dias_sin_observaciones` lo vio
sano—, el proceso murió dentro de `run_once` —así que sus propios `outcomes`
nunca llegaron acá— y los 62 objetivos que no corrieron no dejaron fila en
`scrape_runs`, que es lo único que el canario por target mira. Tres guardas y
ninguna disparó.

**Y el cuarto caso es el propio mensaje** (ver `recortar_para_telegram`). El
7 de noviembre de 2026 una pasada perdió 202 de 727 objetivos por inestabilidad
de la red saliente; `flacas` la detectó, armó el aviso con sus 202 fallos y
Telegram contestó `400 Bad Request: message is too long`. El aviso quedó solo en
el log. El tope que existía era `MAX_LINES = 25`, que acota **líneas** y no
caracteres: con las URLs percent-encodeadas de los `FetchError` la mediana de
línea era 163 y el máximo 435, así que 28 líneas daban 5.766 caracteres. O sea la
guarda fallaba **justo en el caso grave**, porque es el que produce el mensaje
largo — la misma forma de los tres casos de arriba: la guarda existe, corre, y no
avisa.

Configuración (ambas opcionales; sin ellas el módulo es un no-op y solo loguea):
    ALERT_BOT_TOKEN   token del bot que manda el aviso
    ALERT_CHAT_ID     chat destino (tu DM o un canal privado de operación)
"""
from __future__ import annotations

import logging
import os
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime

logger = logging.getLogger("alerts")

#: Cuántos targets degradados se listan antes de resumir el resto en una línea.
#: Si se rompe el adaptador de una tienda entera son ~10 líneas por tienda.
MAX_LINES = 25

#: Tope duro de `sendMessage`. **Es el que manda**: `MAX_LINES` no alcanza para
#: respetarlo porque cada línea lleva la URL que falló, y esas URLs llevan query
#: strings percent-encodeadas. Medido el 2026-11-07 sobre la pasada que lo
#: destapó: 28 líneas, **5.766 caracteres**, mediana de línea 163 y máximo 435.
#: Telegram contestó `400 Bad Request: message is too long` y la alerta quedó
#: solo en el log — o sea la guarda falló **justo** en el caso grave, porque es
#: el que produce el mensaje largo. Un tope en líneas no acota caracteres.
TELEGRAM_MAX_CHARS = 4096

#: Cuánto de un error se transcribe. Sin esto una sola línea podía ocupar 435 de
#: los 4096 y `MAX_LINES` quedaba decorativo.
MAX_ERROR_CHARS = 110


@dataclass(frozen=True)
class RunOutcome:
    """Resultado de un (tienda, categoría, store_key) en una pasada."""

    store_slug: str
    category_slug: str
    store_key: str
    status: str
    items_seen: int
    items_ok: int
    error: str | None = None


@dataclass(frozen=True)
class PasadaFlaca:
    """Una pasada que escribió mucho menos de lo que viene escribiendo."""

    inicio: datetime
    observaciones: int
    mediana: float


def _miles(n: float) -> str:
    """16509 → '16.509'. Separador chileno, igual que el resto del proyecto."""
    return f"{int(n):,}".replace(",", ".")


def _recortar_error(error: str) -> str:
    """El error sin la cola, que en un `FetchError` es la query string."""
    error = error.strip()
    if len(error) <= MAX_ERROR_CHARS:
        return error
    return error[: MAX_ERROR_CHARS - 1] + "…"


def recortar_para_telegram(text: str) -> str:
    """Deja el mensaje dentro de `TELEGRAM_MAX_CHARS`, cortando por línea.

    Va en el camino de salida y no en cada sección a propósito: es el único
    punto por el que pasan todos los avisos, así que acá el límite se cumple sin
    importar qué sección lo haya armado ni cuántas se agreguen después. La
    primera línea —los conteos— es lo que no se puede perder: dice cuántos
    fallaron, que es la parte que decide si alguien mira.
    """
    if len(text) <= TELEGRAM_MAX_CHARS:
        return text

    lineas = text.split("\n")
    aviso = "… mensaje recortado: {} línea(s) más en el log del scraper"
    # El aviso ocupa lugar, así que se reserva ANTES de elegir cuántas entran.
    presupuesto = TELEGRAM_MAX_CHARS - len(aviso.format(len(lineas))) - 1

    salida: list[str] = []
    usado = 0
    for linea in lineas:
        costo = len(linea) + (1 if salida else 0)
        if usado + costo > presupuesto:
            break
        salida.append(linea)
        usado += costo

    # Si ni la primera línea entra en el presupuesto, se manda recortada: un
    # aviso mutilado sigue siendo mejor que ninguno.
    if not salida:
        return lineas[0][:TELEGRAM_MAX_CHARS]

    salida.append(aviso.format(len(lineas) - len(salida)))
    return "\n".join(salida)


def format_summary(
    outcomes: Sequence[RunOutcome],
    gap_days: Sequence[date] = (),
    flacas: Sequence[PasadaFlaca] = (),
) -> str | None:
    """Mensaje de la pasada, o `None` si no hay nada que reportar.

    `gap_days` son días completos sin ninguna observación
    (`db.dias_sin_observaciones`). `flacas` son pasadas que corrieron a medias
    (`runner.pasadas_flacas`). Las dos se reportan aunque la pasada de ahora
    haya salido verde: son la evidencia de una caída anterior cuya propia alerta
    no pudo salir.

    Las secciones van de lo más viejo y más grave a lo más nuevo: un agujero
    perdió la serie entera de esos días, una pasada flaca perdió medio día, y
    los targets degradados de la pasada de ahora son el problema del momento.
    """
    bad = [o for o in outcomes if o.status in ("failed", "partial")]
    if not bad and not gap_days and not flacas:
        return None

    secciones: list[str] = []

    if gap_days:
        dias = ", ".join(d.isoformat() for d in gap_days)
        secciones.append(
            f"🕳️ OfertasCL — {len(gap_days)} día(s) SIN observaciones: {dias}\n"
            "La serie tiene un agujero: nadie scrapeó o falló todo. "
            "Afecta n_days de cada listing y deja al backtest sin candidatos "
            "esos días."
        )

    if flacas:
        detalle = "\n".join(
            f"  {f.inicio:%Y-%m-%d %H:%M} UTC — {_miles(f.observaciones)} obs "
            f"vs mediana {_miles(f.mediana)} "
            f"({round((1 - f.observaciones / f.mediana) * 100)}% menos)"
            for f in flacas
        )
        secciones.append(
            f"📉 OfertasCL — {len(flacas)} pasada(s) a medias:\n{detalle}\n"
            "La pasada corrió pero escribió una fracción de lo normal. El día no "
            "queda vacío, así que el aviso de agujero no la ve, y los objetivos "
            "que nunca corrieron no dejan fila, así que el canario por target "
            "tampoco. Ese medio día pesa menos en el p50 de cada listing."
        )

    if bad:
        failed = [o for o in bad if o.status == "failed"]
        partial = [o for o in bad if o.status == "partial"]
        lines = [
            f"⚠️ OfertasCL — pasada con {len(failed)} fallo(s) y "
            f"{len(partial)} degradada(s) de {len(outcomes)} corridas",
            "",
        ]
        for outcome in failed + partial:
            icon = "❌" if outcome.status == "failed" else "🟡"
            lines.append(
                f"{icon} {outcome.store_slug}/{outcome.category_slug} "
                f"[{outcome.store_key}] — {outcome.items_seen} items"
                + (f": {_recortar_error(outcome.error)}" if outcome.error else "")
            )
            if len(lines) - 2 >= MAX_LINES:
                lines.append(f"… y {len(bad) - MAX_LINES} más")
                break
        secciones.append("\n".join(lines))

    return "\n\n".join(secciones)


async def send_alert(text: str | None) -> bool:
    """Manda el aviso. `False` si no había nada que mandar o no llegó.

    Nunca lanza: el aviso es observabilidad, y un Telegram caído no puede
    tumbar la ingesta ni hacer que la pasada se reporte como fallida.
    """
    if not text:
        return False

    token = os.environ.get("ALERT_BOT_TOKEN", "").strip()
    raw_chat = os.environ.get("ALERT_CHAT_ID", "").strip()
    if not token or not raw_chat:
        logger.warning("alertas sin configurar (ALERT_BOT_TOKEN/ALERT_CHAT_ID):\n%s", text)
        return False

    try:
        chat_id = int(raw_chat)
    except ValueError:
        logger.error("ALERT_CHAT_ID no es un entero: %r", raw_chat)
        return False

    # Import perezoso: el runner no necesita aiohttp cuando no hay alertas que
    # mandar, que es el caso normal.
    from subscriptions.telegram_client import TelegramClient

    client = TelegramClient(token)
    message_id = await client.send_message(chat_id, recortar_para_telegram(text))
    if message_id is None:
        logger.error("no se pudo enviar la alerta; queda solo en el log:\n%s", text)
        return False
    return True
