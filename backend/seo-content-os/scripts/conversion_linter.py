#!/usr/bin/env python3
"""conversion_linter.py - Deterministic pre-check feeding quality gate G13.

Offline, stdlib-only (re, argparse). No network calls. This is the cheap,
repeatable half of G13 (Conversion readiness); the `conversion-optimizer`
agent reads these flags and applies the human judgment the script cannot:
whether a guarantee is a real mechanism or a hollow badge, whether proof
sits next to its claim, whether a price driver is honest, and whether a
competing CTA is truly co-equal.

Doctrine Law 8: this tool never scores or games AI-detection. Doctrine
Law 20: it flags MISSING conversion craft, never fabricated urgency,
scarcity, or proof - truthfulness of any element is verified by the agent
against brand.yaml, and by gates G10 and G12.

What it flags (each with a line number where one applies, and a severity)
------------------------------------------------------------------------
- MISSING_CLICK_TO_CALL   : no tappable tel: link anywhere (ERROR). Local
                            emergency intent converts by phone.
- NO_CTA                  : no primary lead CTA (call/book/quote/estimate)
                            found at all (ERROR). The page never asks.
- NO_CTA_AFTER_PROOF_FAQ  : a proof and/or FAQ block exists but no lead CTA
                            follows the last of them (ERROR). The scroller
                            who read the whole page meets no ask.
- OFF_GOAL_CTA            : a second, unrelated primary action (newsletter,
                            download, "learn more") competes with the lead
                            goal (WARN). A call-and-form pair is NOT this;
                            it serves URGENT vs CONSIDERED intent.
- WEAK_CTA_VERB           : every lead CTA uses a mechanical verb ("Submit",
                            "Send", bare "Get a quote") with no first-person
                            outcome CTA present (WARN).
- MISSING_PRICE_SIGNAL    : no real price, price band, price driver, or
                            honest custom-quote reason found (WARN).
- MISSING_GUARANTEE       : no risk-reversal / guarantee / warranty keyword
                            found (WARN). The agent decides if the ticket
                            warrants one.

Severity: ERROR (fails the gate) or WARN (advisory; fails exit code only
with --strict). By default any ERROR sets exit code 1.

Usage
-----
  python conversion_linter.py draft.md
  python conversion_linter.py --intent urgent draft.md
  echo "Call now [call](tel:5125550100)" | python conversion_linter.py -
  python conversion_linter.py --strict draft.md
  python conversion_linter.py --self-test
"""

import argparse
import re
import sys

EM_DASH = chr(0x2014)  # U+2014, banned by the workspace hook (built, never a literal)

# A tel: click-to-call in any form: [text](tel:...) or a bare tel: token.
TEL_RE = re.compile(r"tel:\s*\+?[\d\-\s().]{5,}", re.IGNORECASE)

# Primary lead-goal CTA cues (call / book / request a quote|estimate|consult).
LEAD_CTA_RES = [
    re.compile(r"\bcall (us |now|today|our )", re.IGNORECASE),
    re.compile(r"\b(tap|click) to call\b", re.IGNORECASE),
    re.compile(r"\bcall\b[^.\n]{0,30}\btel:", re.IGNORECASE),
    re.compile(r"\b(book|schedule|reserve|request)\b[^.\n]{0,40}"
               r"(quote|estimate|consult|appointment|inspection|visit|call|service|now|today|online)",
               re.IGNORECASE),
    re.compile(r"\b(get|claim|start|grab|schedule|book|reserve)\s+(my|your|a|an)\b"
               r"[^.\n]{0,40}(quote|estimate|inspection|consult|appointment|visit|project|repair|booking|spot)",
               re.IGNORECASE),
    re.compile(r"\bcontact us\b", re.IGNORECASE),
    re.compile(r"\bget started\b", re.IGNORECASE),
    re.compile(r"\bsubmit\b[^.\n]{0,30}(info|details|form|request|your)", re.IGNORECASE),
]

