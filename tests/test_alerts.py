"""El aviso post-pasada: silencio cuando todo está verde, ruido cuando no."""
from __future__ import annotations

from datetime import date, datetime

import alerts
from alerts import MAX_LINES, PasadaFlaca, RunOutcome, format_summary, send_alert


def ok(store="falabella", cat="tecno", key="cat1", seen=900):
    return RunOutcome(store, cat, key, "ok", seen, seen)


def bad(status, store="paris", cat="tecno", key="lblCel", seen=3, error="canario: X"):
    return RunOutcome(store, cat, key, status, seen, 0, error)


def test_pasada_verde_no_manda_nada():
    """Si cada pasada mandara un OK, el primer partial real pasaría de largo."""
    assert format_summary([ok(), ok(), ok()]) is None
    assert format_summary([]) is None


def test_resumen_lista_failed_y_partial_con_su_target():
    summary = format_summary([ok(), bad("failed"), bad("partial", store="easy")])
    assert summary is not None
    assert "1 fallo(s)" in summary and "1 degradada(s)" in summary
    assert "de 3 corridas" in summary
    assert "paris/tecno [lblCel]" in summary
    assert "easy/tecno [lblCel]" in summary


def test_los_fallos_van_antes_que_las_degradadas():
    summary = format_summary([bad("partial", store="easy"), bad("failed", store="paris")])
    assert summary.index("paris") < summary.index("easy")


def test_mensaje_acotado_para_no_exceder_el_limite_de_telegram():
    outcomes = [bad("failed", key=f"cat{i}") for i in range(60)]
    summary = format_summary(outcomes)
    cuerpo = summary.splitlines()[2:]
    assert len(cuerpo) == MAX_LINES + 1  # + la línea de "… y N más"
    assert cuerpo[-1] == f"… y {60 - MAX_LINES} más"


async def test_send_alert_sin_configurar_es_no_op(monkeypatch, caplog):
    monkeypatch.delenv("ALERT_BOT_TOKEN", raising=False)
    monkeypatch.delenv("ALERT_CHAT_ID", raising=False)
    assert await send_alert("algo se rompió") is False


async def test_send_alert_sin_texto_no_toca_telegram(monkeypatch):
    monkeypatch.setenv("ALERT_BOT_TOKEN", "t")
    monkeypatch.setenv("ALERT_CHAT_ID", "-100")
    assert await send_alert(None) is False


async def test_send_alert_manda_al_chat_configurado(monkeypatch):
    enviados = []

    class FakeClient:
        def __init__(self, token):
            enviados.append(("token", token))

        async def send_message(self, chat_id, text):
            enviados.append((chat_id, text))
            return 42

    monkeypatch.setattr("subscriptions.telegram_client.TelegramClient", FakeClient)
    monkeypatch.setenv("ALERT_BOT_TOKEN", "abc:123")
    monkeypatch.setenv("ALERT_CHAT_ID", "-1001234")

    assert await send_alert("⚠️ algo") is True
    assert enviados == [("token", "abc:123"), (-1001234, "⚠️ algo")]


async def test_chat_id_invalido_no_lanza(monkeypatch):
    monkeypatch.setenv("ALERT_BOT_TOKEN", "abc:123")
    monkeypatch.setenv("ALERT_CHAT_ID", "no-es-un-id")
    assert await send_alert("⚠️ algo") is False


async def test_telegram_caido_no_tumba_la_pasada(monkeypatch):
    class DeadClient:
        def __init__(self, token):
            pass

        async def send_message(self, chat_id, text):
            return None  # el cliente portado falla como no-op, nunca lanza

    monkeypatch.setattr("subscriptions.telegram_client.TelegramClient", DeadClient)
    monkeypatch.setenv("ALERT_BOT_TOKEN", "abc:123")
    monkeypatch.setenv("ALERT_CHAT_ID", "-100")
    assert await send_alert("⚠️ algo") is False


def test_alerts_no_importa_aiohttp_si_no_hay_nada_que_mandar():
    """El import del cliente es perezoso: la pasada verde no paga aiohttp."""
    assert "aiohttp" not in dir(alerts)


# -----------------------------------------------------------------------------
# El aviso de agujero en la serie
# -----------------------------------------------------------------------------
# Existe porque la alerta de una caída de red viaja por la misma red que se
# cayó: del 18 al 20 de septiembre de 2026 hubo 48 h sin una sola observación,
# 562 corridas `failed` y cero avisos. Lo que sobrevive a esa caída es la serie
# en el Postgres local, así que el agujero se detecta leyendo la DB y se reporta
# en la primera pasada que SÍ logra hablar con Telegram — aunque esa pasada haya
# salido verde.


