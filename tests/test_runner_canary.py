"""El canario relativo: detectar "muchos menos items", no solo "cero items".

El caso que motiva todo esto: una categoría de Falabella devuelve ~942 items.
Con el umbral absoluto anterior (5), un parser roto a medias que devolviera 60
cerraba en `ok` y envenenaba la baseline en silencio.
"""
from __future__ import annotations

import pytest

from scrapers.runner import (
    CANARY_MIN_HISTORY,
    CANARY_MIN_ITEMS,
    canary_verdict,
)


def test_caida_grande_contra_la_mediana_marca_partial():
    history = [942, 940, 945, 939, 941, 944, 938]
    status, reason = canary_verdict(60, history)
    assert status == "partial"
    assert "60 items" in reason
    assert "94" in reason  # 94% menos que la mediana


def test_volumen_normal_pasa_limpio():
    history = [942, 940, 945, 939, 941, 944, 938]
    assert canary_verdict(937, history) == ("ok", None)


def test_fluctuacion_bajo_el_umbral_no_alarma():
    """39% menos todavía es ruido tolerado; el corte acordado es 40%."""
    history = [100, 100, 100, 100, 100]
    assert canary_verdict(61, history) == ("ok", None)

    status, _ = canary_verdict(59, history)
    assert status == "partial"


def test_sin_historia_suficiente_solo_rige_el_piso_absoluto():
    """Un target nuevo no tiene con qué comparar: mejor ciego que gritando."""
    history = [900] * (CANARY_MIN_HISTORY - 1)
    assert canary_verdict(10, history) == ("ok", None)

    status, reason = canary_verdict(0, history)
    assert status == "partial"
    assert f"piso {CANARY_MIN_ITEMS}" in reason


def test_cero_items_siempre_es_partial():
    assert canary_verdict(0, [])[0] == "partial"
    assert canary_verdict(0, [900] * 7)[0] == "partial"


def test_la_mediana_ignora_un_outlier_alto():
    """Una corrida excepcional no puede subir la vara para las siguientes."""
    history = [5000, 100, 100, 100, 100]
    assert canary_verdict(95, history) == ("ok", None)


def test_target_historicamente_chico_no_se_marca_por_ser_chico():
    """Categorías de 8 items existen; lo que importa es su propio historial."""
    history = [8, 8, 9, 8, 8]
    assert canary_verdict(8, history) == ("ok", None)


@pytest.mark.parametrize("median_history", ([0, 0, 0], [0, 0, 0, 0, 0]))
def test_historia_en_cero_no_divide_por_cero(median_history):
    assert canary_verdict(7, median_history) == ("ok", None)
