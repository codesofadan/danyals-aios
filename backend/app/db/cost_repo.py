"""Cost-control data access via the RLS-scoped ``rls_connection`` seam (for endpoints).

The gate itself uses a separate service_role store (``cost_store.py``); this repo
backs the admin-facing read/write endpoints (budgets, dial, log, spend-stop).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import Depends
from psycopg import sql

from app.core.auth import CurrentUserDep
from app.db.database import rls_connection

_Rows = list[dict[str, Any]]


class CostRepo:
    def __init__(self, user_id: str) -> None:
        self._user_id = user_id

    # --- budgets (joined to their client for cn/tier/color) -------------------
    def _client_map(self) -> dict[str, dict[str, Any]]:
        with rls_connection(self._user_id) as cur:
            cur.execute("select id, name, tier, contact_color from public.clients")
            rows = cur.fetchall()
        return {str(c["id"]): c for c in rows}

    def _merge_budget(self, budget: dict[str, Any], clients: dict[str, dict[str, Any]]) -> dict[str, Any]:
        cid = str(budget["client_id"])
        client = clients.get(cid, {})
        return {
            "id": cid,
            "cn": client.get("name", ""),
            "tier": client.get("tier", "Starter"),
            "cap": int(budget.get("cap", 0)),
            "spent": int(budget.get("spent", 0)),
            "c": client.get("contact_color", "#7B69EE"),
        }

    def list_budgets(self, *, limit: int | None = None, offset: int = 0) -> _Rows:
        clients = self._client_map()
        # client_budgets has no created_at; client_id is its stable per-row key.
        query = "select * from public.client_budgets order by client_id"
        params: list[Any] = []
        if limit is not None:
            query += " limit %s offset %s"
            params += [limit, offset]
        with rls_connection(self._user_id) as cur:
            cur.execute(query, params)
            budgets = cur.fetchall()
        return [self._merge_budget(b, clients) for b in budgets]

    def upsert_budget(self, client_id: str, cap: int) -> dict[str, Any] | None:
        clients = self._client_map()
        if client_id not in clients:
            return None
        with rls_connection(self._user_id) as cur:
            cur.execute(
                "insert into public.client_budgets (client_id, cap) values (%s, %s) "
                "on conflict (client_id) do update set cap = excluded.cap",
                (client_id, cap),
            )
            cur.execute(
                "select * from public.client_budgets where client_id = %s limit 1", (client_id,)
            )
            row = cur.fetchone()
        return self._merge_budget(row, clients) if row else None

    # --- dial -----------------------------------------------------------------
    def dial_modes(self) -> dict[str, str]:
        with rls_connection(self._user_id) as cur:
            cur.execute("select feature_key, mode from public.cost_dial")
            rows = cur.fetchall()
        return {r["feature_key"]: r["mode"] for r in rows}

    def set_dial(self, feature_key: str, mode: str) -> None:
        with rls_connection(self._user_id) as cur:
            cur.execute(
                "insert into public.cost_dial (feature_key, mode) values (%s, %s) "
                "on conflict (feature_key) do update set mode = excluded.mode",
                (feature_key, mode),
            )

    # --- cost log -------------------------------------------------------------
    def list_cost_log(self, limit: int | None = 50, offset: int = 0) -> _Rows:
        query = "select * from public.cost_log order by created_at desc"
        params: list[Any] = []
        if limit is not None:
            query += " limit %s offset %s"
            params += [limit, offset]
        with rls_connection(self._user_id) as cur:
            cur.execute(query, params)
            return cur.fetchall()

    def today_spent(self) -> float:
        start = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
        with rls_connection(self._user_id) as cur:
            cur.execute("select cost from public.cost_log where created_at >= %s", (start,))
            rows = cur.fetchall()
        return float(sum(float(r.get("cost", 0) or 0) for r in rows))

    # --- spend-stop settings --------------------------------------------------
    def get_settings(self) -> dict[str, Any]:
        with rls_connection(self._user_id) as cur:
            cur.execute("select * from public.cost_settings limit 1")
            row = cur.fetchone()
        return row if row else {"daily_stop": 75, "halted": False}

    def update_settings(self, changes: dict[str, Any]) -> dict[str, Any]:
        if changes:
            assignments = sql.SQL(", ").join(
                sql.SQL("{} = %s").format(sql.Identifier(c)) for c in changes
            )
            stmt = sql.SQL("update public.cost_settings set {sets} where id = %s").format(
                sets=assignments
            )
            with rls_connection(self._user_id) as cur:
                cur.execute(stmt, [*changes.values(), True])
        return self.get_settings()


def get_cost_repo(user: CurrentUserDep) -> CostRepo:
    """Depends on ``get_current_user`` (via ``user``) so auth resolves first; the
    repo carries ``user.id`` and opens ``rls_connection`` per method.
    """
    return CostRepo(user.id)


CostRepoDep = Annotated[CostRepo, Depends(get_cost_repo)]
