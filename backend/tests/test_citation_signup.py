"""Account-creation + email-verify citation flow (7B-5) - offline tests.

No real browser and no real IMAP server: a fake ``playwright.sync_api`` module is
injected (as in ``test_citation_bot_stealth``) and a FAKE mailbox returns a canned
confirmation email. Proves:
  * ``extract_verification`` pulls BOTH the confirmation link and the numeric code
    from a multipart (text + html) email;
  * ``alias_for`` is unique + deterministic per (directory, client);
  * ``imap_mailbox_from_settings`` returns None when unconfigured;
  * the signup runner does signup -> waits -> clicks the verify link -> proceeds to
    the add-business submit (status 'submitted'); a code-kind spec types the code;
  * a mailbox timeout yields 'blocked' (never a crash), and a link-less email 'failed';
  * ``submitter_for`` routes ``bot:signup`` to the signup engine.
"""

from __future__ import annotations

import sys
import types
from datetime import UTC, datetime
from email.message import EmailMessage
from typing import Any

import pytest

from app.config import Settings
from app.modules.citations.service import submitter_for
from integrations.citation_signup import (
    SignupCitationSubmitter,
    SignupSpec,
    citation_signup_bot_from_settings,
)
from integrations.citation_submitters import CitationJob
from integrations.imap_mailbox import (
    ImapMailbox,
    VerifyInfo,
    alias_for,
    extract_verification,
    imap_mailbox_from_settings,
)

pytestmark = pytest.mark.unit


# --------------------------------------------------------------------------- #
# Canned confirmation email
# --------------------------------------------------------------------------- #
def _canned_email(*, to: str = "testdir-abc@mail.example") -> EmailMessage:
    msg = EmailMessage()
    msg["To"] = to
    msg["Subject"] = "Confirm your account"
    msg["Date"] = "Tue, 19 Aug 2026 10:00:00 +0000"
    msg.set_content("Welcome! Your verification code is 483920. Or confirm via the link.")
    msg.add_alternative(
        "<html><body><p>Your verification code is <b>483920</b>.</p>"
        "<p><a href=\"https://dir.example/confirm?token=abc123&amp;u=9\">Confirm your account</a></p>"
        "</body></html>",
        subtype="html",
    )
    return msg


def _link_only_email() -> EmailMessage:
    msg = EmailMessage()
    msg["To"] = "testdir-abc@mail.example"
    msg["Subject"] = "Activate"
    msg.set_content("Click https://dir.example/activate/xyz to finish.")
    return msg


def _plain_no_verify_email() -> EmailMessage:
    msg = EmailMessage()
    msg["To"] = "testdir-abc@mail.example"
    msg["Subject"] = "Hello"
    msg.set_content("Thanks for reading our newsletter, visit https://dir.example/home for more.")
    return msg


# --------------------------------------------------------------------------- #
# extract_verification
# --------------------------------------------------------------------------- #
def test_extract_verification_pulls_link_and_code() -> None:
    info = extract_verification(_canned_email())
    assert info.link == "https://dir.example/confirm?token=abc123&u=9"  # &amp; decoded, hint-matched
    assert info.code == "483920"


def test_extract_verification_link_only() -> None:
    info = extract_verification(_link_only_email())
    assert info.link == "https://dir.example/activate/xyz"
    assert info.code == ""


def test_extract_verification_no_verify_link() -> None:
    # A non-verify URL (no verify/confirm/activate hint) is NOT treated as a link.
    info = extract_verification(_plain_no_verify_email())
    assert info.link == ""
    assert info.code == ""


# --------------------------------------------------------------------------- #
# alias_for
# --------------------------------------------------------------------------- #
def test_alias_for_deterministic_and_unique() -> None:
    a1 = alias_for(directory="MerchantCircle", client_id="client-1", domain="mail.qanry.com")
    a1_again = alias_for(directory="MerchantCircle", client_id="client-1", domain="mail.qanry.com")
    assert a1 == a1_again  # deterministic
    assert a1.endswith("@mail.qanry.com")
    assert a1.split("@")[0].islower()  # slugified local part

    # different client -> different alias
    a2 = alias_for(directory="MerchantCircle", client_id="client-2", domain="mail.qanry.com")
    assert a2 != a1
    # different directory -> different alias
    a3 = alias_for(directory="Brownbook", client_id="client-1", domain="mail.qanry.com")
    assert a3 != a1
    assert a3.startswith("brownbook-")


