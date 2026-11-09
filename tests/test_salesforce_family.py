"""Contratos con dos tiles reales de cada listado, capturados 2026-11-09."""
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from scrapers.base import CategoryRef
from scrapers.http import BROWSER_HEADERS
from scrapers.stores.salesforce_family import (
    ABCAdapter, ABC_ZONE, InvalidListing, TricotAdapter,
    parse_abc_listing, parse_tricot_listing,
)


FIXTURES = Path(__file__).parent / "fixtures"
NOW = datetime(2026, 11, 9, tzinfo=timezone.utc)
ABC_CAT = CategoryRef("ropa-vestuario", "mujer/ropa-mujer")
TRICOT_CAT = CategoryRef("ropa-accesorios", "accesorios/mujer/bananos")


def fixture(name):
    return (FIXTURES / name).read_text(encoding="utf-8")


def test_abc_wrapper_real_no_triplica_data_pid_y_separa_precio_normal():
    products, ids, total = parse_abc_listing(
        fixture("abc_ropa_mujer.html"), category=ABC_CAT, scraped_at=NOW)
    assert len(products) == len(ids) == 2
    assert total == 820
    first = next(p for p in products if p.store_sku == "635116")
    assert first.price_effective == Decimal("5500")
    assert first.price_normal == Decimal("16990")
    assert first.price_card is None
    assert first.in_stock is True
    assert first.brand == "ICONO"
    assert first.gtin is None
    assert "zone=inventory_LaPolar_whven%7Ct_ecom_metropolitana" in first.url


def test_tricot_usa_dos_links_reales_y_el_total_resultados():
    products, ids, total = parse_tricot_listing(
        fixture("tricot_bananos.html"), category=TRICOT_CAT, scraped_at=NOW)
    assert len(products) == len(ids) == 2
    assert total == 10
    first = next(p for p in products if p.store_sku == "643048")
    assert first.price_effective == Decimal("8990")
    assert first.price_normal == Decimal("39990")
    assert first.in_stock is True
    assert first.gtin is None
    assert first.url == "https://www.tricot.cl/banano-mujer-liso-643048.html"


@pytest.mark.asyncio
async def test_abc_paginas_permitidas_y_canario_exacto():
    class FakeHttp:
        def __init__(self):
            self.calls = []

        async def get_text(self, url, *, rps, headers):
            self.calls.append((url, rps, headers))
            if "start=0" in url:
                return fixture("abc_ropa_mujer.html")
            return '<title>Ropa Mujer | Abc</title><link rel="canonical" href="https://www.abc.cl/mujer/ropa-mujer/?sz=36&amp;start=36">'

    http = FakeHttp()
    adapter = ABCAdapter(http, [ABC_CAT])
    rows = [p async for p in adapter.discover(ABC_CAT)]
    assert len(rows) == 2
    assert adapter.completeness(ABC_CAT) == (2, 820)
    assert len(http.calls) == 2
    assert "start=0&sz=36" in http.calls[0][0]
    assert "start=36&sz=36" in http.calls[1][0]
    assert all(ABC_ZONE.split("|")[0] in url and rps == 0.5 and headers == BROWSER_HEADERS
               for url, rps, headers in http.calls)


@pytest.mark.asyncio
async def test_tricot_no_pide_query_y_declara_cobertura_parcial():
    class FakeHttp:
        def __init__(self):
            self.calls = []

        async def get_text(self, url, *, rps, headers):
            self.calls.append(url)
            return fixture("tricot_bananos.html")

    http = FakeHttp()
    adapter = TricotAdapter(http, [TRICOT_CAT])
    rows = [p async for p in adapter.discover(TRICOT_CAT)]
    assert len(rows) == 2
    assert adapter.completeness(TRICOT_CAT) == (2, 10)
    assert http.calls == ["https://www.tricot.cl/accesorios/mujer/bananos"]


@pytest.mark.asyncio
async def test_tricot_rechaza_query_en_llave():
    bad = CategoryRef("ropa-accesorios", "accesorios/mujer/bananos?start=60")
    with pytest.raises(InvalidListing):
        _ = [p async for p in TricotAdapter(None, [bad]).discover(bad)]


@pytest.mark.asyncio
async def test_tricot_rechaza_sku_que_cruza_categorias_internas():
    class FakeHttp:
        async def get_text(self, url, *, rps, headers):
            return fixture("tricot_bananos.html")

    other = CategoryRef("ropa-calzado", "calzado/mujer/zapatillas")
    adapter = TricotAdapter(FakeHttp(), [TRICOT_CAT, other])
    assert len([p async for p in adapter.discover(TRICOT_CAT)]) == 2
    with pytest.raises(InvalidListing, match="cruza"):
        _ = [p async for p in adapter.discover(other)]


def test_falta_total_es_error_de_contrato():
    with pytest.raises(InvalidListing):
        parse_abc_listing("<div class=product-grid></div>", category=ABC_CAT, scraped_at=NOW)
    with pytest.raises(InvalidListing):
        parse_tricot_listing("<div class=product-grid></div>", category=TRICOT_CAT, scraped_at=NOW)


def test_abc_final_vacio_requiere_canonical_de_la_misma_hoja():
    html = '<link rel="canonical" href="https://www.abc.cl/mujer/ropa-mujer/?sz=36&amp;start=828">'
    products, ids, total = parse_abc_listing(html, category=ABC_CAT, scraped_at=NOW)
    assert products == [] and ids == set() and total is None
    with pytest.raises(InvalidListing):
        parse_abc_listing(html.replace("/mujer/ropa-mujer/", "/hombre/"), category=ABC_CAT, scraped_at=NOW)
