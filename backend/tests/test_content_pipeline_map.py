"""P3: the topical map - cannibalisation and the evidence gate."""

from __future__ import annotations

import json
from typing import Any

from app.modules.content_planning.schemas import KeywordTerm
from app.services.content_pipeline.context import PipelineContext
from app.services.content_pipeline.topical_map import (
    MAX_REPAIRS,
    _candidates,
    run_topical_map,
)


class _Node:
    def __init__(self, **kw: Any) -> None:
        self.__dict__.update(kw)
        self.id = f"node-{kw['primary_keyword']}"


class _Store:
    def __init__(self) -> None:
        self.nodes: list[_Node] = []
        self.edges: list[tuple[str, str]] = []

    def create_map(self, *, engagement_id: str, plan_id: str | None = None) -> str:
        return "map-1"

    def add_node(self, **kw: Any) -> _Node:
        node = _Node(**kw)
        self.nodes.append(node)
        return node

    def map_nodes(self, map_id: str) -> list[_Node]:
        return self.nodes

    def add_link_edge(self, **kw: Any) -> None:
        self.edges.append((kw["from_node_id"], kw["to_node_id"]))


class _Writer:
    def __init__(self, replies: list[str]) -> None:
        self.replies, self.prompts = replies, []

    def write(self, stage: str, prompt: str, **kw: Any) -> str:
        self.prompts.append(prompt)
        return self.replies[min(len(self.prompts) - 1, len(self.replies) - 1)]


_TERMS = [
    KeywordTerm(keyword="ac repair san jose", source="dataforseo", estimated=False,
                volume=8100, opportunity=62.7),
    KeywordTerm(keyword="cheap ac", source="serp_derived", estimated=True,
                volume=99000, opportunity=62.7),
]


def _ctx(**kw: Any) -> PipelineContext:
    base = {"engagement_id": "eng-1", "client_name": "Valley Air",
            "facts": ("1,284 emergency calls in 2025",)}
    return PipelineContext(**{**base, **kw})


_GOOD = json.dumps([
    {"primary_keyword": "ac repair san jose", "role": "hub", "silo": "hvac",
     "status": "page", "evidence": "1,284 emergency calls logged in 2025",
     "info_gain_thesis": "per-call arrival breakdown"},
    {"primary_keyword": "ac maintenance tips", "role": "spoke", "silo": "hvac",
     "status": "index_only", "evidence": "", "info_gain_thesis": ""},
])


def test_a_clean_map_is_stored_with_hubs_before_spokes() -> None:
    store = _Store()
    result = run_topical_map(_ctx(), store=store, writer=_Writer([_GOOD]), terms=_TERMS)
    assert result.outcome == "ok"
    assert result.data["pages"] == 1 and result.data["index_only"] == 1
    assert store.nodes[0].role == "hub", "a spoke's parent must exist before the spoke"


def test_every_spoke_links_up_to_its_hub() -> None:
    """Equity landing on a spoke must flow back to the hub or the cluster never lifts."""
    store = _Store()
    run_topical_map(_ctx(), store=store, writer=_Writer([_GOOD]), terms=_TERMS)
    assert store.edges == [("node-ac maintenance tips", "node-ac repair san jose")]


def test_cannibalisation_is_rejected_and_the_retry_names_the_collision() -> None:
    """A unique-violation names a constraint, not the two queries that competed. The
    retry has to be informed or it is just a re-roll at cost."""
    colliding = json.dumps([
        {"primary_keyword": "ac repair san jose", "role": "hub", "silo": "h",
         "status": "page", "evidence": "1,284 emergency calls", "info_gain_thesis": "x"},
        {"primary_keyword": "AC Repair San Jose", "role": "spoke", "silo": "h",
         "status": "page", "evidence": "1,284 emergency calls", "info_gain_thesis": "y"},
    ])
    writer = _Writer([colliding, _GOOD])
    result = run_topical_map(_ctx(), store=_Store(), writer=writer, terms=_TERMS)
    assert len(writer.prompts) == 2
    assert "cannibalise" in writer.prompts[1]
    assert result.outcome == "ok"


def test_an_unbacked_promotion_is_rejected() -> None:
    """The doctrine's rule: a node becomes a PAGE only with a real first-party
    specific. A placeholder is not one."""
    unbacked = json.dumps([
        {"primary_keyword": "ac repair san jose", "role": "hub", "silo": "h",
         "status": "page", "evidence": "TBD", "info_gain_thesis": "<the angle>"},
    ])
    writer = _Writer([unbacked, _GOOD])
    run_topical_map(_ctx(), store=_Store(), writer=writer, terms=_TERMS)
    assert len(writer.prompts) == 2, "an unbacked promotion must trigger a repair"


def test_an_index_only_node_is_a_legitimate_outcome_not_a_failure() -> None:
    """Coverage the site deliberately does not spend a page on. Treating it as a gap
    is what pads a map with thin pages to look complete."""
    store = _Store()
    result = run_topical_map(_ctx(), store=store, writer=_Writer([_GOOD]), terms=_TERMS)
    assert result.outcome == "ok"
    assert any(n.status == "index_only" for n in store.nodes)


def test_repairs_are_bounded_and_the_map_is_kept_for_review() -> None:
    """A third attempt on the same evidence has nothing new to work with. Storing the
    imperfect map with the issues attached beats re-rolling at cost or losing it."""
    bad = json.dumps([
        {"primary_keyword": "x", "role": "hub", "silo": "h", "status": "page",
         "evidence": "TBD", "info_gain_thesis": "TBD"},
    ])
    writer = _Writer([bad])
    result = run_topical_map(_ctx(), store=_Store(), writer=writer, terms=_TERMS)
    assert len(writer.prompts) == MAX_REPAIRS + 1
    assert result.outcome == "degraded"
    assert result.data["unresolved"]
    assert any("operator should review" in n for n in result.notes)


def test_junk_output_is_retried_rather_than_stored() -> None:
    writer = _Writer(["not json at all", _GOOD])
    assert run_topical_map(_ctx(), store=_Store(), writer=writer, terms=_TERMS).outcome == "ok"
    assert len(writer.prompts) == 2


def test_measured_terms_outrank_estimated_ones_at_equal_opportunity() -> None:
    """Planning a page around a number nobody supplied is how a map acquires
    confident-looking fiction. "cheap ac" has 12x the volume and is estimated."""
    ranked = _candidates(_TERMS)
    assert ranked[0].keyword == "ac repair san jose"
    assert ranked[0].is_measured and not ranked[1].is_measured


def test_a_spend_block_degrades_without_a_partial_map() -> None:
    class _Blocked:
        def write(self, *a: Any, **k: Any) -> str:
            raise RuntimeError("ContentSpendBlocked")

    result = run_topical_map(_ctx(), store=_Store(), writer=_Blocked(), terms=_TERMS)
    assert result.outcome == "degraded" and not result.data
