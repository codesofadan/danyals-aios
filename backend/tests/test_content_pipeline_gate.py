"""P3: RESEARCH and GATE - the brief, and the QA verdict with the judge connected."""

from __future__ import annotations

import json
from typing import Any

from app.services.content_pipeline.context import PipelineContext
from app.services.content_pipeline.gate import answer_block_of, headings_of, run_gate
from app.services.content_pipeline.judge import JUDGED_DIMENSIONS
from app.services.content_pipeline.research import run_research
from app.services.content_pipeline.schema_links import run_schema_links
from app.services.content_research import ContentSpendBlocked, TeardownFetch
from integrations.content_research import FakeSerpResearcher

DRAFT = (
    "## What a slab leak costs\n\n"
    "Most repairs run between $2,200 and $4,800, and the spread comes down to access. "
    "A leak under an open kitchen floor is a different job from one beneath tile.\n\n"
    "## How we find it\n\n"
    "Detection comes first. We use acoustic gear and thermal imaging before anyone "
    "touches concrete.\n"
)


class _Port:
    """`FakeSerpResearcher` covers serp+metrics; teardown needs a page fetcher, so it
    is stubbed - which is also the real degraded-teardown path."""

    def __init__(self, blocked: bool = False) -> None:
        self._inner = FakeSerpResearcher()
        self.blocked = blocked
        self.serp_calls = 0

    def serp(self, keyword: str, geo: str | None = None) -> Any:
        if self.blocked:
            raise ContentSpendBlocked("serp")
        self.serp_calls += 1
        return self._inner.serp(keyword, geo)

    def keyword_metrics(self, keyword: str) -> Any:
        return self._inner.keyword_metrics(keyword)

    def teardown(self, urls: list[str], keyword: str, geo: str | None) -> TeardownFetch:
        return TeardownFetch(pages=[], refused=[])


def _ctx(**kw: Any) -> PipelineContext:
    base = {
        "client_name": "Delaney Plumbing",
        "primary_keyword": "slab leak repair san jose",
        "geo": "San Jose", "vertical": "plumbing", "page_type": "service",
        "draft_md": DRAFT, "title": "Slab Leak Repair in San Jose - Delaney Plumbing",
        "meta_description": "We locate slab leaks before we open your floor.",
        "facts": ("CSLB contractor license #1043327.", "Founded by Mike Delaney in 2011."),
    }
    return PipelineContext(**{**base, **kw})


class TestResearch:
    def test_a_whole_page_costs_one_serp_call(self) -> None:
        """v1 spent up to 10 Serper credits per page: one SERP plus up to nine more for
        a winnability proxy. Everything after the first is derivable from the SERP we
        already hold."""
        port = _Port()
        run_research(_ctx(), researcher=port)
        assert port.serp_calls == 1

    def test_metrics_without_a_plan_row_are_marked_estimated(self) -> None:
        """`difficulty = log10(totalResults) * 8` is an invented number dressed as
        vendor data, and it cost a paid credit to invent. Volume originates in Google's
        ad auction; there is no offline derivation. So say so."""
        ctx = _ctx()
        result = run_research(ctx, researcher=_Port())
        assert result.data["metrics_estimated"] is True
        assert ctx.brief["metrics_estimated"] is True
        assert any("ESTIMATED" in n for n in result.notes)

    def test_a_plan_row_replaces_the_estimate_with_bought_data(self) -> None:
        class Plan:
            def metrics_for(self, engagement_id: str | None, keyword: str) -> dict[str, Any]:
                return {"volume": 880, "difficulty": 34}

        ctx = _ctx()
        result = run_research(ctx, researcher=_Port(), plan=Plan())
        assert result.data["metrics_estimated"] is False
        assert ctx.brief["keyword_metrics"]["volume"] == 880

    def test_a_plan_lookup_failure_does_not_lose_the_brief(self) -> None:
        class Broken:
            def metrics_for(self, engagement_id: str | None, keyword: str) -> Any:
                raise RuntimeError("db down")

        ctx = _ctx()
        result = run_research(ctx, researcher=_Port(), plan=Broken())
        assert "research" in ctx.brief, "the brief must survive a metrics lookup failure"
        assert any("lookup failed" in n for n in result.notes)

    def test_a_gate_block_degrades_rather_than_raising(self) -> None:
        result = run_research(_ctx(), researcher=_Port(blocked=True))
        assert result.outcome == "degraded"

    def test_no_keyword_is_a_failure_not_a_degrade(self) -> None:
        assert run_research(_ctx(primary_keyword=""), researcher=_Port()).outcome == "failed"

    def test_an_unexpected_error_reports_its_message(self) -> None:
        """"research unavailable (AttributeError)" was the first version of this note
        and it was useless - the cause was a fake missing a method, which the exception
        type alone never points at."""
        class Broken(_Port):
            def serp(self, keyword: str, geo: str | None = None) -> Any:
                raise AttributeError("no attribute 'teardown'")

        notes = run_research(_ctx(), researcher=Broken()).notes
        assert any("teardown" in n for n in notes), notes


