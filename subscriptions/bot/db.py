"""Acceso PostgreSQL del bot de onboarding mediante SQL puro y asyncpg.

PORT de `signalsTrading/onboarding_bot/db.py`. Las queries de identidad, trial,
verificación de email y entrega de invitaciones se conservan al pie de la letra:
son las que ya se pelearon con carreras, doble-tap y reuso de email. Lo único
reescrito es lo que hablaba de trading (`fetch_tier_stat_rows`) y el filtro por
`web_user_id`, que acá no existe.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

import asyncpg

from .email_verification import VerifyDecision, verify_code_attempt


@dataclass(frozen=True)
class TrialGrantResult:
    """Resultado de la concesión protegida por transacción."""

    granted: bool
    reason: str
    trial_used_at: datetime | None
    trial_ends_at: datetime | None


@dataclass(frozen=True)
class ConsumeResult:
    """Resultado durable de consumir un código bajo lock de fila."""

    decision: VerifyDecision
    attempts_remaining: int
    email_normalized: str | None

    @property
    def ok(self) -> bool:
        return self.decision.ok


async def fetch_active_tiers(conn: asyncpg.Connection) -> list[asyncpg.Record]:
    """Devuelve los tiers activos en un orden estable."""
    return await conn.fetch(
        """SELECT id, name, slug, description, telegram_channel_id
             FROM telegram_tiers
            WHERE is_active = TRUE
            ORDER BY id"""
    )


# Ventana rodante del track record del menú. En OfertasCL el track record de un
# canal no es win-rate: es lo que efectivamente se publicó ahí. Se agrega en SQL
# —a diferencia del origen, donde la métrica de trading estaba LOCKED en una
# única implementación Python que no se podía duplicar— porque acá el dato ya
# está calculado y persistido en `deal_candidates.discount_real`.
_TIER_STATS_QUERY = """
    SELECT tt.id                    AS tier_id,
           COUNT(*)                 AS posts,
           AVG(dc.discount_real)    AS avg_discount,
           MAX(dc.discount_real)    AS best_discount
      FROM telegram_tiers   AS tt
      JOIN deal_posts       AS dp ON dp.tier_id = tt.id
                                 AND dp.posted_at >= NOW() - INTERVAL '90 days'
      JOIN deal_candidates  AS dc ON dc.id = dp.candidate_id
     WHERE tt.is_active = TRUE
     GROUP BY tt.id
     ORDER BY tt.id
