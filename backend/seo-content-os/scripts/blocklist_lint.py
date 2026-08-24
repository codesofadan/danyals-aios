#!/usr/bin/env python3
"""blocklist_lint.py - Lint a draft against the Tier-1 AI-tell vocabulary.

Offline, stdlib-only (re, os, sys, argparse). No network calls.

What it does
------------
Operationalizes quality gate G9 (voice fidelity). It parses the Tier-1 hard-ban
terms out of `knowledge/voice/vocabulary-blocklist.md` and scans a draft for
literal hits, reporting each with line, column, the matched text, the source
term, and the tier. Optional client `banned_phrases` (via --banned) are scanned
as an extra always-on Tier layer.

This is not detector-evasion (doctrine Law 8). It is a craft check: these terms
read as machine-written to a human and almost always mark a sentence with no
real local fact in it. The tool surfaces hits so a human rewrites from a more
specific premise; it never rewrites or scores AI-detection.

The context / allowlist layer (to cut false positives)
------------------------------------------------------
1. Tricolon and quoted phrases are matched whole, never split into single words
   (so "fast, reliable, and affordable" flags as a phrase, not three words).
2. Comma-separated near-synonym groups that the blocklist annotates as a group
   ("reliable, dependable, trustworthy (when stacked ...)") only flag when 2+
   members of the group appear on the same line.
3. Terms the blocklist marks conditional ("trusted ... OK when tied to a real
   number", "affordable ... name the number") are suppressed on a line that
   carries an allow-signal (a digit, $, %, or the word license/lic).
4. Slash variants ("pride ourselves / take pride") each flag individually.

Exit code 0 = no confirmed hits (pass), 1 = one or more hits found.

Usage
-----
  python blocklist_lint.py draft.md
  python blocklist_lint.py --blocklist knowledge/voice/vocabulary-blocklist.md draft.md
  python blocklist_lint.py --banned "painless" --banned "guarantee" draft.md
  echo '...' | python blocklist_lint.py -
  python blocklist_lint.py --self-test
"""

import argparse
import os
import re
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_BLOCKLIST = os.path.join(
    SCRIPT_DIR, os.pardir, "knowledge", "voice", "vocabulary-blocklist.md")

# An annotation carrying one of these means "allowed when a real specific is
# present"; the hit is suppressed on a line that also carries an allow-signal.
ALLOW_MARKERS = (
    "ok when", "ok only", "allowed only", "fine when", "fine occasionally",
    "only when", "only as", "tied to a real", "name the number",
    "name the price", "name the range", "name the metric", "when tied to",
    "when literal", "when it means", "see tier 2", "literal use",
)

# A line carrying one of these is treated as having the real specific that makes
# a conditional term legitimate (a price, a percentage, a license number).
ALLOW_SIGNAL = re.compile(r"(\$|\d|%|\blic\b|\blicense\b|#)", re.IGNORECASE)

WILDCARD = r"[\w'\-]+(?:\s+[\w'\-]+){0,3}"  # a [placeholder] = 1 to 4 words


def term_to_regex(term):
    """Compile a term to a whitespace-flexible, word-boundaried regex. A
    [placeholder] segment becomes a 1-to-4-word wildcard.

    Returns None when a placeholder term carries too little literal anchor to
    match safely. A fragment like "at [Brand]" would otherwise wildcard-match
    any "at <two words>" (at our practice, at once, at the consult) and flood
    the report with false positives. A placeholder term needs 2+ literal
    anchor words of 3 or more characters."""
    term = term.strip().rstrip(".").strip()
    tokens = re.findall(r"\[[^\]]*\]|[\w'\-]+|[^\s\w]+", term)
    parts = []           # (regex_fragment, is_punctuation)
    has_wild = False
    anchors = 0
    for tok in tokens:
        if tok.startswith("[") and tok.endswith("]"):
            parts.append((WILDCARD, False))
            has_wild = True
        elif re.match(r"^[^\s\w]+$", tok):
            parts.append((re.escape(tok), True))
        else:
            parts.append((re.escape(tok), False))
            if len(tok) >= 3:
                anchors += 1
    if not parts:
        return None
    if has_wild and anchors < 2:
        return None
    pattern = parts[0][0]
    for frag, is_punct in parts[1:]:
        pattern += (r"\s*" if is_punct else r"\s+") + frag
    return re.compile(r"(?<!\w)" + pattern + r"(?!\w)", re.IGNORECASE)


