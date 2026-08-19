"""P7A-7/8: the CONTENT EXECUTION ENGINE - the pipeline worker + the QA-gated
publish path, composing the already-merged content services.

The worker drives ONE content job through the canonical, named pipeline

    research -> cluster -> serp_format -> fan_out -> winnability -> teardown ->
    outline -> draft -> titles_meta -> schema -> images -> assemble -> qa -> review

by composing content_research (the SERP-grounded :class:`ResearchBrief`) ->
content_generator (the ranking-grade, grounded draft) -> content_schema (the
JSON-LD graph + match-visible validation) -> content_qa (the 14-dimension score +
the hard publish gate). Each internal ``stage`` maps to a frontend PIPELINE label
for display. The job advances ``queued -> drafting -> needs_review`` and STOPS at
the human review gate - the worker NEVER auto-publishes.

Design mirrors ``workers/tasks/audit.py`` + ``workers/tasks/context.py``:

* **Pure core, injected seams.** :func:`execute_content_job` is a pure function of
  an injected ``ContentStore`` (the privileged DB seam), a ``ContentProviders``
  bundle (or ``None`` = degraded), and a ``CostGate``. So it is unit-tested with a
  fake store + all-fake providers - NO Celery, NO DB, NO network.
* **Privileged writes (the guard's worker path).** All writes go through
  ``privileged_connection`` (role ``service_role``, ``auth.uid()`` IS NULL), which
  the ``content_jobs_guard_update`` trigger recognises as the WORKER: it allows
  ``queued->drafting``, ``drafting->needs_review``, ``publishing->done``, any
  ``->failed``, and same-status streaming (cost/words/stage/draft into a job
  without a status change).
* **R5 cost pre-check at entry.** Before any spend, the worker estimates the FULL
  job cost (research fan-out + generation) and evaluates it against the client
  budget cap (and the global spend halt); a breach DEFERS the job (held, retried later) rather
  than half-spending then blocking mid-pipeline.
* **Never stuck, never re-raise, idempotent.** A redelivered terminal job is a
  no-op (``task_acks_late`` would otherwise redeliver + double-spend). No path
  leaves a job in a half state: any unexpected error fails it (``->failed``); a
  cost-gate block or absent keys DEGRADES (holds at ``drafting`` with an honest $0
  marker) and catches up when keys/budget return. The core NEVER raises.

Publish (P7A-8) is the same discipline: :func:`publish_content_job` re-checks the
QA hard gate (``qa_score.passed``) and BLOCKS a sub-threshold draft (raising the
typed :class:`PublishBlocked` - never publishing it); a passing job goes to
WordPress (per-site app-password from the vault, idempotent via ``wp_post_id``) or
renders PDF/Markdown to the traversal-safe artifact store, then ``publishing ->
done``. No WP credential degrades to artifact-only, never a crash.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from html import escape as html_escape
from typing import Any, Protocol

from psycopg import sql
from psycopg.types.json import Jsonb

from app.config import Settings, get_settings
from app.db.database import privileged_connection
from app.logging_setup import get_logger
from app.schemas.content import schema_for
from app.services import pricing
from app.services.content_artifacts import (
    ContentArtifactStore,
    content_store_from_settings,
)
from app.services.content_generator import (
    MAX_IMAGES,
    NAP,
    GeneratedContent,
    GenerationContext,
    GeneratorTuning,
    LocalProfile,
    SourcePack,
    generate,
)
from app.services.content_guard import apply_edit_instruction, guard_generated, guided_rewrite
from app.services.content_layout import pick_layout
from app.services.content_qa import Judge, QaScore, rewrite_guidance, score
from app.services.content_research import (
    ContentSpendBlocked,
    GatedResearcher,
    PageFetcher,
    ResearchBrief,
    SsrfSafePageFetcher,
    build_research_brief,
)
from app.services.content_schema import (
    Author,
    Business,
    Page,
    ValidationResult,
    VisibleContent,
    build_json_ld,
    validate_json_ld,
)
from app.services.cost_gate import CostGate, GateContext
from app.services.cost_store import PostgresCostStore
from app.services.deliverables import emit_deliverable
from app.services.elementor import elementor_json
from app.services.notifications import email_client_sync, notify_leads_sync
from app.services.page_blueprints import SectionSpec, resolve_blueprint
from app.services.wp_connections import ResolvedWpConnection, resolve_connection
from integrations.content_providers import ContentProviders, content_providers_from_settings
from integrations.images import FakeImageGenerator, GeneratedImage, ImageGenerator
from integrations.llm import LLMResult, Summarizer
from integrations.wordpress import (
    PostDraft,
    PublishResult,
    WordPressPublisher,
)
from integrations.wordpress_publisher import (
    PluginPublisher,
    WordPressPluginError,
    resolve_plugin_target,
)

logger = get_logger("workers.content")

# The money-dial features these calls gate/log against. Generation + images ride
# the "content" dial (Anthropic); research rides "content_research" inside the
# GatedResearcher. Both bill the tenant client so the per-client cap applies.
_CONTENT_FEATURE = "content"
_LLM_PROVIDER = "Anthropic"
_IMAGE_PROVIDER = "images"
_JOB_TYPE = "content"
_ERROR_MAX = 500  # cap the stored error string; server-side only
# Cap the content guard's de-AI writer rewrites per draft (each rides the content
# dial + pricing.py, so bound them). The unconditional dash-strip still runs on
# every block regardless, so the draft is em/en-dash-free even at the cap.
_GUARD_MAX_REWRITES = 6

# jsonb columns on content_jobs (values are wrapped for their jsonb column).
_JSONB_COLS: frozenset[str] = frozenset(
    {
        "source_pack", "keyword_map", "outline", "entity_coverage",
        "qa_score", "json_ld", "internal_links",
    }
)

# The canonical pipeline (the ONE named stage list). Each key maps to the frontend
# PIPELINE display label; the research sub-stages all present as "Research".
PIPELINE: tuple[str, ...] = (
    "research", "cluster", "serp_format", "fan_out", "winnability", "teardown",
    "outline", "draft", "titles_meta", "schema", "images", "assemble", "qa", "review",
)
_STAGE_LABEL: dict[str, str] = {
    "research": "Research",
    "cluster": "Research",
    "serp_format": "Research",
    "fan_out": "Research",
    "winnability": "Research",
    "teardown": "Research",
    "outline": "Outline",
    "draft": "Draft",
    "titles_meta": "Titles & meta",
    "schema": "Schema",
    "images": "AI images",
    "assemble": "Assemble",
    "qa": "Review",
    "review": "Review",
}

# The worker owns a job ONLY while it is queued or drafting; every other status is
# terminal-for-the-worker (the leads / the publish path / a prior run own it), so a
# redelivery there is an idempotent no-op.
_WORKER_OWNED: frozenset[str] = frozenset({"queued", "drafting"})


# --------------------------------------------------------------------------- #
# Seams
# --------------------------------------------------------------------------- #
class ContentStore(Protocol):
    """The DB seam the worker needs (backed by the privileged connection)."""

    def load(self, code: str) -> dict[str, Any] | None: ...
    def update(self, code: str, fields: dict[str, Any]) -> dict[str, Any] | None: ...


class QaScorer(Protocol):
    """The QA scorer seam - defaults to :func:`app.services.content_qa.score`, injected
    so a unit test can script a deterministic ``fails-twice-then-passes`` (or
    ``always-fails``) sequence and drive the drafting-time improvement loop by exact
    pass count. Mirrors ``score``'s signature verbatim."""

    def __call__(
        self,
        content: GeneratedContent,
        brief: ResearchBrief,
        schema_result: ValidationResult | None,
        source_pack: SourcePack,
        *,
        judge: Judge | None = None,
    ) -> QaScore: ...


class PrivilegedContentStore:
    """Concrete ``ContentStore`` over ``privileged_connection`` (service_role).

    Stateless: each call opens its own privileged connection. Keyed by the public
    ``code`` (CJ-####), never the UUID. Column names are static ``sql.Identifier``s;
    every value is a bound param, and jsonb columns are wrapped.
    """

    def load(self, code: str) -> dict[str, Any] | None:
        with privileged_connection() as cur:
            cur.execute("select * from public.content_jobs where code = %s limit 1", (code,))
            return cur.fetchone()

    def update(self, code: str, fields: dict[str, Any]) -> dict[str, Any] | None:
        if not fields:
            return self.load(code)
        assignments = sql.SQL(", ").join(
            sql.SQL("{} = %s").format(sql.Identifier(col)) for col in fields
        )
        stmt = sql.SQL(
            "update public.content_jobs set {sets} where code = %s returning *"
        ).format(sets=assignments)
        params = [_bind(col, value) for col, value in fields.items()]
        with privileged_connection() as cur:
            cur.execute(stmt, [*params, code])
            return cur.fetchone()


def _bind(col: str, value: Any) -> Any:
    """Wrap a jsonb-column value (or any dict/list) for psycopg; pass scalars."""
    if col in _JSONB_COLS or isinstance(value, (dict, list)):
        return Jsonb(value)
    return value


class MeteredCostGate(CostGate):
    """A ``CostGate`` that also SUMS the real (committed) spend of a run.

    Cached hits + blocked/skip outcomes never call ``commit``, so ``spent`` is
    exactly the paid total - which the worker streams into the job's ``cost``
    column (display) while the store still logs each call to the Part-2 cost_log.
    """

    def __init__(self, store: Any, cache: Any) -> None:
        super().__init__(store, cache)
        self.spent: float = 0.0

    def commit(self, ctx: GateContext, cost: float, *, cache_value: Any | None = None) -> None:
        self.spent += float(cost)
        super().commit(ctx, cost, cache_value=cache_value)


class _NullCostCache:
    """A no-op ``CostCache`` (prod injects a Redis-backed (kw,geo,date) cache)."""

    def get(self, key: str) -> Any | None:
        return None

    def set(self, key: str, value: Any) -> None:
        return None


class _ContentGatedWriter:
    """A ``Summarizer`` that meters every draft call through the cost gate.

    Satisfies the ``Summarizer`` Protocol so the pure generator can never reach the
    raw writer. A gate block raises :class:`ContentSpendBlocked`, which the worker
    catches to DEGRADE (hold at ``drafting``) rather than crash. Bills the "content"
    dial (Anthropic) per call.
    """

    def __init__(
        self,
        inner: Summarizer,
        gate: CostGate,
        *,
        settings: Settings,
        client_id: str | None,
        job_id: str = "",
    ) -> None:
        self._inner = inner
        self._gate = gate
        self._settings = settings
        self._client_id = client_id
        self._job_id = job_id
        self.calls = 0

    def _ctx(self) -> GateContext:
        return GateContext(
            feature_key=_CONTENT_FEATURE,
            client_id=self._client_id,
            provider=_LLM_PROVIDER,
            estimated_cost=self._settings.content_generate_cost_estimate,
            job_id=self._job_id,
            job_type=_JOB_TYPE,
            cache_key=None,
        )

    def summarize(self, prompt: str, *, model: str, max_tokens: int) -> LLMResult:
        self.calls += 1
        ctx = self._ctx()
        decision = self._gate.evaluate(ctx)
        if not decision.allowed:
            raise ContentSpendBlocked(decision.outcome)
        result = self._inner.summarize(prompt, model=model, max_tokens=max_tokens)
        # Commit the ACTUAL draft spend from the call's real token usage x the
        # model's unit price (pricing.py), not the flat per-call estimate.
        actual = pricing.anthropic_cost(
            self._settings,
            model=model,
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
        )
        self._gate.commit(ctx, actual)
        return result


