"""Reconciler de membresía de los canales VIP de OfertasCL.

PORT de `signalsTrading/telegram_signals/membership.py`. La matriz de
transiciones y el manejo de errores se conservan intactos: es el código que ya
sobrevivió a fallos de Bot API, dobles réplicas y reactivaciones. Lo único que
cambia es el nombre del logger y el del env var del master-switch.

Cierra la brecha entre el estado DESEADO (`telegram_memberships.status`, que
mueve PayPal / el bot de onboarding) y el estado APLICADO en Telegram
(`channel_state`). Corre dentro del daemon, tras el poster, de forma idempotente
y reintentable: el webhook y el bot solo escriben DB; el efecto sobre Telegram
(invite / kick) lo ejecuta este worker.

Multi-membresía (F4): la unidad de iteración es la MEMBRESÍA `(user, tier)`, no
el suscriptor. Una persona puede estar en varios canales a la vez; cada membresía
es su propia fila independiente con su `channel_id`, `status` y `channel_state`.
`decide_action` (la matriz de transiciones) NO cambia respecto a F2 — solo cambia
la clave sobre la que opera y la tabla que escribe (`telegram_memberships`).

Tabla de transiciones (docs/plans/telegram-signals-v1.F2-membership-gate.md §4):

| status deseado     | channel_state          | acción                                   |
|--------------------|------------------------|------------------------------------------|
| active / trialing  | none / kicked          | (unban si kicked) + invite → invited     |
| active / trialing  | invited / member       | limpiar gracia pendiente (si la hubiera) |
| past_due           | invited / member       | fija grace_until; vencida → kick         |
| canceled / expired | invited / member       | kick (ban + unban) → kicked              |
| (resto)            | (resto)                | no-op                                    |

Reglas:
- Gate efectivo = AND(env global `GATE_ENABLED`,
  `telegram_tiers.gate_enabled`). El env es el master-switch de seguridad (si
  está apagado el reconciler es inerte, no importa la DB); la columna es el
  control fino por-canal que el owner maneja desde la seed de canales.
- Sweeper de trial (§5.4): antes de reconciliar, las membresías `trialing` con
  `trial_ends_at <= now` pasan a `expired` (solo DB); el gate las kickea en el
  mismo ciclo. Sin sweeper, un trial libre nunca vencería.
- Idempotente: recomputa el estado deseado cada ciclo contra `channel_state`;
  repetir un ciclo no duplica invites ni kicks.
- Un fallo de Bot API NO persiste `channel_state` (queda para reintentar) y se
  registra en `gate_last_error`. Igual patrón que el poster.
- Nunca promueve `invited`→`member` por su cuenta: `invited` ya cuenta como
  acceso concedido y el kick funciona igual sobre un miembro real.
- Serializa por `telegram_user_id` con advisory lock (tolera dos réplicas). El
  lock por-usuario cubre todas sus membresías: over-serializa dos tiers del
  mismo usuario (irrelevante al volumen actual), nunca dos usuarios distintos.
- `pending`/`grace` NO están manejados (PayPal no los usa aún): no-op explícito.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import logging
from typing import Callable, Protocol

import asyncpg


logger = logging.getLogger("ofertascl.gate")


class MembershipGateClient(Protocol):
    async def create_chat_invite_link(
        self,
        chat_id: int | None,
        *,
        member_limit: int = 1,
        expire_date: datetime | int | None = None,
    ) -> str | None: ...

    async def ban_chat_member(
        self, chat_id: int | None, user_id: int | None
    ) -> bool: ...

    async def unban_chat_member(
        self, chat_id: int | None, user_id: int | None
    ) -> bool: ...


_ACTION_GRANT = "grant"
_ACTION_REVOKE = "revoke"
_ACTION_START_GRACE = "start_grace"
_ACTION_CLEAR_GRACE = "clear_grace"
_ACTION_NOOP = "noop"

_GRANT_STATUSES = ("active", "trialing")
_REVOKE_STATUSES = ("canceled", "expired")
_ACCESS_STATES = ("invited", "member")

# Solo estas acciones tocan Bot API → exigen un canal resuelto.
_TELEGRAM_ACTIONS = (_ACTION_GRANT, _ACTION_REVOKE)

# Sweeper de trial: trialing vencido → expired (solo DB). El gate lo kickea
# en el mismo ciclo al recomputar la acción sobre el nuevo status.
_EXPIRE_TRIALS_QUERY = """
    UPDATE telegram_memberships
       SET status = 'expired', updated_at = NOW()
     WHERE status = 'trialing'
       AND trial_ends_at IS NOT NULL
       AND trial_ends_at <= $1
