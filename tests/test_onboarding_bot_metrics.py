"""Tests puros y DB-backed del reporte de conversión F4.5."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from subscriptions.bot import db
from subscriptions.bot.metrics import (
    ConversionReport,
    build_conversion_report,
    format_conversion_report,
    is_admin,
    parse_admin_ids,
)


def _report_by_ref(report: ConversionReport) -> dict[str, object]:
    return {ref.ref: ref for ref in report.refs}


def test_build_conversion_report_merges_arrivals_with_funnel():
    arrivals = [
        {"ref": "campana-a", "arrivals": 10},
        {"ref": "campana-b", "arrivals": 3},
    ]
    funnel = [
        {"ref": "campana-a", "tier_id": 20, "tier_slug": "swing",
         "trials": 2, "paid": 1, "active": 1},
        {"ref": "campana-a", "tier_id": 10, "tier_slug": "scalp",
         "trials": 4, "paid": 2, "active": 1},
        {"ref": "campana-b", "tier_id": 10, "tier_slug": "scalp",
         "trials": 1, "paid": 0, "active": 0},
    ]

    report = build_conversion_report(arrivals, funnel)

    # Orden: más llegadas primero.
    assert [ref.ref for ref in report.refs] == ["campana-a", "campana-b"]

    by_ref = _report_by_ref(report)
    a = by_ref["campana-a"]
    assert a.arrivals == 10
    # Los agregados del ref suman todos sus tiers.
    assert (a.trials, a.paid, a.active) == (6, 3, 2)
    # Tiers ordenados por id ascendente.
    assert [tier.tier_id for tier in a.tiers] == [10, 20]

    assert report.totals.arrivals == 13
    assert report.totals.trials == 7
    assert report.totals.paid == 3
    assert report.totals.active == 2


def test_build_conversion_report_keeps_funnel_ref_without_arrivals():
    report = build_conversion_report(
        [],
        [{"ref": "(sin ref)", "tier_id": 5, "tier_slug": "vip",
          "trials": 1, "paid": 1, "active": 1}],
    )

    by_ref = _report_by_ref(report)
    assert "(sin ref)" in by_ref
    assert by_ref["(sin ref)"].arrivals == 0
    assert by_ref["(sin ref)"].trials == 1


def test_build_conversion_report_normalizes_none_ref_and_counts():
    report = build_conversion_report(
        [{"ref": None, "arrivals": None}],
        [],
    )

    by_ref = _report_by_ref(report)
    assert "(sin ref)" in by_ref
    assert by_ref["(sin ref)"].arrivals == 0


def test_format_conversion_report_renders_totals_and_breakdown():
    report = build_conversion_report(
        [{"ref": "camp", "arrivals": 5}],
        [{"ref": "camp", "tier_id": 1, "tier_slug": "vip",
          "trials": 2, "paid": 1, "active": 1}],
    )

    text = format_conversion_report(report)

    assert "📊 Conversión por campaña" in text
    assert "llegadas 5" in text
    assert "vip: trials 2 · pagos 1 · activos 1" in text


def test_format_conversion_report_handles_empty():
    report = build_conversion_report([], [])
    text = format_conversion_report(report)
    assert "Todavía no hay datos" in text


def test_format_conversion_report_escapes_ref_html():
    report = build_conversion_report(
        [{"ref": "<script>", "arrivals": 1}],
        [],
    )
    text = format_conversion_report(report)
    assert "<script>" not in text
    assert "&lt;script&gt;" in text


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (None, frozenset()),
        ("", frozenset()),
        ("   ", frozenset()),
        ("123", frozenset({123})),
        ("123,456", frozenset({123, 456})),
        ("123, 456 789", frozenset({123, 456, 789})),
        ("123,abc,456", frozenset({123, 456})),
        ("123,123", frozenset({123})),
    ],
)
def test_parse_admin_ids(raw, expected):
    assert parse_admin_ids(raw) == expected


def test_is_admin_respects_allowlist():
    admins = parse_admin_ids("111,222")
    assert is_admin(111, admins) is True
    assert is_admin(333, admins) is False
    assert is_admin(None, admins) is False
    assert is_admin(111, frozenset()) is False


async def _insert_tier(db_conn, name: str, slug: str) -> int:
    return await db_conn.fetchval(
        """INSERT INTO telegram_tiers (name, slug, is_active)
           VALUES ($1, $2, TRUE)
           RETURNING id""",
        name,
        slug,
    )


@pytest.mark.asyncio
async def test_fetch_arrivals_by_ref_groups_identities(db_conn):
    await db.upsert_identity(db_conn, 95001, "u1", "metrics-ref-x")
    await db.upsert_identity(db_conn, 95002, "u2", "metrics-ref-x")
    await db.upsert_identity(db_conn, 95003, "u3", "metrics-ref-y")
    await db.upsert_identity(db_conn, 95004, "u4", None)

    rows = await db.fetch_arrivals_by_ref(db_conn)
    by_ref = {row["ref"]: row["arrivals"] for row in rows}

    assert by_ref["metrics-ref-x"] == 2
    assert by_ref["metrics-ref-y"] == 1
    assert by_ref["(sin ref)"] >= 1  # incluye al menos al usuario sin ref.


@pytest.mark.asyncio
async def test_fetch_conversion_by_ref_tier_derives_funnel(db_conn):
    tier_id = await _insert_tier(db_conn, "Métricas VIP", "metrics-vip")
    await db.upsert_identity(db_conn, 96001, "c1", "metrics-conv")
    await db.upsert_identity(db_conn, 96002, "c2", "metrics-conv")
    await db.upsert_identity(db_conn, 96003, "c3", "metrics-conv")

    await db_conn.executemany(
        """INSERT INTO telegram_memberships
                   (telegram_user_id, tier_id, status, channel_state,
                    trial_ends_at, paypal_subscription_id, source_ref)
           VALUES ($1, $2, $3, $4, $5, $6, $7)""",
        [
            # Trial vigente, aún sin pago.
            (96001, tier_id, "trialing", "none",
             datetime(2026, 8, 1, tzinfo=timezone.utc), None, "metrics-conv"),
            # Trial que ya convirtió a pago activo (trial_ends_at persiste).
            (96002, tier_id, "active", "member",
             datetime(2026, 7, 1, tzinfo=timezone.utc), "I-SUB-96002",
             "metrics-conv"),
            # Pago directo sin trial previo.
            (96003, tier_id, "active", "member",
             None, "I-SUB-96003", "metrics-conv"),
        ],
    )

    rows = await db.fetch_conversion_by_ref_tier(db_conn)
    row = next(
        r for r in rows
        if r["ref"] == "metrics-conv" and r["tier_id"] == tier_id
    )

    assert row["tier_slug"] == "metrics-vip"
    assert row["trials"] == 2   # los dos con trial_ends_at.
    assert row["paid"] == 2     # los dos con paypal_subscription_id.
    assert row["active"] == 2   # los dos en estado active.


@pytest.mark.asyncio
async def test_conversion_report_end_to_end_from_db(db_conn):
    tier_id = await _insert_tier(db_conn, "E2E VIP", "metrics-e2e")
    await db.upsert_identity(db_conn, 97001, "e1", "metrics-e2e-ref")
    await db.upsert_identity(db_conn, 97002, "e2", "metrics-e2e-ref")
    await db_conn.execute(
        """INSERT INTO telegram_memberships
                   (telegram_user_id, tier_id, status, channel_state,
                    trial_ends_at, source_ref)
           VALUES ($1, $2, 'trialing', 'none',
                   '2026-08-01T00:00:00+00:00', 'metrics-e2e-ref')""",
        97001,
        tier_id,
    )

    arrivals = await db.fetch_arrivals_by_ref(db_conn)
    funnel = await db.fetch_conversion_by_ref_tier(db_conn)
    report = build_conversion_report(arrivals, funnel)

    by_ref = _report_by_ref(report)
    assert by_ref["metrics-e2e-ref"].arrivals == 2
    assert by_ref["metrics-e2e-ref"].trials == 1
