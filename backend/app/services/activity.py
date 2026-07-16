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
# triggers, so this behaves exactly like the old admin-client insert -- and the
# AFTER INSERT trigger (0013) coalesces any linked entity into context_dirty.
# entity_type is cast to the enum so a plain text bind assigns cleanly; a NULL
# (unlinked event) casts to NULL and the trigger simply ignores it.
_INSERT_ACTIVITY = (
    "insert into public.activity_log "
    "(actor_id, actor_name, actor_init, actor_color, kind, action, target, meta, "
    "entity_type, entity_id) "
    "values (%(actor_id)s, %(actor_name)s, %(actor_init)s, %(actor_color)s, "
    "%(kind)s, %(action)s, %(target)s, %(meta)s, "
    "%(entity_type)s::public.context_entity, %(entity_id)s)"
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
    entity_type: str | None = None,
    entity_id: str | None = None,
) -> None:
    """Append one activity row via ``privileged_connection`` (blocking; offload
    with ``to_thread``). The actor identity is SNAPSHOTTED (name/init/color).

    ``entity_type``/``entity_id`` optionally LINK the event to the context entity
    (client|user|site) it mutated; the AFTER INSERT trigger then coalesces that
    entity into the debounced ``context_dirty`` queue. Omit both for an unlinked
    event (the trigger ignores it)."""
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
                "entity_type": entity_type,
                "entity_id": entity_id,
            },
        )


async def record_activity(
    actor: CurrentUser,
    *,
    kind: ActivityKind,
    action: str,
    target: str,
    meta: str | None = None,
    entity_type: str | None = None,
    entity_id: str | None = None,
) -> None:
    """Best-effort: record an actor's mutation. Never raises.

    When the caller holds the concrete id of the entity the action mutated, it
    passes ``entity_type`` (client|user|site) + ``entity_id`` so the context
    layer can keep that entity's AI-memory fresh; an unlinked event omits both.
    A bad/unknown entity can never break the mutation being recorded."""
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
            entity_type=entity_type,
            entity_id=entity_id,
        )
    except Exception:
        # Logging must never break the mutation it records (a missing/unreachable
        # privileged pool raises here and is swallowed to a warning).
        logger.warning("activity_log_failed", kind=kind, action=action)
