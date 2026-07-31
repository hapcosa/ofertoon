"""Cliente HTTP compartido por los adaptadores.

Tres responsabilidades: no pasarse de rosca con ninguna tienda (rate limit por
host), reintentar lo que es transitorio, y poder grabar respuestas a disco para
convertirlas en fixtures de test sin volver a salir a la red.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import random
import time
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)

#: User-Agent identificable. No se hace pasar por otra cosa: si una tienda quiere
#: bloquearnos, que pueda hacerlo limpiamente en vez de forzar una escalada.
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/126.0.0.0 Safari/537.36 (+ofertascl-bot)"
)

RETRYABLE_STATUS = frozenset({408, 425, 429, 500, 502, 503, 504})


class RateLimiter:
    """Un token cada `1/rps` segundos, serializado por host."""

    def __init__(self, rps: float) -> None:
        if rps <= 0:
            raise ValueError(f"rps debe ser > 0, llegó {rps!r}")
        self._min_interval = 1.0 / rps
        self._lock = asyncio.Lock()
        self._last = 0.0

    async def acquire(self) -> None:
        async with self._lock:
            wait = self._min_interval - (time.monotonic() - self._last)
            if wait > 0:
                await asyncio.sleep(wait)
            self._last = time.monotonic()


class FetchError(RuntimeError):
    """Falla no recuperable tras agotar los reintentos."""


class HttpClient:
    """Cliente con rate limit por host, backoff exponencial y caché opcional.

    `cache_dir` no es una caché de producción: es el mecanismo para grabar
    respuestas reales y congelarlas como fixtures (`--record`). En el daemon
    queda en None.
    """

    def __init__(
        self,
        *,
        default_rps: float = 1.0,
        timeout: float = 30.0,
        max_retries: int = 3,
        user_agent: str = DEFAULT_USER_AGENT,
        cache_dir: Path | None = None,
    ) -> None:
        self._default_rps = default_rps
        self._max_retries = max_retries
        self._limiters: dict[str, RateLimiter] = {}
        self._cache_dir = cache_dir
        if cache_dir is not None:
            cache_dir.mkdir(parents=True, exist_ok=True)
        self._client = httpx.AsyncClient(
            timeout=timeout,
            follow_redirects=True,
            headers={
                "User-Agent": user_agent,
                "Accept-Language": "es-CL,es;q=0.9",
            },
        )

    async def __aenter__(self) -> "HttpClient":
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self._client.aclose()

    def _limiter(self, host: str, rps: float | None) -> RateLimiter:
        limiter = self._limiters.get(host)
        if limiter is None:
            limiter = RateLimiter(rps or self._default_rps)
            self._limiters[host] = limiter
        return limiter

    def _cache_path(self, url: str) -> Path | None:
        if self._cache_dir is None:
            return None
        digest = hashlib.sha256(url.encode()).hexdigest()[:20]
        return self._cache_dir / f"{digest}.html"

    async def get_text(
        self,
        url: str,
        *,
        rps: float | None = None,
        headers: dict[str, str] | None = None,
    ) -> str:
        cached = self._cache_path(url)
        if cached is not None and cached.exists():
            return cached.read_text(encoding="utf-8")

        host = httpx.URL(url).host or "unknown"
        last_exc: Exception | None = None

        for attempt in range(self._max_retries + 1):
            await self._limiter(host, rps).acquire()
            try:
                response = await self._client.get(url, headers=headers)
            except httpx.HTTPError as exc:
                last_exc = exc
            else:
                if response.status_code == 200:
                    text = response.text
                    if cached is not None:
                        cached.write_text(text, encoding="utf-8")
                    return text
                if response.status_code not in RETRYABLE_STATUS:
                    raise FetchError(f"{url} -> HTTP {response.status_code}")
                last_exc = FetchError(f"{url} -> HTTP {response.status_code}")

            if attempt < self._max_retries:
                # Backoff exponencial con jitter: 1s, 2s, 4s (±25%).
                delay = (2**attempt) * (0.75 + random.random() * 0.5)
                logger.warning(
                    "fetch_retry url=%s attempt=%d/%d delay=%.1fs cause=%s",
                    url,
                    attempt + 1,
                    self._max_retries,
                    delay,
                    last_exc,
                )
                await asyncio.sleep(delay)

        raise FetchError(f"{url}: agotados {self._max_retries} reintentos") from last_exc
