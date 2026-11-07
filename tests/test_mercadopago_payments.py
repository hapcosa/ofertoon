"""Decisiones puras agregadas a subscriptions/bot/payments.py para MercadoPago."""
from __future__ import annotations

from decimal import Decimal

import pytest

from subscriptions.bot.payments import (
    PaymentConfigurationError,
    PaymentProvider,
    PlanChoiceMode,
    build_mp_idempotency_key,
    format_pay_prompt_mercadopago,
    format_provider_button,
    resolve_mercadopago_back_url,
    select_payment_providers,
)


def _plan(
    plan_id: int = 11,
    *,
    period: str = "monthly",
    price_clp: int | None = 6000,
    mercadopago_plan_id: str | None = "MP-F44-MONTHLY",
    paypal_plan_id: str | None = None,
) -> dict:
    return {
        "id": plan_id,
        "period": period,
        "price_clp": price_clp,
        "mercadopago_plan_id": mercadopago_plan_id,
        "paypal_plan_id": paypal_plan_id,
    }


def test_select_payment_providers_both_configured_requires_menu():
    choice = select_payment_providers(_plan(paypal_plan_id="P-F44-MONTHLY"))

    assert choice.mode is PlanChoiceMode.MENU
    assert choice.providers == (PaymentProvider.PAYPAL, PaymentProvider.MERCADOPAGO)


def test_select_payment_providers_mercadopago_only_skips_menu():
    choice = select_payment_providers(_plan())

    assert choice.mode is PlanChoiceMode.DIRECT
    assert choice.direct_provider is PaymentProvider.MERCADOPAGO


def test_select_payment_providers_none_configured_is_unavailable():
    choice = select_payment_providers(_plan(mercadopago_plan_id=None))

    assert choice.mode is PlanChoiceMode.UNAVAILABLE
    assert choice.providers == ()


def test_format_provider_button_is_spanish_and_names_currency():
    assert "PayPal" in format_provider_button(PaymentProvider.PAYPAL)
    assert "USD" in format_provider_button(PaymentProvider.PAYPAL)
    assert "MercadoPago" in format_provider_button(PaymentProvider.MERCADOPAGO)
    assert "CLP" in format_provider_button(PaymentProvider.MERCADOPAGO)


def test_format_pay_prompt_mercadopago_formats_clp_with_dot_thousands():
    prompt = format_pay_prompt_mercadopago({"name": "VIP"}, _plan(price_clp=6000))

    assert prompt == (
        "Completá el pago de VIP (Mensual, CLP $6.000) en MercadoPago. "
        "Tu acceso se activará cuando MercadoPago confirme el pago."
    )


def test_format_pay_prompt_mercadopago_rejects_non_integer_price():
    with pytest.raises(ValueError, match="entero positivo"):
        format_pay_prompt_mercadopago({"name": "VIP"}, _plan(price_clp=Decimal("10.5")))


def test_mp_idempotency_key_is_stable_and_distinct_from_paypal_namespace():
    from subscriptions.bot.payments import build_request_id

    mp_key = build_mp_idempotency_key("callback-1", 123, 7, 11)
    repeated = build_mp_idempotency_key("callback-1", 123, 7, 11)
    paypal_key = build_request_id("callback-1", 123, 7, 11)

    assert mp_key == repeated
    assert mp_key != paypal_key


def test_resolve_mercadopago_back_url_defaults_to_bot_deep_link():
    back_url = resolve_mercadopago_back_url(
        bot_username="@budai_onboarding_bot", back_url=None
    )

    assert back_url == "https://t.me/budai_onboarding_bot?start=mercadopago_approved"


def test_resolve_mercadopago_back_url_requires_https_when_no_valid_bot_username():
    with pytest.raises(PaymentConfigurationError):
        resolve_mercadopago_back_url(bot_username="", back_url="http://inseguro.example")
