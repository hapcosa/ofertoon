"""Sonda reproducible de acceso público para tiendas antes descartadas.

Uso desde la raíz del worktree:
    PYTHONPATH=. python research/2026-11-07/probe.py browser https://example.cl/

No desactiva TLS, no reintenta desafíos y solo usa headers del proyecto.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import time
from collections import Counter
from datetime import datetime, timezone
from urllib.parse import urlsplit
from xml.etree import ElementTree

import httpx

from scrapers.http import (
    BROWSER_HEADERS,
    BROWSER_HEADERS_JSON,
    BROWSER_USER_AGENT,
    DEFAULT_USER_AGENT,
)


HEADERS = {
    "default": {"User-Agent": DEFAULT_USER_AGENT},
    "browser_ua": {"User-Agent": BROWSER_USER_AGENT},
    "browser": BROWSER_HEADERS,
    "browser_json": BROWSER_HEADERS_JSON,
}


def summary(response: httpx.Response) -> dict:
    text = response.text
    title = re.search(r"<title[^>]*>(.*?)</title>", text, re.I | re.S)
    result = {
        "status": response.status_code,
        "url_final": str(response.url),
        "bytes": len(response.content),
        "sha256_16": hashlib.sha256(response.content).hexdigest()[:16],
        "content_type": response.headers.get("content-type"),
        "server": response.headers.get("server"),
        "cf_mitigated": response.headers.get("cf-mitigated"),
        "title": re.sub(r"\s+", " ", title.group(1)).strip()[:120] if title else None,
        "markers": {
            marker: text.lower().count(marker.lower())
            for marker in ("occ-public", "__NEXT_DATA__", "shopify", "jumpseller", "product-list__item")
            if marker.lower() in text.lower()
        },
    }
    if urlsplit(str(response.url)).path == "/robots.txt" and response.status_code == 200:
        rules = [line.strip() for line in text.splitlines()
                 if re.match(r"^(User-agent|Disallow|Allow|Crawl-delay|Sitemap):", line.strip(), re.I)]
        result["robots"] = rules[:70]
    if "xml" in response.headers.get("content-type", "") or str(response.url).endswith(".xml"):
        try:
            root = ElementTree.fromstring(response.content)
            links = [e.text for e in root.iter() if e.tag.endswith("loc") and e.text]
            result["sitemap"] = {
                "root": root.tag.rsplit("}", 1)[-1],
                "links": len(links),
                "groups": dict(Counter(
                    re.search(r"sitemap_([^/?.]+)", urlsplit(link).path).group(1)
                    if re.search(r"sitemap_([^/?.]+)", urlsplit(link).path)
                    else "other" for link in links
                )),
                "sample": links[:8],
            }
        except ElementTree.ParseError:
            pass
    if "json" in response.headers.get("content-type", ""):
        try:
            body = response.json()
            result["json_type"] = type(body).__name__
            if isinstance(body, dict):
                result["json_keys"] = list(body)[:20]
                if response.status_code >= 400:
                    result["error_fields"] = {
                        key: body[key] for key in
                        ("error_name", "error_category", "cloudflare_error", "retryable", "owner_action_required")
                        if key in body
                    }
            elif isinstance(body, list):
                result["json_count"] = len(body)
        except ValueError:
            pass
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("headers", choices=HEADERS)
    parser.add_argument("url")
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--delay", type=float, default=2.0)
    args = parser.parse_args()
    if not 1 <= args.repeat <= 4:
        parser.error("repeat debe estar entre 1 y 4")
    with httpx.Client(headers=HEADERS[args.headers], follow_redirects=True,
                      verify=True, timeout=18.0, http2=False) as client:
        for attempt in range(1, args.repeat + 1):
            started = datetime.now(timezone.utc).isoformat(timespec="seconds")
            try:
                response = client.get(args.url)
                result = summary(response)
            except httpx.HTTPError as exc:
                result = {"error": type(exc).__name__, "detail": str(exc)[:240]}
            print(json.dumps({"at_utc": started, "attempt": attempt,
                              "headers": args.headers, "url": args.url,
                              **result}, ensure_ascii=False), flush=True)
            if attempt < args.repeat:
                time.sleep(args.delay)


if __name__ == "__main__":
    main()
