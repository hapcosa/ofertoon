"""La cuota diaria. Todo puro: sin DB, sin Telegram, sin esperar a septiembre.

Esta suite es la que prueba F3 mientras el catálogo no tiene historia. El
detector va a rechazar el 100% por `history` hasta ~2026-09-02, así que
"correrlo y mirar el canal" no distingue entre "la cuota funciona" y "no había
nada que publicar". Acá sí se distingue.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal

import pytest

from curation import ranker
from curation.ranker import Candidate, PostedToday, TZ

#: Un martes cualquiera a las 12:00 de Santiago, bien dentro de la ventana.
NOW = datetime(2026, 8, 4, 12, 0, tzinfo=TZ)


def make(
    candidate_id: int,
    *,
    score: str | None = "30.0",
    store_id: int = 1,
    category_id: int | None = 1,
    detected_at: datetime | None = None,
    price: str = "100000",
    p50: str = "150000",
) -> Candidate:
    return Candidate(
        candidate_id=candidate_id,
        listing_id=1000 + candidate_id,
        store_id=store_id,
        store_name="Falabella",
        category_id=category_id,
        category_name="Notebooks",
        name=f"Producto {candidate_id}",
        url=f"https://example.cl/p/{candidate_id}",
        price=Decimal(price),
        p50=Decimal(p50),
        discount_real=Decimal("0.3333"),
        score=None if score is None else Decimal(score),
        detected_at=detected_at or NOW - timedelta(hours=1),
    )


# -----------------------------------------------------------------------------
# Ventana horaria y espaciado
# -----------------------------------------------------------------------------


@pytest.mark.parametrize("hour", [0, 3, 8, 22, 23])
def test_fuera_de_ventana_no_publica(hour: int) -> None:
    now = NOW.replace(hour=hour)
    assert ranker.select([make(1)], posted=PostedToday(), now=now) == []


@pytest.mark.parametrize("hour", [9, 13, 21])
def test_dentro_de_ventana_publica(hour: int) -> None:
    now = NOW.replace(hour=hour)
    chosen = ranker.select(
        [make(1, detected_at=now - timedelta(hours=1))], posted=PostedToday(), now=now
    )
    assert [c.candidate_id for c in chosen] == [1]


def test_la_ventana_se_evalua_en_hora_de_santiago_no_utc() -> None:
    """Las 02:00 de Santiago son las 06:00 UTC: publicar ahí sería de madrugada.

    Si la ventana se evaluara en UTC este caso pasaría el filtro (6 < 22) y el
    canal postearía a las dos de la mañana.
    """
    madrugada_santiago = datetime(2026, 8, 4, 2, 0, tzinfo=TZ)
    assert madrugada_santiago.astimezone(tz=None).tzinfo is not None
    assert not ranker.within_window(madrugada_santiago)
    assert ranker.select([make(1)], posted=PostedToday(), now=madrugada_santiago) == []


def test_espaciado_minimo_bloquea() -> None:
    posted = PostedToday(
        total=1,
        by_store={1: 1},
        by_category={1: 1},
        last_posted_at=NOW - timedelta(minutes=ranker.MIN_MINUTES_BETWEEN - 1),
    )
    assert ranker.select([make(1)], posted=posted, now=NOW) == []


def test_espaciado_cumplido_deja_pasar() -> None:
    posted = PostedToday(
        total=1,
        by_store={9: 1},
        by_category={9: 1},
        last_posted_at=NOW - timedelta(minutes=ranker.MIN_MINUTES_BETWEEN + 1),
    )
    chosen = ranker.select([make(1)], posted=posted, now=NOW)
    assert [c.candidate_id for c in chosen] == [1]


# -----------------------------------------------------------------------------
# Topes
# -----------------------------------------------------------------------------


def test_cuota_diaria_agotada() -> None:
    posted = PostedToday(total=ranker.MAX_PER_DAY, last_posted_at=None)
    assert ranker.select([make(1)], posted=posted, now=NOW) == []


def test_tope_por_tienda() -> None:
    """Seis ofertas de Falabella no son un canal curado, son un feed de Falabella."""
    candidates = [make(i, store_id=1, category_id=i) for i in range(1, 6)]
    chosen = ranker.select(candidates, posted=PostedToday(), now=NOW, limit=None)
    assert len(chosen) == ranker.MAX_PER_STORE_PER_DAY


def test_tope_por_categoria() -> None:
    candidates = [make(i, store_id=i, category_id=7) for i in range(1, 6)]
    chosen = ranker.select(candidates, posted=PostedToday(), now=NOW, limit=None)
    assert len(chosen) == ranker.MAX_PER_CATEGORY_PER_DAY


def test_los_topes_arrastran_lo_ya_publicado_hoy() -> None:
    posted = PostedToday(total=1, by_store={1: ranker.MAX_PER_STORE_PER_DAY})
    candidates = [make(1, store_id=1), make(2, store_id=2)]
    chosen = ranker.select(candidates, posted=posted, now=NOW, limit=None)
    assert [c.candidate_id for c in chosen] == [2]


def test_el_tope_deja_pasar_al_siguiente_distinto() -> None:
    """La diversidad sale de los topes, no de un round-robin explícito.

    Los tres primeros tienen más score, pero la tienda 1 se llena en dos y el
    cuarto —peor score, otra tienda— entra igual.
    """
    candidates = [
        make(1, store_id=1, category_id=1, score="90"),
        make(2, store_id=1, category_id=2, score="80"),
        make(3, store_id=1, category_id=3, score="70"),
        make(4, store_id=2, category_id=4, score="10"),
    ]
    chosen = ranker.select(candidates, posted=PostedToday(), now=NOW, limit=None)
    assert [c.candidate_id for c in chosen] == [1, 2, 4]


def test_no_supera_la_cuota_diaria_en_una_vuelta() -> None:
    candidates = [make(i, store_id=i, category_id=i) for i in range(1, 20)]
    chosen = ranker.select(candidates, posted=PostedToday(), now=NOW, limit=None)
    assert len(chosen) == ranker.MAX_PER_DAY


# -----------------------------------------------------------------------------
# Orden y frescura
# -----------------------------------------------------------------------------


def test_orden_por_score_descendente() -> None:
    candidates = [
        make(1, score="10", store_id=1, category_id=1),
        make(2, score="90", store_id=2, category_id=2),
        make(3, score="50", store_id=3, category_id=3),
    ]
    chosen = ranker.select(candidates, posted=PostedToday(), now=NOW, limit=None)
    assert [c.candidate_id for c in chosen] == [2, 3, 1]


def test_score_nulo_va_al_fondo_sin_reventar() -> None:
    candidates = [
        make(1, score=None, store_id=1, category_id=1),
        make(2, score="5", store_id=2, category_id=2),
    ]
    chosen = ranker.select(candidates, posted=PostedToday(), now=NOW, limit=None)
    assert [c.candidate_id for c in chosen] == [2, 1]


def test_empate_de_score_desempata_por_id_para_ser_determinista() -> None:
    candidates = [
        make(7, score="50", store_id=1, category_id=1),
        make(3, score="50", store_id=2, category_id=2),
    ]
    chosen = ranker.select(candidates, posted=PostedToday(), now=NOW, limit=None)
    assert [c.candidate_id for c in chosen] == [3, 7]


def test_candidato_vencido_no_se_publica() -> None:
    """Un aceptado de anteayer trae un precio que ya nadie verificó.

    Si la oferta sigue viva la próxima pasada la vuelve a detectar con precio
    fresco. Publicar un precio vencido es exactamente lo que el canal promete no
    hacer.
    """
    viejo = make(1, detected_at=NOW - timedelta(hours=ranker.MAX_AGE_HOURS + 1))
    assert ranker.select([viejo], posted=PostedToday(), now=NOW) == []


def test_candidato_en_el_limite_de_frescura_pasa() -> None:
    limite = make(1, detected_at=NOW - timedelta(hours=ranker.MAX_AGE_HOURS))
    assert len(ranker.select([limite], posted=PostedToday(), now=NOW)) == 1


def test_limit_uno_es_lo_que_usa_el_daemon() -> None:
    candidates = [make(i, store_id=i, category_id=i) for i in range(1, 6)]
    assert len(ranker.select(candidates, posted=PostedToday(), now=NOW, limit=1)) == 1


def test_sin_candidatos_no_hay_nada_que_elegir() -> None:
    assert ranker.select([], posted=PostedToday(), now=NOW) == []


# -----------------------------------------------------------------------------
# Día calendario
# -----------------------------------------------------------------------------


def test_el_dia_calendario_es_el_de_santiago() -> None:
    """Las 23:00 de Santiago son las 03:00 UTC del día siguiente.

    Con el corte en UTC, la cuota se reiniciaría a las 20:00 o 21:00 hora local
    —el mejor momento del día— y el canal podría publicar doce ofertas en una
    tarde sin violar ningún tope.
    """
    tarde = datetime(2026, 8, 4, 23, 0, tzinfo=TZ)
    start, end = ranker.local_day_bounds(tarde)
    assert start == datetime(2026, 8, 4, 0, 0, tzinfo=TZ)
    assert end == datetime(2026, 8, 5, 0, 0, tzinfo=TZ)
    assert start <= tarde < end


def test_el_dia_calendario_se_calcula_igual_desde_utc() -> None:
    from datetime import timezone

    tarde_utc = datetime(2026, 8, 5, 3, 0, tzinfo=timezone.utc)  # 23:00 en Santiago
    start, end = ranker.local_day_bounds(tarde_utc)
    assert start.astimezone(TZ).date().isoformat() == "2026-08-04"
    assert start <= tarde_utc < end
