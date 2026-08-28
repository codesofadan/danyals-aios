"""Unit tests for the web2 house-account signup + verify + provision flow (7B-5).

Every test runs fully offline with fakes -- no live signup, no real IMAP, no vault:
  * the API providers (Telegra.ph anonymous token, Write.as/WriteFreely signup) over a
    recorder ``HttpJson``;
  * the spec-driven browser provider over a fake Playwright ``page`` + a fake mailbox
    that yields a real ``EmailMessage`` (so the REAL ``extract_verification`` parses it);
  * ``provision_account`` sealing the exact ``web2:<platform>`` vault shape, its
    idempotent skip, and its "only a created result is sealed" guarantee.
"""

from __future__ import annotations

from datetime import UTC, datetime
from email.message import EmailMessage
from typing import Any

import pytest

from integrations.errors import ProviderCallError
from integrations.web2_credentials import vault_provider_for
from integrations.web2_publishers import (
    PLATFORM_LIVEJOURNAL,
    PLATFORM_TELEGRAPH,
    PLATFORM_WRITEAS,
)
from integrations.web2_signup import (
    LIVEJOURNAL_SIGNUP_SPEC,
    STATUS_BLOCKED,
    STATUS_CREATED,
    STATUS_EXISTS,
    STATUS_FAILED,
    BrowserSignupProvider,
    FakeSignupProvider,
    TelegraphAnonymousProvider,
    Web2SignupResult,
    WriteFreelySignupProvider,
    api_signup_provider_for,
    generate_password,
    house_credentials_block,
    make_context,
    provision_account,
)

pytestmark = pytest.mark.unit

_DOMAIN = "mail.qanry.com"
_CLIENT = "client-uuid-1"


# --------------------------------------------------------------------------- #
# Fakes.
# --------------------------------------------------------------------------- #
class _FakeHttp:
    """Recorder ``HttpJson``: returns a canned dict per URL (or raises a canned exc)."""

    def __init__(self, responses: dict[str, Any]) -> None:
        self._responses = responses
        self.calls: list[dict[str, Any]] = []

    def __call__(
        self,
        url: str,
        *,
        method: str = "POST",
        data: Any = None,
        json_body: Any = None,
        headers: Any = None,
        timeout: float = 30.0,
    ) -> dict[str, Any]:
        self.calls.append({"url": url, "method": method, "data": data, "json_body": json_body})
        resp = self._responses[url]
        if isinstance(resp, Exception):
            raise resp
        assert isinstance(resp, dict)
        return resp


class _FakeMailbox:
    """Returns a canned ``EmailMessage`` (or ``None``) and records the alias polled."""

    def __init__(self, message: EmailMessage | None) -> None:
        self._message = message
        self.calls: list[str] = []

    def wait_for_message(self, *, to_alias: str, since: datetime, **_: Any) -> EmailMessage | None:
        self.calls.append(to_alias)
        return self._message


class _FakePage:
    """Minimal Playwright ``page`` recorder. ``content`` drives the text= indicators."""

    def __init__(self, content: str = "please confirm ... account validated") -> None:
        self._content = content
        self.gotos: list[str] = []
        self.filled: list[tuple[str, str]] = []
        self.clicked: list[str] = []

    def goto(self, url: str, **_: Any) -> None:
        self.gotos.append(url)

    def fill(self, selector: str, value: str, **_: Any) -> None:
        self.filled.append((selector, value))

    def click(self, selector: str, **_: Any) -> None:
        self.clicked.append(selector)

    def wait_for_timeout(self, _ms: int) -> None:
        return None

    def content(self) -> str:
        return self._content


class _FakeVault:
    """In-memory vault seam: ``find``/``add`` over a ``{(provider,label): secret}`` map."""

    def __init__(self, existing: dict[tuple[str, str], str] | None = None) -> None:
        self.rows: dict[tuple[str, str], str] = dict(existing or {})
        self.added: list[dict[str, str]] = []

    def find(self, *, provider: str, label: str) -> str | None:
        return self.rows.get((provider, label))

    def add(self, *, provider: str, label: str, secret: str, kind: str) -> None:
        self.added.append({"provider": provider, "label": label, "secret": secret, "kind": kind})
        self.rows[(provider, label)] = secret


def _confirm_email(link: str = "https://www.livejournal.com/confirm?token=abc123") -> EmailMessage:
    msg = EmailMessage()
    msg["To"] = "lj-alias@mail.qanry.com"
    msg["Subject"] = "Confirm your LiveJournal account"
    msg.set_content(f"Welcome! Please confirm your account: {link}")
    return msg


def _fixed_clock() -> datetime:
    return datetime(2026, 8, 19, 10, 0, tzinfo=UTC)


# --------------------------------------------------------------------------- #
# Password + context helpers.
# --------------------------------------------------------------------------- #
def test_generate_password_has_every_class() -> None:
    for _ in range(20):
        pw = generate_password()
        assert len(pw) >= 20
        assert any(c.islower() for c in pw)
        assert any(c.isupper() for c in pw)
        assert any(c.isdigit() for c in pw)
        assert any(c in "!@#$%^&*-_=+" for c in pw)


