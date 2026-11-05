"""Hites: grid HTML público con paginación enlazada por la propia tienda."""
from datetime import datetime, timezone
import re
from urllib.parse import urljoin, urlsplit

from selectolax.parser import HTMLParser

from scrapers.base import RawProduct
from scrapers.http import BROWSER_HEADERS
from scrapers.stores.ripley import clp

BASE_URL = 'https://www.hites.com'


class NotAListingPage(RuntimeError):
    pass


def listing_tree(html):
    tree = HTMLParser(html)
    count = tree.css_first('.product-results-count')
    match = re.search(r'([\d.]+)\s+productos', count.text()) if count else None
    if not match:
        raise NotAListingPage('Hites: falta el total del catálogo')
    return tree, int(match.group(1).replace('.', ''))


def parse_listing(html, *, category, scraped_at):
    tree, _ = listing_tree(html)
    products = []
    for tile in tree.css('.product-tile[data-pid]'):
        seller = tile.css_first('.marketplace-info-plp b')
        if seller is None or seller.text().strip().lower() != 'hites':
            continue
        def price(selector):
            node = tile.css_first(selector + ' .value[content]')
            if node:
                return clp(node.attributes['content'])
            node = tile.css_first(selector)
            match = re.search(r'\$\s*([\d.]+)', node.text()) if node else None
            return clp(match.group(1).replace('.', '')) if match else None
        effective = price('.sales')
        link = tile.css_first('h3 a[href]')
        sku = tile.attributes.get('data-pid')
        if effective is None or link is None or not sku or not link.text().strip():
            continue
        normal = price('.list')
        brand = tile.css_first('.product-brand')
        image = tile.css_first('img.tile-image')
        oos = tile.css_first('.oos-tags')
        # El mensaje SIN STOCK también existe oculto en productos disponibles.
        stock = oos is not None and 'd-none' in oos.attributes.get('class', '').split()
        products.append(RawProduct(
            store_slug='hites', store_sku=sku, url=urljoin(BASE_URL, link.attributes['href']),
            name=link.text().strip(), price_effective=effective,
            price_normal=normal if normal and normal > effective else None,
            price_card=price('.hites-price'), scraped_at=scraped_at, in_stock=stock,
            brand=brand.text().strip() if brand else None,
            image_url=urljoin(BASE_URL, image.attributes.get('src', '')) if image else None,
            category_path=category.store_key,
        ))
    return products


class HitesAdapter:
    slug = 'hites'
    rate_limit_rps = 0.5
    max_pages = 100

    def __init__(self, http, categories):
        self._http = http
        self._categories = tuple(categories)
        self._completeness = {}

    def categories(self):
        return self._categories

    def completeness(self, category):
        return self._completeness.get(category.store_key)

    async def discover(self, category):
        self._completeness.pop(category.store_key, None)
        url = f'{BASE_URL}/{category.store_key.strip("/")}/'
        visited, enumerated, emitted = set(), set(), set()
        total = None
        for _ in range(self.max_pages):
            if url in visited:
                break
            visited.add(url)
            html = await self._http.get_text(url, rps=self.rate_limit_rps, headers=BROWSER_HEADERS)
            tree, declared = listing_tree(html)
            if total is None:
                total = declared
                if total <= 0:
                    raise NotAListingPage('Hites: categoría vacía o inexistente')
            ids = {n.attributes['data-pid'] for n in tree.css('.product-tile[data-pid]')}
            new = ids - enumerated
            enumerated.update(ids)
            for product in parse_listing(html, category=category, scraped_at=datetime.now(timezone.utc)):
                if product.store_sku not in emitted:
                    emitted.add(product.store_sku)
                    yield product
            self._completeness[category.store_key] = (len(enumerated), total)
            next_link = tree.css_first('.pagination__item.next a[href]')
            if not new or next_link is None:
                break
            following = urljoin(url, next_link.attributes['href'])
            parsed = urlsplit(following)
            if parsed.netloc != 'www.hites.com' or parsed.path != urlsplit(url).path:
                raise NotAListingPage('Hites: paginación fuera de la categoría')
            url = following
