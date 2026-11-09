"""Webhook público de MercadoPago para las suscripciones de OfertasCL.

Misma forma que `subscriptions/paypal/webhook.py` (persistir con dedup por
`event_id` ANTES de aplicar, dentro de una transacción), pero con una pieza
extra: `apply_mercadopago_event` necesita un cliente para ir a buscar el
recurso autoritativo a la API, así que este `build_app` recibe ADEMÁS del pool
un `MercadoPagoClient` (o cualquier objeto que cumpla
`MercadoPagoResourceFetcher`).

La firma de MercadoPago (`x-signature: ts=...,v1=...`) NO cubre el body: cubre
un manifiesto `id:{data.id};request-id:{x-request-id};ts:{ts};` armado con el
`data.id` que viene en el QUERY STRING de la notificación. Por eso la
verificación se hace ANTES de tocar el body, y por eso el handler cruza el
`data.id` del query contra el del body antes de confiar en cualquiera de los
dos: la firma solo prueba "MercadoPago me mandó a mirar este id", nunca el
contenido del body.

⚠️ **Revisada el 2026-11-09 contra el SDK oficial de MercadoPago**
(`github.com/mercadopago/sdk-go`, `pkg/webhook/webhook.go`), que es la fuente
autoritativa del esquema, y tenía **un bug que rechazaba el 100% de las
notificaciones reales**: el `ts` viene en milisegundos y se comparaba contra
segundos. Corregido, junto con dos divergencias menores (el manifiesto omite
los pares vacíos; la clave del header se compara en minúsculas).

Sigue faltando la prueba contra una entrega real del sandbox —no hay
`MERCADOPAGO_ACCESS_TOKEN` en este repo—, y la lección de este bug es por qué
esa prueba no es opcional: los 11 tests construían el `ts` en segundos, o sea
medían la implementación contra sí misma y no contra MercadoPago. Antes de
confiar en esto con dinero real: dar de alta un webhook de prueba, mirar un
payload real con sus headers y confirmar que `_build_manifest` reproduce el
hash. Es la misma guarda que CLAUDE.md pide para un 403 viejo.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import time
from typing import Any, Mapping

import asyncpg
from aiohttp import web

from .client import (
    MercadoPagoClient,
    MercadoPagoConfigurationError,
    MercadoPagoUnavailable,
)
from .events import RejectedMercadoPagoEvent, apply_mercadopago_event


logger = logging.getLogger("ofertascl.mercadopago_webhook")

_MAX_BODY_BYTES = 1_000_000
# Tolerancia de replay sobre `ts`: MercadoPago no documenta una ventana, pero
# dejar el campo sin usar sería ignorar la mitad de la firma. 10 minutos es
# generoso para reintentos legítimos y corto para un replay.
#
# 🔴 **El `ts` de la firma viene en MILISEGUNDOS, no en segundos**, y acá estaba
# mal: se comparaba contra `time.time()`. El efecto no era un borde raro, era
# **rechazar con 401 toda notificación real** —`abs(1,76e9 − 1,76e12)` no entra
# en ninguna ventana— y ninguno de los 11 tests lo veía porque construían el
# `ts` en segundos, o sea medían la implementación contra sí misma. Verificado
# el 2026-11-09 contra el SDK oficial de MercadoPago
# (`github.com/mercadopago/sdk-go`, `pkg/webhook/webhook.go`): la variable se
# llama `tsMs` y la tolerancia se compara contra `o.now().UnixMilli()`. El
# ejemplo de header de su propia documentación lo confirma a simple vista:
# `ts=1742505638683`, 13 dígitos.
_MAX_TS_SKEW_MS = 600_000

#: Claves en `app` donde viven el pool asyncpg y el cliente MercadoPago.
POOL_KEY = web.AppKey("mercadopago_webhook_pool", asyncpg.Pool)
CLIENT_KEY = web.AppKey("mercadopago_webhook_client", MercadoPagoClient)


def _parse_signature_header(value: str) -> tuple[str, str] | None:
    """`ts=...,v1=...` → `(ts, v1)`. La clave se compara en minúsculas igual que
    el SDK oficial (`strings.ToLower`), que es lo que decide si un header con
    `TS=` se acepta o se descarta en silencio.

    ⚠️ Solo `v1`, que es la única versión que MercadoPago firma hoy y el default
    del SDK oficial. **Si algún día migran a `v2`, esto devuelve `None` y el
    webhook contesta 401 a todo sin decir por qué** — el SDK documenta ese caso
    como "la versión cambió, actualizá". Si las notificaciones empiezan a dar
    401 en masa sin que nadie toque el secreto, mirá acá primero.
    """
    ts = ""
    v1 = ""
    for part in value.split(","):
        key, _, raw = part.strip().partition("=")
        key = key.strip().lower()
        if key == "ts":
            ts = raw.strip()
        elif key == "v1":
            v1 = raw.strip()
    if not ts or not v1:
        return None
    return ts, v1


def _build_manifest(*, data_id: str, request_id: str, ts: str) -> bytes:
    """El manifiesto firmado, **omitiendo los pares vacíos**.

    No es un detalle cosmético: si `x-request-id` no viene, MercadoPago firma
    `id:X;ts:Y;` —sin el par ni su separador— así que rellenarlo con vacío da
    `id:X;request-id:;ts:Y;` y el HMAC no calza. Copiado de `buildManifest` del
    SDK oficial, verificado el 2026-11-09.
    """
    partes = []
    if data_id:
        partes.append(f"id:{data_id}")
    if request_id:
        partes.append(f"request-id:{request_id}")
    partes.append(f"ts:{ts}")
    return (";".join(partes) + ";").encode("utf-8")


class MercadoPagoWebhookVerifier:
    """Verifica localmente la firma HMAC-SHA256 de MercadoPago."""

    @staticmethod
    def _secret() -> str:
        secret = os.getenv("MERCADOPAGO_WEBHOOK_SECRET", "").strip()
        if not secret:
            raise MercadoPagoConfigurationError(
                "MERCADOPAGO_WEBHOOK_SECRET is not configured"
            )
        return secret

    def verify(
        self,
        headers: Mapping[str, str],
        query: Mapping[str, str],
        *,
        now: float,
    ) -> bool:
        """`now` en SEGUNDOS (`time.time()`); el `ts` del header en milisegundos.

        `data.id` sigue siendo obligatorio: sin él la notificación no dice qué
        recurso mirar y `apply_mercadopago_event` no tiene nada que buscar. El
        `x-request-id`, en cambio, es opcional —el SDK oficial lo trata así— y
        su ausencia cambia el manifiesto, no lo invalida.
        """
        secret = self._secret()
        signature_header = headers.get("x-signature", "").strip()
        request_id = headers.get("x-request-id", "").strip()
        data_id = query.get("data.id", "").strip().lower()
        if not signature_header or not data_id:
            return False
        parsed = _parse_signature_header(signature_header)
        if parsed is None:
            return False
        ts, v1 = parsed
        try:
            ts_ms = int(ts)
        except ValueError:
            return False
        if abs(now * 1000 - ts_ms) > _MAX_TS_SKEW_MS:
            return False
        try:
            expected_signature = bytes.fromhex(v1)
        except ValueError:
            return False
        manifest = _build_manifest(data_id=data_id, request_id=request_id, ts=ts)
        digest = hmac.new(secret.encode("utf-8"), manifest, hashlib.sha256).digest()
        return hmac.compare_digest(digest, expected_signature)


_verifier = MercadoPagoWebhookVerifier()


def _event_identity(envelope: dict[str, Any]) -> tuple[str, str, str | None]:
    event_id = envelope.get("id")
    event_type = envelope.get("type")
    if event_id is None or str(event_id).strip() == "" or len(str(event_id)) > 96:
        raise web.HTTPBadRequest(text="Invalid MercadoPago notification id")
    if (
        not isinstance(event_type, str)
        or not event_type.strip()
        or len(event_type) > 96
    ):
        raise web.HTTPBadRequest(text="Invalid MercadoPago notification type")
    data = envelope.get("data")
    resource_id = None
    if isinstance(data, dict) and data.get("id") is not None:
        resource_id = str(data["id"]).strip() or None
        if resource_id and len(resource_id) > 128:
            resource_id = resource_id[:128]
    return str(event_id).strip(), event_type.strip(), resource_id


async def _persist_and_apply(
    pool: asyncpg.Pool, client: MercadoPagoClient, envelope: dict[str, Any]
) -> bool:
    """Persiste y aplica en una transacción. True indica reintento duplicado.

    Deliberadamente NO atrapa `MercadoPagoUnavailable` ni
    `MercadoPagoConfigurationError`: tienen que abortar la transacción (así el
    `INSERT` de dedup también se revierte) y propagar para que el handler
    conteste 503 — un 5xx transitorio de MercadoPago o un access token roto no
    es "evento rechazado", es "todavía no sabemos".
    """
    if pool is None:
        raise RuntimeError("database is not initialized")
    event_id, event_type, resource_id = _event_identity(envelope)
    payload = json.dumps(envelope, separators=(",", ":"), ensure_ascii=False)

    async with pool.acquire() as conn:
        async with conn.transaction():
            inserted = await conn.fetchval(
                """INSERT INTO mercadopago_webhook_events
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
                processing_status, processing_error = await apply_mercadopago_event(
                    conn, envelope, client
                )
            except RejectedMercadoPagoEvent as exc:
                processing_status = "rejected"
                processing_error = str(exc)

            await conn.execute(
                """UPDATE mercadopago_webhook_events
                      SET processing_status = $2,
                          processing_error = $3,
                          processed_at = NOW()
                    WHERE event_id = $1""",
                event_id,
                processing_status,
                processing_error,
            )
    return False


