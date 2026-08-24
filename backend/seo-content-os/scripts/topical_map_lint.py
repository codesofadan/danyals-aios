#!/usr/bin/env python3
"""topical_map_lint.py - Enforce the topical map's evidence gate deterministically.

Offline, stdlib-only (argparse, re, sys). No network calls.

Operationalizes the promotion gate in knowledge/foundations/topical-map-protocol.md.
The map's whole discipline is that a node becomes a full PAGE only when it carries a
real first-party specific that makes that page un-copyable. That rule was previously
prose the map-building agent was trusted to obey, with no check. This script is the
check.

IMPORTANT - what this is NOT: it is not a "topical authority score" and not a coverage
or completeness percentage. Trap #2 in the protocol forbids scoring the map. This
script scores nothing. It checks PRESENCE: every node marked `status: page` must have a
non-placeholder `evidence` line and a non-placeholder `info_gain_thesis`. That is an
evidence-presence linter, which the protocol explicitly allows.

What it checks
--------------
1. INTEGRITY
   - `Map mode:` is present and is `lite` or `full`.
   - every node's status resolves to `index-only` or `page` (nothing else).
   - no duplicate node_ids.
   - every `page`-status row in the node table has a matching per-node detail block
     (a page node with no detail/evidence block is an unbacked promotion).
2. THE EVIDENCE GATE (the hard rule)
   - for every node with `status: page`: FAIL if `evidence` is empty or a placeholder,
     or if `info_gain_thesis` is empty or a placeholder. `index-only` nodes are exempt
     (they are, by definition, coverage the site has not yet spent a page on).
3. GROUNDING (soft, only with --manifest brand.yaml)
   - WARN if a page node's evidence string shares no meaningful token with brand.yaml
     (a signal the evidence may be invented rather than drawn from real client facts).
     This mirrors the spirit of experience_gate.py --manifest, but as a warning, not a
     hard fail, to avoid false positives on legitimately-phrased evidence.

Usage
-----
  python topical_map_lint.py clients/<slug>/topical-map.md
  python topical_map_lint.py clients/<slug>/topical-map.md --manifest clients/<slug>/brand.yaml
  python topical_map_lint.py --self-test

Exit code: 0 = every page node has present evidence + thesis and no integrity errors,
1 = at least one ERROR (unbacked promotion or integrity failure).
"""

import argparse
import re
import sys

# A value counts as empty/placeholder (not real content) if, once stripped of any
# surrounding template markup, it is blank or one of these stand-ins.
PLACEHOLDER_TOKENS = {
    "", "-", "--", "tbd", "n/a", "na", "none", "todo", "...", "xxx", "?",
    "index-only | page", "core | outer", "planned | briefed | drafted | published",
}

# Template angle-bracket placeholder like <the un-copyable specific ...>
ANGLE_PLACEHOLDER_RE = re.compile(r"^<[^>]*>$")

# Capture to end-of-line only ([ \t]* not \s*, so an empty field does not bleed into
# the next line and mask a missing value).
STATUS_RE = re.compile(r"\*\*Status:\*\*[ \t]*(.*)", re.I)
EVIDENCE_RE = re.compile(r"\*\*Evidence[^:*]*:\*\*[ \t]*(.*)", re.I)
THESIS_RE = re.compile(r"\*\*Info-gain thesis:\*\*[ \t]*(.*)", re.I)
SECTION_RE = re.compile(r"\*\*Section:\*\*[ \t]*(.*)", re.I)
MODE_RE = re.compile(r"\*\*Map mode:\*\*[ \t]*(.*)", re.I)


