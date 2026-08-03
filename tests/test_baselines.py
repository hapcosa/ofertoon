"""La baseline: el precio de verdad del SKU y la firma del inflado."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from pricing.baselines import (
    MIN_DAYS,
    MIN_POINTS,
    RAMP_MIN_DAYS,
    Baseline,
    compute_baseline,
    daily_minimums,
    percentile,
)

NOW = datetime(2026, 9, 15, 20, 0, tzinfo=timezone.utc)


def serie(precios_por_dia, *, dias=60, stock=True, now=NOW):
    """Serie de 2 observaciones/día hacia atrás desde `now`.

    `precios_por_dia` es una función `dias_atras -> precio`.
    """
    puntos = []
    for atras in range(dias):
        momento = now - timedelta(days=atras)
        precio = Decimal(str(precios_por_dia(atras)))
        puntos.append((momento.replace(hour=9), precio, stock))
        puntos.append((momento.replace(hour=20), precio, stock))
    return puntos


def test_percentil_interpola_sin_pasar_por_float():
    valores = [Decimal(10), Decimal(20)]
    assert percentile(valores, 0.5) == Decimal(15)
    assert percentile([Decimal(1), Decimal(2), Decimal(3)], 0.5) == Decimal(2)
    assert percentile([Decimal(7)], 0.1) == Decimal(7)


def test_p50_es_el_precio_habitual_no_el_declarado():
    baseline = compute_baseline(serie(lambda d: 100000 if d else 60000), now=NOW)
    assert baseline.p50 == Decimal(100000)
    assert baseline.minimum == Decimal(60000)


def test_sin_stock_no_entra_en_la_baseline():
    """Un agotado queda con precio congelado; arrastraría el p50 a donde nadie compró."""
    con_stock = serie(lambda d: 100000)
    sin_stock = [(NOW - timedelta(days=1), Decimal(500000), False)]
    baseline = compute_baseline(con_stock + sin_stock, now=NOW)
    assert baseline.p50 == Decimal(100000)
    assert baseline.n_points == len(con_stock)


def test_serie_vacia_o_toda_sin_stock_no_da_baseline():
    assert compute_baseline([], now=NOW) is None
    assert compute_baseline([(NOW, Decimal(1000), False)], now=NOW) is None


def test_observaciones_fuera_de_la_ventana_se_ignoran():
    viejo = [(NOW - timedelta(days=90), Decimal(999999), True)]
    baseline = compute_baseline(serie(lambda d: 100000) + viejo, now=NOW)
    assert baseline.minimum == Decimal(100000)


def test_historia_insuficiente_se_marca_como_no_publicable():
    corta = serie(lambda d: 100000, dias=10)
    baseline = compute_baseline(corta, now=NOW)
    assert baseline is not None
    assert baseline.n_days == 10
    assert not baseline.has_min_history

    larga = compute_baseline(serie(lambda d: 100000, dias=MIN_DAYS), now=NOW)
    assert larga.n_points >= MIN_POINTS and larga.has_min_history


def test_dos_muestras_por_dia_colapsan_al_minimo():
    puntos = [
        (NOW.replace(hour=9), Decimal(100000)),
        (NOW.replace(hour=20), Decimal(80000)),
    ]
    assert daily_minimums(puntos) == [(NOW.date(), Decimal(80000))]


def test_rampa_detecta_el_alza_sostenida_previa():
    """El patrón: precio normal, sube 20% por una semana, después 'descuento'."""

    def precio(atras):
        if 5 <= atras <= 15:  # dentro de d−21..d−3
            return 120000
        return 100000

    baseline = compute_baseline(serie(precio), now=NOW)
    assert baseline.ramp_flag


def test_alza_de_un_par_de_dias_no_es_rampa():
    def precio(atras):
        if 6 <= atras < 6 + RAMP_MIN_DAYS - 2:
            return 120000
        return 100000

    assert not compute_baseline(serie(precio), now=NOW).ramp_flag


def test_alza_menor_al_15_por_ciento_no_es_rampa():
    def precio(atras):
        return 110000 if 5 <= atras <= 15 else 100000

    assert not compute_baseline(serie(precio), now=NOW).ramp_flag


def test_alza_pegada_a_hoy_no_cuenta_como_rampa():
    """d−3 en adelante se excluye para no leer la propia bajada como escalón."""

    def precio(atras):
        return 120000 if atras <= 2 else 100000

    assert not compute_baseline(serie(precio), now=NOW).ramp_flag


def test_un_hueco_de_datos_no_borra_la_rampa():
    """Una pasada que falló no puede hacer desaparecer la evidencia del inflado."""
    puntos = [
        p
        for p in serie(lambda d: 120000 if 5 <= d <= 15 else 100000)
        # se cae el día 10 entero, en medio de la rampa
        if (NOW - p[0]).days != 10
    ]
    assert compute_baseline(puntos, now=NOW).ramp_flag


def test_un_dia_barato_en_medio_si_corta_la_racha():
    """Sin el corte serían 8 días caros; con él quedan dos rachas de 3 y 4."""

    def precio(atras):
        if atras == 8:
            return 100000
        return 120000 if 5 <= atras <= 12 else 100000

    assert not compute_baseline(serie(precio), now=NOW).ramp_flag
    # La misma serie sin el día barato sí es rampa: el corte es lo que decide.
    assert compute_baseline(
        serie(lambda d: 120000 if 5 <= d <= 12 else 100000), now=NOW
    ).ramp_flag


def test_baseline_es_inmutable():
    baseline = Baseline(
        p50=Decimal(1), p10=Decimal(1), minimum=Decimal(1),
        n_points=1, n_days=1, ramp_flag=False,
    )
    assert not baseline.has_min_history
