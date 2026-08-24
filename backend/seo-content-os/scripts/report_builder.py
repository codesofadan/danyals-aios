#!/usr/bin/env python3
"""report_builder.py - monthly local-SEO KPI report from GSC/GA4/GBP CSV exports.

Offline, stdlib-only (argparse, csv, sys, os). No network calls. The human
exports the month's CSVs (Search Console pages export, GA4 landing-page export,
Google Business Profile performance export) plus the prior month's, drops them
in, and this tool aggregates each, joins them into one 8-12 KPI local scorecard,
and prints each KPI with its vs-last-period direction and a single next-action
line. It deliberately omits vanity metrics (research file 06, Part 5).

Data layers and KPIs
--------------------
  GSC : organic clicks, impressions, CTR (derived), avg position
        (impression-weighted)
  GA4 : organic sessions, engaged sessions, conversions (form + call key events)
  GBP : calls, website clicks, direction requests (whichever columns appear)

Cut on purpose (noise / harm): third-party Domain Authority, raw keyword count,
social shares, GA4 bounce rate. These are not in the report.

Direction sense: for every KPI more is better EXCEPT average position, where a
lower number is better. "adverse" means the metric moved the wrong way by more
than --flat-band percent. The next-action line names the single worst adverse
KPI, or holds course if none.

Inputs are all optional; supply at least one current file. Prior files are
optional; without them, direction shows as 'new'. Each source expects its
current and prior file as a pair (--gsc / --gsc-prior, etc).

Exit codes
----------
  0  report built, net trend flat or positive (adverse KPIs do not outnumber
     improved ones)
  1  report built, net trend negative (more KPIs adverse than improved)
  2  usage error, or no usable input provided

Usage
-----
  python report_builder.py --client acme \\
      --gsc jul_pages.csv --gsc-prior jun_pages.csv \\
      --ga4 jul_ga4.csv   --ga4-prior jun_ga4.csv \\
      --gbp jul_gbp.csv   --gbp-prior jun_gbp.csv
  python report_builder.py --self-test
"""

import argparse
import csv
import os
import sys


def _match(fields, cands):
    low = [(f, f.strip().lower()) for f in (fields or [])]
    for cand in cands:
        for orig, lo in low:
            if lo == cand:
                return orig
    for cand in cands:
        for orig, lo in low:
            if cand in lo:
                return orig
    return None


