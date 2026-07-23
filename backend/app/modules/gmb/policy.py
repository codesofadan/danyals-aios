"""Wave 5: the Google Business Profile (GMB) post POLICY checker - a PURE, deterministic
gate that a generated GBP post must pass before a lead can approve or publish it.

Google Business Profile posts have hard content rules and strong best-practices. This
module encodes them as one checkable function (mirrors ``content_qa.score``'s role for
the content pipeline): given a post body + its call-to-action, it returns a
:class:`GbpPolicyReport` of ``violations`` (hard blocks - the post CANNOT go live) and
``warnings`` (advisories the reviewer should weigh). No I/O, no randomness, fully
deterministic, so it is unit-tested exhaustively.

The rules enforced (grounded in Google Business Profile content policy + post
best-practices):

* Hard blocks (``violations``): empty body; over the 1,500-character hard limit; any
  em/en dash (the client's absolute rule); prohibited content (offensive, adult,
  dangerous/illegal, regulated goods, harassment); an invalid CTA action type; a CTA
  that needs a link but has no valid http(s) URL.
* Advisories (``warnings``): over the ~300-char concise best-practice; no CTA at all;
  gimmicky ALL-CAPS or excessive punctuation; a phone number or URL embedded in the
  body (the profile fields / the CTA button carry those); a missing title on an
  offer/event post.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from app.services.content_guard import count_dashes

# --------------------------------------------------------------------------- #
# GBP limits + the valid call-to-action set.
# --------------------------------------------------------------------------- #
GBP_MAX_CHARS = 1500  # Google's hard character ceiling for a post body
GBP_RECOMMENDED_MAX = 300  # the concise best-practice length (a warning above this)
GBP_MIN_CHARS = 12  # anything shorter reads as an empty/placeholder post

# Valid GBP call-to-action action types (Google's LocalPost actionType set), plus the
# sentinel ``none`` (a post may legitimately carry no button).
CTA_TYPES: frozenset[str] = frozenset(
    {"book", "order", "shop", "learn_more", "sign_up", "call", "none"}
)
# CTAs that require a destination URL (every button except a phone call).
CTA_NEEDS_URL: frozenset[str] = frozenset({"book", "order", "shop", "learn_more", "sign_up"})

# Valid GBP post types.
POST_TYPES: frozenset[str] = frozenset({"update", "offer", "event", "product"})

# --------------------------------------------------------------------------- #
# Prohibited-content lexicon (curated, NOT exhaustive - a first-line screen; the human
# reviewer is the backstop). Grouped by the Google policy category each maps to.
# --------------------------------------------------------------------------- #
_PROHIBITED: dict[str, tuple[str, ...]] = {
    "adult": ("porn", "pornography", "xxx", "escort", "nude", "nudes"),
    "hate_harassment": ("slur", "kill yourself", "subhuman"),
    "dangerous_illegal": ("cocaine", "heroin", "meth", "counterfeit", "unlicensed firearm"),
    "regulated_goods": ("buy guns", "cheap cigarettes", "online casino", "vape deals"),
    "misleading": ("100% guaranteed cure", "miracle cure", "get rich quick", "risk-free investment"),
}

# Acronyms/short tokens that are legitimately upper-case (not gimmicky caps).
_CAPS_ALLOWLIST: frozenset[str] = frozenset(
    {"FAQ", "GBP", "SEO", "NAP", "USA", "LLC", "USD", "OK", "DIY", "HVAC", "ASAP"}
)

_URL_RE = re.compile(r"https?://\S+|\bwww\.\S+", re.IGNORECASE)
# A phone number: 7+ digits allowing spaces / dashes / parens / a leading +.
_PHONE_RE = re.compile(r"(?<!\w)(?:\+?\d[\d\-\s().]{6,}\d)(?!\w)")
_ALL_CAPS_WORD_RE = re.compile(r"\b[A-Z]{4,}\b")
_EXCESS_PUNCT_RE = re.compile(r"[!?]{3,}|!{2,}")


@dataclass(frozen=True)
class PolicyIssue:
    """One policy finding: a stable ``code``, a human ``message``, and a ``severity``
    (``violation`` hard-blocks; ``warning`` is advisory)."""

    code: str
    message: str
    severity: str  # "violation" | "warning"

    def as_dict(self) -> dict[str, str]:
        return {"code": self.code, "message": self.message, "severity": self.severity}


@dataclass(frozen=True)
class GbpPolicyReport:
    """The verdict for one GBP post.

    ``ok`` is True iff there are NO violations (warnings do not block). ``char_count``
    is the body length. ``issues`` carries every finding in order; ``violations`` /
    ``warnings`` are the split views the UI + the approve gate consume.
    """

    ok: bool
    char_count: int
    issues: list[PolicyIssue] = field(default_factory=list)

    @property
    def violations(self) -> list[PolicyIssue]:
        return [i for i in self.issues if i.severity == "violation"]

    @property
    def warnings(self) -> list[PolicyIssue]:
        return [i for i in self.issues if i.severity == "warning"]

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "charCount": self.char_count,
            "violations": [i.as_dict() for i in self.violations],
            "warnings": [i.as_dict() for i in self.warnings],
        }


def _prohibited_hits(low: str) -> list[str]:
    """The prohibited categories whose lexicon appears in the (lower-cased) body."""
    hits: list[str] = []
    for category, terms in _PROHIBITED.items():
        if any(term in low for term in terms):
            hits.append(category)
    return hits


def check_gbp_policy(
    body: str,
    *,
    cta_type: str = "none",
    cta_url: str = "",
    post_type: str = "update",
    title: str = "",
) -> GbpPolicyReport:
    """Check one GBP post against Google's content policy + best-practices (pure).

    Returns a :class:`GbpPolicyReport`; ``report.ok`` is the hard approve/publish gate
    (no violations). Deterministic - same inputs always yield the same verdict.
    """
    text = body.strip()
    char_count = len(text)
    issues: list[PolicyIssue] = []

    # --- hard blocks (violations) --------------------------------------------
    if not text:
        issues.append(PolicyIssue("empty", "The post body is empty.", "violation"))
    elif char_count > GBP_MAX_CHARS:
        issues.append(PolicyIssue(
            "too_long", f"Post is {char_count} characters; the GBP limit is {GBP_MAX_CHARS}.", "violation"
        ))

    em, en = count_dashes(text)
    if em or en:
        issues.append(PolicyIssue(
            "forbidden_dash", f"Post contains {em} em / {en} en dash(es); use plain punctuation.", "violation"
        ))

    prohibited = _prohibited_hits(text.lower())
    if prohibited:
        issues.append(PolicyIssue(
            "prohibited_content",
            f"Post may contain content Google prohibits ({', '.join(prohibited)}).",
            "violation",
        ))

    if cta_type not in CTA_TYPES:
        issues.append(PolicyIssue(
            "invalid_cta", f"'{cta_type}' is not a valid GBP call-to-action.", "violation"
        ))
    elif cta_type in CTA_NEEDS_URL:
        url = cta_url.strip()
        if not url:
            issues.append(PolicyIssue(
                "cta_url_missing", f"A '{cta_type}' button needs a destination URL.", "violation"
            ))
        elif not re.match(r"^https?://\S+$", url):
            issues.append(PolicyIssue(
                "cta_url_invalid", "The call-to-action URL must be a valid http(s) link.", "violation"
            ))

    # --- advisories (warnings) -----------------------------------------------
    if 0 < char_count < GBP_MIN_CHARS:
        issues.append(PolicyIssue(
            "very_short", f"Post is only {char_count} characters; add a little more detail.", "warning"
        ))
    if char_count > GBP_RECOMMENDED_MAX:
        issues.append(PolicyIssue(
            "long_for_gbp",
            f"Post is {char_count} characters; GBP posts read best under {GBP_RECOMMENDED_MAX}.",
            "warning",
        ))
    if cta_type == "none":
        issues.append(PolicyIssue("no_cta", "No call-to-action; a clear next step lifts engagement.", "warning"))

    caps = [w for w in _ALL_CAPS_WORD_RE.findall(text) if w not in _CAPS_ALLOWLIST]
    if len(caps) >= 3:
        issues.append(PolicyIssue(
            "excessive_caps", "Avoid gimmicky ALL-CAPS; it reads as spam to Google.", "warning"
        ))
    if _EXCESS_PUNCT_RE.search(text):
        issues.append(PolicyIssue(
            "excessive_punctuation", "Avoid repeated '!' or '?'; keep punctuation clean.", "warning"
        ))
    if _PHONE_RE.search(text):
        issues.append(PolicyIssue(
            "phone_in_body", "Keep the phone number in the profile fields, not the post text.", "warning"
        ))
    if _URL_RE.search(text):
        issues.append(PolicyIssue(
            "url_in_body", "Put the link on the call-to-action button, not inside the post text.", "warning"
        ))
    if post_type in {"offer", "event"} and not title.strip():
        issues.append(PolicyIssue(
            "missing_title", f"A GBP {post_type} post should have a title.", "warning"
        ))

    ok = not any(i.severity == "violation" for i in issues)
    return GbpPolicyReport(ok=ok, char_count=char_count, issues=issues)
