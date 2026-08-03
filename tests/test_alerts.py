"""El aviso post-pasada: silencio cuando todo está verde, ruido cuando no."""
from __future__ import annotations

import alerts
from alerts import MAX_LINES, RunOutcome, format_summary, send_alert


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
