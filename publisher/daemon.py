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

Desde el 2026-11-09 el loop también **mira si el canal arrancó** (ver
`publisher/guarda_canal.py`). Va acá y no en el scraper porque la pregunta es
"¿salió el primer post?", y el único proceso que sabe la respuesta sin inventar
un reloj nuevo es este, que ya despierta cada `PUBLISHER_POLL_SECONDS` y ya lee
`deal_posts`. Arranca apagada (`PUBLISHER_ALERTA_CANAL_MUDO`, default false),
igual que todo lo que habla hacia afuera en este repo.
"""
from __future__ import annotations

import asyncio
import logging
import os
import signal
from datetime import date, datetime, timezone

import asyncpg

from alerts import send_alert
from curation import ranker
from publisher.guarda_canal import DEADLINE_HOUR_UTC, canal_mudo_hoy, posts_hoy_y_ayer
from publisher.poster import run_once
from scrapers.http import HttpClient
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


def _hour_env(name: str, default: int) -> int:
    """Una hora UTC (0-23). Fuera de rango vuelve al default, no revienta.

    `time(hour=...)` lanza con 24, y la guarda corre dentro del loop del
    publisher: un valor mal tipeado en el `.env` dejaría una excepción por poll
    durante toda la ventana en vez de un aviso.
    """
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        hour = int(raw)
    except ValueError:
        logger.warning("env inválida %s=%r — se usa %s", name, raw, default)
        return default
    if not 0 <= hour <= 23:
        logger.warning("%s=%r fuera de 0-23 — se usa %s", name, raw, default)
        return default
    return hour


async def revisar_canal_mudo(
    pool: asyncpg.Pool,
    *,
    now: datetime | None = None,
    ya_avisado: date | None = None,
) -> date | None:
    """Una vuelta de la guarda del canal. Devuelve el día ya avisado.

    `ya_avisado` es el día (calendario de Santiago) sobre el que esta guarda ya
    habló, y es la razón por la que esto no es un bucle de spam: la condición de
    "no publicó nada" se queda prendida hasta que salga el primer post, así que
    sin memoria el daemon mandaría un mensaje cada `PUBLISHER_POLL_SECONDS`
    durante las diez horas que quedan de ventana — ~120 mensajes, que se mutean
    el primer día y dejan la alerta inútil para cuando importe.

    La memoria es del proceso, no de la base: un reinicio del publisher puede
    repetir el aviso del día. Es el trade-off elegido a propósito — una tabla
    nueva para deduplicar un mensaje por día es más superficie que problema, y un
    aviso repetido después de un reinicio es ruido tolerable.

    El intento cuenta como aviso aunque la entrega falle. `send_alert` ya
    documenta por qué no se reintenta a ciegas: la alerta viaja por la misma red
    que todo lo demás, y si esa red está caída reintentar cada cinco minutos no
    la arregla. El texto queda en el log del publisher.
    """
    now = now or datetime.now(timezone.utc)
    async with pool.acquire() as conn:
        posts_hoy, posts_ayer = await posts_hoy_y_ayer(conn, ahora=now)

    texto = canal_mudo_hoy(
        posts_hoy=posts_hoy,
        posts_ayer=posts_ayer,
        ahora=now,
        deadline_hour_utc=_hour_env(
            "PUBLISHER_ALERTA_DEADLINE_HOUR_UTC", DEADLINE_HOUR_UTC
        ),
    )
    if texto is None:
        return ya_avisado

    dia, _ = ranker.local_day_bounds(now)
    if ya_avisado == dia.date():
        return ya_avisado

    await send_alert(texto)
    return dia.date()


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
    # Apagada por default, como el gate y como el publisher mismo: lo que habla
    # hacia afuera no se prende con un despliegue.
    guarda = _bool_env("PUBLISHER_ALERTA_CANAL_MUDO", default=False)
    interval = _float_env("PUBLISHER_POLL_SECONDS", 300.0)
    token = resolve_token()

    pool = await asyncpg.create_pool(database_url, min_size=1, max_size=2)
    client = TelegramClient(token)
    # Para verificar la disponibilidad del candidato en su ficha antes de publicar
    # (migración 30). Son 10-30 fetches por día: un cliente de vida larga, no uno
    # por vuelta, así el rate limit por host persiste entre ciclos.
    http = HttpClient()

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
        "publisher_daemon_started poll_seconds=%s enabled=%s bot_token=%s guarda=%s",
        interval,
        enabled,
        bool(token),
        guarda,
    )
    #: Día de Santiago sobre el que la guarda ya avisó. Ver `revisar_canal_mudo`.
    avisado: date | None = None
    try:
        while not stop_event.is_set():
            if enabled:
                try:
                    await run_once(pool, client, http=http)
                except Exception:
                    # Publicar es lo irreversible, pero fallar publicando no
                    # puede matar al daemon: el próximo ciclo reintenta y las
                    # reservas huérfanas ya se limpian solas en `publish_one`.
                    logger.exception("la vuelta del publisher falló")
                # Dentro de `enabled` a propósito: con el publisher apagado el
                # canal está mudo por decisión, no por falla, y avisar de eso
                # sería una alerta sobre la configuración que alguien eligió.
                if guarda:
                    try:
                        avisado = await revisar_canal_mudo(pool, ya_avisado=avisado)
                    except Exception:
                        # Una guarda que puede tumbar al publisher es peor que no
                        # tener guarda: el daño que vigila es media jornada muda,
                        # el que causaría es el día entero.
                        logger.exception("la guarda del canal falló")
            if once:
                break
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=interval)
            except asyncio.TimeoutError:
                pass
    finally:
        await http.aclose()
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
