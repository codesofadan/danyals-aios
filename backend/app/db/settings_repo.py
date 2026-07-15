"""Data access for the Settings stores via the RLS-scoped ``rls_connection`` seam.

Three surfaces (see 0025):

* ``workspace_settings`` / ``security_policy`` - agency-global SINGLETONS pinned to
  ``id = 1``. Staff read; owner/admin manage (RLS enforces both). Writes upsert the
  singleton so a row always exists.
* ``notification_prefs`` - PER-USER, per-event toggles. RLS scopes every row to
  ``user_id = auth.uid()``, so a caller can only ever read/write their OWN toggles.

The danger-zone ``purge_activity`` is the ONE method on the privileged pool: the
``activity_log`` is append-only under RLS (no delete policy), so a hard purge needs
service_role. It is owner-gated at the app layer (server-only, never client-reachable).

SQL rules (impersonation-review mandate): every VALUE is a bound param; dynamic
column lists come from server-built dicts and are quoted via ``psycopg.sql.Identifier``;
the only table names are fixed literals chosen in-method (never request input).
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import Depends
from psycopg import sql

from app.core.auth import CurrentUserDep
from app.db.database import privileged_connection, rls_connection

_Rows = list[dict[str, Any]]


class SettingsRepo:
    """Thin repository over the workspace/security singletons + per-user notif prefs."""

    def __init__(self, user_id: str) -> None:
        self._user_id = user_id

    # --- Singletons ----------------------------------------------------------
    def get_workspace(self) -> dict[str, Any] | None:
        with rls_connection(self._user_id) as cur:
            cur.execute("select * from public.workspace_settings where id = 1 limit 1")
            return cur.fetchone()

    def get_security(self) -> dict[str, Any] | None:
        with rls_connection(self._user_id) as cur:
            cur.execute("select * from public.security_policy where id = 1 limit 1")
            return cur.fetchone()

    def update_workspace(self, changes: dict[str, Any]) -> dict[str, Any] | None:
        return self._upsert_singleton("workspace_settings", changes)

    def update_security(self, changes: dict[str, Any]) -> dict[str, Any] | None:
        return self._upsert_singleton("security_policy", changes)

    def _upsert_singleton(
        self, table: str, changes: dict[str, Any]
    ) -> dict[str, Any] | None:
        """Upsert the ``id = 1`` row of a fixed singleton table (``table`` is an
        in-method literal, never request input). Guarantees a row exists so a GET
        after a PUT always returns the saved values. ``changes`` is non-empty."""
        cols = list(changes.keys())
        insert_cols = [sql.Identifier("id"), *(sql.Identifier(c) for c in cols)]
        placeholders = [sql.Literal(1), *([sql.Placeholder()] * len(cols))]
        assignments = sql.SQL(", ").join(
            sql.SQL("{col} = excluded.{col}").format(col=sql.Identifier(c)) for c in cols
        )
        stmt = sql.SQL(
            "insert into public.{table} ({cols}) values ({vals}) "
            "on conflict (id) do update set {sets} returning *"
        ).format(
            table=sql.Identifier(table),
            cols=sql.SQL(", ").join(insert_cols),
            vals=sql.SQL(", ").join(placeholders),
            sets=assignments,
        )
        with rls_connection(self._user_id) as cur:
            cur.execute(stmt, list(changes.values()))
            return cur.fetchone()

    # --- Notification prefs (per-user) ---------------------------------------
    def list_notif_prefs(self) -> _Rows:
        """The caller's stored ``(event_key, email, in_app)`` rows (RLS-scoped to
        the caller). Missing events are filled with defaults in the schema layer."""
        with rls_connection(self._user_id) as cur:
            cur.execute(
                "select event_key, email, in_app from public.notification_prefs "
                "where user_id = %s",
                (self._user_id,),
            )
            return cur.fetchall()

    def upsert_notif_pref(
        self, event_key: str, *, email: bool, in_app: bool
    ) -> dict[str, Any] | None:
        """Upsert ONE ``(caller, event)`` toggle row. RLS pins ``user_id`` to the
        caller, so this can only ever write the caller's own prefs."""
        stmt = (
            "insert into public.notification_prefs (user_id, event_key, email, in_app) "
            "values (%s, %s, %s, %s) "
            "on conflict (user_id, event_key) do update "
            "set email = excluded.email, in_app = excluded.in_app returning *"
        )
        with rls_connection(self._user_id) as cur:
            cur.execute(stmt, (self._user_id, event_key, email, in_app))
            return cur.fetchone()

    # --- Danger zone ---------------------------------------------------------
    def purge_activity(self) -> int:
        """Hard-delete every ``activity_log`` row (owner-only, danger zone).

        Runs on the PRIVILEGED pool: the activity log is append-only under RLS (no
        delete policy), so a purge needs service_role. Server-only + owner-gated at
        the router; returns the number of rows removed."""
        with privileged_connection() as cur:
            cur.execute("delete from public.activity_log")
            return cur.rowcount


def get_settings_repo(user: CurrentUserDep) -> SettingsRepo:
    """Dependency: a repo bound to the caller's verified user id (RLS-scoped)."""
    return SettingsRepo(user.id)


SettingsRepoDep = Annotated[SettingsRepo, Depends(get_settings_repo)]
