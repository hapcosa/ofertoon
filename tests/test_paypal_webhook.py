"""Contrato seguro de POST /api/payments/paypal/webhook."""
from __future__ import annotations

import base64
from datetime import datetime, timedelta, timezone
import json
import zlib

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.x509.oid import NameOID
import pytest

from subscriptions.paypal import webhook as paypal_webhook_api


class _StubVerifier:
    def __init__(self, result: bool):
        self.result = result

    async def verify(self, raw_body, headers):
        return self.result


async def _post(client, monkeypatch, event: dict, *, verified: bool = True):
    monkeypatch.setattr(paypal_webhook_api, "_verifier", _StubVerifier(verified))
    return await client.post("/webhook/paypal", json=event)


async def _paypal_plan(db_conn, *, paypal_plan_id: str = "P-TEST-MONTHLY"):
    tier_id = await db_conn.fetchval(
        """INSERT INTO telegram_tiers (name, slug, telegram_channel_id)
             VALUES ('Pro', $1, -1001234567890)
          RETURNING id""",
        f"pro-{paypal_plan_id.lower()}",
    )
    tier_plan_id = await db_conn.fetchval(
        """INSERT INTO telegram_tier_plans
               (tier_id, period, price_usdt, price_usd, paypal_plan_id)
             VALUES ($1, 'monthly', 50.00, 50.00, $2)
          RETURNING id""",
        tier_id,
        paypal_plan_id,
    )
    return tier_id, tier_plan_id


async def _membership(db_conn, telegram_user_id: int = 123456789):
    return await db_conn.fetchrow(
        "SELECT * FROM telegram_memberships WHERE telegram_user_id = $1",
        telegram_user_id,
    )


def _subscription_event(
    event_id: str,
    event_type: str,
    *,
    created: str = "2026-07-16T12:00:00Z",
    telegram_id: int = 123456789,
    plan_id: str = "P-TEST-MONTHLY",
    subscription_id: str = "I-TEST-SUBSCRIPTION",
    status: str = "ACTIVE",
    custom_id: str | None = None,
) -> dict:
    return {
        "id": event_id,
        "event_type": event_type,
        "create_time": created,
        "resource": {
            "id": subscription_id,
            "plan_id": plan_id,
            "custom_id": custom_id if custom_id is not None else f"tg:{telegram_id}",
            "status": status,
            "subscriber": {
                "payer_id": "PAYER-123",
                "email_address": "buyer@example.com",
            },
            "billing_info": {"next_billing_time": "2026-08-16T12:00:00Z"},
        },
    }


@pytest.mark.asyncio
async def test_invalid_signature_is_rejected_without_persistence(
    client, db_conn, monkeypatch
):
    event = _subscription_event(
        "WH-BAD-SIGNATURE", "BILLING.SUBSCRIPTION.ACTIVATED"
    )
    response = await _post(client, monkeypatch, event, verified=False)
    assert response.status_code == 401
    assert await db_conn.fetchval("SELECT COUNT(*) FROM paypal_webhook_events") == 0


@pytest.mark.asyncio
async def test_activation_maps_plan_and_telegram_identity(
    client, db_conn, monkeypatch
):
    tier_id, tier_plan_id = await _paypal_plan(db_conn)
    event = _subscription_event(
        "WH-ACTIVATED-1", "BILLING.SUBSCRIPTION.ACTIVATED"
    )

    response = await _post(client, monkeypatch, event)

    assert response.status_code == 200, response.text
    assert response.json() == {"status": "accepted", "duplicate": False}
    # Identidad en telegram_subscribers; estado de cobro en telegram_memberships.
    identity = await db_conn.fetchrow(
        "SELECT email FROM telegram_subscribers WHERE telegram_user_id = 123456789"
    )
    assert identity["email"] == "buyer@example.com"
    membership = await _membership(db_conn)
    assert membership["payment_provider"] == "paypal"
    assert membership["paypal_subscription_id"] == "I-TEST-SUBSCRIPTION"
    assert membership["paypal_payer_id"] == "PAYER-123"
    assert membership["tier_id"] == tier_id
    assert membership["tier_plan_id"] == tier_plan_id
    assert membership["status"] == "active"
    assert membership["current_period_end"] == datetime(
        2026, 8, 16, 12, tzinfo=timezone.utc
    )
    audit = await db_conn.fetchrow(
        "SELECT processing_status, processing_error FROM paypal_webhook_events"
    )
    assert audit["processing_status"] == "processed"
    assert audit["processing_error"] is None


