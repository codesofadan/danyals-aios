#!/usr/bin/env python3
"""storage_lint.py - Deterministic self-storage compliance + pricing-honesty lint.

Offline, stdlib-only (re, os, argparse; optional yaml). No network calls.

Runs the deterministic half of the self-storage vertical overlay
(knowledge/verticals/self-storage.md). It scans a page draft for the banned
patterns the SS-* rules forbid, and decides ALLOW/FAIL using context the overlay
reads from brand.yaml.storage (tenant-protection type, humidity control, live
inventory, a real rate guarantee). It never invents a fact and never games
AI-detection (Law 8); it surfaces the sentence so a human replaces the slogan
with a real spec.

Rules enforced (each finding carries a line, severity, SS-code, and context)
----------------------------------------------------------------------------
- SS-1/SS-2 (insurance word trap): "insurance / insured / coverage / policy /
    premium". FAIL if --protection-type protection_plan (a self-indemnity plan is
    not insurance, Heckart v. A-1). WARN (verify licence) if licensed_insurance
    without a licence on file; WARN (unknown) if the type is not supplied.
- SS-3 (absolute/unbacked security): "safe and secure", "your belongings are
    safe", "100% secure", "theft-proof", "guaranteed secure/safe", "fully
    protected" -> FAIL (Dilbeck v. Yates: an absolute security claim can void the
    lease). Bare "secure storage" -> WARN (add the real spec).
- SS-4 (clean-history claim): "never had a break-in", "nothing ever stolen",
    "crime-free" -> FAIL unless it is a dated counter (the tool flags; the auditor
    confirms a real brand.yaml.storage.break_in_free_since backs it).
- SS-5 (climate + moisture): "climate controlled" within the page paired with
    "dry / moisture-free / prevents mold / mildew / keeps ... dry" -> FAIL unless
    --humidity-control (DiSanto v. Safeco; "climate controlled" is unregulated).
- SS-6 (free-month disclosure): "first month free / $1 (first month) / % off /
    free month" present without an admin-fee disclosure token on the page
    ("admin fee", "administrative fee") -> FAIL (16 CFR 251.1: conditions at the
    outset, not a footnote).
- SS-8 (rate lock): "rate locked / price never increases / guaranteed rate /
    no rate increase / fixed rate / rate for life" -> FAIL unless
    --rate-guarantee is supplied (false for month-to-month ECRI).
- SS-CV1 (hard-coded scarcity): "only N left / N units remaining / selling fast
    / almost gone / going fast" -> FAIL unless --live-inventory (FTC scarcity
    dark pattern; Law 20).
- SS-CV2 (countdown): "ends in / expires in / hurry, offer ends / HH:MM:SS
    timer" -> WARN (verify it targets a real fixed end datetime and does not
    reset per session).

Context flags (or --brand brand.yaml to auto-fill via PyYAML if available):
  --protection-type {protection_plan,licensed_insurance,none,unknown}
  --humidity-control        the facility actually controls humidity (allows SS-5)
  --live-inventory          the page pulls real live PMS inventory (allows SS-CV1)
  --rate-guarantee TEXT     a real contractual guarantee exists (allows SS-8)
  --state XX                the client state (adds a STATE-DEP note)

Exit code 0 = no FAIL finding, 1 = one or more FAILs (or a usage error).

Usage
-----
  python storage_lint.py draft.md --protection-type protection_plan
  python storage_lint.py draft.md --brand clients/acme-storage/brand.yaml
  python storage_lint.py --self-test
"""

import argparse
import os
import re
import sys

SEVERITY_ORDER = {"FAIL": 0, "WARN": 1}

# --- SS-3 absolute / unbacked security claims (FAIL) ---
SEC_FAIL = [
    r"safe and secure",
    r"secure and safe",
    r"your (?:belongings|items|stuff|things|possessions) (?:are|will be) (?:safe|secure|protected)",
    r"(?:100%|completely|totally|fully|absolutely) (?:safe|secure|protected)",
    r"theft[\s-]?proof",
    r"guaranteed (?:safe|secure)",
    r"fully protected",
    r"your (?:belongings|stuff|items) are safe with us",
    r"safe and sound",
]
# bare "secure storage" / "secure facility" as an adjective (WARN: add the spec)
SEC_WARN = [
    r"(?<!\w)secure storage(?!\w)",
    r"(?<!\w)secure facility(?!\w)",
]

