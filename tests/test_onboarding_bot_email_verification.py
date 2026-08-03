"""Tests puros, DB-backed y de handlers para onboarding F4.6."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from subscriptions import email as auth_email
from subscriptions.bot import db
from subscriptions.bot import email_verification
from subscriptions.bot import main as onboarding_main
from subscriptions.bot.email_verification import (
    VerifyDecision,
    generate_code,
    hash_code,
    render_code_email,
    verify_code_attempt,
)


NOW = datetime(2026, 7, 24, 12, 0, tzinfo=timezone.utc)


@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        ({}, "ok"),
        ({"submitted_code": "999999"}, "mismatch"),
        ({"expires_at": NOW - timedelta(seconds=1)}, "expired"),
        ({"attempts": 5}, "too_many_attempts"),
        ({"consumed_at": NOW - timedelta(minutes=1)}, "already_consumed"),
    ],
)
def test_verify_code_attempt_reason_matrix(overrides, expected):
    values = {
        "submitted_code": "123456",
        "stored_hash": hash_code("123456"),
        "expires_at": NOW + timedelta(minutes=15),
        "attempts": 0,
        "consumed_at": None,
        "max_attempts": 5,
        "now": NOW,
    }
    values.update(overrides)

    assert verify_code_attempt(**values).reason == expected


def test_verify_code_attempt_precedence_and_constant_time_compare(monkeypatch):
    calls = []

    def fake_compare_digest(left, right):
        calls.append((left, right))
        return True

    monkeypatch.setattr(email_verification.hmac, "compare_digest", fake_compare_digest)
    decision = verify_code_attempt(
        submitted_code="123456",
        stored_hash=hash_code("123456"),
        expires_at=NOW + timedelta(minutes=1),
        attempts=0,
        consumed_at=None,
        max_attempts=5,
        now=NOW,
    )
    assert decision.reason == "ok"
    assert calls == [(hash_code("123456"), hash_code("123456"))]

    consumed_wins = verify_code_attempt(
        submitted_code="incorrecto",
        stored_hash=hash_code("123456"),
        expires_at=NOW - timedelta(days=1),
        attempts=99,
        consumed_at=NOW,
        max_attempts=5,
        now=NOW,
    )
    assert consumed_wins.reason == "already_consumed"
    assert len(calls) == 1


def test_hash_and_generated_code_contract():
    assert hash_code("123456") == hash_code("123456")
    assert hash_code("123456") != hash_code("654321")
    assert len(hash_code("123456")) == 64

    for _ in range(50):
        code = generate_code()
        assert len(code) == 6
        assert code.isdigit()


def test_render_code_email_escapes_tier_and_contains_code():
    subject, html = render_code_email(code="012345", tier_name="<VIP>")

    assert "OfertasCL" in subject
    assert "012345" in html
    assert "&lt;VIP&gt;" in html
    assert "<VIP>" not in html


async def _insert_identity(db_conn, user_id: int) -> None:
    await db.upsert_identity(db_conn, user_id, f"user-{user_id}", None)


async def _insert_tier(db_conn, slug: str) -> int:
    return await db_conn.fetchval(
        """INSERT INTO telegram_tiers (name, slug, is_active)
           VALUES ($1, $1, TRUE)
           RETURNING id""",
        slug,
    )


@pytest.mark.asyncio
async def test_create_and_consume_email_verification_happy_path(db_conn):
    user_id = 94601
    await _insert_identity(db_conn, user_id)
    await db.create_email_verification(
        db_conn,
        user_id,
        "persona@example.com",
        hash_code("123456"),
        NOW + timedelta(minutes=15),
    )

    result = await db.consume_email_verification(
        db_conn,
        user_id,
        "123456",
        max_attempts=5,
        now=NOW,
    )
    second = await db.consume_email_verification(
        db_conn,
        user_id,
        "123456",
        max_attempts=5,
        now=NOW + timedelta(seconds=1),
    )
    verification = await db_conn.fetchrow(
        """SELECT consumed_at, attempts
             FROM telegram_email_verifications
            WHERE telegram_user_id = $1""",
        user_id,
    )
    verified_at = await db_conn.fetchval(
        """SELECT email_verified_at
             FROM telegram_subscribers
            WHERE telegram_user_id = $1""",
        user_id,
    )

    assert result.ok is True
    assert result.email_normalized == "persona@example.com"
    assert verification["consumed_at"] == NOW
    assert verified_at == NOW
    assert second.decision.reason == "already_consumed"


@pytest.mark.asyncio
async def test_wrong_code_increments_until_too_many_attempts(db_conn):
    user_id = 94602
    await _insert_identity(db_conn, user_id)
    await db.create_email_verification(
        db_conn,
        user_id,
        "intentos@example.com",
        hash_code("123456"),
        NOW + timedelta(minutes=15),
    )

    first = await db.consume_email_verification(
        db_conn,
        user_id,
        "000000",
        max_attempts=2,
        now=NOW,
    )
    second = await db.consume_email_verification(
        db_conn,
        user_id,
        "000000",
        max_attempts=2,
        now=NOW,
    )
    third = await db.consume_email_verification(
        db_conn,
        user_id,
        "123456",
        max_attempts=2,
        now=NOW,
    )

    assert first.decision.reason == "mismatch"
    assert first.attempts_remaining == 1
    assert second.decision.reason == "too_many_attempts"
    assert second.attempts_remaining == 0
    assert third.decision.reason == "too_many_attempts"
    assert await db_conn.fetchval(
        """SELECT attempts FROM telegram_email_verifications
            WHERE telegram_user_id = $1""",
        user_id,
    ) == 2
    assert await db_conn.fetchval(
        """SELECT email_verified_at FROM telegram_subscribers
            WHERE telegram_user_id = $1""",
        user_id,
    ) is None


@pytest.mark.asyncio
async def test_expired_code_does_not_consume_or_verify(db_conn):
    user_id = 94603
    await _insert_identity(db_conn, user_id)
    await db.create_email_verification(
        db_conn,
        user_id,
        "vencido@example.com",
        hash_code("123456"),
        NOW - timedelta(seconds=1),
    )

    result = await db.consume_email_verification(
        db_conn,
        user_id,
        "123456",
        max_attempts=5,
        now=NOW,
    )
    row = await db_conn.fetchrow(
        """SELECT attempts, consumed_at FROM telegram_email_verifications
            WHERE telegram_user_id = $1""",
        user_id,
    )

    assert result.decision.reason == "expired"
    assert row["attempts"] == 0
    assert row["consumed_at"] is None
    assert await db_conn.fetchval(
        """SELECT email_verified_at FROM telegram_subscribers
            WHERE telegram_user_id = $1""",
        user_id,
    ) is None


@pytest.mark.asyncio
async def test_new_code_upsert_replaces_pending_state(db_conn):
    user_id = 94604
    await _insert_identity(db_conn, user_id)
    await db.create_email_verification(
        db_conn,
        user_id,
        "primero@example.com",
        hash_code("111111"),
        NOW + timedelta(minutes=1),
    )
    await db.consume_email_verification(
        db_conn,
        user_id,
        "000000",
        max_attempts=5,
        now=NOW,
    )
    consumed = await db.consume_email_verification(
        db_conn,
        user_id,
        "111111",
        max_attempts=5,
        now=NOW,
    )
    assert consumed.ok is True
    await db.create_email_verification(
        db_conn,
        user_id,
        "segundo@example.com",
        hash_code("222222"),
        NOW + timedelta(minutes=15),
    )

    row = await db_conn.fetchrow(
        """SELECT email_normalized, code_hash, expires_at, attempts, consumed_at
             FROM telegram_email_verifications
            WHERE telegram_user_id = $1""",
        user_id,
    )
    assert row["email_normalized"] == "segundo@example.com"
    assert row["code_hash"].strip() == hash_code("222222")
    assert row["expires_at"] == NOW + timedelta(minutes=15)
    assert row["attempts"] == 0
    assert row["consumed_at"] is None


@pytest.mark.asyncio
async def test_shared_sender_without_api_key_never_opens_network(
    monkeypatch,
    caplog,
):
    monkeypatch.setenv("RESEND_API_KEY", "")

    class ForbiddenClient:
        def __init__(self, *args, **kwargs):
            raise AssertionError("No debe abrir red sin RESEND_API_KEY")

    monkeypatch.setattr(auth_email.httpx, "AsyncClient", ForbiddenClient)
    caplog.set_level("INFO")

    sent = await auth_email.send_email(
        to="persona@example.com",
        subject="Código",
        html="<p>123456</p>",
    )

    assert sent is True
    assert "[email-dev]" in caplog.text


class _Acquire:
    def __init__(self, conn):
        self.conn = conn

    async def __aenter__(self):
        return self.conn

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _Pool:
    def __init__(self, conn):
        self.conn = conn

    def acquire(self):
        return _Acquire(self.conn)


class _State:
    def __init__(self, **data):
        self.data = dict(data)
        self.current = None
        self.clear_count = 0

    async def clear(self):
        self.data.clear()
        self.current = None
        self.clear_count += 1

    async def update_data(self, **data):
        self.data.update(data)

    async def set_state(self, state):
        self.current = state

    async def get_data(self):
        return dict(self.data)


class _Message:
    def __init__(self, user_id: int, text: str = ""):
        self.from_user = SimpleNamespace(id=user_id)
        self.text = text
        self.answers = []

    async def answer(self, text, **kwargs):
        self.answers.append((text, kwargs))


def _patch_pool(monkeypatch, db_conn):
    async def ensure_pool():
        return _Pool(db_conn)

    monkeypatch.setattr(onboarding_main, "_ensure_pool", ensure_pool)


@pytest.mark.asyncio
async def test_toggle_off_preserves_direct_f42_grant(
    db_conn,
    monkeypatch,
):
    user_id = 94605
    tier_id = await _insert_tier(db_conn, "toggle-off")
    await _insert_identity(db_conn, user_id)
    _patch_pool(monkeypatch, db_conn)
    monkeypatch.setattr(onboarding_main, "_EMAIL_VERIFICATION", False)

    async def forbidden_sender(**kwargs):
        raise AssertionError("Toggle OFF no debe enviar email")

    async def forbidden_create(*args, **kwargs):
        raise AssertionError("Toggle OFF no debe crear una verificación")

    monkeypatch.setattr(onboarding_main, "send_email", forbidden_sender)
    monkeypatch.setattr(db, "create_email_verification", forbidden_create)
    state = _State(tier_id=tier_id)
    message = _Message(user_id)

    await onboarding_main._process_trial_candidate(
        message,
        state,
        user_id,
        tier_id,
        "directo@example.com",
    )

    identity = await db.fetch_identity(db_conn, user_id)
    membership = await db_conn.fetchrow(
        """SELECT status FROM telegram_memberships
            WHERE telegram_user_id = $1 AND tier_id = $2""",
        user_id,
        tier_id,
    )
    assert identity["trial_used_at"] is not None
    assert await db_conn.fetchval(
        """SELECT email_verified_at FROM telegram_subscribers
            WHERE telegram_user_id = $1""",
        user_id,
    ) is None
    assert membership["status"] == "trialing"
    assert state.current is None
    assert message.answers[-1][0] == "Preparando tu acceso a toggle-off ⏳"


@pytest.mark.asyncio
async def test_toggle_on_handler_sends_code_then_verifies_and_grants(
    db_conn,
    monkeypatch,
):
    user_id = 94606
    tier_id = await _insert_tier(db_conn, "toggle-on")
    await _insert_identity(db_conn, user_id)
    _patch_pool(monkeypatch, db_conn)
    monkeypatch.setattr(onboarding_main, "_EMAIL_VERIFICATION", True)
    monkeypatch.setattr(onboarding_main, "generate_code", lambda: "123456")
    sent_payloads = []

    async def fake_sender(**kwargs):
        sent_payloads.append(kwargs)
        return True

    monkeypatch.setattr(onboarding_main, "send_email", fake_sender)
    state = _State(tier_id=tier_id)
    email_message = _Message(user_id)

    await onboarding_main._process_trial_candidate(
        email_message,
        state,
        user_id,
        tier_id,
        "persona+trial@example.com",
    )

    pending = await db_conn.fetchrow(
        """SELECT email_normalized, code_hash, attempts, consumed_at
             FROM telegram_email_verifications
            WHERE telegram_user_id = $1""",
        user_id,
    )
    assert len(sent_payloads) == 1
    assert sent_payloads[0]["to"] == "persona+trial@example.com"
    assert "123456" in sent_payloads[0]["html"]
    assert pending["email_normalized"] == "persona@example.com"
    assert pending["code_hash"].strip() == hash_code("123456")
    assert pending["attempts"] == 0
    assert pending["consumed_at"] is None
    assert state.current == onboarding_main.TrialFlow.awaiting_code
    assert await db_conn.fetchval(
        """SELECT trial_used_at FROM telegram_subscribers
            WHERE telegram_user_id = $1""",
        user_id,
    ) is None

    code_message = _Message(user_id, " 123456 ")
    await onboarding_main.on_trial_code(code_message, state)

    identity = await db.fetch_identity(db_conn, user_id)
    assert identity["trial_used_at"] is not None
    assert await db_conn.fetchval(
        """SELECT email_verified_at FROM telegram_subscribers
            WHERE telegram_user_id = $1""",
        user_id,
    ) is not None
    assert await db_conn.fetchval(
        """SELECT consumed_at FROM telegram_email_verifications
            WHERE telegram_user_id = $1""",
        user_id,
    ) is not None
    assert await db_conn.fetchval(
        """SELECT status FROM telegram_memberships
            WHERE telegram_user_id = $1 AND tier_id = $2""",
        user_id,
        tier_id,
    ) == "trialing"
    assert state.current is None
    assert code_message.answers[-1][0] == "Preparando tu acceso a toggle-on ⏳"


@pytest.mark.asyncio
async def test_grant_conflict_rolls_back_consumption_and_verified_at(
    db_conn,
    monkeypatch,
):
    user_id = 94609
    tier_id = await _insert_tier(db_conn, "conflicto-atomico")
    await _insert_identity(db_conn, user_id)
    _patch_pool(monkeypatch, db_conn)
    monkeypatch.setattr(onboarding_main, "_EMAIL_VERIFICATION", True)
    monkeypatch.setattr(onboarding_main, "generate_code", lambda: "123456")

    async def fake_sender(**kwargs):
        return True

    monkeypatch.setattr(onboarding_main, "send_email", fake_sender)
    state = _State(tier_id=tier_id)
    await onboarding_main._process_trial_candidate(
        _Message(user_id),
        state,
        user_id,
        tier_id,
        "conflicto@example.com",
    )
    await db_conn.execute(
        """INSERT INTO telegram_memberships
                   (telegram_user_id, tier_id, status, channel_state)
           VALUES ($1, $2, 'active', 'member')""",
        user_id,
        tier_id,
    )

    code_message = _Message(user_id, "123456")
    await onboarding_main.on_trial_code(code_message, state)

    verification = await db_conn.fetchrow(
        """SELECT consumed_at FROM telegram_email_verifications
            WHERE telegram_user_id = $1""",
        user_id,
    )
    assert verification["consumed_at"] is None
    assert await db_conn.fetchval(
        """SELECT email_verified_at FROM telegram_subscribers
            WHERE telegram_user_id = $1""",
        user_id,
    ) is None
    assert await db_conn.fetchval(
        """SELECT trial_used_at FROM telegram_subscribers
            WHERE telegram_user_id = $1""",
        user_id,
    ) is None
    assert code_message.answers[-1][0] == (
        "Ya tenés acceso o un trial en curso para este canal."
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "candidate",
    [
        "email-invalido",
        "persona@mailinator.com",
    ],
)
async def test_rejected_d4a_email_never_creates_or_sends_code(
    db_conn,
    monkeypatch,
    candidate,
):
    user_id = 94607
    tier_id = await _insert_tier(db_conn, f"rechazado-{candidate[:4]}")
    await _insert_identity(db_conn, user_id)
    _patch_pool(monkeypatch, db_conn)
    monkeypatch.setattr(onboarding_main, "_EMAIL_VERIFICATION", True)
    monkeypatch.setattr(
        onboarding_main,
        "_DISPOSABLE_DOMAINS",
        {"mailinator.com"},
    )
    sent_payloads = []

    async def fake_sender(**kwargs):
        sent_payloads.append(kwargs)
        return True

    monkeypatch.setattr(onboarding_main, "send_email", fake_sender)
    state = _State(tier_id=tier_id)

    await onboarding_main._process_trial_candidate(
        _Message(user_id),
        state,
        user_id,
        tier_id,
        candidate,
    )

    assert sent_payloads == []
    assert await db_conn.fetchval(
        """SELECT COUNT(*) FROM telegram_email_verifications
            WHERE telegram_user_id = $1""",
        user_id,
    ) == 0


@pytest.mark.asyncio
async def test_used_trial_never_creates_or_sends_code(
    db_conn,
    monkeypatch,
):
    user_id = 94608
    tier_id = await _insert_tier(db_conn, "trial-ya-usado")
    await db.grant_trial(
        db_conn,
        user_id,
        tier_id,
        "usado@example.com",
        "usado@example.com",
        None,
        7,
    )
    _patch_pool(monkeypatch, db_conn)
    monkeypatch.setattr(onboarding_main, "_EMAIL_VERIFICATION", True)
    sent_payloads = []

    async def fake_sender(**kwargs):
        sent_payloads.append(kwargs)
        return True

    monkeypatch.setattr(onboarding_main, "send_email", fake_sender)
    state = _State(tier_id=tier_id)
    await onboarding_main._process_trial_candidate(
        _Message(user_id),
        state,
        user_id,
        tier_id,
        "usado@example.com",
    )

    assert sent_payloads == []
    assert await db_conn.fetchval(
        """SELECT COUNT(*) FROM telegram_email_verifications
            WHERE telegram_user_id = $1""",
        user_id,
    ) == 0
