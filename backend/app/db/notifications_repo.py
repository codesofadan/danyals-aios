"""Data access for the ``notifications`` inbox + ``alerts`` queue via the RLS-scoped
``rls_connection`` seam (0023).

Every read + mutation here is tenant/actor-scoped by Postgres RLS:

* ``notifications`` - the caller reads + marks-read ONLY their own rows
  (``user_id = auth.uid()``). The WRITE path (delivering a notification) is NOT here:
  it runs server-side on the privileged pool in ``app/services/notifications.py`` (a
  notification is addressed to someone else than the actor).
* ``alerts`` - any staff READs (``is_staff()``); only a lead (owner/admin/manager)
  acknowledges (the RLS update policy). Raising an alert is likewise server-side on
  the privileged pool.

Methods are synchronous - the router offloads them with ``asyncio.to_thread`` - and
the single ``get_notifications_repo`` dependency makes the layer trivially replaceable
with an in-memory fake in tests. Every VALUE is a bound param (impersonation-review
mandate).
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import Depends

from app.core.auth import CurrentUserDep
from app.db.database import rls_connection

_Rows = list[dict[str, Any]]


class NotificationsRepo:
    """Thin repository over ``notifications`` (per-user) + ``alerts`` (staff)."""

    def __init__(self, user_id: str) -> None:
        self._user_id = user_id

    # --- Notifications (per-user; RLS scopes to auth.uid()) ------------------
    def list_notifications(
        self, *, unread_only: bool = False, limit: int | None = None, offset: int = 0
    ) -> _Rows:
        query = "select * from public.notifications"
        params: list[Any] = []
        if unread_only:
            query += " where read = false"
        query += " order by created_at desc"
        if limit is not None:
            query += " limit %s offset %s"
            params += [limit, offset]
        with rls_connection(self._user_id) as cur:
            cur.execute(query, params)
            return cur.fetchall()

    def mark_read(self, notification_id: str) -> dict[str, Any] | None:
        """Flip one of the caller's notifications to read. RLS pins it to the caller,
        so this can only ever touch the caller's own rows. Returns the updated row or
        ``None`` (unknown id / not the caller's)."""
        with rls_connection(self._user_id) as cur:
            cur.execute(
                "update public.notifications set read = true where id = %s returning *",
                (notification_id,),
            )
            return cur.fetchone()

    # --- Alerts (staff read; lead acknowledge - RLS enforces both) -----------
    def list_alerts(
        self, *, unacknowledged_only: bool = False, limit: int | None = None, offset: int = 0
    ) -> _Rows:
        query = "select * from public.alerts"
        params: list[Any] = []
        if unacknowledged_only:
            query += " where acknowledged = false"
        query += " order by created_at desc"
        if limit is not None:
            query += " limit %s offset %s"
            params += [limit, offset]
        with rls_connection(self._user_id) as cur:
            cur.execute(query, params)
            return cur.fetchall()

    def acknowledge_alert(self, alert_id: str) -> dict[str, Any] | None:
        """Acknowledge one alert (lead-only; the RLS update policy enforces it).
        Returns the updated row, or ``None`` (unknown id) - the router maps that to a
        404. A non-lead's UPDATE matches no row under RLS and also returns ``None``."""
        with rls_connection(self._user_id) as cur:
            cur.execute(
                "update public.alerts set acknowledged = true where id = %s returning *",
                (alert_id,),
            )
            return cur.fetchone()


def get_notifications_repo(user: CurrentUserDep) -> NotificationsRepo:
    """Dependency: a repo bound to the caller's verified user id (RLS-scoped)."""
    return NotificationsRepo(user.id)


NotificationsRepoDep = Annotated[NotificationsRepo, Depends(get_notifications_repo)]
