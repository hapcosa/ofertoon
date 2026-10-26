"""El `pum` de punta a punta: payload de la tienda → serie → mensaje del canal.

Los tests de `test_tottus.py` prueban que el parser lo lea y los de
`test_formatter.py` que el copy lo muestre. Lo que falta probar —y solo se puede
contra Postgres— son las dos junturas donde el dato se puede perder sin que nadie
se entere:

1. que la observación lo **persista** (la migración 34 y `db.insert_price_point`);
2. que el ranker lo traiga **de la observación que se publica** y no de otra.

La segunda es la que importa: el join va contra `price_points` por
`(listing_id, detected_at)`, y si esa igualdad dejara de valer el mensaje diría
el precio por kilo de un precio distinto del que muestra. Eso no lo ve ningún
test puro.

Necesita `TEST_DATABASE_URL` apuntando a una base descartable; sin ella se
saltea.
"""
from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import asyncpg
import pytest

import db
from curation import ranker
from publisher import formatter
from scrapers.base import CategoryRef
from scrapers.stores.falabella_family import parse_listing

pytestmark = pytest.mark.asyncio

FIXTURE = Path(__file__).parent / "fixtures" / "tottus_aseo_limpieza.html"
CATEGORY = CategoryRef(
    slug="supermercado", store_key="CATG27074/Aseo-y-Limpieza", label="Aseo y Limpieza"
)

#: Una hora atrás: dentro de la partición del mes en curso (la crean las
#: migraciones) y dentro de `ranker.MAX_AGE_HOURS`, así que el candidato está
#: fresco sin tener que inyectar un reloj.
OBSERVED = datetime.now(timezone.utc) - timedelta(hours=1)

#: El SKU del fixture con `normalPrice` tachado y pum por litro: $4.190 el
#: producto, $2.095 el litro (2 L).
SKU = "119445474"


def _productos():
    return parse_listing(
        FIXTURE.read_text(encoding="utf-8"),
        store_slug="tottus",
        category=CATEGORY,
        scraped_at=OBSERVED,
    )[0]


async def _ids(conn) -> tuple[int, int]:
    """(store_id, category_id) de Tottus/supermercado, sembrados por la migración 27."""
    store_id = await conn.fetchval("SELECT id FROM stores WHERE slug = 'tottus'")
    category_id = await conn.fetchval(
        "SELECT id FROM categories WHERE slug = 'supermercado'"
    )
    assert store_id and category_id
    return store_id, category_id


# -----------------------------------------------------------------------------
# Persistencia
# -----------------------------------------------------------------------------


async def test_la_observacion_guarda_el_pum_con_su_base(db_conn, telegram_pool):
    """Antes de la migración 34 el dato llegaba en el payload y se tiraba."""
    store_id, category_id = await _ids(db_conn)
    productos = _productos()

    escritas = await db.persist_batch(
        telegram_pool, productos, store_id=store_id, category_id=category_id
    )
    assert escritas == len(productos) == 6

    row = await db_conn.fetchrow(
        """
        SELECT pp.price_effective, pp.pum_price, pp.pum_label
          FROM price_points AS pp
          JOIN listings     AS l ON l.id = pp.listing_id
         WHERE l.store_sku = $1
        """,
        SKU,
    )
    assert row["price_effective"] == Decimal("4190.00")
    assert row["pum_price"] == Decimal("2095.00")
    assert row["pum_label"] == "LT"

    # Las seis del fixture lo traen; ninguna quedó a medias.
    faltantes = await db_conn.fetchval(
        """SELECT count(*) FROM price_points
            WHERE (pum_price IS NULL) <> (pum_label IS NULL)"""
    )
    assert faltantes == 0


async def test_una_observacion_sin_pum_se_guarda_igual(db_conn, telegram_pool):
    """El 5% del supermercado no lo trae y el resto del canal casi nunca.

    Que falte no puede frenar nada: la fila entra con las dos columnas en NULL.
    """
    store_id, category_id = await _ids(db_conn)
    sin_pum = replace(
        next(p for p in _productos() if p.store_sku == SKU), pum=None
    )

    await db.persist_batch(
        telegram_pool, [sin_pum], store_id=store_id, category_id=category_id
    )

    row = await db_conn.fetchrow(
        """SELECT pp.pum_price, pp.pum_label
             FROM price_points AS pp
             JOIN listings     AS l ON l.id = pp.listing_id
            WHERE l.store_sku = $1""",
        SKU,
    )
    assert (row["pum_price"], row["pum_label"]) == (None, None)


