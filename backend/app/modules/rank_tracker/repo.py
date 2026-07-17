"""Data access for rank tracking (``tracked_keywords`` / ``keyword_rankings``) via the
RLS-scoped ``rls_connection`` seam + the privileged ``ServiceRankStore`` the nightly
check worker writes through.

Every read + mutation on ``RankRepo`` is tenant/actor-scoped by Postgres RLS: staff
read the whole board, clients are excluded (no base-table select policy - they get the
``portal_rank_keywords`` view instead), and only leads (owner/admin/manager) may write
(the 0036 insert/update policies + the ``run_research`` app gate). Methods are
synchronous (psycopg is sync) - the router offloads them with ``asyncio.to_thread``.

SQL rules (impersonation-review mandate): every VALUE is a bound param (``%s``), never
string-formatted; table/column names are static literals and the only dynamic column
lists come from server-built dicts quoted via ``psycopg.sql.Identifier``.
"""

from __future__ import annotations

from datetime import date
from typing import Annotated, Any

from fastapi import Depends
from psycopg import sql

from app.core.auth import CurrentUserDep
from app.db.database import privileged_connection, rls_connection

_Rows = list[dict[str, Any]]

# The board's read projection. A static column set; the client display name is already
# snapshotted on the row, so no join is needed to render it.
_KEYWORD_SELECT = "select * from public.tracked_keywords"

# The dispatcher's advisory-lock key (R6). A CONSTANT, arbitrary-but-stable 64-bit id;
# it only has to be unique among this database's advisory locks. Taken as an
# XACT-scoped lock so it auto-releases on commit: a session-scoped lock taken on a
# POOLED connection could be released onto a different checkout (or leak forever if the
# worker died holding it), which is exactly the failure a beat lock is supposed to
# prevent.
BEAT_LOCK_KEY = 0x52414E4B_54524B31  # "RANKTRK1"


