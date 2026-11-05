"""Catálogo público de Ripley, servido dentro de __NEXT_DATA__.

Solo venta directa: un cambio de vendedor marketplace no debe parecer una
bajada de precio de Ripley. Los anuncios no cuentan para completar el catálogo.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from urllib.parse import urljoin, urlsplit

from selectolax.parser import HTMLParser

from scrapers.base import MAX_PLAUSIBLE_CLP, CategoryRef, RawProduct
from scrapers.http import BROWSER_HEADERS, HttpClient

BASE_URL = 'https://simple.ripley.cl'


class NotAListingPage(RuntimeError):
    pass


def clp(value):
    try:
        price = Decimal(str(value))
        if price.is_finite() and 0 < price <= MAX_PLAUSIBLE_CLP and price == price.to_integral_value():
            return price
    except (InvalidOperation, ValueError):
        pass
    return None


def listing_data(html):
    tree = HTMLParser(html)
    script = tree.css_first('#__NEXT_DATA__')
    try:
        props = json.loads(script.text())['props']['pageProps']['findabilityProps']
        data = props['data']
        if not isinstance(data['products'], list) or not isinstance(data['total'], int):
            raise ValueError('catálogo inválido')
        return tree, props
    except (AttributeError, KeyError, TypeError, ValueError) as exc:
        raise NotAListingPage('Ripley: falta el catálogo estructurado') from exc


def parse_listing(html, *, category, scraped_at):
    tree, props = listing_data(html)
    # La URL canónica de cada producto está en el HTML, no en el objeto de precio.
    links = {}
    for node in tree.css('a[href]'):
        path = urlsplit(node.attributes['href']).path
        key = path.rsplit('-', 1)[-1].lower()
        if key.endswith('p'):
            links[key] = urljoin(BASE_URL, path)
    products = []
    seen = set()
    for item in props['data']['products']:
        sku = str(item.get('sku') or '')
        url = links.get(str(item.get('parentProductID') or '').lower())
        price = clp(item.get('priceNumber'))
        if (item.get('seller') != 'RIPLEY' or item.get('currency') != 'CLP'
                or not sku or not url or price is None or sku in seen or not item.get('name')):
            continue
        seen.add(sku)
        normal = clp(item.get('masterPriceNumber'))
        products.append(RawProduct(
            store_slug='ripley', store_sku=sku, url=url, name=item['name'],
            price_effective=price, price_normal=normal if normal and normal > price else None,
            price_card=clp(item.get('ripleyPriceNumber')),
            scraped_at=scraped_at, in_stock=item.get('inStock') is True,
            brand=item.get('brand'), image_url=item.get('primaryImage'),
            category_path=category.store_key,
        ))
    return products


class RipleyAdapter:
    slug = 'ripley'
    rate_limit_rps = 0.5
    max_pages = 100

    def __init__(self, http: HttpClient, categories):
        self._http = http
        self._categories = tuple(categories)
        self._completeness = {}

    def categories(self):
        return self._categories

    def completeness(self, category):
        return self._completeness.get(category.store_key)

    async def discover(self, category):
        self._completeness.pop(category.store_key, None)
        enumerated, emitted = set(), set()
        total = None
        for page in range(1, self.max_pages + 1):
            url = f'{BASE_URL}/{category.store_key.strip("/")}?page={page}'
            html = await self._http.get_text(url, rps=self.rate_limit_rps, headers=BROWSER_HEADERS)
            _, props = listing_data(html)
            data = props['data']
            if str(props.get('currentPage')) != str(page):
                raise NotAListingPage(f'Ripley: solicitada página {page}, recibida otra')
            if total is None:
                total = data['total']
                if total <= 0 or not data['products']:
                    raise NotAListingPage('Ripley: categoría vacía o inexistente')
            organic = {str(p['sku']) for p in data['products']
                       if p.get('sku') and p.get('sponsoredType') != 'sponsored'}
            new = organic - enumerated
            enumerated.update(organic)
            for product in parse_listing(html, category=category, scraped_at=datetime.now(timezone.utc)):
                if product.store_sku not in emitted:
                    emitted.add(product.store_sku)
                    yield product
            self._completeness[category.store_key] = (len(enumerated), total)
            if len(enumerated) >= total or not new:
                break
            limit = data.get('limit')
            offset = data.get('offset')
            if isinstance(limit, int) and isinstance(offset, int) and offset + limit >= total:
                break
