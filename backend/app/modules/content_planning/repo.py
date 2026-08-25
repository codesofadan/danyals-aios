"""Data access for the planning layer (migrations 0084-0092).

The pipeline runs on Celery with no user JWT, so it writes through
``privileged_connection`` (service_role, BYPASSRLS) exactly like every other module's
worker path. That is a real privilege, so the store keeps a narrow surface: the
methods the stages actually need, and nothing that would let a caller reach past its
own engagement.

SQL rules (impersonation-review mandate): every VALUE is a bound param, never
string-formatted; table and column names are static literals.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import Depends
from psycopg.types.json import Jsonb

from app.core.auth import CurrentUserDep
from app.db.database import privileged_connection, rls_connection
from app.modules.content_planning.schemas import (
    Engagement,
    KeywordTerm,
    MapNode,
    ShingleOverlap,
    SmeDossier,
    SmeSlot,
)
from app.services.brand_kit import BRAND_ASSET_KINDS

_Row = dict[str, Any]


def _engagement(row: _Row) -> Engagement:
    return Engagement(
        id=str(row["id"]), shape=row["shape"], status=row["status"],
        client_id=str(row["client_id"]) if row.get("client_id") else None,
        client_name=row.get("client_name") or "", name=row.get("name") or "",
        scope=row.get("scope") or {},
        budget_cap=float(row["budget_cap"]) if row.get("budget_cap") is not None else None,
        page_target=row.get("page_target") or 0,
        source_audit_id=str(row["source_audit_id"]) if row.get("source_audit_id") else None,
        owner_id=str(row["owner_id"]) if row.get("owner_id") else None,
        created_at=row.get("created_at"),
    )


def _node(row: _Row) -> MapNode:
    return MapNode(
        id=str(row["id"]), map_id=str(row["map_id"]),
        primary_keyword=row["primary_keyword"], status=row["status"], role=row["role"],
        parent_id=str(row["parent_id"]) if row.get("parent_id") else None,
        silo=row.get("silo") or "", page_type=row.get("page_type") or "service",
        secondary_keywords=tuple(row.get("secondary_keywords") or ()),
        intent=row.get("intent") or "", target_city=row.get("target_city") or "",
        priority=row.get("priority") or 0, target_words=row.get("target_words") or 0,
        cluster_key=row.get("cluster_key") or "", evidence=row.get("evidence") or "",
        info_gain_thesis=row.get("info_gain_thesis") or "",
        content_job_id=str(row["content_job_id"]) if row.get("content_job_id") else None,
        published_url=row.get("published_url") or "",
    )


class ContentPlanningStore:
    """Privileged store over the planning tables, for the pipeline."""

    # --- engagements ------------------------------------------------------- #
    def get_engagement(self, engagement_id: str) -> Engagement | None:
        with privileged_connection() as cur:
            cur.execute(
                "select * from public.content_engagements where id = %s limit 1",
                (engagement_id,),
            )
            row = cur.fetchone()
        return _engagement(row) if row else None

    def create_engagement(
        self, *, shape: str, client_id: str | None = None, client_name: str = "",
        name: str = "", scope: dict[str, Any] | None = None,
        budget_cap: float | None = None, page_target: int = 0,
        source_audit_id: str | None = None, owner_id: str | None = None,
        created_by: str | None = None,
    ) -> Engagement:
        with privileged_connection() as cur:
            cur.execute(
                "insert into public.content_engagements "
                "(shape, client_id, client_name, name, scope, budget_cap, page_target, "
                " source_audit_id, owner_id, created_by) "
                "values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) returning *",
                (shape, client_id, client_name, name, Jsonb(scope or {}), budget_cap,
                 page_target, source_audit_id, owner_id, created_by),
            )
            row = cur.fetchone()
        if row is None:  # pragma: no cover - insert...returning always yields a row
            raise RuntimeError("content_engagements insert returned no row")
        return _engagement(row)

    def set_engagement_status(self, engagement_id: str, status: str) -> None:
        with privileged_connection() as cur:
            cur.execute(
                "update public.content_engagements set status = %s where id = %s",
                (status, engagement_id),
            )

    # --- keyword plans ----------------------------------------------------- #
    def create_keyword_plan(
        self, *, engagement_id: str, seed_terms: list[str], geo: str = "",
        provider: str = "",
    ) -> str:
        with privileged_connection() as cur:
            cur.execute(
                "insert into public.keyword_plans (engagement_id, seed_terms, geo, provider) "
                "values (%s,%s,%s,%s) returning id",
                (engagement_id, seed_terms, geo, provider),
            )
            row = cur.fetchone()
        if row is None:  # pragma: no cover
            raise RuntimeError("keyword_plans insert returned no row")
        return str(row["id"])

    def add_keyword_terms(self, plan_id: str, terms: list[KeywordTerm]) -> int:
        """Insert terms, skipping duplicates.

        ON CONFLICT DO NOTHING rather than an error: a plan legitimately re-runs
        (a second seed, a widened geo) and colliding on a keyword already captured is
        expected, not a failure worth aborting the pull for.
        """
        if not terms:
            return 0
        with privileged_connection() as cur:
            cur.executemany(
                "insert into public.keyword_plan_terms "
                "(plan_id, keyword, volume, difficulty, cpc, competition, intent, "
                " source, estimated, relevance, opportunity, cluster_key) "
                "values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
                "on conflict (plan_id, lower(keyword)) do nothing",
                [
                    (plan_id, t.keyword, t.volume, t.difficulty, t.cpc, t.competition,
                     t.intent, t.source, t.estimated, t.relevance, t.opportunity,
                     t.cluster_key)
                    for t in terms
                ],
            )
        return len(terms)

    def keyword_terms(self, plan_id: str, *, measured_only: bool = False) -> list[KeywordTerm]:
        sql = "select * from public.keyword_plan_terms where plan_id = %s"
        if measured_only:
            sql += " and estimated = false"
        sql += " order by volume desc nulls last, keyword"
        with privileged_connection() as cur:
            cur.execute(sql, (plan_id,))
            rows = cur.fetchall()
        return [
            KeywordTerm(
                keyword=r["keyword"], source=r["source"], estimated=r["estimated"],
                volume=r.get("volume"),
                difficulty=float(r["difficulty"]) if r.get("difficulty") is not None else None,
                cpc=float(r["cpc"]) if r.get("cpc") is not None else None,
                competition=float(r["competition"]) if r.get("competition") is not None else None,
                intent=r.get("intent") or "",
                relevance=float(r["relevance"]) if r.get("relevance") is not None else None,
                opportunity=float(r["opportunity"]) if r.get("opportunity") is not None else None,
                cluster_key=r.get("cluster_key") or "",
            )
            for r in rows
        ]

    # --- topical map ------------------------------------------------------- #
    def create_map(self, *, engagement_id: str, plan_id: str | None = None) -> str:
        with privileged_connection() as cur:
            cur.execute(
                "insert into public.topical_maps (engagement_id, plan_id) values (%s,%s) "
                "returning id",
                (engagement_id, plan_id),
            )
            row = cur.fetchone()
        if row is None:  # pragma: no cover
            raise RuntimeError("topical_maps insert returned no row")
        return str(row["id"])

    def add_node(
        self, *, map_id: str, primary_keyword: str, page_type: str = "service",
        role: str = "spoke", silo: str = "", parent_id: str | None = None,
        secondary_keywords: list[str] | None = None, intent: str = "",
        target_city: str = "", priority: int = 0, target_words: int = 0,
        cluster_key: str = "", evidence: str = "", info_gain_thesis: str = "",
        status: str = "planned",
    ) -> MapNode:
        with privileged_connection() as cur:
            cur.execute(
                "insert into public.topical_map_nodes "
                "(map_id, primary_keyword, page_type, role, silo, parent_id, "
                " secondary_keywords, intent, target_city, priority, target_words, "
                " cluster_key, evidence, info_gain_thesis, status) "
                "values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) returning *",
                (map_id, primary_keyword, page_type, role, silo, parent_id,
                 secondary_keywords or [], intent, target_city, priority, target_words,
                 cluster_key, evidence, info_gain_thesis, status),
            )
            row = cur.fetchone()
        if row is None:  # pragma: no cover
            raise RuntimeError("topical_map_nodes insert returned no row")
        return _node(row)

    def map_nodes(self, map_id: str) -> list[MapNode]:
        with privileged_connection() as cur:
            cur.execute(
                "select * from public.topical_map_nodes where map_id = %s "
                "order by priority desc, primary_keyword",
                (map_id,),
            )
            rows = cur.fetchall()
        return [_node(r) for r in rows]

    def add_link_edge(
        self, *, map_id: str, from_node_id: str, to_node_id: str, anchor_text: str = "",
        rationale: str = "",
    ) -> None:
        with privileged_connection() as cur:
            cur.execute(
                "insert into public.internal_link_edges "
                "(map_id, from_node_id, to_node_id, anchor_text, rationale) "
                "values (%s,%s,%s,%s,%s) on conflict (from_node_id, to_node_id) do nothing",
                (map_id, from_node_id, to_node_id, anchor_text, rationale),
            )

    # --- SME dossier: the hard halt ---------------------------------------- #
    def get_or_create_dossier(self, *, engagement_id: str, cluster_key: str = "") -> SmeDossier:
        with privileged_connection() as cur:
            cur.execute(
                "insert into public.sme_dossiers (engagement_id, cluster_key) values (%s,%s) "
                "on conflict (engagement_id, cluster_key) do update set cluster_key = excluded.cluster_key "
                "returning *",
                (engagement_id, cluster_key),
            )
            row = cur.fetchone()
            if row is None:  # pragma: no cover
                raise RuntimeError("sme_dossiers upsert returned no row")
            dossier_id = str(row["id"])
            cur.execute(
                "select * from public.sme_slots where dossier_id = %s order by slot_key",
                (dossier_id,),
            )
            slots = cur.fetchall()
        return SmeDossier(
            id=dossier_id, engagement_id=str(row["engagement_id"]),
            cluster_key=row.get("cluster_key") or "", status=row["status"],
            slots=tuple(
                SmeSlot(
                    slot_key=s["slot_key"], question=s.get("question") or "",
                    answer=s.get("answer") or "", artifact_url=s.get("artifact_url") or "",
                    artifact_date=s.get("artifact_date"), source=s["source"],
                    confidence=float(s.get("confidence") or 1.0),
                )
                for s in slots
            ),
        )

    def upsert_slot(
        self, *, dossier_id: str, slot_key: str, question: str = "", answer: str = "",
        artifact_url: str = "", artifact_date: Any = None, source: str = "operator",
        confidence: float = 1.0,
    ) -> None:
        with privileged_connection() as cur:
            cur.execute(
                "insert into public.sme_slots "
                "(dossier_id, slot_key, question, answer, artifact_url, artifact_date, "
                " source, confidence) values (%s,%s,%s,%s,%s,%s,%s,%s) "
                "on conflict (dossier_id, slot_key) do update set "
                "  question = excluded.question, answer = excluded.answer, "
                "  artifact_url = excluded.artifact_url, artifact_date = excluded.artifact_date, "
                "  source = excluded.source, confidence = excluded.confidence",
                (dossier_id, slot_key, question, answer, artifact_url, artifact_date,
                 source, confidence),
            )

    def refresh_dossier_status(self, dossier_id: str) -> str:
        """Recompute status from the slots and store it.

        Derived rather than set by callers: a status a caller can assert is a status
        that drifts from the rows, and this one gates drafting.
        """
        with privileged_connection() as cur:
            cur.execute(
                "select count(*) as total, "
                "  count(*) filter (where answer <> '' or artifact_url <> '') as answered "
                "from public.sme_slots where dossier_id = %s",
                (dossier_id,),
            )
            row = cur.fetchone() or {"total": 0, "answered": 0}
            total, answered = int(row["total"]), int(row["answered"])
            status = "complete" if total and answered == total else ("partial" if answered else "empty")
            cur.execute(
                "update public.sme_dossiers set status = %s where id = %s", (status, dossier_id)
            )
        return status

    # --- the cross-page uniqueness gate ------------------------------------ #
    def record_shingles(
        self, *, hashes: frozenset[int], job_id: str | None = None,
        node_id: str | None = None, client_id: str | None = None, vertical: str = "",
    ) -> int:
        if not hashes:
            return 0
        with privileged_connection() as cur:
            cur.executemany(
                "insert into public.content_outline_shingles "
                "(job_id, node_id, client_id, vertical, shingle_hash, masked) "
                "values (%s,%s,%s,%s,%s,true)",
                [(job_id, node_id, client_id, vertical, h) for h in hashes],
            )
        return len(hashes)

    def find_overlaps(
        self, *, hashes: frozenset[int], vertical: str = "", client_id: str | None = None,
        exclude_job_id: str | None = None, min_shared: int = 1, limit: int = 10,
    ) -> list[ShingleOverlap]:
        """Prior pages sharing shingles with a candidate outline.

        This is the query the whole shingle table exists for, and it is a SQL
        intersection rather than a Python set comparison because comparing a new
        outline against every prior page in a vertical cannot hold those sets in
        memory.

        Only `masked = true` rows count. An unmasked hash was computed over raw text,
        which measurably fails to catch the templated case (the varying entity token
        hides inside most shingles), so including them would inflate the denominator
        with rows that cannot detect what this is looking for.
        """
        if not hashes:
            return []
        clauses = ["masked = true", "shingle_hash = any(%s)"]
        params: list[Any] = [list(hashes)]
        if vertical and client_id:
            clauses.append("(vertical = %s or client_id = %s)")
            params += [vertical, client_id]
        elif vertical:
            clauses.append("vertical = %s")
            params.append(vertical)
        elif client_id:
            clauses.append("client_id = %s")
            params.append(client_id)
        if exclude_job_id:
            clauses.append("(job_id is distinct from %s)")
            params.append(exclude_job_id)

        params.extend([min_shared, limit])
        with privileged_connection() as cur:
            cur.execute(
                "select job_id, node_id, count(*) as shared "
                "from public.content_outline_shingles "
                f"where {' and '.join(clauses)} "
                "group by job_id, node_id having count(*) >= %s "
                "order by shared desc limit %s",
                tuple(params),
            )
            rows = cur.fetchall()
        total = len(hashes)
        return [
            ShingleOverlap(
                job_id=str(r["job_id"]) if r.get("job_id") else None,
                node_id=str(r["node_id"]) if r.get("node_id") else None,
                shared=int(r["shared"]), total=total,
            )
            for r in rows
        ]

    # --- provenance --------------------------------------------------------- #
    def record_doctrine_usage(
        self, *, stage: str, model: str, chunk_ids: list[str],
        dropped_chunk_ids: list[str] | None = None, job_id: str | None = None,
        version_id: str | None = None, engagement_id: str | None = None,
        input_tokens: int = 0, output_tokens: int = 0, cache_write_tokens: int = 0,
        cache_read_tokens: int = 0, cost: float = 0.0,
    ) -> None:
        """Append one call's provenance. Written as the call happens, because it
        cannot be reconstructed later once the routing table has moved on."""
        with privileged_connection() as cur:
            cur.execute(
                "insert into public.doctrine_usage "
                "(job_id, version_id, engagement_id, stage, model, chunk_ids, "
                " dropped_chunk_ids, input_tokens, output_tokens, cache_write_tokens, "
                " cache_read_tokens, cost) values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (job_id, version_id, engagement_id, stage, model, chunk_ids,
                 dropped_chunk_ids or [], input_tokens, output_tokens,
                 cache_write_tokens, cache_read_tokens, cost),
            )

    # --- brand kits (P6.1) --------------------------------------------------- #
    def active_brand_kit(self, client_id: str) -> _Row | None:
        """The client's current kit, or None.

        "Current" is a DATABASE guarantee, not a convention this method upholds:
        `brand_kits_active_per_client_idx` is a partial unique index on
        `(client_id) where active`, so two active kits cannot exist to choose between.
        """
        with privileged_connection() as cur:
            cur.execute(
                "select * from public.brand_kits where client_id = %s and active limit 1",
                (client_id,),
            )
            return cur.fetchone()

    def save_brand_kit(
        self,
        *,
        client_id: str,
        source_url: str,
        palette: dict[str, Any],
        typography: dict[str, Any],
        spacing: dict[str, Any],
        components: dict[str, Any],
        blueprint: list[dict[str, Any]],
        raw_measurements: dict[str, Any] | None = None,
    ) -> str:
        """Store a new kit VERSION and make it the active one.

        A new capture never overwrites the old kit. Pages published under v1 have to
        stay explainable after the client redesigns, and an overwrite silently rewrites
        the history of every page that already shipped.

        Deactivate-then-insert in ONE transaction, because the partial unique index
        means the intermediate state - two active kits - is not merely untidy, it is
        rejected. Doing it in two statements outside a transaction would leave a client
        with no active kit if the insert failed.
        """
        with privileged_connection() as cur:
            cur.execute(
                "select coalesce(max(version), 0) + 1 as next "
                "from public.brand_kits where client_id = %s",
                (client_id,),
            )
            row = cur.fetchone()
            version = int((row or {}).get("next") or 1)

            cur.execute(
                "update public.brand_kits set active = false "
                "where client_id = %s and active",
                (client_id,),
            )
            cur.execute(
                """insert into public.brand_kits
                     (client_id, source_url, version, palette, typography, spacing,
                      components, blueprint, raw_measurements, active)
                   values (%s, %s, %s, %s, %s, %s, %s, %s, %s, true)
                   returning id""",
                (
                    client_id, source_url, version, Jsonb(palette), Jsonb(typography),
                    Jsonb(spacing), Jsonb(components), Jsonb(blueprint),
                    Jsonb(raw_measurements or {}),
                ),
            )
            inserted = cur.fetchone()
            if inserted is None:  # a RETURNING insert that yields nothing is a bug
                raise RuntimeError("brand kit insert returned no id")
            return str(inserted["id"])

    def record_brand_asset(
        self,
        *,
        kit_id: str,
        kind: str,
        source_url: str,
        stored_key: str = "",
        sha256: str = "",
        width: int | None = None,
        height: int | None = None,
    ) -> str | None:
        """Record one re-hosted asset. Returns None when the bytes are already stored.

        Content-addressed: `brand_assets_kit_sha_idx` makes the same bytes one row, so
        a logo that appears on every captured page is fetched once and stored once.
        `on conflict do nothing` rather than an existence check - two workers fetching
        the same asset concurrently would both pass a check and one would then fail.
        """
        # Checked here so the failure names the value and the allowed set. Reaching
        # Postgres with a bad kind raises InvalidTextRepresentation from inside a
        # worker, which says nothing about which vocabulary was wrong.
        if kind not in BRAND_ASSET_KINDS:
            raise ValueError(
                f"{kind!r} is not a brand_asset_kind; expected one of "
                f"{sorted(BRAND_ASSET_KINDS)}"
            )
        with privileged_connection() as cur:
            cur.execute(
                """insert into public.brand_assets
                     (kit_id, kind, source_url, stored_key, sha256, width, height)
                   values (%s, %s, %s, %s, %s, %s, %s)
                   on conflict do nothing
                   returning id""",
                (kit_id, kind, source_url, stored_key, sha256, width, height),
            )
            row = cur.fetchone()
            return str(row["id"]) if row else None

    # --- what the RESEARCH stage reads instead of paying to invent ---------- #
    def metrics_for(self, engagement_id: str | None, keyword: str) -> dict[str, Any] | None:
        """The metrics stage 1 already bought for this term, or None.

        None is a real answer, not a failure. It means nobody bought a number for this
        keyword, and the research stage marks the term `estimated` rather than deriving
        one and presenting it as demand. Volume originates in Google's ad auction;
        there is no offline derivation, so a computed figure here would be a
        fabrication with a provider's name on it.

        Matched case-insensitively on the exact term: a fuzzy match would silently
        attach one keyword's bought volume to a different keyword.
        """
        if not engagement_id or not keyword.strip():
            return None
        with privileged_connection() as cur:
            cur.execute(
                """select t.volume, t.difficulty, t.cpc, t.competition, t.intent,
                          t.estimated, t.relevance, t.opportunity, t.cluster_key,
                          p.provider, p.provider_run_at
                   from public.keyword_plan_terms t
                   join public.keyword_plans p on p.id = t.plan_id
                   where p.engagement_id = %s and lower(t.keyword) = lower(%s)
                   order by t.estimated asc, p.provider_run_at desc nulls last
                   limit 1""",
                (engagement_id, keyword.strip()),
            )
            row = cur.fetchone()
        if row is None:
            return None
        # A row that is ITSELF estimated is not a bought number. Returning it would
        # launder an estimate into "read from the keyword plan" in the stage notes.
        if row.get("estimated"):
            return None
        return dict(row)

# --------------------------------------------------------------------------- #
# The RLS-scoped half: what an HTTP caller may see
# --------------------------------------------------------------------------- #
class ContentPlanningRepo:
    """Read/write bound to ONE verified user, through ``rls_connection``.

    Deliberately NOT `ContentPlanningStore`. That store runs on `privileged_connection`
    (service_role, BYPASSRLS) because the pipeline is a Celery worker with no user JWT -
    a real and necessary privilege, and exactly the wrong thing to hand an HTTP route.
    Reusing it here would mean every request read every client's engagements while the
    policies on these tables sat there looking correct.

    So the router gets its own door. Same tables, same SQL rules - every value bound,
    every identifier a static literal - and the database decides what this caller can
    see rather than the route remembering to filter.
    """

    def __init__(self, user_id: str) -> None:
        self._user_id = user_id

    def list_engagements(self, *, status: str | None = None, limit: int = 100) -> list[_Row]:
        with rls_connection(self._user_id) as cur:
            if status:
                cur.execute(
                    "select * from public.content_engagements where status = %s "
                    "order by created_at desc limit %s",
                    (status, limit),
                )
            else:
                cur.execute(
                    "select * from public.content_engagements "
                    "order by created_at desc limit %s",
                    (limit,),
                )
            return list(cur.fetchall())

    def get_engagement(self, engagement_id: str) -> _Row | None:
        with rls_connection(self._user_id) as cur:
            cur.execute(
                "select * from public.content_engagements where id = %s limit 1",
                (engagement_id,),
            )
            return cur.fetchone()

    def map_nodes(self, engagement_id: str) -> list[_Row]:
        """Nodes for an engagement's newest map.

        The engagement id is bound and the join runs under RLS, so a caller who cannot
        see the engagement cannot see its nodes either - the filter is the database's,
        not this method's.
        """
        with rls_connection(self._user_id) as cur:
            cur.execute(
                """select n.* from public.topical_map_nodes n
                   join public.topical_maps m on m.id = n.map_id
                   where m.engagement_id = %s
                   order by n.priority desc, n.primary_keyword""",
                (engagement_id,),
            )
            return list(cur.fetchall())

    def keyword_terms(self, engagement_id: str, *, limit: int = 2000) -> list[_Row]:
        with rls_connection(self._user_id) as cur:
            cur.execute(
                """select t.* from public.keyword_plan_terms t
                   join public.keyword_plans p on p.id = t.plan_id
                   where p.engagement_id = %s
                   order by t.opportunity desc nulls last limit %s""",
                (engagement_id, limit),
            )
            return list(cur.fetchall())

    def has_brand_kit(self, client_id: str | None) -> bool:
        if not client_id:
            return False
        with rls_connection(self._user_id) as cur:
            cur.execute(
                "select 1 from public.brand_kits "
                "where client_id = %s and active limit 1",
                (client_id,),
            )
            return cur.fetchone() is not None


def get_content_planning_repo(user: CurrentUserDep) -> ContentPlanningRepo:
    """Dependency: a repo bound to the caller's verified user id (RLS-scoped)."""
    return ContentPlanningRepo(user.id)


ContentPlanningRepoDep = Annotated[ContentPlanningRepo, Depends(get_content_planning_repo)]
