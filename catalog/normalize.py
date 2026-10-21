"""Normalización de datos crudos de tienda a tipos del sistema."""
from __future__ import annotations

import re
import unicodedata
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


#: Marcas de producto que NO es nuevo, tal como las escriben las tiendas chilenas.
#: Verificado contra los nombres reales el 2026-10-12 — las variantes son pocas y
#: consistentes: "(Reacondicionado)", "- Reacondicionado", "Reacondicionado
#: Iphone 13 Pro...", "Open Box".
#:
#: Se buscan sobre el nombre con tildes normalizadas, que es la lección de la
#: migración 24: medir "Botín" con el patrón `botin` daba 32% y era un bug del
#: clasificador, no del dato.
_SEGUNDA_MANO = (
    "reacondicionado",
    "reacondicionada",
    "refurbished",
    "open box",
    "openbox",
    "usado",
    "segunda mano",
)


def es_segunda_mano(nombre: str | None) -> bool:
    """¿El nombre dice que el producto no es nuevo?

    Importa porque un reacondicionado **no tiene la curva de precio de una
    oferta**: baja y se queda abajo, porque el precio sigue la depreciación y el
    grado del equipo, no una promoción. Medido el 2026-10-12 sobre
    `tecno-celulares`, excluirlos sube la precisión del detector entre 10 y 30
    puntos según θ (67,4% → 78,1% a θ 0.10; 41,7% → 71,4% a θ 0.20) y **hace
    desaparecer el patrón invertido** que tenía esa categoría, donde un descuento
    más grande predecía peor: entre los aceptados con ≥30% de descuento el 44% eran
    reacondicionados, contra el 8% entre los de menos de 30%.

    Y es un problema de producto antes que de métrica: el canal promete ofertas de
    retail, y para cuando se midió esto **8 de las 132 ofertas publicadas eran
    reacondicionados**.

    Se mira el nombre y no un campo estructurado porque ninguna de las tiendas
    conectadas expone la condición del producto por separado.
    """
    if not nombre:
        return False
    plano = unicodedata.normalize("NFKD", nombre.lower())
    plano = "".join(ch for ch in plano if not unicodedata.combining(ch))
    return any(marca in plano for marca in _SEGUNDA_MANO)


#: Hardware de servidor: no es producto de consumo y no va al canal.
#:
#: Los cuatro patrones están verificados contra el catálogo real el 2026-10-21, y
#: dos que parecían obvios quedaron AFUERA porque filtraban consumo:
#:
#:     server|servidor   31 listings, p50 $599.990 — limpio, incluye las memorias
#:                       ECC de servidor de $16.990 que también son empresariales
#:     HPE               17 — limpio (es la marca empresarial de HP, no "HP")
#:     SAS               12 — limpio, todos discos de servidor
#:     enterprise         3 — limpio
#:     ── descartados ──────────────────────────────────────────────────────────
#:     rack               ✗ filtraba "Nike Squat Rack" ($449.990) y "Rack Para
#:                          Lavadora Secadora" ($122.990)
#:     SFF | BC           ✗ filtraba "Torta Red Velvet Bc" de Tottus ($4.590) y un
#:                          "Adaptador M.2 SSD a U.2 SFF-8639" de consumo
#:
#: `proliant` entra por completitud aunque hoy dé 0: es la línea de servidores de
#: HPE y aparecería junto a los demás.
_HARDWARE_SERVIDOR = (
    r"\bserver\b",
    r"\bservidor",
    r"\bhpe\b",
    r"\bproliant\b",
    r"\bsas\b",
    r"\benterprise\b",
)


def es_hardware_servidor(nombre: str | None) -> bool:
    """¿El nombre dice que es hardware de servidor?

    El canal es de ofertas de retail de consumo, y un disco de servidor no lo es
    por más real que sea su descuento. El 2026-10-20 el canal publicó dos —de
    $5.989.990 y $7.789.990— que ocuparon **2 de los 14 lugares del día**.

    No es un techo de precio, y eso es deliberado: los televisores de 85" y 98"
    cuestan $1,5-1,9M y son consumo legítimo (14 aceptados en la semana). Lo que
    descalifica al disco de servidor es qué es, no cuánto vale. Medido: son 14
    listings de los 847 de PC Factory (1,7%) y vienen mezclados dentro de llaves
    legítimas —`Discos Internos SSD`, `Memorias PC`—, así que no hay una llave que
    desactivar.

    Mismo mecanismo que `es_segunda_mano`: se mira el nombre porque ninguna tienda
    marca "esto es para servidores" en un campo aparte.
    """
    if not nombre:
        return False
    plano = unicodedata.normalize("NFKD", nombre.lower())
    plano = "".join(ch for ch in plano if not unicodedata.combining(ch))
    return any(re.search(p, plano) for p in _HARDWARE_SERVIDOR)
