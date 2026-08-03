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


#: Largos válidos de GTIN: EAN-8, UPC-12, EAN-13 y GTIN-14. Cualquier otro largo
#: no es un código de barras, es otra cosa que la tienda metió en ese campo.
_GTIN_LENGTHS = frozenset({8, 12, 13, 14})


def normalize_gtin(raw: str | int | None, sku: str | None = None) -> str | None:
    """El GTIN solo cuando de verdad es un GTIN.

    Las tiendas ensucian este campo de tres formas, y las tres envenenarían el
    matching cross-store de F1 — que es el único uso del dato:

      1. Lo dejan vacío o en cero.
      2. Lo rellenan con su propio SKU interno (SP Digital pone `NA0000086755`).
         Dos tiendas nunca comparten un SKU interno, pero un "GTIN" inventado sí
         puede colisionar con el GTIN real de otra tienda y fusionar dos
         productos distintos.
      3. Meten un largo arbitrario que no corresponde a ningún estándar.

    El sesgo es deliberado: ante la duda se descarta. Un GTIN faltante degrada el
    copy del mensaje; un GTIN equivocado publica el producto que no es.

    >>> normalize_gtin("6932554471736")
    '6932554471736'
    >>> normalize_gtin(" 884116671206 ")
    '884116671206'
    >>> normalize_gtin("NA0000086755", sku="NA0000086755")
    >>> normalize_gtin("12345")
    >>> normalize_gtin("0000000000000")
    """
    if raw is None:
        return None

    value = str(raw).strip()
    if not value or not value.isdigit():
        return None
    if sku and value == str(sku).strip():
        return None
    if len(value) not in _GTIN_LENGTHS:
        return None
    # Un código todo ceros es el placeholder clásico de "no tengo el dato".
    if not value.strip("0"):
        return None
    return value
