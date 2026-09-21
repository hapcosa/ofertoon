"""Daemon del publisher: despierta, pregunta al ranker, publica de a una.

Es el único componente de F3 con reloj propio, y esa es la diferencia con la
fase de pricing (que viaja en el ciclo del scraper, ver `pricing/pipeline.py`).
El motivo: *cuándo llega el dato* y *cuándo conviene publicar* son preguntas
distintas. El pipeline produce en dos ráfagas de 12 h a la hora en que se haya
levantado el contenedor; el canal necesita ofertas repartidas en horario
chileno. Pegar el publisher al scraper haría que la cuota entera salga de golpe
a las 3 de la mañana si esa fue la hora del `docker compose up`.

El loop es tonto a propósito: toda la política —cuántas, cuándo, con qué
espaciado, en qué ventana horaria— vive en `curation/ranker.py`. Acá solo se
decide cada cuánto preguntar. Un poll corto no publica de más: el ranker
devuelve `[]` hasta que se cumple el espaciado mínimo.

Arranca INERTE salvo `PUBLISHER_ENABLED=true`. Misma disciplina que el gate:
publicar es irreversible y un despliegue no debería empezar a postear solo.
"""
from __future__ import annotations

import asyncio
import logging
import os
import signal

import asyncpg

from publisher.poster import run_once
from subscriptions.telegram_client import TelegramClient

logger = logging.getLogger("publisher.daemon")


def _float_env(name: str, default: float) -> float:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError:
        logger.warning("env inválida %s=%r — se usa %s", name, raw, default)
        return default
    return value if value >= 0 else default


def _bool_env(name: str, *, default: bool = False) -> bool:
    raw = os.environ.get(name, "").strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on"}


def resolve_token() -> str:
    """El bot que postea.

    El orden dice la preferencia, pero **quién puede postear lo decide Telegram,
    no este archivo**: el bot tiene que ser administrator del canal con
    `can_post_messages`. Al 2026-09-21 eso es cierto solo de `@Ofertoon_bot`
    (`ONBOARDING_BOT_TOKEN`); `GATE_BOT_TOKEN` (`@Ofertoonvip_bot`) administra
    membresías y no es admin del canal, así que caer en él haría fallar todo
    post. `docker-compose.yml` resuelve `PUBLISHER_BOT_TOKEN` al de onboarding
    por eso. Si algún día se separan de verdad, hay que darle admin al nuevo bot
    en el canal antes de cambiar la variable.
    """
    return (
        os.environ.get("PUBLISHER_BOT_TOKEN", "").strip()
        or os.environ.get("GATE_BOT_TOKEN", "").strip()
        or os.environ.get("ONBOARDING_BOT_TOKEN", "").strip()
    )


async def run(*, once: bool = False) -> None:
    database_url = os.environ.get("DATABASE_URL", "").strip()
    if not database_url:
        raise SystemExit("DATABASE_URL is required")

    enabled = _bool_env("PUBLISHER_ENABLED", default=False)
    interval = _float_env("PUBLISHER_POLL_SECONDS", 300.0)
    token = resolve_token()

    pool = await asyncpg.create_pool(database_url, min_size=1, max_size=2)
    client = TelegramClient(token)

    stop_event = asyncio.Event()

    def _shutdown() -> None:
        logger.info("shutdown_signal received")
        stop_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _shutdown)
        except NotImplementedError:  # pragma: no cover - Windows
            pass

    logger.info(
        "publisher_daemon_started poll_seconds=%s enabled=%s bot_token=%s",
        interval,
        enabled,
        bool(token),
    )
    try:
        while not stop_event.is_set():
            if enabled:
                try:
                    await run_once(pool, client)
                except Exception:
                    # Publicar es lo irreversible, pero fallar publicando no
                    # puede matar al daemon: el próximo ciclo reintenta y las
                    # reservas huérfanas ya se limpian solas en `publish_one`.
                    logger.exception("la vuelta del publisher falló")
            if once:
                break
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=interval)
            except asyncio.TimeoutError:
                pass
    finally:
        await pool.close()
        logger.info("publisher_daemon_stopped")


def main() -> None:  # pragma: no cover - entrypoint
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    asyncio.run(run())


if __name__ == "__main__":  # pragma: no cover
    main()
