"""Read-only stock control for public ABC PDPs and their canonical PLP."""
from __future__ import annotations

import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote, urlsplit

import httpx
from selectolax.parser import HTMLParser

from scrapers.http import BROWSER_HEADERS

BASE = "https://www.abc.cl"
ZONE = "inventory_LaPolar_whven|t_ecom_metropolitana"
OUT = Path(__file__).parent / "abc_stock_controls_2026-11-09.json"
PRODUCTS = [
    "/chaqueta-mujer-zibel/28147376.html/",
    "/chaqueta-mujer-alma/611179.html",
    "/chaqueta-mujer-zibel/640962.html",
    "/vestido-mujer-extralindas/625505.html",
    "/chaqueta-deportiva-mujer-alpinextrem/28679580.html",
]


def compact(s):
    return re.sub(r"\s+", " ", s).strip()


def pdp(client, path):
    url = BASE + path + "?zone=" + quote(ZONE, safe="")
    r = client.get(url)
    tree = HTMLParser(r.text)
    buttons = []
    for b in tree.css("button"):
        t = compact(b.text())
        if re.search(r"agregar|comprar|agotado|stock", t, re.I):
            buttons.append({"text": t[:120], "disabled": "disabled" in b.attributes,
                            "class": b.attributes.get("class", "")[:180]})
    m = re.search(r'["\']availability["\']\s*:\s*["\']([^"\']+)', r.text, re.I)
    crumbs = [compact(n.text()) for n in tree.css(".breadcrumb a, .breadcrumbs a, .breadcrumb-item a")]
    sellers = [compact(n.text())[:120] for n in tree.css("[class*=seller], [class*=vendor], [class*=marketplace]") if compact(n.text())][:15]
    return {"requested": url, "final_url": str(r.url), "status": r.status_code,
            "bytes": len(r.content), "title": compact(tree.css_first("title").text()) if tree.css_first("title") else None,
            "availability": m.group(1) if m else None,
            "sold_out_text": [compact(n.text())[:120] for n in tree.css("[class*=stock], [class*=sold], [class*=unavailable]") if re.search(r"agotado|sin stock", n.text(), re.I)][:8],
            "buttons": buttons[:12], "breadcrumbs": crumbs[:12], "sellers": sellers,
            "product_ids": [n.attributes.get("data-pid") for n in tree.css("[data-pid]")[:5]],
            "canonical": tree.css_first('link[rel="canonical"]').attributes.get("href") if tree.css_first('link[rel="canonical"]') else None}


def category(client, path, max_pages=40):
    seen = set()
    pages = []
    declared = None
    for page in range(max_pages):
        if page:
            time.sleep(1.5)
        url = f"{BASE}/{path.strip('/')}/?zone={quote(ZONE, safe='')}&start={page*36}&sz=36"
        r = client.get(url)
        tree = HTMLParser(r.text)
        if page == 0:
            count = tree.css_first(".refinement-bar__mobile-count")
            m = re.search(r"([\d.]+)\s+productos", count.text(), re.I) if count else None
            declared = int(m.group(1).replace(".", "")) if m else None
        tiles = tree.css(".product-grid .product-tile__wrapper[data-pid]")
        ids = [n.attributes["data-pid"] for n in tiles]
        pages.append({"page": page+1, "status": r.status_code, "url": str(r.url),
                      "bytes": len(r.content), "tiles": len(ids), "ids": ids})
        print(json.dumps({"category": path, "page": page+1, "tiles": len(ids), "ids_so_far": len(seen | set(ids))}), flush=True)
        if r.status_code != 200 or str(r.url) != url or (page == 0 and not ids):
            break
        seen.update(ids)
        if not ids:
            break
    return {"path": path, "declared": declared, "ids": sorted(seen), "pages": pages}


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "pdp"
    with httpx.Client(headers=BROWSER_HEADERS, follow_redirects=True, timeout=30, verify=True) as client:
        if mode == "pdp":
            rows = []
            for i, path in enumerate(PRODUCTS):
                if i:
                    time.sleep(1.5)
                row = pdp(client, path)
                rows.append(row)
                print(json.dumps(row, ensure_ascii=False), flush=True)
            OUT.write_text(json.dumps({"at_utc": datetime.now(timezone.utc).isoformat(), "pdps": rows}, ensure_ascii=False, indent=2))
        elif mode == "category":
            path = sys.argv[2]
            result = category(client, path)
            dest = Path(__file__).parent / ("abc_" + path.strip("/").replace("/", "_") + "_latest.json")
            dest.write_text(json.dumps(result, ensure_ascii=False, indent=2))
            print("saved", dest, flush=True)
        elif mode == "listing_control":
            url = f"{BASE}/mujer/ropa-mujer/?zone={quote(ZONE, safe='')}&start=0&sz=36"
            r = client.get(url)
            tree = HTMLParser(r.text)
            tile = tree.css_first(".product-grid .product-tile__wrapper[data-pid]")
            if not tile:
                raise RuntimeError("sin primer tile")
            link = tile.css_first("a[href]")
            if not link:
                raise RuntimeError("tile sin href")
            path = urlsplit(link.attributes["href"]).path
            print(json.dumps({"tile_pid": tile.attributes.get("data-pid"), "tile_href": link.attributes["href"],
                              "tile_stock_terms": bool(re.search(r"sin stock|agotado", tile.text(), re.I))}), flush=True)
            print(json.dumps(pdp(client, path), ensure_ascii=False), flush=True)
        else:
            raise SystemExit("mode must be pdp, category or listing_control")


if __name__ == "__main__":
    main()
