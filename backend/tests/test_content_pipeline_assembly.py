"""The assembly: binding the staged pipeline to real dependencies.

The package was complete and unreachable - every stage injectable, `run_page`
written to consume a dict of bound callables, and no code anywhere that built
that dict. These tests hold the binding to its contract, because the failure mode
it must never have is the quiet one: a stage silently absent, or a stage bound to
something that reports success without doing the work.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from app.services.content_pipeline.assembly import build_page_stages
from app.services.content_pipeline.context import PipelineContext
from app.services.content_pipeline.runner import PAGE_STAGES, run_page

pytestmark = pytest.mark.unit


# --- doubles ----------------------------------------------------------------- #

@dataclass
class _Slot:
    slot_key: str
    question: str = ""
    answer: str = ""

    @property
    def answered(self) -> bool:
        return bool(self.answer.strip())


@dataclass
class _Dossier:
    id: str = "dos-1"
    slots: list[_Slot] = field(default_factory=list)

    @property
    def unanswered(self) -> list[_Slot]:
        return [s for s in self.slots if not s.answered]

    @property
    def answered(self) -> list[_Slot]:
        return [s for s in self.slots if s.answered]

    @property
    def complete(self) -> bool:
        return bool(self.slots) and not self.unanswered

    def proof_signals(self) -> frozenset[str]:
        return frozenset(s.slot_key for s in self.slots if s.answered)


class _Store:
    """Stands in for ContentPlanningStore across all six methods the stages use."""

    def __init__(self, *, answered: bool = False) -> None:
        self.dossier = _Dossier()
        self._answered = answered
        self.shingles_recorded = 0

    def get_or_create_dossier(self, *, engagement_id: str, cluster_key: str = "") -> _Dossier:
        return self.dossier

    def upsert_slot(self, **kwargs: Any) -> None:
        key = str(kwargs["slot_key"])
        if key not in {s.slot_key for s in self.dossier.slots}:
            self.dossier.slots.append(
                _Slot(key, question=str(kwargs.get("question", "")),
                      answer="a measured, checkable fact" if self._answered else "")
            )

    def refresh_dossier_status(self, dossier_id: str) -> str:
        return "complete" if self.dossier.complete else "incomplete"

    def record_shingles(self, **kwargs: Any) -> int:
        self.shingles_recorded += 1
        return 1

    def find_overlaps(self, **kwargs: Any) -> list[Any]:
        return []

    def metrics_for(self, engagement_id: str | None, keyword: str) -> dict[str, Any] | None:
        return None


class _Writer:
    """A DoctrineWriter-shaped double that records which stages actually called it."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def write(self, stage: str, prompt: str, **kwargs: Any) -> str:
        self.calls.append(stage)
        return "{}"


def _ctx(**kw: Any) -> PipelineContext:
    base: dict[str, Any] = {
        "job_code": "CJ-4200", "engagement_id": "eng-1",
        "client_name": "Dallas Plumbing",
        "primary_keyword": "emergency plumber dallas",
        "page_type": "service", "geo": "Dallas",
    }
    base.update(kw)
    return PipelineContext(**base)


# --- what gets bound --------------------------------------------------------- #

class TestAMissingDependencyOmitsItsStageRatherThanFakingIt:
    """`run_page` skips an absent stage. That is the honest degrade: a pipeline with
    no writer produces no prose, instead of a stub that returns success."""

    def test_with_nothing_bound_only_the_free_stages_exist(self) -> None:
        stages = build_page_stages()
        # schema_links is deterministic and free; gate scores without a judge.
        assert set(stages) == {"schema_links", "gate"}

    def test_the_experience_gate_needs_the_dossier_store(self) -> None:
        assert "sme" not in build_page_stages(writer=_Writer())  # type: ignore[arg-type]
        assert "sme" in build_page_stages(store=_Store())

    def test_the_writing_stages_need_a_writer(self) -> None:
        writing = {"outline", "draft", "convert", "voice", "title_meta"}
        assert writing & set(build_page_stages(store=_Store())) == set()
        assert writing <= set(build_page_stages(writer=_Writer(), store=_Store()))  # type: ignore[arg-type]

    def test_fully_bound_covers_every_declared_stage(self) -> None:
        """Both sequences: a full page, and a reviewer's edit. A declared stage
        that cannot be bound is a step `run_page` silently skips."""
        from app.services.content_pipeline.runner import EDIT_STAGES

        stages = build_page_stages(
            writer=_Writer(), researcher=object(), store=_Store(),  # type: ignore[arg-type]
        )
        assert set(stages) == set(PAGE_STAGES) | set(EDIT_STAGES)


# --- what the sequence then does --------------------------------------------- #

class TestTheAssembledPipelineEnforcesTheExperienceGate:
    """Law 16, through the real binding rather than a hand-written stage map."""

    def test_an_unanswered_dossier_halts_the_page_before_any_writing(self) -> None:
        writer = _Writer()
        store = _Store(answered=False)
        run = run_page(_ctx(), build_page_stages(writer=writer, store=store))  # type: ignore[arg-type]
        assert run.outcome == "halted"
        assert run.stopped_at == "sme"
        assert "draft" not in writer.calls, "a halted page must not be drafted"
        assert run.cost == 0.0

    def test_the_halt_names_the_slots_the_operator_must_answer(self) -> None:
        store = _Store(answered=False)
        run = run_page(_ctx(), build_page_stages(writer=_Writer(), store=store))  # type: ignore[arg-type]
        sme = run.results[0]
        assert sme.data["missing"], "the halt must say WHAT is missing, or nobody can clear it"
        assert set(sme.data["questions"]) == set(sme.data["missing"])

    def test_without_an_engagement_the_gate_halts_rather_than_skipping(self) -> None:
        run = run_page(
            _ctx(engagement_id=None),
            build_page_stages(writer=_Writer(), store=_Store(answered=True)),  # type: ignore[arg-type]
        )
        assert run.outcome == "halted"

    def test_an_answered_dossier_lets_the_page_proceed_past_the_gate(self) -> None:
        run = run_page(
            _ctx(), build_page_stages(writer=_Writer(), store=_Store(answered=True)),  # type: ignore[arg-type]
        )
        assert run.stopped_at != "sme", "answered Experience must not halt"
