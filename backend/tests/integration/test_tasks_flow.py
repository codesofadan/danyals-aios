"""Integration: prove the Part-5 task lifecycle + the DB-enforced review gate
against a real Supabase project (RLS + the tasks_guard_update trigger are the
boundary, not FastAPI).

Skips unless SUPABASE_URL + service_role + anon keys are set AND migration 0011
is applied. Provisions a lead (manager), a non-lead assignee (specialist), and a
portal client, then asserts - via each principal's OWN JWT hitting PostgREST
DIRECTLY:

  (A) THE BLOCKER PROOF: a non-lead PATCHing status -> done directly is REJECTED
      by the trigger (both the skip-review jump on a content_sprint and the
      review -> done self-sign-off), the row is unchanged, and a non-status
      column edit is likewise REJECTED - while a lead CAN sign off review -> done;
  (B) a non-lead may make only the LEGAL moves (todo->in_progress,
      in_progress->review for content_sprint, in_progress->done otherwise);
  (C) a lead may reject review -> in_progress;
  (D) an assignee must be staff (reassigning to a client uid is REJECTED);
  (E) my-queue scoping works and a portal client is fully excluded (0 rows on
      read; insert/update blocked).

Everything created is cleaned up in a finally block.
"""

from __future__ import annotations

import contextlib
from typing import Any
from uuid import uuid4

import pytest
from postgrest.exceptions import APIError
from supabase import create_client

from app.config import get_settings
from app.db.supabase import client_for_user, get_admin_client
from app.services.provisioning import provision_user

_PASSWORD = "Passw0rd!tasks-flow-123"


def _require_supabase() -> Any:
    settings = get_settings()
    if not (
        settings.supabase_url
        and settings.supabase_service_role_key
        and settings.supabase_anon_key
    ):
        pytest.skip("Supabase not configured (SUPABASE_URL + keys)")
    return settings


