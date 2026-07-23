"""Wave 5: EXHAUSTIVE unit tests for the AI / em-dash content guard.

The load-bearing contract under test: after :func:`strip_dashes`, :func:`deai_draft`,
or :func:`guard_generated`, the text is GUARANTEED to contain ZERO em (U+2014) and
en (U+2013) dashes - even when the injected writer (perversely) emits one of its own,
or raises, or is absent entirely. These tests prove that guarantee against adversarial
inputs, plus the detection layer (dash counts, AI-cliche phrases, the flag verdict) and
the block-level rewrite routing.
"""

from __future__ import annotations

import pytest

from app.services.content_generator import (
    DifferentiationAngle,
    GeneratedContent,
    Heading,
)
from app.services.content_guard import (
    EM_DASH,
    EN_DASH,
    count_dashes,
    deai_draft,
    find_ai_tells,
    guard_generated,
    has_forbidden_dashes,
    scan,
    split_blocks,
    strip_dashes,
)
from integrations.llm import LLMResult

pytestmark = pytest.mark.unit


# --------------------------------------------------------------------------- #
# Controllable fake writers
# --------------------------------------------------------------------------- #
class _CleanWriter:
    """Returns a fixed clean phrase; counts calls and records every prompt."""

    def __init__(self, reply: str = "Fresh brunch every weekend at our cafe.") -> None:
        self.reply = reply
        self.calls = 0
        self.prompts: list[str] = []

    def summarize(self, prompt: str, *, model: str, max_tokens: int) -> LLMResult:
        self.calls += 1
        self.prompts.append(prompt)
        return LLMResult(text=self.reply, input_tokens=10, output_tokens=8)


class _DashInjectingWriter:
    """An adversarial writer that ALWAYS emits an em dash in its reply. The hard
    strip must still guarantee a dash-free final draft."""

    def summarize(self, prompt: str, *, model: str, max_tokens: int) -> LLMResult:
        return LLMResult(text=f"We open early{EM_DASH}very early{EN_DASH}for brunch.", input_tokens=5, output_tokens=5)


class _ExplodingWriter:
    """Raises on every call; the guard must fall back to a plain strip, never raise."""

    def summarize(self, prompt: str, *, model: str, max_tokens: int) -> LLMResult:
        raise RuntimeError("provider down")


# --------------------------------------------------------------------------- #
# count_dashes / has_forbidden_dashes
# --------------------------------------------------------------------------- #
def test_count_dashes_counts_each_kind() -> None:
    assert count_dashes("plain hyphen - text") == (0, 0)
    assert count_dashes(f"a{EM_DASH}b") == (1, 0)
    assert count_dashes(f"a{EN_DASH}b") == (0, 1)
    assert count_dashes(f"a{EM_DASH}b{EM_DASH}c{EN_DASH}d") == (2, 1)


def test_has_forbidden_dashes() -> None:
    assert has_forbidden_dashes(f"one{EM_DASH}two") is True
    assert has_forbidden_dashes(f"five{EN_DASH}ten") is True
    assert has_forbidden_dashes("a plain, comma sentence - with a hyphen") is False


# --------------------------------------------------------------------------- #
# strip_dashes - the HARD guarantee
# --------------------------------------------------------------------------- #
def test_strip_dashes_replaces_em_and_en() -> None:
    assert strip_dashes(f"open early{EM_DASH}very early") == "open early - very early"
    assert strip_dashes(f"a {EM_DASH} b") == "a - b"
    assert strip_dashes(f"word{EN_DASH}word") == "word - word"


def test_strip_dashes_numeric_range_collapses_tight() -> None:
    assert strip_dashes(f"5{EN_DASH}10 days") == "5-10 days"
    assert strip_dashes(f"9{EM_DASH}5 daily") == "9-5 daily"
    assert strip_dashes(f"open 9 {EN_DASH} 5") == "open 9-5"


def test_strip_dashes_handles_other_unicode_dashes() -> None:
    for dash in (chr(0x2012), chr(0x2015), chr(0x2011)):  # figure, bar, nb hyphen
        cleaned = strip_dashes(f"a{dash}b")
        assert count_dashes(cleaned) == (0, 0)
        assert all(chr(c) not in cleaned for c in (0x2012, 0x2015, 0x2011))


def test_strip_dashes_preserves_newlines_and_markdown_lists() -> None:
    src = f"# Heading{EM_DASH}Two\n\n- a bullet\n- another{EN_DASH}bullet\n"
    out = strip_dashes(src)
    assert count_dashes(out) == (0, 0)
    assert out.count("\n") == src.count("\n")  # no line break swallowed
    assert "- a bullet" in out  # a markdown list marker is untouched


