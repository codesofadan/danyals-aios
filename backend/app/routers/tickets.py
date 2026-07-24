"""Support Tickets endpoints: the client-support ticket queue.

Reads require any provisioned staff (``view_reports``, which a portal client does
NOT hold - so clients are 403'd out of this namespace, mirroring tasks/audits);
creating a ticket and triaging its status require ``manage_clients`` (owner/admin/
manager) - matching the ``support_tickets`` RLS (staff select; lead manage) so the
app-layer 403 and the DB boundary agree. Responses are the frontend ``Ticket`` shape
(``lib/data.ts``); the internal ``client_id`` never leaks. Every mutation appends an
activity entry linked to the ticket's client so the context layer stays fresh.
"""

from __future__ import annotations

import asyncio
from html import escape as html_escape
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.core.auth import CurrentUser, require_perm
from app.core.pagination import PageDep
from app.db.clients_repo import ClientsRepoDep
from app.db.tickets_repo import TicketsRepoDep
from app.schemas.tickets import (
    TicketCreate,
    TicketResponse,
    TicketStatus,
    TicketStatusUpdate,
)
from app.services.activity import record_activity
from app.services.notifications import email_client

router = APIRouter(tags=["tickets"])

# Client-facing label for the internal ticket status (the portal maps pending ->
# in_review; the email uses the same client-facing wording).
_CLIENT_STATUS_LABEL: dict[str, str] = {
    "open": "open", "pending": "in review", "resolved": "resolved"
}

# All six staff roles hold view_reports; a portal client does NOT (mirrors
# tasks.py / milestones.py - clients are confined out of the staff namespace).
ViewReports = Annotated[CurrentUser, Depends(require_perm("view_reports"))]
# Triage = the manage_clients holders (owner/admin/manager) - matches the RLS.
ManageClients = Annotated[CurrentUser, Depends(require_perm("manage_clients"))]

_TICKET_NOT_FOUND = HTTPException(
    status_code=status.HTTP_404_NOT_FOUND, detail="Ticket not found"
)


@router.get("/tickets", response_model=list[TicketResponse])
async def list_tickets(
    repo: TicketsRepoDep,
    page: PageDep,
    _user: ViewReports,
    status_filter: Annotated[TicketStatus | None, Query(alias="status")] = None,
) -> list[TicketResponse]:
    """List support tickets (newest opened first). ``?status=`` scopes to one
    lifecycle state (open / pending / resolved); otherwise the whole queue."""
    rows = await asyncio.to_thread(
        repo.list_tickets, status=status_filter, limit=page.limit, offset=page.offset
    )
    return [TicketResponse.from_row(r) for r in rows]


@router.post("/tickets", response_model=TicketResponse, status_code=status.HTTP_201_CREATED)
async def create_ticket(
    body: TicketCreate, repo: TicketsRepoDep, clients: ClientsRepoDep, actor: ManageClients
) -> TicketResponse:
    """Log a support ticket (status=open). Validates the client, snapshots its name,
    and records activity."""
    client = await asyncio.to_thread(clients.get_client, body.client_id)
    if client is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Client not found")

    row = await asyncio.to_thread(
        repo.insert_ticket,
        {
            "subject": body.subject,
            "client_id": body.client_id,
            "client_name": client.get("name", ""),
            "channel": body.channel,
            "priority": body.priority,
            "status": "open",
            "created_by": actor.id,
        },
    )
    await record_activity(
        actor, kind="client", action="opened a support ticket",
        target=body.subject, meta=client.get("name", ""),
        entity_type="client", entity_id=body.client_id,
    )
    return TicketResponse.from_row(row)


@router.patch("/tickets/{code}/status", response_model=TicketResponse)
async def update_ticket_status(
    code: str, body: TicketStatusUpdate, repo: TicketsRepoDep, actor: ManageClients
) -> TicketResponse:
    """Triage a ticket to a new status (open / pending / resolved). Lead-only."""
    ticket = await asyncio.to_thread(repo.get_ticket_by_code, code)
    if ticket is None:
        raise _TICKET_NOT_FOUND
    prev_status = str(ticket.get("status") or "")  # snapshot BEFORE the update mutates it
    updated = await asyncio.to_thread(
        repo.update_ticket_by_code, code, {"status": body.status}
    )
    if updated is None:
        raise _TICKET_NOT_FOUND

    action = (
        "resolved a support ticket"
        if body.status == "resolved"
        else f"moved a ticket to {body.status}"
    )
    client_id = ticket.get("client_id")
    await record_activity(
        actor, kind="client", action=action, target=ticket.get("subject", ""),
        meta=ticket.get("client_name", ""),
        entity_type="client" if client_id is not None else None,
        entity_id=str(client_id) if client_id is not None else None,
    )
    # ADMIN/LEAD -> CLIENT: the client's request got a reply/answer (its status moved).
    # Email the client (best-effort; key-gated; resolves the client's contact email),
    # only on an ACTUAL status change to a client-linked ticket. Never blocks the triage.
    if client_id is not None and body.status != prev_status:
        await _email_client_ticket_update(
            str(client_id), str(ticket.get("subject", "")), body.status
        )
    return TicketResponse.from_row(updated)


async def _email_client_ticket_update(client_id: str, subject: str, status_: str) -> None:
    """Best-effort: email the client that their request's status changed."""
    label = _CLIENT_STATUS_LABEL.get(status_, status_)
    subj = f"Update on your request: {subject}" if subject else "Update on your request"
    text = (
        f'There is an update on your request "{subject}": it is now {label}. '
        "Sign in to your client portal to see the details."
    )
    html = (
        "<h2>Update on your request</h2>"
        f'<p>Your request "{html_escape(subject)}" is now '
        f"<strong>{html_escape(label)}</strong>.</p>"
        "<p>Sign in to your client portal to see the details.</p>"
    )
    await email_client(client_id, subj, html, text)
