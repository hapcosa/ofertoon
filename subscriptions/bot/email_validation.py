"""Normalización y bloqueo básico de emails para el trial de onboarding."""
from __future__ import annotations

from pathlib import Path
import re


_EMAIL_PATTERN = re.compile(
    r"^[a-z0-9.!#$%&'*+/=?^_`{|}~-]+@"
    r"(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$"
)
_GMAIL_DOMAINS = {"gmail.com", "googlemail.com"}


def normalize_email(raw: str) -> str | None:
    """Devuelve la identidad canónica del email o ``None`` si es inválido."""
    candidate = raw.strip().lower()
    if not _EMAIL_PATTERN.fullmatch(candidate):
        return None

    local, domain = candidate.rsplit("@", 1)
    local = local.split("+", 1)[0]
    if domain in _GMAIL_DOMAINS:
        local = local.replace(".", "")
        domain = "gmail.com"
    if not local:
        return None
    return f"{local}@{domain}"


def load_disposable_domains(path: str | Path) -> set[str]:
    """Carga una denylist ampliable, ignorando blancos y comentarios ``#``."""
    denylist: set[str] = set()
    for raw_line in Path(path).read_text(encoding="utf-8").splitlines():
        domain = raw_line.split("#", 1)[0].strip().lower()
        if domain:
            denylist.add(domain)
    return denylist


def is_disposable(email_normalized: str, denylist: set[str]) -> bool:
    """Indica si el dominio canónico está incluido en la denylist."""
    _local, separator, domain = email_normalized.rpartition("@")
    return bool(separator) and domain in denylist
