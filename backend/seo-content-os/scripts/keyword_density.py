#!/usr/bin/env python3
"""keyword_density.py - Term-frequency and exact-phrase density for a draft.

Offline, stdlib-only (re, argparse, json). No network calls.

What it reports, per target keyword/phrase
------------------------------------------
- Exact-phrase count and density (phrase occurrences * phrase-word-count /
  total words). This is the standard way to express multi-word phrase density.
- A natural-use flag when density exceeds --max-density (default 0.025 = 2.5%),
  which is a common over-optimization signal for local copy.
- Single-word target frequency and density for one-word targets.

This is an over-optimization *detector*, in the spirit of Doctrine Law 8: it
surfaces stuffing so a human writes more naturally. It does NOT rewrite,
optimise toward a number, or game any detector.

Keywords come from --keyword (repeatable), a comma list via --keywords, or a
brand.yaml services: / primary_city (auto-built "[service] [city]" phrases).

Exit code 0 = all targets under threshold, 1 = any target over threshold.

Usage
-----
  python keyword_density.py --keyword "emergency plumber austin" draft.md
  python keyword_density.py --keywords "roof repair, roof replacement" draft.md
  python keyword_density.py --brand clients/acme/brand.yaml draft.md
  python keyword_density.py --self-test
"""

import argparse
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from readability_scorer import strip_markdown  # local, stdlib-only helper


def tokenize(text):
    return re.findall(r"[a-z0-9]+", text.lower())


def count_phrase(tokens, phrase_tokens):
    n = len(phrase_tokens)
    if n == 0:
        return 0
    count = 0
    for i in range(len(tokens) - n + 1):
        if tokens[i:i + n] == phrase_tokens:
            count += 1
    return count


def analyse(text, keywords, max_density=0.025):
    clean = strip_markdown(text)
    tokens = tokenize(clean)
    total = max(1, len(tokens))
    rows = []
    for kw in keywords:
        kw_tokens = tokenize(kw)
        if not kw_tokens:
            continue
        occ = count_phrase(tokens, kw_tokens)
        # density = fraction of the document's words covered by this phrase
        density = (occ * len(kw_tokens)) / total
        rows.append({
            "keyword": kw,
            "words_in_phrase": len(kw_tokens),
            "occurrences": occ,
            "density": density,
            "over": density > max_density,
        })
    return {"total_words": len(tokens), "rows": rows, "max_density": max_density}


def load_brand_keywords(path):
    """Build "[service] [city]" phrases from a brand.yaml (best-effort, no yaml
    dependency required)."""
    with open(path, "r", encoding="utf-8") as fh:
        raw = fh.read()
    services = []
    primary_city = ""
    # services: is a YAML list; capture "- item" lines until dedent/next key.
    lines = raw.splitlines()
    mode = None
    for line in lines:
        if re.match(r"^services:\s*(\[\s*\])?\s*$", line):
            mode = "services"
            continue
        if re.match(r"^\s*primary_city:\s*(.*)$", line):
            m = re.match(r"^\s*primary_city:\s*(.*)$", line)
            primary_city = m.group(1).strip().strip('"').strip("'")
            continue
        if mode == "services":
            m = re.match(r"^\s*-\s*(.+)$", line)
            if m:
                services.append(m.group(1).strip().strip('"').strip("'"))
                continue
            if line and not line[0].isspace():
                mode = None
    keywords = list(services)
    if primary_city:
        keywords += ["%s %s" % (s, primary_city) for s in services]
    return keywords


def run(args):
    keywords = list(args.keyword or [])
    if args.keywords:
        keywords += [k.strip() for k in args.keywords.split(",") if k.strip()]
    if args.brand:
        keywords += load_brand_keywords(args.brand)
    keywords = [k for k in dict.fromkeys(keywords)]  # dedupe, keep order
    if not keywords:
        print("error: no target keywords (use --keyword/--keywords/--brand)",
              file=sys.stderr)
        return 1

    if args.path == "-":
        text = sys.stdin.read()
        src = "<stdin>"
    else:
        with open(args.path, "r", encoding="utf-8") as fh:
            text = fh.read()
        src = args.path

    result = analyse(text, keywords, max_density=args.max_density)
    print("Keyword density report for %s" % src)
    print("  total words: %d   threshold: %.1f%%"
          % (result["total_words"], 100 * result["max_density"]))
    print("  %-34s %5s %6s %8s %s"
          % ("keyword", "words", "count", "density", "flag"))
    any_over = False
    for r in sorted(result["rows"], key=lambda x: -x["density"]):
        flag = "OVER" if r["over"] else "ok"
        if r["over"]:
            any_over = True
        print("  %-34s %5d %6d %7.2f%% %s"
              % (r["keyword"][:34], r["words_in_phrase"], r["occurrences"],
                 100 * r["density"], flag))
    print("")
    if any_over:
        print("FAIL  one or more keywords exceed the natural-use threshold")
        print("      (rewrite for variety; do not target a density number)")
        return 1
    print("PASS  all keywords within natural-use range")
    return 0


def self_test():
    stuffed = (("Emergency plumber Austin is the best emergency plumber Austin. "
                "For an emergency plumber Austin, call the emergency plumber Austin "
                "team. ") * 3)
    natural = (
        "We are a plumbing company in Austin. When a pipe bursts at midnight, "
        "our crew shows up fast and fixes it right the first time. Homeowners "
        "across the city trust our licensed team for repairs of every kind, from "
        "a slow drip under the kitchen sink to a full repipe on an older home. "
        "We answer the phone at any hour, quote the price before we start, and "
        "leave the work area cleaner than we found it. Most jobs finish in a "
        "single visit, and every repair is backed by a written guarantee that we "
        "stand behind for as long as you own the house.")
    r_stuffed = analyse(stuffed, ["emergency plumber austin"])
    r_natural = analyse(natural, ["emergency plumber austin", "plumbing company"])
    assert r_stuffed["rows"][0]["over"], "stuffed text should flag OVER"
    assert not any(x["over"] for x in r_natural["rows"]), "natural text should pass"
    print("self-test OK")
    print("  stuffed: density %.1f%% (OVER)"
          % (100 * r_stuffed["rows"][0]["density"]))
    print("  natural: max density %.1f%% (ok)"
          % (100 * max(x["density"] for x in r_natural["rows"])))
    return 0


def build_parser():
    p = argparse.ArgumentParser(
        description="Keyword frequency + exact-phrase density (over-optimization detector).",
    )
    p.add_argument("path", nargs="?", default="-",
                   help="path to a markdown/text draft, or '-' for stdin")
    p.add_argument("--keyword", action="append",
                   help="a target keyword/phrase (repeatable)")
    p.add_argument("--keywords", help="comma-separated target keywords")
    p.add_argument("--brand", help="brand.yaml to auto-build [service] [city] phrases")
    p.add_argument("--max-density", type=float, default=0.025,
                   help="over-optimization threshold as a fraction (default 0.025)")
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
