"""Fixtures compartidas: Postgres real para los tests que tocan DB.

Los tests portados de signalsTrading (gate, PayPal, trial, métricas) no usan
mocks de base: prueban SQL contra un Postgres de verdad, que es donde vive la
lógica que importa (locks, CHECKs, ON CONFLICT, orden de eventos). Eso exige una
DB de test real.

`TEST_DATABASE_URL` apunta a una base DESCARTABLE: el setup hace
`DROP SCHEMA public CASCADE`. Nunca apuntarla a la base de desarrollo. Si la
variable no está, o el Postgres no responde, los tests que piden `db_conn` /
`telegram_pool` se saltean — la suite pura (parsers, normalize, detector) sigue
corriendo en cualquier máquina sin Docker levantado.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

try:  # pragma: no cover - asyncpg siempre está en el venv del proyecto.
    import asyncpg
    import pytest_asyncio
except ImportError:  # pragma: no cover
    asyncpg = None
    pytest_asyncio = None


REPO_ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS_DIR = REPO_ROOT / "migrations"

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL", "").strip()

# El código bajo test lee `DATABASE_URL` del entorno (bot, webhook). Apuntarlo a
# la base de test evita que un test distraído escriba en la de desarrollo.
if TEST_DATABASE_URL:
    os.environ["DATABASE_URL"] = TEST_DATABASE_URL

_skip_no_db = pytest.mark.skipif(
    not TEST_DATABASE_URL,
    reason="TEST_DATABASE_URL no configurada (base de test descartable)",
)


class _Response:
    """Respuesta ya leída, con la forma que esperan los tests portados."""

    def __init__(self, status: int, body: str) -> None:
        self.status_code = status
        self.text = body

    def json(self):
        import json as _json

        return _json.loads(self.text)


class _HttpxLikeClient:
    """Adaptador mínimo sobre `aiohttp.test_utils.TestClient`."""

    def __init__(self, test_client) -> None:
        self._client = test_client

    async def post(self, path: str, *, json=None):
        resp = await self._client.post(path, json=json)
        return _Response(resp.status, await resp.text())

    async def get(self, path: str):
        resp = await self._client.get(path)
        return _Response(resp.status, await resp.text())


def _ordered_migrations() -> list[Path]:
    """Migraciones en orden NN, igual que `migrate.py`."""
    return sorted(MIGRATIONS_DIR.glob("*.sql"), key=lambda p: p.name)


async def _apply_schema(dsn: str) -> None:
    conn = await asyncpg.connect(dsn)
    try:
        await conn.execute("DROP SCHEMA IF EXISTS public CASCADE;")
        await conn.execute("CREATE SCHEMA public;")
        for path in _ordered_migrations():
            await conn.execute(path.read_text())
    finally:
        await conn.close()


#: Catálogos que sobreviven entre tests porque los siembran las migraciones y
#: re-crearlos en cada test sería re-ejecutar la seed entera.
_PRESERVE_TABLES = {"categories", "stores", "schema_migrations"}


async def _truncate_state(dsn: str) -> None:
    """Borra las filas de cada test preservando los catálogos sembrados.

    Se descubren las tablas por `information_schema` en vez de hardcodear una
    lista: así una migración nueva no deja datos colgando entre tests sin que
    nadie se entere.
    """
    conn = await asyncpg.connect(dsn)
    try:
        rows = await conn.fetch(
            """SELECT table_name FROM information_schema.tables
                WHERE table_schema = 'public' AND table_type = 'BASE TABLE'"""
        )
        targets = [
            r["table_name"] for r in rows if r["table_name"] not in _PRESERVE_TABLES
        ]
        if targets:
            quoted = ", ".join(f'"{t}"' for t in targets)
            await conn.execute(f"TRUNCATE {quoted} RESTART IDENTITY CASCADE;")
    finally:
        await conn.close()


if TEST_DATABASE_URL and pytest_asyncio is not None:

    @pytest_asyncio.fixture(scope="session", autouse=True)
    async def _setup_schema():
        await _apply_schema(TEST_DATABASE_URL)
        yield

    @pytest_asyncio.fixture(autouse=True)
    async def _clean_between_tests():
        await _truncate_state(TEST_DATABASE_URL)
        yield

    @pytest_asyncio.fixture
    async def db_conn():
        """Conexión directa para arrange/assert fuera del código bajo test."""
        conn = await asyncpg.connect(TEST_DATABASE_URL)
        try:
            yield conn
        finally:
            await conn.close()

    @pytest_asyncio.fixture
    async def telegram_pool():
        pool = await asyncpg.create_pool(TEST_DATABASE_URL, min_size=1, max_size=4)
        try:
            yield pool
        finally:
            await pool.close()

    @pytest_asyncio.fixture
    async def client(telegram_pool):
        """Cliente HTTP contra la app aiohttp del webhook PayPal.

        Se expone con la interfaz sincrónica de httpx (`status_code`, `.text`,
        `.json()`) porque así están escritos los tests portados y traducir cada
        assert a la API async de aiohttp solo agregaría ruido.
        """
        from aiohttp.test_utils import TestClient, TestServer

        from subscriptions.paypal.webhook import build_app

        async with TestClient(TestServer(build_app(telegram_pool))) as test_client:
            yield _HttpxLikeClient(test_client)

else:  # pragma: no cover - camino de "sin DB de test".

    @pytest.fixture
    def db_conn():
        pytest.skip("TEST_DATABASE_URL no configurada")

    @pytest.fixture
    def telegram_pool():
        pytest.skip("TEST_DATABASE_URL no configurada")

    @pytest.fixture
    def client():
        pytest.skip("TEST_DATABASE_URL no configurada")