@pytest.mark.asyncio
async def test_duplicate_event_does_not_apply_twice(client, db_conn, monkeypatch):
    await _paypal_plan(db_conn)
    event = _subscription_event(
        "WH-DUPLICATE-1", "BILLING.SUBSCRIPTION.ACTIVATED"
    )

    first = await _post(client, monkeypatch, event)
    second = await _post(client, monkeypatch, event)

    assert first.json()["duplicate"] is False
    assert second.json()["duplicate"] is True
    assert await db_conn.fetchval("SELECT COUNT(*) FROM paypal_webhook_events") == 1
    assert await db_conn.fetchval("SELECT COUNT(*) FROM telegram_subscribers") == 1
    assert await db_conn.fetchval("SELECT COUNT(*) FROM telegram_memberships") == 1


@pytest.mark.asyncio
async def test_unknown_plan_is_audited_but_never_grants_access(
    client, db_conn, monkeypatch
):
    event = _subscription_event(
        "WH-UNKNOWN-PLAN",
        "BILLING.SUBSCRIPTION.ACTIVATED",
        plan_id="P-NOT-OURS",
    )

    response = await _post(client, monkeypatch, event)

    assert response.status_code == 200
    assert await db_conn.fetchval("SELECT COUNT(*) FROM telegram_subscribers") == 0
    assert await db_conn.fetchval("SELECT COUNT(*) FROM telegram_memberships") == 0
    audit = await db_conn.fetchrow(
        "SELECT processing_status, processing_error FROM paypal_webhook_events"
    )
    assert audit["processing_status"] == "rejected"
    assert "unknown or inactive PayPal plan" in audit["processing_error"]


@pytest.mark.asyncio
async def test_activation_with_explicit_tier_suffix(client, db_conn, monkeypatch):
    """custom_id `tg:<user>:<tier>` (F4) mapea a la membresía correcta."""
    tier_id, tier_plan_id = await _paypal_plan(db_conn)
    event = _subscription_event(
        "WH-ACT-TIERED",
        "BILLING.SUBSCRIPTION.ACTIVATED",
        custom_id=f"tg:123456789:{tier_id}",
    )

    response = await _post(client, monkeypatch, event)

    assert response.status_code == 200, response.text
    membership = await _membership(db_conn)
    assert membership["tier_id"] == tier_id
    assert membership["tier_plan_id"] == tier_plan_id
    assert membership["status"] == "active"


@pytest.mark.asyncio
async def test_custom_id_tier_conflicting_with_plan_is_rejected(
    client, db_conn, monkeypatch
):
    """Si el tier del custom_id no coincide con el del plan, se rechaza sin acceso."""
    tier_id, _ = await _paypal_plan(db_conn)
    event = _subscription_event(
        "WH-ACT-TIER-CONFLICT",
        "BILLING.SUBSCRIPTION.ACTIVATED",
        custom_id=f"tg:123456789:{tier_id + 9999}",
    )

    response = await _post(client, monkeypatch, event)

    assert response.status_code == 200
    assert await db_conn.fetchval("SELECT COUNT(*) FROM telegram_memberships") == 0
    audit = await db_conn.fetchval(
        """SELECT processing_error FROM paypal_webhook_events
            WHERE event_id = 'WH-ACT-TIER-CONFLICT'"""
    )
    assert "custom_id tier conflicts with PayPal plan" in audit


@pytest.mark.asyncio
async def test_out_of_order_terminal_event_cannot_override_newer_state(
    client, db_conn, monkeypatch
):
    await _paypal_plan(db_conn)
    active = _subscription_event(
        "WH-ACTIVE-NEWER",
        "BILLING.SUBSCRIPTION.ACTIVATED",
        created="2026-07-16T12:00:00Z",
    )
    canceled = _subscription_event(
        "WH-CANCEL-OLDER",
        "BILLING.SUBSCRIPTION.CANCELLED",
        created="2026-07-16T11:00:00Z",
        status="CANCELLED",
    )
    assert (await _post(client, monkeypatch, active)).status_code == 200

    response = await _post(client, monkeypatch, canceled)

    assert response.status_code == 200
    assert await db_conn.fetchval(
        "SELECT status FROM telegram_memberships WHERE telegram_user_id = 123456789"
    ) == "active"
    audit = await db_conn.fetchrow(
        """SELECT processing_status, processing_error
             FROM paypal_webhook_events WHERE event_id = 'WH-CANCEL-OLDER'"""
    )
    assert audit["processing_status"] == "ignored"
    assert "out-of-order" in audit["processing_error"]


