#!/usr/bin/env python3
"""compliance_lint.py - Static lint for local-SEO red flags in a page draft.

Offline, stdlib-only (re, os, argparse). No network calls.

What it checks (each issue carries a line number, severity, and context)
------------------------------------------------------------------------
- MISSING_H1        : no H1 (# ...) in the draft.
- MULTIPLE_H1       : more than one H1.
- MISSING_META_TITLE / MISSING_META_DESC : no meta title / meta description
  line or front-matter key found.
- DUPLICATE_HEADING : the same heading text appears more than once.
- THIN_SECTION      : an H2 block whose body is under --min-section-words
  (default 40) words. Thin sections are a scaled-low-value-content signal.
- KEYWORD_STUFFING  : an exact "[service] [city]" style phrase whose density
  exceeds --max-density (default 2.5%). Over-optimization signal.
- OVER_EXACT_HEADING: the same exact-match keyword phrase used as a heading
  more than twice (near-doorway signal).
- EM_DASH           : a U+2014 character (banned by the workspace hook).
- MISSING_TARGET    : if --keyword given and it never appears in the body.

If knowledge/doctrine/google-compliance-spine.md (or seo-system-spine.md)
exists, a reminder checklist derived from it is printed at the end. This lint
is a fast pre-gate; it does not replace reading the spine.

Doctrine Law 8: this tool never scores or games AI-detection. It surfaces
low-value / over-optimization patterns so a human writes something better.

Severity: ERROR (fails the gate) or WARN (advisory, still fails exit code if
--strict). By default any ERROR sets exit code 1.

Usage
-----
  python compliance_lint.py draft.md
  python compliance_lint.py --keyword "roof repair austin" draft.md
  python compliance_lint.py --root .. --strict draft.md
  python compliance_lint.py --self-test
"""

import argparse
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from keyword_density import analyse as density_analyse  # stdlib-only sibling

EM_DASH = chr(0x2014)  # U+2014, the banned character (built, never a literal)

# G6 meta-length target bands. Title ~50-60 chars, description ~150-160 chars.
# Outside the band is a WARN (weak-but-present), never a hard block on its own.
META_TITLE_MIN = 50
META_TITLE_MAX = 60
META_DESC_MIN = 150
META_DESC_MAX = 160

SPINE_CANDIDATES = [
    os.path.join("knowledge", "doctrine", "google-compliance-spine.md"),
    os.path.join("knowledge", "doctrine", "seo-system-spine.md"),
]

REMINDER_CHECKLIST = [
    "Every claim is a real, sourced or SME-supplied local fact (no invented specifics).",
    "NAP is byte-consistent with the Google Business Profile (run nap_checker.py).",
    "Each H2 is a self-contained, extractable answer (passage-block protocol).",
    "No doorway pattern: this page carries unique local value vs sibling city pages.",
    "E-E-A-T is shown with specifics, not claimed ('licensed since 2004, lic #...').",
    "Meta title + description present, unique, and match the page's one job.",
    "No exact-match keyword stuffing; phrasing reads natural on a read-aloud test.",
    "Schema validates (run schema_validator.py) and reflects the real business.",
]


def split_lines(text):
    return text.splitlines()


def find_headings(lines):
    """Return list of (level, text, lineno) for markdown ATX headings."""
    heads = []
    in_fence = False
    for i, line in enumerate(lines, 1):
        if line.strip().startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        m = re.match(r"^(#{1,6})\s+(.*\S)\s*$", line)
        if m:
            heads.append((len(m.group(1)), m.group(2).strip(), i))
    return heads


def check_headings(lines, issues):
    heads = find_headings(lines)
    h1s = [h for h in heads if h[0] == 1]
    if not h1s:
        issues.append(("ERROR", "MISSING_H1", 0, "no H1 (# ...) found"))
    elif len(h1s) > 1:
        for _, txt, ln in h1s[1:]:
            issues.append(("ERROR", "MULTIPLE_H1", ln,
                           "extra H1: %r (page should have exactly one)" % txt))

    seen = {}
    for level, txt, ln in heads:
        key = txt.lower()
        if key in seen:
            issues.append(("WARN", "DUPLICATE_HEADING", ln,
                           "heading %r repeats (first at line %d)" % (txt, seen[key])))
        else:
            seen[key] = ln
    return heads


