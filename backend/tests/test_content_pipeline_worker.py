"""The doctrine engine's worker core: what it writes, and what it refuses to write.

Driven entirely through injected doubles - no database, no provider, no broker -
so these assertions are about the ENGINE's behaviour, not about infrastructure.

The three behaviours that matter most here are the ones a screen will be built
on: a halt is not a failure, a redelivery does not draft twice, and the row says
which stage is running while it is running rather than after it finished.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.config import get_settings
from app.services.content_pipeline.context import PipelineContext, StageResult
from workers.tasks.content_pipeline import (
    STAGE_LABEL,
    PipelineDeps,
    execute_pipeline_job,
)

pytestmark = pytest.mark.unit


class _Store:
    """A ContentStore double that remembers every write, in order."""

    def __init__(self, row: dict[str, Any] | None) -> None:
        self.row = dict(row) if row else None
        self.writes: list[dict[str, Any]] = []

    def load(self, code: str) -> dict[str, Any] | None:
        return dict(self.row) if self.row is not None else None

    def update(self, code: str, fields: dict[str, Any]) -> dict[str, Any] | None:
        self.writes.append(dict(fields))
        if self.row is not None:
            self.row.update(fields)
        return dict(self.row) if self.row is not None else None

    @property
    def stages(self) -> list[str]:
        return [w["stage"] for w in self.writes if "stage" in w]

    def final(self, key: str) -> Any:
        for write in reversed(self.writes):
            if key in write:
                return write[key]
        return None


class _Planning:
    """Planning-store double: records engagements it was asked to create."""

    def __init__(self, *, fails: bool = False) -> None:
        self.created: list[dict[str, Any]] = []
        self._fails = fails

    def create_engagement(self, **kwargs: Any) -> Any:
        if self._fails:
            raise RuntimeError("engagements table unreachable")
        self.created.append(dict(kwargs))
        return type("_E", (), {"id": "eng-new"})()


class _Gate:
    def evaluate(self, ctx: Any) -> Any:  # pragma: no cover - never consulted here
        raise AssertionError("the engine must not consult the gate directly")


def _row(**kw: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "id": "11111111-1111-1111-1111-111111111111",
        "code": "CJ-4200", "status": "queued", "client_id": "c-1",
        "client_name": "Dallas Plumbing", "page_type": "service",
        "topic": "Emergency plumbing in Dallas", "framework": "PAS",
        "engagement_id": "eng-1",
        "source_pack": {"primary_keyword": "emergency plumber dallas", "geo": "Dallas"},
    }
    base.update(kw)
    return base


@pytest.fixture(autouse=True)
def _scripted_stages(monkeypatch: pytest.MonkeyPatch) -> None:
    """Let a test script the stage set, and ALWAYS put the real one back.

    Patching the module attribute directly would leak the double into every test
    that runs after this file - the kind of cross-file contamination that makes a
    suite green in one order and red in another.
    """
    monkeypatch.setattr(
        "workers.tasks.content_pipeline.build_page_stages",
        lambda **kwargs: _SCRIPT["stages"],
    )


_SCRIPT: dict[str, Any] = {"stages": {}}


def _stage(name: str, outcome: str = "ok", **data: Any) -> Any:
    def run(ctx: PipelineContext) -> StageResult:
        return ctx.record(StageResult(name, outcome=outcome, data=data))  # type: ignore[arg-type]
    return run


def _run(store: _Store, stages: dict[str, Any], planning: Any | None = None) -> Any:
    _SCRIPT["stages"] = stages
    deps = PipelineDeps(store=store, planning=planning or _Planning())
    return execute_pipeline_job(deps, "CJ-4200", settings=get_settings(), gate=_Gate())


class TestARedeliveryNeverDraftsTwice:
    """The broker is at-least-once and drafting spends real money."""

    @pytest.mark.parametrize("status", ["drafting", "needs_review", "done", "failed"])
    def test_a_job_that_is_not_queued_is_a_no_op(self, status: str) -> None:
        store = _Store(_row(status=status))
        outcome = _run(store, {"gate": _stage("gate")})
        assert outcome.state == "noop"
        assert store.writes == [], "a redelivery must not touch the row"

    def test_a_missing_job_is_a_no_op_not_a_crash(self) -> None:
        store = _Store(None)
        outcome = _run(store, {"gate": _stage("gate")})
        assert outcome.state == "noop" and outcome.status == "unknown"


class TestAHaltIsNotAFailure:
    """Law 16. The Experience gate refusing to draft is the system working, so the
    job must not be marked failed, must not be retried, and must say what is
    outstanding - that is the only thing an operator can act on."""

    def test_an_experience_halt_holds_the_job_instead_of_failing_it(self) -> None:
        store = _Store(_row())
        outcome = _run(store, {
            "sme": _stage("sme", "halted", missing=["proof_metric", "photo"],
                          questions={"proof_metric": "q1", "photo": "q2"}),
        })
        assert outcome.status == "drafting", "a halt must never be written as failed"
        assert outcome.state == "deferred"
        assert store.final("status") == "drafting"
        assert store.final("experience_slots_missing") == 2

    def test_the_held_row_says_how_many_answers_are_outstanding(self) -> None:
        store = _Store(_row())
        _run(store, {"sme": _stage("sme", "halted", missing=["a", "b", "c"])})
        assert "3 to go" in store.stages[-1]

    def test_a_halt_does_not_write_a_draft(self) -> None:
        store = _Store(_row())
        _run(store, {"sme": _stage("sme", "halted", missing=["a"])})
        assert store.final("draft_md") is None


class TestTheRowSaysWhatIsRunningWhileItRuns:
    def test_each_stage_is_streamed_before_it_executes(self) -> None:
        store = _Store(_row())
        order: list[str] = []

        def watcher(name: str) -> Any:
            def run(ctx: PipelineContext) -> StageResult:
                # Whatever the row says right now must already be THIS stage.
                order.append(store.stages[-1])
                return ctx.record(StageResult(name, outcome="ok"))
            return run

        _run(store, {"sme": watcher("sme"), "gate": watcher("gate")})
        assert order == [STAGE_LABEL["sme"], STAGE_LABEL["gate"]]

    def test_every_declared_label_belongs_to_a_real_stage(self) -> None:
        from app.services.content_pipeline.runner import PAGE_STAGES

        assert set(STAGE_LABEL) == set(PAGE_STAGES), (
            "a label with no stage is a step that can never light up - the exact "
            "defect v1's fourteen-key table has"
        )


class TestAFinishedPageGoesToTheHumanGate:
    def test_a_clean_run_lands_on_needs_review_with_its_work_written(self) -> None:
        store = _Store(_row())

        def draft(ctx: PipelineContext) -> StageResult:
            ctx.draft_md = "# Emergency plumbing\n\nWe answered 412 calls last year."
            ctx.title = "Emergency Plumber Dallas"
            ctx.meta_description = "Same-day emergency plumbing in Dallas."
            return ctx.record(StageResult("draft", outcome="ok"))

        outcome = _run(store, {
            "draft": draft,
            "gate": _stage("gate", "ok", weighted_total=88.5, passed=True),
        })
        assert outcome.status == "needs_review" and outcome.state == "advanced"
        assert store.final("draft_md").startswith("# Emergency plumbing")
        assert store.final("words") == 9
        assert store.final("qa_weighted_total") == 88.5
        assert store.final("outline")["meta"]["title"] == "Emergency Plumber Dallas"
        assert outcome.passed is True

    def test_a_degraded_run_still_reaches_review_but_says_so(self) -> None:
        store = _Store(_row())

        def draft(ctx: PipelineContext) -> StageResult:
            ctx.draft_md = "body"
            return ctx.record(StageResult("draft", outcome="ok"))

        outcome = _run(store, {
            "research": _stage("research", "degraded"),
            "draft": draft,
            "gate": _stage("gate", "ok"),
        })
        assert outcome.status == "needs_review"
        assert outcome.state == "degraded"
        assert "degraded" in store.final("stage")

    def test_a_broken_stage_fails_the_job_honestly(self) -> None:
        store = _Store(_row())
        outcome = _run(store, {"draft": _stage("draft", "failed")})
        assert outcome.status == "failed" and store.final("status") == "failed"


class TestAJobWithoutAnEngagementGetsOne:
    """Nothing in the product writes `content_engagements`. Without this the SME
    gate halts every single page with "no engagement" - a reason the operator can
    do absolutely nothing about, forever."""

    def test_an_engagement_is_created_and_stamped_on_the_job(self) -> None:
        store = _Store(_row(engagement_id=None))
        planning = _Planning()
        _run(store, {"gate": _stage("gate")}, planning)
        assert planning.created, "a job with no engagement must get one"
        assert planning.created[0]["shape"] == "single_page"
        assert store.final("engagement_id") == "eng-new"

    def test_an_existing_engagement_is_reused_not_duplicated(self) -> None:
        store = _Store(_row(engagement_id="eng-1"))
        planning = _Planning()
        _run(store, {"gate": _stage("gate")}, planning)
        assert planning.created == [], "a second engagement would open a second dossier"

    def test_an_engagement_that_cannot_be_created_does_not_crash_the_job(self) -> None:
        store = _Store(_row(engagement_id=None))
        outcome = _run(store, {"gate": _stage("gate")}, _Planning(fails=True))
        # Any terminal verdict is fine; the point is that an unavailable
        # engagements table degrades the run instead of raising out of the task.
        assert outcome.state in ("advanced", "deferred", "degraded"), "must degrade, not raise"
        assert outcome.status != "failed"


class TestTheClientsOwnPhoneNumberReachesThePage:
    """Found by running the engine: the conversion stage requires a tappable
    `tel:` link, the draft stage may state nothing outside the supplied facts, and
    the client's phone number was in neither - so the writer had to invent a
    number or fail that check on every page, forever."""

    def test_the_stored_nap_becomes_first_party_facts(self) -> None:
        from workers.tasks.content_pipeline import nap_facts

        facts = nap_facts({
            "phone": "214-555-0142", "website_url": "https://ortizplumbing.com",
            "address_line1": "1820 Greenville Ave", "city": "Dallas",
            "postal_code": "75206",
        })
        assert "phone: 214-555-0142" in facts
        assert any(f.startswith("address: 1820 Greenville Ave, Dallas, 75206") for f in facts)

    def test_a_half_filled_profile_contributes_only_what_it_has(self) -> None:
        from workers.tasks.content_pipeline import nap_facts

        facts = nap_facts({"phone": "214-555-0142", "website_url": "", "city": ""})
        assert facts == ("phone: 214-555-0142",), "blank fields must not be asserted"

    def test_no_profile_adds_nothing_rather_than_blank_facts(self) -> None:
        from workers.tasks.content_pipeline import nap_facts

        assert nap_facts(None) == () and nap_facts({}) == ()

    def test_the_facts_are_appended_to_what_the_experience_gate_collected(self) -> None:
        store = _Store(_row())
        seen: dict[str, Any] = {}

        def sme(ctx: PipelineContext) -> StageResult:
            ctx.facts = ("count_source: 412 callouts in 2025",)
            return ctx.record(StageResult("sme", outcome="ok"))

        def draft(ctx: PipelineContext) -> StageResult:
            seen["facts"] = ctx.facts       # what the WRITER would be given
            ctx.draft_md = "body"
            return ctx.record(StageResult("draft", outcome="ok"))

        _SCRIPT["stages"] = {"sme": sme, "draft": draft}
        deps = PipelineDeps(
            store=store, planning=_Planning(), nap={"phone": "214-555-0142"},
        )
        execute_pipeline_job(deps, "CJ-4200", settings=get_settings(), gate=_Gate())
        assert "count_source: 412 callouts in 2025" in seen["facts"]
        assert "phone: 214-555-0142" in seen["facts"]

    def test_a_halted_experience_gate_does_not_get_nap_facts_appended(self) -> None:
        """Nothing is being written, so there is nothing to ground."""
        store = _Store(_row())
        captured: dict[str, Any] = {}

        def sme(ctx: PipelineContext) -> StageResult:
            result = ctx.record(StageResult("sme", outcome="halted", data={"missing": ["photo"]}))
            captured["facts"] = ctx.facts
            return result

        _SCRIPT["stages"] = {"sme": sme}
        deps = PipelineDeps(store=store, planning=_Planning(), nap={"phone": "214-555-0142"})
        execute_pipeline_job(deps, "CJ-4200", settings=get_settings(), gate=_Gate())
        assert captured["facts"] == ()


class TestAPageThatWasNeverWrittenDoesNotReachAHuman:
    """Found by running a real job: a degraded outline stops the pipeline before a
    word exists, and that used to persist as `needs_review` - putting an EMPTY
    draft in front of a lead and asking them to approve it onto a client's site.
    `needs_review` must mean a human has something to read."""

    def test_a_run_with_no_draft_holds_instead_of_queueing_for_review(self) -> None:
        store = _Store(_row())
        outcome = _run(store, {
            "outline": _stage("outline", "degraded"),
        })
        assert outcome.status == "drafting", "an empty page must not reach the review queue"
        assert store.final("status") != "needs_review"
        assert "Held" in store.final("stage")

    def test_the_hold_says_why_on_the_row(self) -> None:
        store = _Store(_row())
        _run(store, {"outline": _stage("outline", "degraded")})
        assert "outline" in store.final("stage").lower()

    def test_a_run_that_produced_a_page_still_reaches_review(self) -> None:
        store = _Store(_row())

        def draft(ctx: PipelineContext) -> StageResult:
            ctx.draft_md = "# A real page\n\nWith real words in it."
            return ctx.record(StageResult("draft", outcome="ok"))

        outcome = _run(store, {"draft": draft, "gate": _stage("gate", "ok")})
        assert outcome.status == "needs_review"


class TestWhatTheStagesProduceActuallyReachesTheRow:
    """The first paid run wrote an empty qa_score and no JSON-LD onto a job whose
    gate had scored it and whose schema stage had validated it. The work was done
    and dropped on the floor between the pipeline and the row, because this code
    read for keys the stages do not emit - a nested "qa", a "schema_type".

    Nothing failed. The run reported success. That is the failure mode these
    assertions exist to prevent: silent loss between two working halves."""

    def _run_with(self, store: _Store, gate_data: dict[str, Any], schema_data: dict[str, Any]) -> Any:
        def draft(ctx: PipelineContext) -> StageResult:
            ctx.draft_md = "# A page\n\nWith real words."
            return ctx.record(StageResult("draft", outcome="ok"))

        return _run(store, {
            "draft": draft,
            "schema_links": _stage("schema_links", "ok", **schema_data),
            "gate": _stage("gate", "ok", **gate_data),
        })

    def test_the_gate_verdict_lands_whole(self) -> None:
        store = _Store(_row())
        self._run_with(
            store,
            {"weighted_total": 91.5, "passed": True, "dimensions": {"voice": 9},
             "blocked_by": [], "provisional": True},
            {},
        )
        qa = store.final("qa_score")
        assert qa["weighted_total"] == 91.5
        assert qa["passed"] is True
        assert qa["dimensions"] == {"voice": 9}, "the per-dimension scores must survive"
        assert store.final("qa_weighted_total") == 91.5

    def test_the_schema_graph_and_its_settled_type_land(self) -> None:
        store = _Store(_row())
        self._run_with(
            store, {},
            {"json_ld": {"@type": "Service", "name": "Emergency plumbing"},
             "primary_type": "Service", "valid": True},
        )
        assert store.final("json_ld")["@type"] == "Service"
        assert store.final("schema_type") == "Service"

    def test_internal_links_are_not_invented_as_empty(self) -> None:
        """This pipeline does not produce internal links - no stage fills them.
        Writing {"links": []} would say "we looked and found none" where the truth
        is that nothing looked."""
        store = _Store(_row())
        self._run_with(store, {}, {"json_ld": {"@type": "Service"}, "primary_type": "Service"})
        assert store.final("internal_links") is None

    def test_a_gate_that_produced_nothing_writes_no_score_rather_than_a_zero(self) -> None:
        store = _Store(_row())
        self._run_with(store, {}, {})
        assert store.final("qa_weighted_total") is None, "absent is not zero"
