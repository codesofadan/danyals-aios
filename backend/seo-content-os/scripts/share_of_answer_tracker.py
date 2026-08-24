#!/usr/bin/env python3
"""share_of_answer_tracker.py - Measure AI-answer citation share, per engine.

Offline, stdlib-only (csv, argparse, io, os, sys). No network calls, no scraping.

This closes the loop that doctrine Law 13 and Truth 10 open: the system writes
for extraction, then this measures whether extraction happened. It reads a frozen
money-query prompt set and a manually-logged results CSV (you query each engine's
consumer UI by hand and record the outcome), then computes citation share, mention
rate, and per-query presence PER ENGINE, with a cycle-over-cycle diff, and prints a
one-page report naming the single biggest gap and the page fix.

Why per engine, always: the engines disagree wildly. SOCi's 2026 index put location
visibility at 7.4% on Perplexity vs 1.2% on ChatGPT; blending them produces fiction.
Citation share is only comparable across periods if the prompt set is frozen: change
the prompts and you changed the denominator, and the trend line is a lie.

Results CSV
-----------
Header row required. Columns are matched by name (case-insensitive), flexible order:
  query        (aka prompt, money_query)          REQUIRED
  engine       (aka platform)                      REQUIRED
  cited        (aka cited_yes_no, citation)        REQUIRED  yes/no/y/n/1/0/true/false
  mentioned    (aka mention)                       optional  (unlinked brand mention)
  cycle        (aka period, month)                 optional  (else derived from date, else "all")
  date         (aka logged_date)                   optional  YYYY-MM-DD (used to derive cycle)
  run          (aka run_no, run#)                  optional  (repeated-run number)
  competitors  (aka competitors_cited)             optional  ; or , separated
  position     (aka rank, notes)                   optional  free text, carried as a note

A citation counts as a mention. Run each prompt 3-5x per engine and log every run:
AI answers are non-deterministic, so citation FREQUENCY across runs is the signal,
not a single yes/no.

Exit code 0 = report generated, 1 = data / file error.

Usage
-----
  python share_of_answer_tracker.py results.csv
  python share_of_answer_tracker.py --prompt-set money-queries.md results.csv
  python share_of_answer_tracker.py --self-test
"""

import argparse
import csv
import io
import os
import sys

TRUE_TOKENS = {"yes", "y", "1", "true", "cited", "t", "present"}
FALSE_TOKENS = {"no", "n", "0", "false", "absent", "f", "", "-"}

COLUMN_ALIASES = {
    "query": ["query", "prompt", "money_query", "money query"],
    "engine": ["engine", "platform", "ai_engine"],
    "cited": ["cited", "cited_yes_no", "cited_y_n", "citation", "cited?"],
    "mentioned": ["mentioned", "mention", "mentioned_yes_no"],
    "cycle": ["cycle", "period", "month"],
    "date": ["date", "logged_date", "run_date"],
    "run": ["run", "run_no", "run#", "run_number"],
    "competitors": ["competitors", "competitors_cited", "competitor"],
    "position": ["position", "rank", "notes", "note", "position_notes"],
}


def truthy(value):
    v = (value or "").strip().lower()
    if v in TRUE_TOKENS:
        return True
    if v in FALSE_TOKENS:
        return False
    return False


def resolve_columns(header):
    lower = [h.strip().lower() for h in header]
    mapping = {}
    for canon, aliases in COLUMN_ALIASES.items():
        for i, h in enumerate(lower):
            if h in aliases:
                mapping[canon] = i
                break
    return mapping


def parse_prompt_set(text):
    """One money query per line. Skips headings, blank lines, and # comments;
    strips markdown list bullets and numbering."""
    queries = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        # strip bullets / numbering / blockquote marks
        line = line.lstrip("-*+> ").strip()
        line = _strip_leading_number(line)
        if line:
            queries.append(line)
    # dedupe, keep order
    return list(dict.fromkeys(queries))


