"""P3: the outline stage and its cross-page uniqueness gate."""

from __future__ import annotations

import json
from typing import Any

from app.services.content_lint import shingle_hashes
from app.services.content_pipeline.context import PipelineContext
from app.services.content_pipeline.outline import (
    HEADING_SHINGLE_SIZE,
    MAX_REPAIRS,
    heading_text,
    mask_entity,
    run_outline,
)


class _Overlap:
    def __init__(self, jaccard: float) -> None:
        self._j = jaccard

    @property
    def jaccard(self) -> float:
        return self._j


class _Store:
    def __init__(self, overlap: float = 0.0) -> None:
        self.overlap, self.recorded = overlap, 0

    def find_overlaps(self, **kw: Any) -> list[_Overlap]:
        return [_Overlap(self.overlap)] if self.overlap else []

    def record_shingles(self, **kw: Any) -> int:
        self.recorded += len(kw["hashes"])
        return self.recorded


class _Writer:
    def __init__(self, replies: list[str]) -> None:
        self.replies, self.prompts = replies, []

    def write(self, stage: str, prompt: str, **kw: Any) -> str:
        self.prompts.append(prompt)
        return self.replies[min(len(self.prompts) - 1, len(self.replies) - 1)]


def _outline(*headings: str) -> str:
    return json.dumps({"sections": [{"h2": h, "h3s": []} for h in headings]})


_A = _outline("Why roof repair austin matters", "How roof repair austin works",
              "Get started with roof repair austin")


def _ctx(**kw: Any) -> PipelineContext:
    base = {"primary_keyword": "roof repair austin", "geo": "Austin",
            "vertical": "home-services", "client_name": "Acme"}
    return PipelineContext(**{**base, **kw})


# --------------------------------------------------------------------------- #
# The measurement that shapes the gate
# --------------------------------------------------------------------------- #
def test_entity_masking_exposes_a_template_that_raw_shingling_misses() -> None:
    """The finding this whole stage is built around, reproduced as a test.

    Two pages from one template differ ONLY in the city token. Raw, that difference
    hides inside most shingles and the overlap reads as "distinct enough"; masked, the
    template is exposed completely.
    """
    austin = "Why roof repair austin matters\nHow roof repair austin works\nGet started with roof repair austin"
    dallas = austin.replace("austin", "dallas")

    def jac(a: str, b: str) -> float:
        ha, hb = (shingle_hashes(x, size=HEADING_SHINGLE_SIZE) for x in (a, b))
        return len(ha & hb) / len(ha | hb) if (ha | hb) else 0.0

    raw = jac(austin, dallas)
    masked = jac(
        mask_entity(austin, "roof repair austin", "Austin"),
        mask_entity(dallas, "roof repair dallas", "Dallas"),
    )
    assert raw < 0.70, "if raw already caught it, the masking rationale is obsolete"
    assert masked == 1.0, "masked skeletons from one template must be identical"


def test_masking_removes_both_the_query_and_a_bare_city_mention() -> None:
    """The place name appears alone in headings even when the full query does not
    ("Serving Austin since 2011"), so masking only the query would leave it."""
    masked = mask_entity("Serving Austin since 2011", "roof repair austin", "Austin")
    assert "Austin" not in masked and "austin" not in masked


def test_masking_handles_a_city_contained_in_the_query() -> None:
    """Longest-first, so masking the query does not leave an orphaned city fragment."""
    assert "austin" not in mask_entity(
        "roof repair austin guide", "roof repair austin", "austin"
    ).lower()


def test_only_headings_are_compared_not_body_prose() -> None:
    """Body prose differs between two templated pages because the facts differ. The
    HEADINGS are what a template fixes, so they are what the gate compares."""
    text = heading_text({"sections": [{"h2": "A", "h3s": ["A1"]}, {"h2": "B", "h3s": []}]})
    assert text.splitlines() == ["A", "A1", "B"]


# --------------------------------------------------------------------------- #
# The gate's behaviour
# --------------------------------------------------------------------------- #
def test_a_distinct_outline_is_accepted_and_its_shingles_recorded() -> None:
    store = _Store(overlap=0.0)
    result = run_outline(_ctx(), writer=_Writer([_A]), store=store)
    assert result.outcome == "ok"
    assert store.recorded > 0, "an accepted outline must join the index it is compared against"


def test_a_duplicate_outline_is_rejected_and_the_retry_names_the_headings() -> None:
    """A rejection saying only "too similar" is a re-roll. Naming the headings makes
    the retry informed."""
    writer = _Writer([_A, _outline("What a 1970s Austin bungalow roof costs to patch")])
    store = _Store(overlap=0.95)
    run_outline(_ctx(), writer=writer, store=store)
    assert len(writer.prompts) >= 2
    assert "REJECTED" in writer.prompts[1]
    assert "Why roof repair austin matters" in writer.prompts[1]


def test_a_rejected_outlines_shingles_are_never_recorded() -> None:
    """Otherwise the next page collides with a page that was never published."""
    store = _Store(overlap=0.95)
    run_outline(_ctx(), writer=_Writer([_A]), store=store)
    assert store.recorded == 0


def test_repairs_are_bounded_and_the_page_is_flagged_rather_than_lost() -> None:
    """A third attempt yields contortions rather than a genuinely new structure. An
    operator reviewing a flagged page beats an unbounded re-roll at cost."""
    writer = _Writer([_A])
    result = run_outline(_ctx(), writer=writer, store=_Store(overlap=0.95))
    assert len(writer.prompts) == MAX_REPAIRS + 1
    assert result.outcome == "degraded"
    assert any("operator should confirm" in n for n in result.notes)


def test_the_gate_is_skipped_cleanly_when_there_is_no_index() -> None:
    """A first page has no siblings. That is not a failure."""
    result = run_outline(_ctx(), writer=_Writer([_A]), store=None)
    assert result.outcome == "ok"


def test_junk_output_is_retried() -> None:
    writer = _Writer(["not json", _A])
    assert run_outline(_ctx(), writer=writer, store=_Store()).outcome == "ok"
    assert len(writer.prompts) == 2


def test_a_spend_block_degrades_without_an_outline() -> None:
    class _Blocked:
        def write(self, *a: Any, **k: Any) -> str:
            raise RuntimeError("ContentSpendBlocked")

    result = run_outline(_ctx(), writer=_Blocked(), store=_Store())
    assert result.outcome == "degraded" and not result.data


def test_first_party_facts_reach_the_prompt_as_the_only_allowed_facts() -> None:
    writer = _Writer([_A])
    run_outline(_ctx(facts=("1,284 emergency calls in 2025",)), writer=writer, store=_Store())
    assert "1,284 emergency calls in 2025" in writer.prompts[0]
    assert "NOTHING else as fact" in writer.prompts[0]
