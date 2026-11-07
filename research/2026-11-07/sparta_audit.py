"""Re-mide las llaves de la migración 52 con el parser y UA del proyecto.

Uso desde la raíz del worktree:
    PYTHONPATH=. python research/2026-11-07/sparta_audit.py

Solo consulta URLs públicas sin parámetros. Una redirección o error detiene el
recorrido para no confundir una llave cambiada con una categoría sana.
"""
from __future__ import annotations

import json
import re
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import httpx

from scrapers.base import CategoryRef
from scrapers.http import DEFAULT_USER_AGENT
from scrapers.stores.magento_html import parse_listing


ROOT = Path(__file__).resolve().parents[2]
MIGRATION = ROOT / "migrations/52_sparta_tajada_disjunta.sql"
OUT = Path(__file__).with_name("sparta_selected_2026-11-06.json")
KEY_RE = re.compile(r"\('(?P<category>deporte-[^']+)', '(?P<key>[^']+\.html)'\)")


def main() -> None:
    keys = KEY_RE.findall(MIGRATION.read_text(encoding="utf-8"))
    if len(keys) != 63:
        raise RuntimeError(f"se esperaban 63 llaves; hay {len(keys)}")

    rows = []
    last_start = 0.0
    with httpx.Client(headers={"User-Agent": DEFAULT_USER_AGENT},
                      follow_redirects=False, verify=True, timeout=30.0) as client:
        for category_slug, key in keys:
            pause = 1.0 - (time.monotonic() - last_start)
            if pause > 0:
                time.sleep(pause)
            last_start = time.monotonic()
            url = f"https://sparta.cl/{key}"
            response = client.get(url)
            if response.status_code != 200:
                raise RuntimeError(f"HTTP {response.status_code}: {url}")
            parsed = parse_listing(
                response.text,
                store_slug="sparta",
                category=CategoryRef(slug=category_slug, store_key=key),
                scraped_at=datetime.now(timezone.utc),
            )
            if not parsed.products:
                raise RuntimeError(f"sin productos: {url}")
            rows.append({
                "category": category_slug,
                "key": key,
                "declared": parsed.declared,
                "enumerated": parsed.enumerated,
                "decoded_body_bytes": len(response.content),
                "skus": sorted({p.store_sku for p in parsed.products}),
            })

    by_category: dict[str, set[str]] = defaultdict(set)
    for row in rows:
        by_category[row["category"]].update(row["skus"])
    overlaps = {
        f"{a} x {b}": len(by_category[a] & by_category[b])
        for a in sorted(by_category) for b in sorted(by_category) if a < b
    }
    result = {
        "at_utc": datetime.now(timezone.utc).isoformat(),
        "source": "migrations/52_sparta_tajada_disjunta.sql",
        "requests": len(rows),
        "decoded_body_bytes": sum(row["decoded_body_bytes"] for row in rows),
        "unique_skus": len(set().union(*by_category.values())),
        "by_category": {key: len(value) for key, value in by_category.items()},
        "cross_category_overlap": overlaps,
        "partial_keys": sum(
            row["declared"] is not None and row["enumerated"] < row["declared"]
            for row in rows
        ),
        "rows": rows,
    }
    OUT.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({key: value for key, value in result.items() if key != "rows"},
                     ensure_ascii=False))
    if any(overlaps.values()):
        raise RuntimeError("hay SKUs cruzados entre categorías internas")


if __name__ == "__main__":
    main()