def test_alias_for_slugifies_messy_directory_name() -> None:
    alias = alias_for(directory="Chamber of Commerce!", client_id="c", domain="d.com")
    local = alias.split("@")[0]
    assert local.startswith("chamber-of-commerce-")
    assert " " not in local and "!" not in local


# --------------------------------------------------------------------------- #
# imap_mailbox_from_settings
# --------------------------------------------------------------------------- #
def _settings(**overrides: Any) -> Settings:
    return Settings(_env_file=None, app_env="dev", **overrides)


def test_imap_mailbox_from_settings_none_when_unconfigured() -> None:
    assert imap_mailbox_from_settings(_settings()) is None  # no host/user/password
    # host alone is not enough
    assert imap_mailbox_from_settings(_settings(citation_imap_host="imap.example")) is None


def test_imap_mailbox_from_settings_built_when_configured() -> None:
    mailbox = imap_mailbox_from_settings(
        _settings(
            citation_imap_host="imap.example",
            citation_imap_user="catchall@mail.example",
            citation_imap_password="s3cret",
        )
    )
    assert isinstance(mailbox, ImapMailbox)


def test_signup_bot_from_settings_none_without_mailbox_or_domain() -> None:
    # No mailbox -> None even if a domain is set.
    assert (
        citation_signup_bot_from_settings(
            _settings(citation_mail_domain="mail.example"), captcha_solver=None, mailbox=None
        )
        is None
    )


# --------------------------------------------------------------------------- #
# Fake mailbox + fake Playwright for the runner
# --------------------------------------------------------------------------- #
class _FakeMailbox:
    """Returns a preset message (or None) and records the alias it was asked for."""

    def __init__(self, message: EmailMessage | None) -> None:
        self._message = message
        self.asked_alias: str | None = None

    def wait_for_message(self, *, to_alias: str, since: datetime, **_: Any) -> EmailMessage | None:
        self.asked_alias = to_alias
        return self._message


class _Page:
    def __init__(self, content: str = "Thank you, your listing was received") -> None:
        self.goto_urls: list[str] = []
        self.typed: list[tuple[str, str]] = []
        self.clicked: list[str] = []
        self._content = content

    def goto(self, url: str, **_: object) -> None:
        self.goto_urls.append(url)

    def click(self, selector: str, **_: object) -> None:
        self.clicked.append(selector)

    def type(self, selector: str, value: str, **_: object) -> None:
        self.typed.append((selector, value))

    def fill(self, selector: str, value: str, **_: object) -> None:
        self.typed.append((selector, value))

    def wait_for_timeout(self, ms: int) -> None: ...
    def screenshot(self, **_: object) -> None: ...
    def content(self) -> str:
        return self._content

    def locator(self, _: str) -> object:  # pragma: no cover
        raise AssertionError("text= success path should be used")


class _Context:
    def __init__(self, page: _Page) -> None:
        self._page = page

    def add_init_script(self, js: str) -> None: ...
    def new_page(self) -> _Page:
        return self._page

    def close(self) -> None: ...


class _Browser:
    def __init__(self, ctx: _Context) -> None:
        self._ctx = ctx

    def new_context(self, **_: object) -> _Context:
        return self._ctx

    def close(self) -> None: ...


class _Chromium:
    def __init__(self, browser: _Browser) -> None:
        self._browser = browser

    def launch(self, **_: object) -> _Browser:
        return self._browser


class _PW:
    def __init__(self, chromium: _Chromium) -> None:
        self.chromium = chromium

    def __enter__(self) -> _PW:
        return self

    def __exit__(self, *_: object) -> None: ...


@pytest.fixture
def fake_pw(monkeypatch: pytest.MonkeyPatch) -> _Page:
    page = _Page()
    mod = types.ModuleType("playwright.sync_api")
    mod.sync_playwright = lambda: _PW(_Chromium(_Browser(_Context(page))))  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "playwright", types.ModuleType("playwright"))
    monkeypatch.setitem(sys.modules, "playwright.sync_api", mod)
    return page


