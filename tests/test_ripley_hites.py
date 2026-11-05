"""Regresiones sobre listados reales capturados el 2026-11-05."""
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
import json

import pytest
from selectolax.parser import HTMLParser

from scrapers.base import CategoryRef
from scrapers.stores import ripley, hites

FIXTURES = Path(__file__).parent / 'fixtures'
CAT = CategoryRef('tecno-notebooks', 'tecno/computacion/notebooks')
NOW = datetime.now(timezone.utc)


def fixture(store):
    return (FIXTURES / f'{store}_notebooks.html').read_text()


def test_ripley_precios_tarjeta_y_marketplace():
    products = ripley.parse_listing(fixture('ripley'), category=CAT, scraped_at=NOW)
    first = products[0]
    assert first.price_effective == Decimal('869990')
    assert first.price_card == Decimal('849990')
    assert first.price_normal == Decimal('899990')
    assert first.in_stock
    assert '?' not in first.url
    assert len(products) == len({p.store_sku for p in products})
    _, props = ripley.listing_data(fixture('ripley'))
    external = {p['sku'] for p in props['data']['products'] if p['seller'] != 'RIPLEY'}
    assert external.isdisjoint(p.store_sku for p in products)


def test_hites_tarjeta_no_es_precio_efectivo():
    products = hites.parse_listing(fixture('hites'), category=CAT, scraped_at=NOW)
    assert products[0].price_effective == Decimal('689990')
    assert products[0].price_normal == Decimal('1099990')
    assert products[1].price_effective == Decimal('459990')
    assert products[1].price_card == Decimal('439990')
    assert products[0].in_stock


def test_hites_stock_visible_y_vendedor_externo():
    tree = HTMLParser(fixture('hites'))
    tiles = tree.css('.product-tile')
    first_id = tiles[0].attributes['data-pid']
    second_id = tiles[1].attributes['data-pid']
    tiles[0].css_first('.oos-tags').attrs['class'] = 'oos-tags'
    tiles[1].css_first('.marketplace-info-plp b').replace_with(HTMLParser('<b>Otro vendedor</b>').css_first('b'))
    products = hites.parse_listing(tree.html, category=CAT, scraped_at=NOW)
    assert not next(p for p in products if p.store_sku == first_id).in_stock
    assert second_id not in {p.store_sku for p in products}


@pytest.mark.parametrize('value', ['NaN', 'Infinity', '-1', '0', '1.5', '99999999999', None])
def test_precio_invalido(value):
    assert ripley.clp(value) is None


@pytest.mark.parametrize('module', [ripley, hites])
def test_no_confundir_bloqueo_con_catalogo_vacio(module):
    with pytest.raises(module.NotAListingPage):
        module.parse_listing('<html>Access denied</html>', category=CAT, scraped_at=NOW)


class FakeHttp:
    def __init__(self, pages):
        self.pages = pages
        self.calls = []

    async def get_text(self, url, **kwargs):
        self.calls.append(url)
        return self.pages[min(len(self.calls)-1, len(self.pages)-1)]


@pytest.mark.asyncio
async def test_hites_pagina_repetida_es_incompleta():
    category = CategoryRef('tecno-notebooks', 'tecnologia/computacion/notebook')
    http = FakeHttp([fixture('hites')])
    adapter = hites.HitesAdapter(http, [category])
    products = [p async for p in adapter.discover(category)]
    assert len(http.calls) == 2
    assert len(products) == len({p.store_sku for p in products})
    assert adapter.completeness(category) == (36, 276)


@pytest.mark.asyncio
async def test_ripley_repeticion_no_infla_completitud():
    tree = HTMLParser(fixture('ripley'))
    script = tree.css_first('#__NEXT_DATA__')
    data = json.loads(script.text())
    data['props']['pageProps']['findabilityProps']['currentPage'] = 2
    second = fixture('ripley').replace(script.text(), json.dumps(data))
    http = FakeHttp([fixture('ripley'), second])
    adapter = ripley.RipleyAdapter(http, [CAT])
    products = [p async for p in adapter.discover(CAT)]
    assert len(http.calls) == 2
    assert adapter.completeness(CAT) == (48, 916)
    assert len(products) == len({p.store_sku for p in products})


@pytest.mark.asyncio
async def test_ripley_pagina_ignorada_falla():
    adapter = ripley.RipleyAdapter(FakeHttp([fixture('ripley')]), [CAT])
    with pytest.raises(ripley.NotAListingPage):
        _ = [p async for p in adapter.discover(CAT)]


def test_ripley_ultima_pagina_real():
    html = (FIXTURES / 'ripley_notebooks_final.html').read_text()
    _, props = ripley.listing_data(html)
    data = props['data']
    assert str(props['currentPage']) == '20'
    assert data['offset'] == 912
    assert len([p for p in data['products'] if p.get('sponsoredType') != 'sponsored']) == 5
    products = ripley.parse_listing(html, category=CAT, scraped_at=NOW)
    assert products  # Los anuncios se deduplican al recorrer toda la categoría.
    assert all(p.price_effective > 0 for p in products)


def test_ripley_sin_stock_o_precio_general():
    html = fixture('ripley')
    tree = HTMLParser(html)
    script = tree.css_first('#__NEXT_DATA__')
    data = json.loads(script.text())
    products = data['props']['pageProps']['findabilityProps']['data']['products']
    first_id = products[0]['sku']
    second_id = products[1]['sku']
    for product in products:
        if product['sku'] == first_id:
            product.pop('inStock', None)
        if product['sku'] == second_id:
            product['priceNumber'] = None
    changed = html.replace(script.text(), json.dumps(data))
    parsed = ripley.parse_listing(changed, category=CAT, scraped_at=NOW)
    assert not next(p for p in parsed if p.store_sku == first_id).in_stock
    assert second_id not in {p.store_sku for p in parsed}
