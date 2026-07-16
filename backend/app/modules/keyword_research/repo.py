"""Data access for the keyword bank (``keywords`` / ``keyword_clusters`` /
``keyword_lists``) via the RLS-scoped ``rls_connection`` seam + the privileged
``ServiceKeywordStore`` the research worker ingests through.

Every read + mutation on ``KeywordRepo`` is tenant/actor-scoped by Postgres RLS:
staff read the whole bank (including un-assigned NULL-client rows), clients are
excluded (no base-table select policy), and only leads (owner/admin/manager) may
write (the RLS insert/update policies + the ``run_research`` app gate). Methods are
synchronous (psycopg is sync) - the router offloads them with ``asyncio.to_thread``.

SQL rules (impersonation-review mandate): every VALUE is a bound param (``%s``),
never string-formatted; table/column names are static literals and the only dynamic
column lists come from server-built dicts quoted via ``psycopg.sql.Identifier``.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import Depends
from psycopg import sql

from app.core.auth import CurrentUserDep
from app.db.database import privileged_connection, rls_connection

_Rows = list[dict[str, Any]]

# The keyword read projection: the base row + the joined cluster name (so the
# response can show the cluster without a second round-trip). A static column set.
_KEYWORD_SELECT = (
    "select k.*, c.name as cluster_name from public.keywords k "
    "left join public.keyword_clusters c on c.id = k.cluster_id"
)


class KeywordRepo:
    """Thin RLS-scoped repository over the keyword bank + its clusters + lists."""

    def __init__(self, user_id: str) -> None:
        self._user_id = user_id

    # --- keywords -------------------------------------------------------------
    def list_keywords(
        self,
        *,
        client_id: str | None = None,
        cluster_id: str | None = None,
        intent: str | None = None,
        winnable: bool | None = None,
        geo: str | None = None,
        source: str | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> _Rows:
        query = _KEYWORD_SELECT
        clauses: list[str] = []
        params: list[Any] = []
        if client_id is not None:
            clauses.append("k.client_id = %s")
            params.append(client_id)
        if cluster_id is not None:
            clauses.append("k.cluster_id = %s")
            params.append(cluster_id)
        if intent is not None:
            clauses.append("k.intent = %s")
            params.append(intent)
        if winnable is not None:
            clauses.append("k.winnable = %s")
            params.append(winnable)
        if geo is not None:
            clauses.append("k.geo = %s")
            params.append(geo)
        if source is not None:
            clauses.append("k.source = %s")
            params.append(source)
        if clauses:
            query += " where " + " and ".join(clauses)
        # Best opportunities first; volume + code keep the order stable across ties.
        query += " order by k.opportunity desc, k.volume desc, k.code"
        if limit is not None:
            query += " limit %s offset %s"
            params += [limit, offset]
        with rls_connection(self._user_id) as cur:
            cur.execute(query, params)
            return cur.fetchall()

    def keyword_stats(self) -> dict[str, Any]:
        """Bank summary: saved count, distinct clusters used, average difficulty.
        RLS-scoped; an empty bank yields zeros."""
        with rls_connection(self._user_id) as cur:
            cur.execute(
                "select "
                "count(*) as saved, "
                "count(distinct cluster_id) filter (where cluster_id is not null) as clusters, "
                "coalesce(avg(difficulty), 0) as avg_difficulty "
                "from public.keywords"
            )
            row = cur.fetchone()
            return row or {"saved": 0, "clusters": 0, "avg_difficulty": 0}

    def get_by_code(self, code: str) -> dict[str, Any] | None:
        with rls_connection(self._user_id) as cur:
            cur.execute(_KEYWORD_SELECT + " where k.code = %s limit 1", (code,))
            return cur.fetchone()

    def add_keywords(
        self,
        *,
        client_id: str | None,
        client_name: str,
        geo: str | None,
        keywords: list[str],
        created_by: str,
    ) -> _Rows:
        """Bulk-insert manual keywords (source ``manual``). A duplicate (client,
        keyword, geo) is skipped (``on conflict do nothing``). Returns the inserted
        rows (joined cluster name is NULL for a fresh row). Empty input is a no-op."""
        clean = [k.strip() for k in keywords if k and k.strip()]
        if not clean:
            return []
        values = sql.SQL(", ").join(
            sql.SQL("(%s, %s, %s, %s, 'manual', %s)") for _ in clean
        )
        params: list[Any] = []
        for kw in clean:
            params += [client_id, client_name, geo, kw, created_by]
        stmt = sql.SQL(
            "insert into public.keywords "
            "(client_id, client_name, geo, keyword, source, created_by) "
            "values {values} on conflict (client_id, keyword, geo) do nothing "
            "returning *"
        ).format(values=values)
        with rls_connection(self._user_id) as cur:
            cur.execute(stmt, params)
            return cur.fetchall()

    def update_keyword(self, code: str, changes: dict[str, Any]) -> dict[str, Any] | None:
        """Update one keyword by code, returning the JOINED row (or ``None`` if the
        code is unknown/invisible). Column names are static ``sql.Identifier``s;
        values are always bound - the impersonation-review SQL rule."""
        if not changes:
            return self.get_by_code(code)
        assignments = sql.SQL(", ").join(
            sql.SQL("{} = %s").format(sql.Identifier(col)) for col in changes
        )
        stmt = sql.SQL(
            "update public.keywords set {sets} where code = %s returning id"
        ).format(sets=assignments)
        with rls_connection(self._user_id) as cur:
            cur.execute(stmt, [*changes.values(), code])
            if cur.fetchone() is None:
                return None
        # Re-read through the join so the response carries the cluster name.
        return self.get_by_code(code)

    def client_name_for(self, client_id: str) -> str | None:
        """The display name of a client the caller can see (RLS-scoped), or ``None``
        - used to SNAPSHOT client_name so the internal client_id never surfaces."""
        with rls_connection(self._user_id) as cur:
            cur.execute("select name from public.clients where id = %s limit 1", (client_id,))
            row = cur.fetchone()
            return str(row["name"]) if row else None

    # --- clusters -------------------------------------------------------------
    def list_clusters(
        self, *, client_id: str | None = None, limit: int | None = None, offset: int = 0
    ) -> _Rows:
        query = "select * from public.keyword_clusters"
        clauses: list[str] = []
        params: list[Any] = []
        if client_id is not None:
            clauses.append("client_id = %s")
            params.append(client_id)
        if clauses:
            query += " where " + " and ".join(clauses)
        query += " order by total_volume desc, name"
        if limit is not None:
            query += " limit %s offset %s"
            params += [limit, offset]
        with rls_connection(self._user_id) as cur:
            cur.execute(query, params)
            return cur.fetchall()

    # --- cannibalization ------------------------------------------------------
    def cannibalization_rows(self, *, client_id: str | None = None) -> _Rows:
        """Keywords that have an intended landing URL + a classified intent - the raw
        material the service folds into per-URL conflicts (a URL claimed by more than
        one intent). RLS-scoped."""
        query = (
            "select keyword, intent, target_url from public.keywords "
            "where target_url <> '' and intent is not null"
        )
        params: list[Any] = []
        if client_id is not None:
            query += " and client_id = %s"
            params.append(client_id)
        with rls_connection(self._user_id) as cur:
            cur.execute(query, params)
            return cur.fetchall()


def get_keyword_repo(user: CurrentUserDep) -> KeywordRepo:
    """Dependency: a repo bound to the caller's verified user id (RLS-scoped)."""
    return KeywordRepo(user.id)


