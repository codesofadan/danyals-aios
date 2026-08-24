"""Deterministic, offline content validators ported from the SEO-CONTENT-OS corpus.

These are the "build it, don't buy it" half of the content system. Every check here is
stdlib-only and network-free, so it costs nothing per page and can run as many times
as the QA loop needs. What a vendor would sell as a readability API, a keyword-density
tool or an originality score is computed in-process instead.

PROVENANCE. Each module ports one script from ``backend/seo-content-os/scripts/``,
which `test_doctrine_corpus.py` hashes against MANIFEST.json. The port keeps the
arithmetic verbatim and drops the CLI shell - the corpus scripts are command-line
tools that print, and 8 of the 22 WRITE FILES as a side effect. Nothing in this
package touches the filesystem, the network, the clock, or a global.

PORT ORDER IS TOPOLOGICAL, not arbitrary. The corpus scripts import each other, with
``readability_scorer`` as the shared primitive that four others depend on, so it is
ported first and the rest build on its tokenizer. Porting them one at a time in
dimension order would have duplicated that tokenizer four ways.

WHY IN-PROCESS RATHER THAN SUBPROCESS. ``danyals-audit-system`` is invoked as a
subprocess because it is a separate product with its own heavy, incompatible
dependency set. These are stdlib-only pure functions called many times per page; a
process spawn per call would be strictly worse and untestable.
"""

from app.services.content_lint.conversion import (
    ConversionIssue,
    ConversionReport,
    find_headings,
    is_lead_cta,
    is_mechanical_cta,
    is_strong_cta,
    lint_conversion,
)
from app.services.content_lint.duplication import (
    DUPLICATE_THRESHOLD,
    SHINGLE_SIZE,
    DuplicationReport,
    PairSimilarity,
    compare_documents,
    jaccard,
    shingle_hashes,
    shingle_set,
)
from app.services.content_lint.experience import (
    MARKER_KINDS,
    ExperienceClaim,
    ExperienceIssue,
    ExperienceMarker,
    ExperienceReport,
    evaluate_experience,
    find_claims,
    find_markers,
    signals_from_manifest_text,
)
from app.services.content_lint.information_gain import (
    ITEM_CATEGORIES,
    MIN_GAIN,
    GainReport,
    content_tokens,
    extract_items,
    net_new,
    residual_ratio,
    score_information_gain,
)
from app.services.content_lint.keywords import (
    MAX_DENSITY,
    DensityReport,
    KeywordDensity,
    analyse_density,
    count_phrase,
    tokenize,
)
from app.services.content_lint.readability import (
    LONG_SENTENCE_WORDS,
    MAX_GRADE,
    MAX_LONG_RATIO,
    MIN_GRADE,
    ReadabilityReport,
    analyse_readability,
    count_syllables,
    split_sentences,
    strip_markdown,
    words_of,
)

__all__ = [
    "DUPLICATE_THRESHOLD",
    "ITEM_CATEGORIES",
    "LONG_SENTENCE_WORDS",
    "MARKER_KINDS",
    "MAX_DENSITY",
    "MAX_GRADE",
    "MAX_LONG_RATIO",
    "MIN_GAIN",
    "MIN_GRADE",
    "SHINGLE_SIZE",
    "ConversionIssue",
    "ConversionReport",
    "DensityReport",
    "DuplicationReport",
    "ExperienceClaim",
    "ExperienceIssue",
    "ExperienceMarker",
    "ExperienceReport",
    "GainReport",
    "KeywordDensity",
    "PairSimilarity",
    "ReadabilityReport",
    "analyse_density",
    "analyse_readability",
    "compare_documents",
    "content_tokens",
    "count_phrase",
    "count_syllables",
    "evaluate_experience",
    "extract_items",
    "find_claims",
    "find_headings",
    "find_markers",
    "is_lead_cta",
    "is_mechanical_cta",
    "is_strong_cta",
    "jaccard",
    "lint_conversion",
    "net_new",
    "residual_ratio",
    "score_information_gain",
    "shingle_hashes",
    "shingle_set",
    "signals_from_manifest_text",
    "split_sentences",
    "strip_markdown",
    "tokenize",
    "words_of",
]
