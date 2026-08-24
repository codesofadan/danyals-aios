#!/usr/bin/env python3
"""decay_monitor.py - content-decay detector and ranked refresh queue.

Offline, stdlib-only (argparse, csv, sys, os). No network calls. The human
exports two Google Search Console performance CSVs (a current 28-day window and
the prior 28-day window, same property and filters), drops them in, and this
tool joins them on the page/query key and applies the decay flag rules to build
a ranked refresh queue.

Operationalizes doctrine Law 6 (measure or you are guessing) and workspace
Law 18 (a page is not shipped, it is enrolled). Flag thresholds are the Click
Laboratory local-SEO decay workflow defaults (research file 06, Part 3).

The three decay flags (the decision-gate signals)
-------------------------------------------------
- clicks down      : clicks dropped by >= --clicks-drop percent (default 20)
- impressions down : impressions dropped by >= --impr-drop percent (default 15)
- position down    : average position worsened by >= --pos-drop points
                     (default 2.0; larger position number = lower rank)

Decision gate (by flag count)
-----------------------------
  0 flags -> ok        (no action)
  1 flag  -> watch     (note it, recheck next period)
  2 flags -> diagnose  (investigate why this month)
  3 flags -> refresh   (schedule a refresh slot)

Local GSC data is noisy: confirm a 2-consecutive-period signal before you spend
a refresh slot on a low-volume page. This tool flags a single period; the
operator confirms persistence.

CSV format
----------
Any Search Console "Pages" or "Queries" performance export. Column names are
detected case-insensitively: a key column (Page / URL / Landing page / Query)
plus Clicks, Impressions, CTR, Position. CTR like "3.2%" and numbers with
commas are parsed. Pages present in only one window are reported as new / lost.

Exit codes
----------
  0  no page reached the refresh gate (3 flags)
  1  one or more pages reached the refresh gate (a refresh slot is warranted)
  2  usage error (argparse)

Usage
-----
  python decay_monitor.py --current this28.csv --prior last28.csv
  python decay_monitor.py --current c.csv --prior p.csv --clicks-drop 25
  python decay_monitor.py --self-test
"""

import argparse
import csv
import os
import sys

KEY_CANDS = ["page", "url", "landing page", "address", "query", "top queries"]
CLICKS_CANDS = ["clicks", "click"]
IMPR_CANDS = ["impressions", "impr"]
CTR_CANDS = ["ctr"]
POS_CANDS = ["position", "avg. pos", "avg position", "pos"]


def _match(fieldnames, cands):
    lowered = [(f, f.strip().lower()) for f in fieldnames]
    for cand in cands:
        for orig, low in lowered:
            if low == cand:
                return orig
    for cand in cands:
        for orig, low in lowered:
            if cand in low:
                return orig
    return None


