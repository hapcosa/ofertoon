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


# -----------------------------------------------------------------------------
# El precio por unidad de medida: solo en supermercado
# -----------------------------------------------------------------------------


def super_candidate(**overrides) -> Candidate:
    """Una oferta de supermercado con `pum`, con los números del fixture real.

    $3.890 el producto, $3.242 el kilo → 1,2 kg. El p50 de $5.550 llevado a la
    misma base da $4.625: es el "antes real" por kilo.
    """
    base = dict(
        category_id=9,
        category_name="Supermercado",
        category_slug="supermercado",
        name="Detergente Líquido Soft Floral 1,2 kg",
        store_name="Tottus",
        price=Decimal("3890"),
        p50=Decimal("5550"),
        discount_real=Decimal("0.2991"),
        p10=Decimal("4190"),
        min_prior=Decimal("4190"),
        pum_price=Decimal("3242"),
        pum_label="KG",
    )
    base.update(overrides)
    return make(**base)


def test_la_linea_del_pum_muestra_el_precio_por_unidad_y_su_antes() -> None:
    """Lo que convierte "−30%" en una decisión de stockear (PLAN_SUPERMERCADO §2).

    La etiqueta va **tal como la manda la tienda**: traducir `KG` a "kilo" obliga
    a decidir qué son `MR` y `MT`, y una unidad mal traducida miente sobre la
    mitad del dato.
    """
    assert formatter.pum_line(super_candidate()) == (
        "📦 $3.242 por KG  ·  antes real $4.625"
    )


def test_el_antes_por_unidad_es_el_p50_llevado_a_la_misma_base() -> None:
    """Se deriva, no se guarda: `pum/price` es `1/tamaño`, así que `p50 × eso`
    es el p50 por unidad. Sin segunda baseline que pueda divergir."""
    candidate = super_candidate(price=Decimal("1000"), p50=Decimal("2000"),
                                pum_price=Decimal("500"), pum_label="LT")
    # 1.000 por 2 L → el p50 de 2.000 son 1.000 el litro.
    assert formatter.pum_habitual(candidate) == Decimal("1000")


def test_fuera_de_supermercado_no_sale_aunque_la_tienda_lo_declare() -> None:
    """El precio por metro de un cable no es el argumento de compra del canal."""
    cable = super_candidate(category_slug="tecno-componentes", pum_label="MT",
                            pum_price=Decimal("37"))
    assert formatter.pum_line(cable) is None
    assert "📦" not in formatter.format_deal(cable)


def test_sin_pum_la_oferta_de_supermercado_se_publica_igual() -> None:
    """Es el 5% del catálogo: que falte el dato NO puede frenar una oferta."""
    sin_pum = super_candidate(pum_price=None, pum_label=None)
    assert formatter.pum_line(sin_pum) is None
    message = formatter.format_deal(sin_pum)
    assert "<b>$3.890</b>" in message
    assert "📦" not in message


def test_un_pum_a_medias_tampoco_frena_el_mensaje() -> None:
    """La etiqueta es la mitad del dato: sin ella el número no se puede mostrar.

    El CHECK de la migración 34 hace que esta fila no exista en la base; la guarda
    está igual porque el formatter no puede confiar en eso para no quedarse sin
    mensaje.
    """
    assert formatter.pum_line(super_candidate(pum_label=None)) is None
    assert formatter.pum_line(super_candidate(pum_price=None)) is None


def test_sin_contraste_muestra_el_precio_por_unidad_solo() -> None:
    """Con un pum de pocos pesos el redondeo a CLP entero empata los dos números.

    Caso real del fixture: base `100UN` a $8. "📦 $8 por 100UN · antes real $8"
    no dice nada, así que sale solo la mitad que sí dice algo.
    """
    pilas = super_candidate(
        price=Decimal("1190"), p50=Decimal("1200"),
        pum_price=Decimal("8"), pum_label="100UN",
    )
    assert formatter.pum_habitual(pilas) == Decimal("8")
    assert formatter.pum_line(pilas) == "📦 $8 por 100UN"


def test_escapa_la_etiqueta_de_la_unidad() -> None:
    """Viene de la tienda: un `&` sin escapar hace que Telegram rechace todo."""
    raro = super_candidate(pum_label="KG & LT")
    assert "KG &amp; LT" in formatter.pum_line(raro)


def test_mensaje_completo_de_supermercado() -> None:
    assert formatter.format_deal(super_candidate()) == (
        "🔥 <b>−30%</b> · Supermercado\n"
        "\n"
        "<b>Detergente Líquido Soft Floral 1,2 kg</b>\n"
        "Tottus\n"
        "\n"
        "<b>$3.890</b>  ·  antes real <s>$5.550</s>\n"
        "📦 $3.242 por KG  ·  antes real $4.625\n"
        "🏆 El más barato en 60 días\n"
        "\n"
        '<a href="https://falabella.com/p/12345">Ver oferta →</a>\n'
        "\n"
        "<i>«antes real» = precio mediano de este producto en los últimos "
        "60 días, medido por nosotros. No es el precio tachado que declara "
        "la tienda.</i>"
    )


def test_el_pum_no_toca_el_mensaje_del_resto_del_canal() -> None:
    """La línea nueva es aditiva: el contrato del canal general no se movió."""
    assert "📦" not in formatter.format_deal(make())


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
