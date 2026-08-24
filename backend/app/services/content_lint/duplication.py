"""Near-duplicate detection across sibling pages - the anti-doorway gate.

Ported from ``seo-content-os/scripts/duplication_gate.py`` (P1B).

This hardens the doorway rule. Google's spam policy names "sites or pages created to
rank for specific, similar search queries" that offer nothing unique per page. A
multi-location client may legitimately have many pages, but only if each carries a
genuinely differentiated first-party dataset. This makes that testable.

Method: w-shingling. Each page is stripped to prose, tokenized, and reduced to the set
of its overlapping w-word shingles. Shingling is ORDER-SENSITIVE, which is the reason
it is used instead of a bag-of-words measure: a templated page with a swapped city
token still scores high, while two genuinely distinct pages score low. Similarity is
Jaccard, |A n B| / |A u B|.

WHY THIS IS THE MOST IMPORTANT VALIDATOR IN THE PACKAGE. This is the failure mode the
platform itself creates. `content_generator._FRAMEWORK_MOVES` is a fixed heading table,
so two competing plumbers in two cities receive byte-identical heading skeletons - a
textbook scaled-content-abuse fingerprint, produced by us. `content_qa`'s current
`originality` dimension falls back to an internal-duplication proxy that compares a
page only against ITSELF, so it cannot see this at all. Cross-page comparison is the
only thing that can.

PORT CHANGES. The original reads FILE PATHS and expands directories. This takes
already-loaded texts, because the ports must be pure and because P2 keeps drafts in
Postgres rather than on disk. The scoring arithmetic is unchanged.

Added for P2: :func:`shingle_hashes` emits stable 64-bit hashes. Comparing a new
outline against every prior page in a vertical cannot hold all shingle sets in memory,
so ``content_outline_shingles`` stores hashes in an indexed table and the comparison
becomes a SQL intersection. The hash is blake2b, NOT the builtin ``hash()``, which is
randomised per process by PYTHONHASHSEED and would silently change between workers.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping
from dataclasses import dataclass
from itertools import combinations

from app.services.content_lint.readability import strip_markdown

# Doctrine boilerplate ceiling: a pair at or above this is near-duplicate.
DUPLICATE_THRESHOLD = 0.70
SHINGLE_SIZE = 5

_TOKEN_RE = re.compile(r"[a-z0-9']+")

Shingle = tuple[str, ...]


@dataclass(frozen=True)
class PairSimilarity:
    left: str
    right: str
    similarity: float
    duplicate: bool


@dataclass(frozen=True)
class DuplicationReport:
    pairs: tuple[PairSimilarity, ...]
    threshold: float = DUPLICATE_THRESHOLD

    @property
    def passed(self) -> bool:
        return not any(p.duplicate for p in self.pairs)

    @property
    def duplicates(self) -> tuple[PairSimilarity, ...]:
        return tuple(p for p in self.pairs if p.duplicate)

    @property
    def worst(self) -> PairSimilarity | None:
        return max(self.pairs, key=lambda p: p.similarity, default=None)

    def issues(self) -> list[str]:
        return [
            f"{p.left!r} and {p.right!r} are {p.similarity:.0%} identical, at or over "
            f"the {self.threshold:.0%} boilerplate ceiling"
            for p in self.duplicates
        ]


def tokenize(text: str) -> list[str]:
    return _TOKEN_RE.findall(strip_markdown(text).lower())


def shingles(tokens: list[str], size: int = SHINGLE_SIZE) -> frozenset[Shingle]:
    """Overlapping ``size``-word shingles. A document shorter than one shingle
    collapses to a single shingle rather than vanishing, so short pages still compare."""
    if len(tokens) < size:
        return frozenset({tuple(tokens)}) if tokens else frozenset()
    return frozenset(tuple(tokens[i : i + size]) for i in range(len(tokens) - size + 1))


def jaccard(a: frozenset[Shingle], b: frozenset[Shingle]) -> float:
    if not a and not b:
        return 0.0
    union = len(a | b)
    return len(a & b) / union if union else 0.0


def shingle_set(text: str, *, size: int = SHINGLE_SIZE) -> frozenset[Shingle]:
    return shingles(tokenize(text), size)


def shingle_hashes(text: str, *, size: int = SHINGLE_SIZE) -> frozenset[int]:
    """Stable signed-64-bit hashes of a text's shingles, for the P2 shingle index.

    blake2b rather than the builtin ``hash()``: PYTHONHASHSEED randomises the latter
    per process, so two workers would produce different values for the same page and
    the index would silently stop matching. Signed because Postgres ``bigint`` is.
    """
    out: set[int] = set()
    for shingle in shingle_set(text, size=size):
        digest = hashlib.blake2b(" ".join(shingle).encode("utf-8"), digest_size=8).digest()
        out.add(int.from_bytes(digest, "big", signed=True))
    return frozenset(out)


def compare_documents(
    documents: Mapping[str, str],
    *,
    size: int = SHINGLE_SIZE,
    threshold: float = DUPLICATE_THRESHOLD,
) -> DuplicationReport:
    """Score every unordered pair of ``{label: text}``.

    Fewer than two documents yields an empty, passing report rather than an error: a
    single page genuinely has no sibling to duplicate, and this sits on the QA path.
    """
    sets = {label: shingle_set(text, size=size) for label, text in documents.items()}
    pairs = tuple(
        PairSimilarity(left, right, sim := jaccard(sets[left], sets[right]), sim >= threshold)
        for left, right in combinations(sets, 2)
    )
    return DuplicationReport(pairs=pairs, threshold=threshold)
