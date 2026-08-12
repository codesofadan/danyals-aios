"""Unit tests for the SMTP email seam (all-way comms) and the provider-selector factory.

Proves, with NO real network (``smtplib`` is faked):
* message construction - From/To/Subject + a multipart/alternative plain-text primary
  and an HTML alternative;
* the STARTTLS path on :587 (plain connect -> ``starttls`` -> ``login`` -> send) and the
  implicit-SSL path on :465 (``SMTP_SSL``, NO ``starttls``);
* ``login`` fires only when a user + password are configured (an open relay skips it);
* the credential is never part of the transport error message (host:port only);
* a transport failure raises ``ProviderCallError`` (message already built) and, at the
  delivery layer, is SWALLOWED (an SMTP outage never breaks the mutation);
* the factory dispatches on ``EMAIL_PROVIDER`` and DEGRADES to ``None`` when unconfigured
  (blank host, or provider=none), and the real client raises when built without host/from.
"""

from __future__ import annotations

import smtplib
from typing import Any

import pytest

from app.config import Settings
from app.services.notifications import email_admin
from integrations.errors import ProviderCallError, ProviderNotConfiguredError
from integrations.resend import email_sender_from_settings
from integrations.smtp_email import SmtpEmailSender

pytestmark = pytest.mark.unit


# --------------------------------------------------------------------------- #
# Fake smtplib (captures the connection kind, TLS upgrade, auth, and messages)
# --------------------------------------------------------------------------- #
class _FakeSMTP:
    """Stands in for ``smtplib.SMTP`` / ``SMTP_SSL`` - records every interaction."""

    ssl = False  # overridden on the SSL subclass

    def __init__(self, host: str, port: int, timeout: float | None = None) -> None:
        self.host = host
        self.port = port
        self.timeout = timeout
        self.starttls_called = False
        self.login_args: tuple[str, str] | None = None
        self.sent: list[Any] = []
        self.raise_on_send = False

    def __enter__(self) -> _FakeSMTP:
        return self

    def __exit__(self, *exc: object) -> bool:
        return False

    def starttls(self) -> None:
        self.starttls_called = True

    def login(self, user: str, password: str) -> None:
        self.login_args = (user, password)

    def send_message(self, msg: Any) -> None:
        if self.raise_on_send:
            raise smtplib.SMTPRecipientsRefused({})
        self.sent.append(msg)


class _FakeSMTPSSL(_FakeSMTP):
    ssl = True


def _install_fakes(
    monkeypatch: pytest.MonkeyPatch, *, raise_on_send: bool = False
) -> dict[str, list[_FakeSMTP]]:
    """Patch both smtplib constructors; return a registry of built instances."""
    built: dict[str, list[_FakeSMTP]] = {"plain": [], "ssl": []}

    def _mk(kind: str, cls: type[_FakeSMTP]) -> Any:
        def _factory(host: str, port: int, timeout: float | None = None) -> _FakeSMTP:
            inst = cls(host, port, timeout=timeout)
            inst.raise_on_send = raise_on_send
            built[kind].append(inst)
            return inst

        return _factory

    monkeypatch.setattr(smtplib, "SMTP", _mk("plain", _FakeSMTP))
    monkeypatch.setattr(smtplib, "SMTP_SSL", _mk("ssl", _FakeSMTPSSL))
    return built


# --------------------------------------------------------------------------- #
# Message construction + STARTTLS path (:587)
# --------------------------------------------------------------------------- #
def test_starttls_path_builds_message_and_authenticates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    built = _install_fakes(monkeypatch)
    sender = SmtpEmailSender(
        host="smtp.gmail.com", port=587, user="ops@x.com", password="app-pw",
        from_email="AIOS <ops@x.com>",
    )
    msg_id = sender.send(
        to="alex@team.com", subject="New task", html="<h1>Hi</h1>", text="Hi Alex",
    )

    assert built["plain"] and not built["ssl"]  # STARTTLS path, not SSL
    smtp = built["plain"][0]
    assert smtp.starttls_called is True  # TLS upgrade happened before auth
    assert smtp.login_args == ("ops@x.com", "app-pw")  # authenticated
    assert len(smtp.sent) == 1
    msg = smtp.sent[0]
    assert msg["From"] == "AIOS <ops@x.com>"
    assert msg["To"] == "alex@team.com"
    assert msg["Subject"] == "New task"
    assert msg.get_content_type() == "multipart/alternative"
    plain = msg.get_body(preferencelist=("plain",))
    html = msg.get_body(preferencelist=("html",))
    assert plain is not None and "Hi Alex" in plain.get_content()
    assert html is not None and "<h1>Hi</h1>" in html.get_content()
    assert msg_id  # a Message-ID was returned


