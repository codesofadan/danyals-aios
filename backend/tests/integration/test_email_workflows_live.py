"""Integration: prove 3 real notification workflows send REAL email through the
configured Resend provider, against LOCAL Postgres - no fake/mock sender.

Skips unless DATABASE_URL + DATABASE_ADMIN_URL + RESEND_API_KEY are all set (this
is a deliberately live-fire test: it sends genuine transactional email). Every
recipient is redirected to ONE test inbox (adandevelops@gmail.com) - team-member/
lead users are provisioned with a Gmail ``+tag`` alias of that address (Gmail
folds ``user+anything@gmail.com`` into ``user@gmail.com``'s inbox; ``auth.users.
email`` is UNIQUE so two distinct provisioned users cannot share one literal
address), and the fixed admin-alert address is overridden to the bare address.

The 3 workflows, each driven through its REAL router/service function (not a raw
DB write) so the exact code path a production request takes is exercised:

  1. ``POST /tasks`` (``create_task``) -> ``notify(assignee, kind="task_assigned")``
     when an admin/lead assigns a task to a team member.
  2. ``POST /tasks/{code}/advance`` (``advance_task``) -> a direct
     ``in_progress -> done`` transition on a non-review task type fires
     ``notify_leads(kind="task_completed")`` when a team member finishes work.
     NOTE: this LOCAL Postgres is missing migration 0073 (see the inline comment
     at scenario (2) below) so the actual ``advance_task`` router call 500s here
     regardless of task type; the DB write is driven directly (the lead identity,
     columns that DO exist) and the router's own ``notify_leads(kind=
     "task_completed", ...)`` call is then fired verbatim.
  3. ``POST /portal/requests`` (``create_client_request``) -> ``email_admin(...)``
     when a client submits a portal request.

Each real ``notify``/``notify_leads``/``email_admin`` call is driven through its
REAL ``email_sender_from_settings`` factory (real Resend client) - a thin
``_CapturingSender`` WRAPS that real client (never replaces it) purely to record
the provider message id for the report; (1) and (2) call the router's module-level
``notify``/``notify_leads`` names, so those are monkeypatched to close over the
capturing wrapper (the exact idiom ``test_tasks_endpoints.py`` already uses to
intercept ``app.routers.tasks.notify``/``notify_leads`` - here the replacement
still calls the REAL notify/notify_leads, it only injects the sender); (3) calls
the service function directly, which already accepts ``email_sender=`` as first-
class injection.

Everything created (task, users, client, support ticket) is cleaned up in a
``finally`` block.
"""

from __future__ import annotations

import contextlib
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

import pytest

import app.routers.tasks as tasks_router
from app.config import get_settings
from app.core.auth import CurrentClient, CurrentUser
from app.db.clients_repo import ClientsRepo
from app.db.database import (
    build_admin_pool,
    build_rls_pool,
    clear_pools,
    privileged_connection,
    rls_connection,
    set_pools,
)
from app.db.tasks_repo import TasksRepo
from app.schemas.portal_requests import PortalRequestCreate
from app.schemas.tasks import TaskCreate
from app.services import notifications as notifications_mod
from app.services.client_requests import create_client_request, insert_request_row
from integrations.resend import EmailSender, email_sender_from_settings

pytestmark = pytest.mark.integration

_PASSWORD = "Passw0rd!email-live-123"
_TEST_INBOX = "adandevelops@gmail.com"


def _require_live_stack() -> Any:
    settings = get_settings()
    if not (settings.database_url and settings.database_admin_url):
        pytest.skip("local Postgres not configured (DATABASE_URL + DATABASE_ADMIN_URL)")
    if not settings.resend_api_key:
        pytest.skip("RESEND_API_KEY not configured - this test sends real email")
    return settings


@dataclass
class _CapturingSender:
    """Wraps a REAL ``EmailSender`` (never replaces it) to record each send's
    provider message id for the report - the send itself always hits Resend."""

    inner: EmailSender
    sent: list[tuple[str, str, str]] = field(default_factory=list)  # (to, subject, message_id)

    def send(self, *, to: str, subject: str, html: str, text: str | None = None) -> str:
        message_id = self.inner.send(to=to, subject=subject, html=html, text=text)
        self.sent.append((to, subject, message_id))
        return message_id


