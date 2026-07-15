"""Integration: the full shared-base flow against a real Supabase project.

SUPERSEDED by the Part 6 psycopg migration and skipped (see the test body): the
cost + activity writes it asserts on now target the LOCAL Postgres data plane
(``privileged_connection``, P6A-5) while this whole-stack flow still provisions
and authenticates against Supabase cloud -- the two no longer share a database,
so the over-cap / activity-feed assertions can no longer hold. It is reworked or
removed with provisioning (P6A-7) and the ``supabase.py`` deletion (P6A-8).
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest
from supabase import create_client

from app.config import get_settings
from app.db.supabase import client_for_user, get_admin_client
from app.services.activity import log_activity
from app.services.cost_gate import CostGate, GateContext
from app.services.cost_store import SupabaseCostStore
from app.services.provisioning import provision_user


class _NoCache:
    def get(self, key: str) -> Any | None:
        return None

    def set(self, key: str, value: Any) -> None:
        return None


def _require_supabase() -> Any:
    settings = get_settings()
    if not (settings.supabase_url and settings.supabase_service_role_key and settings.supabase_anon_key):
        pytest.skip("Supabase not configured (SUPABASE_URL + keys)")
    return settings


@pytest.mark.integration
def test_shared_base_end_to_end() -> None:
    pytest.skip(
        "Superseded by P6A-5: cost + activity writes moved to the local Postgres "
        "data plane (privileged_connection), while this flow still provisions and "
        "authenticates against Supabase cloud -- the two data planes no longer share "
        "a database. Reworked/removed with provisioning (P6A-7) + supabase.py (P6A-8)."
    )
    settings = _require_supabase()
    admin = get_admin_client()
    anon = create_client(settings.supabase_url, settings.supabase_anon_key.get_secret_value())

    email = f"e2e-{uuid4().hex}@example.com"
    password = "Passw0rd!e2e-123"
    user_row = provision_user(
        admin, email=email, password=password, name="E2E Admin", role="owner", template_key="super"
    )
    user_id = user_row["id"]
    client_id: str | None = None
    stranger_id: str | None = None
    try:
        # login -> JWT -> RLS-scoped client
        session = anon.auth.sign_in_with_password({"email": email, "password": password})
        token = session.session.access_token
        me = client_for_user(token)

        # the provisioned user reads their own row (RLS: self or staff)
        rows = me.table("users").select("*").eq("id", user_id).execute().data
        assert rows and rows[0]["email"] == email

        # owner creates a client (manage_clients) through RLS
        created = me.table("clients").insert({"name": "E2E Client", "tier": "Starter"}).execute().data
        client_id = created[0]["id"]

        # budget cap of 10 with 9 already spent -> a $5 call is over-cap
        admin.table("client_budgets").upsert(
            {"client_id": client_id, "cap": 10, "spent": 9}, on_conflict="client_id"
        ).execute()
        admin.table("cost_dial").upsert({"feature_key": "tech_audit", "mode": "api"}, on_conflict="feature_key").execute()

        gate = CostGate(SupabaseCostStore(), _NoCache())
        decision = gate.evaluate(
            GateContext(feature_key="tech_audit", client_id=client_id, provider="DataForSEO", estimated_cost=5.0)
        )
        assert decision.outcome == "blocked_cap"

        # activity is written server-side and visible to staff via RLS
        log_activity(
            actor_id=user_id, actor_name="E2E Admin", actor_color="#000",
            kind="client", action="created client", target="E2E Client",
        )
        feed = me.table("activity_log").select("*").limit(5).execute().data
        assert any(a["action"] == "created client" for a in feed)

        # a valid token for a NON-provisioned auth user sees no tenant rows (RLS)
        stranger_email = f"stranger-{uuid4().hex}@example.com"
        stranger = admin.auth.admin.create_user(
            {"email": stranger_email, "password": password, "email_confirm": True}
        )
        stranger_id = str(getattr(stranger, "user", stranger).id)
        s_session = anon.auth.sign_in_with_password({"email": stranger_email, "password": password})
        stranger_client = client_for_user(s_session.session.access_token)
        assert stranger_client.table("clients").select("*").execute().data == []
    finally:
        if client_id:
            admin.table("clients").delete().eq("id", client_id).execute()
        admin.auth.admin.delete_user(user_id)
        if stranger_id:
            admin.auth.admin.delete_user(stranger_id)