def _strip_leading_number(line):
    i = 0
    while i < len(line) and line[i].isdigit():
        i += 1
    if i > 0 and i < len(line) and line[i] in ".)":
        return line[i + 1:].strip()
    return line


def parse_results(text):
    reader = csv.reader(io.StringIO(text))
    rows = list(reader)
    if not rows:
        raise ValueError("results CSV is empty")
    header = rows[0]
    cols = resolve_columns(header)
    for required in ("query", "engine", "cited"):
        if required not in cols:
            raise ValueError("results CSV missing required column: %s "
                             "(header was: %s)" % (required, ", ".join(header)))
    out = []
    for r in rows[1:]:
        if not any(cell.strip() for cell in r):
            continue

        def get(name):
            idx = cols.get(name)
            if idx is None or idx >= len(r):
                return ""
            return r[idx].strip()

        query = get("query")
        engine = get("engine")
        if not query or not engine:
            continue
        cycle = get("cycle")
        if not cycle:
            date = get("date")
            cycle = date[:7] if len(date) >= 7 else "all"
        cited = truthy(get("cited"))
        mentioned_raw = get("mentioned")
        mentioned = cited or truthy(mentioned_raw)
        comp = get("competitors")
        competitors = [c.strip() for c in comp.replace(";", ",").split(",")
                       if c.strip()]
        out.append({
            "query": query,
            "engine": engine,
            "cycle": cycle,
            "cited": cited,
            "mentioned": mentioned,
            "competitors": competitors,
            "note": get("position"),
        })
    return out


def _metrics_for(rows):
    """rows: a list for one (cycle, engine). Returns metric dict."""
    n = len(rows)
    cited = sum(1 for r in rows if r["cited"])
    mentioned = sum(1 for r in rows if r["mentioned"])
    queries = {}
    for r in rows:
        q = queries.setdefault(r["query"], {"n": 0, "cited": 0})
        q["n"] += 1
        if r["cited"]:
            q["cited"] += 1
    n_q = max(1, len(queries))
    cited_q = sum(1 for q in queries.values() if q["cited"] > 0)
    return {
        "runs": n,
        "cited": cited,
        "citation_share": cited / max(1, n),
        "mention_rate": mentioned / max(1, n),
        "queries": len(queries),
        "query_presence": cited_q / n_q,
        "per_query": queries,
    }


def compute(rows):
    cycles = sorted({r["cycle"] for r in rows})
    engines = sorted({r["engine"] for r in rows})
    table = {}  # (cycle, engine) -> metrics
    for c in cycles:
        for e in engines:
            sub = [r for r in rows if r["cycle"] == c and r["engine"] == e]
            if sub:
                table[(c, e)] = _metrics_for(sub)
    return {"cycles": cycles, "engines": engines, "table": table}


def competitor_tally(rows, cycle):
    tally = {}
    for r in rows:
        if r["cycle"] != cycle:
            continue
        for c in r["competitors"]:
            tally[c] = tally.get(c, 0) + 1
    return sorted(tally.items(), key=lambda kv: -kv[1])


def find_biggest_gap(computed, rows, latest):
    """Lowest-citation-share engine in the latest cycle, plus the money query it
    is most absent from."""
    engines = [e for e in computed["engines"]
               if (latest, e) in computed["table"]]
    if not engines:
        return None
    worst_engine = min(
        engines,
        key=lambda e: (computed["table"][(latest, e)]["citation_share"],
                       computed["table"][(latest, e)]["query_presence"]))
    m = computed["table"][(latest, worst_engine)]
    # the query with the most absent runs in that engine/cycle
    worst_query = None
    worst_absent = -1
    for q, qm in m["per_query"].items():
        absent = qm["n"] - qm["cited"]
        if absent > worst_absent or (absent == worst_absent and qm["cited"] == 0):
            worst_absent = absent
            worst_query = q
    return {
        "engine": worst_engine,
        "citation_share": m["citation_share"],
        "query": worst_query,
        "absent_runs": worst_absent,
    }


def pct(x):
    return "%.0f%%" % (100 * x)


