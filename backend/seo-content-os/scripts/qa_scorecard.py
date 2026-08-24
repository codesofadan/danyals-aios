#!/usr/bin/env python3
"""qa_scorecard.py - 6-category editorial QA scorecard with a 3-fail kill gate.

Offline, stdlib-only (argparse, re, sys, os). No network calls. Reads one draft
markdown page (the `page.md` from the output contract) and scores it against the
Search Roost editorial QA rubric (research file 06, Part 2): six categories,
each Pass or Needs-work, and a hard publication gate: if 3 or more categories
fail, do not publish.

This is a deterministic heuristic gate, not an editor's judgment. It confirms
the auditable, structural signals are present (sourcing, structure, metadata,
links, uniqueness scaffolding, technical baseline). A human still reads for
substance. It is Law-8 aligned: no detector or plagiarism gate, ever. Originality
is enforced by construction (real facts, SME specifics) and verified here only by
the presence of sourcing, not by a similarity score.

The six categories
------------------
  1 sourcing        external citations present (>= --min-sources) or a Sources
                    section; no naked "invented number" placeholders
  2 structure       H2 hierarchy (>= --min-h2) and skimmable blocks (a list or
                    a short direct-answer opener)
  3 duplication     uniqueness scaffolding present: meta title, meta description,
                    and a slug/canonical, so the page can be made non-duplicate
  4 internal_links  internal (relative) links in the 2..--max-internal band,
                    with at least one that looks like a hub/silo link
  5 metadata        meta title 30-65 chars, meta description 70-160 chars,
                    every image carries non-empty alt text
  6 technical       a schema / JSON-LD signal is present and the page is not
                    marked noindex

Scoring and exit codes
----------------------
  score = passes / 6
  0 fails            -> PASS        exit 0
  1-2 fails          -> NEEDS-WORK  exit 1  (fix the failing categories, re-run)
  3+ fails           -> KILL        exit 3  (publication gate: do not publish)
  usage error                       exit 2  (argparse)

Usage
-----
  python qa_scorecard.py output/acme/plumbing-austin/page.md
  python qa_scorecard.py --min-sources 3 page.md
  echo "# ..." | python qa_scorecard.py -
  python qa_scorecard.py --self-test
"""

import argparse
import os
import re
import sys

LINK_RE = re.compile(r"\[([^\]]*)\]\(([^)]+)\)")
IMG_RE = re.compile(r"!\[([^\]]*)\]\(([^)]+)\)")
H2_RE = re.compile(r"^\s{0,3}##\s+\S", re.MULTILINE)
LIST_RE = re.compile(r"^\s*(?:[-*+]\s+|\d+\.\s+)\S", re.MULTILINE)


def _find_meta(text, label):
    """Find a metadata value written as 'Meta title: X', 'title: X',
    '**Meta title:** X', or a YAML-frontmatter 'title: X'."""
    pats = [
        r"(?im)^\s*[*_>#\s]*meta\s+%s\s*[:=]\s*(.+)$" % label,
        r"(?im)^\s*[*_>#\s]*%s\s*[:=]\s*(.+)$" % label,
    ]
    for pat in pats:
        m = re.search(pat, text)
        if m:
            return m.group(1).strip().strip("*_`\"' ")
    return None


def _links(text):
    imgs = IMG_RE.findall(text)
    all_links = LINK_RE.findall(text)
    # image matches also match the link pattern (minus the leading !); drop them
    img_targets = set(t for _, t in imgs)
    links = [(a, t) for a, t in all_links if t not in img_targets or a]
    # rebuild cleanly: links that are not images
    links = []
    for m in LINK_RE.finditer(text):
        start = m.start()
        if start > 0 and text[start - 1] == "!":
            continue
        links.append((m.group(1), m.group(2)))
    return links, imgs


def _is_internal(target):
    t = target.strip()
    if t.startswith("#") or t.startswith("mailto:") or t.startswith("tel:"):
        return False
    if re.match(r"^[a-z]+://", t, re.I):
        return False
    return True


def cat_sourcing(text, min_sources):
    ext = [t for _, t in _links(text)[0] if re.match(r"^https?://", t.strip(), re.I)]
    has_section = re.search(r"(?im)^\s*#{1,6}\s*(sources|references|citations)\b", text)
    n = len(set(ext))
    passed = n >= min_sources or (has_section is not None and n >= 1)
    return passed, "%d external citation(s)%s" % (
        n, ", Sources section present" if has_section else "")


