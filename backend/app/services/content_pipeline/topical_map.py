"""Topical map - which pages exist, how they link, and which have earned a page.

THE STAGE THE PLATFORM HAS NEVER HAD. Today every page is planned alone, so
`content_generator` invents internal-link slugs like `/{slug(spoke)}` that may point
at nothing, cannibalisation is undetectable, and no page knows its siblings. All three
are consequences of having no record of the other pages.

TWO GATES RUN HERE, and they catch different things.

  1. CANNIBALISATION is a UNIQUE CONSTRAINT, not a report. Two nodes targeting one
     primary keyword is refused by the database (case-insensitively), so the model
     cannot plan two pages that compete with each other.

  2. THE EVIDENCE GATE (`content_lint.topical_map`) decides which nodes become PAGES.
     The doctrine's rule is that a node is promoted only when it carries a real
     first-party specific that makes the page un-copyable. A node without one is
     `index_only` - legitimate coverage the site has deliberately not spent a page on,
     not a backlog item. That distinction is what stops a map being padded to look
     complete.

WHY THE MODEL RUNS ON THE HEAVY TIER. This is the highest-leverage judgement in the
whole pipeline: it decides what gets written at all. A cheap model here produces a
plausible-looking map that quietly targets the wrong queries, and every downstream
stage then executes it faithfully.

WHAT IS DETERMINISTIC. Clustering, cannibalisation and the evidence gate are all
free, offline checks. The model proposes; the rules dispose - and a rejected map is
re-requested with the collisions NAMED, so the retry is informed rather than a
re-roll.
"""

from __future__ import annotations

import json
import re
from typing import Any, Protocol

from app.modules.content_planning.schemas import KeywordTerm
from app.services.content_lint import MapNode as LintNode
from app.services.content_lint import lint_topical_map
from app.services.content_pipeline.context import PipelineContext, StageResult
from app.services.content_pipeline.writer import DoctrineWriter, WriteAccounting

STAGE = "topical_map"

# Retries after a lint or cannibalisation failure. Two, then stop: a third attempt on
# the same evidence has nothing new to work with, and the honest outcome is a map an
# operator reviews rather than one the system keeps re-rolling at cost.
MAX_REPAIRS = 2

# How many candidate terms reach the model. Not all of them: a 700-term plan would
# both blow the prompt and bury the real opportunities under long-tail noise.
MAX_CANDIDATES = 60

# Token budget for a REASONING stage.
#
# MEASURED live 2026-08-25, not guessed. This model emits extended-THINKING blocks. On
# the outline prompt it spent 4,000 tokens reasoning and produced ZERO text - the call
# returned an empty string that looked like "the model had nothing to say", and the
# stage degraded for a reason nobody could see. At 12,000 it finished thinking in
# ~9,965 tokens and wrote a full answer.
#
# So the budget has to cover THINKING PLUS THE ANSWER, not just the answer. That is
# also why `integrations.llm.EmptyCompletionError` exists: if this is ever set too low
# again, the failure is loud instead of a blank page.
# The map's ANSWER is larger than the outline's - a whole site's nodes rather than
# one page's sections - so it gets more room on top of the same thinking budget.
REASONING_MAX_TOKENS = 16_000


class MapStore(Protocol):
    def create_map(self, *, engagement_id: str, plan_id: str | None = ...) -> str: ...
    def add_node(self, **kwargs: Any) -> Any: ...
    def map_nodes(self, map_id: str) -> list[Any]: ...
    def add_link_edge(self, **kwargs: Any) -> None: ...


def _candidates(terms: list[KeywordTerm], limit: int = MAX_CANDIDATES) -> list[KeywordTerm]:
    """Best opportunities first, measured terms preferred.

    A measured term outranks an estimated one at equal opportunity, because planning a
    page around a number nobody supplied is how a map acquires confident-looking
    fiction.
    """
    return sorted(
        terms,
        key=lambda t: (t.is_measured, t.opportunity or 0.0, t.volume or 0),
        reverse=True,
    )[:limit]


def _prompt(ctx: PipelineContext, candidates: list[KeywordTerm], collisions: list[str]) -> str:
    lines = [
        f"Plan the topical map for {ctx.client_name or 'this client'}"
        + (f" in {ctx.geo}" if ctx.geo else "") + ".",
        "",
        "Candidate keywords (keyword | volume | difficulty | opportunity | measured):",
    ]
    lines += [
        f"  {t.keyword} | {t.volume or '-'} | {t.difficulty or '-'} | "
        f"{t.opportunity or '-'} | {'yes' if t.is_measured else 'NO (estimated)'}"
        for t in candidates
    ]
    lines += [
        "",
        "Group these into silos with ONE hub each and its spokes. For every node give:",
        "  primary_keyword  - the single query the page targets (never repeat one)",
        "  role             - hub or spoke",
        "  silo             - the cluster it belongs to",
        "  page_type        - service | local | blog",
        "  status           - page  (only if you can name a real first-party specific)",
        "                     index_only  (coverage the site should NOT spend a page on)",
        "  evidence         - the first-party specific that makes a PAGE un-copyable,"
        "                     or empty for index_only",
        "  info_gain_thesis - what net-new fact this page adds, or empty",
        "",
        "Promote a node to status:page ONLY when you can name a concrete, checkable "
        "first-party specific. If you cannot, mark it index_only. Do NOT invent an "
        "evidence line to justify a promotion - an honest index_only is correct and "
        "an invented specific is a fabrication that will be published.",
    ]
    if collisions:
        lines += [
            "",
            "The previous attempt was REJECTED. Fix exactly these and change nothing else:",
            *(f"  - {c}" for c in collisions),
        ]
    lines += ["", 'Reply with ONLY a JSON array of node objects.']
    return "\n".join(lines)


