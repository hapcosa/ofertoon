"""Cuenta URLs de producto (no URLs de imágenes) en sitemaps de Spacestore."""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from xml.etree import ElementTree

import httpx

from scrapers.http import DEFAULT_USER_AGENT


BASE = "https://spacestore.cl"
OUT = Path(__file__).with_name("spacestore_sitemap_counts.json")


def locs(content: bytes) -> list[str]:
    root = ElementTree.fromstring(content)
    return [node.text for node in root.iter()
            if node.tag.endswith("loc") and node.text]


def main() -> None:
    rows = []
    with httpx.Client(headers={"User-Agent": DEFAULT_USER_AGENT},
                      timeout=30.0, verify=True) as client:
        index = client.get(BASE + "/sitemap.xml")
        index.raise_for_status()
        urls = [url for url in locs(index.content)
                if url.startswith(BASE + "/sitemap_products_")]
        for number, url in enumerate(urls, 1):
            time.sleep(1.5)
            response = client.get(url)
            response.raise_for_status()
            root = ElementTree.fromstring(response.content)
            count = sum(node.tag.endswith("url") for node in root.iter())
            rows.append({"sitemap": url, "products": count,
                         "bytes": len(response.content)})
            if number % 10 == 0 or number == len(urls):
                print(f"{number}/{len(urls)} sitemaps, {sum(x['products'] for x in rows)} URLs", flush=True)
    result = {"at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
              "sitemaps": len(rows), "product_url_entries": sum(x["products"] for x in rows),
              "decoded_body_bytes": sum(x["bytes"] for x in rows), "files": rows}
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({key: value for key, value in result.items() if key != "files"}), flush=True)


if __name__ == "__main__":
    main()