def test_strip_dashes_is_idempotent_and_total() -> None:
    adversarial = f"{EM_DASH}{EN_DASH}5{EN_DASH}10{EM_DASH}{EM_DASH}word{EN_DASH}9{EM_DASH}5"
    once = strip_dashes(adversarial)
    assert count_dashes(once) == (0, 0)  # THE guarantee
    assert strip_dashes(once) == strip_dashes(strip_dashes(once))  # stable


# --------------------------------------------------------------------------- #
# find_ai_tells
# --------------------------------------------------------------------------- #
def test_find_ai_tells_detects_phrases_case_insensitively() -> None:
    labels = {f.text for f in find_ai_tells("In today's fast-paced world, WHEN IT COMES TO brunch")}
    assert "in today's fast-paced world" in labels
    assert "when it comes to" in labels


def test_find_ai_tells_word_boundary_seamless_vs_seamlessly() -> None:
    # "seamlessly" must not also match the shorter "seamless" (both are phrases, but
    # each is counted as its own tell, once).
    tells = {f.text: f.count for f in find_ai_tells("Our seamlessly integrated service")}
    assert tells.get("seamlessly") == 1
    assert "seamless" not in tells


def test_find_ai_tells_templates() -> None:
    labels = {f.text for f in find_ai_tells("Not only fast but also friendly service")}
    assert "not only ... but also" in labels


def test_find_ai_tells_clean_text_is_empty() -> None:
    assert find_ai_tells("We serve fresh brunch in Portland. Book a table today.") == []


# --------------------------------------------------------------------------- #
# scan
# --------------------------------------------------------------------------- #
def test_scan_flags_any_forbidden_dash() -> None:
    report = scan(f"A tidy sentence{EM_DASH}with an em dash.")
    assert report.em_dashes == 1
    assert report.flagged is True
    assert report.dash_free is False
    assert report.clean is False


def test_scan_clean_prose_not_flagged() -> None:
    report = scan("We serve fresh brunch in Portland. Book your table today.")
    assert report.dash_free is True
    assert report.flagged is False
    assert report.clean is True
    assert report.ai_score == 0


def test_scan_flags_on_ai_phrase_density() -> None:
    text = (
        "In today's fast-paced world, when it comes to brunch, rest assured our "
        "world-class, cutting-edge, top-notch kitchen will elevate your morning."
    )
    report = scan(text)
    assert report.phrase_count >= 4
    assert report.flagged is True


def test_scan_ai_score_rises_with_tells() -> None:
    low = scan("Fresh brunch, booked in seconds.").ai_score
    high = scan(f"Fresh brunch{EM_DASH}booked in seconds, world-class and cutting-edge.").ai_score
    assert high > low


# --------------------------------------------------------------------------- #
# split_blocks
# --------------------------------------------------------------------------- #
def test_split_blocks_classifies() -> None:
    md = "# Title\n\nA prose paragraph here.\n\n- bullet one\n- bullet two\n\n[NEEDS: a fact]"
    kinds = [b.kind for b in split_blocks(md)]
    assert kinds == ["heading", "prose", "list", "needs"]


# --------------------------------------------------------------------------- #
# deai_draft - the writer-injected rewrite + the hard guarantee
# --------------------------------------------------------------------------- #
def test_deai_draft_no_writer_still_strips_all_dashes() -> None:
    draft = f"# Best Brunch{EM_DASH}Portland\n\nWe open early{EM_DASH}very early{EN_DASH}for brunch.\n"
    result = deai_draft(draft, writer=None)
    assert count_dashes(result.draft_md) == (0, 0)  # THE guarantee, even with no writer
    assert result.after.dash_free is True
    assert result.rewritten == 0  # no writer -> nothing rephrased
    assert result.writer_calls == 0


def test_deai_draft_rewrites_flagged_prose_and_is_dash_free() -> None:
    writer = _CleanWriter()
    draft = (
        "# Brunch\n\n"
        f"Our kitchen is world-class and cutting-edge{EM_DASH}truly top-notch.\n\n"
        "- a grounded bullet\n"
    )
    result = deai_draft(draft, writer=writer, model="fake")
    assert count_dashes(result.draft_md) == (0, 0)
    assert result.rewritten == 1  # the flagged prose block was rephrased
    assert writer.calls == 1
    assert "- a grounded bullet" in result.draft_md  # the list block was NOT sent to the writer


def test_deai_draft_hard_strips_even_when_writer_injects_a_dash() -> None:
    # The adversarial writer ALWAYS returns an em dash; the unconditional post-strip
    # must still guarantee a dash-free result.
    draft = f"# Brunch\n\nOur service is seamless and world-class{EM_DASH}truly cutting-edge.\n"
    result = deai_draft(draft, writer=_DashInjectingWriter(), model="fake")
    assert count_dashes(result.draft_md) == (0, 0)  # THE guarantee holds vs a hostile provider
    assert result.rewritten == 1