async def test_el_check_impide_un_precio_por_unidad_sin_su_unidad(db_conn):
    """Un número sin su base no se puede interpretar: la fila no debe existir.

    Es la regla "label y precio van juntos" puesta en la base y no solo en el
    dataclass, porque lo que lee el ranker es la tabla.
    """
    store_id, category_id = await _ids(db_conn)
    listing_id = await db_conn.fetchval(
        """INSERT INTO listings (store_id, category_id, store_sku, url, name_raw)
                VALUES ($1, $2, 'solo-numero', 'https://x.cl/p', 'X') RETURNING id""",
        store_id,
        category_id,
    )
    with pytest.raises(asyncpg.CheckViolationError):
        await db_conn.execute(
            """INSERT INTO price_points (listing_id, observed_at, price_effective,
                                         pum_price)
                    VALUES ($1, $2, 4190, 2095)""",
            listing_id,
            OBSERVED,
        )


# -----------------------------------------------------------------------------
# El ranker: el pum DE LA OBSERVACIÓN QUE SE PUBLICA
# -----------------------------------------------------------------------------


async def _candidato_publicable(conn, pool) -> ranker.Candidate:
    """Siembra la cadena mínima y devuelve el candidato que vería el poster."""
    store_id, category_id = await _ids(conn)
    await db.persist_batch(
        pool, _productos(), store_id=store_id, category_id=category_id
    )
    listing_id = await conn.fetchval(
        "SELECT id FROM listings WHERE store_sku = $1", SKU
    )
    tier_id = await conn.fetchval(
        """INSERT INTO telegram_tiers (name, slug, telegram_channel_id, is_active)
                VALUES ('Ofertoon VIP', 'vip', -1003914468578, TRUE) RETURNING id"""
    )
    await conn.execute(
        "INSERT INTO telegram_tier_categories (tier_id, category_id) VALUES ($1, $2)",
        tier_id,
        category_id,
    )
    # `detected_at` ES el `observed_at` de la observación evaluada: así lo escribe
    # `detector._load_candidates`, y de esa igualdad depende el join del ranker.
    await conn.execute(
        """INSERT INTO deal_candidates (listing_id, detected_at, price, p50_60d,
                                        discount_real, score, verdict)
                VALUES ($1, $2, 4190, 5990, 0.3005, 30.05, 'accepted')""",
        listing_id,
        OBSERVED,
    )
    candidatos = await ranker.load_candidates(
        conn, tier_id=tier_id, now=datetime.now(timezone.utc)
    )
    assert len(candidatos) == 1
    return candidatos[0]


async def test_el_ranker_trae_el_pum_de_esa_observacion(db_conn, telegram_pool):
    candidate = await _candidato_publicable(db_conn, telegram_pool)

    assert candidate.category_slug == "supermercado"
    assert candidate.pum_label == "LT"
    assert candidate.pum_price == Decimal("2095.00")


async def test_el_mensaje_del_canal_sale_con_el_precio_por_litro(
    db_conn, telegram_pool
):
    """El cierre de la Fase 1: el dato llega hasta el texto que lee el suscriptor.

    $2.095 el litro hoy contra un p50 de $5.990 llevado a la misma base
    ($5.990 × 2.095 / 4.190 = $2.995).
    """
    candidate = await _candidato_publicable(db_conn, telegram_pool)
    message = formatter.format_deal(candidate)

    assert "📦 $2.095 por LT  ·  antes real $2.995" in message


async def test_otra_observacion_del_mismo_listing_no_contamina_el_mensaje(
    db_conn, telegram_pool
):
    """La prueba del join, y la razón por la que no se usa "el último pum".

    Si el ranker mirara la observación más reciente en vez de la publicada, una
    pasada posterior con otro envase o otra base cambiaría el precio por litro de
    un mensaje cuyo precio de producto es el de antes.
    """
    candidate = await _candidato_publicable(db_conn, telegram_pool)
    await db_conn.execute(
        """INSERT INTO price_points (listing_id, observed_at, price_effective,
                                     pum_price, pum_label)
                VALUES ($1, $2, 9990, 9990, 'KG')""",
        candidate.listing_id,
        OBSERVED + timedelta(minutes=30),
    )

    de_nuevo = await ranker.load_candidates(
        conn=db_conn,
        tier_id=await db_conn.fetchval("SELECT id FROM telegram_tiers LIMIT 1"),
        now=datetime.now(timezone.utc),
    )
    assert [(c.pum_price, c.pum_label) for c in de_nuevo] == [
        (Decimal("2095.00"), "LT")
    ]