class TestGeneratedContentIsAssembledNotGuessed:
    def test_headings_come_out_in_document_order(self) -> None:
        assert [h.text for h in headings_of(DRAFT)] == [
            "What a slab leak costs", "How we find it"]

    def test_the_answer_block_is_the_prose_under_the_first_heading(self) -> None:
        block = answer_block_of(DRAFT)
        assert block.startswith("Most repairs run")
        assert "Detection comes first" not in block, "it must stop at the next heading"

    def test_work_the_pipeline_did_not_do_stays_empty(self) -> None:
        """A fabricated internal-link list would score the linking dimension on links
        that do not exist."""
        from app.services.content_pipeline.gate import _content_for

        content = _content_for(_ctx(), (run_research(_ctx(), researcher=_Port()) and
                               _ctx().brief.get("research")) or _brief())
        assert content.internal_links == []
        assert content.images_plan == []

    def test_measurable_fields_are_measured(self) -> None:
        from app.services.content_pipeline.gate import _content_for

        ctx = _ctx()
        run_research(ctx, researcher=_Port())
        content = _content_for(ctx, ctx.brief["research"])
        assert content.word_count > 0, "a zero here scores keyword handling on nothing"
        assert content.primary_density >= 0.0
        assert content.grounding, "the SME facts are the grounding"


def _brief() -> Any:
    ctx = _ctx()
    run_research(ctx, researcher=_Port())
    return ctx.brief["research"]


class TestGate:
    def _scored(self, **kw: Any) -> Any:
        ctx = _ctx(**kw)
        run_research(ctx, researcher=_Port())
        run_schema_links(ctx, url="https://x.test/p")
        return ctx, run_gate(ctx)

    def test_without_a_writer_the_judged_dimensions_are_named_as_proxies(self) -> None:
        """The scorecard reporting a proxy as a judgment is the defect. Say which."""
        _, result = self._scored()
        assert result.data["judged"] is False
        assert any("proxies" in n for n in result.notes)

    def test_with_a_writer_the_five_dimensions_are_actually_judged(self) -> None:
        reply = json.dumps({d: {"score": 88, "rationale": "r"} for d in JUDGED_DIMENSIONS})

        class W:
            def __init__(self) -> None:
                self.calls = 0

            def write(self, stage: str, prompt: str, **kw: Any) -> str:
                self.calls += 1
                acc = kw.get("accounting")
                if acc is not None:
                    acc.calls += 1
                    acc.cost += 0.09
                return reply

        ctx = _ctx()
        run_research(ctx, researcher=_Port())
        run_schema_links(ctx, url="https://x.test/p")
        writer = W()
        result = run_gate(ctx, writer=writer)  # type: ignore[arg-type]
        assert result.data["judged"] is True
        assert writer.calls == 1, "five dimensions, one call"
        assert result.cost > 0
        scored = [result.data["dimensions"][d] for d in JUDGED_DIMENSIONS]
        assert scored.count(88) >= 3, f"the judge's verdict must reach the card: {scored}"

    def test_a_doctrine_floor_outranks_the_judge(self) -> None:
        """`score()` applies doctrine floors LAST, so no judge can talk a page past a
        hard rule. Measured: with the judge returning 88 across the board,
        information_gain still lands at 25 because the deterministic gain check found
        nothing new on the page. That ordering is the safety property - a judge that
        could overrule it would make every hard gate advisory."""
        reply = json.dumps({d: {"score": 88, "rationale": "r"} for d in JUDGED_DIMENSIONS})

        class W:
            def write(self, stage: str, prompt: str, **kw: Any) -> str:
                return reply

        ctx = _ctx()
        run_research(ctx, researcher=_Port())
        run_schema_links(ctx, url="https://x.test/p")
        result = run_gate(ctx, writer=W())  # type: ignore[arg-type]
        assert result.data["dimensions"]["information_gain"] < 88

    def test_a_broken_judge_falls_back_to_proxies_and_says_so(self) -> None:
        """A judge that returns a number when its own output was unreadable produces a
        page that passed QA because the QA broke."""
        class W:
            def write(self, stage: str, prompt: str, **kw: Any) -> str:
                return "I cannot comply."

        ctx = _ctx()
        run_research(ctx, researcher=_Port())
        result = run_gate(ctx, writer=W())  # type: ignore[arg-type]
        assert result.data["judged"] is False
        assert result.data["weighted_total"] > 0, "the page is still scored"
        assert any("judge unavailable" in n for n in result.notes)

    def test_the_schema_verdict_reaches_the_schema_dimension(self) -> None:
        """Storing only the graph and not the verdict made the gate score 60 on a
        document that had just validated clean."""
        ctx, result = self._scored()
        assert ctx.brief.get("schema_validation") is not None
        assert result.data["dimensions"]["schema_validity"] > 60

    def test_the_provisional_threshold_is_declared_in_the_notes(self) -> None:
        """85 is not calibrated against ranking outcomes or a human grade. A verdict
        that does not say so invites someone to treat it as a hard gate."""
        _, result = self._scored()
        assert result.data["provisional"] is True
        assert any("PROVISIONAL" in n for n in result.notes)

    def test_a_failing_score_is_a_verdict_not_a_stage_failure(self) -> None:
        """The stage did its job. `degraded` is for the gate itself not working."""
        _, result = self._scored()
        assert result.outcome in ("ok", "degraded")
        assert result.blocks_pipeline is False

    def test_no_draft_is_skipped(self) -> None:
        assert run_gate(_ctx(draft_md="")).outcome == "skipped"

    def test_no_brief_degrades_rather_than_scoring_on_nothing(self) -> None:
        result = run_gate(_ctx())
        assert result.outcome == "degraded"
        assert "brief" in result.notes[0]
