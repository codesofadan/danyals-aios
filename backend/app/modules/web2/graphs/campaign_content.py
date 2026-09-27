"""``campaign_content`` - the Web 2.0 property graph.

``06-AI-STACK.md`` §2 names this graph and its justification: *fan-out per platform with
per-platform constraint solving*. ``M05`` §5 draws its shape. This module builds it over
the SAME pure stage functions ``app.services.web2_pipeline`` already uses, so the graph
path and the linear path produce identical articles - and the graph adds the one thing a
straight-line function cannot have.

WHAT THE CHECKPOINT ACTUALLY BUYS, IN THIS MODULE, CONCRETELY.
Drafting one property is not one model call. ``content_generator.generate()`` fans out a
dozen ``summarize()`` calls - one per section, one for the direct-answer block, one per
photo brief - and ``web2_pipeline.run_write`` only writes to the database at the very end.
So a worker that dies three-quarters of the way through property 19 of a thirty-property
campaign has spent real money on nine model calls and has nothing to show for it: the row
is still ``draft``, the retry starts from the first section, and the client is billed
twice for the same paragraphs. With a checkpoint after every node, the retry resumes at
the node that failed.

THE APPROVAL GATE IS NOW AN INTERRUPT, NOT A STATUS POLL.
v1 parks a property at ``needs_review`` and waits for an endpoint to notice. That works,
and it is also why the gate's logic is duplicated in two places (the write worker and the
approval endpoint each run the similarity check, for reasons the code explains at length).
``interrupt()`` makes the park a position IN the graph: the graph stops, its state is
checkpointed, the review queue holds the item, and the operator's decision is injected
back at exactly the point it left. ``M05`` §5 requires a manager to approve the plan and
the first post per platform; this is the mechanism that carries that decision.

WHAT THIS DELIBERATELY DOES NOT CHANGE (yet).
The similarity gate, the anchor rules, the pacing caps, the eligibility rules and every
publisher adapter are called, not rewritten. They are the parts of v1 that were measured
rather than assumed, and a rewrite would put that evidence at risk for no gain. The
per-platform SHAPING node is the one genuinely new stage, and it is additive: with no
router configured it falls back to a deterministic note and the article is exactly what
v1 would have produced.

DEGRADES WITHOUT LANGGRAPH. ``build()`` raises :class:`GraphUnavailable` when the optional
``[graph]`` extra is absent; :func:`run_property` catches that and runs the linear
pipeline instead. A deployment that has not installed the extra keeps publishing.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.config import Settings
from app.logging_setup import get_logger
from app.modules.web2.note_composer import compose as compose_note
from app.modules.web2.platform_spec import ARTICLE_WORD_TARGET, spec_for
from app.modules.web2.seo_fields import derive as derive_seo
from app.platform.ai import graph as graph_runtime
from app.platform.ai.graph import GraphUnavailable
from app.platform.ai.prompts import get as get_prompt
from app.platform.ai.router import (
    CostBlockedError,
    ModelRequest,
    ModelRouter,
    RouterSummarizer,
)
from app.platform.ai.tiers import TaskTier
from app.services.content_generator import DEFAULT_TUNING, GeneratorTuning
from app.services.content_research import ContentSpendBlocked
from app.services.web2_pipeline import (
    Web2Client,
    Web2SimilarityChecker,
    Web2Store,
    check_similarity,
    plan,
    split_title_and_body,
    write,
)
from integrations.web2_publishers import DRAFT_ONLY_PLATFORMS

logger = get_logger("modules.web2.graphs.campaign_content")

MODULE = "web2"
#: The money dial the drafting stage meters against - the branded article IS content
#: drafting, and metering it anywhere else would hide Web 2.0 spend from the content
#: budget an operator actually watches. Mirrors ``web2_pipeline._WRITE_FEATURE``.
WRITE_FEATURE = "content"

#: What a Web 2.0 property is: a tight authority post, not a pillar page. Same figure
#: ``web2_pipeline`` uses, imported as a number rather than re-derived so the two paths
#: cannot drift into producing different lengths.
WEB2_WORD_TARGET = 900

_NEEDS_MARKER = "[NEEDS:"


class PropertyState(BaseModel):
    """The graph's contract (§2: "state is a Pydantic model, never a loose dict").

    Every field is something a node READ or PRODUCED, so a checkpoint is a complete
    account of where a property got to. Nothing here is a handle to a live object -
    checkpointed state must survive a process restart, which a DB connection or a
    publisher client would not.
    """

    # --- identity, set at entry -------------------------------------------------
    web2_id: str
    client_id: str | None = None
    client_name: str = ""
    platform: str = ""
    topic: str = ""
    anchor: str = ""
    target_url: str = ""
    page_type: str = "blog"
    framework: str = "Auto"
    geo: str | None = None

    # --- produced by nodes ------------------------------------------------------
    #: The per-platform constraint note the drafting stage writes against (the
    #: "constraint solving" §2 names). Empty when the shaping node degraded.
    platform_shape: str = ""
    #: The measured post shape this platform takes (`platform_spec.PostShape`). Decides
    #: WHICH composer runs - an article generator that clamps to a 600-word floor cannot
    #: produce a 300-character note, so this is a routing fact, not a label.
    post_shape: str = "article"
    #: Words the writer was actually given, derived from the platform's measured ceiling.
    word_target: int = ARTICLE_WORD_TARGET
    body_md: str = ""
    word_count: int = 0
    publishable: bool = False
    needs: list[str] = Field(default_factory=list)
    similarity_verdict: str = ""
    similarity_code: str = ""

    # --- SEO metadata (REQ-W2-008). EMPTY means "this platform has no such field",
    # never "we skipped it" - `seo_fields` only derives what the adapter transmits.
    slug: str = ""
    meta_description: str = ""
    canonical_url: str = ""
    tags: list[str] = Field(default_factory=list)

    # --- the human decision, injected at the interrupt --------------------------
    approved: bool | None = None
    review_note: str = ""

    # --- terminal facts ---------------------------------------------------------
    status: Literal[
        "draft", "needs_review", "publishing", "published", "blocked", "failed",
        "rejected", "unchanged", "error", "skipped",
    ] = "draft"
    error: str = ""
    spent_usd: float = 0.0
    #: Tier capabilities the backend could not honour. Non-empty means this article was
    #: produced under a weaker configuration than its tier specifies - recorded so the
    #: fact reaches the review screen instead of being inferable only from a log line.
    degraded: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


# --------------------------------------------------------------------------- #
# Nodes. Every one is pure over its inputs EXCEPT the designated IO nodes, which
# are the only place a provider or the database is touched (§2).
# --------------------------------------------------------------------------- #
#: Injected seam: what the capability matrix says about one platform, as its raw
#: catalogue row. A callable rather than a dict so the worker can read Postgres and a
#: test can hand over a literal - the same shape the similarity checker already uses,
#: and the reason this graph has no database import of its own.
CapabilityLookup = Callable[[str], "dict[str, Any] | None"]


def make_nodes(
    *,
    store: Web2Store,
    router: ModelRouter | None,
    settings: Settings,
    similarity: Web2SimilarityChecker | None = None,
    client: Web2Client | None = None,
    capabilities: CapabilityLookup | None = None,
    tuning: GeneratorTuning = DEFAULT_TUNING,
) -> dict[str, Callable[[PropertyState], dict[str, Any]]]:
    """Build the node functions bound to this run's seams.

    A factory rather than module-level functions because a node must not reach for a
    global to find its database or its router - that is precisely what makes a node
    untestable, and §2 makes testability with fakes the reason nodes are pure at all.
    """
    lookup: CapabilityLookup = capabilities or (lambda _platform: None)

    def load(state: PropertyState) -> dict[str, Any]:
        """IO NODE. Read the placement row and confirm it is still ours to draft.

        The status check is what makes a redelivered job a no-op rather than a second
        paid draft - the same guard ``run_write`` opens with, kept because at-least-once
        delivery is a property of the broker, not of this graph.
        """
        row = store.load_web2(state.web2_id)
        if row is None:
            return {"status": "error", "error": "not found"}
        status = str(row.get("status") or "")
        if status != "draft":
            return {"status": "unchanged", "error": f"status={status}"}
        return {
            "client_id": _client_id(row),
            "client_name": str(row.get("client_name") or ""),
            "platform": str(row.get("platform") or ""),
            "topic": str(row.get("topic") or "") or str(row.get("anchor") or ""),
            "anchor": str(row.get("anchor") or ""),
            "target_url": str(row.get("target_url") or ""),
            "page_type": str(row.get("page_type") or "blog"),
            "framework": str(row.get("framework") or "Auto"),
            "status": "draft",
        }

    def shape(state: PropertyState) -> dict[str, Any]:
        """Solve this platform's constraints into a note the writer drafts against.

        THE NEW STAGE, and the one §2 says justifies a graph for this module. v1 drafts
        one 900-word blog article and posts the same shape to a developer community, a
        microblog and a paste site - which is both worse writing and a clearer footprint
        than the similarity gate can see, because every article is individually fine.

        Degrades to the deterministic capability summary when no router is configured, so
        a keyless deployment produces exactly what v1 produces rather than failing.
        """
        spec = spec_for(state.platform)
        # The adapter-derived spec LEADS, and the catalogue row annotates it. That order
        # is the point: the spec states what the publishing code will actually do to this
        # body (truncate it at 300 characters, render it to plain text), which is a
        # harder fact than anything the catalogue records, and it is the fact that decides
        # whether the draft survives contact with the platform.
        caps = spec.describe() + " " + capability_note(state.platform, lookup(state.platform))
        base = {
            "platform_shape": caps,
            "post_shape": spec.shape,
            "word_target": spec.word_target,
        }
        if router is None or not router.configured:
            return {**base,
                    "notes": [*state.notes, "platform shape: measured spec only (no router)"]}
        prompt_spec = get_prompt("web2/platform_shape")
        try:
            result = router.complete(
                ModelRequest(
                    task=TaskTier.STRUCTURED,
                    prompt=prompt_spec.render(platform=state.platform, capabilities=caps),
                    expected_output_tokens=300,
                    module=MODULE,
                    client_id=state.client_id,
                    client_name=state.client_name,
                    job_id=state.web2_id,
                    job_type=MODULE,
                    feature_key=WRITE_FEATURE,
                    prompt_id=prompt_spec.id,
                )
            )
        except CostBlockedError as blocked:
            # A shaping block must not stop the property: the article can still be
            # written against the capability matrix, and refusing to draft over a
            # 300-token call would spend the operator's budget ceiling on nothing.
            return {
                **base,
                "notes": [*state.notes, f"platform shape degraded: {blocked.outcome}"],
            }
        return {
            **base,
            # The model's note is APPENDED to the measured spec, never substituted for it.
            # A model asked to describe a platform can be wrong about it; the character
            # ceiling read off the adapter cannot.
            "platform_shape": (caps + " " + result.text.strip()).strip(),
            "spent_usd": round(state.spent_usd + result.cost_usd, 6),
            "degraded": sorted({*state.degraded, *result.degraded}),
        }

    def draft(state: PropertyState) -> dict[str, Any]:
        """IO NODE. Draft the article through the router, then place the ONE backlink.

        Calls ``web2_pipeline.write`` unchanged - the generator, the framework, the
        ``[NEEDS:]`` discipline and the contextual link placement are all v1's, and all
        measured. What changed is the WRITER it is handed: a :class:`RouterSummarizer`,
        so each of the generator's dozen internal calls is tier-routed, gated, priced
        with cache accounting and traced.
        """
        if router is None or not router.configured:
            # PERSIST the degrade before returning. The graph ends here (there is no
            # article to review), so `persist_draft` never runs - and without this write
            # the row would sit at `draft` while the outcome reported `needs_review`.
            # That gap is the exact class of dishonesty the job contract exists to stop:
            # the operator's board would show a property still queued for drafting, and
            # nothing would ever say that the reason is a missing key. The linear path
            # writes it here too (`run_write`'s `writer is None` branch); both paths must
            # leave the same row behind.
            error = "degraded: content writer unconfigured"
            store.update_web2(state.web2_id, {"status": "needs_review", "error": error})
            logger.info("web2_graph_write_degraded", web2_id=state.web2_id, reason="no_writer")
            return {
                "status": "needs_review",
                "error": error,
                "body_md": "",
                "notes": [*state.notes, "no model backend: nothing was drafted"],
            }
        # ROUTE BY SHAPE. This is the branch the whole phase turns on: the article
        # generator clamps its word budget to a 600-word FLOOR, so asking it for a
        # 300-character Bluesky note returns 600 words and the adapter publishes
        # `text[:300]` - a blog post cut mid-sentence with the backlink sliced off the
        # end. A note is a different artifact, not a smaller article.
        if state.post_shape in ("note", "snippet", "profile"):
            return _compose_note(state)

        the_plan = plan(
            client or Web2Client(client_id=state.client_id, name=state.client_name),
            state.platform,
            state.anchor,
            state.target_url,
            topic=state.topic or None,
            page_type=state.page_type,
            framework=state.framework,
            word_target=state.word_target,
        )
        writer = RouterSummarizer(
            router,
            task=TaskTier.DRAFTING,
            module=MODULE,
            feature_key=WRITE_FEATURE,
            client_id=state.client_id,
            client_name=state.client_name,
            job_id=state.web2_id,
            job_type=MODULE,
        )
        try:
            article = write(
                the_plan,
                writer=writer,
                source_pack=client.source_pack if client else None,
                context=client.context if client else None,
                tuning=tuning,
            )
        except ContentSpendBlocked as blocked:
            # Nothing is persisted: the row stays at `draft` for a clean retry, never a
            # half-billed half-written article. Same reasoning as `run_write`'s handler.
            return {
                "status": "blocked",
                "error": f"spend_blocked:{blocked.outcome}",
                "spent_usd": round(state.spent_usd + writer.spent, 6),
            }
        return {
            "body_md": article.body_md,
            "word_count": article.word_count,
            "publishable": article.publishable,
            "needs": list(article.needs),
            "spent_usd": round(state.spent_usd + writer.spent, 6),
            "degraded": sorted({*state.degraded, *writer.degraded}),
            "notes": [*state.notes, *article.notes],
        }

    def _compose_note(state: PropertyState) -> dict[str, Any]:
        """Compose a short-form placement and shape it into the pipeline's own fields.

        The note lands in ``body_md`` like any other draft, because everything downstream
        - the similarity gate, the review screen, the publish stage - reads that one
        field. What differs is how it was made and how big it is, and both are recorded.
        """
        spec = spec_for(state.platform)
        note = compose_note(
            spec=spec,
            topic=state.topic or state.anchor,
            client_name=state.client_name,
            geo=state.geo,
            source_pack=client.source_pack if client else None,
            router=router,
            module=MODULE,
            feature_key=WRITE_FEATURE,
            client_id=state.client_id,
            job_id=state.web2_id,
        )
        notes = [*state.notes, *note.notes]
        if note.trimmed:
            notes.append(
                f"the composed note overran {spec.platform}'s budget and was trimmed at a "
                "sentence boundary"
            )
        return {
            "body_md": note.text,
            "word_count": len(note.text.split()),
            "publishable": note.publishable,
            "needs": [] if note.publishable else ["the note body"],
            "spent_usd": round(state.spent_usd + note.spent_usd, 6),
            "degraded": sorted({*state.degraded, *note.degraded}),
            "notes": notes,
        }

    def seo(state: PropertyState) -> dict[str, Any]:
        """Derive the SEO fields this platform will actually transmit (REQ-W2-008).

        Runs AFTER the body exists, because the meta description is written from the
        page's own opening rather than from the brief - a description derived from the
        plan describes what we meant to write, which is not always what got written.

        Only the fields the measured spec says the adapter sends are produced. Deriving a
        meta description for Bluesky is not harmlessly redundant: it is a metered model
        call producing a string nothing will ever read, on every placement, forever.
        """
        spec = spec_for(state.platform)
        title, _ = split_title_and_body(state.body_md)
        fields = derive_seo(
            spec=spec,
            title=title or state.topic,
            body_md=state.body_md,
            topic=state.topic,
            client_name=state.client_name,
            candidate_tags=tuple(state.tags) or _tag_candidates(state),
            router=router,
            module=MODULE,
            feature_key=WRITE_FEATURE,
            client_id=state.client_id,
            job_id=state.web2_id,
        )
        return {
            "slug": fields.slug,
            "meta_description": fields.meta_description,
            "canonical_url": fields.canonical_url,
            "tags": list(fields.tags),
            "spent_usd": round(state.spent_usd + fields.spent_usd, 6),
            "notes": [*state.notes, *fields.notes],
        }

    def gate(state: PropertyState) -> dict[str, Any]:
        """IO NODE. Score this draft against the corpus and record the verdict.

        Fail-open here, fail-closed at approval - the asymmetry v1 established and
        explains: a block and a pass both land at review, so refusing to draft because
        the corpus is unreachable stops all work to prevent nothing. What must never
        happen is a placement going live unchecked, and that is the approval node's job.
        """
        row = store.load_web2(state.web2_id) or {}
        outcome = check_similarity(
            similarity,
            web2_id=state.web2_id,
            row=row,
            body_md=state.body_md,
            client=client or Web2Client(client_id=state.client_id, name=state.client_name),
        )
        gap = "" if state.publishable else "draft has unresolved [NEEDS:] gaps"
        # BOTH findings are kept, similarity first. v1 records the reason this order is
        # load-bearing: the approval guard matches on the `sim_` PREFIX, so a duplicate
        # that also happened to be gappy would otherwise carry no similarity code at all.
        error = "; ".join(part for part in (outcome.code, gap) if part)
        return {
            "similarity_verdict": outcome.verdict,
            "similarity_code": outcome.code,
            "status": "needs_review",
            "error": error,
        }

    def persist_draft(state: PropertyState) -> dict[str, Any]:
        """IO NODE. Park the drafted property at the review gate.

        The graph will interrupt immediately after this. The row is written FIRST so the
        review queue has something to show even if this process dies before the
        checkpoint lands - the database is what the operator's screen reads, and a
        checkpoint nobody can see is not a review queue.
        """
        row: dict[str, Any] = {
            "status": "needs_review", "body_md": state.body_md, "error": state.error[:500],
        }
        # Only non-empty values are written, so a platform WITHOUT a field stores NULL
        # rather than an empty string. NULL says "this platform has no meta description";
        # '' would say "we produced an empty one", and an operator reading a thin report
        # needs to tell a correct blank from a defective one.
        for key, value in (
            ("slug", state.slug), ("meta_description", state.meta_description),
            ("canonical_url", state.canonical_url),
        ):
            if value:
                row[key] = value
        if state.tags:
            row["tags"] = list(state.tags)
        store.update_web2(state.web2_id, row)
        logger.info(
            "web2_graph_drafted",
            web2_id=state.web2_id, platform=state.platform, words=state.word_count,
            publishable=state.publishable, similarity=state.similarity_verdict,
            spent=state.spent_usd, degraded=state.degraded,
        )
        return {}

    def await_approval(state: PropertyState) -> dict[str, Any]:
        """THE HUMAN GATE. Park the graph until a lead decides.

        ``interrupt()`` checkpoints everything above and stops. The value handed out is
        the review payload the operator sees; the value passed back to
        ``graph_runtime.run(..., resume=...)`` is their decision. Resuming re-enters this
        node with the decision as the interrupt's return value, which is why the node
        reads as if the call simply returned.
        """
        from langgraph.types import interrupt

        decision = interrupt(
            {
                "web2_id": state.web2_id,
                "platform": state.platform,
                "topic": state.topic,
                "anchor": state.anchor,
                "target_url": state.target_url,
                "word_count": state.word_count,
                "publishable": state.publishable,
                "needs": state.needs,
                "similarity_verdict": state.similarity_verdict,
                "similarity_code": state.similarity_code,
                "degraded": state.degraded,
                "estimated_spend_usd": state.spent_usd,
            }
        )
        if isinstance(decision, dict):
            return {
                "approved": bool(decision.get("approved")),
                "review_note": str(decision.get("note") or ""),
            }
        return {"approved": bool(decision), "review_note": ""}

    def rejected(state: PropertyState) -> dict[str, Any]:
        """IO NODE. Record a lead's refusal. Terminal - nothing is published."""
        store.update_web2(
            state.web2_id,
            {"status": "rejected", "error": (state.review_note or "rejected at review")[:500]},
        )
        logger.info("web2_graph_rejected", web2_id=state.web2_id, note=state.review_note[:120])
        return {"status": "rejected"}

    def queue_publish(state: PropertyState) -> dict[str, Any]:
        """IO NODE. Hand an APPROVED property to the publish path.

        The graph stops here on purpose. Publishing is metered against a different money
        dial, is rate-limited per platform, and is subject to the pacing rules - all of
        which belong to a job, not to a reasoning step. The graph's contribution ends
        when the approved article exists and a human has said yes.
        """
        store.update_web2(state.web2_id, {"status": "publishing", "error": ""})
        logger.info("web2_graph_approved", web2_id=state.web2_id, platform=state.platform)
        return {"status": "publishing"}

    return {
        "load": load,
        "shape": shape,
        "draft": draft,
        "seo": seo,
        "gate": gate,
        "persist_draft": persist_draft,
        "await_approval": await_approval,
        "rejected": rejected,
        "queue_publish": queue_publish,
    }


