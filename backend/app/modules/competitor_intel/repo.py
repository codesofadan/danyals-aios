"""Data access for competitor intel (``competitors`` / ``keyword_gaps``) via the
RLS-scoped ``rls_connection`` seam + the privileged ``ServiceCompetitorStore`` the gap
analysis worker writes through.

Every read + mutation on ``CompetitorRepo`` is tenant/actor-scoped by Postgres RLS:
staff read the whole board, clients are excluded entirely (no base-table select policy -
competitor intelligence is agency analysis, not a client deliverable), and only leads
(owner/admin/manager) may write (the 0037 insert/update policies + the ``run_research``
app gate). Methods are synchronous (psycopg is sync) - the router offloads them with
``asyncio.to_thread``.

SQL rules (impersonation-review mandate): every VALUE is a bound param (``%s``), never
string-formatted; table/column names are static literals and the only dynamic column
lists come from server-built dicts quoted via ``psycopg.sql.Identifier``.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import Depends
from psycopg import sql

from app.core.auth import CurrentUserDep
from app.db.database import privileged_connection, rls_connection

_Rows = list[dict[str, Any]]

# The board's read projection. A static column set; the client display name is already
# snapshotted on the row, so no join is needed to render it.
_COMPETITOR_SELECT = "select * from public.competitors"


class CompetitorRepo:
    """Thin RLS-scoped repository over the competitor set + its keyword gaps."""

    def __init__(self, user_id: str) -> None:
        self._user_id = user_id

    # --- reads ----------------------------------------------------------------
    def list_competitors(
        self,
        *,
        client_id: str | None = None,
        source: str | None = None,
        tracked: bool | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> _Rows:
        """The competitor board, most-competitive first.

        Ordered by overlap then gap count: the rival that actually contests the
        client's terms leads, not merely the one with the biggest gap list (which a
        large, barely-related site would win by sheer size).
        """
        query = _COMPETITOR_SELECT
        clauses: list[str] = []
        params: list[Any] = []
        if client_id is not None:
            clauses.append("client_id = %s")
            params.append(client_id)
        if source is not None:
            clauses.append("discovery_source = %s")
            params.append(source)
        if tracked is not None:
            clauses.append("tracked = %s")
            params.append(tracked)
        if clauses:
            query += " where " + " and ".join(clauses)
        query += " order by overlap_pct desc, keyword_gaps_count desc, domain, code"
        if limit is not None:
            query += " limit %s offset %s"
            params += [limit, offset]
        with rls_connection(self._user_id) as cur:
            cur.execute(query, params)
            return cur.fetchall()

    def competitor_stats(self, *, client_id: str | None = None) -> dict[str, Any]:
        """Board summary: tracked competitors, total open gaps, the client's SoV.

        ``tracked`` counts only rows with ``tracked = true`` - a parked competitor is
        not being tracked, and the tile would otherwise contradict the board's own
        filter. ``keyword_gaps`` sums the denormalised per-competitor counts over
        those same rows.

        ``share_of_voice`` is the CLIENT's slice, derived as ``100 - Σ(competitor
        shares)`` and floored at 0. The stored ``share_of_voice`` column holds each
        COMPETITOR's share (the client has no row of their own), so the client's own
        slice is the remainder of the measured market. It is floored because the
        per-competitor shares are rolled forward by INDEPENDENT analyses that may have
        run at different times and can transiently sum past 100 - and a negative share
        of voice is not a fact, it is a stale-data artefact.
        """
        query = (
            "select "
            "count(*) filter (where tracked) as tracked, "
            "coalesce(sum(keyword_gaps_count) filter (where tracked), 0) as keyword_gaps, "
            "greatest(0, 100 - coalesce(sum(share_of_voice) filter (where tracked), 0)) "
            "  as share_of_voice "
            "from public.competitors"
        )
        params: list[Any] = []
        if client_id is not None:
            query += " where client_id = %s"
            params.append(client_id)
        with rls_connection(self._user_id) as cur:
            cur.execute(query, params)
            row = cur.fetchone()
            return row or {"tracked": 0, "keyword_gaps": 0, "share_of_voice": 0}

    def get_by_code(self, code: str) -> dict[str, Any] | None:
        with rls_connection(self._user_id) as cur:
            cur.execute(_COMPETITOR_SELECT + " where code = %s limit 1", (code,))
            return cur.fetchone()

    def list_gaps(
        self,
        competitor_id: str,
        *,
        gap_type: str | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> _Rows:
        """One competitor's analysed gaps, best opportunity first."""
        query = "select * from public.keyword_gaps where competitor_id = %s"
        params: list[Any] = [competitor_id]
        if gap_type is not None:
            query += " and gap_type = %s"
            params.append(gap_type)
        query += " order by opportunity desc, volume desc, keyword"
        if limit is not None:
            query += " limit %s offset %s"
            params += [limit, offset]
        with rls_connection(self._user_id) as cur:
            cur.execute(query, params)
            return cur.fetchall()

    def get_gap(self, competitor_id: str, gap_id: str) -> dict[str, Any] | None:
        """One gap, scoped to its competitor so a valid id under the WRONG competitor
        cannot be promoted through the wrong client's URL."""
        with rls_connection(self._user_id) as cur:
            cur.execute(
                "select * from public.keyword_gaps where id = %s and competitor_id = %s limit 1",
                (gap_id, competitor_id),
            )
            return cur.fetchone()

    def client_name_for(self, client_id: str) -> str | None:
        """The display name of a client the caller can see (RLS-scoped), or ``None`` -
        used to SNAPSHOT client_name so the internal client_id never surfaces."""
        with rls_connection(self._user_id) as cur:
            cur.execute("select name from public.clients where id = %s limit 1", (client_id,))
            row = cur.fetchone()
            return str(row["name"]) if row else None

    def client_positions(self, client_id: str) -> dict[str, int | None]:
        """The client's OWN positions, FREE, from the Rank Tracker's read model.

        This is the whole point of Phase 2C's reuse: ``tracked_keywords.latest_position``
        is a fact the client already pays for nightly (0036), so a gap's
        ``client_position`` costs this module exactly nothing. Buying it again from a
        provider would bill the client twice for the same number.

        The returned VALUE may be ``None`` - that is 0036's "checked, not in the top-N"
        (unranked), preserved deliberately. An ABSENT key means the term is not tracked
        at all. The gap classifier treats both as "the client does not rank", which is
        why they are read through one ``.get()``.

        Keys are lowercased so the lookup matches the provider's ranked keywords
        case-insensitively (the two vendors do not agree on casing).
        """
        with rls_connection(self._user_id) as cur:
            cur.execute(
                "select keyword, latest_position from public.tracked_keywords "
                "where client_id = %s and status = 'active'",
                (client_id,),
            )
            return {
                str(r["keyword"]).strip().lower(): r["latest_position"] for r in cur.fetchall()
            }

    def client_keyword_volumes(self, client_id: str) -> dict[str, int]:
        """``{keyword: volume}`` for the client's tracked keywords - the demand weights
        the share-of-voice visibility sum multiplies the CTR curve by.

        ``search_volume`` is nullable on ``tracked_keywords`` (it is an optional
        enrichment there); a NULL contributes 0 to the sum rather than a guessed
        number, which keeps an un-enriched book's SoV honestly small instead of
        confidently wrong.
        """
        with rls_connection(self._user_id) as cur:
            cur.execute(
                "select keyword, search_volume from public.tracked_keywords "
                "where client_id = %s and status = 'active'",
                (client_id,),
            )
            return {
                str(r["keyword"]).strip().lower(): int(r["search_volume"] or 0)
                for r in cur.fetchall()
            }

    def competitor_gap_positions(self, competitor_id: str) -> tuple[dict[str, int | None], dict[str, int]]:
        """One competitor's ``({keyword: position}, {keyword: volume})`` from its stored
        gap rows - the visibility inputs for the share-of-voice split.

        Read from ``keyword_gaps`` rather than re-pulling the provider: the analysis
        already bought and stored this competitor's ranked set, so the SoV endpoint is
        free. It is therefore only as fresh as the last analysis, which ``analyzed``
        on the competitor row reports honestly.
        """
        with rls_connection(self._user_id) as cur:
            cur.execute(
                "select keyword, competitor_position, volume from public.keyword_gaps "
                "where competitor_id = %s",
                (competitor_id,),
            )
            rows = cur.fetchall()
        positions = {str(r["keyword"]).strip().lower(): r["competitor_position"] for r in rows}
        volumes = {str(r["keyword"]).strip().lower(): int(r["volume"] or 0) for r in rows}
        return positions, volumes

    def tracked_keywords_sample(self, client_id: str, *, limit: int) -> _Rows:
        """The client's highest-volume tracked keywords - auto-discovery's seed set.

        Bounded and volume-ordered because every one of these costs a PAID SERP pull:
        if only N terms can be afforded, they should be the N that best describe who
        the client actually competes with, not an arbitrary slice.
        """
        with rls_connection(self._user_id) as cur:
            cur.execute(
                "select keyword, coalesce(search_volume, 0) as search_volume "
                "from public.tracked_keywords "
                "where client_id = %s and status = 'active' "
                "order by search_volume desc nulls last, keyword limit %s",
                (client_id, limit),
            )
            return cur.fetchall()

    def client_domain_for(self, client_id: str) -> str:
        """The client's own site domain - what auto-discovery must EXCLUDE from the
        tally (a client is not their own competitor).

        Takes the client's first site by creation order. Returns "" when the client has
        no site on record, which the discovery tally treats as "exclude nothing" - it
        cannot invent the domain, and proposing the client's own site is a visible,
        correctable mistake rather than a silent omission of a real rival.
        """
        with rls_connection(self._user_id) as cur:
            cur.execute(
                "select domain from public.sites where client_id = %s "
                "order by created_at limit 1",
                (client_id,),
            )
            row = cur.fetchone()
            return str(row["domain"] or "") if row else ""

    def backlink_gaps(self, client_id: str, *, limit: int) -> _Rows:
        """Referring domains that link to this client's TRACKED competitors but not to
        the client - ranked by how many of those competitors they link to.

        ZERO provider cost: this reads the EXISTING 0018 ``backlinks`` ledger and makes
        no external call at all. 0037 gave that ledger the competitor dimension it
        lacked (a nullable ``competitor_id``); a NULL means what every pre-0037 row
        means - a link to the CLIENT's own site.

        HONEST STATUS: nothing populates competitor-side rows yet (the 7B-3 off-page
        monitor only pulls the client's own profile, and pulling a rival's is a new
        PAID call Phase 2C does not buy), so this returns an empty set today. That is
        deliberate: the alternative - presenting other monitored clients' referring
        domains as "your competitors' links" - would fabricate a fact.

        ``count(distinct b.competitor_id)`` is the ranking signal: a domain linking to
        four of the client's rivals is demonstrably willing to link in this niche.
        """
        with rls_connection(self._user_id) as cur:
            cur.execute(
                "select b.ref_domain, "
                "  count(distinct b.competitor_id) as competitors, "
                "  max(b.authority) as authority, "
                "  min(b.spam) as spam "
                "from public.backlinks b "
                "join public.competitors c on c.id = b.competitor_id "
                "where c.client_id = %s and c.tracked "
                # NOT a link the client already has. The client's own rows are the ones
                # with a NULL competitor_id, scoped to this client.
                "  and not exists ("
                "    select 1 from public.backlinks own "
                "    where own.client_id = %s and own.competitor_id is null "
                "      and lower(own.ref_domain) = lower(b.ref_domain)"
                "  ) "
                "group by b.ref_domain "
                "order by competitors desc, authority desc, b.ref_domain "
                "limit %s",
                (client_id, client_id, limit),
            )
            return cur.fetchall()

    # --- mutations ------------------------------------------------------------
    def add_competitor(
        self,
        *,
        client_id: str,
        client_name: str,
        domain: str,
        label: str,
        source: str,
        created_by: str,
    ) -> dict[str, Any] | None:
        """Track ONE competitor. Returns the new row, or ``None`` when this client
        already tracks the domain (``on conflict do nothing`` - a duplicate competitor
        is a duplicate PAID analysis, never a second row)."""
        with rls_connection(self._user_id) as cur:
            cur.execute(
                "insert into public.competitors "
                "(client_id, client_name, domain, label, discovery_source, created_by) "
                "values (%s, %s, %s, %s, %s, %s) "
                "on conflict (client_id, domain) do nothing returning *",
                (client_id, client_name, domain, label, source, created_by),
            )
            return cur.fetchone()

    def update_competitor(self, code: str, changes: dict[str, Any]) -> dict[str, Any] | None:
        """Update one competitor by code, returning the fresh row (or ``None`` if the
        code is unknown/invisible). Column names are static ``sql.Identifier``s; values
        are always bound - the impersonation-review SQL rule."""
        if not changes:
            return self.get_by_code(code)
        assignments = sql.SQL(", ").join(
            sql.SQL("{} = %s").format(sql.Identifier(col)) for col in changes
        )
        stmt = sql.SQL(
            "update public.competitors set {sets} where code = %s returning *"
        ).format(sets=assignments)
        with rls_connection(self._user_id) as cur:
            cur.execute(stmt, [*changes.values(), code])
            return cur.fetchone()

    def delete_competitor(self, code: str) -> bool:
        """Stop tracking a competitor entirely (its gaps cascade).

        NOTE: 0037 declares no DELETE policy (v1 mirrors 0035/0036), so this is
        refused by RLS for every app role. It exists as the router's honest door: the
        route returns 403 from the database rather than silently pretending. Parking a
        competitor with ``tracked=false`` is the supported way to retire one, and it
        keeps the analysis that was paid for.
        """
        with rls_connection(self._user_id) as cur:
            cur.execute("delete from public.competitors where code = %s returning id", (code,))
            return cur.fetchone() is not None

    def promote_gap(
        self, gap_id: str, *, client_id: str, client_name: str, geo: str | None = None
    ) -> tuple[str, str, bool] | None:
        """Push ONE gap into the 0035 keyword bank with ``source='gap'``.

        Returns ``(keyword, code, created)`` - ``created`` False when the term was
        already in the bank. Idempotent on BOTH sides: the bank's
        ``(client_id, keyword, geo)`` key absorbs a re-promote, and the gap's
        ``keyword_id`` is stamped so a second attempt is a visible no-op rather than a
        second bank row. One transaction, so a promoted gap can never point at a
        keyword that was not written (or vice versa).

        The gap's ``intent`` casts straight onto ``public.search_intent`` because 0037
        REUSES 0035's enum instead of declaring a parallel copy.
        """
        with rls_connection(self._user_id) as cur:
            cur.execute(
                "select keyword, intent, volume, difficulty, opportunity "
                "from public.keyword_gaps where id = %s limit 1",
                (gap_id,),
            )
            gap = cur.fetchone()
            if gap is None:
                return None
            keyword = str(gap["keyword"])

            cur.execute(
                "insert into public.keywords "
                "(client_id, client_name, keyword, geo, volume, difficulty, intent, "
                "opportunity, source) "
                "values (%s, %s, %s, %s, %s, %s, %s, %s, 'gap') "
                "on conflict (client_id, keyword, geo) do nothing "
                "returning id, code",
                (
                    client_id, client_name, keyword, geo, gap["volume"], gap["difficulty"],
                    gap["intent"], gap["opportunity"],
                ),
            )
            row = cur.fetchone()
            created = row is not None
            if row is None:
                # Already banked (by an earlier promote, a research run, or by hand).
                # Re-read it so the gap still gets stamped and the caller still learns
                # the code - a promote that "fails" because the work is already done is
                # not a failure.
                cur.execute(
                    "select id, code from public.keywords "
                    "where client_id is not distinct from %s and keyword = %s "
                    "and geo is not distinct from %s limit 1",
                    (client_id, keyword, geo),
                )
                row = cur.fetchone()
                if row is None:
                    return None

            cur.execute(
                "update public.keyword_gaps set keyword_id = %s where id = %s",
                (row["id"], gap_id),
            )
            return keyword, str(row["code"]), created


