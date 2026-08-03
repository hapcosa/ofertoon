"""Webhook público de PayPal para las suscripciones de OfertasCL.

PORT de `signalsTrading/dashboard/backend/paypal_webhook_api.py`. La
verificación de firma (`PayPalWebhookVerifier`) y `_persist_and_apply` se copian
sin tocar la lógica; lo único que cambia es el transporte: acá se sirve con
`aiohttp.web` en lugar de FastAPI, porque OfertasCL no tiene dashboard y no vale
la pena arrastrar fastapi+uvicorn por un solo endpoint (aiohttp ya es
dependencia del proyecto).

La firma se verifica LOCALMENTE contra el certificado de PayPal, no con el
endpoint `/v1/notifications/verify-webhook-signature`: eso evita depender de una
llamada extra a PayPal justo cuando hay que decidir si alguien pagó. El body
crudo se firma tal cual llegó, así que nunca hay que reserializarlo antes de
verificar.
"""
from __future__ import annotations

import base64
import binascii
import json
import logging
import os
from typing import Any, Mapping
from urllib.parse import urlsplit
import zlib

import asyncpg
from aiohttp import web
from cryptography import x509
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa
import httpx

from .events import RejectedPayPalEvent, apply_paypal_event


logger = logging.getLogger("ofertascl.paypal_webhook")

_MAX_BODY_BYTES = 1_000_000
_PAYPAL_CERT_HOSTS = {
    "api.paypal.com",
    "api.sandbox.paypal.com",
    "api-m.paypal.com",
    "api-m.sandbox.paypal.com",
}

#: Clave en `app` donde vive el pool asyncpg que usa el handler.
POOL_KEY = web.AppKey("paypal_webhook_pool", asyncpg.Pool)


class PayPalVerificationUnavailable(RuntimeError):
    """La firma no pudo comprobarse por configuración o red."""


class PayPalWebhookVerifier:
    """Verifica localmente la firma RSA de PayPal sobre el body original."""

    def __init__(self) -> None:
        self._certificate_cache: dict[str, bytes] = {}

    @staticmethod
    def _webhook_id() -> str:
        webhook_id = os.getenv("PAYPAL_WEBHOOK_ID", "").strip()
        if not webhook_id:
            raise PayPalVerificationUnavailable("PAYPAL_WEBHOOK_ID is not configured")
        return webhook_id

    @staticmethod
    def _certificate_url_allowed(url: str) -> bool:
        parsed = urlsplit(url)
        return (
            parsed.scheme == "https"
            and parsed.hostname in _PAYPAL_CERT_HOSTS
            and parsed.username is None
            and parsed.password is None
            and parsed.port in (None, 443)
            and parsed.path.startswith("/v1/notifications/certs/")
            and not parsed.query
            and not parsed.fragment
        )

    async def _fetch_certificate(self, url: str) -> bytes:
        cached = self._certificate_cache.get(url)
        if cached is not None:
            return cached
        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(5.0), follow_redirects=False
            ) as client:
                response = await client.get(url)
                response.raise_for_status()
        except (httpx.HTTPError, httpx.TimeoutException) as exc:
            raise PayPalVerificationUnavailable("PayPal certificate unavailable") from exc
        content = response.content
        if not content or len(content) > 65_536:
            raise PayPalVerificationUnavailable("invalid PayPal certificate response")
        if len(self._certificate_cache) >= 8:
            self._certificate_cache.pop(next(iter(self._certificate_cache)))
        self._certificate_cache[url] = content
        return content

    async def verify(self, raw_body: bytes, headers: Mapping[str, str]) -> bool:
        webhook_id = self._webhook_id()
        transmission_id = headers.get("paypal-transmission-id", "").strip()
        transmission_time = headers.get("paypal-transmission-time", "").strip()
        cert_url = headers.get("paypal-cert-url", "").strip()
        auth_algo = headers.get("paypal-auth-algo", "").strip()
        encoded_signature = headers.get("paypal-transmission-sig", "").strip()
        if not all(
            (transmission_id, transmission_time, cert_url, auth_algo, encoded_signature)
        ):
            return False
        if auth_algo.upper() != "SHA256WITHRSA":
            return False
        if not self._certificate_url_allowed(cert_url):
            return False

        try:
            signature = base64.b64decode(encoded_signature, validate=True)
        except (ValueError, binascii.Error):
            return False
        if not signature:
            return False

        pem = await self._fetch_certificate(cert_url)
        try:
            certificate = x509.load_pem_x509_certificate(pem)
            public_key = certificate.public_key()
        except ValueError:
            return False
        if not isinstance(public_key, rsa.RSAPublicKey):
            return False

        crc = zlib.crc32(raw_body) & 0xFFFFFFFF
        message = f"{transmission_id}|{transmission_time}|{webhook_id}|{crc}".encode(
            "utf-8"
        )
        try:
            public_key.verify(
                signature,
                message,
                padding.PKCS1v15(),
                hashes.SHA256(),
            )
        except InvalidSignature:
            return False
        return True


