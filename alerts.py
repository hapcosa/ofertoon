"""Aviso post-pasada: qué targets fallaron o quedaron degradados.

El canario deja la evidencia en `scrape_runs`, pero una fila en una tabla que
nadie mira no es una alerta. Esto cierra el lazo: después de cada pasada manda
un mensaje con las corridas `failed` y `partial`.

Silencio = todo verde, a propósito. Si cada pasada mandara un "OK", en una
semana el mensaje sería ruido y el primer `partial` real pasaría de largo.

Configuración (ambas opcionales; sin ellas el módulo es un no-op y solo loguea):
    ALERT_BOT_TOKEN   token del bot que manda el aviso
    ALERT_CHAT_ID     chat destino (tu DM o un canal privado de operación)
"""
from __future__ import annotations

import logging
import os
from collections.abc import Sequence
from dataclasses import dataclass

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


def format_summary(outcomes: Sequence[RunOutcome]) -> str | None:
    """Mensaje de la pasada, o `None` si no hay nada que reportar."""
    bad = [o for o in outcomes if o.status in ("failed", "partial")]
    if not bad:
        return None

    failed = [o for o in bad if o.status == "failed"]
    partial = [o for o in bad if o.status == "partial"]
    total = len(outcomes)

    header = (
        f"⚠️ OfertasCL — pasada con {len(failed)} fallo(s) y "
        f"{len(partial)} degradada(s) de {total} corridas"
    )
    lines = [header, ""]
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
    return "\n".join(lines)


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