# First-person / outcome CTA verb: "get my free inspection", "book my consult".
STRONG_VERB_RE = re.compile(
    r"\b(get|claim|book|schedule|reserve|start|grab)\s+(my|your)\b"
    r"[^.\n]{0,40}(quote|estimate|inspection|consult|appointment|visit|project|"
    r"repair|booking|spot|plan|design)",
    re.IGNORECASE)
# A call CTA is a strong, direct action in its own right.
CALL_VERB_RE = re.compile(r"\b(call|tap to call|click to call)\b", re.IGNORECASE)

# Mechanical / low-agency CTA verbs.
MECHANICAL_RES = [
    re.compile(r"\bsubmit\b", re.IGNORECASE),
    re.compile(r"\bsend\b", re.IGNORECASE),
    re.compile(r"\bcontact us\b", re.IGNORECASE),
    re.compile(r"\bget started\b", re.IGNORECASE),
    re.compile(r"\bget a quote\b", re.IGNORECASE),
    re.compile(r"\bclick here\b", re.IGNORECASE),
]

# Off-goal CTAs that split intent away from the one lead goal.
OFF_GOAL_RES = [
    re.compile(r"\bsubscribe\b", re.IGNORECASE),
    re.compile(r"\bsign\s?up\b", re.IGNORECASE),
    re.compile(r"\bnewsletter\b", re.IGNORECASE),
    re.compile(r"\bdownload\b", re.IGNORECASE),
    re.compile(r"\bjoin our\b", re.IGNORECASE),
    re.compile(r"\bfollow us\b", re.IGNORECASE),
    re.compile(r"\blearn more\b", re.IGNORECASE),
    re.compile(r"\bread more\b", re.IGNORECASE),
    re.compile(r"\bshop now\b", re.IGNORECASE),
    re.compile(r"\badd to cart\b", re.IGNORECASE),
]

# A real price, price band, price driver, or honest custom-quote reason.
PRICE_RES = [
    re.compile(r"\$\s?\d"),
    re.compile(r"\b\d+(\.\d+)?\s?%\s?(apr|off|financing)", re.IGNORECASE),
    re.compile(r"\bfree\s+(estimate|inspection|quote|consult|consultation|assessment)",
               re.IGNORECASE),
    re.compile(r"\bno\s+(service\s+)?fee\b", re.IGNORECASE),
    re.compile(r"\b(0%|zero)\s+(apr|interest|down)", re.IGNORECASE),
    re.compile(r"\b(starting at|flat rate|per hour|per visit|priced per|"
               r"custom quote|quote depends|quoted upfront|upfront pricing)\b",
               re.IGNORECASE),
]

# Risk-reversal / guarantee keywords.
GUARANTEE_RES = [
    re.compile(r"\bguarantee(d|s)?\b", re.IGNORECASE),
    re.compile(r"\bwarrant(y|ies)\b", re.IGNORECASE),
    re.compile(r"\bmoney[\s-]?back\b", re.IGNORECASE),
    re.compile(r"\brefund\b", re.IGNORECASE),
    re.compile(r"\bno\s+fee\b", re.IGNORECASE),
    re.compile(r"\bno\s+hidden\b", re.IGNORECASE),
    re.compile(r"\bon[\s-]?time\b", re.IGNORECASE),
    re.compile(r"\bno\s+obligation\b", re.IGNORECASE),
    re.compile(r"\bre[\s-]?inspection\b", re.IGNORECASE),
    re.compile(r"\bsatisfaction\b", re.IGNORECASE),
]

# Section anchors: proof block and FAQ block, detected by heading text.
PROOF_HEAD_RE = re.compile(
    r"review|testimonial|what .*\bsay\b|our clients|trusted by|"
    r"neighbors say|customers say|\bproof\b", re.IGNORECASE)
FAQ_HEAD_RE = re.compile(
    r"\bfaq\b|frequently asked|common questions|\bquestions\b", re.IGNORECASE)
HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s+(.*\S)\s*$")


def split_lines(text):
    return text.splitlines()


