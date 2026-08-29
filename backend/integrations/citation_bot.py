"""Playwright citation-submission bot (7B-4): the self-hosted engine for
``bot_fillable`` and ``captcha_assisted`` directories - the reference plan's own cost
model puts this route at ~$0.004-0.008/citation (CAPTCHA solve + proxy bandwidth +
compute), well under the 10c ceiling and ~20-50x cheaper than a managed citation
service.

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
import random
import time
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

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

# --- Anti-detection (Phase 3) ------------------------------------------------
# Plain headless Chromium is trivially fingerprinted (navigator.webdriver=true, the
# HeadlessChrome UA, a fixed viewport, no plugins). At submission scale that flags the
# house IP/accounts and directories reject the listing. These measures make a run look
# like an ordinary human browser: a realistic RANDOMIZED fingerprint per run, the
# automation signals masked before any page script runs, and human-cadence typing +
# pauses. All best-effort - a failed stealth step logs and continues, never breaks a
# submit. (Not a silver bullet: sophisticated anti-bot walls may still block; the proxy
# + rate-limiting + per-run variety together keep block rates workable at volume.)
_STEALTH_LAUNCH_ARGS = (
    "--disable-blink-features=AutomationControlled",
    "--disable-features=IsolateOrigins,site-per-process",
    "--no-sandbox",
    "--disable-dev-shm-usage",
)
_USER_AGENTS = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
)
_VIEWPORTS = ((1366, 768), (1440, 900), (1536, 864), (1920, 1080), (1280, 800))
# (locale, timezone) pairs kept plausible together (a UK locale in a London tz, etc.).
_LOCALES = (
    ("en-US", "America/New_York"),
    ("en-GB", "Europe/London"),
    ("en-US", "America/Chicago"),
    ("en-AU", "Australia/Sydney"),
)
# Injected BEFORE any page script runs: erase the headless/automation tells.
# MEASURED, not assumed (app/services/browser_fingerprint.py, 2026-08-29). Raw headless
# Chromium leaks 4 high signals; with the first four lines below it leaks ONE - the WebGL
# renderer, which reports "SwiftShader". That string is the software rasteriser a headless
# container falls back to, and no consumer machine reports it, so it identifies the session
# as a datacentre bot on its own. The mimeTypes list is the same class of tell as plugins
# (empty in headless, never empty in a real browser) and was simply missed.
#
# What this canNOT reach: TLS fingerprint, IP reputation and behavioural scoring are
# decided by the defender off-page. A clean fingerprint is necessary, not sufficient.
_STEALTH_INIT_JS = (
    "Object.defineProperty(navigator,'webdriver',{get:()=>undefined});"
    "Object.defineProperty(navigator,'plugins',{get:()=>[1,2,3,4,5]});"
    "Object.defineProperty(navigator,'languages',{get:()=>['en-US','en']});"
    "window.chrome=window.chrome||{runtime:{}};"
    # mimeTypes: length is what gets read, so a plausible non-empty list is enough.
    "Object.defineProperty(navigator,'mimeTypes',{get:()=>[1,2,3,4]});"
    # WebGL: answer the two debug-renderer parameters with a common consumer GPU.
    # 37445/37446 are UNMASKED_VENDOR_WEBGL / UNMASKED_RENDERER_WEBGL - the pair every
    # fingerprinting script reads - so they are spoofed on BOTH webgl and webgl2.
    "(()=>{const V='Intel Inc.',R='Intel Iris OpenGL Engine';"
    "for(const C of [window.WebGLRenderingContext,window.WebGL2RenderingContext]){"
    "if(!C)continue;const g=C.prototype.getParameter;"
    "C.prototype.getParameter=function(p){"
    "if(p===37445)return V;if(p===37446)return R;return g.apply(this,arguments);};}})();"
)
_TYPE_DELAY_MS = (40, 140)  # per-character human typing cadence
_FIELD_PAUSE_MS = (250, 900)  # pause between fields / before submit
_SETTLE_MS = (1_800, 3_600)  # post-submit settle (replaces the old fixed 2s)


def _parse_proxy(url: str) -> dict[str, str]:
    """Playwright wants proxy auth SPLIT from the server URL, not inline.
    ``chromium.launch(proxy={"server": "http://user:pass@host:port"})`` silently
    IGNORES the embedded credentials → the upstream proxy refuses the tunnel and
    every ``goto`` hangs to timeout (this looked like a "dead proxy" but the proxy
    was fine). Parse into ``server`` + ``username`` + ``password`` so auth is sent."""
    from urllib.parse import urlparse

    u = urlparse(url)
    scheme = u.scheme or "http"
    server = f"{scheme}://{u.hostname}:{u.port}" if u.port else f"{scheme}://{u.hostname}"
    out: dict[str, str] = {"server": server}
    if u.username:
        out["username"] = u.username
    if u.password:
        out["password"] = u.password
    return out


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


# A spec source that is CONSULTED PER JOB rather than held as a dict. This is what lets
# the whitelist live in Postgres (`directory_specs`, 0108) instead of in this module: the
# bot asks for one directory's spec at submit time and gets it only if that row is active,
# verified, proven live and un-drifted. Returning None means "not earned yet", which is a
# refusal to submit - never a fallback to the module catalogue below.
SpecLoader = Callable[["CitationJob"], "FormSpec | None"]


def form_spec_from_json(directory_name: str, payload: Mapping[str, Any]) -> FormSpec:
    """Rebuild a :class:`FormSpec` from a ``directory_specs.spec`` jsonb payload.

    Pure and DB-free so it is unit-testable without Postgres, and so the JSON shape has
    exactly one reader. The DB already enforced the shape (0108's `directory_specs_shape`
    CHECK: https url, >=1 field, a submit selector, a success indicator), so this does not
    re-validate it - a KeyError here would mean the constraint was bypassed.
    """
    cap = payload.get("captcha")
    return FormSpec(
        directory_name=directory_name,
        url=str(payload["url"]),
        fields=tuple(
            FormField(str(f["selector"]), str(f["value_key"])) for f in payload["fields"]
        ),
        submit_selector=str(payload["submit_selector"]),
        success_indicator=str(payload["success_indicator"]),
        captcha=(
            CaptchaWidget(
                kind=str(cap["kind"]),
                site_key_selector=str(cap["site_key_selector"]),
                site_key_attr=str(cap.get("site_key_attr", "data-sitekey")),
                response_field_name=str(cap.get("response_field_name", "g-recaptcha-response")),
            )
            if isinstance(cap, Mapping)
            else None
        ),
    )


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
        # Richer identity beyond NAP (0060) - a FormSpec field can reference any of these.
        "description": job.description,
        "email": job.email,
        "logo_url": job.logo_url,
        "facebook_url": job.facebook_url,
        "instagram_url": job.instagram_url,
        "linkedin_url": job.linkedin_url,
        "tagline": job.tagline,
        "service_area": job.service_area,
        "year_founded": str(job.year_founded) if job.year_founded is not None else "",
        "payment_types": ", ".join(job.payment_types),
        "hours": "; ".join(f"{day}: {span}" for day, span in job.hours.items()),
    }
    return fields.get(key, "")


# --------------------------------------------------------------------------- #
# THE IMPORT SEED - NOT THE RUNTIME WHITELIST. Since 0108 the bot drives only rows in
# `public.directory_specs` that a human verified against the live DOM and that produced
# a real listing URL. This dict is no longer consulted at submit time; it is the corpus
# `app.cli.citation_specs_import` loads into that table as `active = false` candidates,
# so the operator's verification queue starts from the work already done here.
#
# It is kept because the selectors are a genuine starting point, and DELIBERATELY not
# treated as coverage: R1 §3 measured these 50 URLs and found 29 x 403, 8 x 404, 6 dead
# hosts and 7 x 2xx, with zero ever proven to produce a listing. That is why importing
# every entry below yields exactly ZERO bot-drivable directories until each is earned.
#
# A bot_fillable slice spanning every market (US/UK/CA/AU + the GLOBAL layer), all plain
# web forms, no CAPTCHA, per db/migrations/0046_directories_seed.sql. The dict key +
# `directory_name` are the EXACT seed `name` strings so a queued row lines up - note 7 of
# them (Cybo, EnrollBusiness, n49, Opendi, Storeboard, Tupalo, Tuugo) match TWO catalogue
# rows each on different markets, so the importer requires a market to disambiguate.
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
    # --- GLOBAL --------------------------------------------------------------- #
    "Superpages / YP Network (Thryv)": FormSpec(
        directory_name="Superpages / YP Network (Thryv)",
        url="https://www.superpages.com/add-business",
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
    # --- US: more general long-tail ------------------------------------------- #
    "Tupalo": FormSpec(
        directory_name="Tupalo",
        url="https://www.tupalo.com/en/add-business",
        fields=(
            FormField("input[name='name']", "business_name"),
            FormField("input[name='street']", "address_line1"),
            FormField("input[name='city']", "city"),
            FormField("input[name='zipcode']", "postal_code"),
            FormField("input[name='phone']", "phone"),
            FormField("input[name='website']", "website_url"),
        ),
        submit_selector="button[type='submit']",
        success_indicator="text=thank you",
    ),
    "YellowBot": FormSpec(
        directory_name="YellowBot",
        url="https://www.yellowbot.com/add",
        fields=(
            FormField("input[name='name']", "business_name"),
            FormField("input[name='address']", "address_line1"),
            FormField("input[name='city']", "city"),
            FormField("input[name='state']", "region"),
            FormField("input[name='zip']", "postal_code"),
            FormField("input[name='phone']", "phone"),
        ),
        submit_selector="button[type='submit']",
        success_indicator="text=added",
    ),
    "Judy's Book": FormSpec(
        directory_name="Judy's Book",
        url="https://www.judysbook.com/add-business",
        fields=(
            FormField("input[name='business_name']", "business_name"),
            FormField("input[name='address']", "address_line1"),
            FormField("input[name='city']", "city"),
            FormField("input[name='state']", "region"),
            FormField("input[name='phone']", "phone"),
            FormField("input[name='website']", "website_url"),
        ),
        submit_selector="button[type='submit']",
        success_indicator="text=thank you",
    ),
    "Infobel": FormSpec(
        directory_name="Infobel",
        url="https://www.infobel.com/en/add-business",
        fields=(
            FormField("input[name='companyName']", "business_name"),
            FormField("input[name='address']", "address_line1"),
            FormField("input[name='city']", "city"),
            FormField("input[name='zip']", "postal_code"),
            FormField("input[name='phone']", "phone"),
            FormField("input[name='email']", "email"),
        ),
        submit_selector="button[type='submit']",
        success_indicator="text=submitted",
    ),
    "EnrollBusiness": FormSpec(
        directory_name="EnrollBusiness",
        url="https://www.enrollbusiness.com/AddBusiness",
        fields=(
            FormField("input[name='company']", "business_name"),
            FormField("input[name='address']", "address_line1"),
            FormField("input[name='city']", "city"),
            FormField("input[name='phone']", "phone"),
            FormField("input[name='website']", "website_url"),
            FormField("textarea[name='description']", "description"),
        ),
        submit_selector="button[type='submit']",
        success_indicator="text=thank you",
    ),
    "MyHuckleberry": FormSpec(
        directory_name="MyHuckleberry",
        url="https://www.myhuckleberry.com/AddListing.aspx",
        fields=(
            FormField("input[name='BusinessName']", "business_name"),
            FormField("input[name='Address']", "address_line1"),
            FormField("input[name='City']", "city"),
            FormField("input[name='Phone']", "phone"),
        ),
        submit_selector="input[type='submit']",
        success_indicator="text=added",
    ),
    "n49": FormSpec(
        directory_name="n49",
        url="https://www.n49.com/add-business/",
        fields=(
            FormField("input[name='business_name']", "business_name"),
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
    "Opendi": FormSpec(
        directory_name="Opendi",
        url="https://www.opendi.us/add-business/",
        fields=(
            FormField("input[name='companyName']", "business_name"),
            FormField("input[name='street']", "address_line1"),
            FormField("input[name='city']", "city"),
            FormField("input[name='zip']", "postal_code"),
            FormField("input[name='phone']", "phone"),
            FormField("input[name='website']", "website_url"),
        ),
        submit_selector="button[type='submit']",
        success_indicator="text=thank you",
    ),
    "Tuugo": FormSpec(
        directory_name="Tuugo",
        url="https://www.tuugo.us/add-business/",
        fields=(
            FormField("input[name='name']", "business_name"),
            FormField("input[name='address']", "address_line1"),
            FormField("input[name='city']", "city"),
            FormField("input[name='phone']", "phone"),
            FormField("input[name='website']", "website_url"),
        ),
        submit_selector="button[type='submit']",
        success_indicator="text=thank you",
    ),
    "Apsense": FormSpec(
        directory_name="Apsense",
        url="https://www.apsense.com/register",
        fields=(
            FormField("input[name='businessName']", "business_name"),
            FormField("input[name='email']", "email"),
            FormField("input[name='phone']", "phone"),
            FormField("input[name='website']", "website_url"),
        ),
        submit_selector="button[type='submit']",
        success_indicator="text=welcome",
    ),
    "Yellow.place": FormSpec(
        directory_name="Yellow.place",
        url="https://yellow.place/en/add-place",
        fields=(
            FormField("input[name='name']", "business_name"),
            FormField("input[name='address']", "address_line1"),
            FormField("input[name='city']", "city"),
            FormField("input[name='phone']", "phone"),
            FormField("input[name='website']", "website_url"),
        ),
        submit_selector="button[type='submit']",
        success_indicator="text=thank you",
    ),
    "AGreaterTown": FormSpec(
        directory_name="AGreaterTown",
        url="https://www.agreatertown.com/add-listing",
        fields=(
            FormField("input[name='business_name']", "business_name"),
            FormField("input[name='address']", "address_line1"),
            FormField("input[name='city']", "city"),
            FormField("input[name='state']", "region"),
            FormField("input[name='phone']", "phone"),
        ),
        submit_selector="button[type='submit']",
        success_indicator="text=added",
    ),
    "FindIt": FormSpec(
        directory_name="FindIt",
        url="https://www.findit.com/signup",
        fields=(
            FormField("input[name='businessName']", "business_name"),
            FormField("input[name='address']", "address_line1"),
            FormField("input[name='city']", "city"),
            FormField("input[name='state']", "region"),
            FormField("input[name='phone']", "phone"),
            FormField("input[name='email']", "email"),
        ),
        submit_selector="button[type='submit']",
        success_indicator="text=welcome",
    ),
    # --- US: niche/vertical (bot_fillable per the seed) ----------------------- #
    "Justia (Lawyers)": FormSpec(
        directory_name="Justia (Lawyers)",
        url="https://lawyers.justia.com/signup",
        fields=(
            FormField("input[name='firm_name']", "business_name"),
            FormField("input[name='address']", "address_line1"),
            FormField("input[name='city']", "city"),
            FormField("input[name='state']", "region"),
            FormField("input[name='phone']", "phone"),
            FormField("input[name='email']", "email"),
        ),
        submit_selector="button[type='submit']",
        success_indicator="text=thank you",
    ),
    "Houzz": FormSpec(
        directory_name="Houzz",
        url="https://www.houzz.com/pro/signup",
        fields=(
            FormField("input[name='businessName']", "business_name"),
            FormField("input[name='city']", "city"),
            FormField("input[name='state']", "region"),
            FormField("input[name='phone']", "phone"),
            FormField("input[name='website']", "website_url"),
            FormField("textarea[name='description']", "description"),
        ),
        submit_selector="button[type='submit']",
        success_indicator="text=welcome",
    ),
    "MenuPix": FormSpec(
        directory_name="MenuPix",
        url="https://www.menupix.com/add-restaurant",
        fields=(
            FormField("input[name='restaurant_name']", "business_name"),
            FormField("input[name='address']", "address_line1"),
            FormField("input[name='city']", "city"),
            FormField("input[name='state']", "region"),
            FormField("input[name='phone']", "phone"),
        ),
        submit_selector="button[type='submit']",
        success_indicator="text=thank you",
    ),
    "Wellness.com": FormSpec(
        directory_name="Wellness.com",
        url="https://www.wellness.com/add-listing",
        fields=(
            FormField("input[name='name']", "business_name"),
            FormField("input[name='address']", "address_line1"),
            FormField("input[name='city']", "city"),
            FormField("input[name='state']", "region"),
            FormField("input[name='phone']", "phone"),
        ),
        submit_selector="button[type='submit']",
        success_indicator="text=added",
    ),
    # --- UK ------------------------------------------------------------------- #
    "Thomson Local": FormSpec(
        directory_name="Thomson Local",
        url="https://www.thomsonlocal.com/add-your-business",
        fields=(
            FormField("input[name='businessName']", "business_name"),
            FormField("input[name='address']", "address_line1"),
            FormField("input[name='town']", "city"),
            FormField("input[name='postcode']", "postal_code"),
            FormField("input[name='phone']", "phone"),
            FormField("input[name='website']", "website_url"),
        ),
        submit_selector="button[type='submit']",
        success_indicator="text=thank you",
    ),
    "FreeIndex": FormSpec(
        directory_name="FreeIndex",
        url="https://www.freeindex.co.uk/add.htm",
        fields=(
            FormField("input[name='company']", "business_name"),
            FormField("input[name='address']", "address_line1"),
            FormField("input[name='town']", "city"),
            FormField("input[name='postcode']", "postal_code"),
            FormField("input[name='telephone']", "phone"),
        ),
        submit_selector="input[type='submit']",
        success_indicator="text=added",
    ),
    "Scoot": FormSpec(
        directory_name="Scoot",
        url="https://www.scoot.co.uk/add-business",
        fields=(
            FormField("input[name='name']", "business_name"),
            FormField("input[name='address']", "address_line1"),
            FormField("input[name='town']", "city"),
            FormField("input[name='postcode']", "postal_code"),
            FormField("input[name='phone']", "phone"),
        ),
        submit_selector="button[type='submit']",
        success_indicator="text=thank you",
    ),
    "Cylex UK": FormSpec(
        directory_name="Cylex UK",
        url="https://www.cylex-uk.co.uk/add-company",
        fields=(
            FormField("input[name='companyName']", "business_name"),
            FormField("input[name='street']", "address_line1"),
            FormField("input[name='city']", "city"),
            FormField("input[name='postcode']", "postal_code"),
            FormField("input[name='phone']", "phone"),
            FormField("input[name='website']", "website_url"),
        ),
        submit_selector="button[type='submit']",
        success_indicator="text=success",
    ),
    "192.com": FormSpec(
        directory_name="192.com",
        url="https://www.192.com/businesses/add/",
        fields=(
            FormField("input[name='businessName']", "business_name"),
            FormField("input[name='address']", "address_line1"),
            FormField("input[name='town']", "city"),
            FormField("input[name='postcode']", "postal_code"),
            FormField("input[name='phone']", "phone"),
        ),
        submit_selector="button[type='submit']",
        success_indicator="text=thank you",
    ),
    "Hotfrog UK": FormSpec(
        directory_name="Hotfrog UK",
        url="https://www.hotfrog.co.uk/AddYourBusiness",
        fields=(
            FormField("input[name='businessName']", "business_name"),
            FormField("input[name='address']", "address_line1"),
            FormField("input[name='town']", "city"),
            FormField("input[name='postcode']", "postal_code"),
            FormField("input[name='phone']", "phone"),
            FormField("input[name='url']", "website_url"),
        ),
        submit_selector="button[type='submit']",
        success_indicator="text=thank you",
    ),
    "Applegate": FormSpec(
        directory_name="Applegate",
        url="https://www.applegate.co.uk/add-your-business",
        fields=(
            FormField("input[name='companyName']", "business_name"),
            FormField("input[name='address']", "address_line1"),
            FormField("input[name='town']", "city"),
            FormField("input[name='postcode']", "postal_code"),
            FormField("input[name='phone']", "phone"),
            FormField("input[name='website']", "website_url"),
            FormField("textarea[name='description']", "description"),
        ),
        submit_selector="button[type='submit']",
        success_indicator="text=thank you",
    ),
    # --- Canada --------------------------------------------------------------- #
    "411.ca": FormSpec(
        directory_name="411.ca",
        url="https://411.ca/business/add",
        fields=(
            FormField("input[name='name']", "business_name"),
            FormField("input[name='address']", "address_line1"),
            FormField("input[name='city']", "city"),
            FormField("input[name='province']", "region"),
            FormField("input[name='postal']", "postal_code"),
            FormField("input[name='phone']", "phone"),
        ),
        submit_selector="button[type='submit']",
        success_indicator="text=thank you",
    ),
    "Ourbis": FormSpec(
        directory_name="Ourbis",
        url="https://www.ourbis.ca/en/add-business",
        fields=(
            FormField("input[name='companyName']", "business_name"),
            FormField("input[name='address']", "address_line1"),
            FormField("input[name='city']", "city"),
            FormField("input[name='province']", "region"),
            FormField("input[name='phone']", "phone"),
        ),
        submit_selector="button[type='submit']",
        success_indicator="text=added",
    ),
    "ProfileCanada": FormSpec(
        directory_name="ProfileCanada",
        url="https://www.profilecanada.com/addcompany.cfm",
        fields=(
            FormField("input[name='company']", "business_name"),
            FormField("input[name='address']", "address_line1"),
            FormField("input[name='city']", "city"),
            FormField("input[name='province']", "region"),
            FormField("input[name='postal']", "postal_code"),
            FormField("input[name='phone']", "phone"),
        ),
        submit_selector="input[type='submit']",
        success_indicator="text=thank you",
    ),
    "Weblocal.ca": FormSpec(
        directory_name="Weblocal.ca",
        url="https://www.weblocal.ca/add-business.html",
        fields=(
            FormField("input[name='name']", "business_name"),
            FormField("input[name='address']", "address_line1"),
            FormField("input[name='city']", "city"),
            FormField("input[name='province']", "region"),
            FormField("input[name='phone']", "phone"),
        ),
        submit_selector="button[type='submit']",
        success_indicator="text=thank you",
    ),
    "Cylex Canada": FormSpec(
        directory_name="Cylex Canada",
        url="https://www.cylex-canada.ca/add-company",
        fields=(
            FormField("input[name='companyName']", "business_name"),
            FormField("input[name='street']", "address_line1"),
            FormField("input[name='city']", "city"),
            FormField("input[name='province']", "region"),
            FormField("input[name='postal']", "postal_code"),
            FormField("input[name='phone']", "phone"),
            FormField("input[name='website']", "website_url"),
        ),
        submit_selector="button[type='submit']",
        success_indicator="text=success",
    ),
    "Canadian Business Directory": FormSpec(
        directory_name="Canadian Business Directory",
        url="https://www.canadianbusinessdirectory.ca/add-business",
        fields=(
            FormField("input[name='company']", "business_name"),
            FormField("input[name='address']", "address_line1"),
            FormField("input[name='city']", "city"),
            FormField("input[name='province']", "region"),
            FormField("input[name='postal']", "postal_code"),
            FormField("input[name='phone']", "phone"),
        ),
        submit_selector="button[type='submit']",
        success_indicator="text=thank you",
    ),
    # --- Australia ------------------------------------------------------------ #
    "True Local": FormSpec(
        directory_name="True Local",
        url="https://www.truelocal.com.au/add-business",
        fields=(
            FormField("input[name='businessName']", "business_name"),
            FormField("input[name='address']", "address_line1"),
            FormField("input[name='suburb']", "city"),
            FormField("input[name='state']", "region"),
            FormField("input[name='postcode']", "postal_code"),
            FormField("input[name='phone']", "phone"),
        ),
        submit_selector="button[type='submit']",
        success_indicator="text=thank you",
    ),
    "StartLocal": FormSpec(
        directory_name="StartLocal",
        url="https://www.startlocal.com.au/addbusiness/",
        fields=(
            FormField("input[name='business_name']", "business_name"),
            FormField("input[name='address']", "address_line1"),
            FormField("input[name='suburb']", "city"),
            FormField("input[name='state']", "region"),
            FormField("input[name='postcode']", "postal_code"),
            FormField("input[name='phone']", "phone"),
        ),
        submit_selector="button[type='submit']",
        success_indicator="text=submitted",
    ),
    "Aussie Web": FormSpec(
        directory_name="Aussie Web",
        url="https://www.aussieweb.com.au/addlisting.aspx",
        fields=(
            FormField("input[name='BusinessName']", "business_name"),
            FormField("input[name='Address']", "address_line1"),
            FormField("input[name='Suburb']", "city"),
            FormField("input[name='State']", "region"),
            FormField("input[name='Phone']", "phone"),
        ),
        submit_selector="input[type='submit']",
        success_indicator="text=thank you",
    ),
    "Local.com.au": FormSpec(
        directory_name="Local.com.au",
        url="https://www.local.com.au/add-business/",
        fields=(
            FormField("input[name='name']", "business_name"),
            FormField("input[name='address']", "address_line1"),
            FormField("input[name='suburb']", "city"),
            FormField("input[name='state']", "region"),
            FormField("input[name='postcode']", "postal_code"),
            FormField("input[name='phone']", "phone"),
        ),
        submit_selector="button[type='submit']",
        success_indicator="text=thank you",
    ),
    "White Pages Australia": FormSpec(
        directory_name="White Pages Australia",
        url="https://www.whitepages.com.au/add-business",
        fields=(
            FormField("input[name='businessName']", "business_name"),
            FormField("input[name='address']", "address_line1"),
            FormField("input[name='suburb']", "city"),
            FormField("input[name='state']", "region"),
            FormField("input[name='postcode']", "postal_code"),
            FormField("input[name='phone']", "phone"),
        ),
        submit_selector="button[type='submit']",
        success_indicator="text=thank you",
    ),
    "Cylex Australia": FormSpec(
        directory_name="Cylex Australia",
        url="https://www.cylex.com.au/add-company",
        fields=(
            FormField("input[name='companyName']", "business_name"),
            FormField("input[name='street']", "address_line1"),
            FormField("input[name='suburb']", "city"),
            FormField("input[name='postcode']", "postal_code"),
            FormField("input[name='phone']", "phone"),
            FormField("input[name='website']", "website_url"),
        ),
        submit_selector="button[type='submit']",
        success_indicator="text=success",
    ),
    "Local Search": FormSpec(
        directory_name="Local Search",
        url="https://www.localsearch.com.au/add-business",
        fields=(
            FormField("input[name='businessName']", "business_name"),
            FormField("input[name='address']", "address_line1"),
            FormField("input[name='suburb']", "city"),
            FormField("input[name='state']", "region"),
            FormField("input[name='postcode']", "postal_code"),
            FormField("input[name='phone']", "phone"),
        ),
        submit_selector="button[type='submit']",
        success_indicator="text=thank you",
    ),
}


class PlaywrightCitationSubmitter:
    """Real ``CitationSubmitter`` driving a headless Chromium session per submit.

    Spec resolution has TWO mutually exclusive sources and NO default catalogue:
    ``specs`` is an explicit in-memory dict (tests inject a tiny fixture spec; the signup
    engine passes ``{}``), and ``spec_loader`` is the production source - a per-job
    callable backed by `public.directory_specs` (0108) that returns a spec only for a
    directory that has EARNED the automated route. With neither set the bot has no specs
    and submits nothing, which is the correct fail-closed default: an unconfigured bot
    must refuse, never fall back to the unverified ``FORM_SPECS`` seed.

    ``captcha_solver`` is required only for
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
        spec_loader: SpecLoader | None = None,
        captcha_solver: CaptchaSolver | None = None,
        proxy_url: str | None = None,
        screenshot_dir: str | None = None,
        headless: bool = True,
        rng_seed: int | None = None,
    ) -> None:
        try:
            import playwright.sync_api  # noqa: F401
        except ImportError as exc:
            raise ProviderNotConfiguredError(f"Playwright citation bot unavailable: {_INSTALL_HINT}") from exc
        # NOT `specs or FORM_SPECS`: the signup engine passes {} deliberately, and an
        # empty dict must stay empty rather than silently inherit 50 unverified specs.
        self._specs = specs
        self._spec_loader = spec_loader
        self._captcha_solver = captcha_solver
        self._proxy_url = proxy_url
        self._screenshot_dir = Path(screenshot_dir) if screenshot_dir else None
        self._headless = headless
        # Per-submitter RNG drives the anti-detection variety (fingerprint + delays).
        # ``rng_seed`` is for deterministic tests only; production leaves it None so
        # every run picks a fresh, unpredictable fingerprint.
        self._rng = random.Random(rng_seed)

    def submit(self, job: CitationJob) -> CitationSubmitResult:
        spec = self._spec_for(job)
        if spec is None:
            # Deliberately NOT retried and NOT a crash: there is no verified spec for this
            # directory, so there is nothing to attempt. R1 req 29 renders this to the
            # client as skip_reason='no_verified_spec' rather than a silent absence.
            return CitationSubmitResult(
                status="failed", error=f"no active verified FormSpec for {job.directory_name!r}"
            )
        if spec.captcha is not None and self._captcha_solver is None:
            return CitationSubmitResult(
                status="blocked", error="captcha_assisted directory but no CAPTCHA solver configured"
            )

        try:
            with self._browser_session(job.directory_name) as context:
                return self._run(context, spec, job)
        except Exception as exc:  # a form/selector drift must fail cleanly, never crash the worker
            logger.warning("citation_bot_submit_failed", directory=job.directory_name, error=str(exc))
            return CitationSubmitResult(status="failed", error=str(exc)[:500])

    def can_submit(self, job: CitationJob) -> bool:
        """Whether an EARNED spec exists for this job, WITHOUT submitting anything.

        The worker asks this before the cost gate. With the whitelist starting empty,
        "no spec" is the common answer, and discovering it after the gate had charged
        would bill a client for a submission that could not physically happen."""
        return self._spec_for(job) is not None

    def _spec_for(self, job: CitationJob) -> FormSpec | None:
        """The one place a spec is resolved. An injected ``specs`` dict wins (tests and
        the signup engine); otherwise the DB whitelist is consulted per job. There is no
        third fallback - if neither source has it, the bot does not submit."""
        if self._specs is not None:
            return self._specs.get(job.directory_name)
        if self._spec_loader is not None:
            return self._spec_loader(job)
        return None

    @contextmanager
    def _browser_session(self, directory: str) -> Iterator[Any]:
        """A stealth Chromium browser CONTEXT (fresh randomized fingerprint, webdriver
        mask, optional proxy), opened and reliably torn down. Factored out of ``submit``
        so BOTH the no-signup bot and the signup flow (``citation_signup``) drive an
        identically-hardened session -- the anti-detection lives in one place."""
        from playwright.sync_api import sync_playwright

        # Stealth launch args strip the "controlled by automated test software" tells.
        launch_kwargs: dict[str, object] = {
            "headless": self._headless,
            "args": list(_STEALTH_LAUNCH_ARGS),
        }
        if self._proxy_url:
            launch_kwargs["proxy"] = _parse_proxy(self._proxy_url)  # split auth (see _parse_proxy)
        with sync_playwright() as pw:
            # launch_kwargs is intentionally dict[str, object] (heterogeneous values);
            # Playwright's launch() has many precisely-typed keyword params, so widen
            # to Any at the **unpack boundary rather than loosen the dict's own type.
            browser = pw.chromium.launch(**cast("dict[str, Any]", launch_kwargs))
            # A fresh randomized fingerprint per run: UA + viewport + locale/timezone.
            ua = self._rng.choice(_USER_AGENTS)
            vw, vh = self._rng.choice(_VIEWPORTS)
            locale, tz = self._rng.choice(_LOCALES)
            context = browser.new_context(
                user_agent=ua,
                viewport={"width": vw, "height": vh},
                locale=locale,
                timezone_id=tz,
            )
            try:
                context.add_init_script(_STEALTH_INIT_JS)  # mask webdriver before page JS
            except Exception:  # a stealth step must never break an otherwise-valid submit
                logger.debug("stealth_init_script_failed", directory=directory)
            try:
                yield context
            finally:
                context.close()
                browser.close()

    def _run(self, context: Any, spec: FormSpec, job: CitationJob) -> CitationSubmitResult:
        page = context.new_page()
        page.goto(spec.url, wait_until="domcontentloaded", timeout=_NAV_TIMEOUT_MS)
        return self._fill_form(page, spec, job)

    def _fill_form(self, page: Any, spec: FormSpec, job: CitationJob) -> CitationSubmitResult:
        """Fill + submit ONE add-business FormSpec on an already-navigated page, then
        verify success. Reused by the signup flow's post-verify "add business" step."""
        for f in spec.fields:
            value = _job_value(job, f.value_key)
            if value:
                self._human_fill(page, f.selector, value)  # human-cadence typing, not fill()
                page.wait_for_timeout(self._rng.randint(*_FIELD_PAUSE_MS))
        if spec.captcha is not None:
            self._clear_captcha(page, spec.captcha)
        page.wait_for_timeout(self._rng.randint(*_FIELD_PAUSE_MS))  # settle before submit
        page.click(spec.submit_selector, timeout=_TIMEOUT_MS)
        page.wait_for_timeout(self._rng.randint(*_SETTLE_MS))
        proof_url = self._screenshot(page, job)
        if self._check_success(page, spec.success_indicator):
            return CitationSubmitResult(status="submitted", proof_url=proof_url)
        return CitationSubmitResult(status="failed", proof_url=proof_url, error="success indicator not found")

    def _human_fill(self, page: Any, selector: str, value: str) -> None:
        """Enter text like a person: focus the field, then type character-by-character
        with a randomized per-keystroke delay - instead of Playwright's instant
        ``fill()``, which sets ``.value`` in one shot and is a classic bot tell. Falls
        back to ``fill()`` if the human path throws (e.g. a click intercept), so anti-
        detection can never turn a valid submit into a failure."""
        delay = self._rng.randint(*_TYPE_DELAY_MS)
        try:
            page.click(selector, timeout=_TIMEOUT_MS)
            page.type(selector, value, delay=delay, timeout=_TIMEOUT_MS)
        except Exception:
            page.fill(selector, value, timeout=_TIMEOUT_MS)

    def _clear_captcha(self, page: Any, widget: CaptchaWidget) -> None:
        site_key = page.get_attribute(widget.site_key_selector, widget.site_key_attr, timeout=_TIMEOUT_MS)
        if not site_key:
            raise RuntimeError("could not read the CAPTCHA site key from the page")
        assert self._captcha_solver is not None  # guarded by submit() before this is ever called
        solution = self._captcha_solver.solve(
            CaptchaChallenge(kind=widget.kind, site_key=site_key, page_url=page.url)
        )
        # Write the token into the response field AND fire the widget's registered
        # callback. Token-injection alone is silently ignored by React/MUI forms that
        # validate via ``grecaptcha.getResponse()`` (they read the widget's internal
        # state, not the textarea) - so the submit fails even with a valid token. Walking
        # ``___grecaptcha_cfg.clients`` and invoking the ``callback`` flips that state.
        page.evaluate(
            """([name, token]) => {
                document.getElementsByName(name).forEach
                    ? document.getElementsByName(name).forEach(el => { el.value = token; })
                    : (() => { const el = document.getElementsByName(name)[0]; if (el) el.value = token; })();
                try {
                    const cfg = window.___grecaptcha_cfg;
                    if (cfg && cfg.clients) {
                        for (const cid in cfg.clients) {
                            const client = cfg.clients[cid];
                            for (const k in client) {
                                const o = client[k];
                                if (o && typeof o === 'object') {
                                    if (typeof o.callback === 'function') { o.callback(token); }
                                    for (const kk in o) {
                                        const inner = o[kk];
                                        if (inner && typeof inner === 'object' && typeof inner.callback === 'function') {
                                            inner.callback(token);
                                        }
                                    }
                                }
                            }
                        }
                    }
                } catch (e) { /* best-effort: many sites read the field directly */ }
            }""",
            [widget.response_field_name, solution.token],
        )

    def _screenshot(self, page: Any, job: CitationJob) -> str:
        """Capture the proof screenshot and return a RELATIVE KEY, never a path.

        This used to `return str(path)` - an absolute server path like
        /var/lib/aios/citations/ab12....png - which the worker writes straight into
        `citations.proof_url`. Two defects came out of that one line: a column named
        `*_url` held a filesystem path (so anything rendering it produced a dead link),
        and serialising that row to a dashboard response leaked the server's directory
        layout. The reporting layer then compounded it by publishing those strings to
        operators as "Live listings already earned".

        A key is resolved back to a path server-side by the guarded download route, the
        way the audit artifact routes already do it. The path itself never crosses the
        wire."""
        if self._screenshot_dir is None:
            return ""
        self._screenshot_dir.mkdir(parents=True, exist_ok=True)
        digest = hashlib.sha256(
            f"{job.directory_name}|{job.business_name}|{time.time()}".encode()
        ).hexdigest()[:16]
        key = f"{digest}.png"
        page.screenshot(path=str(self._screenshot_dir / key))
        return key

    def _check_success(self, page: Any, indicator: str) -> bool:
        if indicator.startswith("text="):
            return indicator[5:].lower() in page.content().lower()
        try:
            return bool(page.locator(indicator).count())
        except Exception:
            return False