# --------------------------------------------------------------------------- #
# Outcomes
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class ContentJobOutcome:
    """The verdict of one :func:`execute_content_job` run (JSON-serializable)."""

    code: str
    status: str
    state: str  # advanced | degraded | deferred | failed | noop
    stage: str = ""
    cost: float = 0.0
    passed: bool | None = None
    reason: str = ""
    qa_loops: int = 0  # drafting-time QA improvement rewrite passes actually run

    def as_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "status": self.status,
            "state": self.state,
            "stage": self.stage,
            "cost": self.cost,
            "passed": self.passed,
            "reason": self.reason,
            "qa_loops": self.qa_loops,
        }


@dataclass(frozen=True)
class PublishOutcome:
    """The verdict of one :func:`publish_content_job` run (JSON-serializable)."""

    code: str
    status: str
    state: str  # published | degraded | failed | noop
    reason: str = ""
    wp_post_id: int | None = None
    url: str = ""
    pdf_key: str | None = None
    md_key: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "status": self.status,
            "state": self.state,
            "reason": self.reason,
            "wp_post_id": self.wp_post_id,
            "url": self.url,
            "pdf_key": self.pdf_key,
            "md_key": self.md_key,
        }


class PublishBlocked(RuntimeError):  # noqa: N818 - a typed control signal the approve router surfaces to the lead
    """Raised when a draft fails the QA hard gate at publish time.

    Carries the job ``code`` + the critical ``blocked_by`` dimensions so the
    approve endpoint can tell the reviewer exactly why it cannot go live. The draft
    is NEVER published while this is raised.
    """

    def __init__(self, code: str, blocked_by: list[str] | None = None) -> None:
        super().__init__(f"content job {code} failed the QA hard gate; publish blocked: {blocked_by}")
        self.code = code
        self.blocked_by: list[str] = list(blocked_by or [])


# WordPress publish target (site + a ready publisher); resolved per-site from the
# vault so the pure publish core never touches the vault directly.
@dataclass(frozen=True)
class WpTarget:
    site_url: str
    publisher: WordPressPublisher


# --------------------------------------------------------------------------- #
# Small helpers
# --------------------------------------------------------------------------- #
def _utcnow_date() -> str:
    return datetime.now(UTC).date().isoformat()


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-") or "post"


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _str_list(value: Any) -> list[str]:
    return [str(v) for v in value] if isinstance(value, list) else []


def _nap_from(raw: Any) -> NAP | None:
    d = _as_dict(raw)
    if not d:
        return None
    return NAP(name=str(d.get("name", "")), address=str(d.get("address", "")), phone=str(d.get("phone", "")))


def _loc_from(raw: Any) -> LocalProfile:
    d = _as_dict(raw)
    return LocalProfile(city=str(d.get("city", "")), proof=_str_list(d.get("proof")), nap=_nap_from(d.get("nap")))


def _source_pack_from_row(row: dict[str, Any]) -> SourcePack:
    """Assemble the generator's per-client SourcePack from the job's ``source_pack``
    jsonb (the router seeds client facts there) + the display ``client_name``.

    A missing pack degrades to just the client name - the generator then emits
    ``[NEEDS:]`` placeholders (never hallucinations), which the QA gate flags for
    the human reviewer.
    """
    raw = _as_dict(row.get("source_pack"))
    facts_raw = _as_dict(raw.get("facts"))
    urls_raw = _as_dict(raw.get("internal_urls"))
    return SourcePack(
        client_name=str(raw.get("client_name") or row.get("client_name") or "our team"),
        facts={str(k): str(v) for k, v in facts_raw.items()},
        services=_str_list(raw.get("services")),
        proof_points=_str_list(raw.get("proof_points")),
        unique_data=_str_list(raw.get("unique_data")),
        testimonials=_str_list(raw.get("testimonials")),
        internal_urls={str(k): str(v) for k, v in urls_raw.items()},
        nap=_nap_from(raw.get("nap")),
        locations=[_loc_from(loc) for loc in (raw.get("locations") or []) if isinstance(loc, dict)],
    )


def _geo_for(row: dict[str, Any], source_pack: SourcePack) -> str | None:
    if source_pack.locations and source_pack.locations[0].city:
        return source_pack.locations[0].city
    raw = _as_dict(row.get("source_pack"))
    geo = raw.get("geo")
    return str(geo) if geo else None


def _site_url_of(row: dict[str, Any]) -> str:
    raw = _as_dict(row.get("source_pack"))
    return str(raw.get("wp_site_url") or raw.get("site_url") or raw.get("url") or "").strip()


def _estimate_full_cost(providers: ContentProviders, settings: Settings) -> float:
    """The coarse R5 upfront estimate: research fan-out + generation (provisional)."""
    research = providers.research_cost_estimate * settings.content_precheck_research_calls
    generation = providers.generate_cost_estimate * settings.content_precheck_writer_calls
    return round(research + generation, 4)


def _tuning(settings: Settings) -> GeneratorTuning:
    # Doctrine defaults, except images: when content_images_enabled is off (the default),
    # max_images=0 disables image planning + generation entirely (no photos in the page,
    # no image spend). Flip content_images_enabled on to restore the hero + section images.
    max_images = MAX_IMAGES if settings.content_images_enabled else 0
    return GeneratorTuning(max_images=max_images)


# --- rich-column serializers (plain JSON-safe dicts for the jsonb columns) ---
def _keyword_map(brief: ResearchBrief) -> dict[str, Any]:
    return {
        "primary": brief.terms.primary,
        "secondary": brief.terms.secondary,
        "semantic_entities": brief.terms.semantic_entities,
        "questions": brief.terms.questions,
        "intent": brief.intent,
        "intent_confidence": brief.intent_confidence,
        "content_format": {
            "recommended": brief.content_format.recommended,
            "confidence": brief.content_format.confidence,
        },
        "fanout": brief.fanout,
        "cluster": {"pillar": brief.cluster.pillar, "supporting": brief.cluster.supporting},
        "winnability": {
            "client_da": brief.winnability.client_da,
            "neutral_da_assumed": brief.winnability.neutral_da_assumed,
            "targets": [
                {
                    "keyword": t.keyword,
                    "volume": t.volume,
                    "difficulty": t.difficulty,
                    "winnable": t.winnable,
                }
                for t in brief.winnability.targets
            ],
        },
        "low_confidence": brief.low_confidence,
        "degraded": brief.degraded,
        "notes": brief.notes,
    }


def _outline(content: GeneratedContent, brief: ResearchBrief) -> dict[str, Any]:
    angle = content.differentiation_angle
    return {
        "framework": content.framework,
        "headings": [{"level": h.level, "text": h.text} for h in content.headings],
        "section_roles": content.section_roles,
        "heading_blueprint": brief.teardown.heading_blueprint,
        "answer_block": content.answer_block,
        # The rendered META tags (title + description) so the Review preview can show
        # the exact <title>/<meta description> alongside the SERP snippet; they are
        # not first-class ContentJob columns, so the outline jsonb carries them.
        "meta": {"title": content.title, "description": content.meta_description},
        "differentiation_angle": {
            "kind": angle.kind,
            "statement": angle.statement,
            "grounded": angle.grounded,
        },
        "needs": content.needs,
    }


def _entity_coverage(content: GeneratedContent, brief: ResearchBrief) -> dict[str, Any]:
    return {
        "table_stakes": brief.teardown.table_stakes_entities,
        "differentiators": brief.teardown.differentiator_entities,
        "covered": content.entities_covered,
        "missing": content.entities_missing,
        "primary_density": content.primary_density,
        "local_uniqueness": content.local_uniqueness,
    }


def _internal_links(content: GeneratedContent) -> dict[str, Any]:
    return {
        "links": [
            {"anchor": link.anchor, "url": link.url, "keyword": link.keyword}
            for link in content.internal_links
        ]
    }


def _qa_dict(qa: QaScore) -> dict[str, Any]:
    return {
        "dimensions": qa.dimensions,
        "weighted_total": qa.weighted_total,
        "passed": qa.passed,
        "blocked_by": qa.blocked_by,
        "provisional": qa.provisional,
        "notes": qa.notes,
    }


# --------------------------------------------------------------------------- #
# Schema inputs (assemble Business + Page from the job + brief + draft)
# --------------------------------------------------------------------------- #
def _schema_inputs(
    row: dict[str, Any], brief: ResearchBrief, source_pack: SourcePack, content: GeneratedContent
) -> tuple[str, Business, Page, VisibleContent]:
    """Build the (page_type, Business, Page, VisibleContent) the schema chunk needs.

    Only claims that are actually VISIBLE in the draft are asserted (name via the
    H1 title, serviceType via the primary keyword, areaServed via the geo, phone
    only for a local page that carries a NAP), so match-visible validation stays
    clean rather than tripping on invented markup.
    """
    page_type = str(row.get("page_type") or "blog")
    client = source_pack.client_name or str(row.get("client_name") or "our team")
    site_url = _site_url_of(row)
    org_url = site_url or f"https://{_slug(client)}.example"
    page_url = f"{site_url.rstrip('/')}/{_slug(content.title)}" if site_url else f"/{_slug(content.title)}"
    nap = source_pack.nap or next((loc.nap for loc in source_pack.locations if loc.nap), None)
    geo = _geo_for(row, source_pack) or ""

    business = Business(
        name=client,
        url=org_url,
        telephone=nap.phone if nap else "",
        business_type=str(row.get("schema_type") or "LocalBusiness") if page_type == "local" else "LocalBusiness",
        has_public_address=False,  # NAP is a flat string, not structured parts -> market areaServed
        area_served=(geo,) if geo else (),
    )
    today = _utcnow_date()
    if page_type == "service":
        page = Page(
            url=page_url,
            title=content.title,
            description=content.meta_description,
            service_type=brief.terms.primary,
            area_served=(geo,) if geo else (),
        )
    elif page_type == "local":
        page = Page(
            url=page_url,
            title=content.title,
            description=content.meta_description,
            area_served=(geo,) if geo else (),
        )
    else:  # blog / unknown -> Article
        page = Page(
            url=page_url,
            title=content.title,
            description=content.meta_description,
            author=Author(name=client, is_organization=True),
            date_published=today,
            article_type="BlogPosting",
        )
    visible = VisibleContent(text=content.draft_md, has_reviews=False)
    return page_type, business, page, visible