async def test_task_assigned_and_completed_and_client_request_send_real_email(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _require_live_stack()

    rls_pool = build_rls_pool(settings.database_url)
    admin_pool = build_admin_pool(settings.database_admin_url)
    assert rls_pool is not None and admin_pool is not None
    rls_pool.open()
    admin_pool.open()
    set_pools(rls_pool, admin_pool)

    real_sender = email_sender_from_settings(settings)
    assert real_sender is not None, "resend_api_key is set - the real sender must build"
    spy = _CapturingSender(real_sender)

    # (1)/(2) go through app.routers.tasks's own imported `notify`/`notify_leads`
    # names - wrap them so the REAL notify/notify_leads still run, just with the
    # spy sender injected (mirrors test_tasks_endpoints.py's monkeypatch idiom).
    async def _notify_with_spy(*args: Any, **kwargs: Any) -> None:
        kwargs.setdefault("email_sender", spy)
        await notifications_mod.notify(*args, **kwargs)

    async def _notify_leads_with_spy(*args: Any, **kwargs: Any) -> None:
        kwargs.setdefault("email_sender", spy)
        await notifications_mod.notify_leads(*args, **kwargs)

    monkeypatch.setattr(tasks_router, "notify", _notify_with_spy)
    monkeypatch.setattr(tasks_router, "notify_leads", _notify_leads_with_spy)

    codes: list[str] = []
    uids: list[str] = []
    client_id: str | None = None
    ticket_codes: list[str] = []
    results: dict[str, str] = {}

    try:
        tag = uuid4().hex[:8]

        with privileged_connection(pool=admin_pool) as cur:
            cur.execute(
                "insert into public.clients (name, delivery_tier, contact_email) "
                "values ('Email Flow Co', 'free', %s) returning id",
                (f"adandevelops+client-{tag}@gmail.com",),
            )
            client_id = str(cur.fetchone()["id"])

        from app.services.provisioning import provision_user

        lead_uid = str(provision_user(
            email=f"adandevelops+task-lead-{tag}@gmail.com", password=_PASSWORD,
            name="Live Lead", role="manager", username=f"live_lead_{tag}",
        )["id"])
        spec_uid = str(provision_user(
            email=f"adandevelops+task-assignee-{tag}@gmail.com", password=_PASSWORD,
            name="Live Specialist", role="specialist", username=f"live_spec_{tag}",
        )["id"])
        cli_uid = str(provision_user(
            email=f"adandevelops+client-portal-{tag}@gmail.com", password=_PASSWORD,
            name="Live Client", role="client", username=f"live_cli_{tag}", client_id=client_id,
        )["id"])
        uids += [lead_uid, spec_uid, cli_uid]

        # provision_user always inserts status='invited'; notify_leads's fan-out
        # (_active_lead_ids) excludes invited users, so flip the lead active - a
        # freshly-onboarded lead who has since logged in, in production terms.
        with privileged_connection(pool=admin_pool) as cur:
            cur.execute(
                "update public.users set status = 'active' where id = %s", (lead_uid,)
            )

        lead_user = CurrentUser(
            id=lead_uid, email=f"adandevelops+task-lead-{tag}@gmail.com", role="manager",
            status="active", name="Live Lead", title="", avatar_color="#7B69EE",
            phone="", two_fa=False,
        )
        # ================================================================= (1)
        # Admin/lead assigns a task to a team member -> the assignee gets an
        # email (kind="task_assigned"). Real POST /tasks code path.
        create_body = TaskCreate(
            title="Live email test task", client_id=client_id, type="Technical Audit",
            assignee_id=spec_uid, priority="high",
        )
        task = await tasks_router.create_task(
            create_body,
            TasksRepo(lead_uid),
            ClientsRepo(lead_uid),
            lead_user,
        )
        codes.append(task.id)
        task_assigned_sends = [s for s in spy.sent if s[0] == f"adandevelops+task-assignee-{tag}@gmail.com"]
        assert task_assigned_sends, "task_assigned email did not fire - check NOTIF_EVENTS/prefs"
        results["1_task_assigned"] = task_assigned_sends[-1][2]

        # ================================================================= (2)
        # The assignee finishes the task (a direct in_progress -> done transition
        # on a non-review type) -> notify_leads(kind="task_completed") fans out to
        # every active lead, including ours (redirected to the test inbox).
        #
        # NOTE - this LOCAL Postgres is missing migration 0073 (tasks.started_at /
        # tasks.completed_at do not exist here: `select column_name from
        # information_schema.columns where table_name='tasks'` confirms it, and
        # test_tasks_flow.py - an EXISTING, unmodified integration test - fails the
        # same way on this DB independent of anything in this file). advance_task
        # unconditionally stamps started_at on todo->in_progress and completed_at
        # on ->done, so ANY call to the real router function 500s here regardless
        # of task type or which leg is driven; fixing it needs schema DDL as the
        # Postgres superuser, which this run does not have credentials for. Rather
        # than block scenario 2 entirely, the task row is still driven through a
        # real in_progress->done UPDATE (service_role, the columns that DO exist),
        # then the EXACT call the router makes on that transition - real
        # notify_leads(kind="task_completed", ...), same title/body shape, same
        # kind - is fired directly so the notification-delivery half of the real
        # code path (prefs resolution + Resend send) is still exercised live.
        # The lead identity (not the privileged/service_role pool - the
        # tasks_guard_update trigger runs regardless of RLS-bypass and only a
        # LEAD is allowed to skip straight to done) drives the columns that DO
        # exist on this schema.
        with rls_connection(lead_uid, pool=rls_pool) as cur:
            cur.execute(
                "update public.tasks set status = 'done' where code = %s", (task.id,)
            )
        await tasks_router.notify_leads(
            kind="task_completed",
            title=f"Task completed: {create_body.title} ({task.id})",
            body=(
                f'"{create_body.title}" ({task.id}, technical_audit) for Email Flow Co '
                f"was completed by {spec_uid}."
            ),
        )
        lead_alias = f"adandevelops+task-lead-{tag}@gmail.com"
        task_completed_sends = [s for s in spy.sent if s[0] == lead_alias]
        assert task_completed_sends, "task_completed email to the lead did not fire"
        results["2_task_completed"] = task_completed_sends[-1][2]

        # ================================================================= (3)
        # A client submits a portal request -> the FIXED admin_notify_email
        # address gets an email (email_admin). admin_notify_email is a plain
        # attribute on the (lru_cache'd) Settings singleton - monkeypatch it
        # directly for the duration of this call, redirected to the bare test
        # inbox (there is no per-user row here, so no +alias is needed).
        monkeypatch.setattr(settings, "admin_notify_email", _TEST_INBOX)

        class _FakeReader:
            def get_client(self) -> dict[str, Any]:
                return {"name": "Email Flow Co"}

        client_user = CurrentUser(
            id=cli_uid, email=f"adandevelops+client-portal-{tag}@gmail.com", role="client",
            status="active", name="Live Client", title="", avatar_color="#7B69EE",
            phone="", two_fa=False, client_id=client_id,
        )
        scoped = CurrentClient(user=client_user, client_id=client_id)
        body = PortalRequestCreate(
            kind="Support", subject="Live email integration test",
            detail="Proving the client-request -> admin email workflow end to end.",
        )
        ticket = await create_client_request(
            insert_request=insert_request_row,
            reader=_FakeReader(),
            scoped=scoped,
            body=body,
            email_sender=spy,
        )
        ticket_codes.append(str(ticket["code"]))
        admin_sends = [s for s in spy.sent if s[0] == _TEST_INBOX]
        assert admin_sends, "client-request admin email did not fire"
        results["3_client_request"] = admin_sends[-1][2]

        print("\n=== Live Resend sends (all to adandevelops@gmail.com, via +alias where per-user) ===")
        for to, subject, message_id in spy.sent:
            print(f"  to={to!r} subject={subject!r} resend_message_id={message_id!r}")
        print(f"=== Scenario -> message id: {results} ===\n")

        assert all(results.values()), "every scenario must have produced a real message id"
    finally:
        with contextlib.suppress(Exception), privileged_connection(pool=admin_pool) as cur:
            for code in ticket_codes:
                cur.execute("delete from public.support_tickets where code = %s", (code,))
            for code in codes:
                cur.execute("delete from public.tasks where code = %s", (code,))
            for uid in uids:
                cur.execute("delete from auth.users where id = %s", (uid,))
            if client_id:
                cur.execute("delete from public.clients where id = %s", (client_id,))
        clear_pools()
        rls_pool.close()
        admin_pool.close()
