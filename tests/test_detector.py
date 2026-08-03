"""Las guardas del detector, una por una.

El requisito del producto es que las ofertas sean reales. Cada guarda es un modo
concreto de publicar basura, y cada test de acá es ese modo puesto por escrito.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from pricing.baselines import MIN_DAYS, MIN_POINTS, Baseline
from pricing.detector import (
    COOLDOWN_DAYS,
    REJECT_ABOVE_FLOOR,
    REJECT_COOLDOWN,
    REJECT_HISTORY,
    REJECT_RAMP,
    REJECT_STOCK,
    REJECT_THRESHOLD,
    UNPERSISTED_REJECTS,
    PriorPost,
    evaluate,
)

NOW = datetime(2026, 9, 15, 20, 0, tzinfo=timezone.utc)
THETA = Decimal("0.15")


def baseline(
    p50=100000, p10=85000, minimum=80000, n_points=None, n_days=None, ramp=False
):
    return Baseline(
        p50=Decimal(p50),
        p10=Decimal(p10),
        minimum=Decimal(minimum),
        n_points=MIN_POINTS if n_points is None else n_points,
        n_days=MIN_DAYS if n_days is None else n_days,
        ramp_flag=ramp,
    )


def check(price, *, base=None, in_stock=True, threshold=THETA, prior=None):
    return evaluate(
        price=Decimal(price),
        in_stock=in_stock,
        baseline=base or baseline(),
        threshold=threshold,
        prior_post=prior,
        now=NOW,
    )


def test_oferta_real_pasa_todas_las_guardas():
    decision = check(70000)  # 30% bajo el p50 y bajo el piso de 85.000
    assert decision.accepted
    assert decision.discount_real == Decimal("0.3000")
    assert decision.score > 0


def test_descuento_se_mide_contra_el_p50_no_contra_el_precio_declarado():
    """Es el corazón del producto: la tienda no define cuánto descontó."""
    assert check(50000).discount_real == Decimal("0.5000")


def test_agotado_no_se_publica():
    assert check(50000, in_stock=False).reject_reason == REJECT_STOCK


def test_sin_historia_suficiente_no_hay_señal():
    corta = baseline(n_points=10, n_days=5)
    assert check(50000, base=corta).reject_reason == REJECT_HISTORY


def test_rampa_bloquea_el_descuento_fantasma():
    """Subió 20% tres semanas antes y ahora 'descuenta': es el mismo precio."""
    assert check(50000, base=baseline(ramp=True)).reject_reason == REJECT_RAMP


def test_descuento_bajo_el_umbral_de_categoria_es_ruido():
    assert check(90000).reject_reason == REJECT_THRESHOLD


def test_el_umbral_es_por_categoria():
    """35% para moda, 15% para tecno: el mismo precio decide distinto."""
    assert check(80000, threshold=Decimal("0.15")).accepted
    assert check(80000, threshold=Decimal("0.35")).reject_reason == REJECT_THRESHOLD


def test_precio_sobre_el_piso_habitual_no_es_noticia():
    """20% de descuento pero por encima del p10: ese precio ya se vio varias veces."""
    assert check(80000, base=baseline(p10=75000)).reject_reason == REJECT_ABOVE_FLOOR


def test_cooldown_evita_republicar_el_mismo_producto():
    reciente = PriorPost(NOW - timedelta(days=3), Decimal(70000))
    assert check(70000, prior=reciente).reject_reason == REJECT_COOLDOWN


def test_cooldown_cede_si_el_precio_bajo_de_verdad():
    reciente = PriorPost(NOW - timedelta(days=3), Decimal(70000))
    assert check(60000, prior=reciente).accepted


def test_cooldown_vencido_no_bloquea():
    viejo = PriorPost(NOW - timedelta(days=COOLDOWN_DAYS + 1), Decimal(70000))
    assert check(70000, prior=viejo).accepted


def test_orden_de_guardas_registra_la_causa_mas_fundamental():
    """Agotado Y sin historia Y con rampa: se registra el stock."""
    decision = check(50000, base=baseline(n_points=1, n_days=1, ramp=True), in_stock=False)
    assert decision.reject_reason == REJECT_STOCK


def test_el_rechazado_igual_trae_su_descuento_calculado():
    """Es el dataset de calibración: sin el número no sirve de nada."""
    decision = check(90000)
    assert not decision.accepted
    assert decision.discount_real == Decimal("0.1000")
    assert decision.score is None


def test_score_premia_romper_el_piso_historico():
    """Dos ofertas del mismo %, gana la que se mete más abajo del p10."""
    normal = check(70000, base=baseline(p10=85000))
    rompe_piso = check(70000, base=baseline(p10=100000))
    assert rompe_piso.score > normal.score


def test_solo_el_rechazo_por_historia_queda_sin_persistir():
    """En cold-start son ~10.800 filas por corrida que no calibran nada.

    Los rechazos que SÍ discriminan (rampa, umbral, piso, cooldown) tienen que
    guardarse: son el dataset con el que se mueven los umbrales sin adivinar.
    """
    assert UNPERSISTED_REJECTS == {REJECT_HISTORY}
    for reason in (REJECT_RAMP, REJECT_THRESHOLD, REJECT_ABOVE_FLOOR, REJECT_COOLDOWN):
        assert reason not in UNPERSISTED_REJECTS


@pytest.mark.parametrize("p50", [Decimal(0)])
def test_p50_en_cero_no_divide_por_cero(p50):
    decision = check(1000, base=baseline(p50=p50, p10=0))
    assert decision.discount_real == Decimal(0)
    assert not decision.accepted