def build_report(computed, rows, prompt_set, min_runs=15):
    lines = []
    cycles = computed["cycles"]
    latest = cycles[-1] if cycles else None
    prior = cycles[-2] if len(cycles) >= 2 else None

    lines.append("SHARE OF ANSWER - one-page report")
    lines.append("=" * 52)
    if prompt_set:
        logged_qs = {r["query"] for r in rows}
        missing = [q for q in prompt_set if q not in logged_qs]
        lines.append("Frozen prompt set: %d money queries" % len(prompt_set))
        if missing:
            lines.append("  WARNING: %d frozen queries never logged (denominator "
                         "drift risk):" % len(missing))
            for q in missing[:5]:
                lines.append("    - %s" % q)
    lines.append("Cycles found: %s" % (", ".join(cycles) if cycles else "none"))
    lines.append("Latest cycle: %s%s"
                 % (latest, "   prior: %s" % prior if prior else "   (baseline, no prior)"))
    lines.append("")

    lines.append("PER-ENGINE citation share, latest cycle (%s):" % latest)
    lines.append("  %-14s %6s %8s %8s %9s %8s"
                 % ("engine", "runs", "cite%", "mention%", "qpresent", "vs prior"))
    for e in computed["engines"]:
        key = (latest, e)
        if key not in computed["table"]:
            continue
        m = computed["table"][key]
        delta = ""
        if prior and (prior, e) in computed["table"]:
            d = m["citation_share"] - computed["table"][(prior, e)]["citation_share"]
            delta = "%+.0fpp" % (100 * d)
        elif prior:
            delta = "new"
        warn = "  (low-n)" if m["runs"] < min_runs else ""
        lines.append("  %-14s %6d %8s %8s %9s %8s%s"
                     % (e[:14], m["runs"], pct(m["citation_share"]),
                        pct(m["mention_rate"]), pct(m["query_presence"]),
                        delta, warn))
    lines.append("")

    comps = competitor_tally(rows, latest)
    if comps:
        top = ", ".join("%s (%d)" % (c, n) for c, n in comps[:3])
        lines.append("Most co-cited competitors this cycle: %s" % top)
        lines.append("")

    gap = find_biggest_gap(computed, rows, latest)
    lines.append("BIGGEST GAP")
    lines.append("-" * 52)
    if gap:
        lines.append("Weakest engine: %s at %s citation share."
                     % (gap["engine"], pct(gap["citation_share"])))
        if gap["query"]:
            lines.append('Most-absent money query there: "%s" (%d absent run(s)).'
                         % (gap["query"], gap["absent_runs"]))
        lines.append("Page fix: map that query to a direct-answer passage block "
                     "(passage-block-protocol.md), inject a sourced statistic and "
                     "an operator quote (Law 17), then re-measure next cycle.")
        lines.append("If the page already answers it well, the block is off-page: "
                     "check GBP completeness + entity corroboration for %s "
                     "(geo-ai-citation.md Track B)." % gap["engine"])
    else:
        lines.append("No engine data in the latest cycle.")
    lines.append("")
    lines.append("Note: AI answers are non-deterministic. Trust the trend across "
                 "repeated runs, not any single row. Overlapping cycles = no "
                 "measurable trend yet.")
    return "\n".join(lines)


def run(args):
    prompt_set = []
    if args.prompt_set:
        with open(args.prompt_set, "r", encoding="utf-8") as fh:
            prompt_set = parse_prompt_set(fh.read())
    if args.results == "-":
        text = sys.stdin.read()
    else:
        with open(args.results, "r", encoding="utf-8") as fh:
            text = fh.read()
    rows = parse_results(text)
    if not rows:
        print("error: no usable result rows in %s" % args.results, file=sys.stderr)
        return 1
    computed = compute(rows)
    print(build_report(computed, rows, prompt_set, min_runs=args.min_runs))
    return 0


SAMPLE_PROMPT_SET = """# Frozen money-query set - Acme Plumbing (Tempe)
## discovery
- best emergency plumber in Tempe
- water heater replacement Tempe
## comparison
- top 3 plumbers in Tempe
## problem
- water heater leaking who to call in Tempe
"""