# --- SS-4 clean-history claims (FAIL unless a dated counter backs it) ---
HIST_FAIL = [
    r"never (?:had|have had|experienced) (?:a )?(?:break[\s-]?in|theft|robbery|burglary)",
    r"never been broken into",
    r"no break[\s-]?ins?(?: ever)?",
    r"nothing (?:has )?ever (?:been|got) stolen",
    r"nothing (?:ever )?gets stolen",
    r"(?<!\w)crime[\s-]?free(?!\w)",
    r"theft[\s-]?free",
]

# --- SS-1/2 insurance words (severity depends on protection type) ---
INS_WORDS = [
    r"(?<!\w)insurance(?!\w)",
    r"(?<!\w)insured(?!\w)",
    r"(?<!\w)coverage(?!\w)",
    r"(?<!\w)policy(?!\w)",
    r"(?<!\w)premium(?!\w)",
]
# A line carrying one of these is a legitimate insurance mention: the tenant's
# OWN policy, or the honest "not insurance" disclosure. SS-1/2 forbids calling
# the OPERATOR'S protection plan insurance, not mentioning real insurance.
INS_ALLOW = re.compile(
    r"your own|home\s*-?\s*owner'?s?|renter'?s?|not (?:an )?insurance|"
    r"isn'?t insurance|is not (?:an )?insurance|bring your own|existing "
    r"(?:policy|coverage)|declarations? page|proof of", re.IGNORECASE)

# --- SS-5 moisture / dryness promises (FAIL when climate-controlled + no humidity control) ---
MOISTURE_WORDS = [
    r"(?<!\w)moisture[\s-]?free(?!\w)",
    r"prevents? (?:mold|mildew)",
    r"(?:mold|mildew)[\s-]?free",
    r"keeps? (?:your )?(?:items|belongings|things|stuff)? ?dry",
    r"stays? dry",
    r"protect(?:s|ed)? against (?:moisture|humidity|mold|mildew)",
    r"humidity[\s-]?controlled",  # a specific claim; only OK with real humidity control
]
CLIMATE_MENTION = re.compile(r"climate[\s-]?controlled", re.IGNORECASE)

# --- SS-8 rate-lock claims (FAIL unless a real guarantee) ---
RATE_FAIL = [
    r"rate[\s-]?lock(?:ed)?",
    r"rate (?:is |gets |will be )?locked",
    r"locked(?: in)? for life",
    r"price (?:never|won't|will never) (?:increase|go up|change)",
    r"(?:guaranteed|fixed) rate(?: for life)?",
    r"no rate increases?",
    r"rate for life",
    r"locked[\s-]?in rate",
    r"your rate (?:never|won't) (?:change|increase|go up)",
]

# --- SS-6 free-month claim + the admin-fee disclosure it requires ---
FREE_CLAIM = [
    r"first month free",
    r"free (?:first )?month",
    r"one month free",
    r"month (?:free|on us)",
    r"\$1 (?:first month|move[\s-]?in|to move in)?",
    r"(?:50|25|75|100)%\s*off",
    r"half[\s-]?off (?:your )?first month",
]
ADMIN_DISCLOSURE = re.compile(
    r"admin(?:istrative)?[\s-]?fee|admin\s*charge|one[\s-]?time fee", re.IGNORECASE)

# --- SS-CV1 hard-coded scarcity (FAIL unless live inventory) ---
SCARCITY_FAIL = [
    r"only \d+ (?:units?|left|remaining|available)",
    r"\d+ units? (?:left|remaining)",
    r"only \d+ left",
    r"selling fast",
    r"(?:almost|nearly) (?:gone|sold out)",
    r"going fast",
    r"(?:hurry|act now)[,!]? (?:only|just) \d+",
    r"last (?:one|unit|few)",
]

# --- SS-CV2 countdown / deadline language (WARN: verify it does not reset) ---
COUNTDOWN_WARN = [
    r"(?:offer|sale|deal|promo) ends in",
    r"expires in \d",
    r"\d+\s*(?:hours?|minutes?|days?) left",
    r"\d{1,2}:\d{2}:\d{2}",  # a HH:MM:SS timer string
    r"countdown",
    r"hurry[,!]? (?:offer|sale|deal|this) (?:ends|won't last)",
]


def _compile(patterns):
    return [re.compile(p, re.IGNORECASE) for p in patterns]


SEC_FAIL_RX = _compile(SEC_FAIL)
SEC_WARN_RX = _compile(SEC_WARN)
HIST_FAIL_RX = _compile(HIST_FAIL)
INS_WORDS_RX = _compile(INS_WORDS)
MOISTURE_RX = _compile(MOISTURE_WORDS)
RATE_FAIL_RX = _compile(RATE_FAIL)
FREE_CLAIM_RX = _compile(FREE_CLAIM)
SCARCITY_RX = _compile(SCARCITY_FAIL)
COUNTDOWN_RX = _compile(COUNTDOWN_WARN)


