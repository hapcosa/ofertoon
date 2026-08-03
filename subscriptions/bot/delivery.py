"""Entrega best-effort de invitaciones creadas previamente por el gate."""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
import logging
from typing import Any, Literal

from aiogram.exceptions import TelegramForbiddenError
import asyncpg

from . import db


logger = logging.getLogger("ofertascl.bot.delivery")

SendFn = Callable[[int, str], Awaitable[Any]]
SendErrorKind = Literal["blocked", "transient"]


@dataclass(frozen=True)
class DeliverySummary:
    """Conteos observables de una corrida del batch de entrega."""

    delivered: int = 0
    blocked: int = 0
    errors: int = 0


def format_invite_dm(tier_slug: str, invite_link: str) -> str:
    """Construye el copy español del DM sin depender de Bot API."""
    return f"Tu acceso a {tier_slug}: {invite_link}"


def classify_send_error(exc: Exception) -> SendErrorKind:
    """Distingue un destino bloqueado de cualquier fallo transitorio."""
    if isinstance(exc, TelegramForbiddenError):
        return "blocked"
    return "transient"


async def deliver_pending(
    conn: asyncpg.Connection,
    send_fn: SendFn,
    *,
    limit: int,
) -> DeliverySummary:
    """Intenta una vez cada fila pendiente y continúa ante errores de Telegram.

    Un 403 queda intacto para que la card web sea el fallback. Por decisión de
    F4.3 no se reintenta dentro de este batch; un poll posterior podrá tomar la
    fila nuevamente porque el schema no persiste un estado de bloqueo del DM.
    """
    rows = await db.fetch_pending_dm_deliveries(conn, limit)
    delivered = 0
    blocked = 0
    errors = 0

    for row in rows:
        user_id = int(row["telegram_user_id"])
        tier_id = int(row["tier_id"])
        text = format_invite_dm(row["tier_slug"], row["invite_link"])
        try:
            await send_fn(user_id, text)
        except Exception as exc:
            if classify_send_error(exc) == "blocked":
                blocked += 1
                logger.info(
                    "DM no disponible para telegram_user_id=%s tier_id=%s; "
                    "se conserva el fallback web",
                    user_id,
                    tier_id,
                )
            else:
                errors += 1
                logger.warning(
                    "Error transitorio al entregar DM a telegram_user_id=%s "
                    "tier_id=%s: %s",
                    user_id,
                    tier_id,
                    exc,
                )
            continue

        await db.mark_dm_delivered(conn, user_id, tier_id)
        delivered += 1

    return DeliverySummary(
        delivered=delivered,
        blocked=blocked,
        errors=errors,
    )
