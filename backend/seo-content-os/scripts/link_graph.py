#!/usr/bin/env python3
"""link_graph.py - persistent per-client internal-link graph and silo auditor.

Offline, stdlib-only (argparse, json, sys, os). No network calls. Maintains one
JSON file per client that records every page, its role (hub or spoke), its silo,
and its outgoing internal links. As pages are added the graph compounds, so the
Nth page can be linked into the existing N-1 without re-deriving the structure
by hand. This is doctrine Law 10 (the brain is files that compound) applied to
internal linking; the routing rules are the hub-and-spoke / silo model from
research file 06, Part 4.

Silo and equity-routing rules enforced
--------------------------------------
- spoke -> hub is mandatory : every spoke must link up to its silo's hub, so
  equity that lands on any spoke flows back to the hub and the cluster rises.
- no over-linking           : no page links out to more than --over-link-cap
  pages (default 25). John Mueller: a wall of links dilutes context.
- no cross-silo spoke links : a spoke linking to a spoke in a different silo is
  flagged (spoke -> spoke only within a silo, where context supports it).
- no orphans                : every page must have at least one inbound internal
  link, or it cannot accrue or pass equity.
- no dangling links         : every link target must be a known page.
- one hub per silo          : a silo with zero or multiple hubs is flagged.

Graph file schema
-----------------
  {"client": "acme",
   "pages": {
     "/plumbing":         {"role":"hub",   "silo":"plumbing", "title":"...",
                           "links":["/plumbing/austin"]},
     "/plumbing/austin":  {"role":"spoke", "silo":"plumbing", "title":"...",
                           "links":["/plumbing"]}
   }}

Subcommands
-----------
  add     add or update one page and its outgoing links, then save the graph
  report  audit the whole graph and print orphans / over-linked / missing
          spoke-to-hub / cross-silo / dangling / silo-hub issues
  list    print every page with role, silo, out-degree, in-degree

Exit codes
----------
  add     0 saved, 2 usage error
  report  0 graph is healthy, 1 one or more issues found, 2 usage error
  list    0

Usage
-----
  python link_graph.py add --graph acme.json --client acme --url /plumbing \\
      --role hub --silo plumbing --title "Plumbing" --links /plumbing/austin
  python link_graph.py report --graph acme.json
  python link_graph.py list --graph acme.json
  python link_graph.py --self-test
"""

import argparse
import json
import os
import sys


def new_graph(client=""):
    return {"client": client, "pages": {}}


def add_page(graph, url, role, silo, title="", links=None):
    if role not in ("hub", "spoke"):
        raise ValueError("role must be 'hub' or 'spoke', got %r" % role)
    url = url.strip()
    if not url:
        raise ValueError("url is required")
    clean_links = []
    for l in (links or []):
        l = l.strip()
        if l and l != url and l not in clean_links:
            clean_links.append(l)
    graph["pages"][url] = {
        "role": role,
        "silo": silo.strip(),
        "title": title.strip(),
        "links": clean_links,
    }
    return graph


def _inbound(graph):
    counts = {u: 0 for u in graph["pages"]}
    for src, page in graph["pages"].items():
        for tgt in page["links"]:
            if tgt in counts:
                counts[tgt] += 1
    return counts


def _hubs_by_silo(graph):
    hubs = {}
    for url, page in graph["pages"].items():
        if page["role"] == "hub":
            hubs.setdefault(page["silo"], []).append(url)
    return hubs


