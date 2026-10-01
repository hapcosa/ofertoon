"""El backtest: distinguir el pozo temporal del escalón permanente.

Es la única forma de saber si el detector sirve antes de publicarle nada a
nadie, y de dónde sale el θ de cada categoría.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from pricing.backtest import (
    DIAS_DEGRADADOS,
    LABEL_FAKE,
    LABEL_LIQUIDATION,
    LABEL_REAL,
    LABEL_UNKNOWN,
    LABEL_WINDOW_DAYS,
    dias_de_mercado,
    Signal,
    format_report,
    label_outcome,
    piso_previo,
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
    # El precio nunca se recuperó. Esta aserción decía `fake` y cambió con la
    # decisión de producto del 2026-10-01: una baja sostenida que **rompe el
    # piso de 60 días** es una liquidación, o sea una oferta real, no un escalón
    # inflado. El escalón inflado vuelve a un nivel que ya existía en la ventana
    # y sigue saliendo `fake` (ver
    # `test_inflado_que_vuelve_a_su_nivel_sigue_siendo_falso`). Lo que este test
    # prueba es el cooldown, y eso no cambió.
    assert signals[0].label == LABEL_LIQUIDATION


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


# -----------------------------------------------------------------------------
# Días degradados: los que no son días de mercado
# -----------------------------------------------------------------------------
# Hay días en que la ingesta corrió a medias, y replayearlos como normales
# miente en la mitad del gate. El 18 y el 19 de septiembre de 2026 no tuvieron
# una sola observación (48 h sin salida a internet, 562 corridas `failed`); el
# 29 tuvo 19.361 puntos contra ~33.000 (DNS a ráfagas + un reboot del host se
# llevaron 62 de 129 objetivos).
#
# El daño no es donde parece. `replay_listing` ya salteaba los días sin
# observaciones, así que un día vacío nunca emitió señales — pero sí contaba en
# el DIVISOR de señales/día. O sea: el numerador pierde las señales y el
# denominador igual cuenta el día. Sobre 30 días con los tres adentro, el
# volumen sale 10% abajo, y el gate de F1 es "≥80% de precisión CON ≥3
# señales/día".


def test_los_dias_degradados_estan_documentados():
    """La lista es conocimiento de dominio: si se pierde, se recalibra contra ruido."""
    assert DIAS_DEGRADADOS == (
        date(2026, 9, 18),
        date(2026, 9, 19),
        date(2026, 9, 29),
    )


def test_el_divisor_descuenta_los_dias_excluidos():
    """Es la mitad del gate: 3 señales/día sobre 10 días no son 3 sobre 8."""
    assert dias_de_mercado(date(2026, 9, 1), date(2026, 9, 30), frozenset()) == 30
    excluidos = frozenset(DIAS_DEGRADADOS)
    assert dias_de_mercado(date(2026, 9, 1), date(2026, 9, 30), excluidos) == 27


def test_un_dia_excluido_de_afuera_del_rango_no_infla_nada():
    """Pasar --exclude-day de otra fecha no puede agrandar el volumen."""
    assert dias_de_mercado(
        date(2026, 8, 1), date(2026, 8, 31), frozenset(DIAS_DEGRADADOS)
    ) == 31


def test_excluir_todo_el_rango_no_da_un_divisor_negativo():
    dia = date(2026, 9, 18)
    assert dias_de_mercado(dia, dia, frozenset([dia])) == 0
    # Y `per_day` no explota con divisor 0.
    assert summarize([señal(LABEL_REAL)], days=0)[0].per_day == 0.0


def test_un_dia_excluido_no_emite_señal():
    """La baja cae justo en el día degradado: no se la cuenta como señal."""
    serie = puntos(lambda d: 100000 if d != 50 else 60000, dias=70)
    dia_de_la_baja = START + timedelta(days=50)
    args = dict(
        listing_id=1,
        category_slug="tecno",
        threshold=Decimal("0.15"),
        start=START,
        end=START + timedelta(days=69),
    )
    assert [s.day for s in replay_listing(serie, **args)] == [dia_de_la_baja]
    assert replay_listing(serie, skip_days=frozenset([dia_de_la_baja]), **args) == []


def test_el_dia_excluido_sigue_alimentando_la_baseline():
    """La regla de dominio que esto NO puede violar.

    `compute_baseline` se recomputa "como se veía el día t" con la misma función
    que corre en producción. Borrarle puntos a la serie sería la segunda
    implementación divergente que esa regla existe para prohibir: lo que un día
    degradado invalida es su derecho a contar como día de mercado, no la
    historia, que es la que hubo.

    Se verifica por el efecto observable: excluir un día TEMPRANO no cambia la
    señal que se emite 50 días después, porque sus puntos siguen en el p50.
    """
    serie = puntos(lambda d: 100000 if d != 50 else 60000, dias=70)
    args = dict(
        listing_id=1,
        category_slug="tecno",
        threshold=Decimal("0.15"),
        start=START,
        end=START + timedelta(days=69),
    )
    sin_excluir = replay_listing(serie, **args)
    con_excluido = replay_listing(serie, skip_days=frozenset([START + timedelta(days=3)]), **args)

    assert [s.day for s in con_excluido] == [s.day for s in sin_excluir]
    assert con_excluido[0].discount_real == sin_excluir[0].discount_real


def test_excluir_un_dia_no_consume_el_cooldown():
    """Una señal que no se emitió no puede silenciar al listing 21 días.

    Si el día excluido marcara `prior`, la próxima señal real quedaría tapada y
    el volumen saldría todavía más abajo — justo lo contrario de lo que esta
    exclusión existe para corregir.
    """
    serie = puntos(lambda d: 100000 if d < 50 else 60000, dias=90)
    args = dict(
        listing_id=1,
        category_slug="tecno",
        threshold=Decimal("0.15"),
        start=START,
        end=START + timedelta(days=89),
    )
    primera = replay_listing(serie, **args)[0].day
    # Excluido el día de la primera señal, la serie sigue baja: el detector
    # señala al día siguiente, no 21 días después.
    con_excluido = replay_listing(serie, skip_days=frozenset([primera]), **args)
    assert con_excluido[0].day == primera + timedelta(days=1)


def test_el_reporte_declara_los_dias_excluidos():
    """Un divisor del gate que se mueve sin decirlo no se puede auditar después."""
    metrics = summarize([señal(LABEL_REAL)] * 36 + [señal(LABEL_FAKE)] * 4, days=10)
    reporte = format_report(metrics, excluidos=[date(2026, 9, 18), date(2026, 9, 29)])
    assert "2 día(s) excluido(s)" in reporte
    assert "2026-09-18" in reporte and "2026-09-29" in reporte
    # Sin exclusiones no se agrega ruido al pie.
    assert "excluido" not in format_report(metrics)


# -----------------------------------------------------------------------------
# Liquidación de temporada: la tercera etiqueta
# -----------------------------------------------------------------------------
# Decisión de producto del 2026-10-01: **la liquidación de temporada es una
# oferta real y va al canal.** El precio baja de verdad; el suscriptor compra
# barato algo que estaba caro.
#
# El detector ya las publicaba —`detect_ramp` exige un alza previa que una
# liquidación no tiene, así que `ramp_flag` queda en False y la oferta se
# acepta—. Lo que estaba mal era la MEDICIÓN: `label_outcome` marcaba `fake`
# todo pozo que se quedaba abajo, y una liquidación se queda abajo. Como θ sale
# del backtest, esa etiqueta equivocada empujaba θ hacia arriba hasta dejar
# afuera justo las mejores ofertas de vestuario y calzado.
#
# El discriminante mira el PASADO, no el futuro, y es dato duro:
#   - inflado-normalizado → vuelve a un nivel que ya existía: price >= min_60d
#   - liquidación         → rompe el piso de 60 días: price < min_60d
#
# Y lo que lo hace defendible: un candidato aceptado ya pasó la guarda 3 del
# detector (`ramp_flag` → `reject_reason='ramp'`), que es la que caza el "subo y
# después descuento". Entre los aceptados, el inflado ya se filtró antes.


def test_liquidacion_se_queda_abajo_pero_es_real():
    """Rompe el piso de 60 días: ese precio no se había visto nunca."""
    dia = date(2026, 7, 1)
    futuro = puntos(lambda d: 70000, dias=40, desde=dia + timedelta(days=1))
    assert (
        label_outcome(
            Decimal(70000),
            futuro,
            day=dia,
            series_end=futuro[-1][0],
            prior_min=Decimal(90000),  # lo más barato en 60 días eran 90.000
        )
        == LABEL_LIQUIDATION
    )


def test_inflado_que_vuelve_a_su_nivel_sigue_siendo_falso():
    """El contraste que hace que la etiqueta nueva signifique algo.

    El precio se quedó abajo igual que la liquidación, pero NO rompió el piso:
    volvió a un nivel que ya existía en la ventana, o sea al precio de antes de
    inflar. Eso es exactamente lo que el canal promete no publicar.
    """
    dia = date(2026, 7, 1)
    futuro = puntos(lambda d: 70000, dias=40, desde=dia + timedelta(days=1))
    assert (
        label_outcome(
            Decimal(70000),
            futuro,
            day=dia,
            series_end=futuro[-1][0],
            prior_min=Decimal(70000),  # ese precio YA se había visto
        )
        == LABEL_FAKE
    )


def test_el_pozo_que_se_recupera_sigue_siendo_real_rompa_o_no_el_piso():
    """La recuperación manda: es la señal más fuerte y se evalúa primero."""
    dia = date(2026, 7, 1)
    futuro = puntos(lambda d: 100000, dias=40, desde=dia + timedelta(days=1))
    assert (
        label_outcome(Decimal(70000), futuro, day=dia, series_end=futuro[-1][0],
                      prior_min=Decimal(90000))
        == LABEL_REAL
    )


def test_sin_piso_el_etiquetado_es_el_binario_de_antes():
    """`prior_min=None` conserva el comportamiento viejo.

    Es lo que mantiene válidos los tests de etiquetado que ya existían y lo que
    deja la función usable sin arrastrar una Baseline entera.
    """
    dia = date(2026, 7, 1)
    futuro = puntos(lambda d: 70000, dias=40, desde=dia + timedelta(days=1))
    assert (
        label_outcome(Decimal(70000), futuro, day=dia, series_end=futuro[-1][0])
        == LABEL_FAKE
    )


def test_la_liquidacion_cuenta_como_acierto_en_la_precision():
    """La decisión de producto, expresada en la métrica que fija θ."""
    metrics = summarize(
        [señal(LABEL_REAL)] * 5 + [señal(LABEL_LIQUIDATION)] * 3 + [señal(LABEL_FAKE)] * 2,
        days=10,
    )
    assert metrics[0].labeled == 10
    assert metrics[0].hits == 8
    assert metrics[0].precision == 0.8


def test_el_reporte_lleva_la_liquidacion_en_columna_propia():
    """No es cosmético: sin la columna no se puede ver de dónde sale la precisión."""
    metrics = summarize(
        [señal(LABEL_REAL)] * 20 + [señal(LABEL_LIQUIDATION)] * 16 + [señal(LABEL_FAKE)] * 4,
        days=10,
    )
    reporte = format_report(metrics)
    assert "liquid." in reporte
    assert metrics[0].meets_gate  # 90% de precisión y 4 señales/día


def test_el_reporte_avisa_cuando_la_precision_se_apoya_en_liquidacion():
    """Un canal cuya precisión es toda liquidación es un outlet, no ofertas.

    Hay que verlo ANTES de fijar θ. No bloquea nada: avisa.
    """
    casi_todo = summarize(
        [señal(LABEL_REAL)] * 2 + [señal(LABEL_LIQUIDATION)] * 30, days=10
    )
    assert casi_todo[0].liquidation_share > 0.5
    assert "canal de outlet" in format_report(casi_todo)

    equilibrado = summarize(
        [señal(LABEL_REAL)] * 20 + [señal(LABEL_LIQUIDATION)] * 5, days=10
    )
    assert "canal de outlet" not in format_report(equilibrado)


def test_sin_aciertos_la_proporcion_de_liquidacion_es_desconocida():
    """No es 0%: no hay de qué sacar proporción. Evita dividir por cero."""
    metrics = summarize([señal(LABEL_FAKE)] * 3, days=3)
    assert metrics[0].liquidation_share is None
    assert metrics[0].precision == 0.0


def test_el_replay_etiqueta_la_liquidacion_de_punta_a_punta():
    """La integración: baja que rompe el piso y no vuelve a subir.

    Es la forma de una liquidación de temporada — precio estable, después baja y
    se queda— y antes de esta etiqueta el replay la contaba como falso positivo.
    """
    serie = puntos(lambda d: 100000 if d < 50 else 55000, dias=90)
    signals = replay_listing(
        serie,
        listing_id=1,
        category_slug="deporte-vestuario",
        threshold=Decimal("0.35"),
        start=START,
        end=START + timedelta(days=89),
    )
    assert signals, "la liquidación tiene que generar señal: el detector la acepta"
    assert signals[0].label == LABEL_LIQUIDATION


def test_el_piso_corta_en_el_dia_y_no_en_la_observacion():
    """El bug que hacía inútil la etiqueta nueva, fijado.

    La pasada de la mañana ya trae el precio nuevo, así que el `min_60d` de la
    baseline con la que el detector acepta —que es la historia hasta la
    observación de la TARDE— ya incluye la bajada. Contra ese piso,
    `price < min_60d` nunca se cumple y una liquidación de libro quedaba `fake`
    igual que antes. El piso tiene que ser el de hasta AYER.
    """
    serie = puntos(lambda d: 100000 if d < 50 else 55000, dias=90)
    dia_de_la_baja = START + timedelta(days=50)
    inicio_del_dia = datetime.combine(
        dia_de_la_baja, datetime.min.time(), tzinfo=timezone.utc
    )

    # Hasta ayer el piso eran 100.000...
    assert piso_previo(serie, inicio_del_dia) == Decimal(100000)
    # ...pero la historia que ve la baseline del detector (hasta la observación
    # de las 20:00) ya incluye la bajada de la mañana. De ahí el bug.
    hasta_la_tarde = inicio_del_dia + timedelta(hours=20)
    assert min(
        precio for observado, precio, _ in serie if observado < hasta_la_tarde
    ) == Decimal(55000)


def test_el_piso_previo_ignora_lo_agotado():
    """Mismo criterio que `compute_baseline`: un agotado congela un precio falso."""
    inicio = datetime(2026, 7, 1, tzinfo=timezone.utc)
    serie = [
        (inicio - timedelta(days=2), Decimal(10000), False),  # agotado, barato
        (inicio - timedelta(days=1), Decimal(90000), True),
    ]
    assert piso_previo(serie, inicio) == Decimal(90000)


def test_sin_historia_previa_no_hay_piso():
    """Y sin piso, el etiquetado cae al binario: no se inventa una liquidación."""
    inicio = datetime(2026, 7, 1, tzinfo=timezone.utc)
    assert piso_previo([], inicio) is None


def test_el_piso_previo_respeta_la_ventana_de_60_dias():
    """Un precio de hace 80 días no es el piso de la ventana."""
    inicio = datetime(2026, 7, 1, tzinfo=timezone.utc)
    serie = [
        (inicio - timedelta(days=80), Decimal(20000), True),  # fuera de ventana
        (inicio - timedelta(days=10), Decimal(90000), True),
    ]
    assert piso_previo(serie, inicio) == Decimal(90000)
