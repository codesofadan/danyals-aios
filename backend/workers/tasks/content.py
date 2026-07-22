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
  budget + daily spend-stop; a breach DEFERS the job (held, retried later) rather
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

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol

from psycopg import sql
from psycopg.types.json import Jsonb

from app.config import Settings, get_settings
from app.db.database import privileged_connection
from app.logging_setup import get_logger
from app.schemas.content import schema_for
from app.services.content_artifacts import (
    ContentArtifactStore,
    content_store_from_settings,
)
from app.services.content_generator import (
    NAP,
    GeneratedContent,
    GenerationContext,
    GeneratorTuning,
    LocalProfile,
    SourcePack,
    generate,
)
from app.services.content_qa import Judge, QaScore, score
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
from integrations.content_providers import ContentProviders, content_providers_from_settings
from integrations.images import ImageGenerator
from integrations.llm import LLMResult, Summarizer
from integrations.wordpress import (
    PostDraft,
    PublishResult,
    WordPressPublisher,
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
        self._gate.commit(ctx, ctx.estimated_cost)
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

    def as_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "status": self.status,
            "state": self.state,
            "stage": self.stage,
            "cost": self.cost,
            "passed": self.passed,
            "reason": self.reason,
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


def _tuning() -> GeneratorTuning:
    return GeneratorTuning()  # doctrine defaults; a later chunk may map from Settings


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
    *,
    client_id: str | None,
    code: str,
) -> int:
    """Generate the planned hero/section images, gated on the content dial. A dial
    block stops image generation (not fatal); a provider error skips that image."""
    count = 0
    for item in content.images_plan:
        ctx = GateContext(
            feature_key=_CONTENT_FEATURE,
            client_id=client_id,
            provider=_IMAGE_PROVIDER,
            estimated_cost=0.0,  # negligible vs drafting; folds into the content dial
            job_id=code,
            job_type=_JOB_TYPE,
            cache_key=None,
        )
        decision = gate.evaluate(ctx)
        if not decision.allowed:
            break
        try:
            images.generate(item.prompt, item.alt)
            gate.commit(ctx, 0.0)
            count += 1
        except Exception:  # one bad image never fails the job
            logger.warning("content_image_failed", code=code)
    return count


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
    # the client cap / daily spend-stop (or the content dial is off/byhand).
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
            settings=settings, gate=gate, fetcher=fetcher, judge=judge, client_id=client_id,
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
    client_id: str | None,
) -> ContentJobOutcome:
    """The happy-path composition (research -> ... -> qa -> needs_review)."""
    keyword = str(row.get("topic") or "")
    source_pack = _source_pack_from_row(row)
    geo = _geo_for(row, source_pack)

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
        tuning=_tuning(),
    )
    stream("titles_meta")

    # --- schema (build + validate the JSON-LD against the visible draft)
    stream("schema")
    page_type, business, page, visible = _schema_inputs(row, brief, source_pack, content)
    json_ld = build_json_ld(page_type, business, page)
    schema_result: ValidationResult = validate_json_ld(json_ld, visible)
    schema_type = schema_result.primary_type or schema_for(page_type)

    # --- images (bounded, gated) -> assemble
    stream("images")
    image_count = _generate_images(providers.images, content, gate, client_id=client_id, code=code)
    stream("assemble")

    # --- qa (the 14-dimension scorecard; attached so the reviewer sees it)
    qa = score(content, brief, schema_result, source_pack, judge=judge)

    # --- drafting -> needs_review (STOP at the human gate; carry every rich column)
    final_cost = round(getattr(gate, "spent", 0.0), 2)
    store.update(
        code,
        {
            "status": "needs_review",
            "stage": _STAGE_LABEL["review"],
            "cost": final_cost,
            "words": content.word_count,
            "images": image_count,
            "schema_type": schema_type,
            "draft_md": content.draft_md,
            "keyword_map": _keyword_map(brief),
            "outline": _outline(content, brief),
            "entity_coverage": _entity_coverage(content, brief),
            "qa_score": _qa_dict(qa),
            "json_ld": json_ld,
            "internal_links": _internal_links(content),
        },
    )
    logger.info("content_job_needs_review", code=code, passed=qa.passed, weighted_total=qa.weighted_total)
    return ContentJobOutcome(
        code, "needs_review", "advanced", stage=_STAGE_LABEL["review"], cost=final_cost, passed=qa.passed
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


def _md_inline(text: str) -> str:
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


def publish_content_job(
    store: ContentStore,
    providers: ContentProviders | None,
    code: str,
    *,
    settings: Settings,
    artifacts: ContentArtifactStore | None = None,
    resolve_wp: Any = _resolve_wp_from_vault,
) -> PublishOutcome:
    """Publish an APPROVED content job (the approve path moves it to ``publishing``
    first, then calls this).

    Re-checks the QA hard gate: a sub-threshold draft (``qa_score.passed`` not True)
    is NEVER published - it raises :class:`PublishBlocked`. A passing job is pushed
    to WordPress (per-site app-password from the vault, idempotent via ``wp_post_id``
    - UPDATE if set else CREATE) when ``target=WordPress``, or rendered to PDF +
    Markdown in the traversal-safe artifact store when ``target=PDF/Markdown``; then
    ``publishing -> done``. No WP credential degrades to artifact-only (a marker,
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

    # --- The QA HARD GATE re-check: never publish a sub-threshold draft. ---
    qa = _as_dict(row.get("qa_score"))
    if qa.get("passed") is not True:
        blocked_by = [str(b) for b in qa.get("blocked_by") or []]
        # Leave the job at publishing with a clear marker (same-status write) and
        # signal the caller; the draft is NOT published.
        _safe_stage(store, code, "Blocked — QA gate below publish threshold")
        logger.info("content_publish_blocked", code=code, blocked_by=blocked_by)
        raise PublishBlocked(code, blocked_by)

    draft_md = str(row.get("draft_md") or "")
    title = _extract_title(draft_md) or str(row.get("topic") or code)
    target = str(row.get("target") or "WordPress")

    try:
        if target == "WordPress":
            return _publish_wordpress(store, code, row, draft_md, title, settings, artifacts, resolve_wp)
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


def _publish_wordpress(
    store: ContentStore,
    code: str,
    row: dict[str, Any],
    draft_md: str,
    title: str,
    settings: Settings,
    artifacts: ContentArtifactStore | None,
    resolve_wp: Any,
) -> PublishOutcome:
    wp: WpTarget | None = resolve_wp(row, settings)
    if wp is None:
        # Credential-degraded: artifact-only + a degraded-publish marker (job still
        # completes so the client gets a deliverable), never a crash.
        return _publish_artifact(store, code, row, draft_md, title, artifacts, degraded=True)

    existing = row.get("wp_post_id")
    wp_post_id = int(existing) if existing is not None and str(existing).isdigit() else None
    post = PostDraft(
        title=title,
        content=md_to_html(draft_md),
        status="publish",
        slug=_slug(title),
        wp_post_id=wp_post_id,  # set -> idempotent UPDATE, else CREATE
    )
    result: PublishResult = wp.publisher.publish(wp.site_url, post)
    store.update(code, {"status": "done", "stage": "Published", "wp_post_id": str(result.post_id)})
    _emit_content_deliverable(row, artifact_key=None)  # published to WP; no local artifact
    logger.info("content_published_wp", code=code, wp_post_id=result.post_id)
    return PublishOutcome(
        code, "done", "published", reason="published to WordPress", wp_post_id=result.post_id, url=result.url
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
    emit itself never raises). An unlinked job (no client) is skipped."""
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
    return outcome.as_dict()
