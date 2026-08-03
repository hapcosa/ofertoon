"""F4.4: selección de plan, checkout del bot y round-trip con el webhook."""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

from aiogram.types import Message
import pytest

from subscriptions.paypal import webhook as paypal_webhook_api
from subscriptions.paypal.client import PayPalSubscription
from subscriptions.paypal.events import _telegram_custom_id
from subscriptions.bot import db
from subscriptions.bot import main as onboarding_main
from subscriptions.bot.payments import (
    PaymentConfigurationError,
    PlanChoiceMode,
    build_custom_id,
    build_request_id,
    format_pay_prompt,
    resolve_redirect_urls,
    select_plan_options,
)
from subscriptions.gate import decide_action


class _VerifiedWebhook:
    async def verify(self, raw_body, headers):
        return True


class _StubPayPalClient:
    def __init__(self):
        self.create_calls: list[dict] = []

    async def create_subscription(self, **kwargs) -> PayPalSubscription:
        self.create_calls.append(kwargs)
        return PayPalSubscription(
            id="I-F44-STUB",
            status="APPROVAL_PENDING",
            approval_url="https://www.sandbox.paypal.com/checkoutnow?token=F44",
        )


class _Acquire:
    def __init__(self, conn):
        self.conn = conn

    async def __aenter__(self):
        return self.conn

    async def __aexit__(self, exc_type, exc, traceback):
        return False


class _Pool:
    def __init__(self, conn):
        self.conn = conn

    def acquire(self):
        return _Acquire(self.conn)


def _plan(
    plan_id: int = 11,
    *,
    tier_id: int = 7,
    period: str = "monthly",
    price: str = "25.00",
    paypal_plan_id: str = "P-F44-MONTHLY",
) -> dict:
    return {
        "id": plan_id,
        "tier_id": tier_id,
        "period": period,
        "price_usd": Decimal(price),
        "paypal_plan_id": paypal_plan_id,
    }


def test_build_custom_id_round_trips_through_real_webhook_parser():
    custom_id = build_custom_id(123456789, 42)

    assert custom_id == "tg:123456789:42"
    assert _telegram_custom_id(custom_id) == (123456789, 42)


@pytest.mark.parametrize("user_id,tier_id", [(0, 1), (1, 0), (-1, 1), (1, -1)])
def test_build_custom_id_rejects_non_positive_ids(user_id, tier_id):
    with pytest.raises(ValueError):
        build_custom_id(user_id, tier_id)


def test_select_plan_options_covers_zero_one_and_multiple_plans():
    no_plan = select_plan_options([])
    direct = select_plan_options([_plan()])
    menu = select_plan_options([_plan(), _plan(12, period="annual")])

    assert no_plan.mode is PlanChoiceMode.UNAVAILABLE
    assert no_plan.direct_plan is None
    assert direct.mode is PlanChoiceMode.DIRECT
    assert direct.direct_plan["id"] == 11
    assert menu.mode is PlanChoiceMode.MENU
    assert [plan["id"] for plan in menu.plans] == [11, 12]


def test_format_pay_prompt_is_spanish_and_names_tier_period_and_price():
    prompt = format_pay_prompt({"name": "VIP Swing"}, _plan(price="99.90"))

    assert prompt == (
        "Completá el pago de VIP Swing (Mensual, USD 99.90) en PayPal. "
        "Tu acceso se activará cuando PayPal confirme el pago."
    )


def test_redirect_urls_default_to_distinct_bot_deep_links():
    return_url, cancel_url = resolve_redirect_urls(
        bot_username="@budai_onboarding_bot",
        return_url=None,
        cancel_url=None,
    )

    assert return_url == "https://t.me/budai_onboarding_bot?start=paypal_approved"
    assert cancel_url == "https://t.me/budai_onboarding_bot?start=paypal_cancelled"


def test_redirect_urls_require_https_when_no_valid_bot_username():
    with pytest.raises(PaymentConfigurationError):
        resolve_redirect_urls(
            bot_username="",
            return_url="http://inseguro.example/return",
            cancel_url="https://seguro.example/cancel",
        )


