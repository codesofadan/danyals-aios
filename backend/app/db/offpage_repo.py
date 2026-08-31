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

from collections.abc import Sequence
from datetime import date
from typing import Annotated, Any

from fastapi import Depends
from psycopg import sql
from psycopg.types.json import Jsonb

from app.core.auth import CurrentUserDep
from app.db.database import privileged_connection, rls_connection
from app.services.directory_names import canonical_norm

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

    # --- web 2.0 platform CATALOG (reference data, not client-scoped) ----------
    def list_web2_platforms(
        self,
        *,
        auth_type: str | None = None,
        authority_tier: str | None = None,
        automation_ready: bool | None = None,
        market: str | None = None,
    ) -> _Rows:
        """Browse the Web 2.0 platform catalog (0062/0063). Reference data shared by
        every tenant - RLS gates it to staff (``is_staff()``); a portal client sees
        nothing (and is 403'd out of the router before reaching here). Ordered
        automation-ready-first so the actionable rows lead, then by name."""
        query = "select * from public.web2_platforms"
        clauses: list[str] = []
        params: list[Any] = []
        if auth_type is not None:
            clauses.append("auth_type = %s")
            params.append(auth_type)
        if authority_tier is not None:
            clauses.append("authority_tier = %s")
            params.append(authority_tier)
        if automation_ready is not None:
            clauses.append("automation_ready = %s")
            params.append(automation_ready)
        if market is not None:
            clauses.append("market = %s")
            params.append(market)
        if clauses:
            query += " where " + " and ".join(clauses)
        query += " order by automation_ready desc, name"
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
        source_pack: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        """Insert a PLANNED Web 2.0 placement (status ``draft``) and return the row.

        Lead-only by RLS (the web2_properties insert policy). ``client_name`` is a
        display SNAPSHOT; ``source_pack`` is the writer's first-hand grounding (proof /
        testimonials / unique data), read by the write worker so the draft is gap-free.
        The write worker fills the drafted body + flips the status."""
        with rls_connection(self._user_id) as cur:
            cur.execute(
                # account_id is resolved HERE, in the same statement, because the publish
                # worker reads it to find the vault label. Leaving it NULL sends the
                # worker down its legacy client-id fallback, which cannot match a
                # credential sealed under the account id - so a correctly registered
                # account publishes nothing. It also re-arms the per-account pacing
                # ceilings, which key off this column.
                "insert into public.web2_properties "
                "(client_id, client_name, platform, anchor, target_url, topic, "
                "page_type, framework, source_pack, status, account_id) "
                "values (%s, %s, %s, %s, %s, %s, %s, %s, %s, 'draft', "
                "  (select a.id " + self._USABLE_ACCOUNT_FROM +
                "     and a.platform = %s order by a.created_at limit 1)) returning *",
                (
                    client_id, client_name, platform, anchor, target_url, topic,
                    page_type, framework, Jsonb(source_pack or {}),
                    client_id, platform,
                ),
            )
            return cur.fetchone()

    def get_web2(self, web2_id: str) -> dict[str, Any] | None:
        with rls_connection(self._user_id) as cur:
            cur.execute(
                "select * from public.web2_properties where id = %s limit 1", (web2_id,)
            )
            return cur.fetchone()

    # --- campaigns (the operator's unit of work) ---------------------------------- #

    def list_web2_accounts(self, client_id: str | None = None) -> _Rows:
        """Registered publishing accounts, newest first.

        Deliberately returns the vault COORDINATES (provider + label) and never the
        secret: the board needs to know where a credential lives so it can be verified,
        not what it says.
        """
        where = "where a.client_id = %s" if client_id else ""
        params: tuple[Any, ...] = (client_id,) if client_id else ()
        with rls_connection(self._user_id) as cur:
            cur.execute(
                "select a.id, a.platform, a.ownership, a.client_id, a.handle, "
                "       a.property_url, a.registration_email, a.health, "
                "       a.health_checked_at, a.property_count, a.max_properties, "
                "       a.vault_provider, a.vault_label, a.created_at, "
                "       coalesce(c.name, '') as client_name "
                "from public.web2_accounts a "
                "left join public.clients c on c.id = a.client_id "
                f"{where} order by a.created_at desc",
                params,
            )
            return list(cur.fetchall())

    def get_web2_account(self, account_id: str) -> dict[str, Any] | None:
        with rls_connection(self._user_id) as cur:
            cur.execute(
                "select * from public.web2_accounts where id = %s limit 1", (account_id,)
            )
            return cur.fetchone()

    def eligible_catalog(self) -> _Rows:
        """The automation-ready catalogue rows the eligibility service classifies."""
        with rls_connection(self._user_id) as cur:
            cur.execute(
                "select name, platform_enum, ownership_tier, topical_scope, "
                "       automation_ready, authority_tier, terms_position "
                "from public.web2_platforms order by authority_tier, name"
            )
            return list(cur.fetchall())

    #: ONE definition of "an account this client may publish with", shared by the
    #: platform board and by placement creation. They must not drift: a board that says
    #: "connected" while placement creation resolves no account is exactly how a campaign
    #: gets drafted, paid for and approved, and then fails at publish with
    #: "degraded: publisher unconfigured". Takes one parameter: the client id.
    _USABLE_ACCOUNT_FROM = (
        "from public.web2_accounts a "
        "join public.web2_platforms p on p.platform_enum = a.platform "
        "where a.health not in ('suspended', 'deleted') "
        # AND A CREDENTIAL ACTUALLY EXISTS. An account ROW is not a credential: the
        # registration CLI and the portal both create the row first and seal the secret
        # second, so a half-finished registration leaves a row with nothing behind it.
        # Counting that as connected reports the platform "eligible", lets a campaign be
        # planned, DRAFTED AND PAID FOR, and fails only at publish - measured on the
        # canonical database, where 6 platforms showed green and 0 credentials resolved.
        # Existence is all SQL can check; whether the token still authenticates is what
        # the account board's Test-connection is for.
        "  and exists (select 1 from public.vault_keys v "
        "              where v.provider = a.vault_provider and v.label = a.vault_label) "
        "  and ( (p.ownership_tier = 'per_client' "
        "         and a.ownership = 'per_client' "
        "         and a.client_id = %s) "
        "     or (p.ownership_tier = 'house' and a.ownership = 'house') )"
    )

    def connected_platforms_for(self, client_id: str) -> set[str]:
        """Platforms where THIS client has a usable publishing account.

        Ownership is load-bearing, not decoration. A ``per_client`` platform is only
        connected when the client has an account of their OWN: satisfying it with a house
        account is precisely the shared-origin fan-out P1 retired, and it would put one
        agency identity behind every client's links. A ``house`` platform is the case
        where a shared account is legitimate, so a house row connects it.

        Accounts in a terminal state (``suspended``/``deleted``) are not connected - a
        credential that no longer logs in is not a credential, and reporting it as one
        sends the operator to a platform that will fail at publish time.
        """
        with rls_connection(self._user_id) as cur:
            cur.execute(
                "select distinct a.platform " + self._USABLE_ACCOUNT_FROM, (client_id,)
            )
            return {str(r["platform"]) for r in cur.fetchall()}

    def client_web2_scope(self, client_id: str) -> str:
        """The client's declared topical scope (defaults to the safe agnostic set)."""
        with rls_connection(self._user_id) as cur:
            cur.execute(
                "select web2_topical_scope from public.clients where id = %s", (client_id,)
            )
            row = cur.fetchone()
        return str(row["web2_topical_scope"]) if row else "agnostic"

    def pacing_caps_row(self) -> dict[str, Any] | None:
        with rls_connection(self._user_id) as cur:
            cur.execute("select * from public.web2_pacing_settings where id = 1")
            return cur.fetchone()

    def client_publish_history(self, client_id: str, *, days: int = 120) -> _Rows:
        """Recent placements, for pacing. A campaign does not start from zero for a
        client who published yesterday."""
        with rls_connection(self._user_id) as cur:
            cur.execute(
                "select id, client_id, platform, account_id, published_at, scheduled_for "
                "from public.web2_properties "
                "where client_id = %s "
                "  and coalesce(published_at::timestamptz, scheduled_for) is not null "
                "  and coalesce(published_at::timestamptz, scheduled_for) "
                "      > now() - make_interval(days => %s) "
                "order by coalesce(published_at::timestamptz, scheduled_for) desc",
                (client_id, days),
            )
            return list(cur.fetchall())

    def create_campaign(
        self,
        *,
        client_id: str,
        client_name: str,
        title: str,
        article_count: int,
        platforms: list[str],
        pacing: str,
        drip_window_days: int,
        target_url: str,
        cost_ceiling_usd: float,
        created_by: str | None,
    ) -> dict[str, Any] | None:
        """Insert the campaign row (lead-only by RLS) at status ``planning``."""
        with rls_connection(self._user_id) as cur:
            cur.execute(
                "insert into public.web2_campaigns "
                "(client_id, client_name, title, article_count, platforms, pacing, "
                " drip_window_days, target_url, cost_ceiling_usd, created_by, status) "
                "values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'planning') returning *",
                (
                    client_id, client_name, title, article_count, platforms, pacing,
                    drip_window_days, target_url, cost_ceiling_usd, created_by,
                ),
            )
            return cur.fetchone()

    def get_campaign(self, campaign_id: str) -> dict[str, Any] | None:
        with rls_connection(self._user_id) as cur:
            cur.execute(
                "select * from public.web2_campaigns where id = %s limit 1", (campaign_id,)
            )
            return cur.fetchone()

    def list_campaigns(self, *, client_id: str | None = None, limit: int = 50) -> _Rows:
        with rls_connection(self._user_id) as cur:
            if client_id:
                cur.execute(
                    "select * from public.web2_campaigns where client_id = %s "
                    "order by created_at desc limit %s",
                    (client_id, limit),
                )
            else:
                cur.execute(
                    "select * from public.web2_campaigns order by created_at desc limit %s",
                    (limit,),
                )
            return list(cur.fetchall())

    def campaign_properties(self, campaign_id: str) -> _Rows:
        with rls_connection(self._user_id) as cur:
            cur.execute(
                "select id, platform, topic, anchor, status, post_url, verified, "
                "       scheduled_for, error "
                "from public.web2_properties where campaign_id = %s order by scheduled_for",
                (campaign_id,),
            )
            return list(cur.fetchall())

    def campaign_placements(self, campaign_id: str) -> _Rows:
        """The full per-placement record behind a campaign - the operator's audit trail.

        Separate from `campaign_properties` (which feeds the rollup and stays lean)
        because this is the DELIVERABLE view: every fact needed to answer "what did we
        actually build, where is it, and is the link really live". All of it was already
        stored and none of it was reachable, which is why a finished campaign could not
        be shown to a client.

        The account handle is joined in so the row says WHICH identity published it -
        without that, a shared-account placement is indistinguishable from a client-owned
        one on screen, which is exactly the distinction that matters.
        """
        with rls_connection(self._user_id) as cur:
            cur.execute(
                "select p.id, p.client_name, p.platform, p.topic, p.framework, p.anchor, "
                "       p.target_url, p.post_url, p.status, p.verified, p.error, "
                "       p.link_rel, p.link_found, p.link_checked_at, p.scheduled_for, "
                "       p.published_at, p.created_at, p.updated_at, p.shared_origin, "
                "       coalesce(a.handle, '') as account_handle, "
                "       coalesce(a.ownership::text, '') as account_ownership "
                "from public.web2_properties p "
                "left join public.web2_accounts a on a.id = p.account_id "
                "where p.campaign_id = %s "
                "order by coalesce(p.published_at::timestamptz, p.scheduled_for), p.platform",
                (campaign_id,),
            )
            return list(cur.fetchall())

    def client_placements(self, client_id: str | None = None, *, limit: int = 500) -> _Rows:
        """Every placement, newest first - the cross-campaign ledger.

        A client's Web 2.0 history is not one campaign: it is everything ever published
        for them, including the single-property builds that predate campaigns. Scoping by
        campaign alone would hide those.
        """
        where = "where p.client_id = %s" if client_id else ""
        params: tuple[Any, ...] = (client_id, limit) if client_id else (limit,)
        with rls_connection(self._user_id) as cur:
            cur.execute(
                "select p.id, p.client_name, p.platform, p.topic, p.framework, p.anchor, "
                "       p.target_url, p.post_url, p.status, p.verified, p.error, "
                "       p.link_rel, p.link_found, p.link_checked_at, p.scheduled_for, "
                "       p.published_at, p.created_at, p.updated_at, p.shared_origin, "
                "       p.campaign_id, "
                "       coalesce(a.handle, '') as account_handle, "
                "       coalesce(a.ownership::text, '') as account_ownership "
                "from public.web2_properties p "
                "left join public.web2_accounts a on a.id = p.account_id "
                f"{where} "
                "order by p.created_at desc limit %s",
                params,
            )
            return list(cur.fetchall())

    def update_campaign(self, campaign_id: str, fields: dict[str, Any]) -> dict[str, Any] | None:
        if not fields:
            return self.get_campaign(campaign_id)
        cols = list(fields.keys())
        assignments = sql.SQL(", ").join(
            sql.SQL("{} = %s").format(sql.Identifier(c)) for c in cols
        )
        stmt = sql.SQL(
            "update public.web2_campaigns set {} where id = %s returning *"
        ).format(assignments)
        with rls_connection(self._user_id) as cur:
            cur.execute(stmt, (*[fields[c] for c in cols], campaign_id))
            return cur.fetchone()

    def attach_property_to_campaign(
        self, web2_id: str, campaign_id: str, scheduled_for: Any
    ) -> None:
        with rls_connection(self._user_id) as cur:
            cur.execute(
                "update public.web2_properties set campaign_id = %s, scheduled_for = %s "
                "where id = %s",
                (campaign_id, scheduled_for, web2_id),
            )

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
        """The placement row, plus the client's city as ``client_geo``.

        The LEFT JOIN carries the one fact the row itself cannot: ``web2_properties``
        has no geo column, but the writer wants a geo signal (``Web2Client.geo`` feeds
        the research brief and the generation context) and the similarity gate MUST
        mask the city before shingling - the varying city token is precisely what hides
        templating from a raw comparison. ``p.*`` is preserved, so every existing key is
        unchanged and this is additive for all callers; a client with no business
        profile yields ``''`` rather than a missing key.
        """
        with privileged_connection() as cur:
            cur.execute(
                "select p.*, coalesce(b.city, '') as client_geo "
                "from public.web2_properties p "
                "left join public.client_business_profiles b on b.client_id = p.client_id "
                "where p.id = %s limit 1",
                (web2_id,),
            )
            return cur.fetchone()

    def web2_account_vault(self, account_id: str) -> dict[str, Any] | None:
        """The vault COORDINATES of one publishing account (never the secret).

        The publish worker must read the label from the ACCOUNT ROW rather than assume it
        equals the account id. The two are usually the same, but a house account migrated
        by ``web2_migrate_house`` deliberately keeps its LEGACY client-id label so the
        already-sealed secret stays reachable. Inferring the label instead of reading it
        therefore fails in one direction or the other, and this is also the exact source
        the accounts board and the credential-check endpoint read - so all three agree.
        """
        with privileged_connection() as cur:
            cur.execute(
                "select id, platform, ownership, client_id, health, "
                "       vault_provider, vault_label "
                "from public.web2_accounts where id = %s limit 1",
                (account_id,),
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

    def directory_ids_by_name(self) -> dict[str, str]:
        """Catalog name (canonically normalised) -> directory id, over the whole catalog.

        Lets a DISCOVERED listing be written with the same ``directory_id`` a campaign
        row would carry. Without it, discovery wrote a free-text name and NULL, so the
        gap report could only match those rows by name - and the names differ ("Google
        Business" vs "Google Business Profile", "Bing Places" vs "Bing Places for
        Business"). A listing the client demonstrably had was therefore reported as
        missing, and the count moved between runs depending on which names happened to
        line up. Measured against the live catalog: 11 of the 31 names discovery can
        emit did not match.

        A name that normalises to two different catalog rows is dropped rather than
        guessed: marking the wrong directory covered would suppress a build that never
        happened, and there is no signal afterwards that it went wrong. That guard is
        also why this does not need to be scoped by market - a name that is unique
        across the catalog is unambiguous in any market, and one that is not is
        skipped either way.
        """
        with privileged_connection() as cur:
            cur.execute("select id, name from public.directories where active")
            rows = cur.fetchall()
        by_key: dict[str, list[str]] = {}
        for r in rows:
            by_key.setdefault(canonical_norm(str(r["name"])), []).append(str(r["id"]))
        return {k: v[0] for k, v in by_key.items() if len(v) == 1}

    def insert_citation(
        self,
        *,
        client_id: str | None,
        client_name: str,
        directory: str,
        nap_status: str,
        action: str,
        note: str,
        directory_id: str | None = None,
    ) -> None:
        with privileged_connection() as cur:
            cur.execute(
                "insert into public.citations "
                "(client_id, client_name, directory, nap_status, action, note, directory_id) "
                "values (%s, %s, %s, %s, %s, %s, %s)",
                (client_id, client_name, directory, nap_status, action, note, directory_id),
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


    # --- the cross-property similarity gate (WEB2-007 / R2-09..R2-11) ------------- #
    #
    # These two methods are the ONLY place the platform reads across tenants on purpose.
    # They return hashes and ids - never another client's text - so a collision can be
    # reported ("this duplicates property X on the same house account") without exposing
    # what X says. Both run on the privileged pool for exactly that reason.

    def web2_similarity_candidates(
        self,
        *,
        sampled_hashes: Sequence[int],
        body_sha256: str,
        client_id: str | None,
        account_id: str | None,
        platform: str,
        exclude_web2_id: str,
        platform_window_days: int = 90,
        min_shared: int = 2,
        limit: int = 200,
    ) -> _Rows:
        """Prior fingerprints that could plausibly collide with this draft.

        TWO queries deliberately, unioned, because they fail in different ways:

        1. An EXACT `body_sha256` match, looked up directly on its index. This must not
           depend on the shingle sample: a short draft yields very few sampled hashes
           (measured: a 35-shingle document samples 3), so it can be arithmetically
           impossible for it to share `min_shared` with anything - and an identical copy
           of a short article would then sail through a sample-only search. The exact
           check is cheap and has no such blind spot.
        2. Broder MOD_16 candidate generation - prior documents sharing at least
           `min_shared` SAMPLED hashes. Narrows the field; scoring then runs on the full
           arrays, so the sample can never change a verdict, only what gets scored.

        Scope (R2-10) is applied in SQL rather than in Python so a cross-tenant read is
        never wider than the three scopes justify: S1 the client's own set, S2 everyone
        sharing this house ACCOUNT, S3 the same platform in a rolling window.
        """
        scope_sql = [
            "(f.client_id = %(client_id)s)",
            "(f.platform = %(platform)s and f.created_at > now() - make_interval(days => %(win)s))",
        ]
        params: dict[str, Any] = {
            "client_id": client_id,
            "platform": platform,
            "win": platform_window_days,
            "exclude": exclude_web2_id,
            "sha": body_sha256,
            "hashes": list(sampled_hashes),
            "min_shared": min_shared,
            "limit": limit,
            "account_id": account_id,
        }
        # S2 only exists for a property with a known account. A NULL account_id must not
        # widen into "every property whose account is also unknown" - that would compare
        # unrelated clients under a scope label that claims they share a login.
        if account_id:
            scope_sql.append("(f.account_id = %(account_id)s)")
        scopes = " or ".join(scope_sql)

        # NOTE ON THE SHAPE, because two earlier versions of this query were WRONG in
        # ways that made the gate look installed while missing the thing it exists to
        # catch. Both were reproduced on a real corpus before being fixed:
        #
        #  * `exact` reads the BASE TABLE, not the `scoped` CTE. `scoped` is referenced
        #    twice, so Postgres materializes it and an equality filter over the CTE can
        #    never use `web2_doc_fp_sha_idx` - it scans every scoped row instead.
        #  * The outer LIMIT is ordered by `shared`, NOT by `id`. `distinct on (id)`
        #    forces `id` to lead the INNER order, so ordering the whole thing by `id`
        #    made `limit` keep the 200 lowest UUIDs - i.e. an arbitrary subset. An exact
        #    duplicate with a high uuid was silently discarded and the gate returned
        #    `pass`, and it degraded as the corpus grew: worst exactly where it matters.
        sql_text = f"""
            with scoped as (
                select f.id, f.web2_id, f.client_id, f.account_id, f.platform,
                       f.body_sha256, f.shingle_hashes, f.heading_hashes, f.anchor_norm,
                       f.created_at
                from public.web2_doc_fingerprints f
                where f.web2_id <> %(exclude)s and ({scopes})
            ),
            exact as (
                select f.id, f.web2_id, f.client_id, f.account_id, f.platform,
                       f.body_sha256, f.shingle_hashes, f.heading_hashes, f.anchor_norm,
                       f.created_at, 2147483647 as shared
                from public.web2_doc_fingerprints f
                where f.body_sha256 = %(sha)s and f.web2_id <> %(exclude)s and ({scopes})
            ),
            sampled as (
                select s.*, count(*)::int as shared
                from scoped s
                join public.web2_shingle_index i on i.fingerprint_id = s.id
                where i.shingle_hash = any(%(hashes)s)
                group by s.id, s.web2_id, s.client_id, s.account_id, s.platform,
                         s.body_sha256, s.shingle_hashes, s.heading_hashes, s.anchor_norm,
                         s.created_at
                having count(*) >= %(min_shared)s
            )
            select * from (
                select distinct on (id) * from (
                    select * from exact union all select * from sampled
                ) u
                order by id, shared desc
            ) d
            order by d.shared desc, d.created_at desc
            limit %(limit)s
        """
        with privileged_connection() as cur:
            cur.execute(sql_text, params)
            return list(cur.fetchall())

    def record_web2_fingerprint(
        self,
        *,
        web2_id: str,
        client_id: str,
        account_id: str | None,
        platform: str,
        body_sha256: str,
        shingle_hashes: Sequence[int],
        heading_hashes: Sequence[int],
        sampled_hashes: Sequence[int],
        anchor_norm: str,
        status_at_capture: str,
    ) -> str | None:
        """Persist (or replace) one property's fingerprint and its MOD_16 sample.

        Called on APPROVAL, never on draft (R2-11): a rejected or redrafted article must
        not become part of the corpus that later drafts are measured against, or a bad
        draft would permanently poison its own client's remaining properties.

        Replace-not-append: the unique index on `web2_id` means a re-approval overwrites,
        and the sample rows cascade with it, so a redraft cannot leave its old shingles
        behind to collide with its own replacement.
        """
        with privileged_connection() as cur:
            cur.execute(
                "delete from public.web2_doc_fingerprints where web2_id = %s", (web2_id,)
            )
            cur.execute(
                "insert into public.web2_doc_fingerprints "
                "(web2_id, client_id, account_id, platform, body_sha256, shingle_hashes, "
                " shingle_count, heading_hashes, anchor_norm, status_at_capture) "
                "values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) returning id",
                (
                    web2_id, client_id, account_id, platform, body_sha256,
                    list(shingle_hashes), len(shingle_hashes), list(heading_hashes),
                    anchor_norm, status_at_capture,
                ),
            )
            row = cur.fetchone()
            if row is None:
                return None
            fingerprint_id = str(row["id"] if isinstance(row, dict) else row[0])
            if sampled_hashes:
                cur.executemany(
                    "insert into public.web2_shingle_index (shingle_hash, fingerprint_id) "
                    "values (%s, %s) on conflict do nothing",
                    [(h, fingerprint_id) for h in sampled_hashes],
                )
            return fingerprint_id

    def pacing_caps_row(self) -> dict[str, Any] | None:
        """The agency-global pacing caps (privileged read for the release tick)."""
        with privileged_connection() as cur:
            cur.execute("select * from public.web2_pacing_settings where id = 1")
            return cur.fetchone()

    def recent_web2_publishes(self, *, days: int = 45) -> _Rows:
        """Recent LIVE placements across all clients, for the release tick's cap checks.

        Cross-client on purpose: the house-account ceilings are a property of the shared
        account, not of any one client, so a per-client view could not enforce them.
        Bounded to a window because the caps only ever look back 30 days.
        """
        with privileged_connection() as cur:
            cur.execute(
                "select p.id as web2_id, p.client_id, p.platform, p.account_id, "
                "       p.published_at::timestamptz as published_at, "
                "       coalesce(a.ownership::text, 'per_client') as ownership "
                "from public.web2_properties p "
                "left join public.web2_accounts a on a.id = p.account_id "
                "where p.published_at is not null "
                "  and p.published_at::timestamptz > now() - make_interval(days => %s)",
                (days,),
            )
            return list(cur.fetchall())

    def set_web2_account_health(
        self, account_id: str, *, health: str, checked_at: Any
    ) -> dict[str, Any] | None:
        """Record what a verification actually found.

        Written only from a real check, so `health_checked_at` always answers "when did
        someone last confirm this" rather than "when was the row touched".
        """
        with privileged_connection() as cur:
            cur.execute(
                "update public.web2_accounts set health = %s, health_checked_at = %s "
                "where id = %s returning *",
                (health, checked_at, account_id),
            )
            return cur.fetchone()

    def known_web2_urls(self) -> set[str]:
        """Every published property URL plus every account's property URL.

        R2-15 bans inter-property linking outright: a graph with edges between our own
        properties is the clearest network tell available to a platform or to Google, and
        unlike prose similarity it is trivially machine-detectable from the open web.
        """
        urls: set[str] = set()
        with privileged_connection() as cur:
            cur.execute(
                "select post_url from public.web2_properties "
                "where post_url is not null and post_url <> ''"
            )
            for row in cur.fetchall():
                urls.add(str(row["post_url"] if isinstance(row, dict) else row[0]))
            cur.execute(
                "select property_url from public.web2_accounts "
                "where property_url is not null and property_url <> ''"
            )
            for row in cur.fetchall():
                urls.add(str(row["property_url"] if isinstance(row, dict) else row[0]))
        return urls


def service_offpage_store() -> ServiceOffpageStore:
    """The privileged off-page store the workers use (service_role, BYPASSRLS)."""
    return ServiceOffpageStore()
