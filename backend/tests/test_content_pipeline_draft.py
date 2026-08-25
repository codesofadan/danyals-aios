"""P3: the draft stage - batched writing from grounded facts only."""

from __future__ import annotations

from typing import Any

from app.services.content_pipeline.context import PipelineContext
from app.services.content_pipeline.draft import BATCH_SIZE, run_draft


class _Writer:
    def __init__(self, reply: str = "", fail_after: int | None = None) -> None:
        self.reply, self.fail_after, self.prompts = reply, fail_after, []

    def write(self, stage: str, prompt: str, **kw: Any) -> str:
        self.prompts.append((prompt, kw.get("max_tokens")))
        if self.fail_after is not None and len(self.prompts) > self.fail_after:
            raise RuntimeError("ContentSpendBlocked")
        return self.reply or f"## Section\n\nProse for call {len(self.prompts)}."


def _ctx(sections: int = 7, **kw: Any) -> PipelineContext:
    outline = {"sections": [
        {"h2": f"Heading {i}", "h3s": [], "target_words": 150} for i in range(sections)
    ]}
    base = {"primary_keyword": "roof repair austin", "geo": "Austin",
            "client_name": "Acme", "outline": outline}
    return PipelineContext(**{**base, **kw})


def test_sections_are_written_in_batches_not_one_call_each() -> None:
    """v1 made one call per section, each blind to the others - which is why the page
    read as a stack of paragraphs. Batching is what gives a run continuity."""
    writer = _Writer()
    ctx = _ctx(sections=7)
    result = run_draft(ctx, writer=writer)
    assert result.outcome == "ok"
    assert len(writer.prompts) == 3, "7 sections at batch size 3 is 3 calls, not 7"
    assert result.data["batches"] == 3


def test_each_batch_after_the_first_sees_the_previous_tail() -> None:
    """A transition has to connect to something. Without the tail the model cannot
    refer back, vary its opening, or avoid restating what was just said."""
    writer = _Writer()
    run_draft(_ctx(sections=6), writer=writer)
    assert "previous section ended" not in writer.prompts[0][0]
    assert "previous section ended" in writer.prompts[1][0]
    assert "do not restate it" in writer.prompts[1][0]


def test_only_supplied_facts_are_offered_and_the_rule_is_absolute() -> None:
    writer = _Writer()
    run_draft(_ctx(sections=3, facts=("1,284 emergency calls in 2025",)), writer=writer)
    prompt = writer.prompts[0][0]
    assert "1,284 emergency calls in 2025" in prompt
    assert "must be cut, not softened" in prompt


def test_with_no_facts_the_model_is_told_to_state_none() -> None:
    """Silence is the correct output when nothing is supplied. "Write generally" is how
    a page acquires invented specifics."""
    writer = _Writer()
    run_draft(_ctx(sections=3), writer=writer)
    assert "State no figures" in writer.prompts[0][0]


def test_the_token_ceiling_clears_the_word_budget() -> None:
    """Measured: local copy runs 1.8-2.0 tokens per word, and at a 2.0 multiplier
    three live calls out of three came back cut mid-sentence."""
    writer = _Writer()
    run_draft(_ctx(sections=3), writer=writer)
    _prompt, max_tokens = writer.prompts[0]
    assert max_tokens >= 450, "3 sections x 150 words needs well over 900 tokens of room"


def test_a_spend_block_keeps_what_was_already_written() -> None:
    """A page that stops early is reviewable and resumable. One that vanishes on the
    last batch has spent real money for nothing."""
    ctx = _ctx(sections=9)
    result = run_draft(ctx, writer=_Writer(fail_after=2))
    assert result.outcome == "degraded"
    assert ctx.draft_md, "the written batches must survive"
    assert result.data["batches"] == 2
    assert any("drafting stopped at section" in n for n in result.notes)


def test_a_batch_that_drops_its_headings_is_repaired_not_discarded() -> None:
    """Downstream stages parse markdown. A wall of prose with no headings is
    unreadable to the schema and link stages, but the prose itself is still good."""
    ctx = _ctx(sections=3)
    result = run_draft(ctx, writer=_Writer(reply="Just prose, no headings at all."))
    assert ctx.draft_md.startswith("## Heading 0")
    assert any("omitted its headings" in n for n in result.notes)


def test_an_empty_outline_is_skipped_rather_than_drafted() -> None:
    ctx = PipelineContext(primary_keyword="x", outline={"sections": []})
    assert run_draft(ctx, writer=_Writer()).outcome == "skipped"


def test_batching_is_a_named_constant() -> None:
    assert BATCH_SIZE == 3


# --------------------------------------------------------------------------- #
# Extended thinking: budgets, and the failure it caused
# --------------------------------------------------------------------------- #
def test_the_budget_covers_thinking_as_well_as_prose() -> None:
    """MEASURED live. This model reasons before it writes. At a prose-only budget it
    spent the entire allowance thinking and returned NO text - a blank section that
    looked like "the model had nothing to say". The allowance is separate so the prose
    multiplier keeps meaning tokens-per-word of OUTPUT."""
    from app.services.content_pipeline.draft import THINKING_ALLOWANCE

    writer = _Writer()
    run_draft(_ctx(sections=3), writer=writer)
    _prompt, max_tokens = writer.prompts[0]
    assert max_tokens > THINKING_ALLOWANCE, "the prose budget must sit ON TOP of thinking"


def test_the_adaptive_ceiling_stays_below_the_streaming_threshold() -> None:
    """The SDK refuses a non-streaming request whose max_tokens implies it could run
    past 10 minutes. A retry doubling into that wall surfaced as an opaque
    BadRequestError on the second batch of a page."""
    from app.services.content_pipeline.writer import MAX_ADAPTIVE_TOKENS

    assert MAX_ADAPTIVE_TOKENS <= 21_000


def test_the_prose_constraints_are_specific_not_general() -> None:
    """The doctrine covers rhythm and stuffing, but a general instruction inside a 74k
    system block does not bind as tightly as a measured one in the user turn. Both
    numbers here come from real drafts that missed the target."""
    writer = _Writer()
    run_draft(_ctx(sections=3), writer=writer)
    prompt = writer.prompts[0][0]
    assert "grade 6-9" in prompt
    assert "2.5% stuffing ceiling" in prompt
    assert "AT MOST ONCE per section" in prompt


def test_the_readability_constraint_has_a_floor_as_well_as_a_ceiling() -> None:
    """A one-sided instruction over-corrects. Told only "most sentences under 25
    words", a draft came back at grade 5.0 - out of the 6-9 band on the OTHER side,
    reading as a checklist rather than prose. Both misses are now named in the prompt
    with the number each one produced."""
    writer = _Writer()
    run_draft(_ctx(sections=3), writer=writer)
    prompt = writer.prompts[0][0]
    assert "BAND, not a floor" in prompt
    assert "5.0" in prompt, "the over-correction needs its measured number too"