def get_competitor_repo(user: CurrentUserDep) -> CompetitorRepo:
    """Dependency: a repo bound to the caller's verified user id (RLS-scoped)."""
    return CompetitorRepo(user.id)


CompetitorRepoDep = Annotated[CompetitorRepo, Depends(get_competitor_repo)]


# --------------------------------------------------------------------------- #
# Privileged (service_role, BYPASSRLS) store for the ANALYSIS worker.
# --------------------------------------------------------------------------- #
# The analysis worker has no user JWT, so - exactly like the audit / context / keyword /
# rank workers - it reads/writes on the privileged connection (service_role bypasses the
# RLS policies by design; note it bypasses POLICIES, not TRIGGERS). Each method opens its
# own privileged connection inside its own transaction, so the store is stateless and
# safe to instantiate per call.
class ServiceCompetitorStore:
    """Concrete competitor store over ``privileged_connection`` (BYPASSRLS)."""

    def get_competitor(self, competitor_id: str) -> dict[str, Any] | None:
        with privileged_connection() as cur:
            cur.execute(
                "select * from public.competitors where id = %s limit 1", (competitor_id,)
            )
            return cur.fetchone()

    def get_client_name(self, client_id: str) -> str | None:
        with privileged_connection() as cur:
            cur.execute("select name from public.clients where id = %s limit 1", (client_id,))
            row = cur.fetchone()
            return str(row["name"]) if row else None

    def client_domain(self, client_id: str) -> str:
        """The client's own site domain (the worker's twin of the repo's read)."""
        with privileged_connection() as cur:
            cur.execute(
                "select domain from public.sites where client_id = %s "
                "order by created_at limit 1",
                (client_id,),
            )
            row = cur.fetchone()
            return str(row["domain"] or "") if row else ""

    def client_positions(self, client_id: str) -> dict[str, int | None]:
        """The client's positions from the Rank Tracker's read model - FREE.

        The worker's twin of ``CompetitorRepo.client_positions``; see that docstring
        for why a ``None`` VALUE is preserved rather than coalesced.
        """
        with privileged_connection() as cur:
            cur.execute(
                "select keyword, latest_position from public.tracked_keywords "
                "where client_id = %s and status = 'active'",
                (client_id,),
            )
            return {
                str(r["keyword"]).strip().lower(): r["latest_position"] for r in cur.fetchall()
            }

    def tracked_keywords_sample(self, client_id: str, *, limit: int) -> list[dict[str, Any]]:
        """The client's highest-volume tracked keywords - discovery's seed set."""
        with privileged_connection() as cur:
            cur.execute(
                "select keyword, coalesce(search_volume, 0) as search_volume "
                "from public.tracked_keywords "
                "where client_id = %s and status = 'active' "
                "order by search_volume desc nulls last, keyword limit %s",
                (client_id, limit),
            )
            return cur.fetchall()

    def existing_domains(self, client_id: str) -> set[str]:
        """Every domain this client already has a competitor row for - INCLUDING the
        parked ones. Discovery must not re-propose a rival an analyst already ruled
        on; excluding only the tracked ones would resurrect every parked domain on the
        next run."""
        with privileged_connection() as cur:
            cur.execute(
                "select domain from public.competitors where client_id = %s", (client_id,)
            )
            return {str(r["domain"]) for r in cur.fetchall()}

    def add_discovered(
        self, *, client_id: str, client_name: str, domain: str, label: str
    ) -> bool:
        """Insert ONE auto-discovered competitor (``discovery_source='serp_auto'``).

        ``on conflict do nothing`` makes a redelivered discovery run a no-op rather
        than an error, and returns False so the worker's count stays honest.
        """
        with privileged_connection() as cur:
            cur.execute(
                "insert into public.competitors "
                "(client_id, client_name, domain, label, discovery_source) "
                "values (%s, %s, %s, %s, 'serp_auto') "
                "on conflict (client_id, domain) do nothing returning id",
                (client_id, client_name, domain, label),
            )
            return cur.fetchone() is not None

    def record_analysis(
        self,
        competitor_id: str,
        *,
        client_id: str,
        gaps: list[dict[str, Any]],
        overlap_pct: float,
        keyword_gaps_count: int,
        common_keywords: int,
        analyzed_at: Any,
    ) -> int:
        """Upsert one analysis's gap rows and roll the competitor's read model forward,
        in ONE transaction. Returns how many gap rows were written.

        IDEMPOTENT on redelivery: ``on conflict (competitor_id, keyword) do update``
        REFRESHES a gap in place rather than duplicating it, so re-running an analysis
        (a Celery redelivery, an operator re-clicking) converges on the same rows. The
        ``keyword_id`` stamp is deliberately NOT touched by the update - a re-analysis
        must not un-promote a gap that has already been banked.

        ``share_of_voice`` is NOT written here: it is a property of the whole
        competitive SET (every domain's visibility divided by the set's total), so one
        competitor's analysis cannot know it. The share-of-voice endpoint computes it
        across the set on read.
        """
        if not gaps:
            # Still roll the read model: an analysis that legitimately found no gaps is
            # a RESULT (a competitor who ranks for nothing we do not), and the stamp is
            # what tells the board it ran.
            self._roll_read_model(
                competitor_id,
                overlap_pct=overlap_pct,
                keyword_gaps_count=keyword_gaps_count,
                common_keywords=common_keywords,
                analyzed_at=analyzed_at,
            )
            return 0

        values = sql.SQL(", ").join(
            sql.SQL("(%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)") for _ in gaps
        )
        params: list[Any] = []
        for gap in gaps:
            params += [
                competitor_id, client_id, gap["keyword"], gap["volume"], gap["difficulty"],
                gap["intent"], gap["competitor_position"], gap["client_position"],
                gap["gap_type"], gap["opportunity"], analyzed_at,
            ]
        stmt = sql.SQL(
            "insert into public.keyword_gaps "
            "(competitor_id, client_id, keyword, volume, difficulty, intent, "
            "competitor_position, client_position, gap_type, opportunity, analyzed_at) "
            "values {values} "
            "on conflict (competitor_id, keyword) do update set "
            "  volume = excluded.volume, difficulty = excluded.difficulty, "
            "  intent = excluded.intent, "
            "  competitor_position = excluded.competitor_position, "
            "  client_position = excluded.client_position, "
            "  gap_type = excluded.gap_type, opportunity = excluded.opportunity, "
            "  analyzed_at = excluded.analyzed_at"
        ).format(values=values)
        with privileged_connection() as cur:
            cur.execute(stmt, params)
            written = cur.rowcount if cur.rowcount and cur.rowcount > 0 else 0
            cur.execute(
                "update public.competitors set "
                "overlap_pct = %s, keyword_gaps_count = %s, common_keywords = %s, "
                "last_analyzed_at = %s where id = %s",
                (overlap_pct, keyword_gaps_count, common_keywords, analyzed_at, competitor_id),
            )
            return written

    def _roll_read_model(
        self,
        competitor_id: str,
        *,
        overlap_pct: float,
        keyword_gaps_count: int,
        common_keywords: int,
        analyzed_at: Any,
    ) -> None:
        with privileged_connection() as cur:
            cur.execute(
                "update public.competitors set "
                "overlap_pct = %s, keyword_gaps_count = %s, common_keywords = %s, "
                "last_analyzed_at = %s where id = %s",
                (overlap_pct, keyword_gaps_count, common_keywords, analyzed_at, competitor_id),
            )


def service_competitor_store() -> ServiceCompetitorStore:
    """The privileged competitor store the analysis worker uses (service_role, BYPASSRLS)."""
    return ServiceCompetitorStore()
