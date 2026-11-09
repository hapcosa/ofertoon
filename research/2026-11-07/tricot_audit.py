"""Auditor de listados públicos Tricot sin parámetros de consulta."""
from __future__ import annotations

import argparse
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlsplit
from xml.etree import ElementTree

import httpx
from selectolax.parser import HTMLParser

from scrapers.http import BROWSER_HEADERS

BASE = "https://www.tricot.cl"
OUT = Path(__file__).parent
OUT.mkdir(exist_ok=True)
PRICE = re.compile(r"\$\s*([\d.]+)")


def clean_price(node):
    if node is None:
        return None
    match = PRICE.search(node.text())
    return int(match.group(1).replace(".", "")) if match else None


def listing(client, path):
    url = BASE + "/" + path.strip("/")
    response = client.get(url)
    if response.status_code != 200:
        raise RuntimeError(f"HTTP {response.status_code}: {url}")
    if response.url.query or urlsplit(str(response.url)).path.rstrip("/") != urlsplit(url).path.rstrip("/"):
        raise RuntimeError(f"redirección inesperada: {url} -> {response.url}")
    tree = HTMLParser(response.text)
    nodes = tree.css(".tri-product-tile.product-tile")
    rows = []
    for node in nodes:
        link = node.css_first(".pdp-link a[href]")
        if not link:
            continue
        href = urljoin(BASE, link.attributes["href"])
        pid_node = node.css_first("[data-product-id]")
        rows.append({
            "url": href,
            "pid": pid_node.attributes.get("data-product-id") if pid_node else None,
            "name": link.text().strip(),
            "price": clean_price(node.css_first(".tri-sales")),
            "normal": clean_price(node.css_first(".list")),
            "stock_text": bool(re.search(r"sin stock|agotado|out of stock", node.text(), re.I)),
            "has_cart_button": bool(node.css_first("button.add-to-cart, button.js-add-to-cart, button[data-action=add-to-cart]")),
            "gtin": bool(node.css_first("[itemprop^=gtin], [itemprop=ean], [data-gtin], [data-ean]")),
        })
    total_node = tree.css_first(".results-count-container .js-result-count, .js-result-count")
    total_match = re.search(r"Resultados\s*\(([\d.]+)\)", total_node.text(), re.I) if total_node else None
    total = int(total_match.group(1).replace(".", "")) if total_match else None
    return {
        "at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "path": path, "final_url": str(response.url), "bytes": len(response.content),
        "tile_nodes": len(nodes), "linked_nodes": len(rows),
        "unique_urls": len({row["url"] for row in rows}),
        "unique_pids": len({row["pid"] for row in rows if row["pid"]}),
        "declared_total": total,
        "pagination": [re.sub(r"\s+", " ", x.text()).strip()[:200] for x in tree.css(".pagination")[:2]],
        "rows": rows,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("sitemap", "sitemap_keyword", "snapshot", "robots", "inspect", "pdp", "stock_sample", "stock_listing"))
    parser.add_argument("label", nargs="?")
    parser.add_argument("paths", nargs="*")
    args = parser.parse_args()
    with httpx.Client(headers=BROWSER_HEADERS, follow_redirects=True, verify=True,
                      timeout=25) as client:
        if args.action == "robots":
            response = client.get(BASE + "/robots.txt")
            print(response.status_code, response.text, flush=True)
            return
        if args.action == "sitemap":
            response = client.get(BASE + "/sitemap_2-category.xml")
            response.raise_for_status()
            root = ElementTree.fromstring(response.content)
            urls = [node.text for node in root.iter() if node.tag.endswith("loc") and node.text]
            paths = [urlsplit(url).path for url in urls]
            (OUT / "category_paths.json").write_text(json.dumps(paths, indent=2), encoding="utf-8")
            print(json.dumps({"count": len(paths), "paths": paths}, ensure_ascii=False), flush=True)
            return
        if args.action == "sitemap_keyword":
            keyword = args.label or "banano"
            for index in (0, 1):
                response = client.get(BASE + f"/sitemap_{index}-product.xml")
                response.raise_for_status()
                root = ElementTree.fromstring(response.content)
                urls = [node.text for node in root.iter() if node.tag.endswith("loc") and node.text]
                matches = [url for url in urls if keyword.lower() in url.lower()]
                print(json.dumps({"index": index, "all": len(urls), "matches": matches}, ensure_ascii=False), flush=True)
            return
        if args.action == "inspect":
            if not args.label:
                parser.error("inspect requiere ruta")
            path = args.label
            response = client.get(BASE + "/" + path.strip("/"))
            response.raise_for_status()
            tree = HTMLParser(response.text)
            samples = []
            for match in list(re.finditer(r"\b[\d.]+\s+productos\b|productos\s+encontrados", response.text, re.I))[:12]:
                samples.append(re.sub(r"\s+", " ", response.text[max(0, match.start()-150):match.end()+150]))
            print(json.dumps({"path": path, "bytes": len(response.content),
                              "product_tile": len(tree.css(".product-tile")),
                              "tri_product_tile": len(tree.css(".tri-product-tile")),
                              "data_pid": len(tree.css("[data-pid]")),
                              "contexts": samples,
                              "pagination": [re.sub(r"\s+", " ", x.text())[:200] for x in tree.css(".pagination")[:2]],
                              "count_nodes": [(x.attributes.get("class"), re.sub(r"\s+", " ", x.text()).strip()[:120]) for x in tree.css("[class*=count], [class*=result], [class*=total]") if len(x.text().strip()) < 150][:35],
                              "first_tile_html": tree.css(".tri-product-tile")[0].html[:1600] if tree.css(".tri-product-tile") else None}, ensure_ascii=False), flush=True)
            return
        if args.action == "pdp":
            if not args.label:
                parser.error("pdp requiere ruta")
            response = client.get(BASE + "/" + args.label.strip("/"))
            response.raise_for_status()
            tree = HTMLParser(response.text)
            stock_words = []
            for term in ("OutOfStock", "InStock", "sin stock", "agotado", "no disponible", "disponible"):
                matches = list(re.finditer(re.escape(term), response.text, re.I))
                stock_words.append((term, len(matches), [re.sub(r"\s+", " ", response.text[max(0,m.start()-100):m.end()+140]) for m in matches[:2]]))
            result = {"url": str(response.url), "status": response.status_code,
                              "bytes": len(response.content), "title": tree.css_first("title").text() if tree.css_first("title") else None,
                              "stock_words": stock_words,
                              "breadcrumbs": [(n.text().strip(), n.attributes.get("href")) for n in tree.css(".breadcrumb a, .breadcrumbs a, .breadcrumb-item a")[:20]],
                              "canonical": tree.css_first('link[rel="canonical"]').attributes.get("href") if tree.css_first('link[rel="canonical"]') else None,
                              "gtin_nodes": [(n.attributes, n.text()[:50]) for n in tree.css("[itemprop^=gtin], [data-gtin], [data-ean]")[:5]],
                              "buttons": [(n.attributes.get("class"), n.text().strip()[:80], "disabled" in n.attributes) for n in tree.css("button") if re.search("carro|agregar|comprar|talla", n.text(), re.I)][:10]}
            print(json.dumps(result, ensure_ascii=False), flush=True)
            name = "tricot_pdp_" + Path(args.label).stem + ".json"
            (OUT / name).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
            return
        if args.action == "stock_sample":
            import random
            sample_size = int(args.label or 30)
            sitemap = client.get(BASE + "/sitemap_0-product.xml")
            sitemap.raise_for_status()
            root = ElementTree.fromstring(sitemap.content)
            urls = [n.text for n in root.iter() if n.tag.endswith("loc") and n.text and urlsplit(n.text).path.endswith(".html")]
            chosen = random.Random(20261109).sample(urls, min(sample_size, len(urls)))
            counts = {"InStock": 0, "OutOfStock": 0, "unknown": 0}
            out = []
            for i, url in enumerate(chosen, 1):
                time.sleep(1.5)
                response = client.get(url)
                response.raise_for_status()
                match = re.search(r"[\"']availability[\"']\s*:\s*[\"']([^\"']+)", response.text, re.I)
                if not match:
                    match = re.search(r"itemprop=[\"']availability[\"'][^>]+(?:href|content)=[\"']([^\"']+)", response.text, re.I)
                status = "OutOfStock" if match and "OutOfStock" in match.group(1) else "InStock" if match and "InStock" in match.group(1) else "unknown"
                counts[status] += 1
                if status == "OutOfStock":
                    out.append(url)
                if i % 10 == 0 or status == "OutOfStock":
                    print(json.dumps({"checked": i, "counts": counts, "out": out[-5:]}, ensure_ascii=False), flush=True)
            (OUT / "stock_sample.json").write_text(json.dumps({"sitemap_urls": len(urls), "counts": counts, "out": out, "sample": chosen}, indent=2), encoding="utf-8")
            return
        if args.action == "stock_listing":
            path = args.label or "/accesorios/mujer/bananos"
            result = listing(client, path)
            controls = []
            for row in result["rows"]:
                time.sleep(1.5)
                response = client.get(row["url"])
                match = re.search(r'"availability"\s*:\s*"[^"]*/(InStock|OutOfStock)"', response.text)
                controls.append({"pid": row["pid"], "url": row["url"],
                                 "status": response.status_code,
                                 "availability": match.group(1) if match else None,
                                 "agotado": bool(re.search(r"El producto que buscas está\s*<strong>AGOTADO", response.text))})
                print(json.dumps(controls[-1], ensure_ascii=False), flush=True)
            name = "tricot_stock_" + path.strip("/").replace("/", "_") + ".json"
            (OUT / name).write_text(json.dumps({"path": path, "declared_total": result["declared_total"], "controls": controls}, indent=2), encoding="utf-8")
            return
        if not args.label or not args.paths:
            parser.error("snapshot requiere etiqueta y rutas")
        records = []
        for n, path in enumerate(args.paths):
            if n:
                time.sleep(2)
            result = listing(client, path)
            records.append(result)
            print(json.dumps({k: v for k, v in result.items() if k != "rows"}, ensure_ascii=False), flush=True)
        output = OUT / f"{args.label}.json"
        output.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
        print("saved", output, flush=True)


if __name__ == "__main__":
    main()
