"""Listados públicos Salesforce Commerce Cloud medidos para ABC y Tricot.

ABC publica paginación en la URL de categoría y una zona de inventario explícita.
Tricot prohíbe ``?start`` en robots.txt: su adaptador usa solo la primera página
de cada hoja, y comunica el techo mediante ``completeness()``.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from decimal import Decimal
from urllib.parse import quote, urljoin, urlsplit, urlunsplit

from selectolax.parser import HTMLParser

from scrapers.base import CategoryRef, MAX_PLAUSIBLE_CLP, RawProduct
from scrapers.http import BROWSER_HEADERS


class InvalidListing(RuntimeError):
    pass


_PRICE = re.compile(r"\$\s*([\d.]+)")
_ABC_TOTAL = re.compile(r"([\d.]+)\s+productos", re.I)
_TRICOT_TOTAL = re.compile(r"Resultados\s*\(([\d.]+)\)", re.I)


def _price(node) -> Decimal | None:
    if node is None:
        return None
    match = _PRICE.search(node.text())
    if match is None:
        return None
    value = Decimal(match.group(1).replace(".", ""))
    return value if 0 < value <= MAX_PLAUSIBLE_CLP else None


def _text(node) -> str | None:
    return " ".join(node.text().split()) if node is not None else None


def _image(tile, base_url: str) -> str | None:
    image = tile.css_first("img.tile-image")
    if image is None:
        return None
    source = image.attributes.get("data-src") or image.attributes.get("src")
    if not source or source.startswith("data:"):
        return None
    return urljoin(base_url, source)


def _pdp_url(base_url: str, href: str) -> str:
    url = urljoin(base_url, href)
    if urlsplit(url).netloc != urlsplit(base_url).netloc:
        raise InvalidListing(f"ficha fuera de {base_url}: {url}")
    return url


def parse_abc_listing(html: str, *, category: CategoryRef, scraped_at: datetime):
    """Una sola wrapper por producto: los ``data-pid`` interiores se repiten."""
    tree = HTMLParser(html)
    tiles = tree.css(".product-grid .product-tile__wrapper[data-pid]")
    total_node = tree.css_first(".refinement-bar__mobile-count")
    total_match = _ABC_TOTAL.search(total_node.text()) if total_node else None
    if total_match is None:
        # La página posterior al final de la hoja (start=828 con 820 items)
        # omite el contador y el grid. Su canonical aún apunta a la misma hoja;
        # sin esa prueba, un 200 de un challenge parecería fin de catálogo.
        canonical = tree.css_first('link[rel="canonical"]')
        canonical_url = canonical.attributes.get("href", "") if canonical else ""
        expected_path = "/" + category.store_key.strip("/") + "/"
        if not tiles and urlsplit(canonical_url).path == expected_path:
            return [], set(), None
        raise InvalidListing("ABC: falta el total de categoría")
    total = int(total_match.group(1).replace(".", ""))
    ids = {tile.attributes["data-pid"] for tile in tiles}
    products = []
    for tile in tiles:
        sku = tile.attributes["data-pid"]
        link = tile.css_first(".pdp-link a[href]")
        name = _text(link)
        effective = _price(tile.css_first(".internet .price-value"))
        if not sku or not name or effective is None or link is None:
            continue
        normal = _price(tile.css_first(".normal .price-value"))
        card = _price(tile.css_first(".tarjeta .price-value"))
        url = _pdp_url("https://www.abc.cl", link.attributes["href"])
        parsed = urlsplit(url)
        url = urlunsplit((parsed.scheme, parsed.netloc, parsed.path,
                          "zone=" + quote(ABC_ZONE, safe=""), ""))
        products.append(RawProduct(
            store_slug="abc", store_sku=sku, url=url, name=name,
            price_effective=effective,
            price_normal=normal if normal and normal > effective else None,
            price_card=card if card and card < effective else None,
            scraped_at=scraped_at, in_stock=True,
            brand=_text(tile.css_first(".tile-brand .brand-name")),
            image_url=_image(tile, "https://www.abc.cl"),
            category_path=category.store_key,
        ))
    return products, ids, total


ABC_ZONE = "inventory_LaPolar_whven|t_ecom_metropolitana"


class ABCAdapter:
    """Solo la hoja de ropa mujer, con zona Metropolitana fija."""

    slug = "abc"
    rate_limit_rps = 0.5
    max_pages = 40

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
        path = category.store_key.strip("/")
        if path != "mujer/ropa-mujer":
            raise InvalidListing(f"ABC: categoría no investigada: {path}")
        seen = set()
        emitted = set()
        declared = None
        for page in range(self.max_pages):
            url = (f"https://www.abc.cl/{path}/?zone={quote(ABC_ZONE, safe='')}"
                   f"&start={page * 36}&sz=36")
            html = await self._http.get_text(
                url, rps=self.rate_limit_rps, headers=BROWSER_HEADERS)
            products, ids, total = parse_abc_listing(
                html, category=category, scraped_at=datetime.now(timezone.utc))
            if page == 0:
                if not ids or total <= 0:
                    raise InvalidListing("ABC: primera página vacía")
                declared = total
            if not ids:
                return
            if not ids - seen:
                raise InvalidListing("ABC: paginación repitió una página")
            seen.update(ids)
            self._completeness[category.store_key] = (len(seen), declared)
            for product in products:
                if product.store_sku not in emitted:
                    emitted.add(product.store_sku)
                    yield product
        raise InvalidListing(f"ABC: superó {self.max_pages} páginas")


def parse_tricot_listing(html: str, *, category: CategoryRef, scraped_at: datetime):
    tree = HTMLParser(html)
    total_node = tree.css_first(".js-result-count")
    total_match = _TRICOT_TOTAL.search(total_node.text()) if total_node else None
    if total_match is None:
        raise InvalidListing("Tricot: falta Resultados (N)")
    total = int(total_match.group(1).replace(".", ""))
    tiles = tree.css(".tri-product-tile.product-tile")
    ids = set()
    products = []
    for tile in tiles:
        sku_node = tile.css_first("[data-product-id]")
        link = tile.css_first(".pdp-link a[href]")
        sku = sku_node.attributes.get("data-product-id") if sku_node else None
        if sku:
            ids.add(sku)
        name = _text(link)
        effective = _price(tile.css_first(".tri-sales"))
        if not sku or not name or effective is None or link is None:
            continue
        normal = _price(tile.css_first(".list"))
        products.append(RawProduct(
            store_slug="tricot", store_sku=sku,
            url=_pdp_url("https://www.tricot.cl", link.attributes["href"]),
            name=name, price_effective=effective,
            price_normal=normal if normal and normal > effective else None,
            scraped_at=scraped_at, in_stock=True,
            image_url=_image(tile, "https://www.tricot.cl"),
            category_path=category.store_key,
        ))
    return products, ids, total


class TricotAdapter:
    """Hojas limpias sin parámetros; cobertura parcial declarada por categoría."""

    slug = "tricot"
    rate_limit_rps = 0.5

    def __init__(self, http, categories):
        self._http = http
        self._categories = tuple(categories)
        self._completeness = {}
        self._sku_category = {}

    def categories(self):
        return self._categories

    def completeness(self, category):
        return self._completeness.get(category.store_key)

    async def discover(self, category):
        self._completeness.pop(category.store_key, None)
        path = category.store_key.strip("/")
        if not path or "?" in path or "#" in path:
            raise InvalidListing(f"Tricot: llave inválida: {path}")
        url = f"https://www.tricot.cl/{path}"
        html = await self._http.get_text(
            url, rps=self.rate_limit_rps, headers=BROWSER_HEADERS)
        products, ids, total = parse_tricot_listing(
            html, category=category, scraped_at=datetime.now(timezone.utc))
        if not ids or total <= 0:
            raise InvalidListing(f"Tricot: hoja vacía: {path}")
        self._completeness[category.store_key] = (len(ids), total)
        for product in products:
            previous = self._sku_category.get(product.store_sku)
            if previous is not None and previous != category.slug:
                raise InvalidListing(
                    f"Tricot: SKU {product.store_sku} cruza {previous} y {category.slug}")
            if previous is None:
                self._sku_category[product.store_sku] = category.slug
                yield product
