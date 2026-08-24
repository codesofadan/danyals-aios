#!/usr/bin/env python3
"""duplication_gate.py - Near-duplicate / boilerplate check across sibling pages.

Offline, stdlib-only (argparse, re, os, sys). No network calls. Deterministic:
same inputs always give the same score.

Hardens the doorway-page rule (B1). Doctrine and Google's spam policy both say
templated near-duplicate pages across cities are doorway abuse: "sites or pages
created to rank for specific, similar search queries" that offer nothing unique
per page. A legitimate multi-location client can still have many pages, but only
if each carries a genuinely differentiated first-party dataset. This gate makes
that testable: it computes pairwise w-shingling Jaccard similarity across two or
more sibling page files and fails any pair whose overlap exceeds a boilerplate
threshold (default 0.70).

Method
------
- w-shingling: each page is stripped to prose, tokenized, and turned into the
  set of its overlapping w-word shingles (default w=5). Shingling captures
  phrase-level, order-sensitive overlap, so a template with a swapped city token
  still scores high while two genuinely distinct pages score low.
- Jaccard similarity of two shingle sets = |A intersect B| / |A union B|,
  a value in 0.0 (disjoint) .. 1.0 (identical).
- Every unordered pair is scored; any pair at or above --threshold is flagged.

This never rewrites or games anything (Law 8). It surfaces near-duplication so a
human injects the real per-page local value the doorway rule demands.

Usage
-----
  python duplication_gate.py page-austin.md page-round-rock.md page-cedar-park.md
  python duplication_gate.py output/acme/            # all .md/.txt in a folder
  python duplication_gate.py --threshold 0.60 --shingle-size 4 a.md b.md
  python duplication_gate.py --self-test

Exit code: 0 = no pair over threshold, 1 = at least one near-duplicate pair
(or a usage error: fewer than two comparable files).
"""

import argparse
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from readability_scorer import strip_markdown  # stdlib-only sibling helper

TEXT_EXTS = (".md", ".markdown", ".txt")


def tokenize(text):
    return re.findall(r"[a-z0-9']+", strip_markdown(text).lower())


def shingles(tokens, w):
    """Set of overlapping w-word shingles. Short docs collapse to one shingle."""
    if len(tokens) < w:
        return {tuple(tokens)} if tokens else set()
    return {tuple(tokens[i:i + w]) for i in range(len(tokens) - w + 1)}


def jaccard(a, b):
    if not a and not b:
        return 0.0
    inter = len(a & b)
    union = len(a | b)
    return inter / union if union else 0.0


def collect_paths(paths):
    """Expand any directory argument into its text files; keep file args as-is."""
    out = []
    for p in paths:
        if os.path.isdir(p):
            for name in sorted(os.listdir(p)):
                if name.lower().endswith(TEXT_EXTS):
                    out.append(os.path.join(p, name))
        else:
            out.append(p)
    # dedupe, preserve order
    return list(dict.fromkeys(out))


def score_files(paths, shingle_size, threshold):
    docs = []
    for p in paths:
        with open(p, "r", encoding="utf-8") as fh:
            text = fh.read()
        docs.append((p, shingles(tokenize(text), shingle_size)))

    pairs = []
    for i in range(len(docs)):
        for j in range(i + 1, len(docs)):
            sim = jaccard(docs[i][1], docs[j][1])
            pairs.append((docs[i][0], docs[j][0], sim, sim >= threshold))
    return pairs


