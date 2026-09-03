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
from datetime import UTC, datetime
from html import escape as html_escape
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.core.auth import CurrentUser, require_perm
from app.core.pagination import PageDep
from app.db.clients_repo import ClientsRepoDep
from app.db.tasks_repo import TasksRepoDep
from app.db.threads_repo import ThreadsRepo, ThreadsRepoDep
from app.db.tickets_repo import TicketsRepoDep
from app.schemas.tasks import TaskResponse
from app.schemas.tickets import (
    TicketCreate,
    TicketReplyRequest,
    TicketResponse,
    TicketStatus,
    TicketStatusUpdate,
    TicketToTaskRequest,
)
from app.logging_setup import get_logger
from app.services.activity import record_activity
from app.services.notifications import email_client, notify_client_in_app
from app.services.task_assignment import assign_task

logger = get_logger("routers.tickets")

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
        # ...and light up the client's BELL, which the email leg alone never did:
        # `email_client` writes no notifications row, so a client whose request was
        # finished saw nothing in the portal until they happened to re-open the
        # requests page and notice a changed pill. In-app only (see
        # `notify_client_in_app`) - the email above is the email for this event.
        await _notify_client_ticket_update(
            str(client_id), str(ticket.get("subject", "")), body.status
        )
    return TicketResponse.from_row(updated)


@router.post("/tickets/{code}/reply", response_model=TicketResponse)
async def reply_to_ticket(
    code: str,
    body: TicketReplyRequest,
    repo: TicketsRepoDep,
    threads: ThreadsRepoDep,
    actor: ManageClients,
) -> TicketResponse:
    """Send a real, free-text reply on a ticket/request (lead-only).

    Writes the message into ``support_tickets.reply`` (+ ``replied_at``/``replied_by``)
    - the FIRST endpoint to ever populate that column (0033 added it, unused since).
    When the ticket is client-linked (``client_id`` set - mirrors the same check
    ``update_ticket_status`` uses for its canned status email) the actual reply text
    is emailed to the client, not a canned status label.

    IT ALSO MIRRORS THE REPLY INTO THE THREAD, and that is the point of the mirror.
    Two staff reply paths existed and they did not meet: this one wrote a single
    ``support_tickets.reply`` column and sent an email, while the client portal reads
    ``portal_thread_messages`` (0098). So an operator who used "Reply" on a ticket
    emailed the client and left NOTHING in the conversation the client actually opens
    - the portal thread showed the client's own message and no answer, which reads as
    being ignored. The reply is written ``client_visible`` because that is what this
    endpoint means by definition: it has always emailed the text to the client.

    The email is sent ONCE, by the block below, not by the mirror - writing through
    the repo rather than the /threads route is what keeps it to one message.
    """
    ticket = await asyncio.to_thread(repo.get_ticket_by_code, code)
    if ticket is None:
        raise _TICKET_NOT_FOUND

    updated = await asyncio.to_thread(
        repo.update_ticket_by_code,
        code,
        {
            "reply": body.message,
            "replied_at": datetime.now(UTC).isoformat(),
            "replied_by": actor.id,
        },
    )
    if updated is None:
        raise _TICKET_NOT_FOUND

    client_id = ticket.get("client_id")
    await record_activity(
        actor, kind="client", action="replied to a support ticket",
        target=ticket.get("subject", ""), meta=ticket.get("client_name", ""),
        entity_type="client" if client_id is not None else None,
        entity_id=str(client_id) if client_id is not None else None,
    )
    # ADMIN/LEAD -> CLIENT: the real reply text (not a canned status label), only on
    # Mirror into the thread the CLIENT reads, so "Reply" leaves a trace there and
    # not only in an inbox. Best-effort for the same reason the email is: a thread
    # write that fails must not lose a reply that is already saved on the ticket.
    await _mirror_reply_to_thread(
        threads,
        ticket_id=str(ticket["id"]),
        client_id=str(client_id) if client_id is not None else None,
        actor_id=actor.id,
        actor_name=actor.name or actor.email,
        message=body.message,
    )

    # a client-linked ticket. Best-effort; never blocks the reply from being saved.
    if client_id is not None:
        await _email_client_ticket_reply(
            str(client_id), str(ticket.get("subject", "")), body.message
        )
    return TicketResponse.from_row(updated)


async def _mirror_reply_to_thread(
    threads: ThreadsRepo,
    *,
    ticket_id: str,
    client_id: str | None,
    actor_id: str,
    actor_name: str,
    message: str,
) -> None:
    """Write a ticket reply into the ticket's thread as a client-visible message.

    ``create_thread`` is upsert-shaped (``on conflict do nothing``, returning the
    existing row), so this is safe whether or not the client has already opened the
    conversation. Swallows everything: the reply is already persisted on the ticket
    and already on its way by email; a thread hiccup must not turn that into a 500.
    """
    try:
        thread = await asyncio.to_thread(
            threads.create_thread,
            entity_type="ticket",
            entity_id=ticket_id,
            client_id=client_id,
        )
        if thread is None:
            logger.warning("ticket_reply_thread_unavailable", ticket_id=ticket_id)
            return
        await asyncio.to_thread(
            threads.add_message,
            thread_id=str(thread["id"]),
            author_id=actor_id,
            author_name=actor_name,
            body=message,
            visibility="client_visible",
        )
    except Exception:
        logger.warning("ticket_reply_thread_mirror_failed", ticket_id=ticket_id)


