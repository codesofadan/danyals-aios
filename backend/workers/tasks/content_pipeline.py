"""The doctrine engine, given the entry point it never had.

`app/services/content_pipeline/` is sixteen modules implementing the staged
pipeline: the Experience gate that refuses to draft a page nobody supplied
first-party facts for, the uniqueness gate that kills a template, the conversion
and voice passes, and a QA gate with an LLM judge. Measured 2026-08-29: it had
ONE production import anywhere in the codebase, of a single leaf helper, and
`run_page` had no non-test caller at all. It could not be reached from a route, a
task, or a service - so none of it had ever run outside a test.

This module is the entry point. It mirrors `workers/tasks/content.py`'s shape on
purpose - a pure, injectable core plus a thin Celery entry - so the two engines
are swappable and testable the same way.

WHAT IS DIFFERENT FROM v1, and why it matters to the screens built on top:

* **Nine stages that all actually fire.** v1 declares fourteen stage keys and
  streams six of them, so a UI stepper built from its list shows steps that never
  light up. Every stage here streams before it runs.
* **A halt is not a failure.** The Experience gate stops the page and asks the
  operator questions. That is the system working, so the job holds at `drafting`
  with the questions recorded - it is not retried, not alerted on, and never
  written as `failed`.
* **The QA judge is connected.** v1's judge seam exists and is never passed one.

WHAT THIS DOES NOT DO: switch the platform over. `settings.content_engine`
selects the engine and defaults to `v1`. Making an unverified engine the default
for a live agency would be exactly the "faking success" this codebase keeps
closing; the flip belongs after a real end-to-end run, which currently cannot be
done because the provider account has no credit.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import structlog

from app.config import Settings, get_settings
from app.services.content_guard import strip_dashes
from app.services.content_pipeline.assembly import build_page_stages
from app.services.content_pipeline.context import PipelineContext, StageResult
from app.services.content_pipeline.runner import (
    EDIT_STAGES,
    PAGE_STAGES,
    PipelineRun,
    run_page,
)
from app.services.content_pipeline.writer import DoctrineWriter
from app.services.content_research import GatedResearcher, SsrfSafePageFetcher
from app.services.cost_gate import CostGate
from app.services.notifications import notify_leads_sync
from workers.celery_app import celery_app
from workers.tasks.content import (
    ContentJobOutcome,
    ContentStore,
    PrivilegedContentStore,
    _build_gate,
    _ContentGatedWriter,
    _keyword_map,
)

logger = structlog.get_logger(__name__)

#: Display label per stage. Unlike v1's table, every entry here corresponds to a
#: stage that is bound and streamed, so a UI stepper built from this list has no
#: steps that can never light up.
STAGE_LABEL: dict[str, str] = {
    "guided_edit": "Applying your edits",
    "sme": "Experience",
    "research": "Research",
    "outline": "Outline",
    "draft": "Draft",
    "convert": "Conversion",
    "voice": "Voice",
    "grounding": "Fact-check",
    "claims": "Claims check",
    "images": "AI images",
    "title_meta": "Titles & meta",
    "schema_links": "Schema & links",
    "gate": "QA",
}


@dataclass
class PipelineDeps:
    """Everything the core needs that touches the world, injected in one object.

    A test binds doubles here and drives the whole job without a database, a
    provider or a queue - the same property the pipeline package itself has.
    """

    store: ContentStore
    planning: Any  # ContentPlanningStore | double (see assembly.PageStores)
    writer: DoctrineWriter | None = None
    researcher: Any | None = None
    #: The image seam. `None` (not a fake) when the provider bundle is absent, so the
    #: assembly OMITS the image stage rather than binding a placeholder generator.
    images: Any | None = None
    business: Any | None = None
    #: keyword -> a REAL url on the client's site, for internal links. Merged from the
    #: operator's `source_pack.internal_urls` and the client's published sibling pages.
    internal_urls: dict[str, str] | None = None
    #: The client's stored NAP row (`client_business_profiles`), or None.
    nap: dict[str, Any] | None = None
    page_url: str = ""
    model: str | None = None


def _stream(store: ContentStore, code: str, label: str) -> None:
    """Write the current stage onto the job row.

    Same-status writes only - the `content_jobs_guard_update` trigger allows the
    worker to stream within a status but never to drive the human transitions.
    """
    store.update(code, {"stage": label})


def _with_progress(
    stages: dict[str, Callable[[PipelineContext], StageResult]],
    store: ContentStore,
    code: str,
) -> dict[str, Callable[[PipelineContext], StageResult]]:
    """Wrap each stage so the row says what is running BEFORE it runs.

    Streaming after the fact would leave the longest stage - drafting, minutes of
    it - reported as the stage before it, which is precisely when someone is
    watching the screen to find out what is happening.
    """

    def wrap(name: str, fn: Callable[[PipelineContext], StageResult]) -> Callable[
        [PipelineContext], StageResult
    ]:
        def run(ctx: PipelineContext) -> StageResult:
            _stream(store, code, STAGE_LABEL.get(name, name.title()))
            return fn(ctx)

        return run

    return {name: wrap(name, fn) for name, fn in stages.items()}


def _ensure_engagement(deps: PipelineDeps, row: dict[str, Any]) -> str | None:
    """Give the job an engagement, creating one for the client if it has none.

    Without this the doctrine engine is unusable by construction: `run_sme` halts
    with "no engagement: the Experience dossier has nowhere to live", and NOTHING
    in the product writes `content_engagements` - the planning store's create
    methods have no non-test caller anywhere. So every v2 job would halt on its
    first stage forever, for a reason the operator could do nothing about.

    A job created without an engagement is a `single_page` shape: that is exactly
    what it is - one page, standing alone. When a batch flow later creates the
    engagement up front and stamps it on each job, this simply finds it already
    set and does nothing.

    Returns the engagement id, or None if the store could not provide one - in
    which case the SME gate halts, honestly, and says why.
    """
    existing = row.get("engagement_id")
    if existing:
        return str(existing)
    try:
        engagement = deps.planning.create_engagement(
            shape="single_page",
            client_id=str(row["client_id"]) if row.get("client_id") else None,
            client_name=str(row.get("client_name") or ""),
            name=str(row.get("topic") or row.get("code") or "Single page"),
            page_target=1,
        )
    except Exception as exc:
        logger.warning(
            "content_pipeline_engagement_failed",
            code=row.get("code"), error=type(exc).__name__,
        )
        return None
    engagement_id = str(getattr(engagement, "id", "") or "")
    if engagement_id:
        # Persist it so a re-run reuses the same dossier rather than opening a
        # second one and asking the operator the same questions again.
        deps.store.update(str(row.get("code") or ""), {"engagement_id": engagement_id})
    return engagement_id or None


def nap_facts(profile: dict[str, Any] | None) -> tuple[str, ...]:
    """The client's own NAP, as first-party facts the page is allowed to state.

    Found by running the engine: the conversion stage requires a tappable
    `tel:` link ("mobile local intent converts by phone") and the draft stage is
    told it may state NOTHING outside the supplied facts. The client's phone
    number was in neither place - `client_business_profiles` holds it, and no
    part of the pipeline ever read it. So the writer was asked to produce a
    click-to-call for a number it had not been given, leaving it a choice
    between inventing one and failing the check on every page forever.

    A stored NAP is first-party by definition: the operator entered it about
    their own business. Only non-empty fields travel, so a half-filled profile
    contributes what it has instead of asserting blanks.
    """
    if not profile:
        return ()
    parts: list[tuple[str, str]] = [
        ("phone", str(profile.get("phone") or "")),
        ("website", str(profile.get("website_url") or "")),
        ("address", ", ".join(
            x for x in (
                str(profile.get("address_line1") or ""),
                str(profile.get("city") or ""),
                str(profile.get("postal_code") or ""),
            ) if x
        )),
    ]
    return tuple(f"{k}: {v}" for k, v in parts if v)


def brief_facts(pack: dict[str, Any] | None) -> tuple[str, ...]:
    """The facts the OPERATOR supplied when they ordered the pages.

    The content flow asks for proof points, services, testimonials and anything
    only this client knows, and stores them on the job's `source_pack`. The v1
    generator reads them. This pipeline did not: it grounded a page solely on the
    Experience dossier, so everything typed on the brief screen was collected and
    silently ignored - and the QA gate then scored fact_grounding against facts
    the writer had never been given.
    """
    if not pack:
        return ()
    out: list[str] = []
    for key, label in (
        ("proof_points", "proof"),
        ("unique_data", "only we know"),
        ("services", "service"),
        ("testimonials", "testimonial"),
    ):
        values = pack.get(key) or []
        if isinstance(values, (list, tuple)):
            out.extend(f"{label}: {str(v).strip()}" for v in values if str(v).strip())
    return tuple(out)


def _sme_with_client_facts(
    stage: Callable[[PipelineContext], StageResult],
    profile: dict[str, Any] | None,
    pack: dict[str, Any] | None,
) -> Callable[[PipelineContext], StageResult]:
    """Add the client's NAP and the operator's brief to the Experience facts.

    Wrapped around `sme` rather than folded into it because that stage owns the
    Experience DOSSIER - a governed question-and-answer store - and neither a NAP
    nor a free-text brief is one of its slots. Appending after it runs keeps the
    dossier's contract intact while still giving the writer everything the
    operator actually supplied.

    Only on `ok`: a halted page is not being written, so there is nothing to
    ground, and a re-run collects them again anyway.
    """

    def run(ctx: PipelineContext) -> StageResult:
        result = stage(ctx)
        extra = (*nap_facts(profile), *brief_facts(pack))
        if extra and result.outcome == "ok":
            ctx.facts = (*ctx.facts, *extra)
        return result

    return run


def _context_for(row: dict[str, Any], settings: Settings) -> PipelineContext:
    """Build the pipeline's context from the job row.

    The target keyword is the one the operator actually chose. v1 fell back to the
    topic when `source_pack.primary_keyword` was absent, and that fallback is kept
    - a page with no keyword at all fails the research stage honestly rather than
    being drafted against a title.
    """
    pack = row.get("source_pack") or {}
    if not isinstance(pack, dict):
        pack = {}
    return PipelineContext(
        job_code=str(row.get("code") or ""),
        job_id=str(row["id"]) if row.get("id") else None,
        engagement_id=str(row["engagement_id"]) if row.get("engagement_id") else None,
        client_id=str(row["client_id"]) if row.get("client_id") else None,
        client_name=str(row.get("client_name") or ""),
        node_id=str(row["node_id"]) if row.get("node_id") else None,
        primary_keyword=str(pack.get("primary_keyword") or row.get("topic") or ""),
        page_type=str(row.get("page_type") or "service"),
        vertical=str(pack.get("vertical") or ""),
        framework=str(row.get("framework") or "PAS"),
        geo=str(pack.get("geo") or pack.get("city") or ""),
        # The context's own default (1200) stands unless the operator's brief asked
        # for a length; there is no platform-wide word-count setting to read.
        target_words=int(pack.get("target_words") or 1200),
    )


def _persist_halt(store: ContentStore, code: str, run: PipelineRun) -> ContentJobOutcome:
    """Record an Experience halt as the answerable question it is.

    Held at `drafting`, NOT failed: nothing broke, and a retry would ask the same
    unanswered questions again. The questions themselves were already persisted
    into the Experience dossier by the SME stage, so the row records only how many
    answers are outstanding; the screen reads the questions from the dossier.
    """
    sme = next((r for r in run.results if r.stage == "sme"), None)
    missing = list(sme.data.get("missing", [])) if sme else []
    label = (
        f"Waiting on your experience answers ({len(missing)} to go)"
        if missing else "Waiting on your experience answers"
    )
    store.update(code, {
        "stage": label,
        "cost": round(run.cost, 4),
        "experience_slots_missing": len(missing),
    })
    logger.info(
        "content_pipeline_halted", code=code, missing=len(missing),
        stage=run.stopped_at,
    )
    return ContentJobOutcome(
        code=code, status="drafting", state="deferred", stage=label,
        cost=round(run.cost, 4),
        reason=run.reason or "experience not collected",
    )


def _persist_hold(
    store: ContentStore, code: str, run: PipelineRun, reason: str
) -> ContentJobOutcome:
    """Hold a run that produced no page, instead of queueing nothing for review.

    Found by running a real job: a degraded outline stops the pipeline before a
    word is written, and this used to persist that as `needs_review` - putting an
    EMPTY draft in front of a lead and asking them to approve it. `needs_review`
    means a human has something to read. Held at `drafting` with the reason on the
    row: the operator can see why, and a re-run resumes rather than approving a
    blank page onto a client's site.
    """
    stage = f"Held — {reason}"
    store.update(code, {"stage": stage[:300], "cost": round(run.cost, 4)})
    logger.info("content_pipeline_held", code=code, stage=run.stopped_at, reason=reason)
    return ContentJobOutcome(
        code=code, status="drafting", state="degraded", stage=stage,
        cost=round(run.cost, 4), reason=reason,
    )


def _persist_success(
    store: ContentStore, code: str, ctx: PipelineContext, run: PipelineRun,
    *, applied_edit: bool = False,
) -> ContentJobOutcome:
    """Write everything the page produced and hand it to the human gate."""
    # The stages put their output at the TOP of StageResult.data - there is no
    # nested "qa" or "schema_type" key. Reading for ones that do not exist meant
    # the FIRST paid run wrote an empty qa_score and no JSON-LD onto a job whose
    # gate had actually scored it: the work was done and silently dropped on the
    # floor between the pipeline and the row.
    gate_result = ctx.result_for("gate")
    qa = dict(gate_result.data) if gate_result else {}
    if gate_result is not None and "notes" not in qa:
        # The gate's REASONS live on the StageResult's notes, not in its data, so a
        # straight copy of `data` produced a scorecard with scores and no
        # explanations - and the review screen, which read `qa.notes.length`
        # unguarded, threw a TypeError and took the whole QA tab down with it.
        qa["notes"] = list(gate_result.notes)
    schema_result = ctx.result_for("schema_links")
    schema_data = dict(schema_result.data) if schema_result else {}
    image_result = ctx.result_for("images")
    logger.info(
        "content_pipeline_persist",
        code=code,
        gate_keys=sorted(qa),
        schema_keys=sorted(schema_data),
        words=len(ctx.draft_md.split()),
    )
    degraded = run.outcome == "degraded"

    # Scored means a NUMBER came back - not merely that the gate returned a dict.
    # `qa` always carries the stage's notes now, so emptiness stopped being the
    # test the moment those were added. This mirrors the frontend's qaVerdict().
    unscored = qa.get("weighted_total") is None
    # THE DASH STRIP. v1 guaranteed a stored draft carried no em or en dash - the
    # single clearest machine-writing tell, and the one a client notices. This
    # engine dropped that guarantee, so its pages shipped with them. It is a pure,
    # deterministic, free string pass, so there is no reason it is not applied to
    # everything the reader will actually see: the body, the title and the meta.
    ctx.draft_md = strip_dashes(ctx.draft_md)
    ctx.title = strip_dashes(ctx.title)
    ctx.meta_description = strip_dashes(ctx.meta_description)

    fields: dict[str, Any] = {
        "status": "needs_review",
        "stage": (
            "Review — not re-scored after your edits" if unscored and applied_edit
            else "Review" + (f" — degraded ({run.reason})" if degraded else "")
        ),
        "cost": round(run.cost, 4),
        "words": len(ctx.draft_md.split()),
        "draft_md": ctx.draft_md,
        "outline": ctx.outline,
        "qa_score": qa,
    }
    if ctx.title or ctx.meta_description:
        outline = dict(ctx.outline)
        outline["meta"] = {"title": ctx.title, "description": ctx.meta_description}
        fields["outline"] = outline
    # The gate computes the entity picture on its way to a score; persist it so the
    # reviewer's entity tab has the coverage v1 always gave them.
    entities = qa.pop("entity_coverage", None)
    if isinstance(entities, dict) and entities:
        fields["entity_coverage"] = entities
    if schema_data.get("json_ld"):
        fields["json_ld"] = schema_data["json_ld"]
    # `primary_type` is what the schema stage calls the @type it settled on.
    if schema_data.get("primary_type"):
        fields["schema_type"] = schema_data["primary_type"]
    # THE KEYWORD MAP. The publish leg reads this column for the WordPress focus
    # keyword and the post's tags (workers/tasks/content.py:2006, :1953), and the
    # reviewer's keyword panel is `GET /content/jobs/{code}/keywords`, which maps
    # to it. v1 wrote it; this engine did not, so from the moment it became the
    # default every page it drafted pushed to WordPress with no focus keyword and
    # no tags, and showed the reviewer an empty keyword panel. The guard test did
    # not catch it because it seeds a v1-shaped row.
    #
    # Only when research actually ran: the EDIT path deliberately skips it, and the
    # map already stored from the first run is the right one. Overwriting it with
    # an empty object would strip the SEO fields off a page for being edited.
    brief = ctx.brief.get("research")
    if brief is not None and getattr(brief, "terms", None) is not None:
        try:
            fields["keyword_map"] = _keyword_map(brief)
        except Exception as exc:  # a shape change here must not lose the page
            logger.warning(
                "content_pipeline_keyword_map_failed", code=code, error=type(exc).__name__
            )
    if qa.get("weighted_total") is not None:
        fields["qa_weighted_total"] = qa["weighted_total"]
    else:
        # The gate produced no verdict this run - it degrades to nothing when it has
        # no research brief, which is exactly the case on the EDIT path, where
        # research deliberately does not re-run. Leaving the previous number in place
        # would show a score for a draft that no longer exists: measured on a real
        # edit, the scorecard emptied while the headline still read 84 from before
        # the change. Unscored has to look unscored.
        fields["qa_weighted_total"] = None
    # THE IMAGE COUNT. Written only when the stage actually ran: an absent result means
    # no image seam was bound at all, and on the EDIT path the stage is deliberately not
    # in EDIT_STAGES. Writing 0 in either case would overwrite a real count from the
    # first run with "we looked and there are none" - the distinction the job contract
    # turns on. A stage that RAN and produced nothing does write 0, honestly.
    if image_result is not None:
        fields["images"] = int(image_result.data.get("images", 0))

    # THE INTERNAL LINKS. Same rule: only when the stage produced a link plan. `links`
    # is the FULL plan (what the page should point at, which is what the reviewer's link
    # panel is for); `on_page` is how many of them are real hrefs in the body. Two
    # separate numbers so a plan can never be read as coverage.
    planned_links = schema_data.get("internal_links")
    if planned_links is not None:
        unresolved = int(schema_data.get("internal_links_unresolved", 0))
        links_field: dict[str, Any] = {
            "links": planned_links,
            "on_page": int(schema_data.get("internal_links_on_page", 0)),
            "unresolved": unresolved,
        }
        if unresolved:
            links_field["note"] = (
                f"{unresolved} of these have no url and are NOT in the page: no published "
                "sibling page is known for them. The anchor and target keyword are the "
                "plan; a url here would have been invented."
            )
        fields["internal_links"] = links_field

    if applied_edit:
        # Clear it, or the next run reads the same instruction and re-applies an
        # edit the lead already got - and the job becomes un-redeliverable.
        fields["edit_instruction"] = ""
    store.update(code, fields)

    # A page reaching the human gate has to TELL the humans. v1 notified the leads
    # who own the sign-off; this engine did not, so a draft could sit in the review
    # queue indefinitely with nobody aware it was waiting - a gate is only a gate if
    # someone knows to walk up to it.
    #
    # Best-effort, and the try/except is around the CALL, not the import: each
    # lead's notification prefs govern the email leg, and a mail provider being
    # down must never lose a page that is already written and stored.
    subject = ctx.title or ctx.primary_keyword or "A draft"
    try:
        notify_leads_sync(
            "content_review",
            f"Content ready for review: {subject}",
            f'"{subject}" for {ctx.client_name or "a client"} has been drafted and '
            "is awaiting review. Approve it or send it back from the content "
            "review queue.",
        )
    except Exception as exc:
        logger.warning(
            "content_pipeline_review_notice_failed", code=code, error=type(exc).__name__
        )

    logger.info(
        "content_pipeline_done", code=code, outcome=run.outcome,
        cost=round(run.cost, 4), llm_calls=run.llm_calls,
    )
    return ContentJobOutcome(
        code=code, status="needs_review",
        state="degraded" if degraded else "advanced",
        stage=str(fields["stage"]), cost=round(run.cost, 4),
        passed=bool(qa.get("passed")) if qa else None,
        reason=run.reason,
    )


def execute_pipeline_job(
    deps: PipelineDeps, code: str, *, settings: Settings, gate: CostGate,
    resume: bool = False,
) -> ContentJobOutcome:
    """Run one content job through the doctrine pipeline. Never raises.

    Never re-raising is not tidiness: `task_acks_late` would redeliver a raised
    task and the page would be written - and paid for - twice.

    ``resume`` is how a HALTED page comes back. The Experience gate holds the job
    at `drafting`, and the ordinary guard below refuses anything that is not
    `queued` - correctly, because that guard is what stops an at-least-once broker
    drafting the same page twice. Without an explicit resume the questionnaire
    would be a dead end: the operator answers every question and nothing happens,
    forever. Only the answer path sets this, and it is not a bypass - the SME gate
    still runs first and will halt again if the answers did not actually complete
    the dossier.
    """
    row = deps.store.load(code)
    if row is None:
        return ContentJobOutcome(code=code, status="unknown", state="noop",
                                 reason="no such job")
    status = str(row.get("status") or "")
    # A REVIEWER'S EDIT is a third legitimate way in, and it arrives looking exactly
    # like a redelivery: status `drafting`, not `queued`. Reproduced through the real
    # API before this existed - a lead clicked "Request edits", the instruction was
    # stored, the pipeline was re-enqueued, this returned `noop - job is drafting,
    # not queued`, and the page sat at "Edit requested" forever. The reviewer's only
    # feedback channel was a dead end.
    edit_instruction = str(row.get("edit_instruction") or "").strip()
    editing = bool(edit_instruction) and status == "drafting"
    resumable = (resume and status == "drafting") or editing
    if status != "queued" and not resumable:
        # A redelivery of an already-running or finished job is a no-op, not a
        # second run: the broker is at-least-once and drafting costs real money.
        return ContentJobOutcome(code=code, status=status, state="noop",
                                 reason=f"job is {status}, not queued")

    # A resume is already `drafting`; writing the status again would be a no-op
    # transition, and the guard trigger only needs the stage stream.
    first_label = STAGE_LABEL["guided_edit"] if editing else STAGE_LABEL["sme"]
    deps.store.update(
        code,
        {"stage": first_label} if resumable
        else {"status": "drafting", "stage": first_label},
    )
    row["engagement_id"] = _ensure_engagement(deps, row)
    ctx = _context_for(row, settings)
    if editing:
        # The edit works on the page the lead actually read, not a fresh one.
        ctx.draft_md = str(row.get("draft_md") or "")

    stages = build_page_stages(
        edit_instruction=edit_instruction,
        writer=deps.writer,
        researcher=deps.researcher,
        store=deps.planning,
        business=deps.business,
        page_url=deps.page_url,
        model=deps.model,
        images=deps.images,
        # The image stage spends OUTSIDE the metered writer seam, so it needs the same
        # gate this job already runs on and the price table the gate commits against.
        cost_gate=gate,
        settings=settings,
        internal_urls=deps.internal_urls,
        allowed_contacts=_allowed_contacts(deps.nap, row),
        vendor_terms=_vendor_terms(deps.nap, row),
    )
    if "sme" in stages:
        pack = row.get("source_pack") if isinstance(row.get("source_pack"), dict) else None
        stages["sme"] = _sme_with_client_facts(stages["sme"], deps.nap, pack)
    try:
        run = run_page(
            ctx, _with_progress(stages, deps.store, code),
            order=EDIT_STAGES if editing else PAGE_STAGES,
        )
    except Exception as exc:  # a bug in the sequence itself, not a stage outcome
        logger.warning("content_pipeline_crashed", code=code, error=type(exc).__name__)
        deps.store.update(code, {"status": "failed", "stage": "Failed"})
        return ContentJobOutcome(code=code, status="failed", state="failed",
                                 stage="Failed", reason=type(exc).__name__)

    if run.halted:
        return _persist_halt(deps.store, code, run)
    if run.outcome == "failed":
        reason = run.reason or f"{run.stopped_at} failed"
        deps.store.update(code, {
            "status": "failed", "stage": "Failed", "cost": round(run.cost, 4),
        })
        logger.warning("content_pipeline_failed", code=code, stage=run.stopped_at)
        return ContentJobOutcome(code=code, status="failed", state="failed",
                                 stage="Failed", cost=round(run.cost, 4), reason=reason)
    if not ctx.draft_md.strip():
        # Nothing broke and nothing was refused - but no page came out, so there
        # is nothing for a human to read. Checked AFTER the failure branch on
        # purpose: a failed run must stay recorded as failed, not softened into
        # a hold because it also happened to produce no text.
        return _persist_hold(
            deps.store, code, run,
            run.reason or f"{run.stopped_at or 'the pipeline'} produced no draft",
        )
    return _persist_success(deps.store, code, ctx, run, applied_edit=editing)


@celery_app.task(name="run_content_pipeline_job")  # type: ignore[untyped-decorator]  # celery's decorator is untyped
def run_content_pipeline_job(code: str, resume: bool = False) -> dict[str, Any]:
    """Entry point: build the real seams and run the doctrine pipeline."""
    from app.modules.content_planning.repo import ContentPlanningStore
    from integrations.content_providers import content_providers_from_settings

    settings = get_settings()
    store = PrivilegedContentStore()
    gate = _build_gate()
    row = store.load(code) or {}
    client_id = str(row.get("client_id")) if row.get("client_id") else None

    providers = content_providers_from_settings(settings)
    writer: DoctrineWriter | None = None
    researcher: Any | None = None
    # The image seam stays None when the whole bundle is degraded. The bundle's own
    # `images` is `FakeImageGenerator` on a deploy with no IMAGE_GEN_API_KEY, and
    # `run_images` refuses that generator by identity - so a keyless deployment gets a
    # stage that runs, produces nothing, charges nothing, and names the missing key.
    images: Any | None = None
    if providers is not None:
        writer = DoctrineWriter(
            _ContentGatedWriter(
                providers.writer, gate, settings=settings,
                client_id=client_id, job_id=code,
            ),
            settings=settings,
            model=providers.model_writer,
            job_id=code,
        )
        # Same construction v1 uses: the SERP seam plus an SSRF-safe fetcher for
        # the top-10 teardown, both behind the cost gate.
        researcher = GatedResearcher(
            providers.serp,
            SsrfSafePageFetcher(),
            gate,
            settings=settings,
            client_id=client_id,
            job_id=code,
        )
        images = providers.images

    profile = _load_nap(client_id)
    deps = PipelineDeps(
        store=store,
        planning=ContentPlanningStore(),
        writer=writer,
        researcher=researcher,
        images=images,
        business=_business_for(row, profile),
        nap=profile,
        page_url=str((profile or {}).get("website_url") or ""),
        internal_urls=_internal_url_registry(row, client_id),
        model=providers.model_writer if providers else None,
    )
    return execute_pipeline_job(
        deps, code, settings=settings, gate=gate, resume=resume
    ).as_dict()


def published_sibling_urls(rows: list[dict[str, Any]]) -> dict[str, str]:
    """keyword -> url for the client's pages that are ACTUALLY on the live site.

    THE ONLY HONEST SOURCE OF AN INTERNAL-LINK URL in this platform. `content_jobs.wp_url`
    is written at the publish push (migration 0057) and is the post's real permalink, so
    a row that has one is a page a reader can reach. A row WITHOUT one is a draft, and a
    draft's slug is not a URL - guessing `/{slug}` (which v1 does) puts a 404 in a
    client's own body copy, which is worse than the missing link.

    Split out from the query so the mapping rule is testable without a database.
    """
    out: dict[str, str] = {}
    seen: set[str] = set()
    for row in rows:
        url = str(row.get("wp_url") or "").strip()
        keyword = str(row.get("kw") or "").strip()
        # First writer wins: the query orders newest-first, so the most recently
        # published page for a keyword is the one linked, not a stale permalink.
        if url and keyword and keyword.lower() not in seen:
            seen.add(keyword.lower())
            out[keyword] = url
    return out


def _internal_url_registry(row: dict[str, Any], client_id: str | None) -> dict[str, str]:
    """The operator's own keyword->URL registry, plus the client's published pages.

    The operator's registry wins on a collision: they typed a specific URL for that
    keyword, which is a stronger statement than "some job pushed a post about it".
    """
    registry = dict(_published_sibling_urls(client_id, exclude_code=str(row.get("code") or "")))
    pack = row.get("source_pack")
    supplied = pack.get("internal_urls") if isinstance(pack, dict) else None
    if isinstance(supplied, dict):
        registry.update({
            str(k).strip(): str(v).strip()
            for k, v in supplied.items()
            if str(k).strip() and str(v).strip()
        })
    return registry


def _published_sibling_urls(client_id: str | None, *, exclude_code: str) -> dict[str, str]:
    """Read this client's published pages on the privileged connection.

    Same shape and the same reasoning as `_load_nap`: the worker has no user identity,
    so it cannot use an RLS-scoped repo. A failure here loses INTERNAL LINKS, never the
    page - the stage then records every cluster target as unresolved and says so.
    """
    if not client_id:
        return {}
    try:
        from app.db.database import privileged_connection

        with privileged_connection() as cur:
            cur.execute(
                "select keyword_map->>'primary' as kw, wp_url "
                "from public.content_jobs "
                "where client_id = %s and wp_url is not null and wp_url <> '' "
                "and code <> %s "
                "order by updated_at desc limit 100",
                (client_id, exclude_code),
            )
            rows = [dict(r) for r in cur.fetchall()]
        return published_sibling_urls(rows)
    except Exception as exc:
        logger.warning("content_pipeline_siblings_unavailable", error=type(exc).__name__)
        return {}



def _allowed_contacts(nap: dict[str, Any] | None, row: dict[str, Any]) -> frozenset[str]:
    """Every contact detail the operator actually supplied.

    Anything ELSE that looks like an email, phone number or domain in the finished
    page is treated as invented and removed. That check has no false positives worth
    the name and one very expensive failure mode: a page that reads perfectly and
    routes every lead it generates to an address nobody owns. Measured on a real run
    - the drafts offered "hello@xegents.com", which does not exist.
    """
    values: list[str] = []
    for key in ("phone", "email", "website", "site_url", "domain"):
        value = (nap or {}).get(key)
        if isinstance(value, str) and value.strip():
            values.append(value.strip())
    pack = row.get("source_pack")
    if isinstance(pack, dict):
        site = pack.get("siteDomain") or pack.get("site_domain")
        if isinstance(site, str) and site.strip():
            values.append(site.strip())
    return frozenset(values)


def _vendor_terms(nap: dict[str, Any] | None, row: dict[str, Any]) -> tuple[str, ...]:
    """The names this page might use for the client in the third person.

    The compliance trigger only fires when the vendor is the SUBJECT, which keeps
    "clinics must comply with HIPAA" from being flagged. A page that says "Acme
    Dental is HIPAA compliant" names the client instead of saying "we", so the
    client's own names have to be part of that gate or the check is blind to it.
    """
    terms: list[str] = []
    for source in (nap or {}, row):
        for key in ("business_name", "client_name", "name"):
            value = source.get(key)
            if isinstance(value, str) and value.strip():
                terms.append(value.strip())
    return tuple(dict.fromkeys(terms))

def _load_nap(client_id: str | None) -> dict[str, Any] | None:
    """Read the client's NAP on the privileged connection.

    The worker has no user identity, so it cannot use the RLS-scoped clients
    repo; it reads the one row directly. A missing profile is not an error - the
    add-client wizard allows skipping it - so this returns None and the page is
    written without a phone number rather than failing.
    """
    if not client_id:
        return None
    try:
        from app.db.database import privileged_connection

        with privileged_connection() as cur:
            cur.execute(
                "select * from public.client_business_profiles "
                "where client_id = %s limit 1",
                (client_id,),
            )
            row = cur.fetchone()
        return dict(row) if row else None
    except Exception as exc:
        logger.warning("content_pipeline_nap_unavailable", error=type(exc).__name__)
        return None


def _business_for(row: dict[str, Any], profile: dict[str, Any] | None) -> Any:
    """The Business entity the JSON-LD is built from.

    Built from the client's stored NAP so the markup names a real phone and a
    real area. schema_links validates every marked-up value against the visible
    text, so a wrong value here does not silently ship - it fails the page.
    """
    from app.services.content_schema import Business

    profile = profile or {}
    return Business(
        name=str(profile.get("client_name") or row.get("client_name") or ""),
        url=str(profile.get("website_url") or ""),
        telephone=str(profile.get("phone") or ""),
    )
