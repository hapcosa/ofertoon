"""Recorre una categoría pública ABC con zona Metropolitana fijada.

Solo usa la URL de categoría con parámetros permitidos por robots.txt.
No consulta controladores Demandware ni parámetros de filtro/sort prohibidos.
"""
from __future__ import annotations

import argparse
import json
import re
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

import httpx
from selectolax.parser import HTMLParser

from scrapers.http import BROWSER_HEADERS


BASE = "https://www.abc.cl"
ZONE = "inventory_LaPolar_whven|t_ecom_metropolitana"
OUT = Path(__file__).parent
PRICE = re.compile(r"\$\s*([\d.]+)")


def price(tile, selector: str) -> int | None:
    node = tile.css_first(selector)
    match = PRICE.search(node.text()) if node else None
    return int(match.group(1).replace(".", "")) if match else None


def audit(category: str, label: str, limit: int) -> None:
    ids: list[str] = []
    pages: list[dict] = []
    prices: list[int] = []
    normal_count = 0
    card_count = 0
    gtin_count = 0
    sold_out_count = 0
    seller_markers = Counter()
    declared_total = None
    started = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with httpx.Client(headers=BROWSER_HEADERS, timeout=30.0,
                      follow_redirects=True, verify=True) as client:
        for page in range(limit):
            if page:
                time.sleep(1.5)
            url = (f"{BASE}/{category.strip('/')}/?zone={quote(ZONE, safe='')}"
                   f"&start={page * 36}&sz=36")
            response = client.get(url)
            if response.status_code != 200 or str(response.url) != url:
                raise RuntimeError(f"HTTP {response.status_code}, final={response.url}")
            tree = HTMLParser(response.text)
            if page == 0:
                count_node = tree.css_first(".refinement-bar__mobile-count")
                match = re.search(r"([\d.]+)\s+productos", count_node.text(), re.I) if count_node else None
                declared_total = int(match.group(1).replace(".", "")) if match else None
            tiles = tree.css(".product-grid .product-tile__wrapper[data-pid]")
            page_ids = list(dict.fromkeys(t.attributes["data-pid"] for t in tiles))
            if not page_ids and page == 0:
                raise RuntimeError("página 1 sin tiles")
            pages.append({"start": page * 36, "tiles": len(tiles),
                          "ids": len(page_ids), "bytes": len(response.content)})
            if not page_ids:
                break
            ids.extend(page_ids)
            for tile in tiles:
                effective = price(tile, ".internet .price-value")
                if effective is not None:
                    prices.append(effective)
                normal_count += price(tile, ".normal .price-value") is not None
                card_count += price(tile, ".tarjeta .price-value") is not None
                gtin_count += bool(tile.css_first("[itemprop^=gtin], [itemprop=gtin13]"))
                sold_out_count += bool(re.search(r"sin stock|agotado", tile.text(), re.I))
                for marker in ("marketplace", "vendedor", "vendido por", "seller"):
                    seller_markers[marker] += marker in tile.html.lower()
            if page == 0 or page % 10 == 0:
                print(json.dumps({"page": page + 1, "rows": len(ids),
                                  "unique": len(set(ids))}), flush=True)
        else:
            raise RuntimeError(f"no se llegó al final en {limit} páginas")
    result = {"at_utc": started, "category": category, "zone": ZONE,
              "declared_total": declared_total,
              "pages": pages, "rows": len(ids), "unique": len(set(ids)),
              "duplicates": len(ids) - len(set(ids)), "price_count": len(prices),
              "min_price": min(prices) if prices else None,
              "max_price": max(prices) if prices else None,
              "normal_count": normal_count, "card_count": card_count,
              "gtin_count": gtin_count, "sold_out_text_count": sold_out_count,
              "seller_markers": seller_markers}
    prefix = OUT / f"abc_{category.strip('/').replace('/', '_')}_{label}"
    prefix.with_name(prefix.name + "_ids.json").write_text(
        json.dumps({"base": BASE, "handle": category, "ids": sorted(set(ids))}),
        encoding="utf-8")
    prefix.with_name(prefix.name + "_audit.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in result.items() if k != "pages"},
                     ensure_ascii=False), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("category")
    parser.add_argument("label")
    parser.add_argument("--limit", type=int, default=100)
    args = parser.parse_args()
    audit(args.category, args.label, args.limit)
