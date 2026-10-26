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


def test_categoria_chica_de_verdad_no_dispara_el_piso():
    """Con historia propia, el piso absoluto no manda.

    `Tarjetas Gráficas AMD` de PC Factory tiene 3 productos y los tuvo siempre.
    Marcarla `partial` en cada pasada es ruido permanente que tapa los errores
    reales, no una detección.
    """
    assert canary_verdict(3, [3, 3, 3, 3, 3]) == ("ok", None)


def test_un_nivel_nuevo_sostenido_deja_de_alarmar():
    """El canario no se puede quedar enclavado en el nivel viejo.

    SP Digital perdió un tercio de su stock el 28-ago. Una vez que la historia
    refleja el nivel nuevo —lo que ahora ocurre porque `recent_items_seen`
    incluye las corridas `partial`— la caída deja de ser noticia.
    """
    assert canary_verdict(18, [18, 19, 19, 18, 19, 19, 18]) == ("ok", None)


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


# -----------------------------------------------------------------------------
# Completitud exacta: tiendas que declaran cuántos productos tiene la categoría
# -----------------------------------------------------------------------------


def test_completitud_exacta_reemplaza_a_la_mediana():
    """Si la tienda dice 18 y enumeramos 18, la corrida está completa.

    Ninguna mediana puede contradecir eso: el catálogo cambió de nivel, no el
    adaptador. Es el falso positivo que SP Digital produjo durante días.
    """
    history = [47, 46, 48, 47, 46, 45, 47]
    assert canary_verdict(18, history, completeness=(18, 18)) == ("ok", None)


def test_paginacion_incompleta_es_partial_aunque_el_volumen_parezca_normal():
    """El modo de falla que esto ataca: la paginación se corta a mitad.

    50 de 74 pasa cualquier vara estadística contra una historia de 74.
    """
    status, reason = canary_verdict(50, [74] * 7, completeness=(50, 74))
    assert status == "partial"
    assert "50 de 74" in reason


def test_enumerar_de_mas_no_alarma():
    """`totalCount` se lee de la primera página; si el inventario crece mientras
    paginamos, enumerar más que lo declarado no es una falla nuestra."""
    assert canary_verdict(76, [74] * 7, completeness=(76, 74)) == ("ok", None)


def test_sin_declaracion_de_la_tienda_rige_el_canario_estadistico():
    status, _ = canary_verdict(50, [942] * 7, completeness=None)
    assert status == "partial"
