"""Cliente mínimo de Telegram Bot API — poster (`sendMessage`) + gate de
membresía (`createChatInviteLink`, `banChatMember`, `unbanChatMember`, DM).

PORT de `signalsTrading/telegram_signals/telegram_client.py`, copiado sin tocar
la lógica (solo el logger y el nombre de la variable de entorno del token). Lo
usa hoy `alerts.py` para el aviso post-pasada del scraper; en F2 lo reusan el
gate y el publisher tal cual, que es la razón de no reescribirlo sobre httpx:
un segundo cliente sería una fuente de divergencia gratis.

Estilo defensivo (igual en todos los métodos): cualquier fallo — token ausente,
HTTP != 200, `ok=false`, excepción de red — se loguea como warning y devuelve
una señal de fallo (None / False), NUNCA lanza. Así un canal/tier caído o el Bot
API caído no tumban el daemon; el reconciler reintenta en el próximo ciclo.
"""
from __future__ import annotations

from datetime import datetime, timezone
import logging
from typing import Any

import aiohttp


logger = logging.getLogger("ofertascl.telegram")
_API_URL = "https://api.telegram.org/bot{token}/{method}"


class TelegramClient:
    def __init__(self, token: str, *, timeout_seconds: float = 10.0) -> None:
        self._token = (token or "").strip()
        self._timeout = aiohttp.ClientTimeout(total=timeout_seconds)
        if not self._token:
            logger.warning("telegram_disabled — ALERT_BOT_TOKEN missing")

    async def _call(
        self, method: str, payload: dict[str, Any]
    ) -> dict[str, Any] | None:
        """POST a un método de Bot API; devuelve `result` (dict, `{}` si escalar)
        o `None` ante cualquier fallo. No lanza nunca."""
        if not self._token:
            return None
        try:
            async with aiohttp.ClientSession(timeout=self._timeout) as session:
                async with session.post(
                    _API_URL.format(token=self._token, method=method), json=payload
                ) as response:
                    body = await response.json(content_type=None)
                    if response.status != 200 or not body.get("ok"):
                        logger.warning(
                            "telegram_http_error method=%s status=%s body=%s",
                            method,
                            response.status,
                            str(body)[:200],
                        )
                        return None
                    result = body.get("result")
                    return result if isinstance(result, dict) else {}
        except Exception as exc:  # noqa: BLE001 — un tier caído no tumba el daemon
            logger.warning("telegram_call_error method=%s error=%s", method, exc)
            return None

    async def _call_multipart(
        self, method: str, data: "aiohttp.FormData"
    ) -> dict[str, Any] | None:
        """Igual que `_call` pero con cuerpo multipart (para subir la foto).
        Mismo contrato defensivo: nunca lanza, devuelve `None` ante cualquier
        fallo."""
        if not self._token:
            return None
        try:
            async with aiohttp.ClientSession(timeout=self._timeout) as session:
                async with session.post(
                    _API_URL.format(token=self._token, method=method), data=data
                ) as response:
                    body = await response.json(content_type=None)
                    if response.status != 200 or not body.get("ok"):
                        logger.warning(
                            "telegram_http_error method=%s status=%s body=%s",
                            method,
                            response.status,
                            str(body)[:200],
                        )
                        return None
                    result = body.get("result")
                    return result if isinstance(result, dict) else {}
        except Exception as exc:  # noqa: BLE001 — un tier caído no tumba el daemon
            logger.warning("telegram_call_error method=%s error=%s", method, exc)
            return None

    async def send_message(
        self,
        chat_id: int | None,
        text: str,
        parse_mode: str | None = None,
        *,
        disable_web_page_preview: bool = True,
    ) -> int | None:
        """Publica un mensaje y devuelve `message_id`; falla como no-op.

        `parse_mode` es opcional: sin él el texto va plano (poster VIP/Cornix),
        con `"HTML"` Telegram interpreta el formato (canal informativo). Sólo se
        agrega a la request cuando viene, para no tocar el contrato del VIP.

        `disable_web_page_preview` mantiene el default del port (True: una
        alerta o un DM no quieren card). El publisher de ofertas lo pone en
        False a propósito — la card del link ES la foto del producto, y así no
        hay que subir una imagen que puede fallar.
        """
        if chat_id is None:
            logger.warning("telegram_send_skipped — tier channel_id missing")
            return None
        payload: dict[str, Any] = {
            "chat_id": chat_id,
            "text": text,
            "disable_web_page_preview": disable_web_page_preview,
        }
        if parse_mode is not None:
            payload["parse_mode"] = parse_mode
        result = await self._call("sendMessage", payload)
        if result is None:
            return None
        message_id = result.get("message_id")
        if message_id is None:
            logger.warning(
                "telegram_invalid_response — message_id missing result=%s",
                str(result)[:200],
            )
            return None
        return int(message_id)

    async def send_photo(
        self,
        chat_id: int | None,
        photo: bytes,
        *,
        caption: str | None = None,
        parse_mode: str | None = None,
        filename: str = "result.png",
    ) -> int | None:
        """Publica una foto (`sendPhoto`, multipart) con caption opcional y
        devuelve `message_id`; falla como no-op. El canal informativo la usa para
        la tarjeta de resultado; el caption lleva el mismo texto que el post de
        texto para no perder accesibilidad."""
        if chat_id is None:
            logger.warning("telegram_send_photo_skipped — tier channel_id missing")
            return None
        form = aiohttp.FormData()
        form.add_field("chat_id", str(chat_id))
        if caption is not None:
            form.add_field("caption", caption)
        if parse_mode is not None:
            form.add_field("parse_mode", parse_mode)
        form.add_field(
            "photo", photo, filename=filename, content_type="image/png"
        )
        result = await self._call_multipart("sendPhoto", form)
        if result is None:
            return None
        message_id = result.get("message_id")
        if message_id is None:
            logger.warning(
                "telegram_invalid_response — message_id missing result=%s",
                str(result)[:200],
            )
            return None
        return int(message_id)

    async def edit_message_text(
        self, chat_id: int | None, message_id: int | None, text: str
    ) -> bool:
        """Reescribe un mensaje ya publicado. Devuelve True si Bot API confirmó.

        Telegram responde `ok=false` cuando el texto nuevo es idéntico al viejo
        ("message is not modified"); el llamador ya compara el payload antes de
        pedir la edición, así que ese caso se trata como cualquier otro fallo:
        se loguea y se reintenta en el próximo ciclo.
        """
        if chat_id is None or message_id is None:
            logger.warning("telegram_edit_skipped — chat_id/message_id missing")
            return False
        result = await self._call(
            "editMessageText",
            {
                "chat_id": chat_id,
                "message_id": message_id,
                "text": text,
                "disable_web_page_preview": True,
            },
        )
        return result is not None

    async def pin_chat_message(
        self, chat_id: int | None, message_id: int | None
    ) -> bool:
        """Ancla un mensaje. Idempotente del lado de Telegram: anclar lo ya
        anclado responde ok. `disable_notification` evita avisar al canal cada
        vez que la ficha se re-ancla."""
        if chat_id is None or message_id is None:
            logger.warning("telegram_pin_skipped — chat_id/message_id missing")
            return False
        result = await self._call(
            "pinChatMessage",
            {
                "chat_id": chat_id,
                "message_id": message_id,
                "disable_notification": True,
            },
        )
        return result is not None

    async def create_chat_invite_link(
        self,
        chat_id: int | None,
        *,
        member_limit: int = 1,
        expire_date: datetime | int | None = None,
    ) -> str | None:
        """Crea un invite link (por defecto de un solo uso, con expiración) y
        devuelve el link; falla como no-op (None)."""
        if chat_id is None:
            logger.warning("telegram_invite_skipped — channel_id missing")
            return None
        payload: dict[str, Any] = {"chat_id": chat_id, "member_limit": member_limit}
        if expire_date is not None:
            payload["expire_date"] = _as_unix(expire_date)
        result = await self._call("createChatInviteLink", payload)
        if result is None:
            return None
        link = result.get("invite_link")
        if not link:
            logger.warning(
                "telegram_invite_invalid_response — invite_link missing result=%s",
                str(result)[:200],
            )
            return None
        return str(link)

    async def ban_chat_member(
        self, chat_id: int | None, user_id: int | None
    ) -> bool:
        """Expulsa (banea) a un miembro. Devuelve True si Bot API confirmó."""
        if chat_id is None or user_id is None:
            logger.warning("telegram_ban_skipped — chat_id/user_id missing")
            return False
        result = await self._call(
            "banChatMember", {"chat_id": chat_id, "user_id": user_id}
        )
        return result is not None

    async def unban_chat_member(
        self, chat_id: int | None, user_id: int | None
    ) -> bool:
        """Levanta el ban (permite re-unirse). `only_if_banned` lo hace idempotente.
        Devuelve True si Bot API confirmó."""
        if chat_id is None or user_id is None:
            logger.warning("telegram_unban_skipped — chat_id/user_id missing")
            return False
        result = await self._call(
            "unbanChatMember",
            {"chat_id": chat_id, "user_id": user_id, "only_if_banned": True},
        )
        return result is not None

    async def send_dm(self, user_id: int | None, text: str) -> int | None:
        """DM directo al usuario (reusa `sendMessage` con chat_id=user_id). Falla
        como no-op si el usuario nunca inició el bot (Telegram responde 403)."""
        return await self.send_message(user_id, text)


def _as_unix(expire_date: datetime | int) -> int:
    """Normaliza a epoch-seconds; los naïve se asumen UTC."""
    if isinstance(expire_date, datetime):
        dt = (
            expire_date
            if expire_date.tzinfo is not None
            else expire_date.replace(tzinfo=timezone.utc)
        )
        return int(dt.timestamp())
    return int(expire_date)
