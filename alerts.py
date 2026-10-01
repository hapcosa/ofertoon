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
#: Si se rompe el adaptador de una tienda entera son ~10 líneas por tienda y el
#: mensaje excedería el límite de Telegram (4096 chars).
MAX_LINES = 25


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
                + (f": {outcome.error}" if outcome.error else "")
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
    message_id = await client.send_message(chat_id, text)
    if message_id is None:
        logger.error("no se pudo enviar la alerta; queda solo en el log:\n%s", text)
        return False
    return True
