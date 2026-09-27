"""The page must not arrive in the client's editor pre-marked as broken.

MEASURED on two pages already on a client's site: Yoast showed RED on readability and SEO,
and the arithmetic explains it completely.

    focus keyword : 'About SPOTiNO: how we coach'   <- the job's TOPIC, not a search phrase
    kw in title   : False
    kw in meta    : False
    kw in 1st para: False
    kw in H2s     : 0/6
    kw in body    : 1 time in 819 words  (0.12%; the green band starts at 0.5%)

Every check the analyser runs failed, so every badge went red - on a page whose writing was
fine. Two causes, both ours: nothing told the writer the phrase, and the phrase itself was
a page title. The repair is both, plus the floor tested here.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.services.content_lint.compliance import META_DESC_MAX, META_DESC_MIN
from workers.tasks.content import _supportable_keyphrase

pytestmark = pytest.mark.unit


class TestAKeyphraseThePageCannotCarryIsNotDeclared:
    """Unset reads GREY in the editor - "not analysed", which is honest. Set-and-failing
    reads RED, which is a defect report the client sees before we do."""

    def test_the_measured_failure_is_withheld(self) -> None:
        draft = "# About SPOTiNO\n\n" + ("Eight players per coach. " * 80)
        assert _supportable_keyphrase(
            "About SPOTiNO: how we coach", "Eight players per coach in Lahore", draft
        ) == ""

    def test_a_phrase_the_page_uses_is_declared(self) -> None:
        """Measured on the PUBLISHED BODY, which is what the analyser reads - not on the
        markdown mirror, which repeats the hero heading and inflated every count."""
        body = (
            "<main><h1>Football coaching in Lahore</h1>"
            "<p>Football coaching in Lahore starts with the ratio.</p>"
            "<h2>What football coaching in Lahore covers</h2><p>Squads of eight.</p></main>"
        )
        assert _supportable_keyphrase(
            "football coaching in Lahore", "Small-squad coaching, Lahore", body
        ) == "football coaching in Lahore"

    def test_a_phrase_in_the_seo_title_is_enough_on_its_own(self) -> None:
        """The title is the single strongest placement, and a page whose title is built
        around the phrase is about it whatever the body's density says."""
        assert _supportable_keyphrase(
            "emergency plumber dallas", "Emergency Plumber Dallas, open now", "# Help\n\nCall us."
        ) == "emergency plumber dallas"

    def test_no_phrase_stays_no_phrase(self) -> None:
        assert _supportable_keyphrase("", "A title", "# A\n\nWords.") == ""

    def test_the_match_ignores_case(self) -> None:
        body = (
            "<main><h1>Roof Repair Leeds</h1><p>Roof Repair Leeds done properly.</p>"
            "<h2>Roof repair Leeds, step by step</h2><p>Survey first.</p></main>"
        )
        assert _supportable_keyphrase("roof repair leeds", "Roofing", body) == "roof repair leeds"


class TestTheMetaDescriptionLandsInTheGreenBand:
    """Google truncates on pixels at roughly 160 characters, which is where the old
    ceiling came from. The number an operator SEES is the plugin's, and Yoast turns the
    bar orange above 156 - so a description correct by Google's measure showed amber in
    the editor every time the client opened the page."""

    def test_the_ceiling_is_inside_yoasts_green_band(self) -> None:
        assert META_DESC_MAX <= 156

    def test_the_floor_is_yoasts_own(self) -> None:
        assert META_DESC_MIN >= 120

    def test_the_band_is_wide_enough_to_hit(self) -> None:
        """A five-character window is not a constraint, it is a retry loop."""
        assert META_DESC_MAX - META_DESC_MIN >= 25


class TestTheWriterIsToldThePhrase:
    """The floor above stops a red badge. This is what makes the page green instead:
    the analyser checks the title, the opening paragraph and the subheadings, and a
    writer that was never asked puts the phrase in none of them."""

    @staticmethod
    def _prompt(**over: Any) -> str:
        from app.services.content_pipeline.compose import build_prompt
        from app.services.content_pipeline.context import PipelineContext
        from app.services.page_blueprints import TEMPLATES

        ctx = PipelineContext(page_type="service", primary_keyword="roof repair leeds")
        for key, value in over.items():
            setattr(ctx, key, value)
        return build_prompt(list(TEMPLATES["service"].sections), ctx)

    def test_the_phrase_and_its_three_placements_are_requested(self) -> None:
        prompt = self._prompt()
        assert "roof repair leeds" in prompt
        for placement in ("hero heading", "first sentence", "section heading"):
            assert placement in prompt, f"the writer is not told to use it in the {placement}"

    def test_stuffing_is_refused_in_the_same_breath(self) -> None:
        """Over-optimisation is itself one of the things being measured, so asking for
        the phrase without bounding it trades one red badge for another."""
        prompt = self._prompt()
        assert "never stuffed" in prompt
        assert "not in every paragraph" in prompt

    def test_a_page_with_no_keyword_asks_for_nothing(self) -> None:
        assert "SEARCH PHRASE" not in self._prompt(primary_keyword="")


