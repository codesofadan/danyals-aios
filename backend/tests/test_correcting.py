"""P6.3: the correcting loop - the piece that edits a client's LIVE site.

Every round here re-publishes. A mapping that is confident where it should not be does
not fail safely: it edits a live page, measures it, edits it again, and oscillates until
the cap, having made the page worse in public each time. These tests are mostly about
the refusals.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.services.correcting import (
    MAX_ROUNDS,
    MIN_MAGNITUDE,
    CorrectionHistory,
    apply_overrides,
    plan_corrections,
)
from app.services.visual_diff import Diagnostic, DiffResult

pytestmark = pytest.mark.unit


def _diff(*diagnostics: Diagnostic, status: str = "fail") -> DiffResult:
    return DiffResult(status=status, diagnostics=list(diagnostics))  # type: ignore[arg-type]


def _typography(px: float = 24.0, magnitude: float = 0.4) -> Diagnostic:
    return Diagnostic(
        "typography", "body",
        f"body font-size drifted: expected ~17px, rendered {px:g}px", magnitude=magnitude,
    )


def _spacing(magnitude: float = 0.3) -> Diagnostic:
    return Diagnostic(
        "spacing", "page",
        "container width drifted: expected ~1180px, rendered 1440px", magnitude=magnitude,
    )


def _colour() -> Diagnostic:
    return Diagnostic(
        "color", "hero",
        "background colour drifted: expected #f5f7fa, rendered #ffffff", magnitude=0.5,
    )


def _layout() -> Diagnostic:
    return Diagnostic(
        "layout", "page",
        "expected 5 content section(s), rendered page has 3", magnitude=0.4,
    )


class TestWhatItWillCorrect:
    def test_a_font_size_drift_becomes_a_token_override(self) -> None:
        plan = plan_corrections(_diff(_typography()))
        assert len(plan.overrides) == 1
        assert plan.overrides[0].path == "typography.base_size"
        assert plan.overrides[0].value == "17px", "the DESIGN's value, not the rendered one"

    def test_a_container_width_drift_becomes_a_token_override(self) -> None:
        plan = plan_corrections(_diff(_spacing()))
        assert plan.overrides[0].path == "layout.container_width"
        assert plan.overrides[0].value == "1180px"

    def test_a_background_colour_drift_becomes_a_token_override(self) -> None:
        plan = plan_corrections(_diff(_colour()))
        assert plan.overrides[0].path == "sections.hero.bg_color"
        assert plan.overrides[0].value == "#f5f7fa"

    def test_the_override_carries_the_measurement_that_caused_it(self) -> None:
        """So a republish can be explained without re-deriving why it happened."""
        plan = plan_corrections(_diff(_typography()))
        assert "font-size drifted" in plan.overrides[0].because


class TestWhatItRefusesToCorrect:
    def test_a_section_count_mismatch_is_left_for_a_human(self) -> None:
        """"expected 5 sections, rendered 3" is a rendering or template problem.
        Inventing a token for it is how a loop starts thrashing against a live site."""
        plan = plan_corrections(_diff(_layout()))
        assert plan.overrides == ()
        assert plan.unfixable and plan.unfixable[0].kind == "layout"
        assert plan.stop is True

    @pytest.mark.parametrize("kind", ["size", "image", "alignment", "responsive"])
    def test_kinds_with_no_defensible_token_are_not_guessed_at(self, kind: str) -> None:
        d = Diagnostic(kind, "hero", "something drifted", magnitude=0.9)  # type: ignore[arg-type]
        plan = plan_corrections(_diff(d))
        assert plan.overrides == () and plan.unfixable

    def test_a_diagnostic_whose_expected_value_is_unreadable_is_not_guessed(self) -> None:
        """Better to hand a human a diff than to correct toward a number we invented."""
        d = Diagnostic("typography", "body", "the heading looks wrong", magnitude=0.9)
        plan = plan_corrections(_diff(d))
        assert plan.overrides == () and plan.unfixable


class TestTrivialDriftIsNotWorthAPublish:
    def test_drift_just_past_the_detection_threshold_is_ignored(self) -> None:
        """`visual_diff` flags anything past 12%. Correcting at 13% means editing a
        live page over a difference nobody would notice."""
        plan = plan_corrections(_diff(_typography(magnitude=0.13)))
        assert plan.overrides == ()
        assert any("under the" in n for n in plan.notes)

    def test_drift_above_the_floor_is_corrected(self) -> None:
        assert plan_corrections(_diff(_typography(magnitude=MIN_MAGNITUDE))).overrides

    def test_a_colour_is_judged_by_match_not_magnitude(self) -> None:
        """A background colour either matches or it does not; visual_diff reports a
        flat 0.5. Judging it by the size floor would silently drop every colour fix."""
        assert plan_corrections(_diff(_colour())).overrides


class TestOscillation:
    """The cap alone only bounds how LONG the loop runs. This is what stops it."""

    def test_a_recurring_diagnostic_is_not_retried(self) -> None:
        history = CorrectionHistory()
        first = plan_corrections(_diff(_typography()), history)
        assert first.overrides
        history.record(first.overrides, [_typography()])

        second = plan_corrections(_diff(_typography()), history)
        assert second.overrides == (), "the override did not take; resending cannot help"
        assert second.unfixable
        assert any("not retrying" in n for n in second.notes)

    def test_a_new_diagnostic_in_round_two_is_still_corrected(self) -> None:
        """Recurrence is per-diagnostic, not a blanket stop - a fix that exposed a
        different drift should still be corrected once."""
        history = CorrectionHistory()
        first = plan_corrections(_diff(_typography()), history)
        history.record(first.overrides, [_typography()])
        second = plan_corrections(_diff(_spacing()), history)
        assert len(second.overrides) == 1

    def test_the_round_cap_ends_it_with_the_diff_attached(self) -> None:
        history = CorrectionHistory(rounds=MAX_ROUNDS)
        plan = plan_corrections(_diff(_typography(), _layout()), history)
        assert plan.stop is True and plan.overrides == ()
        assert len(plan.unfixable) == 2, "the human gets every outstanding diagnostic"
        assert "a human should look" in plan.reason

    def test_it_terminates_on_a_diagnostic_that_never_resolves(self) -> None:
        """The property that matters: a page that cannot be fixed must stop being
        published to, not be republished until the cap."""
        history = CorrectionHistory()
        publishes = 0
        for _ in range(10):
            plan = plan_corrections(_diff(_typography()), history)
            if not plan.should_republish:
                break
            publishes += 1
            history.record(plan.overrides, [_typography()])
        assert publishes == 1, f"expected to stop after one failed correction, got {publishes}"


class TestWhenNotToPublishAtAll:
    def test_a_passing_diff_stops_immediately(self) -> None:
        plan = plan_corrections(_diff(status="pass"))
        assert plan.stop and not plan.overrides

    def test_an_empty_diagnostic_list_stops(self) -> None:
        assert plan_corrections(_diff(status="fail")).stop

    def test_an_empty_override_set_never_republishes(self) -> None:
        """Re-publishing with nothing to change edits a client's live page to produce
        byte-identical output - a publish spent on nothing."""
        assert plan_corrections(_diff(_layout())).should_republish is False


class TestApplyingOverrides:
    def _design(self) -> dict[str, Any]:
        return {"typography": {"base_size": "24px"}, "layout": {"container_width": "1440px"}}

    def test_the_dotted_path_is_set(self) -> None:
        plan = plan_corrections(_diff(_typography(), _spacing()))
        out = apply_overrides(self._design(), plan.overrides)
        assert out["typography"]["base_size"] == "17px"
        assert out["layout"]["container_width"] == "1180px"

    def test_the_original_design_is_not_mutated(self) -> None:
        """The next round diffs against the DESIGN. Mutating it would make each round
        compare against the previous round's corrections instead."""
        design = self._design()
        plan = plan_corrections(_diff(_typography()))
        apply_overrides(design, plan.overrides)
        assert design["typography"]["base_size"] == "24px"

    def test_a_missing_intermediate_path_is_created(self) -> None:
        plan = plan_corrections(_diff(_colour()))
        out = apply_overrides({}, plan.overrides)
        assert out["sections"]["hero"]["bg_color"] == "#f5f7fa"

    def test_a_non_dict_on_the_path_is_replaced_rather_than_crashing(self) -> None:
        plan = plan_corrections(_diff(_colour()))
        out = apply_overrides({"sections": "not-a-dict"}, plan.overrides)
        assert out["sections"]["hero"]["bg_color"] == "#f5f7fa"