# --------------------------------------------------------------------------- #
# Image generation (bounded, gated, never fatal)
# --------------------------------------------------------------------------- #
def _generate_images(
    images: ImageGenerator,
    content: GeneratedContent,
    gate: CostGate,
    settings: Settings,
    *,
    client_id: str | None,
    code: str,
) -> tuple[int, list[tuple[str, GeneratedImage]]]:
    """Generate the planned hero/section images, gated on the content dial. A dial
    block stops image generation (not fatal); a provider error skips that image.
    Each generated image is committed at its RUNTIME cost = 1 x the per-image unit
    price (pricing.py); the pre-check estimate is the same per-image price.

    Returns ``(count, resolved)`` where ``count`` is the number of images billed (the
    pre-existing integer behaviour, unchanged) and ``resolved`` is the ``(slot, image)``
    list to inject into the draft. Only REAL hosted images make ``resolved``: a keyless
    ``FakeImageGenerator`` result or an empty/missing url is billed-as-before but yields
    NO injection (so the draft never gets a broken ``![]()``)."""
    per_image = settings.price_image_per_image
    is_fake = isinstance(images, FakeImageGenerator)
    count = 0
    resolved: list[tuple[str, GeneratedImage]] = []
    for item in content.images_plan:
        ctx = GateContext(
            feature_key=_CONTENT_FEATURE,
            client_id=client_id,
            provider=_IMAGE_PROVIDER,
            estimated_cost=per_image,  # one image's per-image price (upfront pre-check)
            job_id=code,
            job_type=_JOB_TYPE,
            cache_key=None,
        )
        decision = gate.evaluate(ctx)
        if not decision.allowed:
            break
        try:
            image = images.generate(item.prompt, item.alt)
            # ACTUAL cost = one image generated x the per-image unit price.
            gate.commit(ctx, pricing.image_cost(settings, images=1))
            count += 1
            # Inject only a REAL hosted image; a fake/degraded result or an empty url
            # injects nothing (count is unaffected - the existing behaviour is preserved).
            if not is_fake and image.url:
                resolved.append((item.slot, image))
        except Exception:  # one bad image never fails the job
            logger.warning("content_image_failed", code=code)
    return count, resolved


def _image_md(image: GeneratedImage) -> str:
    """The Markdown image tag every downstream consumer already understands (the draft
    endpoint, ``md_to_html``, and ``build_elementor_data``)."""
    return f"![{image.alt}]({image.url})"


def _inject_images(draft_md: str, resolved: list[tuple[str, GeneratedImage]]) -> str:
    """Inject each resolved image as its OWN ``![alt](url)`` block into the draft so it
    reaches the stored draft, the Elementor tree, AND the WordPress body.

    Placement is deterministic and CONTEXTUAL - one image per section, in document order,
    each sitting at the TOP of the section its content belongs to (never all bunched at
    the top of the page):

    * the ``hero`` image lands right after the ``# `` H1 (or at the very top when there
      is none);
    * the ``section:<role>`` images are distributed one after each successive ``## `` H2,
      IN ORDER (image 1 -> first H2, image 2 -> second H2, ...), so each image frames the
      section it introduces. This does NOT depend on the image's alt matching the heading
      text, so a rephrased heading never collapses the images into one spot. Any image
      beyond the H2 count folds under the last H2 (or the H1 when the draft has no H2s).

    Only real images are passed in, so no broken markdown is written."""
    if not resolved:
        return draft_md
    lines = draft_md.splitlines()
    h1_idx: int | None = None
    h2_idxs: list[int] = []
    for i, line in enumerate(lines):
        s = line.strip()
        if h1_idx is None and s.startswith("# ") and not s.startswith("## "):
            h1_idx = i
        elif s.startswith("## ") and not s.startswith("### "):
            h2_idxs.append(i)

    after: dict[int, list[str]] = {}  # line index -> image markdown to insert AFTER it (-1 = top)

    def _queue(idx: int, md: str) -> None:
        after.setdefault(idx, []).append(md)

    top = h1_idx if h1_idx is not None else -1
    hero_images = [img for slot, img in resolved if slot == "hero"]
    section_images = [img for slot, img in resolved if slot != "hero"]
    for image in hero_images:
        _queue(top, _image_md(image))
    for k, image in enumerate(section_images):
        idx = (h2_idxs[k] if k < len(h2_idxs) else h2_idxs[-1]) if h2_idxs else top
        _queue(idx, _image_md(image))

    out: list[str] = []
    for md in after.get(-1, []):
        out.extend((md, ""))
    for i, line in enumerate(lines):
        out.append(line)
        for md in after.get(i, []):
            out.extend(("", md))
    return "\n".join(out)


# --------------------------------------------------------------------------- #
# Terminal writes (degrade / defer / fail) - all same-status or ->failed, guarded
# --------------------------------------------------------------------------- #
def _hold_degraded(
    store: ContentStore,
    code: str,
    row: dict[str, Any],
    gate: CostGate,
    *,
    stage_key: str,
    reason: str,
) -> ContentJobOutcome:
    """Advance a queued job to ``drafting`` (if needed) and HOLD it there with an
    honest degraded marker + the real partial spend. A re-enqueue when keys/budget
    return catches up. Never crashes."""
    label = f"{_STAGE_LABEL.get(stage_key, 'Drafting')} — degraded ({reason})"
    cost = round(getattr(gate, "spent", 0.0), 2)
    fields: dict[str, Any] = {"stage": label, "cost": cost}
    if row.get("status") == "queued":
        fields["status"] = "drafting"
    store.update(code, fields)
    logger.info("content_job_degraded", code=code, reason=reason)
    return ContentJobOutcome(code, "drafting", "degraded", stage=label, cost=cost, reason=reason)


def _defer(store: ContentStore, code: str, row: dict[str, Any], *, reason: str) -> ContentJobOutcome:
    """Hold the job at its CURRENT status (no spend, no advance) with a deferred
    marker - the R5 pre-check verdict. A later run retries when budget frees."""
    status = str(row.get("status") or "queued")
    label = f"Deferred — {reason}"
    store.update(code, {"stage": label})  # same-status streaming write
    logger.info("content_job_deferred", code=code, reason=reason)
    return ContentJobOutcome(code, status, "deferred", stage=label, cost=0.0, reason=reason)


def _fail(store: ContentStore, code: str, gate: CostGate, *, error: str) -> ContentJobOutcome:
    """Mark the job ``failed`` (any->failed is always legal) - never leaves it stuck."""
    cost = round(getattr(gate, "spent", 0.0), 2)
    try:
        store.update(code, {"status": "failed", "stage": "Failed", "cost": cost})
    except Exception:  # even the fail-write must not raise out of the task
        logger.warning("content_fail_write_failed", code=code)
    return ContentJobOutcome(code, "failed", "failed", stage="Failed", cost=cost, reason=error[:_ERROR_MAX])


# --------------------------------------------------------------------------- #
# P7A-7: the pipeline core
# --------------------------------------------------------------------------- #
def execute_content_job(
    store: ContentStore,
    providers: ContentProviders | None,
    code: str,
    *,
    settings: Settings,
    gate: CostGate,
    fetcher: PageFetcher | None = None,
    judge: Judge | None = None,
    scorer: QaScorer | None = None,
) -> ContentJobOutcome:
    """Drive one content job through the canonical pipeline to the human gate.

    Pure of Celery/DB/network (all injected). Advances ``queued -> drafting ->
    needs_review`` and STOPS at ``needs_review`` (never auto-publishes), attaching
    the QA score so the reviewer sees it. Idempotent (a terminal job is a no-op),
    never stuck (any error -> failed), never re-raises (``acks_late``-safe). A
    cost-gate block or absent providers DEGRADES (holds at ``drafting``, $0).
    """
    row = store.load(code)
    if row is None:
        logger.warning("content_job_missing", code=code)
        return ContentJobOutcome(code, "failed", "failed", reason="not found")

    status = str(row.get("status") or "")
    if status not in _WORKER_OWNED:
        # Terminal-for-the-worker (needs_review / publishing / done / failed /
        # rejected): a redelivery is a no-op - never re-run the pipeline.
        return ContentJobOutcome(code, status, "noop", reason="not worker-owned (idempotent)")

    # Degraded: no providers (keys unconfigured). Hold at drafting, honest $0.
    if providers is None:
        return _hold_degraded(store, code, row, gate, stage_key="draft", reason="providers unconfigured")

    client_id = str(row["client_id"]) if row.get("client_id") else None

    # R5 cost pre-check: estimate the FULL job spend and defer if it would breach
    # the client cap / the global spend halt (or the content dial is off/byhand).
    precheck = GateContext(
        feature_key=_CONTENT_FEATURE,
        client_id=client_id,
        provider=_LLM_PROVIDER,
        estimated_cost=_estimate_full_cost(providers, settings),
        job_id=code,
        job_type=_JOB_TYPE,
        cache_key=None,
    )
    decision = gate.evaluate(precheck)
    if not decision.allowed:
        return _defer(store, code, row, reason=f"cost pre-check ({decision.outcome})")

    try:
        return _run_pipeline(
            store, providers, code, row,
            settings=settings, gate=gate, fetcher=fetcher, judge=judge,
            scorer=scorer or score, client_id=client_id,
        )
    except ContentSpendBlocked as blocked:
        # A gate block landed mid-generation: no half-write (the needs_review write
        # is the only status advance, and it never ran). Degrade, don't crash.
        return _hold_degraded(store, code, row, gate, stage_key="draft", reason=f"spend blocked ({blocked.outcome})")
    except Exception as exc:  # never re-raise: acks_late would redeliver = double spend
        logger.exception("content_job_crashed", code=code)
        return _fail(store, code, gate, error=f"worker error: {exc!r}")


