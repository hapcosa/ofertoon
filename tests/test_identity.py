"""Identidad de producto: agrupar sin fusionar cosas distintas.

El sesgo del módulo es explícito — ante la duda no se agrupa. Un GTIN faltante
degrada el copy del mensaje; un GTIN equivocado publica el producto que no es.
"""
from __future__ import annotations

from catalog.identity import MIN_MODEL_LENGTH, canonical_key, normalize_model


def test_gtin_manda_sobre_marca_modelo():
    """Es la evidencia dura: si está, no hace falta nada más."""
    key = canonical_key(gtin="6932554471736", brand="Xiaomi", model="Redmi 13")
    assert key == "gtin:6932554471736"


def test_dos_tiendas_con_el_mismo_gtin_dan_la_misma_llave():
    paris = canonical_key(gtin=" 884116671206 ", brand="Dell", model="Inspiron 15")
    spdigital = canonical_key(gtin="884116671206", brand="DELL", model="INSPIRON-15")
    assert paris == spdigital == "gtin:884116671206"


def test_marca_modelo_es_estable_entre_grafias():
    a = canonical_key(gtin=None, brand="APPLE", model="iPhone 15")
    b = canonical_key(gtin=None, brand="  apple ", model="IPHONE-15")
    assert a == b == "bm:apple|iphone15"


def test_sku_interno_disfrazado_de_gtin_no_agrupa():
    """SP Digital pone su propio SKU en el campo del código de barras."""
    assert canonical_key(
        gtin="NA0000086755", brand=None, model=None, sku="NA0000086755"
    ) is None


def test_sin_identidad_no_hay_llave():
    assert canonical_key(gtin=None, brand="Bosch", model=None) is None
    assert canonical_key(gtin=None, brand=None, model="iPhone 15") is None
    assert canonical_key(gtin=None, brand=None, model=None) is None


def test_gtin_y_marca_modelo_viven_en_espacios_separados():
    """Aunque los caracteres coincidan, nunca deben colisionar."""
    con_gtin = canonical_key(gtin="12345678", brand=None, model=None)
    con_modelo = canonical_key(gtin=None, brand="X", model="12345678")
    assert con_gtin != con_modelo


def test_modelo_corto_no_identifica():
    """'XL' o 'V2' aparecen en decenas de productos que no son el mismo."""
    assert normalize_model("XL") is None
    assert normalize_model("V2") is None
    assert normalize_model("A" * MIN_MODEL_LENGTH) is not None


def test_modelo_todo_digitos_y_corto_se_descarta():
    assert normalize_model("1234") is None
    assert normalize_model("123456") == "123456"


def test_modelo_colapsa_separadores():
    assert normalize_model("SM-A155M/DS") == "sma155mds"
    assert normalize_model("  Ryzen 5 5600X ") == "ryzen55600x"
    assert normalize_model("-") is None


# -----------------------------------------------------------------------------
# Asignación contra Postgres. `canonical_key` se prueba arriba en puro; esto
# prueba lo otro: que alguien la llame, que el upsert no duplique y que el
# cruce no confunda dos listings de la MISMA tienda con dos tiendas distintas.
# -----------------------------------------------------------------------------
import pytest

from catalog.identity import assign_products, cross_store_prices


async def _store_id(conn, slug: str) -> int:
    return await conn.fetchval("SELECT id FROM stores WHERE slug = $1", slug)


async def _listing(conn, *, slug: str, sku: str, gtin=None, brand=None, model=None):
    return await conn.fetchval(
        """
        INSERT INTO listings (store_id, store_sku, url, name_raw,
                              brand_raw, gtin_raw, model_raw)
             VALUES ($1, $2, $3, 'Producto', $4, $5, $6)
          RETURNING id
        """,
        await _store_id(conn, slug),
        sku,
        f"https://{slug}.cl/{sku}",
        brand,
        gtin,
        model,
    )


