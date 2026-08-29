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
            "gate": _stage("gate", "ok", qa={"weighted_total": 88.5, "passed": True}),
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
            "gate": _stage("gate", "ok", qa={}),
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
        assert outcome.state in ("advanced", "deferred"), "must degrade, not raise"
