"""The ``campaign_content`` graph: drafting a Web 2.0 property as resumable graph state.

THE TEST THAT JUSTIFIES THE WHOLE PHASE is
``test_resuming_a_parked_run_replays_no_model_call``. Drafting one property is not one
model call - ``content_generator.generate()`` fans out roughly a dozen - and the linear
pipeline writes to the database only at the very end. So a worker that dies late in
property 19 of a thirty-property campaign has spent real money and has nothing: the row
is still ``draft`` and the retry redrafts from the first section. The checkpoint is what
makes the second visit cost nothing.

Everything else here guards the properties the linear path already had, because a graph
that publishes more eagerly than ``web2_pipeline`` would be a downgrade wearing a new
architecture: a redelivered job is still a no-op, a cost block still spends nothing and
still leaves the row retryable, a draft still parks for a human, and a rejection still
publishes nothing.

These run on an IN-MEMORY checkpointer and deterministic fakes - no Postgres, no keys, no
network - which is the property §2 says makes graphs testable at all.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.config import Settings
from app.platform.ai import graph as graph_runtime
from app.platform.ai.router import ModelRouter, SummarizerBackend
from app.platform.ai.tiers import TaskTier
from app.services.cost_gate import CostGate, GateContext
from app.services.web2_pipeline import SimilarityOutcome, Web2Client
from integrations.llm import FakeSummarizer

pytest.importorskip("langgraph", reason="the graph path needs the optional [graph] extra")

from app.modules.web2.graphs import campaign_content as cc

pytestmark = pytest.mark.unit


# --------------------------------------------------------------------------- #
# Fakes
# --------------------------------------------------------------------------- #
class FakeStore:
    """The ``Web2Store`` seam, recording every write so a test can assert on ORDER."""

    def __init__(self, **row: Any) -> None:
        base = {
            "id": "w1", "status": "draft", "client_id": "c1", "client_name": "Acme Drains",
            "platform": "Blogger", "anchor": "Acme Drains",
            "target_url": "https://acme.test/drain-survey", "topic": "cctv drain survey",
            "page_type": "blog", "framework": "Auto",
        }
        base.update(row)
        self.row = base
        self.writes: list[dict[str, Any]] = []

    def load_web2(self, web2_id: str) -> dict[str, Any] | None:
        return dict(self.row) if web2_id == self.row["id"] else None

    def update_web2(self, web2_id: str, fields: dict[str, Any]) -> None:
        self.row.update(fields)
        self.writes.append(dict(fields))

    @property
    def statuses(self) -> list[str]:
        return [w["status"] for w in self.writes if "status" in w]


class FakeCostStore:
    def __init__(self, *, halted: bool = False) -> None:
        self.halted = halted
        self.committed: list[float] = []

    def dial_mode(self, feature_key: str) -> Any:
        return "on"

    def client_budget(self, client_id: str) -> tuple[float, float] | None:
        return None

    def is_halted(self) -> bool:
        return self.halted

    def record_cost(self, ctx: GateContext, cost: float, *, cached: bool) -> None:
        self.committed.append(cost)


class _NullCache:
    def get(self, key: str) -> Any | None:
        return None

    def set(self, key: str, value: Any) -> None:
        return None


def _router(*, halted: bool = False) -> tuple[ModelRouter, FakeCostStore]:
    store = FakeCostStore(halted=halted)
    gate = CostGate(store, _NullCache())
    return ModelRouter(SummarizerBackend(FakeSummarizer()), gate, _settings()), store


def _settings() -> Settings:
    # No database_url: the runtime resolves to the in-memory checkpointer, which is what
    # a unit test wants and which the runtime reports honestly as non-durable.
    return Settings(app_env="dev", database_url=None, database_admin_url=None)


def _passing_similarity(**_: Any) -> SimilarityOutcome:
    return SimilarityOutcome("pass", "", "")


def _capabilities(_platform: str) -> dict[str, Any]:
    return {"mechanism": "api", "authority_tier": "high", "terms_position": "permits"}


def _client() -> Web2Client:
    return Web2Client(client_id="c1", name="Acme Drains", geo="Leeds")


def _memory_saver() -> Any:
    """One in-memory checkpointer shared across a draft and its resume.

    A saver opened per call would not survive to the second one - which is precisely the
    condition ``GraphThreadMissing`` exists to report, and which
    ``test_resuming_without_a_surviving_checkpoint_refuses`` asserts separately.
    """
    from langgraph.checkpoint.memory import InMemorySaver

    return InMemorySaver()


def _run(store: FakeStore, router: ModelRouter | None, **kwargs: Any) -> dict[str, Any]:
    return cc.draft_property(
        store.row["id"], store=store, router=router, settings=_settings(),
        similarity=kwargs.pop("similarity", _passing_similarity),
        client=kwargs.pop("client", _client()),
        capabilities=kwargs.pop("capabilities", _capabilities), **kwargs,
    )


# --------------------------------------------------------------------------- #
# The happy path: draft, then PARK for a human
# --------------------------------------------------------------------------- #
def test_a_drafted_property_parks_for_a_human_and_never_publishes_itself() -> None:
    """Parking IS the success condition. A Web 2.0 property is white-hat authority work
    precisely because a lead approves it; a graph that ran on to publish would have
    removed the one control that makes the module defensible."""
    store = FakeStore()
    router, _ = _router()

    result = _run(store, router)

    assert graph_runtime.parked(result) is True
    assert store.row["status"] == "needs_review"
    assert "published" not in store.statuses
    assert result["body_md"], "the article must exist by the time a human is asked"
    assert result["word_count"] > 0


def test_the_review_payload_carries_what_a_lead_needs_to_decide() -> None:
    """The interrupt value is what the review screen renders. A gate that shows an
    article but not its similarity verdict, its grounding gaps or its cost is asking for
    a decision without the facts the decision turns on."""
    store = FakeStore()
    router, _ = _router()

    payload = graph_runtime.interrupt_payload(_run(store, router))

    assert payload is not None
    for key in (
        "web2_id", "platform", "topic", "anchor", "target_url", "word_count",
        "publishable", "needs", "similarity_verdict", "estimated_spend_usd",
    ):
        assert key in payload, f"the review payload must carry {key}"


def test_every_model_call_is_metered_and_the_spend_lands_on_the_state() -> None:
    store = FakeStore()
    router, cost_store = _router()

    result = _run(store, router)

    assert router.calls > 1, "drafting fans out across sections; one call would be a bug"
    assert len(cost_store.committed) == router.calls
    assert result["spent_usd"] == pytest.approx(sum(cost_store.committed), rel=1e-6)


def test_the_platform_shaping_node_runs_on_the_structured_tier() -> None:
    """The one genuinely new stage. It exists because v1 posted the same 900-word blog
    article to a developer community, a microblog and a paste site - individually fine,
    collectively a clearer footprint than any content-level check can see."""
    store = FakeStore()
    router, _ = _router()
    seen: list[TaskTier] = []
    original = router.complete

    def spy(request: Any) -> Any:
        seen.append(request.task)
        return original(request)

    router.complete = spy  # type: ignore[method-assign]
    result = _run(store, router)

    assert seen[0] is TaskTier.STRUCTURED, "shaping is a structured call, not a draft"
    assert all(t is TaskTier.DRAFTING for t in seen[1:])
    assert result["platform_shape"]


# --------------------------------------------------------------------------- #
# THE point of the phase: resumption
# --------------------------------------------------------------------------- #
def test_resuming_a_parked_run_replays_no_model_call() -> None:
    """The test the whole phase exists for.

    A second router stands in for a second PROCESS - the approval endpoint is not the
    worker that drafted. Resuming must reach the decision point with the draft, the
    similarity verdict and the spend already in state: nothing re-derived, nothing
    re-paid for. If this ever regresses, the checkpoint is decorative.
    """
    store = FakeStore()
    saver = _memory_saver()
    drafting_router, _ = _router()
    first = _run(store, drafting_router, checkpointer=saver)
    assert graph_runtime.parked(first)
    drafted_body = first["body_md"]

    approving_router, approving_costs = _router()
    final = cc.resume_with_decision(
        store.row["id"], approved=True, note="reads well",
        store=store, router=approving_router, settings=_settings(),
        similarity=_passing_similarity, client=_client(), capabilities=_capabilities,
        checkpointer=saver,
    )

    assert approving_router.calls == 0, "a resume must not redraft a single section"
    assert approving_costs.committed == [], "and must not spend a cent"
    assert final["body_md"] == drafted_body
    assert final["approved"] is True
    assert final["review_note"] == "reads well"
    assert store.row["status"] == "publishing"


def test_a_rejection_publishes_nothing_and_records_the_reason() -> None:
    store = FakeStore()
    saver = _memory_saver()
    router, _ = _router()
    _run(store, router, checkpointer=saver)

    final = cc.resume_with_decision(
        store.row["id"], approved=False, note="the second section is wrong",
        store=store, router=router, settings=_settings(),
        similarity=_passing_similarity, client=_client(), capabilities=_capabilities,
        checkpointer=saver,
    )

    assert final["status"] == "rejected"
    assert store.row["status"] == "rejected"
    assert "the second section is wrong" in store.row["error"]
    assert "publishing" not in store.statuses


# --------------------------------------------------------------------------- #
# The guards the linear path already had, kept
# --------------------------------------------------------------------------- #
def test_a_redelivered_job_is_a_no_op_and_spends_nothing() -> None:
    """At-least-once delivery is a property of the broker, not of the graph. A row that
    is no longer ``draft`` has already been paid for once."""
    store = FakeStore(status="needs_review")
    router, cost_store = _router()

    result = _run(store, router)

    assert result["status"] == "unchanged"
    assert router.calls == 0
    assert cost_store.committed == []
    assert store.writes == []


def test_a_missing_row_ends_the_run_without_touching_a_provider() -> None:
    store = FakeStore()
    router, _ = _router()
    result = cc.draft_property(
        "does-not-exist", store=store, router=router, settings=_settings(),
        similarity=_passing_similarity, client=_client(),
    )
    assert result["status"] == "error"
    assert router.calls == 0


def test_a_cost_block_leaves_the_row_retryable_and_writes_nothing() -> None:
    """A block mid-draft must not persist a half-written article. The row stays at
    ``draft`` so the retry is clean - never a half-billed, half-written draft."""
    store = FakeStore()
    router, cost_store = _router(halted=True)

    result = _run(store, router)

    assert result["status"] == "blocked"
    assert "spend_blocked" in result["error"]
    assert cost_store.committed == []
    assert store.writes == [], "nothing may be persisted when the gate refused"
    assert store.row["status"] == "draft", "and the row stays retryable"
    assert graph_runtime.parked(result) is False, "a blocked run is not awaiting a human"


def test_without_a_router_the_property_holds_at_review_rather_than_failing() -> None:
    """Every provider seam in this repo degrades. A keyless deployment holds the
    placement for a human, it does not crash a worker.

    And the DATABASE must say so too. The graph ends without reaching `persist_draft`
    here (there is no article to review), so the degrade is written by the draft node
    itself - otherwise the row would sit at `draft` while the outcome reported
    `needs_review`, and the operator's board would show a property still queued for
    drafting with nothing anywhere saying the reason is a missing key.
    """
    store = FakeStore()
    result = _run(store, None)

    assert result["status"] == "needs_review"
    assert "unconfigured" in result["error"]
    assert graph_runtime.parked(result) is False
    assert store.row["status"] == "needs_review", "the row must not be left at 'draft'"
    assert "unconfigured" in store.row["error"], "and must say why it is held"


def test_the_similarity_verdict_is_recorded_alongside_a_grounding_gap() -> None:
    """Both findings are kept, similarity FIRST.

    v1 records why the order is load-bearing: the approval guard matches on the ``sim_``
    prefix, so writing ``gap_error or sim.code`` meant a duplicate that happened to be
    gappy carried no similarity code at all and skipped the guard entirely.
    """
    store = FakeStore()
    router, _ = _router()

    def blocking(**_: Any) -> SimilarityOutcome:
        return SimilarityOutcome("block", "sim_block:body:client:w0", "too similar")

    result = _run(store, router, similarity=blocking)

    assert result["error"].startswith("sim_block:")
    assert store.row["error"].startswith("sim_block:")


def test_an_unwired_similarity_checker_is_unavailable_not_a_pass() -> None:
    """"The gate could not run" must stay distinguishable from "the gate approved it" -
    the approval endpoint treats ``unavailable`` as a refusal."""
    store = FakeStore()
    router, _ = _router()

    result = _run(store, router, similarity=None)

    assert result["similarity_verdict"] == "unavailable"
    assert "sim_unavailable" in result["error"]


# --------------------------------------------------------------------------- #
# Capability notes
# --------------------------------------------------------------------------- #
def test_an_uncatalogued_platform_is_described_as_unknown_not_guessed() -> None:
    """A writer told nothing produces a plain article. A writer told an invented
    convention produces one that is wrong in a way nobody traces back to here."""
    note = cc.capability_note("Some New Blog", None)
    assert "no measured capability row" in note
    assert "assume nothing" in note


def test_a_catalogued_platform_renders_only_the_facts_the_row_holds() -> None:
    note = cc.capability_note(
        "Blogger", {"mechanism": "api", "terms_position": "permits", "authority_tier": ""}
    )
    assert "mechanism: api" in note
    assert "terms_position: permits" in note
    assert "authority_tier" not in note, "an empty field is not a fact"


def test_the_draft_only_note_fires_for_a_draft_only_platform() -> None:
    """The note is driven by ``DRAFT_ONLY_PLATFORMS``, which is now EMPTY - Medium was
    its only member and A12 reclassified it as `unsupported`, a stronger statement.

    The note stays because the behaviour is real and the next draft-only platform must
    tell its writer so. Asserted by driving the set rather than by naming a platform, so
    this does not have to be rewritten again the next time membership changes.
    """
    import integrations.web2_publishers as pub

    assert frozenset() == pub.DRAFT_ONLY_PLATFORMS, "Medium left; nothing replaced it yet"

    original = pub.DRAFT_ONLY_PLATFORMS
    try:
        pub.DRAFT_ONLY_PLATFORMS = frozenset({"Somewhere"})  # type: ignore[misc]
        cc.DRAFT_ONLY_PLATFORMS = pub.DRAFT_ONLY_PLATFORMS  # type: ignore[misc]
        assert "DRAFT only" in cc.capability_note("Somewhere", {"mechanism": "api"})
    finally:
        pub.DRAFT_ONLY_PLATFORMS = original  # type: ignore[misc]
        cc.DRAFT_ONLY_PLATFORMS = original  # type: ignore[misc]


def test_the_thread_id_is_stable_for_a_property_and_distinct_between_them() -> None:
    """Equal to the job's idempotency identity, which is what makes a redelivered job
    attach to its OWN run instead of forking a second one beside it."""
    assert cc.thread_for("w1") == cc.thread_for("w1")
    assert cc.thread_for("w1") != cc.thread_for("w2")


def test_resuming_without_a_surviving_checkpoint_refuses_rather_than_redrafting() -> None:
    """The failure mode that made ``GraphThreadMissing`` necessary.

    LangGraph treats a resume against a missing thread as a FRESH RUN on whatever input
    it was handed. Here that means the approval endpoint, trying to apply a lead's
    decision, would instead re-enter at the first node and re-draft the article - a
    second bill for work already paid for - or die inside the state schema complaining
    about a field the caller never supplied. Neither is an acceptable way to learn that
    the draft ran on an in-memory saver. A caller that gets this error falls back to the
    linear approval path, which still works: the row is in Postgres.
    """
    store = FakeStore()
    router, _costs = _router()
    _run(store, router, checkpointer=_memory_saver())
    calls_after_draft = router.calls

    with pytest.raises(graph_runtime.GraphThreadMissing) as caught:
        cc.resume_with_decision(
            store.row["id"], approved=True, store=store, router=router,
            settings=_settings(), similarity=_passing_similarity, client=_client(),
            capabilities=_capabilities, checkpointer=_memory_saver(),
        )

    assert "in-memory checkpointer" in str(caught.value)
    assert router.calls == calls_after_draft, "a refused resume must redraft nothing"
