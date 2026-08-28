"""7B-3: the Web 2.0 PUBLISH pipeline - plan -> write -> HUMAN REVIEW GATE ->
publish -> verify -> track.

A Web 2.0 property is an on-topic, branded authority article posted to a client-owned
WordPress.com / Blogger / Tumblr blog, carrying ONE editorial backlink to the client's
page. It is white-hat authority work, NEVER link spam - which is exactly why the
article is NEVER auto-published: a lead must APPROVE it at the ``needs_review`` gate.

The pipeline mirrors the content module's purity (``content_generator`` /
``context_compactor``): the core stages are pure of Celery + DB + network, taking
injected seams (a ``SystemSummarizer`` writer, a ``Web2Publisher``, a ``CostGate``, a
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

import hashlib
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Any, Literal, Protocol

from app.config import Settings
from app.logging_setup import get_logger
from app.schemas.content import auto_framework
from app.services import pricing
from app.services.content_generator import (
    DEFAULT_TUNING,
    GenerationContext,
    GeneratorTuning,
    SourcePack,
    generate,
)
from app.services.content_research import (
    ContentSpendBlocked,
    FormatDecision,
    ResearchBrief,
    Teardown,
    TermSet,
    TopicalCluster,
    assess_winnability,
    build_registry,
)
from app.services.cost_gate import CostGate, GateContext, GateDecision
from app.services.web2_linkcheck import PageFetcher, check_link
from integrations.llm import LLMResult, SystemSummarizer
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


class _Web2GatedWriter:
    """A ``SystemSummarizer`` that meters every draft call through the cost gate, mirroring
    ``workers.tasks.content._ContentGatedWriter`` (duplicated locally rather than
    imported so this module stays free of that module's Celery/DB import chain -
    ``web2_pipeline`` is deliberately pure of Celery + DB + network).

    ``content_generator.generate()`` makes MULTIPLE separate ``writer.summarize()``
    calls per article (one per section, one for the direct-answer block, one for
    photo briefs); each is individually gated + committed here at its REAL cost
    (``pricing.anthropic_cost`` from the call's actual token usage), never a single
    flat estimate for the whole article. A gate block mid-draft raises
    :class:`ContentSpendBlocked`, which ``run_write`` catches to HOLD the placement
    (never a half-billed, half-written draft).
    """

    def __init__(
        self,
        inner: SystemSummarizer,
        gate: CostGate,
        *,
        settings: Settings,
        client_id: str | None,
        job_id: str = "",
        client_name: str = "",
    ) -> None:
        self._inner = inner
        self._gate = gate
        self._settings = settings
        self._client_id = client_id
        self._job_id = job_id
        self._client_name = client_name
        self.calls = 0
        self.spent: float = 0.0

    def _ctx(self) -> GateContext:
        return GateContext(
            feature_key=_WRITE_FEATURE,
            client_id=self._client_id,
            provider=_WRITE_PROVIDER,
            estimated_cost=float(self._settings.content_generate_cost_estimate),
            job_id=self._job_id,
            job_type="content",
            client_name=self._client_name,
        )

    def summarize(
        self,
        prompt: str,
        *,
        model: str,
        max_tokens: int,
        system: str | Sequence[str] | None = None,
        cache: Sequence[bool] | None = None,
    ) -> LLMResult:
        """Meter, then delegate - FORWARDING ``system`` to the inner writer.

        Mirrors ``_ContentGatedWriter``. The ``system`` parameter is load-bearing:
        ``content_generator`` states its own contract with it, and dropping it here
        would land every web2 article back on the context-COMPACTION default (see
        ``integrations.llm._COMPACTION_SYSTEM_PROMPT``). Keep it.
        """
        self.calls += 1
        ctx = self._ctx()
        decision = self._gate.evaluate(ctx)
        if not decision.allowed:
            raise ContentSpendBlocked(decision.outcome)
        result = self._inner.summarize(
            prompt, model=model, max_tokens=max_tokens, system=system, cache=cache
        )
        # Commit the ACTUAL draft spend from the call's real token usage x the
        # model's unit price (pricing.py), not the flat per-call estimate.
        actual = pricing.anthropic_cost(
            self._settings,
            model=model,
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
        )
        self.spent += actual
        self._gate.commit(ctx, actual)
        return result


# --------------------------------------------------------------------------- #
# Stage 2: write (via the ranking-grade content generator)
# --------------------------------------------------------------------------- #
def write(
    plan: Web2Plan,
    *,
    writer: SystemSummarizer,
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
    # Seeded on the property's own identity so the placement is stable for THIS draft
    # (a redraft puts the link in the same place) but differs across properties.
    body_md = _place_backlink(
        generated.draft_md,
        plan.anchor,
        plan.target_url,
        seed=f"{plan.client_name}|{plan.platform}|{plan.topic}|{plan.anchor}",
    )
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


def _place_backlink(draft_md: str, anchor: str, target_url: str, *, seed: str = "") -> str:
    """Place the ONE editorial link the property exists to carry - CONTEXTUALLY.

    This replaced an ``_append_backlink`` that emitted a byte-identical trailing block on
    every property of every client::

        ## More about {anchor}

        Learn more about [{anchor}]({target_url}).

    That was three problems in four lines. It was a **cross-client footprint** - every
    article we had ever published ended with the same two lines, so one suspended
    property fingerprinted the rest. It was an obviously bolted-on link rather than the
    in-sentence editorial reference both R2-14 and current practice require. And its
    fixed ``## More about`` heading sat in **every** document's heading skeleton, which
    would drag the heading-Jaccard gate (:mod:`app.services.web2_similarity`) toward its
    block line on legitimately distinct articles - a safety control defeated by the very
    text it was meant to inspect.

    The strategy, in order of preference:

    1. **Link a mention that is already there.** If the anchor (or the client's brand)
       occurs in ordinary prose, the first such occurrence becomes the link. This adds
       NO new text at all, so there is no template to fingerprint and the placement
       varies exactly as much as the articles do. This is the path that should normally
       win, because the generator grounds the draft in the client's name.
    2. **Otherwise, extend an existing paragraph** with one short sentence, chosen
       deterministically from a small family and attached to a paragraph chosen by the
       same seed - never a new heading, never the same slot twice across properties.

    Exactly one link to ``target_url`` is produced in both paths. An empty
    ``target_url`` yields the draft unchanged (a property with no link is a held draft,
    not a silent no-op link to nowhere).
    """
    anchor = anchor.strip() or "our services"
    if not target_url.strip():
        return draft_md.rstrip() + "\n"

    linked = _link_existing_mention(draft_md, anchor, target_url)
    if linked is not None:
        return linked.rstrip() + "\n"
    return _extend_paragraph_with_link(draft_md, anchor, target_url, seed=seed).rstrip() + "\n"


def _is_prose(line: str) -> bool:
    """A body paragraph line: not a heading, list item, quote, code fence, or table."""
    stripped = line.strip()
    if not stripped:
        return False
    return not stripped.startswith(("#", ">", "-", "*", "+", "|", "```", "    "))


def _link_existing_mention(draft_md: str, anchor: str, target_url: str) -> str | None:
    """Turn the first prose occurrence of ``anchor`` into the editorial link.

    Skips lines that already contain a markdown link, so the anchor can never be nested
    inside another link, and skips the H1/headings so the link lands in a sentence.
    Returns ``None`` when the anchor is not present in prose, which hands the caller the
    fallback.
    """
    pattern = re.compile(rf"(?<!\[)(?<!\w){re.escape(anchor)}(?!\w)(?!\])", re.IGNORECASE)
    out = draft_md.splitlines()
    for i, line in enumerate(out):
        if not _is_prose(line) or "](" in line:
            continue
        match = pattern.search(line)
        if match is None:
            continue
        # Keep the prose's own casing - rewriting it to the anchor's casing would be a
        # visible tell and would read as machine-edited.
        found = match.group(0)
        out[i] = line[: match.start()] + f"[{found}]({target_url})" + line[match.end() :]
        return "\n".join(out)
    return None


# One short closing sentence per property. A FAMILY, not a template: the member is
# chosen by seed, so two properties do not share a line, and none of them is a heading.
_LINK_SENTENCES: tuple[str, ...] = (
    "Full details of the work are on [{anchor}]({url}).",
    "More on how this is handled is at [{anchor}]({url}).",
    "The service pages at [{anchor}]({url}) cover the specifics.",
    "There is a fuller breakdown at [{anchor}]({url}).",
    "See [{anchor}]({url}) for the current details.",
)


def _extend_paragraph_with_link(draft_md: str, anchor: str, target_url: str, *, seed: str) -> str:
    """Append one seeded sentence to an existing LATE paragraph.

    A late paragraph rather than a new trailing section: the link then sits inside the
    body's own prose instead of announcing itself as an appendix. If the draft has no
    prose at all (a ``[NEEDS:]`` skeleton), the sentence becomes its own final line -
    such a draft cannot publish anyway, so it never reaches a real page in that shape.
    """
    sentence = _LINK_SENTENCES[_seed_index(seed or anchor, len(_LINK_SENTENCES))].format(
        anchor=anchor, url=target_url
    )
    lines = draft_md.rstrip().splitlines()
    prose_idx = [i for i, line in enumerate(lines) if _is_prose(line)]
    if not prose_idx:
        return draft_md.rstrip() + "\n\n" + sentence
    # Choose among the last few prose lines, seeded, so the slot itself varies too.
    tail = prose_idx[-3:]
    target = tail[_seed_index(seed or anchor, len(tail))]
    lines[target] = lines[target].rstrip() + " " + sentence
    return "\n".join(lines)


def _seed_index(seed: str, modulo: int) -> int:
    """A stable index from a seed - deterministic across processes (``hash()`` is not,
    because PYTHONHASHSEED is randomised per process, so two workers would place the
    link differently for the same property)."""
    if modulo <= 0:
        return 0
    digest = hashlib.blake2b(seed.encode("utf-8"), digest_size=8).digest()
    return int.from_bytes(digest, "big") % modulo


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
    body_md = _place_backlink(
        body_md,
        plan.anchor,
        plan.target_url,
        seed=f"{plan.client_name}|{plan.platform}|{plan.topic}|{plan.anchor}",
    )
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
    link_rel: str | None = None,
    link_found: bool | None = None,
    link_checked_at: Any = None,
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
    # The MEASURED link facts. `link_found` is deliberately tri-state: None means nobody
    # looked, which must stay distinguishable from False ("we looked and it was gone").
    if link_rel is not None:
        fields["link_rel"] = link_rel
    if link_found is not None:
        fields["link_found"] = link_found
    if link_checked_at is not None:
        fields["link_checked_at"] = link_checked_at
    store.update_web2(web2_id, fields)


# --------------------------------------------------------------------------- #
# The cross-property similarity seam (WEB2-007 / R2-11)
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class SimilarityOutcome:
    """What the gate decided about one draft. ``code`` is the machine-readable string
    persisted on the row (``sim_block:<check>:<scope>:<web2_id>``), so the UI and the
    approval endpoint both read a verdict rather than parse prose."""

    verdict: Literal["pass", "warn", "block", "unavailable"] = "pass"
    code: str = ""
    detail: str = ""

    @property
    def blocked(self) -> bool:
        return self.verdict == "block"


class Web2SimilarityChecker(Protocol):
    """Injected seam: fingerprint this draft and score it against the corpus.

    A Protocol rather than a direct import so the pure pipeline keeps its no-DB
    guarantee - the worker supplies the DB-backed implementation, tests supply a fake,
    and ``None`` means 'not wired' (which is NOT the same as 'passed', see below)."""

    def __call__(
        self, *, web2_id: str, row: dict[str, Any], body_md: str, client: Web2Client
    ) -> SimilarityOutcome: ...


def check_similarity(
    checker: Web2SimilarityChecker | None,
    *,
    web2_id: str,
    row: dict[str, Any],
    body_md: str,
    client: Web2Client,
) -> SimilarityOutcome:
    """Run the gate, converting any failure into an honest ``unavailable`` verdict.

    FAIL-OPEN HERE, FAIL-CLOSED AT APPROVAL - and the asymmetry is the whole point. At
    draft time a block and a pass land in the SAME place (``needs_review``); refusing to
    draft because the corpus is unreachable would stop all work to prevent nothing, since
    nothing publishes from here anyway. What must never happen is a placement going LIVE
    unchecked, so the approval endpoint treats ``unavailable`` as a refusal. The verdict
    is recorded either way, so 'the gate could not run' is visible rather than silently
    indistinguishable from 'the gate approved it'.
    """
    if checker is None:
        return SimilarityOutcome("unavailable", "sim_unavailable:not_wired", "gate not wired")
    try:
        return checker(web2_id=web2_id, row=row, body_md=body_md, client=client)
    except Exception as exc:  # never raise out of run_write (acks_late => double spend)
        logger.warning("web2_similarity_unavailable", web2_id=web2_id, error=repr(exc))
        return SimilarityOutcome("unavailable", "sim_unavailable:error", f"{exc!r}"[:_ERROR_MAX])


# --------------------------------------------------------------------------- #
# Orchestration: run_write (draft -> needs_review) - NEVER raises
# --------------------------------------------------------------------------- #
def run_write(
    store: Web2Store,
    web2_id: str,
    *,
    client: Web2Client,
    writer: SystemSummarizer | None,
    gate: CostGate,
    settings: Settings,
    model: str = "content-writer",
    tuning: GeneratorTuning = DEFAULT_TUNING,
    similarity: Web2SimilarityChecker | None = None,
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

        # R5: cost pre-check BEFORE the paid draft (blocks over-budget clients before
        # any work happens; the real per-call spend is metered below).
        ctx = _write_ctx(row, web2_id, settings)
        decision = gate.evaluate(ctx)
        if not decision.allowed:
            logger.info("web2_write_blocked", web2_id=web2_id, outcome=decision.outcome)
            return Web2Outcome(
                web2_id, "write", "blocked", reason=f"spend_blocked:{decision.outcome}"
            )

        # Every internal writer.summarize() call the generator makes (one per
        # section + the answer block + photo briefs) is individually gated and
        # committed to the cost log at its REAL usage-derived cost - never one flat
        # estimate for the whole article.
        gated_writer = _Web2GatedWriter(
            writer, gate, settings=settings, client_id=_client_id(row), job_id=web2_id,
            client_name=str(row.get("client_name") or ""),
        )
        article = write(
            the_plan, writer=gated_writer, model=model,
            source_pack=client.source_pack, context=client.context, tuning=tuning,
        )

        # The cross-property similarity gate (R2-11): AFTER the draft exists, BEFORE the
        # row is parked at review. It runs on every draft and its verdict is always
        # recorded; whether a `block` actually refuses APPROVAL is decided at the
        # approval endpoint by `settings.web2_similarity_enforce`, so the recorded fact
        # stays honest whatever the enforcement posture is.
        sim = check_similarity(
            similarity, web2_id=web2_id, row=row, body_md=article.body_md, client=client
        )

        gap_error = "" if article.publishable else "draft has unresolved [NEEDS:] gaps"
        # BOTH findings are kept. An earlier version wrote `gap_error or sim.code`, which
        # silently DISCARDED the similarity verdict whenever a draft also had a grounding
        # gap - so a duplicate that happened to be gappy carried no similarity code at
        # all, and the approval guard (which matches on the `sim_` prefix) skipped it
        # entirely. The similarity code leads so that prefix match still works, and the
        # gap is appended rather than replacing it.
        error = "; ".join(part for part in (sim.code, gap_error) if part)
        track(store, web2_id, status="needs_review", body_md=article.body_md, error=error)
        logger.info(
            "web2_write_drafted", web2_id=web2_id, words=article.word_count,
            publishable=article.publishable, spent=gated_writer.spent,
            similarity=sim.verdict,
        )
        return Web2Outcome(
            web2_id, "write", "needs_review",
            reason="drafted" if article.publishable else "drafted_with_gaps",
            needs=article.needs,
        )
    except ContentSpendBlocked as blocked:
        # A gate block landed mid-draft (budget/halt tripped between calls): no
        # half-written row is persisted (track() never ran above), so the row stays
        # at "draft" for a clean retry - never a half-billed, half-written draft.
        logger.info("web2_write_blocked_mid_draft", web2_id=web2_id, outcome=blocked.outcome)
        return Web2Outcome(
            web2_id, "write", "blocked", reason=f"spend_blocked:{blocked.outcome}"
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
    fetch_page: PageFetcher | None = None,
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

        # R2-07: a property published through a credential later found to be SHARED
        # across clients receives no further posts. The article already live is left
        # alone deliberately - deleting a live page is a larger, stranger signal than
        # letting it sit - but continuing to post to it keeps extending a correlation
        # between clients that we can no longer defend. Until this migration ran, the
        # flag was set by the reconciliation, read by the reports, and enforced nowhere.
        if bool(row.get("shared_origin")):
            track(
                store, web2_id, status="needs_review",
                error="frozen: shared_origin (published through a credential shared "
                      "across clients; re-point it at a client-owned account first)",
            )
            logger.info("web2_publish_frozen_shared_origin", web2_id=web2_id, platform=platform)
            return Web2Outcome(
                web2_id, "publish", "needs_review", degraded=True, reason="shared_origin_frozen"
            )

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
        # Fetch the page we were just given and look for our own link. A 201 from the
        # platform means it accepted the post, NOT that the link survived on the page -
        # platforms strip links, wrap them in redirectors, and add rel="nofollow"
        # server-side, and none of that comes back in the create response.
        link = check_link(result.post_url, target_url, fetch_page)
        track(
            store, web2_id, status="published", post_url=result.post_url,
            verified="verified" if verified else "pending", external_id=result.external_id,
            published_at=(now or _utcnow().date()), error="" if verified else why,
            link_rel=link.rel, link_found=link.found,
            link_checked_at=_utcnow() if link.state != "unknown" else None,
        )
        logger.info(
            "web2_published", web2_id=web2_id, verified=verified, url=result.post_url,
            link=link.state, link_rel=link.rel or "-",
        )
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
