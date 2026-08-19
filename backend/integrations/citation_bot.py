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
from collections.abc import Iterator
from contextlib import contextmanager
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
_STEALTH_INIT_JS = (
    "Object.defineProperty(navigator,'webdriver',{get:()=>undefined});"
    "Object.defineProperty(navigator,'plugins',{get:()=>[1,2,3,4,5]});"
    "Object.defineProperty(navigator,'languages',{get:()=>['en-US','en']});"
    "window.chrome=window.chrome||{runtime:{}};"
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
# A bot_fillable slice spanning every market (US/UK/CA/AU + the GLOBAL layer); the
# shape extends unchanged to the rest of the catalog - see the module docstring. All
# plain web forms, no CAPTCHA, per db/migrations/0046_directories_seed.sql. The dict
# key + `directory_name` are the EXACT seed `name` strings so a queued row lines up.
# EVERY selector below is a best-effort starting spec, NOT hand-verified against the
# live DOM (the reference doc's "reconfirm before automating" caution, per site).
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
        rng_seed: int | None = None,
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
        # Per-submitter RNG drives the anti-detection variety (fingerprint + delays).
        # ``rng_seed`` is for deterministic tests only; production leaves it None so
        # every run picks a fresh, unpredictable fingerprint.
        self._rng = random.Random(rng_seed)

    def submit(self, job: CitationJob) -> CitationSubmitResult:
        spec = self._specs.get(job.directory_name)
        if spec is None:
            return CitationSubmitResult(status="failed", error=f"no FormSpec for {job.directory_name!r}")
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
            browser = pw.chromium.launch(**launch_kwargs)
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
