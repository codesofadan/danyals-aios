"""7B-3: the Web 2.0 PUBLISH pipeline - plan -> write -> HUMAN REVIEW GATE ->
publish -> verify -> track.

A Web 2.0 property is an on-topic, branded authority article posted to a client-owned
WordPress.com / Blogger / Tumblr blog, carrying ONE editorial backlink to the client's
page. It is white-hat authority work, NEVER link spam - which is exactly why the
article is NEVER auto-published: a lead must APPROVE it at the ``needs_review`` gate.

The pipeline mirrors the content module's purity (``content_generator`` /
``context_compactor``): the core stages are pure of Celery + DB + network, taking
injected seams (a ``Summarizer`` writer, a ``Web2Publisher``, a ``CostGate``, a
``Web2Store``). Given the deterministic fakes the whole flow runs live with zero keys.

Stages:

* ``plan(client, platform, anchor, target_url)`` -> a :class:`Web2Plan` (a lightweight,
  deterministic research brief seeded from the anchor - a branded property does not
  need a live SERP teardown to rank, it needs to be on-topic and carry the link).
* ``write(plan, writer=...)`` -> a :class:`Web2Article` via the ranking-grade content
  generator (multi-framework, grounded, ``[NEEDS:]`` instead of hallucination), with
  the branded backlink appended. The article is NOT published here.
* the HUMAN QUALITY GATE: the write stage parks the row at ``needs_review``; a lead
  approves (router) before anything goes live.
* ``publish(...)`` via ``integrations.web2_publishers`` (post-approval only).
* ``verify_live_and_indexable(...)`` -> the ``verified`` verdict (a real live/indexable
  placement vs a held draft, e.g. Medium is draft-only).
* ``track(...)`` -> the single write-back to ``web2_properties``.

R5 (cost pre-check): the paid WRITE (Claude drafting) is gated on the ``content``
money-dial and the paid PUBLISH on the ``backlinks`` (off-page) dial BEFORE the call -
a block HOLDS the placement (never spends, never crashes). Key/OAuth-gated: with no
writer the draft degrades to a ``[NEEDS:]`` placeholder held at review; with no
publisher the approved article HOLDS at review until the per-account OAuth (vault) lands.

The two orchestration entry points (:func:`run_write` / :func:`run_publish`) NEVER
raise - with ``task_acks_late`` a raised exception would redeliver the job and re-run
the (paid) stage, so they always mark a terminal state and return a small outcome.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Any, Literal, Protocol

from app.config import Settings
from app.logging_setup import get_logger
from app.schemas.content import auto_framework
from app.services.content_generator import (
    DEFAULT_TUNING,
    GenerationContext,
    GeneratorTuning,
    SourcePack,
    generate,
)
from app.services.content_research import (
    FormatDecision,
    ResearchBrief,
    Teardown,
    TermSet,
    TopicalCluster,
    assess_winnability,
    build_registry,
)
from app.services.cost_gate import CostGate, GateContext, GateDecision
from integrations.llm import Summarizer
from integrations.web2_publishers import (
    DRAFT_ONLY_PLATFORMS,
    WEB2_PLATFORMS,
    Web2Post,
    Web2Publisher,
    Web2PublishResult,
)

logger = get_logger("services.web2_pipeline")

_ERROR_MAX = 500  # cap the stored error/reason string; server-side only

# The money-dial features + cost provider labels the two paid stages gate/log against.
_WRITE_FEATURE = "content"  # the branded article is content drafting (Claude)
_WRITE_PROVIDER = "Anthropic"
_PUBLISH_FEATURE = "backlinks"  # publishing an off-page property rides the off-page dial
_PUBLISH_PROVIDER = "web2"
_JOB_TYPE = "backlinks"

# A branded Web 2.0 article is a tight authority post, not a pillar page.
_WEB2_WORD_TARGET = 900

# A drafted article with an unresolved grounding gap must never auto-publish.
_NEEDS_MARKER = "[NEEDS:"

Web2Stage = Literal["write", "publish"]
Web2State = Literal[
    "needs_review", "published", "blocked", "failed", "rejected", "unchanged", "error", "skipped"
]


# --------------------------------------------------------------------------- #
# Injected inputs / outputs
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class Web2Client:
    """The client a property is built for: the display ``name`` + optional grounding
    (a ``source_pack`` of source-of-truth facts, fresh ``context``, ``geo``, and Moz
    ``da``). With no source pack the generator degrades to ``[NEEDS:]`` gaps (the draft
    then HOLDS at review for a human to fill), never hallucinating."""

    client_id: str | None
    name: str
    source_pack: SourcePack | None = None
    context: GenerationContext | None = None
    geo: str | None = None
    da: float | None = None


@dataclass(frozen=True)
class Web2Plan:
    """A planned placement: the target platform + the anchor -> target_url backlink, the
    resolved page type / framework, and the deterministic research ``brief`` the writer
    grounds the article on."""

    client_id: str | None
    client_name: str
    platform: str
    anchor: str
    target_url: str
    topic: str
    page_type: str
    framework: str
    geo: str | None
    brief: ResearchBrief


@dataclass(frozen=True)
class Web2Article:
    """A drafted (NOT yet published) article: its ``title`` + ``body_md`` (the branded
    backlink appended), the ``word_count``, whether it is ``publishable`` (no unresolved
    ``[NEEDS:]`` gap), the recorded ``needs`` gaps, and generator ``notes``."""

    plan: Web2Plan
    title: str
    body_md: str
    word_count: int
    publishable: bool
    needs: list[str]
    notes: list[str]


@dataclass(frozen=True)
class Web2Outcome:
    """The verdict of one orchestration run (a small, JSON-serializable value)."""

    web2_id: str
    stage: Web2Stage
    state: Web2State
    degraded: bool = False
    post_url: str = ""
    verified: bool = False
    reason: str = ""
    needs: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "web2_id": self.web2_id,
            "stage": self.stage,
            "state": self.state,
            "degraded": self.degraded,
            "post_url": self.post_url,
            "verified": self.verified,
            "reason": self.reason,
            "needs": list(self.needs),
        }


class Web2Store(Protocol):
    """The persistence surface the orchestration needs (a privileged, service_role
    store in the worker; a fake dict store in tests)."""

    def load_web2(self, web2_id: str) -> dict[str, Any] | None: ...
    def update_web2(self, web2_id: str, fields: dict[str, Any]) -> None: ...


# --------------------------------------------------------------------------- #
# Stage 1: plan
# --------------------------------------------------------------------------- #
def plan(
    client: Web2Client,
    platform: str,
    anchor: str,
    target_url: str,
    *,
    topic: str | None = None,
    page_type: str = "blog",
    framework: str = "Auto",
) -> Web2Plan:
    """Plan a placement. The article ``topic`` defaults to the ``anchor`` (the branded
    property is about the anchor's subject); the research ``brief`` is a deterministic,
    network-free seed (a branded authority post is on-topic + carries the link - it does
    not chase a SERP teardown). ``framework`` ``"Auto"`` resolves per page type."""
    resolved_topic = (topic or anchor).strip() or anchor
    brief = _seed_brief(resolved_topic, client.geo, client.da)
    resolved_fw = auto_framework(page_type) if framework == "Auto" else framework
    return Web2Plan(
        client_id=client.client_id,
        client_name=client.name,
        platform=platform,
        anchor=anchor,
        target_url=target_url,
        topic=resolved_topic,
        page_type=page_type,
        framework=resolved_fw,
        geo=client.geo,
        brief=brief,
    )


def _seed_brief(keyword: str, geo: str | None, da: float | None) -> ResearchBrief:
    """A minimal, deterministic :class:`ResearchBrief` seeded from the topic keyword -
    no SERP call. Enough structure for the generator to build a grounded, on-topic
    article; ``low_confidence`` is set (no live SERP research backed it)."""
    primary = keyword.strip() or "the topic"
    questions = [f"What is {primary}?", f"How does {primary} help?", f"Why choose {primary}?"]
    terms = TermSet(primary=primary, secondary=[], semantic_entities=[], questions=questions)
    cluster = TopicalCluster(pillar=primary, primary=primary, supporting=[])
    teardown = Teardown(
        pages=[],
        table_stakes_entities=[],
        differentiator_entities=[],
        heading_blueprint=[],
        word_count_target=_WEB2_WORD_TARGET,
        schema_types=[],
        media_target=1,
        freshness_expected=False,
        fetched=0,
        refused=[],
    )
    return ResearchBrief(
        keyword=primary,
        geo=geo,
        serp_date=_utcnow().date().isoformat(),
        intent="informational",
        intent_confidence=0.3,
        terms=terms,
        cluster=cluster,
        content_format=FormatDecision(recommended="blog", confidence=0.4, signals={}),
        fanout=questions,
        winnability=assess_winnability([], da),
        teardown=teardown,
        registry=build_registry(terms, "informational"),
        low_confidence=True,
        degraded=False,
        notes=["web2 property brief: seeded from the anchor (no live SERP research)"],
    )


# --------------------------------------------------------------------------- #
# Stage 2: write (via the ranking-grade content generator)
# --------------------------------------------------------------------------- #
def write(
    plan: Web2Plan,
    *,
    writer: Summarizer,
    model: str = "content-writer",
    source_pack: SourcePack | None = None,
    context: GenerationContext | None = None,
    tuning: GeneratorTuning = DEFAULT_TUNING,
) -> Web2Article:
    """Draft the branded article via the content generator, then append the ONE
    editorial backlink (anchor -> target_url) that the property exists to carry.

    The generator injects all structure + facts and only PHRASES via the writer, so a
    missing fact becomes a ``[NEEDS:]`` gap, never a hallucination. ``publishable`` is
    False whenever any ``[NEEDS:]`` gap remains - such a draft HOLDS at the review gate
    until a human resolves it."""
    pack = source_pack or SourcePack(client_name=plan.client_name)
    generated = generate(
        plan.brief,
        pack,
        context,
        page_type=plan.page_type,
        framework=plan.framework,
        target="WordPress",
        writer=writer,
        model=model,
        tuning=tuning,
    )
    body_md = _append_backlink(generated.draft_md, plan.anchor, plan.target_url)
    needs = list(generated.needs)
    publishable = _NEEDS_MARKER not in body_md
    return Web2Article(
        plan=plan,
        title=generated.title,
        body_md=body_md,
        word_count=generated.word_count,
        publishable=publishable,
        needs=needs,
        notes=list(generated.notes),
    )


def _append_backlink(draft_md: str, anchor: str, target_url: str) -> str:
    """Append the branded backlink section - the whole point of a Web 2.0 property is
    one on-topic editorial link back to the client's page."""
    anchor = anchor.strip() or "our services"
    if not target_url.strip():
        return draft_md.rstrip() + "\n"
    return (
        draft_md.rstrip()
        + f"\n\n## More about {anchor}\n\n"
        + f"Learn more about [{anchor}]({target_url}).\n"
    )


def _degraded_article(plan: Web2Plan, reason: str) -> Web2Article:
    """A held placeholder draft when the writer is unavailable (no key). Produces a
    ``[NEEDS:]`` skeleton (never fake prose) that HOLDS at the review gate - the gap is
    visible to a lead, never silently published."""
    title = plan.topic[:1].upper() + plan.topic[1:] if plan.topic else "Draft"
    body_md = (
        f"# {title}\n\n"
        f"{_NEEDS_MARKER} article copy - the content writer (Anthropic) is not "
        "configured; a lead should draft or re-run once the key lands]\n"
    )
    body_md = _append_backlink(body_md, plan.anchor, plan.target_url)
    return Web2Article(
        plan=plan,
        title=title,
        body_md=body_md,
        word_count=0,
        publishable=False,
        needs=["article copy (content writer unconfigured)"],
        notes=[reason],
    )


# --------------------------------------------------------------------------- #
# Stage 4: publish (post-approval) + Stage 5: verify
# --------------------------------------------------------------------------- #
def publish(
    publisher: Web2Publisher, platform: str, article_body_md: str, anchor: str, target_url: str,
    *, external_id: str | None = None, tags: tuple[str, ...] = (),
) -> Web2PublishResult:
    """Publish an approved article to ``platform`` via the injected publisher. The H1 is
    lifted as the post title; the remainder is rendered to HTML. Idempotent when
    ``external_id`` is supplied (the publisher UPDATES that post)."""
    title, rest_md = split_title_and_body(article_body_md)
    post = Web2Post(
        title=title or anchor,
        body_html=markdown_to_html(rest_md),
        anchor=anchor,
        target_url=target_url,
        slug=_slugify(title or anchor),
        tags=tags,
        external_id=external_id,
    )
    return publisher.publish(platform, post)


def verify_live_and_indexable(result: Web2PublishResult, platform: str) -> tuple[bool, str]:
    """The ``verified`` verdict: a placement is live + indexable only when it has a real
    post URL, is not a held draft, and the provider reports it published. A draft-only
    platform (Medium) is never 'verified' - it is placed as a draft for a human to push
    live, so it stays ``pending``."""
    if platform in DRAFT_ONLY_PLATFORMS or result.draft_only:
        return (False, "draft-only platform: pending manual publish")
    if not result.post_url:
        return (False, "no post URL returned")
    if not result.verified:
        return (False, "provider did not confirm the post is live")
    return (True, "live and indexable")


# --------------------------------------------------------------------------- #
# Stage 6: track (the single write-back)
# --------------------------------------------------------------------------- #
def track(
    store: Web2Store,
    web2_id: str,
    *,
    status: str,
    post_url: str | None = None,
    verified: str | None = None,
    external_id: str | None = None,
    published_at: date | None = None,
    body_md: str | None = None,
    error: str | None = None,
) -> None:
    """Write one placement's new state back to ``web2_properties`` (only the given
    fields; ``updated_at`` is trigger-maintained)."""
    fields: dict[str, Any] = {"status": status}
    if post_url is not None:
        fields["post_url"] = post_url
    if verified is not None:
        fields["verified"] = verified
    if external_id is not None:
        fields["external_id"] = external_id
    if published_at is not None:
        fields["published_at"] = published_at
    if body_md is not None:
        fields["body_md"] = body_md
    if error is not None:
        fields["error"] = error[:_ERROR_MAX]
    store.update_web2(web2_id, fields)


# --------------------------------------------------------------------------- #
# Orchestration: run_write (draft -> needs_review) - NEVER raises
# --------------------------------------------------------------------------- #
def run_write(
    store: Web2Store,
    web2_id: str,
    *,
    client: Web2Client,
    writer: Summarizer | None,
    gate: CostGate,
    settings: Settings,
    model: str = "content-writer",
    tuning: GeneratorTuning = DEFAULT_TUNING,
) -> Web2Outcome:
    """Draft one planned property and HOLD it at the review gate. Never raises.

    Idempotent: a row not in ``draft`` is left untouched (redelivery no-op). No writer
    (degraded) -> a placeholder held at ``needs_review``. A cost-gate block -> HOLD as
    ``blocked`` (no spend). Success -> the drafted article at ``needs_review`` (awaiting
    a lead's approval); the paid write is committed to the cost log only when it ran."""
    try:
        row = store.load_web2(web2_id)
        if row is None:
            logger.warning("web2_write_missing", web2_id=web2_id)
            return Web2Outcome(web2_id, "write", "error", reason="not found")
        status = str(row.get("status") or "")
        if status != "draft":
            # Idempotent redelivery: already drafted / published / rejected.
            return Web2Outcome(web2_id, "write", "unchanged", reason=f"status={status}")

        the_plan = plan(
            client,
            str(row.get("platform") or ""),
            str(row.get("anchor") or ""),
            str(row.get("target_url") or ""),
            topic=str(row.get("topic") or "") or None,
            page_type=str(row.get("page_type") or "blog"),
            framework=str(row.get("framework") or "Auto"),
        )

        if writer is None:
            article = _degraded_article(the_plan, "content providers unconfigured (no writer key)")
            track(
                store, web2_id, status="needs_review", body_md=article.body_md,
                error="degraded: content writer unconfigured",
            )
            logger.info("web2_write_degraded", web2_id=web2_id, reason="no_writer")
            return Web2Outcome(
                web2_id, "write", "needs_review", degraded=True,
                reason="providers_unconfigured", needs=article.needs,
            )

        # R5: cost pre-check BEFORE the paid draft.
        ctx = _write_ctx(row, web2_id, settings)
        decision = gate.evaluate(ctx)
        if not decision.allowed:
            logger.info("web2_write_blocked", web2_id=web2_id, outcome=decision.outcome)
            return Web2Outcome(
                web2_id, "write", "blocked", reason=f"spend_blocked:{decision.outcome}"
            )

        article = write(
            the_plan, writer=writer, model=model,
            source_pack=client.source_pack, context=client.context, tuning=tuning,
        )
        gate.commit(ctx, ctx.estimated_cost)
        track(
            store, web2_id, status="needs_review", body_md=article.body_md,
            error="" if article.publishable else "draft has unresolved [NEEDS:] gaps",
        )
        logger.info(
            "web2_write_drafted", web2_id=web2_id, words=article.word_count,
            publishable=article.publishable,
        )
        return Web2Outcome(
            web2_id, "write", "needs_review",
            reason="drafted" if article.publishable else "drafted_with_gaps",
            needs=article.needs,
        )
    except Exception as exc:  # never re-raise (acks_late would redeliver = double spend)
        logger.exception("web2_write_error", web2_id=web2_id)
        _safe_mark_failed(store, web2_id, f"write error: {exc!r}")
        return Web2Outcome(web2_id, "write", "error", reason=f"{exc!r}"[:_ERROR_MAX])


# --------------------------------------------------------------------------- #
# Orchestration: run_publish (publishing -> published) - NEVER raises
# --------------------------------------------------------------------------- #
def run_publish(
    store: Web2Store,
    web2_id: str,
    *,
    publisher: Web2Publisher | None,
    gate: CostGate,
    settings: Settings,
    now: date | None = None,
) -> Web2Outcome:
    """Publish an APPROVED property, verify it, and track it. Never raises.

    Idempotent: an already ``published`` row is a no-op; a row not in ``publishing``
    (not approved) is skipped. A draft with unresolved gaps, an absent publisher, or a
    cost-gate block all HOLD the row back at ``needs_review`` (never a bad/blocked
    publish). A publish exception marks ``failed`` - never stuck, never re-raised."""
    try:
        row = store.load_web2(web2_id)
        if row is None:
            logger.warning("web2_publish_missing", web2_id=web2_id)
            return Web2Outcome(web2_id, "publish", "error", reason="not found")
        status = str(row.get("status") or "")
        if status == "published":
            return Web2Outcome(web2_id, "publish", "unchanged", reason="already published")
        if status != "publishing":
            # Not approved (or rejected) - do not publish.
            return Web2Outcome(web2_id, "publish", "skipped", reason=f"status={status}")

        platform = str(row.get("platform") or "")
        anchor = str(row.get("anchor") or "")
        target_url = str(row.get("target_url") or "")
        body_md = str(row.get("body_md") or "")
        external_id = row.get("external_id")
        external_id = str(external_id) if external_id else None

        if platform not in WEB2_PLATFORMS:
            track(store, web2_id, status="failed", error=f"unknown platform: {platform}")
            return Web2Outcome(web2_id, "publish", "failed", reason="unknown platform")

        if _NEEDS_MARKER in body_md or not body_md.strip():
            # A draft with unresolved gaps (or no body) must never go live: hold it.
            track(store, web2_id, status="needs_review", error="draft has unresolved [NEEDS:] gaps")
            return Web2Outcome(
                web2_id, "publish", "needs_review", degraded=True, reason="unresolved_gaps",
            )

        if publisher is None:
            # No per-account OAuth (vault wiring is a later chunk): HOLD at review.
            track(store, web2_id, status="needs_review", error="degraded: publisher unconfigured")
            logger.info("web2_publish_degraded", web2_id=web2_id, reason="no_publisher")
            return Web2Outcome(
                web2_id, "publish", "needs_review", degraded=True,
                reason="publisher_unconfigured",
            )

        # R5: cost pre-check BEFORE the publish call.
        ctx = _publish_ctx(row, web2_id, platform, settings)
        decision = gate.evaluate(ctx)
        if not decision.allowed:
            track(store, web2_id, status="needs_review", error=f"spend_blocked:{decision.outcome}")
            logger.info("web2_publish_blocked", web2_id=web2_id, outcome=decision.outcome)
            return Web2Outcome(
                web2_id, "publish", "blocked", reason=f"spend_blocked:{decision.outcome}"
            )

        try:
            result = publish(
                publisher, platform, body_md, anchor, target_url, external_id=external_id,
            )
        except Exception as exc:  # a provider failure marks failed (never stuck/never raised)
            gate.commit(ctx, ctx.estimated_cost)  # the attempt still incurred the metered cost
            logger.exception("web2_publish_provider_error", web2_id=web2_id)
            track(store, web2_id, status="failed", error=f"publish failed: {exc!r}")
            return Web2Outcome(web2_id, "publish", "failed", reason=f"{exc!r}"[:_ERROR_MAX])

        gate.commit(ctx, ctx.estimated_cost)
        verified, why = verify_live_and_indexable(result, platform)
        track(
            store, web2_id, status="published", post_url=result.post_url,
            verified="verified" if verified else "pending", external_id=result.external_id,
            published_at=(now or _utcnow().date()), error="" if verified else why,
        )
        logger.info("web2_published", web2_id=web2_id, verified=verified, url=result.post_url)
        return Web2Outcome(
            web2_id, "publish", "published", verified=verified, post_url=result.post_url,
            reason=why,
        )
    except Exception as exc:  # never re-raise
        logger.exception("web2_publish_error", web2_id=web2_id)
        _safe_mark_failed(store, web2_id, f"publish error: {exc!r}")
        return Web2Outcome(web2_id, "publish", "error", reason=f"{exc!r}"[:_ERROR_MAX])


# --------------------------------------------------------------------------- #
# Cost-gate contexts + helpers
# --------------------------------------------------------------------------- #
def _write_ctx(row: dict[str, Any], web2_id: str, settings: Settings) -> GateContext:
    return GateContext(
        feature_key=_WRITE_FEATURE,
        client_id=_client_id(row),
        provider=_WRITE_PROVIDER,
        estimated_cost=float(settings.content_generate_cost_estimate),
        job_id=web2_id,
        job_type="content",
        client_name=str(row.get("client_name") or ""),
    )


def _publish_ctx(row: dict[str, Any], web2_id: str, platform: str, settings: Settings) -> GateContext:
    return GateContext(
        feature_key=_PUBLISH_FEATURE,
        client_id=_client_id(row),
        provider=f"{_PUBLISH_PROVIDER}:{platform}",
        estimated_cost=float(settings.web2_publish_cost_estimate),
        job_id=web2_id,
        job_type=_JOB_TYPE,
        client_name=str(row.get("client_name") or ""),
    )


def _client_id(row: dict[str, Any]) -> str | None:
    cid = row.get("client_id")
    return str(cid) if cid else None


def _safe_mark_failed(store: Web2Store, web2_id: str, reason: str) -> None:
    """Best-effort terminal mark on an unexpected error; suppresses its own failures so
    the error path never raises."""
    try:
        store.update_web2(web2_id, {"status": "failed", "error": reason[:_ERROR_MAX]})
    except Exception:
        logger.warning("web2_mark_failed_failed", web2_id=web2_id)


def _utcnow() -> datetime:
    return datetime.now(UTC)


# --------------------------------------------------------------------------- #
# Minimal, deterministic Markdown -> HTML (no external dep)
# --------------------------------------------------------------------------- #
_LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")


def split_title_and_body(body_md: str) -> tuple[str, str]:
    """Split the leading H1 (``# Title``) from the rest of the article. Web 2.0 APIs
    take a separate title + content, so the H1 becomes the post title and is dropped
    from the body. No H1 -> ('', body)."""
    lines = body_md.splitlines()
    title = ""
    start = 0
    for i, line in enumerate(lines):
        if line.strip() == "":
            continue
        if line.startswith("# "):
            title = line[2:].strip()
            start = i + 1
        break
    rest = "\n".join(lines[start:]).strip()
    return title, rest


def markdown_to_html(body_md: str) -> str:
    """Render a subset of Markdown (headings, paragraphs, bullet lists, inline links) to
    HTML. Deterministic + dependency-free; the article the generator emits uses exactly
    this subset."""
    blocks = re.split(r"\n\s*\n", body_md.strip())
    html_parts: list[str] = []
    for block in blocks:
        block = block.strip()
        if not block:
            continue
        if block.startswith("### "):
            html_parts.append(f"<h3>{_inline(block[4:])}</h3>")
        elif block.startswith("## "):
            html_parts.append(f"<h2>{_inline(block[3:])}</h2>")
        elif block.startswith("# "):
            html_parts.append(f"<h1>{_inline(block[2:])}</h1>")
        elif all(line.lstrip().startswith("- ") for line in block.splitlines()):
            items = "".join(
                f"<li>{_inline(line.lstrip()[2:])}</li>" for line in block.splitlines()
            )
            html_parts.append(f"<ul>{items}</ul>")
        else:
            html_parts.append(f"<p>{_inline(block)}</p>")
    return "\n".join(html_parts)


def _inline(text: str) -> str:
    """Escape HTML metacharacters, then linkify ``[text](url)`` -> ``<a>``."""
    escaped = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return _LINK_RE.sub(lambda m: f'<a href="{m.group(2)}">{m.group(1)}</a>', escaped)


def _slugify(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-") or "post"


def gate_decision_blocks(decision: GateDecision) -> bool:
    """Whether a gate decision should HOLD the stage (any non-``call`` outcome)."""
    return not decision.allowed