def _split_head(head):
    """Split a bullet head into member terms, protecting [ ... ] placeholders
    from being split on their internal '/' or ','. Returns (members, style)."""
    stash = []

    def _protect(m):
        stash.append(m.group(0))
        return "\x00%d\x00" % (len(stash) - 1)

    protected = re.sub(r"\[[^\]]*\]", _protect, head)

    if "/" in protected:
        raw_parts, style = re.split(r"\s*/\s*", protected), "variant"
    elif "," in protected and "\x00" not in protected:
        # Never comma-split a phrase that contains a [placeholder]. Splitting
        # "at [Brand], we understand that..." would leave the fragment
        # "at [Brand]", which matches almost anything.
        raw_parts, style = re.split(r"\s*,\s*", protected), "list"
    else:
        raw_parts, style = [protected], "single"

    members = []
    for p in raw_parts:
        p = re.sub(r"\x00(\d+)\x00", lambda mm: stash[int(mm.group(1))], p)
        p = p.strip().strip('"').strip("'")
        p = re.sub(r"^(and|or)\s+", "", p, flags=re.IGNORECASE)
        if len(p) >= 3:
            members.append(p)
    return members, style


def parse_blocklist(path):
    """Parse Tier-1 bullets from the vocabulary blocklist into term records.

    Each record: dict(display, regex, category, group_id, stacked,
    allow_number, tier)."""
    with open(path, "r", encoding="utf-8") as fh:
        lines = fh.read().splitlines()

    terms = []
    in_tier1 = False
    category = None
    group_id = 0
    # group_id -> set of member display strings (for stacking counts)
    groups = {}

    for line in lines:
        h2 = re.match(r"^##\s+(.*)$", line)
        if h2:
            in_tier1 = h2.group(1).strip().lower().startswith("tier 1")
            category = None
            continue
        if not in_tier1:
            continue
        h3 = re.match(r"^###\s+(.*)$", line)
        if h3:
            category = h3.group(1).strip()
            continue
        m = re.match(r"^-\s+(.*\S)\s*$", line)
        if not m:
            continue
        raw = m.group(1).strip()

        # Quoted entries (tricolons and quoted phrases): the quoted string is a
        # single whole-phrase term; everything after the close quote is note.
        qm = re.match(r'^[\'"](.+?)[\'"](.*)$', raw)
        if qm:
            members = [qm.group(1).strip()]
            annotation = qm.group(2)
            style = "single"
        else:
            pa = raw.find(" (")
            if pa >= 0:
                head, annotation = raw[:pa], raw[pa:]
            else:
                head, annotation = raw, ""
            members, style = _split_head(head)

        if not members:
            continue

        ann_low = annotation.lower()
        allow_number = any(mk in ann_low for mk in ALLOW_MARKERS)
        stacked = (style == "list" and len(members) >= 2
                   and bool(annotation.strip()))

        group_id += 1
        groups[group_id] = set()
        for term in members:
            try:
                rx = term_to_regex(term)
            except re.error:
                continue
            if rx is None:
                continue          # too generic to match safely
            groups[group_id].add(term.lower())
            terms.append({
                "display": term,
                "regex": rx,
                "category": category or "(uncategorized)",
                "group_id": group_id,
                "stacked": stacked,
                "allow_number": allow_number,
                "tier": "Tier 1",
            })
    return terms, groups


def _iter_scan_lines(text):
    """Yield (lineno, line), skipping fenced code blocks."""
    in_fence = False
    for i, line in enumerate(text.splitlines(), 1):
        if line.strip().startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        yield i, line


def scan(text, terms, groups):
    """Return a list of hits: dict(line, col, match, display, tier, category)."""
    hits = []
    for lineno, line in _iter_scan_lines(text):
        allow_here = bool(ALLOW_SIGNAL.search(line))
        # First pass: collect candidate matches per line.
        line_candidates = []
        group_members_on_line = {}
        for term in terms:
            for m in term["regex"].finditer(line):
                if term["allow_number"] and allow_here:
                    continue  # conditional term, real specific present
                line_candidates.append((term, m.start(), m.group(0)))
                group_members_on_line.setdefault(term["group_id"], set()).add(
                    term["display"].lower())
        # Second pass: drop stacked-group hits unless 2+ members co-occur.
        for term, col, matched in line_candidates:
            if term["stacked"]:
                if len(group_members_on_line.get(term["group_id"], ())) < 2:
                    continue
            hits.append({
                "line": lineno, "col": col, "match": matched,
                "display": term["display"], "tier": term["tier"],
                "category": term["category"],
            })
    hits.sort(key=lambda h: (h["line"], h["col"]))
    return hits


def load_extra_banned(phrases):
    """Build always-on term records from client banned_phrases (repeatable)."""
    terms = []
    gid = 100000
    for ph in phrases or []:
        ph = ph.strip()
        if len(ph) < 2:
            continue
        gid += 1
        try:
            rx = term_to_regex(ph)
        except re.error:
            continue
        if rx is None:
            continue
        terms.append({
            "display": ph, "regex": rx, "category": "client banned_phrases",
            "group_id": gid, "stacked": False, "allow_number": False,
            "tier": "client-banned",
        })
    return terms


