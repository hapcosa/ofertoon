"""Medición reproducible de tiendas Shopify reabiertas.

Desde la raíz del worktree, con el Python del proyecto:
    PYTHONPATH=. python research/2026-11-07/shopify_audit.py list https://www.rkflife.com
    PYTHONPATH=. python research/2026-11-07/shopify_audit.py collection https://www.rkflife.com HANDLE

Solo consulta rutas públicas permitidas por robots; verifica TLS y se detiene
ante 403/429. El archivo de IDs permite medir solapamiento entre llaves.
"""
from __future__ import annotations

import argparse
import json
import statistics
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote, urlsplit
from xml.etree import ElementTree

import httpx

from scrapers.http import DEFAULT_USER_AGENT


OUT_DIR = Path(__file__).parent


def get(client: httpx.Client, url: str) -> httpx.Response:
    response = client.get(url)
    if response.status_code != 200:
        raise RuntimeError(f"HTTP {response.status_code} {url} -> {response.url}")
    return response


def xml_locs(content: bytes) -> list[str]:
    root = ElementTree.fromstring(content)
    return [node.text for node in root.iter()
            if node.tag.endswith("loc") and node.text]


def list_collections(client: httpx.Client, base: str, store: str) -> None:
    index = xml_locs(get(client, base + "/sitemap.xml").content)
    matches = [url for url in index if "/sitemap_collections_" in url]
    if not matches:
        raise RuntimeError("sitemapindex sin sitemap de colecciones")
    handles: set[str] = set()
    for url in matches:
        time.sleep(1.5)
        handles.update(parsed.path.split("/collections/", 1)[1]
                       for item in xml_locs(get(client, url).content)
                       if (parsed := urlsplit(item)).hostname == urlsplit(base).hostname
                       and parsed.path.startswith("/collections/"))
    path = OUT_DIR / f"{store}_collections.txt"
    path.write_text("\n".join(sorted(handles)) + "\n", encoding="utf-8")
    print(json.dumps({"at_utc": datetime.now(timezone.utc).isoformat(),
                      "base": base, "sitemap_files": len(matches),
                      "collections": len(handles), "file": str(path),
                      "handles": sorted(handles)}, ensure_ascii=False))


def parse_price(value: object) -> int | None:
    if value is None:
        return None
    text = str(value)
    return int(text) if text.isdigit() else None


def audit_collection(client: httpx.Client, base: str, store: str,
                     handle: str, max_pages: int) -> None:
    products: list[dict] = []
    decoded_body_bytes = 0
    data_pages = 0
    for page in range(1, max_pages + 1):
        if page > 1:
            time.sleep(1.5)
        url = f"{base}/collections/{quote(handle)}/products.json?limit=250&page={page}"
        response = get(client, url)
        decoded_body_bytes += len(response.content)
        payload = response.json()
        rows = payload.get("products")
        if not isinstance(rows, list):
            raise RuntimeError(f"sin products[]: {url}")
        if page == 1 and not rows:
            raise RuntimeError(f"primera página vacía: {url}")
        if not rows:
            complete = True
            break
        products.extend(rows)
        data_pages += 1
    else:
        complete = False
    ids = [str(product.get("id")) for product in products if product.get("id") is not None]
    variants = [variant for product in products
                for variant in product.get("variants", []) if isinstance(variant, dict)]
    prices = [price for variant in variants
              if (price := parse_price(variant.get("price"))) is not None]
    price_spreads = 0
    for product in products:
        p = {parse_price(v.get("price")) for v in product.get("variants", [])
             if isinstance(v, dict)}
        p.discard(None)
        price_spreads += len(p) > 1
    output = {
        "at_utc": datetime.now(timezone.utc).isoformat(),
        "base": base, "handle": handle, "pages": page,
        "data_pages": data_pages, "complete": complete,
        "decoded_body_bytes": decoded_body_bytes,
        "rows": len(products), "unique_product_ids": len(set(ids)),
        "variants": len(variants),
        "available_variants": sum(v.get("available") is True for v in variants),
        "unavailable_variants": sum(v.get("available") is False for v in variants),
        "products_all_unavailable": sum(
            not any(v.get("available") is True for v in p.get("variants", []))
            for p in products
        ),
        "products_mixed_stock": sum(
            any(v.get("available") is True for v in p.get("variants", []))
            and any(v.get("available") is False for v in p.get("variants", []))
            for p in products
        ),
        "products_with_price_spread": price_spreads,
        "price_count": len(prices),
        "price_min": min(prices) if prices else None,
        "price_max": max(prices) if prices else None,
        "price_median": statistics.median(prices) if prices else None,
        "compare_at_count": sum(parse_price(v.get("compare_at_price")) is not None for v in variants),
        "barcode_count": sum(bool(v.get("barcode")) for v in variants),
        "types": Counter(str(p.get("product_type")) for p in products).most_common(12),
        "vendors": Counter(str(p.get("vendor")) for p in products).most_common(8),
        "sample": [{"id": p.get("id"), "title": p.get("title"),
                    "handle": p.get("handle"), "variants": len(p.get("variants", []))}
                   for p in products[:3]],
    }
    path = OUT_DIR / f"{store}_{handle.replace('/', '_')}_ids.json"
    path.write_text(json.dumps({"base": base, "handle": handle, "ids": sorted(set(ids))},
                               ensure_ascii=False), encoding="utf-8")
    output["ids_file"] = str(path)
    print(json.dumps(output, ensure_ascii=False))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("list", "collection"))
    parser.add_argument("base")
    parser.add_argument("handle", nargs="?")
    parser.add_argument("--max-pages", type=int, default=20)
    args = parser.parse_args()
    if args.action == "collection" and not args.handle:
        parser.error("collection requiere handle")
    base = args.base.rstrip("/")
    store = urlsplit(base).hostname.removeprefix("www.").split(".", 1)[0]
    with httpx.Client(headers={"User-Agent": DEFAULT_USER_AGENT},
                      follow_redirects=True, verify=True, timeout=20.0) as client:
        if args.action == "list":
            list_collections(client, base, store)
        else:
            audit_collection(client, base, store, args.handle, args.max_pages)


if __name__ == "__main__":
    main()
