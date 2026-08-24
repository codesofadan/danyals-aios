"""GEO / AI-search citability - the page-controllable levers that move AI citation.

Ported from ``seo-content-os/scripts/geo_page_linter.py`` (P1B). Operationalises the
corpus's Local AI-Citation Stack: the levers the Princeton GEO study and the 2026
per-engine research found actually move whether an answer engine cites a page, plus
the one tactic that measurably REDUCES citation.

Six levers, and why each is here rather than being folklore:

  1. DIRECT-ANSWER-FIRST H2s. An answer engine extracts passages, not pages. A block
     whose first sentence is filler ("When it comes to...", "There are several...")
     is not extractable, and filler openers are the single most common reason a block
     is skipped. A block passes when its opening sentence carries a concrete anchor -
     a number, a yes/no, or a named specific.
  2. STATISTIC DENSITY. "Statistics Addition" was a top mover in the GEO study, and a
     local page's own numbers double as first-hand Experience markers (Law 16).
  3. SOURCE PRESENCE. The "Cite Sources" lever: contestable claims backed by
     something checkable.
  4. OPERATOR / EXPERT QUOTE. A real attributed quote was the single highest mover in
     the study - and it cannot be fabricated, so it is also an Experience artifact.
  5. KEYWORD STUFFING. The ONLY tactic in the study that made citation LESS likely,
     and independently a spam signal. Detected self-contained: the most-repeated
     meaningful phrase, flagged when its density crosses the ceiling. No keyword list
     needed, so it catches stuffing of a phrase nobody declared as a target.
  6. FRESHNESS STAMP. A visible last-updated date keeps citation eligibility - but
     only when earned by a real content delta (Law 19). This checks PRESENCE only; the
     delta is `decay_monitor`'s job, and a stamp without a delta is a lie this module
     deliberately cannot detect.

This is a DRAFT-TIME ADVISOR, not an optimiser (Law 8). It surfaces where a page is
weak so a human writes a more specific one. It never rewrites, never optimises toward
a number, and never scores AI-detection.

PORT CHANGES: no argparse, no stdout, typed results. Thresholds are named constants.
All patterns and arithmetic carried over verbatim.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.services.content_lint.readability import split_sentences, strip_markdown, words_of

# Corpus defaults.
MIN_STAT_DENSITY = 1.0      # concrete numbers per 100 words
MIN_SOURCES = 1
MIN_QUOTES = 1
MAX_PHRASE_DENSITY = 0.025  # the stuffing ceiling

_LQ, _RQ = "“", "”"

_STAT_RE = re.compile(
    r"\$\s?\d[\d,]*(?:\.\d+)?"     # $1,400 / $ 3,200.50
    r"|\b\d+(?:\.\d+)?\s?%"        # 25% / 4.3 %
    r"|\b\d[\d,]*(?:\.\d+)?\b"     # any standalone number
)

# The anti-direct-answer tells from the passage-block protocol.
_FILLER_OPENERS: tuple[str, ...] = (
    r"there are (?:several|many|a number of|various|multiple)",
    r"when it comes to",
    r"every (?:home|business|situation|project|customer|client) is",
    r"it is important to",
    r"it'?s important to",
    r"in today'?s",
    r"we understand that",
    r"have you ever",
    r"as a (?:homeowner|business owner|property owner)",
    r"one of the (?:most|biggest|best)",
    r"first and foremost",
    r"in this (?:article|section|guide|post|page)",
    r"let'?s (?:take a look|dive|explore|discuss)",
    r"if you'?re like most",
    r"whether you",
    r"there'?s no doubt",
)
# Built via a local rather than a nested f-string: reusing the outer quote inside an
# f-string is Python 3.12+ syntax, and this package targets 3.11.
_FILLER_ALTERNATION = "|".join(_FILLER_OPENERS)
_FILLER_RE = re.compile(rf"^\W*(?:{_FILLER_ALTERNATION})", re.IGNORECASE)

_MD_LINK_RE = re.compile(r"\[[^\]]+\]\((?:https?://|/)[^)]+\)")
_BARE_URL_RE = re.compile(r"(?<!\()\bhttps?://[^\s)]+")
_CITE_CUE_RE = re.compile(
    r"\b(?:according to|source:|sources:|per the|as reported by|data from|citing|cited by)\b",
    re.IGNORECASE,
)
_QUOTE_RE = re.compile(rf'["{_LQ}]([^"{_RQ}]{{18,}}?)["{_RQ}]')
_FRESHNESS_RE = re.compile(
    r"(?:last[\s-]*updated|updated(?:\s+on)?|reviewed(?:\s+on)?|as of)"
    r"[:\s][^\n]{0,40}?(?:19|20)\d{2}"
    r"|\b(?:19|20)\d\d-\d\d-\d\d\b",
    re.IGNORECASE,
)
_H2_RE = re.compile(r"^##(?!#)\s+(.*)$")
_TOKEN_RE = re.compile(r"[a-z0-9]+")

_STOPWORDS: frozenset[str] = frozenset({
    "the", "a", "an", "and", "or", "of", "to", "in", "on", "for", "with", "at",
    "by", "is", "are", "we", "you", "your", "our", "it", "that", "this", "as",
    "be", "can", "will", "from", "us", "has", "have", "do", "does", "if", "so",
})


@dataclass(frozen=True)
class H2Block:
    heading: str
    ok: bool
    reason: str


@dataclass(frozen=True)
class GeoReport:
    total_words: int
    h2: tuple[H2Block, ...]
    stat_count: int
    stat_density: float
    source_count: int
    quote_count: int
    stuffed: bool
    stuff_phrase: str | None
    stuff_occurrences: int
    stuff_density: float
    has_freshness: bool
    min_stat_density: float = MIN_STAT_DENSITY
    min_sources: int = MIN_SOURCES
    min_quotes: int = MIN_QUOTES
    max_phrase_density: float = MAX_PHRASE_DENSITY

    @property
    def n_h2(self) -> int:
        return len(self.h2)

    @property
    def n_h2_ok(self) -> int:
        return sum(1 for b in self.h2 if b.ok)

    @property
    def passed(self) -> bool:
        return not self.issues()

    def issues(self) -> list[str]:
        out: list[str] = []
        if self.n_h2 == 0:
            out.append("no H2 passage blocks found (page is not a federation of "
                       "extractable answers)")
        elif self.n_h2_ok < self.n_h2:
            weak = [b.heading or "(untitled)" for b in self.h2 if not b.ok]
            out.append(f"{self.n_h2 - self.n_h2_ok} of {self.n_h2} H2 blocks do not open "
                       f"with a direct answer: {'; '.join(weak[:5])}")
        if self.stat_density < self.min_stat_density:
            out.append(f"statistic density {self.stat_density:.2f} per 100 words is below "
                       f"target {self.min_stat_density:.2f} (replace vague claims with "
                       "concrete numbers)")
        if self.source_count < self.min_sources:
            out.append(f"only {self.source_count} cited source(s), target {self.min_sources} "
                       "(name a source for each contestable claim)")
        if self.quote_count < self.min_quotes:
            out.append(f"only {self.quote_count} operator/expert quote(s), target "
                       f"{self.min_quotes} (harvest a real quote in the SME interview)")
        if self.stuffed:
            out.append(f'keyword stuffing: "{self.stuff_phrase}" repeats '
                       f"{self.stuff_occurrences}x ({100 * self.stuff_density:.1f}% density, "
                       f"over {100 * self.max_phrase_density:.1f}% ceiling); rewrite for variety")
        if not self.has_freshness:
            out.append("no visible last-updated stamp (add one, earned by a real content "
                       "delta per Law 19)")
        return out


def split_h2_sections(raw: str) -> list[tuple[str, str]]:
    """``(heading, body)`` per H2 block. H3+ stays inside its parent's body.

    Content before the first H2 is the INTRO and is excluded: it is not an answer
    block, so scoring it for direct-answer-first would penalise a normal page opening.
    """
    sections: list[tuple[str, str]] = []
    head: str | None = None
    body: list[str] = []
    for line in raw.splitlines():
        m = _H2_RE.match(line)
        if m:
            if head is not None:
                sections.append((head, "\n".join(body)))
            head, body = m.group(1).strip(), []
        elif head is not None:
            body.append(line)
    if head is not None:
        sections.append((head, "\n".join(body)))
    return sections


def first_sentence(text: str) -> str:
    sentences = split_sentences(strip_markdown(text).strip())
    return sentences[0].strip() if sentences else ""


def opens_with_direct_answer(body: str) -> tuple[bool, str]:
    """A block passes when its opening sentence is not filler AND carries a concrete
    anchor: a number, a yes/no, or a named specific."""
    opener = first_sentence(body)
    if not opener:
        return False, "empty (no answer under the heading)"
    if _FILLER_RE.match(opener):
        return False, f"opens with filler ({opener[:40]}...)"
    has_number = bool(_STAT_RE.search(opener))
    yes_no = bool(re.match(r"^\W*(?:yes|no)\b", opener, re.IGNORECASE))
    # A capitalised word past position 0 usually means a real place, code or brand.
    proper = any(re.match(r"^[A-Z][a-z]+", t) for t in opener.split()[1:])
    if has_number or yes_no or proper:
        return True, "direct answer"
    return False, "no concrete anchor in the opening sentence"


def top_repeated_phrase(tokens: list[str], ns: tuple[int, ...] = (4, 3, 2)) -> tuple[str | None, int, float]:
    """Highest-density repeated meaningful phrase across n-gram sizes.

    Needs 3+ occurrences and at least one non-stopword, so ordinary connective phrasing
    is not reported as stuffing.
    """
    total = max(1, len(tokens))
    best: tuple[str | None, int, float] = (None, 0, 0.0)
    for n in ns:
        counts: dict[str, int] = {}
        for i in range(len(tokens) - n + 1):
            gram = tokens[i : i + n]
            if all(t in _STOPWORDS for t in gram):
                continue
            key = " ".join(gram)
            counts[key] = counts.get(key, 0) + 1
        for phrase, occ in counts.items():
            if occ < 3:
                continue
            density = (occ * n) / total
            if density > best[2]:
                best = (phrase, occ, density)
    return best


def analyse_geo(
    raw: str,
    *,
    min_stat_density: float = MIN_STAT_DENSITY,
    min_sources: int = MIN_SOURCES,
    min_quotes: int = MIN_QUOTES,
    max_phrase_density: float = MAX_PHRASE_DENSITY,
) -> GeoReport:
    """Score a draft on the evidenced GEO levers. Total: never raises, never does I/O."""
    stripped = strip_markdown(raw)
    total_words = max(1, len(words_of(stripped)))
    tokens = _TOKEN_RE.findall(stripped.lower())

    blocks = tuple(
        H2Block(heading, *opens_with_direct_answer(body))
        for heading, body in split_h2_sections(raw)
    )
    stat_count = len(_STAT_RE.findall(stripped))
    # Sources are counted on the RAW markdown: stripping would remove the links.
    source_count = (len(_MD_LINK_RE.findall(raw)) + len(_BARE_URL_RE.findall(raw))
                    + len(_CITE_CUE_RE.findall(raw)))
    quote_count = sum(1 for q in _QUOTE_RE.findall(raw) if len(q.split()) >= 4)
    phrase, occ, density = top_repeated_phrase(tokens)

    return GeoReport(
        total_words=total_words, h2=blocks,
        stat_count=stat_count, stat_density=100.0 * stat_count / total_words,
        source_count=source_count, quote_count=quote_count,
        stuffed=density > max_phrase_density, stuff_phrase=phrase,
        stuff_occurrences=occ, stuff_density=density,
        has_freshness=bool(_FRESHNESS_RE.search(raw)),
        min_stat_density=min_stat_density, min_sources=min_sources,
        min_quotes=min_quotes, max_phrase_density=max_phrase_density,
    )