# --------------------------------------------------------------------------- #
# Graph assembly
# --------------------------------------------------------------------------- #
def _after_load(state: PropertyState) -> str:
    """Stop before spending anything if this row is not ours to draft."""
    return "shape" if state.status == "draft" else "__end__"


def _after_draft(state: PropertyState) -> str:
    """A cost-gate block or an unconfigured writer ends the run; nothing to review."""
    if state.status in ("blocked", "error"):
        return "__end__"
    if not state.body_md:
        return "__end__"
    return "seo"


def _after_approval(state: PropertyState) -> str:
    return "queue_publish" if state.approved else "rejected"


def build(
    *,
    store: Web2Store,
    router: ModelRouter | None,
    settings: Settings,
    similarity: Web2SimilarityChecker | None = None,
    client: Web2Client | None = None,
    capabilities: CapabilityLookup | None = None,
    checkpointer: Any = None,
    tuning: GeneratorTuning = DEFAULT_TUNING,
) -> Any:
    """Compile the ``campaign_content`` graph.

    Raises :class:`GraphUnavailable` when the optional ``[graph]`` extra is absent, which
    :func:`run_property` translates into "use the linear pipeline".
    """
    try:
        from langgraph.graph import END, START, StateGraph
    except ImportError as exc:
        raise GraphUnavailable(
            "langgraph not installed (pip install -e '.[graph]')"
        ) from exc

    nodes = make_nodes(
        store=store, router=router, settings=settings,
        similarity=similarity, client=client, capabilities=capabilities, tuning=tuning,
    )
    builder = StateGraph(PropertyState)
    for name, fn in nodes.items():
        builder.add_node(name, graph_runtime.node(f"web2.{name}", fn))

    builder.add_edge(START, "load")
    builder.add_conditional_edges("load", _after_load, {"shape": "shape", "__end__": END})
    builder.add_edge("shape", "draft")
    builder.add_conditional_edges("draft", _after_draft, {"seo": "seo", "__end__": END})
    builder.add_edge("seo", "gate")
    builder.add_edge("gate", "persist_draft")
    builder.add_edge("persist_draft", "await_approval")
    builder.add_conditional_edges(
        "await_approval", _after_approval,
        {"queue_publish": "queue_publish", "rejected": "rejected"},
    )
    builder.add_edge("queue_publish", END)
    builder.add_edge("rejected", END)
    return builder.compile(checkpointer=checkpointer)