"""

# Candidatos que PODRÍAN necesitar acción; la decisión final se hace en Python
# con `now` (la gracia depende del reloj). Los ya asentados no se traen.
#
# Gate por-canal: sólo entran tiers con `gate_enabled = TRUE` (el toggle que el
# owner maneja desde la seed de canales). El opt-in global sigue siendo el
# master-switch: `enabled=False` (env GATE_ENABLED) deja este
# reconciler inerte sin importar la columna. Efectivo = AND(env, tier).
_CANDIDATES_QUERY = """
    SELECT m.telegram_user_id, m.tier_id
      FROM telegram_memberships m
      JOIN telegram_tiers t
        ON t.id = m.tier_id
       AND t.gate_enabled = TRUE
     WHERE (
             (m.status = ANY($1::varchar[])
              AND (m.channel_state IN ('none', 'kicked')
                   OR m.grace_until IS NOT NULL))
          OR (m.status = 'past_due'
              AND m.channel_state IN ('invited', 'member'))
          OR (m.status = ANY($2::varchar[])
              AND m.channel_state IN ('invited', 'member'))
       )
     ORDER BY m.telegram_user_id, m.tier_id
"""

_CURRENT_QUERY = """
    SELECT m.telegram_user_id, m.tier_id, m.status, m.channel_state,
           m.grace_until, m.access_granted_at,
           t.telegram_channel_id, t.slug AS tier_slug,
           COALESCE(t.gate_enabled, FALSE) AS gate_enabled
      FROM telegram_memberships m
      LEFT JOIN telegram_tiers t ON t.id = m.tier_id
     WHERE m.telegram_user_id = $1 AND m.tier_id = $2
