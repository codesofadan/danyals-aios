"""House-account API signup + verify + provision for the web2 pipeline (7B-5).

The web2 publish pipeline builds a real ``Web2Publisher`` from a per-client vault
credential (``integrations.web2_credentials.build_publisher``). Today ~5 platforms
have a working house credential; the other automation_ready platforms have a real
publisher CLASS but NO account/token to publish with. This module closes that gap
FOR THE PLATFORMS WITH A REAL SIGNUP API: it creates the account over the platform's
own endpoint, optionally reads a confirmation email over the shared catch-all IMAP
mailbox (``integrations.imap_mailbox``), and seals the resulting token/creds into
the web2 vault in the exact shape ``build_publisher`` reads back -- after which the
existing publisher publishes.

ONE signup mechanism survives (off-page redesign Phase 3, resolution C2): **API
signup** -- a platform with a real signup/token endpoint (no browser):

  - :class:`TelegraphAnonymousProvider` mints an anonymous Telegra.ph ``access_token``
    (no email at all) -> ``{"access_token": ...}``.
  - :class:`WriteFreelySignupProvider` registers a Write.as/WriteFreely account over
    ``/api/auth/signup`` and returns the issued token -> ``{"token": ..., "alias": ...}``.

The Playwright ``BrowserSignupProvider`` (never wired to a worker) was DELETED with
the citation bot: it carried a CAPTCHA-injection step and human-cadence typing --
the anti-detection posture this platform has ruled out. Every other platform's
account is created in the GUIDED lane (0123): a person signs up in their own
browser; the provisioning queue watches the mailbox for the verify link and
``register_account`` seals the credential.

Every provider DEGRADES to a ``blocked``/``failed`` result rather than raising -- a
platform we cannot yet sign up for HOLDS for manual account creation, it never crashes
the worker. ``provision_account`` is idempotent (an existing vault row is reused, no
signup) and only seals a ``created`` result. All external I/O is behind an injected
seam (``HttpJson``, the mailbox, the vault ``find``/``add``) so the whole flow
unit-tests with fakes and ZERO live signups.
"""

from __future__ import annotations

import json
import re
import secrets
import string
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from app.logging_setup import get_logger
from integrations.errors import ProviderCallError
from integrations.imap_mailbox import alias_for, extract_verification
from integrations.web2_credentials import VAULT_KIND_CLIENT_ACCESS, vault_provider_for
from integrations.web2_publishers import (
    PLATFORM_TELEGRAPH,
    PLATFORM_WRITEAS,
)

if TYPE_CHECKING:
    from email.message import EmailMessage

logger = get_logger("integrations.web2_signup")

STATUS_CREATED = "created"
STATUS_EXISTS = "exists"
STATUS_BLOCKED = "blocked"
STATUS_FAILED = "failed"

_PW_ALPHABET = string.ascii_letters + string.digits
_PW_SYMBOLS = "!@#$%^&*-_=+"
_NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")


def generate_password(length: int = 20) -> str:
    """A strong random signup password (upper+lower+digit+symbol guaranteed).

    ``secrets``-based; re-rolls until it carries at least one of each class so it
    clears a platform's "must contain ..." rule. Never persisted except sealed in the
    vault as part of the credential blob (for the platforms whose credential IS the
    login, e.g. LiveJournal/Dreamwidth)."""
    alphabet = _PW_ALPHABET + _PW_SYMBOLS
    while True:
        pw = "".join(secrets.choice(alphabet) for _ in range(max(length, 8)))
        if (
            any(c.islower() for c in pw)
            and any(c.isupper() for c in pw)
            and any(c.isdigit() for c in pw)
            and any(c in _PW_SYMBOLS for c in pw)
        ):
            return pw


def _username_from_alias(alias_email: str) -> str:
    """A platform-legal username derived from the alias local part (lower alnum, <=24).

    The alias is ``<platform-slug>-<client-hash>@domain`` (deterministic per platform +
    client), so the stripped local part is unique per client without leaking the id."""
    local = alias_email.split("@", 1)[0]
    return (_NON_ALNUM_RE.sub("", local.lower()) or "qanry")[:24]


def _default_clock() -> datetime:
    """UTC now -- the ``since`` watermark captured before a signup so the mailbox only
    matches the confirmation email THIS signup triggered, not an older one."""
    return datetime.now(tz=UTC)