def test_make_context_alias_is_deterministic_per_platform_and_client() -> None:
    a = make_context(platform=PLATFORM_WRITEAS, client_id=_CLIENT, catchall_domain=_DOMAIN)
    b = make_context(platform=PLATFORM_WRITEAS, client_id=_CLIENT, catchall_domain=_DOMAIN)
    assert a.alias_email == b.alias_email  # a retry reuses the same account
    assert a.alias_email.endswith(f"@{_DOMAIN}")
    assert a.alias_email.startswith("write")  # slug of the platform name
    # A different platform (or client) yields a different alias local part.
    other = make_context(platform=PLATFORM_TELEGRAPH, client_id=_CLIENT, catchall_domain=_DOMAIN)
    assert other.alias_email != a.alias_email
    assert a.username and "@" not in a.username


def test_a_per_client_signup_refuses_the_generated_identity() -> None:
    """R2-08. The generated alias is ``{platform}-{sha1(client_id)[:10]}@{one domain}``,
    which hands a platform three joinable keys - a shared prefix per platform, a shared
    suffix per client, one registrant domain across the whole base. Refusing (not
    warning) is the point: a warning would be ignored and the footprint would ship."""
    with pytest.raises(ValueError, match="footprint"):
        make_context(
            platform=PLATFORM_WRITEAS, client_id=_CLIENT, catchall_domain=_DOMAIN,
            ownership="per_client",
        )


def test_a_per_client_signup_uses_the_supplied_brand_identity() -> None:
    ctx = make_context(
        platform=PLATFORM_WRITEAS, client_id=_CLIENT, catchall_domain=_DOMAIN,
        ownership="per_client", handle="acmeroofing", email="web@acmeroofing.co.uk",
    )
    assert ctx.username == "acmeroofing"
    assert ctx.alias_email == "web@acmeroofing.co.uk"
    assert _DOMAIN not in ctx.alias_email  # never the shared catch-all


# --------------------------------------------------------------------------- #
# Telegra.ph anonymous provider.
# --------------------------------------------------------------------------- #
def test_telegraph_provider_mints_access_token() -> None:
    http = _FakeHttp({TelegraphAnonymousProvider._ENDPOINT: {"ok": True, "result": {"access_token": "tg-tok"}}})
    ctx = make_context(platform=PLATFORM_TELEGRAPH, client_id=_CLIENT, catchall_domain=_DOMAIN, http=http)
    result = TelegraphAnonymousProvider().signup(ctx)
    assert result.status == STATUS_CREATED
    assert result.credentials == {"access_token": "tg-tok"}
    assert http.calls[0]["url"] == TelegraphAnonymousProvider._ENDPOINT


def test_telegraph_provider_degrades_on_not_ok_and_on_error() -> None:
    ctx_bad = make_context(
        platform=PLATFORM_TELEGRAPH,
        client_id=_CLIENT,
        catchall_domain=_DOMAIN,
        http=_FakeHttp({TelegraphAnonymousProvider._ENDPOINT: {"ok": False}}),
    )
    assert TelegraphAnonymousProvider().signup(ctx_bad).status == STATUS_FAILED
    ctx_err = make_context(
        platform=PLATFORM_TELEGRAPH,
        client_id=_CLIENT,
        catchall_domain=_DOMAIN,
        http=_FakeHttp({TelegraphAnonymousProvider._ENDPOINT: ProviderCallError("boom")}),
    )
    assert TelegraphAnonymousProvider().signup(ctx_err).status == STATUS_FAILED


# --------------------------------------------------------------------------- #
# Write.as / WriteFreely provider.
# --------------------------------------------------------------------------- #
def test_writefreely_provider_returns_token_and_alias() -> None:
    url = "https://write.as/api/auth/signup"
    http = _FakeHttp({url: {"code": 200, "data": {"access_token": "wf-tok"}}})
    ctx = make_context(platform=PLATFORM_WRITEAS, client_id=_CLIENT, catchall_domain=_DOMAIN, http=http)
    result = WriteFreelySignupProvider().signup(ctx)
    assert result.status == STATUS_CREATED
    assert result.credentials == {"token": "wf-tok", "alias": ctx.username}
    assert result.account_url == f"https://{ctx.username}.write.as"
    # The signup body carried the alias/pass/email as JSON.
    assert http.calls[0]["json_body"]["alias"] == ctx.username


def test_writefreely_provider_missing_token_fails() -> None:
    url = "https://write.as/api/auth/signup"
    http = _FakeHttp({url: {"code": 200, "data": {}}})
    ctx = make_context(platform=PLATFORM_WRITEAS, client_id=_CLIENT, catchall_domain=_DOMAIN, http=http)
    assert WriteFreelySignupProvider().signup(ctx).status == STATUS_FAILED


# --------------------------------------------------------------------------- #
# Browser provider (spec-driven, injected page + mailbox).
# --------------------------------------------------------------------------- #
def _browser_ctx(page: Any, mailbox: Any) -> Any:
    return make_context(
        platform=PLATFORM_LIVEJOURNAL,
        client_id=_CLIENT,
        catchall_domain=_DOMAIN,
        page=page,
        mailbox=mailbox,
    )


