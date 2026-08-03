"""Contrato del cliente server-side de PayPal Subscriptions."""
from __future__ import annotations

import json

import httpx
import pytest

from subscriptions.paypal.client import PayPalClient, PayPalConfigurationError


PLAN_ID = "P-8YF6357695952401WNJNGKTQ"


def _plan_payload(*, interval_count: object = 1) -> dict:
    return {
        "id": PLAN_ID,
        "product_id": "100002",
        "name": "Telegram Signals Pro Test mensual pro trader",
        "status": "ACTIVE",
        "billing_cycles": [
            {
                "tenure_type": "REGULAR",
                "sequence": 1,
                "total_cycles": 0,
                "frequency": {
                    "interval_unit": "MONTH",
                    "interval_count": interval_count,
                },
                "pricing_scheme": {
                    "fixed_price": {"value": "1.00", "currency_code": "USD"}
                },
            }
        ],
    }


@pytest.mark.asyncio
async def test_validates_plan_and_creates_server_side_subscription():
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/v1/oauth2/token":
            return httpx.Response(
                200,
                json={"access_token": "token-1", "expires_in": 3600},
            )
        if request.url.path == f"/v1/billing/plans/{PLAN_ID}":
            return httpx.Response(200, json=_plan_payload())
        if request.url.path == "/v1/billing/subscriptions":
            return httpx.Response(
                201,
                json={
                    "id": "I-SANDBOX-CHECKOUT-1",
                    "status": "APPROVAL_PENDING",
                    "custom_id": "tg:123456789",
                    "links": [
                        {
                            "rel": "approve",
                            "href": "https://www.sandbox.paypal.com/webapps/billing/subscriptions?ba_token=BA-1",
                        }
                    ],
                },
            )
        return httpx.Response(404)

    client = PayPalClient(
        environment="sandbox",
        client_id="client-id",
        client_secret="client-secret",
        transport=httpx.MockTransport(handler),
    )

    plan = await client.get_monthly_plan(PLAN_ID)
    subscription = await client.create_subscription(
        plan_id=PLAN_ID,
        custom_id="tg:123456789",
        request_id="tg-checkout-123",
        return_url="https://budaicapital.com/telegram-signals?paypal=approved",
        cancel_url="https://budaicapital.com/telegram-signals?paypal=cancelled",
        email="buyer@example.com",
    )

    assert str(plan.price_usd) == "1.00"
    assert plan.product_id == "100002"
    assert plan.has_trial is False
    assert subscription.id == "I-SANDBOX-CHECKOUT-1"
    assert sum(r.url.path == "/v1/oauth2/token" for r in requests) == 1
    create_request = next(
        r for r in requests if r.url.path == "/v1/billing/subscriptions"
    )
    assert create_request.headers["paypal-request-id"] == "tg-checkout-123"
    body = json.loads(create_request.content)
    assert body["plan_id"] == PLAN_ID
    assert body["custom_id"] == "tg:123456789"
    assert body["application_context"]["shipping_preference"] == "NO_SHIPPING"
    assert body["subscriber"]["email_address"] == "buyer@example.com"


@pytest.mark.asyncio
async def test_rejects_malformed_billing_interval_as_configuration_error():
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/oauth2/token":
            return httpx.Response(200, json={"access_token": "token-1"})
        return httpx.Response(200, json=_plan_payload(interval_count="monthly"))

    client = PayPalClient(
        environment="sandbox",
        client_id="client-id",
        client_secret="client-secret",
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(PayPalConfigurationError, match="billing intervals"):
        await client.get_monthly_plan(PLAN_ID)


@pytest.mark.asyncio
async def test_rejects_approval_url_outside_paypal():
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/oauth2/token":
            return httpx.Response(200, json={"access_token": "token-1"})
        return httpx.Response(
            201,
            json={
                "id": "I-SANDBOX-CHECKOUT-1",
                "status": "APPROVAL_PENDING",
                "links": [
                    {"rel": "approve", "href": "https://attacker.example/pay"}
                ],
            },
        )

    client = PayPalClient(
        environment="sandbox",
        client_id="client-id",
        client_secret="client-secret",
        transport=httpx.MockTransport(handler),
    )

    from subscriptions.paypal.client import PayPalUnavailable

    with pytest.raises(PayPalUnavailable, match="approval URL"):
        await client.create_subscription(
            plan_id=PLAN_ID,
            custom_id="tg:123456789",
            request_id="tg-checkout-123",
            return_url="https://budaicapital.com/telegram-signals?paypal=approved",
            cancel_url="https://budaicapital.com/telegram-signals?paypal=cancelled",
            email=None,
        )