async def mercadopago_webhook(request: web.Request) -> web.Response:
    """Recibe notificaciones MercadoPago; no requiere sesión de usuario."""
    client = request.app.get(CLIENT_KEY)
    if client is None:
        logger.warning("mercadopago_webhook_not_configured")
        raise web.HTTPServiceUnavailable(text="MercadoPago is not configured")

    try:
        verified = _verifier.verify(request.headers, request.query, now=time.time())
    except MercadoPagoConfigurationError as exc:
        logger.error("mercadopago_webhook_verification_unavailable reason=%s", exc)
        raise web.HTTPServiceUnavailable(
            text="MercadoPago verification temporarily unavailable"
        ) from exc
    if not verified:
        logger.warning("mercadopago_webhook_invalid_signature")
        raise web.HTTPUnauthorized(text="Invalid MercadoPago signature")

    raw_body = await request.read()
    if not raw_body:
        raise web.HTTPBadRequest(text="Empty webhook body")
    if len(raw_body) > _MAX_BODY_BYTES:
        raise web.HTTPRequestEntityTooLarge(
            max_size=_MAX_BODY_BYTES, actual_size=len(raw_body)
        )
    try:
        envelope = json.loads(raw_body)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise web.HTTPBadRequest(text="Invalid JSON body") from exc
    if not isinstance(envelope, dict):
        raise web.HTTPBadRequest(text="Webhook body must be an object")

    # La firma solo prueba el data.id del QUERY; si el body trae otro, alguien
    # (o algo) desalineó los dos y no hay garantía sobre cuál es el real.
    query_data_id = request.query.get("data.id", "").strip()
    body_data = envelope.get("data")
    body_data_id = (
        str(body_data.get("id", "")).strip() if isinstance(body_data, dict) else ""
    )
    if body_data_id and query_data_id and body_data_id != query_data_id:
        logger.warning("mercadopago_webhook_data_id_mismatch")
        raise web.HTTPBadRequest(text="data.id mismatch between query and body")

    try:
        duplicate = await _persist_and_apply(request.app[POOL_KEY], client, envelope)
    except web.HTTPException:
        raise
    except (MercadoPagoUnavailable, MercadoPagoConfigurationError) as exc:
        logger.warning("mercadopago_webhook_apply_unavailable reason=%s", exc)
        raise web.HTTPServiceUnavailable(
            text="MercadoPago temporarily unavailable"
        ) from exc
    except (asyncpg.PostgresError, RuntimeError) as exc:
        logger.exception("mercadopago_webhook_database_error")
        raise web.HTTPServiceUnavailable(
            text="Webhook persistence temporarily unavailable"
        ) from exc

    return web.json_response({"status": "accepted", "duplicate": duplicate})


async def health(_request: web.Request) -> web.Response:
    return web.json_response({"status": "ok"})


def build_app(pool: asyncpg.Pool, client: MercadoPagoClient | None) -> web.Application:
    """Arma la app aiohttp con el pool y el cliente ya creados (tests)."""
    app = web.Application(client_max_size=_MAX_BODY_BYTES)
    app[POOL_KEY] = pool
    if client is not None:
        app[CLIENT_KEY] = client
    app.router.add_post("/webhook/mercadopago", mercadopago_webhook)
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
    try:
        client: MercadoPagoClient | None = MercadoPagoClient.from_env()
    except MercadoPagoConfigurationError as exc:
        logger.warning("mercadopago_client_not_configured reason=%s", exc)
        client = None
    app = build_app(pool, client)
    port = int(os.environ.get("MERCADOPAGO_WEBHOOK_PORT", "8080"))
    logger.info("webhook MercadoPago escuchando en :%d/webhook/mercadopago", port)
    await web._run_app(app, host="0.0.0.0", port=port, print=None)


if __name__ == "__main__":  # pragma: no cover
    import asyncio

    asyncio.run(_run())
