"""Data access for the local-SEO ledgers (``local_rankings`` / ``gbp_profiles`` /
``local_rank_history``) via the RLS-scoped ``rls_connection`` seam + the privileged
``ServiceLocalStore`` the refresh worker writes through.

Every read + mutation on ``LocalRepo`` is tenant/actor-scoped by Postgres RLS: staff
read the whole local surface, clients are excluded (no base-table select policy), and
only leads (owner/admin/manager) may write (the 0039 insert/update policies + the
router's ``require_role`` gate). Methods are synchronous (psycopg is sync) - the
router offloads them with ``asyncio.to_thread``.

The Citations KPI reads the EXISTING ``citations`` table from ``0018_offpage`` - this
module OWNS no citations table and creates none. That read is a plain RLS-scoped
count, so the off-page module stays the sole owner of the ledger's shape and writes.

SQL rules (impersonation-review mandate): every VALUE is a bound param (``%s``),
never string-formatted; table/column names are static literals and the only dynamic
column lists come from server-built dicts quoted via ``psycopg.sql.Identifier``.
"""

from __future__ import annotations

import json
from typing import Annotated, Any

from fastapi import Depends
from psycopg import sql

from app.core.auth import CurrentUserDep
from app.db.database import privileged_connection, rls_connection

_Rows = list[dict[str, Any]]

# The ranking read projection: the base row + the joined profile's location label (the
# workspace's `[Location]` cell) and place id. A LEFT join would be wrong here - a
# ranking cannot exist without its profile (NOT NULL FK), and an inner join lets
# Postgres drop a row whose profile RLS hides. A static column set.
_RANKING_SELECT = (
    "select r.*, p.location_label, p.place_id from public.local_rankings r "
    "join public.gbp_profiles p on p.id = r.profile_id"
)