def citation_bot_from_settings(
    settings: Settings,
    *,
    captcha_solver: CaptchaSolver | None,
    spec_loader: SpecLoader | None = None,
    route: str = "",
) -> PlaywrightCitationSubmitter | None:
    """The self-hosted bot, or ``None`` when Playwright is not installed (degraded -
    a bot_fillable/captcha_assisted job HOLDS rather than crashing the worker).
    ``captcha_solver`` is passed in (built once per worker call by the caller, which
    already knows whether a key is configured) rather than resolved here.

    ``spec_loader`` is the 0108 whitelist reader. Left None the bot has NO specs and
    submits nothing - the fail-closed default, so a caller that forgets to wire the
    whitelist gets zero submissions rather than 50 unverified ones.

    ``route`` suppresses the proxy on Route B (R1 req 17). Route B is by definition an
    undefended open form: if it starts answering 403 or presenting a CAPTCHA it has
    BECOME Route C, and that is a route change to record, not proxy bandwidth to buy.
    Spending residential-proxy budget on Route B would also quietly break the ~$0.002
    compute-only cost model that justifies the route."""
    proxy = settings.citation_proxy_url.get_secret_value() if settings.citation_proxy_url else None
    if route == "B" and proxy:
        logger.info("citation_bot_proxy_ignored_on_route_b", reason="route_b_is_undefended")
        proxy = None
    try:
        return PlaywrightCitationSubmitter(
            captcha_solver=captcha_solver,
            spec_loader=spec_loader,
            proxy_url=proxy,
            screenshot_dir=settings.citation_artifact_dir,
        )
    except ProviderNotConfiguredError:
        logger.info("citation_bot_degraded", reason="playwright_not_installed")
        return None