def test_browser_signup_happy_path_seals_username_password() -> None:
    page = _FakePage()
    mailbox = _FakeMailbox(_confirm_email())
    ctx = _browser_ctx(page, mailbox)
    result = BrowserSignupProvider(LIVEJOURNAL_SIGNUP_SPEC).signup(ctx)
    assert result.status == STATUS_CREATED
    assert result.credentials == {"username": ctx.username, "password": ctx.password}
    # It filled the form, submitted, and navigated to the verification link.
    assert page.clicked == [LIVEJOURNAL_SIGNUP_SPEC.submit_selector]
    assert any("confirm" in g for g in page.gotos)
    assert mailbox.calls == [ctx.alias_email]


def test_browser_signup_blocks_without_mailbox() -> None:
    ctx = make_context(
        platform=PLATFORM_LIVEJOURNAL, client_id=_CLIENT, catchall_domain=_DOMAIN, page=_FakePage()
    )
    assert BrowserSignupProvider(LIVEJOURNAL_SIGNUP_SPEC).signup(ctx).status == STATUS_BLOCKED


def test_browser_signup_blocks_when_no_verification_email() -> None:
    ctx = _browser_ctx(_FakePage(), _FakeMailbox(None))
    assert BrowserSignupProvider(LIVEJOURNAL_SIGNUP_SPEC).signup(ctx).status == STATUS_BLOCKED


def test_browser_signup_fails_when_form_not_accepted() -> None:
    page = _FakePage(content="error: username already taken")  # no success indicator
    ctx = _browser_ctx(page, _FakeMailbox(_confirm_email()))
    assert BrowserSignupProvider(LIVEJOURNAL_SIGNUP_SPEC).signup(ctx).status == STATUS_FAILED


# --------------------------------------------------------------------------- #
# Provisioning (vault wiring) + registry.
# --------------------------------------------------------------------------- #
def test_provision_seals_created_credential_in_web2_vault_shape() -> None:
    vault = _FakeVault()
    provider = FakeSignupProvider(platform=PLATFORM_TELEGRAPH, credentials={"access_token": "tg"})
    ctx = make_context(platform=PLATFORM_TELEGRAPH, client_id=_CLIENT, catchall_domain=_DOMAIN, http=None)
    result = provision_account(
        client_id=_CLIENT, platform=PLATFORM_TELEGRAPH, provider=provider, ctx=ctx,
        find=vault.find, add=vault.add,
    )
    assert result.status == STATUS_CREATED
    assert len(vault.added) == 1
    row = vault.added[0]
    assert row["provider"] == vault_provider_for(PLATFORM_TELEGRAPH) == "web2:Telegra.ph"
    assert row["label"] == _CLIENT
    assert row["kind"] == "client_access"
    assert row["secret"] == '{"access_token":"tg"}'


def test_provision_is_idempotent_when_row_exists() -> None:
    vault = _FakeVault({(vault_provider_for(PLATFORM_TELEGRAPH), _CLIENT): '{"access_token":"old"}'})
    provider = FakeSignupProvider(platform=PLATFORM_TELEGRAPH)
    ctx = make_context(platform=PLATFORM_TELEGRAPH, client_id=_CLIENT, catchall_domain=_DOMAIN, http=None)
    result = provision_account(
        client_id=_CLIENT, platform=PLATFORM_TELEGRAPH, provider=provider, ctx=ctx,
        find=vault.find, add=vault.add,
    )
    assert result.status == STATUS_EXISTS
    assert provider.calls == []  # no signup attempted
    assert vault.added == []  # nothing re-sealed


def test_provision_does_not_seal_a_blocked_or_failed_signup() -> None:
    vault = _FakeVault()
    provider = FakeSignupProvider(platform=PLATFORM_LIVEJOURNAL, status=STATUS_BLOCKED)
    ctx = make_context(platform=PLATFORM_LIVEJOURNAL, client_id=_CLIENT, catchall_domain=_DOMAIN, http=None)
    result = provision_account(
        client_id=_CLIENT, platform=PLATFORM_LIVEJOURNAL, provider=provider, ctx=ctx,
        find=vault.find, add=vault.add,
    )
    assert result.status == STATUS_BLOCKED
    assert vault.added == []


def test_api_signup_registry_maps_only_api_platforms() -> None:
    assert isinstance(api_signup_provider_for(PLATFORM_TELEGRAPH), TelegraphAnonymousProvider)
    assert isinstance(api_signup_provider_for(PLATFORM_WRITEAS), WriteFreelySignupProvider)
    assert api_signup_provider_for(PLATFORM_LIVEJOURNAL) is None  # browser/manual only


def test_house_credentials_block_folds_created_only() -> None:
    results = [
        Web2SignupResult(platform=PLATFORM_TELEGRAPH, status=STATUS_CREATED, credentials={"access_token": "t"}),
        Web2SignupResult(platform=PLATFORM_WRITEAS, status=STATUS_BLOCKED),
    ]
    block = house_credentials_block(results)
    assert block == {PLATFORM_TELEGRAPH: {"access_token": "t"}}
