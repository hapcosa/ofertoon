"""Un GTIN que no cabe en la columna se descarta; el producto entra igual.

Nació de un fallo real: el 2026-11-09 una llave de `unimarc/supermercado`
fallaba en cada pasada con `StringDataRightTruncationError: value too long for
type character varying(14)`, y con ella se perdían ~1.700 observaciones por
pasada. El GTIN solo alimenta el matching cross-store, así que perderlo degrada
el copy — perder la llave pierde la serie, que es el producto.
"""
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from scrapers.base import GTIN_MAX_CHARS, PRICE_CONDITION_MAX_CHARS, RawProduct


def _producto(**extra) -> RawProduct:
    return RawProduct(
        store_slug="tienda", store_sku="sku-1", url="https://x/p", name="Producto",
        price_effective=Decimal("1000"),
        scraped_at=datetime(2026, 11, 9, tzinfo=timezone.utc), **extra,
    )


@pytest.mark.parametrize("gtin", ["7802910007062", "8" * GTIN_MAX_CHARS, "884116671206"])
def test_gtin_que_cabe_se_conserva(gtin: str) -> None:
    assert _producto(gtin=gtin).gtin == gtin


@pytest.mark.parametrize("largo", [GTIN_MAX_CHARS + 1, 20, 40])
def test_gtin_que_no_cabe_se_descarta_sin_perder_el_producto(largo: int) -> None:
    producto = _producto(gtin="9" * largo)
    assert producto.gtin is None
    # Lo que importa: el producto sigue existiendo y su precio intacto.
    assert producto.store_sku == "sku-1"
    assert producto.price_effective == Decimal("1000")


def test_el_gtin_largo_no_lanza_pero_la_condicion_si() -> None:
    """El caso de control: descartar y lanzar son decisiones distintas.

    Un GTIN largo es ruido conocido de las tiendas y hacerlo lanzar costaría la
    llave entera. Una `price_condition` larga es un bug del adaptador y tiene que
    gritar. Si alguien unifica los dos comportamientos, este test falla.
    """
    _producto(gtin="9" * 40)                      # no lanza

    with pytest.raises(ValueError, match="price_condition"):
        _producto(price_condition="x" * (PRICE_CONDITION_MAX_CHARS + 1))