def db_spec_loader(job: CitationJob) -> FormSpec | None:
    """A ``SpecLoader`` over the 0108 whitelist: the ACTIVE spec for one directory.

    Per-job rather than a snapshot loaded at factory time, so activating or deactivating
    a spec takes effect on the next submission instead of the next worker restart - which
    matters because deactivation is how drift is contained.

    NEVER RAISES. An unreachable database, or a schema predating 0108, yields ``None`` -
    the bot then submits nothing. That is the correct direction to fail; the alternative
    is a worker that crashes on every citation, and the alternative to THAT is falling
    back to the unverified in-code catalogue, which is the behaviour this whitelist
    exists to end."""
    specs = active_form_specs(directory_name=job.directory_name)
    return specs.get(job.directory_name)


def active_form_specs(*, directory_name: str | None = None) -> dict[str, FormSpec]:
    """The EARNED whitelist: every directory with an active, verified spec.

    Reads `directory_specs` (0108) joined to the catalogue, keyed by directory name
    because that is what a `CitationJob` carries. Runs on the privileged connection: the
    worker has no user identity, and the whitelist is reference data rather than tenant
    data.

    NEVER RAISES. A database that is unreachable, or a schema that predates 0108, yields
    an EMPTY whitelist - which means the bot submits nothing. That is the correct
    direction to fail: the alternative is a worker that crashes on every citation, and
    the alternative to *that* is falling back to the unverified in-code catalogue, which
    is the exact behaviour this whitelist exists to end.
    """
    try:
        from app.db.database import privileged_connection
    except Exception:  # pragma: no cover - import-time environment problem
        return {}
    try:
        with privileged_connection() as cur:
            if directory_name is None:
                cur.execute(
                    "select d.name as directory_name, s.spec "
                    "from public.directory_specs s "
                    "join public.directories d on d.id = s.directory_id "
                    "where s.active"
                )
            else:
                cur.execute(
                    "select d.name as directory_name, s.spec "
                    "from public.directory_specs s "
                    "join public.directories d on d.id = s.directory_id "
                    "where s.active and d.name = %s",
                    (directory_name,),
                )
            rows = list(cur.fetchall())
    except Exception:
        logger.info("citation_specs_unavailable", reason="whitelist read failed; submitting nothing")
        return {}

    out: dict[str, FormSpec] = {}
    for row in rows:
        try:
            name = str(row["directory_name"])
            out[name] = _spec_from_json(dict(row["spec"]), name)
        except Exception:
            # One malformed row must not deny every other directory its verified spec.
            logger.warning("citation_spec_malformed", directory=str(row.get("directory_name")))
    return out


def _spec_from_json(raw: dict[str, Any], directory_name: str = "") -> FormSpec:
    """Rehydrate a stored spec into the dataclass the bot drives."""
    captcha_raw = raw.get("captcha")
    return FormSpec(
        directory_name=directory_name,
        url=str(raw["url"]),
        fields=tuple(
            FormField(selector=str(f["selector"]), value_key=str(f["value_key"]))
            for f in raw.get("fields", [])
        ),
        submit_selector=str(raw["submit_selector"]),
        success_indicator=str(raw.get("success_indicator", "")),
        captcha=(
            CaptchaWidget(
                kind=str(captcha_raw["kind"]),
                site_key_selector=str(captcha_raw.get("site_key_selector", "")),
                response_field_name=str(captcha_raw.get("response_field_name", "")),
            )
            if isinstance(captcha_raw, dict)
            else None
        ),
    )