def iter_scan_lines(text):
    """Yield (lineno, line), skipping fenced code blocks."""
    in_fence = False
    for i, line in enumerate(text.splitlines(), 1):
        if line.strip().startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        yield i, line


def _first_hit(line, rxs):
    for rx in rxs:
        m = rx.search(line)
        if m:
            return m
    return None


def lint(text, protection_type="unknown", humidity_control=False,
         live_inventory=False, rate_guarantee="", state=""):
    """Return a list of findings: (severity, code, lineno, message)."""
    findings = []
    climate_on_page = bool(CLIMATE_MENTION.search(text))

    for lineno, line in iter_scan_lines(text):
        # SS-3 security (FAIL)
        m = _first_hit(line, SEC_FAIL_RX)
        if m:
            findings.append(("FAIL", "SS-3", lineno,
                             "absolute/unbacked security claim %r - replace with a "
                             "concrete spec from storage.security_features "
                             "(Dilbeck v. Yates)" % m.group(0)))
        else:
            m = _first_hit(line, SEC_WARN_RX)
            if m:
                findings.append(("WARN", "SS-3", lineno,
                                 "bare %r - name the mechanism (cameras, door "
                                 "alarms, gate code, on-site manager)" % m.group(0)))

        # SS-4 clean-history (FAIL unless a dated counter)
        m = _first_hit(line, HIST_FAIL_RX)
        if m:
            findings.append(("FAIL", "SS-4", lineno,
                             "clean-history claim %r - only a real dated counter "
                             "(storage.break_in_free_since) may appear (Dilbeck)"
                             % m.group(0)))

        # SS-1/2 insurance words
        m = _first_hit(line, INS_WORDS_RX)
        if m and INS_ALLOW.search(line):
            m = None  # legitimate: the tenant's own policy, or an honest "not insurance" line
        if m:
            if protection_type == "protection_plan":
                findings.append(("FAIL", "SS-1", lineno,
                                 "%r used for a self-indemnity protection plan - "
                                 "call it a 'protection plan', never insurance "
                                 "(Heckart v. A-1)" % m.group(0)))
            elif protection_type == "licensed_insurance":
                findings.append(("WARN", "SS-2", lineno,
                                 "%r - confirm the state insurance licence number "
                                 "is on file (storage.insurance_license)"
                                 % m.group(0)))
            else:
                findings.append(("WARN", "SS-1", lineno,
                                 "%r - confirm whether this is a protection plan "
                                 "(may NOT say insurance) or licensed insurance; "
                                 "set --protection-type" % m.group(0)))

        # SS-5 moisture/dryness promise (needs the page to mention climate control)
        if climate_on_page and not humidity_control:
            m = _first_hit(line, MOISTURE_RX)
            if m:
                findings.append(("FAIL", "SS-5", lineno,
                                 "moisture/dryness promise %r with climate-controlled "
                                 "copy but no confirmed humidity control - use "
                                 "'temperature controlled' or set --humidity-control "
                                 "(DiSanto v. Safeco)" % m.group(0)))

        # SS-8 rate lock (FAIL unless a real guarantee)
        m = _first_hit(line, RATE_FAIL_RX)
        if m and not rate_guarantee:
            findings.append(("FAIL", "SS-8", lineno,
                             "rate-lock claim %r on month-to-month - false under "
                             "ECRI unless storage.rate_guarantee is real "
                             "(set --rate-guarantee)" % m.group(0)))

        # SS-CV1 hard-coded scarcity (FAIL unless live inventory)
        m = _first_hit(line, SCARCITY_RX)
        if m and not live_inventory:
            findings.append(("FAIL", "SS-CV1", lineno,
                             "scarcity claim %r without live PMS inventory - remove "
                             "or wire to real inventory (set --live-inventory; FTC "
                             "dark-pattern, Law 20)" % m.group(0)))

        # SS-CV2 countdown (WARN)
        m = _first_hit(line, COUNTDOWN_RX)
        if m:
            findings.append(("WARN", "SS-CV2", lineno,
                             "deadline/countdown %r - verify it targets a real fixed "
                             "end datetime and does not reset per session (FTC)"
                             % m.group(0)))

    # SS-6 free-month disclosure (page-level: a free claim needs an admin-fee token)
    free_hit = None
    free_line = 0
    for lineno, line in iter_scan_lines(text):
        m = _first_hit(line, FREE_CLAIM_RX)
        if m:
            free_hit = m.group(0)
            free_line = lineno
            break
    if free_hit and not ADMIN_DISCLOSURE.search(text):
        findings.append(("FAIL", "SS-6", free_line,
                         "free/discount claim %r without an in-copy admin-fee "
                         "disclosure - disclose the admin fee and required add-ons "
                         "in close conjunction (16 CFR 251.1)" % free_hit))

    if state and state.upper() not in ("CA", "TX", "FL"):
        findings.append(("WARN", "STATE-DEP", 0,
                         "state %r not statute-verified in this build - confirm the "
                         "state Self-Service Storage Facility Act, late-fee cap, and "
                         "protection-plan classification live" % state))

    findings.sort(key=lambda f: (f[2], SEVERITY_ORDER.get(f[0], 9), f[1]))
    return findings


