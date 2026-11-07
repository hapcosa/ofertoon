"""Entry point combinado: un solo puerto expone PayPal y MercadoPago.

El túnel Cloudflare de producción (fuera del repo, ver CLAUDE.md
§Infraestructura) ya apunta `sendtelegram.budaicapital.com` al servicio
Docker `paypal-webhook:8080`. Agregar un segundo servicio con su propio puerto
para MercadoPago obligaría a editar ese túnel desde afuera del repo — una
acción del dueño, no del código. En vez de eso, un solo proceso atiende los
dos paths y el servicio Docker sigue llamándose `paypal-webhook` a propósito
(ver docker-compose.yml).

Cada proveedor sigue siendo un módulo aparte y completamente independiente
(`subscriptions.paypal.webhook`, `subscriptions.mercadopago.webhook`), cada
uno con su propio `build_app` para tests unitarios; este archivo es la única
pieza que los junta en un proceso real.
"""
from __future__ import annotations

import logging
import os

import asyncpg
from aiohttp import web

from .mercadopago.client import MercadoPagoClient, MercadoPagoConfigurationError
from .mercadopago import webhook as mercadopago_webhook
from .paypal import webhook as paypal_webhook


logger = logging.getLogger("ofertascl.webhooks")

_MAX_BODY_BYTES = 1_000_000


def build_app(
    pool: asyncpg.Pool, mercadopago_client: MercadoPagoClient | None
) -> web.Application:
    app = web.Application(client_max_size=_MAX_BODY_BYTES)
    app[paypal_webhook.POOL_KEY] = pool
    app[mercadopago_webhook.POOL_KEY] = pool
    if mercadopago_client is not None:
        app[mercadopago_webhook.CLIENT_KEY] = mercadopago_client
    app.router.add_post("/webhook/paypal", paypal_webhook.paypal_webhook)
    app.router.add_post("/webhook/mercadopago", mercadopago_webhook.mercadopago_webhook)
    app.router.add_get("/health", paypal_webhook.health)
    return app


async def _run() -> None:
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    pool = await asyncpg.create_pool(
        os.environ["DATABASE_URL"], min_size=1, max_size=4
    )
    # Sin MERCADOPAGO_ACCESS_TOKEN el proceso arranca igual: PayPal no puede
    # depender de que MercadoPago esté configurado, porque comparten puerto.
    # `/webhook/mercadopago` contesta 503 "not configured" en vez de tumbar
    # todo el proceso.
    try:
        mercadopago_client: MercadoPagoClient | None = MercadoPagoClient.from_env()
    except MercadoPagoConfigurationError as exc:
        logger.warning("mercadopago_client_not_configured reason=%s", exc)
        mercadopago_client = None
    app = build_app(pool, mercadopago_client)
    port = int(os.environ.get("PAYPAL_WEBHOOK_PORT", "8080"))
    logger.info(
        "webhooks escuchando en :%d (/webhook/paypal, /webhook/mercadopago) "
        "mercadopago_configurado=%s",
        port,
        mercadopago_client is not None,
    )
    await web._run_app(app, host="0.0.0.0", port=port, print=None)


if __name__ == "__main__":  # pragma: no cover
    import asyncio

    asyncio.run(_run())