def _run_pipeline(
    store: ContentStore,
    providers: ContentProviders,
    code: str,
    row: dict[str, Any],
    *,
    settings: Settings,
    gate: CostGate,
    fetcher: PageFetcher | None,
    judge: Judge | None,
    scorer: QaScorer,
    client_id: str | None,
) -> ContentJobOutcome:
    """The happy-path composition (research -> ... -> qa loop -> needs_review)."""
    keyword = str(row.get("topic") or "")
    source_pack = _source_pack_from_row(row)
    geo = _geo_for(row, source_pack)
    # The reviewer's guided-edit instruction (set by a lead on the needs_review->
    # drafting `edit` transition). When present this run is a GUIDED re-draft: after
    # generation the body prose is rewritten to satisfy it (below), then cleared.
    edit_instruction = str(row.get("edit_instruction") or "").strip()

    def stream(stage_key: str) -> None:
        # Same-status streaming write (drafting->drafting): stage label + live cost.
        store.update(code, {"stage": _STAGE_LABEL[stage_key], "cost": round(getattr(gate, "spent", 0.0), 2)})

    # queued -> drafting (the one status advance before the human gate).
    if row.get("status") == "queued":
        store.update(code, {"status": "drafting", "stage": _STAGE_LABEL["research"]})

    # --- research -> cluster -> serp_format -> fan_out -> winnability -> teardown
    researcher = GatedResearcher(
        providers.serp,
        fetcher or SsrfSafePageFetcher(),
        gate,
        settings=settings,
        client_id=client_id,
        job_id=code,
    )
    brief = build_research_brief(
        keyword,
        researcher=researcher,
        geo=geo,
        client_da=None,  # un-audited by default -> neutral DA, brief flags low_confidence
        max_teardown=settings.content_teardown_max_pages,
        neutral_da=settings.content_research_neutral_da,
        winnable_stretch=settings.content_research_winnable_stretch,
    )
    stream("teardown")
    if brief.degraded:
        # The SERP pull itself was gate-blocked -> a shell brief; nothing to draft.
        return _hold_degraded(store, code, row, gate, stage_key="research", reason="research spend blocked")

    # --- outline -> draft -> titles_meta (one generation pass builds all three)
    stream("outline")
    context: GenerationContext | None = None  # fresh 6B context not wired here yet
    writer = _ContentGatedWriter(providers.writer, gate, settings=settings, client_id=client_id, job_id=code)
    content = generate(
        brief,
        source_pack,
        context,
        page_type=str(row.get("page_type") or "blog"),
        framework=str(row.get("framework") or "Auto"),
        target=str(row.get("target") or "WordPress"),
        writer=writer,
        model=providers.model_writer,
        tuning=_tuning(settings),
    )
    stream("titles_meta")

    # --- guided edit (only when a reviewer requested changes): re-draft the body
    # prose to satisfy the instruction, reusing the SAME cost-gated writer (billed to
    # the content dial) + content_guard's per-section rewrite + hard dash-strip. This
    # is a GUIDED edit, not a blind regen - the reviewer's note steers each prose
    # block; headings + the extractable answer block are untouched so QA structure
    # holds. Runs BEFORE the em-dash guard + schema/QA so all of them see the edited
    # draft. A spend-blocked / erroring writer degrades per-block to a plain strip.
    if edit_instruction:
        content = apply_edit_instruction(
            content,
            instruction=edit_instruction,
            writer=writer,
            model=providers.model_writer,
            max_rewrites=_GUARD_MAX_REWRITES,
        )
        logger.info("content_guided_edit_applied", code=code)

    # --- content guard (single em-dash / de-AI pass): rewrite any over-AI section via
    # the SAME cost-gated writer (billed to the content dial + priced by pricing.py)
    # and HARD-strip every em/en dash from the body + every text field. The strip is
    # unconditional, so the stored + published draft is GUARANTEED em/en-dash-free even
    # if a rewrite is spend-blocked or the writer errs. Runs ONCE, before the QA loop,
    # so every scored candidate is already clean.
    guarded = guard_generated(
        content, writer=writer, model=providers.model_writer, max_rewrites=_GUARD_MAX_REWRITES
    )
    content = guarded.content
    logger.info(
        "content_guard_applied",
        code=code,
        em_before=guarded.result.before.em_dashes,
        en_before=guarded.result.before.en_dashes,
        rewritten=guarded.result.rewritten,
    )

    page_type = str(row.get("page_type") or "blog")

    def _score_candidate(cand: GeneratedContent) -> tuple[QaScore, dict[str, Any], str]:
        # Build + validate the JSON-LD against THIS candidate's visible draft, then
        # score it with the 14-dimension §11 scorecard. Pure + free (no provider
        # spend), so it is safe to re-run on every loop pass.
        pt, business, page, visible = _schema_inputs(row, brief, source_pack, cand)
        graph = build_json_ld(pt, business, page)
        result: ValidationResult = validate_json_ld(graph, visible)
        cand_qa = scorer(cand, brief, result, source_pack, judge=judge)
        return cand_qa, graph, (result.primary_type or schema_for(pt))

    # --- QA IMPROVEMENT LOOP (drafting-time): the worker does NOT accept the first
    # draft. It scores the guarded draft and, while it is below the TOP-1% target
    # (>= the publish floor), feeds the failing dimensions + notes back as a targeted
    # rewrite (the SAME cost-gated writer + revise machinery the human edit uses,
    # driven by rewrite_guidance instead of a human note) and re-scores. Bounded by
    # settings.content_qa_max_loops; EVERY rewrite is cost-gated, so a spend block does
    # ZERO writer work -> the loop stops and advances with the BEST draft so far. Never
    # spins forever, never raises. Only after the loop does the job advance to review.
    stream("qa")
    target = settings.content_qa_target_score
    max_loops = max(0, settings.content_qa_max_loops)
    qa, json_ld, schema_type = _score_candidate(content)
    best_content, best_qa, best_json_ld, best_schema_type = content, qa, json_ld, schema_type
    qa_loops = 0
    while not (qa.passed and qa.weighted_total >= target) and qa_loops < max_loops:
        guidance = rewrite_guidance(qa, target=target)
        if not guidance:  # nothing below target to steer (defensive; while-cond implies some)
            break
        rewrite = guided_rewrite(
            content, instruction=guidance, writer=writer, model=providers.model_writer,
            max_rewrites=_GUARD_MAX_REWRITES, note_label="QA auto-revise",
        )
        if rewrite.result.writer_calls == 0:
            # Cost-blocked (or no revisable prose): stop, advance with the best draft.
            logger.info("content_qa_loop_cost_stopped", code=code, loops=qa_loops)
            break
        content = rewrite.content
        qa_loops += 1
        qa, json_ld, schema_type = _score_candidate(content)
        if qa.weighted_total > best_qa.weighted_total:
            best_content, best_qa, best_json_ld, best_schema_type = content, qa, json_ld, schema_type
        stream("qa")

    # Advance with the BEST-scoring candidate (a later pass can regress; keep the best).
    content, qa, json_ld, schema_type = best_content, best_qa, best_json_ld, best_schema_type
    logger.info(
        "content_qa_loop_done", code=code, loops=qa_loops,
        passed=qa.passed, weighted_total=qa.weighted_total,
    )

    # --- images (bounded, gated) -> inject into the draft -> assemble
    stream("images")
    image_count, resolved_images = _generate_images(
        providers.images, content, gate, settings, client_id=client_id, code=code
    )
    if resolved_images:
        # Weave the generated image URLs into the draft as ![alt](url) blocks so they flow
        # to the stored draft, the Elementor tree, AND the WordPress payload (a fake/empty
        # result was filtered out above -> nothing to inject, no broken markdown).
        content = replace(content, draft_md=_inject_images(content.draft_md, resolved_images))
    stream("assemble")

    # --- layout: a simple deterministic heuristic picks ONE presentation template
    # from the finished draft's observable signals (page type, images, length, a Q&A
    # block). Stored on the outline so the Review preview frames the draft correctly.
    layout = pick_layout(
        page_type,
        images=image_count,
        words=content.word_count,
        has_faq=any(h.level == 3 for h in content.headings),
        has_local=page_type == "local",
    )
    outline = _outline(content, brief)
    outline["layout"] = layout.as_dict()

    # --- drafting -> needs_review (STOP at the human gate; carry every rich column)
    final_cost = round(getattr(gate, "spent", 0.0), 2)
    fields: dict[str, Any] = {
        "status": "needs_review",
        "stage": _STAGE_LABEL["review"],
        "cost": final_cost,
        "words": content.word_count,
        "images": image_count,
        "schema_type": schema_type,
        "draft_md": content.draft_md,
        "keyword_map": _keyword_map(brief),
        "outline": outline,
        "entity_coverage": _entity_coverage(content, brief),
        "qa_score": _qa_dict(qa),
        "json_ld": json_ld,
        "internal_links": _internal_links(content),
    }
    if edit_instruction:
        # Applied - clear it so a later unrelated re-run does not re-apply it.
        fields["edit_instruction"] = ""
    store.update(code, fields)
    logger.info(
        "content_job_needs_review",
        code=code, passed=qa.passed, weighted_total=qa.weighted_total, qa_loops=qa_loops,
    )
    # TEAM/WORKER -> LEAD: a draft reached the review gate; email + in-app the leads who
    # own the sign-off (best-effort; each lead's notification_prefs govern the email leg;
    # content_review is a NOTIF_EVENTS key, email default on). Never fails the job.
    client_name = str(row.get("client_name") or "a client")
    topic = str(row.get("topic") or "A draft")
    notify_leads_sync(
        "content_review",
        f"Content ready for review: {topic}",
        f'"{topic}" for {client_name} has been drafted and is awaiting review. '
        "Approve it or send it back from the content review queue.",
    )
    return ContentJobOutcome(
        code, "needs_review", "advanced", stage=_STAGE_LABEL["review"], cost=final_cost,
        passed=qa.passed, qa_loops=qa_loops,
    )


# --------------------------------------------------------------------------- #
# P7A-8: the QA-gated publish core
# --------------------------------------------------------------------------- #
def _extract_title(draft_md: str) -> str:
    for line in draft_md.splitlines():
        stripped = line.strip()
        if stripped.startswith("# "):
            return stripped[2:].strip()
    return ""


_MD_LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
_MD_BOLD_RE = re.compile(r"\*\*([^*]+)\*\*")
_MD_IMG_RE = re.compile(r"!\[([^\]]*)\]\(([^)]+)\)")


def _md_inline(text: str) -> str:
    # Images FIRST (``![alt](url)``) so the link regex never mistakes one for a plain
    # link; then links and bold. A standalone image line becomes ``<p><img ..></p>``.
    text = _MD_IMG_RE.sub(r'<img src="\2" alt="\1">', text)
    text = _MD_LINK_RE.sub(r'<a href="\2">\1</a>', text)
    return _MD_BOLD_RE.sub(r"<strong>\1</strong>", text)


def md_to_html(draft_md: str) -> str:
    """A minimal, dependency-free Markdown -> HTML render for the WP body (headings,
    paragraphs, bullet lists, inline links/bold). The draft is human-reviewed; this
    need not be a full CommonMark implementation."""
    parts: list[str] = []
    bullets: list[str] = []

    def flush() -> None:
        if bullets:
            parts.append("<ul>" + "".join(f"<li>{_md_inline(b)}</li>" for b in bullets) + "</ul>")
            bullets.clear()

    for line in draft_md.splitlines():
        s = line.strip()
        if not s:
            flush()
        elif s.startswith("### "):
            flush()
            parts.append(f"<h3>{_md_inline(s[4:])}</h3>")
        elif s.startswith("## "):
            flush()
            parts.append(f"<h2>{_md_inline(s[3:])}</h2>")
        elif s.startswith("# "):
            flush()
            parts.append(f"<h1>{_md_inline(s[2:])}</h1>")
        elif s.startswith("- "):
            bullets.append(s[2:])
        else:
            flush()
            parts.append(f"<p>{_md_inline(s)}</p>")
    flush()
    return "\n".join(parts)


