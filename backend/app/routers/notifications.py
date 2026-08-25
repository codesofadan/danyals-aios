"""Delivery-layer endpoints (7F-1): the per-user notification inbox + the staff
alert queue.

Two audiences, two RBAC boundaries (matching the 0023 RLS):

* ``/notifications*`` - PER-USER. Any authenticated caller reads + marks-read ONLY
  their OWN rows (RLS: ``user_id = auth.uid()``); there is no cross-user read. A
  portal client is allowed here (they simply have no rows) - notifications are not a
  staff-only namespace.
* ``/alerts*`` - STAFF. Reading requires ``view_reports`` (a portal client does NOT
  hold it, so clients are 403'd out, mirroring tasks/tickets); acknowledging requires
  a LEAD (owner/admin/manager) - the set the RLS update policy gates to. The app-layer
  403 is clean UX on top of the DB boundary.

Responses are the internal ``NotificationResponse`` / ``AlertResponse`` shapes (no
``lib/*.ts`` contract type mirrors them, so there is no contract-lock entry). The
WRITE path (delivering notifications / raising alerts) is NOT here - it is server-side
in ``app/services/notifications.py`` on the privileged pool.
"""

from __future__ import annotations

import asyncio
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.core.auth import CurrentUser, get_current_user, require_perm, require_role
from app.core.pagination import PageDep
from app.db.notifications_repo import NotificationsRepoDep
from app.schemas.notifications import (
    AlertResponse,
    NotificationResponse,
    UnreadCountResponse,
)
from app.services.activity import record_activity

router = APIRouter(tags=["notifications"])

# All six staff roles hold view_reports; a portal client does NOT (clients are
# confined out of the staff alert namespace, mirroring tasks.py / tickets.py).
ViewReports = Annotated[CurrentUser, Depends(require_perm("view_reports"))]
# The two per-user notification routes take this EXPLICITLY. They were authenticated
# only transitively, through NotificationsRepoDep's own dependency on the current user -
# correct, but invisible in the signature and one refactor away from an open endpoint:
# swap the repo for a fake or a non-user-bound dep and the authentication disappears
# with no test failing. Any authenticated caller may read their own rows (a portal
# client included - they simply have none), so this is deliberately not a permission.
AnyUser = Annotated[CurrentUser, Depends(get_current_user)]
# Acknowledging an alert is lead-only (owner/admin/manager) - the RLS update set.
Lead = Annotated[CurrentUser, Depends(require_role("owner", "admin", "manager"))]

_NOTIFICATION_NOT_FOUND = HTTPException(
    status_code=status.HTTP_404_NOT_FOUND, detail="Notification not found"
)
_ALERT_NOT_FOUND = HTTPException(
    status_code=status.HTTP_404_NOT_FOUND, detail="Alert not found"
)


# --- Notifications (per-user) ------------------------------------------------
@router.get("/notifications", response_model=list[NotificationResponse])
async def list_notifications(
    repo: NotificationsRepoDep,
    page: PageDep,
    _user: AnyUser,
    unread: Annotated[bool, Query()] = False,
) -> list[NotificationResponse]:
    """List the caller's own notifications (newest first). ``unread=true`` scopes to
    the unread ones. Any authenticated caller; RLS returns only their rows."""
    rows = await asyncio.to_thread(
        repo.list_notifications, unread_only=unread, limit=page.limit, offset=page.offset
    )
    return [NotificationResponse.from_row(r) for r in rows]


@router.get("/notifications/unread-count", response_model=UnreadCountResponse)
async def notifications_unread_count(repo: NotificationsRepoDep, _user: AnyUser) -> UnreadCountResponse:
    """How many unread notifications the caller has.

    Its own endpoint rather than a client-side ``length`` over the list: the bell sits
    in the shared top bar, so it renders on every page of all three portals and polls
    for new arrivals. Counting server-side keeps the most-frequent call in the product
    from shipping every unread body over the wire to render one integer.

    DECLARED BEFORE ``/notifications/{notification_id}``-style paths would matter -
    ``unread-count`` is a literal segment and Starlette matches in declaration order,
    so a future ``GET /notifications/{id}`` cannot swallow it.
    """
    return UnreadCountResponse(unread=await asyncio.to_thread(repo.unread_count))


@router.post("/notifications/read-all", response_model=UnreadCountResponse)
async def mark_all_notifications_read(
    repo: NotificationsRepoDep, _user: AnyUser
) -> UnreadCountResponse:
    """Clear the caller's whole inbox. Returns the new (zero) unread count.

    Without this, an inbox that has accumulated while nobody was reading it can only
    be cleared one row at a time, which is how a notification surface becomes
    permanently badged and then ignored.
    """
    await asyncio.to_thread(repo.mark_all_read)
    return UnreadCountResponse(unread=await asyncio.to_thread(repo.unread_count))


@router.post("/notifications/{notification_id}/read", response_model=NotificationResponse)
async def mark_notification_read(
    notification_id: UUID, repo: NotificationsRepoDep, _user: AnyUser
) -> NotificationResponse:
    """Mark one of the caller's notifications read. 404 if it is unknown or not the
    caller's (RLS scopes the update to the caller)."""
    row = await asyncio.to_thread(repo.mark_read, str(notification_id))
    if row is None:
        raise _NOTIFICATION_NOT_FOUND
    return NotificationResponse.from_row(row)


# --- Alerts (staff) ----------------------------------------------------------
@router.get("/alerts", response_model=list[AlertResponse])
async def list_alerts(
    repo: NotificationsRepoDep,
    page: PageDep,
    _user: ViewReports,
    unacknowledged: Annotated[bool, Query()] = False,
) -> list[AlertResponse]:
    """List staff alerts (newest first). ``unacknowledged=true`` scopes to the open
    ones. Staff-only (``view_reports``); RLS also gates reads to ``is_staff()``."""
    rows = await asyncio.to_thread(
        repo.list_alerts,
        unacknowledged_only=unacknowledged,
        limit=page.limit,
        offset=page.offset,
    )
    return [AlertResponse.from_row(r) for r in rows]


@router.post("/alerts/{alert_id}/acknowledge", response_model=AlertResponse)
async def acknowledge_alert(
    alert_id: UUID, repo: NotificationsRepoDep, actor: Lead
) -> AlertResponse:
    """Acknowledge (clear) one staff alert. Lead-only (owner/admin/manager) - the RLS
    update set. 404 if the alert is unknown. Records an activity entry linked to the
    alert's client so the context layer stays fresh."""
    row = await asyncio.to_thread(repo.acknowledge_alert, str(alert_id))
    if row is None:
        raise _ALERT_NOT_FOUND
    client_id = row.get("client_id")
    await record_activity(
        actor,
        kind="client",
        action="acknowledged an alert",
        target=str(row.get("type", "")),
        entity_type="client" if client_id is not None else None,
        entity_id=str(client_id) if client_id is not None else None,
    )
    return AlertResponse.from_row(row)
