#!/usr/bin/env python3
"""geo_page_linter.py - Score a draft on the evidenced GEO citation levers.

Offline, stdlib-only (re, argparse, os, sys). No network calls.

Operationalizes Law 17 and the Local AI-Citation Stack
(knowledge/foundations/geo-ai-citation.md). It scores a local page draft on the
page-controllable levers that the Princeton GEO study and the 2026 per-engine
research show move AI citation, and flags the one tactic that hurts it.

Levers scored (Track A of the citation stack)
---------------------------------------------
1. Direct-answer-first H2s: does each H2 open with a real answer, not filler?
   (passage-block protocol). Filler openers are the #1 reason a block is not
   extractable.
2. Statistic density: concrete numbers per 100 words. Statistics Addition was a
   top mover in the GEO study; a local page's own numbers are also first-hand
   Experience markers (Law 16).
3. Source presence: cited sources / links backing contestable claims
   (Cite Sources lever).
4. Operator/expert quote presence: a real quote was the single highest mover in
   the GEO study, and doubles as a first-hand marker.
5. Keyword-stuffing flag: the ONLY tactic that reduced citation in the study,
   and a compliance-rule-B3 spam signal. Self-contained (no keyword list needed):
   flags the most-repeated meaningful phrase if its density is over the ceiling.
6. Freshness signal: a visible last-updated stamp keeps citation eligibility,
   but only when earned by a real delta (Law 19; this checks presence, not the
   delta, which /refresh + decay_monitor.py own).

This is a DRAFT-TIME advisor in the spirit of Law 8. It surfaces where a page is
weak on the evidenced levers so a human writes a stronger, more specific page. It
does NOT rewrite, optimise toward a number, or game any detector. AI-detector
evasion is forbidden here; see doctrine Law 8 and Truth 8.

Exit code 0 = all levers pass, 1 = one or more levers below target.

Usage
-----
  python geo_page_linter.py draft.md
  python geo_page_linter.py --min-stat-density 1.5 --min-quotes 1 draft.md
  cat draft.md | python geo_page_linter.py -
  python geo_page_linter.py --self-test
"""

import argparse
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from readability_scorer import strip_markdown, split_sentences  # stdlib-only

# Curly quotes built via chr() so this source file stays pure ASCII.
_LQ = chr(0x201C)
_RQ = chr(0x201D)

STAT_RE = re.compile(
    r"\$\s?\d[\d,]*(?:\.\d+)?"        # currency: $1,400 / $ 3,200.50
    r"|\b\d+(?:\.\d+)?\s?%"           # percentage: 25% / 4.3 %
    r"|\b\d[\d,]*(?:\.\d+)?\b"        # any standalone number: 40, 2018, 150
)

# Filler openers: the anti-direct-answer tells from the passage-block protocol.
FILLER_OPENERS = [
    r"there are (?:several|many|a number of|various|multiple)",
    r"when it comes to",
    r"every (?:home|business|situation|project|customer|client) is",
    r"it is important to",
    r"it'?s important to",
    r"in today'?s",
    r"we understand that",
    r"have you ever",
    r"as a (?:homeowner|business owner|property owner)",
    r"one of the (?:most|biggest|best)",
    r"first and foremost",
    r"in this (?:article|section|guide|post|page)",
    r"let'?s (?:take a look|dive|explore|discuss)",
    r"if you'?re like most",
    r"whether you",
    r"there'?s no doubt",
]
FILLER_RE = re.compile(r"^\W*(?:%s)" % "|".join(FILLER_OPENERS), re.IGNORECASE)

# Source / citation cues in the RAW markdown (before links are stripped).
MD_LINK_RE = re.compile(r"\[[^\]]+\]\((?:https?://|/)[^)]+\)")
BARE_URL_RE = re.compile(r"(?<!\()\bhttps?://[^\s)]+")
CITE_CUE_RE = re.compile(
    r"\b(?:according to|source:|sources:|per the|as reported by|data from|"
    r"citing|cited by)\b",
    re.IGNORECASE,
)

# Attributed-quote span: text inside straight or curly double quotes.
QUOTE_RE = re.compile(
    r'["%s]([^"%s]{18,}?)["%s]' % (_LQ, _RQ, _RQ)
)

