"""Data access for the citation-builder module (7B-4): ``business_profiles`` +
``directories`` (0045/0046) plus the SUBMISSION side of the existing ``citations``
ledger (0018, additively extended by 0045). Router-facing reads/writes go through
the RLS-scoped ``rls_connection``; the WORKER's privileged store lives at the bottom
(mirrors ``app/db/offpage_repo.py`` exactly - same seams, same conventions).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import Depends
from psycopg import sql
from psycopg.types.json import Jsonb

from app.core.auth import CurrentUserDep
from app.db.database import DatabaseNotConfiguredError, privileged_connection, rls_connection
from app.modules.citations.service import derive_business_profile_fields


def _now_iso() -> str:
    """UTC now as an ISO string, for jsonb audit payloads."""
    return datetime.now(UTC).isoformat()

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

    def get_citation(self, citation_id: str) -> dict[str, Any] | None:
        """One citation the CALLER can see. RLS-scoped on purpose: the proof-download
        route resolves a filesystem key from this row, so the tenant check has to happen
        in the database rather than in the route - a staff member who cannot see the
        citation must not be able to read its screenshot by guessing an id."""
        with rls_connection(self._user_id) as cur:
            cur.execute("select * from public.citations where id = %s limit 1", (citation_id,))
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

    def client_business_profile_for(self, client_id: str) -> dict[str, Any] | None:
        """The client's OWN stored NAP (``client_business_profiles``, 0051) - the
        identity captured at creation. ``None`` when the wizard skipped it (or the
        client is invisible to the caller). RLS-scoped."""
        with rls_connection(self._user_id) as cur:
            cur.execute(
                "select * from public.client_business_profiles where client_id = %s limit 1",
                (client_id,),
            )
            return cur.fetchone()

    def ensure_business_profile(
        self, *, client_id: str, client_name: str
    ) -> dict[str, Any] | None:
        """Return a SUBMISSION ``business_profiles`` row for a client, deriving one from
        the client's own NAP (0051) when none exists yet.

        This is the fix for "No business profile yet for this client": the operator no
        longer has to re-enter a NAP the Add-Client wizard already collected. Prefers an
        existing primary profile; else derives + inserts one from
        ``client_business_profiles`` (only when that NAP carries a business name -
        deriving an empty profile would just move the "no NAP" problem downstream);
        else ``None`` (the caller reports the honest "capture a NAP first")."""
        existing = self.list_business_profiles(client_id=client_id)
        if existing:
            return existing[0]  # already sorted is_primary desc, created_at
        client_nap = self.client_business_profile_for(client_id)
        if client_nap is None or not str(client_nap.get("business_name") or "").strip():
            return None
        fields = derive_business_profile_fields(client_nap)
        return self.create_business_profile(
            client_id=client_id, client_name=client_name, fields=fields
        )

    def list_citations_for_client(self, client_id: str) -> _Rows:
        """Every citation row for a client (submission + monitoring), for gap analysis -
        the columns the pure ``compute_citation_gap`` reads. RLS-scoped.

        `live_url` is REQUIRED here, not optional. `compute_citation_gap` reads it to
        build the live-listings list, and a projection that omits it makes every live
        citation report as having no URL - the fix in service.py would be correct and
        produce nothing, which is a worse failure than the bug it replaced because it
        looks like an empty result rather than an error. `proof_url` stays because the
        board links the proof screenshot; the two are never interchangeable."""
        with rls_connection(self._user_id) as cur:
            cur.execute(
                "select id, directory, directory_id, nap_status, submit_status, "
                "       proof_url, live_url "
                "from public.citations where client_id = %s",
                (client_id,),
            )
            return cur.fetchall()

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

    # --- NAP change fan-out (0107) ----------------------------------------------
    def citations_for_profile(self, profile_id: str) -> _Rows:
        """Every citation built from this business profile, with just the columns the
        staleness decision needs. RLS-scoped: a lead can only fan out across a tenant
        they can already see."""
        with rls_connection(self._user_id) as cur:
            cur.execute(
                "select id, directory, submit_status from public.citations "
                "where business_profile_id = %s",
                (profile_id,),
            )
            return cur.fetchall()

    def record_nap_change(
        self,
        *,
        client_id: str,
        profile_id: str,
        events: list[dict[str, str]],
        citation_ids: list[str],
    ) -> int:
        """Write the change ledger and flag the listings it made stale, in ONE
        transaction.

        Atomic on purpose: a change row without its fan-out would claim the listings had
        been dealt with, and a fan-out without its change row would leave operators
        looking at flagged citations with no explanation of what moved. Either both facts
        land or neither does.

        Returns the number of citations flagged. Zero is a legitimate answer - the client
        may simply have no live listings yet - and it is recorded in `fanout_state` so
        "it ran and found none" stays distinguishable from "it never ran"."""
        if not events:
            return 0
        flagged = 0
        with rls_connection(self._user_id) as cur:
            for event in events:
                cur.execute(
                    "insert into public.client_change_events "
                    "  (client_id, business_profile_id, field, old_value, new_value, fanout_state) "
                    "values (%s, %s, %s, %s, %s, %s)",
                    (
                        client_id,
                        profile_id,
                        event["field"],
                        event["old_value"],
                        event["new_value"],
                        Jsonb({"citations_flagged": len(citation_ids), "at": _now_iso()}),
                    ),
                )
            if citation_ids:
                # `drifted`, because that is what these listings now ARE: they exist and
                # they no longer match us. The CAUSE goes in the evidence - a status says
                # what is true, not how it came to be.
                cur.execute(
                    "update public.citations set "
                    "  submit_status = 'drifted', "
                    "  verification_evidence = %s "
                    "where id = any(%s) ",
                    (
                        Jsonb({"reason": "canonical_nap_changed", "at": _now_iso()}),
                        citation_ids,
                    ),
                )
                flagged = cur.rowcount or 0
        return flagged

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


class CitationQueueRepo:
    """The human work queue (0110), RLS-scoped to the operator working it.

    Every method here runs on ``rls_connection`` and never on the privileged pool. That
    is deliberate and it is the tenant boundary: an operator must only ever be able to
    claim, read or complete an item for a client they can already see, and the cheapest
    way to guarantee that is to let Postgres decide rather than to remember a WHERE
    clause in five different methods."""

    def __init__(self, user_id: str) -> None:
        self._user_id = user_id

    def claim_next(self, *, lease_seconds: int, client_id: str | None = None) -> dict[str, Any] | None:
        """Take the next available queue item, or ``None`` when the queue is empty.

        ``for update skip locked`` is what makes this safe with several operators
        working at once: two simultaneous claims take two different rows instead of
        fighting over one, and neither blocks. Without ``skip locked`` the second
        operator waits on the first's lock and then claims the row the first just took.

        An item is available when it is unclaimed OR its lease has lapsed. A claim is a
        LEASE and not a lock precisely so a closed laptop cannot strand work: the item
        returns to the pool on its own, and `human_attempts` records that someone had it
        and did not finish - which over time is how a directory earns its way OFF the
        offer list."""
        with rls_connection(self._user_id) as cur:
            cur.execute(
                "with candidate as ( "
                "  select c.id from public.citations c "
                "  where c.submit_status = 'ready_for_human' "
                "    and (c.claimed_by is null or c.claim_expires_at < now()) "
                "    and (%(client_id)s::uuid is null or c.client_id = %(client_id)s::uuid) "
                "  order by c.created_at "
                "  for update of c skip locked "
                "  limit 1 "
                ") "
                "update public.citations set "
                "  claimed_by = %(user_id)s::uuid, "
                "  claimed_at = now(), "
                "  claim_expires_at = now() + make_interval(secs => %(lease)s), "
                "  human_attempts = human_attempts + 1 "
                "from candidate where public.citations.id = candidate.id "
                "returning public.citations.*",
                {
                    "client_id": client_id,
                    "user_id": self._user_id,
                    "lease": lease_seconds,
                },
            )
            return cur.fetchone()

    def held_item(self, citation_id: str) -> dict[str, Any] | None:
        """The item, but ONLY if this operator currently holds an unexpired claim on it.

        Every mutating queue call goes through this first. Checking the holder in the
        WHERE clause rather than in Python means a lapsed or stolen claim cannot be
        written through by a client that simply kept the id around."""
        with rls_connection(self._user_id) as cur:
            cur.execute(
                "select c.*, d.name as directory_name, d.url as directory_url, "
                "       d.add_url as directory_add_url, d.tier as directory_tier, "
                "       d.route as directory_route, d.tos_position as directory_tos_position, "
                "       d.tos_clause as directory_tos_clause, "
                "       d.tos_source_url as directory_tos_source_url, "
                "       bp.business_name as bp_business_name, bp.address_line1 as bp_address_line1, "
                "       bp.address_line2 as bp_address_line2, bp.city as bp_city, "
                "       bp.region as bp_region, bp.postal_code as bp_postal_code, "
                "       bp.phone as bp_phone, bp.website_url as bp_website_url, "
                "       bp.categories as bp_categories, bp.description as bp_description, "
                "       bp.email as bp_email, bp.hours as bp_hours "
                "from public.citations c "
                "left join public.directories d on d.id = c.directory_id "
                "left join public.business_profiles bp on bp.id = c.business_profile_id "
                "where c.id = %s and c.claimed_by = %s::uuid and c.claim_expires_at > now() "
                "limit 1",
                (citation_id, self._user_id),
            )
            return cur.fetchone()

    def extend_claim(self, citation_id: str, *, lease_seconds: int, worked_seconds: int) -> bool:
        """Heartbeat: push the lease out and bank the time worked so far.

        Time is ACCUMULATED, not replaced, so an item picked up twice still totals
        correctly - and so a crash loses at most one heartbeat's worth of measurement
        rather than the whole session."""
        with rls_connection(self._user_id) as cur:
            cur.execute(
                "update public.citations set "
                "  claim_expires_at = now() + make_interval(secs => %s), "
                "  worked_seconds = worked_seconds + %s "
                "where id = %s and claimed_by = %s::uuid and claim_expires_at > now()",
                (lease_seconds, max(0, worked_seconds), citation_id, self._user_id),
            )
            return (cur.rowcount or 0) > 0

    def release_claim(self, citation_id: str, *, worked_seconds: int = 0) -> bool:
        """Give the item back without completing it. The attempt still counts."""
        with rls_connection(self._user_id) as cur:
            cur.execute(
                "update public.citations set "
                "  claimed_by = null, claimed_at = null, claim_expires_at = null, "
                "  worked_seconds = worked_seconds + %s "
                "where id = %s and claimed_by = %s::uuid",
                (max(0, worked_seconds), citation_id, self._user_id),
            )
            return (cur.rowcount or 0) > 0

    def complete_item(
        self,
        citation_id: str,
        *,
        live_url: str,
        submit_status: str,
        evidence: dict[str, Any],
        worked_seconds: int,
        note: str = "",
    ) -> dict[str, Any] | None:
        """Close an item WITH a verified listing URL.

        The caller must have already run the liveness check and be passing its verdict -
        this method does not decide liveness, it records a decision that was made. That
        split is deliberate: completion is the one place an operator could assert
        something the system never saw, so the assertion has to be checked before it
        reaches the database, and the check has to be the same one the re-check uses."""
        with rls_connection(self._user_id) as cur:
            cur.execute(
                "update public.citations set "
                "  submit_status = %s, live_url = %s, live_url_verified_at = now(), "
                "  verification_method = 'human', verification_evidence = %s, "
                "  submitted_at = coalesce(submitted_at, now()), "
                "  worked_seconds = worked_seconds + %s, operator_note = %s, "
                "  claimed_by = null, claimed_at = null, claim_expires_at = null, "
                "  next_recheck_at = now() + interval '3 days' "
                "where id = %s and claimed_by = %s::uuid "
                "returning *",
                (
                    submit_status,
                    live_url,
                    Jsonb(evidence),
                    max(0, worked_seconds),
                    note[:2000],
                    citation_id,
                    self._user_id,
                ),
            )
            return cur.fetchone()

    def block_item(
        self, citation_id: str, *, reason: str, detail: str, worked_seconds: int
    ) -> dict[str, Any] | None:
        """Close an item as NOT DONE, with a machine-readable reason.

        This is as important as completion and is the option operators will reach for
        most often. A queue whose only exit is "success" trains people to fake success -
        so `blocked` is a first-class, one-click outcome that costs the operator nothing
        to report honestly."""
        with rls_connection(self._user_id) as cur:
            cur.execute(
                "update public.citations set "
                "  submit_status = 'blocked', blocked_reason = %s, error = %s, "
                "  worked_seconds = worked_seconds + %s, "
                "  claimed_by = null, claimed_at = null, claim_expires_at = null "
                "where id = %s and claimed_by = %s::uuid "
                "returning *",
                (reason, detail[:500], max(0, worked_seconds), citation_id, self._user_id),
            )
            return cur.fetchone()

    def queue_stats(self) -> dict[str, Any]:
        """Depth, work in flight, and the MEDIAN minutes per finished item.

        The median and not the mean: one item where an operator went to lunch mid-claim
        would drag a mean far enough to make the whole cost model wrong, and this number
        feeds the cost model. Returns ``None`` for the median until something has
        actually been finished - an unmeasured number must read as unmeasured, not as
        zero."""
        with rls_connection(self._user_id) as cur:
            cur.execute(
                "select "
                "  count(*) filter (where submit_status = 'ready_for_human') as waiting, "
                "  count(*) filter (where claimed_by is not null "
                "                     and claim_expires_at > now()) as in_progress, "
                "  percentile_cont(0.5) within group (order by worked_seconds) "
                "    filter (where worked_seconds > 0 "
                "              and submit_status in ('live', 'submitted', 'blocked')) "
                "    as median_seconds "
                "from public.citations"
            )
            row = cur.fetchone()
            return dict(row) if row else {"waiting": 0, "in_progress": 0, "median_seconds": None}


def get_citations_repo(user: CurrentUserDep) -> CitationsRepo:
    return CitationsRepo(user.id)


def get_citation_queue_repo(user: CurrentUserDep) -> CitationQueueRepo:
    return CitationQueueRepo(user.id)


CitationQueueRepoDep = Annotated[CitationQueueRepo, Depends(get_citation_queue_repo)]


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
                # The DIRECTORY's route and terms position, aliased so they can never be
                # confused with the citation's own `route` column that `c.*` already
                # brings in. The worker's terms guard reads `directory_route`: reading a
                # bare `route` here would silently read the CITATION's copy (default 'C')
                # and the guard would never fire on a prohibited directory.
                "  d.route as directory_route, d.tos_position as directory_tos_position, "
                "  d.tos_source_url as directory_tos_source_url, "
                "  bp.business_name as bp_business_name, bp.address_line1 as bp_address_line1, "
                "  bp.address_line2 as bp_address_line2, bp.city as bp_city, bp.region as bp_region, "
                "  bp.postal_code as bp_postal_code, bp.phone as bp_phone, "
                "  bp.website_url as bp_website_url, bp.categories as bp_categories, "
                "  bp.description as bp_description, bp.email as bp_email, "
                "  bp.logo_url as bp_logo_url, bp.facebook_url as bp_facebook_url, "
                "  bp.instagram_url as bp_instagram_url, bp.linkedin_url as bp_linkedin_url, "
                "  bp.year_founded as bp_year_founded, bp.payment_types as bp_payment_types, "
                "  bp.tagline as bp_tagline, bp.service_area as bp_service_area, bp.hours as bp_hours "
                "from public.citations c "
                "left join public.directories d on d.id = c.directory_id "
                "left join public.business_profiles bp on bp.id = c.business_profile_id "
                "where c.id = %s limit 1",
                (citation_id,),
            )
            return cur.fetchone()

    def due_for_recheck(self, limit: int = 200) -> list[dict[str, Any]]:
        """Citations whose liveness should be re-confirmed now.

        A listing is not a fact you establish once. Directories delete listings, merge
        duplicates, expire unclaimed entries and quietly change a phone number, and none
        of that sends us a notification - so `live` decays into a claim unless something
        goes and looks again. `next_recheck_at` is what schedules that.

        Only rows with a `live_url` are selectable: there is nothing to fetch otherwise,
        and a row that has never had one is the submission pipeline's problem, not this
        one's. Ordered oldest-due-first and LIMITed so one sweep is bounded work."""
        with privileged_connection() as cur:
            cur.execute(
                "select c.id, c.live_url, c.submit_status, c.recheck_count, c.directory, "
                "  d.authority_tier as directory_authority_tier, d.route as directory_route, "
                "  bp.business_name as bp_business_name, bp.phone as bp_phone, "
                "  bp.address_line1 as bp_address_line1 "
                "from public.citations c "
                "left join public.directories d on d.id = c.directory_id "
                "left join public.business_profiles bp on bp.id = c.business_profile_id "
                "where c.live_url <> '' "
                "  and c.next_recheck_at is not null "
                "  and c.next_recheck_at <= now() "
                "order by c.next_recheck_at asc "
                "limit %s",
                (limit,),
            )
            return list(cur.fetchall())

    def update_citation(self, citation_id: str, fields: dict[str, Any]) -> None:
        if not fields:
            return
        assignments = sql.SQL(", ").join(
            sql.SQL("{} = %s").format(sql.Identifier(c)) for c in fields
        )
        stmt = sql.SQL("update public.citations set {sets} where id = %s").format(sets=assignments)
        with privileged_connection() as cur:
            cur.execute(stmt, [*fields.values(), citation_id])

    def clear_citations(self, client_id: str) -> int:
        """DELETE every citation row for a client and return the row count.

        Runs on the privileged connection because ``citations`` has ENABLE+FORCE RLS
        with NO delete policy (0018) - a delete must be service_role. Used by the
        operator "clear citations" action so a client can be re-audited from a clean
        slate (an audit re-discovers the true built-vs-missing state)."""
        with privileged_connection() as cur:
            cur.execute("delete from public.citations where client_id = %s", (client_id,))
            return int(cur.rowcount or 0)