class LocalRepo:
    """Thin RLS-scoped repository over the map-pack rankings + GBP profiles."""

    def __init__(self, user_id: str) -> None:
        self._user_id = user_id

    # --- rankings -------------------------------------------------------------
    def list_rankings(
        self,
        *,
        client_id: str | None = None,
        profile_id: str | None = None,
        keyword: str | None = None,
        geo: str | None = None,
        in_map_pack: bool | None = None,
        is_active: bool | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> _Rows:
        query = _RANKING_SELECT
        clauses: list[str] = []
        params: list[Any] = []
        if client_id is not None:
            clauses.append("r.client_id = %s")
            params.append(client_id)
        if profile_id is not None:
            clauses.append("r.profile_id = %s")
            params.append(profile_id)
        if keyword is not None:
            clauses.append("r.keyword = %s")
            params.append(keyword)
        if geo is not None:
            clauses.append("r.geo = %s")
            params.append(geo)
        if in_map_pack is not None:
            clauses.append("r.in_map_pack = %s")
            params.append(in_map_pack)
        if is_active is not None:
            clauses.append("r.is_active = %s")
            params.append(is_active)
        if clauses:
            query += " where " + " and ".join(clauses)
        # Best ranks first, with NULLs (not in the pack) LAST - an unranked row is the
        # worst outcome, not the best, and a bare `order by rank` would float every
        # NULL to the top in Postgres's default ordering. location + keyword keep
        # paging deterministic across ties.
        query += " order by r.rank asc nulls last, p.location_label, r.keyword"
        if limit is not None:
            query += " limit %s offset %s"
            params += [limit, offset]
        with rls_connection(self._user_id) as cur:
            cur.execute(query, params)
            return cur.fetchall()

    def get_ranking(self, ranking_id: str) -> dict[str, Any] | None:
        with rls_connection(self._user_id) as cur:
            cur.execute(_RANKING_SELECT + " where r.id = %s limit 1", (ranking_id,))
            return cur.fetchone()

    def local_stats(self) -> dict[str, Any]:
        """The three KPI tiles: tracked profiles, average map rank, citations.

        Three RLS-scoped counts. ``avg_map_rank`` averages ONLY rows that are ranked
        AND active (see ``service.average_map_rank`` for the rationale) - an unranked
        row has no number to average, and an inactive one is no longer tracked.
        ``citations`` reads the EXISTING 0018 ledger, which this module never writes.
        """
        with rls_connection(self._user_id) as cur:
            cur.execute("select count(*) as gbp_profiles from public.gbp_profiles")
            profiles = cur.fetchone() or {}
            cur.execute(
                "select coalesce(avg(rank), 0) as avg_map_rank from public.local_rankings "
                "where rank is not null and is_active"
            )
            avg = cur.fetchone() or {}
            cur.execute("select count(*) as citations from public.citations")
            citations = cur.fetchone() or {}
            return {
                "gbp_profiles": profiles.get("gbp_profiles", 0),
                "avg_map_rank": avg.get("avg_map_rank", 0),
                "citations": citations.get("citations", 0),
            }

    def rank_history(self, ranking_id: str, *, limit: int = 90) -> _Rows:
        """One ranking's append-only timeline, newest first (index-aligned)."""
        with rls_connection(self._user_id) as cur:
            cur.execute(
                "select rank, in_map_pack, provider, checked_at "
                "from public.local_rank_history where ranking_id = %s "
                "order by checked_at desc limit %s",
                (ranking_id, limit),
            )
            return cur.fetchall()

    def add_ranking(
        self,
        *,
        client_id: str,
        client_name: str,
        profile_id: str,
        keyword: str,
        geo: str | None,
    ) -> dict[str, Any] | None:
        """Track one (profile, keyword, geo). A duplicate is a no-op that RETURNS the
        existing row (``do update`` touching one column so ``returning`` fires) rather
        than a 409 - re-adding a tracked keyword is a benign, idempotent request.

        The conflict target relies on 0039's ``unique nulls not distinct`` index, so a
        geo-less row dedupes too.
        """
        with rls_connection(self._user_id) as cur:
            cur.execute(
                "insert into public.local_rankings "
                "(client_id, client_name, profile_id, keyword, geo) "
                "values (%s, %s, %s, %s, %s) "
                "on conflict (profile_id, keyword, geo) do update set "
                "client_name = excluded.client_name "
                "returning id",
                (client_id, client_name, profile_id, keyword, geo),
            )
            row = cur.fetchone()
        if row is None:
            return None
        # Re-read through the join so the response carries the location label.
        return self.get_ranking(str(row["id"]))

    def set_ranking_active(self, ranking_id: str, *, is_active: bool) -> dict[str, Any] | None:
        """Activate / deactivate ONE tracked row (history is preserved either way)."""
        with rls_connection(self._user_id) as cur:
            cur.execute(
                "update public.local_rankings set is_active = %s where id = %s returning id",
                (is_active, ranking_id),
            )
            if cur.fetchone() is None:
                return None
        return self.get_ranking(ranking_id)

    # --- profiles -------------------------------------------------------------
    def list_profiles(
        self, *, client_id: str | None = None, limit: int | None = None, offset: int = 0
    ) -> _Rows:
        query = "select * from public.gbp_profiles"
        params: list[Any] = []
        if client_id is not None:
            query += " where client_id = %s"
            params.append(client_id)
        query += " order by client_name, location_label"
        if limit is not None:
            query += " limit %s offset %s"
            params += [limit, offset]
        with rls_connection(self._user_id) as cur:
            cur.execute(query, params)
            return cur.fetchall()

    def get_profile(self, profile_id: str) -> dict[str, Any] | None:
        with rls_connection(self._user_id) as cur:
            cur.execute(
                "select * from public.gbp_profiles where id = %s limit 1", (profile_id,)
            )
            return cur.fetchone()

    def add_profile(self, values: dict[str, Any]) -> dict[str, Any] | None:
        """Insert one GBP profile from a SERVER-BUILT column dict.

        ``values`` is composed by the router/service (never caller JSON), so its KEYS
        are trusted identifiers - quoted through ``sql.Identifier`` regardless - while
        every VALUE is bound.
        """
        if not values:
            return None
        columns = sql.SQL(", ").join(sql.Identifier(col) for col in values)
        placeholders = sql.SQL(", ").join(sql.SQL("%s") for _ in values)
        stmt = sql.SQL(
            "insert into public.gbp_profiles ({cols}) values ({vals}) returning *"
        ).format(cols=columns, vals=placeholders)
        with rls_connection(self._user_id) as cur:
            cur.execute(stmt, list(values.values()))
            return cur.fetchone()

    def update_profile(
        self, profile_id: str, changes: dict[str, Any]
    ) -> dict[str, Any] | None:
        """Update one profile by id, returning the row (or ``None`` if unknown/hidden).
        Column names are static ``sql.Identifier``s; values are always bound."""
        if not changes:
            return self.get_profile(profile_id)
        assignments = sql.SQL(", ").join(
            sql.SQL("{} = %s").format(sql.Identifier(col)) for col in changes
        )
        stmt = sql.SQL(
            "update public.gbp_profiles set {sets} where id = %s returning *"
        ).format(sets=assignments)
        with rls_connection(self._user_id) as cur:
            cur.execute(stmt, [*changes.values(), profile_id])
            return cur.fetchone()

    def citations_for_client(self, client_id: str) -> _Rows:
        """One client's rows from the EXISTING 0018 citations ledger (read-only).

        The NAP-alignment report folds these against the profile's canonical NAP. The
        off-page module owns every WRITE to this table; local_seo only ever reads it.
        """
        with rls_connection(self._user_id) as cur:
            cur.execute(
                "select directory, nap_status, note from public.citations "
                "where client_id = %s order by directory",
                (client_id,),
            )
            return cur.fetchall()

    def client_name_for(self, client_id: str) -> str | None:
        """The display name of a client the caller can see (RLS-scoped), or ``None``
        - used to SNAPSHOT client_name so the internal client_id never surfaces."""
        with rls_connection(self._user_id) as cur:
            cur.execute("select name from public.clients where id = %s limit 1", (client_id,))
            row = cur.fetchone()
            return str(row["name"]) if row else None


def get_local_repo(user: CurrentUserDep) -> LocalRepo:
    """Dependency: a repo bound to the caller's verified user id (RLS-scoped)."""
    return LocalRepo(user.id)


LocalRepoDep = Annotated[LocalRepo, Depends(get_local_repo)]


# --------------------------------------------------------------------------- #
# Privileged (service_role, BYPASSRLS) store for the REFRESH worker.
# --------------------------------------------------------------------------- #
# The refresh worker has no user JWT, so - exactly like the audit / context / offpage
# / keyword workers - it reads/writes on the privileged connection (service_role
# bypasses the RLS policies by design). Each method opens its own privileged
# connection, so the store is stateless and safe to instantiate per call.
class ServiceLocalStore:
    """Concrete local store over ``privileged_connection`` (BYPASSRLS)."""

    def claim_due_rankings(self, limit: int) -> _Rows:
        """Atomically claim up to ``limit`` ACTIVE rankings to refresh.

        One statement: a ``FOR UPDATE SKIP LOCKED`` sub-select picks active rows
        (oldest check first, never-checked first), skipping any a concurrent beat tick
        already holds, and the outer ``UPDATE`` stamps ``last_checked_at`` and returns
        them. SKIP LOCKED means two beats never claim the same row - the same
        exactly-once-ish backbone as ``context_repo.claim_due_dirty``.

        Stamping ``last_checked_at`` AT CLAIM (not after the provider answers) is
        deliberate: it rotates the queue so a row that fails repeatedly cannot starve
        every other row behind it. It is a "we looked at this" stamp; whether the look
        SUCCEEDED is recorded only by an appended history row.
        """
        with privileged_connection() as cur:
            cur.execute(
                "with due as ( "
                "  select id from public.local_rankings "
                "  where is_active "
                "  order by last_checked_at asc nulls first "
                "  for update skip locked "
                "  limit %s "
                ") "
                "update public.local_rankings r set last_checked_at = now() "
                "from due where r.id = due.id "
                "returning r.id, r.client_id, r.client_name, r.profile_id, r.keyword, "
                "          r.geo, r.rank",
                (limit,),
            )
            return cur.fetchall()

    def profile_for_ranking(self, profile_id: str) -> dict[str, Any] | None:
        """The GBP profile a ranking checks against (its place_id + business name)."""
        with privileged_connection() as cur:
            cur.execute(
                "select id, client_id, client_name, location_label, place_id, nap_name "
                "from public.gbp_profiles where id = %s limit 1",
                (profile_id,),
            )
            return cur.fetchone()

    def record_check(
        self,
        ranking_id: str,
        *,
        client_id: str,
        rank: int | None,
        previous_rank: int | None,
        rank_change: int,
        in_map_pack: bool,
        found_url: str,
        top_competitors: list[str],
        provider: str,
    ) -> None:
        """Persist ONE SUCCESSFUL check: update the current row AND append history.

        Both writes share a single connection/transaction, so the current state and
        its timeline can never disagree.

        CALLER CONTRACT: only ever called for a check that SUCCEEDED. A ``rank`` of
        ``None`` here means "checked, not in the pack" - an honest absence worth
        recording. A FAILED check must never reach this method: writing it would
        fabricate a ranking loss the business never suffered.
        """
        with privileged_connection() as cur:
            cur.execute(
                "update public.local_rankings set "
                "rank = %s, previous_rank = %s, rank_change = %s, in_map_pack = %s, "
                "found_url = %s, top_competitors = %s, provider = %s, last_checked_at = now() "
                "where id = %s",
                (
                    rank, previous_rank, rank_change, in_map_pack, found_url,
                    json.dumps(top_competitors), provider, ranking_id,
                ),
            )
            cur.execute(
                "insert into public.local_rank_history "
                "(ranking_id, client_id, rank, in_map_pack, provider) "
                "values (%s, %s, %s, %s, %s)",
                (ranking_id, client_id, rank, in_map_pack, provider),
            )

    def update_profile_sync(
        self,
        profile_id: str,
        *,
        primary_category: str,
        secondary_categories: list[str],
        nap_name: str,
        nap_address: str,
        nap_phone: str,
        website_uri: str,
        regular_hours: dict[str, Any],
        review_count: int,
        avg_rating: float | None,
        completeness_score: int,
        audit: dict[str, Any],
    ) -> None:
        """Write back ONE read-only GBP sync (profile fields + the derived audit)."""
        with privileged_connection() as cur:
            cur.execute(
                "update public.gbp_profiles set "
                "primary_category = %s, secondary_categories = %s, nap_name = %s, "
                "nap_address = %s, nap_phone = %s, website_uri = %s, regular_hours = %s, "
                "review_count = %s, avg_rating = %s, completeness_score = %s, audit = %s, "
                "last_synced_at = now() where id = %s",
                (
                    primary_category, secondary_categories, nap_name, nap_address,
                    nap_phone, website_uri, json.dumps(regular_hours), review_count,
                    avg_rating, completeness_score, json.dumps(audit), profile_id,
                ),
            )


def service_local_store() -> ServiceLocalStore:
    """The privileged local store the refresh worker uses (service_role, BYPASSRLS)."""
    return ServiceLocalStore()
