"""Data access for the Off-page ledgers (``backlinks`` / ``citations`` /
``web2_properties``) via the RLS-scoped ``rls_connection`` seam.

Every read + mutation is tenant/actor-scoped by Postgres RLS: staff read the whole
board, clients are excluded (no base-table select policy), and only leads (owner/
admin/manager) may write (the RLS insert/update policies + the paid-tier gate at the
service layer). Methods are synchronous (psycopg is sync) - the router offloads them
with ``asyncio.to_thread`` - and the single ``get_offpage_repo`` dependency makes the
layer trivially replaceable with an in-memory fake in tests.

SQL rules (impersonation-review mandate): every VALUE is a bound param (``%s``),
never string-formatted; table/column names are static literals and the only dynamic
column lists come from server-built dicts quoted via ``psycopg.sql.Identifier``.
"""

from __future__ import annotations

from datetime import date
from typing import Annotated, Any

from fastapi import Depends
from psycopg import sql

from app.core.auth import CurrentUserDep
from app.db.database import privileged_connection, rls_connection

_Rows = list[dict[str, Any]]


class OffpageRepo:
    """Thin repository over the three off-page monitoring tables (RLS-scoped)."""

    def __init__(self, user_id: str) -> None:
        self._user_id = user_id

    # --- backlinks ------------------------------------------------------------
    def list_backlinks(
        self,
        *,
        status: str | None = None,
        client_id: str | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> _Rows:
        # OWN-PROFILE INVARIANT (0037): `backlinks` also carries COMPETITOR-side rows
        # (competitor_id set). Every off-page read is the CLIENT's own profile, so it
        # MUST pin competitor_id is null - otherwise the board would show a rival's
        # links as the client's own. Pinned by tests/test_backlinks_own_profile.py.
        query = "select * from public.backlinks"
        clauses: list[str] = ["competitor_id is null"]
        params: list[Any] = []
        if status is not None:
            clauses.append("status = %s")
            params.append(status)
        if client_id is not None:
            clauses.append("client_id = %s")
            params.append(client_id)
        if clauses:
            query += " where " + " and ".join(clauses)
        # Freshest discoveries first; id keeps the order stable across equal dates.
        query += " order by first_seen desc nulls last, created_at desc, id"
        if limit is not None:
            query += " limit %s offset %s"
            params += [limit, offset]
        with rls_connection(self._user_id) as cur:
            cur.execute(query, params)
            return cur.fetchall()

    def backlink_status_counts(self) -> dict[str, int]:
        """A ``{status: count}`` breakdown over the caller-visible backlinks (feeds
        the new/lost/toxic KPI tiles). RLS-scoped; an empty ledger yields ``{}``."""
        with rls_connection(self._user_id) as cur:
            cur.execute(
                "select status, count(*) as n from public.backlinks "
                "where competitor_id is null group by status"
            )
            return {str(r["status"]): int(r["n"]) for r in cur.fetchall()}

    def referring_domain_count(self) -> int:
        """The live profile size: distinct referring domains over non-lost backlinks
        (a lost link is no longer part of the profile)."""
        with rls_connection(self._user_id) as cur:
            cur.execute(
                "select count(distinct ref_domain) as n from public.backlinks "
                "where competitor_id is null and status <> 'lost'"
            )
            row = cur.fetchone()
            return int(row["n"]) if row else 0

    def new_backlink_count(self, *, days: int) -> int:
        """How many links were DISCOVERED in the last ``days`` (the growth tile).

        Additive read for the ``backlink_manager`` tool workspace (Part 8 Phase 2.5),
        which needs a WINDOWED count: ``backlink_status_counts`` is all-time, so it
        cannot answer "new links (30d)" without inventing the window. Counts by
        ``first_seen`` (the discovery date), not ``created_at``: a link is new when the
        crawler first SAW it, not when this row happened to be written. RLS-scoped.
        """
        with rls_connection(self._user_id) as cur:
            cur.execute(
                "select count(*) as n from public.backlinks "
                "where competitor_id is null and status = 'new' "
                "and first_seen >= current_date - %s::int",
                (days,),
            )
            row = cur.fetchone()
            return int(row["n"]) if row else 0

    def web2_publish_stats(self, *, days: int) -> dict[str, int]:
        """The Web 2.0 publish tiles in ONE pass: scheduled / failed / published(window).

        Additive read for the ``publishing`` tool workspace (Part 8 Phase 2.5). The
        ``filter (where ...)`` form computes every tile in a single scan (mirrors
        ``team_metrics._TASK_AGG_SQL``). ``published`` is windowed on ``published_at``
        (the live date), the other two are current state and inherently un-windowed.
        RLS-scoped; an empty ledger yields all zeros.
        """
        with rls_connection(self._user_id) as cur:
            cur.execute(
                "select "
                "count(*) filter (where status = 'publishing')::int as scheduled, "
                "count(*) filter (where status = 'failed')::int as failed, "
                "count(*) filter (where status = 'published' "
                "  and published_at >= current_date - %s::int)::int as published "
                "from public.web2_properties",
                (days,),
            )
            row = cur.fetchone()
            if row is None:  # pragma: no cover - an aggregate always yields one row
                return {"scheduled": 0, "failed": 0, "published": 0}
            return {k: int(v or 0) for k, v in row.items()}

    def flag_toxic_backlinks(self, *, spam_threshold: int) -> _Rows:
        """Flag every backlink at/above ``spam_threshold`` spam as ``toxic`` (the
        disavow-review queue). Idempotent: rows already ``toxic`` are skipped, so a
        re-run flags only newly-spammy links. Returns the rows it moved.

        OWN-PROFILE INVARIANT (0037): pins ``competitor_id is null``. This is a WRITE,
        so the stake is higher than a read - without the pin a COMPETITOR's spammy
        links would be flagged toxic into THIS client's disavow queue, i.e. the client
        would be asked to disavow a rival's links.
        """
        with rls_connection(self._user_id) as cur:
            cur.execute(
                "update public.backlinks set status = 'toxic' "
                "where competitor_id is null and spam >= %s and status <> 'toxic' "
                "returning *",
                (spam_threshold,),
            )
            return cur.fetchall()

    # --- citations ------------------------------------------------------------
    def list_citations(
        self,
        *,
        nap_status: str | None = None,
        client_id: str | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> _Rows:
        query = "select * from public.citations"
        clauses: list[str] = []
        params: list[Any] = []
        if nap_status is not None:
            clauses.append("nap_status = %s")
            params.append(nap_status)
        if client_id is not None:
            clauses.append("client_id = %s")
            params.append(client_id)
        if clauses:
            query += " where " + " and ".join(clauses)
        query += " order by created_at desc, id"
        if limit is not None:
            query += " limit %s offset %s"
            params += [limit, offset]
        with rls_connection(self._user_id) as cur:
            cur.execute(query, params)
            return cur.fetchall()

    def get_citation(self, citation_id: str) -> dict[str, Any] | None:
        with rls_connection(self._user_id) as cur:
            cur.execute(
                "select * from public.citations where id = %s limit 1", (citation_id,)
            )
            return cur.fetchone()

    def update_citation(
        self, citation_id: str, changes: dict[str, Any]
    ) -> dict[str, Any] | None:
        """Update one citation by id, returning the updated row or ``None``."""
        cols = list(changes.keys())
        assignments = sql.SQL(", ").join(
            sql.SQL("{} = %s").format(sql.Identifier(c)) for c in cols
        )
        stmt = sql.SQL(
            "update public.citations set {sets} where id = %s returning *"
        ).format(sets=assignments)
        with rls_connection(self._user_id) as cur:
            cur.execute(stmt, [*changes.values(), citation_id])
            return cur.fetchone()

    def bulk_update_citations(
        self, ids: list[str], changes: dict[str, Any]
    ) -> _Rows:
        """Apply ``changes`` to every citation in ``ids`` in ONE statement, returning
        the updated rows. Empty ``ids`` is a no-op (no query). Only the rows RLS lets
        the caller see/write are affected."""
        if not ids:
            return []
        cols = list(changes.keys())
        assignments = sql.SQL(", ").join(
            sql.SQL("{} = %s").format(sql.Identifier(c)) for c in cols
        )
        stmt = sql.SQL(
            "update public.citations set {sets} where id::text = any(%s) returning *"
        ).format(sets=assignments)
        with rls_connection(self._user_id) as cur:
            cur.execute(stmt, [*changes.values(), ids])
            return cur.fetchall()

    # --- web 2.0 --------------------------------------------------------------
    def list_web2(
        self,
        *,
        client_id: str | None = None,
        platform: str | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> _Rows:
        query = "select * from public.web2_properties"
        clauses: list[str] = []
        params: list[Any] = []
        if client_id is not None:
            clauses.append("client_id = %s")
            params.append(client_id)
        if platform is not None:
            clauses.append("platform = %s")
            params.append(platform)
        if clauses:
            query += " where " + " and ".join(clauses)
        query += " order by published_at desc nulls last, created_at desc, id"
        if limit is not None:
            query += " limit %s offset %s"
            params += [limit, offset]
        with rls_connection(self._user_id) as cur:
            cur.execute(query, params)
            return cur.fetchall()

    def client_name_for(self, client_id: str) -> str | None:
        """The display name of a client the caller can see (RLS-scoped), or ``None`` if
        it does not exist / is not visible - used to SNAPSHOT client_name on a new
        placement so the internal client_id never has to be surfaced."""
        with rls_connection(self._user_id) as cur:
            cur.execute(
                "select name from public.clients where id = %s limit 1", (client_id,)
            )
            row = cur.fetchone()
            return str(row["name"]) if row else None

    def create_web2(
        self,
        *,
        client_id: str,
        client_name: str,
        platform: str,
        anchor: str,
        target_url: str,
        topic: str,
        page_type: str,
        framework: str,
    ) -> dict[str, Any] | None:
        """Insert a PLANNED Web 2.0 placement (status ``draft``) and return the row.

        Lead-only by RLS (the web2_properties insert policy). ``client_name`` is a
        display SNAPSHOT; the write worker fills the drafted body + flips the status."""
        with rls_connection(self._user_id) as cur:
            cur.execute(
                "insert into public.web2_properties "
                "(client_id, client_name, platform, anchor, target_url, topic, "
                "page_type, framework, status) "
                "values (%s, %s, %s, %s, %s, %s, %s, %s, 'draft') returning *",
                (
                    client_id, client_name, platform, anchor, target_url, topic,
                    page_type, framework,
                ),
            )
            return cur.fetchone()

    def get_web2(self, web2_id: str) -> dict[str, Any] | None:
        with rls_connection(self._user_id) as cur:
            cur.execute(
                "select * from public.web2_properties where id = %s limit 1", (web2_id,)
            )
            return cur.fetchone()

    def update_web2_status(
        self, web2_id: str, changes: dict[str, Any]
    ) -> dict[str, Any] | None:
        """Update one Web 2.0 placement by id (lead-only by RLS), returning the row.

        Column names are static ``sql.Identifier``s (never a bound param); values are
        always bound - the impersonation-review SQL rule."""
        cols = list(changes.keys())
        assignments = sql.SQL(", ").join(
            sql.SQL("{} = %s").format(sql.Identifier(c)) for c in cols
        )
        stmt = sql.SQL(
            "update public.web2_properties set {sets} where id = %s returning *"
        ).format(sets=assignments)
        with rls_connection(self._user_id) as cur:
            cur.execute(stmt, [*changes.values(), web2_id])
            return cur.fetchone()


def get_offpage_repo(user: CurrentUserDep) -> OffpageRepo:
    """Dependency: a repo bound to the caller's verified user id (RLS-scoped)."""
    return OffpageRepo(user.id)


OffpageRepoDep = Annotated[OffpageRepo, Depends(get_offpage_repo)]


# --------------------------------------------------------------------------- #
# Privileged (service_role, BYPASSRLS) store for the WORKERS.
# --------------------------------------------------------------------------- #
# The publish + monitoring workers have no user JWT, so - exactly like the audit /
# context workers - they read/write the off-page ledgers on the privileged connection
# (service_role bypasses the RLS policies by design; 0018's header notes the monitoring
# ingest path runs here). Each method opens its own privileged connection, so the store
# is stateless and safe to instantiate per call. It satisfies ``web2_pipeline.Web2Store``
# structurally (load_web2 / update_web2).
class ServiceOffpageStore:
    """Concrete off-page store over ``privileged_connection`` (BYPASSRLS)."""

    # --- web 2.0 (the publish pipeline's Web2Store) ---------------------------
    def load_web2(self, web2_id: str) -> dict[str, Any] | None:
        with privileged_connection() as cur:
            cur.execute(
                "select * from public.web2_properties where id = %s limit 1", (web2_id,)
            )
            return cur.fetchone()

    def update_web2(self, web2_id: str, fields: dict[str, Any]) -> None:
        if not fields:
            return
        cols = list(fields.keys())
        assignments = sql.SQL(", ").join(
            sql.SQL("{} = %s").format(sql.Identifier(c)) for c in cols
        )
        stmt = sql.SQL(
            "update public.web2_properties set {sets} where id = %s"
        ).format(sets=assignments)
        with privileged_connection() as cur:
            cur.execute(stmt, [*fields.values(), web2_id])

    # --- backlinks (monitoring diff/apply) ------------------------------------
    def list_backlinks_for_client(self, client_id: str) -> _Rows:
        with privileged_connection() as cur:
            cur.execute(
                "select * from public.backlinks "
                "where client_id = %s and competitor_id is null",
                (client_id,),
            )
            return cur.fetchall()

    def insert_backlink(
        self,
        *,
        client_id: str | None,
        client_name: str,
        ref_domain: str,
        anchor: str,
        authority: int,
        spam: int,
        first_seen: date | None,
        status: str,
    ) -> None:
        with privileged_connection() as cur:
            cur.execute(
                "insert into public.backlinks "
                "(client_id, client_name, ref_domain, anchor, authority, spam, "
                "first_seen, status) values (%s, %s, %s, %s, %s, %s, %s, %s)",
                (
                    client_id, client_name, ref_domain, anchor, authority, spam,
                    first_seen, status,
                ),
            )

    def set_backlink_status(self, backlink_id: str, status: str) -> None:
        """Move one OWN-PROFILE backlink's status (the monitoring new/lost diff).

        OWN-PROFILE INVARIANT (0037): pins ``competitor_id is null`` even though the
        id already targets a single row. This runs on the PRIVILEGED (BYPASSRLS) seam,
        so the pin is the only thing standing between a mis-sourced id and the monitor
        silently rewriting a COMPETITOR-side row's status. Safe-by-construction beats
        safe-because-every-caller-currently-passes-an-own-profile-id.
        """
        with privileged_connection() as cur:
            cur.execute(
                "update public.backlinks set status = %s "
                "where id = %s and competitor_id is null",
                (status, backlink_id),
            )

    # --- citations (monitoring diff/apply) ------------------------------------
    def list_citations_for_client(self, client_id: str) -> _Rows:
        with privileged_connection() as cur:
            cur.execute(
                "select * from public.citations where client_id = %s", (client_id,)
            )
            return cur.fetchall()

    def insert_citation(
        self,
        *,
        client_id: str | None,
        client_name: str,
        directory: str,
        nap_status: str,
        action: str,
        note: str,
    ) -> None:
        with privileged_connection() as cur:
            cur.execute(
                "insert into public.citations "
                "(client_id, client_name, directory, nap_status, action, note) "
                "values (%s, %s, %s, %s, %s, %s)",
                (client_id, client_name, directory, nap_status, action, note),
            )

    def update_citation_status(
        self, citation_id: str, *, nap_status: str, action: str, note: str
    ) -> None:
        with privileged_connection() as cur:
            cur.execute(
                "update public.citations set nap_status = %s, action = %s, note = %s "
                "where id = %s",
                (nap_status, action, note, citation_id),
            )


def service_offpage_store() -> ServiceOffpageStore:
    """The privileged off-page store the workers use (service_role, BYPASSRLS)."""
    return ServiceOffpageStore()
