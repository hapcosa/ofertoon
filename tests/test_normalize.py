"""Normalización compartida entre adaptadores.

`normalize_gtin` es la que más importa: es el campo con el que F1 va a decidir
que el notebook de Paris y el de SP Digital son el mismo producto. Un falso
negativo cuesta un match perdido; un falso positivo publica el producto que no
es, con el precio de otro. Por eso los tests cargan hacia el rechazo.
"""
from __future__ import annotations

from decimal import Decimal

import pytest

from catalog.normalize import clean_text, normalize_brand, normalize_gtin, parse_clp


class TestNormalizeGtin:
    @pytest.mark.parametrize(
        "raw",
        [
            "6932554471736",  # EAN-13, el de Paris
            "884116671206",  # UPC-12, el de SP Digital
            "12345670",  # EAN-8
            "10614141000415",  # GTIN-14
        ],
    )
    def test_acepta_los_cuatro_largos_estandar(self, raw):
        assert normalize_gtin(raw) == raw

    def test_recorta_espacios(self):
        assert normalize_gtin("  884116671206 ") == "884116671206"

    def test_acepta_entero(self):
        """Un JSON puede traerlo sin comillas; el cero a la izquierda no aplica ahí."""
        assert normalize_gtin(884116671206) == "884116671206"

    def test_conserva_ceros_a_la_izquierda(self):
        """En un código de barras el cero inicial es significativo, no relleno."""
        assert normalize_gtin("0884116671206") == "0884116671206"

    @pytest.mark.parametrize("raw", [None, "", "   "])
    def test_vacio_es_none(self, raw):
        assert normalize_gtin(raw) is None

    def test_sku_interno_se_descarta(self):
        """SP Digital rellena el campo con su propio SKU cuando no tiene el código."""
        assert normalize_gtin("NA0000086755", sku="NA0000086755") is None

    def test_sku_numerico_igual_al_gtin_se_descarta(self):
        """El caso peligroso: un SKU que además tiene largo de GTIN.

        Sin la comparación contra el SKU pasaría todos los otros filtros.
        """
        assert normalize_gtin("422530999999", sku="422530999999") is None

    def test_sku_distinto_no_estorba(self):
        assert normalize_gtin("884116671206", sku="NA0000098116") == "884116671206"

    @pytest.mark.parametrize("raw", ["12345", "123456789012345", "1234567890"])
    def test_largo_no_estandar_se_descarta(self, raw):
        assert normalize_gtin(raw) is None

    @pytest.mark.parametrize("raw", ["ABC12345678", "6932-554-4717", "6932554471736 x"])
    def test_no_digitos_se_descarta(self, raw):
        assert normalize_gtin(raw) is None

    @pytest.mark.parametrize("raw", ["00000000", "0000000000000"])
    def test_todo_ceros_es_placeholder(self, raw):
        assert normalize_gtin(raw) is None


class TestParseClp:
    def test_separador_de_miles_chileno(self):
        assert parse_clp("$ 1.299.990") == Decimal("1299990")

    def test_cero_es_none(self):
        """Un precio cero no es un precio: corrompería la baseline de por vida."""
        assert parse_clp("$0") is None
        assert parse_clp(0) is None

    def test_sin_numero_es_none(self):
        assert parse_clp("Consultar") is None


class TestTexto:
    def test_clean_text_colapsa_whitespace(self):
        assert clean_text("  Taladro   percutor \n 20V ") == "Taladro percutor 20V"

    def test_marca_estable_entre_tiendas(self):
        """'APPLE' en una tienda y 'Apple' en otra tienen que agrupar igual."""
        assert normalize_brand("APPLE") == normalize_brand("apple") == "Apple"
