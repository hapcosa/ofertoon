"""DB-backed tests del reconciler de membresía del canal VIP.

Cubre la tabla de transiciones (§4/§6 del plan): grant, revoke, gracia de
past_due, idempotencia, fallo de Bot API, resolución de canal, reactivación
kicked→active y gate deshabilitado.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import os

import asyncpg
import pytest
import pytest_asyncio

from subscriptions.gate import MembershipReconciler, decide_action


class FakeGateClient:
    def __init__(
        self,
        *,
        invite_link: str | None = "https://t.me/+invite",
        invite_ok: bool = True,
        ban_ok: bool = True,
        unban_ok: bool = True,
    ) -> None:
        self.invite_calls: list[tuple] = []
        self.ban_calls: list[tuple] = []
        self.unban_calls: list[tuple] = []
        self._invite_link = invite_link
        self._invite_ok = invite_ok
        self._ban_ok = ban_ok
        self._unban_ok = unban_ok

    async def create_chat_invite_link(
        self, chat_id, *, member_limit=1, expire_date=None
    ):
        self.invite_calls.append((chat_id, member_limit, expire_date))
        return self._invite_link if self._invite_ok else None

    async def ban_chat_member(self, chat_id, user_id):
        self.ban_calls.append((chat_id, user_id))
        return self._ban_ok

    async def unban_chat_member(self, chat_id, user_id):
        self.unban_calls.append((chat_id, user_id))
        return self._unban_ok


class _Clock:
    def __init__(self, now: datetime) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now


async def _seed_tier(
    db_conn, slug: str, channel_id: int | None, *, gate_enabled: bool = True
) -> int:
    # `gate_enabled` es el toggle fino por-canal (default FALSE en DB). Los tests
    # de transiciones lo siembran en TRUE porque prueban el gate ya encendido;
    # el default-off tiene su propio test.
    return await db_conn.fetchval(
        """INSERT INTO telegram_tiers (name, slug, telegram_channel_id, gate_enabled)
           VALUES ($1, $1, $2, $3)
           RETURNING id""",
        slug,
        channel_id,
        gate_enabled,
    )


async def _seed_subscriber(
    db_conn,
    telegram_user_id: int,
    tier_id: int | None,
    *,
    status: str,
    channel_state: str = "none",
    grace_until: datetime | None = None,
    trial_ends_at: datetime | None = None,
) -> None:
    # Identidad primero (FK), luego la membresía por (persona, tier).
    await db_conn.execute(
        "INSERT INTO telegram_subscribers (telegram_user_id) VALUES ($1) "
        "ON CONFLICT (telegram_user_id) DO NOTHING",
        telegram_user_id,
    )
    await db_conn.execute(
        """INSERT INTO telegram_memberships
               (telegram_user_id, tier_id, status, channel_state,
                grace_until, trial_ends_at, payment_provider)
           VALUES ($1, $2, $3, $4, $5, $6, 'paypal')""",
        telegram_user_id,
        tier_id,
        status,
        channel_state,
        grace_until,
        trial_ends_at,
    )


async def _state(db_conn, telegram_user_id: int, tier_id: int | None = None):
    if tier_id is None:
        return await db_conn.fetchrow(
            """SELECT status, channel_state, invite_link, invite_expires_at,
                      access_granted_at, access_revoked_at, grace_until,
                      gate_last_error
                 FROM telegram_memberships WHERE telegram_user_id = $1""",
            telegram_user_id,
        )
    return await db_conn.fetchrow(
        """SELECT status, channel_state, invite_link, invite_expires_at,
                  access_granted_at, access_revoked_at, grace_until,
                  gate_last_error
             FROM telegram_memberships
            WHERE telegram_user_id = $1 AND tier_id = $2""",
        telegram_user_id,
        tier_id,
    )


# --------------------------------------------------------------------------- #
# decide_action (función pura)
# --------------------------------------------------------------------------- #
def test_decide_action_matrix():
    now = datetime(2026, 7, 19, tzinfo=timezone.utc)
    grace_future = now + timedelta(days=1)
    grace_past = now - timedelta(days=1)

    assert decide_action("active", "none", None, now) == "grant"
    assert decide_action("trialing", "kicked", None, now) == "grant"
    assert decide_action("active", "invited", None, now) == "noop"
    assert decide_action("active", "member", grace_future, now) == "clear_grace"
    assert decide_action("past_due", "member", None, now) == "start_grace"
    assert decide_action("past_due", "member", grace_future, now) == "noop"
    assert decide_action("past_due", "member", grace_past, now) == "revoke"
    assert decide_action("past_due", "none", None, now) == "noop"
    assert decide_action("canceled", "invited", None, now) == "revoke"
    assert decide_action("expired", "member", None, now) == "revoke"
    assert decide_action("canceled", "kicked", None, now) == "noop"
    # pending / grace: no manejados en el MVP → no-op explícito.
    assert decide_action("pending", "none", None, now) == "noop"
    assert decide_action("grace", "member", None, now) == "noop"


# --------------------------------------------------------------------------- #
# reconciler (DB-backed)
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_active_none_grants_invite(db_conn, telegram_pool):
    tier_id = await _seed_tier(db_conn, "grant-tier", -100100)
    await _seed_subscriber(db_conn, 111, tier_id, status="active")
    client = FakeGateClient()
    reconciler = MembershipReconciler(telegram_pool, client, now=_Clock(
        datetime(2026, 7, 19, tzinfo=timezone.utc)
    ))

    assert await reconciler.run_once() == 1

    assert client.invite_calls == [(-100100, 1, datetime(2026, 7, 20, tzinfo=timezone.utc))]
    assert client.ban_calls == []
    row = await _state(db_conn, 111)
    assert row["channel_state"] == "invited"
    assert row["invite_link"] == "https://t.me/+invite"
    assert row["access_granted_at"] is not None
    assert row["gate_last_error"] is None


@pytest.mark.asyncio
async def test_grant_is_idempotent(db_conn, telegram_pool):
    tier_id = await _seed_tier(db_conn, "idem-tier", -100200)
    await _seed_subscriber(db_conn, 222, tier_id, status="active")
    client = FakeGateClient()
    reconciler = MembershipReconciler(telegram_pool, client)

    assert await reconciler.run_once() == 1
    assert await reconciler.run_once() == 0  # ya 'invited' → no es candidato
    assert len(client.invite_calls) == 1


@pytest.mark.asyncio
async def test_canceled_member_kicks(db_conn, telegram_pool):
    tier_id = await _seed_tier(db_conn, "kick-tier", -100300)
    await _seed_subscriber(
        db_conn, 333, tier_id, status="canceled", channel_state="member"
    )
    client = FakeGateClient()
    reconciler = MembershipReconciler(telegram_pool, client)

    assert await reconciler.run_once() == 1

    assert client.ban_calls == [(-100300, 333)]
    assert client.unban_calls == [(-100300, 333)]  # kick = ban + unban
    row = await _state(db_conn, 333)
    assert row["channel_state"] == "kicked"
    assert row["access_revoked_at"] is not None


@pytest.mark.asyncio
async def test_past_due_respects_grace_then_kicks(db_conn, telegram_pool):
    tier_id = await _seed_tier(db_conn, "grace-tier", -100400)
    await _seed_subscriber(
        db_conn, 444, tier_id, status="past_due", channel_state="member"
    )
    clock = _Clock(datetime(2026, 7, 19, tzinfo=timezone.utc))
    client = FakeGateClient()
    reconciler = MembershipReconciler(
        telegram_pool, client, grace_days=3.0, now=clock
    )

    # 1) Primer ciclo: fija grace_until, NO kickea.
    assert await reconciler.run_once() == 1
    row = await _state(db_conn, 444)
    assert row["channel_state"] == "member"
    assert row["grace_until"] == datetime(2026, 7, 22, tzinfo=timezone.utc)
    assert client.ban_calls == []

    # 2) Dentro de la gracia: no kickea.
    clock.now = datetime(2026, 7, 21, tzinfo=timezone.utc)
    assert await reconciler.run_once() == 0
    assert client.ban_calls == []

    # 3) Vencida la gracia: kickea.
    clock.now = datetime(2026, 7, 23, tzinfo=timezone.utc)
    assert await reconciler.run_once() == 1
    assert client.ban_calls == [(-100400, 444)]
    row = await _state(db_conn, 444)
    assert row["channel_state"] == "kicked"
    assert row["grace_until"] is None


@pytest.mark.asyncio
async def test_reactivation_kicked_to_active_unbans_and_reinvites(db_conn, telegram_pool):
    tier_id = await _seed_tier(db_conn, "react-tier", -100500)
    await _seed_subscriber(
        db_conn, 555, tier_id, status="active", channel_state="kicked"
    )
    client = FakeGateClient(invite_link="https://t.me/+again")
    reconciler = MembershipReconciler(telegram_pool, client)

    assert await reconciler.run_once() == 1

    assert client.unban_calls == [(-100500, 555)]  # destraba el ban antes de invitar
    assert len(client.invite_calls) == 1
    row = await _state(db_conn, 555)
    assert row["channel_state"] == "invited"
    assert row["invite_link"] == "https://t.me/+again"


@pytest.mark.asyncio
async def test_bot_api_failure_does_not_persist_state(db_conn, telegram_pool):
    tier_id = await _seed_tier(db_conn, "fail-tier", -100600)
    await _seed_subscriber(db_conn, 666, tier_id, status="active")
    client = FakeGateClient(invite_ok=False)
    reconciler = MembershipReconciler(telegram_pool, client)

    assert await reconciler.run_once() == 0  # nada aplicado

    row = await _state(db_conn, 666)
    assert row["channel_state"] == "none"  # NO persiste — se reintenta
    assert row["invite_link"] is None
    assert row["gate_last_error"] == "invite_failed"
    # Sigue siendo candidato: un cliente sano en el próximo ciclo lo resuelve.
    healthy = FakeGateClient()
    assert await MembershipReconciler(telegram_pool, healthy).run_once() == 1
    assert (await _state(db_conn, 666))["channel_state"] == "invited"


@pytest.mark.asyncio
async def test_tier_without_channel_is_noop(db_conn, telegram_pool):
    tier_id = await _seed_tier(db_conn, "nochannel-tier", None)
    await _seed_subscriber(db_conn, 777, tier_id, status="active")
    client = FakeGateClient()
    reconciler = MembershipReconciler(telegram_pool, client)

    assert await reconciler.run_once() == 0  # no-op + warning, el loop sigue

    assert client.invite_calls == []
    assert (await _state(db_conn, 777))["channel_state"] == "none"


@pytest.mark.asyncio
async def test_disabled_gate_is_inert(db_conn, telegram_pool):
    tier_id = await _seed_tier(db_conn, "disabled-tier", -100800)
    await _seed_subscriber(db_conn, 888, tier_id, status="active")
    client = FakeGateClient()
    reconciler = MembershipReconciler(telegram_pool, client, enabled=False)

    assert await reconciler.run_once() == 0

    assert client.invite_calls == []
    assert (await _state(db_conn, 888))["channel_state"] == "none"


@pytest.mark.asyncio
async def test_channel_gate_off_is_inert_even_with_env_master_on(
    db_conn, telegram_pool
):
    """Gate efectivo = AND(env global, tier.gate_enabled). Con el master global
    encendido (enabled=True) pero el toggle del canal apagado, el reconciler no
    invita ni expulsa a nadie de ese canal."""
    tier_id = await _seed_tier(
        db_conn, "channel-gate-off", -100850, gate_enabled=False
    )
    await _seed_subscriber(db_conn, 889, tier_id, status="active")
    await _seed_subscriber(
        db_conn, 890, tier_id, status="canceled", channel_state="member"
    )
    client = FakeGateClient()
    reconciler = MembershipReconciler(telegram_pool, client, enabled=True)

    assert await reconciler.run_once() == 0

    assert client.invite_calls == []
    assert client.ban_calls == []
    assert (await _state(db_conn, 889, tier_id))["channel_state"] == "none"
    assert (await _state(db_conn, 890, tier_id))["channel_state"] == "member"


@pytest.mark.asyncio
async def test_channel_gate_only_touches_its_own_channel(db_conn, telegram_pool):
    """Dos canales, uno con el gate encendido y otro apagado: sólo el encendido
    se reconcilia."""
    tier_on = await _seed_tier(db_conn, "gate-on", -100860, gate_enabled=True)
    tier_off = await _seed_tier(db_conn, "gate-off", -100870, gate_enabled=False)
    await _seed_subscriber(db_conn, 891, tier_on, status="active")
    await _seed_subscriber(db_conn, 891, tier_off, status="active")
    client = FakeGateClient()

    assert await MembershipReconciler(telegram_pool, client).run_once() == 1

    assert [call[0] for call in client.invite_calls] == [-100860]
    assert (await _state(db_conn, 891, tier_on))["channel_state"] == "invited"
    assert (await _state(db_conn, 891, tier_off))["channel_state"] == "none"


# --------------------------------------------------------------------------- #
# multi-membresía: una persona en varios tiers, resueltos independientemente
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_multi_membership_resolved_independently(db_conn, telegram_pool):
    tier_a = await _seed_tier(db_conn, "multi-a", -100900)
    tier_b = await _seed_tier(db_conn, "multi-b", -101000)
    # Misma persona (999) en dos canales: uno se concede, el otro se expulsa.
    await _seed_subscriber(db_conn, 999, tier_a, status="active")
    await _seed_subscriber(
        db_conn, 999, tier_b, status="canceled", channel_state="member"
    )
    client = FakeGateClient()
    reconciler = MembershipReconciler(telegram_pool, client)

    assert await reconciler.run_once() == 2

    assert client.invite_calls == [
        (-100900, 1, client.invite_calls[0][2])
    ]  # solo el tier activo recibe invite
    assert client.ban_calls == [(-101000, 999)]  # solo el tier cancelado se kickea
    assert (await _state(db_conn, 999, tier_a))["channel_state"] == "invited"
    row_b = await _state(db_conn, 999, tier_b)
    assert row_b["channel_state"] == "kicked"
    assert row_b["status"] == "canceled"


# --------------------------------------------------------------------------- #
# sweeper de expiración de trial (§5.4)
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_expired_trial_is_swept_then_kicked(db_conn, telegram_pool):
    tier_id = await _seed_tier(db_conn, "trial-tier", -101100)
    clock = _Clock(datetime(2026, 7, 19, tzinfo=timezone.utc))
    await _seed_subscriber(
        db_conn,
        1010,
        tier_id,
        status="trialing",
        channel_state="member",
        trial_ends_at=datetime(2026, 7, 18, tzinfo=timezone.utc),  # ya vencido
    )
    client = FakeGateClient()
    reconciler = MembershipReconciler(telegram_pool, client, now=clock)

    assert await reconciler.run_once() == 1

    # El sweeper lo pasó a expired y el gate lo kickeó en el mismo ciclo.
    row = await _state(db_conn, 1010, tier_id)
    assert row["status"] == "expired"
    assert row["channel_state"] == "kicked"
    assert client.ban_calls == [(-101100, 1010)]


@pytest.mark.asyncio
async def test_trial_not_yet_expired_stays_active(db_conn, telegram_pool):
    tier_id = await _seed_tier(db_conn, "trial-live-tier", -101200)
    clock = _Clock(datetime(2026, 7, 19, tzinfo=timezone.utc))
    await _seed_subscriber(
        db_conn,
        1020,
        tier_id,
        status="trialing",
        channel_state="member",
        trial_ends_at=datetime(2026, 7, 25, tzinfo=timezone.utc),  # futuro
    )
    client = FakeGateClient()
    reconciler = MembershipReconciler(telegram_pool, client, now=clock)

    assert await reconciler.run_once() == 0  # trial vigente + member → no-op

    row = await _state(db_conn, 1020, tier_id)
    assert row["status"] == "trialing"
    assert row["channel_state"] == "member"
    assert client.ban_calls == []
