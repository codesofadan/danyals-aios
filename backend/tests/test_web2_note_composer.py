"""The short-form composer: placements the article generator structurally cannot make.

``content_generator`` clamps its word budget to a 600-word FLOOR. Ask it for a
300-character Bluesky note and it returns 600 words; ``BlueskyClient`` then publishes
``text[:300]``. So the note is not a smaller article, and these tests pin the three
properties that make it a real placement instead of a fragment:

1. it FITS - and where the model overruns anyway, it is cut at a sentence boundary, never
   mid-word;
2. the LINK SURVIVES - the budget reserves room for the ``anchor: url`` the adapter
   appends afterwards, because a body that fills the ceiling deletes exactly the backlink
   the property exists to carry;
3. the ``[NEEDS:]`` discipline is unchanged - a 200-character placement is a smaller lie,
   not a permissible one.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import pytest

from app.config import Settings
from app.modules.web2 import note_composer as nc
from app.modules.web2.platform_spec import LINK_RESERVE_CHARS, spec_for
from app.platform.ai.router import ModelRouter, SummarizerBackend
from app.services.content_generator import SourcePack
from app.services.cost_gate import CostGate, GateContext
from integrations.llm import LLMResult
from integrations.web2_publishers import (
    PLATFORM_BLUESKY,
    PLATFORM_MASTODON,
    PLATFORM_PASTEBIN,
)

pytestmark = pytest.mark.unit


class _Canned:
    """A summarizer that returns exactly what a test hands it."""

    def __init__(self, text: str) -> None:
        self.text = text
        self.prompts: list[str] = []

    def summarize(
        self, prompt: str, *, model: str, max_tokens: int,
        system: str | Sequence[str] | None = None, cache: Sequence[bool] | None = None,
    ) -> LLMResult:
        self.prompts.append(prompt)
        return LLMResult(text=self.text, input_tokens=100, output_tokens=40)


class _Store:
    def __init__(self, *, halted: bool = False) -> None:
        self.halted = halted

    def dial_mode(self, feature_key: str) -> Any:
        return "on"

    def client_budget(self, client_id: str) -> tuple[float, float] | None:
        return None

    def is_halted(self) -> bool:
        return self.halted

    def record_cost(self, ctx: GateContext, cost: float, *, cached: bool) -> None:
        return None


class _Cache:
    def get(self, key: str) -> Any | None:
        return None

    def set(self, key: str, value: Any) -> None:
        return None


def _router(text: str, *, halted: bool = False) -> tuple[ModelRouter, _Canned]:
    inner = _Canned(text)
    gate = CostGate(_Store(halted=halted), _Cache())
    return ModelRouter(SummarizerBackend(inner), gate, Settings(app_env="dev")), inner


def _compose(text: str, *, platform: str = PLATFORM_BLUESKY, **kw: Any) -> nc.Note:
    router, _ = _router(text, halted=kw.pop("halted", False))
    return nc.compose(
        spec=spec_for(platform), topic="cctv drain survey", client_name="Acme Drains",
        geo="Leeds", source_pack=kw.pop("source_pack", SourcePack(client_name="Acme Drains")),
        router=kw.pop("router", router), **kw,
    )


# --------------------------------------------------------------------------- #
# 1. It fits
# --------------------------------------------------------------------------- #
def test_a_note_that_fits_is_left_exactly_as_written() -> None:
    note = _compose("A blocked drain usually shows itself weeks before it backs up.")
    assert note.text == "A blocked drain usually shows itself weeks before it backs up."
    assert note.trimmed is False
    assert note.publishable is True


def test_an_overlong_note_is_cut_at_a_sentence_not_mid_word() -> None:
    """The difference between a short post and a visibly severed one.

    Mid-word truncation is what the adapters already do; if this composer did the same
    thing it would have no reason to exist.
    """
    long_text = " ".join(
        f"Sentence number {i} about drain surveys in Leeds and what they show."
        for i in range(30)
    )
    note = _compose(long_text)

    budget = spec_for(PLATFORM_BLUESKY).max_body_chars or 0
    assert note.trimmed is True
    assert len(note.text) <= budget - LINK_RESERVE_CHARS
    assert note.text.endswith("."), "a trimmed note must end at a sentence boundary"
    assert not note.text.endswith(" "), "and must not leave dangling whitespace"


def test_one_sentence_longer_than_the_whole_budget_still_breaks_on_a_word() -> None:
    """The degenerate case. There is no sentence boundary to find, so the fallback is a
    word boundary - which is still never mid-word."""
    note = _compose("word " * 200)
    assert note.trimmed is True
    assert not note.text.endswith("wor"), "never a partial word"
    assert " " in note.text


def test_every_platform_shape_composes_inside_its_own_budget() -> None:
    long_text = " ".join(f"Point {i} about drainage." for i in range(200))
    for platform in (PLATFORM_BLUESKY, PLATFORM_MASTODON, PLATFORM_PASTEBIN):
        spec = spec_for(platform)
        note = _compose(long_text, platform=platform)
        ceiling = spec.max_body_chars
        if ceiling is not None:
            assert len(note.text) <= ceiling - LINK_RESERVE_CHARS, platform
        assert note.char_count == len(note.text)


# --------------------------------------------------------------------------- #
# 2. The link survives
# --------------------------------------------------------------------------- #
def test_the_budget_reserves_room_for_the_link_the_adapter_appends() -> None:
    """THE subtle half of the original defect.

    Every note-platform adapter builds ``f"{title}\\n\\n{body}\\n\\n{anchor}: {url}"`` and
    THEN truncates. A body sized to the platform's full ceiling therefore publishes with
    the backlink cut off - a placement that cost a model call, reports success, and
    carries nothing at all.
    """
    spec = spec_for(PLATFORM_BLUESKY)
    ceiling = spec.max_body_chars or 0
    note = _compose(" ".join(f"Sentence {i} here." for i in range(50)))

    room_left = ceiling - len(note.text)
    assert room_left >= LINK_RESERVE_CHARS, (
        f"only {room_left} characters left for 'anchor: url' on a {ceiling}-char platform"
    )


def test_the_prompt_forbids_writing_a_link_in_the_body() -> None:
    """Writing one inline would publish it twice - once in the prose, once appended."""
    router, inner = _router("A short note.")
    nc.compose(
        spec=spec_for(PLATFORM_BLUESKY), topic="drains", client_name="Acme",
        geo="Leeds", source_pack=SourcePack(client_name="Acme"), router=router,
    )
    prompt = inner.prompts[0]
    assert "Do NOT write a link" in prompt
    assert "appended after your text" in prompt


# --------------------------------------------------------------------------- #
# 3. Grounding discipline is unchanged
# --------------------------------------------------------------------------- #
def test_a_needs_gap_makes_the_note_unpublishable() -> None:
    note = _compose("We have served [NEEDS: years in business] customers in Leeds.")
    assert note.publishable is False


def test_an_empty_source_pack_is_stated_rather_than_left_blank() -> None:
    """An empty facts section reads to a model as an omission it may helpfully fill -
    which is the hallucination the [NEEDS:] discipline exists to prevent."""
    router, inner = _router("A note.")
    nc.compose(
        spec=spec_for(PLATFORM_BLUESKY), topic="drains", client_name="Acme",
        geo="Leeds", source_pack=None, router=router,
    )
    assert "No verified facts are available" in inner.prompts[0]


def test_the_source_pack_facts_reach_the_prompt() -> None:
    router, inner = _router("A note.")
    pack = SourcePack(
        client_name="Acme Drains",
        services=["CCTV drain surveys", "emergency unblocking"],
        proof_points=["1,400 surveys completed in 2025"],
        facts={"founded": "2011"},
    )
    nc.compose(
        spec=spec_for(PLATFORM_BLUESKY), topic="drains", client_name="Acme Drains",
        geo="Leeds", source_pack=pack, router=router,
    )
    prompt = inner.prompts[0]
    assert "CCTV drain surveys" in prompt
    assert "1,400 surveys completed in 2025" in prompt
    assert "founded: 2011" in prompt


# --------------------------------------------------------------------------- #
# Formatting the platform would destroy
# --------------------------------------------------------------------------- #
def test_markdown_the_platform_would_show_literally_is_stripped() -> None:
    """These platforms render to plain text. A heading the model emits becomes the
    literal characters ``## Why drains block`` on the page."""
    note = _compose("## Why drains block\n\n- roots\n- grease\n\n> a quote")
    assert "##" not in note.text
    assert not note.text.lstrip().startswith("-")
    assert ">" not in note.text


def test_paragraph_breaks_are_collapsed_into_one_block() -> None:
    note = _compose("First thought.\n\n\nSecond thought.")
    assert "\n\n" not in note.text


# --------------------------------------------------------------------------- #
# Degrading
# --------------------------------------------------------------------------- #
def test_without_a_router_the_note_holds_at_review_and_says_why() -> None:
    note = _compose("unused", router=None)
    assert note.publishable is False
    assert nc.NEEDS_MARKER in note.text
    assert note.spent_usd == 0.0
    assert any("degraded" in n for n in note.notes)


def test_a_cost_block_degrades_rather_than_raising() -> None:
    """Mirrors how the article path treats ``ContentSpendBlocked``: the placement HOLDS,
    the worker does not crash, and nothing was spent."""
    note = _compose("unused", halted=True)
    assert note.publishable is False
    assert note.spent_usd == 0.0
    assert any("spend_blocked" in n for n in note.notes)


def test_a_degraded_note_never_exceeds_the_platform_budget_either() -> None:
    spec = spec_for(PLATFORM_BLUESKY)
    note = _compose("unused", router=None)
    assert len(note.text) <= (spec.max_body_chars or 0) - LINK_RESERVE_CHARS
