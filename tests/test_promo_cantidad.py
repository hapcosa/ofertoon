"""La promoción de multicompra: del adaptador al mensaje.

Decisión del dueño del 2026-11-05: **las promociones de más de un producto van al
canal, y el mensaje tiene que dejar claro que el ahorro es por cantidad y no una
rebaja por unidad.**

El dato que obliga a todo esto, medido sobre las 107 promociones de multicompra
de una raíz de Unimarc: **en las 107 el precio unitario publicado es igual al de
lista**. O sea no hay descuento comprando una, y el ahorro de 13-20% existe solo
comprando N. Dos consecuencias, y los tests de acá cubren las dos:

1. Con el numerador sin condición, `discount_real ≈ 0` y **ninguna** sería nunca
   candidato. Por eso `evaluate` compara `promo.unitario`.
2. Publicar ese porcentaje sin la condición sería anunciar una rebaja que no
   existe. Por eso la línea del formatter **no es opcional**.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from curation.ranker import Candidate
from pricing.baselines import Baseline
from pricing.detector import PriorPost, evaluate
from publisher.formatter import condition_line, format_deal, promo_line
from scrapers.base import PromoCantidad

NOW = datetime(2026, 11, 5, 12, 0, tzinfo=timezone.utc)


def baseline(p50="300", p10="290", min60="280", n=40):
    return Baseline(
        p50=Decimal(p50), p10=Decimal(p10), minimum=Decimal(min60),
        n_points=n, n_days=n, ramp_flag=False,
    )


#: El caso real: yoghurt Colun, $300 la unidad, promo 4 x $1.000 ($250/u).
PROMO = PromoCantidad(qty=4, total=Decimal("1000"), label="4 x $1.000")


# --- el detector --------------------------------------------------------


def test_sin_promo_el_precio_unitario_no_da_senal():
    """El caso de las 107: unitario == lista, así que no hay descuento."""
    d = evaluate(
        price=Decimal("300"), in_stock=True, baseline=baseline(),
        threshold=Decimal("0.25"), now=NOW,
    )
    assert d.discount_real == Decimal("0.0000")
    assert not d.accepted
    assert d.por_cantidad is False


def test_con_promo_el_numerador_es_el_unitario_de_la_promo():
    """$250 contra un p50 de $300 son 16,67%."""
    d = evaluate(
        price=Decimal("300"), in_stock=True, baseline=baseline(),
        threshold=Decimal("0.10"), now=NOW, promo=PROMO,
    )
    assert d.discount_real == Decimal("0.1667")
    assert d.accepted
    assert d.por_cantidad is True


def test_el_precio_de_la_serie_no_cambia_el_resultado():
    """`price` sigue siendo el unitario sin condición y alimenta la serie.

    Lo que decide el descuento es `promo.unitario`, así que mover `price` sin
    mover la promo no cambia el veredicto — que es justo lo que queremos: la
    baseline se construye con precios comparables entre sí.
    """
    a = evaluate(price=Decimal("300"), in_stock=True, baseline=baseline(),
                 threshold=Decimal("0.10"), now=NOW, promo=PROMO)
    b = evaluate(price=Decimal("999"), in_stock=True, baseline=baseline(),
                 threshold=Decimal("0.10"), now=NOW, promo=PROMO)
    assert a.discount_real == b.discount_real


def test_la_promo_tambien_rige_el_piso():
    """Si el ahorro se anuncia por unidad bajo promo, el p10 juzga ese número.

    Con p10 = $240 el unitario de promo ($250) queda POR ENCIMA del piso: el
    precio ya se vio varias veces en dos meses y no es noticia.
    """
    d = evaluate(
        price=Decimal("300"), in_stock=True,
        baseline=baseline(p50="300", p10="240", min60="230"),
        threshold=Decimal("0.10"), now=NOW, promo=PROMO,
    )
    assert d.reject_reason == "above_floor"
    assert d.por_cantidad is True, "un rechazo también declara la condición"


def test_la_promo_tambien_rige_el_cooldown():
    anterior = PriorPost(posted_at=NOW - timedelta(days=1), price=Decimal("200"))
    d = evaluate(
        price=Decimal("300"), in_stock=True, baseline=baseline(),
        threshold=Decimal("0.10"), now=NOW, promo=PROMO, prior_post=anterior,
    )
    assert d.reject_reason == "cooldown"


def test_el_umbral_sigue_siendo_el_de_la_categoria():
    """Decisión del dueño: mismo pool, mismo θ. 16,67% no pasa un θ de 0,25."""
    d = evaluate(
        price=Decimal("300"), in_stock=True, baseline=baseline(),
        threshold=Decimal("0.25"), now=NOW, promo=PROMO,
    )
    assert d.reject_reason == "threshold"
    assert d.discount_real == Decimal("0.1667")


# --- `PromoCantidad` ----------------------------------------------------


def test_el_unitario_no_se_redondea():
    """`4 x $1.150` da 287,5. Redondear cambiaría el descuento publicado."""
    p = PromoCantidad(qty=4, total=Decimal("1150"), label="4 x $1.150")
    assert p.unitario == Decimal("287.5")


@pytest.mark.parametrize(
    "kwargs",
    [
        dict(qty=1, total=Decimal("1000"), label="1 x $1.000"),   # no es multicompra
        dict(qty=4, total=Decimal("0"), label="4 x $0"),
        dict(qty=4, total=Decimal("-1"), label="x"),
        dict(qty=4, total=Decimal("1000"), label=""),             # sin condición legible
        dict(qty=4, total=Decimal("1000"), label="x" * 49),
    ],
)
def test_lo_que_no_es_una_promo_valida(kwargs):
    with pytest.raises(ValueError):
        PromoCantidad(**kwargs)


def test_los_tres_campos_son_enteros_o_texto_nunca_el_unitario():
    """Lo que se persiste son `qty` y `total`; el unitario es derivado.

    Es la misma naturaleza que el `pum`: una normalización para comparar, no un
    precio que alguien pague. La regla 3 (CLP entero) se cumple en la capa de
    datos.
    """
    p = PromoCantidad(qty=3, total=Decimal("1000"), label="3 x $1.000")
    assert p.total == p.total.to_integral_value()
    assert isinstance(p.qty, int)


# --- el copy ------------------------------------------------------------


def candidato(**kw):
    base = dict(
        candidate_id=1, listing_id=1, store_id=1, store_name="Unimarc",
        category_id=1, category_name="Supermercado",
        name="Yoghurt Colun frutilla 125 g", url="https://www.unimarc.cl/product/x",
        price=Decimal("300"), p50=Decimal("300"),
        discount_real=Decimal("0.1667"), score=Decimal("16.67"), detected_at=NOW,
    )
    base.update(kw)
    return Candidate(**base)


def test_la_linea_de_promo_dice_la_condicion_y_que_la_unidad_no_baja():
    linea = promo_line(
        candidato(promo_qty=4, promo_total=Decimal("1000"), promo_label="4 x $1.000")
    )
    assert "4 x $1.000" in linea
    assert "cantidad" in linea.lower()
    assert "no baja" in linea.lower()


def test_sin_promo_no_hay_linea():
    assert promo_line(candidato()) is None


def test_la_condicion_sale_en_el_mensaje_y_antes_de_la_evidencia():
    """Una condición que se lee al final ya se leyó tarde."""
    msg = format_deal(
        candidato(promo_qty=4, promo_total=Decimal("1000"), promo_label="4 x $1.000",
                  category_slug="supermercado")
    )
    assert "4 x $1.000" in msg
    i_promo = msg.index("4 x $1.000")
    i_link = msg.index("Ver oferta")
    assert i_promo < i_link
    # y el porcentaje del encabezado sigue estando: lo que cambia es que ahora
    # está calificado. 0,1667 se muestra redondeado a 17%.
    assert "17%" in msg.split("\n")[0]


def test_la_etiqueta_va_escapada():
    linea = promo_line(
        candidato(promo_qty=2, promo_total=Decimal("1000"), promo_label="2 x <b>$1k</b>")
    )
    assert "<b>$1k</b>" not in linea
    assert "&lt;b&gt;" in linea


# --- la condición del precio (Club Unimarc) -----------------------------
#
# Decisión del dueño del 2026-11-05: el precio Club cuenta como oferta porque ser
# Club es solo dar el RUT. Por eso es `price_effective` y no `price_card`. Lo que
# no se puede es publicar el porcentaje sin decir que hay que ser Club: quien
# llega a la caja sin RUT paga el precio de lista, y entonces el mensaje mintió.
# Es la misma lógica que `promo_line` y por eso vive en el mismo archivo.


def test_la_condicion_del_precio_sale_verbatim():
    linea = condition_line(candidato(price_condition="Club Unimarc"))
    assert "Club Unimarc" in linea


def test_sin_condicion_no_hay_linea():
    """Casi todo el catálogo del sistema no tiene condición: escribir una donde
    no hay es tan malo como callar la que hay."""
    assert condition_line(candidato()) is None
    assert condition_line(candidato(price_condition="")) is None


def test_la_condicion_del_precio_va_escapada():
    linea = condition_line(candidato(price_condition="Club <b>X</b>"))
    assert "<b>X</b>" not in linea and "&lt;b&gt;" in linea


def test_la_condicion_aparece_en_el_mensaje_antes_del_link():
    msg = format_deal(candidato(price_condition="Club Unimarc", category_slug="supermercado"))
    assert "Club Unimarc" in msg
    assert msg.index("Club Unimarc") < msg.index("Ver oferta")


def test_promo_y_condicion_conviven_y_son_cosas_distintas():
    """`4 x $1.150` es el ahorro por cantidad; `Club Unimarc` es quién puede
    pagarlo. En los 626 casos medidos el 2026-11-06 las dos vienen juntas, y el
    mensaje tiene que decir las dos: una promo que exige RUT y no lo declara es
    tan falsa como un porcentaje sin la condición de cantidad."""
    msg = format_deal(
        candidato(promo_qty=4, promo_total=Decimal("1150"), promo_label="4 x $1.150",
                  price_condition="Club Unimarc", category_slug="supermercado")
    )
    assert "4 x $1.150" in msg and "Club Unimarc" in msg
    assert msg.index("4 x $1.150") < msg.index("Club Unimarc") < msg.index("Ver oferta")