def test_request_id_is_stable_for_the_same_callback_and_plan():
    first = build_request_id("callback-1", 123, 7, 11)
    repeated = build_request_id("callback-1", 123, 7, 11)
    another_plan = build_request_id("callback-1", 123, 7, 12)

    assert first == repeated
    assert first != another_plan
    assert len(first) == 36


async def _insert_tier(db_conn, slug: str, *, active: bool = True) -> int:
    return await db_conn.fetchval(
        """INSERT INTO telegram_tiers (name, slug, is_active)
           VALUES ($1, $1, $2)
           RETURNING id""",
        slug,
        active,
    )


async def _insert_plan(
    db_conn,
    tier_id: int,
    *,
    period: str,
    paypal_plan_id: str | None,
    active: bool = True,
    price_usd: str | None = "25.00",
) -> int:
    return await db_conn.fetchval(
        """INSERT INTO telegram_tier_plans
                  (tier_id, period, price_usdt, price_usd,
                   paypal_plan_id, is_active)
           VALUES ($1, $2, 25.00, $3, $4, $5)
           RETURNING id""",
        tier_id,
        period,
        Decimal(price_usd) if price_usd is not None else None,
        paypal_plan_id,
        active,
    )


@pytest.mark.asyncio
async def test_fetch_active_plans_filters_tier_and_paypal_eligibility_in_order(
    db_conn,
):
    tier_id = await _insert_tier(db_conn, "f44-plans-target")
    other_tier_id = await _insert_tier(db_conn, "f44-plans-other")
    annual_id = await _insert_plan(
        db_conn,
        tier_id,
        period="annual",
        paypal_plan_id="P-F44-ANNUAL",
    )
    monthly_id = await _insert_plan(
        db_conn,
        tier_id,
        period="monthly",
        paypal_plan_id="P-F44-MONTHLY",
    )
    await _insert_plan(
        db_conn,
        tier_id,
        period="quarterly",
        paypal_plan_id="P-F44-INACTIVE",
        active=False,
    )
    await _insert_plan(
        db_conn,
        tier_id,
        period="semiannual",
        paypal_plan_id=None,
    )
    await _insert_plan(
        db_conn,
        other_tier_id,
        period="monthly",
        paypal_plan_id="P-F44-OTHER-TIER",
    )

    plans = await db.fetch_active_plans(db_conn, tier_id)

    assert [row["id"] for row in plans] == [monthly_id, annual_id]
    assert all(row["tier_id"] == tier_id for row in plans)


def _activation_event(
    *,
    event_id: str,
    user_id: int,
    tier_id: int,
    paypal_plan_id: str,
    subscription_id: str,
) -> dict:
    return {
        "id": event_id,
        "event_type": "BILLING.SUBSCRIPTION.ACTIVATED",
        "create_time": "2026-07-22T15:00:00Z",
        "resource": {
            "id": subscription_id,
            "plan_id": paypal_plan_id,
            "custom_id": build_custom_id(user_id, tier_id),
            "status": "ACTIVE",
            "subscriber": {
                "payer_id": "PAYER-F44",
                "email_address": "f44@example.com",
            },
            "billing_info": {"next_billing_time": "2026-08-22T15:00:00Z"},
        },
    }


