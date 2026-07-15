"""Central activity logging.

``log_activity`` appends one row on the privileged (service_role, BYPASSRLS)
psycopg connection -- the only writer to the append-only audit table (staff have
read-only RLS; there is no insert policy). ``record_activity`` is the best-effort
helper routers call after a mutation: it never raises, so a logging hiccup can
never fail the mutation it is recording.
"""

from __future__ import annotations

import asyncio

from app.core.auth import CurrentUser
from app.db.database import privileged_connection
from app.logging_setup import get_logger
from app.schemas.activity import ActivityKind
from app.util.text import initials

logger = get_logger("app.activity")

# Append-only insert; the column list is a static literal and every value is a
# bound parameter. service_role BYPASSes the RLS policies but NOT the table's
# triggers, so this behaves exactly like the old admin-client insert.
_INSERT_ACTIVITY = (
    "insert into public.activity_log "
    "(actor_id, actor_name, actor_init, actor_color, kind, action, target, meta) "
    "values (%(actor_id)s, %(actor_name)s, %(actor_init)s, %(actor_color)s, "
    "%(kind)s, %(action)s, %(target)s, %(meta)s)"
)


def log_activity(
    *,
    actor_id: str | None,
    actor_name: str,
    actor_color: str,
    kind: str,
    action: str,
    target: str,
    meta: str | None = None,
) -> None:
    """Append one activity row via ``privileged_connection`` (blocking; offload
    with ``to_thread``). The actor identity is SNAPSHOTTED (name/init/color)."""
    with privileged_connection() as cur:
        cur.execute(
            _INSERT_ACTIVITY,
            {
                "actor_id": actor_id,
                "actor_name": actor_name,
                "actor_init": initials(actor_name),
                "actor_color": actor_color,
                "kind": kind,
                "action": action,
                "target": target,
                "meta": meta,
            },
        )


async def record_activity(
    actor: CurrentUser,
    *,
    kind: ActivityKind,
    action: str,
    target: str,
    meta: str | None = None,
) -> None:
    """Best-effort: record an actor's mutation. Never raises."""
    try:
        await asyncio.to_thread(
            log_activity,
            actor_id=actor.id,
            actor_name=actor.name,
            actor_color=actor.avatar_color,
            kind=kind,
            action=action,
            target=target,
            meta=meta,
        )
    except Exception:
        # Logging must never break the mutation it records (a missing/unreachable
        # privileged pool raises here and is swallowed to a warning).
        logger.warning("activity_log_failed", kind=kind, action=action)
