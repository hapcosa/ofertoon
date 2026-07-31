"""Normalización de datos crudos de tienda a tipos del sistema."""
from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

#: CLP no usa decimales y el punto es separador de miles: "1.299.990" → 1299990.
#: Se aceptan comas por si alguna tienda invierte la convención en un campo suelto.
_NON_DIGIT = re.compile(r"[^\d]")


def parse_clp(raw: str | int | float | None) -> Decimal | None:
    """Convierte un precio chileno a Decimal entero. None si no hay número.

    >>> parse_clp("$ 1.299.990")
    Decimal('1299990')
    >>> parse_clp("679.990")
    Decimal('679990')
    >>> parse_clp("")
    """
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        value = Decimal(str(int(raw)))
        return value if value > 0 else None

    digits = _NON_DIGIT.sub("", raw)
    if not digits:
        return None
    try:
        value = Decimal(digits)
    except InvalidOperation:
        return None
    return value if value > 0 else None


_WHITESPACE = re.compile(r"\s+")


def clean_text(raw: str | None) -> str | None:
    """Colapsa whitespace y recorta. None si queda vacío."""
    if raw is None:
        return None
    cleaned = _WHITESPACE.sub(" ", raw).strip()
    return cleaned or None


def normalize_brand(raw: str | None) -> str | None:
    """Marca en Title Case estable, para que 'APPLE' y 'Apple' sean la misma.

    >>> normalize_brand("APPLE")
    'Apple'
    >>> normalize_brand("  bosch professional ")
    'Bosch Professional'
    """
    cleaned = clean_text(raw)
    return cleaned.title() if cleaned else None
