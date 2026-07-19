"""Playwright citation-submission bot (7B-4): the self-hosted engine for
``bot_fillable`` and ``captcha_assisted`` directories - the reference plan's own cost
model puts this route at ~$0.004-0.008/citation (CAPTCHA solve + proxy bandwidth +
compute), well under the 10c ceiling and ~2.5x cheaper than an off-the-shelf Apify
actor, ~20-50x cheaper than a managed citation service.

A :class:`FormSpec` is a small, DATA-driven description of one directory's signup
form (URL + CSS selectors mapped to NAP fields + the submit button + a success
indicator) - a NEW directory is added as DATA in ``FORM_SPECS``, never new Python.
``FORM_SPECS`` below seeds a representative slice of the ``bot_fillable`` long-tail
from ``db/migrations/0046_directories_seed.sql``; extending coverage to the rest of
that catalog's ``bot_fillable``/``captcha_assisted`` rows is exactly one FormSpec
entry each, not a new client class.

EVERY SELECTOR HERE IS A BEST-EFFORT STARTING SPEC, not hand-verified against each
directory's current live DOM markup (these change without notice - exactly the
reference doc's own "reconfirm before automating" caution, repeated site-by-site
throughout it). A submission's screenshot (``proof_url``) exists precisely so a human
spot-checks the FIRST few runs per directory before the ledger is trusted at scale;
a FormSpec that has drifted from the live form fails CLEANLY (a missing selector
raises inside ``submit``, caught here and returned as ``status="failed"`` with
whatever screenshot could be captured attached for diagnosis) - never a silent false
"submitted".

Uses Playwright's SYNC API deliberately (this module runs inside a Celery worker,
never the async FastAPI request path). Playwright is an OPTIONAL dependency
(``pip install -e .[automation]``) - lazy-imported so importing this module (and the
rest of the citations package) costs nothing until a bot_fillable job actually runs,
mirroring how every other optional SDK in this codebase is gated.
"""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.config import Settings
from app.logging_setup import get_logger
from integrations.captcha_solver import CaptchaChallenge, CaptchaSolver
from integrations.citation_submitters import CitationJob, CitationSubmitResult
from integrations.errors import ProviderNotConfiguredError

logger = get_logger("integrations.citation_bot")

_INSTALL_HINT = (
    "pip install -e .[automation] (Playwright) to enable bot_fillable/"
    "captcha_assisted citation submits"
)

_TIMEOUT_MS = 15_000
_NAV_TIMEOUT_MS = 30_000


@dataclass(frozen=True)
class FormField:
    """One form field to fill: a CSS selector + which NAP attribute feeds it (or a
    fixed ``literal:<text>`` value for a field the NAP doesn't supply, e.g. a
    category dropdown some directories require)."""

    selector: str
    value_key: str


@dataclass(frozen=True)
class CaptchaWidget:
    """The CAPTCHA gating a ``captcha_assisted`` directory's form: where to read the
    site key from, and which field the solved token must be written back into."""

    kind: str  # matches CaptchaChallenge.kind (recaptcha_v2 | hcaptcha | turnstile | ...)
    site_key_selector: str
    site_key_attr: str = "data-sitekey"
    response_field_name: str = "g-recaptcha-response"


@dataclass(frozen=True)
class FormSpec:
    """One directory's submission form: where to go, what to fill, how to submit,
    and how to know it worked. ``success_indicator`` is either ``text=<substring>``
    (a case-insensitive page-content check) or a CSS selector to find on the
    resulting page."""

    directory_name: str
    url: str
    fields: tuple[FormField, ...]
    submit_selector: str
    success_indicator: str
    captcha: CaptchaWidget | None = None


