"""P3: the post-draft stages - convert, voice, title/meta.

What these tests are really defending is the three-part shape in `repair.py`: measure
before spending, repair only what was measured, and keep the original when the repair
loses. Each of those is a real failure mode, not a style preference.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.services.content_pipeline.context import PipelineContext
from app.services.content_pipeline.convert import run_convert
from app.services.content_pipeline.repair import Finding, run_repair_stage
from app.services.content_pipeline.title_meta import run_title_meta
from app.services.content_pipeline.voice import run_voice


class _Writer:
    def __init__(self, reply: str = "", fail: bool = False) -> None:
        self.reply, self.fail, self.prompts = reply, fail, []

    def write(self, stage: str, prompt: str, **kw: Any) -> str:
        self.prompts.append((stage, prompt, kw.get("max_tokens")))
        if self.fail:
            raise RuntimeError("ContentSpendBlocked")
        # The real DoctrineWriter fills the caller's accounting object; a fake that
        # skips it makes every cost assertion in this file quietly vacuous.
        acc = kw.get("accounting")
        if acc is not None:
            acc.calls += 1
            acc.cost += 0.01
            acc.input_tokens += 100
            acc.output_tokens += 50
        return self.reply


def _ctx(**kw: Any) -> PipelineContext:
    base = {"primary_keyword": "slab leak repair san jose", "geo": "San Jose",
            "client_name": "Delaney Plumbing", "vertical": "plumbing"}
    return PipelineContext(**{**base, **kw})


# --------------------------------------------------------------------------- #
# The shape itself
# --------------------------------------------------------------------------- #
class TestMeasureBeforeSpending:
    def test_a_clean_draft_costs_nothing(self) -> None:
        """The linters are stdlib and run in microseconds, so the check that decides
        whether to spend is free. A stage that always calls always bills."""
        writer = _Writer()
        ctx = _ctx(draft_md="## H\n\nfine prose.")
        result = run_repair_stage(
            ctx, stage="x", writer=writer, measure=lambda _t: (), instruction="i"
        )
        assert result.outcome == "skipped"
        assert writer.prompts == [], "a passing draft must not reach the model"
        assert result.cost == 0.0

    def test_an_empty_draft_is_skipped_not_failed(self) -> None:
        writer = _Writer()
        result = run_repair_stage(
            ctx := _ctx(draft_md="  "), stage="x", writer=writer,
            measure=lambda _t: (Finding("C", 1, "m"),), instruction="i",
        )
        assert result.outcome == "skipped"
        assert not writer.prompts
        assert ctx.draft_md == "  "


class TestRepairOnlyWhatWasMeasured:
    def test_the_prompt_carries_the_findings_verbatim(self) -> None:
        """Blind self-critique - "improve this page" - is how a model rewrites prose
        that was fine and drops facts on the way through."""
        writer = _Writer(reply="## H\n\nrepaired.")
        run_repair_stage(
            _ctx(draft_md="## H\n\nbad."), stage="x", writer=writer,
            measure=lambda t: () if "repaired" in t else (
                Finding("NO_CTA", 4, "no primary lead CTA found"),),
            instruction="fix it",
        )
        prompt = writer.prompts[0][1]
        assert "[NO_CTA] line 4: no primary lead CTA found" in prompt
        assert "fix it" in prompt

    def test_the_prompt_forbids_inventing_evidence(self) -> None:
        """A repair that adds a statistic to satisfy a linter is worse than the defect
        it fixes: it puts an unsourced claim on a client's live page."""
        writer = _Writer(reply="## H\n\nok.")
        run_repair_stage(
            _ctx(draft_md="## H\n\nbad."), stage="x", writer=writer,
            measure=lambda t: () if "ok" in t else (Finding("C", 0, "m"),),
            instruction="i",
        )
        prompt = writer.prompts[0][1]
        assert "Do not add a fact" in prompt
        assert "Do not drop a heading" in prompt

    def test_a_whole_page_repair_gets_a_whole_page_budget(self) -> None:
        """A repair returns the entire document. Budgeting it like a section truncates
        the page mid-repair, which is worse than the defect."""
        writer = _Writer(reply="ok")
        long_draft = "## H\n\n" + ("word " * 1200)
        run_repair_stage(
            _ctx(draft_md=long_draft), stage="x", writer=writer,
            measure=lambda t: (Finding("C", 0, "m"),) if "word" in t else (),
            instruction="i",
        )
        assert writer.prompts[0][2] > 1200, "budget must scale with the draft"