def _link_spec() -> SignupSpec:
    from integrations.citation_bot import FormField, FormSpec

    return SignupSpec(
        directory_name="TestDir",
        signup_url="https://dir.example/signup",
        name_selector="#name",
        email_selector="#email",
        password_selector="#password",
        submit_selector="#signup-go",
        verify_kind="link",
        add_business=FormSpec(
            directory_name="TestDir",
            url="https://dir.example/business/add",
            fields=(FormField("#biz", "business_name"),),
            submit_selector="#add-go",
            success_indicator="text=your listing was received",
        ),
    )


def _code_spec() -> SignupSpec:
    from integrations.citation_bot import FormField, FormSpec

    return SignupSpec(
        directory_name="TestDir",
        signup_url="https://dir.example/signup",
        email_selector="#email",
        password_selector="#password",
        submit_selector="#signup-go",
        verify_kind="code",
        code_field_selector="#code",
        code_submit_selector="#code-go",
        add_business=FormSpec(
            directory_name="TestDir",
            url="https://dir.example/business/add",
            fields=(FormField("#biz", "business_name"),),
            submit_selector="#add-go",
            success_indicator="text=your listing was received",
        ),
    )


def _job() -> CitationJob:
    return CitationJob(
        directory_name="TestDir",
        directory_url="https://dir.example",
        market="global",
        submit_method="bot:signup",
        business_name="Acme Co",
        address_line1="1 St",
        address_line2="",
        city="Lahore",
        region="Punjab",
        postal_code="54000",
        phone="+920000000",
        website_url="https://acme.example",
        client_id="client-1",
    )


def _bot(mailbox: _FakeMailbox, spec: SignupSpec) -> SignupCitationSubmitter:
    return SignupCitationSubmitter(
        mailbox=mailbox,  # type: ignore[arg-type]  # duck-typed fake
        mail_domain="mail.example",
        signup_specs={"TestDir": spec},
        rng_seed=7,
    )


# --------------------------------------------------------------------------- #
# The signup runner
# --------------------------------------------------------------------------- #
def test_signup_link_flow_submits(fake_pw: _Page) -> None:
    mailbox = _FakeMailbox(_canned_email())
    result = _bot(mailbox, _link_spec()).submit(_job())

    assert result.status == "submitted"
    # the alias the mailbox was polled for is the unique per-(dir,client) address
    assert mailbox.asked_alias == alias_for(
        directory="TestDir", client_id="client-1", domain="mail.example"
    )
    # signup email field got the alias, not a shared address
    assert ("#email", mailbox.asked_alias) in fake_pw.typed
    # the confirmation LINK was visited, then the add-business form navigated to
    assert "https://dir.example/confirm?token=abc123&u=9" in fake_pw.goto_urls
    assert "https://dir.example/business/add" in fake_pw.goto_urls
    # and the add-business form was actually submitted
    assert "#add-go" in fake_pw.clicked


def test_signup_code_flow_types_code(fake_pw: _Page) -> None:
    mailbox = _FakeMailbox(_canned_email())
    result = _bot(mailbox, _code_spec()).submit(_job())

    assert result.status == "submitted"
    assert ("#code", "483920") in fake_pw.typed  # the emailed code was entered
    assert "#code-go" in fake_pw.clicked


def test_signup_mailbox_timeout_is_blocked_not_crash(fake_pw: _Page) -> None:
    mailbox = _FakeMailbox(None)  # no confirmation email arrives
    result = _bot(mailbox, _link_spec()).submit(_job())

    assert result.status == "blocked"
    assert "pending" in result.error
    # we never proceeded to the add-business step
    assert "https://dir.example/business/add" not in fake_pw.goto_urls


def test_signup_link_missing_in_email_is_failed(fake_pw: _Page) -> None:
    mailbox = _FakeMailbox(_plain_no_verify_email())  # email has no verify link
    result = _bot(mailbox, _link_spec()).submit(_job())

    assert result.status == "failed"
    assert "link" in result.error


def test_signup_no_mailbox_is_blocked(fake_pw: _Page) -> None:
    # submit() short-circuits on the None mailbox BEFORE opening a browser; the fake
    # Playwright is only needed so the base ctor's import check passes at construction.
    bot = SignupCitationSubmitter(
        mailbox=None, mail_domain="mail.example", signup_specs={"TestDir": _link_spec()}, rng_seed=1
    )
    result = bot.submit(_job())
    assert result.status == "blocked"
    assert "mailbox" in result.error


