"""Cableado de `scrape_target`: qué lee, qué escribe y qué reporta.

La lógica del canario se prueba pura en `test_runner_canary.py`; acá se prueba
lo que la rodea, que es donde un bug duele: que la historia se pida para el
target correcto (tienda, categoría, store_key) y que el `store_key` quede
persistido en la corrida — sin él la mediana mezcla targets incomparables.
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime, timezone
from decimal import Decimal

import pytest

import db as db_module
from scrapers import runner
from scrapers.base import CategoryRef, RawProduct


class FakePool:
    """Lo único que el runner le pide a un pool es `acquire()`."""

    def __init__(self):
        self.conn = object()

    @asynccontextmanager
    async def acquire(self):
        yield self.conn


class FakeAdapter:
    slug = "spdigital"
    rate_limit_rps = 0.2

    def __init__(self, items):
        self._items = items

    async def discover(self, category):
        for i in range(self._items):
            yield RawProduct(
                store_slug=self.slug,
                store_sku=f"sku-{i}",
                url=f"https://example.cl/{i}",
                name=f"Producto {i}",
                price_effective=Decimal("199990"),
                scraped_at=datetime.now(timezone.utc),
            )


@pytest.fixture
def calls(monkeypatch):
    """Intercepta el acceso a datos y registra cada llamada."""
    registro = {"history_args": None, "start_args": None, "finish_args": None}

    async def fake_recent(conn, **kwargs):
        registro["history_args"] = kwargs
        return registro.get("history", [])

    async def fake_start(conn, **kwargs):
        registro["start_args"] = kwargs
        return 777

    async def fake_finish(conn, run_id, **kwargs):
        registro["finish_args"] = {"run_id": run_id, **kwargs}

    async def fake_persist(pool, products, **kwargs):
        return len(products)

    monkeypatch.setattr(db_module, "recent_items_seen", fake_recent)
    monkeypatch.setattr(db_module, "start_run", fake_start)
    monkeypatch.setattr(db_module, "finish_run", fake_finish)
    monkeypatch.setattr(db_module, "persist_batch", fake_persist)
    return registro


TARGET = {
    "category_id": 1,
    "category": CategoryRef(slug="tecno", store_key="Q2F0ZWdvcnk6MTIzOA==", label="Notebooks"),
}


async def test_historia_y_corrida_van_por_store_key(calls):
    calls["history"] = [88, 90, 89]
    outcome = await runner.scrape_target(
        FakePool(), FakeAdapter(87), TARGET, store_id=6, dry_run=False
    )

    assert calls["history_args"] == {
        "store_id": 6,
        "category_id": 1,
        "store_key": "Q2F0ZWdvcnk6MTIzOA==",
        "window": runner.CANARY_WINDOW,
    }
    assert calls["start_args"] == {
        "store_id": 6,
        "category_id": 1,
        "store_key": "Q2F0ZWdvcnk6MTIzOA==",
    }
    assert outcome.status == "ok"
    assert (outcome.store_slug, outcome.store_key) == ("spdigital", "Q2F0ZWdvcnk6MTIzOA==")


async def test_derrumbe_de_volumen_cierra_la_corrida_como_partial(calls):
    """El caso real: la store_key de 88 items devolviendo 7."""
    calls["history"] = [88, 90, 89, 91]
    outcome = await runner.scrape_target(
        FakePool(), FakeAdapter(7), TARGET, store_id=6, dry_run=False
    )

    assert outcome.status == "partial"
    assert calls["finish_args"]["status"] == "partial"
    assert calls["finish_args"]["items_seen"] == 7
    assert "mediana" in calls["finish_args"]["error"]


async def test_excepcion_del_adaptador_se_reporta_failed(calls):
    class Roto(FakeAdapter):
        async def discover(self, category):
            raise RuntimeError("cambió el JSON")
            yield  # pragma: no cover — hace de esto un generador

    calls["history"] = [88, 90, 89]
    outcome = await runner.scrape_target(
        FakePool(), Roto(0), TARGET, store_id=6, dry_run=False
    )

    assert outcome.status == "failed"
    assert "cambió el JSON" in outcome.error
    assert calls["finish_args"]["status"] == "failed"


async def test_dry_run_no_toca_la_db(calls):
    outcome = await runner.scrape_target(
        FakePool(), FakeAdapter(30), TARGET, store_id=6, dry_run=True
    )

    assert calls["history_args"] is None
    assert calls["start_args"] is None
    assert calls["finish_args"] is None
    assert outcome.status == "ok" and outcome.items_seen == 30