class RankRepo:
    """Thin RLS-scoped repository over the tracked-keyword board + its history."""

    def __init__(self, user_id: str) -> None:
        self._user_id = user_id

    # --- reads ----------------------------------------------------------------
    def list_keywords(
        self,
        *,
        client_id: str | None = None,
        status: str | None = None,
        engine: str | None = None,
        device: str | None = None,
        tag: str | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> _Rows:
        """The tracked board. Best positions first, with unranked rows LAST.

        ``latest_position asc nulls last`` is load-bearing: Postgres sorts NULLs FIRST
        for ``asc`` by default, so the plain ordering would open the board with every
        keyword that does not rank at all.
        """
        query = _KEYWORD_SELECT
        clauses: list[str] = []
        params: list[Any] = []
        if client_id is not None:
            clauses.append("client_id = %s")
            params.append(client_id)
        if status is not None:
            clauses.append("status = %s")
            params.append(status)
        if engine is not None:
            clauses.append("engine = %s")
            params.append(engine)
        if device is not None:
            clauses.append("device = %s")
            params.append(device)
        if tag is not None:
            # The GIN index on tags answers this containment test directly.
            clauses.append("tags @> array[%s]::text[]")
            params.append(tag)
        if clauses:
            query += " where " + " and ".join(clauses)
        query += " order by latest_position asc nulls last, keyword, code"
        if limit is not None:
            query += " limit %s offset %s"
            params += [limit, offset]
        with rls_connection(self._user_id) as cur:
            cur.execute(query, params)
            return cur.fetchall()

    def rank_stats(self, *, client_id: str | None = None) -> dict[str, Any]:
        """Board summary: tracked count, average position, top-3 count.

        The average is over RANKED rows ONLY - ``avg`` ignores NULLs natively, which is
        exactly the semantic the service documents; the ``coalesce`` then keeps an
        all-unranked board at 0 rather than NULL. ``tracked`` counts EVERY row, so the
        tile pair stays honest: "128 tracked, avg 8.4 where we rank".
        """
        query = (
            "select "
            "count(*) as tracked, "
            "coalesce(avg(latest_position) filter (where latest_position is not null), 0) "
            "  as avg_position, "
            "count(*) filter (where latest_position is not null and latest_position <= 3) "
            "  as top_three "
            "from public.tracked_keywords"
        )
        params: list[Any] = []
        if client_id is not None:
            query += " where client_id = %s"
            params.append(client_id)
        with rls_connection(self._user_id) as cur:
            cur.execute(query, params)
            row = cur.fetchone()
            return row or {"tracked": 0, "avg_position": 0, "top_three": 0}

    def get_by_code(self, code: str) -> dict[str, Any] | None:
        with rls_connection(self._user_id) as cur:
            cur.execute(_KEYWORD_SELECT + " where code = %s limit 1", (code,))
            return cur.fetchone()

    def history(self, keyword_id: str, *, limit: int = 90) -> _Rows:
        """One keyword's daily history, newest first.

        A day the check FAILED has no row at all (the worker writes nothing on a
        provider error), so the series has an honest GAP rather than a fabricated
        unranked point.
        """
        with rls_connection(self._user_id) as cur:
            cur.execute(
                "select * from public.keyword_rankings where keyword_id = %s "
                "order by checked_on desc limit %s",
                (keyword_id, limit),
            )
            return cur.fetchall()

    def client_name_for(self, client_id: str) -> str | None:
        """The display name of a client the caller can see (RLS-scoped), or ``None`` -
        used to SNAPSHOT client_name so the internal client_id never surfaces."""
        with rls_connection(self._user_id) as cur:
            cur.execute("select name from public.clients where id = %s limit 1", (client_id,))
            row = cur.fetchone()
            return str(row["name"]) if row else None

    def active_cadence_counts(self, client_id: str) -> dict[str, int]:
        """``{cadence: count}`` over the client's ACTIVE subscriptions - the input the
        N-A projection prices. Paused rows are excluded because they cost nothing."""
        with rls_connection(self._user_id) as cur:
            cur.execute(
                "select cadence, count(*) as n from public.tracked_keywords "
                "where client_id = %s and status = 'active' group by cadence",
                (client_id,),
            )
            return {str(r["cadence"]): int(r["n"]) for r in cur.fetchall()}

    def client_budget(self, client_id: str) -> tuple[float, float] | None:
        """The client's ``(cap, spent)`` budget pair, or ``None`` when they have no
        budget row. Read on the RLS seam (the cost gate's own store reads the same
        table privileged, from the worker, where there is no caller identity)."""
        with rls_connection(self._user_id) as cur:
            cur.execute(
                "select cap, spent from public.client_budgets where client_id = %s limit 1",
                (client_id,),
            )
            row = cur.fetchone()
            if row is None:
                return None
            return float(row["cap"]), float(row["spent"])

    # --- mutations ------------------------------------------------------------
    def add_keywords(
        self,
        *,
        client_id: str,
        client_name: str,
        site_id: str | None,
        keywords: list[tuple[str, str]],
        target_url: str,
        engine: str,
        device: str,
        location: str,
        location_code: int | None,
        language: str,
        country: str,
        tags: list[str],
        cadence: str,
        next_check_on: date,
    ) -> _Rows:
        """Bulk-subscribe keywords for one client.

        ``keywords`` is a list of ``(display, normalized)`` pairs - the service folds
        the normalized form so the DB's uniqueness key (and therefore the BILL) is
        case/whitespace-insensitive. A duplicate subscription is skipped
        (``on conflict do nothing``), never double-billed. Empty input is a no-op.
        """
        if not keywords:
            return []
        values = sql.SQL(", ").join(
            sql.SQL("(%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)")
            for _ in keywords
        )
        params: list[Any] = []
        for display, normalized in keywords:
            params += [
                client_id, client_name, site_id, display, normalized, target_url,
                engine, device, location, location_code, language, country, tags,
                cadence, next_check_on,
            ]
        stmt = sql.SQL(
            "insert into public.tracked_keywords "
            "(client_id, client_name, site_id, keyword, normalized_keyword, target_url, "
            "engine, device, location, location_code, language, country, tags, cadence, "
            "next_check_on) values {values} "
            "on conflict (client_id, normalized_keyword, engine, device, location, language) "
            "do nothing returning *"
        ).format(values=values)
        with rls_connection(self._user_id) as cur:
            cur.execute(stmt, params)
            return cur.fetchall()

    def update_keyword(self, code: str, changes: dict[str, Any]) -> dict[str, Any] | None:
        """Update one subscription by code, returning the fresh row (or ``None`` if the
        code is unknown/invisible). Column names are static ``sql.Identifier``s; values
        are always bound - the impersonation-review SQL rule."""
        if not changes:
            return self.get_by_code(code)
        assignments = sql.SQL(", ").join(
            sql.SQL("{} = %s").format(sql.Identifier(col)) for col in changes
        )
        stmt = sql.SQL(
            "update public.tracked_keywords set {sets} where code = %s returning *"
        ).format(sets=assignments)
        with rls_connection(self._user_id) as cur:
            cur.execute(stmt, [*changes.values(), code])
            return cur.fetchone()


def get_rank_repo(user: CurrentUserDep) -> RankRepo:
    """Dependency: a repo bound to the caller's verified user id (RLS-scoped)."""
    return RankRepo(user.id)


RankRepoDep = Annotated[RankRepo, Depends(get_rank_repo)]


# --------------------------------------------------------------------------- #
# Privileged (service_role, BYPASSRLS) store for the CHECK worker.
# --------------------------------------------------------------------------- #
# The check worker has no user JWT, so - exactly like the audit / context / keyword
# workers - it reads/writes on the privileged connection (service_role bypasses the RLS
# policies by design; note it bypasses POLICIES, not TRIGGERS). Each method opens its
# own privileged connection inside its own transaction, so the store is stateless and
# safe to instantiate per call.
class ServiceRankStore:
    """Concrete rank store over ``privileged_connection`` (BYPASSRLS)."""

    def claim_due_keywords(self, limit: int) -> list[dict[str, Any]]:
        """R6: take the beat-overlap lock, then CLAIM up to ``limit`` due subscriptions.

        Two guards stack, and both are needed:

        1. ``pg_try_advisory_xact_lock`` - the BEAT-OVERLAP lock. If a previous nightly
           dispatch is still draining (or two beat processes are running), this returns
           False and the tick is a clean no-op instead of a second fan-out. It is
           XACT-scoped, so it releases when this transaction commits - a session lock on
           a POOLED connection could be released onto someone else's checkout, or leak
           forever if the worker died holding it.
        2. ``for update skip locked`` - the row-level claim (the ``context_dirty``
           precedent), so concurrent claimers never hand the same keyword out twice.

        The claim ADVANCES ``next_check_on`` in the same statement, so a keyword leaves
        the due set the moment it is handed out. Without that, a redelivered dispatch
        would re-fan-out the same keyword and pay for a second check - the history's
        ``on conflict`` would swallow the duplicate ROW, but the money would already be
        spent. The check task re-stamps ``next_check_on`` authoritatively on success.
        """
        with privileged_connection() as cur:
            cur.execute("select pg_try_advisory_xact_lock(%s) as locked", (BEAT_LOCK_KEY,))
            row = cur.fetchone()
            if row is None or not row.get("locked"):
                return []
            cur.execute(
                "update public.tracked_keywords t "
                "set next_check_on = current_date + "
                "    (case when t.cadence = 'daily' then 1 else 7 end) "
                "where t.id in ("
                "  select k.id from public.tracked_keywords k "
                "  where k.status = 'active' and k.next_check_on <= current_date "
                "  order by k.next_check_on, k.id "
                "  limit %s for update skip locked"
                ") returning t.id, t.code, t.keyword, t.client_id, t.cadence",
                (limit,),
            )
            return cur.fetchall()

    def get_keyword(self, keyword_id: str) -> dict[str, Any] | None:
        """One subscription joined to its site's domain - the domain is what the rank
        check actually looks for in the SERP. ``left join`` so a keyword with no linked
        site still loads (the worker reports it honestly rather than vanishing)."""
        with privileged_connection() as cur:
            cur.execute(
                "select t.*, s.domain as site_domain from public.tracked_keywords t "
                "left join public.sites s on s.id = t.site_id where t.id = %s limit 1",
                (keyword_id,),
            )
            return cur.fetchone()

    def has_ranking_on(self, keyword_id: str, checked_on: date) -> bool:
        """Whether a snapshot already exists for this keyword on this day.

        This is the DOUBLE-SPEND guard, and it is why it runs BEFORE the gate: the
        ``unique (keyword_id, checked_on)`` index makes the WRITE idempotent, but a
        redelivered task would still have paid the vendor before hitting the conflict.
        """
        with privileged_connection() as cur:
            cur.execute(
                "select 1 from public.keyword_rankings "
                "where keyword_id = %s and checked_on = %s limit 1",
                (keyword_id, checked_on),
            )
            return cur.fetchone() is not None

    def record_check(
        self,
        keyword_id: str,
        *,
        client_id: str,
        checked_on: date,
        position: int | None,
        ranking_url: str,
        serp_features: list[str],
        own_urls: str,
        delta: int | None,
        provider: str,
        cost: float,
        previous_position: int | None,
        next_check_on: date,
        checked_at: Any,
        features: list[str],
    ) -> bool:
        """Append ONE day's snapshot and roll the subscription's read model forward,
        in ONE transaction. Returns True when the snapshot was NEW.

        Called ONLY for a SUCCESSFUL check. ``position=None`` here means "checked, not
        in the top-N" (unranked) - a provider FAILURE never reaches this method, which
        is what stops an outage from being recorded as a lost ranking.

        ``on conflict (keyword_id, checked_on) do nothing`` makes a redelivery a no-op;
        when it fires, the roll-forward is skipped too, so ``previous_position`` cannot
        be corrupted by re-applying the same day twice (which would silently overwrite
        the real previous position with today's and zero out the reported movement).
        """
        with privileged_connection() as cur:
            cur.execute(
                "insert into public.keyword_rankings "
                "(keyword_id, client_id, checked_on, position, ranking_url, serp_features, "
                "own_urls, delta, provider, cost) "
                "values (%s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s) "
                "on conflict (keyword_id, checked_on) do nothing returning id",
                (
                    keyword_id, client_id, checked_on, position, ranking_url, serp_features,
                    own_urls, delta, provider, cost,
                ),
            )
            if cur.fetchone() is None:
                return False  # already recorded today: a redelivery, not a new check
            cur.execute(
                "update public.tracked_keywords set "
                "previous_position = %s, latest_position = %s, latest_url = %s, "
                "latest_features = %s, latest_checked_at = %s, next_check_on = %s, "
                # A NULL best_position (never ranked) must LOSE to any real position;
                # `least` returns NULL if any argument is NULL, so coalesce first.
                "best_position = case when %s is null then best_position "
                "  else least(coalesce(best_position, %s), %s) end, "
                "best_position_at = case when %s is not null and "
                "  (best_position is null or %s < best_position) then %s "
                "  else best_position_at end "
                "where id = %s",
                (
                    previous_position, position, ranking_url, features, checked_at,
                    next_check_on,
                    position, position, position,
                    position, position, checked_on,
                    keyword_id,
                ),
            )
            return True

    def replace_check(
        self,
        keyword_id: str,
        *,
        checked_on: date,
        position: int | None,
        ranking_url: str,
        serp_features: list[str],
        own_urls: str,
        delta: int | None,
        provider: str,
        cost: float,
        next_check_on: date,
        checked_at: Any,
        features: list[str],
    ) -> None:
        """CORRECT today's snapshot in place with a fresher reading (the FORCED
        on-demand re-check), in ONE transaction.

        This is the ONE write that overwrites an existing ``keyword_rankings`` row, and
        the constraint on it is narrow by design: it only ever touches TODAY's row, and
        only when an operator explicitly forced a re-read and PAID for it. Correcting
        today's in-progress reading is not falsifying history - and without it the
        forced check would bill the client and then discard what they bought (the
        ``on conflict do nothing`` insert would swallow it).

        It deliberately does NOT touch ``previous_position``: that already rolled when
        today's FIRST check landed, and re-rolling it would overwrite yesterday's real
        reading with this morning's - silently zeroing out the reported movement.
        """
        with privileged_connection() as cur:
            cur.execute(
                "update public.keyword_rankings set "
                "position = %s, ranking_url = %s, serp_features = %s, own_urls = %s::jsonb, "
                "delta = %s, provider = %s, cost = cost + %s "
                "where keyword_id = %s and checked_on = %s",
                (
                    position, ranking_url, serp_features, own_urls, delta, provider, cost,
                    keyword_id, checked_on,
                ),
            )
            cur.execute(
                "update public.tracked_keywords set "
                "latest_position = %s, latest_url = %s, latest_features = %s, "
                "latest_checked_at = %s, next_check_on = %s, "
                "best_position = case when %s is null then best_position "
                "  else least(coalesce(best_position, %s), %s) end, "
                "best_position_at = case when %s is not null and "
                "  (best_position is null or %s < best_position) then %s "
                "  else best_position_at end "
                "where id = %s",
                (
                    position, ranking_url, features, checked_at, next_check_on,
                    position, position, position,
                    position, position, checked_on,
                    keyword_id,
                ),
            )

    def record_stall(self, keyword_id: str, *, next_check_on: date) -> None:
        """The STALENESS SIGNAL's write half: re-arm a subscription whose check was
        skipped, WITHOUT touching ``latest_checked_at``.

        Holding the freshness stamp is the point (it mirrors the context worker's "HOLD
        the watermark so lag stays visible"): the read side computes ``stale`` from that
        stamp, so a degraded run surfaces on the board within a cadence window instead
        of quietly presenting last week's position as today's. Advancing only the
        schedule means the tracker retries at its next slot rather than hot-spinning.
        """
        with privileged_connection() as cur:
            cur.execute(
                "update public.tracked_keywords set next_check_on = %s where id = %s",
                (next_check_on, keyword_id),
            )

    def rollup_history(self, *, rollup_before: date, purge_before: date) -> dict[str, int]:
        """Retention: thin out old history, then drop what is past retention entirely.

        The chosen alternative to PARTITIONING (see 0036's header). Two passes:

        1. ROLL UP everything older than ``rollup_before`` to ONE snapshot per ISO week
           per keyword (the week's LAST check - the freshest datum for that week). Old
           daily granularity has no reporting value; the weekly trend line does.
        2. PURGE everything older than ``purge_before`` outright.

        Runs as service_role, which bypasses POLICIES - so the deliberate absence of a
        delete policy on ``keyword_rankings`` constrains the app tier (where rank
        history is billed-against evidence) without hobbling this sweeper.
        """
        with privileged_connection() as cur:
            cur.execute(
                "delete from public.keyword_rankings r where r.checked_on < %s "
                "and r.id not in ("
                "  select distinct on (keyword_id, date_trunc('week', checked_on)) id "
                "  from public.keyword_rankings where checked_on < %s "
                "  order by keyword_id, date_trunc('week', checked_on), checked_on desc"
                ")",
                (rollup_before, rollup_before),
            )
            rolled = cur.rowcount if cur.rowcount and cur.rowcount > 0 else 0
            cur.execute(
                "delete from public.keyword_rankings where checked_on < %s", (purge_before,)
            )
            purged = cur.rowcount if cur.rowcount and cur.rowcount > 0 else 0
            return {"rolled_up": rolled, "purged": purged}


def service_rank_store() -> ServiceRankStore:
    """The privileged rank store the check worker uses (service_role, BYPASSRLS)."""
    return ServiceRankStore()