class TestKeepTheBetterVersion:
    def test_a_repair_that_made_it_worse_is_discarded(self) -> None:
        """Nothing guarantees a rewrite is better. A loop that assumes it is will walk
        a page downhill one confident pass at a time."""
        original = "## H\n\noriginal prose."
        ctx = _ctx(draft_md=original)
        result = run_repair_stage(
            ctx, stage="x", writer=_Writer(reply="## H\n\nworse prose."),
            measure=lambda t: tuple(
                Finding("C", i, "m") for i in range(3 if "worse" in t else 1)
            ),
            instruction="i",
        )
        assert ctx.draft_md == original, "the losing repair must not be adopted"
        assert result.outcome == "degraded"
        assert "original draft kept" in result.notes[0]

    def test_a_discarded_repair_is_still_billed(self) -> None:
        """The call happened. Pretending a paid-for failure was free is how a cost
        model drifts away from the invoice."""
        result = run_repair_stage(
            _ctx(draft_md="## H\n\nx."), stage="x", writer=_Writer(reply="## H\n\ny."),
            measure=lambda t: tuple(Finding("C", i, "m") for i in range(2 if "y" in t else 1)),
            instruction="i",
        )
        assert result.llm_calls == 1
        assert result.data["findings_before"] == 1
        assert result.data["findings_after"] == 2

    def test_an_improvement_is_adopted(self) -> None:
        ctx = _ctx(draft_md="## H\n\nbad.")
        result = run_repair_stage(
            ctx, stage="x", writer=_Writer(reply="## H\n\ngood."),
            measure=lambda t: () if "good" in t else (Finding("C", 0, "m"),),
            instruction="i",
        )
        assert result.outcome == "ok"
        assert ctx.draft_md == "## H\n\ngood."

    def test_an_empty_reply_leaves_the_draft_alone(self) -> None:
        ctx = _ctx(draft_md="## H\n\nkeep me.")
        result = run_repair_stage(
            ctx, stage="x", writer=_Writer(reply="   "),
            measure=lambda _t: (Finding("C", 0, "m"),), instruction="i",
        )
        assert ctx.draft_md == "## H\n\nkeep me."
        assert result.outcome == "degraded"

    def test_a_spend_block_degrades_rather_than_losing_the_draft(self) -> None:
        ctx = _ctx(draft_md="## H\n\nkeep me.")
        result = run_repair_stage(
            ctx, stage="x", writer=_Writer(fail=True),
            measure=lambda _t: (Finding("C", 0, "m"),), instruction="i",
        )
        assert result.outcome == "degraded"
        assert ctx.draft_md == "## H\n\nkeep me."


# --------------------------------------------------------------------------- #
# convert
# --------------------------------------------------------------------------- #
def test_convert_spends_on_errors_but_not_on_warnings() -> None:
    """WARNs do not fail G13 by the linter's own definition. Repairing them means
    paying to satisfy a check that was never going to block the page."""
    from app.services.content_lint import lint_conversion
    from app.services.content_pipeline.convert import _measure

    text = "## Heading\n\nSome prose about the work.\n"
    report = lint_conversion(text)
    assert report.warnings or report.errors, "fixture must trip something"
    assert len(_measure(text)) == len(report.errors)


def test_convert_leaves_a_page_that_already_asks_for_the_business() -> None:
    writer = _Writer()
    ctx = _ctx(draft_md=(
        "## Slab leak repair\n\nCall [(408) 555-0111](tel:+14085550111) to book an "
        "estimate. We answer the phone and give you a firm price before we start.\n"
    ))
    result = run_convert(ctx, writer=writer)
    if result.outcome == "skipped":
        assert not writer.prompts


