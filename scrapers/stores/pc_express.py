"""Catálogo público de PC Express (OpenCart).

Las categorías son nodos del menú, no la vitrina «Ofertas». El precio del grid
está rotulado «Transferencia» y es el que paga cualquiera con ese medio; el
«Normal» tachado es solo evidencia y nunca alimenta el descuento real.

El listado no declara stock: el botón de compra es una señal débil. La tienda
empieza como fuente de historial con `publish_enabled = FALSE` (migración 40)
hasta validar un agotado real y la verificación de ficha antes de publicar.
"""
from __future__ import annotations

import re
from collections.abc import AsyncIterator, Sequence
from datetime import datetime, timezone
from decimal import Decimal
from urllib.parse import urlsplit

from selectolax.parser import HTMLParser

from catalog.normalize import clean_text
from scrapers.base import MAX_PLAUSIBLE_CLP, CategoryRef, RawProduct
from scrapers.http import HttpClient

BASE_URL = "https://tienda.pc-express.cl"
PAGE_SIZE = 20
MAX_PAGES = 50
_COUNT = re.compile(
    r"Mostrando del\s+([\d.]+) al\s+([\d.]+) de\s+([\d.]+)\s*\((\d+) p[aá]ginas?\)",
    re.I,
)
_MONEY = re.compile(r"^\$?\s*(?:\d{1,3}(?:\.\d{3})+|\d+)$")


class NotAListingPage(RuntimeError):
    """La página no tiene la estructura o la posición esperada."""


def _clp(value: str | None) -> Decimal | None:
    if not value or not _MONEY.fullmatch(value.strip()):
        return None
    price = Decimal(value.replace("$", "").replace(".", "").strip())
    return price if 0 < price <= MAX_PLAUSIBLE_CLP else None


def parse_listing(
    html: str,
    *,
    category: CategoryRef,
    scraped_at: datetime,
    page: int,
    expected_total: int | None = None,
) -> tuple[list[RawProduct], set[str], int, bool]:
    """Devuelve productos, SKU enumerados, total y si hay otra página."""
    tree = HTMLParser(html)
    tiles = tree.css(".product-list__item[data-product-id]")
    count = _COUNT.search(tree.text(separator=" "))
    if tree.css_first("h1") is None or count is None or not tiles:
        raise NotAListingPage(f"PC Express/{category.store_key}: listado ausente")
    first, last, total, pages = (
        int(group.replace(".", "")) for group in count.groups()
    )
    expected_first = (page - 1) * PAGE_SIZE + 1
    if (
        first != expected_first
        or last != first + len(tiles) - 1
        or total < last
        or pages != (total + PAGE_SIZE - 1) // PAGE_SIZE
        or (expected_total is not None and total != expected_total)
    ):
        raise NotAListingPage(
            f"PC Express/{category.store_key}: página {page} incoherente "
            f"({first}-{last} de {total}, {len(tiles)} filas)"
        )

    products: list[RawProduct] = []
    enumerated: set[str] = set()
    for tile in tiles:
        sku = tile.attributes["data-product-id"].strip()
        enumerated.add(sku)
        shown_sku = tile.css_first(".product-list__sku")
        link = tile.css_first(".product-list__name a[href]")
        title = tile.css_first(".product-list__price-title")
        price_node = tile.css_first(".product-list__price")
        if title is None or title.text(strip=True).lower() not in {
            "transferencia", "efectivo/transferencia",
        }:
            raise NotAListingPage(
                f"PC Express/{category.store_key}: cambió la condición del precio"
            )
        if not (sku and shown_sku and shown_sku.text(strip=True) == sku and link):
            continue
        url = link.attributes["href"]
        name = clean_text(link.text(strip=True))
        price = _clp(price_node.text(strip=True) if price_node else None)
        if not name or not price or urlsplit(url).netloc != "tienda.pc-express.cl":
            continue
        old_node = tile.css_first(".product-list__price-old")
        old = _clp(old_node.text(strip=True) if old_node else None)
        image = tile.css_first(".product-list__image img[src]")
        products.append(
            RawProduct(
                store_slug="pc-express",
                store_sku=sku,
                url=url,
                name=name,
                price_effective=price,
                price_normal=old if old and old > price else None,
                scraped_at=scraped_at,
                in_stock=tile.css_first(".product-list__actions button") is not None,
                image_url=image.attributes["src"] if image else None,
                category_path=category.store_key,
            )
        )
    return products, enumerated, total, last < total


class PcExpressAdapter:
    slug = "pc-express"
    rate_limit_rps = 0.4  # robots sin Crawl-delay; 27 páginas en ~68 s.

    def __init__(self, http: HttpClient, categories: Sequence[CategoryRef]) -> None:
        self._http = http
        self._categories = tuple(categories)
        self._completeness: dict[str, tuple[int, int]] = {}

    def categories(self) -> Sequence[CategoryRef]:
        return self._categories

    def completeness(self, category: CategoryRef) -> tuple[int, int] | None:
        return self._completeness.get(category.store_key)

    async def discover(self, category: CategoryRef) -> AsyncIterator[RawProduct]:
        self._completeness.pop(category.store_key, None)
        seen: set[str] = set()
        total: int | None = None
        for page in range(1, MAX_PAGES + 1):
            url = (
                f"{BASE_URL}/index.php?route=product/category"
                f"&path={category.store_key}&page={page}"
            )
            html = await self._http.get_text(url, rps=self.rate_limit_rps)
            products, ids, total, has_next = parse_listing(
                html,
                category=category,
                scraped_at=datetime.now(timezone.utc),
                page=page,
                expected_total=total,
            )
            for product in products:
                if product.store_sku not in seen:
                    yield product
            seen.update(ids)
            self._completeness[category.store_key] = (len(seen), total)
            if not has_next:
                break
        else:
            raise NotAListingPage(
                f"PC Express/{category.store_key}: más de {MAX_PAGES} páginas"
            )
