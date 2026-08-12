"""Unit tests for the FOUR comms directions - each event resolves the correct
counterpart's email and fires the send (best-effort, prefs-aware), and the whole path
routes through whichever provider ``EMAIL_PROVIDER`` selects (proved here with SMTP).

Directions:
* admin/staff -> team member  : ``notify(uid, "task_assigned", ...)``  -> the assignee's
  ``public.users`` email;
* team member -> admin/leads  : ``notify_leads("content_review", ...)`` -> each active
  lead's email;
* admin -> client             : ``email_client(client_id, ...)`` -> the client's
  ``contact_email``;
* client -> admin             : ``email_admin(...)`` -> the fixed operator inbox
  (``settings.admin_notify_email``).

No DB, no network: the privileged pool is a capturing fake cursor and the email seam is
the in-memory ``FakeEmailSender`` (or a fake-smtplib ``SmtpEmailSender`` for the
transport-routing test).
"""

from __future__ import annotations

import smtplib
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import pytest

from app.config import get_settings
from app.services import notifications as svc
from app.services.notifications import email_admin, email_client, notify, notify_leads
from integrations.resend import FakeEmailSender
from integrations.smtp_email import SmtpEmailSender

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
        self._last = ""

    def execute(self, query: Any, params: Any = None) -> None:
        self._last = str(query)

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


@contextmanager
def _fake_privileged(cur: _FakeCursor) -> Iterator[_FakeCursor]:
    yield cur


def _patch(monkeypatch: pytest.MonkeyPatch, cur: _FakeCursor) -> None:
    monkeypatch.setattr(
        "app.services.notifications.privileged_connection", lambda: _fake_privileged(cur)
    )


_EMAIL_ON = {"email": True, "in_app": True}


# --------------------------------------------------------------------------- #
# Direction 1 - admin/staff -> team member
# --------------------------------------------------------------------------- #
async def test_admin_to_team_emails_the_assignee(monkeypatch: pytest.MonkeyPatch) -> None:
    cur = _FakeCursor(user_row={"email": "alex@team.com"}, pref_row=_EMAIL_ON)
    _patch(monkeypatch, cur)
    sender = FakeEmailSender()
    await notify(
        "11111111-1111-1111-1111-111111111111", "task_assigned",
        "New task assigned", "On-page fixes for /pricing", email_sender=sender,
    )
    assert len(sender.sent) == 1
    assert sender.sent[0].to == "alex@team.com"  # the counterpart = the assignee


# --------------------------------------------------------------------------- #
# Direction 2 - team member -> admin/leads
# --------------------------------------------------------------------------- #
async def test_team_to_admin_emails_each_lead(monkeypatch: pytest.MonkeyPatch) -> None:
    cur = _FakeCursor(
        user_row={"email": "lead@agency.com"},  # served to each lead's notify()
        pref_row=_EMAIL_ON,
        lead_rows=[{"id": "22222222-2222-2222-2222-222222222222"},
                   {"id": "33333333-3333-3333-3333-333333333333"}],
    )
    _patch(monkeypatch, cur)
    sender = FakeEmailSender()
    await notify_leads("content_review", "Submitted for review", "Draft ready",
                       email_sender=sender)
    assert len(sender.sent) == 2  # one per active lead
    assert {s.to for s in sender.sent} == {"lead@agency.com"}


# --------------------------------------------------------------------------- #
# Direction 3 - admin -> client
# --------------------------------------------------------------------------- #
async def test_admin_to_client_emails_the_client_contact(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cur = _FakeCursor(client_row={"name": "Atlas Legal", "contact_email": "hi@atlas.com"})
    _patch(monkeypatch, cur)
    sender = FakeEmailSender()
    await email_client("cl-1", "Your report is ready", "<p>hi</p>", "hi", email_sender=sender)
    assert len(sender.sent) == 1
    assert sender.sent[0].to == "hi@atlas.com"  # the counterpart = the client contact


# --------------------------------------------------------------------------- #
# Direction 4 - client -> admin
# --------------------------------------------------------------------------- #
async def test_client_to_admin_emails_the_operator_inbox(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sender = FakeEmailSender()
    await email_admin("New portal request", "<p>details</p>", "details", email_sender=sender)
    assert len(sender.sent) == 1
    assert sender.sent[0].to == get_settings().admin_notify_email  # the operator inbox


# --------------------------------------------------------------------------- #
# The whole path routes through the SELECTED provider (SMTP), end-to-end.
# --------------------------------------------------------------------------- #
class _FakeSMTP:
    last: _FakeSMTP | None = None

    def __init__(self, host: str, port: int, timeout: float | None = None) -> None:
        self.sent: list[Any] = []
        _FakeSMTP.last = self

    def __enter__(self) -> _FakeSMTP:
        return self

    def __exit__(self, *exc: object) -> bool:
        return False

    def starttls(self) -> None:
        pass

    def login(self, user: str, password: str) -> None:
        pass

    def send_message(self, msg: Any) -> None:
        self.sent.append(msg)


async def test_admin_to_client_routes_through_smtp_transport(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # With EMAIL_PROVIDER=smtp the factory yields an SmtpEmailSender; prove a direction
    # event lands on the resolved recipient over the (faked) SMTP transport.
    monkeypatch.setattr(smtplib, "SMTP", _FakeSMTP)
    cur = _FakeCursor(client_row={"name": "Atlas Legal", "contact_email": "hi@atlas.com"})
    _patch(monkeypatch, cur)
    smtp_sender = SmtpEmailSender(host="smtp.gmail.com", port=587, user="ops@x.com",
                                  password="pw", from_email="AIOS <ops@x.com>")
    monkeypatch.setattr(
        "app.services.notifications.email_sender_from_settings", lambda _s: smtp_sender
    )
    await email_client("cl-1", "Your report is ready", "<p>hi</p>", "hi")  # no injected sender
    assert _FakeSMTP.last is not None
    assert len(_FakeSMTP.last.sent) == 1
    assert _FakeSMTP.last.sent[0]["To"] == "hi@atlas.com"


# --------------------------------------------------------------------------- #
# The in-app email body is now branded (routes through the templates module).
# --------------------------------------------------------------------------- #
async def test_in_app_email_body_is_branded(monkeypatch: pytest.MonkeyPatch) -> None:
    cur = _FakeCursor(user_row={"email": "alex@team.com"}, pref_row=_EMAIL_ON)
    _patch(monkeypatch, cur)
    sender = FakeEmailSender()
    await notify("u-1", "task_assigned", "New task", "Body here", email_sender=sender)
    assert "AIOS" in sender.sent[0].html  # branded header
    assert svc._email_html("T", "B").startswith("<div")  # wrapper, not the old <h2>
