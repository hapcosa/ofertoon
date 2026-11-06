"""Contrato seguro de POST /webhook/mercadopago.

A diferencia de `test_paypal_webhook.py`, acá el "cliente" inyectado en
`build_app` no es HTTP real: es un doble de prueba que responde `get_preapproval`
/ `get_authorized_payment` con el recurso que cada test programa, porque
`apply_mercadopago_event` SIEMPRE busca el recurso autoritativo antes de
decidir nada (la notificación solo trae un id).
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import hmac
import time

import pytest
import pytest_asyncio

from subscriptions.mercadopago.client import MercadoPagoAPIError, MercadoPagoUnavailable
from subscriptions.mercadopago import webhook as mp_webhook_api


_SECRET = "test-webhook-secret"


class _StubVerifier:
    def __init__(self, result: bool):
        self.result = result

    def verify(self, headers, query, *, now):
        return self.result


class _StubMercadoPagoClient:
    def __init__(self) -> None:
        self.preapprovals: dict[str, dict] = {}
        self.authorized_payments: dict[str, dict] = {}

    async def get_preapproval(self, preapproval_id: str) -> dict:
        try:
            return self.preapprovals[preapproval_id]
        except KeyError:
            raise MercadoPagoAPIError(f"preapproval not found: {preapproval_id}")

    async def get_authorized_payment(self, authorized_payment_id: str) -> dict:
        try:
            return self.authorized_payments[authorized_payment_id]
        except KeyError:
            raise MercadoPagoAPIError(
                f"authorized_payment not found: {authorized_payment_id}"
            )


@pytest_asyncio.fixture
async def mp(telegram_pool, monkeypatch):
    """Cliente HTTP contra la app aiohttp del webhook MercadoPago + el doble."""
    from aiohttp.test_utils import TestClient, TestServer

    monkeypatch.setattr(mp_webhook_api, "_verifier", _StubVerifier(True))
    stub_client = _StubMercadoPagoClient()
    async with TestClient(
        TestServer(mp_webhook_api.build_app(telegram_pool, stub_client))
    ) as test_client:
        yield test_client, stub_client


async def _post(test_client, envelope: dict, *, data_id: str | None = None):
    query = {}
    if data_id is not None:
        query["data.id"] = data_id
    elif isinstance(envelope.get("data"), dict):
        query["data.id"] = str(envelope["data"]["id"])
    return await test_client.post("/webhook/mercadopago", params=query, json=envelope)


async def _mp_plan(
    db_conn, *, mercadopago_plan_id: str = "MP-TEST-MONTHLY", price_clp: int = 6000
):
    tier_id = await db_conn.fetchval(
        """INSERT INTO telegram_tiers (name, slug, telegram_channel_id)
             VALUES ('Pro', $1, -1001234567890)
          RETURNING id""",
        f"pro-{mercadopago_plan_id.lower()}",
    )
    tier_plan_id = await db_conn.fetchval(
        """INSERT INTO telegram_tier_plans
               (tier_id, period, price_usdt, price_clp, mercadopago_plan_id)
             VALUES ($1, 'monthly', 0, $2, $3)
          RETURNING id""",
        tier_id,
        price_clp,
        mercadopago_plan_id,
    )
    return tier_id, tier_plan_id


async def _membership(db_conn, telegram_user_id: int = 123456789):
    return await db_conn.fetchrow(
        "SELECT * FROM telegram_memberships WHERE telegram_user_id = $1",
        telegram_user_id,
    )


def _preapproval_envelope(
    event_id: str,
    *,
    created: str = "2026-07-16T12:00:00Z",
    data_id: str = "MP-PRE-1",
) -> dict:
    return {
        "id": event_id,
        "type": "subscription_preapproval",
        "date_created": created,
        "data": {"id": data_id},
    }


def _preapproval_resource(
    *,
    preapproval_id: str = "MP-PRE-1",
    plan_id: str = "MP-TEST-MONTHLY",
    status: str = "authorized",
    external_reference: str = "tg:123456789",
    payer_id: str = "PAYER-123",
    payer_email: str = "buyer@example.com",
    next_payment_date: str | None = "2026-08-16T12:00:00Z",
) -> dict:
    return {
        "id": preapproval_id,
        "preapproval_plan_id": plan_id,
        "status": status,
        "external_reference": external_reference,
        "payer_id": payer_id,
        "payer_email": payer_email,
        "next_payment_date": next_payment_date,
    }


@pytest.mark.asyncio
async def test_invalid_signature_is_rejected_without_persistence(mp, db_conn, monkeypatch):
    test_client, _stub = mp
    monkeypatch.setattr(mp_webhook_api, "_verifier", _StubVerifier(False))
    envelope = _preapproval_envelope("WH-BAD-SIGNATURE")

    response = await _post(test_client, envelope)

    assert response.status == 401
    assert await db_conn.fetchval("SELECT COUNT(*) FROM mercadopago_webhook_events") == 0


@pytest.mark.asyncio
async def test_data_id_mismatch_between_query_and_body_is_rejected(mp, db_conn):
    test_client, _stub = mp
    envelope = _preapproval_envelope("WH-MISMATCH", data_id="MP-PRE-1")

    response = await test_client.post(
        "/webhook/mercadopago", params={"data.id": "MP-PRE-OTHER"}, json=envelope
    )

    assert response.status == 400
    assert await db_conn.fetchval("SELECT COUNT(*) FROM mercadopago_webhook_events") == 0


@pytest.mark.asyncio
async def test_authorized_preapproval_maps_plan_and_telegram_identity(mp, db_conn):
    test_client, stub = mp
    tier_id, tier_plan_id = await _mp_plan(db_conn)
    stub.preapprovals["MP-PRE-1"] = _preapproval_resource()
    envelope = _preapproval_envelope("WH-AUTHORIZED-1")

    response = await _post(test_client, envelope)
    body = await response.json()

    assert response.status == 200, await response.text()
    assert body == {"status": "accepted", "duplicate": False}
    identity = await db_conn.fetchrow(
        "SELECT email FROM telegram_subscribers WHERE telegram_user_id = 123456789"
    )
    assert identity["email"] == "buyer@example.com"
    membership = await _membership(db_conn)
    assert membership["payment_provider"] == "mercadopago"
    assert membership["mercadopago_preapproval_id"] == "MP-PRE-1"
    assert membership["mercadopago_payer_id"] == "PAYER-123"
    assert membership["tier_id"] == tier_id
    assert membership["tier_plan_id"] == tier_plan_id
    assert membership["status"] == "active"
    assert membership["current_period_end"] == datetime(
        2026, 8, 16, 12, tzinfo=timezone.utc
    )
    audit = await db_conn.fetchrow(
        "SELECT processing_status, processing_error FROM mercadopago_webhook_events"
    )
    assert audit["processing_status"] == "processed"
    assert audit["processing_error"] is None


@pytest.mark.asyncio
async def test_duplicate_event_does_not_apply_twice(mp, db_conn):
    test_client, stub = mp
    await _mp_plan(db_conn)
    stub.preapprovals["MP-PRE-1"] = _preapproval_resource()
    envelope = _preapproval_envelope("WH-DUPLICATE-1")

    first = await _post(test_client, envelope)
    second = await _post(test_client, envelope)

    assert (await first.json())["duplicate"] is False
    assert (await second.json())["duplicate"] is True
    assert await db_conn.fetchval("SELECT COUNT(*) FROM mercadopago_webhook_events") == 1
    assert await db_conn.fetchval("SELECT COUNT(*) FROM telegram_memberships") == 1


@pytest.mark.asyncio
async def test_unknown_plan_is_audited_but_never_grants_access(mp, db_conn):
    test_client, stub = mp
    stub.preapprovals["MP-PRE-1"] = _preapproval_resource(plan_id="MP-NOT-OURS")
    envelope = _preapproval_envelope("WH-UNKNOWN-PLAN")

    response = await _post(test_client, envelope)

    assert response.status == 200
    assert await db_conn.fetchval("SELECT COUNT(*) FROM telegram_subscribers") == 0
    assert await db_conn.fetchval("SELECT COUNT(*) FROM telegram_memberships") == 0
    audit = await db_conn.fetchrow(
        "SELECT processing_status, processing_error FROM mercadopago_webhook_events"
    )
    assert audit["processing_status"] == "rejected"
    assert "unknown or inactive MercadoPago plan" in audit["processing_error"]


@pytest.mark.asyncio
async def test_unknown_preapproval_resource_is_rejected_not_crashed(mp, db_conn):
    """Un id que MercadoPago ya no reconoce (404) se audita, no tumba el webhook."""
    test_client, _stub = mp
    envelope = _preapproval_envelope("WH-404", data_id="MP-PRE-GHOST")

    response = await _post(test_client, envelope)

    assert response.status == 200
    audit = await db_conn.fetchrow(
        "SELECT processing_status, processing_error FROM mercadopago_webhook_events"
    )
    assert audit["processing_status"] == "rejected"
    assert "mercadopago resource fetch rejected" in audit["processing_error"]


class _FlakyClient:
    async def get_preapproval(self, preapproval_id):
        raise MercadoPagoUnavailable("timeout")

    async def get_authorized_payment(self, authorized_payment_id):
        raise MercadoPagoUnavailable("timeout")


@pytest.mark.asyncio
async def test_transient_unavailable_rolls_back_and_returns_503(
    telegram_pool, db_conn, monkeypatch
):
    """Un 5xx/timeout de MercadoPago al buscar el recurso no se clasifica como
    rechazado: la transacción se revierte entera (ni la fila de dedup queda) y
    el webhook contesta 503 para que MercadoPago reintente.

    Arma su propia app (en vez de reusar la fixture `mp`) para inyectar el
    cliente fallido desde la construcción: mutar `app[CLIENT_KEY]` después de
    que el server ya arrancó tira un DeprecationWarning de aiohttp.
    """
    from aiohttp.test_utils import TestClient, TestServer

    monkeypatch.setattr(mp_webhook_api, "_verifier", _StubVerifier(True))
    envelope = _preapproval_envelope("WH-FLAKY")
    async with TestClient(
        TestServer(mp_webhook_api.build_app(telegram_pool, _FlakyClient()))
    ) as test_client:
        response = await _post(test_client, envelope)

    assert response.status == 503
    assert await db_conn.fetchval("SELECT COUNT(*) FROM mercadopago_webhook_events") == 0


@pytest.mark.asyncio
async def test_out_of_order_terminal_event_cannot_override_newer_state(mp, db_conn):
    test_client, stub = mp
    await _mp_plan(db_conn)
    stub.preapprovals["MP-PRE-NEWER"] = _preapproval_resource(
        preapproval_id="MP-PRE-NEWER"
    )
    newer = _preapproval_envelope(
        "WH-AUTH-NEWER", created="2026-07-16T12:00:00Z", data_id="MP-PRE-NEWER"
    )
    assert (await _post(test_client, newer)).status == 200

    stub.preapprovals["MP-PRE-NEWER"] = _preapproval_resource(
        preapproval_id="MP-PRE-NEWER", status="cancelled"
    )
    older_cancel = _preapproval_envelope(
        "WH-CANCEL-OLDER", created="2026-07-16T11:00:00Z", data_id="MP-PRE-NEWER"
    )

    response = await _post(test_client, older_cancel)

    assert response.status == 200
    assert await db_conn.fetchval(
        "SELECT status FROM telegram_memberships WHERE telegram_user_id = 123456789"
    ) == "active"
    audit = await db_conn.fetchrow(
        """SELECT processing_status, processing_error
             FROM mercadopago_webhook_events WHERE event_id = 'WH-CANCEL-OLDER'"""
    )
    assert audit["processing_status"] == "ignored"
    assert "out-of-order" in audit["processing_error"]


def _authorized_payment_envelope(
    event_id: str, *, created: str, data_id: str = "AP-1"
) -> dict:
    return {
        "id": event_id,
        "type": "subscription_authorized_payment",
        "date_created": created,
        "data": {"id": data_id},
    }


@pytest.mark.asyncio
async def test_processed_payment_requires_exact_clp_price(mp, db_conn):
    test_client, stub = mp
    await _mp_plan(db_conn, price_clp=6000)
    stub.preapprovals["MP-PRE-1"] = _preapproval_resource()
    activated = _preapproval_envelope("WH-ACTIVE-PAYMENT")
    assert (await _post(test_client, activated)).status == 200

    stub.authorized_payments["AP-1"] = {
        "preapproval_id": "MP-PRE-1",
        "status": "processed",
        "transaction_amount": 6000,
        "currency_id": "CLP",
    }
    payment = _authorized_payment_envelope(
        "WH-PAYMENT-COMPLETED", created="2026-07-16T12:05:00Z", data_id="AP-1"
    )

    response = await _post(test_client, payment)

    assert response.status == 200
    assert await db_conn.fetchval(
        "SELECT mercadopago_last_payment_at FROM telegram_memberships"
    ) == datetime(2026, 7, 16, 12, 5, tzinfo=timezone.utc)

    stub.authorized_payments["AP-2"] = {
        "preapproval_id": "MP-PRE-1",
        "status": "processed",
        "transaction_amount": 1,
        "currency_id": "CLP",
    }
    mismatch = _authorized_payment_envelope(
        "WH-PAYMENT-MISMATCH", created="2026-07-16T12:06:00Z", data_id="AP-2"
    )
    assert (await _post(test_client, mismatch)).status == 200
    status = await db_conn.fetchval(
        """SELECT processing_status FROM mercadopago_webhook_events
            WHERE event_id = 'WH-PAYMENT-MISMATCH'"""
    )
    assert status == "rejected"


@pytest.mark.asyncio
async def test_rejected_payment_moves_membership_to_past_due(mp, db_conn):
    test_client, stub = mp
    await _mp_plan(db_conn, price_clp=6000)
    stub.preapprovals["MP-PRE-1"] = _preapproval_resource()
    activated = _preapproval_envelope("WH-ACTIVE-2")
    assert (await _post(test_client, activated)).status == 200

    stub.authorized_payments["AP-REJECTED"] = {
        "preapproval_id": "MP-PRE-1",
        "status": "rejected",
        "transaction_amount": 6000,
        "currency_id": "CLP",
    }
    rejected = _authorized_payment_envelope(
        "WH-PAYMENT-REJECTED", created="2026-07-16T12:10:00Z", data_id="AP-REJECTED"
    )

    response = await _post(test_client, rejected)

    assert response.status == 200
    assert await db_conn.fetchval(
        "SELECT status FROM telegram_memberships WHERE telegram_user_id = 123456789"
    ) == "past_due"


def test_real_signature_verifier_accepts_valid_and_rejects_tampered(monkeypatch):
    monkeypatch.setenv("MERCADOPAGO_WEBHOOK_SECRET", _SECRET)
    verifier = mp_webhook_api.MercadoPagoWebhookVerifier()
    now = time.time()
    ts = str(int(now))
    data_id = "123456"
    request_id = "req-1"
    manifest = f"id:{data_id};request-id:{request_id};ts:{ts};".encode("utf-8")
    signature = hmac.new(_SECRET.encode("utf-8"), manifest, hashlib.sha256).hexdigest()
    headers = {"x-signature": f"ts={ts},v1={signature}", "x-request-id": request_id}
    query = {"data.id": data_id}

    assert verifier.verify(headers, query, now=now) is True
    # El id firmado era 123456; si el query trajera otro, el manifiesto deja
    # de calzar con la firma.
    assert verifier.verify(headers, {"data.id": "999999"}, now=now) is False
    # ts fuera de la ventana de tolerancia.
    assert verifier.verify(headers, query, now=now + 3600) is False
