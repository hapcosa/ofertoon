"""El backtest: distinguir el pozo temporal del escalón permanente.

Es la única forma de saber si el detector sirve antes de publicarle nada a
nadie, y de dónde sale el θ de cada categoría.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from pricing.backtest import (
    LABEL_FAKE,
    LABEL_REAL,
    LABEL_UNKNOWN,
    LABEL_WINDOW_DAYS,
    Signal,
    format_report,
    label_outcome,
    replay_listing,
    summarize,
)
from pricing.detector import COOLDOWN_DAYS

START = date(2026, 6, 1)


def puntos(precio_por_dia, *, dias, desde=START, stock=True):
    """Serie de 2 obs/día hacia adelante desde `desde`."""
    salida = []
    for offset in range(dias):
        momento = datetime.combine(
            desde + timedelta(days=offset),
            datetime.min.time(),
            tzinfo=timezone.utc,
        )
        precio = Decimal(str(precio_por_dia(offset)))
        salida.append((momento.replace(hour=9), precio, stock))
        salida.append((momento.replace(hour=20), precio, stock))
    return salida


# -----------------------------------------------------------------------------
# Etiquetado
# -----------------------------------------------------------------------------


def test_pozo_temporal_es_oferta_real():
    """El precio vuelve a subir: el descuento era de verdad."""
    dia = date(2026, 7, 1)
    futuro = puntos(lambda d: 100000, dias=40, desde=dia + timedelta(days=1))
    assert (
        label_outcome(
            Decimal(70000), futuro, day=dia, series_end=futuro[-1][0]
        )
        == LABEL_REAL
    )


def test_escalon_permanente_es_oferta_falsa():
    """El 'descuento' se quedó: era el precio nuevo con otro nombre."""
    dia = date(2026, 7, 1)
    futuro = puntos(lambda d: 70000, dias=40, desde=dia + timedelta(days=1))
    assert (
        label_outcome(
            Decimal(70000), futuro, day=dia, series_end=futuro[-1][0]
        )
        == LABEL_FAKE
    )


def test_senal_sin_ventana_completa_queda_sin_etiquetar():
    """Contarla como acierto o como error sesgaría las señales más recientes."""
    dia = date(2026, 7, 1)
    futuro = puntos(lambda d: 100000, dias=5, desde=dia + timedelta(days=1))
    assert (
        label_outcome(Decimal(70000), futuro, day=dia, series_end=futuro[-1][0])
        == LABEL_UNKNOWN
    )


def test_recuperacion_menor_al_10_por_ciento_no_alcanza():
    dia = date(2026, 7, 1)
    futuro = puntos(lambda d: 74000, dias=40, desde=dia + timedelta(days=1))
    assert (
        label_outcome(Decimal(70000), futuro, day=dia, series_end=futuro[-1][0])
        == LABEL_FAKE
    )


# -----------------------------------------------------------------------------
# Replay
# -----------------------------------------------------------------------------


def test_replay_no_mira_el_futuro():
    """Un producto que baja el día 45 no puede generar señal el día 10.

    Si la baseline usara la serie entera, el precio bajo del final arrastraría
    el p50 y cambiaría lo que el detector "habría visto" en junio.
    """
    serie = puntos(lambda d: 100000 if d < 45 else 60000, dias=70)
    signals = replay_listing(
        serie,
        listing_id=1,
        category_slug="tecno",
        threshold=Decimal("0.15"),
        start=START,
        end=START + timedelta(days=20),
    )
    assert signals == []


def test_replay_emite_la_señal_el_dia_de_la_bajada():
    serie = puntos(lambda d: 100000 if d != 50 else 60000, dias=70)
    signals = replay_listing(
        serie,
        listing_id=1,
        category_slug="tecno",
        threshold=Decimal("0.15"),
        start=START,
        end=START + timedelta(days=69),
    )
    assert [s.day for s in signals] == [START + timedelta(days=50)]
    assert signals[0].discount_real >= Decimal("0.39")


def test_replay_respeta_el_cooldown():
    """Una baja sostenida no puede generar una señal por día durante un mes.

    A los 21 días el cooldown vence y el listing puede volver a señalar — eso
    es lo que el detector hace en producción, y el etiquetado +30d se encarga
    de marcar esa segunda señal como falsa si el precio nunca se recuperó.
    """
    serie = puntos(lambda d: 100000 if d < 50 else 60000, dias=90)
    signals = replay_listing(
        serie,
        listing_id=1,
        category_slug="tecno",
        threshold=Decimal("0.15"),
        start=START,
        end=START + timedelta(days=89),
    )
    assert len(signals) == 2
    assert (signals[1].day - signals[0].day).days >= COOLDOWN_DAYS
    # El precio nunca se recuperó: era un escalón, y así queda etiquetado.
    assert signals[0].label == LABEL_FAKE


def test_umbral_mas_alto_emite_menos_señales():
    serie = puntos(lambda d: 100000 if d != 50 else 78000, dias=70)
    args = dict(listing_id=1, category_slug="tecno", start=START, end=START + timedelta(days=69))
    flojo = replay_listing(serie, threshold=Decimal("0.15"), **args)
    estricto = replay_listing(serie, threshold=Decimal("0.35"), **args)
    assert len(flojo) == 1 and len(estricto) == 0


def test_serie_vacia_no_rompe():
    assert replay_listing([], listing_id=1, category_slug="x",
                          threshold=Decimal("0.2"), start=START, end=START) == []


# -----------------------------------------------------------------------------
# Métricas
# -----------------------------------------------------------------------------


def señal(label, categoria="tecno", theta=Decimal("0.20")):
    return Signal(
        day=START,
        listing_id=1,
        category_slug=categoria,
        threshold=theta,
        price=Decimal(1000),
        discount_real=Decimal("0.3"),
        label=label,
    )


def test_precision_ignora_las_no_maduradas():
    metrics = summarize(
        [señal(LABEL_REAL)] * 8 + [señal(LABEL_FAKE)] * 2 + [señal(LABEL_UNKNOWN)] * 5,
        days=10,
    )
    assert len(metrics) == 1
    assert metrics[0].precision == 0.8
    assert metrics[0].per_day == 1.5


def test_sin_señales_maduras_la_precision_es_desconocida_no_cero():
    metrics = summarize([señal(LABEL_UNKNOWN)] * 3, days=3)
    assert metrics[0].precision is None
    assert not metrics[0].meets_gate


def test_gate_de_f1_exige_precision_y_volumen():
    """≥80% de precisión CON ≥3 señales/día. Una sola no alcanza."""
    preciso_pero_flaco = summarize([señal(LABEL_REAL)] * 9 + [señal(LABEL_FAKE)], days=10)
    assert preciso_pero_flaco[0].precision == 0.9
    assert not preciso_pero_flaco[0].meets_gate  # 1 señal/día

    completo = summarize([señal(LABEL_REAL)] * 36 + [señal(LABEL_FAKE)] * 4, days=10)
    assert completo[0].meets_gate


def test_las_metricas_se_separan_por_categoria_y_umbral():
    metrics = summarize(
        [
            señal(LABEL_REAL, "tecno", Decimal("0.15")),
            señal(LABEL_FAKE, "tecno", Decimal("0.30")),
            señal(LABEL_REAL, "ferre", Decimal("0.15")),
        ],
        days=1,
    )
    assert len(metrics) == 3
    assert [(m.category_slug, float(m.threshold)) for m in metrics] == [
        ("ferre", 0.15),
        ("tecno", 0.15),
        ("tecno", 0.30),
    ]


def test_reporte_vacio_lo_dice_en_vez_de_imprimir_una_tabla_vacia():
    assert "sin señales" in format_report([])


def test_reporte_marca_las_filas_que_pasan_el_gate():
    metrics = summarize([señal(LABEL_REAL)] * 36 + [señal(LABEL_FAKE)] * 4, days=10)
    reporte = format_report(metrics)
    assert "90.0%" in reporte and "✓" in reporte


def test_ventana_de_etiquetado_es_la_del_plan():
    assert LABEL_WINDOW_DAYS == 30
