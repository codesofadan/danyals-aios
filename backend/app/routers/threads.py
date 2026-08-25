"""Discussion threads - the STAFF surface (0098).

One primitive, two entity types. ``/threads/task/{code}/messages`` is the agency and
its delivery team talking about a job; ``/threads/ticket/{code}/messages`` is the same
mechanism on a client request, where some of the conversation is also readable by the
client. The client's own half lives in ``portal.py`` and reads a different view - see
``app/services/portal_threads.py``.

ADDRESSED BY PUBLIC CODE, never a UUID. Every other surface in this API renders
``J-1042`` / ``T-4821``, the frontend holds those codes, and nothing should have to
learn an internal id to leave a comment.

WHO MAY POST. Any staff member holding ``view_reports`` - which is all six staff
roles. Commenting is deliberately not a privileged act: restricting it to leads would
recreate the gap this table exists to close, where a specialist doing the work had no
way to ask a question about it. The DB policy agrees (``is_staff()``), so the app
layer and the boundary say the same thing.

VISIBILITY DEFAULTS TO ``internal``. A staff member has to choose to address the
client. The safe direction for a mistake is a note the client does not see.

A ``client_visible`` message also EMAILS the client, the same way the one-shot
``POST /tickets/{code}/reply`` did - otherwise moving the conversation into threads
would quietly stop clients being told they have an answer. Both legs are best-effort
and never raise: a dead mail provider must not fail the post the operator just made.
"""

from __future__ import annotations

import asyncio
from html import escape as html_escape
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, status

from app.core.auth import CurrentUser, require_perm
from app.core.pagination import PageDep
from app.db.tasks_repo import TasksRepoDep
from app.db.threads_repo import ThreadsRepoDep
from app.db.tickets_repo import TicketsRepoDep
from app.schemas.threads import MessageCreate, ThreadMessageResponse
from app.services.activity import record_activity
from app.services.notifications import email_client, notify

router = APIRouter(tags=["threads"])

Staff = Annotated[CurrentUser, Depends(require_perm("view_reports"))]

EntityTypeParam = Literal["task", "ticket"]

_ENTITY_NOT_FOUND = HTTPException(
    status_code=status.HTTP_404_NOT_FOUND, detail="No such task or request"
)
_THREAD_UNAVAILABLE = HTTPException(
    status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Discussion is unavailable"
)


async def _resolve_entity(
    entity_type: str, code: str, tasks: TasksRepoDep, tickets: TicketsRepoDep
) -> dict[str, Any]:
    """The entity behind a public code, or 404.

    Resolving through the caller's own RLS-scoped repo is what authorizes the thread:
    if the caller cannot read the task, they get the same 404 as if it did not exist,
    and never reach its discussion.
    """
    if entity_type == "task":
        row = await asyncio.to_thread(tasks.get_task_by_code, code)
    else:
        row = await asyncio.to_thread(tickets.get_ticket_by_code, code)
    if row is None:
        raise _ENTITY_NOT_FOUND
    return dict(row)


@router.get(
    "/threads/{entity_type}/{code}/messages", response_model=list[ThreadMessageResponse]
)
async def list_thread_messages(
    entity_type: EntityTypeParam,
    code: str,
    repo: ThreadsRepoDep,
    tasks: TasksRepoDep,
    tickets: TicketsRepoDep,
    page: PageDep,
    _user: Staff,
) -> list[ThreadMessageResponse]:
    """The whole conversation on one entity, oldest first, internal notes included."""
    entity = await _resolve_entity(entity_type, code, tasks, tickets)
    thread = await asyncio.to_thread(repo.get_thread, entity_type, str(entity["id"]))
    if thread is None:
        # No thread yet is not an error - nobody has said anything.
        return []
    rows = await asyncio.to_thread(
        repo.list_messages, str(thread["id"]), limit=page.limit, offset=page.offset
    )
    return [ThreadMessageResponse.from_row(r) for r in rows]


@router.post(
    "/threads/{entity_type}/{code}/messages",
    response_model=ThreadMessageResponse,
    status_code=status.HTTP_201_CREATED,
)
async def post_thread_message(
    entity_type: EntityTypeParam,
    code: str,
    body: MessageCreate,
    repo: ThreadsRepoDep,
    tasks: TasksRepoDep,
    tickets: TicketsRepoDep,
    actor: Staff,
) -> ThreadMessageResponse:
    """Post a message, creating the thread on first use."""
    entity = await _resolve_entity(entity_type, code, tasks, tickets)
    client_id = entity.get("client_id")
    thread = await asyncio.to_thread(
        repo.create_thread,
        entity_type=entity_type,
        entity_id=str(entity["id"]),
        client_id=str(client_id) if client_id else None,
    )
    if thread is None:  # pragma: no cover - only on a DB that refused both paths
        raise _THREAD_UNAVAILABLE

    posted = await asyncio.to_thread(
        repo.add_message,
        thread_id=str(thread["id"]),
        author_id=actor.id,
        author_name=actor.name or actor.email,
        body=body.body,
        visibility=body.visibility,
    )
    if posted is None:  # pragma: no cover
        raise _THREAD_UNAVAILABLE

    # Tell the other side. An internal note pings the assignee (if the entity has
    # one and it is not the author); a client-visible reply emails the client, which
    # is what `POST /tickets/{code}/reply` used to do and must keep happening.
    if body.visibility == "client_visible" and client_id:
        await _email_client_reply(str(client_id), entity_type, code, body.body)
    else:
        await _notify_counterpart(entity_type, entity_dict=entity, actor_id=actor.id, code=code)

    await record_activity(
        actor,
        kind="content" if entity_type == "task" else "client",
        action=(
            "replied to a client on"
            if body.visibility == "client_visible"
            else "commented on"
        ),
        target=code,
        entity_type="client" if client_id else None,
        entity_id=str(client_id) if client_id else None,
    )
    return ThreadMessageResponse.from_row(posted)


async def _email_client_reply(client_id: str, entity_type: str, code: str, message: str) -> None:
    """Best-effort: tell the client, in email, that they have a new reply.

    Mirrors ``_email_client_ticket_reply`` in tickets.py - the same signal the one-shot
    reply column used to send. ``email_client`` never raises and silently skips when no
    recipient or no provider key resolves.
    """
    label = "request" if entity_type == "ticket" else "project"
    subj = f"New reply on your {label} ({code})"
    text = (
        f"You have a new reply on your {label} {code}:\n\n{message}\n\n"
        "Sign in to your client portal to see the full conversation."
    )
    html = (
        "<h2>New reply</h2>"
        f"<p>On your {html_escape(label)} <b>{html_escape(code)}</b>:</p>"
        f'<p style="white-space:pre-wrap">{html_escape(message)}</p>'
        "<p>Sign in to your client portal to see the full conversation.</p>"
    )
    await email_client(client_id, subj, html, text)


async def _notify_counterpart(
    entity_type: str, *, entity_dict: dict[str, Any], actor_id: str, code: str
) -> None:
    """Best-effort in-app ping to the task's assignee when someone else comments.

    Only for tasks - a ticket has no assignee. Skipped when the commenter IS the
    assignee, so nobody is notified about their own note.
    """
    if entity_type != "task":
        return
    assignee = entity_dict.get("assignee_id")
    if not assignee or str(assignee) == actor_id:
        return
    await notify(
        str(assignee),
        kind="task_comment",
        title=f"New comment on {code}",
        body="A team member commented on a task assigned to you.",
    )
