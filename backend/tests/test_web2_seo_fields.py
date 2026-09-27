"""SEO fields for a placement - and the discipline of only deriving what exists.

``M05`` REQ-W2-008 says "SEO fields **wherever the platform has them**", and the
qualifier is the design. The failure this guards against is not a missing description, it
is a *fabricated* one: deriving a meta description for Bluesky is a metered model call
producing a string nothing will ever read, on every placement, forever.

The second thing pinned here is the distinction between an EMPTY field and an ABSENT one.
A Bluesky placement with no meta description is correct; a Ghost placement with no meta
description is a defect. If both stored ``''`` nobody could tell them apart, which is why
:meth:`SeoFields.as_row` omits blanks rather than writing them.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import pytest

from app.config import Settings
from app.modules.web2 import seo_fields as sf
from app.modules.web2.platform_spec import spec_for
from app.platform.ai.router import ModelRouter, SummarizerBackend
from app.services.cost_gate import CostGate, GateContext
from integrations.llm import LLMResult
from integrations.web2_publishers import (
    PLATFORM_BLUESKY,
    PLATFORM_DEVTO,
    PLATFORM_GHOST,
    PLATFORM_PASTEBIN,
)

pytestmark = pytest.mark.unit

BODY = (
    "# What a CCTV drain survey actually shows\n\n"
    "A camera survey finds the blockage before it becomes a collapse. "
    "Most reports we run in Leeds come back with root ingress at a joint. "
    "The repair is cheaper the earlier it is found.\n\n"
    "## How it works\n\n- a camera goes in\n- we record the run\n"
)


class _Canned:
    def __init__(self, text: str) -> None:
        self.text = text
        self.calls = 0
        self.prompts: list[str] = []

    def summarize(
        self, prompt: str, *, model: str, max_tokens: int,
        system: str | Sequence[str] | None = None, cache: Sequence[bool] | None = None,
    ) -> LLMResult:
        self.calls += 1
        self.prompts.append(prompt)
        return LLMResult(text=self.text, input_tokens=80, output_tokens=30)


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


def _router(text: str = "A camera survey finds the blockage before it becomes a collapse.",
            *, halted: bool = False) -> tuple[ModelRouter, _Canned]:
    inner = _Canned(text)
    gate = CostGate(_Store(halted=halted), _Cache())
    return ModelRouter(SummarizerBackend(inner), gate, Settings(app_env="dev")), inner


def _derive(platform: str, **kw: Any) -> sf.SeoFields:
    router = kw.pop("router", _router()[0])
    return sf.derive(
        spec=spec_for(platform), title="What a CCTV drain survey actually shows",
        body_md=BODY, topic="cctv drain survey", client_name="Acme Drains",
        router=router, **kw,
    )


# --------------------------------------------------------------------------- #
# Only derive what the platform transmits
# --------------------------------------------------------------------------- #
def test_a_platform_without_a_description_field_never_spends_on_one() -> None:
    """THE rule. Bluesky's adapter sends a 300-character status - there is nowhere for a
    meta description to go, so producing one is pure waste repeated per placement."""
    router, inner = _router()
    fields = _derive(PLATFORM_BLUESKY, router=router)

    assert fields.meta_description == ""
    assert inner.calls == 0, "no model call may be made for a field that cannot be sent"
    assert fields.spent_usd == 0.0
    assert any("no meta description" in n for n in fields.notes), (
        "the absence must be STATED - a thin report is indistinguishable from a bug "
        "unless somebody wrote down which it is"
    )


def test_a_platform_with_a_description_field_gets_one() -> None:
    router, inner = _router()
    fields = _derive(PLATFORM_GHOST, router=router)

    assert fields.meta_description
    assert inner.calls == 1
    assert fields.spent_usd > 0


def test_slug_and_tags_follow_the_platforms_own_support() -> None:
    ghost = _derive(PLATFORM_GHOST, candidate_tags=("Drain Surveys", "Leeds"))
    assert ghost.slug == "what-a-cctv-drain-survey-actually-shows"
    assert ghost.tags == ("drain-surveys", "leeds")

    # Pastebin's adapter sends plain text with no slug or tags at all.
    paste = _derive(PLATFORM_PASTEBIN, candidate_tags=("Drain Surveys",))
    assert paste.slug == ""
    assert paste.tags == ()


def test_tags_are_capped_at_the_platforms_measured_limit() -> None:
    """dev.to slices to ``_MAX_TAGS=4``. Sending ten means six were chosen, carried and
    dropped without anyone being told which - so the cap is applied where the choice is."""
    fields = _derive(
        PLATFORM_DEVTO,
        candidate_tags=("one", "two", "three", "four", "five", "six"),
    )
    assert len(fields.tags) == spec_for(PLATFORM_DEVTO).max_tags == 4
    assert fields.tags == ("one", "two", "three", "four")


def test_a_canonical_is_only_set_where_the_adapter_sends_one() -> None:
    """Hashnode's adapter DELIBERATELY omits its canonical field - pointing a property's
    canonical at the client's page declares the property a duplicate and voids the link.
    The spec must not claim a capability the adapter refuses to use."""
    assert not spec_for("Hashnode").supports_canonical
    fields = _derive(PLATFORM_DEVTO, canonical_url="https://example.test/post")
    assert fields.canonical_url == "https://example.test/post"
    assert _derive(PLATFORM_BLUESKY, canonical_url="https://example.test/post").canonical_url == ""


# --------------------------------------------------------------------------- #
# Absent vs empty
# --------------------------------------------------------------------------- #
def test_as_row_omits_blank_fields_rather_than_writing_empty_strings() -> None:
    """NULL says "this platform has no such field"; '' would say "we produced an empty
    one". An operator reading a thin report needs to tell those apart."""
    row = _derive(PLATFORM_BLUESKY).as_row
    assert "meta_description" not in row
    assert "slug" not in row
    assert "tags" not in row

    ghost_row = _derive(PLATFORM_GHOST, candidate_tags=("leeds",)).as_row
    assert ghost_row["meta_description"]
    assert ghost_row["slug"]
    assert ghost_row["tags"] == ["leeds"]