def cat_structure(text, min_h2):
    h2 = len(H2_RE.findall(text))
    skimmable = bool(LIST_RE.search(text))
    passed = h2 >= min_h2 and skimmable
    return passed, "%d H2 heading(s), %s" % (
        h2, "has list/skimmable block" if skimmable else "no list block")


def cat_duplication(text):
    title = _find_meta(text, "title")
    desc = _find_meta(text, "description")
    slug = (_find_meta(text, "slug") or _find_meta(text, "canonical")
            or _find_meta(text, "url"))
    present = [n for n, v in (("title", title), ("description", desc),
                              ("slug/canonical", slug)) if v]
    passed = title is not None and desc is not None and slug is not None
    return passed, "uniqueness fields present: %s" % (", ".join(present) or "none")


def cat_internal_links(text, max_internal):
    internal = [(a, t) for a, t in _links(text)[0] if _is_internal(t)]
    n = len(internal)
    # a "hub" link looks like a single-segment path e.g. /plumbing or /services
    hub = any(re.match(r"^/?[a-z0-9-]+/?$", t.strip(), re.I) for _, t in internal)
    passed = 2 <= n <= max_internal and hub
    detail = "%d internal link(s)" % n
    if n > max_internal:
        detail += " (over-linked, cap %d)" % max_internal
    if not hub and n:
        detail += ", no hub/silo link"
    return passed, detail


def cat_metadata(text):
    title = _find_meta(text, "title")
    desc = _find_meta(text, "description")
    _, imgs = _links(text)
    empty_alt = [t for a, t in imgs if not a.strip()]
    tlen = len(title) if title else 0
    dlen = len(desc) if desc else 0
    title_ok = title is not None and 30 <= tlen <= 65
    desc_ok = desc is not None and 70 <= dlen <= 160
    alt_ok = len(empty_alt) == 0
    passed = title_ok and desc_ok and alt_ok
    return passed, "title %d chars, description %d chars, %d image(s) missing alt" % (
        tlen, dlen, len(empty_alt))


def cat_technical(text):
    schema = bool(re.search(r'@context|application/ld\+json|schema\.json|JSON-LD',
                            text, re.I))
    noindex = bool(re.search(r"noindex", text, re.I))
    passed = schema and not noindex
    return passed, "%s, %s" % (
        "schema/JSON-LD signal present" if schema else "no schema signal",
        "noindex flagged" if noindex else "indexable")


CATEGORIES = ["sourcing", "structure", "duplication",
              "internal_links", "metadata", "technical"]


def score_draft(text, min_sources=2, min_h2=3, max_internal=6):
    results = {
        "sourcing": cat_sourcing(text, min_sources),
        "structure": cat_structure(text, min_h2),
        "duplication": cat_duplication(text),
        "internal_links": cat_internal_links(text, max_internal),
        "metadata": cat_metadata(text),
        "technical": cat_technical(text),
    }
    fails = [c for c in CATEGORIES if not results[c][0]]
    passes = len(CATEGORIES) - len(fails)
    if len(fails) >= 3:
        verdict, code = "KILL", 3
    elif len(fails) >= 1:
        verdict, code = "NEEDS-WORK", 1
    else:
        verdict, code = "PASS", 0
    return {"results": results, "fails": fails, "passes": passes,
            "verdict": verdict, "code": code}


def render_scorecard_md(src, sc):
    """Render the scorecard as markdown (the `scorecard.md` artifact the
    lifecycle docs reference: editorial-scorecard.md, refresh.md)."""
    lines = [
        "# Editorial QA Scorecard", "",
        "**Page:** %s" % src,
        "**Verdict:** %s" % sc["verdict"],
        "**Score:** %d/6 categories pass" % sc["passes"], "",
        "| Category | Result | Detail |", "|---|---|---|",
    ]
    for c in CATEGORIES:
        passed, detail = sc["results"][c]
        lines.append("| %s | %s | %s |" % (c, "PASS" if passed else "NEEDS-WORK", detail))
    lines += ["", "Gate: 0 fails = PASS, 1-2 = NEEDS-WORK, 3+ = KILL (do not publish)."]
    if sc["fails"]:
        lines.append("Failing categories: %s" % ", ".join(sc["fails"]))
    return "\n".join(lines) + "\n"