def analyze(graph, over_link_cap=25):
    pages = graph["pages"]
    inbound = _inbound(graph)
    hubs = _hubs_by_silo(graph)
    silos = set(p["silo"] for p in pages.values() if p["silo"])

    issues = {
        "orphans": [],
        "over_linked": [],
        "missing_spoke_to_hub": [],
        "cross_silo_spoke": [],
        "dangling": [],
        "silo_no_hub": [],
        "silo_multi_hub": [],
    }

    for silo in sorted(silos):
        h = hubs.get(silo, [])
        if len(h) == 0:
            issues["silo_no_hub"].append(silo)
        elif len(h) > 1:
            issues["silo_multi_hub"].append((silo, sorted(h)))

    for url, page in pages.items():
        # orphan (a hub is expected to be linked from the homepage/nav too)
        if inbound.get(url, 0) == 0:
            issues["orphans"].append(url)
        # over-linked
        if len(page["links"]) > over_link_cap:
            issues["over_linked"].append((url, len(page["links"])))
        # dangling targets
        for tgt in page["links"]:
            if tgt not in pages:
                issues["dangling"].append((url, tgt))
        if page["role"] == "spoke":
            silo_hubs = hubs.get(page["silo"], [])
            # missing spoke -> hub (only enforceable when the silo has a hub)
            if silo_hubs and not any(h in page["links"] for h in silo_hubs):
                issues["missing_spoke_to_hub"].append((url, page["silo"]))
            # cross-silo spoke -> spoke
            for tgt in page["links"]:
                t = pages.get(tgt)
                if t and t["role"] == "spoke" and t["silo"] != page["silo"]:
                    issues["cross_silo_spoke"].append((url, tgt))

    total = sum(len(v) for v in issues.values())
    return issues, total, inbound


def load_graph(path):
    if path and os.path.exists(path):
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    return None


def save_graph(path, graph):
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(graph, fh, indent=2, ensure_ascii=False)
        fh.write("\n")


def cmd_add(args):
    graph = load_graph(args.graph) or new_graph(args.client or "")
    if args.client:
        graph["client"] = args.client
    links = args.links or []
    try:
        add_page(graph, args.url, args.role, args.silo, args.title or "", links)
    except ValueError as e:
        sys.stderr.write("error: %s\n" % e)
        return 2
    save_graph(args.graph, graph)
    print("saved %s: %s (%s, silo=%s, %d out-link(s)) -> %s"
          % (args.graph, args.url, args.role, args.silo, len(links), args.graph))
    print("  graph now holds %d page(s)" % len(graph["pages"]))
    return 0


def _print_issues(issues, total):
    labels = [
        ("orphans", "orphan pages (no inbound internal link)"),
        ("over_linked", "over-linked pages (out-degree above cap)"),
        ("missing_spoke_to_hub", "spokes not linking up to their silo hub"),
        ("cross_silo_spoke", "cross-silo spoke-to-spoke links"),
        ("dangling", "links to unknown pages"),
        ("silo_no_hub", "silos with no hub"),
        ("silo_multi_hub", "silos with more than one hub"),
    ]
    for key, label in labels:
        items = issues[key]
        if not items:
            continue
        print("  [%d] %s:" % (len(items), label))
        for it in items:
            if isinstance(it, tuple):
                print("      %s" % " -> ".join(str(x) for x in it))
            else:
                print("      %s" % it)


def cmd_report(args):
    graph = load_graph(args.graph)
    if graph is None:
        sys.stderr.write("graph not found: %s\n" % args.graph)
        return 2
    issues, total, inbound = analyze(graph, args.over_link_cap)
    print("Link-graph audit for client '%s'" % graph.get("client", ""))
    print("  pages: %d   over-link cap: %d" % (len(graph["pages"]), args.over_link_cap))
    print("")
    if total == 0:
        print("HEALTHY  no routing issues; silo structure is clean.")
        return 0
    _print_issues(issues, total)
    print("")
    print("ISSUES  %d routing issue(s) found. Fix before adding more spokes." % total)
    return 1


def cmd_list(args):
    graph = load_graph(args.graph)
    if graph is None:
        sys.stderr.write("graph not found: %s\n" % args.graph)
        return 2
    inbound = _inbound(graph)
    print("Pages for client '%s' (%d)" % (graph.get("client", ""), len(graph["pages"])))
    print("  %-32s %-6s %-14s %4s %4s" % ("url", "role", "silo", "out", "in"))
    print("  " + "-" * 66)
    for url in sorted(graph["pages"]):
        p = graph["pages"][url]
        print("  %-32s %-6s %-14s %4d %4d"
              % (url[:32], p["role"], p["silo"][:14], len(p["links"]), inbound.get(url, 0)))
    return 0