def parse_num(raw):
    if raw is None:
        return None
    s = str(raw).strip().replace(",", "").replace("%", "")
    if s == "" or s.lower() in ("n/a", "na", "-"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def read_gsc(rows):
    """rows: iterable of CSV lines (or a file handle). Returns dict key -> metrics."""
    reader = csv.DictReader(rows)
    fields = reader.fieldnames or []
    key_col = _match(fields, KEY_CANDS)
    if key_col is None:
        raise ValueError("no key column (Page/URL/Query) found in: %s" % fields)
    c_col = _match(fields, CLICKS_CANDS)
    i_col = _match(fields, IMPR_CANDS)
    ctr_col = _match(fields, CTR_CANDS)
    p_col = _match(fields, POS_CANDS)

    out = {}
    for r in reader:
        key = (r.get(key_col) or "").strip()
        if not key:
            continue
        out[key] = {
            "clicks": parse_num(r.get(c_col)) if c_col else None,
            "impressions": parse_num(r.get(i_col)) if i_col else None,
            "ctr": parse_num(r.get(ctr_col)) if ctr_col else None,
            "position": parse_num(r.get(p_col)) if p_col else None,
        }
    return out


def drop_pct(prior_v, cur_v):
    if prior_v is None or cur_v is None or prior_v == 0:
        return None
    return (prior_v - cur_v) / prior_v * 100.0


def evaluate(cur, prior, clicks_drop, impr_drop, pos_drop):
    flags = []
    dc = drop_pct(prior.get("clicks"), cur.get("clicks"))
    di = drop_pct(prior.get("impressions"), cur.get("impressions"))
    if dc is not None and dc >= clicks_drop:
        flags.append("clicks")
    if di is not None and di >= impr_drop:
        flags.append("impressions")
    pp, cp = prior.get("position"), cur.get("position")
    pos_delta = None
    if pp is not None and cp is not None:
        pos_delta = cp - pp
        if pos_delta >= pos_drop:
            flags.append("position")
    n = len(flags)
    decision = ("ok", "watch", "diagnose", "refresh")[min(n, 3)]
    return {
        "flags": flags,
        "count": n,
        "decision": decision,
        "clicks_drop_pct": dc,
        "impr_drop_pct": di,
        "pos_delta": pos_delta,
        "clicks_lost": (
            (prior.get("clicks") or 0) - (cur.get("clicks") or 0)
        ),
    }


def build_queue(current, prior, clicks_drop, impr_drop, pos_drop):
    queue, new_pages, lost_pages = [], [], []
    for key, cur in current.items():
        if key not in prior:
            new_pages.append(key)
            continue
        ev = evaluate(cur, prior[key], clicks_drop, impr_drop, pos_drop)
        ev["key"] = key
        queue.append(ev)
    for key in prior:
        if key not in current:
            lost_pages.append(key)
    queue.sort(key=lambda e: (-e["count"], -e["clicks_lost"], e["key"]))
    return queue, new_pages, lost_pages


def _fmt_pct(v):
    return "     -" if v is None else "%5.0f%%" % v


def _fmt_delta(v):
    return "    -" if v is None else "%+5.1f" % v


def run(args):
    if not os.path.exists(args.current):
        sys.stderr.write("current CSV not found: %s\n" % args.current)
        return 2
    if not os.path.exists(args.prior):
        sys.stderr.write("prior CSV not found: %s\n" % args.prior)
        return 2
    with open(args.current, newline="", encoding="utf-8-sig") as fh:
        current = read_gsc(fh)
    with open(args.prior, newline="", encoding="utf-8-sig") as fh:
        prior = read_gsc(fh)

    queue, new_pages, lost_pages = build_queue(
        current, prior, args.clicks_drop, args.impr_drop, args.pos_drop
    )

    print("Content-decay refresh queue")
    print("  current: %s  (%d rows)" % (args.current, len(current)))
    print("  prior:   %s  (%d rows)" % (args.prior, len(prior)))
    print("  gate: clicks -%g%%  impr -%g%%  position +%g pts"
          % (args.clicks_drop, args.impr_drop, args.pos_drop))
    print("")
    print("  %-40s %5s %8s %6s %6s  %s"
          % ("page/query", "flags", "clk drop", "imp", "pos", "decision"))
    print("  " + "-" * 84)
    counts = {"ok": 0, "watch": 0, "diagnose": 0, "refresh": 0}
    for e in queue:
        counts[e["decision"]] += 1
        key = e["key"]
        if len(key) > 40:
            key = key[:37] + "..."
        print("  %-40s   %d   %8s %6s %6s  %s"
              % (key, e["count"], _fmt_pct(e["clicks_drop_pct"]),
                 _fmt_pct(e["impr_drop_pct"]), _fmt_delta(e["pos_delta"]),
                 e["decision"].upper()))

    print("")
    print("  totals: %d refresh, %d diagnose, %d watch, %d ok"
          % (counts["refresh"], counts["diagnose"], counts["watch"], counts["ok"]))
    if new_pages:
        print("  new pages (no prior baseline, not flagged): %d" % len(new_pages))
    if lost_pages:
        print("  pages gone from current window: %d" % len(lost_pages))
    print("")
    if counts["refresh"]:
        print("ACTION  %d page(s) hit the refresh gate. Confirm a 2-period "
              "signal, then enroll in the month's refresh slate." % counts["refresh"])
        return 1
    print("CLEAR   no page hit the refresh gate this period.")
    return 0


def self_test():
    header = "Page,Clicks,Impressions,CTR,Position\n"
    prior_csv = header + (
        "/plumbing/austin,100,4000,2.5%,6.0\n"
        "/hvac/dallas,50,2000,2.5%,8.0\n"
        "/roofing/houston,30,900,3.3%,5.0\n"
        "/steady/page,40,1000,4.0%,7.0\n"
    )
    cur_csv = header + (
        "/plumbing/austin,60,3000,2.0%,9.5\n"      # 3 flags -> refresh
        "/hvac/dallas,30,1900,1.6%,8.4\n"          # clicks only -> watch
        "/roofing/houston,20,600,3.3%,7.5\n"       # clicks+impr+pos -> refresh
        "/steady/page,41,1010,4.1%,6.8\n"          # 0 flags -> ok
        "/brand/new,15,300,5.0%,4.0\n"             # new page
    )
    prior = read_gsc(prior_csv.splitlines())
    current = read_gsc(cur_csv.splitlines())
    queue, new_pages, lost_pages = build_queue(current, prior, 20.0, 15.0, 2.0)

    by_key = {e["key"]: e for e in queue}
    assert by_key["/plumbing/austin"]["decision"] == "refresh", by_key["/plumbing/austin"]
    assert by_key["/plumbing/austin"]["count"] == 3
    assert by_key["/hvac/dallas"]["decision"] == "watch", by_key["/hvac/dallas"]
    assert by_key["/roofing/houston"]["decision"] == "refresh", by_key["/roofing/houston"]
    assert by_key["/steady/page"]["decision"] == "ok", by_key["/steady/page"]
    assert new_pages == ["/brand/new"], new_pages
    assert lost_pages == [], lost_pages
    # ranked: refresh pages sort ahead of watch/ok
    assert queue[0]["decision"] == "refresh" and queue[-1]["decision"] == "ok"
    # parser tolerates commas, percent signs, and a BOM-free header
    two = read_gsc(["URL,Clicks,Impressions,CTR,Position",
                    "/a,\"1,200\",\"12,000\",10%,3.4"])
    assert two["/a"]["clicks"] == 1200.0 and two["/a"]["ctr"] == 10.0

    print("self-test OK")
    print("  ranked queue: %s" % ", ".join(
        "%s=%s" % (e["key"], e["decision"]) for e in queue))
    return 0


def build_parser():
    p = argparse.ArgumentParser(
        description="Content-decay detector and ranked refresh queue (GSC CSVs, offline).")
    p.add_argument("--current", help="current-window GSC performance CSV export")
    p.add_argument("--prior", help="prior-window GSC performance CSV export")
    p.add_argument("--clicks-drop", type=float, default=20.0,
                   help="clicks-down flag threshold, percent (default 20)")
    p.add_argument("--impr-drop", type=float, default=15.0,
                   help="impressions-down flag threshold, percent (default 15)")
    p.add_argument("--pos-drop", type=float, default=2.0,
                   help="position-down flag threshold, points (default 2.0)")
    p.add_argument("--self-test", action="store_true",
                   help="run the built-in self-test and exit")
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    if args.self_test:
        return self_test()
    if not args.current or not args.prior:
        build_parser().error("--current and --prior are both required "
                             "(or use --self-test)")
    return run(args)


if __name__ == "__main__":
    sys.exit(main())