@pytest.mark.integration
async def test_task_lifecycle_and_db_review_gate() -> None:
    settings = _require_supabase()
    admin = get_admin_client()
    anon = create_client(settings.supabase_url, settings.supabase_anon_key.get_secret_value())

    codes: list[str] = []
    client_id: str | None = None
    uids: list[str] = []

    def _seed(**over: Any) -> str:
        row = {
            "client_id": client_id, "client_name": "Flow Co", "title": "Flow task",
            "type": "content_sprint", "assignee_id": None, "status": "todo", "priority": "med",
        }
        row.update(over)
        code = admin.table("tasks").insert(row).execute().data[0]["code"]
        codes.append(code)
        return str(code)

    def _row(code: str) -> dict[str, Any]:
        return admin.table("tasks").select("*").eq("code", code).execute().data[0]

    try:
        client_id = admin.table("clients").insert(
            {"name": "Flow Co", "delivery_tier": "free"}
        ).execute().data[0]["id"]

        email_lead = f"flow-lead-{uuid4().hex}@example.com"
        email_spec = f"flow-spec-{uuid4().hex}@example.com"
        email_cli = f"flow-cli-{uuid4().hex}@example.com"
        lead_uid = provision_user(
            admin, email=email_lead, password=_PASSWORD, name="Flow Lead", role="manager"
        )["id"]
        spec_uid = provision_user(
            admin, email=email_spec, password=_PASSWORD, name="Flow Spec", role="specialist"
        )["id"]
        cli_uid = provision_user(
            admin, email=email_cli, password=_PASSWORD, name="Flow Client",
            role="client", client_id=client_id,
        )["id"]
        uids += [lead_uid, spec_uid, cli_uid]

        lead_tok = anon.auth.sign_in_with_password(
            {"email": email_lead, "password": _PASSWORD}
        ).session.access_token
        spec_tok = anon.auth.sign_in_with_password(
            {"email": email_spec, "password": _PASSWORD}
        ).session.access_token
        cli_tok = anon.auth.sign_in_with_password(
            {"email": email_cli, "password": _PASSWORD}
        ).session.access_token
        lead = client_for_user(lead_tok)
        spec = client_for_user(spec_tok)
        cli = client_for_user(cli_tok)

        # ============================================================= (A) BLOCKER
        # A content_sprint assigned to the specialist, sitting in_progress.
        t1 = _seed(type="content_sprint", status="in_progress", assignee_id=spec_uid)

        # (A1) the specialist tries to SKIP REVIEW by jumping straight to done.
        with pytest.raises(APIError) as skip:
            spec.table("tasks").update({"status": "done"}).eq("code", t1).execute()
        # Trigger raised; the row never moved.
        assert _row(t1)["status"] == "in_progress"

        # (A2) the specialist tries to edit a NON-status column on their own task.
        with pytest.raises(APIError):
            spec.table("tasks").update({"title": "hijacked"}).eq("code", t1).execute()
        assert _row(t1)["title"] != "hijacked"

        # (A2b) ...nor the normally-immutable created_at, even alongside a no-op
        # status (0012 hardened the column-lock to include id + created_at).
        original_created = _row(t1)["created_at"]
        with pytest.raises(APIError):
            spec.table("tasks").update(
                {"status": "in_progress", "created_at": "2000-01-01T00:00:00+00:00"}
            ).eq("code", t1).execute()
        assert _row(t1)["created_at"] == original_created

        # (A3) the LEGAL submit-for-review move (in_progress -> review) is allowed.
        spec.table("tasks").update({"status": "review"}).eq("code", t1).execute()
        assert _row(t1)["status"] == "review"

        # (A4) now in review, the specialist tries to self-sign-off review -> done.
        with pytest.raises(APIError):
            spec.table("tasks").update({"status": "done"}).eq("code", t1).execute()
        assert _row(t1)["status"] == "review"

        # (A5) ...and tries to self-reject review -> in_progress. Also lead-only.
        with pytest.raises(APIError):
            spec.table("tasks").update({"status": "in_progress"}).eq("code", t1).execute()
        assert _row(t1)["status"] == "review"

        # (A6) the LEAD signs off: review -> done succeeds (the gate is lead-only).
        lead.table("tasks").update({"status": "done"}).eq("code", t1).execute()
        assert _row(t1)["status"] == "done"

        # The BLOCKER assertion, quoted for the record:
        assert skip.value is not None  # a direct non-lead status->done PATCH raised

        # ================================================= (B) legal non-lead path
        t2 = _seed(type="technical_audit", status="todo", assignee_id=spec_uid)
        spec.table("tasks").update({"status": "in_progress"}).eq("code", t2).execute()
        assert _row(t2)["status"] == "in_progress"
        # non-content delivers straight to done (no review gate)
        spec.table("tasks").update({"status": "done"}).eq("code", t2).execute()
        assert _row(t2)["status"] == "done"

        # ===================================================== (C) lead may reject
        t3 = _seed(type="content_sprint", status="review", assignee_id=spec_uid)
        lead.table("tasks").update({"status": "in_progress"}).eq("code", t3).execute()
        assert _row(t3)["status"] == "in_progress"

        # ============================================ (D) assignee must be staff
        t4 = _seed(type="local_seo", status="todo", assignee_id=spec_uid)
        with pytest.raises(APIError):
            lead.table("tasks").update({"assignee_id": cli_uid}).eq("code", t4).execute()
        assert _row(t4)["assignee_id"] == spec_uid

        # ================================= (E) my-queue scoping + client exclusion
        # Staff see the board; the specialist can scope to their own queue.
        my_queue = spec.table("tasks").select("code").eq("assignee_id", spec_uid).execute().data
        assert {t1, t2, t3, t4}.issubset({r["code"] for r in my_queue})

        # A portal client is fully excluded: no reads, no insert, no update.
        assert cli.table("tasks").select("*").execute().data == []
        with pytest.raises(APIError):
            cli.table("tasks").insert(
                {"client_id": client_id, "title": "x", "type": "publishing"}
            ).execute()
        # update matches 0 rows under RLS (no error, just nothing changed)
        assert cli.table("tasks").update({"status": "done"}).eq("code", t2).execute().data == []
    finally:
        for code in codes:
            with contextlib.suppress(Exception):
                admin.table("tasks").delete().eq("code", code).execute()
        if client_id:
            with contextlib.suppress(Exception):
                admin.table("clients").delete().eq("id", client_id).execute()
        for uid in uids:
            with contextlib.suppress(Exception):
                admin.auth.admin.delete_user(uid)