# --------------------------------------------------------------------------- #
# Design-profile structural shaping (match the target site's section order).
# --------------------------------------------------------------------------- #
# When a content job carries a site-design profile (from POST /content/site-design,
# seeded into source_pack["design_profile"] by the router), the publish body is wrapped
# in ordered <section class="aios-<name>"> blocks following the profile's
# layout.section_order - a best-effort STRUCTURAL match to the client's existing site so
# a theme can style each named section. Deep Elementor/Gutenberg BLOCK generation (a live
# page builder's block tree) is a LATER chunk and is deliberately NOT built here. When no
# profile is present the body is EXACTLY md_to_html(draft_md) - no regression.
def _design_section_order(row: dict[str, Any]) -> list[str]:
    """The ordered section names from the job's design profile, or ``[]`` when absent."""
    profile = _as_dict(_as_dict(row.get("source_pack")).get("design_profile"))
    order = _as_dict(profile.get("layout")).get("section_order")
    if not isinstance(order, list):
        return []
    return [str(name).strip() for name in order if str(name).strip()]


def _resolve_row_blueprint(row: dict[str, Any]) -> list[SectionSpec]:
    """The effective ordered page blueprint for a job: the ANALYZED site's blueprint if
    present, else the chosen TEMPLATE, else the page-type default (see
    ``page_blueprints.resolve_blueprint``). ``[]`` -> no structure to shape by (the
    publish path keeps its plain behaviour)."""
    raw = _as_dict(row.get("source_pack"))
    profile = _as_dict(raw.get("design_profile")) or None
    template = str(raw.get("template") or "").strip() or None
    page_type = str(row.get("page_type") or "blog")
    return resolve_blueprint(design_profile=profile, template=template, page_type=page_type)


def _content_section_specs(specs: list[SectionSpec]) -> list[tuple[str, str]]:
    """The (kind, layout) pairs of the CONTENT-bearing sections - the ones the flat-HTML
    wrapper distributes the rendered ``<h2>`` groups across (chrome sections are theme /
    plugin supplied, never wrapped around generated copy)."""
    return [(s.kind, s.layout) for s in specs if s.content]


def _wrap_sections(body_html: str, section_order: list[str]) -> str:
    """Back-compat wrapper: wrap by bare section NAMES (``aios-<name>``). Retained for
    the design-profile-only path + existing tests; the richer path uses
    :func:`_wrap_sections_specs` to also carry the per-kind ``aios-layout-<variant>``."""
    return _wrap_sections_specs(body_html, [(name, "") for name in section_order])


def _wrap_sections_specs(body_html: str, specs: list[tuple[str, str]]) -> str:
    """Group the rendered top-level blocks by ``<h2>`` boundary and wrap each group in
    the next content section's ``<section class="aios-<kind> aios-layout-<variant>">``
    block, so the published page follows the blueprint's exact section sequence + carries
    the per-kind component-styling hooks the ``<style>`` block targets.

    Content before the first ``<h2>`` (the ``<h1>`` + intro) is the first group; groups
    beyond the section count fold into the LAST section; empty sections are skipped.
    Returns the plain body unchanged when there is nothing to wrap.
    """
    blocks = [b for b in body_html.split("\n") if b.strip()]
    if not blocks or not specs:
        return body_html

    groups: list[list[str]] = []
    current: list[str] = []
    for block in blocks:
        if block.startswith("<h2") and current:
            groups.append(current)
            current = [block]
        else:
            current.append(block)
    if current:
        groups.append(current)

    n = len(specs)
    buckets: list[list[str]] = [[] for _ in specs]
    for idx, group in enumerate(groups):
        buckets[idx if idx < n else n - 1].extend(group)

    out: list[str] = []
    for (kind, variant), bucket in zip(specs, buckets, strict=True):
        if not bucket:
            continue
        cls = f"aios-{_slug(kind)}"
        if variant:
            cls += f" aios-layout-{_slug(variant)}"
        out.append(f'<section class="{cls}">\n' + "\n".join(bucket) + "\n</section>")
    return "\n".join(out) if out else body_html


# --------------------------------------------------------------------------- #
# Design-profile VISUAL styling: a <style> block from the COPIED site's tokens so the
# published WordPress page visually matches it (colours + fonts + layout + components),
# not just its section order. Every token is optional -> a missing sub-field simply
# omits its rule (degrade to the prior behaviour); no profile -> no <style> at all.
# --------------------------------------------------------------------------- #
def _radius_px(style: str) -> int:
    """Map a component style phrase (button/card) to a border-radius in px."""
    s = (style or "").lower()
    if "pill" in s:
        return 999
    if "sharp" in s or "square" in s:
        return 0
    if "round" in s:
        return 8
    return 6


def _spacing_px(scale: str) -> int:
    """Map a spacing-scale phrase to a section vertical padding in px."""
    s = (scale or "").lower()
    if "compact" in s or "tight" in s or "dense" in s:
        return 24
    if "spacious" in s or "airy" in s or "generous" in s or "roomy" in s:
        return 72
    return 48  # comfortable / default


def _design_style_block(profile: dict[str, Any]) -> str:
    """Build a self-contained ``<style>`` block from the design profile's palette /
    typography / layout / component tokens, scoped to ``.aios-page`` so it only styles
    the generated body. Returns ``""`` when the profile carries nothing usable."""
    palette = _as_dict(profile.get("palette"))
    typo = _as_dict(profile.get("typography"))
    layout = _as_dict(profile.get("layout"))
    comps = _as_dict(profile.get("components"))
    page = ".aios-page"
    rules: list[str] = []

    container = str(layout.get("container_width") or "").strip()
    body_font = str(typo.get("body_font") or "").strip()
    heading_font = str(typo.get("heading_font") or "").strip()
    base_size = str(typo.get("base_size") or "").strip()
    text_color = str(palette.get("text") or "").strip()
    accent = str(palette.get("accent") or "").strip()
    primary = str(palette.get("primary") or "").strip()

    page_decls = ["margin:0 auto"]
    if container:
        page_decls.append(f"max-width:{container}")
    if body_font:
        page_decls.append(f"font-family:{body_font}")
    if base_size:
        page_decls.append(f"font-size:{base_size}")
    if text_color:
        page_decls.append(f"color:{text_color}")
    rules.append(f"{page}{{{';'.join(page_decls)}}}")

    head_decls: list[str] = []
    if heading_font:
        head_decls.append(f"font-family:{heading_font}")
    if primary:
        head_decls.append(f"color:{primary}")
    if head_decls:
        rules.append(f"{page} h1,{page} h2,{page} h3{{{';'.join(head_decls)}}}")

    spacing = str(comps.get("spacing_scale") or "").strip()
    if spacing:
        rules.append(f"{page} section{{padding:{_spacing_px(spacing)}px 0}}")

    if accent:
        rules.append(f"{page} a{{color:{accent}}}")
    button_style = str(comps.get("button_style") or "").strip()
    if accent and button_style:
        bg = str(palette.get("background") or "#ffffff").strip() or "#ffffff"
        btn = ["display:inline-block", "padding:12px 22px",
               f"border-radius:{_radius_px(button_style)}px", "text-decoration:none"]
        low = button_style.lower()
        if "outline" in low or "ghost" in low:
            btn += ["background:transparent", f"color:{accent}", f"border:2px solid {accent}"]
        else:
            btn += [f"background:{accent}", f"color:{bg}"]
        rules.append(f"{page} .aios-cta a{{{';'.join(btn)}}}")

    card_style = str(comps.get("card_style") or "").strip()
    if card_style:
        card = ["padding:20px", f"border-radius:{_radius_px(card_style)}px"]
        low = card_style.lower()
        if "shadow" in low:
            card.append("box-shadow:0 2px 12px rgba(0,0,0,.08)")
        elif "border" in low or "outline" in low:
            line = str(palette.get("secondary") or "#e5e7eb").strip() or "#e5e7eb"
            card.append(f"border:1px solid {line}")
        rules.append(f"{page} blockquote,{page} .aios-card{{{';'.join(card)}}}")

    hero_style = str(layout.get("hero_style") or "").strip()
    if hero_style:
        hero = ["padding:64px 0"]
        if "center" in hero_style.lower():
            hero.append("text-align:center")
        bg = str(palette.get("background") or "").strip()
        if bg:
            hero.append(f"background:{bg}")
        rules.append(f"{page} > section:first-child{{{';'.join(hero)}}}")

    return "<style>" + "".join(rules) + "</style>" if rules else ""


# Structural, palette-agnostic component CSS (scoped to ``.aios-page``): renders the
# per-kind ``aios-layout-<variant>`` hooks as classic components (grids, banners, cards)
# so the flat-HTML body + PDF look good even without an analyzed profile. The palette /
# font rules are layered on top by ``_design_style_block`` (or ``_classic_style_block``).
_LAYOUT_CSS = (
    ".aios-page section{margin:40px auto;padding:8px 0}"
    ".aios-page img{max-width:100%;height:auto;border-radius:10px}"
    ".aios-page .aios-layout-grid ul{display:grid;"
    "grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:18px;list-style:none;"
    "padding:0;margin:22px 0}"
    ".aios-page .aios-layout-grid li{padding:18px 20px;border-radius:12px;"
    "background:rgba(15,23,42,.035)}"
    ".aios-page .aios-layout-numbered-steps ol,.aios-page .aios-layout-numbered-steps ul"
    "{padding-left:1.1em;margin:18px 0}"
    ".aios-page .aios-layout-numbered-steps li{margin:10px 0}"
    ".aios-page .aios-layout-accordion h3{margin:14px 0 4px;cursor:default}"
    ".aios-page .aios-cta,.aios-page .aios-layout-banner{text-align:center;"
    "padding:52px 24px;border-radius:16px;margin:48px auto}"
    ".aios-page .aios-hero,.aios-page section:first-child{padding-top:16px}"
)


def _classic_style_block() -> str:
    """A premium, palette-agnostic default ``<style>`` for a TEMPLATE-only page (no
    analyzed profile): clean type scale + spacing so a generated page still looks
    professional out of the box."""
    return (
        "<style>.aios-page{max-width:1160px;margin:0 auto;color:#1e293b;"
        "font-family:system-ui,-apple-system,'Segoe UI',Roboto,sans-serif;line-height:1.65;"
        "font-size:17px}"
        ".aios-page h1,.aios-page h2,.aios-page h3{color:#0f172a;line-height:1.18;"
        "font-weight:700}"
        ".aios-page h1{font-size:2.6rem;margin:.2em 0 .4em}"
        ".aios-page h2{font-size:1.9rem;margin:1.4em 0 .5em}"
        ".aios-page h3{font-size:1.3rem;margin:1.1em 0 .3em}"
        ".aios-page a{color:#2563eb}</style>"
    )


def _with_layout_css(style: str) -> str:
    """Fold the structural ``_LAYOUT_CSS`` into an existing ``<style>…</style>`` block
    (or wrap it when there is none)."""
    if style.endswith("</style>"):
        return style[: -len("</style>")] + _LAYOUT_CSS + "</style>"
    return f"<style>{_LAYOUT_CSS}</style>{style}"


