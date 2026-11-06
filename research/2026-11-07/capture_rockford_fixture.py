"""Captura tres productos reales para el contrato Rockford, incluido un agotado."""
from __future__ import annotations

import json
import time
from pathlib import Path

import httpx

from scrapers.http import DEFAULT_USER_AGENT


BASE = "https://www.rkflife.com"
OUT = Path("tests/fixtures/rockford_hombre_vestuario.json")


def slim(product: dict) -> dict:
    return {key: product.get(key) for key in
            ("id", "handle", "title", "vendor", "images", "variants")}


def main() -> None:
    found: dict[str, tuple[int, dict]] = {}
    with httpx.Client(headers={"User-Agent": DEFAULT_USER_AGENT},
                      follow_redirects=True, verify=True, timeout=20) as client:
        for page in range(1, 6):
            if page > 1:
                time.sleep(2)
            url = f"{BASE}/collections/hombre-vestuario/products.json?limit=250&page={page}"
            response = client.get(url)
            response.raise_for_status()
            for product in response.json()["products"]:
                variants = product.get("variants") or []
                available = [v.get("available") for v in variants]
                if not variants:
                    continue
                if not any(available) and "agotado" not in found:
                    found["agotado"] = (page, product)
                elif any(available) and not all(available) and "mixto" not in found:
                    found["mixto"] = (page, product)
                elif all(available) and "disponible" not in found:
                    found["disponible"] = (page, product)
            if len(found) == 3:
                break
    if len(found) != 3:
        raise RuntimeError(f"faltan controles de stock: {list(found)}")
    pages = sorted({page for page, _ in found.values()})
    payload = {
        "_fixture": (
            "HTML/JSON público real de Rockford, 2026-11-06, "
            "https://www.rkflife.com/collections/hombre-vestuario/"
            "products.json?limit=250&page=N, N=" + ",".join(map(str, pages)) +
            ". Recortado a tres productos reales: uno disponible, uno con "
            "talles mixtos y uno agotado; se conservaron campos de producto "
            "y variantes necesarios para el parser."
        ),
        "products": [slim(found[name][1]) for name in
                     ("disponible", "mixto", "agotado")],
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({name: {"page": page, "id": product["id"],
                             "title": product["title"],
                             "variants": len(product["variants"])}
                      for name, (page, product) in found.items()}, ensure_ascii=False))
    print(OUT)


if __name__ == "__main__":
    main()