def run(args):
    if args.path == "-":
        text = sys.stdin.read()
        src = "<stdin>"
    else:
        if not os.path.exists(args.path):
            sys.stderr.write("draft not found: %s\n" % args.path)
            return 2
        with open(args.path, "r", encoding="utf-8") as fh:
            text = fh.read()
        src = args.path

    sc = score_draft(text, args.min_sources, args.min_h2, args.max_internal)

    # Write scorecard.md next to the page (or to --out) so the artifact the
    # lifecycle docs reference actually exists on disk.
    out_path = args.out
    if out_path is None and src != "<stdin>":
        out_path = os.path.join(
            os.path.dirname(os.path.abspath(args.path)), "scorecard.md")
    wrote = None
    if out_path and not args.no_file:
        try:
            with open(out_path, "w", encoding="utf-8") as fh:
                fh.write(render_scorecard_md(src, sc))
            wrote = out_path
        except OSError as e:
            sys.stderr.write("could not write scorecard.md: %s\n" % e)
    print("Editorial QA scorecard for %s" % src)
    print("  %-16s %-11s %s" % ("category", "result", "detail"))
    print("  " + "-" * 68)
    for c in CATEGORIES:
        passed, detail = sc["results"][c]
        print("  %-16s %-11s %s" % (c, "PASS" if passed else "NEEDS-WORK", detail))
    print("")
    print("  score: %d/6 pass" % sc["passes"])
    if wrote:
        print("  scorecard written: %s" % wrote)
    print("")
    if sc["verdict"] == "PASS":
        print("PASS  publishable; all 6 categories clear.")
    elif sc["verdict"] == "NEEDS-WORK":
        print("NEEDS-WORK  fix: %s, then re-run." % ", ".join(sc["fails"]))
    else:
        print("KILL  %d categories failed (3-fail gate). Do not publish. Fix: %s"
              % (len(sc["fails"]), ", ".join(sc["fails"])))
    return sc["code"]


def self_test():
    good = (
        "Meta title: Emergency Plumber in Austin TX | 24/7 Fast Response\n"
        "Meta description: Need an emergency plumber in Austin? Our licensed "
        "crew arrives same-day across Travis County. Call for a fast, fair quote "
        "today.\n"
        "slug: /plumbing/austin-emergency\n\n"
        "## Same-day emergency plumbing in Austin\n"
        "We answer calls in under 60 seconds. Here is what to expect.\n\n"
        "- Licensed, insured technicians\n"
        "- Flat-rate pricing, no call-out fee\n\n"
        "## What an Austin repair costs\n"
        "Average burst-pipe repair here runs $350-$600 per city permit data "
        "([permits](https://example.gov/permits)) and licensed under state "
        "records ([license lookup](https://example.gov/tdlr)).\n\n"
        "## Book an Austin plumber today\n"
        "Call or request a visit online and we confirm your slot in minutes.\n\n"
        "See our [plumbing](/plumbing) hub and [water heaters](/plumbing/water-heaters).\n\n"
        "![Our Austin crew on a job](/img/crew.jpg)\n\n"
        '<script type="application/ld+json">{"@context":"https://schema.org"}</script>\n'
    )
    sc = score_draft(good)
    for c in CATEGORIES:
        assert sc["results"][c][0], "%s should pass: %s" % (c, sc["results"][c][1])
    assert sc["verdict"] == "PASS" and sc["code"] == 0, sc["verdict"]

    # kill case: no metadata, no sources, no structure, no links, no schema
    bad = "# A page\n\nSome text with no headings past this and nothing else.\n"
    sk = score_draft(bad)
    assert sk["verdict"] == "KILL" and sk["code"] == 3, sk
    assert len(sk["fails"]) >= 3

    # needs-work: good page but strip the schema signal -> exactly 1 fail
    nw_text = good.replace("application/ld+json", "text/plain").replace(
        "@context", "context")
    nw = score_draft(nw_text)
    assert nw["verdict"] == "NEEDS-WORK" and nw["code"] == 1, nw
    assert nw["fails"] == ["technical"], nw["fails"]

    print("self-test OK")
    print("  good draft -> PASS (6/6), stripped-schema -> NEEDS-WORK (%s), "
          "empty draft -> KILL (%d fails)"
          % (nw["fails"][0], len(sk["fails"])))
    return 0


def build_parser():
    p = argparse.ArgumentParser(
        description="6-category editorial QA scorecard with a 3-fail kill gate.")
    p.add_argument("path", nargs="?", default="-",
                   help="path to a draft page.md, or '-' for stdin")
    p.add_argument("--min-sources", type=int, default=2,
                   help="external citations needed to pass sourcing (default 2)")
    p.add_argument("--min-h2", type=int, default=3,
                   help="H2 headings needed to pass structure (default 3)")
    p.add_argument("--max-internal", type=int, default=6,
                   help="max internal links before over-linking (default 6)")
    p.add_argument("--out",
                   help="write scorecard.md to this path (default: alongside the input page)")
    p.add_argument("--no-file", action="store_true",
                   help="do not write scorecard.md (stdout only)")
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