FRESHNESS_RE = re.compile(
    r"(?:last[\s-]*updated|updated(?:\s+on)?|reviewed(?:\s+on)?|as of)"
    r"[:\s][^\n]{0,40}?(?:19|20)\d{2}"
    r"|\b(?:19|20)\d\d-\d\d-\d\d\b",
    re.IGNORECASE,
)

STOPWORDS = {
    "the", "a", "an", "and", "or", "of", "to", "in", "on", "for", "with", "at",
    "by", "is", "are", "we", "you", "your", "our", "it", "that", "this", "as",
    "be", "can", "will", "from", "us", "has", "have", "do", "does", "if", "so",
}


def words_of(text):
    return re.findall(r"[A-Za-z]+(?:'[A-Za-z]+)?", text)


def split_h2_sections(raw):
    """Return list of (heading_text, body_text) for each H2 (## ) block.

    Level-3+ headings stay inside their parent H2's body. Content before the
    first H2 is returned under an empty heading and is not scored for the
    direct-answer rule (it is the intro, not an answer block)."""
    lines = raw.splitlines()
    sections = []
    current_head = None
    current_body = []
    preamble = []
    for line in lines:
        m = re.match(r"^##(?!#)\s+(.*)$", line)
        if m:
            if current_head is not None:
                sections.append((current_head, "\n".join(current_body)))
            current_head = m.group(1).strip()
            current_body = []
        else:
            if current_head is None:
                preamble.append(line)
            else:
                current_body.append(line)
    if current_head is not None:
        sections.append((current_head, "\n".join(current_body)))
    return sections


def first_sentence(text):
    clean = strip_markdown(text).strip()
    if not clean:
        return ""
    sents = split_sentences(clean)
    return sents[0].strip() if sents else ""


def opens_with_direct_answer(heading, body):
    """A block passes if its first sentence is not a filler opener and carries
    a concrete anchor (a number, a Yes/No answer, or a proper-noun specific)."""
    fs = first_sentence(body)
    if not fs:
        return False, "empty (no answer under the heading)"
    if FILLER_RE.match(fs):
        return False, "opens with filler (%s...)" % fs[:40]
    has_number = bool(STAT_RE.search(fs))
    yes_no = bool(re.match(r"^\W*(?:yes|no)\b", fs, re.IGNORECASE))
    # A proper-noun specific (a capitalised word past position 0) is a weak
    # positive: it usually means a real place/code/brand is being named.
    tokens = fs.split()
    proper = any(re.match(r"^[A-Z][a-z]+", t) for t in tokens[1:])
    if has_number or yes_no or proper:
        return True, "direct answer"
    return False, "no concrete anchor in the opening sentence"


def top_repeated_phrase(tokens, ns=(4, 3, 2)):
    """Find the highest-density repeated meaningful phrase across n-gram sizes.

    Returns (phrase, occurrences, density) for the worst offender, or
    (None, 0, 0.0). A phrase must occur >=3 times and contain a non-stopword."""
    total = max(1, len(tokens))
    best = (None, 0, 0.0)
    for n in ns:
        counts = {}
        for i in range(len(tokens) - n + 1):
            gram = tokens[i:i + n]
            if all(t in STOPWORDS for t in gram):
                continue
            key = " ".join(gram)
            counts[key] = counts.get(key, 0) + 1
        for phrase, occ in counts.items():
            if occ < 3:
                continue
            density = (occ * n) / total
            if density > best[2]:
                best = (phrase, occ, density)
    return best