def _shape_body_html(row: dict[str, Any], draft_md: str) -> str:
    """Render the draft to HTML and shape it to the job's page BLUEPRINT: wrap the body
    in the blueprint's ordered ``<section class="aios-<kind> aios-layout-<variant>">``
    blocks + a ``<style>`` block so the published page MATCHES the analyzed site (colours
    + fonts + layout + components) or the chosen TEMPLATE's classic structure - not just
    a flat section-order. No profile AND no template -> plain render (no regression)."""
    html = md_to_html(draft_md)
    profile = _as_dict(_as_dict(row.get("source_pack")).get("design_profile"))
    specs = _resolve_row_blueprint(row)
    content_specs = _content_section_specs(specs)
    if content_specs:
        html = _wrap_sections_specs(html, content_specs)
    elif profile:
        order = _design_section_order(row)
        if order:
            html = _wrap_sections(html, order)
    if not profile and not specs:
        return html  # nothing to shape by -> plain render (no regression)
    style = (_design_style_block(profile) if profile else "") or _classic_style_block()
    style = _with_layout_css(style)
    return f'{style}\n<div class="aios-page">\n{html}\n</div>'


def _write_artifacts(
    artifacts: ContentArtifactStore | None, code: str, draft_md: str, title: str
) -> tuple[str | None, str | None]:
    """Render the draft to the traversal-safe artifact store; never fatal."""
    if artifacts is None:
        return None, None
    try:
        return artifacts.store(code, markdown=draft_md, title=title)
    except Exception:
        logger.warning("content_artifact_store_failed", code=code)
        return None, None


def _wp_creds_by_domain(site_url: str, code: str) -> tuple[str, str] | None:
    """Look up ``"<username>:<app password>"`` by THE vault convention (see on_page).

    One ``vault_keys`` row per WordPress site: ``provider='wordpress'``, ``label`` =
    the site's domain, secret = ``"<username>:<application password>"`` — the exact
    convention ``app.modules.on_page`` already resolves. Tries the URL's host and
    its ``www.``-stripped twin so the label matches however the site was added.
    Returns ``(username, app_password)`` or None; never raises.
    """
    from urllib.parse import urlparse

    host = (urlparse(site_url).netloc or site_url).strip().lower()
    if not host:
        return None
    labels = [host]
    if host.startswith("www."):
        labels.append(host[4:])
    else:
        labels.append(f"www.{host}")
    try:
        from app.db.database import privileged_connection
        from app.services.vault import reveal_secret

        with privileged_connection() as cur:
            cur.execute(
                "select id from public.vault_keys "
                "where provider = 'wordpress' and lower(label) = any(%s) limit 1",
                (labels,),
            )
            key_row = cur.fetchone()
        if key_row is None:
            return None
        secret = reveal_secret(str(key_row["id"])) or ""
    except Exception:
        logger.warning("wp_credential_reveal_failed", code=code)
        return None
    if ":" not in secret:
        return None
    username, app_password = secret.split(":", 1)
    if not username.strip() or not app_password.strip():
        return None
    return username.strip(), app_password.strip()


def _resolve_wp_from_vault(row: dict[str, Any], settings: Settings) -> WpTarget | None:
    """Resolve a per-site WordPress publisher from the job's WP config + the vault.

    Two resolution paths, in order:

    1. EXPLICIT: ``source_pack`` carries ``wp_username`` + ``wp_vault_key_id``
       (a pre-resolved key id) -> reveal that key directly.
    2. DOMAIN CONVENTION (the path the router actually seeds): only
       ``wp_site_url`` is present -> look up the ``vault_keys`` row with
       ``provider='wordpress'`` and ``label`` = the site's domain, secret
       ``"<username>:<app password>"`` — the SAME convention the on-page module
       resolves, so one vault row powers both publish and on-page edits.

    Any missing piece (or a reveal failure) returns ``None`` -> the publish
    degrades to artifact-only, never a crash.
    """
    raw = _as_dict(row.get("source_pack"))
    site_url = str(raw.get("wp_site_url") or "").strip()
    if not site_url:
        return None
    code = str(row.get("code", ""))
    username = str(raw.get("wp_username") or "").strip()
    key_id = str(raw.get("wp_vault_key_id") or "").strip()
    app_password = ""
    if username and key_id:
        try:
            from app.services.vault import reveal_secret

            app_password = reveal_secret(key_id) or ""
        except Exception:
            logger.warning("wp_credential_reveal_failed", code=code)
            return None
    else:
        creds = _wp_creds_by_domain(site_url, code)
        if creds is None:
            return None
        username, app_password = creds
    if not app_password:
        return None
    try:
        from integrations.wordpress import WordPressClient

        publisher: WordPressPublisher = WordPressClient(username=username, app_password=app_password)
    except Exception:
        logger.warning("wp_client_unavailable", code=code)
        return None
    return WpTarget(site_url=site_url, publisher=publisher)


# --------------------------------------------------------------------------- #
# AIOS Publisher plugin resolution (the host-independent WordPress push).
# --------------------------------------------------------------------------- #
# The companion WordPress plugin exposes its OWN endpoint + shared-key auth, so a
# client site that strips the Authorization header / disables Application Passwords /
# runs an anti-bot layer can still receive an approved page as a DRAFT. The shared
# key lives in the vault under the EXISTING 'wordpress' provider (the ProviderId the
# vault API already allows) with a distinct label PREFIX so it never collides with
# the app-password row (label = the bare domain). One vault row per site:
# provider='wordpress', label='aios-publisher:<domain>', secret = the plugin key.
_WP_PLUGIN_LABEL_PREFIX = "aios-publisher:"


def _plugin_key_default(settings: Settings) -> str:
    """The single-site fallback plugin key from settings (revealed), or ''."""
    key = settings.wp_plugin_api_key
    return key.get_secret_value() if key is not None else ""


def _plugin_key_by_domain(site_url: str, code: str) -> str | None:
    """Reveal the per-site AIOS Publisher key from the vault by the label convention
    (provider='wordpress', label='aios-publisher:<domain>'). Tries the host and its
    ``www.``-toggled twin so the label matches however the site was added. Returns the
    key or None; never raises."""
    from urllib.parse import urlparse

    host = (urlparse(site_url).netloc or site_url).strip().lower()
    if not host:
        return None
    hosts = [host]
    if host.startswith("www."):
        hosts.append(host[4:])
    else:
        hosts.append(f"www.{host}")
    labels = [f"{_WP_PLUGIN_LABEL_PREFIX}{h}" for h in hosts]
    try:
        from app.db.database import privileged_connection
        from app.services.vault import reveal_secret

        with privileged_connection() as cur:
            cur.execute(
                "select id from public.vault_keys "
                "where provider = 'wordpress' and lower(label) = any(%s) limit 1",
                (labels,),
            )
            key_row = cur.fetchone()
        if key_row is None:
            return None
        secret = (reveal_secret(str(key_row["id"])) or "").strip()
    except Exception:
        logger.warning("wp_plugin_key_reveal_failed", code=code)
        return None
    return secret or None


def _resolve_wp_plugin(row: dict[str, Any], settings: Settings) -> PluginPublisher | None:
    """Resolve a per-client AIOS Publisher target from the job + the vault/settings.

    ``site_url`` comes from the job's ``source_pack`` (seeded by the router from the
    client's site) or the single-site settings default; the shared key from the vault
    (per the label convention) or the settings default. A missing site_url OR key
    returns None -> the publish path keeps its existing behavior (app-password REST /
    artifact), unchanged. Never raises."""
    raw = _as_dict(row.get("source_pack"))
    code = str(row.get("code", ""))
    site_url = str(
        raw.get("wp_site_url") or raw.get("site_url") or (settings.wp_plugin_site_url or "")
    ).strip()
    if not site_url:
        return None
    api_key = _plugin_key_by_domain(site_url, code) or _plugin_key_default(settings)
    target = resolve_plugin_target(raw, default_site_url=site_url, default_api_key=api_key or "")
    if target is None:
        return None
    try:
        return target.publisher(
            user_agent=settings.wp_plugin_browser_ua, timeout=settings.wp_plugin_timeout_seconds
        )
    except Exception:
        logger.warning("wp_plugin_client_unavailable", code=code)
        return None


# --------------------------------------------------------------------------- #
# Per-client WordPress Connections registry (0058) - the PRIMARY publish target.
# --------------------------------------------------------------------------- #
# The admin connects EVERY client's WordPress site in one place (public.wp_connections:
# site_url + auth_method + a sealed credential). At publish time the RIGHT client's
# connection is resolved by client_id and the approved draft is pushed through the
# adapter for its auth_method: 'plugin' -> the AIOS Publisher plugin; 'xmlrpc' -> the
# XML-RPC seam (hostile-host-proof); 'app_password' -> the REST app-password seam. No
# connection for a client -> None (the legacy single-site fallbacks + artifact path,
# unchanged). All resolution is best-effort and NEVER raises.
@dataclass(frozen=True)
class ClientWpTarget:
    """A resolved per-client WordPress target: the site + a ready adapter for its auth
    method. ``plugin`` carries a PluginPublisher (method ``plugin``); ``publisher``
    carries a WordPressPublisher (methods ``xmlrpc`` / ``app_password``)."""

    method: str
    site_url: str
    plugin: PluginPublisher | None = None
    publisher: WordPressPublisher | None = None


def build_client_wp_target(conn: ResolvedWpConnection, settings: Settings) -> ClientWpTarget | None:
    """Turn a resolved + opened connection into a ready adapter, or None if unusable.

    Pure of the DB (the credential is already opened by ``resolve_connection``), so it
    is unit-tested directly with a fabricated ``ResolvedWpConnection``. A construction
    failure (missing httpx / bad config) degrades to None -> the publish falls back."""
    site_url = conn.site_url.strip()
    if not site_url or not conn.secret:
        return None
    ua = settings.wp_connection_browser_ua
    timeout = settings.wp_connection_timeout_seconds
    try:
        if conn.auth_method == "plugin":
            from integrations.wordpress_publisher import WordPressPluginPublisher

            plugin = WordPressPluginPublisher(
                site_url=site_url, api_key=conn.secret, user_agent=ua, timeout=timeout
            )
            return ClientWpTarget("plugin", site_url, plugin=plugin)
        if conn.auth_method == "xmlrpc":
            from integrations.wordpress import XmlRpcWordPressPublisher

            xml = XmlRpcWordPressPublisher(
                username=conn.username, app_password=conn.secret, user_agent=ua, timeout=timeout
            )
            return ClientWpTarget("xmlrpc", site_url, publisher=xml)
        if conn.auth_method == "app_password":
            from integrations.wordpress import WordPressClient

            rest = WordPressClient(
                username=conn.username, app_password=conn.secret, user_agent=ua, timeout=timeout
            )
            return ClientWpTarget("app_password", site_url, publisher=rest)
    except Exception:
        logger.warning("wp_connection_client_unavailable", method=conn.auth_method)
        return None
    return None


def _resolve_wp_connection(row: dict[str, Any], settings: Settings) -> ClientWpTarget | None:
    """Resolve the job's client's WordPress connection (0058) into a publish target.

    Never raises: no client_id / no connection row / no sealed credential / an
    unopenable blob all degrade to None -> the legacy single-site fallbacks run,
    unchanged. The credential is opened only here, server-side, never on the wire."""
    client_id = row.get("client_id")
    if not client_id:
        return None
    try:
        conn = resolve_connection(str(client_id))
    except Exception:
        logger.warning("wp_connection_resolve_failed", code=str(row.get("code", "")))
        return None
    if conn is None:
        return None
    return build_client_wp_target(conn, settings)


