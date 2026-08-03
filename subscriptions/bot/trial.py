"""Decisiones puras del trial global de onboarding.

La deduplicación por Telegram + email solo encarece el abuso: varias cuentas de
Telegram con varios emails reales todavía pueden obtener más de un trial. La
verificación por código con Resend es el siguiente escalón (F4.6) y queda fuera
del alcance de esta fase.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from .email_validation import is_disposable, normalize_email


TrialReason = Literal[
    "ok",
    "invalid_email",
    "disposable",
    "already_used",
    "email_reused",
]


@dataclass(frozen=True)
class TrialDecision:
    allowed: bool
    reason: TrialReason
    email_normalized: str | None

    @property
    def should_retry_email(self) -> bool:
        return self.reason in {"invalid_email", "disposable"}


def evaluate_trial_eligibility(
    email_raw: str,
    denylist: set[str],
    identity_trial_used_at: datetime | None,
    email_owner_trial_used_at: datetime | None,
) -> TrialDecision:
    """Evalúa las cuatro defensas de D-4a sin hacer I/O."""
    normalized = normalize_email(email_raw)
    if normalized is None:
        return TrialDecision(False, "invalid_email", None)
    if is_disposable(normalized, denylist):
        return TrialDecision(False, "disposable", normalized)
    if identity_trial_used_at is not None:
        return TrialDecision(False, "already_used", normalized)
    if email_owner_trial_used_at is not None:
        return TrialDecision(False, "email_reused", normalized)
    return TrialDecision(True, "ok", normalized)


def trial_decision_message(decision: TrialDecision) -> str:
    """Copy español asociado a una decisión, independiente de aiogram."""
    messages = {
        "invalid_email": "Email inválido, probá de nuevo.",
        "disposable": (
            "Ese proveedor de email no está permitido. "
            "Probá con un email personal."
        ),
        "already_used": "Ya usaste tu trial. Pagá 👇",
        "email_reused": "Ya usaste tu trial. Pagá 👇",
        "ok": "",
    }
    return messages[decision.reason]


def grant_conflict_message(reason: str) -> str:
    """Copy para una carrera detectada dentro de la transacción DB."""
    if reason == "membership_exists":
        return "Ya tenés acceso o un trial en curso para este canal."
    return "Ya usaste tu trial. Pagá 👇"