@pytest.mark.asyncio
async def test_webhook_activation_updates_only_the_selected_trial_membership(
    client,
    db_conn,
    monkeypatch,
):
    user_id = 9544001
    tier_a = await _insert_tier(db_conn, "f44-webhook-a")
    tier_b = await _insert_tier(db_conn, "f44-webhook-b")
    plan_a = await _insert_plan(
        db_conn,
        tier_a,
        period="monthly",
        paypal_plan_id="P-F44-WEBHOOK-A",
    )
    await _insert_plan(
        db_conn,
        tier_b,
        period="monthly",
        paypal_plan_id="P-F44-WEBHOOK-B",
    )
    await db.upsert_identity(db_conn, user_id, "f44_user", "campana-f44")
    await db_conn.executemany(
        """INSERT INTO telegram_memberships
                  (telegram_user_id, tier_id, status, channel_state, source_ref)
           VALUES ($1, $2, 'trialing', 'invited', 'campana-f44')""",
        [(user_id, tier_a), (user_id, tier_b)],
    )
    monkeypatch.setattr(paypal_webhook_api, "_verifier", _VerifiedWebhook())
    event = _activation_event(
        event_id="WH-F44-TRIAL-UPGRADE",
        user_id=user_id,
        tier_id=tier_a,
        paypal_plan_id="P-F44-WEBHOOK-A",
        subscription_id="I-F44-TRIAL-UPGRADE",
    )

    response = await client.post("/webhook/paypal", json=event)

    assert response.status_code == 200, response.text
    selected = await db_conn.fetchrow(
        """SELECT status, tier_plan_id, paypal_subscription_id, source_ref
             FROM telegram_memberships
            WHERE telegram_user_id = $1 AND tier_id = $2""",
        user_id,
        tier_a,
    )
    untouched = await db_conn.fetchrow(
        """SELECT status, tier_plan_id, paypal_subscription_id, source_ref
             FROM telegram_memberships
            WHERE telegram_user_id = $1 AND tier_id = $2""",
        user_id,
        tier_b,
    )
    assert selected["status"] == "active"
    assert selected["tier_plan_id"] == plan_a
    assert selected["paypal_subscription_id"] == "I-F44-TRIAL-UPGRADE"
    assert selected["source_ref"] == "campana-f44"
    assert dict(untouched) == {
        "status": "trialing",
        "tier_plan_id": None,
        "paypal_subscription_id": None,
        "source_ref": "campana-f44",
    }


@pytest.mark.asyncio
async def test_direct_payment_webhook_keeps_bot_origin_eligible_for_dm_delivery(
    client,
    db_conn,
    monkeypatch,
):
    user_id = 9544002
    tier_id = await _insert_tier(db_conn, "f44-direct-dm")
    await _insert_plan(
        db_conn,
        tier_id,
        period="annual",
        paypal_plan_id="P-F44-DIRECT-DM",
        price_usd="240.00",
    )
    await db.upsert_identity(db_conn, user_id, "direct_user", "anuncio-directo")
    monkeypatch.setattr(paypal_webhook_api, "_verifier", _VerifiedWebhook())
    event = _activation_event(
        event_id="WH-F44-DIRECT-DM",
        user_id=user_id,
        tier_id=tier_id,
        paypal_plan_id="P-F44-DIRECT-DM",
        subscription_id="I-F44-DIRECT-DM",
    )

    response = await client.post("/webhook/paypal", json=event)

    assert response.status_code == 200, response.text
    membership = await db_conn.fetchrow(
        """SELECT status, source_ref
             FROM telegram_memberships
            WHERE telegram_user_id = $1 AND tier_id = $2""",
        user_id,
        tier_id,
    )
    assert dict(membership) == {
        "status": "active",
        "source_ref": "anuncio-directo",
    }
    assert decide_action(
        membership["status"],
        "none",
        None,
        datetime(2026, 7, 22, 15, tzinfo=timezone.utc),
    ) == "grant"

    # Simula el output del gate F4.0 y verifica el input real del loop DM F4.3.
    await db_conn.execute(
        """UPDATE telegram_memberships
              SET channel_state = 'invited',
                  invite_link = 'https://t.me/+f44-direct'
            WHERE telegram_user_id = $1 AND tier_id = $2""",
        user_id,
        tier_id,
    )
    pending = await db.fetch_pending_dm_deliveries(db_conn, limit=10)
    assert [(row["telegram_user_id"], row["tier_id"]) for row in pending] == [
        (user_id, tier_id)
    ]


