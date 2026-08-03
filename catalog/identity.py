"""Identidad de producto: agrupa el mismo artículo vendido en varias tiendas.

Esto NO alimenta el detector. El detector usa la historia propia de cada
`listing`, así que un match malo degrada el copy del mensaje ("$X más barato que
en Paris"), nunca la señal. Ese es exactamente el motivo por el que se puede ser
agresivo con el descarte: ante la duda, no se agrupa, y el sistema sigue igual
de correcto con menos adorno.

Jerarquía de identidad, de más fuerte a más débil:

    1. GTIN         — código de barras, único global. Es evidencia dura.
    2. (marca, modelo) — bueno cuando la tienda declara modelo de verdad.
    3. nada         — el listing queda sin `product_id` y no se cruza. Es el
                      caso normal hoy: 4 de las 6 tiendas no publican ninguno
                      de los dos en el listado.

El fuzzy sobre nombres que menciona el plan queda deliberadamente afuera: con
`gtin_raw` cubriendo Paris y SP Digital, el fuzzy solo agregaría los matches
dudosos, que son los que rompen el copy. Se reevalúa cuando F3 abra fichas.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any

import asyncpg

from catalog.normalize import normalize_brand, normalize_gtin

logger = logging.getLogger("catalog.identity")

#: Todo lo que no sea alfanumérico se colapsa: "SM-A155M/DS" y "sm a155m ds"
#: son el mismo modelo escrito por dos tiendas distintas.
_NON_ALNUM = re.compile(r"[^a-z0-9]+")

#: Un "modelo" más corto que esto no identifica nada: "L5", "V2", "XL" aparecen
#: en decenas de productos distintos y fusionarían cosas que no van juntas.
MIN_MODEL_LENGTH = 4


def normalize_model(raw: str | None) -> str | None:
    """Modelo comparable entre tiendas, o None si no sirve para identificar.

    >>> normalize_model("SM-A155M/DS")
    'sma155mds'
    >>> normalize_model("  iPhone 15  ")
    'iphone15'
    >>> normalize_model("XL")
    >>> normalize_model("-")
    """
    if raw is None:
        return None
    collapsed = _NON_ALNUM.sub("", raw.strip().lower())
    if len(collapsed) < MIN_MODEL_LENGTH:
        return None
    # Un modelo que es solo dígitos suele ser un SKU interno disfrazado.
    if collapsed.isdigit() and len(collapsed) < 6:
        return None
    return collapsed


def canonical_key(
    *, gtin: str | None, brand: str | None, model: str | None, sku: str | None = None
) -> str | None:
    """Llave estable del producto, o None si no hay identidad confiable.

    El prefijo mantiene los dos espacios separados a propósito: un GTIN y un
    (marca, modelo) nunca deben colisionar entre sí aunque coincidan los
    caracteres.

    >>> canonical_key(gtin="6932554471736", brand="Xiaomi", model="Redmi 13")
    'gtin:6932554471736'
    >>> canonical_key(gtin=None, brand="APPLE", model="iPhone 15")
    'bm:apple|iphone15'
    >>> canonical_key(gtin=None, brand="Bosch", model=None)
    >>> canonical_key(gtin=None, brand=None, model="iPhone 15")
    """
    clean_gtin = normalize_gtin(gtin, sku)
    if clean_gtin:
        return f"gtin:{clean_gtin}"

    clean_brand = normalize_brand(brand)
    clean_model = normalize_model(model)
    if clean_brand and clean_model:
        return f"bm:{clean_brand.lower()}|{clean_model}"
    return None


@dataclass(frozen=True)
class IdentityStats:
    """Qué pasó en una corrida de asignación."""

    scanned: int = 0
    linked: int = 0
    products_created: int = 0
    skipped_no_identity: int = 0

    def __str__(self) -> str:
        return (
            f"{self.scanned} listings revisados, {self.linked} vinculados "
            f"({self.products_created} productos nuevos), "
            f"{self.skipped_no_identity} sin identidad"
        )


async def _load_unlinked(conn: asyncpg.Connection, limit: int) -> list[dict[str, Any]]:
    rows = await conn.fetch(
        """
        SELECT id, store_sku, name_raw, brand_raw, gtin_raw, model_raw, category_id
          FROM listings
         WHERE product_id IS NULL
           AND (gtin_raw IS NOT NULL OR model_raw IS NOT NULL)
         ORDER BY id
         LIMIT $1
        """,
        limit,
    )
    return [dict(r) for r in rows]


async def _upsert_product(
    conn: asyncpg.Connection, key: str, row: dict[str, Any]
) -> tuple[int, bool]:
    """`(product_id, se_creó)` para la llave dada.

    Los campos descriptivos se completan con COALESCE por la misma razón que en
    `listings`: la tienda que aportó el GTIN puede no ser la que aporta la
    marca, y una pasada posterior sin el dato no puede borrarlo.
    """
    # `xmax = 0` distingue el INSERT del UPDATE en un upsert: en la fila recién
    # insertada no hay transacción que la haya borrado/actualizado.
    row_out = await conn.fetchrow(
        """
        INSERT INTO products (canonical_key, brand, model, gtin, name, category_id)
             VALUES ($1, $2, $3, $4, $5, $6)
        ON CONFLICT (canonical_key) DO UPDATE
                SET brand       = COALESCE(products.brand, EXCLUDED.brand),
                    model       = COALESCE(products.model, EXCLUDED.model),
                    gtin        = COALESCE(products.gtin, EXCLUDED.gtin),
                    name        = COALESCE(products.name, EXCLUDED.name),
                    category_id = COALESCE(products.category_id, EXCLUDED.category_id)
          RETURNING id, (xmax = 0) AS created
        """,
        key,
        normalize_brand(row["brand_raw"]),
        row["model_raw"],
        normalize_gtin(row["gtin_raw"], row["store_sku"]),
        row["name_raw"],
        row["category_id"],
    )
    return int(row_out["id"]), bool(row_out["created"])


async def assign_products(
    pool: asyncpg.Pool, *, batch_size: int = 5000
) -> IdentityStats:
    """Vincula listings sueltos a `products`. Idempotente: re-correr no duplica.

    Solo mira listings con `product_id IS NULL`; los ya vinculados no se
    revisan, porque una llave no cambia salvo que la tienda corrija el dato, y
    ese caso es tan raro que no justifica reescanear la tabla entera dos veces
    por día.
    """
    scanned = linked = created = skipped = 0
    async with pool.acquire() as conn:
        rows = await _load_unlinked(conn, batch_size)
        scanned = len(rows)
        for row in rows:
            key = canonical_key(
                gtin=row["gtin_raw"],
                brand=row["brand_raw"],
                model=row["model_raw"],
                sku=row["store_sku"],
            )
            if key is None:
                skipped += 1
                continue
            async with conn.transaction():
                product_id, was_created = await _upsert_product(conn, key, row)
                await conn.execute(
                    "UPDATE listings SET product_id = $2 WHERE id = $1",
                    row["id"],
                    product_id,
                )
            linked += 1
            created += int(was_created)

    stats = IdentityStats(scanned, linked, created, skipped)
    logger.info("identidad: %s", stats)
    return stats


async def cross_store_prices(
    conn: asyncpg.Connection, listing_id: int
) -> list[dict[str, Any]]:
    """El mismo producto en otras tiendas, con su último precio observado.

    Es todo lo que el publisher necesita para el "más barato que en X". Devuelve
    lista vacía cuando el listing no está vinculado, que es el caso mayoritario.
    """
    rows = await conn.fetch(
        """
        SELECT s.slug AS store_slug,
               o.id   AS listing_id,
               o.url,
               pp.price_effective,
               pp.observed_at
          FROM listings AS l
          JOIN listings AS o  ON o.product_id = l.product_id AND o.id <> l.id
          JOIN stores   AS s  ON s.id = o.store_id
          JOIN LATERAL (
               SELECT price_effective, observed_at
                 FROM price_points
                WHERE listing_id = o.id
                ORDER BY observed_at DESC
                LIMIT 1
          ) AS pp ON TRUE
         WHERE l.id = $1
           AND l.product_id IS NOT NULL
           AND o.is_active
         ORDER BY pp.price_effective
        """,
        listing_id,
    )
    return [dict(r) for r in rows]