SAMPLE_RESULTS = """query,engine,cycle,run,cited,mentioned,competitors,position
best emergency plumber in Tempe,ChatGPT,2026-06,1,no,no,BigCo Plumbing,
best emergency plumber in Tempe,ChatGPT,2026-06,2,no,yes,BigCo Plumbing,
best emergency plumber in Tempe,Perplexity,2026-06,1,yes,yes,BigCo Plumbing,pos2
water heater replacement Tempe,Perplexity,2026-06,1,yes,yes,,pos1
water heater replacement Tempe,ChatGPT,2026-06,1,no,no,BigCo Plumbing,
best emergency plumber in Tempe,ChatGPT,2026-07,1,yes,yes,BigCo Plumbing,pos3
best emergency plumber in Tempe,ChatGPT,2026-07,2,no,yes,,
best emergency plumber in Tempe,Perplexity,2026-07,1,yes,yes,BigCo Plumbing,pos1
water heater replacement Tempe,Perplexity,2026-07,1,yes,yes,,pos1
water heater replacement Tempe,ChatGPT,2026-07,1,no,no,BigCo Plumbing,
"""


def self_test():
    prompt_set = parse_prompt_set(SAMPLE_PROMPT_SET)
    assert len(prompt_set) == 4, prompt_set
    assert "best emergency plumber in Tempe" in prompt_set

    rows = parse_results(SAMPLE_RESULTS)
    assert len(rows) == 10, len(rows)
    # mentioned is implied by cited
    cited_rows = [r for r in rows if r["cited"]]
    assert all(r["mentioned"] for r in cited_rows), "citation implies mention"

    computed = compute(rows)
    assert computed["cycles"] == ["2026-06", "2026-07"], computed["cycles"]

    # ChatGPT 2026-07: 3 runs, 1 cited -> 33% citation share
    m_c = computed["table"][("2026-07", "ChatGPT")]
    assert m_c["runs"] == 3, m_c["runs"]
    assert abs(m_c["citation_share"] - 1 / 3) < 1e-9, m_c["citation_share"]
    # Perplexity 2026-07: 2 runs, both cited -> 100%
    m_p = computed["table"][("2026-07", "Perplexity")]
    assert abs(m_p["citation_share"] - 1.0) < 1e-9, m_p["citation_share"]

    # biggest gap is ChatGPT (lower share)
    gap = find_biggest_gap(computed, rows, "2026-07")
    assert gap["engine"] == "ChatGPT", gap
    assert gap["query"] is not None

    # cycle-over-cycle diff: ChatGPT went 0% (2026-06: 0/2) -> 33% (2026-07)
    m_c_prior = computed["table"][("2026-06", "ChatGPT")]
    assert m_c_prior["citation_share"] == 0.0, m_c_prior["citation_share"]

    report = build_report(computed, rows, prompt_set)
    assert "BIGGEST GAP" in report
    assert "ChatGPT" in report

    print("self-test OK")
    print("  parsed %d rows across cycles %s"
          % (len(rows), ", ".join(computed["cycles"])))
    print("  2026-07 ChatGPT citation share %s (was %s in 2026-06)"
          % (pct(m_c["citation_share"]), pct(m_c_prior["citation_share"])))
    print("  2026-07 Perplexity citation share %s" % pct(m_p["citation_share"]))
    print("  biggest gap: %s" % gap["engine"])
    return 0


def build_parser():
    p = argparse.ArgumentParser(
        description="Compute AI-answer citation share per engine, cycle over cycle.",
    )
    p.add_argument("results", nargs="?", default="-",
                   help="path to the manually-logged results CSV, or '-' for stdin")
    p.add_argument("--prompt-set",
                   help="path to the frozen money-query prompt set (md/txt)")
    p.add_argument("--min-runs", type=int, default=15,
                   help="flag an engine cycle with fewer runs as low-sample "
                        "(default 15)")
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
