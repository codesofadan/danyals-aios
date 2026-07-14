"""Cost-control data access via the RLS-scoped user-JWT client (for endpoints).

The gate itself uses a separate service_role store (``cost_store.py``); this repo
backs the admin-facing read/write endpoints (budgets, dial, log, spend-stop).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Any, cast

from fastapi import Depends, Request

from app.core.auth import CurrentUserDep
from app.db.supabase import client_for_user

_Rows = list[dict[str, Any]]


class CostRepo:
    def __init__(self, access_token: str) -> None:
        self._token = access_token

    def _client(self) -> Any:
        return client_for_user(self._token)

    # --- budgets (joined to their client for cn/tier/color) -------------------
    def _client_map(self) -> dict[str, dict[str, Any]]:
        resp = self._client().table("clients").select("id,name,tier,contact_color").execute()
        return {str(c["id"]): c for c in cast("_Rows", resp.data or [])}

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

    def list_budgets(self) -> _Rows:
        clients = self._client_map()
        resp = self._client().table("client_budgets").select("*").execute()
        return [self._merge_budget(b, clients) for b in cast("_Rows", resp.data or [])]

    def upsert_budget(self, client_id: str, cap: int) -> dict[str, Any] | None:
        clients = self._client_map()
        if client_id not in clients:
            return None
        self._client().table("client_budgets").upsert(
            {"client_id": client_id, "cap": cap}, on_conflict="client_id"
        ).execute()
        resp = (
            self._client().table("client_budgets").select("*").eq("client_id", client_id).limit(1).execute()
        )
        rows = cast("_Rows", resp.data or [])
        return self._merge_budget(rows[0], clients) if rows else None

    # --- dial -----------------------------------------------------------------
    def dial_modes(self) -> dict[str, str]:
        resp = self._client().table("cost_dial").select("feature_key, mode").execute()
        return {r["feature_key"]: r["mode"] for r in cast("_Rows", resp.data or [])}

    def set_dial(self, feature_key: str, mode: str) -> None:
        self._client().table("cost_dial").upsert(
            {"feature_key": feature_key, "mode": mode}, on_conflict="feature_key"
        ).execute()

    # --- cost log -------------------------------------------------------------
    def list_cost_log(self, limit: int = 50) -> _Rows:
        resp = (
            self._client().table("cost_log").select("*").order("created_at", desc=True).limit(limit).execute()
        )
        return cast("_Rows", resp.data or [])

    def today_spent(self) -> float:
        start = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
        resp = self._client().table("cost_log").select("cost").gte("created_at", start.isoformat()).execute()
        return float(sum(float(r.get("cost", 0) or 0) for r in cast("_Rows", resp.data or [])))

    # --- spend-stop settings --------------------------------------------------
    def get_settings(self) -> dict[str, Any]:
        resp = self._client().table("cost_settings").select("*").limit(1).execute()
        rows = cast("_Rows", resp.data or [])
        return rows[0] if rows else {"daily_stop": 75, "halted": False}

    def update_settings(self, changes: dict[str, Any]) -> dict[str, Any]:
        if changes:
            self._client().table("cost_settings").update(changes).eq("id", True).execute()
        return self.get_settings()


def get_cost_repo(request: Request, _user: CurrentUserDep) -> CostRepo:
    """Depends on ``get_current_user`` (via ``_user``) so auth resolves first and
    populates ``request.state.access_token`` before this factory reads it -
    independent of the sibling-dependency order in a route's signature.
    """
    token: str = getattr(request.state, "access_token", "")
    return CostRepo(token)


CostRepoDep = Annotated[CostRepo, Depends(get_cost_repo)]
