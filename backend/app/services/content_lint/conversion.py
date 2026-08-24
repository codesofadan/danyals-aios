"""Conversion readiness - the deterministic half of quality gate G13.

Ported from ``seo-content-os/scripts/conversion_linter.py`` (P1B).

This flags MISSING conversion craft. It never fabricates urgency, scarcity or proof
(Law 20), and it never scores or games AI detection (Law 8). Whether a guarantee is a
real mechanism or a hollow badge, and whether proof sits beside its claim, is human or
model judgment layered on top; this is the cheap, repeatable part that can run on
every redraft for free.

WHAT IT CATCHES that a word count and a readability score cannot:

  * ``MISSING_CLICK_TO_CALL`` - no ``tel:`` link anywhere. Local emergency intent
    converts by phone, on a handset, and an untappable number is a dead end.
  * ``NO_CTA`` - the page never asks for the business.
  * ``NO_CTA_AFTER_PROOF_FAQ`` - the most under-appreciated one. A reader who got
    through the reviews and the FAQ is the most qualified visitor on the page, and
    they arrive at the bottom with nothing to do.
  * ``WEAK_CTA_VERB`` - every ask is mechanical ("Submit", "Contact us") rather than a
    first-person outcome ("Get my free estimate").
  * ``OFF_GOAL_CTA`` - a newsletter or download competing with the lead goal. Note a
    call-and-form PAIR is deliberately not flagged: those serve urgent versus
    considered intent and belong together.
  * ``MISSING_PRICE_SIGNAL`` / ``MISSING_GUARANTEE`` - no price band, driver, or
    honest custom-quote reason; no risk reversal.

This replaces ``content_qa._proxy_cta_ux``, which degrades to a heuristic when no
Judge is wired - and a Judge is wired on no real run today.

Severity is load-bearing here, unlike the earlier ports: ERROR means the page fails
G13, WARN means a human should look. ``passed`` keys off ERRORs only.

PORT NOTE: ``_only_mechanical`` in the original is dead code - it returns False
unconditionally, so the "call ... submit" edge it names always resolves to strong.
Carried over as an inlined comment rather than a function that does nothing, and the
BEHAVIOUR is unchanged.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_TEL_RE = re.compile(r"tel:\s*\+?[\d\-\s().]{5,}", re.IGNORECASE)

_LEAD_CTA_RES: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bcall (us |now|today|our )", re.IGNORECASE),
    re.compile(r"\b(tap|click) to call\b", re.IGNORECASE),
    re.compile(r"\bcall\b[^.\n]{0,30}\btel:", re.IGNORECASE),
    re.compile(
        r"\b(book|schedule|reserve|request)\b[^.\n]{0,40}"
        r"(quote|estimate|consult|appointment|inspection|visit|call|service|now|today|online)",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(get|claim|start|grab|schedule|book|reserve)\s+(my|your|a|an)\b"
        r"[^.\n]{0,40}(quote|estimate|inspection|consult|appointment|visit|project|repair|booking|spot)",
        re.IGNORECASE,
    ),
    re.compile(r"\bcontact us\b", re.IGNORECASE),
    re.compile(r"\bget started\b", re.IGNORECASE),
    re.compile(r"\bsubmit\b[^.\n]{0,30}(info|details|form|request|your)", re.IGNORECASE),
)

_STRONG_VERB_RE = re.compile(
    r"\b(get|claim|book|schedule|reserve|start|grab)\s+(my|your)\b"
    r"[^.\n]{0,40}(quote|estimate|inspection|consult|appointment|visit|project|"
    r"repair|booking|spot|plan|design)",
    re.IGNORECASE,
)
_CALL_VERB_RE = re.compile(r"\b(call|tap to call|click to call)\b", re.IGNORECASE)

_MECHANICAL_RES: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bsubmit\b", re.IGNORECASE),
    re.compile(r"\bsend\b", re.IGNORECASE),
    re.compile(r"\bcontact us\b", re.IGNORECASE),
    re.compile(r"\bget started\b", re.IGNORECASE),
    re.compile(r"\bget a quote\b", re.IGNORECASE),
    re.compile(r"\bclick here\b", re.IGNORECASE),
)

_OFF_GOAL_RES: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bsubscribe\b", re.IGNORECASE),
    re.compile(r"\bsign\s?up\b", re.IGNORECASE),
    re.compile(r"\bnewsletter\b", re.IGNORECASE),
    re.compile(r"\bdownload\b", re.IGNORECASE),
    re.compile(r"\bjoin our\b", re.IGNORECASE),
    re.compile(r"\bfollow us\b", re.IGNORECASE),
    re.compile(r"\blearn more\b", re.IGNORECASE),
    re.compile(r"\bread more\b", re.IGNORECASE),
    re.compile(r"\bshop now\b", re.IGNORECASE),
    re.compile(r"\badd to cart\b", re.IGNORECASE),
)

_PRICE_RES: tuple[re.Pattern[str], ...] = (
    re.compile(r"\$\s?\d"),
    re.compile(r"\b\d+(\.\d+)?\s?%\s?(apr|off|financing)", re.IGNORECASE),
    re.compile(r"\bfree\s+(estimate|inspection|quote|consult|consultation|assessment)", re.IGNORECASE),
    re.compile(r"\bno\s+(service\s+)?fee\b", re.IGNORECASE),
    re.compile(r"\b(0%|zero)\s+(apr|interest|down)", re.IGNORECASE),
    re.compile(
        r"\b(starting at|flat rate|per hour|per visit|priced per|"
        r"custom quote|quote depends|quoted upfront|upfront pricing)\b",
        re.IGNORECASE,
    ),
)

_GUARANTEE_RES: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bguarantee(d|s)?\b", re.IGNORECASE),
    re.compile(r"\bwarrant(y|ies)\b", re.IGNORECASE),
    re.compile(r"\bmoney[\s-]?back\b", re.IGNORECASE),
    re.compile(r"\brefund\b", re.IGNORECASE),
    re.compile(r"\bno\s+fee\b", re.IGNORECASE),
    re.compile(r"\bno\s+hidden\b", re.IGNORECASE),
    re.compile(r"\bon[\s-]?time\b", re.IGNORECASE),
    re.compile(r"\bno\s+obligation\b", re.IGNORECASE),
    re.compile(r"\bre[\s-]?inspection\b", re.IGNORECASE),
    re.compile(r"\bsatisfaction\b", re.IGNORECASE),
)

_PROOF_HEAD_RE = re.compile(
    r"review|testimonial|what .*\bsay\b|our clients|trusted by|"
    r"neighbors say|customers say|\bproof\b",
    re.IGNORECASE,
)
_FAQ_HEAD_RE = re.compile(r"\bfaq\b|frequently asked|common questions|\bquestions\b", re.IGNORECASE)
_HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s+(.*\S)\s*$")


@dataclass(frozen=True)
class ConversionIssue:
    severity: str  # "ERROR" | "WARN"
    code: str
    line: int      # 0 = whole document
    message: str


@dataclass(frozen=True)
class ConversionReport:
    issues: tuple[ConversionIssue, ...] = ()

    @property
    def errors(self) -> tuple[ConversionIssue, ...]:
        return tuple(i for i in self.issues if i.severity == "ERROR")

    @property
    def warnings(self) -> tuple[ConversionIssue, ...]:
        return tuple(i for i in self.issues if i.severity == "WARN")

    @property
    def passed(self) -> bool:
        """ERRORs fail G13; WARNs are advisory and do not block."""
        return not self.errors


def find_headings(lines: list[str]) -> list[tuple[str, int]]:
    """Headings as ``(text, lineno)``, skipping fenced code blocks."""
    heads: list[tuple[str, int]] = []
    in_fence = False
    for i, line in enumerate(lines, 1):
        if line.strip().startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        m = _HEADING_RE.match(line)
        if m:
            heads.append((m.group(1).strip(), i))
    return heads


def is_lead_cta(line: str) -> bool:
    return any(rx.search(line) for rx in _LEAD_CTA_RES)


def is_strong_cta(line: str) -> bool:
    """A first-person outcome verb, or a direct call action (which is strong per se)."""
    # The original guarded this with `_only_mechanical`, which returns False
    # unconditionally, so a "call ... submit" line always resolves to strong.
    return bool(_STRONG_VERB_RE.search(line) or _CALL_VERB_RE.search(line))


def is_mechanical_cta(line: str) -> bool:
    return any(rx.search(line) for rx in _MECHANICAL_RES)


def _has_any(text: str, regexes: tuple[re.Pattern[str], ...]) -> bool:
    return any(rx.search(text) for rx in regexes)


def lint_conversion(text: str) -> ConversionReport:
    """Grade one draft's conversion readiness. Total: never raises, never does I/O."""
    lines = text.splitlines()
    joined = "\n".join(lines)
    issues: list[ConversionIssue] = []

    if not _TEL_RE.search(joined):
        issues.append(ConversionIssue(
            "ERROR", "MISSING_CLICK_TO_CALL", 0,
            "no tappable tel: link found (mobile local intent converts by phone)",
        ))

    lead_lines = [i for i, ln in enumerate(lines, 1) if is_lead_cta(ln)]
    strong_lines = [i for i, ln in enumerate(lines, 1) if is_strong_cta(ln)]
    if not lead_lines:
        issues.append(ConversionIssue(
            "ERROR", "NO_CTA", 0,
            "no primary lead CTA (call/book/request a quote|estimate|consult) found",
        ))
    elif not strong_lines:
        mech = next((i for i in lead_lines if is_mechanical_cta(lines[i - 1])), lead_lines[0])
        issues.append(ConversionIssue(
            "WARN", "WEAK_CTA_VERB", mech,
            'every lead CTA is mechanical; use a first-person outcome verb '
            '("Get my free estimate", not "Submit")',
        ))

    heads = find_headings(lines)
    proof_line = next((ln for txt, ln in heads if _PROOF_HEAD_RE.search(txt)), None)
    faq_line = next((ln for txt, ln in heads if _FAQ_HEAD_RE.search(txt)), None)
    anchors = [a for a in (proof_line, faq_line) if a]
    if lead_lines and anchors:
        anchor = max(anchors)
        if not any(c > anchor for c in lead_lines):
            which = " and ".join(w for w, a in (("proof", proof_line), ("FAQ", faq_line)) if a)
            issues.append(ConversionIssue(
                "ERROR", "NO_CTA_AFTER_PROOF_FAQ", anchor,
                f"no lead CTA after the {which} block; add the closing ask",
            ))

    seen: set[str] = set()
    for i, line in enumerate(lines, 1):
        for rx in _OFF_GOAL_RES:
            if rx.search(line):
                if rx.pattern not in seen:
                    seen.add(rx.pattern)
                    issues.append(ConversionIssue(
                        "WARN", "OFF_GOAL_CTA", i,
                        f"off-goal action {rx.pattern.strip(chr(92) + 'b')!r} competes with the "
                        "lead goal (a call-and-form pair does not; a newsletter/download does)",
                    ))
                break

    if not _has_any(joined, _PRICE_RES):
        issues.append(ConversionIssue(
            "WARN", "MISSING_PRICE_SIGNAL", 0,
            'no price, price band, price driver, or honest custom-quote reason '
            '(bare "contact us for pricing" is a fail)',
        ))

    if not _has_any(joined, _GUARANTEE_RES):
        issues.append(ConversionIssue(
            "WARN", "MISSING_GUARANTEE", 0,
            "no risk-reversal/guarantee keyword; add a real one where the ticket warrants it",
        ))

    return ConversionReport(issues=tuple(issues))