def _read_brand(path):
    """Best-effort read of brand.yaml.storage context. PyYAML if available, else
    a tiny scan for the flat storage scalars this tool needs."""
    ctx = {"protection_type": "unknown", "humidity_control": False,
           "live_inventory": False, "rate_guarantee": "", "state": ""}
    with open(path, "r", encoding="utf-8") as fh:
        raw = fh.read()
    try:
        import yaml
        data = yaml.safe_load(raw) or {}
        st = (data.get("storage") or {})
        ctx["protection_type"] = st.get("tenant_protection_type") or "unknown"
        cc = st.get("climate_control") or {}
        ctx["humidity_control"] = bool(cc.get("humidity_control"))
        ctx["live_inventory"] = bool(st.get("live_inventory"))
        ctx["rate_guarantee"] = str(st.get("rate_guarantee") or "")
        ctx["state"] = str((data.get("nap") or {}).get("state_region") or "")
        return ctx
    except ImportError:
        pass
    # minimal fallback: scan flat keys
    def _scalar(key):
        m = re.search(r"^\s*%s:\s*(.+?)\s*$" % re.escape(key), raw, re.MULTILINE)
        return m.group(1).strip().strip('"').strip("'") if m else ""
    ctx["protection_type"] = _scalar("tenant_protection_type") or "unknown"
    ctx["humidity_control"] = _scalar("humidity_control").lower() == "true"
    ctx["live_inventory"] = _scalar("live_inventory").lower() == "true"
    ctx["rate_guarantee"] = _scalar("rate_guarantee")
    ctx["state"] = _scalar("state_region")
    return ctx


def run(args):
    if args.path == "-":
        text = sys.stdin.read()
        src = "<stdin>"
    else:
        with open(args.path, "r", encoding="utf-8") as fh:
            text = fh.read()
        src = args.path

    ctx = {"protection_type": args.protection_type, "humidity_control": args.humidity_control,
           "live_inventory": args.live_inventory, "rate_guarantee": args.rate_guarantee or "",
           "state": args.state or ""}
    if args.brand:
        try:
            b = _read_brand(args.brand)
        except OSError as exc:
            print("error: could not read %s: %s" % (args.brand, exc), file=sys.stderr)
            return 1
        # explicit flags override brand.yaml; brand fills the unset ones
        if args.protection_type == "unknown":
            ctx["protection_type"] = b["protection_type"]
        if not args.humidity_control:
            ctx["humidity_control"] = b["humidity_control"]
        if not args.live_inventory:
            ctx["live_inventory"] = b["live_inventory"]
        if not args.rate_guarantee:
            ctx["rate_guarantee"] = b["rate_guarantee"]
        if not args.state:
            ctx["state"] = b["state"]

    findings = lint(text, **ctx)
    lines = text.splitlines()

    print("Self-storage lint for %s" % src)
    fails = [f for f in findings if f[0] == "FAIL"]
    warns = [f for f in findings if f[0] == "WARN"]
    print("  protection-type=%s humidity-control=%s live-inventory=%s state=%s"
          % (ctx["protection_type"], ctx["humidity_control"], ctx["live_inventory"],
             ctx["state"] or "-"))
    print("  %d fail(s), %d warning(s)" % (len(fails), len(warns)))
    for sev, code, ln, msg in findings:
        loc = ("line %d" % ln) if ln else "-"
        print("  [%-4s] %-8s %-9s %s" % (sev, code, loc, msg))
        if 1 <= ln <= len(lines):
            print("           > %s" % lines[ln - 1].strip()[:88])
    print("")
    if fails:
        print("FAIL  %d self-storage overlay violation(s); fix before the gate passes"
              % len(fails))
        return 1
    print("PASS  no self-storage FAIL findings" + (" (warnings advisory)" if warns else ""))
    return 0


