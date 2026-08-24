"""Flesch readability metrics for a draft - the SHARED PRIMITIVE of the lint package.

Ported from ``seo-content-os/scripts/readability_scorer.py`` (P1B). Four other corpus
validators import that script, so this module is the topological root of the port and
everything else in ``content_lint`` builds on its tokenizer.

WHAT CHANGED IN THE PORT (the CLI shell, not the arithmetic):
  * ``argparse`` / ``main`` / ``run`` / stdout are gone. The corpus scripts are
    command-line tools that PRINT and, in 8 of 22 cases, WRITE FILES. Everything here
    is pure: no I/O, no globals, no clock. It runs many times per page inside the QA
    loop, so a subprocess-per-call (the ``danyals-audit-system`` pattern) would be
    strictly worse - that engine is a subprocess because it has heavy incompatible
    dependencies; these are stdlib-only.
  * The ``dict`` return becomes a frozen dataclass so mypy can see the fields.
  * Thresholds become named constants rather than argparse defaults.

The arithmetic is UNCHANGED and deliberately so: it is the reference implementation
that ``tests/test_doctrine_calibration.py`` pins the backend against.

WHY THIS SUPERSEDES ``content_qa.flesch_reading_ease``. Same formula, different
tokenizer, and the corpus tokenizer is right on both counts:

  * ``words_of`` matches LETTERS ONLY. ``content_qa._words`` keeps bare numerals, so
    ``555``, ``90403``, ``2026`` and ``tel`` score as one-syllable words. Numerals are
    short, so they drag syllables-per-word down and push Flesch UP. On a local-SEO
    page - NAP data, prices, dimensions, years in business - that is every page.
  * ``split_sentences`` requires WHITESPACE after the terminator, so ``555.1234`` and
    ``3.5`` stay inside their sentence. ``content_qa._SENTENCE_RE`` splits there,
    reading 101 sentences where this reads 96 on the same page.

Measured delta on the corpus's own samples: 1.4-2.1 Flesch points, the backend always
reading easier. See ``tests/test_doctrine_calibration.py`` for the pinned numbers.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Local service copy reads best at roughly US grade 6-9 (corpus defaults).
MIN_GRADE = 6.0
MAX_GRADE = 9.0
# A sentence longer than this is "long"; too many of them is the readability failure
# mode that survives a good Flesch score.
LONG_SENTENCE_WORDS = 25
MAX_LONG_RATIO = 0.15

_VOWELS = "aeiouy"

_CODE_FENCE_RE = re.compile(r"```.*?```", re.DOTALL)
_INLINE_CODE_RE = re.compile(r"`[^`]*`")
_IMAGE_RE = re.compile(r"!\[[^\]]*\]\([^)]*\)")
_LINK_RE = re.compile(r"\[([^\]]*)\]\([^)]*\)")
_HTML_RE = re.compile(r"<[^>]+>")
_HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s*", re.MULTILINE)
_BULLET_RE = re.compile(r"^\s*[-*+]\s+", re.MULTILINE)
_NUMBERED_RE = re.compile(r"^\s*\d+\.\s+", re.MULTILINE)
_LEFTOVER_MARKS_RE = re.compile(r"[*_~>|#]")

# Split on a terminator followed by WHITESPACE. The whitespace requirement is the
# load-bearing part: it keeps "555.1234" and "3.5" inside one sentence.
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")

# Letters only, with an internal apostrophe. Numerals are NOT words for readability:
# "90403" is read aloud as five syllables, not one, and counting it as a short word
# makes the prose look simpler than it is.
_WORD_RE = re.compile(r"[A-Za-z]+(?:'[A-Za-z]+)?")

_NON_ALPHA_RE = re.compile(r"[^a-z]")


@dataclass(frozen=True)
class ReadabilityReport:
    """One draft's readability measurements. Pure data; no verdict baked in."""

    sentences: int
    words: int
    syllables: int
    words_per_sentence: float
    syllables_per_word: float
    flesch_reading_ease: float
    fk_grade: float
    long_sentences: int
    long_ratio: float

    @property
    def grade_in_band(self) -> bool:
        return MIN_GRADE <= self.fk_grade <= MAX_GRADE

    @property
    def long_sentences_ok(self) -> bool:
        return self.long_ratio <= MAX_LONG_RATIO

    @property
    def passed(self) -> bool:
        """The corpus tool's exit-0 condition, as a property rather than an exit code."""
        return self.grade_in_band and self.long_sentences_ok

    def issues(self) -> list[str]:
        """Human-readable reasons this draft is outside the band (empty when passing)."""
        out: list[str] = []
        if self.fk_grade < MIN_GRADE:
            out.append(f"grade {self.fk_grade:.1f} is below the {MIN_GRADE:.0f}-{MAX_GRADE:.0f} band")
        elif self.fk_grade > MAX_GRADE:
            out.append(f"grade {self.fk_grade:.1f} is above the {MIN_GRADE:.0f}-{MAX_GRADE:.0f} band")
        if not self.long_sentences_ok:
            out.append(
                f"{self.long_ratio:.0%} long sentences exceeds the {MAX_LONG_RATIO:.0%} cap "
                f"({self.long_sentences} of {self.sentences} over {LONG_SENTENCE_WORDS} words)"
            )
        return out