def analyse(raw, min_stat_density=1.0, min_sources=1, min_quotes=1,
            max_phrase_density=0.025):
    stripped = strip_markdown(raw)
    words = words_of(stripped)
    total_words = max(1, len(words))
    tokens = re.findall(r"[a-z0-9]+", stripped.lower())

    # Lever 1: direct-answer-first H2s
    sections = split_h2_sections(raw)
    h2_results = []
    for head, body in sections:
        ok, reason = opens_with_direct_answer(head, body)
        h2_results.append({"heading": head, "ok": ok, "reason": reason})
    n_h2 = len(h2_results)
    n_h2_ok = sum(1 for r in h2_results if r["ok"])

    # Lever 2: statistic density
    stat_count = len(STAT_RE.findall(stripped))
    stat_density = 100.0 * stat_count / total_words

    # Lever 3: sources
    source_count = (len(MD_LINK_RE.findall(raw))
                    + len(BARE_URL_RE.findall(raw))
                    + len(CITE_CUE_RE.findall(raw)))

    # Lever 4: attributed quotes (a quoted span of >= 4 words)
    quote_count = sum(1 for q in QUOTE_RE.findall(raw)
                      if len(q.split()) >= 4)

    # Lever 5: keyword-stuffing
    phrase, phrase_occ, phrase_density = top_repeated_phrase(tokens)
    stuffed = phrase_density > max_phrase_density

    # Lever 6: freshness stamp
    has_freshness = bool(FRESHNESS_RE.search(raw))

    return {
        "total_words": total_words,
        "h2": h2_results,
        "n_h2": n_h2,
        "n_h2_ok": n_h2_ok,
        "stat_count": stat_count,
        "stat_density": stat_density,
        "min_stat_density": min_stat_density,
        "source_count": source_count,
        "min_sources": min_sources,
        "quote_count": quote_count,
        "min_quotes": min_quotes,
        "stuffed": stuffed,
        "stuff_phrase": phrase,
        "stuff_occ": phrase_occ,
        "stuff_density": phrase_density,
        "max_phrase_density": max_phrase_density,
        "has_freshness": has_freshness,
    }


def evaluate(m):
    """Return (list_of_failures) given an analyse() result."""
    fails = []
    if m["n_h2"] == 0:
        fails.append("no H2 passage blocks found (page is not a federation of "
                     "extractable answers)")
    elif m["n_h2_ok"] < m["n_h2"]:
        weak = [r["heading"] or "(untitled)" for r in m["h2"] if not r["ok"]]
        fails.append("%d of %d H2 blocks do not open with a direct answer: %s"
                     % (m["n_h2"] - m["n_h2_ok"], m["n_h2"],
                        "; ".join(weak[:5])))
    if m["stat_density"] < m["min_stat_density"]:
        fails.append("statistic density %.2f per 100 words is below target %.2f "
                     "(replace vague claims with concrete numbers)"
                     % (m["stat_density"], m["min_stat_density"]))
    if m["source_count"] < m["min_sources"]:
        fails.append("only %d cited source(s), target %d (name a source for each "
                     "contestable claim)" % (m["source_count"], m["min_sources"]))
    if m["quote_count"] < m["min_quotes"]:
        fails.append("only %d operator/expert quote(s), target %d (harvest a real "
                     "quote in the SME interview)"
                     % (m["quote_count"], m["min_quotes"]))
    if m["stuffed"]:
        fails.append('keyword stuffing: "%s" repeats %dx (%.1f%% density, over '
                     "%.1f%% ceiling); rewrite for variety"
                     % (m["stuff_phrase"], m["stuff_occ"],
                        100 * m["stuff_density"], 100 * m["max_phrase_density"]))
    if not m["has_freshness"]:
        fails.append("no visible last-updated stamp (add one, earned by a real "
                     "content delta per Law 19)")
    return fails


def run(args):
    if args.path == "-":
        raw = sys.stdin.read()
        src = "<stdin>"
    else:
        with open(args.path, "r", encoding="utf-8") as fh:
            raw = fh.read()
        src = args.path

    m = analyse(raw, min_stat_density=args.min_stat_density,
                min_sources=args.min_sources, min_quotes=args.min_quotes,
                max_phrase_density=args.max_phrase_density)

    print("GEO citation-lever report for %s" % src)
    print("  words:                 %d" % m["total_words"])
    print("  H2 direct-answer:      %d/%d blocks open with an answer"
          % (m["n_h2_ok"], m["n_h2"]))
    for r in m["h2"]:
        mark = "ok  " if r["ok"] else "WEAK"
        print("      [%s] %s -- %s"
              % (mark, (r["heading"] or "(untitled)")[:48], r["reason"]))
    print("  statistic density:     %.2f per 100 words (%d stats; target %.2f)"
          % (m["stat_density"], m["stat_count"], m["min_stat_density"]))
    print("  cited sources:         %d (target %d)"
          % (m["source_count"], m["min_sources"]))
    print("  operator/expert quotes:%d (target %d)"
          % (m["quote_count"], m["min_quotes"]))
    if m["stuff_phrase"]:
        print('  most-repeated phrase:  "%s" x%d (%.1f%%)'
              % (m["stuff_phrase"], m["stuff_occ"], 100 * m["stuff_density"]))
    else:
        print("  most-repeated phrase:  none over 3x")
    print("  freshness stamp:       %s" % ("present" if m["has_freshness"]
                                           else "MISSING"))

    fails = evaluate(m)
    print("")
    if not fails:
        print("PASS  all GEO citation levers meet target")
        return 0
    print("FAIL  %d lever(s) below target:" % len(fails))
    for f in fails:
        print("  - %s" % f)
    return 1


