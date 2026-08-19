"""Account-creation + email-verify citation flow (7B-5): the signup half of the
Playwright citation engine.

Most real directories do NOT expose a public "add a business" form -- they require
a SIGNUP (create an account, then confirm it via a link OR a numeric code emailed to
you) BEFORE you can submit a listing. The no-signup bot (``citation_bot``) only
handles the minority of public-form directories; this module handles the majority.

A :class:`SignupSpec` is the DATA description of one directory's account-creation:
the signup URL + the name/email/password selectors + the submit button + a
"verification kind" (click a link, or type a code) + the POST-verify add-business
step, which REUSES the existing :class:`~integrations.citation_bot.FormSpec`. Adding
a new signup directory is one ``SignupSpec`` entry, never new Python -- exactly the
data-driven shape of ``FORM_SPECS``.

The runner subclasses :class:`~integrations.citation_bot.PlaywrightCitationSubmitter`
so it inherits ALL of the anti-detection (stealth fingerprint, proxy split, human-
cadence typing) + the CAPTCHA solver hook + the screenshot/proof machinery unchanged.
The flow: open signup -> fill a GENERATED unique alias email + a generated strong
password -> submit -> wait for the confirmation email in the catch-all IMAP mailbox
-> extract the link/code -> click the link (or type the code) -> then run the
existing add-business FormSpec. EVERY branch is degrade-safe: no mailbox / no spec /
no email / selector drift returns a clean ``blocked``/``failed`` result, never a
crash (with ``task_acks_late`` a raised exception would redeliver = double spend).

EVERY SELECTOR HERE IS A BEST-EFFORT STARTING SPEC, not hand-verified against the
directory's live DOM (the same "reconfirm before automating" caveat as ``FORM_SPECS``);
the first runs' proof screenshots exist precisely so a human spot-checks before the
ledger is trusted. Playwright is lazy-imported by the base class -- importing this
module costs nothing until a signup job runs.
"""

from __future__ import annotations

import string
from dataclasses import dataclass, field
from typing import Any

from app.config import Settings
from app.logging_setup import get_logger
from integrations.captcha_solver import CaptchaSolver
from integrations.citation_bot import (
    _FIELD_PAUSE_MS,
    _NAV_TIMEOUT_MS,
    _SETTLE_MS,
    _TIMEOUT_MS,
    CaptchaWidget,
    FormField,
    FormSpec,
    PlaywrightCitationSubmitter,
)
from integrations.citation_submitters import CitationJob, CitationSubmitResult
from integrations.errors import ProviderNotConfiguredError
from integrations.imap_mailbox import ImapMailbox, alias_for, extract_verification

logger = get_logger("integrations.citation_signup")

_ERROR_MAX = 500


@dataclass(frozen=True)
class SignupSpec:
    """One directory's account-creation, DATA-driven end to end.

    ``verify_kind`` is ``'link'`` (the email carries a click-to-confirm URL we visit)
    or ``'code'`` (the email carries a numeric code we type into ``code_field_selector``
    on the pending page, then click ``code_submit_selector``). ``add_business`` is the
    EXISTING FormSpec run AFTER the account is confirmed -- the same add-listing step
    a public-form directory would use, reused verbatim. ``subject_contains`` narrows
    which INBOX message counts as the confirmation (empty -> match on recipient only)."""

    directory_name: str
    signup_url: str
    email_selector: str
    password_selector: str
    submit_selector: str
    verify_kind: str  # 'link' | 'code'
    add_business: FormSpec
    name_selector: str = ""
    signup_captcha: CaptchaWidget | None = None
    subject_contains: tuple[str, ...] = field(default_factory=tuple)
    code_field_selector: str = ""
    code_submit_selector: str = ""
    verify_timeout_s: int = 180


