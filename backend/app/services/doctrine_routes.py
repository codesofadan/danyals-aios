"""Which doctrine governs which stage - the hand-authored routing table.

Turns ``(stage, page_type, vertical, framework)`` into the three cached prompt blocks
the pipeline sends. This is the deliberate alternative to semantic retrieval: 133
curated files do not need embeddings, and a table is deterministic, free, testable and
auditable in a way a similarity score is not.

THE THREE-BLOCK STRUCTURE EXISTS FOR PROMPT CACHING, not tidiness. Anthropic bills a
cache write at 1.25x and a cache read at 0.1x, so a block's value depends entirely on
how often it changes AND on how many calls reuse it - a block sent once is 25% more
expensive cached than plain (see :meth:`PromptBlocks.cache_flags`):

    Block A  CONSTITUTION  ~20k tokens   NEVER varies      -> written once, read always
    Block B  STAGE ROLE    ~4k tokens    varies per stage  -> one write per stage
    Block C  PAGE PACK     ~10-18k       varies per job    -> one write per page type

Ordering matters and is not cosmetic: the cache matches on a PREFIX, so the most
stable block must come first. Putting the page pack ahead of the constitution would
invalidate the whole prefix on every new page type and forfeit the entire saving.

MEASURED, and this corrected an assumption worth stating. Block A is 20,257 tokens and
IS shared by every call, but B and C change per stage - so the shared prefix is 20k,
not the ~45k a single-prefix model would assume. Per page that puts the doctrine at
about $0.70 cold rather than $0.29.

The lever that actually matters is BATCHING. Within one batch of the same
(page_type, vertical), every block is already warm, so every call is a read:

    cold (a one-off page)            $0.70
    warm (a page inside a batch)     $0.18      3.9x cheaper

A 50-page site ordered by (vertical, page_type) is 1 cold page plus 49 warm ones, so
the doctrine amortises to about $0.23 per page. That ordering is not an optimisation
to do later; it is the difference between a $35 site and a $12 one.

WHAT IS DELIBERATELY NOT HERE. `research/` is indexed nowhere and routed nowhere - it
is provenance for why the doctrine says what it says, not instruction. And no stage
receives the whole corpus: a stage that gets everything is a stage with no priorities,
and 428k tokens of doctrine would drown the actual brief.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.services.doctrine import DoctrineChunk, fit, resolve, total_tokens

# --- Block A: the constitution. Identical for every call, forever. ---------- #
CONSTITUTION_REFS: tuple[str, ...] = (
    "CLAUDE.md",
    "knowledge/doctrine/seo-system-doctrine.md",       # Laws 1-20
    "knowledge/doctrine/google-compliance-spine.md",   # the 33 rules
    "knowledge/voice/vocabulary-blocklist.md",         # Tier-1 bans
)

# --- Block B: the stage's role, one corpus agent definition per stage ------- #
STAGE_AGENT: dict[str, str] = {
    "keyword_discovery": "agents/keyword-intent-researcher.md",
    "topical_map": "agents/topical-map-architect.md",
    "sme": "agents/sme-interviewer.md",
    "research": "agents/keyword-intent-researcher.md",
    "outline": "agents/outline-architect.md",
    "draft": "agents/voice-writer.md",
    "convert": "agents/conversion-optimizer.md",
    "voice": "agents/critical-editor.md",
    "title_meta": "agents/outline-architect.md",
    "links": "agents/link-architect.md",
    "schema": "agents/schema-linking-finisher.md",
    "gate": "agents/compliance-auditor.md",
}

# --- Block C: the page pack ------------------------------------------------ #
# The backend's `content_page_type` enum is service | blog | local | gbp_post. The
# corpus has finer page types, so the extra keys are reachable once the engagement
# tier (P4) can express them; mapping them now costs nothing and avoids a second
# table later.
PAGE_PLAYBOOK: dict[str, str] = {
    "service": "knowledge/playbooks/service-page.md",
    "local": "knowledge/playbooks/service-city-page.md",
    "gbp_post": "knowledge/playbooks/gbp-posts.md",
    # `blog` has no corpus playbook - it is not a local money page. The passage-block
    # protocol carries the extractability rules that matter for it, and pretending a
    # service-page playbook applies would import the wrong structure wholesale.
    "blog": "knowledge/foundations/passage-block-protocol.md",
    "homepage": "knowledge/playbooks/homepage.md",
    "location": "knowledge/playbooks/location-page.md",
    "service_area": "knowledge/playbooks/service-area-page.md",
    "about": "knowledge/playbooks/about-team-page.md",
    "faq": "knowledge/playbooks/faq-page.md",
    "local_asset": "knowledge/playbooks/local-asset.md",
    "unit_size": "knowledge/playbooks/unit-size-page.md",
}

VERTICAL_OVERLAY: dict[str, str] = {
    "legal": "knowledge/verticals/legal.md",
    "medical": "knowledge/verticals/medical-dental.md",
    "dental": "knowledge/verticals/medical-dental.md",
    "medical-dental": "knowledge/verticals/medical-dental.md",
    "financial": "knowledge/verticals/financial.md",
    "home-services": "knowledge/verticals/home-services.md",
    "self-storage": "knowledge/verticals/self-storage.md",
}

FRAMEWORK_REF: dict[str, str] = {
    "PAS": "knowledge/frameworks/pas-and-pastor.md",
    "PASTOR": "knowledge/frameworks/pas-and-pastor.md",
    "AIDA": "knowledge/frameworks/aida-and-4ps.md",
    "4Ps": "knowledge/frameworks/aida-and-4ps.md",
    "SB7": "knowledge/frameworks/storybrand-sb7.md",
    "BAB": "knowledge/frameworks/copyhackers-hero-and-belief.md",
    "Cialdini": "knowledge/frameworks/cialdini-7-principles.md",
}

# Foundations each stage needs, beyond its playbook. Kept tight on purpose - a stage
# handed everything has no priorities.
STAGE_FOUNDATIONS: dict[str, tuple[str, ...]] = {
    "keyword_discovery": (
        "knowledge/foundations/keyword-research-method.md",
        "knowledge/foundations/search-intent-taxonomy.md",
    ),
    "topical_map": (
        "knowledge/foundations/topical-map-protocol.md",
        "knowledge/foundations/cluster-graph-protocol.md",
    ),
    "sme": (
        "knowledge/foundations/experience-signals.md",
        "knowledge/foundations/eeat-framework.md",
    ),
    "research": ("knowledge/foundations/research-input-protocol.md",),
    "outline": (
        "knowledge/foundations/passage-block-protocol.md",
        "knowledge/foundations/meta-and-headings.md",
    ),
    "draft": (
        "knowledge/voice/natural-voice-engineering.md",
        "knowledge/foundations/passage-block-protocol.md",
    ),
    "convert": ("knowledge/frameworks/objection-handling.md",),
    "voice": (
        "knowledge/voice/humanization-layer.md",
        "knowledge/voice/sentence-rhythm.md",
    ),
    "title_meta": (
        "knowledge/foundations/meta-and-headings.md",
        "knowledge/voice/hooks-and-titles.md",
    ),
    "links": ("knowledge/foundations/internal-linking.md",),
    "schema": ("knowledge/foundations/schema-library.md",),
    "gate": ("knowledge/quality-gates/gates.md",),
}

# Per-block ceilings. Exceeding one drops WHOLE trailing chunks (see `doctrine.render`)
# rather than cutting mid-rule, because half a rule is worse than no rule.
MAX_CONSTITUTION_TOKENS = 34_000
MAX_STAGE_ROLE_TOKENS = 6_000
# Raised from 20k after measuring: at 20k the draft and SME packs lost 29% of their
# doctrine. The extra ~8k tokens cost roughly $0.05 per page (one cache write at 1.25x
# plus ~10 reads at 0.1x, Sonnet input), against a page that already costs ~$0.30. Nine
# cents of doctrine is not where this system should economise, and anything still over
# the ceiling is now REPORTED rather than dropped in silence.
MAX_PAGE_PACK_TOKENS = 30_000


@dataclass(frozen=True)
class PromptBlocks:
    """The three cached system blocks, plus the provenance the ledger records."""

    constitution: str
    stage_role: str
    page_pack: str
    chunk_ids: tuple[str, ...] = field(default_factory=tuple)
    tokens: int = 0
    #: Chunks that did NOT fit their block's ceiling. Non-empty means this call saw
    #: less doctrine than the route intended - record it, do not ignore it.
    dropped_chunk_ids: tuple[str, ...] = field(default_factory=tuple)

    @property
    def complete(self) -> bool:
        return not self.dropped_chunk_ids

    def as_system(self) -> list[str]:
        """The blocks in CACHE-PREFIX ORDER: most stable first. Empty blocks are
        dropped so a stage with no pack does not send an empty cache breakpoint."""
        return [b for b in (self.constitution, self.stage_role, self.page_pack) if b]

    def cache_flags(self, *, expected_calls: int = 1) -> list[bool]:
        """Whether each block returned by :meth:`as_system` is worth CACHING.

        Caching is not free: a write costs 1.25x and a read 0.1x, so a block used
        ONCE is 25% more expensive cached than sent plain. Block A spans every stage
        and every page in a batch, so it always pays. Blocks B and C only pay when
        their stage makes 2+ calls - measured, that is outline, draft and gate, while
        convert, voice and title_meta are single-call and lose money if cached.

        Blindly caching everything costs about $0.04 per page. Small, but it is the
        exact opposite of what the caching is for, and avoiding it is one comparison.
        """
        worth_it = expected_calls >= 2
        flags: list[bool] = []
        for i, block in enumerate((self.constitution, self.stage_role, self.page_pack)):
            if block:
                flags.append(True if i == 0 else worth_it)
        return flags


def _pack_refs(
    stage: str, page_type: str, vertical: str | None, framework: str | None
) -> tuple[str, ...]:
    refs: list[str] = []
    playbook = PAGE_PLAYBOOK.get(page_type)
    if playbook:
        refs.append(playbook)
    if vertical:
        overlay = VERTICAL_OVERLAY.get(vertical.strip().lower())
        if overlay:
            refs.append(overlay)
    refs.extend(STAGE_FOUNDATIONS.get(stage, ()))
    if framework:
        ref = FRAMEWORK_REF.get(framework.strip())
        if ref:
            refs.append(ref)
    return tuple(refs)


def assemble(
    stage: str,
    *,
    page_type: str = "service",
    vertical: str | None = None,
    framework: str | None = None,
) -> PromptBlocks:
    """Build the three cached blocks for one stage.

    An unknown stage still gets the constitution and the page pack - the platform
    should degrade to "governed by the laws but without a specialist role" rather than
    to "no doctrine at all", which is what an exception here would cause at the call
    site.
    """
    constitution_chunks = resolve(*CONSTITUTION_REFS)
    role_chunks: tuple[DoctrineChunk, ...] = ()
    agent = STAGE_AGENT.get(stage)
    if agent:
        role_chunks = resolve(agent)
    pack_chunks = resolve(*_pack_refs(stage, page_type, vertical, framework))

    kept_const, dropped_const = fit(constitution_chunks, max_tokens=MAX_CONSTITUTION_TOKENS)
    kept_role, dropped_role = fit(role_chunks, max_tokens=MAX_STAGE_ROLE_TOKENS)
    kept_pack, dropped_pack = fit(pack_chunks, max_tokens=MAX_PAGE_PACK_TOKENS)

    def _text(chunks: tuple[DoctrineChunk, ...]) -> str:
        return "\n\n".join(c.text for c in chunks)

    kept = kept_const + kept_role + kept_pack
    dropped = dropped_const + dropped_role + dropped_pack
    return PromptBlocks(
        constitution=_text(kept_const),
        stage_role=_text(kept_role),
        page_pack=_text(kept_pack),
        chunk_ids=tuple(c.id for c in kept),
        tokens=total_tokens(kept),
        dropped_chunk_ids=tuple(c.id for c in dropped),
    )


def known_stages() -> tuple[str, ...]:
    return tuple(sorted(STAGE_AGENT))