def parse_num(raw):
    if raw is None:
        return None
    s = str(raw).strip().replace(",", "").replace("%", "").replace("$", "")
    if s == "" or s.lower() in ("n/a", "na", "-"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _sum_col(rows, fields, cands):
    col = _match(fields, cands)
    if col is None:
        return None
    total, seen = 0.0, False
    for r in rows:
        v = parse_num(r.get(col))
        if v is not None:
            total += v
            seen = True
    return total if seen else None


def _read(path):
    if not path:
        return None
    with open(path, newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        return reader.fieldnames or [], list(reader)


def aggregate_gsc(parsed):
    if not parsed:
        return {}
    fields, rows = parsed
    clicks = _sum_col(rows, fields, ["clicks", "click"])
    impr = _sum_col(rows, fields, ["impressions", "impr"])
    pos_col = _match(fields, ["position", "avg. pos", "avg position", "pos"])
    impr_col = _match(fields, ["impressions", "impr"])
    wpos = None
    if pos_col and impr_col:
        num = den = 0.0
        for r in rows:
            p = parse_num(r.get(pos_col))
            i = parse_num(r.get(impr_col))
            if p is not None and i:
                num += p * i
                den += i
        wpos = (num / den) if den else None
    ctr = (clicks / impr * 100.0) if (clicks is not None and impr) else None
    out = {}
    if clicks is not None:
        out["organic_clicks"] = clicks
    if impr is not None:
        out["impressions"] = impr
    if ctr is not None:
        out["organic_ctr_pct"] = ctr
    if wpos is not None:
        out["avg_position"] = wpos
    return out


def aggregate_ga4(parsed):
    if not parsed:
        return {}
    fields, rows = parsed
    out = {}
    sess = _sum_col(rows, fields, ["sessions", "session"])
    eng = _sum_col(rows, fields, ["engaged sessions", "engaged"])
    conv = _sum_col(rows, fields, ["conversions", "key events", "key event"])
    if sess is not None:
        out["organic_sessions"] = sess
    if eng is not None:
        out["engaged_sessions"] = eng
    if conv is not None:
        out["conversions"] = conv
    return out


def aggregate_gbp(parsed):
    if not parsed:
        return {}
    fields, rows = parsed
    out = {}
    calls = _sum_col(rows, fields, ["calls", "call clicks", "phone"])
    web = _sum_col(rows, fields, ["website clicks", "website", "web clicks"])
    dirs = _sum_col(rows, fields, ["directions", "direction requests", "direction"])
    if calls is not None:
        out["gbp_calls"] = calls
    if web is not None:
        out["gbp_website_clicks"] = web
    if dirs is not None:
        out["gbp_directions"] = dirs
    return out


# kpi -> (label, unit, good_direction)  good_direction: "up" or "down"
KPI_SPEC = {
    "organic_clicks": ("Organic clicks", "", "up"),
    "impressions": ("Impressions", "", "up"),
    "organic_ctr_pct": ("Organic CTR", "%", "up"),
    "avg_position": ("Avg position", "", "down"),
    "organic_sessions": ("Organic sessions", "", "up"),
    "engaged_sessions": ("Engaged sessions", "", "up"),
    "conversions": ("Conversions (forms+calls)", "", "up"),
    "gbp_calls": ("GBP calls", "", "up"),
    "gbp_website_clicks": ("GBP website clicks", "", "up"),
    "gbp_directions": ("GBP direction requests", "", "up"),
}
KPI_ORDER = list(KPI_SPEC.keys())


def _pct_change(cur, prior):
    if prior is None or prior == 0:
        return None
    return (cur - prior) / prior * 100.0


def build_report(cur_metrics, prior_metrics, flat_band=1.0):
    rows, adverse, improved = [], 0, 0
    worst = None  # (adverse_magnitude, kpi, label)
    for kpi in KPI_ORDER:
        if kpi not in cur_metrics:
            continue
        label, unit, good = KPI_SPEC[kpi]
        cur = cur_metrics[kpi]
        prior = prior_metrics.get(kpi)
        pct = _pct_change(cur, prior)
        if pct is None:
            direction = "new"
        elif abs(pct) < flat_band:
            direction = "flat"
        else:
            rose = pct > 0
            good_move = (rose and good == "up") or ((not rose) and good == "down")
            direction = "up" if rose else "down"
            if good_move:
                improved += 1
            else:
                adverse += 1
                mag = abs(pct)
                if worst is None or mag > worst[0]:
                    worst = (mag, kpi, label)
        rows.append({"kpi": kpi, "label": label, "unit": unit,
                     "cur": cur, "prior": prior, "pct": pct,
                     "direction": direction, "good": good})
    net_negative = adverse > improved
    return {"rows": rows, "adverse": adverse, "improved": improved,
            "worst": worst, "net_negative": net_negative}


def _fmt_val(v, unit):
    if v is None:
        return "-"
    if unit == "%":
        return "%.1f%%" % v
    if abs(v - round(v)) < 1e-9:
        return "%d" % round(v)
    return "%.1f" % v


def _arrow(direction, good):
    if direction == "new":
        return "new"
    if direction == "flat":
        return "flat"
    good_move = (direction == "up" and good == "up") or \
                (direction == "down" and good == "down")
    return "%s (%s)" % (direction, "good" if good_move else "adverse")


def next_action(report):
    if report["worst"] is None:
        if report["improved"]:
            return "Hold course. Protect the top-converting page and keep the cadence."
        return "Insufficient movement to act. Recheck next period."
    _, kpi, label = report["worst"]
    templates = {
        "avg_position": "%s slipped most. Run decay_monitor on the money pages "
                        "and schedule the top refresh.",
        "organic_clicks": "%s fell most. Snippet-test titles/meta on the pages "
                          "that lost the most clicks.",
        "conversions": "%s dropped most. Audit the primary conversion path on "
                       "the top landing pages before chasing more traffic.",
        "gbp_calls": "%s dropped most. Refresh the GBP profile (photos, posts, "
                     "hours) and confirm the tel: link tracking.",
    }
    tmpl = templates.get(kpi, "%s moved the wrong way most. Investigate that "
                               "metric's top pages this month.")
    return tmpl % label


def run(args):
    for p in [args.gsc, args.gsc_prior, args.ga4, args.ga4_prior,
              args.gbp, args.gbp_prior]:
        if p and not os.path.exists(p):
            sys.stderr.write("file not found: %s\n" % p)
            return 2
    if not (args.gsc or args.ga4 or args.gbp):
        sys.stderr.write("provide at least one current file "
                         "(--gsc / --ga4 / --gbp)\n")
        return 2

    cur = {}
    cur.update(aggregate_gsc(_read(args.gsc)))
    cur.update(aggregate_ga4(_read(args.ga4)))
    cur.update(aggregate_gbp(_read(args.gbp)))
    prior = {}
    prior.update(aggregate_gsc(_read(args.gsc_prior)))
    prior.update(aggregate_ga4(_read(args.ga4_prior)))
    prior.update(aggregate_gbp(_read(args.gbp_prior)))

    report = build_report(cur, prior, args.flat_band)

    print("Monthly local-SEO report - %s" % (args.client or "client"))
    print("  %-28s %12s %12s %s" % ("KPI", "current", "prior", "vs last period"))
    print("  " + "-" * 74)
    for r in report["rows"]:
        print("  %-28s %12s %12s %s"
              % (r["label"], _fmt_val(r["cur"], r["unit"]),
                 _fmt_val(r["prior"], r["unit"]), _arrow(r["direction"], r["good"])))
    print("")
    print("  movement: %d improved, %d adverse" % (report["improved"], report["adverse"]))
    print("  next action: %s" % next_action(report))
    print("")
    if report["net_negative"]:
        print("ATTENTION  net trend is negative this period.")
        return 1
    print("OK  net trend is flat or positive this period.")
    return 0


def self_test():
    gsc_fields = ["Page", "Clicks", "Impressions", "CTR", "Position"]
    gsc_cur = [
        {"Page": "/a", "Clicks": "120", "Impressions": "3000", "CTR": "4%", "Position": "5"},
        {"Page": "/b", "Clicks": "80", "Impressions": "2000", "CTR": "4%", "Position": "9"},
    ]
    gsc_prior = [
        {"Page": "/a", "Clicks": "150", "Impressions": "3200", "CTR": "4.7%", "Position": "4"},
        {"Page": "/b", "Clicks": "90", "Impressions": "2100", "CTR": "4.3%", "Position": "7"},
    ]
    g = aggregate_gsc((gsc_fields, gsc_cur))
    gp = aggregate_gsc((gsc_fields, gsc_prior))
    assert g["organic_clicks"] == 200.0, g
    assert g["impressions"] == 5000.0, g
    # weighted position = (5*3000 + 9*2000)/5000 = 6.6
    assert abs(g["avg_position"] - 6.6) < 1e-9, g["avg_position"]

    ga4 = aggregate_ga4((["Landing page", "Sessions", "Engaged sessions", "Conversions"],
                         [{"Landing page": "/a", "Sessions": "300",
                           "Engaged sessions": "210", "Conversions": "12"}]))
    ga4p = aggregate_ga4((["Landing page", "Sessions", "Engaged sessions", "Conversions"],
                          [{"Landing page": "/a", "Sessions": "260",
                            "Engaged sessions": "180", "Conversions": "9"}]))
    assert ga4["conversions"] == 12.0, ga4

    gbp = aggregate_gbp((["Date", "Calls", "Website clicks", "Directions"],
                         [{"Date": "d1", "Calls": "5", "Website clicks": "10", "Directions": "3"},
                          {"Date": "d2", "Calls": "7", "Website clicks": "8", "Directions": "4"}]))
    assert gbp["gbp_calls"] == 12.0 and gbp["gbp_directions"] == 7.0, gbp

    cur = {}
    cur.update(g); cur.update(ga4); cur.update(gbp)
    prior = {}
    prior.update(gp); prior.update(ga4p)  # no prior GBP -> direction 'new'
    report = build_report(cur, prior)

    by = {r["kpi"]: r for r in report["rows"]}
    # clicks fell 200 vs 240 -> adverse; conversions rose -> improved
    assert by["organic_clicks"]["direction"] == "down"
    assert by["conversions"]["direction"] == "up"
    # avg position rose 6.6 vs ~5.15 -> worse rank -> adverse (down is good)
    assert by["avg_position"]["good"] == "down"
    assert by["gbp_calls"]["direction"] == "new", by["gbp_calls"]
    assert report["adverse"] >= 1 and report["improved"] >= 1
    action = next_action(report)
    assert isinstance(action, str) and len(action) > 0

    print("self-test OK")
    print("  KPIs built: %d   improved: %d   adverse: %d"
          % (len(report["rows"]), report["improved"], report["adverse"]))
    print("  next action: %s" % action)
    return 0


def build_parser():
    p = argparse.ArgumentParser(
        description="Monthly local-SEO KPI report from GSC/GA4/GBP CSV exports (offline).")
    p.add_argument("--client", default="", help="client name for the report header")
    p.add_argument("--gsc", help="current-month Search Console pages CSV")
    p.add_argument("--gsc-prior", help="prior-month Search Console pages CSV")
    p.add_argument("--ga4", help="current-month GA4 landing-page CSV")
    p.add_argument("--ga4-prior", help="prior-month GA4 landing-page CSV")
    p.add_argument("--gbp", help="current-month GBP performance CSV")
    p.add_argument("--gbp-prior", help="prior-month GBP performance CSV")
    p.add_argument("--flat-band", type=float, default=1.0,
                   help="abs percent move under this counts as flat (default 1.0)")
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
