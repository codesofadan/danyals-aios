"""Data access for client onboarding (``onboarding_runs`` / ``onboarding_steps``)
via the RLS-scoped ``rls_connection`` seam.

Every read + mutation on ``OnboardingRepo`` is tenant/actor-scoped by Postgres RLS:
staff read the whole board, clients are excluded (no base-table select policy - the
checklist names which of a client's credentials the agency holds), and only leads
(owner/admin/manager) may write (the 0040 insert/update policies + the app's
``manage_clients`` gate). Methods are synchronous (psycopg is sync) - the router
offloads them with ``asyncio.to_thread``.

There is deliberately NO privileged (BYPASSRLS) store in this module. Every write
path here has a real authenticated actor behind it (a lead starting/advancing a run,
or the client-create hook, which runs under the creating lead's identity), so
nothing needs to escape RLS - and the sensitivity of this data makes "no BYPASSRLS
seam exists at all" a materially stronger position than "one exists but we are
careful with it". The one privileged write this module causes is the vault seal
itself, which happens inside ``app/services/vault.py`` where it always has.

SQL rules (impersonation-review mandate): every VALUE is a bound param (``%s``),
never string-formatted; table/column names are static literals and the only dynamic
column lists come from server-built dicts quoted via ``psycopg.sql.Identifier``.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import Depends
from psycopg import sql

from app.core.auth import CurrentUserDep
from app.db.database import rls_connection

_Rows = list[dict[str, Any]]

# The live run states (mirrors the 0040 partial unique index predicate exactly: one
# ACTIVE run per client). Kept as one constant so the index, the "already running"
# guard and the KPI can never drift apart.
LIVE_STATUSES: tuple[str, ...] = ("in_progress", "on_hold")


class OnboardingRepo:
    """Thin RLS-scoped repository over the onboarding runs + their checklist steps."""

    def __init__(self, user_id: str) -> None:
        self._user_id = user_id

    # --- runs -----------------------------------------------------------------
    def list_runs(
        self, *, status: str | None = None, limit: int | None = None, offset: int = 0
    ) -> _Rows:
        query = "select * from public.onboarding_runs"
        params: list[Any] = []
        if status is not None:
            query += " where status = %s"
            params.append(status)
        # Newest first; id breaks ties so paging stays deterministic.
        query += " order by created_at desc, id"
        if limit is not None:
            query += " limit %s offset %s"
            params += [limit, offset]
        with rls_connection(self._user_id) as cur:
            cur.execute(query, params)
            return cur.fetchall()

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        with rls_connection(self._user_id) as cur:
            cur.execute(
                "select * from public.onboarding_runs where id = %s limit 1", (run_id,)
            )
            return cur.fetchone()

    def active_run_for(self, client_id: str) -> dict[str, Any] | None:
        """The client's LIVE run, if any - the app-side half of the 0040 partial
        unique index. Checked before an insert so a duplicate is a clean 409 rather
        than an opaque unique-violation from Postgres; the index remains the actual
        guarantee (this check races, that one cannot)."""
        with rls_connection(self._user_id) as cur:
            cur.execute(
                "select * from public.onboarding_runs "
                "where client_id = %s and status = any(%s) limit 1",
                (client_id, list(LIVE_STATUSES)),
            )
            return cur.fetchone()

    def insert_run(
        self,
        *,
        client_id: str,
        client_name: str,
        template_key: str,
        owner_user_id: str | None,
        owner_name: str,
        target_date: Any = None,
    ) -> dict[str, Any] | None:
        """Insert one run. Returns the row, or ``None`` when the 0040 partial unique
        index rejected it (the client already has a live run) - the router turns that
        into a 409."""
        with rls_connection(self._user_id) as cur:
            cur.execute(
                "insert into public.onboarding_runs "
                "(client_id, client_name, template_key, owner_user_id, owner_name, "
                "target_date) values (%s, %s, %s, %s, %s, %s) "
                "on conflict do nothing returning *",
                (client_id, client_name, template_key, owner_user_id, owner_name, target_date),
            )
            return cur.fetchone()

    def update_run(self, run_id: str, changes: dict[str, Any]) -> dict[str, Any] | None:
        """Update one run by id (or ``None`` if unknown/invisible). Column names are
        static ``sql.Identifier``s; values are always bound."""
        if not changes:
            return self.get_run(run_id)
        assignments = sql.SQL(", ").join(
            sql.SQL("{} = %s").format(sql.Identifier(col)) for col in changes
        )
        stmt = sql.SQL(
            "update public.onboarding_runs set {sets} where id = %s returning *"
        ).format(sets=assignments)
        with rls_connection(self._user_id) as cur:
            cur.execute(stmt, [*changes.values(), run_id])
            return cur.fetchone()

    # --- steps ----------------------------------------------------------------
    def list_steps(self, run_id: str) -> _Rows:
        """One run's checklist, in template order."""
        with rls_connection(self._user_id) as cur:
            cur.execute(
                "select * from public.onboarding_steps where run_id = %s "
                "order by sort_order, id",
                (run_id,),
            )
            return cur.fetchall()

    def list_board(
        self, *, status: str | None = None, limit: int | None = None, offset: int = 0
    ) -> _Rows:
        """The cross-client step BOARD. Reads ``onboarding_steps`` alone (client_name
        is denormalized onto it), optionally narrowed to one status."""
        query = "select * from public.onboarding_steps"
        params: list[Any] = []
        if status is not None:
            query += " where status = %s"
            params.append(status)
        query += " order by client_name, sort_order, id"
        if limit is not None:
            query += " limit %s offset %s"
            params += [limit, offset]
        with rls_connection(self._user_id) as cur:
            cur.execute(query, params)
            return cur.fetchall()

    def steps_for_runs(self, run_ids: list[str]) -> _Rows:
        """The steps for a SET of runs, in per-run template order (mirrors the
        milestones repo's ``list_stages``).

        This is what keeps the run BOARD at two queries instead of an N+1: the router
        lists the runs, then fetches every one of their checklists in one round-trip
        and zips them. Returns ``[]`` for an empty id list (no query at all)."""
        if not run_ids:
            return []
        with rls_connection(self._user_id) as cur:
            cur.execute(
                "select * from public.onboarding_steps "
                "where run_id::text = any(%s) order by run_id, sort_order, id",
                (run_ids,),
            )
            return cur.fetchall()

    def live_run_steps(self) -> _Rows:
        """Every step of every LIVE run, in per-run template order - the raw material
        the workspace folds into ONE row per run (each run shown at its current step).

        One query, not one per run: the workspace would otherwise be an N+1 over the
        whole live board. Ordered by client_name so the emitted board is stable."""
        with rls_connection(self._user_id) as cur:
            cur.execute(
                "select s.* from public.onboarding_steps s "
                "join public.onboarding_runs r on r.id = s.run_id "
                "where r.status = any(%s) "
                "order by s.client_name, s.run_id, s.sort_order, s.id",
                (list(LIVE_STATUSES),),
            )
            return cur.fetchall()

    def get_step(self, run_id: str, step_id: str) -> dict[str, Any] | None:
        """One step, scoped to its run: a step id from ANOTHER run is a 404 rather
        than an edit applied to the wrong client's checklist."""
        with rls_connection(self._user_id) as cur:
            cur.execute(
                "select * from public.onboarding_steps where id = %s and run_id = %s limit 1",
                (step_id, run_id),
            )
            return cur.fetchone()

    def seed_steps(self, *, run_id: str, client_id: str, client_name: str,
                   steps: list[dict[str, Any]]) -> _Rows:
        """Bulk-insert a run's checklist from the code template.

        IDEMPOTENT: ``on conflict (run_id, step_key) do nothing`` means a re-seed
        (a retried client-create hook) inserts nothing and returns no rows, instead
        of duplicating the checklist. Empty input is a no-op."""
        if not steps:
            return []
        values = sql.SQL(", ").join(
            sql.SQL("(%s, %s, %s, %s, %s, %s)") for _ in steps
        )
        params: list[Any] = []
        for step in steps:
            params += [
                run_id, client_id, client_name,
                step["step_key"], step["label"], step["sort_order"],
            ]
        stmt = sql.SQL(
            "insert into public.onboarding_steps "
            "(run_id, client_id, client_name, step_key, label, sort_order) "
            "values {values} on conflict (run_id, step_key) do nothing returning *"
        ).format(values=values)
        with rls_connection(self._user_id) as cur:
            cur.execute(stmt, params)
            return cur.fetchall()

    def update_step(
        self, run_id: str, step_id: str, changes: dict[str, Any]
    ) -> dict[str, Any] | None:
        """Update one step, scoped to its run (or ``None`` if unknown/invisible).

        The dynamic column list is composed with ``sql.Identifier``; values are
        bound. ``vault_secret_id`` may appear here - it is a REFERENCE, never a
        secret (the plaintext went to ``app/services/vault.py`` and nowhere else)."""
        if not changes:
            return self.get_step(run_id, step_id)
        assignments = sql.SQL(", ").join(
            sql.SQL("{} = %s").format(sql.Identifier(col)) for col in changes
        )
        stmt = sql.SQL(
            "update public.onboarding_steps set {sets} "
            "where id = %s and run_id = %s returning *"
        ).format(sets=assignments)
        with rls_connection(self._user_id) as cur:
            cur.execute(stmt, [*changes.values(), step_id, run_id])
            return cur.fetchone()

    # --- stats ----------------------------------------------------------------
    def onboarding_stats(self) -> dict[str, Any]:
        """The three KPI tiles in ONE round-trip. RLS-scoped; an empty board yields
        zeros. ``steps_pending`` counts unresolved steps of LIVE runs only - a
        pending step on a completed/archived run is history, not a to-do."""
        with rls_connection(self._user_id) as cur:
            cur.execute(
                "select "
                "(select count(*) from public.onboarding_runs "
                " where status = any(%s)) as in_onboarding, "
                "(select count(*) from public.onboarding_steps s "
                " join public.onboarding_runs r on r.id = s.run_id "
                " where r.status = any(%s) "
                " and s.status in ('pending', 'in_progress', 'blocked')) as steps_pending, "
                "(select count(*) from public.onboarding_runs "
                " where status = 'completed' "
                " and completed_at >= now() - interval '30 days') as completed_30d",
                (list(LIVE_STATUSES), list(LIVE_STATUSES)),
            )
            row = cur.fetchone()
            return row or {"in_onboarding": 0, "steps_pending": 0, "completed_30d": 0}

    # --- snapshot lookups -----------------------------------------------------
    def client_name_for(self, client_id: str) -> str | None:
        """The display name of a client the caller can see (RLS-scoped), or ``None``
        - used to SNAPSHOT client_name so the internal client_id never surfaces."""
        with rls_connection(self._user_id) as cur:
            cur.execute("select name from public.clients where id = %s limit 1", (client_id,))
            row = cur.fetchone()
            return str(row["name"]) if row else None

    def staff_for(self, user_id: str) -> dict[str, Any] | None:
        """The display snapshot (name + avatar colour) of a STAFF user, or ``None``.

        Portal clients are excluded in SQL: a client can never be made the owner of
        an onboarding step, which would hand a tenant a seat on a staff-only board."""
        with rls_connection(self._user_id) as cur:
            cur.execute(
                "select name, avatar_color from public.users "
                "where id = %s and role <> 'client' limit 1",
                (user_id,),
            )
            return cur.fetchone()


def get_onboarding_repo(user: CurrentUserDep) -> OnboardingRepo:
    """Dependency: a repo bound to the caller's verified user id (RLS-scoped)."""
    return OnboardingRepo(user.id)


OnboardingRepoDep = Annotated[OnboardingRepo, Depends(get_onboarding_repo)]
