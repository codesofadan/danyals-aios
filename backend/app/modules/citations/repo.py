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
from psycopg.types.json import Jsonb

from app.core.auth import CurrentUserDep
from app.db.database import privileged_connection, rls_connection

_Rows = list[dict[str, Any]]


def _adapt_jsonb(fields: dict[str, Any]) -> dict[str, Any]:
    """Wrap the ``hours`` dict in ``Jsonb`` so it binds cleanly into the jsonb column -
    psycopg3 will not adapt a raw ``dict`` through a ``%s`` placeholder (mirrors
    ``policy_repo``/``context_repo``'s jsonb handling). ``categories`` is ``text[]``,
    which psycopg adapts from a list natively, so only ``hours`` needs wrapping."""
    if isinstance(fields.get("hours"), dict):
        return {**fields, "hours": Jsonb(fields["hours"])}
    return fields


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

    def client_meta_for(self, client_id: str) -> dict[str, Any] | None:
        """``{name, industry}`` for a client the caller can see (RLS-scoped), or
        ``None``. ``industry`` drives the campaign's vertical resolution - it is a
        free-text column, normalized to a vertical key by ``verticals.normalize_vertical``."""
        with rls_connection(self._user_id) as cur:
            cur.execute(
                "select name, industry from public.clients where id = %s limit 1", (client_id,)
            )
            return cur.fetchone()

    def create_business_profile(
        self, *, client_id: str, client_name: str, fields: dict[str, Any]
    ) -> dict[str, Any] | None:
        # client_id is stored (NOT NULL FK + the tenant link) AND client_name is a
        # display snapshot; the response model exposes only the name, so the id never
        # leaks on the wire but the row is still correctly tenant-scoped.
        fields = _adapt_jsonb(fields)
        cols = ["client_id", "client_name", *fields.keys()]
        placeholders = ", ".join(["%s"] * len(cols))
        col_sql = sql.SQL(", ").join(sql.Identifier(c) for c in cols)
        stmt = sql.SQL(
            "insert into public.business_profiles ({cols}) values ({vals}) returning *"
        ).format(cols=col_sql, vals=sql.SQL(placeholders))
        with rls_connection(self._user_id) as cur:
            cur.execute(stmt, [client_id, client_name, *fields.values()])
            return cur.fetchone()

    def update_business_profile(self, profile_id: str, changes: dict[str, Any]) -> dict[str, Any] | None:
        changes = _adapt_jsonb(changes)
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
        self,
        *,
        markets: list[str] | None = None,
        tiers: list[str] | None = None,
        vertical: str | None = None,
        active_only: bool = True,
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
        if vertical:
            # A general directory (no verticals) serves every client; a niche one only
            # its own vertical. GIN-indexed (0048) so this stays cheap on the catalog.
            clauses.append("(cardinality(verticals) = 0 or %s = any(verticals))")
            params.append(vertical)
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

    def stale_directories(self, *, older_than_days: int = 90, limit: int = 100) -> _Rows:
        """Active catalog rows never verified, or not verified within the window - the
        candidates the verify-live health-check (P4) re-checks. Oldest/never-checked
        first, so a bounded batch always makes progress across the whole catalog."""
        with rls_connection(self._user_id) as cur:
            cur.execute(
                "select id, name, url from public.directories "
                "where active = true and url <> '' "
                "and (last_verified is null or last_verified < now() - make_interval(days => %s)) "
                "order by last_verified asc nulls first limit %s",
                (older_than_days, limit),
            )
            return cur.fetchall()

    def mark_directory_verified(self, directory_id: str, *, alive: bool) -> None:
        """Stamp a directory's ``last_verified`` and DEACTIVATE it if the URL is dead
        (churn: a 2019-era entry that is now parked). Never deletes - a churned
        directory can come back, and reporting wants the row. Catalog maintenance is a
        system operation, so it runs on the privileged (service_role) connection."""
        with privileged_connection() as cur:
            cur.execute(
                "update public.directories set last_verified = now(), active = %s where id = %s",
                (alive, directory_id),
            )

    # --- citation campaign dispatch (writes the SAME citations table 0018/0045) -
    def existing_citation_directory_ids(self, client_id: str) -> set[str]:
        """Every directory_id already IN FLIGHT or DONE for this client - the
        campaign dispatch never double-queues those. A ``blocked``/``failed`` row is
        deliberately NOT in this set: those are retryable outcomes (a past cost-gate
        hold or engine outage), and the next campaign RE-QUEUES them via
        :meth:`requeueable_citations` instead of skipping the directory forever."""
        with rls_connection(self._user_id) as cur:
            cur.execute(
                "select directory_id from public.citations "
                "where client_id = %s and directory_id is not null "
                "and coalesce(submit_status::text, 'not_started') not in ('blocked', 'failed')",
                (client_id,),
            )
            return {str(r["directory_id"]) for r in cur.fetchall()}

    def requeueable_citations(self, client_id: str) -> dict[str, str]:
        """``{directory_id: citation_id}`` for this client's ``blocked``/``failed``
        rows - the retry surface a new campaign RESETS instead of re-inserting."""
        with rls_connection(self._user_id) as cur:
            cur.execute(
                "select id, directory_id from public.citations "
                "where client_id = %s and directory_id is not null "
                "and submit_status in ('blocked', 'failed')",
                (client_id,),
            )
            return {str(r["directory_id"]): str(r["id"]) for r in cur.fetchall()}

    def requeue_citation(self, citation_id: str) -> dict[str, Any] | None:
        """Reset one blocked/failed row back to ``queued`` (clearing the stale
        error) so the submit worker picks it up again."""
        with rls_connection(self._user_id) as cur:
            cur.execute(
                "update public.citations "
                "set submit_status = 'queued', error = '', action = 'Submit' "
                "where id = %s and submit_status in ('blocked', 'failed') "
                "returning *",
                (citation_id,),
            )
            return cur.fetchone()

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
