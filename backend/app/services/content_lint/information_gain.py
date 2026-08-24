"""Information gain: what a page ADDS beyond the SERP consensus.

Ported from ``seo-content-os/scripts/information_gain_scorer.py`` (P1B).

Google's information-gain patent rewards the material a page contributes that the
existing results do not already contain - not how completely it covers the topic. So
coverage is the wrong target and "comprehensive" is not a virtue by itself. The test
is: take the bland consensus answer for the query, align the draft against it, and
measure the RESIDUAL - what survives that is genuinely new.

Two numbers, and they answer different questions:

  * ``residual`` - the share of the draft's token sequence not aligned to the
    consensus, via ``difflib`` longest-matching-block alignment. This is the headline.
    A thin residual means the page is a rehash however well written it is.
  * ``net_new`` - the concrete gain-bearing SPECIFICS present in the draft and absent
    from the consensus: NUMBERS (prices, counts, years), QUOTES (operator or customer
    voice), ENTITIES (multi-word proper nouns - crews, streets, neighbourhoods). This
    is where first-party gain actually lives, and it is the inventory the SME
    interview should be filling.

THIS MODULE NEVER CALLS A MODEL. The consensus baseline is supplied BY THE CALLER.
That is a deliberate boundary from the corpus design: generating the bland answer is a
model's job and costs money, while measuring the residual is arithmetic and is free.
Keeping them apart means the expensive half runs once per query and can be cached,
and this half can run on every redraft at no cost.

WHY IT MATTERS HERE. ``content_qa``'s ``information_gain`` is a HARD-GATE dimension,
but with no ``Judge`` wired it falls back to checking that a ``differentiation_angle``
string is merely PRESENT and grounded. Present is not the same as new. This measures
newness against something external, which is the only way the question can be
answered.

PORT CHANGES: no file reads, no argparse, typed results. The arithmetic and every
pattern are carried over verbatim.
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass

from app.services.content_lint.readability import strip_markdown

# Doctrine floor: below this share of net-new material the page is a rehash.
MIN_GAIN = 0.30

_LDQUO, _RDQUO = "“", "”"

_NUMBER_RE = re.compile(
    r"\$\s?\d[\d,]*(?:\.\d+)?%?|\b\d[\d,]*(?:\.\d+)?\s?%|\b(?:19|20)\d{2}\b|\b\d[\d,]*(?:\.\d+)?\b"
)
_QUOTE_RE = re.compile(
    r'"([^"\n]{6,240})"' + r"|" + _LDQUO + r"([^" + _RDQUO + r"\n]{6,240})" + _RDQUO
)
_ENTITY_RE = re.compile(
    r"\b[A-Z][a-zA-Z0-9]+(?:\s+(?:[A-Z][a-zA-Z0-9]+|[a-z]{1,3}\s+[A-Z][a-zA-Z0-9]+)){1,4}\b"
)
_CONTENT_TOKEN_RE = re.compile(r"[a-z0-9']+")

# Sentence-initial words a capitalisation-based entity finder would misread as part of
# a proper noun ("The Round Rock crew" -> "Round Rock", not "The Round Rock").
_STOP_LEAD: frozenset[str] = frozenset({
    "The", "This", "That", "These", "Those", "Our", "Your", "We", "You",
    "When", "Where", "What", "Why", "How", "If", "In", "On", "At", "For",
    "And", "But", "Most", "Every", "Each", "A", "An", "It", "They", "He",
    "She", "Google", "Call", "Book", "Get", "See",
})

ITEM_CATEGORIES: tuple[str, ...] = ("NUMBERS", "QUOTES", "ENTITIES")


@dataclass(frozen=True)
class GainReport:
    """One draft's information gain. ``residual`` is None when no baseline was given."""

    items: dict[str, tuple[str, ...]]
    net_new: dict[str, tuple[str, ...]]
    item_count: int
    net_new_count: int
    has_consensus: bool
    residual: float | None = None
    matched_tokens: int = 0
    total_tokens: int = 0
    min_gain: float = MIN_GAIN

    @property
    def passed(self) -> bool:
        """Without a baseline this cannot be judged, so it does not fail - it abstains.

        Reporting "pass" for an unmeasurable page would be worse than reporting
        nothing; callers must check :attr:`has_consensus` before trusting a verdict.
        """
        if self.residual is None:
            return True
        return self.residual >= self.min_gain

    def issues(self) -> list[str]:
        if self.residual is None:
            return []
        if self.residual >= self.min_gain:
            return []
        return [
            f"information gain {self.residual:.0%} is below the {self.min_gain:.0%} "
            f"floor: {self.matched_tokens} of {self.total_tokens} tokens already "
            "appear in the consensus answer, so the page is a rehash"
        ]