# --------------------------------------------------------------------------- #
# The injected HTTP seam (API providers) -- a tiny JSON poster so the real path
# uses httpx and the test path a recorder, with no HttpProviderClient header
# pre-binding (signup calls are unauthenticated or set their own headers).
# --------------------------------------------------------------------------- #
@runtime_checkable
class HttpJson(Protocol):
    """Issue one HTTP request and return the parsed JSON object. Raises
    :class:`ProviderCallError` on a non-2xx or a non-JSON/non-object body."""

    def __call__(
        self,
        url: str,
        *,
        method: str = "POST",
        data: Mapping[str, Any] | None = None,
        json_body: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
        timeout: float = 30.0,
    ) -> dict[str, Any]: ...


def httpx_json(
    url: str,
    *,
    method: str = "POST",
    data: Mapping[str, Any] | None = None,
    json_body: Mapping[str, Any] | None = None,
    headers: Mapping[str, str] | None = None,
    timeout: float = 30.0,
) -> dict[str, Any]:
    """The real :class:`HttpJson` (httpx, lazy-imported). No secret ever rides in the
    URL, so a stripped error line cannot echo one."""
    import httpx

    try:
        resp = httpx.request(
            method,
            url,
            data=dict(data) if data else None,
            json=dict(json_body) if json_body else None,
            headers=dict(headers) if headers else None,
            timeout=httpx.Timeout(timeout),
            follow_redirects=True,
        )
    except httpx.TransportError as exc:
        raise ProviderCallError(f"signup transport error: {type(exc).__name__}") from exc
    if resp.status_code >= 400:
        logger.error("signup_http_error", status=resp.status_code, path=str(resp.request.url).split("?", 1)[0])
        raise ProviderCallError(f"signup request failed with status {resp.status_code}")
    try:
        payload = resp.json()
    except ValueError as exc:
        raise ProviderCallError("signup returned a non-JSON body") from exc
    if not isinstance(payload, dict):
        raise ProviderCallError("signup returned an unexpected JSON shape")
    return payload


# --------------------------------------------------------------------------- #
# The mailbox seam this flow needs (structural; the real ``ImapMailbox`` satisfies
# it). Kept a local Protocol so a test fake needs no IMAP and the module never
# imports the concrete reader for typing.
# --------------------------------------------------------------------------- #
@runtime_checkable
class MailboxLike(Protocol):
    def wait_for_message(
        self,
        *,
        to_alias: str,
        since: datetime,
        subject_contains: Sequence[str] = (),
        timeout_s: int = 180,
        poll_s: int = 5,
    ) -> EmailMessage | None: ...


# --------------------------------------------------------------------------- #
# Result + context + provider protocol.
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class Web2SignupResult:
    """The outcome of a house-account signup.

    ``credentials`` (only on ``created``) is the dict matching
    ``web2_publishers.PLATFORM_CREDENTIAL_FIELDS[platform]`` that ``provision_account``
    seals into the vault. ``blocked`` = a known dead-end (captcha we can't solve, no
    mailbox to verify with); ``failed`` = an unexpected error; ``exists`` = a vault row
    was already present (no signup attempted)."""

    platform: str
    status: str
    credentials: dict[str, str] = field(default_factory=dict)
    account_email: str = ""
    account_url: str = ""
    error: str = ""


@dataclass(frozen=True)
class SignupContext:
    """Everything a provider needs to create + verify one house account. Injected so
    the flow is pure/testable: ``http`` (API providers), ``mailbox`` (email
    verification), and the ``clock`` watermark. ``alias_email`` is the deterministic
    per-(platform, client) catch-all address. (The browser ``page`` and ``captcha``
    seams were deleted with the browser provider - resolution C2.)"""

    platform: str
    alias_email: str
    username: str
    password: str
    business_name: str = ""
    mailbox: MailboxLike | None = None
    http: HttpJson | None = None
    verify_timeout_s: int = 120
    clock: Callable[[], datetime] = _default_clock


@runtime_checkable
class Web2SignupProvider(Protocol):
    """Create (and verify) one house account on :attr:`platform`, returning the sealed
    credential shape. Satisfied by the API + browser providers below and by
    :class:`FakeSignupProvider` in tests."""

    platform: str

    def signup(self, ctx: SignupContext) -> Web2SignupResult: ...


class FakeSignupProvider:
    """Deterministic, offline provider for the signup suite -- returns a canned
    ``created`` credential (or a forced ``blocked``/``failed``) and records the ctx."""

    def __init__(
        self, *, platform: str, credentials: dict[str, str] | None = None, status: str = STATUS_CREATED
    ) -> None:
        self.platform = platform
        self._credentials = credentials or {"token": "fake-token"}
        self._status = status
        self.calls: list[SignupContext] = []

    def signup(self, ctx: SignupContext) -> Web2SignupResult:
        self.calls.append(ctx)
        if self._status != STATUS_CREATED:
            return Web2SignupResult(platform=self.platform, status=self._status, error="forced")
        return Web2SignupResult(
            platform=self.platform,
            status=STATUS_CREATED,
            credentials=dict(self._credentials),
            account_email=ctx.alias_email,
        )


