"""P3: ClaudeJudge - the LLM half of the QA gate that has never run.

`content_qa` ships a `Judge` seam and five dimensions that use it. In every real run
`judge` is None, so all five fall back to deterministic proxies while the scorecard
reports a number that reads like a judgment. Three of the five are HARD GATE dimensions.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from app.services.content_pipeline.judge import (
    DEFAULT_CRITERIA,
    JUDGED_DIMENSIONS,
    ClaudeJudge,
    JudgeUnavailableError,
)

GOOD = json.dumps({d: {"score": 70 + i, "rationale": f"because {d}"}
                   for i, d in enumerate(JUDGED_DIMENSIONS)})


class _Writer:
    def __init__(self, reply: str = GOOD, fail: bool = False) -> None:
        self.reply, self.fail, self.prompts = reply, fail, []

    def write(self, stage: str, prompt: str, **kw: Any) -> str:
        self.prompts.append(prompt)
        if self.fail:
            raise RuntimeError("ContentSpendBlocked")
        acc = kw.get("accounting")
        if acc is not None:
            acc.calls += 1
            acc.cost += 0.05
        return self.reply


def _judge(**kw: Any) -> ClaudeJudge:
    return ClaudeJudge(_Writer(**kw))  # type: ignore[arg-type]


def _assess_all(judge: ClaudeJudge, draft: str = "## H\n\nprose.") -> dict[str, int]:
    return {
        d: judge.assess(d, draft=draft, criteria=DEFAULT_CRITERIA[d]).score
        for d in JUDGED_DIMENSIONS
    }


class TestOneCallNotFive:
    def test_five_dimensions_cost_one_call(self) -> None:
        """The five differ only in rubric; the draft is identical. Asking five times
        sends the same page five times and bills for it five times."""
        writer = _Writer()
        judge = ClaudeJudge(writer)  # type: ignore[arg-type]
        scores = _assess_all(judge)
        assert len(writer.prompts) == 1, f"expected 1 batched call, got {len(writer.prompts)}"
        assert len(scores) == len(JUDGED_DIMENSIONS)

    def test_every_rubric_reaches_the_single_prompt(self) -> None:
        """A batched call that omits a rubric scores that dimension against nothing."""
        writer = _Writer()
        _assess_all(ClaudeJudge(writer))  # type: ignore[arg-type]
        for dim in JUDGED_DIMENSIONS:
            assert dim in writer.prompts[0]

    def test_the_callers_own_criteria_wins_for_its_dimension(self) -> None:
        writer = _Writer()
        judge = ClaudeJudge(writer)  # type: ignore[arg-type]
        judge.assess("originality", draft="d", criteria="MY BESPOKE RUBRIC")
        assert "MY BESPOKE RUBRIC" in writer.prompts[0]

    def test_the_prompt_carries_scoring_anchors(self) -> None:
        """Without anchors a judge converges everything on 80 and the scorecard stops
        discriminating between a good page and a mediocre one."""
        writer = _Writer()
        _assess_all(ClaudeJudge(writer))  # type: ignore[arg-type]
        assert "90-100" in writer.prompts[0]
        assert "0-49" in writer.prompts[0]


class TestFailingSafe:
    """A judge that invents a score when its own output was unreadable produces a page
    that passed QA because the QA broke. Raising lets `score(judge=None)` degrade to
    documented proxies and SAY so."""

    @pytest.mark.parametrize("reply", ["not json at all", "", "[1,2,3]", "{}",
                                       '{"originality": {"score": "high"}}'])
    def test_an_unusable_reply_raises_rather_than_scoring(self, reply: str) -> None:
        with pytest.raises(JudgeUnavailableError):
            _assess_all(_judge(reply=reply))

    def test_a_spend_block_raises_as_unavailable(self) -> None:
        with pytest.raises(JudgeUnavailableError):
            _assess_all(_judge(fail=True))

    def test_a_missing_dimension_raises_instead_of_defaulting(self) -> None:
        partial = json.dumps({"originality": {"score": 90, "rationale": "r"}})
        judge = _judge(reply=partial)
        assert judge.assess("originality", draft="d", criteria="c").score == 90
        with pytest.raises(JudgeUnavailableError):
            judge.assess("cta_ux", draft="d", criteria="c")


class TestVerdicts:
    def test_scores_are_clamped_to_the_0_100_band(self) -> None:
        reply = json.dumps({d: {"score": 9999 if i else -50, "rationale": "r"}
                            for i, d in enumerate(JUDGED_DIMENSIONS)})
        scores = _assess_all(_judge(reply=reply))
        assert set(scores.values()) <= {0, 100}

    def test_a_bare_number_is_accepted_as_a_score(self) -> None:
        reply = json.dumps(dict.fromkeys(JUDGED_DIMENSIONS, 77))
        assert set(_assess_all(_judge(reply=reply)).values()) == {77}

    def test_a_boolean_is_not_a_score(self) -> None:
        """`True` is an int in Python. Accepting it would score a dimension 1."""
        reply = json.dumps(dict.fromkeys(JUDGED_DIMENSIONS, True))
        with pytest.raises(JudgeUnavailableError):
            _assess_all(_judge(reply=reply))

    def test_the_rationale_survives_for_the_human_reviewer(self) -> None:
        v = _judge().assess("originality", draft="d", criteria="c")
        assert v.rationale == "because originality"

    def test_the_call_is_billed_to_the_shared_accounting(self) -> None:
        judge = _judge()
        _assess_all(judge)
        assert judge.accounting.calls == 1
        assert judge.accounting.cost > 0


def test_the_batch_covers_exactly_the_dimensions_content_qa_judges() -> None:
    """THE COUPLING GUARD. `content_qa` decides which dimensions route through the
    judge seam; this module has to mirror that list to batch them. If a sixth is added
    there and not here, it silently keeps using its proxy while the scorecard reports
    it as judged - the exact failure this whole stage exists to end."""
    import inspect
    import re

    from app.services import content_qa

    source = inspect.getsource(content_qa)
    judged = set(re.findall(r'_judge_score\(\s*judge,\s*\n?\s*"([a-z_]+)"', source))
    assert judged, "could not find the judge call sites; this guard has gone stale"
    assert judged == set(JUDGED_DIMENSIONS), (
        f"content_qa judges {sorted(judged)}, this module batches "
        f"{sorted(JUDGED_DIMENSIONS)}"
    )


def test_every_batched_dimension_has_a_mirrored_rubric() -> None:
    assert set(DEFAULT_CRITERIA) == set(JUDGED_DIMENSIONS)
