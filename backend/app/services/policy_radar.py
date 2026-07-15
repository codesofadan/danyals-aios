"""Policy Radar closed-loop APPLY (R3): an applied recommendation -> an OVERLAY.

THE HARD RULE (Part 3): the ``danyals-audit-system`` ENGINE is NEVER mutated.
Applying a recommendation does NOT edit the engine's check set, its config, or the
content generator; it writes a SEPARATE ``audit_overlay`` row (migration 0027) that
the PRESENTATION layer lays ON TOP of the untouched engine output. This module is
the ONLY writer of that closed loop and it touches NOTHING outside Postgres - it
opens no file, spawns no subprocess, and imports nothing from the engine adapter,
so no path under the engine dir is ever reachable from here. Deleting every overlay
row (or flipping ``active=false``) returns the platform to pure-engine behaviour.

``overlay_row_from_rec`` is the PURE mapping (a recommendation dict -> an overlay
insert row dict); ``apply_recommendation`` offloads the RLS-scoped insert. The
human CONFIRM that authorises this is the router's ``require_role('owner', 'admin',
'manager')`` on the transition route - this module assumes the caller already
passed it, and the overlay INSERT's RLS re-checks the SAME lead set at the DB.
"""

from __future__ import annotations

import asyncio
from typing import Any, get_args

from app.core.auth import CurrentUser
from app.db.policy_repo import PolicyRepo
from app.schemas.policy import Region, TargetModule

# The valid enum label sets (derived from the locked unions, so a drift can't slip
# an invalid label into an audit_overlay enum column).
_TARGETS: frozenset[str] = frozenset(get_args(TargetModule))
_REGIONS: frozenset[str] = frozenset(get_args(Region))

# Only an AUDIT overlay adds a weighted check; a content/portal overlay is a pure
# advisory (weight 0). The delta is intentionally small - the overlay NUDGES the
# untouched engine output, it does not overwrite it.
_AUDIT_TARGET = "audit"
_AUDIT_CHECK_WEIGHT = 1.0


def overlay_row_from_rec(rec: dict[str, Any], *, created_by: str | None) -> dict[str, Any]:
    """Map an APPLIED recommendation row to an ``audit_overlay`` insert row (pure).

    ``target_module`` routes the overlay (an audit check vs a content/portal
    advisory); ``region`` is copied through as a keyed axis; ``audit_type`` is
    ``""`` (applies to EVERY audit type) because a recommendation is not
    type-specific. ``kb_ref`` / ``id`` / ``action`` are snapshotted for
    traceability back to the KB finding. An audit overlay gets a small positive
    weight so the extra check counts; an advisory overlay gets 0. The rec's scope is
    stashed in ``payload`` so the shape can grow without a migration.
    """
    target = rec.get("target_module", "audit")
    if target not in _TARGETS:
        target = "audit"
    region = rec.get("region", "global")
    if region not in _REGIONS:
        region = "global"
    action = rec.get("action", "")
    return {
        "target_module": target,
        "audit_type": "",
        "region": region,
        "title": rec.get("title", ""),
        "guidance": action,
        "weight": _AUDIT_CHECK_WEIGHT if target == _AUDIT_TARGET else 0.0,
        "payload": {"scope": rec.get("scope", "global")},
        "source_kb_ref": rec.get("kb_ref", ""),
        "source_rec_id": str(rec.get("id", "")),
        "action": action,
        "version": 1,
        "active": True,
        "created_by": created_by,
    }


async def apply_recommendation(
    actor: CurrentUser, rec: dict[str, Any], repo: PolicyRepo
) -> dict[str, Any]:
    """Write the applied recommendation into the overlay - the R3 CLOSED LOOP.

    NEVER mutates the engine: it inserts ONE ``audit_overlay`` row via the
    RLS-scoped repo (the insert's RLS re-checks the lead set), off the event loop.
    Returns the inserted overlay row. The caller (the ``apply`` transition) has
    already enforced the human-confirm via ``require_role``.
    """
    row = overlay_row_from_rec(rec, created_by=actor.id)
    return await asyncio.to_thread(repo.insert_overlay, row)