def capability_note(platform: str, row: dict[str, Any] | None) -> str:
    """Render one platform's MEASURED capability row into a note a writer can act on.

    The matrix is dated evidence gathered per platform (migration 0135 and the catalogue
    rows it annotates), and it lives in Postgres. Describing a platform from memory here
    would create a second source that drifts from the one an operator can actually check,
    so this formats what the row SAYS and nothing else.

    ``row`` is None when the catalogue has no entry - which happens, and which must read
    as "nothing is known" rather than as a set of confident defaults. A writer told
    nothing produces a plain article; a writer told an invented convention produces an
    article that is wrong in a way nobody will trace back to here.
    """
    if not row:
        return (
            f"{platform}: no measured capability row. Write a plain, self-contained "
            "article with no platform-specific formatting, and assume nothing about "
            "headings, tags or media support."
        )
    interesting = (
        "mechanism", "topical_scope", "authority_tier", "terms_position",
        "media_support", "link_verifiable", "adapter_status", "ownership_tier",
    )
    parts = [
        f"{key}: {row[key]}"
        for key in interesting
        if row.get(key) not in (None, "", [])
    ]
    if platform in DRAFT_ONLY_PLATFORMS:
        parts.append("publishes as a DRAFT only: a human pushes it live")
    if not parts:
        return f"{platform}: a catalogue row exists but records no capability facts."
    return f"{platform}: " + "; ".join(parts)