def self_test():
    g = new_graph("acme")
    add_page(g, "/plumbing", "hub", "plumbing", "Plumbing",
             ["/plumbing/austin", "/plumbing/dallas"])
    add_page(g, "/plumbing/austin", "spoke", "plumbing", "Austin Plumber",
             ["/plumbing"])
    add_page(g, "/plumbing/dallas", "spoke", "plumbing", "Dallas Plumber",
             ["/plumbing"])
    issues, total, _ = analyze(g)
    assert total == 0, issues  # clean hub-and-spoke silo

    # now break it: a plumbing spoke that does not link up to its hub
    # (missing spoke->hub, and an orphan), plus an hvac spoke with a cross-silo
    # link, a dangling link, and no hub in its silo
    add_page(g, "/plumbing/houston", "spoke", "plumbing", "Houston Plumber",
             ["/plumbing/dallas"])
    add_page(g, "/hvac/austin", "spoke", "hvac", "Austin HVAC",
             ["/plumbing/austin", "/ghost"])
    issues, total, _ = analyze(g)
    assert "/hvac/austin" in issues["orphans"], issues["orphans"]
    assert ("/plumbing/houston", "plumbing") in issues["missing_spoke_to_hub"], \
        issues["missing_spoke_to_hub"]
    assert ("/hvac/austin", "/plumbing/austin") in issues["cross_silo_spoke"]
    assert ("/hvac/austin", "/ghost") in issues["dangling"]
    assert "hvac" in issues["silo_no_hub"], issues["silo_no_hub"]
    assert total >= 5

    # over-linking
    g2 = new_graph("big")
    targets = ["/p/%d" % i for i in range(30)]
    for t in targets:
        add_page(g2, t, "spoke", "p", "", ["/p-hub"])
    add_page(g2, "/p-hub", "hub", "p", "Hub", targets)
    issues2, _, _ = analyze(g2, over_link_cap=25)
    assert any(u == "/p-hub" for u, _ in issues2["over_linked"]), issues2["over_linked"]

    print("self-test OK")
    print("  clean silo: 0 issues; broken graph: %d issues; over-link detected" % total)
    return 0


def build_parser():
    p = argparse.ArgumentParser(
        description="Persistent per-client internal-link graph and silo auditor.")
    p.add_argument("--self-test", action="store_true",
                   help="run the built-in self-test and exit")
    sub = p.add_subparsers(dest="cmd")

    a = sub.add_parser("add", help="add or update one page and its out-links")
    a.add_argument("--graph", required=True, help="path to the client's graph JSON")
    a.add_argument("--client", default="", help="client name (set on first add)")
    a.add_argument("--url", required=True, help="page URL/path, e.g. /plumbing/austin")
    a.add_argument("--role", required=True, choices=["hub", "spoke"])
    a.add_argument("--silo", required=True, help="silo the page belongs to")
    a.add_argument("--title", default="", help="page title (optional)")
    a.add_argument("--links", nargs="*", default=[],
                   help="outgoing internal link targets (space-separated)")

    r = sub.add_parser("report", help="audit the whole graph")
    r.add_argument("--graph", required=True, help="path to the client's graph JSON")
    r.add_argument("--over-link-cap", type=int, default=25,
                   help="max out-links before over-linking is flagged (default 25)")

    l = sub.add_parser("list", help="list every page with role/silo/degree")
    l.add_argument("--graph", required=True, help="path to the client's graph JSON")

    return p


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.self_test:
        return self_test()
    if args.cmd == "add":
        return cmd_add(args)
    if args.cmd == "report":
        return cmd_report(args)
    if args.cmd == "list":
        return cmd_list(args)
    parser.error("a subcommand is required (add / report / list) or use --self-test")


if __name__ == "__main__":
    sys.exit(main())