class TestTheDescriptionIsTrimmedIntoTheBandRatherThanOverIt:
    """`title_meta` bounds the length and re-prompts, but it is asking a model to count
    characters in its head - and two pages already on a client's site went out at 157 and
    159, amber in the editor every time it is opened. A deterministic trim cannot miss."""

    @staticmethod
    def _fit(text: str) -> str:
        from workers.tasks.content import _fit_description

        return _fit_description(text)

    def test_a_description_already_inside_the_band_is_untouched(self) -> None:
        text = "A" * 140
        assert self._fit(text) == text

    def test_an_overlong_description_is_brought_under_the_ceiling(self) -> None:
        from app.services.content_lint.compliance import META_DESC_MAX

        out = self._fit("Squads capped at eight players per coach. " * 6)
        assert len(out) <= max(META_DESC_MAX, 155)

    def test_the_trim_never_drops_below_the_floor(self) -> None:
        """CAUGHT BY THE AUDIT. Cutting at the last sentence boundary took a 157
        character description to 111 - trading an amber "too long" for an amber "too
        short", which is not a fix."""
        text = (
            "Age-group squads capped at eight players per coach, every session. A written "
            "development plan for every player, and training that runs all twelve months "
            "of the year without a break."
        )
        assert len(text) > 155, "the fixture must exceed the ceiling or it proves nothing"
        assert 120 <= len(self._fit(text)) <= 155

    def test_a_description_with_no_sentence_boundary_still_fits(self) -> None:
        out = self._fit("one very long unbroken clause that keeps going " * 5)
        assert 120 <= len(out) <= 155
        assert not out.endswith(" "), "a trim must not leave a trailing space"

    def test_whitespace_is_normalised_first(self) -> None:
        assert self._fit("  a   b\n\nc  ") == "a b c"


class TestTheKeyphraseIsJudgedOnWhatPublishes:
    """It used to be counted in `draft_md` - the markdown MIRROR of the page, which
    repeats the hero heading. A phrase appearing ONCE on the rendered page counted as
    twice there, so the guard waved through exactly the pages it existed to stop."""

    @staticmethod
    def _keep(body: str, title: str = "A title", phrase: str = "roof repair leeds") -> str:
        from workers.tasks.content import _supportable_keyphrase

        return _supportable_keyphrase(phrase, title, body)

    def test_a_phrase_placed_where_the_analyser_looks_is_kept(self) -> None:
        body = (
            "<main><h1>Roof repair Leeds</h1><p>Roof repair Leeds starts with a survey.</p>"
            "<h2>What roof repair Leeds covers</h2><p>Flat and pitched roofs.</p></main>"
        )
        assert self._keep(body) == "roof repair leeds"

    def test_a_phrase_in_the_body_but_no_heading_is_withheld(self) -> None:
        """All three placements are required rather than any of them: each one missing
        is its own red badge."""
        body = "<main><h1>Roofing</h1><p>Roof repair Leeds is what we do.</p><h2>Our work</h2></main>"
        assert self._keep(body) == ""

    def test_the_seo_title_alone_is_enough(self) -> None:
        body = "<main><h1>Roofing</h1><p>We fix roofs.</p></main>"
        assert self._keep(body, title="Roof repair Leeds, same week") == "roof repair leeds"

    def test_the_markdown_mirror_can_no_longer_fool_it(self) -> None:
        """The exact shape that slipped through: the phrase twice, but only because the
        heading is repeated - and in no subheading, in no opening paragraph."""
        mirror_like = "<main><h1>Roof repair leeds</h1><p>Something else entirely.</p></main>"
        assert self._keep(mirror_like) == ""


class TestTheWriterIsToldToKeepItReadable:
    """The plugin turns the readability light red above a quarter of sentences running
    over twenty words. Measured on two shipped pages: 30% and 43%."""

    @staticmethod
    def _prompt() -> str:
        from app.services.content_pipeline.compose import build_prompt
        from app.services.content_pipeline.context import PipelineContext
        from app.services.page_blueprints import TEMPLATES

        return build_prompt(
            list(TEMPLATES["service"].sections),
            PipelineContext(page_type="service", primary_keyword="roof repair leeds"),
        )

    def test_the_threshold_is_stated(self) -> None:
        prompt = self._prompt()
        assert "under twenty words" in prompt
        assert "one in four" in prompt

    def test_uniform_shortness_is_refused_in_the_same_breath(self) -> None:
        """A page of uniformly short sentences reads like a manual and is its own
        defect, so the bound is on the SHARE that run long - which is what is measured."""
        assert "Vary the length" in self._prompt()
