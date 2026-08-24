#!/usr/bin/env python3
"""enroll.py - register a finalized page in the client's measurement log.

Offline, stdlib-only (argparse, csv, os, sys, datetime). No network calls.
Operationalizes Local Content Law 18 (a page is not shipped, it is enrolled)
and doctrine Law 6 (measure or you are guessing). The write pipeline ends at
FINALIZE with the five-file package; a page is not counted as done until it has
a row in the client's measurement log. This tool writes and checks that row.

The log is one CSV per client (clients/<slug>/measurement-log.csv). It is the
enrollment record (enrolled = shipped) and the operator's measurement worksheet.
Its `url` column is the intended join key for a future `--log` filter in
decay_monitor.py / report_builder.py; today those scripts run on the raw GSC/GA4
exports directly, so the log is the record of what is enrolled, not yet a script
input. Columns follow the enrollment row in
knowledge/lifecycle/content-decay-refresh-protocol.md, Stage 1.

Columns
-------
  url                 the live absolute URL (join key, must be unique)
  tier                1 / 2 / 3 review cadence (1 monthly, 2 quarterly, 3 annual)
  target_query        the primary "[service] [city]" query the page ranks for
  publish_date        ISO 8601 (YYYY-MM-DD or full datetime)
  conversion_event    the GA4 event this page closes on (click_to_call, form_submit)
  success_hypothesis  one sentence: what this page should do, by when
  last_refresh_date   blank at enrollment; publish_date is the baseline

Subcommands
-----------
  add     validate and append one enrollment row (creates the log + header on
          first call); refuses a duplicate URL unless --update is passed
  check   exit 0 if a URL is enrolled, 1 if it is not (the Law 18 ship gate)
  list    print every enrolled page with tier and publish date

Exit codes
----------
  add     0 enrolled, 1 duplicate URL without --update, 2 usage/validation error
  check   0 enrolled, 1 not enrolled, 2 usage error
  list    0 ok, 2 usage error

Usage
-----
  python enroll.py add --log clients/acme/measurement-log.csv \\
      --url https://acme.com/plumbing/austin --tier 1 \\
      --query "plumber austin tx" --publish-date 2026-07-21 \\
      --conversion-event click_to_call \\
      --hypothesis "rank top-5 and drive 8+ calls/month within 90 days"
  python enroll.py check --log clients/acme/measurement-log.csv \\
      --url https://acme.com/plumbing/austin
  python enroll.py list --log clients/acme/measurement-log.csv
  python enroll.py --self-test
"""

import argparse
import csv
import io
import os
import sys
from datetime import datetime

HEADER = [
    "url", "tier", "target_query", "publish_date",
    "conversion_event", "success_hypothesis", "last_refresh_date",
]

VALID_TIERS = ("1", "2", "3")
DATE_FORMATS = ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%S%z")


def valid_date(s):
    s = (s or "").strip()
    if not s:
        return False
    for fmt in DATE_FORMATS:
        try:
            datetime.strptime(s, fmt)
            return True
        except ValueError:
            continue
    return False


def read_log(text_lines):
    """text_lines: iterable of CSV lines. Returns list of row dicts."""
    reader = csv.DictReader(text_lines)
    rows = []
    for r in reader:
        url = (r.get("url") or "").strip()
        if not url:
            continue
        rows.append({k: (r.get(k) or "").strip() for k in HEADER})
    return rows


def load_log(path):
    if path and os.path.exists(path):
        with io.open(path, "r", encoding="utf-8-sig", newline="") as fh:
            return read_log(fh)
    return []