GOOD_DRAFT = """## How much does water heater replacement cost in Tempe?

Replacing a standard 40-to-50-gallon tank water heater in Tempe typically runs
$1,400 to $2,600 installed, and a tankless unit runs $3,200 to $5,500. According
to the [2018 International Plumbing Code](https://example.com/ipc), an expansion
tank is required on older installs, which adds $180 to $350.

Our lead plumber puts it plainly: "In 1920s Highland Park homes we almost always
find the gas line predates current code." A like-for-like tank swap is a same-day
job, usually 2 to 3 hours on site.

## Do I need a permit to replace my roof in Austin?

Yes. The City of Austin requires a building permit for a full roof replacement on
almost every home, and re-roofing without one can force a tear-off at your cost
during a future sale.

Last updated: June 2026.
"""

BAD_DRAFT = """## Water Heater Replacement Pricing

When it comes to replacing your water heater, there are several factors to
consider. Emergency plumber Austin is the best emergency plumber Austin. For an
emergency plumber Austin, call the emergency plumber Austin team today.

## About Our Service

Every home is different, and we pride ourselves on customer satisfaction and
quality workmanship on every job we take.
"""


def self_test():
    good = analyse(GOOD_DRAFT)
    bad = analyse(BAD_DRAFT)

    # Good draft passes cleanly.
    assert not evaluate(good), "good draft should pass, got: %s" % evaluate(good)
    # Bad draft fails.
    assert evaluate(bad), "bad draft should fail"

    # Lever-level checks.
    assert good["stat_count"] > 0, "good draft should have statistics"
    assert bad["stat_count"] == 0, "bad draft should have no statistics"
    assert good["n_h2_ok"] == good["n_h2"], "good H2s should all be direct"
    assert bad["n_h2_ok"] == 0, "both bad H2s open with filler"
    assert good["source_count"] >= 1, "good draft has a cited source"
    assert bad["source_count"] == 0, "bad draft has no source"
    assert good["quote_count"] >= 1, "good draft has an operator quote"
    assert bad["quote_count"] == 0, "bad draft has no quote"
    assert bad["stuffed"], "bad draft should flag keyword stuffing"
    assert not good["stuffed"], "good draft should not flag stuffing"
    assert good["has_freshness"], "good draft has a freshness stamp"
    assert not bad["has_freshness"], "bad draft has no freshness stamp"

    print("self-test OK")
    print("  good draft: %d/%d direct H2s, %.1f stats/100w, %d sources, "
          "%d quotes, stuffed=%s, fresh=%s"
          % (good["n_h2_ok"], good["n_h2"], good["stat_density"],
             good["source_count"], good["quote_count"], good["stuffed"],
             good["has_freshness"]))
    print("  bad draft:  %d/%d direct H2s, %.1f stats/100w, %d sources, "
          "%d quotes, stuffed=%s, fresh=%s"
          % (bad["n_h2_ok"], bad["n_h2"], bad["stat_density"],
             bad["source_count"], bad["quote_count"], bad["stuffed"],
             bad["has_freshness"]))
    return 0


def build_parser():
    p = argparse.ArgumentParser(
        description="Score a local-page draft on the evidenced GEO citation levers.",
    )
    p.add_argument("path", nargs="?", default="-",
                   help="path to a markdown/text draft, or '-' for stdin")
    p.add_argument("--min-stat-density", type=float, default=1.0,
                   help="min statistics per 100 words (default 1.0)")
    p.add_argument("--min-sources", type=int, default=1,
                   help="min cited sources / links (default 1)")
    p.add_argument("--min-quotes", type=int, default=1,
                   help="min operator/expert quotes (default 1)")
    p.add_argument("--max-phrase-density", type=float, default=0.025,
                   help="keyword-stuffing ceiling as a fraction (default 0.025)")
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