def _parse(raw: str) -> list[dict[str, Any]]:
    match = re.search(r"\[.*\]", raw, re.DOTALL)
    if not match:
        return []
    try:
        parsed = json.loads(match.group(0))
    except (ValueError, TypeError):
        return []
    return [n for n in parsed if isinstance(n, dict) and n.get("primary_keyword")]


def _dedupe(nodes: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[str]]:
    """Drop nodes that would collide on primary keyword, and say which.

    Caught here as well as in the database because the collision message must reach
    the RETRY prompt. A unique-violation exception names a constraint, not the two
    queries that competed.
    """
    seen: dict[str, str] = {}
    kept: list[dict[str, Any]] = []
    collisions: list[str] = []
    for node in nodes:
        key = str(node["primary_keyword"]).strip().lower()
        if key in seen:
            collisions.append(
                f"two nodes target {node['primary_keyword']!r}; they would cannibalise "
                "each other - merge them or retarget one"
            )
            continue
        seen[key] = key
        kept.append(node)
    return kept, collisions


def run_topical_map(
    ctx: PipelineContext,
    *,
    store: MapStore,
    writer: DoctrineWriter,
    terms: list[KeywordTerm],
    plan_id: str | None = None,
    client_facts: list[str] | None = None,
    model: str | None = None,
) -> StageResult:
    """Design the map, then let the deterministic gates accept or reject it."""
    if not ctx.engagement_id:
        return ctx.record(StageResult(STAGE, outcome="skipped", notes=("no engagement",)))
    if not terms:
        return ctx.record(StageResult(STAGE, outcome="skipped", notes=("no keyword terms",)))

    accounting = WriteAccounting()
    notes: list[str] = []
    candidates = _candidates(terms)
    collisions: list[str] = []
    nodes: list[dict[str, Any]] = []

    for attempt in range(MAX_REPAIRS + 1):
        try:
            raw = writer.write(
                STAGE, _prompt(ctx, candidates, collisions),
                page_type=ctx.page_type, vertical=ctx.vertical or None,
                max_tokens=REASONING_MAX_TOKENS, expected_calls=MAX_REPAIRS + 1,
                model=model, accounting=accounting,
            )
        except Exception as exc:
            return ctx.record(StageResult(
                STAGE, outcome="degraded",
                notes=(f"map generation unavailable ({type(exc).__name__})",),
                cost=accounting.cost, llm_calls=accounting.calls,
            ))

        parsed = _parse(raw)
        if not parsed:
            collisions = ["the reply was not a JSON array of node objects"]
            continue

        nodes, collisions = _dedupe(parsed)

        lint = lint_topical_map(
            [
                LintNode(
                    node_id=str(n.get("primary_keyword", "")),
                    status="page" if str(n.get("status", "")).startswith("page") else "index-only",
                    evidence=str(n.get("evidence", "")),
                    info_gain_thesis=str(n.get("info_gain_thesis", "")),
                )
                for n in nodes
            ],
            client_facts=client_facts or list(ctx.facts),
        )
        collisions += [i.message for i in lint.errors]
        if not collisions:
            break
        notes.append(f"attempt {attempt + 1} rejected: {len(collisions)} issue(s)")

    if not nodes:
        return ctx.record(StageResult(
            STAGE, outcome="degraded", notes=(*notes, "no usable map after retries"),
            cost=accounting.cost, llm_calls=accounting.calls,
        ))

    map_id = store.create_map(engagement_id=ctx.engagement_id, plan_id=plan_id)
    hubs: dict[str, str] = {}
    created: list[Any] = []
    # Hubs first: a spoke's parent must exist before the spoke references it.
    for node in sorted(nodes, key=lambda n: 0 if n.get("role") == "hub" else 1):
        role = "hub" if node.get("role") == "hub" else "spoke"
        silo = str(node.get("silo", "")).strip()
        promoted = str(node.get("status", "")).startswith("page")
        record = store.add_node(
            map_id=map_id,
            primary_keyword=str(node["primary_keyword"]).strip(),
            page_type=str(node.get("page_type", ctx.page_type)),
            role=role, silo=silo,
            parent_id=hubs.get(silo) if role == "spoke" else None,
            intent=str(node.get("intent", "")),
            cluster_key=silo,
            evidence=str(node.get("evidence", "")),
            info_gain_thesis=str(node.get("info_gain_thesis", "")),
            status="planned" if promoted else "index_only",
        )
        created.append(record)
        if role == "hub" and silo:
            hubs[silo] = record.id

    # Every spoke links UP to its silo hub: equity landing on a spoke has to flow back
    # or the cluster never lifts.
    for record in created:
        if record.role == "spoke" and record.silo in hubs:
            store.add_link_edge(
                map_id=map_id, from_node_id=record.id, to_node_id=hubs[record.silo],
                anchor_text=record.primary_keyword,
                rationale="spoke -> hub (mandatory equity routing)",
            )

    pages = sum(1 for r in created if r.status == "planned")
    if collisions:
        notes.append(
            f"stored with {len(collisions)} unresolved issue(s) after {MAX_REPAIRS} "
            "repairs; an operator should review the map before production"
        )
    return ctx.record(StageResult(
        STAGE, outcome="degraded" if collisions else "ok", notes=tuple(notes),
        data={"map_id": map_id, "nodes": len(created), "pages": pages,
              "index_only": len(created) - pages, "unresolved": collisions},
        cost=accounting.cost, llm_calls=accounting.calls,
        input_tokens=accounting.input_tokens, output_tokens=accounting.output_tokens,
        cache_write_tokens=accounting.cache_write_tokens,
        cache_read_tokens=accounting.cache_read_tokens,
        chunk_ids=tuple(accounting.chunk_ids),
    ))
