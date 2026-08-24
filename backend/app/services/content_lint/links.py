"""Internal-link graph and silo auditor - hub-and-spoke equity routing.

Ported from ``seo-content-os/scripts/link_graph.py`` (P1B).

Internal linking is the one ranking factor entirely within our control, and it is
structural rather than per-page: the Nth page has to be wired into the existing N-1,
which no single-page check can see. This audits the whole client graph at once.

The rules, and why each exists:

  * ``missing_spoke_to_hub`` - every spoke must link UP to its silo hub, so equity
    landing on any spoke flows back to the hub and lifts the whole cluster. A spoke
    that does not is a dead end for authority.
  * ``orphans`` - a page with zero inbound internal links cannot accrue or pass
    equity. It may be indexed and still be invisible.
  * ``dangling`` - a link to a page that does not exist.
  * ``cross_silo_spoke`` - spoke-to-spoke across silos blurs the topical boundary the
    silo exists to draw.
  * ``over_linked`` - more than 25 outbound links dilutes the context each one
    carries.
  * ``silo_no_hub`` / ``silo_multi_hub`` - a cluster with no hub has nothing to lift;
    a cluster with two has split authority and the two will compete.

This replaces ``content_qa._score_internal_linking``, which is a stub: it can only
count links on the page in front of it, and every rule above is about the RELATIONSHIP
between pages. A per-page check is structurally incapable of catching an orphan.

PORT CHANGES. The original persists one JSON file per client and mutates it in place.
This takes an immutable graph built from data, because the ports must be pure and
because P2 keeps this in Postgres (``topical_map_nodes`` + ``internal_link_edges``),
where "the graph compounds as pages are added" is a row insert rather than a file
rewrite. The analysis arithmetic is carried over verbatim.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field

# John Mueller's guidance, and the corpus default: a wall of links dilutes context.
OVER_LINK_CAP = 25

Role = str  # "hub" | "spoke"
VALID_ROLES: frozenset[str] = frozenset({"hub", "spoke"})


@dataclass(frozen=True)
class LinkPage:
    url: str
    role: Role
    silo: str
    title: str = ""
    links: tuple[str, ...] = ()


@dataclass(frozen=True)
class LinkGraph:
    client: str = ""
    pages: Mapping[str, LinkPage] = field(default_factory=dict)


@dataclass(frozen=True)
class LinkGraphReport:
    orphans: tuple[str, ...] = ()
    over_linked: tuple[tuple[str, int], ...] = ()
    missing_spoke_to_hub: tuple[tuple[str, str], ...] = ()
    cross_silo_spoke: tuple[tuple[str, str], ...] = ()
    dangling: tuple[tuple[str, str], ...] = ()
    silo_no_hub: tuple[str, ...] = ()
    silo_multi_hub: tuple[tuple[str, tuple[str, ...]], ...] = ()
    inbound: Mapping[str, int] = field(default_factory=dict)

    @property
    def total_issues(self) -> int:
        return (
            len(self.orphans) + len(self.over_linked) + len(self.missing_spoke_to_hub)
            + len(self.cross_silo_spoke) + len(self.dangling)
            + len(self.silo_no_hub) + len(self.silo_multi_hub)
        )

    @property
    def passed(self) -> bool:
        return self.total_issues == 0

    def issues(self) -> list[str]:
        out: list[str] = []
        out += [f"{u} has no inbound internal link and cannot accrue equity" for u in self.orphans]
        out += [f"{u} links out to {n} pages, over the {OVER_LINK_CAP} cap" for u, n in self.over_linked]
        out += [f"{u} is a spoke in {silo!r} that never links up to its hub"
                for u, silo in self.missing_spoke_to_hub]
        out += [f"{a} links across silos to the spoke {b}" for a, b in self.cross_silo_spoke]
        out += [f"{a} links to {b}, which is not a known page" for a, b in self.dangling]
        out += [f"silo {s!r} has no hub, so nothing collects its equity" for s in self.silo_no_hub]
        out += [f"silo {s!r} has {len(h)} hubs ({', '.join(h)}); they will compete"
                for s, h in self.silo_multi_hub]
        return out


def build_page(
    url: str, role: Role, silo: str, *, title: str = "", links: Sequence[str] = ()
) -> LinkPage:
    """One page node. Self-links and duplicates are dropped, order preserved."""
    if role not in VALID_ROLES:
        raise ValueError(f"role must be one of {sorted(VALID_ROLES)}, got {role!r}")
    clean_url = url.strip()
    if not clean_url:
        raise ValueError("url is required")

    seen: list[str] = []
    for link in links:
        target = link.strip()
        if target and target != clean_url and target not in seen:
            seen.append(target)
    return LinkPage(url=clean_url, role=role, silo=silo.strip(), title=title.strip(),
                    links=tuple(seen))


def build_graph(pages: Iterable[LinkPage], *, client: str = "") -> LinkGraph:
    return LinkGraph(client=client, pages={p.url: p for p in pages})


def _inbound_counts(graph: LinkGraph) -> dict[str, int]:
    counts = dict.fromkeys(graph.pages, 0)
    for page in graph.pages.values():
        for target in page.links:
            if target in counts:
                counts[target] += 1
    return counts


def _hubs_by_silo(graph: LinkGraph) -> dict[str, list[str]]:
    hubs: dict[str, list[str]] = {}
    for url, page in graph.pages.items():
        if page.role == "hub":
            hubs.setdefault(page.silo, []).append(url)
    return hubs


def analyze_links(graph: LinkGraph, *, over_link_cap: int = OVER_LINK_CAP) -> LinkGraphReport:
    """Audit the whole graph. Total: never raises, never does I/O."""
    pages = graph.pages
    inbound = _inbound_counts(graph)
    hubs = _hubs_by_silo(graph)
    silos = {p.silo for p in pages.values() if p.silo}

    silo_no_hub: list[str] = []
    silo_multi_hub: list[tuple[str, tuple[str, ...]]] = []
    for silo in sorted(silos):
        found = hubs.get(silo, [])
        if not found:
            silo_no_hub.append(silo)
        elif len(found) > 1:
            silo_multi_hub.append((silo, tuple(sorted(found))))

    orphans: list[str] = []
    over_linked: list[tuple[str, int]] = []
    dangling: list[tuple[str, str]] = []
    missing_up: list[tuple[str, str]] = []
    cross_silo: list[tuple[str, str]] = []

    for url, page in pages.items():
        if inbound.get(url, 0) == 0:
            orphans.append(url)
        if len(page.links) > over_link_cap:
            over_linked.append((url, len(page.links)))
        for target in page.links:
            if target not in pages:
                dangling.append((url, target))
        if page.role == "spoke":
            silo_hubs = hubs.get(page.silo, [])
            # Only enforceable when the silo actually has a hub to point at.
            if silo_hubs and not any(h in page.links for h in silo_hubs):
                missing_up.append((url, page.silo))
            for target in page.links:
                other = pages.get(target)
                if other and other.role == "spoke" and other.silo != page.silo:
                    cross_silo.append((url, target))

    return LinkGraphReport(
        orphans=tuple(orphans), over_linked=tuple(over_linked),
        missing_spoke_to_hub=tuple(missing_up), cross_silo_spoke=tuple(cross_silo),
        dangling=tuple(dangling), silo_no_hub=tuple(silo_no_hub),
        silo_multi_hub=tuple(silo_multi_hub), inbound=inbound,
    )
