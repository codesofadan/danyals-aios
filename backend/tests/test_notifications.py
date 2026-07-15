"""Unit tests for the delivery layer (7F-1): the notify()/raise_alert() service and
the /notifications + /alerts endpoints.

Covers:
* notify honours notification_prefs - in-app row written when in_app on, email leg
  fired ONLY when email on AND a provider is present (the two legs are independent);
* an unknown kind (an alert type) delivers in-app only, never email;
* keyless degrade - email pref on but no provider -> no email, no crash, in-app lands;
* notify + raise_alert are best-effort (never raise) when the privileged pool booms;
* raise_alert writes the alert, notifies every lead, and posts to Slack (key-gated);
* endpoint RBAC - per-user notification isolation, staff-only alerts, lead-only ack.

No DB, no network: the privileged pool is monkeypatched to a capturing cursor and the
email/Slack seams use their in-memory fakes.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
from fastapi import FastAPI

from app.core.auth import CurrentUser, get_current_user
from app.db.notifications_repo import get_notifications_repo
from app.services import notifications as svc
from app.services.notifications import notify, raise_alert
from integrations.resend import FakeEmailSender
from integrations.slack import FakeSlackNotifier

pytestmark = pytest.mark.unit


# --------------------------------------------------------------------------- #
# Fake privileged cursor (dispatches fetch by the last query's shape)
# --------------------------------------------------------------------------- #
class _FakeCursor:
    def __init__(
        self,
        *,
        user_row: dict[str, Any] | None = None,
        pref_row: dict[str, Any] | None = None,
        client_row: dict[str, Any] | None = None,
        lead_rows: list[dict[str, Any]] | None = None,
    ) -> None:
        self.user_row = user_row
        self.pref_row = pref_row
        self.client_row = client_row
        self.lead_rows = lead_rows or []
        self.executed: list[tuple[str, Any]] = []
        self._last = ""

    def execute(self, query: Any, params: Any = None) -> None:
        self._last = str(query)
        self.executed.append((str(query), params))

    def fetchone(self) -> dict[str, Any] | None:
        q = self._last
        if "from public.users where id" in q:
            return self.user_row
        if "from public.notification_prefs" in q:
            return self.pref_row
        if "from public.clients where id" in q:
            return self.client_row
        return None

    def fetchall(self) -> list[dict[str, Any]]:
        if "from public.users" in self._last and "role in" in self._last:
            return self.lead_rows
        return []

    def count(self, fragment: str) -> int:
        return sum(1 for q, _ in self.executed if fragment in q)


@contextmanager
def _fake_privileged(cur: _FakeCursor) -> Iterator[_FakeCursor]:
    yield cur


def _patch_privileged(monkeypatch: pytest.MonkeyPatch, cur: _FakeCursor) -> None:
    monkeypatch.setattr(
        "app.services.notifications.privileged_connection", lambda: _fake_privileged(cur)
    )


_NOTIF_INSERT = "insert into public.notifications"
_ALERT_INSERT = "insert into public.alerts"


# --------------------------------------------------------------------------- #
# notify() - preference honouring
# --------------------------------------------------------------------------- #
async def test_notify_writes_in_app_and_emails_when_both_on(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cur = _FakeCursor(
        user_row={"email": "lead@x.com"}, pref_row={"email": True, "in_app": True}
    )
    _patch_privileged(monkeypatch, cur)
    sender = FakeEmailSender()
    await notify("11111111-1111-1111-1111-111111111111", "audit_done", "Audit done", "Body",
                 email_sender=sender)
    assert cur.count(_NOTIF_INSERT) == 1  # in-app row written
    assert len(sender.sent) == 1  # email leg fired
    assert sender.sent[0].to == "lead@x.com"
    assert sender.sent[0].subject == "Audit done"


async def test_notify_in_app_only_when_email_pref_off(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cur = _FakeCursor(
        user_row={"email": "lead@x.com"}, pref_row={"email": False, "in_app": True}
    )
    _patch_privileged(monkeypatch, cur)
    sender = FakeEmailSender()
    await notify("u-1", "audit_done", "T", "B", email_sender=sender)
    assert cur.count(_NOTIF_INSERT) == 1  # in-app still lands
    assert sender.sent == []  # email pref off -> no send


async def test_notify_emails_without_in_app_when_email_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The two legs are INDEPENDENT: in_app off + email on -> no row, but an email.
    cur = _FakeCursor(
        user_row={"email": "lead@x.com"}, pref_row={"email": True, "in_app": False}
    )
    _patch_privileged(monkeypatch, cur)
    sender = FakeEmailSender()
    await notify("u-1", "audit_done", "T", "B", email_sender=sender)
    assert cur.count(_NOTIF_INSERT) == 0  # in_app off -> no row
    assert len(sender.sent) == 1  # email on -> sent


async def test_notify_unknown_kind_is_in_app_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # An unknown kind (no stored pref, not a NOTIF_EVENTS key) falls back to
    # in-app-only - never email.
    cur = _FakeCursor(user_row={"email": "lead@x.com"}, pref_row=None)
    _patch_privileged(monkeypatch, cur)
    sender = FakeEmailSender()
    await notify("u-1", "rank_drop", "T", "B", email_sender=sender)
    assert cur.count(_NOTIF_INSERT) == 1
    assert sender.sent == []  # unknown kind never emails


async def test_notify_default_pref_used_when_no_stored_row(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # weekly_digest defaults (NOTIF_EVENTS) are email=True, in_app=False - so with NO
    # stored row we should email and NOT write an in-app row.
    cur = _FakeCursor(user_row={"email": "lead@x.com"}, pref_row=None)
    _patch_privileged(monkeypatch, cur)
    sender = FakeEmailSender()
    await notify("u-1", "weekly_digest", "Weekly", "B", email_sender=sender)
    assert cur.count(_NOTIF_INSERT) == 0
    assert len(sender.sent) == 1


async def test_notify_keyless_degrade_no_email_no_crash(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Email pref ON but NO provider configured -> email leg skipped, in-app still
    # lands, and nothing raises.
    cur = _FakeCursor(
        user_row={"email": "lead@x.com"}, pref_row={"email": True, "in_app": True}
    )
    _patch_privileged(monkeypatch, cur)
    monkeypatch.setattr(
        "app.services.notifications.email_sender_from_settings", lambda _s: None
    )
    await notify("u-1", "audit_done", "T", "B")  # no injected sender, no provider
    assert cur.count(_NOTIF_INSERT) == 1  # in-app landed
    # (no sender to assert against; the point is it did not raise)


async def test_notify_unknown_recipient_is_noop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cur = _FakeCursor(user_row=None, pref_row={"email": True, "in_app": True})
    _patch_privileged(monkeypatch, cur)
    sender = FakeEmailSender()
    await notify("u-ghost", "audit_done", "T", "B", email_sender=sender)
    assert cur.count(_NOTIF_INSERT) == 0
    assert sender.sent == []


async def test_notify_never_raises_when_pool_booms(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _boom() -> Any:
        raise RuntimeError("no privileged pool")

    monkeypatch.setattr("app.services.notifications.privileged_connection", _boom)
    await notify("u-1", "audit_done", "T", "B", email_sender=FakeEmailSender())  # no raise


# --------------------------------------------------------------------------- #
# raise_alert()
# --------------------------------------------------------------------------- #
async def test_raise_alert_writes_alert_notifies_leads_and_slacks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cur = _FakeCursor(
        user_row={"email": "lead@x.com"},  # served to each lead's notify()
        pref_row=None,  # alert kind is unknown -> in-app only
        client_row={"name": "Atlas Legal"},
        lead_rows=[{"id": "22222222-2222-2222-2222-222222222222"},
                   {"id": "33333333-3333-3333-3333-333333333333"}],
    )
    _patch_privileged(monkeypatch, cur)
    slack = FakeSlackNotifier()
    await raise_alert("c-atlas", "rank_drop", "critical", "Keyword slipped to page 2",
                      slack=slack)
    assert cur.count(_ALERT_INSERT) == 1  # the alert row
    assert cur.count(_NOTIF_INSERT) == 2  # one in-app per lead
    assert len(slack.posts) == 1
    assert "Rank drop: Atlas Legal" in slack.posts[0]
    assert "critical" in slack.posts[0]


async def test_raise_alert_unknown_client_is_noop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cur = _FakeCursor(client_row=None, lead_rows=[{"id": "u-a"}])
    _patch_privileged(monkeypatch, cur)
    slack = FakeSlackNotifier()
    await raise_alert("c-ghost", "budget", "warning", "over cap", slack=slack)
    assert cur.count(_ALERT_INSERT) == 0
    assert cur.count(_NOTIF_INSERT) == 0
    assert slack.posts == []


async def test_raise_alert_never_raises_when_pool_booms(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _boom() -> Any:
        raise RuntimeError("no privileged pool")

    monkeypatch.setattr("app.services.notifications.privileged_connection", _boom)
    await raise_alert("c-atlas", "lost_link", "warning", "backlink dark",
                      slack=FakeSlackNotifier())  # no raise


async def test_raise_alert_without_slack_key_does_not_crash(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cur = _FakeCursor(
        user_row={"email": "lead@x.com"}, pref_row=None,
        client_row={"name": "Atlas"}, lead_rows=[],
    )
    _patch_privileged(monkeypatch, cur)
    monkeypatch.setattr(
        "app.services.notifications.slack_notifier_from_settings", lambda _s: None
    )
    await raise_alert("c-atlas", "budget", "info", "near cap")  # no slack, no raise
    assert cur.count(_ALERT_INSERT) == 1


# --------------------------------------------------------------------------- #
# svc default-pref table sanity
# --------------------------------------------------------------------------- #
def test_default_prefs_seeded_from_catalogue() -> None:
    # audit_done is email+in_app; member_login is in_app-only (NOTIF_EVENTS).
    assert svc._DEFAULT_PREFS["audit_done"] == (True, True)
    assert svc._DEFAULT_PREFS["member_login"] == (False, True)
    assert svc._UNKNOWN_KIND_PREF == (False, True)


# --------------------------------------------------------------------------- #
# Endpoints (faked repo)
# --------------------------------------------------------------------------- #
def _n_row(**over: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "id": "aaaaaaaa-0000-0000-0000-000000000001",
        "kind": "audit_done",
        "title": "Audit done",
        "body": "The report is ready",
        "read": False,
        "created_at": datetime.now(UTC),
    }
    row.update(over)
    return row


def _a_row(**over: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "id": "bbbbbbbb-0000-0000-0000-000000000001",
        "client_id": "cccccccc-0000-0000-0000-000000000001",
        "type": "rank_drop",
        "severity": "warning",
        "detail": "Keyword slipped",
        "acknowledged": False,
        "created_at": datetime.now(UTC),
    }
    row.update(over)
    return row


class FakeNotificationsRepo:
    def __init__(self) -> None:
        self.notifications: list[dict[str, Any]] = []
        self.alerts: list[dict[str, Any]] = []

    def list_notifications(
        self, *, unread_only: bool = False, limit: int | None = None, offset: int = 0
    ) -> list[dict[str, Any]]:
        rows = self.notifications
        if unread_only:
            rows = [r for r in rows if not r.get("read")]
        return rows

    def mark_read(self, notification_id: str) -> dict[str, Any] | None:
        for r in self.notifications:
            if str(r["id"]) == notification_id:
                r["read"] = True
                return r
        return None

    def list_alerts(
        self, *, unacknowledged_only: bool = False, limit: int | None = None, offset: int = 0
    ) -> list[dict[str, Any]]:
        rows = self.alerts
        if unacknowledged_only:
            rows = [r for r in rows if not r.get("acknowledged")]
        return rows

    def acknowledge_alert(self, alert_id: str) -> dict[str, Any] | None:
        for r in self.alerts:
            if str(r["id"]) == alert_id:
                r["acknowledged"] = True
                return r
        return None


def _user(role: str, uid: str = "44444444-4444-4444-4444-444444444444") -> CurrentUser:
    return CurrentUser(
        id=uid, email="op@x.com", role=role, status="active",  # type: ignore[arg-type]
        name="Op", title="", avatar_color="#000", phone="", two_fa=False,
    )


@pytest.fixture
def repo() -> FakeNotificationsRepo:
    return FakeNotificationsRepo()


@pytest.fixture
def wire(app: FastAPI, repo: FakeNotificationsRepo) -> Callable[..., None]:
    app.dependency_overrides[get_notifications_repo] = lambda: repo

    def _as(role: str) -> None:
        app.dependency_overrides[get_current_user] = lambda: _user(role)

    return _as


# --- notifications (per-user) ---

async def test_notifications_require_auth(client: httpx.AsyncClient) -> None:
    assert (await client.get("/api/v1/notifications")).status_code == 401


async def test_notifications_list_own_and_unread_filter(
    client: httpx.AsyncClient, repo: FakeNotificationsRepo, wire: Callable[..., None]
) -> None:
    repo.notifications = [_n_row(read=False), _n_row(id="aaaaaaaa-0000-0000-0000-000000000002", read=True)]
    wire("viewer")
    body = (await client.get("/api/v1/notifications")).json()
    assert len(body) == 2
    assert set(body[0]) == {"id", "kind", "title", "body", "read", "createdAt"}
    only_unread = (await client.get("/api/v1/notifications", params={"unread": True})).json()
    assert len(only_unread) == 1
    assert only_unread[0]["read"] is False


async def test_notifications_allowed_for_portal_client(
    client: httpx.AsyncClient, wire: Callable[..., None]
) -> None:
    # notifications are per-user (not a staff namespace) - a client may read its own.
    wire("client")
    assert (await client.get("/api/v1/notifications")).status_code == 200


async def test_mark_read_flips_and_unknown_404(
    client: httpx.AsyncClient, repo: FakeNotificationsRepo, wire: Callable[..., None]
) -> None:
    seeded = _n_row()
    repo.notifications = [seeded]
    wire("viewer")
    ok = await client.post(f"/api/v1/notifications/{seeded['id']}/read")
    assert ok.status_code == 200
    assert ok.json()["read"] is True
    missing = await client.post(
        "/api/v1/notifications/aaaaaaaa-0000-0000-0000-0000000000ff/read"
    )
    assert missing.status_code == 404


async def test_mark_read_rejects_malformed_id(
    client: httpx.AsyncClient, wire: Callable[..., None]
) -> None:
    wire("viewer")
    assert (await client.post("/api/v1/notifications/not-a-uuid/read")).status_code == 422


# --- alerts (staff read; lead acknowledge) ---

async def test_alerts_forbidden_for_client(
    client: httpx.AsyncClient, wire: Callable[..., None]
) -> None:
    wire("client")  # a portal client lacks view_reports
    assert (await client.get("/api/v1/alerts")).status_code == 403


async def test_alerts_list_for_staff_and_filter(
    client: httpx.AsyncClient, repo: FakeNotificationsRepo, wire: Callable[..., None]
) -> None:
    repo.alerts = [_a_row(acknowledged=False),
                   _a_row(id="bbbbbbbb-0000-0000-0000-000000000002", acknowledged=True)]
    wire("viewer")
    body = (await client.get("/api/v1/alerts")).json()
    assert len(body) == 2
    assert set(body[0]) == {"id", "clientId", "type", "severity", "detail",
                            "acknowledged", "createdAt"}
    open_only = (await client.get("/api/v1/alerts", params={"unacknowledged": True})).json()
    assert len(open_only) == 1
    assert open_only[0]["acknowledged"] is False


async def test_acknowledge_requires_lead(
    client: httpx.AsyncClient, repo: FakeNotificationsRepo, wire: Callable[..., None]
) -> None:
    seeded = _a_row()
    repo.alerts = [seeded]
    wire("specialist")  # not a lead
    assert (await client.post(f"/api/v1/alerts/{seeded['id']}/acknowledge")).status_code == 403


async def test_acknowledge_happy_path_and_unknown_404(
    client: httpx.AsyncClient, repo: FakeNotificationsRepo, wire: Callable[..., None]
) -> None:
    seeded = _a_row()
    repo.alerts = [seeded]
    wire("manager")
    ok = await client.post(f"/api/v1/alerts/{seeded['id']}/acknowledge")
    assert ok.status_code == 200
    assert ok.json()["acknowledged"] is True
    missing = await client.post(
        "/api/v1/alerts/bbbbbbbb-0000-0000-0000-0000000000ff/acknowledge"
    )
    assert missing.status_code == 404
