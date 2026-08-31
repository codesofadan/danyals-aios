"""Is this citation actually LIVE? The one question the module could not answer.

Before this file, `submitted` was the end of the road. Every write path we have returns
`submitted` honestly and none of them can promise more: Data Axle runs teleresearch for up
to three business days, Apple returns state SUBMITTED, Google requires verification before
a location is eligible for Search or Maps, and a form bot only ever knows that a page
changed after it pressed a button. None of those is a listing. So the reporting layer had
nothing true to count, reached for `proof_url` - a screenshot key - and published it to
operators under the heading "Live listings already earned".

The fix is not a better query. It is going and LOOKING: fetch the public URL and check
that the business is on the page. That is what `judge_liveness` decides, and it is the
only thing in this codebase permitted to move a row to `live`.

WHY THE CORE IS PURE. `judge_liveness` takes an already-fetched page and returns a verdict.
No network, no DB, no clock. That makes every branch - a soft-404 that returns 200, a
listing whose phone drifted, a page that is simply gone - unit-testable without a fixture
server, which is what keeps the ladder below honest as it grows.

WHAT THIS DELIBERATELY DOES NOT DO. It does not promote anything on a redirect to a
homepage, it does not accept a page that merely contains the directory's name, and it never
infers liveness from the absence of an error. A listing we cannot see is not live.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from app.modules.local_seo.service import normalize_nap_text, normalize_phone

# Strip tags, scripts and entities down to comparable visible text. This is a
# comparison-only reduction (never rendered), so a crude strip is correct and a real
# HTML parser would buy nothing but a dependency.
_SCRIPT_RE = re.compile(r"<(script|style|noscript)\b[^>]*>.*?</\1>", re.I | re.S)
_TAG_RE = re.compile(r"<[^>]+>")
_ENTITY_RE = re.compile(r"&(?:nbsp|amp|quot|#39|apos|lt|gt);")

# A name this short matches half the web ("Joe", "AB"). Requiring a couple of real
# tokens is what stops a generic category page from reading as a listing.
_MIN_NAME_TOKENS = 1
_MIN_NAME_CHARS = 4

# The verdicts this module can return. `submitted` means "still waiting, ask again" -
# it is NOT a failure, and it is the correct answer for a directory that has not
# published yet.
LIVE = "live"
DRIFTED = "drifted"
DELISTED = "delisted"
SUBMITTED = "submitted"


@dataclass(frozen=True)
class LivenessProbe:
    """One fetch of a candidate listing URL. `text` is the raw response body; an
    unreachable host is `status_code=None`, which is NOT the same as a 404."""

    status_code: int | None
    text: str = ""
    final_url: str = ""
    checked_from: str = ""
    screenshot_key: str = ""


@dataclass(frozen=True)
class LivenessVerdict:
    """What we concluded, and the receipt for it. `evidence` is stored verbatim on the
    citation row so "why is this live?" stays answerable a year from now, long after the
    page itself has changed."""

    status: str
    method: str = "http_probe"
    evidence: dict[str, Any] = field(default_factory=dict)

    @property
    def is_live(self) -> bool:
        return self.status == LIVE


def visible_text(html: str) -> str:
    """The page's comparable text: scripts/styles dropped, tags flattened, whitespace
    collapsed, lowercased. Normalised through the same `normalize_nap_text` the local-SEO
    module uses, so "123 Main St." on a page matches "123 Main Street" in our profile."""
    body = _SCRIPT_RE.sub(" ", html or "")
    body = _TAG_RE.sub(" ", body)
    body = _ENTITY_RE.sub(" ", body)
    return normalize_nap_text(body)


def _name_present(page_text: str, business_name: str) -> bool:
    """Whether the business's own name appears on the page.

    Guards against a name too short or too generic to mean anything: a two-character
    "name" would match nearly any page, and a page that matches anything proves nothing.
    """
    needle = normalize_nap_text(business_name)
    if len(needle) < _MIN_NAME_CHARS or len(needle.split()) < _MIN_NAME_TOKENS:
        return False
    return needle in page_text


def _phone_present(html: str, phone: str) -> bool:
    """Whether the canonical phone appears, comparing on significant digits only.

    Digits are read from the RAW html rather than the normalised text because
    `normalize_nap_text` collapses punctuation and a phone can legitimately be split
    across markup ("(555)<span> 010-9999</span>")."""
    canonical = normalize_phone(phone)
    if not canonical:
        return False
    page_digits = re.sub(r"\D", "", html or "")
    return canonical in page_digits


def judge_liveness(
    probe: LivenessProbe,
    *,
    business_name: str,
    phone: str = "",
    address_line1: str = "",
) -> LivenessVerdict:
    """Decide what a fetched page proves about a listing.

    The ladder, in order, and each rung is a different fact:

      * The host did not answer -> `submitted`. An unreachable host is OUR failure to
        look, not evidence the listing is gone. Delisting a client's citation because
        our own DNS blipped would be a fabrication in the opposite direction.
      * 4xx/5xx -> `delisted`. The directory answered and said there is nothing there.
      * 2xx but the business name is absent -> `delisted`. This is the soft-404 case,
        and it is the common one: a removed listing usually 301s to the directory's
        homepage, which returns a perfectly healthy 200.
      * 2xx, name present, but neither phone nor address matches -> `drifted`. The
        listing EXISTS - so it still covers that directory - but what it says about the
        business is wrong, and the fix is a correction, not a new submission.
      * 2xx, name present, and phone or address matches -> `live`.

    Requiring name AND one of phone/address is deliberate. A name alone is met by any
    page that merely mentions the business; a phone alone is met by a directory listing
    a completely different branch."""
    evidence: dict[str, Any] = {
        "http_status": probe.status_code,
        "final_url": probe.final_url,
        "checked_from": probe.checked_from,
        "screenshot_key": probe.screenshot_key,
        "matched_fields": [],
    }

    if probe.status_code is None:
        evidence["reason"] = "host did not answer; treated as unverified, not delisted"
        return LivenessVerdict(status=SUBMITTED, evidence=evidence)

    if not (200 <= probe.status_code < 300):
        evidence["reason"] = f"directory answered {probe.status_code}"
        return LivenessVerdict(status=DELISTED, evidence=evidence)

    page_text = visible_text(probe.text)
    if not _name_present(page_text, business_name):
        evidence["reason"] = (
            "page returned 2xx but does not contain the business name - a removed "
            "listing usually redirects to a healthy directory homepage"
        )
        return LivenessVerdict(status=DELISTED, evidence=evidence)

    matched: list[str] = ["business_name"]
    if phone and _phone_present(probe.text, phone):
        matched.append("phone")
    if address_line1 and normalize_nap_text(address_line1) in page_text:
        matched.append("address_line1")
    evidence["matched_fields"] = matched

    if len(matched) < 2:
        evidence["reason"] = "listing found, but neither phone nor address matches the canonical NAP"
        return LivenessVerdict(status=DRIFTED, evidence=evidence)

    return LivenessVerdict(status=LIVE, evidence=evidence)


# --------------------------------------------------------------------------- #
# Re-check cadence. Cheap enough (~$41/yr at 100 clients) that this is a quality
# decision, not a budget one - so a new listing is checked often while it is still
# settling, and an established one is checked at a rate that catches drift.
# --------------------------------------------------------------------------- #
NEW_LISTING_CADENCE_DAYS: tuple[int, ...] = (3, 14, 60)
CORE_CADENCE_DAYS = 30
STANDARD_CADENCE_DAYS = 90


def next_recheck_days(*, recheck_count: int, authority_tier: str = "", route: str = "") -> int:
    """How many days until this row should be looked at again.

    The first three checks walk the new-listing ladder (+3d, +14d, +60d): a submission
    is most likely to become live - or to be rejected - in its first fortnight, and
    that is exactly when a client asks. After that a route-A anchor or a `core` tier
    row is checked monthly because it is the one feeding everything downstream;
    everything else is quarterly."""
    if recheck_count < len(NEW_LISTING_CADENCE_DAYS):
        return NEW_LISTING_CADENCE_DAYS[recheck_count]
    if route.upper() == "A" or authority_tier == "core":
        return CORE_CADENCE_DAYS
    return STANDARD_CADENCE_DAYS


# --------------------------------------------------------------------------- #
# The real fetcher. Kept OUT of `judge_liveness` so the whole decision path stays
# pure and network-free under test; the worker injects this one in production.
# --------------------------------------------------------------------------- #
_PROBE_TIMEOUT_SECONDS = 15.0
_PROBE_MAX_BYTES = 2_000_000
# Identify honestly. A directory that would rather not be probed can then say so, and
# we are not pretending to be a person - this is a status check on a listing we built,
# not an attempt to look like organic traffic.
_PROBE_UA = "AIOS-CitationLivenessCheck/1.0 (+listing status verification)"


def http_liveness_probe(url: str) -> LivenessProbe:
    """GET a listing URL and return what came back. NEVER raises.

    Every failure mode collapses to `status_code=None`, which `judge_liveness` reads as
    "we could not look" and holds the row - deliberately NOT as `delisted`. Delisting a
    client's citation because of our own timeout would be a fabrication pointing the
    other way, and it is the more dangerous direction: it invents work to redo.

    Unauthenticated on purpose. A listing that only renders for a logged-in session is
    not publicly visible, and public visibility is the entire point of a citation."""
    import httpx

    try:
        with httpx.Client(
            follow_redirects=True,
            timeout=_PROBE_TIMEOUT_SECONDS,
            headers={"User-Agent": _PROBE_UA},
        ) as client:
            response = client.get(url)
            return LivenessProbe(
                status_code=response.status_code,
                text=response.text[:_PROBE_MAX_BYTES],
                final_url=str(response.url),
                checked_from="http_probe",
            )
    except Exception:
        # No logging of the exception body: a URL can carry a token in a query string.
        return LivenessProbe(status_code=None, checked_from="http_probe:unreachable")
