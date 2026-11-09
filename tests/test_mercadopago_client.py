"""Contrato del cliente server-side de MercadoPago Suscripciones (preapproval)."""
from __future__ import annotations

import json

import httpx
import pytest

from subscriptions.mercadopago.client import (
    MercadoPagoClient,
    MercadoPagoConfigurationError,
    MercadoPagoUnavailable,
)


PLAN_ID = "2c9380848efa0abc018efa1234560001"


def _plan_payload(*, transaction_amount: object = 6000) -> dict:
    return {
        "id": PLAN_ID,
        "status": "active",
        "auto_recurring": {
            "frequency": 1,
            "frequency_type": "months",
            "transaction_amount": transaction_amount,
            "currency_id": "CLP",
        },
    }


@pytest.mark.asyncio
async def test_validates_plan_and_creates_preapproval():
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == f"/preapproval_plan/{PLAN_ID}":
            return httpx.Response(200, json=_plan_payload())
        if request.url.path == "/preapproval":
            return httpx.Response(
                201,
                json={
                    "id": "2c9380848efa0abc018efapreapproval1",
                    "status": "pending",
                    "external_reference": "tg:123456789:1",
                    "init_point": "https://www.mercadopago.cl/subscriptions/checkout?preapproval_id=1",
                },
            )
        return httpx.Response(404)

    client = MercadoPagoClient(
        access_token="TEST-token",
        transport=httpx.MockTransport(handler),
    )

    plan = await client.get_monthly_plan(PLAN_ID)
    preapproval = await client.create_preapproval(
        plan_id=PLAN_ID,
        external_reference="tg:123456789:1",
        idempotency_key="mp-checkout-123",
        back_url="https://t.me/OfertoonBot?start=mp_approved",
        payer_email="buyer@example.com",
    )

    assert plan.price_clp == 6000
    assert preapproval.id == "2c9380848efa0abc018efapreapproval1"
    assert preapproval.init_point.startswith("https://www.mercadopago.cl/")
    create_request = next(r for r in requests if r.url.path == "/preapproval")
    assert create_request.headers["authorization"] == "Bearer TEST-token"
    assert create_request.headers["x-idempotency-key"] == "mp-checkout-123"
    body = json.loads(create_request.content)
    assert body["preapproval_plan_id"] == PLAN_ID
    assert body["external_reference"] == "tg:123456789:1"
    assert body["payer_email"] == "buyer@example.com"


@pytest.mark.asyncio
async def test_rejects_non_integer_clp_amount_as_configuration_error():
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_plan_payload(transaction_amount=1999.5))

    client = MercadoPagoClient(
        access_token="TEST-token",
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(MercadoPagoConfigurationError, match="positive integer CLP"):
        await client.get_monthly_plan(PLAN_ID)


@pytest.mark.asyncio
async def test_rejects_init_point_outside_mercadopago():
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            201,
            json={
                "id": "2c9380848efa0abc018efapreapproval1",
                "status": "pending",
                "external_reference": "tg:123456789:1",
                "init_point": "https://attacker.example/pay",
            },
        )

    client = MercadoPagoClient(
        access_token="TEST-token",
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(MercadoPagoUnavailable, match="init point"):
        await client.create_preapproval(
            plan_id=PLAN_ID,
            external_reference="tg:123456789:1",
            idempotency_key="mp-checkout-123",
            back_url="https://t.me/OfertoonBot?start=mp_approved",
            payer_email=None,
        )


def test_from_env_requires_access_token(monkeypatch):
    monkeypatch.delenv("MERCADOPAGO_ACCESS_TOKEN", raising=False)
    with pytest.raises(MercadoPagoConfigurationError):
        MercadoPagoClient.from_env()