def run(args):
    paths = collect_paths(args.paths)
    missing = [p for p in paths if not os.path.isfile(p)]
    if missing:
        print("error: file(s) not found: %s" % ", ".join(missing), file=sys.stderr)
        return 1
    if len(paths) < 2:
        print("error: need at least two comparable files (got %d). Pass sibling "
              "page files or a directory of them." % len(paths), file=sys.stderr)
        return 1

    pairs = score_files(paths, args.shingle_size, args.threshold)

    print("Duplication gate across %d files" % len(paths))
    print("  shingle size: %d words   near-duplicate threshold: %.2f"
          % (args.shingle_size, args.threshold))
    print("")
    print("  %-8s %-32s %-32s" % ("jaccard", "file A", "file B"))
    flagged = [p for p in pairs if p[3]]
    for a, b, sim, over in sorted(pairs, key=lambda x: -x[2]):
        mark = "OVER" if over else "ok"
        print("  %6.2f %-4s %-32s %-32s"
              % (sim, mark, os.path.basename(a)[:32], os.path.basename(b)[:32]))
    print("")

    if flagged:
        print("FAIL  %d pair(s) at or above %.2f: near-duplicate / doorway risk."
              % (len(flagged), args.threshold))
        print("      Each sibling page must carry unique local value (different")
        print("      facts, prices, projects, landmarks), not a swapped city token.")
        return 1
    print("PASS  all pairs below %.2f: no near-duplicate boilerplate detected"
          % args.threshold)
    return 0


def self_test():
    # A doorway template: a long shared body, only the city token swapped. This
    # is what real doorway spam looks like: the template dominates, the variable
    # is tiny. Single-token city names keep the shingle windows aligned.
    template = (
        "# Emergency Plumber in {city}\n\n"
        "Looking for an emergency plumber? Our licensed team is on call around "
        "the clock, every day of the year, ready to roll the moment you phone. "
        "When a pipe bursts at midnight the water does not wait, and neither do "
        "we. Our trucks are stocked with the parts that fix the most common "
        "failures on the first visit, so you are not left waiting for a second "
        "appointment. We quote the price before we start any work, we protect "
        "your floors, and we leave the work area cleaner than we found it. From "
        "burst pipes and failed water heaters to slow drains and running "
        "toilets, we handle the whole list, and we back every repair with a "
        "written guarantee that most shops in {city} will not put in writing."
    )
    page_a = template.replace("{city}", "Austin")
    page_b = template.replace("{city}", "Dallas")
    # A genuinely differentiated page: different facts, structure, specifics.
    page_c = (
        "# Water Heater Replacement in Cedar Park\n\n"
        "A failed water heater on a January morning is a Cedar Park classic, "
        "usually a 12-year-old tank that finally rusted through. We stock 40 and "
        "50 gallon Bradford White units and swap most of them in about three "
        "hours. On Whitestone Boulevard last winter we moved a family from a "
        "leaking tank to a tankless Navien in a single afternoon for $3,900."
    )

    sh = lambda t: shingles(tokenize(t), 5)
    sa, sb, sc = sh(page_a), sh(page_b), sh(page_c)
    dup = jaccard(sa, sb)
    distinct_ac = jaccard(sa, sc)
    distinct_bc = jaccard(sb, sc)

    assert dup >= 0.70, "swapped-token doorway pair should flag, got %.2f" % dup
    assert distinct_ac < 0.70, "distinct pair A/C should pass, got %.2f" % distinct_ac
    assert distinct_bc < 0.70, "distinct pair B/C should pass, got %.2f" % distinct_bc

    print("self-test OK")
    print("  doorway template (Austin vs Dallas): jaccard %.2f (OVER, would FAIL)" % dup)
    print("  differentiated page (vs Cedar Park):      jaccard %.2f / %.2f (ok, PASS)"
          % (distinct_ac, distinct_bc))
    return 0


def build_parser():
    p = argparse.ArgumentParser(
        description="Pairwise w-shingling Jaccard near-duplicate check across sibling pages (hardens B1/doorway).",
    )
    p.add_argument("paths", nargs="*",
                   help="two or more page files, or a directory of them")
    p.add_argument("--threshold", type=float, default=0.70,
                   help="Jaccard at or above this flags a near-duplicate pair (default 0.70)")
    p.add_argument("--shingle-size", type=int, default=5,
                   help="shingle window in words (default 5)")
    p.add_argument("--self-test", action="store_true",
                   help="run the built-in self-test and exit")
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    if args.self_test:
        return self_test()
    if not args.paths:
        build_parser().error("need at least two files or a directory (or --self-test)")
    return run(args)


if __name__ == "__main__":
    sys.exit(main())
