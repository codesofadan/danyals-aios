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

from app.services.content_lint.blocklist import (
    BlockedTerm,
    BlocklistHit,
    BlocklistReport,
    lint_blocklist,
    parse_blocklist,
    term_to_regex,
)
from app.services.content_lint.compliance import (
    EM_DASH,
    META_DESC_MAX,
    META_TITLE_MAX,
    MIN_SECTION_WORDS,
    ComplianceIssue,
    ComplianceReport,
    extract_meta_values,
    extract_schema_nap,
    lint_compliance,
)
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
from app.services.content_lint.geo import (
    MAX_PHRASE_DENSITY,
    MIN_QUOTES,
    MIN_SOURCES,
    MIN_STAT_DENSITY,
    GeoReport,
    H2Block,
    analyse_geo,
    opens_with_direct_answer,
    split_h2_sections,
    top_repeated_phrase,
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
from app.services.content_lint.links import (
    OVER_LINK_CAP,
    LinkGraph,
    LinkGraphReport,
    LinkPage,
    analyze_links,
    build_graph,
    build_page,
)
from app.services.content_lint.nap import (
    ABBREV,
    MISS,
    VARIANT,
    CanonicalNap,
    NapIssue,
    NapReport,
    check_nap,
    normalise_tokens,
    same_number,
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
from app.services.content_lint.schema import (
    LOCAL_BUSINESS_TYPES,
    REQUIRED_FIELDS,
    SchemaIssue,
    SchemaReport,
    validate_schema,
    walk_nodes,
)
from app.services.content_lint.voice import (
    MAX_FILLER_RATIO,
    VoiceFingerprint,
    compute_filler_ratio,
    distinctive_ngrams,
    fingerprint_voice,
    is_imperative,
)

__all__ = [
    "ABBREV",
    "DUPLICATE_THRESHOLD",
    "EM_DASH",
    "ITEM_CATEGORIES",
    "LOCAL_BUSINESS_TYPES",
    "LONG_SENTENCE_WORDS",
    "MARKER_KINDS",
    "MAX_DENSITY",
    "MAX_FILLER_RATIO",
    "MAX_GRADE",
    "MAX_LONG_RATIO",
    "MAX_PHRASE_DENSITY",
    "META_DESC_MAX",
    "META_TITLE_MAX",
    "MIN_GAIN",
    "MIN_GRADE",
    "MIN_QUOTES",
    "MIN_SECTION_WORDS",
    "MIN_SOURCES",
    "MIN_STAT_DENSITY",
    "MISS",
    "OVER_LINK_CAP",
    "REQUIRED_FIELDS",
    "SHINGLE_SIZE",
    "VARIANT",
    "BlockedTerm",
    "BlocklistHit",
    "BlocklistReport",
    "CanonicalNap",
    "ComplianceIssue",
    "ComplianceReport",
    "ConversionIssue",
    "ConversionReport",
    "DensityReport",
    "DuplicationReport",
    "ExperienceClaim",
    "ExperienceIssue",
    "ExperienceMarker",
    "ExperienceReport",
    "GainReport",
    "GeoReport",
    "H2Block",
    "KeywordDensity",
    "LinkGraph",
    "LinkGraphReport",
    "LinkPage",
    "NapIssue",
    "NapReport",
    "PairSimilarity",
    "ReadabilityReport",
    "SchemaIssue",
    "SchemaReport",
    "VoiceFingerprint",
    "analyse_density",
    "analyse_geo",
    "analyse_readability",
    "analyze_links",
    "build_graph",
    "build_page",
    "check_nap",
    "compare_documents",
    "compute_filler_ratio",
    "content_tokens",
    "count_phrase",
    "count_syllables",
    "distinctive_ngrams",
    "evaluate_experience",
    "extract_items",
    "extract_meta_values",
    "extract_schema_nap",
    "find_claims",
    "find_headings",
    "find_markers",
    "fingerprint_voice",
    "is_imperative",
    "is_lead_cta",
    "is_mechanical_cta",
    "is_strong_cta",
    "jaccard",
    "lint_blocklist",
    "lint_compliance",
    "lint_conversion",
    "net_new",
    "normalise_tokens",
    "opens_with_direct_answer",
    "parse_blocklist",
    "residual_ratio",
    "same_number",
    "score_information_gain",
    "shingle_hashes",
    "shingle_set",
    "signals_from_manifest_text",
    "split_h2_sections",
    "split_sentences",
    "strip_markdown",
    "term_to_regex",
    "tokenize",
    "top_repeated_phrase",
    "validate_schema",
    "walk_nodes",
    "words_of",
]