"""


def decide_action(
    status: str,
    channel_state: str,
    grace_until: datetime | None,
    now: datetime,
) -> str:
    """Función pura estado deseado → acción. Testeable sin DB ni cliente."""
    if status in _GRANT_STATUSES:
        if channel_state in ("none", "kicked"):
            return _ACTION_GRANT
        if grace_until is not None:  # volvió a activo: limpiar gracia pendiente
            return _ACTION_CLEAR_GRACE
        return _ACTION_NOOP
    if status == "past_due":
        if channel_state in _ACCESS_STATES:
            if grace_until is None:
                return _ACTION_START_GRACE
            if now >= grace_until:
                return _ACTION_REVOKE
        return _ACTION_NOOP
    if status in _REVOKE_STATUSES:
        if channel_state in _ACCESS_STATES:
            return _ACTION_REVOKE
        return _ACTION_NOOP
    return _ACTION_NOOP


class MembershipReconciler:
    def __init__(
        self,
        pool: asyncpg.Pool,
        client: MembershipGateClient,
        *,
        grace_days: float = 3.0,
        invite_ttl_hours: float = 24.0,
        enabled: bool = True,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._pool = pool
        self._client = client
        self._grace_days = grace_days
        self._invite_ttl_hours = invite_ttl_hours
        self._enabled = enabled
        self._now = now or (lambda: datetime.now(timezone.utc))

    async def _expire_trials(self, now: datetime) -> None:
        async with self._pool.acquire() as connection:
            await connection.execute(_EXPIRE_TRIALS_QUERY, now)

    async def _candidate_keys(self) -> list[tuple[int, int]]:
        async with self._pool.acquire() as connection:
            rows = await connection.fetch(
                _CANDIDATES_QUERY,
                list(_GRANT_STATUSES),
                list(_REVOKE_STATUSES),
            )
        return [(int(row["telegram_user_id"]), int(row["tier_id"])) for row in rows]

    async def run_once(self) -> int:
        """Reconcilia candidatos serialmente; devuelve membresías con acción
        aplicada. Inerte (0) si el gate está deshabilitado."""
        if not self._enabled:
            return 0
        now = self._now()
        try:
            await self._expire_trials(now)
        except Exception as exc:  # noqa: BLE001 — el loop sobrevive a DB transitoria
            logger.exception("membership_expire_trials_failed error=%s", exc)
        try:
            candidate_keys = await self._candidate_keys()
        except Exception as exc:  # noqa: BLE001 — el loop sobrevive a DB transitoria
            logger.exception("membership_candidate_query_failed error=%s", exc)
            return 0

        reconciled = 0
        for user_id, tier_id in candidate_keys:
            locked = False
            try:
                async with self._pool.acquire() as connection:
                    # Un solo lock bigint por usuario cubre el HTTP + UPDATE de
                    # todas sus membresías, y tolera una segunda réplica.
                    locked = bool(
                        await connection.fetchval(
                            "SELECT pg_try_advisory_lock($1)", user_id
                        )
                    )
                    if not locked:
                        continue
                    try:
                        if await self._reconcile_one(connection, user_id, tier_id):
                            reconciled += 1
                    finally:
                        await connection.execute(
                            "SELECT pg_advisory_unlock($1)", user_id
                        )
                        locked = False
            except Exception as exc:  # noqa: BLE001 — una membresía no frena el barrido
                logger.exception(
                    "membership_failed user=%s tier=%s error=%s",
                    user_id,
                    tier_id,
                    exc,
                )
            finally:
                if locked:
                    logger.error(
                        "membership_advisory_lock_release_uncertain user=%s tier=%s",
                        user_id,
                        tier_id,
                    )
        return reconciled

    async def _reconcile_one(
        self, conn: asyncpg.Connection, user_id: int, tier_id: int
    ) -> bool:
        # Re-leer bajo el lock: el webhook pudo mover `status` entre el query de
        # candidatos y ahora (evita invitar a quien justo canceló, y viceversa).
        current = await conn.fetchrow(_CURRENT_QUERY, user_id, tier_id)
        if current is None:
            return False
        # Re-chequear el gate del canal bajo el lock: el owner pudo apagarlo
        # desde el panel entre el query de candidatos y ahora.
        if not current["gate_enabled"]:
            return False
        now = self._now()
        action = decide_action(
            current["status"], current["channel_state"], current["grace_until"], now
        )
        if action == _ACTION_NOOP:
            return False
        if action in _TELEGRAM_ACTIONS and current["telegram_channel_id"] is None:
            logger.warning(
                "membership_channel_unresolved user=%s tier=%s status=%s",
                user_id,
                tier_id,
                current["status"],
            )
            return False

        applied = await self._dispatch(conn, action, current, now)
        if applied:
            logger.info(
                "membership_reconciled user=%s tier=%s action=%s status=%s state=%s",
                user_id,
                tier_id,
                action,
                current["status"],
                current["channel_state"],
            )
        return applied

    async def _dispatch(
        self,
        conn: asyncpg.Connection,
        action: str,
        row: asyncpg.Record,
        now: datetime,
    ) -> bool:
        if action == _ACTION_GRANT:
            return await self._apply_grant(conn, row, now)
        if action == _ACTION_REVOKE:
            return await self._apply_revoke(conn, row, now)
        if action == _ACTION_START_GRACE:
            return await self._apply_start_grace(conn, row, now)
        if action == _ACTION_CLEAR_GRACE:
            return await self._apply_clear_grace(conn, row)
        return False

    async def _apply_grant(
        self, conn: asyncpg.Connection, row: asyncpg.Record, now: datetime
    ) -> bool:
        channel_id = row["telegram_channel_id"]
        user_id = row["telegram_user_id"]
        tier_id = row["tier_id"]
        # Si venía expulsado, levantar el ban ANTES del invite: un baneado no
        # puede usar el link aunque exista. Si el unban falla, no invitamos —
        # se reintenta el próximo ciclo (no persistimos channel_state).
        if row["channel_state"] == "kicked":
            if not await self._client.unban_chat_member(channel_id, user_id):
                await self._record_error(conn, user_id, tier_id, "unban_failed")
                return False
        expire_at = now + timedelta(hours=self._invite_ttl_hours)
        link = await self._client.create_chat_invite_link(
            channel_id, member_limit=1, expire_date=expire_at
        )
        if link is None:
            await self._record_error(conn, user_id, tier_id, "invite_failed")
            return False
        await conn.execute(
            """UPDATE telegram_memberships
                  SET channel_state = 'invited',
                      invite_link = $3,
                      invite_expires_at = $4,
                      access_granted_at = COALESCE(access_granted_at, $5),
                      grace_until = NULL,
                      gate_last_error = NULL,
                      updated_at = NOW()
                WHERE telegram_user_id = $1 AND tier_id = $2""",
            user_id,
            tier_id,
            link,
            expire_at,
            now,
        )
        return True

    async def _apply_revoke(
        self, conn: asyncpg.Connection, row: asyncpg.Record, now: datetime
    ) -> bool:
        channel_id = row["telegram_channel_id"]
        user_id = row["telegram_user_id"]
        tier_id = row["tier_id"]
        if not await self._client.ban_chat_member(channel_id, user_id):
            await self._record_error(conn, user_id, tier_id, "ban_failed")
            return False
        # Kick = ban + unban (no ban permanente): destrabar para permitir
        # re-unirse tras una futura reactivación. Best-effort — si el unban
        # falla, el usuario queda expulsado igual (objetivo logrado) y el GRANT
        # de una reactivación (kicked→active) vuelve a hacer unban.
        await self._client.unban_chat_member(channel_id, user_id)
        await conn.execute(
            """UPDATE telegram_memberships
                  SET channel_state = 'kicked',
                      access_revoked_at = $3,
                      grace_until = NULL,
                      gate_last_error = NULL,
                      updated_at = NOW()
                WHERE telegram_user_id = $1 AND tier_id = $2""",
            user_id,
            tier_id,
            now,
        )
        return True

    async def _apply_start_grace(
        self, conn: asyncpg.Connection, row: asyncpg.Record, now: datetime
    ) -> bool:
        # Solo DB: no toca Bot API. Mantiene el acceso hasta que venza la gracia.
        grace_until = now + timedelta(days=self._grace_days)
        await conn.execute(
            """UPDATE telegram_memberships
                  SET grace_until = $3, updated_at = NOW()
                WHERE telegram_user_id = $1 AND tier_id = $2""",
            row["telegram_user_id"],
            row["tier_id"],
            grace_until,
        )
        return True

    async def _apply_clear_grace(
        self, conn: asyncpg.Connection, row: asyncpg.Record
    ) -> bool:
        # Solo DB: volvió a activo, la gracia pendiente ya no aplica.
        await conn.execute(
            """UPDATE telegram_memberships
                  SET grace_until = NULL, updated_at = NOW()
                WHERE telegram_user_id = $1 AND tier_id = $2""",
            row["telegram_user_id"],
            row["tier_id"],
        )
        return True

    async def _record_error(
        self, conn: asyncpg.Connection, user_id: int, tier_id: int, error: str
    ) -> None:
        await conn.execute(
            """UPDATE telegram_memberships
                  SET gate_last_error = $3, updated_at = NOW()
                WHERE telegram_user_id = $1 AND tier_id = $2""",
            user_id,
            tier_id,
            error,
        )
