"""P0-2 REGRESSION GUARD: a bounded section may never end mid-sentence.

Prevented defect: `_bound_words` was `" ".join(tokens[:max_words])` - no sentence
logic at all. It was DOCUMENTED as a safety clamp against a runaway provider, but the
per-section budget (~133 words for a 1200-word target) sits far under what
`max_tokens = max_words * 2` lets the model emit, so it fired on ORDINARY output. Every
oversized section shipped to the client's live WordPress page ending in a half
sentence. The root cause was upstream: `_write` never told the model a length at all.

The bound itself is still a hard guarantee - these tests pin BOTH properties, because
fixing the fragment by letting sections overflow would trade one defect for another.
"""

from __future__ import annotations

import pytest

from app.services.content_generator import _bound_words, _terminate

_TERMINATORS = ".!?"

# Deliberately nasty: no punctuation at all, punctuation only at the very start,
# dangling connectors at the cut, unicode, and already-short input.
_CASES: tuple[str, ...] = (
    "word " * 400,
    "Short. " + "filler " * 400,
    "The team arrived early and " * 60,
    "Alpha beta gamma. Delta epsilon zeta! Eta theta? " * 40,
    "We service the whole metro area because " * 50,
    "Ünïcödé têxt with accents " * 60,
    "One sentence that simply never ends " * 80,
)


@pytest.mark.parametrize("text", _CASES)
@pytest.mark.parametrize("budget", [5, 12, 40, 55, 133])
def test_bounded_text_never_ends_mid_sentence(text: str, budget: int) -> None:
    out = _bound_words(text, budget)
    assert out, "bounding produced empty prose"
    assert out[-1] in _TERMINATORS, f"ended mid-sentence: ...{out[-40:]!r}"


@pytest.mark.parametrize("text", _CASES)
@pytest.mark.parametrize("budget", [5, 12, 40, 55, 133])
def test_bound_is_still_a_hard_guarantee(text: str, budget: int) -> None:
    """The clamp must survive the fix - a runaway provider still cannot overrun the
    doctrine word budget. Nothing in the sentence logic may ADD a word."""
    assert len(_bound_words(text, budget).split()) <= budget


def test_text_within_budget_is_returned_untouched() -> None:
    """Only OVER-budget prose is reshaped; a compliant section is passed through so the
    writer's own punctuation and phrasing survive verbatim."""
    assert _bound_words("Short text.", 50) == "Short text."
    assert _bound_words("No terminator here", 50) == "No terminator here"


def test_prefers_a_sentence_boundary_over_the_hard_cut() -> None:
    text = "First sentence here. Second sentence here. " + "tail " * 100
    out = _bound_words(text, 12)
    assert out == "First sentence here. Second sentence here."


def test_hard_cut_is_used_when_the_only_boundary_is_too_early() -> None:
    """A boundary in the first few words would throw away most of the budgeted prose,
    so the hard bound wins - terminated cleanly rather than left dangling."""
    text = "Yes. " + "continuing prose without any stop " * 40
    out = _bound_words(text, 40)
    assert out != "Yes."
    assert out[-1] in _TERMINATORS
    assert len(out.split()) <= 40


def test_terminate_drops_a_dangling_connector() -> None:
    """'... and.' reads worse than the fragment did, so the connector goes first."""
    assert _terminate("we serve the whole metro area and") == "we serve the whole metro area."
    assert _terminate("open early because") == "open early."
    assert _terminate("already complete.") == "already complete."


def test_write_states_the_word_budget_to_the_model() -> None:
    """The upstream half of the fix. The model used to be given `max_tokens` and no
    length instruction, so it wrote past the budget as a matter of course and every
    section was cut back. If this instruction is dropped, overshoot returns."""
    from app.services.content_generator import _write

    class _Spy:
        def __init__(self) -> None:
            self.prompts: list[str] = []

        def summarize(self, prompt, *, model, max_tokens, system=None):
            from integrations.llm import LLMResult

            self.prompts.append(prompt)
            return LLMResult(text="Fine.", input_tokens=1, output_tokens=1)

    spy = _Spy()
    _write(
        spy,
        "m",
        heading="Why it matters",
        primary="ac repair san jose",
        intent="transactional",
        role="body",
        grounded=(),
        entities=(),
        max_words=133,
    )
    assert spy.prompts, "the writer was never called"
    assert "133 words" in spy.prompts[0], spy.prompts[0]
