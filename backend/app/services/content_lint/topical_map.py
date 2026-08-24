"""The topical map's evidence gate - a node becomes a PAGE only when it earns it.

Ported from ``seo-content-os/scripts/topical_map_lint.py`` (P1B).

The map's whole discipline is one rule: a node is promoted from coverage to a full
PAGE only when it carries a real first-party specific that makes that page
un-copyable. In the corpus that rule was prose the map-building agent was trusted to
obey, with nothing checking it. This is the check.

WHAT THIS IS NOT, and the protocol is explicit about it (trap #2): not a "topical
authority score", not a coverage percentage, not a completeness rating. It scores
NOTHING. It checks PRESENCE - every node marked ``page`` must carry non-placeholder
evidence and a non-placeholder info-gain thesis. An `index-only` node is exempt by
definition: it is coverage the site has deliberately not spent a page on.

That distinction matters because a score invites optimisation toward the score, which
is how a map ends up with 200 thin pages and a healthy-looking number.

WHAT WAS PORTED, AND WHAT WAS DELIBERATELY NOT. The original parses the corpus's
markdown map format - a node table plus per-node detail blocks. P3 builds the map as
STRUCTURED ROWS (``topical_map_nodes``), so porting that markdown parser would carry a
format this platform never produces. The RULE is what transfers, so this takes typed
nodes and applies the same gate. ``is_placeholder`` is carried over verbatim, because
its exact behaviour is the difference between catching an unbacked promotion and
waving through "TBD".

The GROUNDING check is retained and is the subtle one: evidence must share a
meaningful token with the client's known facts. Evidence that overlaps nothing the
client actually has is how invented specifics enter a map and look rigorous.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

PLACEHOLDER_TOKENS: frozenset[str] = frozenset({
    "", "-", "--", "tbd", "n/a", "na", "none", "todo", "...", "xxx", "?",
    "index-only | page", "core | outer", "planned | briefed | drafted | published",
})

_ANGLE_PLACEHOLDER_RE = re.compile(r"^<[^>]*>$")
_ONLY_ANGLES_RE = re.compile(r"(<[^>]*>[\s,;/]*)+")
_TRAILING_PAREN_RE = re.compile(r"\s*\(.*\)\s*$")
_MEANINGFUL_TOKEN_RE = re.compile(r"[a-z0-9]{4,}")

STATUS_PAGE = "page"
STATUS_INDEX_ONLY = "index-only"
STATUS_UNKNOWN = "unknown"


@dataclass(frozen=True)
class MapNode:
    """One planned node. ``status`` is ``page`` | ``index-only``."""

    node_id: str
    status: str
    evidence: str = ""
    info_gain_thesis: str = ""


@dataclass(frozen=True)
class MapIssue:
    severity: str  # "ERROR" | "WARN"
    code: str
    node_id: str
    message: str


@dataclass(frozen=True)
class TopicalMapReport:
    issues: tuple[MapIssue, ...] = ()
    page_nodes: int = 0
    index_nodes: int = 0

    @property
    def errors(self) -> tuple[MapIssue, ...]:
        return tuple(i for i in self.issues if i.severity == "ERROR")

    @property
    def warnings(self) -> tuple[MapIssue, ...]:
        return tuple(i for i in self.issues if i.severity == "WARN")

    @property
    def passed(self) -> bool:
        return not self.errors


def is_placeholder(value: str | None) -> bool:
    """True when a field is blank, a stop-word placeholder, or template angle text.

    Carried over verbatim: its exact behaviour is the difference between catching an
    unbacked promotion and waving through "TBD".
    """
    if value is None:
        return True
    cleaned = value.strip().strip("`").strip()
    core = _TRAILING_PAREN_RE.sub("", cleaned).strip()
    if core == "" or core.lower() in PLACEHOLDER_TOKENS:
        return True
    if _ANGLE_PLACEHOLDER_RE.match(core):
        return True
    return bool(_ONLY_ANGLES_RE.fullmatch(core))


def normalize_status(raw: str | None) -> str:
    """Map a free-text status to ``page`` | ``index-only`` | ``unknown``."""
    if raw is None or is_placeholder(raw):
        return STATUS_UNKNOWN
    lowered = raw.lower()
    if "index-only" in lowered or "index only" in lowered:
        return STATUS_INDEX_ONLY
    if "page" in lowered:
        return STATUS_PAGE
    return STATUS_UNKNOWN


def meaningful_tokens(text: str | None) -> set[str]:
    """Tokens of 4+ characters - short words carry no grounding signal."""
    return set(_MEANINGFUL_TOKEN_RE.findall((text or "").lower()))


def lint_topical_map(
    nodes: Sequence[MapNode], *, client_facts: Iterable[str] = ()
) -> TopicalMapReport:
    """Apply the evidence gate. Total: never raises, never does I/O.

    ``client_facts`` are the strings the client can actually back (from ``sme_slots``
    in P2). When supplied, evidence sharing no meaningful token with them is WARNed as
    possibly invented - a soft signal, because a real fact can legitimately be phrased
    in words the fact list does not contain.
    """
    fact_tokens: set[str] | None = None
    facts = list(client_facts)
    if facts:
        fact_tokens = meaningful_tokens(" ".join(facts))

    issues: list[MapIssue] = []
    page_nodes = index_nodes = 0
    seen: set[str] = set()

    for node in nodes:
        if node.node_id in seen:
            issues.append(MapIssue("ERROR", "DUPLICATE_NODE", node.node_id,
                                   f"duplicate node id: {node.node_id!r}"))
            continue
        seen.add(node.node_id)

        status = normalize_status(node.status)
        if status == STATUS_PAGE:
            page_nodes += 1
        elif status == STATUS_INDEX_ONLY:
            index_nodes += 1
        else:
            issues.append(MapIssue("ERROR", "STATUS_UNKNOWN", node.node_id,
                                   f"node {node.node_id!r} has no resolvable status "
                                   f"({node.status!r}); expected page or index-only"))
            continue

        # Only page nodes are gated. An index-only node is coverage by design.
        if status != STATUS_PAGE:
            continue

        if is_placeholder(node.evidence):
            issues.append(MapIssue(
                "ERROR", "UNBACKED_PROMOTION", node.node_id,
                f"node {node.node_id!r} is status:page with no real evidence "
                "(empty/placeholder): demote to index-only or supply a first-party specific",
            ))
        elif fact_tokens is not None:
            evidence_tokens = meaningful_tokens(node.evidence)
            if evidence_tokens and not (evidence_tokens & fact_tokens):
                issues.append(MapIssue(
                    "WARN", "EVIDENCE_UNGROUNDED", node.node_id,
                    f"node {node.node_id!r} evidence shares no token with the client's "
                    "known facts; verify it is real rather than invented",
                ))

        if is_placeholder(node.info_gain_thesis):
            issues.append(MapIssue(
                "ERROR", "MISSING_THESIS", node.node_id,
                f"node {node.node_id!r} is status:page with no real info-gain thesis "
                "(empty/placeholder): name the net-new fact this page adds, or demote "
                "to index-only",
            ))

    return TopicalMapReport(issues=tuple(issues), page_nodes=page_nodes, index_nodes=index_nodes)