def check_meta(text, lines, issues):
    lower = text.lower()
    has_title = bool(re.search(r"meta[\s_-]*title\s*[:=]", lower)) or \
        bool(re.search(r"^\s*title\s*:", lower, re.MULTILINE))
    has_desc = bool(re.search(r"meta[\s_-]*desc(ription)?\s*[:=]", lower)) or \
        bool(re.search(r"^\s*description\s*:", lower, re.MULTILINE))
    if not has_title:
        issues.append(("ERROR", "MISSING_META_TITLE", 0,
                       "no meta title line/front-matter key found"))
    if not has_desc:
        issues.append(("ERROR", "MISSING_META_DESC", 0,
                       "no meta description line/front-matter key found"))


def extract_meta_values(text):
    """Pull the meta title and description values from front-matter or inline
    'meta title:'/'title:' style lines. Returns (title, desc), each str or None.
    First match wins."""
    title = None
    desc = None
    for line in text.splitlines():
        if title is None:
            m = re.match(r"\s*(?:meta[\s_-]*)?title\s*[:=]\s*(.+?)\s*$",
                         line, re.IGNORECASE)
            if m:
                title = m.group(1).strip().strip('"').strip("'")
        if desc is None:
            m = re.match(r"\s*(?:meta[\s_-]*)?desc(?:ription)?\s*[:=]\s*(.+?)\s*$",
                         line, re.IGNORECASE)
            if m:
                desc = m.group(1).strip().strip('"').strip("'")
    return title, desc


def check_meta_length(text, issues):
    """G6: meta title in the ~50-60 char band, description in the ~150-160 band.
    Presence is handled by check_meta; this checks only length when present."""
    title, desc = extract_meta_values(text)
    if title is not None and title:
        n = len(title)
        if n < META_TITLE_MIN or n > META_TITLE_MAX:
            issues.append(("WARN", "META_TITLE_LENGTH", 0,
                           "meta title is %d chars (target %d-%d)"
                           % (n, META_TITLE_MIN, META_TITLE_MAX)))
    if desc is not None and desc:
        n = len(desc)
        if n < META_DESC_MIN or n > META_DESC_MAX:
            issues.append(("WARN", "META_DESC_LENGTH", 0,
                           "meta description is %d chars (target %d-%d)"
                           % (n, META_DESC_MIN, META_DESC_MAX)))


def _digits(s):
    return re.sub(r"\D", "", s or "")


def _iter_typed_nodes(obj):
    """Yield every dict carrying an @type, recursively (incl. @graph)."""
    if isinstance(obj, dict):
        if "@type" in obj:
            yield obj
        for value in obj.values():
            yield from _iter_typed_nodes(value)
    elif isinstance(obj, list):
        for item in obj:
            yield from _iter_typed_nodes(item)