@pytest.mark.asyncio
async def test_single_plan_handler_uses_real_contract_and_returns_approval_button(
    monkeypatch,
):
    tier = {"id": 7, "name": "VIP Scalping", "slug": "vip-scalping"}
    plan = _plan()
    identity = {"email": "telegram@example.com"}
    conn = object()
    stub = _StubPayPalClient()
    message = Mock(spec=Message)
    message.answer = AsyncMock()
    callback = SimpleNamespace(
        id="callback-f44",
        data="pay:7",
        from_user=SimpleNamespace(id=123456789),
        message=message,
        answer=AsyncMock(),
    )

    async def _pool():
        return _Pool(conn)

    monkeypatch.setattr(onboarding_main, "_ensure_pool", _pool)
    monkeypatch.setattr(
        onboarding_main.db,
        "fetch_identity",
        AsyncMock(return_value=identity),
    )
    monkeypatch.setattr(
        onboarding_main.db,
        "fetch_active_tier",
        AsyncMock(return_value=tier),
    )
    monkeypatch.setattr(
        onboarding_main.db,
        "fetch_active_plans",
        AsyncMock(return_value=[plan]),
    )
    monkeypatch.setattr(onboarding_main, "_paypal_client", stub)
    monkeypatch.setenv("ONBOARDING_BOT_USERNAME", "budai_onboarding_bot")
    monkeypatch.delenv("ONBOARDING_PAYPAL_RETURN_URL", raising=False)
    monkeypatch.delenv("ONBOARDING_PAYPAL_CANCEL_URL", raising=False)

    await onboarding_main.on_payment(callback)

    assert len(stub.create_calls) == 1
    call = stub.create_calls[0]
    assert call["plan_id"] == "P-F44-MONTHLY"
    assert call["custom_id"] == "tg:123456789:7"
    assert call["email"] == "telegram@example.com"
    assert call["return_url"].endswith("?start=paypal_approved")
    assert call["cancel_url"].endswith("?start=paypal_cancelled")
    callback.answer.assert_awaited_once_with("Preparando tu enlace de pago…")
    sent = message.answer.await_args
    assert "VIP Scalping" in sent.args[0]
    button = sent.kwargs["reply_markup"].inline_keyboard[0][0]
    assert button.text == "💳 Pagar en PayPal"
    assert button.url == "https://www.sandbox.paypal.com/checkoutnow?token=F44"


@pytest.mark.asyncio
async def test_multiple_plan_handler_shows_period_menu_before_calling_paypal(
    monkeypatch,
):
    tier = {"id": 7, "name": "VIP Scalping", "slug": "vip-scalping"}
    plans = [
        _plan(),
        _plan(
            12,
            period="annual",
            price="240.00",
            paypal_plan_id="P-F44-ANNUAL",
        ),
    ]
    conn = object()
    stub = _StubPayPalClient()
    message = Mock(spec=Message)
    message.answer = AsyncMock()
    callback = SimpleNamespace(
        id="callback-f44-menu",
        data="pay:7",
        from_user=SimpleNamespace(id=123456789),
        message=message,
        answer=AsyncMock(),
    )

    async def _pool():
        return _Pool(conn)

    monkeypatch.setattr(onboarding_main, "_ensure_pool", _pool)
    monkeypatch.setattr(
        onboarding_main.db,
        "fetch_identity",
        AsyncMock(return_value={"email": None}),
    )
    monkeypatch.setattr(
        onboarding_main.db,
        "fetch_active_tier",
        AsyncMock(return_value=tier),
    )
    monkeypatch.setattr(
        onboarding_main.db,
        "fetch_active_plans",
        AsyncMock(return_value=plans),
    )
    monkeypatch.setattr(onboarding_main, "_paypal_client", stub)

    await onboarding_main.on_payment(callback)

    assert stub.create_calls == []
    callback.answer.assert_awaited_once_with()
    sent = message.answer.await_args
    assert sent.args[0] == "Elegí el período para VIP Scalping:"
    markup = sent.kwargs["reply_markup"]
    assert [row[0].text for row in markup.inline_keyboard] == [
        "Mensual · USD 25.00",
        "Anual · USD 240.00",
    ]
    assert [row[0].callback_data for row in markup.inline_keyboard] == [
        "pay_plan:7:11",
        "pay_plan:7:12",
    ]
