"""Lógica pura de verificación de email para el onboarding Telegram."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
from html import escape
import hmac
import secrets
from typing import Literal


VerifyReason = Literal[
    "ok",
    "expired",
    "too_many_attempts",
    "already_consumed",
    "mismatch",
]


@dataclass(frozen=True)
class VerifyDecision:
    """Resultado tipado de un intento, independiente de DB y aiogram."""

    reason: VerifyReason

    @property
    def ok(self) -> bool:
        return self.reason == "ok"


def generate_code() -> str:
    """Genera un código numérico criptográficamente seguro de seis dígitos."""
    return f"{secrets.randbelow(1_000_000):06d}"


def hash_code(code: str) -> str:
    """Devuelve el SHA-256 hexadecimal del código recibido."""
    return sha256(code.encode("utf-8")).hexdigest()


def verify_code_attempt(
    *,
    submitted_code: str,
    stored_hash: str,
    expires_at: datetime,
    attempts: int,
    consumed_at: datetime | None,
    max_attempts: int,
    now: datetime,
) -> VerifyDecision:
    """Evalúa un intento respetando la precedencia del contrato F4.6."""
    if max_attempts <= 0:
        raise ValueError("max_attempts debe ser mayor que cero")
    if consumed_at is not None:
        return VerifyDecision("already_consumed")
    if now > expires_at:
        return VerifyDecision("expired")
    if attempts >= max_attempts:
        return VerifyDecision("too_many_attempts")
    if not hmac.compare_digest(hash_code(submitted_code), stored_hash):
        return VerifyDecision("mismatch")
    return VerifyDecision("ok")


def verify_decision_message(decision: VerifyDecision) -> str:
    """Copy español asociado a cada decisión de verificación."""
    messages = {
        "ok": "",
        "expired": "El código venció. Ingresá tu email para recibir uno nuevo.",
        "too_many_attempts": (
            "Agotaste los intentos. Ingresá tu email para recibir un código nuevo."
        ),
        "already_consumed": (
            "Ese código ya fue usado. Ingresá tu email para recibir uno nuevo."
        ),
        "mismatch": "Código incorrecto.",
    }
    return messages[decision.reason]


def render_code_email(*, code: str, tier_name: str) -> tuple[str, str]:
    """Renderiza subject y HTML inline del código de verificación."""
    subject = "Tu código de verificación — OfertasCL"
    html = f"""
    <div style="font-family:-apple-system,system-ui,sans-serif;max-width:480px;margin:0 auto">
      <h2 style="color:#ff5722">OfertasCL</h2>
      <p>Tu código para activar el trial de <b>{escape(tier_name)}</b> es:</p>
      <p style="font-size:32px;font-weight:bold;letter-spacing:8px">{code}</p>
      <p style="color:#666;font-size:12px">
        El código vence pronto. Si no pediste este trial, ignorá este mensaje.
      </p>
    </div>
    """.strip()
    return subject, html