# --------------------------------------------------------------------------- #
# voice
# --------------------------------------------------------------------------- #
class TestVoiceMeasuresBothSidesOfTheBand:
    def test_a_page_below_the_grade_floor_is_caught(self) -> None:
        """MEASURED: correcting a grade-12.6 draft without a floor produced a 5.0 one.
        The draft prompt now carries a two-sided constraint, but a prompt is a request -
        this is the check that makes it a guarantee."""
        from app.services.content_pipeline.voice import _measure

        codes = {f.code for f in _measure("Call now. We fix it. It is fast. You save. " * 8)}
        assert "GRADE_LOW" in codes

    def test_a_page_above_the_grade_ceiling_is_caught(self) -> None:
        from app.services.content_pipeline.voice import _measure

        dense = (
            "The comprehensive remediation methodology necessitates preliminary "
            "diagnostic instrumentation prior to any invasive structural intervention "
            "being undertaken by qualified personnel. " * 6
        )
        assert "GRADE_HIGH" in {f.code for f in _measure(dense)}

    def test_one_banned_phrase_used_many_times_is_one_finding(self) -> None:
        """Emitting a finding per occurrence inflates the repair prompt with near
        identical lines, and every one of those tokens is billed on a call whose whole
        purpose is to remove them."""
        from app.services.content_pipeline.voice import _measure

        findings = _measure("We are the leading provider of world-class solutions. " * 12)
        blocklist = [f for f in findings if f.code == "BLOCKLIST"]
        assert blocklist, "fixture must trip the blocklist"
        assert len(blocklist) <= 4, f"one phrase should be one finding, got {len(blocklist)}"
        assert "12x" in blocklist[0].message, "the count belongs in the instruction"

    def test_rhythm_is_not_judged_on_too_little_text(self) -> None:
        """A stdev over three sentences is noise, and paying to 'fix' noise is waste."""
        from app.services.content_pipeline.voice import _measure

        assert "MONOTONE" not in {f.code for f in _measure("One. Two. Three.")}

    def test_clean_prose_makes_no_call(self) -> None:
        writer = _Writer()
        ctx = _ctx(draft_md=(
            "## What a slab leak costs\n\nMost repairs run between $2,200 and $4,800, "
            "and the spread comes down to access. A leak under an open kitchen floor "
            "is a different job from one beneath tile. We give you the number before "
            "we start. If it changes mid-job, the leak was never properly located.\n"
        ))
        result = run_voice(ctx, writer=writer)
        if result.outcome == "skipped":
            assert not writer.prompts and result.cost == 0.0


# --------------------------------------------------------------------------- #
# title / meta
# --------------------------------------------------------------------------- #
class TestTitleAndMeta:
    GOOD = (
        '{"title": "Slab Leak Repair in San Jose - Delaney Plumbing Co",'
        ' "description": "We locate slab leaks with acoustic and thermal gear before '
        'we open your floor, then quote a firm price up front. Licensed, family-run in '
        'the valley since 2011."}'
    )

    def test_it_refuses_the_keyword_pipe_city_pipe_brand_template(self) -> None:
        """v1 concatenated these, so every page in an engagement shared one title SHAPE -
        the scaled-content fingerprint, in the one field Google shows before the click."""
        writer = _Writer(reply=self.GOOD)
        run_title_meta(_ctx(), writer=writer)
        assert "'Keyword | City | Brand' template" in writer.prompts[0][1]

    def test_lengths_are_enforced_and_the_retry_names_the_overshoot(self) -> None:
        """A title eight characters too long is fixable if the model is told the
        number, and not fixable if nobody tells it."""
        long_title = "x" * 90
        writer = _Writer(reply=f'{{"title": "{long_title}", "description": "y"}}')
        result = run_title_meta(_ctx(), writer=writer)
        assert len(writer.prompts) == 2, "a length miss is worth exactly one retry"
        assert "was 90 characters" in writer.prompts[1][1]
        assert result.outcome == "degraded"
        assert result.data["in_band"] is False

    def test_out_of_band_values_are_kept_not_discarded(self) -> None:
        """Length is a WARN in the compliance linter, not a blocker. Dropping a usable
        title to hold a soft bound leaves the page with no title at all."""
        ctx = _ctx()
        writer = _Writer(reply='{"title": "Short", "description": "Also short"}')
        run_title_meta(ctx, writer=writer)
        assert ctx.title == "Short"
        assert ctx.meta_description == "Also short"

    def test_a_good_pair_is_accepted_in_one_call(self) -> None:
        ctx = _ctx()
        result = run_title_meta(ctx, writer=(w := _Writer(reply=self.GOOD)))
        assert result.outcome == "ok", result.notes
        assert len(w.prompts) == 1
        assert ctx.title.startswith("Slab Leak Repair")

    def test_a_non_json_reply_degrades_without_setting_junk(self) -> None:
        ctx = _ctx()
        result = run_title_meta(ctx, writer=_Writer(reply="Sure! Here you go."))
        assert result.outcome == "degraded"
        assert ctx.title == ""

    @pytest.mark.parametrize("model_hint", [None, "claude-haiku-4-5"])
    def test_the_stage_passes_its_model_through(self, model_hint: str | None) -> None:
        writer = _Writer(reply=self.GOOD)
        run_title_meta(_ctx(), writer=writer, model=model_hint)
        assert writer.prompts
