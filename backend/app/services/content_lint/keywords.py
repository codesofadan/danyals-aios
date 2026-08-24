"""Keyword density and anti-stuffing, ported from ``seo-content-os/scripts/keyword_density.py``.

Density here is the FRACTION OF THE DOCUMENT'S WORDS COVERED BY A PHRASE, not the
naive count of occurrences:

    density = (occurrences * words_in_phrase) / total_words

That distinction is the whole point. Counting occurrences alone treats a one-word term
and a five-word long-tail phrase as equally "dense", when the long-tail phrase is
occupying five times the page. Google's scaled-content and keyword-stuffing systems
react to saturation, not to a tally.

Note this differs deliberately from ``content_generator._density``, which caps the
per-occurrence multiplier at ``_DENSITY_HEAD_WORDS = 2`` so that a long informational
query is not over-penalised purely for being long. Both are defensible; they answer
slightly different questions, and the generator's variant exists because the raw
measure was tripping the stuffing ceiling on content that was not stuffed. They are
NOT reconciled here - that belongs with the QA dimension rewrite, and doing it inside
a port would bury a behaviour change in a mechanical commit.

The tokenizer is `[a-z0-9]+` (numerals INCLUDED), unlike the readability tokenizer
which counts letters only. That is correct for this check and not an inconsistency: a
keyword can legitimately contain a number ("24 hour plumber", "3d printing"), whereas
a zip code is not a readability word.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from app.services.content_lint.readability import strip_markdown

# Doctrine anti-stuffing ceiling: a phrase covering more than this share of the page.
MAX_DENSITY = 0.025

_TOKEN_RE = re.compile(r"[a-z0-9]+")


@dataclass(frozen=True)
class KeywordDensity:
    keyword: str
    words_in_phrase: int
    occurrences: int
    density: float
    over: bool


@dataclass(frozen=True)
class DensityReport:
    total_words: int
    rows: tuple[KeywordDensity, ...]
    max_density: float = MAX_DENSITY

    @property
    def passed(self) -> bool:
        return not any(row.over for row in self.rows)

    @property
    def stuffed(self) -> tuple[KeywordDensity, ...]:
        return tuple(row for row in self.rows if row.over)

    def issues(self) -> list[str]:
        return [
            f"{row.keyword!r} covers {row.density:.1%} of the page "
            f"({row.occurrences} x {row.words_in_phrase} words), over the "
            f"{self.max_density:.1%} ceiling"
            for row in self.stuffed
        ]


def tokenize(text: str) -> list[str]:
    return _TOKEN_RE.findall(text.lower())


def count_phrase(tokens: Sequence[str], phrase_tokens: Sequence[str]) -> int:
    """Occurrences of a contiguous token sequence. Phrase-aware, so "ac repair" is not
    counted for a page that merely contains "ac" and "repair" far apart."""
    n = len(phrase_tokens)
    if n == 0:
        return 0
    return sum(1 for i in range(len(tokens) - n + 1) if list(tokens[i : i + n]) == list(phrase_tokens))


def analyse_density(
    text: str, keywords: Iterable[str], *, max_density: float = MAX_DENSITY
) -> DensityReport:
    """Measure each keyword's page coverage. Total: never raises, never does I/O."""
    tokens = tokenize(strip_markdown(text))
    total = max(1, len(tokens))

    rows: list[KeywordDensity] = []
    for keyword in keywords:
        phrase = tokenize(keyword)
        if not phrase:
            continue
        occurrences = count_phrase(tokens, phrase)
        density = (occurrences * len(phrase)) / total
        rows.append(
            KeywordDensity(
                keyword=keyword,
                words_in_phrase=len(phrase),
                occurrences=occurrences,
                density=density,
                over=density > max_density,
            )
        )
    return DensityReport(total_words=len(tokens), rows=tuple(rows), max_density=max_density)
