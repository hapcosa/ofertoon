"""La condición del precio de punta a punta: payload → serie → mensaje.

`test_unimarc.py` prueba que el adaptador la lea y `test_promo_cantidad.py` que
el copy la imprima. Lo que solo se puede probar contra Postgres son las dos
junturas donde el dato se pierde sin que nadie se entere:

1. que la observación la **persista** (migración 47 y `db.insert_price_point`);
2. que el ranker la traiga **de la observación que se publica** y no de otra —
   el mismo riesgo que documenta `test_pum.py`, y acá es peor: una condición
   traída de otra observación diría "Club Unimarc" sobre un precio que no lo es,
   o peor, callaría la del precio que sí lo exige.

Necesita `TEST_DATABASE_URL` apuntando a una base descartable; sin ella se
saltea.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import asyncpg
import pytest

import db
from scrapers.base import CategoryRef
from scrapers.stores.unimarc import listing_data, parse_product

pytestmark = pytest.mark.asyncio

FIXTURE = Path(__file__).parent / "fixtures" / "unimarc_lacteos_p1.html"
CATEGORY = CategoryRef(
    slug="supermercado", store_key="lacteos-huevos-y-refrigerados", label="Supermercado"
)
OBSERVED = datetime.now(timezone.utc) - timedelta(hours=1)

#: Club Unimarc con precio menor al de lista: $1.190 contra $1.350.
SKU_CLUB = "2896"
#: Sin etiqueta y con precio igual al de lista: no hay condición que declarar.
SKU_SIN_CONDICION = "97541"


def _productos():
    _, _, disponibles, _ = listing_data(FIXTURE.read_text(encoding="utf-8"))
    return [
        p
        for p in (
            parse_product(i, category=CATEGORY, in_stock=True, scraped_at=OBSERVED)
            for i in disponibles
        )
        if p is not None
    ]


async def _ids(conn) -> tuple[int, int]:
    """(store_id, category_id). Unimarc la siembra la migración 47."""
    store_id = await conn.fetchval("SELECT id FROM stores WHERE slug = 'unimarc'")
    category_id = await conn.fetchval(
        "SELECT id FROM categories WHERE slug = 'supermercado'"
    )
    assert store_id and category_id, "la migración 47 no sembró la tienda"
    return store_id, category_id


async def test_la_migracion_47_sembro_la_tienda(db_conn):
    """Verifica el efecto, no el mensaje: `0 migración(es) aplicada(s)` se lee
    igual en una corrida sana y en una imagen vieja.

    ⚠️ Acá solo se puede comprobar `stores`. Las ocho `store_categories` que la
    migración siembra **no** son verificables desde un test: `_truncate_state`
    del conftest preserva `categories`, `stores` y `schema_migrations`, y trunca
    todo el resto entre tests — `store_categories` incluida. O sea una migración
    que sembrara llaves equivocadas pasaría la suite igual. Esa parte se verifica
    aplicando la migración a una base descartable y leyendo las filas; está
    hecho y anotado en `research/2026-11-06/INVESTIGACION_unimarc.md` §7.
    """
    fila = await db_conn.fetchrow(
        "SELECT name, base_url, adapter, rate_limit_rps, is_active "
        "FROM stores WHERE slug = 'unimarc'"
    )
    assert fila is not None, "la migración 47 no sembró la tienda"
    assert fila["adapter"] == "scrapers.stores.unimarc:UnimarcAdapter"
    assert fila["base_url"] == "https://www.unimarc.cl"
    assert fila["rate_limit_rps"] == Decimal("0.4")
    assert fila["is_active"] is True


async def test_la_observacion_guarda_la_condicion(db_conn, telegram_pool):
    """Antes de la migración 47 el dato llegaba en el payload y se tiraba, y el
    canal publicaba un precio Club sin decir que había que ser Club."""
    store_id, category_id = await _ids(db_conn)
    productos = _productos()
    assert len(productos) == 7

    escritas = await db.persist_batch(
        telegram_pool, productos, store_id=store_id, category_id=category_id
    )
    assert escritas == 7

    club = await db_conn.fetchrow(
        """SELECT pp.price_effective, pp.price_normal, pp.price_condition
             FROM price_points AS pp
             JOIN listings     AS l ON l.id = pp.listing_id
            WHERE l.store_sku = $1""",
        SKU_CLUB,
    )
    assert club["price_effective"] == Decimal("1190.00")
    assert club["price_normal"] == Decimal("1350.00")
    assert club["price_condition"] == "Club Unimarc"

    # El caso de control, en la misma corrida: sin etiqueta no se inventa una.
    sin_condicion = await db_conn.fetchval(
        """SELECT pp.price_condition
             FROM price_points AS pp
             JOIN listings     AS l ON l.id = pp.listing_id
            WHERE l.store_sku = $1""",
        SKU_SIN_CONDICION,
    )
    assert sin_condicion is None


async def test_el_check_impide_una_condicion_vacia(db_conn):
    """Una condición vacía no es una condición: produciría "Requiere " sobre una
    oferta sin letra chica. O hay texto o es NULL."""
    store_id, category_id = await _ids(db_conn)
    listing_id = await db_conn.fetchval(
        """INSERT INTO listings (store_id, category_id, store_sku, url, name_raw)
                VALUES ($1, $2, 'condicion-vacia', 'https://x.cl/p', 'X') RETURNING id""",
        store_id,
        category_id,
    )
    with pytest.raises(asyncpg.IntegrityConstraintViolationError):
        await db_conn.execute(
            """INSERT INTO price_points (listing_id, observed_at, price_effective,
                                         in_stock, price_condition)
                    VALUES ($1, $2, 1000, TRUE, '   ')""",
            listing_id,
            OBSERVED,
        )


async def test_la_condicion_es_de_la_observacion_que_se_publica(db_conn, telegram_pool):
    """El mismo riesgo que `test_pum.py`: el ranker joinea `price_points` por
    `(listing_id, detected_at)`. Si esa igualdad dejara de valer, el mensaje
    podría declarar la condición de una observación distinta de la que muestra —
    o callar la de la que muestra, que es peor.

    Se escriben DOS observaciones del mismo listing con condiciones distintas y
    se verifica que cada una conserva la suya.
    """
    store_id, category_id = await _ids(db_conn)
    club = next(p for p in _productos() if p.store_sku == SKU_CLUB)
    await db.persist_batch(
        telegram_pool, [club], store_id=store_id, category_id=category_id
    )

    # Una hora después la tienda ya no declara el Club: mismo listing, otra
    # observación, sin condición.
    from dataclasses import replace

    despues = replace(
        club,
        scraped_at=club.scraped_at + timedelta(minutes=30),
        price_effective=Decimal("1350"),
        price_normal=None,
        price_condition=None,
    )
    await db.persist_batch(
        telegram_pool, [despues], store_id=store_id, category_id=category_id
    )

    filas = await db_conn.fetch(
        """SELECT pp.observed_at, pp.price_effective, pp.price_condition
             FROM price_points AS pp
             JOIN listings     AS l ON l.id = pp.listing_id
            WHERE l.store_sku = $1
            ORDER BY pp.observed_at""",
        SKU_CLUB,
    )
    assert len(filas) == 2
    assert (filas[0]["price_effective"], filas[0]["price_condition"]) == (
        Decimal("1190.00"),
        "Club Unimarc",
    )
    assert (filas[1]["price_effective"], filas[1]["price_condition"]) == (
        Decimal("1350.00"),
        None,
    )
