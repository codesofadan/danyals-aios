"""Data access for the citation-builder module (7B-4): ``business_profiles`` +
``directories`` (0045/0046) plus the SUBMISSION side of the existing ``citations``
ledger (0018, additively extended by 0045). Router-facing reads/writes go through
the RLS-scoped ``rls_connection``; the WORKER's privileged store lives at the bottom
(mirrors ``app/db/offpage_repo.py`` exactly - same seams, same conventions).
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import Depends
from psycopg import sql

from app.core.auth import CurrentUserDep
from app.db.database import privileged_connection, rls_connection

_Rows = list[dict[str, Any]]


class CitationsRepo:
    """Thin repository over business_profiles/directories/citations (RLS-scoped)."""

    def __init__(self, user_id: str) -> None:
        self._user_id = user_id

    # --- business profiles -----------------------------------------------------
    def list_business_profiles(self, *, client_id: str | None = None) -> _Rows:
        query = "select * from public.business_profiles"
        params: list[Any] = []
        if client_id is not None:
            query += " where client_id = %s"
            params.append(client_id)
        query += " order by is_primary desc, created_at, id"
        with rls_connection(self._user_id) as cur:
            cur.execute(query, params)
            return cur.fetchall()

    def get_business_profile(self, profile_id: str) -> dict[str, Any] | None:
        with rls_connection(self._user_id) as cur:
            cur.execute(
                "select * from public.business_profiles where id = %s limit 1", (profile_id,)
            )
            return cur.fetchone()

    def client_name_for(self, client_id: str) -> str | None:
        """The display name of a client the caller can see (RLS-scoped), or ``None``
        - mirrors ``offpage_repo.OffpageRepo.client_name_for`` (a display SNAPSHOT so
        the internal client_id never has to be surfaced on a new row)."""
        with rls_connection(self._user_id) as cur:
            cur.execute("select name from public.clients where id = %s limit 1", (client_id,))
            row = cur.fetchone()
            return str(row["name"]) if row else None

    def create_business_profile(self, *, client_name: str, fields: dict[str, Any]) -> dict[str, Any] | None:
        cols = ["client_name", *fields.keys()]
        placeholders = ", ".join(["%s"] * len(cols))
        col_sql = sql.SQL(", ").join(sql.Identifier(c) for c in cols)
        stmt = sql.SQL(
            "insert into public.business_profiles ({cols}) values ({vals}) returning *"
        ).format(cols=col_sql, vals=sql.SQL(placeholders))
        with rls_connection(self._user_id) as cur:
            cur.execute(stmt, [client_name, *fields.values()])
            return cur.fetchone()

    def update_business_profile(self, profile_id: str, changes: dict[str, Any]) -> dict[str, Any] | None:
        assignments = sql.SQL(", ").join(
            sql.SQL("{} = %s").format(sql.Identifier(c)) for c in changes
        )
        stmt = sql.SQL(
            "update public.business_profiles set {sets} where id = %s returning *"
        ).format(sets=assignments)
        with rls_connection(self._user_id) as cur:
            cur.execute(stmt, [*changes.values(), profile_id])
            return cur.fetchone()

    # --- directories catalog (reference data, not client-scoped) ----------------
    def list_directories(
        self, *, markets: list[str] | None = None, tiers: list[str] | None = None, active_only: bool = True
    ) -> _Rows:
        query = "select * from public.directories"
        clauses: list[str] = []
        params: list[Any] = []
        if active_only:
            clauses.append("active = true")
        if markets:
            clauses.append("market = any(%s)")
            params.append(markets)
        if tiers:
            clauses.append("tier = any(%s)")
            params.append(tiers)
        if clauses:
            query += " where " + " and ".join(clauses)
        query += " order by market, tier, name"
        with rls_connection(self._user_id) as cur:
            cur.execute(query, params)
            return cur.fetchall()

    def get_directory(self, directory_id: str) -> dict[str, Any] | None:
        with rls_connection(self._user_id) as cur:
            cur.execute("select * from public.directories where id = %s limit 1", (directory_id,))
            return cur.fetchone()

    # --- citation campaign dispatch (writes the SAME citations table 0018/0045) -
    def existing_citation_directory_ids(self, client_id: str) -> set[str]:
        """Every directory_id already queued/submitted for this client - the
        campaign dispatch never double-queues a directory that's already in flight
        or done for this client."""
        with rls_connection(self._user_id) as cur:
            cur.execute(
                "select directory_id from public.citations "
                "where client_id = %s and directory_id is not null",
                (client_id,),
            )
            return {str(r["directory_id"]) for r in cur.fetchall()}

    def queue_citation(
        self,
        *,
        client_id: str,
        client_name: str,
        directory_id: str,
        directory_name: str,
        business_profile_id: str,
        submit_method: str,
    ) -> dict[str, Any] | None:
        """Insert one queued citation row for a campaign. ``directory`` (the legacy
        free-text column the existing ``GET /offpage/citations`` read endpoint
        already projects) is populated from the catalog name so that endpoint keeps
        working unchanged for a submission-originated row, exactly as it does for a
        monitoring-originated one."""
        with rls_connection(self._user_id) as cur:
            cur.execute(
                "insert into public.citations "
                "(client_id, client_name, directory, nap_status, action, "
                " directory_id, business_profile_id, submit_status, submit_method) "
                "values (%s, %s, %s, 'missing', 'Submit', %s, %s, 'queued', %s) "
                "returning *",
                (client_id, client_name, directory_name, directory_id, business_profile_id, submit_method),
            )
            return cur.fetchone()


def get_citations_repo(user: CurrentUserDep) -> CitationsRepo:
    return CitationsRepo(user.id)


CitationsRepoDep = Annotated[CitationsRepo, Depends(get_citations_repo)]


# --------------------------------------------------------------------------- #
# Privileged (service_role, BYPASSRLS) store for the citation_submit_job WORKER.
# Mirrors ServiceOffpageStore exactly - each method opens its own connection, so
# the store is stateless and safe to instantiate per call.
# --------------------------------------------------------------------------- #
class ServiceCitationsStore:
    """Concrete citation-submission store over ``privileged_connection``."""

    def load_citation_with_directory(self, citation_id: str) -> dict[str, Any] | None:
        """One citation row JOINed with its directory catalog row (the worker needs
        both: the NAP to submit and which engine/tier handles it) plus its
        business_profile row's NAP fields, all flattened into one dict."""
        with privileged_connection() as cur:
            cur.execute(
                "select c.*, "
                "  d.name as directory_name, d.url as directory_url, d.tier as directory_tier, "
                "  d.market as directory_market, d.submit_method as directory_submit_method, "
                "  bp.business_name as bp_business_name, bp.address_line1 as bp_address_line1, "
                "  bp.address_line2 as bp_address_line2, bp.city as bp_city, bp.region as bp_region, "
                "  bp.postal_code as bp_postal_code, bp.phone as bp_phone, "
                "  bp.website_url as bp_website_url, bp.categories as bp_categories "
                "from public.citations c "
                "left join public.directories d on d.id = c.directory_id "
                "left join public.business_profiles bp on bp.id = c.business_profile_id "
                "where c.id = %s limit 1",
                (citation_id,),
            )
            return cur.fetchone()

    def update_citation(self, citation_id: str, fields: dict[str, Any]) -> None:
        if not fields:
            return
        assignments = sql.SQL(", ").join(
            sql.SQL("{} = %s").format(sql.Identifier(c)) for c in fields
        )
        stmt = sql.SQL("update public.citations set {sets} where id = %s").format(sets=assignments)
        with privileged_connection() as cur:
            cur.execute(stmt, [*fields.values(), citation_id])


def service_citations_store() -> ServiceCitationsStore:
    """The privileged citations store the citation_submit_job worker uses."""
    return ServiceCitationsStore()
