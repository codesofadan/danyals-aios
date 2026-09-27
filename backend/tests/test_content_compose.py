"""The templated page: a wireframe the writer FILLS, not a wrapper applied to prose.

THE DEFECT THIS LOCKS OUT, measured on a real client push before the rewrite: a service page
whose template specified eleven sections published with three. The template reached only the
publish path, where it was applied as a wrapper over prose the writer had produced to its own
plan - so "Pricing" and "What clients say" found nothing that looked like a price or a quote,
every slot collapsed into one prose band, and the five generated images were injected between
paragraphs wherever an H2 happened to fall.

So the assertions here are about STRUCTURE SURVIVING THE WHOLE JOURNEY:

  * every template is exactly seven slots, hero first, cta last;
  * a slot the client has no evidence for is DROPPED, never filled from imagination;
  * a filled page renders as components (cards, steps, accordion, price table) rather than
    as one prose band with headings in it;
  * images go to the hero and to prose, never to a card grid, and a page asks for only as
    many as it can place;
  * the claims guard still runs - on structured fields now, because there is no document.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from app.services.content_pipeline.compose import (
    ComposedSection,
    build_prompt,
    compose_page,
    evidence_available,
    plan_slots,
    scrub_sections,
    sections_to_markdown,
)
from app.services.content_pipeline.context import PipelineContext
from app.services.content_pipeline.slots import parse_json_object, validate_slot
from app.services.page_blueprints import TEMPLATES, get_template
from app.services.page_compose import image_capacity, model_from_composed
from app.services.page_model import model_to_html

pytestmark = pytest.mark.unit


# --------------------------------------------------------------------------- #
# The wireframes themselves
# --------------------------------------------------------------------------- #
class TestEveryTemplateIsSevenSections:
    def test_exactly_seven(self) -> None:
        for name, blueprint in TEMPLATES.items():
            assert len(blueprint.sections) == 7, f"{name} has {len(blueprint.sections)}"

    def test_hero_first_and_cta_last(self) -> None:
        """The two doctrine invariants. A page that opens on a price table or ends on an
        FAQ has no entry and no exit."""
        for name, blueprint in TEMPLATES.items():
            kinds = [s.kind for s in blueprint.sections]
            assert kinds[0] == "hero", name
            assert kinds[-1] == "cta", name

    def test_five_writable_slots_survive_a_client_with_no_evidence(self) -> None:
        """The reason a FIXED seven is safe. Two slots per template are gated on client
        data; the other five can always be written from the brief - so the worst case is a
        five-section page, not a seven-section page with two fabrications in it."""
        for name, blueprint in TEMPLATES.items():
            ungated = [s for s in blueprint.sections if not s.evidence]
            assert len(ungated) >= 5, f"{name} keeps only {len(ungated)} without evidence"

    def test_about_exists_and_is_not_the_service_wireframe(self) -> None:
        about, service = get_template("about"), get_template("service")
        assert about is not None and service is not None
        assert about.section_order != service.section_order


# --------------------------------------------------------------------------- #
# Evidence gating
# --------------------------------------------------------------------------- #
def _ctx(**over: Any) -> PipelineContext:
    ctx = PipelineContext(
        job_code="CJ-1",
        client_name="Acme Plumbing",
        primary_keyword="emergency plumber leeds",
        page_type="service",
    )
    for key, value in over.items():
        setattr(ctx, key, value)
    return ctx


class TestASlotWithNoEvidenceIsNeverAskedFor:
    def test_pricing_and_testimonials_drop_without_client_data(self) -> None:
        specs = TEMPLATES["service"].sections
        keep, dropped = plan_slots(specs, _ctx(brief={"source_pack": {}}))
        assert [k for k, _ in dropped] == ["testimonials", "pricing"]
        assert [s.kind for s in keep] == ["hero", "features", "process", "faq", "cta"]

    def test_supplying_the_data_brings_the_slot_back(self) -> None:
        ctx = _ctx(brief={"source_pack": {
            "testimonials": ["Great work - Sam"], "pricing": ["Basic $200"],
        }})
        keep, dropped = plan_slots(TEMPLATES["service"].sections, ctx)
        assert dropped == []
        assert len(keep) == 7

    def test_the_dropped_slot_is_absent_from_the_prompt_entirely(self) -> None:
        """Not merely unfilled: a model that is SHOWN a pricing slot and told it has no
        prices is one prompt-tuning accident away from inventing one. It is never shown."""
        ctx = _ctx(brief={"source_pack": {}})
        keep, _ = plan_slots(TEMPLATES["service"].sections, ctx)
        prompt = build_prompt(keep, ctx)
        assert "pricing" not in prompt.lower()
        assert "testimonial" not in prompt.lower()

    def test_the_fact_allow_list_is_stated_either_way(self) -> None:
        with_facts = build_prompt(
            list(TEMPLATES["service"].sections[:2]), _ctx(facts=("Gas Safe 552831",))
        )
        assert "VERIFIED FACTS" in with_facts and "552831" in with_facts
        without = build_prompt(list(TEMPLATES["service"].sections[:2]), _ctx())
        assert "NO VERIFIED FACTS" in without
        assert "no credentials" in without

    def test_proof_is_satisfied_by_answered_experience(self) -> None:
        assert evidence_available(_ctx(facts=("412 callouts in 2025",)), "proof") is True
        assert evidence_available(_ctx(), "proof") is False


# --------------------------------------------------------------------------- #
# The writer's reply -> validated slots
# --------------------------------------------------------------------------- #
_REPLY = {
    "s1_hero": {
        "heading": "Emergency plumbing in Leeds",
        "subheading": "A qualified engineer at your door within the hour, day or night.",
        "bullets": [{"text": "One hour response"}, {"text": "No call-out fee"}],
        "cta_label": "Call now",
    },
    "s2_features": {
        "heading": "What's included",
        "items": [
            {"title": "Leak detection", "text": "We find the leak without taking your wall apart."},
            {"title": "Same-day repair", "text": "Most jobs are finished on the first visit."},
            {"title": "Written guarantee", "text": "Every repair is guaranteed in writing."},
        ],
    },
    "s3_process": {
        "heading": "How it works",
        "steps": [
            {"title": "You call", "text": "Tell us what is happening and where."},
            {"title": "We arrive", "text": "An engineer reaches you within the hour."},
            {"title": "We fix it", "text": "You see the price before any work starts."},
        ],
    },
    "s4_faq": {
        "heading": "Questions",
        "items": [
            {"question": "Do you charge a call-out fee?", "answer": "No. You pay for the work."},
            {"question": "Are you available at night?", "answer": "Yes, every night of the year."},
            {"question": "Do you guarantee repairs?", "answer": "Yes, in writing, on every job."},
            {"question": "How fast can you come?", "answer": "Within the hour across Leeds."},
        ],
    },
    "s5_cta": {
        "heading": "Need a plumber now?",
        "text": "Call and speak to an engineer, not an answering service.",
        "button_label": "Call now",
    },
}


class _Writer:
    """A DoctrineWriter double that returns a scripted reply and records the prompt."""

    def __init__(self, reply: Any) -> None:
        self.reply = reply if isinstance(reply, str) else json.dumps(reply)
        self.prompt = ""

    def write(self, stage: str, prompt: str, **kw: Any) -> str:
        self.prompt = prompt
        return self.reply


class TestTheReplyBecomesSections:
    def test_a_full_reply_fills_every_writable_slot(self) -> None:
        ctx = _ctx(brief={"source_pack": {}})
        writer = _Writer(_REPLY)
        result, _cost, calls = compose_page(writer, ctx, TEMPLATES["service"].sections)
        assert calls == 1
        assert result.kinds == ["hero", "features", "process", "faq", "cta"]
        hero = result.sections[0]
        assert hero.heading == "Emergency plumbing in Leeds"
        assert len(hero.data["bullets"]) == 2

    def test_a_slot_keyed_by_kind_instead_of_id_still_counts(self) -> None:
        """A model that returns `hero` rather than `s1_hero` has done the work; refusing it
        would cost a whole repair call to fix a key name."""
        reply = {"hero": _REPLY["s1_hero"], "features": _REPLY["s2_features"],
                 "process": _REPLY["s3_process"], "faq": _REPLY["s4_faq"],
                 "cta": _REPLY["s5_cta"]}
        result, _c, _n = compose_page(
            _Writer(reply), _ctx(brief={"source_pack": {}}), TEMPLATES["service"].sections
        )
        assert len(result.sections) == 5

    def test_a_malformed_slot_is_dropped_with_its_reason_not_crashed_on(self) -> None:
        reply = dict(_REPLY)
        reply["s2_features"] = {"heading": "What's included", "items": []}
        result, _c, _n = compose_page(
            _Writer(reply), _ctx(brief={"source_pack": {}}), TEMPLATES["service"].sections
        )
        assert "features" not in result.kinds
        assert any(k == "features" and "required items" in why for k, why in result.dropped)
        # ...and the rest of the page is untouched.
        assert result.kinds == ["hero", "process", "faq", "cta"]

    def test_an_unparseable_reply_costs_the_page_not_the_worker(self) -> None:
        result, _c, _n = compose_page(
            _Writer("I'm sorry, I can't help with that."),
            _ctx(brief={"source_pack": {}}),
            TEMPLATES["service"].sections,
        )
        assert result.sections == []
        # All seven: the two evidence-gated slots were dropped before the call, and the
        # five writable ones after it, each with its own reason.
        assert len(result.dropped) == 7

    def test_a_fenced_reply_parses(self) -> None:
        raw = "Here you go:\n```json\n" + json.dumps(_REPLY) + "\n```"
        assert parse_json_object(raw)["s1_hero"]["heading"] == "Emergency plumbing in Leeds"

    def test_counts_are_bounded_not_merely_requested(self) -> None:
        """A grid that renders four cards and a writer that returns nine is a broken layout
        or six silently dropped paragraphs."""
        payload = {"heading": "x", "items": [
            {"title": f"t{i}", "text": f"body {i}"} for i in range(20)
        ]}
        out = validate_slot("features", payload)
        assert out.ok and len(out.data["items"]) == 6


# --------------------------------------------------------------------------- #
# The claims guard, on structured fields
# --------------------------------------------------------------------------- #
class TestTheClaimsGuardSurvivedTheChangeOfShape:
    def test_an_uncited_figure_is_removed_from_a_card(self) -> None:
        sections = [
            ComposedSection(
                kind="features", layout="grid", heading="What's included",
                data={"items": [
                    {"title": "Leak detection", "text": "We have completed 4,120 repairs since 2011."},
                    {"title": "Guarantee", "text": "Every repair is guaranteed in writing."},
                ]},
            )
        ]
        removed = scrub_sections(sections, facts=())
        assert removed >= 1
        kept = [i["title"] for i in sections[0].data["items"]]
        assert "Guarantee" in kept
        assert "4,120" not in json.dumps(sections[0].data)

    def test_a_supplied_figure_is_left_alone(self) -> None:
        sections = [
            ComposedSection(
                kind="intro", heading="About",
                data={"paragraphs": [{"text": "We have completed 4,120 repairs. [F1]"}]},
            )
        ]
        scrub_sections(sections, facts=("4,120 repairs completed, from our job log",))
        assert "4,120" in json.dumps(sections[0].data)


# --------------------------------------------------------------------------- #
# Rendering: components, not a prose band
# --------------------------------------------------------------------------- #
class TestTheRenderedPageIsComponents:
    def _page(self) -> str:
        ctx = _ctx(brief={"source_pack": {}})
        result, _c, _n = compose_page(_Writer(_REPLY), ctx, TEMPLATES["service"].sections)
        model = model_from_composed(
            [s.as_dict() for s in result.sections],
            design={"palette": {"accent": "#b91c4b"}}, title="Emergency plumbing",
            images=[("https://img.test/hero.png", "A plumber at work")],
        )
        return model_to_html(model, fragment=True)

    def test_every_slot_renders_as_its_own_component(self) -> None:
        html = self._page()
        for marker in ("aios-hero", "aios-features", "aios-process", "aios-faq", "aios-cta"):
            assert marker in html, marker
        # the components themselves, not just the section wrappers
        assert "<article class=\"card\">" in html
        assert "step-n" in html
        assert "<details>" in html

    def test_the_page_is_not_one_prose_band(self) -> None:
        """The published symptom of the old path: every section rendered as `prose-text`.

        Counted in the MARKUP, not the stylesheet - the CSS legitimately defines the class
        for the article templates that still use it."""
        body = self._page().split("</style>", 1)[-1]
        assert body.count("prose-text") == 0

    def test_the_hero_image_is_on_the_hero(self) -> None:
        html = self._page()
        hero = html.split("aios-features")[0]
        assert "hero.png" in hero

    def test_a_grid_never_gets_a_band_photo(self) -> None:
        """A full-width photograph above a card grid is the 'child threw it at the wall'
        symptom the operator reported. Grids are visual already."""
        ctx = _ctx(brief={"source_pack": {}})
        result, _c, _n = compose_page(_Writer(_REPLY), ctx, TEMPLATES["service"].sections)
        model = model_from_composed(
            [s.as_dict() for s in result.sections], design={}, title="t",
            images=[("https://img.test/a.png", "a"), ("https://img.test/b.png", "b")],
        )
        with_images = [s.kind for s in model.sections if s.images]
        assert with_images == ["hero"]

    def test_a_page_asks_for_only_the_images_it_can_place(self) -> None:
        assert image_capacity(["hero", "features", "process", "faq", "cta"]) == 1
        assert image_capacity(["hero", "intro", "body", "faq", "conclusion", "cta"]) == 4


# --------------------------------------------------------------------------- #
# The markdown mirror
# --------------------------------------------------------------------------- #
def test_the_markdown_mirror_describes_the_same_page() -> None:
    """The review screen, the QA scorecard and the word count all read running text. It is
    generated FROM the slots, so it cannot describe a page other than the one that ships."""
    ctx = _ctx(brief={"source_pack": {}})
    result, _c, _n = compose_page(_Writer(_REPLY), ctx, TEMPLATES["service"].sections)
    md = sections_to_markdown(result.sections)
    assert md.startswith("# Emergency plumbing in Leeds")
    assert "## What's included" in md
    assert "**Leak detection**" in md
    assert "### Do you charge a call-out fee?" in md
    assert len(md.split()) > 80
