"""Identidad de producto: agrupar sin fusionar cosas distintas.

El sesgo del módulo es explícito — ante la duda no se agrupa. Un GTIN faltante
degrada el copy del mensaje; un GTIN equivocado publica el producto que no es.
"""
from __future__ import annotations

from catalog.identity import MIN_MODEL_LENGTH, canonical_key, normalize_model


def test_gtin_manda_sobre_marca_modelo():
    """Es la evidencia dura: si está, no hace falta nada más."""
    key = canonical_key(gtin="6932554471736", brand="Xiaomi", model="Redmi 13")
    assert key == "gtin:6932554471736"


def test_dos_tiendas_con_el_mismo_gtin_dan_la_misma_llave():
    paris = canonical_key(gtin=" 884116671206 ", brand="Dell", model="Inspiron 15")
    spdigital = canonical_key(gtin="884116671206", brand="DELL", model="INSPIRON-15")
    assert paris == spdigital == "gtin:884116671206"


def test_marca_modelo_es_estable_entre_grafias():
    a = canonical_key(gtin=None, brand="APPLE", model="iPhone 15")
    b = canonical_key(gtin=None, brand="  apple ", model="IPHONE-15")
    assert a == b == "bm:apple|iphone15"


def test_sku_interno_disfrazado_de_gtin_no_agrupa():
    """SP Digital pone su propio SKU en el campo del código de barras."""
    assert canonical_key(
        gtin="NA0000086755", brand=None, model=None, sku="NA0000086755"
    ) is None


def test_sin_identidad_no_hay_llave():
    assert canonical_key(gtin=None, brand="Bosch", model=None) is None
    assert canonical_key(gtin=None, brand=None, model="iPhone 15") is None
    assert canonical_key(gtin=None, brand=None, model=None) is None


def test_gtin_y_marca_modelo_viven_en_espacios_separados():
    """Aunque los caracteres coincidan, nunca deben colisionar."""
    con_gtin = canonical_key(gtin="12345678", brand=None, model=None)
    con_modelo = canonical_key(gtin=None, brand="X", model="12345678")
    assert con_gtin != con_modelo


def test_modelo_corto_no_identifica():
    """'XL' o 'V2' aparecen en decenas de productos que no son el mismo."""
    assert normalize_model("XL") is None
    assert normalize_model("V2") is None
    assert normalize_model("A" * MIN_MODEL_LENGTH) is not None


def test_modelo_todo_digitos_y_corto_se_descarta():
    assert normalize_model("1234") is None
    assert normalize_model("123456") == "123456"


def test_modelo_colapsa_separadores():
    assert normalize_model("SM-A155M/DS") == "sma155mds"
    assert normalize_model("  Ryzen 5 5600X ") == "ryzen55600x"
    assert normalize_model("-") is None
