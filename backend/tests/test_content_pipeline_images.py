"""The doctrine engine's image stage: what it draws, and what it refuses to charge for.

Two defects drove this file.

1. THE ENGINE PRODUCED NO IMAGES AT ALL. `settings.content_engine` defaults to `v2`
   and `PAGE_STAGES` had no image step, so every page the default engine wrote was
   text-only while its v1-written siblings all carried photos. Found by reading the
   stage list against `workers/tasks/content.py`'s `_generate_images`.

2. A KEYLESS RUN MUST NOT BE BILLED. v1 already fixed this once - it used to commit
   the per-image price BEFORE checking whether the generator was the deterministic
   `FakeImageGenerator`, so a deployment with no image key wrote spend into the cost
   ledger for provider calls that never happened. Re-porting the generator loop is
   exactly how that defect comes back, so the assertions below are written against
   the gate double, not against the return value.

Every test drives real `run_images` against doubles - no provider, no ledger.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.config import Settings, get_settings
from app.services.content_pipeline.context import PipelineContext
from app.services.content_pipeline.images import (
    DEFAULT_MAX_IMAGES,
    inject_images,
    max_images_for,
    plan_images,
    run_images,
)
from app.services.cost_gate import GateContext, GateDecision
from integrations.images import FakeImageGenerator, GeneratedImage

pytestmark = pytest.mark.unit

_DRAFT = """# Emergency plumber in Dallas

We answer the phone at 2am, every night.

## What a burst pipe costs

Water spreads fast.

## How fast we get there

Twenty minutes, most nights.

## What we check first

