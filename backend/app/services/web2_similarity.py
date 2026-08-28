"""The cross-property similarity gate - WEB2-007 / R2-09..R2-11.

WHAT IT STOPS. A Web 2.0 property is defensible only while it is a genuine brand asset.
The moment two properties share a skeleton, the set stops being N independent blog posts
and becomes one detectable pattern - which is what gets a whole client base actioned at
once rather than one placement removed. `content_qa`'s originality dimension cannot see
this: it compares a document only against ITSELF. Only a cross-document, cross-client
comparison can, and nothing in the repo did that before this module.

THE MEASUREMENT THAT SHAPES THE GATE - and where it departs from R2-10 as written.
R2-10 specifies shingling the normalized text RAW. This repo has already measured that
raw shingling does not detect the templated case at all
(`content_pipeline/outline.py:11-23`, on real generator output):

    w=3   raw 58.2%   entity-masked 100.0%
    w=5   raw 27.6%   entity-masked 100.0%

Both raw scores sit UNDER the duplicate ceiling, so a raw gate PASSES every templated
page - and it degrades as the window grows, which is the opposite of the intuition. The
cause is that the varying entity token (the city, the brand) sits inside most shingles
and hides the duplication being looked for. Two properties for two different plumbers in
two different cities are exactly that case, and it is the primary local-business use.

So the client entity is MASKED before shingling. Without that this gate ships, passes its
own tests, and silently approves precisely what it exists to stop. Masking also largely
dissolves R2's open question O-1 about the r >= 0.25 block line: masked templated content
scores near 1.0, not near the threshold, so the verdict is not balanced on a hair.

PURE. No DB, no vault, no network. Candidates are passed in, so the caller owns the three
R2-10 scopes (same client / same house account / same platform in 90 days) and the
privileged read that spans tenants. This module never sees another client's TEXT - it
compares hashes and returns a verdict plus the colliding id, which is what keeps the
cross-tenant read honest (`web2_id` + scope are staff-visible facts; the article is not).
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Literal

from app.services.content_lint import shingle_hashes
from app.services.content_pipeline.outline import mask_entity

# Body text: the 5-word window R2-10 specifies. Ours, not Broder's (the paper's own
# production values are w=10 / m=25 over a 30M-page web walk); a shorter window is more
# sensitive to local rewording, which is what templating looks like at article scale.
BODY_SHINGLE_SIZE = 5
# Headings are SHORT strings, so a 5-word window would leave most of them unrepresented.
# Same reasoning (and same value) as the outline stage's HEADING_SHINGLE_SIZE.
HEADING_SHINGLE_SIZE = 3

# Broder's MOD_m sampling: index only hashes where h % m == 0, an unbiased resemblance
# estimator that shrinks the candidate index m-fold. Candidate GENERATION only - scoring
# always uses the full sets, so the sample never changes a verdict.
SAMPLE_MODULUS = 16

# AGENCY POLICY, not vendor guidance. Broder's 0.50 is the DUPLICATE line; a safety gate
# must trip well before duplicate because the harm is a detectable pattern, not a
# duplicate. Calibration against a graded golden set is a precondition to hardening
# (R2 O-1) - until then the caller runs the gate in warn-only mode.
BODY_BLOCK = 0.25
BODY_WARN = 0.15
HEADING_BLOCK = 0.60
HEADING_WARN = 0.45

Verdict = Literal["pass", "warn", "block"]
Scope = Literal["client", "account", "platform"]

_HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s+(.*\S)\s*$", re.MULTILINE)
_MD_NOISE_RE = re.compile(r"[*_`>\[\]()!]|https?://\S+")
_WS_RE = re.compile(r"\s+")


@dataclass(frozen=True)
class DocFingerprint:
    """Everything the gate needs about one draft. Hashes only - never the text."""

    body_sha256: str
    body_hashes: frozenset[int]
    heading_hashes: frozenset[int]
    anchor_norm: str

    @property
    def sampled(self) -> frozenset[int]:
        """The MOD_16 subset used for candidate generation (R2-10 step 3)."""
        return frozenset(h for h in self.body_hashes if h % SAMPLE_MODULUS == 0)


@dataclass(frozen=True)
class Candidate:
    """A previously-fingerprinted property to compare against."""

    web2_id: str
    scope: Scope
    body_sha256: str
    body_hashes: frozenset[int]
    heading_hashes: frozenset[int]
    anchor_norm: str = ""


@dataclass(frozen=True)
class SimilarityVerdict:
    """The gate's answer. ``check`` names WHICH rule fired so the held row's error is
    machine-readable and the operator is told what to change, not merely that it failed."""

    verdict: Verdict = "pass"
    check: str = ""
    scope: Scope | None = None
    colliding_web2_id: str = ""
    body_resemblance: float = 0.0
    heading_resemblance: float = 0.0
    notes: list[str] = field(default_factory=list)

    @property
    def blocked(self) -> bool:
        return self.verdict == "block"


def normalize(text: str) -> str:
    """Strip markdown/URL noise, casefold, collapse whitespace.

    Stopwords are deliberately KEPT: they carry the template. Removing them is the
    standard search-index move and it is wrong here - two documents built from one
    skeleton differ mostly in their content words, so the function words are the
    signal, not the noise.
    """
    return _WS_RE.sub(" ", _MD_NOISE_RE.sub(" ", text)).strip().casefold()


def headings_of(body_md: str) -> list[str]:
    """The H1-H6 texts, in order - the document's skeleton."""
    return [m.group(1).strip() for m in _HEADING_RE.finditer(body_md)]


