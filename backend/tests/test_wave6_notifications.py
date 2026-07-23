"""Wave 6: lead fan-out + SYNC notification wrappers (the content_review / audit_done
email dispatch). Proves notify_leads emails EACH active lead through the (fake) Resend
seam for a known event key, the sync wrappers drive notify from a worker context, and
all of them are best-effort (never raise). No DB, no network: the privileged pool is a
capturing fake cursor and the email seam is the in-memory FakeEmailSender.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import pytest

from app.services.notifications import notify_leads, notify_leads_sync, notify_sync
from integrations.resend import FakeEmailSender

pytestmark = pytest.mark.unit

_NOTIF_INSERT = "insert into public.notifications"


class _FakeCursor:
    def __init__(
        self,
        *,
        user_row: dict[str, Any] | None = None,
        pref_row: dict[str, Any] | None = None,
        lead_rows: list[dict[str, Any]] | None = None,
    ) -> None:
        self.user_row = user_row
        self.pref_row = pref_row
        self.lead_rows = lead_rows or []
        self.executed: list[tuple[str, Any]] = []
        self._last = ""

    def execute(self, query: Any, params: Any = None) -> None:
        self._last = str(query)
        self.executed.append((str(query), params))

    def fetchone(self) -> dict[str, Any] | None:
        if "from public.users where id" in self._last:
            return self.user_row
        if "from public.notification_prefs" in self._last:
            return self.pref_row
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


def _patch(monkeypatch: pytest.MonkeyPatch, cur: _FakeCursor) -> None:
    monkeypatch.setattr(
        "app.services.notifications.privileged_connection", lambda: _fake_privileged(cur)
    )


# --- notify_leads --------------------------------------------------------------
async def test_notify_leads_emails_each_active_lead(monkeypatch: pytest.MonkeyPatch) -> None:
    cur = _FakeCursor(
        user_row={"email": "lead@x.com"},
        pref_row={"email": True, "in_app": True},
        lead_rows=[{"id": "l-1"}, {"id": "l-2"}],
    )
    _patch(monkeypatch, cur)
    sender = FakeEmailSender()
    # content_review is a NOTIF_EVENTS key with email default on -> email leg fires.
    await notify_leads("content_review", "Review", "A draft is ready", email_sender=sender)
    assert cur.count(_NOTIF_INSERT) == 2  # one in-app row per lead
    assert len(sender.sent) == 2  # one email per lead
    assert {s.to for s in sender.sent} == {"lead@x.com"}


async def test_notify_leads_no_leads_is_noop(monkeypatch: pytest.MonkeyPatch) -> None:
    cur = _FakeCursor(lead_rows=[])
    _patch(monkeypatch, cur)
    sender = FakeEmailSender()
    await notify_leads("audit_done", "T", "B", email_sender=sender)
    assert cur.count(_NOTIF_INSERT) == 0
    assert sender.sent == []


async def test_notify_leads_never_raises_when_pool_booms(monkeypatch: pytest.MonkeyPatch) -> None:
    def _boom() -> Any:
        raise RuntimeError("no privileged pool")

    monkeypatch.setattr("app.services.notifications.privileged_connection", _boom)
    await notify_leads("content_review", "T", "B", email_sender=FakeEmailSender())  # no raise


# --- sync wrappers (Celery worker context) ------------------------------------
def test_notify_sync_drives_notify(monkeypatch: pytest.MonkeyPatch) -> None:
    cur = _FakeCursor(user_row={"email": "u@x.com"}, pref_row={"email": True, "in_app": True})
    _patch(monkeypatch, cur)
    sender = FakeEmailSender()
    monkeypatch.setattr(
        "app.services.notifications.email_sender_from_settings", lambda _s: sender
    )
    notify_sync("u-1", "audit_done", "Audit ready", "The report is ready")
    assert cur.count(_NOTIF_INSERT) == 1
    assert len(sender.sent) == 1


def test_notify_leads_sync_drives_fan_out(monkeypatch: pytest.MonkeyPatch) -> None:
    cur = _FakeCursor(
        user_row={"email": "lead@x.com"},
        pref_row={"email": True, "in_app": True},
        lead_rows=[{"id": "l-1"}, {"id": "l-2"}],
    )
    _patch(monkeypatch, cur)
    sender = FakeEmailSender()
    monkeypatch.setattr(
        "app.services.notifications.email_sender_from_settings", lambda _s: sender
    )
    notify_leads_sync("audit_done", "Audit ready", "Report is ready")
    assert cur.count(_NOTIF_INSERT) == 2
    assert len(sender.sent) == 2


def test_notify_sync_never_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    def _boom() -> Any:
        raise RuntimeError("no privileged pool")

    monkeypatch.setattr("app.services.notifications.privileged_connection", _boom)
    notify_sync("u-1", "audit_done", "T", "B")  # no raise
    notify_leads_sync("audit_done", "T", "B")  # no raise