The main shutoff.
"""


class _Generator:
    """A REAL-looking generator: not a FakeImageGenerator, so the stage may spend."""

    def __init__(self, *, url: str = "https://cdn.example/{n}.png", boom: bool = False) -> None:
        self.calls: list[tuple[str, str]] = []
        self._url = url
        self._boom = boom

    def generate(self, prompt: str, alt: str) -> GeneratedImage:
        self.calls.append((prompt, alt))
        if self._boom:
            raise RuntimeError("provider 503")
        return GeneratedImage(url=self._url.format(n=len(self.calls)), alt=alt)


class _Gate:
    """Records every evaluate/commit so a phantom charge cannot hide in a return value."""

    def __init__(self, *, allow: int = 99) -> None:
        self.evaluated: list[GateContext] = []
        self.committed: list[tuple[GateContext, float]] = []
        self._allow = allow

    def evaluate(self, ctx: GateContext) -> GateDecision:
        self.evaluated.append(ctx)
        if len(self.evaluated) > self._allow:
            return GateDecision(outcome="blocked_cap", reason="client budget cap reached")
        return GateDecision(outcome="call", cost=ctx.estimated_cost)

    def commit(self, ctx: GateContext, cost: float, *, cache_value: Any | None = None) -> None:
        self.committed.append((ctx, cost))


def _ctx(draft: str = _DRAFT, **kw: Any) -> PipelineContext:
    base: dict[str, Any] = {
        "job_code": "CJ-4200",
        "client_id": "c-1",
        "client_name": "Dallas Plumbing",
        "primary_keyword": "emergency plumber dallas",
        "page_type": "service",
    }
    base.update(kw)
    ctx = PipelineContext(**base)
    ctx.draft_md = draft
    return ctx


def _settings(**kw: Any) -> Settings:
    return get_settings().model_copy(update=kw)


class TestAKeylessDeploymentIsNeverBilled:
    """v1's hard-won rule, re-ported. The provider factory substitutes
    FakeImageGenerator when IMAGE_GEN_API_KEY is absent; its URLs are sha256
    placeholders. Charging for them wrote ledger rows for calls that never happened,
    and reported an image count for pictures that do not exist."""

    def test_a_fake_generator_writes_no_cost_row_and_no_image_count(self) -> None:
        gate = _Gate()
        ctx = _ctx()
        result = run_images(
            ctx, generator=FakeImageGenerator(), gate=gate,
            settings=_settings(content_pipeline_max_images=3),
        )
        assert gate.committed == [], "a keyless run must not write a cost row"
        assert gate.evaluated == [], "a keyless run must not even ask the gate"
        assert result.cost == 0.0
        assert result.data["images"] == 0
        assert result.outcome == "skipped"

    def test_it_says_which_key_is_missing_rather_than_reporting_a_silent_zero(self) -> None:
        result = run_images(
            _ctx(), generator=FakeImageGenerator(), gate=_Gate(),
            settings=_settings(content_pipeline_max_images=3),
        )
        assert any("IMAGE_GEN_API_KEY" in n for n in result.notes)

    def test_no_placeholder_image_is_injected_into_the_draft(self) -> None:
        """A sha256 placeholder URL in a client's page is a broken picture on a live
        site - worse than the absence it was standing in for."""
        ctx = _ctx()
        run_images(
            ctx, generator=FakeImageGenerator(), gate=_Gate(),
            settings=_settings(content_pipeline_max_images=3),
        )
        assert ctx.draft_md == _DRAFT


class TestEveryGeneratedImageGoesThroughTheCostGate:
    def test_each_image_is_evaluated_and_committed_once(self) -> None:
        gate, gen = _Gate(), _Generator()
        settings = _settings(content_pipeline_max_images=3, price_image_per_image=0.04)
        result = run_images(_ctx(), generator=gen, gate=gate, settings=settings)
        assert len(gen.calls) == 3
        assert len(gate.evaluated) == 3
        assert [round(c, 4) for _ctx_, c in gate.committed] == [0.04, 0.04, 0.04]
        assert round(result.cost, 4) == 0.12

    def test_the_gate_context_names_the_content_dial_and_the_images_provider(self) -> None:
        """A wrong feature_key makes the spend unswitchable-off: `dial_mode()` falls
        back to "off" for an unregistered key, which is how four Part-8 modules
        shipped dead paid paths (workers/tasks defect e8964de)."""
        gate = _Gate()
        run_images(
            _ctx(), generator=_Generator(), gate=gate,
            settings=_settings(content_pipeline_max_images=1),
        )
        first = gate.evaluated[0]
        assert first.feature_key == "content"
        assert first.provider == "images"
        assert first.job_type == "content"
        assert first.client_id == "c-1"
        assert first.job_id == "CJ-4200"

    def test_a_blocked_dial_stops_images_without_losing_the_page(self) -> None:
        gate, gen = _Gate(allow=1), _Generator()
        ctx = _ctx()
        result = run_images(
            ctx, generator=gen, gate=gate,
            settings=_settings(content_pipeline_max_images=3),
        )
        assert len(gen.calls) == 1, "the second evaluate was blocked; no call may follow"
        assert len(gate.committed) == 1
        assert result.outcome == "degraded"
        assert any("blocked_cap" in n for n in result.notes)
        assert ctx.draft_md.count("![") == 1, "the one image that was paid for is kept"

    def test_a_provider_that_returns_no_url_is_not_charged_for(self) -> None:
        """The ledger records what happened, not what was attempted."""
        gate, gen = _Gate(), _Generator(url="")
        result = run_images(
            _ctx(), generator=gen, gate=gate,
            settings=_settings(content_pipeline_max_images=2),
        )
        assert gate.committed == []
        assert result.cost == 0.0
        assert result.data["images"] == 0
        assert result.outcome == "degraded"

    def test_a_provider_error_never_loses_a_written_page(self) -> None:
        gate, gen = _Gate(), _Generator(boom=True)
        ctx = _ctx()
        result = run_images(
            ctx, generator=gen, gate=gate,
            settings=_settings(content_pipeline_max_images=2),
        )
        assert result.outcome == "degraded", "a failed image is a degrade, never a halt"
        assert not result.blocks_pipeline
        assert gate.committed == []
        assert ctx.draft_md == _DRAFT


class TestTheCountIsConservativeAndConfigurable:
    def test_the_shipped_default_is_one_hero_image(self) -> None:
        """v1's cap is 5. Defaulting v2 to 5 would quintuple the per-page image bill on
        an engine that has never had a paid image run."""
        assert DEFAULT_MAX_IMAGES == 1
        assert Settings().content_pipeline_max_images == 1, (
            "the setting must exist on Settings - a getattr fallback would let the "
            "field be deleted without anything noticing"
        )

    def test_the_default_page_gets_exactly_one_image(self) -> None:
        gen = _Generator()
        ctx = _ctx()
        run_images(ctx, generator=gen, gate=_Gate(), settings=_settings())
        assert len(gen.calls) == 1
        assert ctx.draft_md.count("![") == 1

    def test_the_platform_photo_switch_still_wins(self) -> None:
        """`content_images_enabled` is the existing dial v1 honours; a deployment that
        turned photos off must not have the new engine turn them back on."""
        assert max_images_for(_settings(content_images_enabled=False,
                                        content_pipeline_max_images=5)) == 0

    def test_zero_images_generates_nothing_and_says_why(self) -> None:
        gate, gen = _Gate(), _Generator()
        result = run_images(
            _ctx(), generator=gen, gate=gate,
            settings=_settings(content_pipeline_max_images=0),
        )
        assert gen.calls == [] and gate.evaluated == []
        assert result.outcome == "skipped"
        assert any("switched off" in n for n in result.notes)


class TestThePlanCostsNothingToMake:
    """v1 spends a writer call per page whose only product is a decision about what to
    photograph. Adding that call here would make an image stage cost tokens before it
    costs a cent."""

    def test_planning_reads_the_draft_and_needs_no_writer(self) -> None:
        plan = plan_images(_ctx(), max_images=3)
        assert [item.alt for item in plan] == [
            "Emergency plumber in Dallas",
            "What a burst pipe costs",
            "How fast we get there",
        ]
        assert plan[0].slot == "hero"
        assert plan[1].slot.startswith("section:")

    def test_the_prompt_never_contains_the_page_topic(self) -> None:
        """PROVEN at the provider (content_generator.py:971): handed an abstract topic
        as its subject, gpt-image renders that topic AS TITLE TEXT and returns a
        flat-vector infographic. The topic belongs in the alt text, never the prompt."""
        plan = plan_images(_ctx(), max_images=2)
        for item in plan:
            assert "emergency plumber dallas" not in item.prompt.lower()
            assert "burst pipe" not in item.prompt.lower()

    def test_two_pages_do_not_get_the_same_hero_photo(self) -> None:
        """The scene bank is topic-free, so without a per-page rotation every page on a
        client's site would open with the identical stock photo."""
        a = plan_images(_ctx(primary_keyword="emergency plumber dallas"), max_images=1)
        b = plan_images(_ctx(primary_keyword="water heater repair austin"), max_images=1)
        assert a[0].prompt != b[0].prompt

    def test_the_same_page_re_drafted_gets_the_same_photos(self) -> None:
        assert plan_images(_ctx(), max_images=2) == plan_images(_ctx(), max_images=2)

    def test_a_draft_with_no_headings_still_gets_a_hero(self) -> None:
        plan = plan_images(_ctx("Just prose, no headings at all.", title="A page"), max_images=2)
        assert len(plan) == 1 and plan[0].slot == "hero"

    def test_a_draft_with_nothing_to_name_plans_nothing(self) -> None:
        plan = plan_images(_ctx("prose only", primary_keyword="", title=""), max_images=2)
        assert plan == ()