def run(args):
    if not os.path.exists(args.blocklist):
        print("error: blocklist not found: %s" % args.blocklist, file=sys.stderr)
        return 2
    terms, groups = parse_blocklist(args.blocklist)
    if not terms:
        print("error: no Tier-1 terms parsed from %s" % args.blocklist,
              file=sys.stderr)
        return 2
    terms = terms + load_extra_banned(args.banned)

    if args.path == "-":
        text = sys.stdin.read()
        src = "<stdin>"
    else:
        with open(args.path, "r", encoding="utf-8") as fh:
            text = fh.read()
        src = args.path

    hits = scan(text, terms, groups)

    print("Blocklist lint for %s" % src)
    print("  %d Tier-1 term(s) loaded from %s"
          % (len(terms), os.path.relpath(args.blocklist)))
    print("  %d hit(s)" % len(hits))
    lines = text.splitlines()
    for h in hits:
        print("  [%-12s] %-22s line %d col %d  match: %r"
              % (h["tier"], h["category"], h["line"], h["col"], h["match"]))
        if 1 <= h["line"] <= len(lines):
            print("            > %s" % lines[h["line"] - 1].strip()[:90])
    print("")
    if hits:
        print("FAIL  %d blocklist hit(s); rewrite from a more specific premise"
              % len(hits))
        return 1
    print("PASS  no Tier-1 blocklist hits")
    return 0


def self_test():
    terms, groups = parse_blocklist(DEFAULT_BLOCKLIST)
    assert len(terms) > 80, "expected a substantial Tier-1 list, got %d" % len(terms)

    clean = (
        "# Roof Repair in Round Rock\n\n"
        "Acme Roofing has fixed storm-damaged roofs across Round Rock since "
        "2004. Our crew replaces cracked flashing and torn shingles, then "
        "documents the damage for your insurer the same day.\n"
    )
    dirty = (
        "# Seamless Roofing Solutions\n\n"
        "We are your trusted partner and pride ourselves on world-class work. "
        "When it comes to your roof, look no further. We offer peace of mind "
        "and top-notch service.\n\n"
        "Our team is reliable, dependable, and trustworthy.\n"
    )
    clean_hits = scan(clean, terms, groups)
    dirty_hits = scan(dirty, terms, groups)
    dirty_terms = {h["display"].lower() for h in dirty_hits}

    assert clean_hits == [], "clean draft should have no hits: %s" % clean_hits
    for want in ("seamless", "world-class", "look no further", "peace of mind"):
        assert want in dirty_terms, "expected %r in dirty hits, got %s" % (
            want, sorted(dirty_terms))

    # Stacking: all three near-synonyms on one line -> flagged.
    stacked_line = scan("Our team is reliable, dependable, and trustworthy.\n",
                        terms, groups)
    assert stacked_line, "co-occurring near-synonyms should flag"
    # ... but a lone member on its own line -> suppressed.
    lone = scan("Our reliable crew arrives early.\n", terms, groups)
    assert lone == [], "a lone near-synonym should not flag: %s" % lone

    # Conditional allow-signal: "trusted" with a real number on the line.
    allowed = scan("We are trusted by 400 homeowners since 2009.\n",
                   terms, groups)
    assert allowed == [], "conditional term with a number should be allowed: %s" % allowed
    # ... but bare "your trusted partner" (no number) flags.
    bare = scan("We are your trusted partner in home comfort.\n", terms, groups)
    bare_terms = {h["display"].lower() for h in bare}
    assert "trusted" in bare_terms or "partner" in bare_terms, \
        "bare decoration should flag: %s" % bare

    # Client banned_phrases layer.
    extra = terms + load_extra_banned(["painless"])
    ph = scan("We promise a painless visit.\n", extra, groups)
    assert any(h["display"].lower() == "painless" for h in ph), \
        "client banned phrase should flag: %s" % ph

    print("self-test OK")
    print("  Tier-1 terms parsed: %d" % len(terms))
    print("  clean draft: 0 hits")
    print("  dirty draft: %d hits, sample: %s"
          % (len(dirty_hits), ", ".join(sorted(dirty_terms))[:70]))
    print("  stacking + allow-signal + client-banned layers: verified")
    return 0


def build_parser():
    p = argparse.ArgumentParser(
        description="Lint a draft against the Tier-1 AI-tell vocabulary (G9).",
    )
    p.add_argument("path", nargs="?", default="-",
                   help="path to a markdown/text draft, or '-' for stdin")
    p.add_argument("--blocklist", default=DEFAULT_BLOCKLIST,
                   help="path to vocabulary-blocklist.md (default: repo copy)")
    p.add_argument("--banned", action="append",
                   help="an extra client banned phrase, always flagged (repeatable)")
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