def write_log(path, rows):
    parent = os.path.dirname(path)
    if parent and not os.path.isdir(parent):
        os.makedirs(parent, exist_ok=True)
    with io.open(path, "w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=HEADER)
        writer.writeheader()
        for r in rows:
            writer.writerow({k: r.get(k, "") for k in HEADER})


def validate_add(url, tier, query, publish_date, conversion_event, hypothesis):
    errs = []
    if not (url or "").strip():
        errs.append("url is required")
    elif not url.strip().lower().startswith(("http://", "https://")):
        errs.append("url must be absolute (http:// or https://)")
    if str(tier).strip() not in VALID_TIERS:
        errs.append("tier must be 1, 2, or 3")
    if not (query or "").strip():
        errs.append("target query is required")
    if not valid_date(publish_date):
        errs.append("publish-date must be ISO 8601 (e.g. 2026-07-21)")
    if not (conversion_event or "").strip():
        errs.append("conversion-event is required (e.g. click_to_call, form_submit)")
    if not (hypothesis or "").strip():
        errs.append("success hypothesis is required (Law 18: what should this page do, by when)")
    return errs


def cmd_add(args):
    errs = validate_add(args.url, args.tier, args.query, args.publish_date,
                        args.conversion_event, args.hypothesis)
    if errs:
        for e in errs:
            sys.stderr.write("error: %s\n" % e)
        return 2
    rows = load_log(args.log)
    url = args.url.strip()
    existing = next((r for r in rows if r["url"] == url), None)
    if existing is not None and not args.update:
        sys.stderr.write(
            "error: %s is already enrolled (use --update to overwrite its row)\n" % url)
        return 1
    row = {
        "url": url,
        "tier": str(args.tier).strip(),
        "target_query": args.query.strip(),
        "publish_date": args.publish_date.strip(),
        "conversion_event": args.conversion_event.strip(),
        "success_hypothesis": args.hypothesis.strip(),
        "last_refresh_date": (args.last_refresh or "").strip(),
    }
    if existing is not None:
        rows = [row if r["url"] == url else r for r in rows]
        action = "updated"
    else:
        rows.append(row)
        action = "enrolled"
    write_log(args.log, rows)
    print("%s %s (tier %s) in %s" % (action, url, row["tier"], args.log))
    print("  the measured set now holds %d page(s)" % len(rows))
    return 0


def cmd_check(args):
    rows = load_log(args.log)
    url = (args.url or "").strip()
    if any(r["url"] == url for r in rows):
        print("ENROLLED  %s is in the measured set (%s)" % (url, args.log))
        return 0
    sys.stderr.write(
        "NOT ENROLLED  %s has no row in %s. Law 18: not shipped until enrolled.\n"
        % (url, args.log))
    return 1


def cmd_list(args):
    rows = load_log(args.log)
    print("Measurement log: %s (%d page(s))" % (args.log, len(rows)))
    print("  %-48s %-4s %-12s %s" % ("url", "tier", "published", "target query"))
    print("  " + "-" * 84)
    for r in sorted(rows, key=lambda x: (x["tier"], x["url"])):
        url = r["url"] if len(r["url"]) <= 48 else r["url"][:45] + "..."
        print("  %-48s %-4s %-12s %s"
              % (url, r["tier"], r["publish_date"], r["target_query"]))
    return 0


def self_test():
    # valid-date helper
    assert valid_date("2026-07-21")
    assert valid_date("2026-07-21T09:30:00")
    assert not valid_date("21-07-2026")
    assert not valid_date("")

    # validation catches every missing/invalid required field
    errs = validate_add("", "9", "", "not-a-date", "", "")
    assert len(errs) == 6, errs
    assert validate_add("ftp://x/y", "1", "q", "2026-07-21", "call", "h"), "non-absolute url"
    assert validate_add("https://x/y", "1", "q", "2026-07-21", "call", "h") == []

    # round-trip a log through read/write in memory
    rows = [{
        "url": "https://acme.com/plumbing/austin", "tier": "1",
        "target_query": "plumber austin tx", "publish_date": "2026-07-21",
        "conversion_event": "click_to_call",
        "success_hypothesis": "rank top-5, 8+ calls/mo in 90 days",
        "last_refresh_date": "",
    }]
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=HEADER)
    w.writeheader()
    w.writerow(rows[0])
    parsed = read_log(buf.getvalue().splitlines())
    assert len(parsed) == 1, parsed
    assert parsed[0]["url"] == "https://acme.com/plumbing/austin"
    assert parsed[0]["conversion_event"] == "click_to_call"
    # header order is exactly the protocol's enrollment row
    assert HEADER[0] == "url" and HEADER[-1] == "last_refresh_date"

    print("self-test OK")
    print("  validation: 6 errors on an empty add; clean add passes; url join-key first")
    return 0


def build_parser():
    p = argparse.ArgumentParser(
        description="Register a finalized page in the client's measurement log (Law 18).")
    p.add_argument("--self-test", action="store_true",
                   help="run the built-in self-test and exit")
    sub = p.add_subparsers(dest="cmd")

    a = sub.add_parser("add", help="validate and append one enrollment row")
    a.add_argument("--log", required=True, help="path to the client's measurement-log.csv")
    a.add_argument("--url", required=True, help="the live absolute URL")
    a.add_argument("--tier", required=True, help="review cadence tier: 1, 2, or 3")
    a.add_argument("--query", required=True, help="primary target query")
    a.add_argument("--publish-date", required=True, help="ISO 8601 publish date")
    a.add_argument("--conversion-event", required=True,
                   help="GA4 conversion event (click_to_call, form_submit)")
    a.add_argument("--hypothesis", required=True,
                   help="one-sentence success hypothesis (what, by when)")
    a.add_argument("--last-refresh", default="", help="last-refresh date (blank at enrollment)")
    a.add_argument("--update", action="store_true",
                   help="overwrite the row if the URL is already enrolled")

    c = sub.add_parser("check", help="exit 0 if a URL is enrolled, 1 if not")
    c.add_argument("--log", required=True, help="path to the client's measurement-log.csv")
    c.add_argument("--url", required=True, help="the URL to check")

    l = sub.add_parser("list", help="list every enrolled page")
    l.add_argument("--log", required=True, help="path to the client's measurement-log.csv")

    return p


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.self_test:
        return self_test()
    if args.cmd == "add":
        return cmd_add(args)
    if args.cmd == "check":
        return cmd_check(args)
    if args.cmd == "list":
        return cmd_list(args)
    parser.error("a subcommand is required (add / check / list) or use --self-test")


if __name__ == "__main__":
    sys.exit(main())