def test_deai_draft_writer_failure_falls_back_to_strip_never_raises() -> None:
    draft = f"# Brunch\n\nworld-class and cutting-edge{EM_DASH}top-notch service everywhere.\n"
    result = deai_draft(draft, writer=_ExplodingWriter(), model="fake")  # must not raise
    assert count_dashes(result.draft_md) == (0, 0)
    assert result.writer_calls == 0  # the failed call is not counted as a spend


def test_deai_draft_protects_the_answer_block() -> None:
    answer = f"Best brunch in Portland{EM_DASH}served fresh daily by our team, booked online now."
    writer = _CleanWriter()
    draft = f"# Brunch\n\n{answer}\n\nOur world-class, cutting-edge, top-notch kitchen delivers.\n"
    result = deai_draft(draft, writer=writer, model="fake", protect=frozenset({answer}))
    # The protected answer block was dash-stripped but NEVER sent to the writer.
    assert count_dashes(result.draft_md) == (0, 0)
    assert all(answer not in p for p in writer.prompts)
    assert "Best brunch in Portland - served fresh daily" in result.draft_md


def test_deai_draft_headings_and_lists_never_rewritten() -> None:
    writer = _CleanWriter()
    draft = "## A heading with world-class cutting-edge top-notch tells\n\n- world-class bullet item\n"
    result = deai_draft(draft, writer=writer, model="fake")
    assert writer.calls == 0  # neither a heading nor a list block is a rewrite candidate
    assert result.rewritten == 0


def test_deai_draft_max_rewrites_caps_writer_calls() -> None:
    writer = _CleanWriter()
    block = f"world-class cutting-edge top-notch service{EM_DASH}everywhere you look."
    draft = "\n\n".join(f"{block} number {i}." for i in range(5))
    result = deai_draft(draft, writer=writer, model="fake", max_rewrites=2)
    assert writer.calls == 2  # capped
    assert count_dashes(result.draft_md) == (0, 0)  # the rest still get plain-stripped


def test_deai_draft_before_after_reports() -> None:
    draft = f"# Brunch\n\nOpen early{EM_DASH}very early for brunch.\n"
    result = deai_draft(draft, writer=None)
    assert result.before.em_dashes == 1
    assert result.after.em_dashes == 0


# --------------------------------------------------------------------------- #
# guard_generated - the GeneratedContent adapter
# --------------------------------------------------------------------------- #
def _content(**over: object) -> GeneratedContent:
    base: dict[str, object] = {
        "title": f"Best Brunch{EM_DASH}Portland",
        "meta_description": f"Fresh brunch daily{EN_DASH}book now.",
        "draft_md": f"# Best Brunch{EM_DASH}Portland\n\nWe open early{EM_DASH}very early for brunch.\n",
        "page_type": "blog",
        "framework": "PAS",
        "target": "WordPress",
        "headings": [Heading(level=1, text=f"Best Brunch{EM_DASH}Portland")],
        "answer_block": f"Best brunch in Portland{EM_DASH}served fresh.",
        "section_roles": ["problem"],
        "differentiation_angle": DifferentiationAngle(
            kind="unique_data", statement="Our guest survey", grounded=True, derived_from=[]
        ),
        "internal_links": [],
        "images_plan": [],
        "grounding": [],
        "needs": [],
        "word_count": 12,
        "primary_density": 0.01,
        "entities_covered": [],
        "entities_missing": [],
        "local_uniqueness": {},
        "notes": [],
    }
    base.update(over)
    return GeneratedContent(**base)  # type: ignore[arg-type]


def test_guard_generated_strips_every_text_field() -> None:
    guarded = guard_generated(_content(), writer=None)
    c = guarded.content
    assert count_dashes(c.title) == (0, 0)
    assert count_dashes(c.meta_description) == (0, 0)
    assert count_dashes(c.draft_md) == (0, 0)
    assert count_dashes(c.answer_block) == (0, 0)
    for h in c.headings:
        assert count_dashes(h.text) == (0, 0)
    assert guarded.result.after.dash_free is True


def test_guard_generated_records_a_note_and_recounts_words() -> None:
    guarded = guard_generated(_content(), writer=None)
    assert any("content guard" in n for n in guarded.content.notes)
    assert guarded.content.word_count > 0


def test_guard_generated_dash_free_even_with_adversarial_writer() -> None:
    # A flagged body + a writer that injects a dash: the final content is still clean.
    content = _content(
        draft_md=(
            "# Brunch\n\n"
            f"Our world-class, cutting-edge, top-notch kitchen{EM_DASH}truly seamless.\n"
        )
    )
    guarded = guard_generated(content, writer=_DashInjectingWriter())
    assert count_dashes(guarded.content.draft_md) == (0, 0)