@pytest.mark.asyncio
async def test_completed_payment_requires_exact_usd_price(
    client, db_conn, monkeypatch
):
    await _paypal_plan(db_conn)
    active = _subscription_event(
        "WH-ACTIVE-PAYMENT", "BILLING.SUBSCRIPTION.ACTIVATED"
    )
    assert (await _post(client, monkeypatch, active)).status_code == 200
    payment = {
        "id": "WH-PAYMENT-COMPLETED",
        "event_type": "PAYMENT.SALE.COMPLETED",
        "create_time": "2026-07-16T12:05:00Z",
        "resource": {
            "id": "SALE-1",
            "billing_agreement_id": "I-TEST-SUBSCRIPTION",
            "amount": {"total": "50.00", "currency": "USD"},
        },
    }

    response = await _post(client, monkeypatch, payment)

    assert response.status_code == 200
    assert await db_conn.fetchval(
        "SELECT paypal_last_payment_at FROM telegram_memberships"
    ) == datetime(2026, 7, 16, 12, 5, tzinfo=timezone.utc)

    mismatch = {
        **payment,
        "id": "WH-PAYMENT-MISMATCH",
        "resource": {
            **payment["resource"],
            "amount": {"total": "5.00", "currency": "USD"},
        },
    }
    assert (await _post(client, monkeypatch, mismatch)).status_code == 200
    status = await db_conn.fetchval(
        """SELECT processing_status FROM paypal_webhook_events
            WHERE event_id = 'WH-PAYMENT-MISMATCH'"""
    )
    assert status == "rejected"


def _payment_event(
    event_id: str,
    event_type: str,
    *,
    created: str,
    amount: str = "50.00",
    currency: str = "USD",
    subscription_id: str = "I-TEST-SUBSCRIPTION",
) -> dict:
    return {
        "id": event_id,
        "event_type": event_type,
        "create_time": created,
        "resource": {
            "id": f"SALE-{event_id}",
            "billing_agreement_id": subscription_id,
            "amount": {"total": amount, "currency": currency},
        },
    }


@pytest.mark.asyncio
async def test_out_of_order_completed_payment_does_not_reactivate_past_due(
    client, db_conn, monkeypatch
):
    """Un pago viejo entregado después de un evento de riesgo más nuevo no reactiva."""
    await _paypal_plan(db_conn)
    activated = _subscription_event(
        "WH-ACT-A", "BILLING.SUBSCRIPTION.ACTIVATED", created="2026-07-16T12:00:00Z"
    )
    refunded = _payment_event(
        "WH-REFUND-NEW", "PAYMENT.SALE.REFUNDED", created="2026-07-16T13:00:00Z"
    )
    old_payment = _payment_event(
        "WH-PAY-OLD", "PAYMENT.SALE.COMPLETED", created="2026-07-16T11:00:00Z"
    )
    assert (await _post(client, monkeypatch, activated)).status_code == 200
    assert (await _post(client, monkeypatch, refunded)).status_code == 200
    assert await db_conn.fetchval(
        "SELECT status FROM telegram_memberships WHERE telegram_user_id = 123456789"
    ) == "past_due"

    # El pago llega tarde pero es más viejo que el reembolso: no debe reactivar.
    assert (await _post(client, monkeypatch, old_payment)).status_code == 200

    row = await db_conn.fetchrow(
        """SELECT status, paypal_last_event_at, paypal_last_payment_at
             FROM telegram_memberships WHERE telegram_user_id = 123456789"""
    )
    assert row["status"] == "past_due"
    # El evento de riesgo (13:00) sigue siendo el último aplicado.
    assert row["paypal_last_event_at"] == datetime(
        2026, 7, 16, 13, tzinfo=timezone.utc
    )
    # El pago (aunque viejo) se conserva como el último pago conocido.
    assert row["paypal_last_payment_at"] == datetime(
        2026, 7, 16, 11, tzinfo=timezone.utc
    )
    audit = await db_conn.fetchval(
        "SELECT processing_status FROM paypal_webhook_events WHERE event_id = 'WH-PAY-OLD'"
    )
    assert audit == "processed"


