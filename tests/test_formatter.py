"""El mensaje del canal. Es producto, así que se testea como contrato.

El test que más importa es `test_el_precio_tachado_es_el_p50_no_el_de_la_tienda`:
si eso se rompe, el canal pasa a ser una cuenta más que reenvía el banner de la
tienda y el proyecto entero pierde su razón de existir.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from curation.ranker import Candidate
from publisher import formatter

NOW = datetime(2026, 8, 4, 15, 0, tzinfo=timezone.utc)


def make(**overrides) -> Candidate:
    base = dict(
        candidate_id=1,
        listing_id=42,
        store_id=1,
        store_name="Falabella",
        category_id=1,
        category_name="Notebooks",
        name="Lenovo IdeaPad Slim 3 15IAH8 i5-12450H 16GB 512GB",
        url="https://falabella.com/p/12345",
        price=Decimal("399990"),
        p50=Decimal("649990"),
        discount_real=Decimal("0.3846"),
        score=Decimal("42.5"),
        detected_at=NOW - timedelta(hours=1),
        p10=Decimal("450000"),
        min_prior=Decimal("420000"),
    )
    base.update(overrides)
    return Candidate(**base)


# -----------------------------------------------------------------------------
# Formato de números
# -----------------------------------------------------------------------------


@pytest.mark.parametrize(
    "value,expected",
    [
        ("399990.00", "$399.990"),
        ("1290000", "$1.290.000"),
        ("9990", "$9.990"),
        ("999", "$999"),
        ("12345678", "$12.345.678"),
    ],
)
def test_format_clp(value: str, expected: str) -> None:
    assert formatter.format_clp(Decimal(value)) == expected


def test_format_clp_no_muestra_centavos() -> None:
    """Los precios chilenos son enteros; un centavo delata la columna NUMERIC."""
    assert formatter.format_clp(Decimal("399990.49")) == "$399.990"
    assert formatter.format_clp(Decimal("399990.50")) == "$399.991"


@pytest.mark.parametrize(
    "value,expected", [("0.3846", "−38%"), ("0.15", "−15%"), ("0.5", "−50%")]
)
def test_format_discount(value: str, expected: str) -> None:
    assert formatter.format_discount(Decimal(value)) == expected


def test_el_signo_menos_es_u2212_no_guion() -> None:
    """Detalle tipográfico deliberado: el guion ASCII se ve angosto al lado del %."""
    assert formatter.format_discount(Decimal("0.20")).startswith("−")


# -----------------------------------------------------------------------------
# La línea de evidencia
# -----------------------------------------------------------------------------


def test_minimo_historico_cuando_el_precio_rompe_el_piso_previo() -> None:
    candidate = make(price=Decimal("400000"), min_prior=Decimal("420000"))
    assert formatter.evidence_line(candidate) == "🏆 El más barato en 60 días"


def test_fallback_cuando_no_es_el_minimo() -> None:
    candidate = make(price=Decimal("430000"), min_prior=Decimal("420000"))
    assert "piso habitual" in formatter.evidence_line(candidate)


def test_sin_min_prior_no_afirma_lo_que_no_sabe() -> None:
    """Sin historia previa no se puede decir "el más barato": se degrada."""
    candidate = make(min_prior=None)
    assert "piso habitual" in formatter.evidence_line(candidate)


def test_empatar_el_minimo_previo_cuenta_como_el_mas_barato() -> None:
    candidate = make(price=Decimal("420000"), min_prior=Decimal("420000"))
    assert formatter.evidence_line(candidate) == "🏆 El más barato en 60 días"


# -----------------------------------------------------------------------------
# El mensaje
# -----------------------------------------------------------------------------


def test_mensaje_completo() -> None:
    assert formatter.format_deal(make()) == (
        "🔥 <b>−38%</b> · Notebooks\n"
        "\n"
        "<b>Lenovo IdeaPad Slim 3 15IAH8 i5-12450H 16GB 512GB</b>\n"
        "Falabella\n"
        "\n"
        "<b>$399.990</b>  ·  antes real <s>$649.990</s>\n"
        "🏆 El más barato en 60 días\n"
        "\n"
        '<a href="https://falabella.com/p/12345">Ver oferta →</a>\n'
        "\n"
        "<i>«antes real» = precio mediano de este producto en los últimos "
        "60 días, medido por nosotros. No es el precio tachado que declara "
        "la tienda.</i>"
    )


def test_el_precio_tachado_es_el_p50_no_el_de_la_tienda() -> None:
    """LA prueba del producto.

    `price_normal` —el "antes" que declara la tienda— no está ni siquiera
    disponible en `Candidate`, y eso es a propósito: es el número que el
    proyecto existe para desmentir. Lo tachado es el p50 medido por nosotros.
    """
    message = formatter.format_deal(make(p50=Decimal("649990")))
    assert "antes real <s>$649.990</s>" in message
    assert not hasattr(make(), "price_normal")


def test_el_pie_explica_de_donde_sale_el_numero() -> None:
    """El diferencial no puede depender de que alguien leyó la bio del canal."""
    message = formatter.format_deal(make())
    assert "medido por nosotros" in message
    assert "No es el precio tachado que declara la tienda" in message


def test_escapa_html_del_nombre_del_producto() -> None:
    """Un `&` sin escapar rompe el parseo y Telegram rechaza el mensaje entero."""
    message = formatter.format_deal(make(name='Monitor 27" <AOC> & LG'))
    assert "&lt;AOC&gt; &amp; LG" in message
    assert "<AOC>" not in message


def test_escapa_la_url_en_el_atributo() -> None:
    message = formatter.format_deal(make(url='https://x.cl/p?a=1&b="2"'))
    assert 'href="https://x.cl/p?a=1&amp;b=&quot;2&quot;"' in message


def test_trunca_el_nombre_largo() -> None:
    largo = "Notebook " + "X" * 300
    message = formatter.format_deal(make(name=largo))
    assert "…</b>" in message
    assert len(message) < 700


def test_truncate_no_toca_lo_corto() -> None:
    assert formatter.truncate("Notebook Lenovo") == "Notebook Lenovo"


def test_truncate_normaliza_espacios() -> None:
    """Los nombres de Sodimac vienen con saltos de línea y espacios dobles."""
    assert formatter.truncate("Taladro\n\n  Bosch   GSB") == "Taladro Bosch GSB"


def test_sin_categoria_no_deja_hueco() -> None:
    message = formatter.format_deal(make(category_name=None))
    assert "· Ofertas" in message


def test_no_muestra_precio_con_tarjeta() -> None:
    """El canal promete el precio que paga cualquiera, sin tarjeta de la casa."""
    assert not hasattr(make(), "price_card")


def test_deal_url_es_el_unico_punto_de_extension_para_afiliados() -> None:
    candidate = make(url="https://falabella.com/p/12345")
    assert formatter.deal_url(candidate) == "https://falabella.com/p/12345"