def fingerprint(
    *,
    body_md: str,
    client_name: str = "",
    geo: str = "",
    anchor: str = "",
) -> DocFingerprint:
    """Fingerprint one draft, MASKING the client entity first.

    ``client_name``/``geo`` are the tokens that legitimately differ between two
    otherwise-identical properties; leaving them in is what makes a raw gate blind (see
    the module docstring). The exact-duplicate hash is taken over the masked, normalized
    body too, so byte-identical-modulo-the-brand is caught as an exact duplicate rather
    than sneaking through as merely 'similar'.
    """
    masked_body = mask_entity(body_md, client_name, geo)
    normalized = normalize(masked_body)
    masked_headings = mask_entity("\n".join(headings_of(body_md)), client_name, geo)
    return DocFingerprint(
        body_sha256=hashlib.sha256(normalized.encode("utf-8")).hexdigest(),
        body_hashes=shingle_hashes(normalized, size=BODY_SHINGLE_SIZE),
        heading_hashes=shingle_hashes(
            normalize(masked_headings), size=HEADING_SHINGLE_SIZE
        ),
        anchor_norm=normalize(anchor),
    )


def resemblance(a: Iterable[int], b: Iterable[int]) -> float:
    """Broder resemblance r = |A n B| / |A u B|, computed EXACTLY.

    MinHash exists to approximate this at billion scale; at 10^3-10^4 documents the
    approximation buys nothing and costs explainability, so the full sets are used.
    """
    sa, sb = frozenset(a), frozenset(b)
    if not sa or not sb:
        return 0.0
    union = len(sa | sb)
    return (len(sa & sb) / union) if union else 0.0


def evaluate(
    fingerprint_: DocFingerprint,
    candidates: Sequence[Candidate],
    *,
    body_block: float = BODY_BLOCK,
    body_warn: float = BODY_WARN,
    heading_block: float = HEADING_BLOCK,
    heading_warn: float = HEADING_WARN,
) -> SimilarityVerdict:
    """Score a draft against its candidates and return the WORST verdict.

    Order matters: an exact body match is unconditional and is reported as such rather
    than as a high resemblance, because 'identical' and 'similar' need different fixes
    (regenerate vs vary the structure). Anchor reuse is checked last so a real content
    collision is never masked by it.
    """
    worst = SimilarityVerdict()
    for cand in candidates:
        if cand.body_sha256 and cand.body_sha256 == fingerprint_.body_sha256:
            # Unconditional, no override: this is the same article.
            return SimilarityVerdict(
                verdict="block", check="body_sha256", scope=cand.scope,
                colliding_web2_id=cand.web2_id, body_resemblance=1.0,
                notes=["identical body (after masking the client entity)"],
            )
        body_r = resemblance(fingerprint_.body_hashes, cand.body_hashes)
        head_r = resemblance(fingerprint_.heading_hashes, cand.heading_hashes)

        if body_r >= body_block:
            found = SimilarityVerdict(
                verdict="block", check="body_resemblance", scope=cand.scope,
                colliding_web2_id=cand.web2_id, body_resemblance=body_r,
                heading_resemblance=head_r,
            )
        elif head_r >= heading_block:
            found = SimilarityVerdict(
                verdict="block", check="heading_skeleton", scope=cand.scope,
                colliding_web2_id=cand.web2_id, body_resemblance=body_r,
                heading_resemblance=head_r,
                notes=["same outline, different words"],
            )
        elif body_r >= body_warn:
            found = SimilarityVerdict(
                verdict="warn", check="body_resemblance", scope=cand.scope,
                colliding_web2_id=cand.web2_id, body_resemblance=body_r,
                heading_resemblance=head_r,
            )
        elif head_r >= heading_warn:
            found = SimilarityVerdict(
                verdict="warn", check="heading_skeleton", scope=cand.scope,
                colliding_web2_id=cand.web2_id, body_resemblance=body_r,
                heading_resemblance=head_r,
            )
        else:
            continue
        worst = _worse(worst, found)

    if worst.verdict == "pass":
        anchor_hit = _anchor_collision(fingerprint_, candidates)
        if anchor_hit is not None:
            return anchor_hit
    return worst


def _anchor_collision(
    fingerprint_: DocFingerprint, candidates: Sequence[Candidate]
) -> SimilarityVerdict | None:
    """R2-14.2: an anchor string may not repeat within a client (S1) or a house account
    (S2). Repeating one is a self-made pattern independent of the prose."""
    if not fingerprint_.anchor_norm:
        return None
    for cand in candidates:
        if cand.scope not in ("client", "account"):
            continue
        if cand.anchor_norm and cand.anchor_norm == fingerprint_.anchor_norm:
            return SimilarityVerdict(
                verdict="block", check="anchor_reuse", scope=cand.scope,
                colliding_web2_id=cand.web2_id,
                notes=["this anchor is already used on another property"],
            )
    return None


_RANK: dict[str, int] = {"pass": 0, "warn": 1, "block": 2}


def _worse(a: SimilarityVerdict, b: SimilarityVerdict) -> SimilarityVerdict:
    """The more severe of two verdicts; ties break toward the higher resemblance so the
    reported collision is the most informative one."""
    if _RANK[b.verdict] > _RANK[a.verdict]:
        return b
    if _RANK[b.verdict] == _RANK[a.verdict] and b.body_resemblance > a.body_resemblance:
        return b
    return a


def error_code(verdict: SimilarityVerdict) -> str:
    """The machine-readable string persisted on a held row, e.g.
    ``sim_block:heading_skeleton:client:<web2_id>``. Parsed by the UI, so it is a
    contract: colon-delimited, no spaces, scope before id."""
    if verdict.verdict == "pass":
        return ""
    return ":".join(
        [
            f"sim_{verdict.verdict}",
            verdict.check,
            verdict.scope or "unknown",
            verdict.colliding_web2_id or "unknown",
        ]
    )
