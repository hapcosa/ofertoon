"""Ripley puede acumular observaciones sin pasar al detector ni al publisher."""
from datetime import datetime, timedelta, timezone

import pytest

from curation import ranker
from pricing.detector import _load_candidates


@pytest.mark.asyncio
async def test_store_activa_con_publicacion_cerrada_guarda_precios_sin_candidatos(
    db_conn,
):
    store = await db_conn.fetchrow(
        "SELECT id, is_active, publish_enabled FROM stores WHERE slug='ripley'"
    )
    assert store["is_active"] is True
    # El test fija el estado que necesita en vez de heredarlo de las migraciones:
    # `publish_enabled` de una tienda concreta es una decisión de producto y
    # cambia (la 40 abrió `ripley` en FALSE, la 53 la volvió a abrir en TRUE), y
    # el mecanismo que se prueba acá es el de la columna, no el valor sembrado.
    # `stores` además sobrevive al `_truncate_state` del conftest, así que el
    # valor original se restaura al final o se lo lleva el test siguiente.
    original = store["publish_enabled"]
    await db_conn.execute(
        "UPDATE stores SET publish_enabled=FALSE WHERE id=$1", store["id"]
    )
    category_id = await db_conn.fetchval(
        "SELECT id FROM categories WHERE slug='tecno-notebooks'"
    )
    tier_id = await db_conn.fetchval(
        "INSERT INTO telegram_tiers (name, slug) "
        "VALUES ('Tecnología de prueba', 'tecno-gate-test') RETURNING id"
    )
    await db_conn.execute(
        "INSERT INTO telegram_tier_categories (tier_id, category_id) VALUES ($1, $2)",
        tier_id, category_id,
    )
    listing_id = await db_conn.fetchval(
        "INSERT INTO listings (store_id, category_id, store_sku, url, name_raw) "
        "VALUES ($1, $2, 'ripley-gate-test', 'https://simple.ripley.cl/test', "
        "'Notebook de prueba') RETURNING id", store["id"], category_id
    )
    now = datetime.now(timezone.utc)
    observed = now - timedelta(minutes=1)
    await db_conn.execute(
        "INSERT INTO price_points (listing_id, observed_at, price_effective, in_stock) "
        "VALUES ($1, $2, 100000, TRUE)", listing_id, observed
    )
    await db_conn.execute(
        "INSERT INTO listing_baselines "
        "(listing_id, p50_60d, p10_60d, min_60d, n_points, n_days) "
        "VALUES ($1, 200000, 180000, 180000, 60, 30)", listing_id
    )
    try:
        assert await db_conn.fetchval(
            "SELECT count(*) FROM price_points WHERE listing_id=$1", listing_id
        ) == 1
        assert not any(r["listing_id"] == listing_id for r in await _load_candidates(db_conn))

        await db_conn.execute(
            "UPDATE stores SET publish_enabled=TRUE WHERE id=$1", store["id"]
        )
        assert any(r["listing_id"] == listing_id for r in await _load_candidates(db_conn))
        await db_conn.execute(
            "INSERT INTO deal_candidates "
            "(listing_id, detected_at, price, p50_60d, discount_real, score, verdict) "
            "VALUES ($1, $2, 100000, 200000, 0.5, 50, 'accepted')",
            listing_id, observed,
        )
        await db_conn.execute(
            "UPDATE stores SET publish_enabled=FALSE WHERE id=$1", store["id"]
        )
        assert not any(
            c.listing_id == listing_id
            for c in await ranker.load_candidates(db_conn, tier_id=tier_id, now=now)
        )
        await db_conn.execute(
            "UPDATE stores SET publish_enabled=TRUE WHERE id=$1", store["id"]
        )
        # Un candidato ya aceptado reaparece al abrir el gate, sin reingerir.
        assert any(
            c.listing_id == listing_id
            for c in await ranker.load_candidates(db_conn, tier_id=tier_id, now=now)
        )
    finally:
        await db_conn.execute(
            "UPDATE stores SET publish_enabled=$2 WHERE id=$1",
            store["id"], original,
        )