# --- Article-template component derivation (best-effort, from the finished draft).
# The AIOS Publisher plugin renders these into styled, theme-native components (a key-
# takeaways callout, an accessible FAQ + FAQPage JSON-LD, a closing CTA banner). Parsed
# from the markdown the generator already produces; every piece is OPTIONAL (absent ->
# the plugin simply omits that component), so this never fabricates content.
_TAKEAWAY_HEADINGS: tuple[str, ...] = (
    "key takeaway", "takeaway", "key point", "summary", "tl;dr", "tldr", "in short",
)
_FAQ_HEADINGS: tuple[str, ...] = ("faq", "frequently asked", "questions")


def _strip_md(text: str) -> str:
    """Reduce inline markdown (links, bold) to the plain text a data field needs."""
    text = _MD_LINK_RE.sub(r"\1", text)
    text = _MD_BOLD_RE.sub(r"\1", text)
    return text.strip().strip("*").strip()


def _derive_takeaways(draft_md: str) -> list[str]:
    """Key-takeaway bullets: an explicit takeaways/summary section if the draft has one,
    else the first contiguous bullet list in the body (capped at 6)."""
    lines = draft_md.splitlines()
    explicit: list[str] = []
    in_section = False
    for line in lines:
        s = line.strip()
        heading = re.match(r"^#{1,6}\s+(.*)$", s)
        if heading:
            in_section = any(k in heading.group(1).strip().lower() for k in _TAKEAWAY_HEADINGS)
            continue
        if in_section and s.startswith("- "):
            item = _strip_md(s[2:])
            if item:
                explicit.append(item)
    if explicit:
        return explicit[:6]
    first: list[str] = []
    for line in lines:
        s = line.strip()
        if s.startswith("- "):
            item = _strip_md(s[2:])
            if item:
                first.append(item)
        elif first:
            break  # the first bullet list ended
    return first[:6]


def _derive_faq(draft_md: str) -> list[dict[str, str]]:
    """FAQ pairs parsed from an FAQ section (H3 questions + the prose that follows)."""
    in_faq = False
    faq: list[dict[str, str]] = []
    question: str | None = None
    answer: list[str] = []

    def flush() -> None:
        nonlocal question, answer
        if question and answer:
            faq.append({"question": question, "answer": " ".join(answer).strip()})
        question, answer = None, []

    for line in draft_md.splitlines():
        s = line.strip()
        h2 = re.match(r"^##\s+(.*)$", s)
        h3 = re.match(r"^###\s+(.*)$", s)
        if h2:
            flush()
            in_faq = any(k in h2.group(1).strip().lower() for k in _FAQ_HEADINGS)
        elif not in_faq:
            continue
        elif h3:
            flush()
            question = _strip_md(h3.group(1))
        elif s and question is not None:
            answer.append(_strip_md(s))
    flush()
    return faq[:8]


def _derive_cta(row: dict[str, Any]) -> dict[str, str]:
    """A closing call-to-action for the article (always present; best practice). The
    button defaults to the client's own site."""
    raw = _as_dict(row.get("source_pack"))
    site_url = str(raw.get("wp_site_url") or raw.get("site_url") or "").strip()
    client = str(raw.get("client_name") or row.get("client_name") or "our team").strip() or "our team"
    topic = str(row.get("topic") or "your goals").strip() or "your goals"
    return {
        "heading": "Ready to take the next step?",
        "text": f"Talk to {client} about {topic} and get expert guidance tailored to you.",
        "button_label": "Get in touch",
        "button_url": site_url,
    }


def _plugin_payload(
    row: dict[str, Any], draft_md: str, title: str, *, settings: Settings | None = None
) -> dict[str, Any]:
    """Build the AIOS Publisher push body from the finished job (title, rendered HTML,
    SEO meta, slug, focus keyword, JSON-LD, and the article-template components). Pushed
    as a DRAFT so the admin publishes it on the WordPress site itself (the operator's
    flow). The api_key is injected by the adapter, never assembled here.

    When ``settings.content_elementor_enabled`` is on (the default), the payload ALSO
    carries an Elementor widget TREE (``elementor_data``) + ``elementor_edit_mode`` so
    the plugin writes the Elementor post-meta and the page opens fully editable
    (drag-and-drop) in Elementor. The flat ``content`` HTML is ALWAYS sent too (the
    fallback for a site without Elementor). With the flag OFF the payload is
    byte-identical to the pre-Elementor behaviour (no extra keys)."""
    outline = _as_dict(row.get("outline"))
    meta = _as_dict(outline.get("meta"))
    keyword_map = _as_dict(row.get("keyword_map"))
    payload: dict[str, Any] = {
        "title": title,
        "content": _shape_body_html(row, draft_md),
        "status": "draft",  # push as a DRAFT - a human publishes it on WordPress
        "post_type": "post",
        "slug": _slug(title),
        "meta_title": str(meta.get("title") or title),
        "meta_description": str(meta.get("description") or ""),
        "focus_keyword": str(keyword_map.get("primary") or ""),
    }
    json_ld = row.get("json_ld")
    if isinstance(json_ld, dict) and json_ld.get("@graph"):
        payload["schema_jsonld"] = json.dumps(json_ld)
    # Article-template components (each optional; the plugin styles them theme-native).
    takeaways = _derive_takeaways(draft_md)
    if takeaways:
        payload["key_takeaways"] = takeaways
    faq = _derive_faq(draft_md)
    if faq:
        payload["faq"] = faq
    payload["cta"] = _derive_cta(row)
    # Elementor-editable output: attach the widget tree so the plugin writes the builder
    # post-meta (guarded by the setting; absent when disabled -> byte-identical payload).
    settings = settings or get_settings()
    if settings.content_elementor_enabled:
        raw_pack = _as_dict(row.get("source_pack"))
        design_profile = _as_dict(raw_pack.get("design_profile")) or None
        # Resolve the effective page blueprint (analyzed site > chosen template > page-type
        # default) and SLOT the draft's content into its sections, rendered as classic,
        # editable Elementor components - the hero copy + image + CTA land in the hero, the
        # FAQ pairs in an accordion, testimonials in cards, etc.
        specs = _resolve_row_blueprint(row)
        blueprint = [s.as_dict() for s in specs] or None
        payload["elementor_data"] = elementor_json(
            draft_md,
            design_profile,
            blueprint=blueprint,
            cta=payload.get("cta") or _derive_cta(row),
            testimonials=_str_list(raw_pack.get("testimonials")),
        )
        payload["elementor_edit_mode"] = "builder"
    return payload


def _publish_via_plugin(
    store: ContentStore,
    code: str,
    row: dict[str, Any],
    publisher: PluginPublisher,
    draft_md: str,
    title: str,
    settings: Settings | None = None,
) -> PublishOutcome:
    """Push the approved draft to the client's AIOS Publisher plugin + record the URLs.

    Raises :class:`WordPressPluginError` on a push failure (the caller SWALLOWS it and
    falls back to the legacy path - best-effort, never crashing the approve). On
    success the job goes ``publishing -> done`` with the WordPress permalink + edit
    link stored, and the reviewer is pointed at the WP draft to publish it there."""
    result = publisher.publish(_plugin_payload(row, draft_md, title, settings=settings))
    where = result.edit_url or result.url
    stage = "Pushed to WordPress (draft) — publish it on the site"
    if where:
        stage = f"{stage}: {where}"
    store.update(
        code,
        {
            "status": "done",
            "stage": stage,
            "wp_post_id": str(result.post_id),
            "wp_url": result.url,
            "wp_edit_url": result.edit_url,
        },
    )
    _emit_content_deliverable(row, artifact_key=None)  # pushed to WP; no local artifact
    logger.info(
        "content_pushed_to_plugin", code=code, wp_post_id=result.post_id, status=result.status
    )
    return PublishOutcome(
        code, "done", "published", reason="pushed to WordPress plugin (draft)",
        wp_post_id=result.post_id, url=result.url,
    )


def publish_content_job(
    store: ContentStore,
    providers: ContentProviders | None,
    code: str,
    *,
    settings: Settings,
    artifacts: ContentArtifactStore | None = None,
    resolve_wp: Any = _resolve_wp_from_vault,
    resolve_wp_plugin: Any = _resolve_wp_plugin,
    resolve_client_wp: Any = _resolve_wp_connection,
) -> PublishOutcome:
    """Publish an APPROVED content job (the approve path moves it to ``publishing``
    first, then calls this).

    Re-checks the QA hard gate: a sub-threshold draft (``qa_score.passed`` not True)
    is NEVER published - it raises :class:`PublishBlocked`. A passing ``WordPress`` job
    is pushed, in order: (1) to the client's AIOS Publisher PLUGIN as a DRAFT (the
    host-independent push - its own endpoint + shared key, bypassing header-stripping
    / app-passwords) when a plugin target is configured, recording the returned
    permalink + edit link; else (2) to WordPress over the REST app-password (per-site,
    from the vault, idempotent via ``wp_post_id``); else (3) rendered to PDF + Markdown
    in the traversal-safe artifact store. A ``PDF/Markdown`` target renders directly;
    then ``publishing -> done``. A plugin push failure falls through to (2)/(3) - a
    push never crashes the approve. No credential degrades to artifact-only (a marker,
    never a crash). Idempotent: a redelivered ``done`` job is a no-op.
    """
    row = store.load(code)
    if row is None:
        logger.warning("content_publish_missing", code=code)
        return PublishOutcome(code, "failed", "failed", reason="not found")

    status = str(row.get("status") or "")
    if status == "done":
        return PublishOutcome(code, "done", "noop", reason="already published (idempotent)")
    if status != "publishing":
        # The approve path is responsible for needs_review -> publishing; anything
        # else here is not ready to publish.
        return PublishOutcome(code, status, "noop", reason="not in the publishing state")

    # QA is ADVISORY, not a gate (product decision): the automated QA scorecard is
    # still computed at drafting and surfaced for the reviewer, but it NO LONGER blocks
    # publish. The HUMAN review gate (a lead approving needs_review -> publishing) is the
    # quality gate now - "QA approves it after reading". This keeps a job from taking a
    # long, token-heavy rewrite loop just to clear an automated threshold; generation
    # aims for top quality up front and a person signs off. The qa_score is logged for
    # visibility.
    qa = _as_dict(row.get("qa_score"))
    logger.info(
        "content_publish_qa_advisory",
        code=code,
        qa_passed=qa.get("passed"),
        qa_total=qa.get("weighted_total"),
    )

    draft_md = str(row.get("draft_md") or "")
    title = _extract_title(draft_md) or str(row.get("topic") or code)
    target = str(row.get("target") or "WordPress")

    try:
        if target == "WordPress":
            return _publish_wordpress(
                store, code, row, draft_md, title, settings, artifacts,
                resolve_wp, resolve_wp_plugin, resolve_client_wp,
            )
        return _publish_artifact(store, code, row, draft_md, title, artifacts, degraded=False)
    except PublishBlocked:
        raise
    except Exception as exc:  # never crash the publish; mark failed (publishing->failed is legal)
        logger.exception("content_publish_crashed", code=code)
        try:
            store.update(code, {"status": "failed", "stage": "Publish failed"})
        except Exception:
            logger.warning("content_publish_fail_write_failed", code=code)
        return PublishOutcome(code, "failed", "failed", reason=f"publish error: {exc!r}"[:_ERROR_MAX])