def find_headings(lines):
    heads = []
    in_fence = False
    for i, line in enumerate(lines, 1):
        if line.strip().startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        m = HEADING_RE.match(line)
        if m:
            heads.append((m.group(1).strip(), i))
    return heads


def is_lead_cta(line):
    return any(rx.search(line) for rx in LEAD_CTA_RES)


def is_strong_cta(line):
    return bool(STRONG_VERB_RE.search(line) or
                (CALL_VERB_RE.search(line) and not _only_mechanical(line)))


def _only_mechanical(line):
    # a "call ... submit" edge: treat a real call action as strong regardless.
    return False


def is_mechanical_cta(line):
    return any(rx.search(line) for rx in MECHANICAL_RES)


def find_off_goal(lines):
    hits = []
    for i, line in enumerate(lines, 1):
        for rx in OFF_GOAL_RES:
            if rx.search(line):
                hits.append((i, rx.pattern))
                break
    return hits


def has_any(text, regexes):
    return any(rx.search(text) for rx in regexes)


def lint(text):
    lines = split_lines(text)
    joined = "\n".join(lines)
    issues = []

    # 1. Click-to-call.
    if not TEL_RE.search(joined):
        issues.append(("ERROR", "MISSING_CLICK_TO_CALL", 0,
                       "no tappable tel: link found (mobile local intent converts by phone)"))

    # 2. Lead CTAs + verb quality.
    lead_lines = [i for i, ln in enumerate(lines, 1) if is_lead_cta(ln)]
    strong_lines = [i for i, ln in enumerate(lines, 1) if is_strong_cta(ln)]
    if not lead_lines:
        issues.append(("ERROR", "NO_CTA", 0,
                       "no primary lead CTA (call/book/request a quote|estimate|consult) found"))
    elif not strong_lines:
        mech = next((i for i in lead_lines if is_mechanical_cta(lines[i - 1])), lead_lines[0])
        issues.append(("WARN", "WEAK_CTA_VERB", mech,
                       "every lead CTA is mechanical; use a first-person outcome verb "
                       "(\"Get my free estimate\", not \"Submit\")"))

    # 3. CTA after the proof and FAQ blocks.
    heads = find_headings(lines)
    proof_line = next((ln for txt, ln in heads if PROOF_HEAD_RE.search(txt)), None)
    faq_line = next((ln for txt, ln in heads if FAQ_HEAD_RE.search(txt)), None)
    anchors = [a for a in (proof_line, faq_line) if a]
    if lead_lines and anchors:
        anchor = max(anchors)
        if not any(c > anchor for c in lead_lines):
            which = " and ".join(
                w for w, a in (("proof", proof_line), ("FAQ", faq_line)) if a)
            issues.append(("ERROR", "NO_CTA_AFTER_PROOF_FAQ", anchor,
                           "no lead CTA after the %s block; add the closing ask" % which))

    # 4. Off-goal competing CTAs.
    seen_off = set()
    for ln, pat in find_off_goal(lines):
        key = pat
        if key in seen_off:
            continue
        seen_off.add(key)
        issues.append(("WARN", "OFF_GOAL_CTA", ln,
                       "off-goal action %r competes with the lead goal "
                       "(a call-and-form pair does not; a newsletter/download does)"
                       % pat.strip("\\b")))

    # 5. Price signal.
    if not has_any(joined, PRICE_RES):
        issues.append(("WARN", "MISSING_PRICE_SIGNAL", 0,
                       "no price, price band, price driver, or honest custom-quote reason "
                       "(bare \"contact us for pricing\" is a fail)"))

    # 6. Guarantee / risk-reversal.
    if not has_any(joined, GUARANTEE_RES):
        issues.append(("WARN", "MISSING_GUARANTEE", 0,
                       "no risk-reversal/guarantee keyword; add a real one where the ticket warrants it"))

    return issues


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

    lines = split_lines(text)
    issues = lint(text)

    print("Conversion lint for %s" % src)
    if args.intent:
        lead = "phone / click-to-call" if args.intent == "urgent" else "form / scheduler"
        print("  intent=%s -> primary CTA should lead with the %s (playbook)" % (args.intent, lead))
    errors = [i for i in issues if i[0] == "ERROR"]
    warns = [i for i in issues if i[0] == "WARN"]
    print("  %d error(s), %d warning(s)" % (len(errors), len(warns)))
    for sev, code, ln, msg in issues:
        loc = ("line %d" % ln) if ln else "-"
        print("  [%-5s] %-22s %-9s %s" % (sev, code, loc, msg))
        ctx = context_line(lines, ln)
        if ctx:
            print("            > %s" % ctx)

    print("")
    print("Judgment left to the conversion-optimizer agent (G13): whether a guarantee is a")
    print("real mechanism or a hollow badge, whether proof sits next to its claim or is")
    print("pooled, whether the price driver is honest, and whether an OFF_GOAL_CTA is truly")
    print("co-equal. All conversion elements must be truthful (Law 20).")

    print("")
    fail = bool(errors) or (args.strict and bool(warns))
    if fail:
        print("FAIL  fix errors%s before this draft clears G13"
              % (" and warnings" if args.strict else ""))
        return 1
    print("PASS  no blocking conversion issues" + (" (warnings advisory)" if warns else ""))
    return 0