# --------------------------------------------------------------------------- #
# API providers (no browser).
# --------------------------------------------------------------------------- #
class TelegraphAnonymousProvider:
    """Mint an anonymous Telegra.ph ``access_token`` via ``createAccount`` -- the one
    web2 platform that needs NO email and NO password (it is anonymous by design). The
    resulting token is the whole credential the ``TelegraPhClient`` publishes with."""

    platform = PLATFORM_TELEGRAPH
    _ENDPOINT = "https://api.telegra.ph/createAccount"

    def signup(self, ctx: SignupContext) -> Web2SignupResult:
        http = ctx.http
        if http is None:
            return Web2SignupResult(platform=self.platform, status=STATUS_FAILED, error="no http seam")
        short = (ctx.username or "qanry")[:32]
        try:
            payload = http(self._ENDPOINT, method="POST", data={"short_name": short, "author_name": short})
        except ProviderCallError as exc:
            return Web2SignupResult(platform=self.platform, status=STATUS_FAILED, error=str(exc)[:200])
        if not payload.get("ok"):
            return Web2SignupResult(platform=self.platform, status=STATUS_FAILED, error="telegraph not ok")
        result = payload.get("result")
        token = str(result.get("access_token") or "") if isinstance(result, dict) else ""
        if not token:
            return Web2SignupResult(platform=self.platform, status=STATUS_FAILED, error="no access_token")
        auth_url = str(result.get("auth_url") or "") if isinstance(result, dict) else ""
        return Web2SignupResult(
            platform=self.platform,
            status=STATUS_CREATED,
            credentials={"access_token": token},
            account_url=auth_url,
        )


class WriteFreelySignupProvider:
    """Register a Write.as/WriteFreely account over ``POST {host}/api/auth/signup`` and
    return the issued bearer token + the collection alias the ``WriteAsClient`` posts
    to. Write.as email is optional (no mandatory click-verify), so this is a clean
    API-only house-account creation; if ``ctx.mailbox`` is set the flow still reads a
    confirmation link when one is sent, but never BLOCKS on its absence."""

    platform = PLATFORM_WRITEAS
    _DEFAULT_HOST = "https://write.as"

    def __init__(self, *, host: str = _DEFAULT_HOST) -> None:
        self._host = host.rstrip("/")

    def signup(self, ctx: SignupContext) -> Web2SignupResult:
        http = ctx.http
        if http is None:
            return Web2SignupResult(platform=self.platform, status=STATUS_FAILED, error="no http seam")
        alias = ctx.username
        try:
            payload = http(
                f"{self._host}/api/auth/signup",
                method="POST",
                json_body={"alias": alias, "pass": ctx.password, "email": ctx.alias_email},
                headers={"Content-Type": "application/json"},
            )
        except ProviderCallError as exc:
            return Web2SignupResult(platform=self.platform, status=STATUS_FAILED, error=str(exc)[:200])
        data = payload.get("data")
        token = str(data.get("access_token") or "") if isinstance(data, dict) else ""
        if not token:
            return Web2SignupResult(platform=self.platform, status=STATUS_FAILED, error="no access_token")
        # Best-effort activation click if the platform emailed one; never required.
        if ctx.mailbox is not None:
            msg = ctx.mailbox.wait_for_message(
                to_alias=ctx.alias_email, since=ctx.clock(), subject_contains=("confirm", "verify"), timeout_s=5
            )
            if msg is not None and extract_verification(msg).link:
                logger.info("web2_signup_verify_link_seen", platform=self.platform)
        return Web2SignupResult(
            platform=self.platform,
            status=STATUS_CREATED,
            credentials={"token": token, "alias": alias},
            account_email=ctx.alias_email,
            account_url=f"https://{alias}.write.as",
        )


# --------------------------------------------------------------------------- #
# Registry + provisioning (vault wiring).
# --------------------------------------------------------------------------- #
def api_signup_provider_for(platform: str) -> Web2SignupProvider | None:
    """The API (no-browser) signup provider for a platform, or ``None`` when there is
    no automatable API signup for it (it needs the browser flow or manual creation)."""
    if platform == PLATFORM_TELEGRAPH:
        return TelegraphAnonymousProvider()
    if platform == PLATFORM_WRITEAS:
        return WriteFreelySignupProvider()
    return None