def is_placeholder(value):
    """True if a field value is blank, a stop-word placeholder, or angle-bracket text."""
    if value is None:
        return True
    v = value.strip().strip("`").strip()
    # strip a trailing parenthetical hint like "(page only if evidence is real)"
    v_core = re.sub(r"\s*\(.*\)\s*$", "", v).strip()
    if v_core == "" or v_core.lower() in PLACEHOLDER_TOKENS:
        return True
    if ANGLE_PLACEHOLDER_RE.match(v_core):
        return True
    # a value that is ONLY angle-bracket placeholders (possibly with "and"/commas)
    if re.fullmatch(r"(<[^>]*>[\s,;/]*)+", v_core):
        return True
    return False


def normalize_status(raw):
    """Map a free-text status cell to index-only | page | unknown."""
    if raw is None:
        return "unknown"
    s = raw.lower()
    # placeholder like "<index-only | page>" -> treat as unknown, not a real status
    if is_placeholder(raw):
        return "unknown"
    if "index-only" in s or "index only" in s:
        return "index-only"
    if "page" in s:
        return "page"
    return "unknown"


def parse_table(text):
    """Parse the node table. Return {node_id: status} for rows that name a node.

    Looks for a markdown table whose header row contains 'node_id' and 'status'.
    """
    rows = {}
    lines = text.splitlines()
    header_idx = None
    cols = None
    for i, line in enumerate(lines):
        if line.strip().startswith("|") and "node_id" in line.lower() and "status" in line.lower():
            cols = [c.strip().lower() for c in line.strip().strip("|").split("|")]
            header_idx = i
            break
    if header_idx is None:
        return rows
    try:
        id_col = next(j for j, c in enumerate(cols) if "node_id" in c)
        status_col = next(j for j, c in enumerate(cols) if "status" in c)
    except StopIteration:
        return rows
    # data rows start after the separator row (the |---|---| line)
    for line in lines[header_idx + 1:]:
        s = line.strip()
        if not s.startswith("|"):
            break
        if set(s) <= set("|-: "):  # separator row
            continue
        cells = [c.strip().strip("`").strip() for c in s.strip("|").split("|")]
        if len(cells) <= max(id_col, status_col):
            continue
        node_id = cells[id_col].strip("<>").strip()
        if not node_id or is_placeholder(node_id) or node_id.lower() == "node_id":
            continue
        rows[node_id] = normalize_status(cells[status_col])
    return rows


def parse_detail_blocks(text):
    """Parse the per-node '### <id>' detail blocks.

    Return {node_id: {status, evidence, thesis, section}} using the bold-label lines.
    """
    blocks = {}
    # isolate the "## Per-node detail" section if present, else scan whole file
    detail = text
    m = re.search(r"^##\s+Per-node detail\b", text, re.M)
    if m:
        detail = text[m.end():]
    # split on level-3 headers
    parts = re.split(r"^###\s+", detail, flags=re.M)
    for part in parts[1:]:
        lines = part.splitlines()
        if not lines:
            continue
        node_id = lines[0].strip().strip("`<>").strip()
        if not node_id or is_placeholder(node_id):
            continue
        body = "\n".join(lines[1:])
        rec = {"status_raw": None, "evidence": None, "thesis": None, "section": None}
        ms = STATUS_RE.search(body)
        if ms:
            rec["status_raw"] = ms.group(1).strip()
        me = EVIDENCE_RE.search(body)
        if me:
            rec["evidence"] = me.group(1).strip()
        mt = THESIS_RE.search(body)
        if mt:
            rec["thesis"] = mt.group(1).strip()
        msec = SECTION_RE.search(body)
        if msec:
            rec["section"] = msec.group(1).strip()
        blocks[node_id] = rec
    return blocks


def meaningful_tokens(s):
    return {t for t in re.findall(r"[a-z0-9]{4,}", (s or "").lower())}