"""


async def fetch_tier_stat_rows(conn: asyncpg.Connection) -> list[asyncpg.Record]:
    """Ofertas publicadas por cada tier activo en los últimos 90 días.

    Un tier sin publicaciones en la ventana simplemente no aparece: el menú lo
    muestra por su estado en vez de inventarle métricas.
    """
    return await conn.fetch(_TIER_STATS_QUERY)


async def fetch_memberships(
    conn: asyncpg.Connection,
    user_id: int,
) -> list[asyncpg.Record]:
    """Devuelve únicamente las membresías del usuario indicado."""
    return await conn.fetch(
        """SELECT tier_id, status, channel_state, trial_ends_at
             FROM telegram_memberships
            WHERE telegram_user_id = $1
            ORDER BY tier_id""",
        user_id,
    )


async def fetch_identity(
    conn: asyncpg.Connection,
    user_id: int,
) -> asyncpg.Record | None:
    """Carga los datos de identidad necesarios para evaluar el trial."""
    return await conn.fetchrow(
        """SELECT telegram_user_id, telegram_username, email, email_normalized,
                  trial_used_at, source_ref
             FROM telegram_subscribers
            WHERE telegram_user_id = $1""",
        user_id,
    )


async def find_trial_owner_by_email(
    conn: asyncpg.Connection,
    email_normalized: str,
) -> asyncpg.Record | None:
    """Busca primero una identidad que ya usó el email canónico para trial."""
    return await conn.fetchrow(
        """SELECT telegram_user_id AS user_id, trial_used_at
             FROM telegram_subscribers
            WHERE email_normalized = $1
            ORDER BY trial_used_at DESC NULLS LAST, telegram_user_id
            LIMIT 1""",
        email_normalized,
    )


async def fetch_active_tier(
    conn: asyncpg.Connection,
    tier_id: int,
) -> asyncpg.Record | None:
    """Resuelve un callback únicamente contra un tier todavía activo."""
    return await conn.fetchrow(
        """SELECT id, name, slug
             FROM telegram_tiers
            WHERE id = $1 AND is_active = TRUE""",
        tier_id,
    )


async def fetch_active_plans(
    conn: asyncpg.Connection,
    tier_id: int,
) -> list[asyncpg.Record]:
    """Devuelve los planes PayPal pagables del tier en orden de duración."""
    return await conn.fetch(
        """SELECT p.id, p.tier_id, p.period, p.price_usd, p.paypal_plan_id
             FROM telegram_tier_plans AS p
             JOIN telegram_tiers AS t ON t.id = p.tier_id
            WHERE p.tier_id = $1
              AND p.is_active = TRUE
              AND t.is_active = TRUE
              AND p.paypal_plan_id IS NOT NULL
              AND BTRIM(p.paypal_plan_id) <> ''
              AND p.price_usd > 0
            ORDER BY CASE p.period
                         WHEN 'weekly' THEN 0
                         WHEN 'monthly' THEN 1
                         WHEN 'quarterly' THEN 2
                         WHEN 'semiannual' THEN 3
                         WHEN 'annual' THEN 4
                         ELSE 5
                     END,
                     p.id""",
        tier_id,
    )


async def upsert_identity(
    conn: asyncpg.Connection,
    user_id: int,
    username: str | None,
    ref: str | None,
) -> asyncpg.Record:
    """Registra la identidad y conserva la primera atribución no vacía.

    Telegram permite cambiar o quitar el username, por eso siempre se refleja
    el valor actual. ``source_ref`` solo se completa si todavía es NULL.
    """
    row = await conn.fetchrow(
        """INSERT INTO telegram_subscribers
                    (telegram_user_id, telegram_username, source_ref)
             VALUES ($1, $2, $3)
             ON CONFLICT (telegram_user_id) DO UPDATE
                 SET telegram_username = EXCLUDED.telegram_username,
                     source_ref = COALESCE(
                         telegram_subscribers.source_ref,
                         EXCLUDED.source_ref
                     ),
                     updated_at = NOW()
         RETURNING telegram_user_id, telegram_username, email_normalized,
                   trial_used_at, source_ref""",
        user_id,
        username,
        ref,
    )
    if row is None:  # pragma: no cover - INSERT ... RETURNING siempre retorna.
        raise RuntimeError("No se pudo registrar la identidad de Telegram")
    return row


async def create_email_verification(
    conn: asyncpg.Connection,
    user_id: int,
    email_normalized: str,
    code_hash: str,
    expires_at: datetime,
) -> None:
    """Crea o reemplaza el único código pendiente de una identidad."""
    await conn.execute(
        """INSERT INTO telegram_email_verifications
                    (telegram_user_id, email_normalized, code_hash, expires_at)
             VALUES ($1, $2, $3, $4)
             ON CONFLICT (telegram_user_id) DO UPDATE
                 SET email_normalized = EXCLUDED.email_normalized,
                     code_hash = EXCLUDED.code_hash,
                     expires_at = EXCLUDED.expires_at,
                     attempts = 0,
                     created_at = NOW(),
                     consumed_at = NULL""",
        user_id,
        email_normalized,
        code_hash,
        expires_at,
    )


async def consume_email_verification(
    conn: asyncpg.Connection,
    user_id: int,
    submitted_code: str,
    *,
    max_attempts: int,
    now: datetime,
) -> ConsumeResult:
    """Consume un código e identifica el email en una transacción serializada."""
    if max_attempts <= 0:
        raise ValueError("max_attempts debe ser mayor que cero")

    async with conn.transaction():
        row = await conn.fetchrow(
            """SELECT email_normalized, code_hash, expires_at, attempts, consumed_at
                 FROM telegram_email_verifications
                WHERE telegram_user_id = $1
                FOR UPDATE""",
            user_id,
        )
        if row is None:
            return ConsumeResult(VerifyDecision("expired"), 0, None)

        decision = verify_code_attempt(
            submitted_code=submitted_code,
            stored_hash=row["code_hash"],
            expires_at=row["expires_at"],
            attempts=row["attempts"],
            consumed_at=row["consumed_at"],
            max_attempts=max_attempts,
            now=now,
        )
        attempts_remaining = max(0, max_attempts - row["attempts"])

        if decision.reason == "mismatch":
            attempts = await conn.fetchval(
                """UPDATE telegram_email_verifications
                      SET attempts = attempts + 1
                    WHERE telegram_user_id = $1
                RETURNING attempts""",
                user_id,
            )
            if attempts is None:  # pragma: no cover - fila bloqueada arriba.
                raise RuntimeError("La verificación desapareció durante el consumo")
            attempts_remaining = max(0, max_attempts - attempts)
            if attempts_remaining == 0:
                decision = VerifyDecision("too_many_attempts")

        if decision.ok:
            consumed_at = await conn.fetchval(
                """UPDATE telegram_email_verifications
                      SET consumed_at = $2
                    WHERE telegram_user_id = $1
                RETURNING consumed_at""",
                user_id,
                now,
            )
            verified_at = await conn.fetchval(
                """UPDATE telegram_subscribers
                      SET email_verified_at = $2,
                          updated_at = NOW()
                    WHERE telegram_user_id = $1
                RETURNING email_verified_at""",
                user_id,
                now,
            )
            if consumed_at is None or verified_at is None:  # pragma: no cover
                raise RuntimeError("No se pudo persistir la verificación de email")

        return ConsumeResult(
            decision,
            attempts_remaining,
            row["email_normalized"],
        )


async def grant_trial(
    conn: asyncpg.Connection,
    user_id: int,
    tier_id: int,
    email: str,
    email_normalized: str,
    source_ref: str | None,
    trial_days: int,
) -> TrialGrantResult:
    """Concede un único trial global de forma transaccional e idempotente.

    El advisory lock serializa cuentas distintas que intentan usar a la vez la
    misma clave de email. El lock de identidad impide que un doble tap extienda
    ``trial_ends_at``. Una membresía activa/trialing nunca se rebaja.
    """
    if trial_days <= 0:
        raise ValueError("trial_days debe ser mayor que cero")

    async with conn.transaction():
        await conn.fetchval(
            "SELECT pg_advisory_xact_lock(hashtextextended($1::text, 0))",
            email_normalized,
        )
        await conn.execute(
            """INSERT INTO telegram_subscribers
                        (telegram_user_id, source_ref)
                 VALUES ($1, $2)
                 ON CONFLICT (telegram_user_id) DO NOTHING""",
            user_id,
            source_ref,
        )
        identity = await conn.fetchrow(
            """SELECT trial_used_at
                 FROM telegram_subscribers
                WHERE telegram_user_id = $1
                FOR UPDATE""",
            user_id,
        )
        if identity is None:  # pragma: no cover - protegido por el INSERT.
            raise RuntimeError("No se pudo bloquear la identidad de Telegram")

        membership = await conn.fetchrow(
            """SELECT status, trial_ends_at
                 FROM telegram_memberships
                WHERE telegram_user_id = $1 AND tier_id = $2
                FOR UPDATE""",
            user_id,
            tier_id,
        )
        if identity["trial_used_at"] is not None:
            return TrialGrantResult(
                granted=False,
                reason="already_used",
                trial_used_at=identity["trial_used_at"],
                trial_ends_at=(membership["trial_ends_at"] if membership else None),
            )

        reused = await conn.fetchval(
            """SELECT EXISTS (
                   SELECT 1
                     FROM telegram_subscribers
                    WHERE email_normalized = $1
                      AND telegram_user_id <> $2
                      AND trial_used_at IS NOT NULL
               )""",
            email_normalized,
            user_id,
        )
        if reused:
            return TrialGrantResult(False, "email_reused", None, None)

        if membership and membership["status"] in {"active", "trialing"}:
            return TrialGrantResult(
                granted=False,
                reason="membership_exists",
                trial_used_at=None,
                trial_ends_at=membership["trial_ends_at"],
            )

        updated_identity = await conn.fetchrow(
            """UPDATE telegram_subscribers
                  SET email = $2,
                      email_normalized = $3,
                      trial_used_at = COALESCE(trial_used_at, NOW()),
                      source_ref = COALESCE(source_ref, $4),
                      updated_at = NOW()
                WHERE telegram_user_id = $1
            RETURNING trial_used_at""",
            user_id,
            email,
            email_normalized,
            source_ref,
        )
        granted_membership = await conn.fetchrow(
            """INSERT INTO telegram_memberships
                        (telegram_user_id, tier_id, status, channel_state,
                         trial_ends_at, source_ref)
                 VALUES ($1, $2, 'trialing', 'none',
                         NOW() + ($4::integer * INTERVAL '1 day'), $3)
                 ON CONFLICT (telegram_user_id, tier_id) DO UPDATE
                     SET status = 'trialing',
                         channel_state = 'none',
                         trial_ends_at = EXCLUDED.trial_ends_at,
                         source_ref = COALESCE(
                             telegram_memberships.source_ref,
                             EXCLUDED.source_ref
                         ),
                         updated_at = NOW()
             RETURNING trial_ends_at""",
            user_id,
            tier_id,
            source_ref,
            trial_days,
        )
        if updated_identity is None or granted_membership is None:  # pragma: no cover
            raise RuntimeError("No se pudo persistir el trial")
        return TrialGrantResult(
            granted=True,
            reason="ok",
            trial_used_at=updated_identity["trial_used_at"],
            trial_ends_at=granted_membership["trial_ends_at"],
        )


async def fetch_pending_dm_deliveries(
    conn: asyncpg.Connection,
    limit: int,
) -> list[asyncpg.Record]:
    """Carga invitaciones pendientes que el bot puede entregar por DM.

    El origen filtraba por ``telegram_subscribers.web_user_id IS NULL`` para
    dejarle las membresías nacidas en el checkout web a la card del dashboard.
    Acá no hay funnel web: toda identidad nace en el bot, así que toda invitación
    pendiente es entregable por DM. Deliberadamente NO se filtra por
    ``source_ref``: quien abre el bot directo, sin deep-link de campaña, también
    tiene que recibir su link.
    """
    if limit <= 0:
        raise ValueError("limit debe ser mayor que cero")
    return await conn.fetch(
        """SELECT m.telegram_user_id, m.tier_id, m.invite_link,
                  t.slug AS tier_slug
             FROM telegram_memberships AS m
             JOIN telegram_tiers AS t ON t.id = m.tier_id
            WHERE m.channel_state = 'invited'
              AND m.invite_link IS NOT NULL
              AND m.invite_delivered_at IS NULL
            ORDER BY m.updated_at, m.telegram_user_id, m.tier_id
            LIMIT $1""",
        limit,
    )


async def mark_dm_delivered(
    conn: asyncpg.Connection,
    user_id: int,
    tier_id: int,
) -> None:
    """Marca la entrega una sola vez para que no vuelva a seleccionarse."""
    await conn.execute(
        """UPDATE telegram_memberships
              SET invite_delivered_at = NOW(),
                  updated_at = NOW()
            WHERE telegram_user_id = $1
              AND tier_id = $2
              AND invite_delivered_at IS NULL""",
        user_id,
        tier_id,
    )


async def fetch_arrivals_by_ref(
    conn: asyncpg.Connection,
) -> list[asyncpg.Record]:
    """Cuenta las identidades (llegadas) agrupadas por su ref de atribución.

    ``source_ref`` es la primera atribución que ganó (COALESCE en el upsert),
    así que agrupar la tabla de identidad da las personas únicas por campaña.
    Las llegadas sin ref se agregan bajo la etiqueta ``(sin ref)``.
    """
    return await conn.fetch(
        """SELECT COALESCE(source_ref, '(sin ref)') AS ref,
                  COUNT(*) AS arrivals
             FROM telegram_subscribers
            GROUP BY COALESCE(source_ref, '(sin ref)')
            ORDER BY ref"""
    )


async def fetch_conversion_by_ref_tier(
    conn: asyncpg.Connection,
) -> list[asyncpg.Record]:
    """Deriva el embudo trials/pagos/activos por (ref, tier) de las membresías.

    ``trial_ends_at IS NOT NULL`` marca de forma durable a quien alguna vez tuvo
    trial (sobrevive la conversión a pago). ``paypal_subscription_id`` marca el
    pago, y ``status = 'active'`` la membresía vigente. Con D-4a (un trial global
    por persona) los trials por tier ≈ personas distintas.
    """
    return await conn.fetch(
        """SELECT COALESCE(m.source_ref, '(sin ref)') AS ref,
                  m.tier_id,
                  t.slug AS tier_slug,
                  COUNT(*) FILTER (WHERE m.trial_ends_at IS NOT NULL) AS trials,
                  COUNT(*) FILTER (
                      WHERE m.paypal_subscription_id IS NOT NULL
                  ) AS paid,
                  COUNT(*) FILTER (WHERE m.status = 'active') AS active
             FROM telegram_memberships AS m
             JOIN telegram_tiers AS t ON t.id = m.tier_id
            GROUP BY COALESCE(m.source_ref, '(sin ref)'), m.tier_id, t.slug
            ORDER BY ref, m.tier_id"""
    )


def memberships_by_tier_id(
    memberships: list[asyncpg.Record],
) -> dict[int, Any]:
    """Indexa filas DB por tier sin introducir decisiones de negocio."""
    return {int(row["tier_id"]): row for row in memberships}