def test_signup_unknown_directory_is_failed(fake_pw: _Page) -> None:
    mailbox = _FakeMailbox(_canned_email())
    bot = _bot(mailbox, _link_spec())
    job = CitationJob(
        directory_name="Unknown",
        directory_url="",
        market="global",
        submit_method="bot:signup",
        business_name="Acme",
        address_line1="",
        address_line2="",
        city="",
        region="",
        postal_code="",
        phone="",
        website_url="",
        client_id="client-1",
    )
    assert bot.submit(job).status == "failed"


# --------------------------------------------------------------------------- #
# Worker routing
# --------------------------------------------------------------------------- #
def test_submitter_for_routes_bot_signup() -> None:
    signup = object()
    plain = object()
    sub, reason = submitter_for(
        "bot:signup", api_submitters={}, bot=plain, signup_bot=signup  # type: ignore[arg-type]
    )
    assert sub is signup and reason == ""

    # bot:signup with no signup engine -> honest blocked reason, NOT the plain bot
    sub2, reason2 = submitter_for("bot:signup", api_submitters={}, bot=plain, signup_bot=None)  # type: ignore[arg-type]
    assert sub2 is None and "signup bot not configured" in reason2

    # a plain bot:playwright still routes to the no-signup engine, unchanged
    sub3, _ = submitter_for(
        "bot:playwright", api_submitters={}, bot=plain, signup_bot=signup  # type: ignore[arg-type]
    )
    assert sub3 is plain


def test_verify_info_defaults_empty() -> None:
    info = VerifyInfo()
    assert info.link == "" and info.code == ""


# --------------------------------------------------------------------------- #
# ImapMailbox.wait_for_message against a FAKE imaplib (no network)
# --------------------------------------------------------------------------- #
class _FakeIMAP:
    def __init__(self, raw: bytes | None, *, boom: bool = False) -> None:
        if boom:
            raise OSError("connection refused")
        self._raw = raw

    def login(self, user: str, password: str) -> None: ...
    def select(self, mailbox: str) -> tuple[str, list[bytes]]:
        return ("OK", [b"1"])

    def search(self, charset: object, *criteria: str) -> tuple[str, list[bytes]]:
        return ("OK", [b"1"] if self._raw else [b""])

    def fetch(self, mid: bytes, spec: str) -> tuple[str, list[object]]:
        assert self._raw is not None
        return ("OK", [(b"1 (RFC822 {n}", self._raw)])

    def logout(self) -> None: ...


def _mailbox() -> ImapMailbox:
    return ImapMailbox(host="imap.example", port=993, user="catchall@mail.example", password="pw")


def test_wait_for_message_matches_recipient(monkeypatch: pytest.MonkeyPatch) -> None:
    import imaplib

    alias = "testdir-abc@mail.example"
    raw = _canned_email(to=alias).as_bytes()
    monkeypatch.setattr(imaplib, "IMAP4_SSL", lambda host, port: _FakeIMAP(raw))
    since = datetime(2026, 8, 19, 9, 0, tzinfo=UTC)  # before the email's 10:00 Date
    msg = _mailbox().wait_for_message(to_alias=alias, since=since, timeout_s=1)
    assert msg is not None
    assert extract_verification(msg).code == "483920"


def test_wait_for_message_ignores_other_recipient(monkeypatch: pytest.MonkeyPatch) -> None:
    import imaplib

    raw = _canned_email(to="someone-else@mail.example").as_bytes()
    monkeypatch.setattr(imaplib, "IMAP4_SSL", lambda host, port: _FakeIMAP(raw))
    since = datetime(2026, 8, 19, 9, 0, tzinfo=UTC)
    msg = _mailbox().wait_for_message(to_alias="testdir-abc@mail.example", since=since, timeout_s=0)
    assert msg is None  # alias not in the recipients -> no match


def test_wait_for_message_imap_error_degrades_to_none(monkeypatch: pytest.MonkeyPatch) -> None:
    import imaplib

    def _boom(host: str, port: int) -> _FakeIMAP:
        return _FakeIMAP(None, boom=True)

    monkeypatch.setattr(imaplib, "IMAP4_SSL", _boom)
    since = datetime(2026, 8, 19, 9, 0, tzinfo=UTC)
    # An IMAP connect failure must NEVER raise out - it degrades to None.
    assert _mailbox().wait_for_message(to_alias="x@mail.example", since=since, timeout_s=0) is None
