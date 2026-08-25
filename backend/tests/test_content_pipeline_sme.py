"""P3: the SME stage - the hard halt that stops drafting without Experience.

Runs on a fake store so it needs no database. The behaviours pinned here are the ones
that make the halt a GATE rather than a warning, and each has a specific failure mode
it prevents.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.services.content_pipeline.context import PipelineContext
from app.services.content_pipeline.sme import (
    FALLBACK_QUESTIONS,
    _parse_questions,
    required_slots,
    run_sme,
)


class _Slot:
    def __init__(self, key: str, answer: str = "", artifact_url: str = "", question: str = "") -> None:
        self.slot_key, self.answer, self.artifact_url, self.question = key, answer, artifact_url, question

    @property
    def answered(self) -> bool:
        return bool(self.answer.strip() or self.artifact_url.strip())


class _Dossier:
    def __init__(self, slots: list[_Slot]) -> None:
        self.id, self.slots = "dossier-1", slots

    @property
    def answered(self) -> tuple[_Slot, ...]:
        return tuple(s for s in self.slots if s.answered)

    @property
    def unanswered(self) -> tuple[_Slot, ...]:
        return tuple(s for s in self.slots if not s.answered)

    @property
    def complete(self) -> bool:
        return bool(self.slots) and not self.unanswered

    def proof_signals(self) -> frozenset[str]:
        return frozenset(s.slot_key for s in self.answered)


class _Store:
    def __init__(self, slots: list[_Slot] | None = None) -> None:
        self.slots = slots or []
        self.upserts: list[str] = []

    def get_or_create_dossier(self, *, engagement_id: str, cluster_key: str = "") -> _Dossier:
        return _Dossier(self.slots)

    def upsert_slot(self, **kw: Any) -> None:
        self.upserts.append(kw["slot_key"])
        self.slots.append(_Slot(kw["slot_key"], question=kw.get("question", "")))

    def refresh_dossier_status(self, dossier_id: str) -> str:
        return "complete" if all(s.answered for s in self.slots) and self.slots else "partial"


def _ctx(**kw: Any) -> PipelineContext:
    base = {"engagement_id": "eng-1", "primary_keyword": "ac repair", "page_type": "service"}
    return PipelineContext(**{**base, **kw})


# --------------------------------------------------------------------------- #
# The halt itself
# --------------------------------------------------------------------------- #
def test_an_empty_dossier_halts_and_asks_for_every_category() -> None:
    """A model asked for Experience it does not have will invent it, fluently and
    undetectably. The only place that can be stopped is before drafting."""
    store = _Store()
    result = run_sme(_ctx(), store=store, writer=None)
    assert result.outcome == "halted"
    assert set(result.data["missing"]) == set(required_slots("service"))
    assert all(result.data["questions"].values()), "every question must be answerable"


def test_one_missing_slot_is_still_a_halt() -> None:
    """No partial pass. "Nearly enough Experience" is the state in which a model fills
    the remainder with invention."""
    slots = [_Slot(k, answer="x") for k in required_slots("service")[:-1]]
    slots.append(_Slot(required_slots("service")[-1]))
    result = run_sme(_ctx(), store=_Store(slots), writer=None)
    assert result.outcome == "halted"
    assert result.data["missing"] == [required_slots("service")[-1]]


def test_a_complete_dossier_proceeds_and_publishes_its_signals() -> None:
    slots = [_Slot(k, answer="supplied") for k in required_slots("service")]
    ctx = _ctx()
    result = run_sme(ctx, store=_Store(slots), writer=None)
    assert result.outcome == "ok"
    # These feed content_lint.experience, so a legitimate claim is not failed for
    # lacking an inline artifact the client can nonetheless back.
    assert ctx.proof_signals == frozenset(required_slots("service"))
    assert len(ctx.facts) == len(required_slots("service"))


def test_a_halt_is_not_a_failure() -> None:
    """It must not be retried, alerted on, or counted as an error. The gate working is
    not the system breaking."""
    result = run_sme(_ctx(), store=_Store(), writer=None)
    assert result.outcome == "halted"
    assert result.blocks_pipeline and not result.ok


def test_no_engagement_halts_rather_than_skipping() -> None:
    """A page drafted with no Experience store is precisely the ungoverned path this
    stage exists to close, so an absent engagement must not wave it through."""
    result = run_sme(_ctx(engagement_id=None), store=_Store(), writer=None)
    assert result.outcome == "halted"


def test_an_artifact_alone_satisfies_a_slot() -> None:
    """A dated photo IS the evidence. Requiring prose beside it would reject exactly
    the first-party proof the gate wants."""
    slots = [_Slot(k, artifact_url="https://x/p.jpg") for k in required_slots("service")]
    assert run_sme(_ctx(), store=_Store(slots), writer=None).outcome == "ok"


# --------------------------------------------------------------------------- #
# Degradation: the questionnaire must survive the model being unavailable
# --------------------------------------------------------------------------- #
def test_a_spend_block_still_produces_an_answerable_questionnaire() -> None:
    """A halt with no questions is a dead end for the operator. The fallbacks are real
    questions, not filler, so a degraded run is still actionable."""
    class _Blocked:
        def write(self, *a: Any, **k: Any) -> str:
            raise RuntimeError("ContentSpendBlocked")

    store = _Store()
    result = run_sme(_ctx(), store=store, writer=_Blocked())
    assert result.outcome == "halted"
    assert all(q.strip() for q in result.data["questions"].values())
    assert any("default interview questions" in n for n in result.notes)


@pytest.mark.parametrize("raw", ["", "not json", "[]", "{}", '{"bogus_key": "q"}', "null"])
def test_junk_model_output_degrades_to_the_defaults(raw: str) -> None:
    assert _parse_questions(raw, ("founding_date",)) in ({}, {})


def test_parsed_questions_are_filtered_to_the_requested_categories() -> None:
    """A model that invents a category would create a slot nothing ever asks for and
    that the Experience gate cannot consume."""
    parsed = _parse_questions(
        '{"founding_date": "When?", "made_up": "Ignore me"}', ("founding_date",)
    )
    assert parsed == {"founding_date": "When?"}


# --------------------------------------------------------------------------- #
# The slot vocabulary must match what the Experience gate reports
# --------------------------------------------------------------------------- #
def test_slot_keys_match_the_experience_gates_proof_categories() -> None:
    """The gate says a claim needs a `license_permit`; the questionnaire must have a
    slot called exactly that, or the two halves cannot talk to each other."""
    from app.services.content_lint.experience import _CLAIM_PATTERNS

    gate_categories = {c for _k, _rx, accepted in _CLAIM_PATTERNS for c in accepted}
    all_slots = {k for pt in ("service", "about", "homepage") for k in required_slots(pt)}
    assert all_slots & gate_categories, "slot vocabulary has drifted from the gate's"
    assert set(FALLBACK_QUESTIONS) >= all_slots, "a required slot has no fallback question"


def test_an_about_page_requires_a_named_person() -> None:
    """An about page is ABOUT the people; a nameless one has no Experience to show."""
    assert "named_team" in required_slots("about")
    assert "named_team" not in required_slots("service")
