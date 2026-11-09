"""Contrato del listado público de PC Express, con HTML real recortado."""
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from scrapers.base import CategoryRef
from scrapers.stores.pc_express import (
    NotAListingPage,
    PcExpressAdapter,
    parse_listing,
)

FIXTURES = Path(__file__).parent / "fixtures"
NOW = datetime(2026, 11, 6, tzinfo=timezone.utc)
GPU = CategoryRef("tecno-componentes", "460_475")
GAMER = CategoryRef("tecno-notebooks", "476_479")


def fixture(name: str) -> str:
    return (FIXTURES / name).read_text()


def test_precio_transferencia_y_normal_no_contaminan_baseline():
    products, ids, total, next_page = parse_listing(
        fixture("pc_express_gpu.html"), category=GPU, scraped_at=NOW, page=1
    )
    bridge = next(p for p in products if p.store_sku == "8680")
    assert (len(products), len(ids), total, next_page) == (20, 20, 26, True)
    assert bridge.price_effective == Decimal(9900)
    assert bridge.price_normal == Decimal(53191)
    assert bridge.price_card is None
    assert bridge.in_stock is True
    assert bridge.url.startswith("https://tienda.pc-express.cl/")


def test_categoria_corta_termina_sin_pedir_pagina_fuera_de_rango():
    products, ids, total, next_page = parse_listing(
        fixture("pc_express_gamer.html"), category=GAMER, scraped_at=NOW, page=1
    )
    assert (len(products), len(ids), total, next_page) == (2, 2, 2, False)
    assert products[0].price_effective == Decimal(2379500)


class FakeHttp:
    def __init__(self, pages: list[str]):
        self.pages = pages
        self.urls: list[str] = []

    async def get_text(self, url: str, **kwargs) -> str:
        self.urls.append(url)
        return self.pages.pop(0)


@pytest.mark.asyncio
async def test_dos_paginas_26_sku_unicos_y_canario_exacto():
    http = FakeHttp([
        fixture("pc_express_gpu.html"),
        fixture("pc_express_gpu_p2.html"),
    ])
    adapter = PcExpressAdapter(http, [GPU])
    products = [p async for p in adapter.discover(GPU)]
    assert len(products) == len({p.store_sku for p in products}) == 26
    assert adapter.completeness(GPU) == (26, 26)
    assert len(http.urls) == 2
    assert http.urls[-1].endswith("path=460_475&page=2")


def test_pagina_ignorada_y_condicion_cambiada_fallan_ruidosamente():
    html = fixture("pc_express_gamer.html")
    with pytest.raises(NotAListingPage):
        parse_listing(html, category=GAMER, scraped_at=NOW, page=2)
    with pytest.raises(NotAListingPage):
        parse_listing(
            html.replace("Transferencia</p>", "Tarjeta</p>", 1),
            category=GAMER, scraped_at=NOW, page=1,
        )


def test_sin_boton_no_se_afirma_stock():
    html = fixture("pc_express_gamer.html")
    html = html.replace('class="product-list__actions"', 'class="sin-boton"', 1)
    # El botón también es una señal débil: este control solo verifica que su
    # ausencia no se convierta en disponible. Publicación sigue bloqueada.
    html = html.replace("<button", "<span", 1).replace("</button>", "</span>", 1)
    products, _, _, _ = parse_listing(html, category=GAMER, scraped_at=NOW, page=1)
    assert products[0].in_stock is False