def _client_id(row: dict[str, Any]) -> str | None:
    value = row.get("client_id")
    return str(value) if value else None


# --------------------------------------------------------------------------- #
# Entry points: draft one property, and resume it with a human decision
# --------------------------------------------------------------------------- #
def thread_for(web2_id: str) -> str:
    """The graph thread this property's run lives on.

    Derived from the property id alone, which is also what the write job's idempotency
    key is built from - so a redelivered job attaches to the SAME graph run rather than
    starting a second one beside it. That equality is the whole reason "retry" means the
    same thing at the job layer and the graph layer.
    """
    return graph_runtime.thread_id_for("web2", "campaign_content", web2_id)


def draft_property(
    web2_id: str,
    *,
    store: Web2Store,
    router: ModelRouter | None,
    settings: Settings,
    similarity: Web2SimilarityChecker | None = None,
    client: Web2Client | None = None,
    capabilities: CapabilityLookup | None = None,
    checkpointer: Any = None,
    tuning: GeneratorTuning = DEFAULT_TUNING,
) -> dict[str, Any]:
    """Run one property from ``draft`` to the review interrupt. Returns the final state.

    The run PARKS at ``await_approval`` - that is success, not an incomplete run. Check
    :func:`app.platform.ai.graph.parked` on the result: parked means the article exists,
    the row is at ``needs_review`` and a human owes a decision. A result that is NOT
    parked ended early, and ``status`` says why (``unchanged`` on a redelivery,
    ``blocked`` on a cost gate, ``error`` on a missing row).

    Raises :class:`GraphUnavailable` when the ``[graph]`` extra is absent. The caller
    decides what that means - the worker runs the linear pipeline instead.

    ``checkpointer`` lets a caller supply one it already holds. That is not an
    optimisation: an in-memory saver lives and dies with its context manager, so a test
    (or a single process driving draft-then-approve) MUST pass the same one to both calls
    or the second finds no thread. In production the saver is Postgres-backed and shared
    through the database, so the default - open one per call - is correct there.
    """
    with _saver(settings, checkpointer) as saver:
        compiled = build(
            store=store, router=router, settings=settings, similarity=similarity,
            client=client, capabilities=capabilities, checkpointer=saver, tuning=tuning,
        )
        return graph_runtime.run(
            compiled,
            {"web2_id": web2_id},
            thread_id=thread_for(web2_id),
            module=MODULE,
            client_id=client.client_id if client else None,
            job_id=web2_id,
        )


