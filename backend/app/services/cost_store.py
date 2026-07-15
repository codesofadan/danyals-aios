"""Concrete ``CostStore`` for the gate, backed by the privileged psycopg
connection (role ``service_role``, BYPASSRLS).

Workers have no user JWT, so the gate reads/writes cost state on the privileged
connection -- the old service_role admin path. The gate's decision logic is
unit-tested against an in-memory fake (``app/services/cost_gate.py``); this
store's hand-SQL is exercised in the integration suite.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import cast

from app.db.database import privileged_connection
from app.schemas.cost import DIAL_FEATURES
from app.services.cost_gate import DialMode, GateContext

_DEFAULT_MODE: dict[str, DialMode] = {f.key: f.default_mode for f in DIAL_FEATURES}


class SupabaseCostStore:
    """``CostStore`` over ``privileged_connection`` (service_role, BYPASSRLS).

    Stateless: each method opens its own privileged connection, so the store
    needs no construction arguments and is safe to instantiate per call.
    """

    def dial_mode(self, feature_key: str) -> DialMode:
        with privileged_connection() as cur:
            cur.execute(
                "select mode from public.cost_dial where feature_key = %s limit 1",
                (feature_key,),
            )
            row = cur.fetchone()
        if row is not None:
            return cast("DialMode", row["mode"])
        return _DEFAULT_MODE.get(feature_key, "off")

    def client_budget(self, client_id: str) -> tuple[float, float] | None:
        with privileged_connection() as cur:
            cur.execute(
                "select cap, spent from public.client_budgets where client_id = %s limit 1",
                (client_id,),
            )
            row = cur.fetchone()
        if row is None:
            return None
        return float(row["cap"]), float(row["spent"])

    def daily_spent(self) -> float:
        start = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
        with privileged_connection() as cur:
            cur.execute("select cost from public.cost_log where created_at >= %s", (start,))
            rows = cur.fetchall()
        return float(sum(float(r.get("cost", 0) or 0) for r in rows))

    def daily_stop(self) -> float:
        with privileged_connection() as cur:
            cur.execute("select daily_stop from public.cost_settings limit 1")
            row = cur.fetchone()
        return float(row["daily_stop"]) if row else 75.0

    def is_halted(self) -> bool:
        with privileged_connection() as cur:
            cur.execute("select halted from public.cost_settings limit 1")
            row = cur.fetchone()
        return bool(row["halted"]) if row else False

    def record_cost(self, ctx: GateContext, cost: float, *, cached: bool) -> None:
        # The append + the atomic budget increment run in ONE privileged
        # transaction so the cost_log row and the client's month-to-date spend
        # stay consistent (an improvement over the two separate PostgREST calls).
        with privileged_connection() as cur:
            cur.execute(
                "insert into public.cost_log "
                "(client_id, client_name, job_id, job_type, provider, cost, cached) "
                "values (%(client_id)s, %(client_name)s, %(job_id)s, %(job_type)s, "
                "%(provider)s, %(cost)s, %(cached)s)",
                {
                    "client_id": ctx.client_id,
                    "client_name": ctx.client_name,
                    "job_id": ctx.job_id,
                    "job_type": ctx.job_type,
                    "provider": ctx.provider,
                    "cost": cost,
                    "cached": cached,
                },
            )
            if not cached and cost > 0 and ctx.client_id:
                # Atomic increment via the SECURITY DEFINER helper (granted to
                # service_role) -- avoids a read-modify-write race, exactly as the
                # old ``.rpc('add_budget_spend', ...)`` call did. The casts pin the
                # overload: client_id binds as text and ``cost`` as double
                # precision, neither of which resolves to (uuid, numeric) implicitly.
                cur.execute(
                    "select public.add_budget_spend(%s::uuid, %s::numeric)",
                    (ctx.client_id, cost),
                )
