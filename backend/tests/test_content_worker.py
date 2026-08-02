"""P7A-7/8 gate: the CONTENT worker's pure core + the QA-gated publish path, with
a FAKE store + all-fake providers + an in-memory cost gate - no Celery, no DB, no
network (the teardown fan-out is disabled so the SSRF guard never does DNS).

Worker (P7A-7) proves:

* the full pipeline advances ``queued -> drafting -> needs_review`` with EVERY rich
  column populated (draft/words/keyword_map/outline/entity_coverage/qa_score/
  json_ld/internal_links/schema) and the QA score ATTACHED at the gate;
* cost is logged through the Part-2 path and streamed to the ``cost`` column;
* redelivery of a terminal (needs_review/done) job is a no-op (never re-runs);
* degraded (providers=None) HOLDS at ``drafting`` with an honest $0 marker;
* the R5 cost pre-check DEFERS an over-budget job at entry (no spend, no advance);
* a research-spend block degrades (holds), the writer is never reached;
* an unexpected error FAILS the job and is NEVER re-raised.

Publish (P7A-8) proves:

* QA is ADVISORY, not a gate: a sub-threshold (or unscored) job still publishes -
  the human review gate is the quality gate now;
* a passing job publishes to WordPress; the publish is idempotent (a set
  ``wp_post_id`` -> UPDATE, id reused);
* the PDF/Markdown path renders to the traversal-safe store and never leaks a path;
* no WP credential degrades to artifact-only (a marker, never a crash);
* a redelivered ``done`` publish is a no-op.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

import pytest

from app.config import Settings
from app.services.content_qa import QA_DIMENSIONS, QaScore
from app.services.content_research import ContentSpendBlocked, FakePageFetcher
from app.services.cost_gate import DialMode, GateContext
from app.services.wp_connections import ResolvedWpConnection
from integrations.content_providers import content_providers_for_tests
from integrations.llm import LLMResult
from integrations.wordpress import (
    FakeWordPressPublisher,
    PostDraft,
    PublishResult,
    XmlRpcWordPressPublisher,
)
from workers.tasks.content import (
    ClientWpTarget,
    MeteredCostGate,
    WpTarget,
    build_client_wp_target,
    execute_content_job,
    md_to_html,
    publish_content_job,
)

pytestmark = pytest.mark.unit


# --------------------------------------------------------------------------- #
# Fakes: an in-memory content-job store + a configurable cost store + null cache.
# --------------------------------------------------------------------------- #
class FakeContentStore:
    """In-memory ``ContentStore`` keyed by ``code`` (mirrors the privileged repo)."""

    def __init__(self, row: dict[str, Any]) -> None:
        self.row = dict(row)
        self.updates: list[dict[str, Any]] = []

    def load(self, code: str) -> dict[str, Any] | None:
        return dict(self.row) if self.row.get("code") == code else None

    def update(self, code: str, fields: dict[str, Any]) -> dict[str, Any] | None:
        self.updates.append(dict(fields))
        self.row.update(fields)
        return dict(self.row)


class _FakeCostStore:
    """A configurable ``CostStore`` for the gate; records every logged cost."""

    def __init__(
        self,
        *,
        dials: dict[str, DialMode] | None = None,
        budget: tuple[float, float] | None = None,
        daily_stop: float = 1000.0,
        daily_spent: float = 0.0,
        halted: bool = False,
    ) -> None:
        self._dials = dials or {}
        self._budget = budget
        self._daily_stop = daily_stop
        self._daily_spent = daily_spent
        self._halted = halted
        self.records: list[tuple[str, float, bool]] = []

    def dial_mode(self, feature_key: str) -> DialMode:
        return self._dials.get(feature_key, "api")

    def client_budget(self, client_id: str) -> tuple[float, float] | None:
        return self._budget

    def daily_spent(self) -> float:
        return self._daily_spent

    def daily_stop(self) -> float:
        return self._daily_stop

    def is_halted(self) -> bool:
        return self._halted

    def record_cost(self, ctx: GateContext, cost: float, *, cached: bool) -> None:
        self.records.append((ctx.feature_key, cost, cached))


class _NullCache:
    def get(self, key: str) -> Any | None:
        return None

    def set(self, key: str, value: Any) -> None:
        return None


def _gate(store: _FakeCostStore | None = None) -> MeteredCostGate:
    return MeteredCostGate(store or _FakeCostStore(), _NullCache())


def _settings(**over: Any) -> Settings:
    base: dict[str, Any] = {
        # No teardown fetch -> the SSRF guard never runs -> fully offline.
        "content_teardown_max_pages": 0,
        "content_research_cost_estimate": 0.01,
        "content_generate_cost_estimate": 0.15,
        "content_precheck_research_calls": 10,
        "content_precheck_writer_calls": 14,
    }
    base.update(over)
    return Settings(_env_file=None, app_env="dev", **base)


_CLIENT_ID = "11111111-1111-1111-1111-111111111111"
_OTHER_ID = "22222222-2222-2222-2222-222222222222"


def _job_row(**over: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "code": "CJ-4200",
        "client_id": _CLIENT_ID,
        "client_name": "Verde Cafe",
        "page_type": "blog",
        "topic": "best brunch in portland",
        "framework": "PAS",
        "target": "WordPress",
        "status": "queued",
        "source_pack": {
            "client_name": "Verde Cafe",
            "facts": {"founded": "twenty fifteen"},
            "services": ["weekend brunch", "single-origin espresso"],
            "proof_points": ["Named best brunch by the Portland food guide"],
            "unique_data": ["Our guest survey of regular diners"],
            "testimonials": ["The best brunch in the Pearl District — a happy regular"],
            "internal_urls": {"brunch menu": "/menu"},
        },
    }
    row.update(over)
    return row


# --------------------------------------------------------------------------- #
# 1. Full pipeline: queued -> needs_review with every rich column populated.
# --------------------------------------------------------------------------- #
def test_full_pipeline_advances_to_needs_review_with_rich_columns() -> None:
    store = FakeContentStore(_job_row())
    cost_store = _FakeCostStore()
    gate = _gate(cost_store)
    providers = content_providers_for_tests()

    out = execute_content_job(
        store, providers, "CJ-4200",
        settings=_settings(), gate=gate, fetcher=FakePageFetcher(),
    )

    assert out.state == "advanced"
    assert out.status == "needs_review"
    row = store.row
    assert row["status"] == "needs_review"
    assert row["stage"] == "Review"
    # Rich pipeline columns are all populated.
    assert row["draft_md"] and "# " in row["draft_md"]  # a real H1 draft
    assert row["words"] > 0
    assert row["schema_type"]  # a validated JSON-LD @type
    assert row["keyword_map"]["primary"] == "best brunch in portland"
    assert row["outline"]["headings"]  # the section outline
    assert "table_stakes" in row["entity_coverage"]
    assert row["json_ld"]["@graph"]  # the assembled JSON-LD graph
    assert "links" in row["internal_links"]
    # The QA score is ATTACHED at the gate so the reviewer sees it.
    qa = row["qa_score"]
    assert "dimensions" in qa and "passed" in qa and "weighted_total" in qa
    assert len(qa["dimensions"]) == 14
    # Cost was streamed to the column AND logged through the Part-2 path.
    assert row["cost"] > 0
    assert gate.spent > 0
    assert any(cost > 0 and not cached for _f, cost, cached in cost_store.records)
    # Both the research + generation dials were billed.
    billed = {feature for feature, _c, _cached in cost_store.records}
    assert "content_research" in billed and "content" in billed
    # The content guard picked a deterministic layout for the Review preview.
    assert store.row["outline"]["layout"]["key"]


# --------------------------------------------------------------------------- #
# 1b. The content guard runs in-pipeline: the stored draft is em/en-dash-free even
#     when the WRITER emits dashes (the unconditional hard strip is the guarantee).
# --------------------------------------------------------------------------- #
def test_pipeline_output_is_em_dash_free_even_when_writer_emits_dashes() -> None:
    store = FakeContentStore(_job_row())

    class _DashWriter:
        """Every section the writer phrases comes back stuffed with em/en dashes."""

        def summarize(self, prompt: str, *, model: str, max_tokens: int) -> LLMResult:
            em, en = chr(0x2014), chr(0x2013)
            body = f"Fresh brunch{em}served daily{en}book 9{en}11 weekends, world-class and cutting-edge."
            return LLMResult(text=body, input_tokens=8, output_tokens=8)

    providers = replace(content_providers_for_tests(), writer=_DashWriter())
    out = execute_content_job(
        store, providers, "CJ-4200", settings=_settings(), gate=_gate(), fetcher=FakePageFetcher()
    )

    assert out.status == "needs_review"
    draft = store.row["draft_md"]
    # THE guarantee: not a single em (U+2014) or en (U+2013) dash survives to storage.
    assert chr(0x2014) not in draft and chr(0x2013) not in draft
    # And the title/answer fields were cleaned too (they feed schema + QA + publish).
    assert chr(0x2014) not in store.row["stage"]


# --------------------------------------------------------------------------- #
# 1c. GUIDED EDIT: a `drafting` job carrying an edit_instruction is re-drafted with
#     that instruction fed to the writer, then the instruction is CLEARED.
# --------------------------------------------------------------------------- #
def test_guided_edit_redraft_applies_instruction_and_clears_it() -> None:
    store = FakeContentStore(
        _job_row(status="drafting", edit_instruction="make the intro punchier and mention brunch")
    )

    class _SpyWriter:
        """Records every prompt so the test can prove the reviewer note reached it."""

        def __init__(self) -> None:
            self.prompts: list[str] = []

        def summarize(self, prompt: str, *, model: str, max_tokens: int) -> LLMResult:
            self.prompts.append(prompt)
            return LLMResult(text="Fresh, direct brunch copy for weekend diners.", input_tokens=6, output_tokens=6)

    spy = _SpyWriter()
    providers = replace(content_providers_for_tests(), writer=spy)
    out = execute_content_job(
        store, providers, "CJ-4200", settings=_settings(), gate=_gate(), fetcher=FakePageFetcher()
    )

    assert out.status == "needs_review"  # a `drafting` job is worker-owned -> re-drafts
    # The reviewer's guided-edit instruction reached the writer as a steered rewrite.
    assert any("REVIEWER INSTRUCTION" in p for p in spy.prompts)
    assert any("make the intro punchier" in p for p in spy.prompts)
    # Once applied, the instruction is cleared so a later re-run does not re-apply it.
    assert store.row["edit_instruction"] == ""


# --------------------------------------------------------------------------- #
# 1d. The Review preview's META tags (title + description) are persisted in outline.
# --------------------------------------------------------------------------- #
def test_pipeline_persists_meta_in_outline_for_the_preview() -> None:
    store = FakeContentStore(_job_row())
    out = execute_content_job(
        store, content_providers_for_tests(), "CJ-4200",
        settings=_settings(), gate=_gate(), fetcher=FakePageFetcher(),
    )
    assert out.status == "needs_review"
    meta = store.row["outline"]["meta"]
    assert meta["title"]  # the rendered <title> for the SERP preview
    assert "description" in meta  # the <meta name=description>


# --------------------------------------------------------------------------- #
# 1e. THE QA IMPROVEMENT LOOP (drafting-time): the worker re-drafts against the §11
#     scorecard until it clears the top-1% target OR the MAX_QA_LOOPS cap OR the
#     spend-stop trips. Driven by an INJECTED scorer so the pass/fail sequence + the
#     exact rewrite count are deterministic.
# --------------------------------------------------------------------------- #
def _qa(total: int, *, passed: bool) -> QaScore:
    """A scripted QaScore. A failing one carries a below-target dim + a note so
    ``rewrite_guidance`` yields a non-empty steer (the loop attempts a rewrite)."""
    dims = dict.fromkeys(QA_DIMENSIONS, 95 if passed else 60)
    if not passed:
        dims["fact_grounding"] = 50
    return QaScore(
        dimensions=dims,
        weighted_total=total,
        passed=passed,
        blocked_by=[] if passed else ["fact_grounding"],
        notes=[] if passed else ["fact_grounding: an untraceable concrete claim"],
    )


class _ScriptedScorer:
    """Returns a scripted QaScore per call (last entry repeats), counting calls."""

    def __init__(self, scores: list[QaScore]) -> None:
        self._scores = scores
        self.calls = 0

    def __call__(self, content: Any, brief: Any, schema_result: Any, source_pack: Any, *, judge: Any = None) -> QaScore:
        qa = self._scores[min(self.calls, len(self._scores) - 1)]
        self.calls += 1
        return qa


def test_qa_loop_fails_twice_then_passes_runs_exactly_two_rewrites() -> None:
    store = FakeContentStore(_job_row())
    scorer = _ScriptedScorer([_qa(60, passed=False), _qa(60, passed=False), _qa(95, passed=True)])

    out = execute_content_job(
        store, content_providers_for_tests(), "CJ-4200",
        settings=_settings(content_qa_target_score=90, content_qa_max_loops=3),
        gate=_gate(), fetcher=FakePageFetcher(), scorer=scorer,
    )

    assert out.status == "needs_review"
    assert out.qa_loops == 2          # two targeted rewrite passes before it cleared
    assert scorer.calls == 3          # initial score + one after each rewrite
    assert out.passed is True         # advanced with the passing draft
    assert store.row["qa_score"]["passed"] is True
    assert store.row["qa_score"]["weighted_total"] == 95


def test_qa_loop_caps_at_max_loops_and_advances_with_best() -> None:
    store = FakeContentStore(_job_row())
    scorer = _ScriptedScorer([_qa(60, passed=False)])  # ALWAYS fails

    out = execute_content_job(
        store, content_providers_for_tests(), "CJ-4200",
        settings=_settings(content_qa_target_score=90, content_qa_max_loops=2),
        gate=_gate(), fetcher=FakePageFetcher(), scorer=scorer,
    )

    assert out.status == "needs_review"   # still advances (the publish gate blocks later)
    assert out.qa_loops == 2              # HARD cap honoured, never spins
    assert scorer.calls == 3              # initial + 2 capped rewrites
    assert out.passed is False            # advanced with the best (still sub-threshold)


def test_qa_loop_cost_blocked_mid_loop_advances_with_best_never_spins() -> None:
    store = FakeContentStore(_job_row())
    scorer = _ScriptedScorer([_qa(60, passed=False)])  # would loop forever if uncapped

    class _RewriteBlockedWriter:
        """Writes normally for generation + the em-dash guard, but the cost gate
        blocks a QA-loop rewrite (its prompt carries the guided-rewrite marker) ->
        that pass does ZERO writer work, so the loop must stop, not spin."""

        def summarize(self, prompt: str, *, model: str, max_tokens: int) -> LLMResult:
            if "REVIEWER INSTRUCTION" in prompt:
                raise ContentSpendBlocked("blocked_halt")
            return LLMResult(text="Grounded, clean brunch copy for weekend diners.", input_tokens=6, output_tokens=6)

    providers = replace(content_providers_for_tests(), writer=_RewriteBlockedWriter())
    out = execute_content_job(
        store, providers, "CJ-4200",
        settings=_settings(content_qa_target_score=90, content_qa_max_loops=3),
        gate=_gate(), fetcher=FakePageFetcher(), scorer=scorer,
    )

    assert out.status == "needs_review"   # advanced with the best draft so far
    assert out.qa_loops == 0              # the first rewrite was cost-blocked -> stop
    assert scorer.calls == 1              # only the initial score ran
    assert out.passed is False


# --------------------------------------------------------------------------- #
# 2. Redelivery of a terminal job => no-op (never re-runs the pipeline).
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("status", ["needs_review", "done", "publishing", "failed", "rejected"])
def test_redelivery_of_terminal_job_is_noop(status: str) -> None:
    store = FakeContentStore(_job_row(status=status))
    out = execute_content_job(
        store, content_providers_for_tests(), "CJ-4200",
        settings=_settings(), gate=_gate(), fetcher=FakePageFetcher(),
    )
    assert out.state == "noop"
    assert out.status == status
    assert store.updates == []  # nothing written; the pipeline never ran


# --------------------------------------------------------------------------- #
# 3. Degraded (providers=None) => holds at drafting, honest $0, never crashes.
# --------------------------------------------------------------------------- #
def test_degraded_no_providers_holds_at_drafting() -> None:
    store = FakeContentStore(_job_row())
    out = execute_content_job(
        store, None, "CJ-4200", settings=_settings(), gate=_gate(), fetcher=FakePageFetcher()
    )
    assert out.state == "degraded"
    assert out.status == "drafting"
    assert store.row["status"] == "drafting"  # advanced but held
    assert out.cost == 0.0
    assert "degraded" in store.row["stage"].lower()


# --------------------------------------------------------------------------- #
# 4. R5 cost pre-check DEFERS an over-budget job at entry (no spend, no advance).
# --------------------------------------------------------------------------- #
def test_r5_precheck_defers_over_budget_job() -> None:
    store = FakeContentStore(_job_row())
    # A tiny cap ($0.01) the full-job estimate (~$2) will breach at pre-check.
    cost_store = _FakeCostStore(budget=(0.01, 0.0))
    gate = _gate(cost_store)

    out = execute_content_job(
        store, content_providers_for_tests(), "CJ-4200",
        settings=_settings(), gate=gate, fetcher=FakePageFetcher(),
    )

    assert out.state == "deferred"
    assert out.status == "queued"  # NOT advanced to drafting
    assert store.row["status"] == "queued"
    assert "deferred" in store.row["stage"].lower()
    assert gate.spent == 0.0  # nothing spent
    # No provider was billed (the block happened before any call).
    assert cost_store.records == []


# --------------------------------------------------------------------------- #
# 5. A research-spend block degrades (holds), the writer is never reached.
# --------------------------------------------------------------------------- #
def test_research_spend_block_degrades_before_generation() -> None:
    store = FakeContentStore(_job_row())
    # content dial on (pre-check passes) but content_research dial OFF -> the SERP
    # pull raises ContentSpendBlocked -> build_research_brief returns a shell brief.
    cost_store = _FakeCostStore(dials={"content": "api", "content_research": "off"})
    gate = _gate(cost_store)

    class _BoomWriter:
        def summarize(self, prompt: str, *, model: str, max_tokens: int) -> LLMResult:
            raise AssertionError("the writer must never be reached when research is blocked")

    providers = replace(content_providers_for_tests(), writer=_BoomWriter())

    out = execute_content_job(
        store, providers, "CJ-4200", settings=_settings(), gate=gate, fetcher=FakePageFetcher()
    )

    assert out.state == "degraded"
    assert out.status == "drafting"
    assert store.row["status"] == "drafting"


# --------------------------------------------------------------------------- #
# 6. An unexpected error FAILS the job and is NEVER re-raised (acks_late-safe).
# --------------------------------------------------------------------------- #
def test_unexpected_error_fails_and_never_reraises() -> None:
    store = FakeContentStore(_job_row())

    class _ExplodingWriter:
        def summarize(self, prompt: str, *, model: str, max_tokens: int) -> LLMResult:
            raise RuntimeError("writer exploded")

    providers = replace(content_providers_for_tests(), writer=_ExplodingWriter())

    out = execute_content_job(  # must NOT raise
        store, providers, "CJ-4200", settings=_settings(), gate=_gate(), fetcher=FakePageFetcher()
    )

    assert out.state == "failed"
    assert out.status == "failed"
    assert store.row["status"] == "failed"
    assert "writer exploded" in out.reason


def test_missing_job_is_failed_not_crash() -> None:
    store = FakeContentStore(_job_row())
    out = execute_content_job(
        store, content_providers_for_tests(), "CJ-NOPE",
        settings=_settings(), gate=_gate(), fetcher=FakePageFetcher(),
    )
    assert out.state == "failed" and out.reason == "not found"


# --------------------------------------------------------------------------- #
# Publish (P7A-8)
# --------------------------------------------------------------------------- #
def _publish_row(**over: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "code": "CJ-4200",
        "client_id": _CLIENT_ID,
        "client_name": "Verde Cafe",
        "page_type": "blog",
        "topic": "best brunch in portland",
        "target": "WordPress",
        "status": "publishing",
        "draft_md": "# Best Brunch in Portland\n\nA grounded, reviewed draft body.\n\n- one\n- two\n",
        "qa_score": {"passed": True, "blocked_by": [], "weighted_total": 91},
        "wp_post_id": None,
    }
    row.update(over)
    return row


class _SpyWordPress:
    """Records the PostDraft it was handed so a test can prove UPDATE vs CREATE."""

    def __init__(self) -> None:
        self.published: list[tuple[str, PostDraft]] = []

    def publish(self, site_url: str, post: PostDraft) -> PublishResult:
        self.published.append((site_url, post))
        post_id = post.wp_post_id if post.wp_post_id is not None else 777
        return PublishResult(post_id=post_id, url=f"{site_url}/{post.slug}")


def _wp_resolver(publisher: Any, site_url: str = "https://verde.example") -> Any:
    return lambda row, settings: WpTarget(site_url=site_url, publisher=publisher)


def test_publish_not_blocked_by_failing_qa() -> None:
    # QA is ADVISORY (product decision): a sub-threshold draft still publishes - the
    # human review gate already approved it, so the automated scorecard no longer blocks.
    store = FakeContentStore(
        _publish_row(qa_score={"passed": False, "blocked_by": ["fact_grounding"], "weighted_total": 60})
    )
    spy = _SpyWordPress()

    out = publish_content_job(
        store, None, "CJ-4200", settings=_settings(), resolve_wp=_wp_resolver(spy)
    )

    assert out.state == "published"           # published despite the failing QA score
    assert len(spy.published) == 1
    assert store.row["status"] == "done"


def test_publish_not_blocked_when_no_qa_score() -> None:
    # An unscored job (empty qa_score) also publishes - QA is advisory, not a gate.
    store = FakeContentStore(_publish_row(qa_score={}))
    spy = _SpyWordPress()
    out = publish_content_job(store, None, "CJ-4200", settings=_settings(), resolve_wp=_wp_resolver(spy))
    assert out.state == "published"
    assert store.row["status"] == "done"


def test_publish_passes_to_wordpress() -> None:
    store = FakeContentStore(_publish_row())
    out = publish_content_job(
        store, None, "CJ-4200",
        settings=_settings(), resolve_wp=_wp_resolver(FakeWordPressPublisher()),
    )
    assert out.state == "published"
    assert out.status == "done"
    assert store.row["status"] == "done"
    assert store.row["stage"].startswith("Draft on WordPress")  # carries the post URL when present
    assert store.row["wp_post_id"]  # recorded for idempotent re-publish
    assert out.url
    # The live URL is surfaced on the wire-visible stage label for the dashboard.
    assert out.url in store.row["stage"]


def test_publish_wordpress_idempotent_update_reuses_post_id() -> None:
    # A job that already carries a wp_post_id must UPDATE that same post.
    store = FakeContentStore(_publish_row(wp_post_id="4242"))
    spy = _SpyWordPress()

    out = publish_content_job(
        store, None, "CJ-4200", settings=_settings(), resolve_wp=_wp_resolver(spy)
    )

    assert out.wp_post_id == 4242  # reused, not a fresh id
    assert len(spy.published) == 1
    _site, post = spy.published[0]
    assert post.wp_post_id == 4242  # the draft carried the existing id -> UPDATE
    assert store.row["wp_post_id"] == "4242"


def test_publish_pdf_markdown_renders_and_never_leaks_path(tmp_path: Any) -> None:
    from app.services.content_artifacts import LocalContentArtifactStore

    artifacts = LocalContentArtifactStore(tmp_path)
    store = FakeContentStore(_publish_row(target="PDF/Markdown"))

    out = publish_content_job(
        store, None, "CJ-4200", settings=_settings(), artifacts=artifacts,
    )

    assert out.state == "published"
    assert store.row["status"] == "done"
    assert store.row["md_path"] == "CJ-4200/content.md"
    assert store.row["pdf_path"] == "CJ-4200/content.pdf"
    # The files really exist and the PDF is a real PDF.
    md_file = artifacts.resolve(store.row["md_path"])
    pdf_file = artifacts.resolve(store.row["pdf_path"])
    assert md_file is not None and md_file.is_file()
    assert pdf_file is not None and pdf_file.read_bytes().startswith(b"%PDF")
    # A traversal key is REFUSED (the path is never leaked outside the root).
    assert artifacts.resolve("../../etc/passwd") is None
    assert artifacts.resolve("/etc/passwd") is None


def test_publish_degraded_no_wp_creds_is_artifact_only(tmp_path: Any) -> None:
    from app.services.content_artifacts import LocalContentArtifactStore

    artifacts = LocalContentArtifactStore(tmp_path)
    store = FakeContentStore(_publish_row(target="WordPress"))

    out = publish_content_job(
        store, None, "CJ-4200",
        settings=_settings(), artifacts=artifacts,
        resolve_wp=lambda row, settings: None,  # no per-site WP credential
    )

    assert out.state == "degraded"
    assert out.status == "done"  # still delivers an artifact, never crashes
    assert store.row["md_path"] == "CJ-4200/content.md"
    assert "artifact-only" in store.row["stage"].lower()


def test_publish_done_is_noop() -> None:
    store = FakeContentStore(_publish_row(status="done"))
    out = publish_content_job(store, None, "CJ-4200", settings=_settings())
    assert out.state == "noop"
    assert store.updates == []


def test_publish_not_publishing_is_noop() -> None:
    store = FakeContentStore(_publish_row(status="needs_review"))
    out = publish_content_job(store, None, "CJ-4200", settings=_settings())
    assert out.state == "noop"
    assert store.updates == []


# --------------------------------------------------------------------------- #
# Per-client WordPress Connections registry (0058): resolve the RIGHT client's
# connection at publish time + publish through its auth method.
# --------------------------------------------------------------------------- #
def _connection_resolver(targets: dict[str, ClientWpTarget]) -> Any:
    """A resolve_client_wp that returns the target for the JOB's client_id (the exact
    per-client resolution the worker does), or None when that client has none."""
    return lambda row, settings: targets.get(str(row.get("client_id")))


def test_publish_via_client_connection_plugin() -> None:
    # A 'plugin' connection pushes to the AIOS Publisher plugin (draft) + records URLs.
    from integrations.wordpress_publisher import FakeWordPressPluginPublisher

    plugin = FakeWordPressPluginPublisher(site_url="https://verde.test")
    target = ClientWpTarget("plugin", "https://verde.test", plugin=plugin)
    store = FakeContentStore(_publish_row())
    out = publish_content_job(
        store, None, "CJ-4200", settings=_settings(),
        resolve_client_wp=_connection_resolver({_CLIENT_ID: target}),
    )
    assert out.state == "published"
    assert store.row["status"] == "done"
    assert plugin.published  # the draft was pushed to the plugin
    assert store.row["wp_url"] and store.row["wp_edit_url"]  # the plugin URLs recorded


def test_publish_via_client_connection_app_password() -> None:
    # An 'app_password' connection publishes over the REST WordPressPublisher.
    spy = _SpyWordPress()
    target = ClientWpTarget("app_password", "https://verde.test", publisher=spy)
    store = FakeContentStore(_publish_row())
    out = publish_content_job(
        store, None, "CJ-4200", settings=_settings(),
        resolve_client_wp=_connection_resolver({_CLIENT_ID: target}),
    )
    assert out.state == "published" and store.row["status"] == "done"
    assert len(spy.published) == 1
    site, _post = spy.published[0]
    assert site == "https://verde.test"


def test_publish_via_client_connection_xmlrpc() -> None:
    # An 'xmlrpc' connection publishes over the XML-RPC WordPressPublisher (same
    # Protocol) - proven here with a spy that satisfies publish(site_url, post).
    spy = _SpyWordPress()
    target = ClientWpTarget("xmlrpc", "https://hostile.test", publisher=spy)
    store = FakeContentStore(_publish_row())
    out = publish_content_job(
        store, None, "CJ-4200", settings=_settings(),
        resolve_client_wp=_connection_resolver({_CLIENT_ID: target}),
    )
    assert out.state == "published"
    assert spy.published[0][0] == "https://hostile.test"
    assert out.url  # the live URL surfaced on the stage label


def test_publish_resolves_the_right_connection_per_client() -> None:
    # TWO clients, each with its OWN connection/site: each job must publish to ITS site.
    verde, other = _SpyWordPress(), _SpyWordPress()
    targets = {
        _CLIENT_ID: ClientWpTarget("app_password", "https://verde.test", publisher=verde),
        _OTHER_ID: ClientWpTarget("xmlrpc", "https://other.test", publisher=other),
    }
    resolver = _connection_resolver(targets)

    store_v = FakeContentStore(_publish_row(code="CJ-4200", client_id=_CLIENT_ID))
    store_o = FakeContentStore(_publish_row(code="CJ-4300", client_id=_OTHER_ID))
    publish_content_job(store_v, None, "CJ-4200", settings=_settings(), resolve_client_wp=resolver)
    publish_content_job(store_o, None, "CJ-4300", settings=_settings(), resolve_client_wp=resolver)

    # Each client's draft went to ITS OWN site, never the other's.
    assert verde.published[0][0] == "https://verde.test"
    assert other.published[0][0] == "https://other.test"
    assert len(other.published) == 1 and len(verde.published) == 1


def test_publish_degrades_cleanly_when_no_connection(tmp_path: Any) -> None:
    # No per-client connection AND no legacy vault target -> artifact-only degrade
    # (the clean "skip the push" the task describes), never a crash.
    from app.services.content_artifacts import LocalContentArtifactStore

    store = FakeContentStore(_publish_row())
    out = publish_content_job(
        store, None, "CJ-4200", settings=_settings(), artifacts=LocalContentArtifactStore(tmp_path),
        resolve_client_wp=lambda row, settings: None,  # no connection configured
        resolve_wp=lambda row, settings: None,          # no legacy vault credential
    )
    assert out.state == "degraded" and store.row["status"] == "done"
    assert "artifact-only" in store.row["stage"].lower()


# --------------------------------------------------------------------------- #
# build_client_wp_target: the pure method->adapter dispatch (no DB, no network).
# --------------------------------------------------------------------------- #
def _resolved(method: str, *, secret: str = "s", site: str = "https://verde.test") -> ResolvedWpConnection:
    return ResolvedWpConnection(
        client_id=_CLIENT_ID, site_url=site, auth_method=method, username="editor", secret=secret
    )


def test_build_client_wp_target_dispatches_by_method() -> None:
    s = _settings()
    plugin = build_client_wp_target(_resolved("plugin"), s)
    assert plugin is not None and plugin.method == "plugin" and plugin.plugin is not None

    xml = build_client_wp_target(_resolved("xmlrpc"), s)
    assert xml is not None and xml.method == "xmlrpc" and isinstance(xml.publisher, XmlRpcWordPressPublisher)

    rest = build_client_wp_target(_resolved("app_password"), s)
    assert rest is not None and rest.method == "app_password" and rest.publisher is not None


def test_build_client_wp_target_none_without_site_or_secret() -> None:
    assert build_client_wp_target(_resolved("plugin", site=""), _settings()) is None
    assert build_client_wp_target(_resolved("plugin", secret=""), _settings()) is None


# --------------------------------------------------------------------------- #
# XmlRpcWordPressPublisher: parses wp.newPost + strips a hostile-host HTML footer.
# --------------------------------------------------------------------------- #
def test_xmlrpc_publish_parses_post_id_and_strips_trailing_html() -> None:
    import xmlrpc.client

    # A valid XML-RPC response returning the new post id, with junk a hostile host
    # appended AFTER </methodResponse> (a WAF/cache footer) - which must be trimmed.
    valid = xmlrpc.client.dumps(("9137",), methodresponse=True)
    body = valid + "\n<!-- cache -->\n<html>blocked-notice</html>"

    class _Resp:
        status_code = 200
        text = body

    class _FakeHttp:
        def __init__(self) -> None:
            self.posted: list[bytes] = []

        def post(self, url: str, content: bytes) -> _Resp:
            self.posted.append(content)
            return _Resp()

    pub = XmlRpcWordPressPublisher(username="editor", app_password="pw")
    fake = _FakeHttp()
    pub._client = fake  # type: ignore[assignment]  # inject the fake transport
    result = pub.publish("https://hostile.test", PostDraft(title="Hello", content="<p>Body</p>"))
    assert result.post_id == 9137
    assert result.url == "https://hostile.test/?p=9137"
    # The credential rode in the XML BODY (never a header).
    assert b"editor" in fake.posted[0] and b"wp.newPost" in fake.posted[0]


# --------------------------------------------------------------------------- #
# The minimal Markdown->HTML render used for the WordPress body.
# --------------------------------------------------------------------------- #
def test_md_to_html_covers_headings_lists_links() -> None:
    html = md_to_html("# Title\n\nA [link](https://x.test) and **bold**.\n\n- a\n- b\n")
    assert "<h1>Title</h1>" in html
    assert '<a href="https://x.test">link</a>' in html
    assert "<strong>bold</strong>" in html
    assert "<ul><li>a</li><li>b</li></ul>" in html


# --------------------------------------------------------------------------- #
# All-way comms: the content worker's cross-actor email legs.
# --------------------------------------------------------------------------- #
def test_content_needs_review_notifies_the_leads(monkeypatch: pytest.MonkeyPatch) -> None:
    # TEAM/WORKER -> LEAD: when the pipeline reaches the review gate it fans a
    # content_review notification out to the leads who own the sign-off.
    import workers.tasks.content as content_mod

    calls: list[tuple[Any, ...]] = []
    monkeypatch.setattr(content_mod, "notify_leads_sync", lambda *a, **k: calls.append(a))

    store = FakeContentStore(_job_row())
    out = execute_content_job(
        store, content_providers_for_tests(), "CJ-4200",
        settings=_settings(), gate=_gate(), fetcher=FakePageFetcher(),
    )
    assert out.status == "needs_review"
    assert calls and calls[0][0] == "content_review"
    assert "best brunch in portland" in calls[0][1]  # the topic is in the subject


def test_content_published_emails_the_client(monkeypatch: pytest.MonkeyPatch) -> None:
    # ADMIN/LEAD -> CLIENT: publishing content emits a portal deliverable AND emails
    # the client that new content is live.
    import workers.tasks.content as content_mod

    client_calls: list[tuple[Any, ...]] = []
    monkeypatch.setattr(content_mod, "email_client_sync", lambda *a, **k: client_calls.append(a))
    monkeypatch.setattr(content_mod, "emit_deliverable", lambda **k: None)

    content_mod._emit_content_deliverable(
        {"client_id": _CLIENT_ID, "client_name": "Verde Cafe", "topic": "Spring Menu", "id": "j1"},
        artifact_key="CJ-4200/content.pdf",
    )
    assert client_calls and client_calls[0][0] == _CLIENT_ID
    assert "Spring Menu" in client_calls[0][1]  # subject carries the topic


def test_content_published_no_client_is_noop(monkeypatch: pytest.MonkeyPatch) -> None:
    import workers.tasks.content as content_mod

    client_calls: list[tuple[Any, ...]] = []
    monkeypatch.setattr(content_mod, "email_client_sync", lambda *a, **k: client_calls.append(a))
    monkeypatch.setattr(content_mod, "emit_deliverable", lambda **k: None)
    # An unlinked job (no client_id) neither emits a deliverable nor emails anyone.
    content_mod._emit_content_deliverable({"topic": "X"}, artifact_key=None)
    assert client_calls == []
