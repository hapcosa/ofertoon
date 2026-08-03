"""Daemon del gate: reconcilia membresías contra los canales de Telegram.

En signalsTrading el reconciler viajaba de polizón en el loop del poster de
señales (`telegram_signals/daemon.py`, que además publica, postea resultados y
ancla fichas). OfertasCL todavía no tiene publisher (F3), así que el gate corre
solo: un loop chico que llama a `run_once()` cada `GATE_POLL_SECONDS`.

Arranca INERTE salvo que `GATE_ENABLED=true`. Es a propósito: con los canales
recién creados y los tiers a medio sembrar, un gate encendido expulsa gente por
un error de configuración. Además hay un segundo interruptor por canal
(`telegram_tiers.gate_enabled`); el efectivo es el AND de los dos.
"""
from __future__ import annotations

import asyncio
import logging
import os
import signal

import asyncpg

from .gate import MembershipReconciler
from .telegram_client import TelegramClient


logger = logging.getLogger("ofertascl.gate_daemon")


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


async def run(*, once: bool = False) -> None:
    database_url = os.environ.get("DATABASE_URL", "").strip()
    if not database_url:
        raise SystemExit("DATABASE_URL is required")

    # El gate administra los canales con el MISMO bot del onboarding: es el que
    # tiene que ser admin de ambos canales para poder invitar y expulsar.
    # `GATE_BOT_TOKEN` permite separarlos si algún día conviene.
    token = (
        os.environ.get("GATE_BOT_TOKEN", "").strip()
        or os.environ.get("ONBOARDING_BOT_TOKEN", "").strip()
    )
    pool = await asyncpg.create_pool(database_url, min_size=1, max_size=2)
    enabled = _bool_env("GATE_ENABLED", default=False)
    reconciler = MembershipReconciler(
        pool,
        TelegramClient(token),
        grace_days=_float_env("GATE_GRACE_DAYS", 3.0),
        invite_ttl_hours=_float_env("GATE_INVITE_TTL_HOURS", 24.0),
        enabled=enabled,
    )

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

    interval = _float_env("GATE_POLL_SECONDS", 30.0)
    logger.info(
        "gate_daemon_started poll_seconds=%s gate_enabled=%s bot_token=%s",
        interval,
        enabled,
        bool(token),
    )
    try:
        while not stop_event.is_set():
            await reconciler.run_once()
            if once:
                break
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=interval)
            except asyncio.TimeoutError:
                pass
    finally:
        await pool.close()
        logger.info("gate_daemon_stopped")


def main() -> None:  # pragma: no cover - entrypoint
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    asyncio.run(run())


if __name__ == "__main__":  # pragma: no cover
    main()
