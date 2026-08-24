"""Voice fingerprint - measurable idiolect from a client's own writing.

Ported from ``seo-content-os/scripts/voice_fingerprint.py`` (P1B).

Seeds the brand-voice profile from a corpus of what the client ALREADY writes: their
current pages, email replies, discovery-call transcripts, GBP posts. It measures the
idiolect a hand-written voice template cannot capture, so the writer matches how this
one business actually sounds rather than how service businesses sound in general.

A MEASUREMENT TOOL, NOT A HUMANIZER. It reports numbers and candidate phrases and
never rewrites anything, and it does not score AI detection (Law 8).

What it measures, and why each one:

  * SENTENCE RHYTHM - mean, variance, stdev, and the short/medium/long mix. Flat
    variance is the machine tell; human writing is bursty. This quantifies the
    burstiness instead of asserting it.
  * SYLLABLES PER WORD - a lexical-complexity proxy that seeds reading level.
  * CONTRACTION RATE - high means a conversational register ("we'll", "don't");
    near-zero means formal or corporate.
  * QUESTION and IMPERATIVE RATE - local service copy that converts leans on direct
    imperatives ("Call by 4pm").
  * DISTINCTIVE N-GRAMS - phrases frequent in THIS corpus and absent from the generic
    marketing baseline. These are the candidate characteristic phrases the operator
    actually uses. Multi-word grams are weighted up, because a phrase is far more
    characteristic of a voice than a single word.

THE GUARDRAIL IS THE CLEVER PART. ``filler_ratio`` measures how much of the corpus is
generic marketing slop. A client site can itself be generic, and a naive
learn-the-voice tool would faithfully learn "trusted partner" and "peace of mind" and
then reproduce them forever. A high filler ratio means the source must NOT be learned
from - the caller checks this BEFORE adopting any of the measurements. Filler grams
are also excluded from the distinctive ranking, so slop can never surface as a
"characteristic phrase".

PORT NOTE: the original carries its own copies of ``strip_markup`` / ``split_sentences``
/ ``words_of`` / ``count_syllables``. Verified byte-identical in behaviour to the
readability module's, so those are reused rather than duplicated a fourth time - the
equivalence was CHECKED, not assumed.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass

from app.services.content_lint.readability import (
    count_syllables,
    split_sentences,
    strip_markdown,
    words_of,
)

# Above this share of generic filler, the source is slop and its voice must not be
# learned. The caller checks this before adopting any other measurement.
MAX_FILLER_RATIO = 0.08

_STOPWORDS: frozenset[str] = frozenset({
    "a", "an", "the", "and", "or", "but", "if", "so", "as", "of", "at", "by",
    "for", "in", "into", "on", "onto", "to", "up", "out", "off", "over", "with",
    "from", "is", "are", "was", "were", "be", "been", "being", "am", "do",
    "does", "did", "have", "has", "had", "will", "would", "can", "could",
    "shall", "should", "may", "might", "must", "i", "you", "he", "she", "it",
    "we", "they", "me", "him", "her", "us", "them", "my", "your", "his", "its",
    "our", "their", "this", "that", "these", "those", "there", "here", "who",
    "what", "which", "when", "where", "why", "how", "not", "no", "yes", "than",
    "then", "too", "very", "just", "also", "about", "all", "any", "some",
})

_FILLER_TOKENS: frozenset[str] = frozenset({
    "solutions", "seamless", "trusted", "partner", "premier", "leading",
    "cutting", "edge", "innovative", "unparalleled", "unmatched", "bespoke",
    "tailored", "holistic", "synergy", "leverage", "empower", "elevate",
    "unlock", "seamlessly", "effortless", "worry", "free", "peace", "mind",
    "commitment", "dedicated", "passionate", "strive", "ensure", "utilize",
    "utilise", "comprehensive", "robust", "dynamic", "state", "art", "world",
    "class", "top", "notch", "one", "stop", "shop", "excellence", "quality",
    "professional", "professionals", "expertise", "reliable", "affordable",
    "journey", "delight", "delighted", "pride", "proudly", "needs", "goals",
    "vision", "mission", "values", "customer", "satisfaction", "exceed",
    "expectations", "wide", "range", "variety", "array", "diverse", "boasts",
    "nestled", "heart", "whether", "look", "further", "rest", "assured",
})

_FILLER_PHRASES: tuple[str, ...] = (
    "trusted partner", "seamless solutions", "peace of mind",
    "state of the art", "one stop shop", "wide range", "worry free",
    "we pride ourselves", "we strive to", "when it comes to", "look no further",
    "rest assured", "your trusted", "nestled in the heart", "top notch",
    "customer satisfaction", "exceed your expectations", "your unique needs",
    "committed to providing", "dedicated to providing", "wide variety of",
    "cutting edge", "world class", "your one stop", "tailored to your",
    "here to help", "we understand that", "at the end of the day",
)

_IMPERATIVE_VERBS: frozenset[str] = frozenset({
    "call", "get", "book", "schedule", "request", "find", "save", "stop",
    "start", "try", "ask", "learn", "see", "check", "grab", "claim", "reserve",
    "contact", "visit", "explore", "discover", "join", "sign", "read", "meet",
    "let", "give", "take", "make", "keep", "skip", "beat", "avoid", "protect",
    "fix", "repair", "replace", "upgrade", "compare", "choose", "pick",
    "download", "watch", "tell", "talk", "reach", "hire", "trust", "leave",
})

_CONTRACTION_RE = re.compile(r"[A-Za-z]+'[A-Za-z]+")

Ngram = tuple[str, int, float]  # (phrase, count, score)


@dataclass(frozen=True)
class VoiceFingerprint:
    sentences: int
    words: int
    avg_sentence_len: float
    sentence_len_variance: float
    sentence_len_stdev: float
    min_sentence_len: int
    max_sentence_len: int
    short_sentences: int
    medium_sentences: int
    long_sentences: int
    syllables_per_word: float
    contraction_rate_per_100w: float
    question_rate: float
    imperative_rate: float
    filler_ratio: float
    filler_word_hits: int
    filler_phrase_hits: int
    distinctive_unigrams: tuple[Ngram, ...] = ()
    distinctive_bigrams: tuple[Ngram, ...] = ()
    distinctive_trigrams: tuple[Ngram, ...] = ()
    max_filler_ratio: float = MAX_FILLER_RATIO

    @property
    def learnable(self) -> bool:
        """False when the source corpus is itself generic slop.

        Check this BEFORE adopting any other measurement. A naive tool would learn
        "trusted partner" from a generic site and reproduce it forever.
        """
        return self.filler_ratio <= self.max_filler_ratio

    @property
    def is_bursty(self) -> bool:
        """Human writing varies sentence length; flat variance is the machine tell."""
        return self.sentence_len_stdev >= 5.0


def is_imperative(sentence: str) -> bool:
    """First real word is a known imperative verb and the sentence is not a question.
    Approximate by design: a signal for the voice profile, not a grammatical claim."""
    if sentence.strip().endswith("?"):
        return False
    words = words_of(sentence)
    if not words:
        return False
    return words[0].lower().split("'")[0] in _IMPERATIVE_VERBS


def _is_all_stop(tokens: tuple[str, ...]) -> bool:
    return all(t in _STOPWORDS for t in tokens)


def _is_filler(tokens: tuple[str, ...]) -> bool:
    """Filler when the whole gram is a known filler phrase, or every content word in
    it is a filler token."""
    if " ".join(tokens) in _FILLER_PHRASES:
        return True
    content = [t for t in tokens if t not in _STOPWORDS]
    return bool(content) and all(t in _FILLER_TOKENS for t in content)


def distinctive_ngrams(
    sentence_tokens: list[list[str]], n: int, min_count: int, top: int
) -> tuple[Ngram, ...]:
    counts: Counter[tuple[str, ...]] = Counter()
    for tokens in sentence_tokens:
        for i in range(len(tokens) - n + 1):
            counts[tuple(tokens[i : i + n])] += 1

    ranked: list[Ngram] = []
    for gram, count in counts.items():
        if count < min_count or _is_all_stop(gram) or _is_filler(gram):
            continue
        # A repeated multi-word phrase is far more characteristic of a voice than a
        # single word, so length weights the score.
        ranked.append((" ".join(gram), count, round(count * (1 + 0.75 * (n - 1)), 2)))
    ranked.sort(key=lambda r: (-r[2], -r[1], r[0]))
    return tuple(ranked[:top])


def compute_filler_ratio(
    sentence_tokens: list[list[str]], normalised_text: str
) -> tuple[float, int, int]:
    """``(ratio, word_hits, phrase_hits)``. Phrase hits are weighted by phrase length
    so a filler phrase counts across its whole span, and the ratio is bounded at 1."""
    total = sum(len(t) for t in sentence_tokens)
    word_hits = sum(1 for tokens in sentence_tokens for t in tokens if t in _FILLER_TOKENS)
    phrase_hits = sum(normalised_text.count(p) for p in _FILLER_PHRASES)
    phrase_tokens = sum(normalised_text.count(p) * len(p.split()) for p in _FILLER_PHRASES)
    return min(1.0, (word_hits + phrase_tokens) / max(1, total)), word_hits, phrase_hits


def fingerprint_voice(text: str, *, top: int = 20, min_count: int = 2) -> VoiceFingerprint:
    """Measure a corpus's voice. Total: never raises, never does I/O."""
    sentences = split_sentences(strip_markdown(text))

    lengths: list[int] = []
    all_words: list[str] = []
    sentence_tokens: list[list[str]] = []
    questions = imperatives = 0

    for sentence in sentences:
        words = words_of(sentence)
        if not words:
            continue
        lengths.append(len(words))
        all_words.extend(words)
        if sentence.strip().endswith("?"):
            questions += 1
        if is_imperative(sentence):
            imperatives += 1
        sentence_tokens.append([w.lower() for w in words])

    n_sentences = max(1, len(lengths))
    n_words = max(1, len(all_words))
    mean_len = sum(lengths) / n_sentences
    variance = sum((length - mean_len) ** 2 for length in lengths) / n_sentences

    normalised = " ".join(t for tokens in sentence_tokens for t in tokens)
    ratio, word_hits, phrase_hits = compute_filler_ratio(sentence_tokens, normalised)

    return VoiceFingerprint(
        sentences=len(lengths),
        words=len(all_words),
        avg_sentence_len=round(mean_len, 1),
        sentence_len_variance=round(variance, 1),
        sentence_len_stdev=round(math.sqrt(variance), 1),
        min_sentence_len=min(lengths) if lengths else 0,
        max_sentence_len=max(lengths) if lengths else 0,
        short_sentences=sum(1 for length in lengths if length <= 8),
        medium_sentences=sum(1 for length in lengths if 9 <= length <= 20),
        long_sentences=sum(1 for length in lengths if length > 20),
        syllables_per_word=round(sum(count_syllables(w) for w in all_words) / n_words, 2),
        contraction_rate_per_100w=round(100 * len(_CONTRACTION_RE.findall(text)) / n_words, 1),
        question_rate=round(questions / n_sentences, 3),
        imperative_rate=round(imperatives / n_sentences, 3),
        filler_ratio=round(ratio, 3),
        filler_word_hits=word_hits,
        filler_phrase_hits=phrase_hits,
        distinctive_unigrams=distinctive_ngrams(sentence_tokens, 1, min_count, top),
        distinctive_bigrams=distinctive_ngrams(sentence_tokens, 2, min_count, top),
        distinctive_trigrams=distinctive_ngrams(sentence_tokens, 3, min_count, top),
    )
