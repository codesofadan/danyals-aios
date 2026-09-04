"""Shared context and result types for the staged pipeline (P3).

The v1 generator is a single pure function that takes a brief and returns a page. That
shape is why it could not carry doctrine, could not gate on Experience, and could not
compare a page against its siblings: everything it knew had to fit in one call's
arguments.

The staged pipeline is a sequence of steps over a shared context instead. Each stage
reads what earlier stages produced, may spend, and returns a typed result carrying its
own cost and provenance - so "what did this page cost, and what governed it" is
answerable per stage rather than as one number at the end.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

StageOutcome = Literal["ok", "halted", "degraded", "skipped", "failed"]


@dataclass(frozen=True)
class StageResult:
    """One stage's outcome. Carries cost and provenance, never just data.

    ``halted`` is distinct from ``failed`` on purpose. A halt is the system working -
    the SME gate refusing to draft without first-party facts - and must not be
    retried, alerted on, or counted as an error. A failure is something broken.
    """

    stage: str
    outcome: StageOutcome = "ok"
    data: dict[str, Any] = field(default_factory=dict)
    notes: tuple[str, ...] = ()
    cost: float = 0.0
    llm_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cache_write_tokens: int = 0
    cache_read_tokens: int = 0
    chunk_ids: tuple[str, ...] = ()
    dropped_chunk_ids: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        return self.outcome in ("ok", "degraded", "skipped")

    @property
    def blocks_pipeline(self) -> bool:
        return self.outcome in ("halted", "failed")


@dataclass
class PipelineContext:
    """Everything the stages share. Mutable by design - stages accumulate into it.

    Deliberately NOT frozen, unlike almost everything else in this package: the whole
    point is that OUTLINE reads what RESEARCH produced. Making it immutable would mean
    threading a growing tuple of results through every signature, which is the same
    coupling with more ceremony.
    """

    # --- identity ---------------------------------------------------------- #
    job_code: str = ""
    job_id: str | None = None
    engagement_id: str | None = None
    client_id: str | None = None
    client_name: str = ""
    node_id: str | None = None

    # --- what to write ------------------------------------------------------ #
    primary_keyword: str = ""
    page_type: str = "service"
    vertical: str = ""
    framework: str = "PAS"
    geo: str = ""
    target_words: int = 1200

    # --- accumulated by stages ---------------------------------------------- #
    # Experience answers the OPERATOR supplied up front, keyed by sme slot_key.
    # The SME stage seeds the dossier from these, which is what lets a job that was
    # answered in the wizard run straight through instead of halting after submit.
    experience: dict[str, str] = field(default_factory=dict)
    proof_signals: frozenset[str] = field(default_factory=frozenset)
    facts: tuple[str, ...] = ()
    brief: dict[str, Any] = field(default_factory=dict)
    outline: dict[str, Any] = field(default_factory=dict)
    draft_md: str = ""
    title: str = ""
    meta_description: str = ""

    results: list[StageResult] = field(default_factory=list)

    def record(self, result: StageResult) -> StageResult:
        self.results.append(result)
        return result

    @property
    def total_cost(self) -> float:
        return sum(r.cost for r in self.results)

    @property
    def total_llm_calls(self) -> int:
        return sum(r.llm_calls for r in self.results)

    def result_for(self, stage: str) -> StageResult | None:
        return next((r for r in reversed(self.results) if r.stage == stage), None)
