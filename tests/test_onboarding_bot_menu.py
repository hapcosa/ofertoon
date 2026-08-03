"""Tests puros y DB-backed del menú multi-tier de onboarding F4.1."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from subscriptions.bot import db
from subscriptions.bot.menu import (
    TierStats,
    build_menu_model,
    format_stats_line,
    membership_status_label,
    trial_days_left,
)


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (None, "Sin acceso"),
        ("pending", "Pendiente"),
        ("trialing", "⏳ En trial"),
        ("active", "✅ Miembro"),
        ("past_due", "Pago pendiente"),
        ("grace", "Período de gracia"),
        ("canceled", "Cancelado"),
        ("expired", "Vencido"),
    ],
)
def test_membership_status_label_covers_schema_statuses(status, expected):
    assert membership_status_label(status, "member") == expected


@pytest.mark.parametrize(
    ("channel_state", "expected"),
    [
        ("member", "✅ Miembro"),
        ("invited", "✅ Activo · link enviado"),
        ("kicked", "⚠️ Activo · reingreso pendiente"),
        ("none", "✅ Activo · preparando acceso"),
        (None, "✅ Activo · preparando acceso"),
    ],
)
def test_active_label_refines_by_channel_state(channel_state, expected):
    assert membership_status_label("active", channel_state) == expected


@pytest.mark.parametrize("channel_state", ["member", "invited", "kicked", None])
def test_non_active_label_ignores_channel_state(channel_state):
    assert membership_status_label("trialing", channel_state) == "⏳ En trial"
    assert membership_status_label("expired", channel_state) == "Vencido"


def test_trial_days_left_rounds_up_and_floors_at_zero():
    now = datetime(2026, 7, 23, 12, 0, tzinfo=timezone.utc)
    assert trial_days_left(None, now) is None
    assert trial_days_left(now + timedelta(days=6, hours=12), now) == 7
    assert trial_days_left(now + timedelta(hours=2), now) == 1
    assert trial_days_left(now, now) == 0
    assert trial_days_left(now - timedelta(hours=1), now) == 0
    assert trial_days_left(now + timedelta(days=1), None) is None


def test_build_menu_shows_trial_countdown_when_now_provided():
    now = datetime(2026, 7, 23, 12, 0, tzinfo=timezone.utc)
    memberships = {
        10: {
            "status": "trialing",
            "channel_state": "member",
            "trial_ends_at": now + timedelta(days=2, hours=1),
        },
    }

    model = build_menu_model(_tiers(), memberships, {"trial_used_at": None}, now=now)

    assert model.rows[0].status_label == "⏳ En trial · 3 días restantes"


def test_build_menu_omits_countdown_without_now():
    memberships = {
        10: {
            "status": "trialing",
            "channel_state": "member",
            "trial_ends_at": datetime(2026, 7, 25, tzinfo=timezone.utc),
        },
    }

    model = build_menu_model(_tiers(), memberships, {"trial_used_at": None})

    assert model.rows[0].status_label == "⏳ En trial"


def _tiers():
    return [
        {
            "id": 10,
            "name": "VIP Scalping",
            "slug": "vip-scalping",
            "description": "Señales de corto plazo",
        },
        {
            "id": 20,
            "name": "VIP Swing",
            "slug": "vip-swing",
            "description": None,
        },
    ]


def test_build_menu_without_memberships_offers_each_tier_independently():
    model = build_menu_model(_tiers(), {}, {"trial_used_at": None})

    assert [row.tier_id for row in model.rows] == [10, 20]
    assert [row.status_label for row in model.rows] == ["Sin acceso", "Sin acceso"]
    assert all(row.trial_available for row in model.rows)
    assert all(row.payment_available for row in model.rows)
    assert [button.callback_data for button in model.rows[0].buttons] == [
        "trial:10",
        "pay:10",
    ]
    assert [button.callback_data for button in model.rows[1].buttons] == [
        "trial:20",
        "pay:20",
    ]


def test_build_menu_keeps_membership_state_isolated_per_tier():
    memberships = {
        10: {"status": "active", "channel_state": "member"},
    }

    model = build_menu_model(_tiers(), memberships, {"trial_used_at": None})

    active, missing = model.rows
    assert active.status_label == "✅ Miembro"
    assert active.trial_available is False
    assert active.payment_available is False
    assert active.buttons == ()
    assert missing.status_label == "Sin acceso"
    assert missing.trial_available is True
    assert missing.payment_available is True


def test_build_menu_disables_trial_globally_after_it_was_used():
    identity = {"trial_used_at": datetime(2026, 7, 22, tzinfo=timezone.utc)}

    model = build_menu_model(_tiers(), {}, identity)

    assert all(row.trial_available is False for row in model.rows)
    assert all(row.payment_available is True for row in model.rows)
    assert all(
        [button.callback_data for button in row.buttons] == [f"pay:{row.tier_id}"]
        for row in model.rows
    )


def test_build_menu_hides_second_trial_for_trialing_tier():
    memberships = {
        10: {"status": "trialing", "channel_state": "invited"},
    }

    model = build_menu_model(_tiers(), memberships, {"trial_used_at": None})

    assert model.rows[0].status_label == "⏳ En trial"
    assert model.rows[0].trial_available is False
    assert [button.callback_data for button in model.rows[0].buttons] == ["pay:10"]


def test_format_stats_line_none_and_empty_show_nothing():
    assert format_stats_line(None) is None
    assert format_stats_line(TierStats(0, Decimal(0), Decimal(0))) is None


def test_format_stats_line_labels_window_posts_and_discounts():
    stats = TierStats(
        posts=100, avg_discount=Decimal("0.352"), best_discount=Decimal("0.71")
    )
    assert format_stats_line(stats) == "📊 90d · 100 ofertas · 35% promedio · mejor 71%"


def test_format_stats_line_rounds_discounts_to_whole_percent():
    stats = TierStats(
        posts=7, avg_discount=Decimal("0.185"), best_discount=Decimal("0.4")
    )
    assert format_stats_line(stats) == "📊 90d · 7 ofertas · 18% promedio · mejor 40%"


def test_build_menu_injects_stats_line_only_where_stats_exist():
    stats_by_tier = {
        10: TierStats(
            posts=20, avg_discount=Decimal("0.4"), best_discount=Decimal("0.65")
        ),
    }

    model = build_menu_model(
        _tiers(), {}, {"trial_used_at": None}, stats_by_tier_id=stats_by_tier
    )

    assert model.rows[0].stats_line == "📊 90d · 20 ofertas · 40% promedio · mejor 65%"
    # El tier sin stats no inventa una línea.
    assert model.rows[1].stats_line is None


def test_build_menu_without_stats_argument_keeps_lines_empty():
    model = build_menu_model(_tiers(), {}, {"trial_used_at": None})

    assert all(row.stats_line is None for row in model.rows)


def test_tier_stats_from_rows_types_the_aggregated_rows():
    from subscriptions.bot.main import _tier_stats_from_rows

    # La query ya agrega por tier: acá solo se tipa. Un tier sin publicaciones
    # nunca aparece en las filas (lo excluye el GROUP BY), así que no tiene stats.
    rows = [
        {"tier_id": 1, "posts": 12, "avg_discount": Decimal("0.31"),
         "best_discount": Decimal("0.62")},
        {"tier_id": 2, "posts": 3, "avg_discount": None, "best_discount": None},
    ]

    stats = _tier_stats_from_rows(rows)

    assert stats[1].posts == 12
    assert stats[1].avg_discount == Decimal("0.31")
    assert stats[1].best_discount == Decimal("0.62")
    # NULL de SQL no revienta el formateo: cae en 0, no en None.
    assert stats[2].avg_discount == Decimal(0)
    assert 2 in stats and stats[2].posts == 3


async def _seed_posted_deal(
    db_conn, tier_id: int, *, discount: str, posted_sql: str
) -> None:
    """Publica una oferta en `tier_id` con el descuento y antigüedad pedidos."""
    store_id = await db_conn.fetchval(
        """INSERT INTO stores (slug, name, base_url, adapter)
           VALUES ($1, $1, 'https://example.cl', 'stub')
           ON CONFLICT (slug) DO UPDATE SET name = EXCLUDED.name
           RETURNING id""",
        "stats-store",
    )
    listing_id = await db_conn.fetchval(
        """INSERT INTO listings (store_id, store_sku, url, name_raw)
           VALUES ($1, $2, $3, 'Producto stats')
           RETURNING id""",
        store_id,
        f"sku-{discount}-{posted_sql!r:.12}",
        f"https://example.cl/{discount}-{abs(hash(posted_sql))}",
    )
    candidate_id = await db_conn.fetchval(
        """INSERT INTO deal_candidates
               (listing_id, price, p50_60d, discount_real, verdict)
           VALUES ($1, 1000, 2000, $2, 'accepted')
           RETURNING id""",
        listing_id,
        Decimal(discount),
    )
    await db_conn.execute(
        f"""INSERT INTO deal_posts (candidate_id, tier_id, posted_at)
            VALUES ($1, $2, {posted_sql})""",
        candidate_id,
        tier_id,
    )


@pytest.mark.asyncio
async def test_fetch_tier_stat_rows_windows_and_aggregates_published_deals(db_conn):
    tier_id = await db_conn.fetchval(
        """INSERT INTO telegram_tiers (name, slug, telegram_channel_id, is_active)
           VALUES ('Stats Tier', 'stats-tier', -90001, TRUE)
           RETURNING id"""
    )
    inactive_id = await db_conn.fetchval(
        """INSERT INTO telegram_tiers (name, slug, is_active)
           VALUES ('Apagado', 'stats-tier-off', FALSE)
           RETURNING id"""
    )

    await _seed_posted_deal(
        db_conn, tier_id, discount="0.30", posted_sql="NOW() - INTERVAL '2 days'"
    )
    await _seed_posted_deal(
        db_conn, tier_id, discount="0.50", posted_sql="NOW() - INTERVAL '10 days'"
    )
    # Fuera de la ventana rodante de 90d: no debe entrar al promedio ni al máximo.
    await _seed_posted_deal(
        db_conn, tier_id, discount="0.90", posted_sql="NOW() - INTERVAL '100 days'"
    )
    # Tier inactivo: no se muestra en el menú, no debe traer stats.
    await _seed_posted_deal(
        db_conn, inactive_id, discount="0.80", posted_sql="NOW() - INTERVAL '1 day'"
    )

    rows = await db.fetch_tier_stat_rows(db_conn)
    by_tier = {row["tier_id"]: row for row in rows}

    assert inactive_id not in by_tier
    row = by_tier[tier_id]
    assert row["posts"] == 2
    assert Decimal(str(row["avg_discount"])) == Decimal("0.4000")
    assert Decimal(str(row["best_discount"])) == Decimal("0.5000")


@pytest.mark.asyncio
async def test_upsert_identity_keeps_first_ref_and_updates_username(db_conn):
    first = await db.upsert_identity(db_conn, 91001, "nombre_original", "campana-a")
    second = await db.upsert_identity(db_conn, 91001, "nombre_nuevo", "campana-b")

    assert first["source_ref"] == "campana-a"
    assert second["source_ref"] == "campana-a"
    assert second["telegram_username"] == "nombre_nuevo"
    assert await db_conn.fetchval(
        "SELECT COUNT(*) FROM telegram_memberships WHERE telegram_user_id = $1",
        91001,
    ) == 0


@pytest.mark.asyncio
async def test_upsert_identity_can_attribute_later_start_if_ref_was_missing(db_conn):
    await db.upsert_identity(db_conn, 91002, None, None)
    identity = await db.upsert_identity(db_conn, 91002, "nuevo_nombre", "campana-c")

    assert identity["source_ref"] == "campana-c"
    assert identity["telegram_username"] == "nuevo_nombre"


async def _insert_tier(db_conn, name: str, slug: str, *, active: bool) -> int:
    return await db_conn.fetchval(
        """INSERT INTO telegram_tiers (name, slug, is_active)
           VALUES ($1, $2, $3)
           RETURNING id""",
        name,
        slug,
        active,
    )


@pytest.mark.asyncio
async def test_fetch_active_tiers_filters_and_orders_by_id(db_conn):
    first_id = await _insert_tier(db_conn, "Primero", "onboarding-primero", active=True)
    await _insert_tier(db_conn, "Oculto", "onboarding-oculto", active=False)
    last_id = await _insert_tier(db_conn, "Último", "onboarding-ultimo", active=True)

    tiers = await db.fetch_active_tiers(db_conn)

    fetched_ids = [row["id"] for row in tiers]
    assert first_id in fetched_ids
    assert last_id in fetched_ids
    assert fetched_ids == sorted(fetched_ids)
    assert all(row["slug"] != "onboarding-oculto" for row in tiers)


@pytest.mark.asyncio
async def test_fetch_memberships_only_returns_requested_user_in_order(db_conn):
    tier_a = await _insert_tier(db_conn, "Tier A", "onboarding-tier-a", active=True)
    tier_b = await _insert_tier(db_conn, "Tier B", "onboarding-tier-b", active=True)
    await db.upsert_identity(db_conn, 92001, "usuario_a", None)
    await db.upsert_identity(db_conn, 92002, "usuario_b", None)
    await db_conn.executemany(
        """INSERT INTO telegram_memberships
                   (telegram_user_id, tier_id, status, channel_state)
           VALUES ($1, $2, $3, $4)""",
        [
            (92001, tier_b, "active", "member"),
            (92001, tier_a, "trialing", "invited"),
            (92002, tier_a, "expired", "kicked"),
        ],
    )

    memberships = await db.fetch_memberships(db_conn, 92001)

    assert [row["tier_id"] for row in memberships] == sorted([tier_a, tier_b])
    assert [row["status"] for row in memberships] == ["trialing", "active"]