def self_test():
    good = (
        "# Emergency Plumber in Round Rock, TX - On-Site Same Day\n\n"
        "Burst pipe flooding your kitchen? Call our licensed Round Rock crew now and we "
        "are on site the same day. [Call 512-555-0100](tel:5125550100)\n\n"
        "Most drain cleanings run $89 to $150, and your first local estimate is free.\n\n"
        "## What our Round Rock neighbors say\n\n"
        "\"They arrived in 40 minutes and fixed the leak for the price they quoted.\" - Maria G\n\n"
        "We back every repair with a written workmanship warranty, and there is no service "
        "fee if we cannot help.\n\n"
        "## Frequently asked questions\n\n"
        "### How fast can you arrive?\n\n"
        "On-site same day across Round Rock and Georgetown.\n\n"
        "[Get my free estimate](tel:5125550100)\n"
    )
    bad = (
        "# Plumber\n\n"
        "We do plumbing. Contact us for pricing. Submit your info and we will get back "
        "to you.\n\n"
        "## Reviews\n\n"
        "Great service. Five stars.\n\n"
        "## FAQ\n\n"
        "### Do you offer service?\n\n"
        "Yes.\n\n"
        "Subscribe to our newsletter for tips!\n"
    )
    good_issues = lint(good)
    good_errors = [i for i in good_issues if i[0] == "ERROR"]
    bad_issues = lint(bad)
    bad_codes = {c for _, c, _, _ in bad_issues}

    assert not good_errors, "good draft should have no errors: %s" % good_errors
    for expected in ("MISSING_CLICK_TO_CALL", "WEAK_CTA_VERB", "OFF_GOAL_CTA",
                     "MISSING_PRICE_SIGNAL", "MISSING_GUARANTEE",
                     "NO_CTA_AFTER_PROOF_FAQ"):
        assert expected in bad_codes, "expected %s in bad draft, got %s" % (
            expected, sorted(bad_codes))
    # Guard: the em-dash character must never appear in this file's own output.
    assert EM_DASH not in "".join(m for _, _, _, m in good_issues + bad_issues)
    print("self-test OK")
    print("  good draft: %d issues, 0 errors" % len(good_issues))
    print("  bad draft:  %d issues, codes: %s" % (len(bad_issues), ", ".join(sorted(bad_codes))))
    return 0


def build_parser():
    p = argparse.ArgumentParser(
        description="Deterministic conversion pre-check feeding quality gate G13.",
    )
    p.add_argument("path", nargs="?", default="-",
                   help="path to a markdown/text draft, or '-' for stdin")
    p.add_argument("--intent", choices=["urgent", "considered"],
                   help="page intent; prints which CTA should lead (informational)")
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