KeywordRepoDep = Annotated[KeywordRepo, Depends(get_keyword_repo)]


# --------------------------------------------------------------------------- #
# Privileged (service_role, BYPASSRLS) store for the RESEARCH worker.
# --------------------------------------------------------------------------- #
# The research worker has no user JWT, so - exactly like the audit / context / offpage
# workers - it reads/writes the keyword bank on the privileged connection
# (service_role bypasses the RLS policies by design). Each method opens its own
# privileged connection, so the store is stateless and safe to instantiate per call.
class ServiceKeywordStore:
    """Concrete keyword store over ``privileged_connection`` (BYPASSRLS)."""

    def get_client_name(self, client_id: str) -> str | None:
        with privileged_connection() as cur:
            cur.execute("select name from public.clients where id = %s limit 1", (client_id,))
            row = cur.fetchone()
            return str(row["name"]) if row else None

    def upsert_cluster(
        self,
        *,
        client_id: str | None,
        client_name: str,
        name: str,
        pillar_keyword: str,
        dominant_intent: str | None,
        size: int,
        total_volume: int,
        avg_difficulty: float,
    ) -> str:
        """Idempotently upsert a cluster keyed by (client_id, name) - NULL-safe via
        ``is not distinct from`` - and return its id. A re-run of the same seed
        refreshes the aggregates in place instead of duplicating the cluster."""
        with privileged_connection() as cur:
            cur.execute(
                "select id from public.keyword_clusters "
                "where name = %s and client_id is not distinct from %s limit 1",
                (name, client_id),
            )
            existing = cur.fetchone()
            if existing is not None:
                cur.execute(
                    "update public.keyword_clusters set "
                    "client_name = %s, pillar_keyword = %s, dominant_intent = %s, "
                    "size = %s, total_volume = %s, avg_difficulty = %s "
                    "where id = %s",
                    (
                        client_name, pillar_keyword, dominant_intent, size,
                        total_volume, avg_difficulty, existing["id"],
                    ),
                )
                return str(existing["id"])
            cur.execute(
                "insert into public.keyword_clusters "
                "(client_id, client_name, name, pillar_keyword, dominant_intent, "
                "size, total_volume, avg_difficulty) "
                "values (%s, %s, %s, %s, %s, %s, %s, %s) returning id",
                (
                    client_id, client_name, name, pillar_keyword, dominant_intent,
                    size, total_volume, avg_difficulty,
                ),
            )
            row = cur.fetchone()
            return str(row["id"]) if row else ""

    def upsert_keyword(
        self,
        *,
        client_id: str | None,
        client_name: str,
        keyword: str,
        geo: str | None,
        volume: int,
        difficulty: float,
        cpc: float,
        competition: float,
        intent: str | None,
        intent_source: str | None,
        intent_confidence: float,
        cluster_id: str | None,
        opportunity: float,
        winnable: bool | None,
        source: str,
        metrics_confidence: str,
        provider: str,
        fetched_at: Any,
    ) -> bool:
        """Idempotently upsert one researched keyword keyed by (client_id, keyword,
        geo) - NULL-safe via ``is not distinct from`` so a re-run refreshes the metrics
        in place rather than duplicating a bank row. Returns ``True`` when a NEW row was
        inserted (so the worker can count fresh saves)."""
        with privileged_connection() as cur:
            cur.execute(
                "select id from public.keywords "
                "where keyword = %s and client_id is not distinct from %s "
                "and geo is not distinct from %s limit 1",
                (keyword, client_id, geo),
            )
            existing = cur.fetchone()
            if existing is not None:
                cur.execute(
                    "update public.keywords set "
                    "client_name = %s, volume = %s, difficulty = %s, cpc = %s, "
                    "competition = %s, intent = %s, intent_source = %s, "
                    "intent_confidence = %s, cluster_id = %s, opportunity = %s, "
                    "winnable = %s, metrics_confidence = %s, provider = %s, "
                    "fetched_at = %s where id = %s",
                    (
                        client_name, volume, difficulty, cpc, competition, intent,
                        intent_source, intent_confidence, cluster_id, opportunity,
                        winnable, metrics_confidence, provider, fetched_at,
                        existing["id"],
                    ),
                )
                return False
            cur.execute(
                "insert into public.keywords "
                "(client_id, client_name, keyword, geo, volume, difficulty, cpc, "
                "competition, intent, intent_source, intent_confidence, cluster_id, "
                "opportunity, winnable, source, metrics_confidence, provider, fetched_at) "
                "values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (
                    client_id, client_name, keyword, geo, volume, difficulty, cpc,
                    competition, intent, intent_source, intent_confidence, cluster_id,
                    opportunity, winnable, source, metrics_confidence, provider, fetched_at,
                ),
            )
            return True


def service_keyword_store() -> ServiceKeywordStore:
    """The privileged keyword store the research worker uses (service_role, BYPASSRLS)."""
    return ServiceKeywordStore()