def _job_value(job: CitationJob, key: str) -> str:
    if key.startswith("literal:"):
        return key.split(":", 1)[1]
    fields: dict[str, str] = {
        "business_name": job.business_name,
        "address_line1": job.address_line1,
        "address_line2": job.address_line2,
        "city": job.city,
        "region": job.region,
        "postal_code": job.postal_code,
        "phone": job.phone,
        "website_url": job.website_url,
        "categories": ", ".join(job.categories),
    }
    return fields.get(key, "")


# --------------------------------------------------------------------------- #
# A representative bot_fillable slice (US long-tail; the shape extends unchanged to
# the rest of the catalog - see the module docstring). All plain web forms, no
# CAPTCHA, per db/migrations/0046_directories_seed.sql.
# --------------------------------------------------------------------------- #
FORM_SPECS: dict[str, FormSpec] = {
    "Brownbook": FormSpec(
        directory_name="Brownbook",
        url="https://www.brownbook.net/business/add/",
        fields=(
            FormField("input[name='business_name']", "business_name"),
            FormField("input[name='address']", "address_line1"),
            FormField("input[name='city']", "city"),
            FormField("input[name='phone']", "phone"),
            FormField("input[name='website']", "website_url"),
        ),
        submit_selector="button[type='submit']",
        success_indicator="text=successfully",
    ),
    "MerchantCircle": FormSpec(
        directory_name="MerchantCircle",
        url="https://www.merchantcircle.com/signup",
        fields=(
            FormField("input[name='businessName']", "business_name"),
            FormField("input[name='address']", "address_line1"),
            FormField("input[name='city']", "city"),
            FormField("input[name='state']", "region"),
            FormField("input[name='zip']", "postal_code"),
            FormField("input[name='phone']", "phone"),
        ),
        submit_selector="button[type='submit']",
        success_indicator="text=thank you",
    ),
    "Chamber of Commerce": FormSpec(
        directory_name="Chamber of Commerce",
        url="https://www.chamberofcommerce.com/business-directory/add",
        fields=(
            FormField("input[name='company']", "business_name"),
            FormField("input[name='address1']", "address_line1"),
            FormField("input[name='city']", "city"),
            FormField("input[name='state']", "region"),
            FormField("input[name='zip']", "postal_code"),
            FormField("input[name='phone']", "phone"),
            FormField("input[name='website']", "website_url"),
        ),
        submit_selector="button[type='submit']",
        success_indicator="text=added",
    ),
    "Hotfrog": FormSpec(
        directory_name="Hotfrog",
        url="https://www.hotfrog.com/AddYourBusiness",
        fields=(
            FormField("input[name='businessName']", "business_name"),
            FormField("input[name='address']", "address_line1"),
            FormField("input[name='city']", "city"),
            FormField("input[name='phone']", "phone"),
            FormField("input[name='url']", "website_url"),
        ),
        submit_selector="button[type='submit']",
        success_indicator="text=thank you",
    ),
    "EZLocal": FormSpec(
        directory_name="EZLocal",
        url="https://www.ezlocal.com/addlisting",
        fields=(
            FormField("input[name='business_name']", "business_name"),
            FormField("input[name='address']", "address_line1"),
            FormField("input[name='city']", "city"),
            FormField("input[name='phone']", "phone"),
        ),
        submit_selector="button[type='submit']",
        success_indicator="text=submitted",
    ),
    "ShowMeLocal": FormSpec(
        directory_name="ShowMeLocal",
        url="https://www.showmelocal.com/addbusiness.aspx",
        fields=(
            FormField("input[name='BusinessName']", "business_name"),
            FormField("input[name='Address']", "address_line1"),
            FormField("input[name='City']", "city"),
            FormField("input[name='Phone']", "phone"),
        ),
        submit_selector="input[type='submit']",
        success_indicator="text=thank you",
    ),
    "Cylex USA": FormSpec(
        directory_name="Cylex USA",
        url="https://www.cylex-usa.com/add-company",
        fields=(
            FormField("input[name='companyName']", "business_name"),
            FormField("input[name='street']", "address_line1"),
            FormField("input[name='city']", "city"),
            FormField("input[name='phone']", "phone"),
            FormField("input[name='website']", "website_url"),
        ),
        submit_selector="button[type='submit']",
        success_indicator="text=success",
    ),
    "CitySquares": FormSpec(
        directory_name="CitySquares",
        url="https://citysquares.com/add-business",
        fields=(
            FormField("input[name='name']", "business_name"),
            FormField("input[name='address']", "address_line1"),
            FormField("input[name='city']", "city"),
            FormField("input[name='phone']", "phone"),
        ),
        submit_selector="button[type='submit']",
        success_indicator="text=thank you",
    ),
    "Callupcontact": FormSpec(
        directory_name="Callupcontact",
        url="https://www.callupcontact.com/add_business",
        fields=(
            FormField("input[name='business_name']", "business_name"),
            FormField("input[name='address']", "address_line1"),
            FormField("input[name='phone']", "phone"),
        ),
        submit_selector="button[type='submit']",
        success_indicator="text=added",
    ),
    "Cybo": FormSpec(
        directory_name="Cybo",
        url="https://www.cybo.com/add-company",
        fields=(
            FormField("input[name='name']", "business_name"),
            FormField("input[name='address']", "address_line1"),
            FormField("input[name='city']", "city"),
            FormField("input[name='phone']", "phone"),
        ),
        submit_selector="button[type='submit']",
        success_indicator="text=thank you",
    ),
    "Storeboard": FormSpec(
        directory_name="Storeboard",
        url="https://www.storeboard.com/signup",
        fields=(
            FormField("input[name='companyName']", "business_name"),
            FormField("input[name='address']", "address_line1"),
            FormField("input[name='phone']", "phone"),
            FormField("input[name='website']", "website_url"),
        ),
        submit_selector="button[type='submit']",
        success_indicator="text=welcome",
    ),
    "YaSabe": FormSpec(
        directory_name="YaSabe",
        url="https://www.yasabe.com/add-business",
        fields=(
            FormField("input[name='business_name']", "business_name"),
            FormField("input[name='address']", "address_line1"),
            FormField("input[name='city']", "city"),
            FormField("input[name='phone']", "phone"),
        ),
        submit_selector="button[type='submit']",
        success_indicator="text=gracias",
    ),
}


