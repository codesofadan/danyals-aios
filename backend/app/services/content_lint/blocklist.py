"""Tier-1 AI-tell vocabulary lint - quality gate G9 (voice fidelity).

Ported from ``seo-content-os/scripts/blocklist_lint.py`` (P1B). The banned terms come
from the corpus itself (``knowledge/voice/vocabulary-blocklist.md``), parsed at first
use and cached, so the doctrine stays the single source of truth rather than being
re-typed into Python.

THIS IS NOT DETECTOR EVASION (Law 8). It is a craft check. These phrases read as
machine-written to a human, and - more usefully - they almost always mark a sentence
that contains no real local fact. "We pride ourselves on fast, reliable, affordable
service" says nothing a competitor could not also say. The point is to send the writer
back for a specific, not to launder the text past a classifier.

THE INTERESTING PART IS THE FALSE-POSITIVE CONTROL, which is what makes the check
usable rather than noise:

  * Tricolons and quoted phrases match WHOLE. "fast, reliable, and affordable" is one
    hit, not three, so the report reflects one bad sentence rather than three bad words.
  * Near-synonym GROUPS ("reliable, dependable, trustworthy") only fire when 2+ members
    appear on the same line. Any one of those words alone is ordinary English; it is
    the stacking that reads as filler.
  * CONDITIONAL terms are suppressed on a line carrying a real specific. The blocklist
    annotates "affordable ... name the number" and similar, so "affordable" beside a
    price or a licence number is allowed - the objection was never the word, it was the
    vagueness.
  * A placeholder term needs 2+ literal anchor words of 3+ characters, else it is
    dropped as too generic. Without that rule "at [Brand]" would wildcard-match "at
    our practice", "at once", "at the consult" and flood the report.
  * Fenced code blocks are skipped.

PORT CHANGES: no argparse, no stdout, typed results. The blocklist path is resolved
through :mod:`app.services.content_lint.corpus` so it works from a checkout and from
the installed wheel. Parsing is cached per process. All parsing and matching logic is
carried over verbatim.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from functools import cache

from app.services.content_lint.corpus import corpus_file

# An annotation carrying one of these means "allowed when a real specific is present".
_ALLOW_MARKERS: tuple[str, ...] = (
    "ok when", "ok only", "allowed only", "fine when", "fine occasionally",
    "only when", "only as", "tied to a real", "name the number",
    "name the price", "name the range", "name the metric", "when tied to",
    "when literal", "when it means", "see tier 2", "literal use",
)

# A line carrying one of these has the real specific that legitimises a conditional term.
_ALLOW_SIGNAL = re.compile(r"(\$|\d|%|\blic\b|\blicense\b|#)", re.IGNORECASE)

_WILDCARD = r"[\w'\-]+(?:\s+[\w'\-]+){0,3}"  # a [placeholder] = 1 to 4 words

_H2_RE = re.compile(r"^##\s+(.*)$")
_H3_RE = re.compile(r"^###\s+(.*)$")
_BULLET_RE = re.compile(r"^-\s+(.*\S)\s*$")
_QUOTED_RE = re.compile(r'^[\'"](.+?)[\'"](.*)$')


@dataclass(frozen=True)
class BlockedTerm:
    display: str
    regex: re.Pattern[str]
    category: str
    group_id: int
    stacked: bool
    allow_number: bool
    tier: str = "Tier 1"


@dataclass(frozen=True)
class BlocklistHit:
    line: int
    col: int
    match: str
    display: str
    category: str
    tier: str


@dataclass(frozen=True)
class BlocklistReport:
    hits: tuple[BlocklistHit, ...] = ()

    @property
    def passed(self) -> bool:
        return not self.hits

    def issues(self) -> list[str]:
        return [
            f"line {h.line}: {h.match!r} is a {h.tier} blocklisted phrase "
            f"({h.category}); rewrite from a more specific premise"
            for h in self.hits
        ]


def term_to_regex(term: str) -> re.Pattern[str] | None:
    """Compile a blocklist term to a whitespace-flexible, word-boundaried regex.

    Returns None when a placeholder term carries too little literal anchor to match
    safely - a fragment like "at [Brand]" would otherwise match "at our practice", "at
    once", "at the consult" and drown the report. A placeholder term needs 2+ literal
    anchor words of 3 or more characters.
    """
    term = term.strip().rstrip(".").strip()
    tokens = re.findall(r"\[[^\]]*\]|[\w'\-]+|[^\s\w]+", term)

    parts: list[tuple[str, bool]] = []
    has_wild = False
    anchors = 0
    for tok in tokens:
        if tok.startswith("[") and tok.endswith("]"):
            parts.append((_WILDCARD, False))
            has_wild = True
        elif re.match(r"^[^\s\w]+$", tok):
            parts.append((re.escape(tok), True))
        else:
            parts.append((re.escape(tok), False))
            if len(tok) >= 3:
                anchors += 1

    if not parts or (has_wild and anchors < 2):
        return None

    pattern = parts[0][0]
    for frag, is_punct in parts[1:]:
        pattern += (r"\s*" if is_punct else r"\s+") + frag
    return re.compile(r"(?<!\w)" + pattern + r"(?!\w)", re.IGNORECASE)


def _split_head(head: str) -> tuple[list[str], str]:
    """Split a bullet head into member terms, protecting ``[...]`` placeholders from
    being split on their internal ``/`` or ``,``."""
    stash: list[str] = []

    def _protect(m: re.Match[str]) -> str:
        stash.append(m.group(0))
        return f"\x00{len(stash) - 1}\x00"

    protected = re.sub(r"\[[^\]]*\]", _protect, head)

    if "/" in protected:
        raw_parts, style = re.split(r"\s*/\s*", protected), "variant"
    elif "," in protected and "\x00" not in protected:
        # Never comma-split a phrase containing a placeholder: splitting
        # "at [Brand], we understand that..." leaves "at [Brand]", which matches
        # almost anything.
        raw_parts, style = re.split(r"\s*,\s*", protected), "list"
    else:
        raw_parts, style = [protected], "single"

    members: list[str] = []
    for part in raw_parts:
        restored = re.sub(r"\x00(\d+)\x00", lambda mm: stash[int(mm.group(1))], part)
        cleaned = restored.strip().strip('"').strip("'")
        cleaned = re.sub(r"^(and|or)\s+", "", cleaned, flags=re.IGNORECASE)
        if len(cleaned) >= 3:
            members.append(cleaned)
    return members, style


def parse_blocklist(text: str) -> tuple[tuple[BlockedTerm, ...], dict[int, frozenset[str]]]:
    """Parse Tier-1 bullets out of the vocabulary blocklist markdown."""
    terms: list[BlockedTerm] = []
    groups: dict[int, set[str]] = {}
    in_tier1 = False
    category: str | None = None
    group_id = 0

    for line in text.splitlines():
        h2 = _H2_RE.match(line)
        if h2:
            in_tier1 = h2.group(1).strip().lower().startswith("tier 1")
            category = None
            continue
        if not in_tier1:
            continue
        h3 = _H3_RE.match(line)
        if h3:
            category = h3.group(1).strip()
            continue
        bullet = _BULLET_RE.match(line)
        if not bullet:
            continue

        raw = bullet.group(1).strip()
        quoted = _QUOTED_RE.match(raw)
        if quoted:
            # A quoted entry (a tricolon or a set phrase) is ONE whole-phrase term.
            members, annotation, style = [quoted.group(1).strip()], quoted.group(2), "single"
        else:
            paren = raw.find(" (")
            head, annotation = (raw[:paren], raw[paren:]) if paren >= 0 else (raw, "")
            members, style = _split_head(head)

        if not members:
            continue

        ann_low = annotation.lower()
        allow_number = any(mk in ann_low for mk in _ALLOW_MARKERS)
        stacked = style == "list" and len(members) >= 2 and bool(annotation.strip())

        group_id += 1
        groups[group_id] = set()
        for term in members:
            try:
                rx = term_to_regex(term)
            except re.error:
                continue
            if rx is None:
                continue
            groups[group_id].add(term.lower())
            terms.append(BlockedTerm(
                display=term, regex=rx, category=category or "(uncategorized)",
                group_id=group_id, stacked=stacked, allow_number=allow_number,
            ))

    return tuple(terms), {gid: frozenset(members) for gid, members in groups.items()}


@cache
def _default_terms() -> tuple[BlockedTerm, ...]:
    """Tier-1 terms from the corpus blocklist, parsed once per process."""
    text = corpus_file("knowledge", "voice", "vocabulary-blocklist.md").read_text(encoding="utf-8")
    return parse_blocklist(text)[0]


def _scan_lines(text: str) -> Iterable[tuple[int, str]]:
    """Yield ``(lineno, line)``, skipping fenced code blocks."""
    in_fence = False
    for i, line in enumerate(text.splitlines(), 1):
        if line.strip().startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        yield i, line


def scan(text: str, terms: tuple[BlockedTerm, ...]) -> tuple[BlocklistHit, ...]:
    """Find blocklist hits, applying the conditional and stacking suppressions."""
    hits: list[BlocklistHit] = []
    for lineno, line in _scan_lines(text):
        allow_here = bool(_ALLOW_SIGNAL.search(line))

        candidates: list[tuple[BlockedTerm, int, str]] = []
        members_on_line: dict[int, set[str]] = {}
        for term in terms:
            for m in term.regex.finditer(line):
                if term.allow_number and allow_here:
                    continue  # conditional term, and a real specific is present
                candidates.append((term, m.start(), m.group(0)))
                members_on_line.setdefault(term.group_id, set()).add(term.display.lower())

        for term, col, matched in candidates:
            # A near-synonym alone is ordinary English; the stacking is the tell.
            if term.stacked and len(members_on_line.get(term.group_id, ())) < 2:
                continue
            hits.append(BlocklistHit(
                line=lineno, col=col, match=matched, display=term.display,
                category=term.category, tier=term.tier,
            ))

    hits.sort(key=lambda h: (h.line, h.col))
    return tuple(hits)


def lint_blocklist(
    text: str, *, extra_banned: Iterable[str] = (), terms: tuple[BlockedTerm, ...] | None = None
) -> BlocklistReport:
    """Lint a draft against Tier-1 doctrine terms plus any client-banned phrases.

    ``extra_banned`` carries per-client vocabulary (a competitor's name, a phrase the
    brand refuses). Total: never raises on bad input, never does network I/O.
    """
    active = list(_default_terms() if terms is None else terms)
    for phrase in extra_banned:
        rx = term_to_regex(phrase)
        if rx is not None:
            active.append(BlockedTerm(
                display=phrase, regex=rx, category="client banned",
                group_id=0, stacked=False, allow_number=False, tier="Client",
            ))
    return BlocklistReport(hits=scan(text, tuple(active)))
