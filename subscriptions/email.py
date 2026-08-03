"""Envío de email transaccional (Resend), con fallback a log.

PORT de `signalsTrading/dashboard/backend/auth/email.py`, recortado a lo único
que OfertasCL necesita: el código de verificación del trial. Las plantillas de
auth del dashboard no se portan (no hay dashboard).

Sin `RESEND_API_KEY` el "envío" solo loguea el payload y devuelve True: el
funnel completo se puede probar en dev sin proveedor. Es deliberado que devuelva
True — un False hace que el bot le pida al usuario reintentar el email, que en
dev sería un callejón sin salida.
"""
from __future__ import annotations

import logging
import os

import httpx

logger = logging.getLogger("ofertascl.email")

_RESEND_URL = "https://api.resend.com/emails"
_RESEND_TIMEOUT = 10.0

#: Remitente sandbox de Resend: funciona sin verificar un dominio propio. El
#: "From" se lee `onboarding@resend.dev`, feo pero permite ejercitar el flujo
#: antes de registrar el dominio de producción.
_SANDBOX_FROM = "onboarding@resend.dev"


def _config() -> tuple[str | None, str]:
    """Devuelve (api_key o None, from_email)."""
    api_key = os.environ.get("RESEND_API_KEY", "").strip() or None
    from_email = os.environ.get("FROM_EMAIL", "").strip() or _SANDBOX_FROM
    return api_key, from_email


async def send_email(
    *,
    to: str,
    subject: str,
    html: str,
    text: str | None = None,
    reply_to: str | None = None,
) -> bool:
    """Envía un email transaccional. True si se envió (o si estamos en dev)."""
    api_key, from_email = _config()
    payload: dict[str, object] = {
        "from": from_email,
        "to": [to] if isinstance(to, str) else to,
        "subject": subject,
        "html": html,
    }
    if text:
        payload["text"] = text
    if reply_to:
        payload["reply_to"] = reply_to

    if not api_key:
        snippet = html[:200] + ("…" if len(html) > 200 else "")
        logger.info(
            "[email-dev] from=%s to=%s subject=%r body=%r",
            from_email,
            to,
            subject,
            snippet,
        )
        return True

    try:
        async with httpx.AsyncClient(timeout=_RESEND_TIMEOUT) as client:
            resp = await client.post(
                _RESEND_URL,
                headers={"Authorization": f"Bearer {api_key}"},
                json=payload,
            )
    except httpx.HTTPError as exc:
        logger.warning("[email] falló el request a Resend: %s", exc)
        return False

    if resp.status_code >= 400:
        # Resend devuelve un JSON con `message`; loguearlo hace que los
        # problemas de entregabilidad (dominio sin verificar, rate limit, From
        # inválido) sean accionables sin volver a pegarle a Resend.
        try:
            body = resp.json()
        except ValueError:
            body = {"raw": resp.text[:500]}
        logger.warning("[email] Resend HTTP %s para to=%s: %s", resp.status_code, to, body)
        return False

    return True