_verifier = PayPalWebhookVerifier()


def _event_identity(event: dict[str, Any]) -> tuple[str, str, str | None]:
    event_id = event.get("id")
    event_type = event.get("event_type")
    if not isinstance(event_id, str) or not event_id.strip() or len(event_id) > 96:
        raise web.HTTPBadRequest(text="Invalid PayPal event id")
    if (
        not isinstance(event_type, str)
        or not event_type.strip()
        or len(event_type) > 96
    ):
        raise web.HTTPBadRequest(text="Invalid PayPal event type")
    resource = event.get("resource")
    resource_id = None
    if isinstance(resource, dict) and resource.get("id") is not None:
        resource_id = str(resource["id"]).strip() or None
        if resource_id and len(resource_id) > 128:
            resource_id = resource_id[:128]
    return event_id.strip(), event_type.strip(), resource_id


async def _persist_and_apply(pool: asyncpg.Pool, event: dict[str, Any]) -> bool:
    """Persiste y aplica en una transacción. True indica reintento duplicado."""
    if pool is None:
        raise RuntimeError("database is not initialized")
    event_id, event_type, resource_id = _event_identity(event)
    payload = json.dumps(event, separators=(",", ":"), ensure_ascii=False)

    async with pool.acquire() as conn:
        async with conn.transaction():
            inserted = await conn.fetchval(
                """INSERT INTO paypal_webhook_events
                       (event_id, event_type, resource_id, payload)
                     VALUES ($1, $2, $3, $4::jsonb)
                     ON CONFLICT (event_id) DO NOTHING
                  RETURNING event_id""",
                event_id,
                event_type,
                resource_id,
                payload,
            )
            if inserted is None:
                return True

            try:
                processing_status, processing_error = await apply_paypal_event(conn, event)
            except RejectedPayPalEvent as exc:
                processing_status = "rejected"
                processing_error = str(exc)

            await conn.execute(
                """UPDATE paypal_webhook_events
                      SET processing_status = $2,
                          processing_error = $3,
                          processed_at = NOW()
                    WHERE event_id = $1""",
                event_id,
                processing_status,
                processing_error,
            )
    return False


async def paypal_webhook(request: web.Request) -> web.Response:
    """Recibe eventos PayPal firmados; no requiere sesión de usuario."""
    raw_body = await request.read()
    if not raw_body:
        raise web.HTTPBadRequest(text="Empty webhook body")
    if len(raw_body) > _MAX_BODY_BYTES:
        raise web.HTTPRequestEntityTooLarge(
            max_size=_MAX_BODY_BYTES, actual_size=len(raw_body)
        )

    try:
        verified = await _verifier.verify(raw_body, request.headers)
    except PayPalVerificationUnavailable as exc:
        logger.error("paypal_webhook_verification_unavailable reason=%s", exc)
        raise web.HTTPServiceUnavailable(
            text="PayPal verification temporarily unavailable"
        ) from exc
    except Exception as exc:
        logger.exception("paypal_webhook_verification_error")
        raise web.HTTPServiceUnavailable(
            text="PayPal verification temporarily unavailable"
        ) from exc
    if not verified:
        logger.warning("paypal_webhook_invalid_signature")
        raise web.HTTPUnauthorized(text="Invalid PayPal signature")

    try:
        event = json.loads(raw_body)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise web.HTTPBadRequest(text="Invalid JSON body") from exc
    if not isinstance(event, dict):
        raise web.HTTPBadRequest(text="Webhook body must be an object")

    try:
        duplicate = await _persist_and_apply(request.app[POOL_KEY], event)
    except web.HTTPException:
        raise
    except (asyncpg.PostgresError, RuntimeError) as exc:
        logger.exception("paypal_webhook_database_error")
        raise web.HTTPServiceUnavailable(
            text="Webhook persistence temporarily unavailable"
        ) from exc

    return web.json_response({"status": "accepted", "duplicate": duplicate})


async def health(_request: web.Request) -> web.Response:
    return web.json_response({"status": "ok"})


def build_app(pool: asyncpg.Pool) -> web.Application:
    """Arma la app aiohttp con el pool ya creado (facilita los tests)."""
    app = web.Application(client_max_size=_MAX_BODY_BYTES)
    app[POOL_KEY] = pool
    app.router.add_post("/webhook/paypal", paypal_webhook)
    app.router.add_get("/health", health)
    return app


async def _run() -> None:
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    pool = await asyncpg.create_pool(
        os.environ["DATABASE_URL"], min_size=1, max_size=4
    )
    app = build_app(pool)
    port = int(os.environ.get("PAYPAL_WEBHOOK_PORT", "8080"))
    logger.info("webhook PayPal escuchando en :%d/webhook/paypal", port)
    await web._run_app(app, host="0.0.0.0", port=port, print=None)


if __name__ == "__main__":  # pragma: no cover
    import asyncio

    asyncio.run(_run())
