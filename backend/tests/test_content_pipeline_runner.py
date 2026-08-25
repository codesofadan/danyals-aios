"""P3: the runner - the stage sequence and where it is allowed to stop."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from app.services.content_pipeline.context import PipelineContext, StageResult
from app.services.content_pipeline.runner import PAGE_STAGES, run_page


def _stage(name: str, outcome: str = "ok", **kw: Any) -> Callable[[PipelineContext], StageResult]:
    def _run(ctx: PipelineContext) -> StageResult:
        return ctx.record(StageResult(name, outcome=outcome, **kw))  # type: ignore[arg-type]
    return _run


def _all(outcome: str = "ok") -> dict[str, Callable[[PipelineContext], StageResult]]:
    return {n: _stage(n, outcome) for n in PAGE_STAGES}


class TestAHaltIsNotAFailure:
    """The SME stage refusing to draft a page nobody supplied facts for is the system
    working - Law 16, and the owner's "hard halt, no exceptions" decision. Retrying it,
    alerting on it, or counting it as an error would all be wrong."""

    def test_a_halt_stops_the_run_and_is_reported_as_a_halt(self) -> None:
        stages = _all()
        stages["sme"] = _stage("sme", "halted", notes=("3 slots unanswered",))
        run = run_page(PipelineContext(), stages)
        assert run.outcome == "halted"
        assert run.halted is True
        assert run.stopped_at == "sme"
        assert run.reason == "3 slots unanswered"

    def test_a_halt_spends_nothing_downstream(self) -> None:
        stages = _all()
        stages["sme"] = _stage("sme", "halted")
        stages["draft"] = _stage("draft", "ok", cost=5.0, llm_calls=9)
        run = run_page(PipelineContext(), stages)
        assert run.cost == 0.0 and run.llm_calls == 0
        assert "draft" not in {r.stage for r in run.results}

    def test_a_failure_is_distinguished_from_a_halt(self) -> None:
        stages = _all()
        stages["research"] = _stage("research", "failed")
        run = run_page(PipelineContext(), stages)
        assert run.outcome == "failed"
        assert run.halted is False


class TestDegradesThatAreSurvivableAndOnesThatAreNot:
    def test_a_degraded_research_brief_does_not_stop_the_page(self) -> None:
        """A low-confidence brief still lets a page be written under a flag."""
        stages = _all()
        stages["research"] = _stage("research", "degraded")
        run = run_page(PipelineContext(), stages)
        assert run.stopped_at is None
        assert run.outcome == "degraded"
        assert "research" in run.reason

    def test_a_degraded_outline_stops_before_the_expensive_stages(self) -> None:
        """Everything downstream is built on the outline. Continuing spends real money
        producing prose nobody should publish."""
        stages = _all()
        stages["outline"] = _stage("outline", "degraded")
        stages["draft"] = _stage("draft", "ok", cost=3.0, llm_calls=5)
        run = run_page(PipelineContext(), stages)
        assert run.outcome == "degraded"
        assert run.stopped_at == "outline"
        assert run.cost == 0.0, "the draft must not run on a degraded outline"

    def test_every_degrade_survives_into_the_final_reason(self) -> None:
        stages = _all()
        stages["convert"] = _stage("convert", "degraded")
        stages["voice"] = _stage("voice", "degraded")
        run = run_page(PipelineContext(), stages)
        assert "convert" in run.reason and "voice" in run.reason

    def test_a_skipped_stage_does_not_degrade_the_run(self) -> None:
        """CONVERT and VOICE skip when the draft already passes - the free path. A run
        of clean skips must still be `ok`, or every good page reports as degraded."""
        stages = _all()
        stages["convert"] = _stage("convert", "skipped")
        stages["voice"] = _stage("voice", "skipped")
        run = run_page(PipelineContext(), stages)
        assert run.outcome == "ok"


class TestTheSequence:
    def test_stages_run_in_the_declared_order(self) -> None:
        seen: list[str] = []

        def spy(name: str) -> Callable[[PipelineContext], StageResult]:
            def _run(ctx: PipelineContext) -> StageResult:
                seen.append(name)
                return ctx.record(StageResult(name))
            return _run

        run_page(PipelineContext(), {n: spy(n) for n in PAGE_STAGES})
        assert seen == list(PAGE_STAGES)

    def test_the_halt_comes_before_anything_that_spends(self) -> None:
        """If SME ran after RESEARCH, a page with no first-party facts would still buy
        a SERP before being refused."""
        assert PAGE_STAGES.index("sme") == 0

    def test_the_gate_runs_last(self) -> None:
        assert PAGE_STAGES[-1] == "gate"

    def test_schema_runs_after_title_meta(self) -> None:
        """The JSON-LD marks up the title and description, so they have to exist."""
        assert PAGE_STAGES.index("schema_links") > PAGE_STAGES.index("title_meta")

    def test_an_absent_stage_is_skipped_not_an_error(self) -> None:
        run = run_page(PipelineContext(), {"draft": _stage("draft")})
        assert run.outcome == "ok"
        assert [r.stage for r in run.results] == ["draft"]

    def test_a_raising_stage_is_recorded_where_it_broke(self) -> None:
        """A stage that raises is a bug, not a business outcome. The run must report
        WHERE it broke rather than the exception vanishing."""
        def boom(ctx: PipelineContext) -> StageResult:
            raise ValueError("kaboom")

        stages = _all()
        stages["draft"] = boom
        run = run_page(PipelineContext(), stages)
        assert run.outcome == "failed"
        assert run.stopped_at == "draft"
        assert "ValueError" in run.reason and "kaboom" in run.reason

    def test_cost_and_calls_roll_up_across_stages(self) -> None:
        stages = _all()
        stages["draft"] = _stage("draft", "ok", cost=0.42, llm_calls=3)
        stages["gate"] = _stage("gate", "ok", cost=0.08, llm_calls=1)
        run = run_page(PipelineContext(), stages)
        assert round(run.cost, 4) == 0.50
        assert run.llm_calls == 4

    def test_the_summary_names_every_stage_outcome(self) -> None:
        stages = _all()
        stages["voice"] = _stage("voice", "skipped")
        summary = run_page(PipelineContext(), stages).summary()
        assert summary["stages"]["voice"] == "skipped"
        assert summary["outcome"] == "ok"
