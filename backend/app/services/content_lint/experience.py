"""Law 16: Experience must be SHOWN, not asserted - the E-E-A-T proof gate.

Ported from ``seo-content-os/scripts/experience_gate.py`` (P1B).

Experience is the first E of E-E-A-T and the one signal no competitor and no model can
scrape, because it exists only inside the operator's head and invoice history. It is a
moat only when it is PROVEN. So this separates two things the prose blurs together:

  * a CLAIM - "serving Austin since 2009", "over 1,200 roofs", "licensed and insured";
  * a PROVING ARTIFACT - an original photo, a license NUMBER (not the word
    "licensed"), a named team member, a cited external source.

A claim whose proof category is unavailable is ``UNPROVEN_CLAIM``. Crucially, a bare
prose number is treated as the claim and NEVER as its own proof - otherwise "since
2009" would prove itself and the gate would be decorative.

WHY THIS MATTERS HERE. The owner's standing decision is a HARD HALT: no page is
drafted until the operator supplies verifiable client facts. This module is the
machine half of that decision. :meth:`ExperienceReport.missing_proof_categories` names
exactly which artifacts are absent, so the SME questionnaire asks for those and not for
a generic list - and so a page cannot quietly acquire fluent, unprovable Experience
prose instead.

PORT CHANGES. The CLI shell is gone and nothing here does I/O. The original took the
raw ``brand.yaml`` TEXT and regex-searched it; that is split out into
:func:`signals_from_manifest_text` so the evaluator takes an already-resolved set of
proof categories. P2 moves the client profile into Postgres (``sme_slots`` /
``brand_kits``), so the caller will pass structured signals and never touch YAML -
which is also how three of the corpus scripts' PyYAML dependency disappears rather
than becoming a declared runtime dependency.

The patterns and the claim->proof mapping are carried over verbatim.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# --- proving artifacts found IN THE DRAFT ----------------------------------- #
_IMAGE_RE = re.compile(r"!\[[^\]]*\]\([^)]+\)|<img\b[^>]*>", re.I)
# A license NUMBER, not the bare adjective "licensed" - that is the claim, not proof.
_LICENSE_NUM_RE = re.compile(
    r"\b(?:license|licence|lic\.?|permit|reg(?:istration)?\.?|cert(?:ificate)?\.?)\s*"
    r"(?:no\.?|number|#)?\s*[:#]?\s*([A-Za-z]{0,4}-?\d{3,}[A-Za-z0-9-]*)",
    re.I,
)
_CITED_SOURCE_RE = re.compile(r"\]\(\s*https?://[^)]+\)|(?<!\()\bhttps?://\S+", re.I)
_NAMED_TEAM_RE = re.compile(
    r"\b(?:[Oo]ur|[Tt]he|[Mm]eet)\s+"
    r"(?:founder|owner|co-owner|president|principal|lead|master|senior|head|"
    r"technician|electrician|plumber|roofer|contractor|manager)\s+"
    r"([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)"
)

MARKER_KINDS: tuple[str, ...] = ("PHOTO", "LICENSE_NUM", "NAMED_TEAM", "CITED_SOURCE")

# --- falsifiable claims, each mapped to the proof categories that satisfy it - #
_CLAIM_PATTERNS: tuple[tuple[str, re.Pattern[str], frozenset[str]], ...] = (
    (
        "YEARS_IN_BUSINESS",
        re.compile(r"\b(?:since|established|est\.?|founded|serving[^.]{0,40}?since)\s+(?:19|20)\d{2}\b", re.I),
        frozenset({"founding_date", "cited_source"}),
    ),
    (
        "YEARS_COUNT",
        re.compile(r"\b\d{1,3}\+?\s+years?\b(?=[^.\n]{0,40}?(?:experience|in business|serving|of service))", re.I),
        frozenset({"founding_date", "cited_source"}),
    ),
    (
        "REVIEW_COUNT",
        re.compile(r"\b\d[\d,]*\s+(?:5[- ]star\s+)?(?:reviews|ratings)\b", re.I),
        frozenset({"review_source", "cited_source"}),
    ),
    (
        "RATING",
        re.compile(r"\brated\s+\d(?:\.\d)?\s*(?:stars?|/\s*5|out of\s*5)\b", re.I),
        frozenset({"review_source", "cited_source"}),
    ),
    (
        "VOLUME_COUNT",
        re.compile(
            r"\b(?:over|more than|upwards of)?\s*\d[\d,]*\+?\s+"
            r"(?:customers|clients|homeowners|homes|families|jobs|projects|"
            r"installations|roofs|repairs|patients|customers served)\b",
            re.I,
        ),
        frozenset({"count_source", "cited_source"}),
    ),
    (
        "CREDENTIAL",
        re.compile(
            r"\b(?:licensed|bonded|insured|certified|accredited|"
            r"award[- ]winning|bbb[- ]accredited|epa[- ]certified|nate[- ]certified)\b",
            re.I,
        ),
        frozenset({"license_permit", "credential_source", "cited_source"}),
    ),
)

# --- keyword -> proof category, for a raw brand.yaml / proof manifest -------- #
_MANIFEST_SIGNALS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("founding_date", re.compile(r"\b(?:established|founded|est\.?|since|year_founded|founding_year|in_business_since)\b", re.I)),
    ("review_source", re.compile(r"\b(?:review|reviews|rating|ratings|testimonial|testimonials|gbp_reviews)\b", re.I)),
    ("count_source", re.compile(r"\b(?:completed|projects|jobs_done|customers|clients|installs|installations|homes_served)\b", re.I)),
    ("license_permit", re.compile(r"\b(?:license|licence|license_no|permit|registration|lic_number)\b", re.I)),
    ("credential_source", re.compile(r"\b(?:certification|certified|accreditation|accredited|award|awards|bbb)\b", re.I)),
    ("photo", re.compile(r"\b(?:photo|photos|image|images|gallery|original_photo)\b", re.I)),
    ("named_team", re.compile(r"\b(?:founder|owner|team|staff|technician|crew_member)\b", re.I)),
)

_SNIPPET_MAX = 70


@dataclass(frozen=True)
class ExperienceMarker:
    """One proving artifact found in the draft."""

    kind: str
    line: int
    snippet: str


@dataclass(frozen=True)
class ExperienceClaim:
    """One falsifiable Experience claim, with the proof categories that would satisfy it."""

    kind: str
    line: int
    snippet: str
    accepted_proof: frozenset[str]


@dataclass(frozen=True)
class ExperienceIssue:
    code: str
    line: int
    message: str


@dataclass(frozen=True)
class ExperienceReport:
    markers: tuple[ExperienceMarker, ...] = ()
    claims: tuple[ExperienceClaim, ...] = ()
    signals: frozenset[str] = frozenset()
    issues: tuple[ExperienceIssue, ...] = field(default=())

    @property
    def passed(self) -> bool:
        return not self.issues

    @property
    def unproven(self) -> tuple[ExperienceClaim, ...]:
        """Claims the draft makes but cannot back."""
        return tuple(c for c in self.claims if not (c.accepted_proof & self.signals))

    def missing_proof_categories(self) -> frozenset[str]:
        """Proof categories that would resolve the outstanding claims.

        This is what the SME questionnaire should ASK FOR. Asking for exactly the
        missing artifact is the difference between an operator answering three
        specific questions and being handed a generic intake form.
        """
        needed: set[str] = set()
        for claim in self.unproven:
            needed |= set(claim.accepted_proof)
        return frozenset(needed - self.signals)


def signals_from_manifest_text(manifest_text: str | None) -> frozenset[str]:
    """Proof categories a raw brand.yaml / proof-manifest TEXT advertises.

    Kept text-based to stay equivalent to the corpus script. New callers should build
    the signal set from structured client data instead (P2 ``sme_slots``), which is
    why this is a separate function rather than a parameter of the evaluator.
    """
    if not manifest_text:
        return frozenset()
    return frozenset(cat for cat, rx in _MANIFEST_SIGNALS if rx.search(manifest_text))


def find_markers(text: str) -> tuple[ExperienceMarker, ...]:
    """Concrete proving artifacts present in the draft, in document order."""
    out: list[ExperienceMarker] = []
    for lineno, line in enumerate(text.splitlines(), 1):
        for m in _IMAGE_RE.finditer(line):
            out.append(ExperienceMarker("PHOTO", lineno, m.group(0)[:_SNIPPET_MAX]))
        for m in _LICENSE_NUM_RE.finditer(line):
            out.append(ExperienceMarker("LICENSE_NUM", lineno, m.group(0).strip()[:_SNIPPET_MAX]))
        for m in _CITED_SOURCE_RE.finditer(line):
            out.append(ExperienceMarker("CITED_SOURCE", lineno, m.group(0)[:_SNIPPET_MAX]))
        for m in _NAMED_TEAM_RE.finditer(line):
            out.append(ExperienceMarker("NAMED_TEAM", lineno, m.group(0).strip()[:_SNIPPET_MAX]))
    return tuple(out)


def find_claims(text: str) -> tuple[ExperienceClaim, ...]:
    """Falsifiable Experience claims the draft makes, in document order."""
    out: list[ExperienceClaim] = []
    for lineno, line in enumerate(text.splitlines(), 1):
        for kind, rx, needed in _CLAIM_PATTERNS:
            for m in rx.finditer(line):
                out.append(ExperienceClaim(kind, lineno, m.group(0).strip()[:_SNIPPET_MAX], needed))
    return tuple(out)


def _draft_signals(markers: tuple[ExperienceMarker, ...]) -> frozenset[str]:
    kinds = {m.kind for m in markers}
    mapping = {
        "PHOTO": "photo",
        "LICENSE_NUM": "license_permit",
        "NAMED_TEAM": "named_team",
        "CITED_SOURCE": "cited_source",
    }
    return frozenset(mapping[k] for k in kinds if k in mapping)


def evaluate_experience(
    text: str, *, proof_signals: frozenset[str] = frozenset()
) -> ExperienceReport:
    """Grade one draft's Experience proof.

    ``proof_signals`` are categories the CLIENT can back that the draft does not show
    inline - from ``sme_slots`` in P2, or from :func:`signals_from_manifest_text` when
    reading a raw brand.yaml. Signals found in the draft itself are added to them.

    Total: never raises, never performs I/O.
    """
    markers = find_markers(text)
    claims = find_claims(text)
    signals = _draft_signals(markers) | proof_signals

    issues: list[ExperienceIssue] = []
    if not markers:
        issues.append(
            ExperienceIssue(
                "NO_EXPERIENCE_MARKERS",
                0,
                "no proving artifact anywhere (no photo, license number, named team "
                "member, or cited source): Experience is asserted, never shown",
            )
        )
    for claim in claims:
        if claim.accepted_proof & signals:
            continue
        issues.append(
            ExperienceIssue(
                "UNPROVEN_CLAIM",
                claim.line,
                f"{claim.kind} {claim.snippet!r} has no proving artifact "
                f"(needs one of: {', '.join(sorted(claim.accepted_proof))})",
            )
        )

    return ExperienceReport(
        markers=markers, claims=claims, signals=frozenset(signals), issues=tuple(issues)
    )