def evaluate(text, manifest_text=None):
    issues = []
    mode_m = MODE_RE.search(text)
    mode = mode_m.group(1).strip().split()[0].strip("`").lower() if mode_m else None
    if mode not in ("lite", "full"):
        issues.append(("ERROR", "MAP_MODE_MISSING", 0,
                       "map header has no valid `Map mode:` (expected `lite` or `full`)"))

    table = parse_table(text)
    blocks = parse_detail_blocks(text)

    # duplicate node ids in the table are caught by dict collapse; detect via raw scan
    # (a light check: count '### <id>' occurrences)
    detail_ids = re.findall(r"^###\s+`?<?([A-Za-z0-9][A-Za-z0-9 _-]*?)`?>?\s*$", text, re.M)
    seen = set()
    for nid in detail_ids:
        nid = nid.strip()
        if is_placeholder(nid):
            continue
        if nid in seen:
            issues.append(("ERROR", "DUPLICATE_NODE", 0, "duplicate node detail block: %r" % nid))
        seen.add(nid)

    manifest_tokens = meaningful_tokens(manifest_text) if manifest_text else None

    # unify the node set: prefer detail-block status, fall back to table status
    all_ids = set(table) | set(blocks)
    page_nodes = 0
    index_nodes = 0
    checked = 0
    for nid in sorted(all_ids):
        blk = blocks.get(nid)
        table_status = table.get(nid)
        detail_status = normalize_status(blk["status_raw"]) if blk else None
        status = detail_status if detail_status and detail_status != "unknown" else table_status

        if status == "page":
            page_nodes += 1
        elif status == "index-only":
            index_nodes += 1

        if status != "page":
            continue  # only page nodes are gated
        checked += 1

        # a page node MUST have a detail block with real evidence + thesis
        if blk is None:
            issues.append(("ERROR", "PAGE_NO_DETAIL", 0,
                           "node %r is status:page in the table but has no per-node "
                           "detail block (no evidence recorded)" % nid))
            continue
        if is_placeholder(blk["evidence"]):
            issues.append(("ERROR", "UNBACKED_PROMOTION", 0,
                           "node %r is status:page with no real `evidence` "
                           "(empty/placeholder): demote to index-only or supply a "
                           "first-party specific" % nid))
        elif manifest_tokens is not None:
            ev_tokens = meaningful_tokens(blk["evidence"])
            if ev_tokens and not (ev_tokens & manifest_tokens):
                issues.append(("WARN", "EVIDENCE_UNGROUNDED", 0,
                               "node %r evidence shares no token with brand.yaml; "
                               "verify it is a real client fact, not invented" % nid))
        if is_placeholder(blk["thesis"]):
            issues.append(("ERROR", "MISSING_THESIS", 0,
                           "node %r is status:page with no real `info_gain_thesis` "
                           "(empty/placeholder): name the net-new fact this page adds, "
                           "or demote to index-only" % nid))

    return {
        "mode": mode,
        "page_nodes": page_nodes,
        "index_nodes": index_nodes,
        "checked": checked,
        "issues": issues,
    }


def run(args):
    with open(args.path, "r", encoding="utf-8") as fh:
        text = fh.read()
    manifest_text = None
    if args.manifest:
        with open(args.manifest, "r", encoding="utf-8") as fh:
            manifest_text = fh.read()

    result = evaluate(text, manifest_text)
    print("Topical map lint for %s" % args.path)
    print("  map mode: %s" % (result["mode"] or "(missing)"))
    print("  nodes: %d page, %d index-only  (page nodes gated: %d)"
          % (result["page_nodes"], result["index_nodes"], result["checked"]))
    if args.manifest:
        print("  grounding manifest: %s" % args.manifest)
    print("")

    errors = [i for i in result["issues"] if i[0] == "ERROR"]
    for sev, code, ln, msg in result["issues"]:
        print("  [%-5s] %-20s %s" % (sev, code, msg))
    print("")

    if errors:
        print("FAIL  %d evidence-gate/integrity error(s). Every status:page node must"
              % len(errors))
        print("      carry a real, non-placeholder `evidence` line and `info_gain_thesis`.")
        print("      Demote unbacked nodes to index-only or supply the first-party fact.")
        return 1
    print("PASS  every status:page node has present evidence and an info-gain thesis")
    return 0


