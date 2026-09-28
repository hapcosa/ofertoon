"""El pipeline de pricing: que las tres fases corran, y en el orden correcto.

Este archivo nace de un bug de ausencia, no de lógica:
`catalog.identity.assign_products()` estaba escrita, testeada y **sin
llamador** — `products` llevaba 0 filas con 25.548 listings y 3.216 `gtin_raw`
guardados. Un test unitario de `canonical_key` no lo detecta: la función era
correcta, nadie la invocaba. Por eso lo que se prueba acá es el cableado.
"""
from __future__ import annotations

import pytest

from pricing import pipeline

pytestmark = pytest.mark.asyncio


async def _listing_con_gtin(conn, slug: str, sku: str, gtin: str) -> int:
    store_id = await conn.fetchval("SELECT id FROM stores WHERE slug = $1", slug)
    return await conn.fetchval(
        """
        INSERT INTO listings (store_id, store_sku, url, name_raw, gtin_raw)
             VALUES ($1, $2, $3, 'Producto', $4)
          RETURNING id
        """,
        store_id,
        sku,
        f"https://{slug}.cl/{sku}",
        gtin,
    )


async def test_el_pipeline_asigna_identidad(db_conn, telegram_pool):
    """La regresión que importa: que `assign_products` tenga un llamador."""
    await _listing_con_gtin(db_conn, "paris", "p-1", "884116671206")
    await _listing_con_gtin(db_conn, "spdigital", "s-1", "884116671206")

    stats = await pipeline.run(telegram_pool)

    assert stats.identity is not None
    assert stats.identity.linked == 2
    assert await db_conn.fetchval("SELECT count(*) FROM products") == 1
    assert await db_conn.fetchval(
        "SELECT count(*) FROM listings WHERE product_id IS NOT NULL"
    ) == 2


async def test_un_fallo_de_identidad_no_se_lleva_la_senal(
    db_conn, telegram_pool, monkeypatch
):
    """La identidad es copy; el detector es el producto. No pueden ir juntas.

    Si un fallo de identidad propagara, costaría la corrida de baselines y
    detector que YA quedó persistida — y la próxima pasada es 12 h después.
    """
    async def explota(*_args, **_kwargs):
        raise RuntimeError("la identidad se cayó")

    monkeypatch.setattr(pipeline.identity, "assign_products", explota)

    stats = await pipeline.run(telegram_pool)

    # `None` y no un stats en cero: "falló" no es "no había nada que hacer".
    assert stats.identity is None
    assert "identidad[falló]" in str(stats)
    assert stats.baselines is not None and stats.detector is not None