def service_citations_store() -> ServiceCitationsStore:
    """The privileged citations store the citation_submit_job worker uses."""
    return ServiceCitationsStore()


def web2_credential_counts() -> dict[str, int]:
    """``{platform: count}`` of stored per-client Web 2.0 vault credentials, for the
    API status board. Counts ONLY (no secret is read), grouped from the
    ``provider = 'web2:<platform>'`` convention. A system status read, so it runs on
    the privileged connection; an unconfigured DB degrades to an empty board (every
    platform then reads MISSING) rather than raising - the status board must never 500."""
    counts: dict[str, int] = {}
    try:
        with privileged_connection() as cur:
            cur.execute(
                "select provider, count(*) as n from public.vault_keys "
                "where provider like %s group by provider",
                ("web2:%",),
            )
            rows = cur.fetchall()
    except DatabaseNotConfiguredError:
        return {}
    for row in rows:
        provider = str(row.get("provider") or "")
        platform = provider.split(":", 1)[1] if ":" in provider else provider
        if platform:
            counts[platform] = int(row.get("n") or 0)
    return counts


class DirectorySpecsRepo:
    """The earned whitelist (0111), RLS-scoped.

    Reads are staff-wide; every write is lead-only by policy. The invariants that matter
    - a spec is immutable, a verification is write-once, activation requires both halves
    of the contract, and a spec may only navigate to its own directory's host - live in
    the DATABASE, not here, because `service_role` bypasses RLS but not CHECK constraints
    or triggers. This class is a thin caller; it deliberately does not re-implement any
    of those rules, so there is exactly one place they can be wrong."""

    def __init__(self, user_id: str) -> None:
        self._user_id = user_id

    def list_specs(self, *, directory_id: str | None = None) -> _Rows:
        query = (
            "select s.*, d.name as directory_name, d.url as directory_url, "
            "       d.route as directory_route, d.tier as directory_tier "
            "from public.directory_specs s "
            "join public.directories d on d.id = s.directory_id "
        )
        params: list[Any] = []
        if directory_id is not None:
            query += "where s.directory_id = %s "
            params.append(directory_id)
        query += "order by s.active desc, d.name, s.created_at desc"
        with rls_connection(self._user_id) as cur:
            cur.execute(query, params)
            return cur.fetchall()

    def get_spec(self, spec_id: str) -> dict[str, Any] | None:
        with rls_connection(self._user_id) as cur:
            cur.execute(
                "select s.*, d.name as directory_name, d.url as directory_url "
                "from public.directory_specs s "
                "join public.directories d on d.id = s.directory_id "
                "where s.id = %s limit 1",
                (spec_id,),
            )
            return cur.fetchone()

    def create_spec(self, *, directory_id: str, spec: dict[str, Any]) -> dict[str, Any] | None:
        """Insert a NEW, inactive spec revision.

        There is no update path on purpose: `spec` is immutable after insert, so a
        revision is a new row. That is what makes a verification meaningful - it signs
        the selectors it actually checked, and cannot be carried onto different ones."""
        with rls_connection(self._user_id) as cur:
            cur.execute(
                "insert into public.directory_specs (directory_id, spec) values (%s, %s) "
                "returning *",
                (directory_id, Jsonb(spec)),
            )
            return cur.fetchone()

    def record_verification(
        self, spec_id: str, *, verified_by: str, evidence: dict[str, Any]
    ) -> dict[str, Any] | None:
        """Half (a): a dated human live-DOM check, signed.

        Write-once at the database level, so a stale verification cannot be silently
        refreshed to make an old spec look recently checked."""
        with rls_connection(self._user_id) as cur:
            cur.execute(
                "update public.directory_specs set "
                "  verified_at = now(), verified_by = %s, verified_evidence = %s "
                "where id = %s and verified_at is null "
                "returning *",
                (verified_by, Jsonb(evidence), spec_id),
            )
            return cur.fetchone()

    def record_first_live(self, spec_id: str, *, live_url: str) -> dict[str, Any] | None:
        """Half (b): the first submission using this exact spec that produced a public
        listing URL. Write-once; a screenshot key can never satisfy it (the schema
        requires an absolute http(s) URL)."""
        with rls_connection(self._user_id) as cur:
            cur.execute(
                "update public.directory_specs set "
                "  first_live_url = %s, first_live_at = now(), "
                "  last_success_at = now(), success_count = success_count + 1 "
                "where id = %s and first_live_url = '' "
                "returning *",
                (live_url, spec_id),
            )
            return cur.fetchone()

    def activate(self, spec_id: str) -> dict[str, Any] | None:
        """Turn the spec on AND promote its directory to route B, in ONE transaction.

        The route move is not bookkeeping - it is the point. Gating the loader on
        `directories.route = 'B'` while nothing could ever SET route B was a design that
        looked correct and could never have a member: measured on this catalogue, route B
        held zero rows and no code path wrote it. Activation IS the evidence a directory
        earned route B, so the two facts are established together or not at all.

        The `active_is_earned` CHECK does the refusing: an unverified spec, or one with
        no first live URL, cannot reach `active = true` however it is asked."""
        with rls_connection(self._user_id) as cur:
            cur.execute(
                "update public.directory_specs set active = true, deactivated_reason = '' "
                "where id = %s returning *",
                (spec_id,),
            )
            row = cur.fetchone()
            if row is None:
                return None
            cur.execute(
                "update public.directories set route = 'B' where id = %s and route <> 'F'",
                (row["directory_id"],),
            )
            return row

    def deactivate(self, spec_id: str, *, reason: str) -> dict[str, Any] | None:
        """Turn a spec off, with a reason that reaches the client report.

        The directory is NOT moved back off route B here. Route B says "this directory
        has an open form we have successfully submitted to", which stays true even while
        the current spec is broken - and a row that flip-flops between routes on every
        drift event tells an operator nothing."""
        with rls_connection(self._user_id) as cur:
            cur.execute(
                "update public.directory_specs set active = false, deactivated_reason = %s "
                "where id = %s returning *",
                (reason, spec_id),
            )
            return cur.fetchone()

    def record_drift(
        self, spec_id: str, *, selector: str, evidence: dict[str, Any]
    ) -> dict[str, Any] | None:
        """A submit failed because a selector is GONE - the spec no longer describes the
        live form. Deactivates and records WHICH selector vanished, which is what turns
        'submit failed' into a two-minute repair. Never retried: a blind retry against a
        form that changed is a second wasted submission, not a second chance."""
        with rls_connection(self._user_id) as cur:
            cur.execute(
                "update public.directory_specs set "
                "  active = false, deactivated_reason = 'drift_detected', "
                "  drift_detected_at = now(), drift_selector = %s, drift_evidence = %s, "
                "  failure_count = failure_count + 1, last_attempt_at = now() "
                "where id = %s returning *",
                (selector[:500], Jsonb(evidence), spec_id),
            )
            return cur.fetchone()


def get_directory_specs_repo(user: CurrentUserDep) -> DirectorySpecsRepo:
    return DirectorySpecsRepo(user.id)


DirectorySpecsRepoDep = Annotated[DirectorySpecsRepo, Depends(get_directory_specs_repo)]