def content_tokens(text: str) -> list[str]:
    return _CONTENT_TOKEN_RE.findall(strip_markdown(text).lower())


def _dedupe(seq: list[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(seq))


def extract_items(text: str) -> dict[str, tuple[str, ...]]:
    """Gain-bearing specifics in the draft, deduped, in document order."""
    clean = strip_markdown(text)

    numbers = [m.group(0).strip() for m in _NUMBER_RE.finditer(clean)]

    quotes: list[str] = []
    for m in _QUOTE_RE.finditer(clean):
        quoted = (m.group(1) or m.group(2) or "").strip()
        if quoted:
            quotes.append(quoted)

    entities: list[str] = []
    for m in _ENTITY_RE.finditer(clean):
        phrase = m.group(0).strip()
        if phrase.split()[0] in _STOP_LEAD:
            rest = phrase.split(None, 1)
            if len(rest) == 2 and len(rest[1].split()) >= 2:
                entities.append(rest[1])
            continue
        entities.append(phrase)

    return {"NUMBERS": _dedupe(numbers), "QUOTES": _dedupe(quotes), "ENTITIES": _dedupe(entities)}


def net_new(items: dict[str, tuple[str, ...]], consensus_text: str) -> dict[str, tuple[str, ...]]:
    """Items present in the draft and absent from the consensus baseline."""
    hay = consensus_text.lower()
    return {cat: tuple(v for v in values if v.lower() not in hay) for cat, values in items.items()}


def residual_ratio(draft_text: str, consensus_text: str) -> tuple[float, int, int]:
    """``(residual, matched_tokens, total_tokens)`` for the draft against the baseline.

    ``autojunk=False`` matters: difflib's default heuristic discards tokens appearing
    in more than 1% of a long sequence, which on prose means the common words - and
    would inflate the apparent residual exactly where it should not.
    """
    draft = content_tokens(draft_text)
    base = content_tokens(consensus_text)
    if not draft:
        return 0.0, 0, 0
    matcher = difflib.SequenceMatcher(None, base, draft, autojunk=False)
    matched = min(sum(block.size for block in matcher.get_matching_blocks()), len(draft))
    return 1.0 - (matched / len(draft)), matched, len(draft)


def score_information_gain(
    draft_text: str, consensus_text: str | None = None, *, min_gain: float = MIN_GAIN
) -> GainReport:
    """Measure net-new value. Total: never raises, never does I/O, never calls a model."""
    items = extract_items(draft_text)
    item_count = sum(len(v) for v in items.values())

    if consensus_text is None:
        # No baseline: inventory only. Everything is "unverified new" - reported as
        # such rather than scored, because a residual against nothing is meaningless.
        return GainReport(
            items=items, net_new=items, item_count=item_count, net_new_count=item_count,
            has_consensus=False, residual=None, min_gain=min_gain,
        )

    ratio, matched, total = residual_ratio(draft_text, consensus_text)
    fresh = net_new(items, consensus_text)
    return GainReport(
        items=items, net_new=fresh, item_count=item_count,
        net_new_count=sum(len(v) for v in fresh.values()),
        has_consensus=True, residual=ratio, matched_tokens=matched,
        total_tokens=total, min_gain=min_gain,
    )
