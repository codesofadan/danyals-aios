#!/usr/bin/env python3
"""storage_cluster_seed.py - Expand a self-storage client's real axes into the
candidate node CEILING for the topical-map architect.

Offline, stdlib-only (argparse, os, re; optional yaml). No network calls.

WHAT THIS IS AND IS NOT
-----------------------
This is a CANDIDATE generator, NOT a map. It crosses the client's real storage
axes (unit sizes x storage types x audiences x served cities) into the full grid
of pages that COULD exist. The topical-map architect then demand-filters every
candidate (a real autocomplete/PAA/ranking-competitor signal), merges behavioral
duplicates, and evidence-gates each survivor (real inventory / a real first-party
specific) before any candidate becomes a `status: page` node. Emitting the whole
grid as pages would be a doorway farm (knowledge/foundations/topical-map-protocol.md
trap #4, and SS-DOORWAY). Every candidate below is born `index-only`.

It also enforces the single-facility collapse rule
(knowledge/foundations/storage-topical-map.md 6a): if operator_type is
single_facility, the whole grid collapses to ONE homepage-as-facility page plus
About/FAQ/asset - it emits no axis pages, because they would be thin.

Inputs (either the axis flags, or --brand to read them from brand.yaml.storage):
  --operator-type {single_facility,multi_facility}
  --sizes 5x5,5x10,10x10,10x15,10x20,10x30
  --types climate-controlled,drive-up,vehicle,business
  --audiences student,military,business
  --cities Austin,"Round Rock",Pflugerville         (from brand.yaml.service_areas)

Usage
-----
  python storage_cluster_seed.py --operator-type multi_facility \
      --sizes 5x10,10x10,10x20 --types climate-controlled,drive-up \
      --audiences student --cities Austin,"Round Rock"
  python storage_cluster_seed.py --brand clients/acme-storage/brand.yaml
  python storage_cluster_seed.py --self-test

Exit code is always 0 on a successful run (this is a planning aid, not a gate).
"""

import argparse
import os
import re
import sys

# Physical-world equivalents for the target-query context (industry-standard
# pattern; the writer replaces with the facility's real what-fits at build time).
SIZE_EQUIV = {
    "5x5": "a small closet",
    "5x10": "a studio apartment",
    "10x10": "a one-bedroom apartment",
    "10x15": "a two-bedroom apartment",
    "10x20": "a one-car garage / a 3-bedroom home",
    "10x30": "a large home or a vehicle",
}


def _slug(s):
    return re.sub(r"[^a-z0-9]+", "-", s.strip().lower()).strip("-")


def _clean_list(items):
    out = []
    for it in items or []:
        it = str(it).strip().strip('"').strip("'")
        if it:
            out.append(it)
    return out


def generate(operator_type, sizes, types, audiences, cities):
    """Return a list of candidate node dicts. Each is born index-only."""
    sizes = _clean_list(sizes)
    types = _clean_list(types)
    audiences = _clean_list(audiences)
    cities = _clean_list(cities)
    nodes = []

    def add(node_id, cluster, page_type, target_query, command, section, note=""):
        nodes.append({
            "node_id": node_id, "cluster": cluster, "page_type": page_type,
            "target_query": target_query, "command": command, "section": section,
            "status": "index-only", "note": note,
        })

    # Always: the entity anchor + trust/utility.
    add("homepage", "J/A", "homepage", "[brand] / [brand] [primary city]",
        "/write-homepage", "core", "the entity anchor")
    add("about", "J", "about-team", "[brand] about / owner / manager",
        "/write-about-page", "outer", "E-E-A-T surface")
    add("faq", "I", "faq-page", "storage FAQ / [common renter questions]",
        "/write-faq-page", "outer")

    if operator_type == "single_facility":
        add("size-guide-asset", "B2", "local-asset",
            "storage unit sizes / what fits in a 10x10", "/write-local-asset", "outer",
            "the ONE informational size guide a single-facility op may own")
        # Collapse rule: sizes and types are SECTIONS on the homepage, not pages.
        return nodes, {
            "collapsed": True,
            "reason": "single_facility: unit sizes and storage types are sections "
                      "on the homepage-as-facility page, never separate pages "
                      "(they would be thin). No axis pages emitted.",
        }

    # Multi-facility: emit the grid ceiling (all index-only).
    for city in cities:
        cs = _slug(city)
        add("facility-%s" % cs, "A", "location", "storage units %s" % city,
            "/write-location-page", "core", "one per real staffed building in the city")
        for size in sizes:
            add("size-%s-%s" % (_slug(size), cs), "B1", "unit-size",
                "%s storage units %s" % (size, city), "/write-unit-size-page", "core",
                "holds %s; needs real %s inventory in %s"
                % (SIZE_EQUIV.get(size, "[real what-fits]"), size, city))
        for t in types:
            add("type-%s-%s" % (_slug(t), cs), "C/D/E", "service-city",
                "%s storage %s" % (t, city), "/write-service-city-page", "core",
                "needs real %s inventory in %s + the facility's own spec" % (t, city))

    # Audience nodes localize on the anchor institution, not just the city.
    for aud in audiences:
        add("audience-%s" % _slug(aud), "E/F", "service-page or service-city",
            "%s storage near [campus/base/city]" % aud,
            "/write-service-page", "core",
            "localize on a real campus/base; needs audience-specific proof")

    # The two link/citation assets.
    add("size-guide-asset", "B2", "local-asset",
        "storage unit sizes / what fits in a 10x10", "/write-local-asset", "outer")
    add("cost-guide-asset", "G2", "local-asset",
        "how much does a storage unit cost [market]", "/write-local-asset", "outer",
        "needs original dated market data, never recycled ranges")

    return nodes, {"collapsed": False, "reason": ""}