class SecretFinder(Protocol):
    def __call__(self, *, provider: str, label: str) -> str | None: ...


class SecretAdder(Protocol):
    def __call__(self, *, provider: str, label: str, secret: str, kind: str) -> Any: ...


def _default_add(*, provider: str, label: str, secret: str, kind: str) -> Any:
    from typing import cast

    from app.services.vault import VaultKind, add_key

    return add_key(provider=provider, label=label, secret=secret, kind=cast("VaultKind", kind))


def _default_find(*, provider: str, label: str) -> str | None:
    from app.services.vault import find_secret

    return find_secret(provider=provider, label=label)


def make_context(
    *,
    platform: str,
    client_id: str,
    catchall_domain: str,
    ownership: str = "house",
    handle: str = "",
    email: str = "",
    mailbox: MailboxLike | None = None,
    http: HttpJson | None = httpx_json,
    password: str | None = None,
    business_name: str = "",
    verify_timeout_s: int = 120,
) -> SignupContext:
    """Build a :class:`SignupContext`.

    ``ownership='house'`` (the default) keeps the deterministic per-(platform, client)
    catch-all alias: a retry REUSES the same account (never fans one client into many)
    and the confirmation email lands in the catch-all under that address. That is
    legitimate for a house account, which is openly agency-owned and impersonates
    nobody.

    ``ownership='per_client'`` REFUSES to generate an identity and requires an explicit
    ``handle`` + ``email`` (R2-08). The generated alias is
    ``{platform-slug}-{sha1(client_id)[:10]}@{one shared domain}``, which emits three
    joinable keys at once - a shared prefix per platform, a shared suffix per client,
    and one registrant domain across the whole client base - so a platform that
    suspends ONE account can enumerate the rest. No content-level check can see that,
    which is why it is refused here rather than warned about."""
    if ownership == "per_client":
        if not handle.strip() or not email.strip():
            raise ValueError(
                "a per_client signup needs an explicit brand handle and a registration "
                "email on the client's own domain; the generated catch-all alias is a "
                "cross-client footprint (R2-08)"
            )
        alias_email = email.strip()
        username = handle.strip()
    else:
        alias_email = email.strip() or alias_for(
            directory=platform, client_id=client_id, domain=catchall_domain
        )
        username = handle.strip() or _username_from_alias(alias_email)
    return SignupContext(
        platform=platform,
        alias_email=alias_email,
        username=username,
        password=password or generate_password(),
        business_name=business_name,
        mailbox=mailbox,
        http=http,
        verify_timeout_s=verify_timeout_s,
    )


def provision_account(
    *,
    client_id: str,
    platform: str,
    provider: Web2SignupProvider,
    ctx: SignupContext,
    find: SecretFinder = _default_find,
    add: SecretAdder = _default_add,
) -> Web2SignupResult:
    """Create + verify a house account and SEAL its credential into the web2 vault.

    Idempotent: an existing ``web2:<platform>`` / ``label=<client_id>`` row is REUSED
    (returns ``exists`` without signing up), exactly like ``seed_web2_vault`` skips an
    existing row. Only a ``created`` result is sealed -- a ``blocked``/``failed`` signup
    writes nothing, so the pipeline holds the placement at review (never a dead vault
    row a publisher can't use). The sealed secret is the compact JSON the credential
    factory (``web2_credentials.build_publisher``) parses straight back."""
    vault_provider = vault_provider_for(platform)
    if find(provider=vault_provider, label=client_id) is not None:
        logger.info("web2_signup_skip_exists", platform=platform, client_id=client_id)
        return Web2SignupResult(platform=platform, status=STATUS_EXISTS)
    result = provider.signup(ctx)
    if result.status != STATUS_CREATED or not result.credentials:
        logger.info("web2_signup_not_created", platform=platform, status=result.status)
        return result
    add(
        provider=vault_provider,
        label=client_id,
        secret=json.dumps(result.credentials, separators=(",", ":")),
        kind=VAULT_KIND_CLIENT_ACCESS,
    )
    logger.info("web2_signup_sealed", platform=platform, client_id=client_id)
    return result


def house_credentials_block(results: Sequence[Web2SignupResult]) -> dict[str, dict[str, str]]:
    """Fold ``created`` signup results into a ``WEB2_HOUSE_CREDENTIALS_JSON`` block
    (``{platform: {field: value}}``) -- the shape ``app.cli.seed_web2_vault`` fans out to
    every client. Lets a house-account signup run feed the existing per-client seeder
    instead of sealing one client at a time."""
    return {r.platform: dict(r.credentials) for r in results if r.status == STATUS_CREATED and r.credentials}
