"""Contrato de Rockford con payload público real del 2026-11-06.

El fixture incluye talles disponibles, mixtos y un producto enteramente agotado.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from scrapers.base import CategoryRef
from scrapers.stores.rockford import RockfordAdapter
from scrapers.stores.shopify_family import NotAListingPage, parse_listing


FIXTURE = Path(__file__).parent / "fixtures" / "rockford_hombre_vestuario.json"
CATEGORY = CategoryRef(
    slug="ropa-vestuario", store_key="hombre-vestuario", label="Vestuario hombre"
)
NOW = datetime(2026, 11, 6, 14, 30, tzinfo=timezone.utc)


def _products():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))["products"]


def _parse(payload):
    return parse_listing(
        payload,
        store_slug=RockfordAdapter.slug,
        base_url=RockfordAdapter.base_url,
        category=CATEGORY,
        scraped_at=NOW,
        non_brand_vendors=RockfordAdapter.non_brand_vendors,
        emitir_por_producto=RockfordAdapter.emitir_por_producto,
    )


def test_fixture_real_emite_producto_y_respeta_stock():
    rows = _parse({"products": _products()})
    assert len(rows) == 3
    assert {p.store_sku for p in rows} == {
        "11053777125412", "8209747279908", "8209911349284"
    }
    by_id = {p.store_sku: p for p in rows}
    assert by_id["8209747279908"].in_stock is True  # primer talle agotado
    assert by_id["8209911349284"].in_stock is False
    assert by_id["8209911349284"].price_effective == Decimal("41245")
    assert by_id["8209911349284"].price_normal == Decimal("74990")
    assert all("?variant=" not in p.url for p in rows)
    assert all(p.price_card is None and p.claimed_discount is None for p in rows)
    assert all(p.gtin is None and p.model is None for p in rows)


def test_vendor_interno_no_inventa_marca_columbia():
    polar = next(p for p in _parse({"products": _products()}) if "Columbia" in p.name)
    assert polar.brand is None  # el JSON dice vendor=rockfordcl
    assert polar.in_stock is False


@pytest.mark.asyncio
async def test_paginacion_y_dedupe_en_las_dos_llaves_del_mismo_rubro():
    first, mixed, exhausted = _products()
    second = CategoryRef(
        slug="ropa-vestuario", store_key="mujer-vestuario", label="Vestuario mujer"
    )
    class FakeHttp:
        def __init__(self):
            self.calls = []

        async def get_text(self, url, *, rps, headers):
            self.calls.append((url, rps, headers))
            if "hombre-vestuario" in url:
                rows = [first, mixed] if "page=1" in url else []
            else:
                rows = [mixed, exhausted] if "page=1" in url else []
            return json.dumps({"products": rows})

    http = FakeHttp()
    adapter = RockfordAdapter(http, [CATEGORY, second])
    rows = []
    for cat in adapter.categories():
        rows.extend([p async for p in adapter.discover(cat)])
    assert len(rows) == 3
    assert len({p.store_sku for p in rows}) == 3
    assert [p.category_path for p in rows] == ["ropa-vestuario"] * 3
    assert len(http.calls) == 4  # dos primeras páginas y dos finales vacías
    assert all("/collections/" in url and "limit=250" in url for url, _, _ in http.calls)
    assert all(rps == 0.5 and headers is None for _, rps, headers in http.calls)


@pytest.mark.asyncio
async def test_primera_pagina_vacia_es_error_no_exito():
    class FakeHttp:
        async def get_text(self, url, *, rps, headers):
            return '{"products": []}'

    with pytest.raises(NotAListingPage):
        _ = [p async for p in RockfordAdapter(FakeHttp(), [CATEGORY]).discover(CATEGORY)]
