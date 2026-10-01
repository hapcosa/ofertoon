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

#: Mismo UA sin el sufijo identificable, para las tiendas que hacen UA-sniffing.
#:
#: Easy es el caso verificado (2026-07-31): con `DEFAULT_USER_AGENT` responde
#: **HTTP 200 con la home** (`__NEXT_DATA__.page == "/"`) en vez del listado. No
#: es un bloqueo — es una degradación silenciosa, que es peor: sin el guard de
#: `NotAListingPage` habríamos ingerido cero productos sin un solo error.
#:
#: Se usa **por adaptador**, nunca como default: las tiendas que respetan el UA
#: identificable lo siguen recibiendo.
BROWSER_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/126.0.0.0 Safari/537.36"
)

#: El juego completo de headers que manda un navegador. Para las tiendas cuyo
#: borde no mira el User-Agent sino la **ausencia** de los headers que cualquier
#: navegador envía — sobre todo `Accept-Language`, `Accept-Encoding` y la familia
#: `Sec-Fetch-*`, que son los que delatan a un cliente HTTP pelado.
#:
#: Medido el 2026-10-01 sobre las 8 tiendas que el plan tenía como "bloqueadas
#: por 403" (PLAN_TIENDAS Fase 6). Con `BROWSER_USER_AGENT` solo contra con esto:
#:
#:     Tottus       403 → 200
#:     Nike         403 → 200
#:     Unimarc      403 → pasa el borde (su API VTEX contesta 500, le faltan params)
#:     PC Express   403 → pasa el borde (404: hay que descubrir las rutas)
#:     Adidas       403 → robots.txt 200 (la home sigue 403, es Akamai)
#:
#: No abre todo, y eso está bien: Decathlon, Nice One y MTS siguen en 403 duro
#: con Cloudflare. **Ahí se para.** Pasar un bot management de verdad pide
#: fingerprint de TLS o un navegador headless, y este scraper es deliberadamente
#: `httpx` + parseo posicional, sin browser. Una tienda que de verdad no nos
#: quiere, no nos tiene.
#:
#: Igual que `BROWSER_USER_AGENT`: se usa **por adaptador**, nunca como default.
BROWSER_HEADERS = {
    "User-Agent": BROWSER_USER_AGENT,
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "image/avif,image/webp,*/*;q=0.8"
    ),
    "Accept-Language": "es-CL,es;q=0.9,en;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Sec-Ch-Ua": '"Chromium";v="126", "Not;A=Brand";v="24"',
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Ch-Ua-Platform": '"Linux"',
    "Upgrade-Insecure-Requests": "1",
    "Connection": "keep-alive",
}

#: La variante para llamadas XHR/API: mismo borde, otro `Accept` y otra familia
#: `Sec-Fetch-*`. Un `Sec-Fetch-Mode: navigate` pidiendo JSON es incoherente y
#: algunos bordes lo marcan.
BROWSER_HEADERS_JSON = {
    **BROWSER_HEADERS,
    "Accept": "application/json",
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-origin",
}

#: Qué cuenta como respuesta buena. **206 está acá por VTEX**: su API pública de
#: catálogo (`/api/catalog_system/pub/products/search`) contesta `206 Partial
#: Content` SIEMPRE, porque el rango pedido con `_from`/`_to` es por definición
#: parcial respecto del total que declara en el header `Resources`. No es un
#: error ni una degradación: es la respuesta normal y completa para ese rango.
#:
#: Sin esto, cualquier adaptador VTEX muere en el primer fetch con
#: `FetchError: HTTP 206` — y VTEX es la plataforma de buena parte del retail
#: chileno (Nike, Colloky y las cinco de la Fase 3).
#:
#: Se listan los códigos uno por uno en vez de aceptar todo 2xx a propósito: un
#: 204 sin cuerpo devolvería `""` y el parser lo leería como catálogo vacío, que
#: es exactamente el fallo silencioso que `NotAListingPage` existe para evitar.
SUCCESS_STATUS = frozenset({200, 206})

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
    """Falla no recuperable tras agotar los reintentos.

    `status_code` viene poblado solo cuando la tienda respondió con un status
    HTTP: es `None` si lo que falló fue el transporte. Existe para que un
    adaptador pueda distinguir un status que en ESA tienda significa algo
    (Easy devuelve 404 pasado el final de la paginación) sin parsear el mensaje.
    """

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


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
        text, _ = await self._request("GET", url, rps=rps, headers=headers)
        return text

    async def get_with_headers(
        self,
        url: str,
        *,
        rps: float | None = None,
        headers: dict[str, str] | None = None,
    ) -> tuple[str, dict[str, str]]:
        """Como `get_text` pero devuelve también los headers de respuesta.

        Lo pide el chequeo exacto de completitud: VTEX no pone el total de la
        categoría en el cuerpo sino en `Resources: 0-49/2546`. Leer ese header es
        la diferencia entre el canario estadístico (una inferencia) y el exacto.
        """
        return await self._request("GET", url, rps=rps, headers=headers)

    async def post_json(
        self,
        url: str,
        payload: object,
        *,
        rps: float | None = None,
        headers: dict[str, str] | None = None,
    ) -> str:
        """POST con cuerpo JSON. Devuelve el texto crudo de la respuesta.

        Existe porque no todas las tiendas exponen su catálogo por GET: Paris lo
        sirve con un POST cuyo cuerpo lleva filtros y paginación. La caché de
        fixtures se saltea acá a propósito — la clave sería la URL, y dos POST a
        la misma URL con cuerpos distintos colisionarían.
        """
        text, _ = await self._request("POST", url, rps=rps, headers=headers, json=payload)
        return text

    async def _request(
        self,
        method: str,
        url: str,
        *,
        rps: float | None,
        headers: dict[str, str] | None,
        json: object | None = None,
    ) -> tuple[str, dict[str, str]]:
        """`(cuerpo, headers)`. Los headers importan para el canario exacto:
        VTEX declara el total de la categoría en `Resources: 0-49/2546`, que es
        justo lo que `CountingAdapter` necesita y no viene en el cuerpo."""
        cached = self._cache_path(url) if method == "GET" else None
        if cached is not None and cached.exists():
            # Una respuesta congelada como fixture no tiene headers que ofrecer.
            return cached.read_text(encoding="utf-8"), {}

        host = httpx.URL(url).host or "unknown"
        last_exc: Exception | None = None

        for attempt in range(self._max_retries + 1):
            await self._limiter(host, rps).acquire()
            try:
                response = await self._client.request(
                    method, url, headers=headers, json=json
                )
            except httpx.HTTPError as exc:
                last_exc = exc
            else:
                if response.status_code in SUCCESS_STATUS:
                    text = response.text
                    if cached is not None:
                        cached.write_text(text, encoding="utf-8")
                    return text, dict(response.headers)
                if response.status_code not in RETRYABLE_STATUS:
                    raise FetchError(
                        f"{url} -> HTTP {response.status_code}",
                        status_code=response.status_code,
                    )
                last_exc = FetchError(
                    f"{url} -> HTTP {response.status_code}",
                    status_code=response.status_code,
                )

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

        raise FetchError(
            f"{url}: agotados {self._max_retries} reintentos",
            status_code=getattr(last_exc, "status_code", None),
        ) from last_exc
