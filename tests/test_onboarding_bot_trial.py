"""Tests puros y DB-backed del trial global de onboarding F4.2."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from subscriptions.bot import db
from subscriptions.bot.email_validation import (
    is_disposable,
    load_disposable_domains,
    normalize_email,
)
from subscriptions.bot.trial import evaluate_trial_eligibility


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (" First.Last+promo@GMAIL.com ", "firstlast@gmail.com"),
        ("first.last@googlemail.com", "firstlast@gmail.com"),
        ("User.Name+tag@Example.COM", "user.name@example.com"),
        ("simple@example.org", "simple@example.org"),
    ],
)
def test_normalize_email_returns_canonical_identity(raw, expected):
    assert normalize_email(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "sin-arroba.example.com",
        "persona@localhost",
        "@gmail.com",
        "+tag@gmail.com",
        "persona con espacio@example.com",
        "persona@example",
    ],
)
def test_normalize_email_rejects_invalid_values(raw):
    assert normalize_email(raw) is None


def test_load_disposable_domains_ignores_comments_and_normalizes(tmp_path):
    path = tmp_path / "denylist.txt"
    path.write_text(
        "# comentario\nMailinator.COM\n\ntempmail.com # inline\n",
        encoding="utf-8",
    )

    assert load_disposable_domains(path) == {"mailinator.com", "tempmail.com"}


def test_is_disposable_compares_canonical_domain():
    denylist = {"mailinator.com", "yopmail.com"}

    assert is_disposable("persona@mailinator.com", denylist) is True
    assert is_disposable("persona@example.com", denylist) is False


@pytest.mark.parametrize(
    (
        "email_raw",
        "identity_used",
        "owner_used",
        "expected_allowed",
        "expected_reason",
        "expected_normalized",
    ),
    [
        ("User.Name+tag@example.com", None, None, True, "ok", "user.name@example.com"),
        ("invalido", None, None, False, "invalid_email", None),
        (
            "persona@mailinator.com",
            None,
            None,
            False,
            "disposable",
            "persona@mailinator.com",
        ),
        (
            "persona@example.com",
            datetime(2026, 7, 20, tzinfo=timezone.utc),
            None,
            False,
            "already_used",
            "persona@example.com",
        ),
        (
            "persona@example.com",
            None,
            datetime(2026, 7, 20, tzinfo=timezone.utc),
            False,
            "email_reused",
            "persona@example.com",
        ),
    ],
)
def test_evaluate_trial_eligibility_reason_matrix(
    email_raw,
    identity_used,
    owner_used,
    expected_allowed,
    expected_reason,
    expected_normalized,
):
    decision = evaluate_trial_eligibility(
        email_raw=email_raw,
        denylist={"mailinator.com"},
        identity_trial_used_at=identity_used,
        email_owner_trial_used_at=owner_used,
    )

    assert decision.allowed is expected_allowed
    assert decision.reason == expected_reason
    assert decision.email_normalized == expected_normalized


async def _insert_tier(db_conn, slug: str) -> int:
    return await db_conn.fetchval(
        """INSERT INTO telegram_tiers (name, slug, is_active)
           VALUES ($1, $1, TRUE)
           RETURNING id""",
        slug,
    )


@pytest.mark.asyncio
async def test_grant_trial_persists_identity_and_membership_atomically(db_conn):
    tier_id = await _insert_tier(db_conn, "trial-atomico")
    before = datetime.now(timezone.utc)

    result = await db.grant_trial(
        db_conn,
        user_id=93001,
        tier_id=tier_id,
        email="Persona+tag@example.com",
        email_normalized="persona@example.com",
        source_ref="campana-trial",
        trial_days=7,
    )
    after = datetime.now(timezone.utc)

    assert result.granted is True
    assert result.reason == "ok"
    assert before <= result.trial_used_at <= after
    assert before + timedelta(days=7) <= result.trial_ends_at
    assert result.trial_ends_at <= after + timedelta(days=7)

    identity = await db.fetch_identity(db_conn, 93001)
    membership = await db_conn.fetchrow(
        """SELECT status, channel_state, trial_ends_at, source_ref
             FROM telegram_memberships
            WHERE telegram_user_id = $1 AND tier_id = $2""",
        93001,
        tier_id,
    )
    assert identity["email"] == "Persona+tag@example.com"
    assert identity["email_normalized"] == "persona@example.com"
    assert identity["trial_used_at"] == result.trial_used_at
    assert identity["source_ref"] == "campana-trial"
    assert membership["status"] == "trialing"
    assert membership["channel_state"] == "none"
    assert membership["trial_ends_at"] == result.trial_ends_at
    assert membership["source_ref"] == "campana-trial"


@pytest.mark.asyncio
async def test_grant_trial_double_call_does_not_reopen_or_extend(db_conn):
    tier_id = await _insert_tier(db_conn, "trial-idempotente")
    kwargs = {
        "user_id": 93002,
        "tier_id": tier_id,
        "email": "doble@example.com",
        "email_normalized": "doble@example.com",
        "source_ref": "primera-campana",
        "trial_days": 7,
    }

    first = await db.grant_trial(db_conn, **kwargs)
    second = await db.grant_trial(
        db_conn,
        **{**kwargs, "source_ref": "segunda-campana", "trial_days": 30},
    )

    assert first.granted is True
    assert second.granted is False
    assert second.reason == "already_used"
    assert second.trial_used_at == first.trial_used_at
    assert second.trial_ends_at == first.trial_ends_at
    identity = await db.fetch_identity(db_conn, 93002)
    membership = await db_conn.fetchrow(
        """SELECT trial_ends_at, source_ref
             FROM telegram_memberships
            WHERE telegram_user_id = $1 AND tier_id = $2""",
        93002,
        tier_id,
    )
    assert identity["trial_used_at"] == first.trial_used_at
    assert identity["source_ref"] == "primera-campana"
    assert membership["trial_ends_at"] == first.trial_ends_at
    assert membership["source_ref"] == "primera-campana"
    assert await db_conn.fetchval(
        "SELECT COUNT(*) FROM telegram_memberships WHERE telegram_user_id = $1",
        93002,
    ) == 1


@pytest.mark.asyncio
async def test_cross_account_email_dedup_uses_canonical_gmail(db_conn):
    tier_id = await _insert_tier(db_conn, "trial-dedup-email")
    first = await db.grant_trial(
        db_conn,
        93003,
        tier_id,
        "x@gmail.com",
        "x@gmail.com",
        None,
        7,
    )
    canonical = normalize_email("x+promo@gmail.com")
    owner = await db.find_trial_owner_by_email(db_conn, canonical)

    decision = evaluate_trial_eligibility(
        email_raw="x+promo@gmail.com",
        denylist=set(),
        identity_trial_used_at=None,
        email_owner_trial_used_at=owner["trial_used_at"],
    )

    assert first.granted is True
    assert owner["user_id"] == 93003
    assert decision.allowed is False
    assert decision.reason == "email_reused"

    raced_grant = await db.grant_trial(
        db_conn,
        93004,
        tier_id,
        "x+promo@gmail.com",
        canonical,
        None,
        7,
    )
    assert raced_grant.granted is False
    assert raced_grant.reason == "email_reused"
    assert await db_conn.fetchval(
        "SELECT COUNT(*) FROM telegram_memberships WHERE telegram_user_id = $1",
        93004,
    ) == 0


@pytest.mark.asyncio
async def test_trial_is_global_and_second_tier_is_blocked(db_conn):
    tier_a = await _insert_tier(db_conn, "trial-tier-a")
    tier_b = await _insert_tier(db_conn, "trial-tier-b")
    await db.grant_trial(
        db_conn,
        93005,
        tier_a,
        "global@example.com",
        "global@example.com",
        None,
        7,
    )
    identity = await db.fetch_identity(db_conn, 93005)
    owner = await db.find_trial_owner_by_email(db_conn, "global@example.com")

    decision = evaluate_trial_eligibility(
        email_raw="global@example.com",
        denylist=set(),
        identity_trial_used_at=identity["trial_used_at"],
        email_owner_trial_used_at=owner["trial_used_at"],
    )
    second_tier = await db.grant_trial(
        db_conn,
        93005,
        tier_b,
        "global@example.com",
        "global@example.com",
        None,
        7,
    )

    assert decision.reason == "already_used"
    assert second_tier.granted is False
    assert second_tier.reason == "already_used"
    assert await db_conn.fetchval(
        """SELECT COUNT(*) FROM telegram_memberships
            WHERE telegram_user_id = $1 AND tier_id = $2""",
        93005,
        tier_b,
    ) == 0


@pytest.mark.asyncio
async def test_grant_trial_never_downgrades_active_membership(db_conn):
    tier_id = await _insert_tier(db_conn, "trial-activo-protegido")
    await db.upsert_identity(db_conn, 93006, "miembro", None)
    await db_conn.execute(
        """INSERT INTO telegram_memberships
                   (telegram_user_id, tier_id, status, channel_state)
           VALUES ($1, $2, 'active', 'member')""",
        93006,
        tier_id,
    )

    result = await db.grant_trial(
        db_conn,
        93006,
        tier_id,
        "miembro@example.com",
        "miembro@example.com",
        None,
        7,
    )

    assert result.granted is False
    assert result.reason == "membership_exists"
    assert await db_conn.fetchval(
        """SELECT status FROM telegram_memberships
            WHERE telegram_user_id = $1 AND tier_id = $2""",
        93006,
        tier_id,
    ) == "active"
    assert (await db.fetch_identity(db_conn, 93006))["trial_used_at"] is None