class PlaywrightCitationSubmitter:
    """Real ``CitationSubmitter`` driving a headless Chromium session per submit.

    ``specs`` defaults to the module's ``FORM_SPECS`` catalog but is overridable
    (tests inject a tiny fixture spec). ``captcha_solver`` is required only for
    ``captcha_assisted`` directories (a spec with ``captcha`` set) - a
    ``bot_fillable`` job never needs one. ``proxy_url`` is optional (budget-tier
    residential proxy, per the reference plan's cost model); ``screenshot_dir`` is
    where every submission's proof screenshot lands (unset -> no screenshot, an
    empty ``proof_url``, which is still an honest result, just without visual proof).
    """

    def __init__(
        self,
        *,
        specs: dict[str, FormSpec] | None = None,
        captcha_solver: CaptchaSolver | None = None,
        proxy_url: str | None = None,
        screenshot_dir: str | None = None,
        headless: bool = True,
    ) -> None:
        try:
            import playwright.sync_api  # noqa: F401
        except ImportError as exc:
            raise ProviderNotConfiguredError(f"Playwright citation bot unavailable: {_INSTALL_HINT}") from exc
        self._specs = specs if specs is not None else FORM_SPECS
        self._captcha_solver = captcha_solver
        self._proxy_url = proxy_url
        self._screenshot_dir = Path(screenshot_dir) if screenshot_dir else None
        self._headless = headless

    def submit(self, job: CitationJob) -> CitationSubmitResult:
        spec = self._specs.get(job.directory_name)
        if spec is None:
            return CitationSubmitResult(status="failed", error=f"no FormSpec for {job.directory_name!r}")
        if spec.captcha is not None and self._captcha_solver is None:
            return CitationSubmitResult(
                status="blocked", error="captcha_assisted directory but no CAPTCHA solver configured"
            )

        from playwright.sync_api import sync_playwright

        launch_kwargs: dict[str, object] = {"headless": self._headless}
        if self._proxy_url:
            launch_kwargs["proxy"] = {"server": self._proxy_url}
        try:
            with sync_playwright() as pw:
                browser = pw.chromium.launch(**launch_kwargs)
                try:
                    return self._run(browser, spec, job)
                finally:
                    browser.close()
        except Exception as exc:  # a form/selector drift must fail cleanly, never crash the worker
            logger.warning("citation_bot_submit_failed", directory=job.directory_name, error=str(exc))
            return CitationSubmitResult(status="failed", error=str(exc)[:500])

    def _run(self, browser: Any, spec: FormSpec, job: CitationJob) -> CitationSubmitResult:
        page = browser.new_page()
        page.goto(spec.url, wait_until="domcontentloaded", timeout=_NAV_TIMEOUT_MS)
        for f in spec.fields:
            value = _job_value(job, f.value_key)
            if value:
                page.fill(f.selector, value, timeout=_TIMEOUT_MS)
        if spec.captcha is not None:
            self._clear_captcha(page, spec.captcha)
        page.click(spec.submit_selector, timeout=_TIMEOUT_MS)
        page.wait_for_timeout(2_000)
        proof_url = self._screenshot(page, job)
        if self._check_success(page, spec.success_indicator):
            return CitationSubmitResult(status="submitted", proof_url=proof_url)
        return CitationSubmitResult(status="failed", proof_url=proof_url, error="success indicator not found")

    def _clear_captcha(self, page: Any, widget: CaptchaWidget) -> None:
        site_key = page.get_attribute(widget.site_key_selector, widget.site_key_attr, timeout=_TIMEOUT_MS)
        if not site_key:
            raise RuntimeError("could not read the CAPTCHA site key from the page")
        assert self._captcha_solver is not None  # guarded by submit() before this is ever called
        solution = self._captcha_solver.solve(
            CaptchaChallenge(kind=widget.kind, site_key=site_key, page_url=page.url)
        )
        page.evaluate(
            "([name, token]) => { const el = document.getElementsByName(name)[0]; "
            "if (el) el.value = token; }",
            [widget.response_field_name, solution.token],
        )

    def _screenshot(self, page: Any, job: CitationJob) -> str:
        if self._screenshot_dir is None:
            return ""
        self._screenshot_dir.mkdir(parents=True, exist_ok=True)
        digest = hashlib.sha256(
            f"{job.directory_name}|{job.business_name}|{time.time()}".encode()
        ).hexdigest()[:16]
        path = self._screenshot_dir / f"{digest}.png"
        page.screenshot(path=str(path))
        return str(path)

    def _check_success(self, page: Any, indicator: str) -> bool:
        if indicator.startswith("text="):
            return indicator[5:].lower() in page.content().lower()
        try:
            return bool(page.locator(indicator).count())
        except Exception:
            return False


def citation_bot_from_settings(
    settings: Settings, *, captcha_solver: CaptchaSolver | None
) -> PlaywrightCitationSubmitter | None:
    """The self-hosted bot, or ``None`` when Playwright is not installed (degraded -
    a bot_fillable/captcha_assisted job HOLDS rather than crashing the worker).
    ``captcha_solver`` is passed in (built once per worker call by the caller, which
    already knows whether a key is configured) rather than resolved here."""
    try:
        return PlaywrightCitationSubmitter(
            captcha_solver=captcha_solver,
            proxy_url=settings.citation_proxy_url.get_secret_value() if settings.citation_proxy_url else None,
            screenshot_dir=settings.citation_artifact_dir,
        )
    except ProviderNotConfiguredError:
        logger.info("citation_bot_degraded", reason="playwright_not_installed")
        return None