@pytest.mark.asyncio
async def test_out_of_order_risk_event_does_not_downgrade_active(
    client, db_conn, monkeypatch
):
    """Un evento de riesgo viejo entregado después de un pago más nuevo no degrada."""
    await _paypal_plan(db_conn)
    activated = _subscription_event(
        "WH-ACT-B", "BILLING.SUBSCRIPTION.ACTIVATED", created="2026-07-16T12:00:00Z"
    )
    new_payment = _payment_event(
        "WH-PAY-NEW", "PAYMENT.SALE.COMPLETED", created="2026-07-16T13:00:00Z"
    )
    old_refund = _payment_event(
        "WH-REFUND-OLD", "PAYMENT.SALE.REFUNDED", created="2026-07-16T11:00:00Z"
    )
    assert (await _post(client, monkeypatch, activated)).status_code == 200
    assert (await _post(client, monkeypatch, new_payment)).status_code == 200
    assert await db_conn.fetchval(
        "SELECT status FROM telegram_memberships WHERE telegram_user_id = 123456789"
    ) == "active"

    # El reembolso llega tarde pero es más viejo que el pago: no debe degradar.
    assert (await _post(client, monkeypatch, old_refund)).status_code == 200

    row = await db_conn.fetchrow(
        """SELECT status, paypal_last_event_at
             FROM telegram_memberships WHERE telegram_user_id = 123456789"""
    )
    assert row["status"] == "active"
    assert row["paypal_last_event_at"] == datetime(
        2026, 7, 16, 13, tzinfo=timezone.utc
    )
    audit = await db_conn.fetchval(
        "SELECT processing_status FROM paypal_webhook_events WHERE event_id = 'WH-REFUND-OLD'"
    )
    assert audit == "processed"


@pytest.mark.asyncio
async def test_locally_deactivated_plan_still_accepts_existing_subscription(
    client, db_conn, monkeypatch
):
    """Un plan desactivado localmente sigue procesando eventos de una suscripción viva."""
    await _paypal_plan(db_conn)
    activated = _subscription_event(
        "WH-ACT-LIVE", "BILLING.SUBSCRIPTION.ACTIVATED", created="2026-07-16T12:00:00Z"
    )
    assert (await _post(client, monkeypatch, activated)).status_code == 200

    await db_conn.execute(
        "UPDATE telegram_tier_plans SET is_active = FALSE WHERE paypal_plan_id = 'P-TEST-MONTHLY'"
    )

    updated = _subscription_event(
        "WH-UPD-INACTIVE-PLAN",
        "BILLING.SUBSCRIPTION.UPDATED",
        created="2026-07-16T13:00:00Z",
        status="ACTIVE",
    )
    assert (await _post(client, monkeypatch, updated)).status_code == 200

    audit = await db_conn.fetchval(
        "SELECT processing_status FROM paypal_webhook_events WHERE event_id = 'WH-UPD-INACTIVE-PLAN'"
    )
    assert audit == "processed"
    assert await db_conn.fetchval(
        "SELECT status FROM telegram_memberships WHERE telegram_user_id = 123456789"
    ) == "active"


@pytest.mark.asyncio
async def test_real_signature_verifier_uses_exact_raw_body(monkeypatch):
    webhook_id = "WEBHOOK-TEST-ID"
    monkeypatch.setenv("PAYPAL_WEBHOOK_ID", webhook_id)
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "api.sandbox.paypal.com")])
    now = datetime.now(timezone.utc)
    certificate = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(private_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=1))
        .not_valid_after(now + timedelta(days=1))
        .sign(private_key, hashes.SHA256())
    )
    pem = certificate.public_bytes(serialization.Encoding.PEM)
    raw_body = json.dumps({"id": "WH-SIGNED"}, separators=(",", ":")).encode()
    transmission_id = "transmission-1"
    transmission_time = "2026-07-16T12:00:00Z"
    crc = zlib.crc32(raw_body) & 0xFFFFFFFF
    message = f"{transmission_id}|{transmission_time}|{webhook_id}|{crc}".encode()
    signature = private_key.sign(message, padding.PKCS1v15(), hashes.SHA256())
    headers = {
        "paypal-transmission-id": transmission_id,
        "paypal-transmission-time": transmission_time,
        "paypal-cert-url": (
            "https://api.sandbox.paypal.com/v1/notifications/certs/CERT-TEST"
        ),
        "paypal-auth-algo": "SHA256withRSA",
        "paypal-transmission-sig": base64.b64encode(signature).decode(),
    }
    verifier = paypal_webhook_api.PayPalWebhookVerifier()

    async def _certificate(_url):
        return pem

    monkeypatch.setattr(verifier, "_fetch_certificate", _certificate)
    assert await verifier.verify(raw_body, headers) is True
    assert await verifier.verify(raw_body + b" ", headers) is False


@pytest.mark.asyncio
async def test_verifier_rejects_non_paypal_certificate_url(monkeypatch):
    monkeypatch.setenv("PAYPAL_WEBHOOK_ID", "WEBHOOK-TEST-ID")
    verifier = paypal_webhook_api.PayPalWebhookVerifier()
    headers = {
        "paypal-transmission-id": "transmission-1",
        "paypal-transmission-time": "2026-07-16T12:00:00Z",
        "paypal-cert-url": "https://attacker.example/cert.pem",
        "paypal-auth-algo": "SHA256withRSA",
        "paypal-transmission-sig": base64.b64encode(b"not-a-signature").decode(),
    }
    assert await verifier.verify(b"{}", headers) is False