def _read_brand_axes(path):
    """Read the storage axes from brand.yaml. PyYAML if available, else a minimal
    parser for the storage block's list fields."""
    with open(path, "r", encoding="utf-8") as fh:
        raw = fh.read()
    axes = {"operator_type": "", "sizes": [], "types": [],
            "audiences": [], "cities": []}
    try:
        import yaml
        data = yaml.safe_load(raw) or {}
        st = data.get("storage") or {}
        axes["operator_type"] = st.get("operator_type") or ""
        axes["sizes"] = st.get("unit_sizes") or []
        axes["types"] = st.get("storage_types") or []
        axes["audiences"] = st.get("audiences") or []
        axes["cities"] = data.get("service_areas") or []
        return axes
    except ImportError:
        pass

    def _flow_list(key):
        # matches `key: [a, b, "c d"]`
        m = re.search(r"^\s*%s:\s*\[(.*?)\]\s*$" % re.escape(key), raw, re.MULTILINE)
        if not m:
            return []
        return [p.strip().strip('"').strip("'") for p in m.group(1).split(",")
                if p.strip()]

    def _scalar(key):
        m = re.search(r"^\s*%s:\s*(.+?)\s*$" % re.escape(key), raw, re.MULTILINE)
        return m.group(1).strip().strip('"').strip("'") if m else ""

    axes["operator_type"] = _scalar("operator_type")
    axes["sizes"] = _flow_list("unit_sizes")
    axes["types"] = _flow_list("storage_types")
    axes["audiences"] = _flow_list("audiences")
    axes["cities"] = _flow_list("service_areas")
    return axes


def _split(arg):
    if not arg:
        return []
    # split on commas not inside quotes; simple: split on comma, strip quotes
    return [p.strip().strip('"').strip("'") for p in arg.split(",") if p.strip()]


def run(args):
    if args.brand:
        try:
            axes = _read_brand_axes(args.brand)
        except OSError as exc:
            print("error: could not read %s: %s" % (args.brand, exc), file=sys.stderr)
            return 1
        operator_type = args.operator_type or axes["operator_type"] or "multi_facility"
        sizes = _split(args.sizes) or axes["sizes"]
        types = _split(args.types) or axes["types"]
        audiences = _split(args.audiences) or axes["audiences"]
        cities = _split(args.cities) or axes["cities"]
    else:
        operator_type = args.operator_type or "multi_facility"
        sizes, types = _split(args.sizes), _split(args.types)
        audiences, cities = _split(args.audiences), _split(args.cities)

    nodes, meta = generate(operator_type, sizes, types, audiences, cities)

    print("Self-storage candidate ceiling (operator_type=%s)" % operator_type)
    print("  A CEILING, not a map. Every node is index-only: the architect must "
          "demand-filter and evidence-gate each before promotion to a page.")
    if meta["collapsed"]:
        print("  COLLAPSED - %s" % meta["reason"])
    print("  %d candidate node(s)\n" % len(nodes))
    print("  %-26s %-8s %-16s %s" % ("node_id", "cluster", "page_type", "target_query"))
    print("  " + "-" * 90)
    for n in nodes:
        print("  %-26s %-8s %-16s %s"
              % (n["node_id"][:26], n["cluster"], n["page_type"][:16], n["target_query"]))
    print("")
    print("  Next: hand this to topical-map-architect. It runs the demand filter, "
          "the user-cluster merge, and the storage evidence gate "
          "(storage-topical-map.md section 5), then writes clients/<slug>/topical-map.md.")
    return 0