def extract_schema_nap(schema_path):
    """Read the business NAP strings from a schema.json. Picks the first typed
    node that carries a name plus a telephone or address (the business node).
    Returns a dict of the present NAP fields, or {} if none found."""
    with open(schema_path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    for node in _iter_typed_nodes(data):
        if not isinstance(node, dict):
            continue
        name = str(node.get("name", "")).strip()
        phone = str(node.get("telephone", "")).strip()
        addr = node.get("address")
        if not name or not (phone or addr):
            continue
        nap = {}
        if name:
            nap["name"] = name
        if phone:
            nap["telephone"] = phone
        if isinstance(addr, list):
            addr = addr[0] if addr else None
        if isinstance(addr, dict):
            for k in ("streetAddress", "addressLocality",
                      "addressRegion", "postalCode"):
                v = addr.get(k)
                if v is not None and str(v).strip():
                    nap[k] = str(v).strip()
        return nap
    return {}


def check_schema_nap(text, schema_path, issues):
    """G11/E2: schema NAP must be byte-identical to the page copy. When a
    schema.json is supplied, each NAP string is asserted to appear verbatim in
    the draft. A telephone whose digits match but whose display format differs
    is a formatting variant (WARN); anything else missing is a mismatch (ERROR).
    """
    try:
        nap = extract_schema_nap(schema_path)
    except (OSError, ValueError) as exc:
        issues.append(("ERROR", "SCHEMA_READ", 0,
                       "could not read schema NAP from %s: %s"
                       % (schema_path, exc)))
        return
    if not nap:
        issues.append(("WARN", "SCHEMA_NO_NAP", 0,
                       "no LocalBusiness/Organization NAP node found in %s"
                       % schema_path))
        return
    for label, val in nap.items():
        if not val or val in text:
            continue
        if label == "telephone" and _digits(val) and _digits(val) in _digits(text):
            issues.append(("WARN", "SCHEMA_NAP_FORMAT", 0,
                           "schema telephone %r matches digits but is not "
                           "byte-identical in the page copy" % val))
        else:
            issues.append(("ERROR", "SCHEMA_NAP_MISMATCH", 0,
                           "schema %s %r is not byte-identical in the page copy "
                           "(G11/E2)" % (label, val)))


def check_thin_sections(lines, heads, issues, min_words):
    """An H2 block = text from an H2 line until the next H2/H1."""
    h2_positions = [(lvl, txt, ln) for lvl, txt, ln in heads if lvl == 2]
    stops = sorted(ln for lvl, _, ln in heads if lvl in (1, 2))
    for lvl, txt, ln in h2_positions:
        next_stop = next((s for s in stops if s > ln), len(lines) + 1)
        body = " ".join(lines[ln:next_stop - 1])  # lines between headings
        body = re.sub(r"^\s*[-*+#>0-9.]+\s*", " ", body)
        words = re.findall(r"[A-Za-z0-9']+", body)
        if len(words) < min_words:
            issues.append(("WARN", "THIN_SECTION", ln,
                           "H2 %r has only %d words (< %d)" % (txt, len(words), min_words)))


def check_em_dash(lines, issues):
    for i, line in enumerate(lines, 1):
        if EM_DASH in line:
            col = line.index(EM_DASH)
            issues.append(("ERROR", "EM_DASH", i,
                           "em dash (U+2014) at col %d - use a hyphen" % col))


def check_keyword_stuffing(text, keywords, issues, max_density):
    if not keywords:
        return
    result = density_analyse(text, keywords, max_density=max_density)
    for r in result["rows"]:
        if r["over"]:
            issues.append(("ERROR", "KEYWORD_STUFFING", 0,
                           "%r density %.2f%% > %.1f%% (over-optimization)"
                           % (r["keyword"], 100 * r["density"], 100 * max_density)))


def check_target_present(text, keywords, issues):
    low = text.lower()
    for kw in keywords:
        if kw.lower() not in low:
            issues.append(("WARN", "MISSING_TARGET", 0,
                           "target keyword %r never appears in the draft" % kw))


def check_over_exact_headings(heads, keywords, issues):
    if not keywords:
        return
    head_texts = [t.lower() for _, t, _ in heads]
    for kw in keywords:
        n = sum(1 for h in head_texts if kw.lower() in h)
        if n > 2:
            issues.append(("WARN", "OVER_EXACT_HEADING", 0,
                           "%r used in %d headings (near-doorway signal)" % (kw, n)))


def lint(text, keywords=None, min_section_words=40, max_density=0.025,
         schema_path=None):
    keywords = keywords or []
    lines = split_lines(text)
    issues = []
    heads = check_headings(lines, issues)
    check_meta(text, lines, issues)
    check_meta_length(text, issues)
    check_thin_sections(lines, heads, issues, min_section_words)
    check_em_dash(lines, issues)
    check_keyword_stuffing(text, keywords, issues, max_density)
    check_over_exact_headings(heads, keywords, issues)
    check_target_present(text, keywords, issues)
    if schema_path:
        check_schema_nap(text, schema_path, issues)
    return issues


def find_spine(root):
    for rel in SPINE_CANDIDATES:
        cand = os.path.join(root, rel)
        if os.path.exists(cand):
            return cand
    return None


def context_line(lines, lineno):
    if 1 <= lineno <= len(lines):
        return lines[lineno - 1].strip()[:80]
    return ""


def run(args):
    if args.path == "-":
        text = sys.stdin.read()
        src = "<stdin>"
    else:
        with open(args.path, "r", encoding="utf-8") as fh:
            text = fh.read()
        src = args.path

    keywords = list(args.keyword or [])
    if args.keywords:
        keywords += [k.strip() for k in args.keywords.split(",") if k.strip()]

    lines = split_lines(text)
    issues = lint(text, keywords=keywords,
                  min_section_words=args.min_section_words,
                  max_density=args.max_density,
                  schema_path=args.schema)

    print("Compliance lint for %s" % src)
    errors = [i for i in issues if i[0] == "ERROR"]
    warns = [i for i in issues if i[0] == "WARN"]
    print("  %d error(s), %d warning(s)" % (len(errors), len(warns)))
    for sev, code, ln, msg in issues:
        loc = ("line %d" % ln) if ln else "-"
        print("  [%-5s] %-19s %-9s %s" % (sev, code, loc, msg))
        ctx = context_line(lines, ln)
        if ctx:
            print("            > %s" % ctx)

    spine = find_spine(args.root)
    if spine:
        print("")
        print("Reminder checklist (source: %s):" % os.path.relpath(spine, args.root))
        for item in REMINDER_CHECKLIST:
            print("  [ ] %s" % item)

    print("")
    fail = bool(errors) or (args.strict and bool(warns))
    if fail:
        print("FAIL  fix errors%s before this draft passes the gate"
              % (" and warnings" if args.strict else ""))
        return 1
    print("PASS  no blocking issues" + (" (warnings advisory)" if warns else ""))
    return 0


def self_test():
    clean = (
        "---\n"
        "meta_title: Roof Repair in Austin | Acme Roofing\n"
        "meta_description: Same-day roof repair in Austin by a licensed local crew.\n"
        "---\n\n"
        "# Roof Repair in Austin\n\n"
        "Acme Roofing has fixed leaking roofs across Austin since 2004. When a "
        "storm tears off shingles, our licensed crew is on site the same day with "
        "the materials to make it right, and we back every repair with a written "
        "workmanship guarantee that most local shops will not put in writing.\n\n"
        "## What a same-day roof repair actually covers\n\n"
        "A same-day repair means a licensed roofer inspects the damage, seals the "
        "active leak, replaces the affected shingles or flashing, and documents "
        "everything for your insurer. We carry common shingle profiles on the truck "
        "so most repairs finish in a single visit rather than dragging across a week.\n"
    )
    bad = (
        "# Roof Repair Austin\n\n"
        "# Second H1 here\n\n"
        "Roof repair Austin. Roof repair Austin. Roof repair Austin roof repair "
        "Austin roof repair Austin roof repair Austin roof repair Austin.\n\n"
        "## Thin\n\n"
        "Too short.\n\n"
        "## Thin\n\n"
        "Also short " + EM_DASH + " and has an em dash.\n"
    )
    clean_issues = lint(clean, keywords=["roof repair austin"])
    clean_errors = [i for i in clean_issues if i[0] == "ERROR"]
    bad_issues = lint(bad, keywords=["roof repair austin"])
    bad_codes = {c for _, c, _, _ in bad_issues}

    assert not clean_errors, "clean draft should have no errors: %s" % clean_errors
    for expected in ("MULTIPLE_H1", "KEYWORD_STUFFING", "EM_DASH",
                     "MISSING_META_TITLE", "THIN_SECTION", "DUPLICATE_HEADING"):
        assert expected in bad_codes, "expected %s in bad draft, got %s" % (
            expected, bad_codes)

    # --- meta length (G6) ---
    short_meta = ("---\nmeta_title: Roof\nmeta_description: Too short.\n---\n\n"
                  "# Roof Repair\n\nBody copy here.\n")
    short_codes = {c for _, c, _, _ in lint(short_meta)}
    assert "META_TITLE_LENGTH" in short_codes, short_codes
    assert "META_DESC_LENGTH" in short_codes, short_codes

    good_title = "Emergency Roof Repair in Austin TX by Acme Roofing Team"  # 55
    good_desc = ("Same-day roof repair in Austin by a licensed local crew. "
                 * 4)[:155]
    good_meta = ("---\nmeta_title: %s\nmeta_description: %s\n---\n\n"
                 "# Roof Repair in Austin\n\n"
                 "Acme Roofing has served Austin homeowners since 2004 with a "
                 "licensed crew and written guarantees on every repair job that "
                 "most local shops will not put in writing.\n"
                 % (good_title, good_desc))
    good_meta_codes = {c for _, c, _, _ in lint(good_meta)}
    assert "META_TITLE_LENGTH" not in good_meta_codes, good_meta_codes
    assert "META_DESC_LENGTH" not in good_meta_codes, good_meta_codes

    # --- schema-NAP byte identity (G11/E2) ---
    import tempfile
    schema = {"@context": "https://schema.org", "@type": "Plumber",
              "name": "Acme Roofing", "telephone": "+1-512-555-0100",
              "address": {"@type": "PostalAddress",
                          "streetAddress": "100 Congress Ave",
                          "addressLocality": "Austin", "addressRegion": "TX",
                          "postalCode": "78701", "addressCountry": "US"}}
    d = tempfile.mkdtemp()
    sp = os.path.join(d, "schema.json")
    with open(sp, "w", encoding="utf-8") as fh:
        json.dump(schema, fh)
    page_match = ("Acme Roofing, 100 Congress Ave, Austin, TX 78701. "
                  "Call +1-512-555-0100 today.")
    page_bad = "Acme Roofing of Round Rock. Call us at (512) 555 0100."
    match_codes = {c for _, c, _, _ in lint(page_match, schema_path=sp)}
    bad_nap_codes = {c for _, c, _, _ in lint(page_bad, schema_path=sp)}
    assert "SCHEMA_NAP_MISMATCH" not in match_codes, match_codes
    assert "SCHEMA_NAP_MISMATCH" in bad_nap_codes, bad_nap_codes

    print("self-test OK")
    print("  clean draft: %d issues, 0 errors" % len(clean_issues))
    print("  bad draft:   %d issues, codes: %s"
          % (len(bad_issues), ", ".join(sorted(bad_codes))))
    print("  meta-length: short flags %s"
          % ", ".join(sorted(c for c in short_codes if c.startswith("META_"))))
    print("  schema-NAP:  mismatch caught on divergent page")
    return 0


def build_parser():
    p = argparse.ArgumentParser(
        description="Static lint for local-SEO red flags in a page draft.",
    )
    p.add_argument("path", nargs="?", default="-",
                   help="path to a markdown/text draft, or '-' for stdin")
    p.add_argument("--keyword", action="append",
                   help="target keyword to check stuffing/presence (repeatable)")
    p.add_argument("--keywords", help="comma-separated target keywords")
    p.add_argument("--min-section-words", type=int, default=40,
                   help="H2 body under this many words is thin (default 40)")
    p.add_argument("--max-density", type=float, default=0.025,
                   help="keyword-stuffing density threshold (default 0.025)")
    p.add_argument("--schema",
                   help="path to schema.json; cross-checks its NAP strings are "
                        "byte-identical to the page copy (G11/E2)")
    p.add_argument("--root", default=".",
                   help="workspace root, used to find the compliance spine (default .)")
    p.add_argument("--strict", action="store_true",
                   help="treat warnings as failures too")
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
