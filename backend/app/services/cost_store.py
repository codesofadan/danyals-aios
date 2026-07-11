"""Concrete ``CostStore`` for the gate, backed by the service_role admin client.

Workers have no user JWT, so the gate reads/writes cost state with service_role.
Exercised in the integration suite (needs a real Supabase); the gate's logic is
unit-tested against an in-memory fake instead.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, cast

from supabase import Client

from app.schemas.cost import DIAL_FEATURES
from app.services.cost_gate import DialMode, GateContext

_DEFAULT_MODE: dict[str, DialMode] = {f.key: f.default_mode for f in DIAL_FEATURES}


class SupabaseCostStore:
    def __init__(self, admin: Client) -> None:
        self._admin = admin

    def dial_mode(self, feature_key: str) -> DialMode:
        resp = self._admin.table("cost_dial").select("mode").eq("feature_key", feature_key).limit(1).execute()
        rows = cast("list[dict[str, Any]]", resp.data or [])
        if rows:
            return cast(DialMode, rows[0]["mode"])
        return _DEFAULT_MODE.get(feature_key, "off")

    def client_budget(self, client_id: str) -> tuple[float, float] | None:
        resp = (
            self._admin.table("client_budgets").select("cap, spent").eq("client_id", client_id).limit(1).execute()
        )
        rows = cast("list[dict[str, Any]]", resp.data or [])
        if not rows:
            return None
        return float(rows[0]["cap"]), float(rows[0]["spent"])

    def daily_spent(self) -> float:
        start = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
        resp = self._admin.table("cost_log").select("cost").gte("created_at", start.isoformat()).execute()
        return float(sum(float(r.get("cost", 0) or 0) for r in cast("list[dict[str, Any]]", resp.data or [])))

    def daily_stop(self) -> float:
        resp = self._admin.table("cost_settings").select("daily_stop").limit(1).execute()
        rows = cast("list[dict[str, Any]]", resp.data or [])
        return float(rows[0]["daily_stop"]) if rows else 75.0

    def is_halted(self) -> bool:
        resp = self._admin.table("cost_settings").select("halted").limit(1).execute()
        rows = cast("list[dict[str, Any]]", resp.data or [])
        return bool(rows[0]["halted"]) if rows else False

    def record_cost(self, ctx: GateContext, cost: float, *, cached: bool) -> None:
        self._admin.table("cost_log").insert(
            {
                "client_id": ctx.client_id,
                "client_name": ctx.client_name,
                "job_id": ctx.job_id,
                "job_type": ctx.job_type,
                "provider": ctx.provider,
                "cost": cost,
                "cached": cached,
            }
        ).execute()
        if not cached and cost > 0 and ctx.client_id:
            self._admin.rpc("add_budget_spend", {"p_client": ctx.client_id, "p_amount": cost}).execute()