def test_ssl_path_used_on_465_without_starttls(monkeypatch: pytest.MonkeyPatch) -> None:
    built = _install_fakes(monkeypatch)
    sender = SmtpEmailSender(
        host="smtp.gmail.com", port=465, user="ops@x.com", password="pw",
        from_email="ops@x.com",
    )
    sender.send(to="a@b.com", subject="S", html="<p>h</p>", text="h")
    assert built["ssl"] and not built["plain"]  # implicit-SSL path
    assert built["ssl"][0].starttls_called is False  # SSL never calls starttls


def test_no_credentials_skips_login(monkeypatch: pytest.MonkeyPatch) -> None:
    built = _install_fakes(monkeypatch)
    sender = SmtpEmailSender(host="relay.internal", port=587, from_email="ops@x.com")
    sender.send(to="a@b.com", subject="S", html="<p>h</p>")
    assert built["plain"][0].login_args is None  # open relay -> no login


def test_text_fallback_derived_from_html(monkeypatch: pytest.MonkeyPatch) -> None:
    built = _install_fakes(monkeypatch)
    sender = SmtpEmailSender(host="h", port=587, from_email="ops@x.com")
    sender.send(to="a@b.com", subject="S", html="<h1>Report</h1><p>ready</p>")  # no text
    plain = built["plain"][0].sent[0].get_body(preferencelist=("plain",))
    assert plain is not None
    derived = plain.get_content()
    assert "Report" in derived and "ready" in derived and "<" not in derived


# --------------------------------------------------------------------------- #
# Failure handling (never leaks the secret; delivery layer swallows it)
# --------------------------------------------------------------------------- #
def test_send_failure_raises_provider_call_error_without_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fakes(monkeypatch, raise_on_send=True)
    sender = SmtpEmailSender(
        host="smtp.gmail.com", port=587, user="ops@x.com", password="super-secret-pw",
        from_email="ops@x.com",
    )
    with pytest.raises(ProviderCallError) as ei:
        sender.send(to="a@b.com", subject="S", html="<p>h</p>", text="h")
    assert "super-secret-pw" not in str(ei.value)  # the password never appears
    assert "smtp.gmail.com:587" in str(ei.value)  # only host:port


async def test_delivery_layer_swallows_smtp_send_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A raising SMTP sender injected into the best-effort email_admin must NOT propagate.
    _install_fakes(monkeypatch, raise_on_send=True)
    sender = SmtpEmailSender(host="h", port=587, user="u", password="p", from_email="ops@x.com")
    await email_admin("Subject", "<p>h</p>", "h", email_sender=sender)  # no raise


# --------------------------------------------------------------------------- #
# Constructor guard + factory dispatch / degrade
# --------------------------------------------------------------------------- #
def test_constructor_requires_host_and_from() -> None:
    with pytest.raises(ProviderNotConfiguredError):
        SmtpEmailSender(host="", from_email="ops@x.com")
    with pytest.raises(ProviderNotConfiguredError):
        SmtpEmailSender(host="h", from_email="")


def _settings(**over: Any) -> Settings:
    # _env_file=None -> deterministic (never reads a stray local .env).
    return Settings(_env_file=None, **over)  # type: ignore[call-arg]


def test_factory_builds_smtp_sender_when_selected() -> None:
    sender = email_sender_from_settings(
        _settings(
            email_provider="smtp", smtp_host="smtp.gmail.com", smtp_user="ops@x.com",
            smtp_password="pw", smtp_from="AIOS <ops@x.com>",
        )
    )
    assert isinstance(sender, SmtpEmailSender)
    assert sender.provider == "smtp"


def test_factory_from_falls_back_to_user_when_blank() -> None:
    sender = email_sender_from_settings(
        _settings(email_provider="smtp", smtp_host="h", smtp_user="ops@x.com")
    )
    assert isinstance(sender, SmtpEmailSender)
    assert sender._from == "ops@x.com"  # SMTP_FROM blank -> SMTP_USER


def test_factory_degrades_when_smtp_host_missing() -> None:
    assert email_sender_from_settings(_settings(email_provider="smtp", smtp_host="")) is None


def test_factory_none_provider_disables_email() -> None:
    # Even with a resend key present, EMAIL_PROVIDER=none returns no sender.
    sender = email_sender_from_settings(
        _settings(email_provider="none", resend_api_key="re_live_key")
    )
    assert sender is None


def test_factory_defaults_to_resend() -> None:
    from integrations.resend import ResendClient

    sender = email_sender_from_settings(
        _settings(resend_api_key="re_live_key", resend_from_email="AIOS <n@x.com>")
    )
    assert isinstance(sender, ResendClient)