async def _email_client_ticket_reply(client_id: str, subject: str, message: str) -> None:
    """Best-effort: email the client the admin's actual free-text reply."""
    subj = f"Reply to your request: {subject}" if subject else "Reply to your request"
    text = (
        f'You have a new reply on your request "{subject}":\n\n{message}\n\n'
        "Sign in to your client portal to see the full conversation."
    )
    html = (
        "<h2>New reply on your request</h2>"
        + (f'<p>Re: "{html_escape(subject)}"</p>' if subject else "")
        + f'<p style="white-space:pre-wrap">{html_escape(message)}</p>'
        "<p>Sign in to your client portal to see the full conversation.</p>"
    )
    await email_client(client_id, subj, html, text)


async def _notify_client_ticket_update(client_id: str, subject: str, status_: str) -> None:
    """Best-effort: put the status change in the client's portal inbox.

    Only ``resolved`` gets the completed wording; the intermediate states say what
    they are. A client is told their request is DONE exactly once, by the same
    transition that emails them.
    """
    label = _CLIENT_STATUS_LABEL.get(status_, status_)
    named = f'"{subject}"' if subject else "your request"
    if status_ == "resolved":
        title = "Your request is complete"
        body = f"{named} has been completed. Sign in to your portal to see the details."
    else:
        title = "Update on your request"
        body = f"{named} is now {label}."
    await notify_client_in_app(client_id, kind="request_resolved", title=title, body=body)


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


# --- Turning a client's request into work -------------------------------------
AssignTasks = Annotated[CurrentUser, Depends(require_perm("assign_tasks"))]

_TICKET_NOT_FOUND = HTTPException(
    status_code=status.HTTP_404_NOT_FOUND, detail="Ticket not found"
)
_NO_CLIENT = HTTPException(
    status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
    detail="This request is not linked to a client, so it cannot become client work",
)


@router.post(
    "/tickets/{code}/convert-to-task",
    response_model=TaskResponse,
    status_code=status.HTTP_201_CREATED,
)
async def convert_ticket_to_task(
    code: str,
    body: TicketToTaskRequest,
    tickets: TicketsRepoDep,
    tasks: TasksRepoDep,
    clients: ClientsRepoDep,
    threads: ThreadsRepoDep,
    actor: AssignTasks,
) -> TaskResponse:
    """Create a task from a client's request, and record the link on both sides.

    THE LOOP THIS CLOSES. A client raised a request; it became a `support_tickets`
    row, an email to the operator inbox, and a truncated six-row widget on the Clients
    page. Nothing ever turned it into work that somebody was assigned - there was no
    path at all from a request to the team's queue, so the only thing connecting them
    was an operator remembering.

    `client_id` is resolved from the TICKET, never from the body: a ticket deliberately
    never exposes its tenant on the wire, and taking it from the caller would let a
    request be converted into work billed against a different client.

    The link is recorded as an INTERNAL message on the request's own thread. The client
    does not need to see a job code, but the next person to open the request does -
    otherwise the same request gets converted twice.
    """
    ticket = await asyncio.to_thread(tickets.get_ticket_by_code, code)
    if ticket is None:
        raise _TICKET_NOT_FOUND
    client_id = ticket.get("client_id")
    if not client_id:
        raise _NO_CLIENT
    if ticket.get("task_id"):
        # The link used to exist only as prose in a thread message, which is easy to
        # miss - so the same request could be converted again and again, each time
        # producing another task for work already assigned. Now it is a column, and
        # this is what it is for.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This request has already been converted to a task.",
        )

    title = (body.title or "").strip() or str(ticket.get("subject") or "Client request")
    row = await assign_task(
        repo=tasks,
        clients=clients,
        actor=actor,
        title=title,
        client_id=str(client_id),
        task_type=body.type,
        assignee_id=body.assignee_id,
        priority=body.priority,
        due=body.due,
        origin=code,
    )

    task_code = str(row.get("code") or "")
    # Record the link on the request itself, so "which requests are being worked on,
    # and how far along?" is a query rather than a reading exercise.
    await asyncio.to_thread(tickets.link_task, str(ticket["id"]), str(row["id"]))
    thread = await asyncio.to_thread(
        threads.create_thread,
        entity_type="ticket",
        entity_id=str(ticket["id"]),
        client_id=str(client_id),
    )
    if thread is not None:
        await asyncio.to_thread(
            threads.add_message,
            thread_id=str(thread["id"]),
            author_id=actor.id,
            author_name=actor.name or actor.email,
            body=f"Converted to task {task_code} — \"{title}\".",
            # Internal: the job code is agency bookkeeping. The client is told the work
            # is happening by a reply somebody writes, not by a task id appearing.
            visibility="internal",
        )
    return TaskResponse.from_row(row)