@pytest.mark.asyncio
async def test_el_mismo_gtin_en_dos_tiendas_cae_en_un_solo_product(
    db_conn, telegram_pool
):
    a = await _listing(db_conn, slug="paris", sku="p-1", gtin="884116671206")
    b = await _listing(db_conn, slug="spdigital", sku="s-1", gtin="884116671206")

    stats = await assign_products(telegram_pool)

    assert stats.linked == 2
    assert stats.products_created == 1
    ids = await db_conn.fetch(
        "SELECT product_id FROM listings WHERE id = ANY($1::int[])", [a, b]
    )
    assert len({r["product_id"] for r in ids}) == 1
    assert await db_conn.fetchval("SELECT count(*) FROM products") == 1


@pytest.mark.asyncio
async def test_recorrer_no_duplica_ni_reescanea(db_conn, telegram_pool):
    """Idempotencia: es lo que la habilita a correr en cada pasada del scraper."""
    await _listing(db_conn, slug="paris", sku="p-1", gtin="884116671206")

    primera = await assign_products(telegram_pool)
    segunda = await assign_products(telegram_pool)

    assert primera.linked == 1
    # La segunda no ve nada: `_load_unlinked` filtra por `product_id IS NULL`.
    assert segunda.scanned == 0 and segunda.linked == 0
    assert await db_conn.fetchval("SELECT count(*) FROM products") == 1


@pytest.mark.asyncio
async def test_sin_identidad_no_se_vincula(db_conn, telegram_pool):
    """El SKU interno que SP Digital pone en el campo del código de barras."""
    solo = await _listing(
        db_conn, slug="spdigital", sku="NA0000086755", gtin="NA0000086755"
    )

    stats = await assign_products(telegram_pool)

    assert stats.scanned == 1 and stats.linked == 0 and stats.skipped_no_identity == 1
    assert await db_conn.fetchval(
        "SELECT product_id FROM listings WHERE id = $1", solo
    ) is None


@pytest.mark.asyncio
async def test_el_cruce_no_compara_una_tienda_consigo_misma(db_conn, telegram_pool):
    """Paris publica el mismo GTIN bajo dos `store_sku`: no son dos tiendas.

    Sin el filtro por `store_id`, el copy saldría "más barato que en Paris"
    sobre una oferta que ES de Paris.
    """
    gtin = "8806091917027"
    propio = await _listing(db_conn, slug="paris", sku="218673999", gtin=gtin)
    gemelo = await _listing(db_conn, slug="paris", sku="EAGASW7UCP-1", gtin=gtin)
    await assign_products(telegram_pool)

    # Los dos comparten `product_id` — eso está bien, es el mismo producto.
    compartido = await db_conn.fetch(
        "SELECT product_id FROM listings WHERE id = ANY($1::int[])", [propio, gemelo]
    )
    assert len({r["product_id"] for r in compartido}) == 1

    for listing_id in (propio, gemelo):
        await db_conn.execute(
            """INSERT INTO price_points (listing_id, observed_at, price_effective,
                                         price_normal, in_stock)
               VALUES ($1, NOW(), 100000, 100000, TRUE)""",
            listing_id,
        )

    assert await cross_store_prices(db_conn, propio) == []


@pytest.mark.asyncio
async def test_el_cruce_si_devuelve_la_otra_tienda(db_conn, telegram_pool):
    gtin = "884116671206"
    propio = await _listing(db_conn, slug="paris", sku="p-1", gtin=gtin)
    otro = await _listing(db_conn, slug="spdigital", sku="s-1", gtin=gtin)
    await assign_products(telegram_pool)

    await db_conn.execute(
        """INSERT INTO price_points (listing_id, observed_at, price_effective,
                                     price_normal, in_stock)
           VALUES ($1, NOW(), 90000, 90000, TRUE)""",
        otro,
    )

    filas = await cross_store_prices(db_conn, propio)

    assert [f["store_slug"] for f in filas] == ["spdigital"]
    assert filas[0]["price_effective"] == 90000