# --------------------------------------------------------------------------- #
# ONE real example. MerchantCircle's signup exposes user_email/user_password fields
# and confirms the account via an emailed LINK; after confirmation a business listing
# is added through its add-a-business form. EVERY selector/URL below is a best-effort
# starting spec (NOT hand-verified against the live DOM) - it proves the framework end
# to end and is the template each further signup directory copies. The dict key +
# `directory_name` are the EXACT catalog `name` so a queued row lines up.
# --------------------------------------------------------------------------- #
SIGNUP_SPECS: dict[str, SignupSpec] = {
    "MerchantCircle": SignupSpec(
        directory_name="MerchantCircle",
        signup_url="https://www.merchantcircle.com/signup",
        name_selector="input[name='user_name']",
        email_selector="input[name='user_email']",
        password_selector="input[name='user_password']",
        submit_selector="button[type='submit']",
        verify_kind="link",
        subject_contains=("confirm", "verify", "welcome", "merchantcircle"),
        add_business=FormSpec(
            directory_name="MerchantCircle",
            url="https://www.merchantcircle.com/business/add",
            fields=(
                FormField("input[name='businessName']", "business_name"),
                FormField("input[name='address']", "address_line1"),
                FormField("input[name='city']", "city"),
                FormField("input[name='state']", "region"),
                FormField("input[name='zip']", "postal_code"),
                FormField("input[name='phone']", "phone"),
                FormField("input[name='website']", "website_url"),
            ),
            submit_selector="button[type='submit']",
            success_indicator="text=thank you",
        ),
    ),
}


def _generate_password(rng: Any) -> str:
    """A strong, per-account password. The ``Aa1!`` prefix guarantees an upper, lower,
    digit and symbol so it clears any directory's strength policy; the 14-char random
    body (drawn from the submitter's RNG - deterministic under a test seed, unpredictable
    in prod) supplies the entropy. Never logged."""
    alphabet = string.ascii_letters + string.digits
    body = "".join(rng.choice(alphabet) for _ in range(14))
    return f"Aa1!{body}"


