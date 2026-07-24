"""Unit tests for the client-addressed email leg of the delivery layer (all-way
comms): ``email_client`` / ``email_client_sync`` + the ``_resolve_client_email``
resolver.

Covers:
* recipient resolution - prefers the client's ``contact_email``, falls back to a
  provisioned portal login (``users`` role='client'), and an explicit ``email`` wins
  and skips resolution entirely;
* best-effort + key-gated - a keyless provider, an unresolvable recipient, a booming
  pool, or a raising sender are ALL swallowed (the send is skipped, nothing raises);
* the sync wrapper drives the async helper from a worker context.

No DB, no network: the privileged pool is a capturing fake cursor and the email seam
uses the in-memory FakeEmailSender.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import pytest

from app.services.notifications import email_client, email_client_sync
from integrations.resend import FakeEmailSender

pytestmark = pytest.mark.unit


class _FakeCursor:
    """Dispatches fetchone by the query shape: the clients row for the contact-email
    lookup, the portal-user row for the role='client' fallback."""

    def __init__(
        self,
        *,
        client_row: dict[str, Any] | None = None,
        portal_user_row: dict[str, Any] | None = None,
    ) -> None:
        self.client_row = client_row
        self.portal_user_row = portal_user_row
        self.executed: list[str] = []
        self._last = ""

    def execute(self, query: Any, params: Any = None) -> None:
        self._last = str(query)
        self.executed.append(str(query))

    def fetchone(self) -> dict[str, Any] | None:
        q = self._last
        if "from public.clients where id" in q:
            return self.client_row
        if "from public.users" in q and "role = 'client'" in q:
            return self.portal_user_row
        return None


@contextmanager
def _fake_privileged(cur: _FakeCursor) -> Iterator[_FakeCursor]:
    yield cur


def _patch(monkeypatch: pytest.MonkeyPatch, cur: _FakeCursor) -> None:
    monkeypatch.setattr(
        "app.services.notifications.privileged_connection", lambda: _fake_privileged(cur)
    )


# --------------------------------------------------------------------------- #
# Recipient resolution
# --------------------------------------------------------------------------- #
async def test_email_client_uses_contact_email(monkeypatch: pytest.MonkeyPatch) -> None:
    cur = _FakeCursor(client_row={"name": "Atlas Legal", "contact_email": "hi@atlas.com"})
    _patch(monkeypatch, cur)
    sender = FakeEmailSender()
    await email_client("cl-1", "Your report is ready", "<p>hi</p>", "hi", email_sender=sender)
    assert len(sender.sent) == 1
    assert sender.sent[0].to == "hi@atlas.com"
    assert sender.sent[0].subject == "Your report is ready"


async def test_email_client_falls_back_to_portal_login(monkeypatch: pytest.MonkeyPatch) -> None:
    # No primary contact recorded -> use the provisioned portal user's email.
    cur = _FakeCursor(
        client_row={"name": "Atlas Legal", "contact_email": ""},
        portal_user_row={"email": "portal@atlas.com"},
    )
    _patch(monkeypatch, cur)
    sender = FakeEmailSender()
    await email_client("cl-1", "Subject", "<p>hi</p>", email_sender=sender)
    assert len(sender.sent) == 1
    assert sender.sent[0].to == "portal@atlas.com"


async def test_email_client_explicit_email_skips_resolution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # An explicit address wins - resolution is never attempted (prove it by booming
    # the pool: if the helper touched it, this would blow up rather than send).
    def _boom() -> Any:
        raise RuntimeError("pool must not be touched")

    monkeypatch.setattr("app.services.notifications.privileged_connection", _boom)
    sender = FakeEmailSender()
    await email_client("cl-1", "Subject", "<p>hi</p>", email="direct@x.com", email_sender=sender)
    assert len(sender.sent) == 1
    assert sender.sent[0].to == "direct@x.com"


async def test_email_client_no_recipient_is_noop(monkeypatch: pytest.MonkeyPatch) -> None:
    cur = _FakeCursor(client_row=None, portal_user_row=None)
    _patch(monkeypatch, cur)
    sender = FakeEmailSender()
    await email_client("cl-ghost", "S", "<p>h</p>", email_sender=sender)
    assert sender.sent == []  # nothing to email -> silently skipped


# --------------------------------------------------------------------------- #
# Best-effort + key-gated (never breaks the caller's mutation)
# --------------------------------------------------------------------------- #
async def test_email_client_keyless_degrade_no_send_no_crash(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cur = _FakeCursor(client_row={"name": "Atlas", "contact_email": "hi@atlas.com"})
    _patch(monkeypatch, cur)
    monkeypatch.setattr(
        "app.services.notifications.email_sender_from_settings", lambda _s: None
    )
    await email_client("cl-1", "S", "<p>h</p>")  # no injected sender, no provider -> skipped


async def test_email_client_swallows_a_raising_sender(monkeypatch: pytest.MonkeyPatch) -> None:
    cur = _FakeCursor(client_row={"name": "Atlas", "contact_email": "hi@atlas.com"})
    _patch(monkeypatch, cur)

    class _BoomSender:
        def send(self, *, to: str, subject: str, html: str, text: str | None = None) -> str:
            raise RuntimeError("smtp down")

    # A raising provider must be swallowed - the mutation that fired the email survives.
    await email_client("cl-1", "S", "<p>h</p>", email_sender=_BoomSender())


async def test_email_client_never_raises_when_pool_booms(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _boom() -> Any:
        raise RuntimeError("no privileged pool")

    monkeypatch.setattr("app.services.notifications.privileged_connection", _boom)
    await email_client("cl-1", "S", "<p>h</p>", email_sender=FakeEmailSender())  # no raise


# --------------------------------------------------------------------------- #
# Sync wrapper (Celery worker context)
# --------------------------------------------------------------------------- #
def test_email_client_sync_drives_send(monkeypatch: pytest.MonkeyPatch) -> None:
    cur = _FakeCursor(client_row={"name": "Atlas", "contact_email": "hi@atlas.com"})
    _patch(monkeypatch, cur)
    sender = FakeEmailSender()
    monkeypatch.setattr(
        "app.services.notifications.email_sender_from_settings", lambda _s: sender
    )
    email_client_sync("cl-1", "Report ready", "<p>hi</p>", "hi")
    assert len(sender.sent) == 1
    assert sender.sent[0].to == "hi@atlas.com"


def test_email_client_sync_never_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    def _boom() -> Any:
        raise RuntimeError("no privileged pool")

    monkeypatch.setattr("app.services.notifications.privileged_connection", _boom)
    email_client_sync("cl-1", "S", "<p>h</p>")  # no raise
