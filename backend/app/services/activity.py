"""Central activity logging.

``log_activity`` appends one row via the service_role client (the only writer to
the append-only audit table). ``record_activity`` is the best-effort helper
routers call after a mutation: it never raises, so a logging hiccup can never
fail the mutation it is recording.
"""

from __future__ import annotations

import asyncio

from supabase import Client

from app.core.auth import CurrentUser
from app.db.supabase import get_admin_client
from app.logging_setup import get_logger
from app.schemas.activity import ActivityKind
from app.util.text import initials

logger = get_logger("app.activity")


def log_activity(
    admin: Client,
    *,
    actor_id: str | None,
    actor_name: str,
    actor_color: str,
    kind: str,
    action: str,
    target: str,
    meta: str | None = None,
) -> None:
    """Append one activity row (blocking; offload with ``to_thread``)."""
    admin.table("activity_log").insert(
        {
            "actor_id": actor_id,
            "actor_name": actor_name,
            "actor_init": initials(actor_name),
            "actor_color": actor_color,
            "kind": kind,
            "action": action,
            "target": target,
            "meta": meta,
        }
    ).execute()


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
        admin = get_admin_client()
        await asyncio.to_thread(
            log_activity,
            admin,
            actor_id=actor.id,
            actor_name=actor.name,
            actor_color=actor.avatar_color,
            kind=kind,
            action=action,
            target=target,
            meta=meta,
        )
    except Exception:
        # Logging must never break the mutation it records.
        logger.warning("activity_log_failed", kind=kind, action=action)