class TestImagesLandInTheSectionTheyIntroduce:
    """v1's placement rule, which is ORDER-based on purpose: matching an image's alt to
    a heading collapses every image into one spot the moment the voice stage rephrases
    a heading."""

    def _images(self, n: int) -> list[tuple[str, GeneratedImage]]:
        out: list[tuple[str, GeneratedImage]] = [
            ("hero", GeneratedImage(url="https://cdn/h.png", alt="hero"))
        ]
        for i in range(n - 1):
            out.append((f"section:{i}", GeneratedImage(url=f"https://cdn/s{i}.png", alt=f"s{i}")))
        return out

    def test_the_hero_sits_under_the_h1_and_sections_under_their_h2(self) -> None:
        out = inject_images(_DRAFT, self._images(3)).splitlines()
        h1 = out.index("# Emergency plumber in Dallas")
        first_h2 = out.index("## What a burst pipe costs")
        second_h2 = out.index("## How fast we get there")
        assert "![hero](https://cdn/h.png)" in out[h1 + 1: first_h2]
        assert "![s0](https://cdn/s0.png)" in out[first_h2 + 1: second_h2]
        assert "![s1](https://cdn/s1.png)" in out[second_h2 + 1:]

    def test_a_draft_with_no_h1_puts_the_hero_at_the_very_top(self) -> None:
        out = inject_images("Some prose.\n\n## A section\n\nMore.", self._images(1))
        assert out.startswith("![hero](https://cdn/h.png)")

    def test_nothing_is_written_when_nothing_was_generated(self) -> None:
        assert inject_images(_DRAFT, []) == _DRAFT


class TestTheStageReportsWhatItActuallyDid:
    def test_a_full_run_reports_ok_with_its_urls(self) -> None:
        result = run_images(
            _ctx(), generator=_Generator(), gate=_Gate(),
            settings=_settings(content_pipeline_max_images=2),
        )
        assert result.outcome == "ok"
        assert result.data == {
            "images": 2,
            "planned": 2,
            "slots": ["hero", "section:what-a-burst-pipe-costs"],
            "alts": ["Emergency plumber in Dallas", "What a burst pipe costs"],
            "urls": ["https://cdn.example/1.png", "https://cdn.example/2.png"],
        }

    def test_it_admits_the_photo_does_not_depict_the_topic(self) -> None:
        """The scene bank is topic-free because a topical prompt renders an
        infographic. That is a real limitation of the free plan, so it is stated
        rather than left for someone to discover in a client's page."""
        result = run_images(
            _ctx(), generator=_Generator(), gate=_Gate(), settings=_settings(),
        )
        assert any("alt text" in n for n in result.notes)

    def test_no_draft_means_no_spend(self) -> None:
        gate = _Gate()
        result = run_images(_ctx(""), generator=_Generator(), gate=gate, settings=_settings())
        assert result.outcome == "skipped" and gate.evaluated == []

    def test_an_image_generation_is_not_counted_as_an_llm_call(self) -> None:
        """`llm_calls` drives the token/cache reporting; an image has no tokens, so
        counting it there would put a call with no tokens into a token report."""
        result = run_images(
            _ctx(), generator=_Generator(), gate=_Gate(), settings=_settings(),
        )
        assert result.llm_calls == 0
        assert result.cost > 0
