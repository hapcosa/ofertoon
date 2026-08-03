"""Tests puros y DB-backed de la entrega DM de onboarding F4.3."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from aiogram.exceptions import TelegramForbiddenError
from aiogram.methods import SendMessage
import pytest

from subscriptions.bot import db
from subscriptions.bot.delivery import (
    DeliverySummary,
    classify_send_error,
    deliver_pending,
    format_invite_dm,
)


def _forbidden_error() -> TelegramForbiddenError:
    return TelegramForbiddenError(
        method=SendMessage(chat_id=94000, text="test"),
        message="Forbidden: bot was blocked by the user",
    )


def test_format_invite_dm_includes_spanish_copy_slug_and_link():
    text = format_invite_dm("vip-scalping", "https://t.me/+invite")

    assert text == "Tu acceso a vip-scalping: https://t.me/+invite"


def test_classify_send_error_distinguishes_blocked_and_transient():
    assert classify_send_error(_forbidden_error()) == "blocked"
    assert classify_send_error(ConnectionError("red caída")) == "transient"


async def _seed_delivery(
    db_conn,
    *,
    user_id: int,
    slug: str,
    channel_state: str = "invited",
    invite_link: str | None = "https://t.me/+invite",
    delivered_at: datetime | None = None,
    source_ref: str | None = "campana-f43",
    updated_at: datetime | None = None,
) -> int:
    tier_id = await db_conn.fetchval(
        """INSERT INTO telegram_tiers (name, slug, is_active)
           VALUES ($1, $1, TRUE)
           RETURNING id""",
        slug,
    )
    await db_conn.execute(
        """INSERT INTO telegram_subscribers (telegram_user_id, source_ref)
           VALUES ($1, $2)""",
        user_id,
        source_ref,
    )
    await db_conn.execute(
        """INSERT INTO telegram_memberships
                  (telegram_user_id, tier_id, status, channel_state,
                   invite_link, invite_delivered_at, source_ref, updated_at)
           VALUES ($1, $2, 'active', $3, $4, $5, $6, COALESCE($7, NOW()))""",
        user_id,
        tier_id,
        channel_state,
        invite_link,
        delivered_at,
        source_ref,
        updated_at,
    )
    return tier_id


@pytest.mark.asyncio
async def test_fetch_pending_dm_deliveries_filters_and_respects_limit(db_conn):
    base = datetime(2026, 7, 22, tzinfo=timezone.utc)
    first_tier = await _seed_delivery(
        db_conn,
        user_id=94001,
        slug="dm-primero",
        updated_at=base,
    )
    await _seed_delivery(
        db_conn,
        user_id=94002,
        slug="dm-segundo",
        updated_at=base + timedelta(seconds=1),
    )
    await _seed_delivery(
        db_conn,
        user_id=94004,
        slug="dm-ya-entregado",
        delivered_at=base,
        updated_at=base - timedelta(seconds=3),
    )
    await _seed_delivery(
        db_conn,
        user_id=94005,
        slug="dm-sin-link",
        invite_link=None,
        updated_at=base - timedelta(seconds=2),
    )
    await _seed_delivery(
        db_conn,
        user_id=94006,
        slug="dm-no-invitado",
        channel_state="none",
        updated_at=base - timedelta(seconds=1),
    )
    # Abrió el bot directo (sin deep-link): source_ref NULL. En OfertasCL toda
    # identidad nace en el bot, así que igual DEBE recibir el DM.
    await _seed_delivery(
        db_conn,
        user_id=94007,
        slug="dm-bot-directo",
        source_ref=None,
        updated_at=base + timedelta(seconds=2),
    )

    limited = await db.fetch_pending_dm_deliveries(db_conn, limit=1)
    all_pending = await db.fetch_pending_dm_deliveries(db_conn, limit=10)

    assert len(limited) == 1
    assert limited[0]["telegram_user_id"] == 94001
    assert limited[0]["tier_id"] == first_tier
    assert limited[0]["tier_slug"] == "dm-primero"
    assert [row["telegram_user_id"] for row in all_pending] == [94001, 94002, 94007]


@pytest.mark.asyncio
async def test_deliver_pending_happy_path_is_idempotent(db_conn):
    tiers = {
        94101: await _seed_delivery(
            db_conn,
            user_id=94101,
            slug="dm-happy-a",
        ),
        94102: await _seed_delivery(
            db_conn,
            user_id=94102,
            slug="dm-happy-b",
        ),
    }
    sent: list[tuple[int, str]] = []

    async def send_fn(user_id: int, text: str) -> None:
        sent.append((user_id, text))

    first = await deliver_pending(db_conn, send_fn, limit=50)
    second = await deliver_pending(db_conn, send_fn, limit=50)

    assert first == DeliverySummary(delivered=2, blocked=0, errors=0)
    assert second == DeliverySummary()
    assert [user_id for user_id, _text in sent] == [94101, 94102]
    assert all("Tu acceso a dm-happy-" in text for _user_id, text in sent)
    for user_id, tier_id in tiers.items():
        assert await db_conn.fetchval(
            """SELECT invite_delivered_at
                 FROM telegram_memberships
                WHERE telegram_user_id = $1 AND tier_id = $2""",
            user_id,
            tier_id,
        ) is not None


@pytest.mark.asyncio
async def test_deliver_pending_blocked_keeps_row_and_continues(db_conn):
    blocked_tier = await _seed_delivery(
        db_conn,
        user_id=94201,
        slug="dm-bloqueado",
        updated_at=datetime(2026, 7, 22, tzinfo=timezone.utc),
    )
    delivered_tier = await _seed_delivery(
        db_conn,
        user_id=94202,
        slug="dm-despues-bloqueado",
        updated_at=datetime(2026, 7, 22, tzinfo=timezone.utc)
        + timedelta(seconds=1),
    )
    calls: list[int] = []

    async def send_fn(user_id: int, _text: str) -> None:
        calls.append(user_id)
        if user_id == 94201:
            raise _forbidden_error()

    summary = await deliver_pending(db_conn, send_fn, limit=50)

    assert summary == DeliverySummary(delivered=1, blocked=1, errors=0)
    assert calls == [94201, 94202]
    assert await db_conn.fetchval(
        """SELECT invite_delivered_at FROM telegram_memberships
            WHERE telegram_user_id = $1 AND tier_id = $2""",
        94201,
        blocked_tier,
    ) is None
    assert await db_conn.fetchval(
        """SELECT invite_delivered_at FROM telegram_memberships
            WHERE telegram_user_id = $1 AND tier_id = $2""",
        94202,
        delivered_tier,
    ) is not None


@pytest.mark.asyncio
async def test_deliver_pending_transient_error_keeps_row_and_continues(db_conn):
    failed_tier = await _seed_delivery(
        db_conn,
        user_id=94301,
        slug="dm-error-red",
        updated_at=datetime(2026, 7, 22, tzinfo=timezone.utc),
    )
    delivered_tier = await _seed_delivery(
        db_conn,
        user_id=94302,
        slug="dm-despues-error",
        updated_at=datetime(2026, 7, 22, tzinfo=timezone.utc)
        + timedelta(seconds=1),
    )
    calls: list[int] = []

    async def send_fn(user_id: int, _text: str) -> None:
        calls.append(user_id)
        if user_id == 94301:
            raise ConnectionError("Telegram no disponible")

    summary = await deliver_pending(db_conn, send_fn, limit=50)

    assert summary == DeliverySummary(delivered=1, blocked=0, errors=1)
    assert calls == [94301, 94302]
    assert await db_conn.fetchval(
        """SELECT invite_delivered_at FROM telegram_memberships
            WHERE telegram_user_id = $1 AND tier_id = $2""",
        94301,
        failed_tier,
    ) is None
    assert await db_conn.fetchval(
        """SELECT invite_delivered_at FROM telegram_memberships
            WHERE telegram_user_id = $1 AND tier_id = $2""",
        94302,
        delivered_tier,
    ) is not None
