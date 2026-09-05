"""Team requests - a staff member asking the agency's leads for something.

The client portal has had a request channel since 0024. The team portal had none, so a
member who needed an access grant, a tool, a deadline moved or a decision had no route
inside the product: the ask went to chat, where it left no record, no owner and no
status, and "did anyone action that?" had no answer.

WHY THIS REUSES ``support_tickets``. A team request and a client request are the same
object with a different origin - subject, body, status, reply, conversation. A second
table would need its own status vocabulary, its own reply path and its own thread, and
every admin surface would then merge two ledgers that can disagree about what happened
to one request. The origin is ``client_id is null`` (see 0127 for why that, and not a
new channel value or a role lookup on ``created_by``).

WHAT IS PINNED SERVER-SIDE. ``created_by`` is the authenticated staff user and
``client_id`` is forced NULL - neither is ever read from the body. A team member cannot
raise a request that appears to come from a client, or from another member.

THE NOTIFICATION IS BEST-EFFORT, exactly like the client path's. ``email_admin`` and
``notify_leads`` both swallow their own failures, and they are awaited AFTER the row is
persisted, so a missing Resend key or a dead provider can never fail the submission the
member just made. That ordering is the whole reason the request survives a broken
mailer.
"""

from __future__ import annotations

import asyncio
from html import escape as html_escape
from typing import Any

from app.core.auth import CurrentUser
from app.services.activity import record_activity
from app.services.client_requests import insert_request_row
from app.services.notifications import email_admin, notify_leads

#: The in-app event key leads' notification_prefs govern this alert with.
NOTIFY_KIND = "team_request"


def _alert(member_name: str, subject: str, detail: str, kind: str) -> tuple[str, str, str]:
    """(subject, html, text) for the operator alert. Every value is escaped."""
    line = f"{member_name} raised a team request: {subject}"
    text = f"{line}\n\nType: {kind}\n\n{detail or '(no detail)'}"
    html = (
        "<h2>New team request</h2>"
        f"<p><strong>From:</strong> {html_escape(member_name)}</p>"
        f"<p><strong>Type:</strong> {html_escape(kind)}</p>"
        f"<p><strong>Subject:</strong> {html_escape(subject)}</p>"
        f"<p><strong>Message:</strong> {html_escape(detail or '(none)')}</p>"
    )
    return f"[AIOS] Team request: {subject}", html, text


async def create_team_request(
    *, user: CurrentUser, subject: str, detail: str, kind: str
) -> dict[str, Any]:
    """Persist one team request and alert the leads. Returns the stored row."""
    member_name = str(getattr(user, "name", "") or getattr(user, "username", "") or "A team member")
    row = await asyncio.to_thread(
        insert_request_row,
        {
            # NULL is the origin marker, and it is set here rather than accepted from
            # the caller: a body-supplied client_id would let a member file a request
            # that reads as a client's.
            "client_id": None,
            "client_name": member_name,
            "subject": subject,
            "detail": detail,
            "kind": kind,
            "channel": "Portal",
            "priority": "med",
            "status": "open",
            "created_by": user.id,
        },
    )
    await record_activity(
        user, kind="team", action="raised a team request", target=subject,
    )
    mail_subject, html, text = _alert(member_name, subject, detail, kind)
    await email_admin(mail_subject, html, text)
    await notify_leads(
        NOTIFY_KIND,
        f"{member_name} raised a team request",
        f"{subject} - {detail[:160]}" if detail else subject,
    )
    return row
