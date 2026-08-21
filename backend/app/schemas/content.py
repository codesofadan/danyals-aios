"""Content-job request/response models in the frontend shape (``lib/content.ts``).

``ContentJobResponse`` mirrors ``ContentJob`` EXACTLY - the 15 camelCase keys
``{id, client, color, pageType, topic, framework, auto, target, status, cost,
words, schema, images, stage, ago}`` and nothing else. ``id`` is the short PUBLIC
job code (``CJ-####``), never the UUID; ``client``/``color`` are display SNAPSHOTS
so the internal ``client_id`` never leaks.

THE ``schema`` GOTCHA: ``schema`` is a reserved attribute on Pydantic's
``BaseModel`` (the JSON-schema builder), so the Python attribute is named
``schema_type`` and re-aliased to the wire key ``schema`` via
``serialization_alias`` - which the contract-lock test verifies is emitted.

The two server rules the router will reuse live here as pure helpers:
``auto_framework(page_type)`` (service->AIDA, local->BAB, blog->PAS,
gbp_post->4 U's) and ``schema_for(page_type)`` (service->Service,
local->LocalBusiness, blog->Article, gbp_post->"" - a GBP post is never
rendered as its own page, so it carries no JSON-LD @type).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.util.timefmt import relative_ago

# Statuses that count as "in the automated pipeline" (pre-terminal, pre-review-exit)
# for the board KPI. Mirrors ``ContentKpis.tsx`` (queued|drafting|needs_review|
# publishing). ``done``/``failed``/``rejected`` are terminal and excluded.
_IN_PIPELINE: frozenset[str] = frozenset(
    {"queued", "drafting", "needs_review", "publishing"}
)

# Unions verbatim from content.ts (note the spaces / apostrophes in the
# frameworks). These are the SAME values front + back - no display remapping.
PageType = Literal["service", "blog", "local", "gbp_post"]
# The 7 named page-layout TEMPLATES (the audited section sequences). Mirrors the
# canonical keys in ``app.services.page_blueprints.TEMPLATES`` (a unit test asserts
# they stay identical). The sentinel ``"Auto"`` -> the server derives the template
# from the page type (service->service, local->local, blog->blog).
PageTemplate = Literal[
    "service", "location", "service_area", "blog", "faq", "local", "homepage"
]
_PAGE_TEMPLATES: frozenset[str] = frozenset(
    {"service", "location", "service_area", "blog", "faq", "local", "homepage"}
)
PublishTarget = Literal["WordPress", "PDF/Markdown"]
Framework = Literal["AIDA", "PAS", "BAB", "FAB", "4 Ps", "PASTOR", "4 U's"]
JobStatus = Literal[
    "queued", "drafting", "needs_review", "publishing", "done", "failed", "rejected"
]

_PAGE_TYPES: frozenset[str] = frozenset({"service", "blog", "local", "gbp_post"})
_TARGETS: frozenset[str] = frozenset({"WordPress", "PDF/Markdown"})
_FRAMEWORKS: frozenset[str] = frozenset(
    {"AIDA", "PAS", "BAB", "FAB", "4 Ps", "PASTOR", "4 U's"}
)
_STATUSES: frozenset[str] = frozenset(
    {"queued", "drafting", "needs_review", "publishing", "done", "failed", "rejected"}
)

# Server rule: content type -> the framework "Auto" resolves to. gbp_post uses
# "4 U's" (Urgent/Unique/Useful/Ultra-specific) - the one existing framework built
# for short punchy copy, not AIDA/BAB/PAS's long-form persuasion arc.
_AUTO_FRAMEWORK: dict[str, Framework] = {
    "service": "AIDA",
    "local": "BAB",
    "blog": "PAS",
    "gbp_post": "4 U's",
}
# Server rule: content type -> the JSON-LD @type (the schema the page validates
# as). gbp_post maps to "" (no schema) - it is never rendered as its own page, so
# it has nothing to mark up; ``schema_type`` already tolerates an empty string.
_SCHEMA_FOR: dict[str, str] = {
    "service": "Service",
    "local": "LocalBusiness",
    "blog": "Article",
    "gbp_post": "",
}


def auto_framework(page_type: str) -> Framework:
    """The framework "Auto" resolves to for a page type (service->AIDA,
    local->BAB, blog->PAS, gbp_post->4 U's). Falls back to AIDA for an unknown
    type."""
    return _AUTO_FRAMEWORK.get(page_type, "AIDA")


def schema_for(page_type: str) -> str:
    """The JSON-LD @type for a page type (service->Service, local->LocalBusiness,
    blog->Article, gbp_post->""). Falls back to Article for an unknown type."""
    return _SCHEMA_FOR.get(page_type, "Article")


# --------------------------------------------------------------------------- #
# Site-design EXTRACTOR profile models (POST /content/site-design).
#
# OPERATIONAL models (there is NO ``frontend/lib/*.ts`` mirror), so - like
# ``ContentResearchResponse`` / ``PolicyAskResponse`` - they deliberately sit OUTSIDE
# ``test_contract_lock`` (they are simply never registered in its ``_CONTRACT`` list).
# Snake_case, no serialization aliases: the profile round-trips unchanged from the
# response, into a content job's ``source_pack["design_profile"]``, and back out when
# the publish path reads ``layout.section_order`` - one representation, no re-mapping.
# The nested models mirror ``app.services.site_design.SiteDesignProfile.as_dict()``.
# Defined here (before ContentJobCreate) so the create body can carry a profile.
# --------------------------------------------------------------------------- #
class SiteDesignPalette(BaseModel):
    """The site's core colours (CSS hex strings)."""

    primary: str = "#111827"
    secondary: str = "#4b5563"
    background: str = "#ffffff"
    text: str = "#111827"
    accent: str = "#2563eb"


class SiteDesignTypography(BaseModel):
    """The site's type system (CSS font-family stacks + a base size)."""

    heading_font: str = "system-ui, sans-serif"
    body_font: str = "system-ui, sans-serif"
    base_size: str = "16px"


class SiteDesignSection(BaseModel):
    """ONE section of the analyzed page blueprint: its ``kind`` (section-type name),
    the ``heading`` shown, and the ``layout`` variant. The ordered list of these IS
    the deep page blueprint - the exact section-by-section sequence a matching page
    follows. Snake_case, no aliases: it round-trips into ``source_pack`` unchanged."""

    kind: str = "section"
    heading: str = ""
    layout: str = "stacked"


class SiteDesignLayout(BaseModel):
    """The page skeleton: the full ordered ``blueprint`` (every section's kind +
    heading + layout, in exact sequence - the deep structural capture the publish path
    builds to) plus the flat ``section_order`` (kinds only, kept for back-compat), the
    container width, and the hero / CTA presentation styles."""

    container_width: str = "1200px"
    section_order: list[str] = Field(
        default_factory=lambda: ["hero", "intro", "services", "proof", "faq", "cta"]
    )
    blueprint: list[SiteDesignSection] = Field(default_factory=list)
    hero_style: str = "centered"
    cta_style: str = "banner"


class SiteDesignComponents(BaseModel):
    """Reusable component styling cues the new page should echo."""

    button_style: str = "solid rounded"
    card_style: str = "soft shadow"
    spacing_scale: str = "comfortable"


class SiteDesignProfile(BaseModel):
    """The extracted design system a new page is built to MATCH. Every field defaults,
    so a partial payload still validates into a usable profile.

    ``wireframe_html`` is a self-contained, styled HTML snippet (inline ``<style>`` + one
    ``<section>``) that renders a representative hero/homepage section in the EXTRACTED
    colours + fonts + layout, so the operator can SEE how a matching page would look. It
    is emitted on the wire as ``wireframeHtml`` (FastAPI serializes ``by_alias``); it does
    NOT round-trip back into ``source_pack`` (it is a preview artifact, not publish
    grounding), so ``model_dump()`` still keeps the snake_case field for internal use."""

    palette: SiteDesignPalette = Field(default_factory=SiteDesignPalette)
    typography: SiteDesignTypography = Field(default_factory=SiteDesignTypography)
    layout: SiteDesignLayout = Field(default_factory=SiteDesignLayout)
    components: SiteDesignComponents = Field(default_factory=SiteDesignComponents)
    notes: str = ""
    wireframe_html: str = Field(default="", serialization_alias="wireframeHtml")


class ContentJobCreate(BaseModel):
    """POST /content body: queue a new content job.

    ``framework`` accepts the sentinel ``"Auto"`` -> the endpoint resolves it via
    ``auto_framework(pageType)`` and flags ``auto=true``. ``client_id`` is validated
    + snapshotted (name/color) by the endpoint; ``pageType``/``target`` are the same
    values front + back.
    """

    model_config = ConfigDict(populate_by_name=True)

    client_id: str = Field(min_length=1)
    page_type: PageType = Field(alias="pageType")
    topic: str = Field(min_length=1)
    framework: Framework | Literal["Auto"] = "Auto"
    # The page-layout TEMPLATE the generated page is built to (one of the 7 named
    # templates). ``"Auto"`` (the default) -> the server derives it from the page type.
    # When a design_profile is ALSO supplied, the ANALYZED site's blueprint wins over
    # the template (the page mirrors the client's own site); the template is the
    # fallback structure when no site was analyzed.
    template: PageTemplate | Literal["Auto"] = "Auto"
    target: PublishTarget = "WordPress"
    # First-hand grounding the E-E-A-T / fact-grounding QA gate requires (§2/§7).
    # Optional, but a job with NONE of these will hard-fail the publish gate
    # (fact_grounding / eeat_experience floor) because the generator can only emit a
    # ``[NEEDS:]`` marker with nothing real to ground against. Each is a short list of
    # plain-text lines (one proof point / testimonial / stat / service per line); the
    # endpoint seeds them into the job's ``source_pack`` verbatim. Capped so a body
    # can't balloon the pack.
    proof_points: list[str] = Field(default_factory=list, alias="proofPoints", max_length=12)
    testimonials: list[str] = Field(default_factory=list, max_length=12)
    unique_data: list[str] = Field(default_factory=list, alias="uniqueData", max_length=12)
    services: list[str] = Field(default_factory=list, max_length=20)
    # The target site's extracted design profile (from POST /content/site-design). When
    # supplied it is seeded verbatim into the job's ``source_pack["design_profile"]`` so
    # the publish path builds the page structure to MATCH the client's existing site
    # (ordered ``<section class="aios-<name>">`` blocks from ``layout.section_order``).
    # Absent -> the publish path behaves exactly as before (no structural wrap).
    design_profile: SiteDesignProfile | None = Field(default=None, alias="designProfile")


ReviewAction = Literal["approve", "edit", "reject"]


class ContentReviewRequest(BaseModel):
    """POST /content/{code}/review body: the reviewer's decision at the gate.

    ``approve`` -> publishing, ``reject`` -> rejected, ``edit`` -> back to drafting.

    ``note`` is the reviewer's free-text GUIDED-EDIT instruction (e.g. "make the
    intro punchier, add an FAQ, tighten the H2s"). It is only meaningful for the
    ``edit`` action: the endpoint persists it on the job (``edit_instruction``) so
    the worker re-drafts targeting exactly what the reviewer asked instead of
    blind-regenerating. Ignored (harmless) for approve/reject; optional for edit (an
    empty note simply re-runs the pipeline without steering).
    """

    model_config = ConfigDict(populate_by_name=True)

    action: ReviewAction
    note: str | None = Field(default=None, alias="editInstruction", max_length=4000)
    # Scheduled publishing (spec section 46): meaningful only for `approve`. When
    # set to a FUTURE time, the router still moves the job to `publishing` right
    # now (a human still approves before anything is queued - the existing gate is
    # unchanged) but defers the actual Celery enqueue to this time instead of
    # firing immediately. A past/omitted value publishes immediately (today's
    # behaviour, unchanged).
    publish_at: datetime | None = Field(default=None, alias="publishAt")


class ContentJobUpdate(BaseModel):
    """PATCH /content/jobs/{code} body: a LEAD's limited edit of a job's inputs.

    Deliberately narrow: only the ``topic`` (the content brief line) and the
    server-only ``brief`` (extra instructions) are editable here. Status is NEVER
    touched on this path - the lifecycle moves only via /review and the worker, and
    the DB guard would reject a non-lead edit anyway. Every field is optional; an
    empty patch is a no-op.
    """

    model_config = ConfigDict(populate_by_name=True)

    topic: str | None = Field(default=None, min_length=1)
    brief: str | None = None


class ContentStatsResponse(BaseModel):
    """Content-board KPI headline (frontend ``ContentKpis`` shape).

    ``inPipeline`` = jobs still moving through the automated pipeline;
    ``awaitingReview`` = jobs parked at the human review gate; ``publishedThisMonth``
    = jobs completed this calendar month; ``avgCost`` = mean per-page cost over the
    priced (cost > 0) jobs, in dollars.
    """

    in_pipeline: int = Field(serialization_alias="inPipeline")
    awaiting_review: int = Field(serialization_alias="awaitingReview")
    published_this_month: int = Field(serialization_alias="publishedThisMonth")
    avg_cost: float = Field(serialization_alias="avgCost")


def compute_content_stats(rows: list[dict[str, Any]]) -> ContentStatsResponse:
    """Derive the content KPIs from the job rows (pure, unit-testable).

    inPipeline = jobs in {queued, drafting, needs_review, publishing}; awaitingReview
    = jobs in needs_review; publishedThisMonth = ``done`` jobs created this calendar
    month; avgCost = mean cost of jobs with cost > 0 (0 when none are priced).
    """
    month_prefix = datetime.now(UTC).strftime("%Y-%m")
    in_pipeline = 0
    awaiting = 0
    published = 0
    costs: list[float] = []
    for r in rows:
        status = str(r.get("status") or "")
        if status in _IN_PIPELINE:
            in_pipeline += 1
        if status == "needs_review":
            awaiting += 1
        if status == "done" and str(r.get("created_at", ""))[:7] == month_prefix:
            published += 1
        cost = float(r.get("cost", 0) or 0)
        if cost > 0:
            costs.append(cost)
    avg_cost = round(sum(costs) / len(costs), 2) if costs else 0.0
    return ContentStatsResponse(
        in_pipeline=in_pipeline,
        awaiting_review=awaiting,
        published_this_month=published,
        avg_cost=avg_cost,
    )


class ContentJobResponse(BaseModel):
    """One content job in the frontend ``ContentJob`` shape - and ONLY those 15
    keys. ``id`` is the public ``CJ-####`` code; ``client``/``color`` are the
    snapshotted display fields. No internal column (UUID id, client_id, assignee_id,
    created_by, the rich pipeline columns, timestamps) is ever exposed.

    ``schema_type`` is emitted as the wire key ``schema`` (the attribute is renamed
    to dodge Pydantic's reserved ``BaseModel.schema``).
    """

    id: str
    client: str
    color: str
    page_type: PageType = Field(serialization_alias="pageType")
    topic: str
    framework: Framework
    auto: bool
    target: PublishTarget
    status: JobStatus
    cost: float
    words: int
    schema_type: str = Field(serialization_alias="schema")
    images: int
    stage: str
    ago: str

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> ContentJobResponse:
        page_type = row.get("page_type")
        framework = row.get("framework")
        target = row.get("target")
        status = row.get("status")
        return cls(
            id=str(row["code"]),
            client=row.get("client_name", ""),
            color=row.get("color", ""),
            page_type=page_type if page_type in _PAGE_TYPES else "service",
            topic=row.get("topic", ""),
            framework=framework if framework in _FRAMEWORKS else "AIDA",
            auto=bool(row.get("auto", False)),
            target=target if target in _TARGETS else "WordPress",
            status=status if status in _STATUSES else "queued",
            cost=float(row.get("cost", 0) or 0),
            words=int(row.get("words", 0) or 0),
            schema_type=row.get("schema_type", ""),
            images=int(row.get("images", 0) or 0),
            stage=row.get("stage", ""),
            ago=relative_ago(row.get("created_at"), empty="just now"),
        )


def to_response(row: dict[str, Any]) -> ContentJobResponse:
    """Map a ``content_jobs`` row to the frontend ``ContentJob`` shape."""
    return ContentJobResponse.from_row(row)


# --------------------------------------------------------------------------- #
# Research-first bulk content (POST /content/research + /content/research/generate).
#
# OPERATIONAL models: there is NO ``frontend/lib/*.ts`` mirror for the page-set
# recommender, so these deliberately sit OUTSIDE ``test_contract_lock`` (exactly
# like ``PolicyAskResponse`` / ``OverlayResponse``). ``ContentRecommendation`` is
# symmetric - it is both a RESPONSE item (from /content/research) and a REQUEST
# item (the selected checkboxes posted back to /content/research/generate) - so it
# accepts camelCase OR snake_case on the wire (``populate_by_name``) and always
# emits camelCase (``serialization_alias``), letting an item round-trip unchanged.
# --------------------------------------------------------------------------- #
# The six content types the recommender researches. ``service_location`` returns
# city x service landing pages (each item carries ``city`` + ``service``).
ContentType = Literal["service", "location", "service_location", "service_area", "blog", "faq"]
Difficulty = Literal["easy", "medium", "hard"]

_CONTENT_TYPES: frozenset[str] = frozenset(
    {"service", "location", "service_location", "service_area", "blog", "faq"}
)
_DIFFICULTIES: frozenset[str] = frozenset({"easy", "medium", "hard"})

# A research content type -> the ``ContentJob`` page type the generator understands
# (the generator only knows service/blog/local/gbp_post). All location-flavoured
# types map to ``local`` (LocalBusiness schema); an FAQ page drafts as an Article.
_RESEARCH_PAGE_TYPE: dict[str, PageType] = {
    "service": "service",
    "location": "local",
    "service_location": "local",
    "service_area": "local",
    "blog": "blog",
    "faq": "blog",
}


def job_page_type_for(content_type: str) -> PageType:
    """The ``ContentJob`` page type a research content type fans out into
    (service->service, blog->blog, every location flavour->local, faq->blog).
    Falls back to ``service`` for an unknown type."""
    return _RESEARCH_PAGE_TYPE.get(content_type, "service")


class ContentRecommendation(BaseModel):
    """One recommended page (a "checkbox") the recommender proposes and the operator
    selects to generate. ``city``/``service`` are meaningful only for the
    ``service_location`` type (the city x service landing pages); empty otherwise."""

    model_config = ConfigDict(populate_by_name=True)

    title: str = Field(min_length=1)
    page_type: str = Field(default="service", alias="pageType", serialization_alias="pageType")
    primary_keyword: str = Field(
        default="", alias="primaryKeyword", serialization_alias="primaryKeyword"
    )
    secondary_keywords: list[str] = Field(
        default_factory=list, alias="secondaryKeywords", serialization_alias="secondaryKeywords"
    )
    est_volume: int = Field(default=0, alias="estVolume", serialization_alias="estVolume")
    difficulty: Difficulty = "medium"
    rationale: str = ""
    city: str = ""
    service: str = ""


class ContentResearchRequest(BaseModel):
    """POST /content/research body: research a site + content type for a page set."""

    model_config = ConfigDict(populate_by_name=True)

    site: str = Field(min_length=1, max_length=2048)
    content_type: ContentType = Field(alias="contentType")
    # Optional cap; ``None`` -> the ``content_research_count`` setting default.
    count: int | None = Field(default=None, ge=1, le=50)


class ContentResearchResponse(BaseModel):
    """The recommended page set (or a clean degraded shell). ``reason`` is populated
    only when ``status='degraded'`` (keyless / dial-blocked / research failed)."""

    status: Literal["ok", "degraded"]
    items: list[ContentRecommendation]
    reason: str = ""


class ContentBulkGenerateRequest(BaseModel):
    """POST /content/research/generate body: fan the SELECTED recommendations into
    content jobs. ``clientId`` + ``framework``/``target`` + the first-hand grounding
    are shared across every item (each mirrors ``ContentJobCreate``); each item
    supplies its own ``title`` (-> the job topic) and ``pageType``. The per-site
    WordPress publish target is resolved server-side from the client's site + vault
    (exactly like ``POST /content/jobs``), so no wpConnection field is needed here."""

    model_config = ConfigDict(populate_by_name=True)

    items: list[ContentRecommendation] = Field(min_length=1, max_length=100)
    client_id: str = Field(min_length=1, alias="clientId")
    framework: Framework | Literal["Auto"] = "Auto"
    # The page-layout template shared across every fanned-out job (like framework);
    # ``"Auto"`` derives it per-item from each item's page type. The analyzed
    # design_profile (when supplied) still wins over the template per job.
    template: PageTemplate | Literal["Auto"] = "Auto"
    target: PublishTarget = "WordPress"
    proof_points: list[str] = Field(default_factory=list, alias="proofPoints", max_length=12)
    testimonials: list[str] = Field(default_factory=list, max_length=12)
    unique_data: list[str] = Field(default_factory=list, alias="uniqueData", max_length=12)
    services: list[str] = Field(default_factory=list, max_length=20)
    # Shared across every fanned-out job (like the grounding lists above): the target
    # site's design profile is seeded into each job's ``source_pack["design_profile"]``.
    design_profile: SiteDesignProfile | None = Field(default=None, alias="designProfile")


class ContentBulkGenerateResponse(BaseModel):
    """The fan-out result: the public ``CJ-####`` codes of the queued jobs."""

    jobs: list[str]


class SiteDesignRequest(BaseModel):
    """POST /content/site-design body: analyze a site's existing design.

    ``site`` is the target site URL (SSRF-guarded server-side); ``maxPages`` optionally
    caps how many same-domain pages (homepage + internal) are fetched, defaulting to
    the ``content_design_max_pages`` setting when omitted."""

    model_config = ConfigDict(populate_by_name=True)

    site: str = Field(min_length=1, max_length=2048)
    max_pages: int | None = Field(default=None, alias="maxPages", ge=1, le=10)


class SiteDesignResponse(BaseModel):
    """The extracted design profile (or a clean degraded shell). ``reason`` is populated
    only when ``status='degraded'`` (keyless / dial-blocked / analysis failed); a
    degraded result carries ``profile=None``."""

    status: Literal["ok", "degraded"]
    profile: SiteDesignProfile | None = None
    reason: str = ""
