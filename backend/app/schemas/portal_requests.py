"""Client-portal request models in the frontend shape (``lib/client.ts``
``ClientRequest``).

A "request" is a client-raised support ticket carrying a request KIND. The
``kind``/``status`` ``Literal`` unions are pinned verbatim to the TS types
``RequestKind`` / ``RequestStatus`` (§3 enum fidelity); ``status`` is already the
client-facing value (the ``portal_requests`` view maps the internal ``pending`` ->
``in_review``).

``ClientRequestResponse`` mirrors ``ClientRequest`` EXACTLY - the 7 keys ``{id,
kind, subject, detail, status, ago, reply}``. ``id`` is the public ``T-####`` code
(never the UUID); ``ago`` is the humanized time since ``opened_at``. The internal
``client_id`` is never exposed.

``PortalRequestCreate`` is the POST body: ``{kind, subject, detail}`` and NOTHING
else - the tenant is pinned server-side from the authenticated client, never taken
from the body (mirrors ``PortalAuditCreate``).
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from app.util.timefmt import relative_ago

# Unions verbatim from lib/client.ts (RequestKind / RequestStatus).
RequestKind = Literal["Report", "Access", "Support", "Feature", "Billing"]
RequestStatus = Literal["open", "in_review", "resolved"]

_KINDS: frozenset[str] = frozenset({"Report", "Access", "Support", "Feature", "Billing"})
_STATUSES: frozenset[str] = frozenset({"open", "in_review", "resolved"})


class PortalRequestCreate(BaseModel):
    """POST /portal/requests body: raise a request. ``client_id`` is pinned by the
    endpoint from the authenticated client (NOT part of this body); ``status`` always
    starts server-side. Only ``kind`` / ``subject`` / ``detail`` are client-supplied.
    """

    kind: RequestKind
    subject: str = Field(min_length=1)
    detail: str = ""


class ClientRequestResponse(BaseModel):
    """One request in the frontend ``ClientRequest`` shape - and ONLY those 7 keys.

    ``id`` is the public ``T-####`` code; ``ago`` is the relative time since
    ``opened_at`` ("2h ago"); ``reply`` is the latest admin reply (absent -> null).
    No internal column (UUID id, client_id, created_by, timestamps) is ever exposed.
    """

    id: str
    kind: RequestKind
    subject: str
    detail: str
    status: RequestStatus
    ago: str
    reply: str | None = None

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> ClientRequestResponse:
        kind = row.get("kind")
        status = row.get("status")
        reply = row.get("reply")
        return cls(
            id=str(row["code"]),
            kind=kind if kind in _KINDS else "Support",
            subject=row.get("subject", ""),
            detail=row.get("detail", ""),
            status=status if status in _STATUSES else "open",
            ago=relative_ago(row.get("opened_at"), empty="just now"),
            reply=str(reply) if reply else None,
        )