# --------------------------------------------------------------------------- #
# Termination, exhaustively
# --------------------------------------------------------------------------- #
_ALL_KINDS = ("typography", "layout", "spacing", "image", "color", "alignment",
              "size", "responsive")


def _diagnostic(kind: str, section: str = "page") -> Diagnostic:
    """One of each kind, each with a readable expected value where its mapping needs
    one - so the mapped kinds genuinely produce an override rather than bailing early
    and making termination look better than it is."""
    detail = {
        "typography": "body font-size drifted: expected ~17px, rendered 24px",
        "spacing": "container width drifted: expected ~1180px, rendered 1440px",
        "color": "background colour drifted: expected #f5f7fa, rendered #ffffff",
    }.get(kind, f"{kind} drifted on {section}")
    section = {"typography": "body", "color": "hero"}.get(kind, section)
    return Diagnostic(kind, section, detail, magnitude=0.9)  # type: ignore[arg-type]


def _run_to_completion(diagnostics: list[Diagnostic], *, limit: int = 25) -> int:
    """Drive the loop against a page that NEVER improves, and count publishes.

    The worst realistic case: every override is applied and the page still measures
    exactly the same. If the loop can run away, it runs away here.
    """
    history = CorrectionHistory()
    for publishes in range(limit):
        plan = plan_corrections(_diff(*diagnostics), history)
        if not plan.should_republish:
            return publishes
        history.record(plan.overrides, diagnostics)
    raise AssertionError(f"the loop did not terminate within {limit} rounds")


@pytest.mark.parametrize("kind", _ALL_KINDS)
def test_every_diagnostic_kind_terminates(kind: str) -> None:
    assert _run_to_completion([_diagnostic(kind)]) <= MAX_ROUNDS


def test_every_pair_of_kinds_terminates() -> None:
    """Combinations matter: a mix of fixable and unfixable must not let the fixable
    one keep the loop alive while the unfixable one keeps it failing."""
    import itertools

    for a, b in itertools.combinations(_ALL_KINDS, 2):
        publishes = _run_to_completion([_diagnostic(a), _diagnostic(b, "hero")])
        assert publishes <= MAX_ROUNDS, f"{a}+{b} published {publishes} times"


def test_all_kinds_at_once_terminates() -> None:
    assert _run_to_completion([_diagnostic(k) for k in _ALL_KINDS]) <= MAX_ROUNDS


def test_a_page_that_never_improves_is_published_at_most_once() -> None:
    """Stronger than the cap. If an override does not take, the recurrence check
    should stop the loop on the SECOND assessment - well before MAX_ROUNDS."""
    for kind in ("typography", "spacing", "color"):
        assert _run_to_completion([_diagnostic(kind)]) == 1, kind