# --------------------------------------------------------------------------- #
# The description itself
# --------------------------------------------------------------------------- #
def test_a_long_description_is_cut_at_a_word_boundary() -> None:
    """Enforcing the length limit must not reintroduce the failure the limit exists to
    prevent: a description cut mid-word."""
    router, _ = _router("word " * 200)
    fields = _derive(PLATFORM_GHOST, router=router)

    assert len(fields.meta_description) <= sf.META_DESCRIPTION_CHARS
    assert not fields.meta_description.endswith("wor")
    assert not fields.meta_description.endswith(" ")


def test_model_wrapping_is_stripped() -> None:
    router, _ = _router('  "A camera survey finds the blockage early."  ')
    assert _derive(PLATFORM_GHOST, router=router).meta_description == (
        "A camera survey finds the blockage early."
    )


def test_the_excerpt_fed_to_the_writer_drops_headings_and_markup() -> None:
    """A heading is a label. Feeding it to a description writer produces a description
    that restates the title - which the prompt's own rule 2 forbids."""
    router, inner = _router()
    _derive(PLATFORM_GHOST, router=router)
    prompt = inner.prompts[0]

    assert "# What a CCTV drain survey" not in prompt
    assert "A camera survey finds the blockage" in prompt
    assert "- a camera goes in" not in prompt, "list scaffolding is not prose"


# --------------------------------------------------------------------------- #
# Degrading
# --------------------------------------------------------------------------- #
def test_without_a_router_a_description_is_still_produced_from_the_page() -> None:
    """Worse prose than a model would write, and materially better than an empty tag:
    the page describes itself in the SERP instead of letting the engine invent a snippet."""
    fields = _derive(PLATFORM_GHOST, router=None)

    assert fields.meta_description
    assert "camera survey" in fields.meta_description
    assert fields.spent_usd == 0.0
    assert any("no router" in n for n in fields.notes)


def test_a_cost_block_degrades_to_the_deterministic_description() -> None:
    """A description is worth a fraction of a cent. Refusing the whole placement over one
    would spend the operator's budget ceiling on nothing."""
    router, _ = _router(halted=True)
    fields = _derive(PLATFORM_GHOST, router=router)

    assert fields.meta_description
    assert fields.spent_usd == 0.0
    assert any("degraded" in n for n in fields.notes)


def test_a_slug_stays_url_safe_and_readable() -> None:
    assert sf._slugify("Tom's Drains & Sons — Leeds!") == "tom-s-drains-sons-leeds"
    long_slug = sf._slugify("a " * 80)
    assert len(long_slug) <= sf.MAX_SLUG_CHARS
    assert not long_slug.endswith("-")