def self_test():
    # Multi-facility: 2 cities x 2 sizes x 1 type + 1 audience -> grid emitted.
    nodes, meta = generate("multi_facility", ["10x10", "10x20"],
                           ["climate-controlled"], ["student"],
                           ["Austin", "Round Rock"])
    ids = {n["node_id"] for n in nodes}
    assert not meta["collapsed"], "multi-facility should not collapse"
    assert "size-10x10-austin" in ids, ids
    assert "size-10x20-round-rock" in ids, ids
    assert "type-climate-controlled-austin" in ids, ids
    assert "facility-round-rock" in ids, ids
    assert "audience-student" in ids, ids
    assert all(n["status"] == "index-only" for n in nodes), "all born index-only"

    # Single-facility: collapse - NO axis pages, only homepage/about/faq/asset.
    s_nodes, s_meta = generate("single_facility", ["10x10", "10x20"],
                               ["climate-controlled"], [], ["Austin"])
    s_ids = {n["node_id"] for n in s_nodes}
    assert s_meta["collapsed"], "single-facility must collapse"
    assert not any(i.startswith("size-1") or i.startswith("type-") or
                   i.startswith("facility-") for i in s_ids), \
        "single-facility must emit NO axis pages: %s" % sorted(s_ids)
    assert "homepage" in s_ids and "size-guide-asset" in s_ids, sorted(s_ids)

    # brand.yaml minimal parse (flow-style lists) works without PyYAML being needed.
    import tempfile
    b = ("client:\n  slug: acme\n"
         "service_areas: [\"Austin\", \"Round Rock\"]\n"
         "storage:\n  operator_type: multi_facility\n"
         "  unit_sizes: [\"10x10\", \"10x20\"]\n"
         "  storage_types: [\"drive-up\"]\n"
         "  audiences: []\n")
    d = tempfile.mkdtemp()
    bp = os.path.join(d, "brand.yaml")
    with open(bp, "w", encoding="utf-8") as fh:
        fh.write(b)
    axes = _read_brand_axes(bp)
    assert axes["operator_type"] == "multi_facility", axes
    assert axes["sizes"] == ["10x10", "10x20"], axes
    assert axes["cities"] == ["Austin", "Round Rock"], axes

    print("self-test OK")
    print("  multi-facility grid: %d nodes (all index-only)" % len(nodes))
    print("  single-facility collapse: %d nodes, no axis pages" % len(s_nodes))
    print("  brand.yaml minimal-parse axes: %s sizes, %s cities"
          % (len(axes["sizes"]), len(axes["cities"])))
    return 0


def build_parser():
    p = argparse.ArgumentParser(
        description="Expand a self-storage client's real axes into the candidate "
                    "node ceiling for the topical-map architect (a planning aid, "
                    "NOT the map).")
    p.add_argument("--brand", help="path to brand.yaml (reads storage axes + service_areas)")
    p.add_argument("--operator-type", default="",
                   choices=["", "single_facility", "multi_facility"],
                   help="single_facility collapses the grid; multi_facility emits it")
    p.add_argument("--sizes", default="", help="comma-separated unit sizes")
    p.add_argument("--types", default="", help="comma-separated storage types")
    p.add_argument("--audiences", default="", help="comma-separated audiences")
    p.add_argument("--cities", default="", help="comma-separated served cities")
    p.add_argument("--self-test", action="store_true",
                   help="run the built-in self-test and exit")
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    if args.self_test:
        return self_test()
    return run(args)


if __name__ == "__main__":
    sys.exit(main())