class SignupCitationSubmitter(PlaywrightCitationSubmitter):
    """The signup+verify engine. Inherits the base bot's stealth/proxy/human-typing/
    CAPTCHA/screenshot machinery; adds account creation and email confirmation via the
    catch-all IMAP mailbox. Degrade-safe: no mailbox / no spec / no email / drift ->
    a clean blocked/failed result, never a crash."""

    def __init__(
        self,
        *,
        mailbox: ImapMailbox | None,
        mail_domain: str,
        signup_specs: dict[str, SignupSpec] | None = None,
        captcha_solver: CaptchaSolver | None = None,
        proxy_url: str | None = None,
        screenshot_dir: str | None = None,
        headless: bool = True,
        rng_seed: int | None = None,
    ) -> None:
        # No FORM_SPECS: this engine dispatches on SIGNUP_SPECS, not the public-form
        # catalog. The base ctor still validates Playwright is importable (raises
        # ProviderNotConfiguredError otherwise, caught by the factory).
        super().__init__(
            specs={},
            captcha_solver=captcha_solver,
            proxy_url=proxy_url,
            screenshot_dir=screenshot_dir,
            headless=headless,
            rng_seed=rng_seed,
        )
        self._mailbox = mailbox
        self._mail_domain = mail_domain
        self._signup_specs = signup_specs if signup_specs is not None else SIGNUP_SPECS

    def submit(self, job: CitationJob) -> CitationSubmitResult:
        spec = self._signup_specs.get(job.directory_name)
        if spec is None:
            return CitationSubmitResult(status="failed", error=f"no SignupSpec for {job.directory_name!r}")
        if spec.add_business.captcha is not None and self._captcha_solver is None:
            return CitationSubmitResult(
                status="blocked", error="captcha_assisted add-business step but no CAPTCHA solver configured"
            )
        if self._mailbox is None:
            return CitationSubmitResult(
                status="blocked", error="no IMAP mailbox configured - cannot confirm the account"
            )
        if not self._mail_domain:
            return CitationSubmitResult(status="blocked", error="no catch-all mail domain configured")
        if not job.client_id:
            return CitationSubmitResult(
                status="blocked", error="no client id on the job - cannot mint a unique signup alias"
            )
        try:
            with self._browser_session(job.directory_name) as context:
                return self._run_signup(context, spec, job)
        except Exception as exc:  # signup/selector drift must fail cleanly, never crash the worker
            logger.warning("citation_signup_failed", directory=job.directory_name, error=str(exc))
            return CitationSubmitResult(status="failed", error=str(exc)[:_ERROR_MAX])

    def _run_signup(self, context: Any, spec: SignupSpec, job: CitationJob) -> CitationSubmitResult:
        from datetime import UTC, datetime

        alias = alias_for(directory=job.directory_name, client_id=job.client_id, domain=self._mail_domain)
        password = _generate_password(self._rng)  # never logged

        page = context.new_page()
        page.goto(spec.signup_url, wait_until="domcontentloaded", timeout=_NAV_TIMEOUT_MS)
        since = datetime.now(UTC)  # record BEFORE submit so the confirmation is "since" this
        if spec.name_selector:
            self._human_fill(page, spec.name_selector, job.business_name)
            page.wait_for_timeout(self._rng.randint(*_FIELD_PAUSE_MS))
        self._human_fill(page, spec.email_selector, alias)
        page.wait_for_timeout(self._rng.randint(*_FIELD_PAUSE_MS))
        self._human_fill(page, spec.password_selector, password)
        page.wait_for_timeout(self._rng.randint(*_FIELD_PAUSE_MS))
        if spec.signup_captcha is not None:
            self._clear_captcha(page, spec.signup_captcha)
        page.click(spec.submit_selector, timeout=_TIMEOUT_MS)
        page.wait_for_timeout(self._rng.randint(*_SETTLE_MS))

        assert self._mailbox is not None  # guarded in submit() before we ever get here
        msg = self._mailbox.wait_for_message(
            to_alias=alias,
            since=since,
            subject_contains=spec.subject_contains,
            timeout_s=spec.verify_timeout_s,
        )
        if msg is None:
            proof = self._screenshot(page, job)
            logger.info("citation_signup_no_email", directory=job.directory_name)
            return CitationSubmitResult(
                status="blocked",
                proof_url=proof,
                error="no confirmation email within timeout - account signup is pending",
            )

        info = extract_verification(msg)
        failure = self._apply_verification(page, spec, info)
        if failure is not None:
            return failure  # missing/unusable link or code -> honest failed

        # Account confirmed: run the EXISTING add-business FormSpec (reused verbatim).
        page.goto(spec.add_business.url, wait_until="domcontentloaded", timeout=_NAV_TIMEOUT_MS)
        return self._fill_form(page, spec.add_business, job)

    def _apply_verification(
        self, page: Any, spec: SignupSpec, info: Any
    ) -> CitationSubmitResult | None:
        """Consume the confirmation. Returns ``None`` on success (the account is now
        confirmed and the caller proceeds to add-business), or a ``failed`` result when
        the email lacked the link/code the spec needs."""
        if spec.verify_kind == "link":
            if not info.link:
                return CitationSubmitResult(status="failed", error="confirmation email had no verify link")
            page.goto(info.link, wait_until="domcontentloaded", timeout=_NAV_TIMEOUT_MS)
            page.wait_for_timeout(self._rng.randint(*_SETTLE_MS))
            return None
        if spec.verify_kind == "code":
            if not info.code:
                return CitationSubmitResult(status="failed", error="confirmation email had no verify code")
            if not spec.code_field_selector:
                return CitationSubmitResult(
                    status="failed", error="code-verify SignupSpec has no code_field_selector"
                )
            self._human_fill(page, spec.code_field_selector, info.code)
            page.wait_for_timeout(self._rng.randint(*_FIELD_PAUSE_MS))
            if spec.code_submit_selector:
                page.click(spec.code_submit_selector, timeout=_TIMEOUT_MS)
                page.wait_for_timeout(self._rng.randint(*_SETTLE_MS))
            return None
        return CitationSubmitResult(status="failed", error=f"unknown verify_kind {spec.verify_kind!r}")


def citation_signup_bot_from_settings(
    settings: Settings, *, captcha_solver: CaptchaSolver | None, mailbox: ImapMailbox | None
) -> SignupCitationSubmitter | None:
    """The signup engine, or ``None`` when it cannot run: no catch-all mailbox / no
    mail domain (unconfigured), or Playwright not installed. A ``bot:signup`` directory
    then HOLDS as ``blocked`` (via ``submitter_for``'s honest reason) rather than
    crashing the worker. ``mailbox`` + ``captcha_solver`` are built once by the caller
    and passed in, mirroring ``citation_bot_from_settings``."""
    if mailbox is None or not settings.citation_mail_domain:
        logger.info("citation_signup_bot_degraded", reason="no_mailbox_or_domain")
        return None
    try:
        return SignupCitationSubmitter(
            mailbox=mailbox,
            mail_domain=settings.citation_mail_domain,
            captcha_solver=captcha_solver,
            proxy_url=settings.citation_proxy_url.get_secret_value() if settings.citation_proxy_url else None,
            screenshot_dir=settings.citation_artifact_dir,
        )
    except ProviderNotConfiguredError:
        logger.info("citation_signup_bot_degraded", reason="playwright_not_installed")
        return None