def _fire_indexing_best_effort(store: ContentStore, outcome: PublishOutcome) -> None:
    """Enqueue a search-engine indexing submission for a JUST-PUBLISHED page.

    Called from the PUBLISH TASK entry point (never the pure core, which unit tests
    drive directly without a broker). BEST-EFFORT + NEVER BLOCKS OR FAILS THE PUBLISH:
    only fires when the publish landed live with a real URL (a degraded artifact-only
    publish has no live URL, so nothing to index), and any enqueue error is swallowed.
    The client is resolved from the just-published row so the indexing ledger links to
    it; the indexing module owns its own key-gating + degrade behaviour.
    """
    if outcome.state != "published" or not outcome.url:
        return
    try:
        from app.modules.indexing.tasks import submit_urls_for_indexing

        row = store.load(outcome.code) or {}
        client_id = row.get("client_id")
        submit_urls_for_indexing.delay(
            [outcome.url], None, str(client_id) if client_id else None
        )
        logger.info("content_indexing_enqueued", code=outcome.code, url=outcome.url)
    except Exception:
        logger.warning("content_indexing_enqueue_failed", code=outcome.code)


def _publish_wordpress(
    store: ContentStore,
    code: str,
    row: dict[str, Any],
    draft_md: str,
    title: str,
    settings: Settings,
    artifacts: ContentArtifactStore | None,
    resolve_wp: Any,
    resolve_wp_plugin: Any,
    resolve_client_wp: Any,
) -> PublishOutcome:
    # --- PRIMARY: the per-client WordPress Connections registry (0058). One row per
    # client selects the site + auth method + sealed credential; publish the approved
    # draft through it - 'plugin' via the AIOS Publisher plugin, 'xmlrpc'/'app_password'
    # via the WordPressPublisher (XML-RPC / REST app-password). A configured-but-failing
    # connection is logged and FALLS THROUGH to the legacy single-site fallbacks below
    # (best-effort, never crashes the approve). No connection for this client leaves
    # the existing behavior completely unchanged.
    connection: ClientWpTarget | None = resolve_client_wp(row, settings)
    if connection is not None:
        try:
            if connection.method == "plugin" and connection.plugin is not None:
                return _publish_via_plugin(
                    store, code, row, connection.plugin, draft_md, title, settings
                )
            if connection.publisher is not None:
                return _publish_via_rest(
                    store, code, row, connection.site_url, connection.publisher, draft_md, title
                )
        except WordPressPluginError:
            logger.warning("content_connection_plugin_push_failed", code=code)
        except Exception:  # any REST / XML-RPC push failure -> fall through, never crash
            logger.warning("content_connection_push_failed", code=code, method=connection.method)

    # --- FALLBACK 1: the single-site AIOS Publisher PLUGIN (host-independent; bypasses
    # header-stripping + app-passwords), resolved from the vault/settings default.
    plugin: PluginPublisher | None = resolve_wp_plugin(row, settings)
    if plugin is not None:
        try:
            return _publish_via_plugin(store, code, row, plugin, draft_md, title, settings)
        except WordPressPluginError:
            logger.warning("content_plugin_push_failed", code=code)

    # --- FALLBACK 2: the REST app-password path resolved from the vault by domain.
    wp: WpTarget | None = resolve_wp(row, settings)
    if wp is None:
        # Credential-degraded: artifact-only + a degraded-publish marker (job still
        # completes so the client gets a deliverable), never a crash. This is the
        # clean "no connection configured for this client" skip the task describes.
        return _publish_artifact(store, code, row, draft_md, title, artifacts, degraded=True)
    return _publish_via_rest(store, code, row, wp.site_url, wp.publisher, draft_md, title)


def _publish_via_rest(
    store: ContentStore,
    code: str,
    row: dict[str, Any],
    site_url: str,
    publisher: WordPressPublisher,
    draft_md: str,
    title: str,
) -> PublishOutcome:
    """Publish (idempotent UPDATE-or-CREATE) through a ``WordPressPublisher`` - the REST
    app-password client OR the XML-RPC client, which share the Protocol - and record
    the live URL. Shared by the per-client connection path (xmlrpc / app_password) and
    the legacy vault path so both record the post identically."""
    existing = row.get("wp_post_id")
    wp_post_id = int(existing) if existing is not None and str(existing).isdigit() else None
    post = PostDraft(
        title=title,
        content=_shape_body_html(row, draft_md),
        # Push as a DRAFT: AIOS already ran the QA gate + human approval, but the final
        # go-live stays with the client in wp-admin (safer on a live site, and matches
        # the AIOS Publisher plugin path which also drafts). Flip to "publish" only if
        # the agency wants fully-automated go-live.
        status="draft",
        slug=_slug(title),
        wp_post_id=wp_post_id,  # set -> idempotent UPDATE, else CREATE
    )
    result: PublishResult = publisher.publish(site_url, post)
    # Surface the WordPress post URL on the wire-visible `stage` field so the dashboard's
    # Review surface can display it + offer an "open in WordPress" action (the wire
    # ContentJob has no dedicated url column; the stage label carries it). It lands as a
    # DRAFT in wp-admin for the client to publish.
    stage = f"Draft on WordPress: {result.url}" if result.url else "Draft on WordPress"
    store.update(code, {"status": "done", "stage": stage, "wp_post_id": str(result.post_id)})
    _emit_content_deliverable(row, artifact_key=None)  # pushed to WP; no local artifact
    logger.info("content_drafted_wp", code=code, wp_post_id=result.post_id)
    return PublishOutcome(
        code, "done", "published", reason="drafted to WordPress", wp_post_id=result.post_id, url=result.url
    )


def _publish_artifact(
    store: ContentStore,
    code: str,
    row: dict[str, Any],
    draft_md: str,
    title: str,
    artifacts: ContentArtifactStore | None,
    *,
    degraded: bool,
) -> PublishOutcome:
    pdf_key, md_key = _write_artifacts(artifacts, code, draft_md, title)
    if pdf_key is None and md_key is None:
        # No artifact store configured: hold at publishing (same-status marker) so a
        # configured re-run can complete it; never a crash.
        _safe_stage(store, code, "Publish held — no artifact store configured")
        return PublishOutcome(code, "publishing", "degraded", reason="no artifact store configured")
    stage = "Published (artifact-only — WordPress credentials pending)" if degraded else "Published"
    store.update(code, {"status": "done", "stage": stage, "pdf_path": pdf_key, "md_path": md_key})
    _emit_content_deliverable(row, artifact_key=pdf_key or md_key)
    reason = "degraded: artifact-only (no WordPress credentials)" if degraded else "rendered PDF/Markdown"
    logger.info("content_published_artifact", code=code, degraded=degraded)
    return PublishOutcome(
        code, "done", "degraded" if degraded else "published", reason=reason, pdf_key=pdf_key, md_key=md_key
    )


def _safe_stage(store: ContentStore, code: str, stage: str) -> None:
    """Best-effort same-status stage marker; must never raise out of publish."""
    try:
        store.update(code, {"stage": stage})
    except Exception:
        logger.warning("content_stage_write_failed", code=code)


def _emit_content_deliverable(row: dict[str, Any], *, artifact_key: str | None) -> None:
    """Publish a client deliverable for a PUBLISHED content job (best-effort; the
    emit itself never raises). An unlinked job (no client) is skipped.

    Also emails the CLIENT that new content is live (ADMIN/LEAD -> CLIENT). Both legs
    are best-effort + key-gated, so a keyless/failing provider or an unresolvable
    recipient degrades silently and can never fail the completed publish.
    """
    client_id = row.get("client_id")
    if not client_id:
        return
    source_id = row.get("id")
    emit_deliverable(
        client_id=str(client_id),
        client_name=row.get("client_name", ""),
        title=str(row.get("topic") or "Content"),
        kind="Content",
        requires="content_status",
        source_kind="content",
        source_id=str(source_id) if source_id else None,
        icon="article",
        artifact_key=artifact_key,
        media_type="application/pdf",
    )
    topic = str(row.get("topic") or "New content")
    who = str(row.get("client_name") or "there")
    subject = f"New content published: {topic}"
    text = (
        f"Hi {who}, a new piece of content, \"{topic}\", has been published. "
        "Sign in to your client portal to view it."
    )
    html = (
        f"<h2>New content published</h2>"
        f"<p>Hi {html_escape(who)}, a new piece of content, "
        f"\"{html_escape(topic)}\", has been published.</p>"
        "<p>Sign in to your client portal to view it.</p>"
    )
    email_client_sync(str(client_id), subject, html, text)


# --------------------------------------------------------------------------- #
# Celery entry points (thin; import the app after the pure core, per the template)
# --------------------------------------------------------------------------- #
from workers.celery_app import celery_app  # noqa: E402 - after the pure core, per the worker template


def _build_gate() -> MeteredCostGate:
    return MeteredCostGate(PostgresCostStore(), _NullCostCache())


@celery_app.task(name="run_content_job")  # type: ignore[untyped-decorator]  # celery's decorator is untyped
def run_content_job(code: str) -> dict[str, Any]:
    """Entry point: wire the privileged store + key-gated providers + the metered
    cost gate and run the pipeline. Never re-raises (the core owns failure)."""
    settings = get_settings()
    store = PrivilegedContentStore()
    providers = content_providers_from_settings(settings)  # None (degraded) if no writer key
    outcome = execute_content_job(store, providers, code, settings=settings, gate=_build_gate())
    return outcome.as_dict()


@celery_app.task(name="publish_content_job")  # type: ignore[untyped-decorator]  # celery's decorator is untyped
def publish_content_job_task(code: str) -> dict[str, Any]:
    """Entry point for an async publish: wire the concrete seams and publish. A QA
    block is caught + returned (never re-raised: acks_late would redeliver). The
    synchronous approve router instead calls ``publish_content_job`` directly and
    surfaces :class:`PublishBlocked` to the reviewer."""
    settings = get_settings()
    store = PrivilegedContentStore()
    providers = content_providers_from_settings(settings)
    artifacts = content_store_from_settings(settings)
    try:
        outcome = publish_content_job(store, providers, code, settings=settings, artifacts=artifacts)
    except PublishBlocked as blocked:
        return {"code": code, "status": "publishing", "state": "blocked", "blocked_by": blocked.blocked_by}
    # Fire-on-publish: best-effort submit the live URL to the search engines. Runs in the
    # worker (a broker is available here); never blocks or fails the completed publish.
    _fire_indexing_best_effort(store, outcome)
    return outcome.as_dict()