def self_test():
    good = (
        "# Topical Map - Test\n\n"
        "## Entity anchor\n- **Map mode:** lite\n\n"
        "## Node table\n"
        "| node_id | entity / attribute | section | status | priority | command |\n"
        "|---|---|---|---|---|---|\n"
        "| implants-hub | biz + dental implants | core | page | 1 | /write-service-page |\n"
        "| implants-brentwood | biz + implants Brentwood | core | index-only | - | /write-service-city-page |\n\n"
        "## Per-node detail\n\n"
        "### implants-hub\n"
        "- **Section:** core\n"
        "- **Evidence (the promotion gate):** 6,000+ implants placed since 2009; in-house "
        "board-certified periodontist and prosthodontist; CBCT guided surgery at all offices\n"
        "- **Info-gain thesis:** the periodontist who places and the prosthodontist who "
        "restores are one in-house team, not a referral chain\n"
        "- **Status:** page\n\n"
        "### implants-brentwood\n"
        "- **Section:** core\n"
        "- **Evidence (the promotion gate):** <none yet - no job documented in Brentwood>\n"
        "- **Info-gain thesis:** <tbd>\n"
        "- **Status:** index-only\n"
    )
    good_manifest = (
        "services: [dental implants]\n"
        "eeat:\n  proof:\n    - 6,000+ implants placed since 2009\n"
        "  credentials:\n    - in-house board-certified periodontist and prosthodontist\n"
    )
    bad = (
        "# Topical Map - Test\n\n"
        "## Entity anchor\n- **Map mode:** lite\n\n"
        "## Node table\n"
        "| node_id | entity / attribute | section | status | priority | command |\n"
        "|---|---|---|---|---|---|\n"
        "| whitening-glendale | biz + whitening Glendale | core | page | 2 | /write-service-city-page |\n"
        "| veneers-pasadena | biz + veneers Pasadena | core | page | 3 | /write-service-city-page |\n\n"
        "## Per-node detail\n\n"
        "### whitening-glendale\n"
        "- **Section:** core\n"
        "- **Evidence (the promotion gate):** \n"
        "- **Info-gain thesis:** teeth whitening in Glendale\n"
        "- **Status:** page\n"
    )

    r_good = evaluate(good, good_manifest)
    r_bad = evaluate(bad, None)

    good_errors = [i for i in r_good["issues"] if i[0] == "ERROR"]
    assert not good_errors, "good map should pass, got: %s" % good_errors
    assert r_good["page_nodes"] == 1 and r_good["index_nodes"] == 1, \
        "good map node counts wrong: %s" % r_good

    bad_codes = [c for s, c, _, _ in r_bad["issues"] if s == "ERROR"]
    assert "UNBACKED_PROMOTION" in bad_codes, \
        "empty-evidence page node must be flagged: %s" % bad_codes
    assert "PAGE_NO_DETAIL" in bad_codes, \
        "page row with no detail block must be flagged: %s" % bad_codes

    print("self-test OK")
    print("  good map: %d page / %d index-only, 0 errors (PASS)"
          % (r_good["page_nodes"], r_good["index_nodes"]))
    print("  bad  map: %d error(s) incl. %s (FAIL)"
          % (len([i for i in r_bad["issues"] if i[0] == "ERROR"]), sorted(set(bad_codes))))
    return 0


def build_parser():
    p = argparse.ArgumentParser(
        description="Enforce the topical map evidence gate (presence, not a score).",
    )
    p.add_argument("path", nargs="?", help="path to clients/<slug>/topical-map.md")
    p.add_argument("--manifest", "--brand",
                   help="optional brand.yaml to soft-check evidence grounding")
    p.add_argument("--self-test", action="store_true",
                   help="run the built-in self-test and exit")
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    if args.self_test:
        return self_test()
    if not args.path:
        build_parser().error("path to topical-map.md is required (or use --self-test)")
    return run(args)


if __name__ == "__main__":
    sys.exit(main())