def test_pasada_verde_con_agujero_si_avisa():
    """El caso del 18-sep: la pasada de hoy anduvo, pero faltan días."""
    summary = format_summary([ok(), ok()], [date(2026, 9, 18), date(2026, 9, 19)])
    assert summary is not None
    assert "2 día(s) SIN observaciones" in summary
    assert "2026-09-18" in summary and "2026-09-19" in summary


def test_sin_agujero_la_pasada_verde_sigue_callada():
    assert format_summary([ok(), ok()], []) is None


def test_agujero_y_fallos_van_en_el_mismo_mensaje():
    """Una sola alerta: son el mismo incidente visto por dos lados."""
    summary = format_summary([ok(), bad("failed")], [date(2026, 9, 18)])
    assert summary is not None
    assert "1 día(s) SIN observaciones" in summary
    assert "1 fallo(s)" in summary
    # El agujero va primero: es el dato más viejo y el más grave.
    assert summary.index("SIN observaciones") < summary.index("fallo(s)")


def test_el_agujero_explica_por_que_importa():
    """Un aviso que no dice qué rompe se ignora a la tercera vez."""
    summary = format_summary([ok()], [date(2026, 9, 18)])
    assert "n_days" in summary and "backtest" in summary


# -----------------------------------------------------------------------------
# El aviso de pasada a medias
# -----------------------------------------------------------------------------
# El tercer caso, y el que no veía ninguna de las dos guardas anteriores: el
# 29-sep-2026 una pasada perdió 62 de 129 objetivos y escribió 1.481
# observaciones contra ~16.500. El día no quedó vacío (así que la guarda de
# agujero lo vio sano), los objetivos que no corrieron no dejaron fila (así que
# el canario por target no tuvo qué comparar) y el proceso murió dentro de
# `run_once`, antes de `send_alert`. Se reporta en la pasada siguiente, leyendo
# la DB local, por el mismo motivo que el agujero.


def flaca(obs=1481, mediana=16509.0, dia=29):
    return PasadaFlaca(datetime(2026, 9, dia, 3, 16), obs, mediana)


def test_pasada_verde_con_una_flaca_anterior_si_avisa():
    """El caso del 29-sep: la pasada de ahora anduvo, la anterior corrió a medias."""
    summary = format_summary([ok(), ok()], [], [flaca()])
    assert summary is not None
    assert "1 pasada(s) a medias" in summary
    assert "2026-09-29 03:16" in summary


def test_la_flaca_muestra_el_volumen_contra_su_mediana():
    """Un aviso sin el número al lado no deja decidir si es un incidente."""
    summary = format_summary([ok()], [], [flaca()])
    assert "1.481 obs" in summary          # separador chileno, como el resto
    assert "vs mediana 16.509" in summary
    assert "91% menos" in summary


def test_la_flaca_explica_por_que_ninguna_otra_guarda_la_ve():
    """Si no dice eso, el lector asume que es lo mismo que el canario y lo ignora."""
    summary = format_summary([ok()], [], [flaca()])
    assert "p50" in summary
    assert "canario" in summary and "agujero" in summary


def test_sin_flacas_la_pasada_verde_sigue_callada():
    assert format_summary([ok(), ok()], [], []) is None


def test_las_tres_guardas_van_en_el_mismo_mensaje():
    """Una sola alerta: son el mismo incidente visto desde tres alturas."""
    summary = format_summary([ok(), bad("failed")], [date(2026, 9, 18)], [flaca()])
    assert summary is not None
    # De lo más viejo y más grave a lo más nuevo: agujero, pasada, targets.
    assert summary.index("SIN observaciones") < summary.index("a medias")
    assert summary.index("a medias") < summary.index("fallo(s)")


def test_varias_flacas_se_listan_todas():
    summary = format_summary([ok()], [], [flaca(dia=27), flaca(dia=29)])
    assert "2 pasada(s) a medias" in summary
    assert "2026-09-27 03:16" in summary and "2026-09-29 03:16" in summary


def test_una_pasada_en_cero_no_divide_por_cero():
    """El patrón del 18-sep: volumen 0 contra una mediana sana."""
    summary = format_summary([ok()], [], [flaca(obs=0, mediana=10713.0)])
    assert "0 obs" in summary and "100% menos" in summary
