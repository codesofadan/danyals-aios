"""Data access for the import ledger (``import_runs`` / ``import_mappings``) via the
RLS-scoped ``rls_connection`` seam + the privileged ``ServiceImportStore`` the commit
worker writes through.

Every read + mutation on ``ImportRepo`` is tenant/actor-scoped by Postgres RLS: staff
read the whole ledger (including agency-global NULL-client runs), clients are excluded
(no base-table select policy), and only leads (owner/admin/manager) may write (the 0042
insert/update policies + the app gate). Methods are synchronous (psycopg is sync) - the
router offloads them with ``asyncio.to_thread``.

``ServiceImportStore`` is the COMMIT writer and runs on ``privileged_connection``
(service_role, BYPASSRLS) for a specific reason: the RLS insert policies on the target
tables (``backlinks``/``citations``/``keywords``/``tracked_keywords``) are lead-only and
the worker holds no user JWT - exactly the situation ``ServiceKeywordStore`` (0035) and
``ServiceRankStore`` (0036) already solve this way. Because it bypasses RLS it stamps
``client_id`` + ``client_name`` itself, from the run row, and never from file input.

SQL rules (impersonation-review mandate): every VALUE is a bound param (``%s``), never
string-formatted; table/column names are static literals and the only dynamic
identifiers come from the FROZEN ``constants`` allow-list, quoted via
``psycopg.sql.Identifier``. ``insert_rows`` iterates the allow-list and tests membership
in the row - it never reads the row's own keys - so a user-supplied string cannot become
an identifier even if validation were somehow bypassed.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import Depends
from psycopg import sql
from psycopg.types.json import Jsonb

from app.core.auth import CurrentUserDep
from app.db.database import privileged_connection, rls_connection
from app.modules.data_import.constants import CLAIMABLE_STATUSES, ImportTarget

_Rows = list[dict[str, Any]]

# The ledger's read projection. A static column set; the client display name is already
# snapshotted on the row, so no join is needed to render it.
_RUN_SELECT = "select * from public.import_runs"


class ImportTargetError(RuntimeError):
    """A row carried a column that is not in its target's allow-list.

    Unreachable through the router (``validate_mapping`` rejects it first) - which is the
    point: this is the second, independent gate, so a future caller that forgets to
    validate fails loudly here instead of writing an arbitrary column.
    """


class ImportRepo:
    """Thin RLS-scoped repository over the import ledger + its saved templates."""

    def __init__(self, user_id: str) -> None:
        self._user_id = user_id

    # --- reads ----------------------------------------------------------------
    def list_runs(
        self,
        *,
        client_id: str | None = None,
        status: str | None = None,
        source_type: str | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> _Rows:
        """The import ledger, newest first (an import is read as a timeline)."""
        query = _RUN_SELECT
        clauses: list[str] = []
        params: list[Any] = []
        if client_id is not None:
            clauses.append("client_id = %s")
            params.append(client_id)
        if status is not None:
            clauses.append("status = %s")
            params.append(status)
        if source_type is not None:
            clauses.append("source_type = %s")
            params.append(source_type)
        if clauses:
            query += " where " + " and ".join(clauses)
        query += " order by created_at desc, id"
        if limit is not None:
            query += " limit %s offset %s"
            params += [limit, offset]
        with rls_connection(self._user_id) as cur:
            cur.execute(query, params)
            return cur.fetchall()

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        with rls_connection(self._user_id) as cur:
            cur.execute(_RUN_SELECT + " where id = %s limit 1", (run_id,))
            return cur.fetchone()

    def import_stats(self) -> dict[str, Any]:
        """The summary tiles. ``imports_30d`` counts RUNS in the window; the row counters
        sum over the SAME window, so the three tiles describe one period rather than
        pairing a 30-day count with an all-time total."""
        with rls_connection(self._user_id) as cur:
            cur.execute(
                "select "
                "count(*) as imports_30d, "
                "coalesce(sum(rows_mapped), 0) as rows_mapped, "
                "coalesce(sum(rows_error), 0) as rows_error "
                "from public.import_runs where created_at >= now() - interval '30 days'"
            )
            row = cur.fetchone()
            return row or {"imports_30d": 0, "rows_mapped": 0, "rows_error": 0}

    def client_name_for(self, client_id: str) -> str | None:
        """The display name of a client the caller can see (RLS-scoped), or ``None`` -
        used to SNAPSHOT client_name so the internal client_id never surfaces."""
        with rls_connection(self._user_id) as cur:
            cur.execute("select name from public.clients where id = %s limit 1", (client_id,))
            row = cur.fetchone()
            return str(row["name"]) if row else None

    # --- mutations ------------------------------------------------------------
    def create_run(
        self,
        *,
        client_id: str | None,
        client_name: str,
        filename: str,
        stored_path: str,
        source_type: str,
        detected_columns: list[str],
        column_map: dict[str, str],
        content_sha256: str,
        uploaded_by: str,
    ) -> dict[str, Any] | None:
        """Record one uploaded file. ``stored_path`` is written here and read only by the
        worker - no response model ever projects it."""
        with rls_connection(self._user_id) as cur:
            cur.execute(
                "insert into public.import_runs "
                "(client_id, client_name, filename, stored_path, source_type, "
                "detected_columns, column_map, content_sha256, uploaded_by) "
                "values (%s, %s, %s, %s, %s, %s, %s, %s, %s) returning *",
                (
                    client_id, client_name, filename, stored_path, source_type,
                    Jsonb(detected_columns), Jsonb(column_map), content_sha256, uploaded_by,
                ),
            )
            return cur.fetchone()

    def set_mapping(self, run_id: str, column_map: dict[str, str]) -> dict[str, Any] | None:
        """Persist a VALIDATED column map and move the run to ``mapping`` (ready to
        commit). Returns ``None`` when the run is unknown/invisible."""
        with rls_connection(self._user_id) as cur:
            cur.execute(
                "update public.import_runs set column_map = %s, status = 'mapping' "
                "where id = %s returning *",
                (Jsonb(column_map), run_id),
            )
            return cur.fetchone()

    def list_mappings(self, *, source_type: str | None = None) -> _Rows:
        query = "select * from public.import_mappings"
        params: list[Any] = []
        if source_type is not None:
            query += " where source_type = %s"
            params.append(source_type)
        query += " order by source_type, name"
        with rls_connection(self._user_id) as cur:
            cur.execute(query, params)
            return cur.fetchall()

    def find_mapping_for(self, source_type: str, signature: str) -> dict[str, Any] | None:
        """The saved template whose header fingerprint matches this file exactly, if any
        - so next month's export of the same report maps itself."""
        if not signature:
            return None
        with rls_connection(self._user_id) as cur:
            cur.execute(
                "select * from public.import_mappings "
                "where source_type = %s and source_signature = %s "
                "order by created_at desc limit 1",
                (source_type, signature),
            )
            return cur.fetchone()

    def create_mapping(
        self,
        *,
        name: str,
        source_type: str,
        column_map: dict[str, str],
        source_signature: str,
        created_by: str,
    ) -> dict[str, Any] | None:
        """Save (or refresh) a reusable template.

        ``on conflict (source_type, name)`` reuses 0042's ``nulls not distinct`` unique
        verbatim, so re-saving a template under the same name UPDATES it instead of
        raising - a save button must be idempotent.
        """
        with rls_connection(self._user_id) as cur:
            cur.execute(
                "insert into public.import_mappings "
                "(name, source_type, column_map, source_signature, created_by) "
                "values (%s, %s, %s, %s, %s) "
                "on conflict (source_type, name) do update set "
                "column_map = excluded.column_map, "
                "source_signature = excluded.source_signature "
                "returning *",
                (name, source_type, Jsonb(column_map), source_signature, created_by),
            )
            return cur.fetchone()