def self_test():
    clean = (
        "# 10x10 Storage Units in Austin, TX\n\n"
        "A 10x10 holds a one-bedroom apartment: bed, sofa, dresser, and about 100 "
        "boxes. Our South Austin gate is open 6am to 10pm daily, with a per-tenant "
        "code that logs every entry and exit, 24 recorded cameras, and individually "
        "alarmed units. First month free, plus a one-time $29 admin fee. Units are "
        "climate-controlled and held at 55 to 80 F.\n"
    )
    dirty = (
        "# Storage Units\n\n"
        "Your belongings are safe with us - our facility is 100% secure and "
        "theft-proof. We've never had a break-in. Our insurance covers everything. "
        "Climate-controlled units keep your items dry and prevent mold. First month "
        "free! Only 2 units left, offer ends in 04:59:59. Your rate is locked for "
        "life.\n"
    )
    clean_f = lint(clean, protection_type="protection_plan", humidity_control=True,
                   live_inventory=False, state="TX")
    clean_fails = [f for f in clean_f if f[0] == "FAIL"]
    assert not clean_fails, "clean storage draft should have no FAILs: %s" % clean_fails

    dirty_f = lint(dirty, protection_type="protection_plan", humidity_control=False,
                   live_inventory=False, state="NM")
    codes = {c for _, c, _, _ in dirty_f}
    for expected in ("SS-3", "SS-4", "SS-1", "SS-5", "SS-6", "SS-CV1", "SS-8", "SS-CV2"):
        assert expected in codes, "expected %s in dirty draft, got %s" % (
            expected, sorted(codes))
    # STATE-DEP fires for a non-verified state
    assert "STATE-DEP" in codes, "NM should raise a STATE-DEP note: %s" % sorted(codes)

    # context relaxes the right rules:
    relaxed = lint(
        "Only 2 units left at this price. Your rate won't increase for a year.",
        live_inventory=True, rate_guarantee="12-month no-increase, in writing")
    relaxed_codes = {c for _, c, _, _ in relaxed if _ == "FAIL"} if False else \
        {c for s, c, _, _ in relaxed if s == "FAIL"}
    assert "SS-CV1" not in relaxed_codes, "live inventory should allow scarcity"
    assert "SS-8" not in relaxed_codes, "a real guarantee should allow the rate claim"

    # SS-1: a protection plan may not be called insurance, but the tenant's OWN
    # policy and the honest "not insurance" disclosure are allowed.
    ins_bad = lint("Our protection plan gives you full insurance coverage.",
                   protection_type="protection_plan")
    assert any(c == "SS-1" and s == "FAIL" for s, c, _, _ in ins_bad), \
        "calling the operator's plan insurance must FAIL SS-1: %s" % ins_bad
    ins_ok = lint("A protection plan is required, or bring proof of your own "
                  "renters or homeowners policy. Our plan is not insurance.",
                  protection_type="protection_plan")
    assert not any(c == "SS-1" for _, c, _, _ in ins_ok), \
        "the tenant's own policy + 'not insurance' must NOT fire SS-1: %s" % ins_ok

    print("self-test OK")
    print("  clean draft: 0 fails")
    print("  dirty draft: %d findings, codes: %s"
          % (len(dirty_f), ", ".join(sorted(codes))))
    print("  context relaxation (live-inventory + rate-guarantee): verified")
    return 0


def build_parser():
    p = argparse.ArgumentParser(
        description="Deterministic self-storage compliance + pricing-honesty lint "
                    "(the SS-* overlay rules).")
    p.add_argument("path", nargs="?", default="-",
                   help="path to a markdown/text draft, or '-' for stdin")
    p.add_argument("--brand", help="path to brand.yaml (auto-fills the context flags)")
    p.add_argument("--protection-type", default="unknown",
                   choices=["protection_plan", "licensed_insurance", "none", "unknown"],
                   help="tenant_protection_type (gates SS-1/SS-2)")
    p.add_argument("--humidity-control", action="store_true",
                   help="the facility actually controls humidity (allows SS-5 moisture copy)")
    p.add_argument("--live-inventory", action="store_true",
                   help="the page pulls real live PMS inventory (allows SS-CV1 scarcity)")
    p.add_argument("--rate-guarantee", default="",
                   help="a real contractual rate guarantee text (allows SS-8)")
    p.add_argument("--state", default="", help="client state, e.g. CA (STATE-DEP note)")
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
