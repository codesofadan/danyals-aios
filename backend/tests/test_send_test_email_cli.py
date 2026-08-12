"""Unit tests for the ``python -m app.cli.send_test_email`` operator entry point.

Proves the CLI renders the REAL template and reports OK on a successful send, DEGRADED
(exit 0) when no provider is configured, and DEGRADED (exit 1) when a configured send
fails - all with NO real network (the sender/factory is faked).
"""

from __future__ import annotations

from typing import Any

import pytest

from app.cli.send_test_email import main
from integrations.resend import FakeEmailSender

pytestmark = pytest.mark.unit

_FACTORY = "app.cli.send_test_email.email_sender_from_settings"


def test_cli_ok_sends_and_reports(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    sender = FakeEmailSender()
    monkeypatch.setattr(_FACTORY, lambda _s: sender)
    rc = main(["--to", "you@example.com", "--kind", "admin_to_client"])
    assert rc == 0
    assert len(sender.sent) == 1
    assert sender.sent[0].to == "you@example.com"
    assert sender.sent[0].subject  # a rendered subject
    out = capsys.readouterr().out
    assert out.startswith("OK:") and "admin_to_client" in out


def test_cli_degrades_when_no_provider(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(_FACTORY, lambda _s: None)
    rc = main(["--to", "you@example.com"])
    assert rc == 0  # an intentionally-unconfigured host is not a failure
    assert "DEGRADED" in capsys.readouterr().out


def test_cli_send_failure_exits_nonzero(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    class _Boom:
        provider = "smtp"

        def send(self, *, to: str, subject: str, html: str, text: str | None = None) -> str:
            raise RuntimeError("connection refused")

    monkeypatch.setattr(_FACTORY, lambda _s: _Boom())
    rc = main(["--to", "you@example.com", "--kind", "team_to_admin"])
    assert rc == 1
    err = capsys.readouterr().err
    assert "DEGRADED" in err and "smtp" in err


def test_cli_rejects_unknown_kind() -> None:
    with pytest.raises(SystemExit):  # argparse choices guard
        main(["--to", "you@example.com", "--kind", "bogus"])


def test_cli_requires_to() -> None:
    with pytest.raises(SystemExit):
        main([])


def test_cli_all_kinds_render_and_send(monkeypatch: pytest.MonkeyPatch) -> None:
    sender = FakeEmailSender()
    monkeypatch.setattr(_FACTORY, lambda _s: sender)
    for kind in ("admin_to_team", "team_to_admin", "admin_to_client", "client_to_admin"):
        assert main(["--to", "op@x.com", "--kind", kind]) == 0
    assert len(sender.sent) == 4
    assert all(s.html and s.text and s.subject for s in sender.sent)


def test_cli_passes_link_into_template(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    class _Capture:
        provider = "smtp"

        def send(self, *, to: str, subject: str, html: str, text: str | None = None) -> str:
            captured["html"] = html
            return "id-1"

    monkeypatch.setattr(_FACTORY, lambda _s: _Capture())
    main(["--to", "op@x.com", "--kind", "admin_to_client", "--link", "https://app.qanry.com/x"])
    assert "https://app.qanry.com/x" in captured["html"]