def get_import_repo(user: CurrentUserDep) -> ImportRepo:
    """Dependency: a repo bound to the caller's verified user id (RLS-scoped)."""
    return ImportRepo(user.id)


ImportRepoDep = Annotated[ImportRepo, Depends(get_import_repo)]


# --------------------------------------------------------------------------- #
# Privileged (service_role, BYPASSRLS) store for the COMMIT worker.
# --------------------------------------------------------------------------- #
class ServiceImportStore:
    """Concrete import store over ``privileged_connection`` (BYPASSRLS).

    Stateless: each method opens its own privileged connection, so it is safe to
    instantiate per call (mirrors ``ServiceKeywordStore`` / ``ServiceRankStore``).
    """

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        with privileged_connection() as cur:
            cur.execute("select * from public.import_runs where id = %s limit 1", (run_id,))
            return cur.fetchone()

    def claim_run(self, run_id: str) -> dict[str, Any] | None:
        """CLAIM a run for import: ``uploaded|mapping|validating -> importing``, atomically.

        This is the module's idempotency guard, and it is a conditional UPDATE rather
        than a read-then-write for a reason: ``task_acks_late`` redelivers, and two
        workers reading "status = mapping" a millisecond apart would both import the
        file. The UPDATE's ``where status in (...)`` is evaluated under the row lock, so
        exactly one caller ever transitions it; everyone else gets ``None`` and no-ops.

        ``importing`` is deliberately NOT claimable, so a redelivery MID-import is a
        no-op too - which matters because ``backlinks``/``citations`` have no natural key
        to conflict on, and re-running would duplicate every row.
        """
        with privileged_connection() as cur:
            cur.execute(
                "update public.import_runs set status = 'importing' "
                "where id = %s and status = any(%s) returning *",
                (run_id, list(CLAIMABLE_STATUSES)),
            )
            return cur.fetchone()

    def update_progress(
        self, run_id: str, *, rows_total: int, rows_mapped: int, rows_error: int
    ) -> None:
        """Stream the live counters mid-import (a same-status write), so a long import is
        observable on the board instead of looking hung."""
        with privileged_connection() as cur:
            cur.execute(
                "update public.import_runs set "
                "rows_total = %s, rows_mapped = %s, rows_error = %s where id = %s",
                (rows_total, rows_mapped, rows_error, run_id),
            )

    def finish_run(
        self,
        run_id: str,
        *,
        status: str,
        rows_total: int,
        rows_mapped: int,
        rows_error: int,
        error_sample: list[dict[str, Any]],
    ) -> None:
        """Write the TERMINAL verdict + the bounded error sample. The caller has already
        capped the sample; this is the only place it is persisted."""
        with privileged_connection() as cur:
            cur.execute(
                "update public.import_runs set status = %s, rows_total = %s, "
                "rows_mapped = %s, rows_error = %s, error_sample = %s where id = %s",
                (status, rows_total, rows_mapped, rows_error, Jsonb(error_sample), run_id),
            )

    def insert_rows(self, target: ImportTarget, rows: list[dict[str, Any]]) -> int:
        """Batch-insert coerced rows into ``target.table`` THROUGH the allow-list.

        The injection boundary's last gate. Two properties make a user-supplied column
        name unreachable here, and both are deliberate:

        1. The column list is built by iterating ``target.all_columns`` - a frozen tuple
           of literals in ``constants`` - and testing membership in the row. The row's
           OWN keys are never read into an identifier, so there is no path from file
           input to SQL text even if ``validate_mapping`` were bypassed.
        2. Every row is checked against that same tuple first; an unexpected key raises
           :class:`ImportTargetError` rather than being silently dropped, so a bug
           upstream surfaces instead of half-importing.

        Every VALUE is bound. The table name and the ``on conflict`` key come from the
        same frozen target. Reuses each target's EXISTING uniqueness key verbatim
        (``do nothing``), so a re-import of an overlapping export is a no-op on the
        tables that have one; the run-claim covers the append-shaped ledgers that do not.
        """
        if target.table is None:
            raise ImportTargetError(f"'{target.source_type}' has no import target")
        if not rows:
            return 0

        allowed = set(target.all_columns)
        for row in rows:
            unknown = set(row) - allowed
            if unknown:
                raise ImportTargetError(
                    f"columns {sorted(unknown)} are not importable into {target.table}"
                )
        # Iterate the ALLOW-LIST (constants), not the row: identifiers can only ever be
        # these literals. A column no row supplies is left out entirely so the table's
        # own DEFAULT applies (``anchor text not null default ''`` would reject a NULL).
        columns = [name for name in target.all_columns if any(name in row for row in rows)]
        if not columns:
            return 0

        placeholders = sql.SQL("({})").format(
            sql.SQL(", ").join(sql.Placeholder() * len(columns))
        )
        values_sql = sql.SQL(", ").join(placeholders for _ in rows)
        params: list[Any] = []
        for row in rows:
            params += [row.get(name) for name in columns]

        # Composable, not SQL: ``.format()`` returns a Composed, so the narrower
        # annotation would not hold once the conflict clause is built.
        conflict: sql.Composable = sql.SQL("")
        if target.conflict:
            conflict = sql.SQL(" on conflict ({keys}) do nothing").format(
                keys=sql.SQL(", ").join(sql.Identifier(k) for k in target.conflict)
            )
        stmt = sql.SQL("insert into {table} ({cols}) values {vals}{conflict}").format(
            table=sql.SQL(target.table),  # a frozen literal from constants, never input
            cols=sql.SQL(", ").join(sql.Identifier(c) for c in columns),
            vals=values_sql,
            conflict=conflict,
        )
        with privileged_connection() as cur:
            cur.execute(stmt, params)
            return len(rows)


def service_import_store() -> ServiceImportStore:
    """The privileged import store the commit worker uses (service_role, BYPASSRLS)."""
    return ServiceImportStore()
