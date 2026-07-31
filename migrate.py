"""Runner idempotente de migraciones.

Mismo mecanismo que el `db-migrate` de signalsTrading: una tabla
`schema_migrations` registra lo aplicado y cada archivo corre una sola vez, en
orden alfabético (el prefijo `NN_` es el orden canónico). Re-ejecutar es no-op.

Uso:
    python migrate.py              # aplica lo pendiente
    python migrate.py --status     # lista aplicadas / pendientes sin tocar nada
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import logging
import os
import sys
from pathlib import Path

import asyncpg

logger = logging.getLogger("migrate")

MIGRATIONS_DIR = Path(__file__).parent / "migrations"

_BOOTSTRAP = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    filename    TEXT PRIMARY KEY,
    checksum    TEXT NOT NULL,
    applied_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
"""


def discover() -> list[Path]:
    return sorted(MIGRATIONS_DIR.glob("*.sql"))


def checksum(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:32]


async def apply_all(conn: asyncpg.Connection, *, dry_run: bool = False) -> int:
    await conn.execute(_BOOTSTRAP)
    applied = {
        r["filename"]: r["checksum"]
        for r in await conn.fetch("SELECT filename, checksum FROM schema_migrations")
    }

    pending = 0
    for path in discover():
        digest = checksum(path)
        known = applied.get(path.name)

        if known is not None:
            if known != digest:
                # Editar una migración ya aplicada rompe la reproducibilidad: lo
                # que corrió en prod dejó de existir en el repo. Se avisa fuerte.
                logger.error(
                    "checksum_mismatch %s — el archivo cambió DESPUÉS de aplicarse. "
                    "Escribí una migración nueva en vez de editar esta.",
                    path.name,
                )
            continue

        pending += 1
        if dry_run:
            logger.info("PENDIENTE %s", path.name)
            continue

        logger.info("aplicando %s", path.name)
        async with conn.transaction():
            await conn.execute(path.read_text(encoding="utf-8"))
            await conn.execute(
                "INSERT INTO schema_migrations (filename, checksum) VALUES ($1, $2)",
                path.name,
                digest,
            )

    if not dry_run and pending:
        # Las particiones del mes en curso y los siguientes se aseguran en cada
        # arranque, no solo cuando corre la migración que creó la función.
        await conn.execute("SELECT ensure_price_partitions(2)")

    return pending


async def main() -> int:
    parser = argparse.ArgumentParser(description="Runner de migraciones OfertasCL")
    parser.add_argument("--status", action="store_true", help="solo listar pendientes")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    dsn = os.environ.get("DATABASE_URL", "").strip()
    if not dsn:
        logger.error("DATABASE_URL es obligatoria")
        return 2

    conn = await asyncpg.connect(dsn)
    try:
        pending = await apply_all(conn, dry_run=args.status)
    finally:
        await conn.close()

    if args.status:
        logger.info("%d migración(es) pendiente(s)", pending)
    else:
        logger.info("listo — %d migración(es) aplicada(s)", pending)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
