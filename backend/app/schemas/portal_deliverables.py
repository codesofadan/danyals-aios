"""Client-portal deliverable response model in the frontend shape (``lib/client.ts``
``ClientDeliverable``).

``ClientDeliverableResponse`` mirrors ``ClientDeliverable`` EXACTLY - the 9 keys
``{id, title, kind, icon, period, date, size, status, requires}`` and nothing else.
``id`` is the deliverable uuid (a string); ``date`` is the humanized ``issued_at``
(or "In progress" while generating); ``size`` is the stored size label. The
server-only columns (``artifact_key`` / ``media_type`` / ``source_*`` /
``client_id``) are never exposed - the download endpoint resolves the artifact
server-side.

The ``kind``/``status`` ``Literal`` unions are pinned verbatim to the TS type (§3
enum fidelity) and mirror the DB enums (``deliverable_kind`` / ``deliverable_status``)
one-for-one.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel

from app.util.timefmt import format_date

# Unions verbatim from lib/client.ts (ClientDeliverable). Canonical: same value on
# the wire and in the DB enum, so no display mapping is needed.
DeliverableKind = Literal["Audit", "Monthly", "Content", "Backlinks", "Local"]
DeliverableStatus = Literal["ready", "generating"]

_KINDS: frozenset[str] = frozenset({"Audit", "Monthly", "Content", "Backlinks", "Local"})
_STATUSES: frozenset[str] = frozenset({"ready", "generating"})


class ClientDeliverableResponse(BaseModel):
    """One deliverable in the frontend ``ClientDeliverable`` shape - and ONLY those
    9 keys. ``date`` is the humanized ``issued_at`` ("Jul 03, 2026"), or
    "In progress" while the deliverable is still generating. No internal column
    (client_id, artifact_key, media_type, source_*, timestamps) is ever exposed.
    """

    id: str
    title: str
    kind: DeliverableKind
    icon: str
    period: str
    date: str
    size: str
    status: DeliverableStatus
    requires: str

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> ClientDeliverableResponse:
        kind = row.get("kind")
        status = row.get("status")
        status_v: DeliverableStatus = status if status in _STATUSES else "ready"
        # A generating deliverable has no issued_at yet - show the frontend's
        # "In progress" marker (matching the seed row in lib/client.ts).
        date = "In progress" if status_v == "generating" else format_date(row.get("issued_at"))
        return cls(
            id=str(row["id"]),
            title=row.get("title", ""),
            kind=kind if kind in _KINDS else "Audit",
            icon=row.get("icon", ""),
            period=row.get("period", ""),
            date=date,
            size=row.get("size_label", ""),
            status=status_v,
            requires=row.get("requires", ""),
        )