def resume_with_decision(
    web2_id: str,
    *,
    approved: bool,
    note: str = "",
    store: Web2Store,
    router: ModelRouter | None,
    settings: Settings,
    similarity: Web2SimilarityChecker | None = None,
    client: Web2Client | None = None,
    capabilities: CapabilityLookup | None = None,
    checkpointer: Any = None,
    tuning: GeneratorTuning = DEFAULT_TUNING,
) -> dict[str, Any]:
    """Inject a lead's approve/reject into a parked run and let it finish.

    This is the approval endpoint's half of the human-in-the-loop contract. It resumes
    the EXISTING thread from its checkpoint, so the decision lands at exactly the point
    the graph left off - with the draft, the similarity verdict and the spend already in
    state, none of it re-derived and none of it re-paid for.

    Requires a DURABLE checkpointer to work across processes: the endpoint and the
    worker are different processes, so an in-memory saver would find no thread to resume
    and the run would restart from ``load`` (which, finding the row at ``needs_review``
    rather than ``draft``, returns ``unchanged`` - safe, but not a resumption). See
    :func:`app.platform.ai.graph.runtime_state`, whose ``durable`` flag says which you
    have. When the thread is gone, this raises
    :class:`app.platform.ai.graph.GraphThreadMissing` rather than restarting the graph -
    a restart would re-draft and re-bill the article instead of applying the decision.
    """
    with _saver(settings, checkpointer) as saver:
        compiled = build(
            store=store, router=router, settings=settings, similarity=similarity,
            client=client, capabilities=capabilities, checkpointer=saver, tuning=tuning,
        )
        return graph_runtime.run(
            compiled,
            {},
            thread_id=thread_for(web2_id),
            module=MODULE,
            client_id=client.client_id if client else None,
            job_id=web2_id,
            resume={"approved": approved, "note": note},
        )


@contextmanager
def _saver(settings: Settings, provided: Any) -> Iterator[Any]:
    """Yield the caller's checkpointer, or open one for the duration of this call."""
    if provided is not None:
        yield provided
        return
    with graph_runtime.checkpointer(settings) as opened:
        yield opened


def _tag_candidates(state: PropertyState) -> tuple[str, ...]:
    """Topical tags for a placement, from what the row already knows.

    The topic and the anchor, not a model call: a tag is a label, and a platform that
    caps them at four (dev.to) does not reward invention. `seo_fields` normalises and
    caps them against the platform's measured limit.
    """
    parts = [part for part in (state.topic, state.anchor) if part and part.strip()]
    return tuple(dict.fromkeys(parts))