def strip_markdown(text: str) -> str:
    """Remove markdown structure so syntax does not skew the counts.

    Order matters: fences before inline code, images before links (an image is a link
    with a leading ``!``), and the leftover-marks sweep last.
    """
    text = _CODE_FENCE_RE.sub(" ", text)
    text = _INLINE_CODE_RE.sub(" ", text)
    text = _IMAGE_RE.sub(" ", text)          # drop entirely: alt text is not body prose
    text = _LINK_RE.sub(r"\1", text)         # keep the anchor, drop the URL
    text = _HTML_RE.sub(" ", text)
    text = _HEADING_RE.sub("", text)
    text = _BULLET_RE.sub("", text)
    text = _NUMBERED_RE.sub("", text)
    return _LEFTOVER_MARKS_RE.sub(" ", text)


def split_sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENTENCE_SPLIT_RE.split(text.strip()) if s.strip()]


def words_of(text: str) -> list[str]:
    return _WORD_RE.findall(text)


def count_syllables(word: str) -> int:
    """Heuristic English syllable count; at least 1 for any real word, 0 for none.

    Vowel groups, with a silent trailing ``e`` removed EXCEPT after ``le`` - in
    "table" the ``e`` carries the second syllable, so stripping it would undercount.
    """
    lowered = _NON_ALPHA_RE.sub("", word.lower())
    if not lowered:
        return 0
    if len(lowered) <= 3:
        return 1
    count = 0
    prev_vowel = False
    for ch in lowered:
        is_vowel = ch in _VOWELS
        if is_vowel and not prev_vowel:
            count += 1
        prev_vowel = is_vowel
    if lowered.endswith("e") and not lowered.endswith("le"):
        count -= 1
    return max(1, count)


def analyse_readability(text: str, *, long_sentence_words: int = LONG_SENTENCE_WORDS) -> ReadabilityReport:
    """Measure ``text`` (markdown or plain prose). Total: never raises, never empty.

    Empty input yields a zeroed report rather than a ZeroDivisionError, because this
    runs inside the QA loop where a degraded section must not crash the job.
    """
    clean = strip_markdown(text)
    sentences = split_sentences(clean)

    all_words: list[str] = []
    long_count = 0
    for sentence in sentences:
        words = words_of(sentence)
        if len(words) > long_sentence_words:
            long_count += 1
        all_words.extend(words)

    n_sentences = max(1, len(sentences))
    n_words = max(1, len(all_words))
    n_syllables = sum(count_syllables(w) for w in all_words)

    words_per_sentence = n_words / n_sentences
    syllables_per_word = n_syllables / n_words

    return ReadabilityReport(
        sentences=len(sentences),
        words=len(all_words),
        syllables=n_syllables,
        words_per_sentence=words_per_sentence,
        syllables_per_word=syllables_per_word,
        flesch_reading_ease=206.835 - 1.015 * words_per_sentence - 84.6 * syllables_per_word,
        fk_grade=0.39 * words_per_sentence + 11.8 * syllables_per_word - 15.59,
        long_sentences=long_count,
        long_ratio=long_count / n_sentences,
    )
