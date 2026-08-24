#!/usr/bin/env python3
"""review_response_lint.py - quality gate for a batch of review responses.

Offline, stdlib-only (re, argparse, sys, os). No network calls.

It lints a batch of owner-written review responses for the four failure modes
the review-responses playbook forbids:

  1. PII leakage      - a customer email, phone, street address, SSN, or
                        account/invoice-like number surfaced in a public reply.
  2. Keyword stuffing - a service phrase or content word repeated unnaturally
                        inside a single short response (relevance-farming).
  3. Templated near-duplication - responses that share too much wording across
                        the batch (copy-paste sameness the engine and readers
                        both discount), plus identical repeated openings.
  4. Off-voice tells   - corporate/AI boilerplate ("we value your feedback",
                        "your satisfaction is our top priority", etc.).

This is a DETECTOR in the spirit of Doctrine Law 8: it surfaces problems so a
human rewrites more honestly and naturally. It does not rewrite, optimise
toward a number, or evade any detector.

Input format
------------
A markdown/text file containing the batch. Responses are separated either by a
horizontal rule line (`---`) or, failing that, by blank lines. Within each
block, quoted-review context (blockquote `>` lines) and metadata/label lines
(`Review:`, `Rating:`, `Platform:`, `Type:`, `Reviewer:`, `Response:`) are
stripped, so the linter can run directly on the paired responses.md the command
produces and lint only the response text.

Exit code 0 = clean, 1 = any finding (or a file error).

Usage
-----
  python review_response_lint.py responses.md
  python review_response_lint.py --dup-threshold 0.5 responses.md
  cat responses.md | python review_response_lint.py -
  python review_response_lint.py --self-test
"""

import argparse
import os
import re
import sys

EM_DASH = chr(0x2014)  # U+2014, banned by the workspace hook (built, never a literal)

STOPWORDS = {
    "the", "a", "an", "and", "or", "but", "if", "of", "to", "in", "on", "for",
    "with", "at", "by", "from", "up", "about", "into", "over", "after", "is",
    "are", "was", "were", "be", "been", "being", "we", "you", "your", "our",
    "us", "it", "its", "that", "this", "as", "so", "i", "me", "my", "they",
    "them", "their", "he", "she", "his", "her", "im", "youre", "were", "well",
    "get", "got", "had", "has", "have", "do", "did", "not", "no", "yes", "any",
    "all", "out", "back", "again", "here", "there", "when", "how", "what",
    "glad", "thanks", "thank", "really", "very", "one", "will", "can",
}

# Off-voice / corporate-boilerplate tells (case-insensitive substring match).
OFF_VOICE = [
    "we value your feedback",
    "we value your business",
    "your satisfaction is our top priority",
    "your satisfaction is our number one priority",
    "we strive to provide",
    "we strive to offer",
    "we apologize for any inconvenience",
    "sorry for any inconvenience",
    "thank you for choosing",
    "we pride ourselves",
    "exceptional service",
    "we look forward to serving",
    "we look forward to serving all your",
    "valued customer",
    "please do not hesitate",
    "please dont hesitate",
    "we appreciate your business",
    "our team of dedicated professionals",
    "we are committed to providing",
    "top-notch service",
    "second to none",
]

# --- PII patterns. High-confidence PII is ERROR; contactable info is WARN
# because a business's own line in a sign-off can be legitimate. ---
RE_EMAIL = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
RE_SSN = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
RE_PHONE = re.compile(
    r"(?<!\d)(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}(?!\d)")
RE_STREET = re.compile(
    r"\b\d{1,6}\s+(?:[A-Z][A-Za-z]+\.?\s+){1,4}"
    r"(?:Street|St|Avenue|Ave|Road|Rd|Boulevard|Blvd|Lane|Ln|Drive|Dr|"
    r"Court|Ct|Way|Place|Pl|Terrace|Ter|Circle|Cir|Highway|Hwy)\b\.?",
    re.IGNORECASE)
RE_ACCOUNT = re.compile(
    r"\b(?:account|acct|invoice|order|policy|claim|case)\s*(?:#|number|no\.?|num)?\s*"
    r":?\s*[A-Za-z]?\d{4,}\b",
    re.IGNORECASE)
RE_LONGNUM = re.compile(r"(?<!\d)\d{9,}(?!\d)")

LABEL_LINE = re.compile(
    r"^\s*(review|rating|platform|type|reviewer|source|stars?|response|reply)\s*:",
    re.IGNORECASE)


def tokenize(text):
    return re.findall(r"[a-z0-9]+", text.lower())


def clean_response_text(block):
    """Strip headings, quoted-review blockquotes, and metadata/label lines,
    leaving only the owner's response text."""
    out = []
    for line in block.splitlines():
        s = line.strip()
        if not s:
            continue
        if s.startswith("#"):
            continue
        if s.startswith(">"):
            continue
        if LABEL_LINE.match(s):
            # keep any text after a "Response:" label; drop pure metadata
            m = re.match(r"^\s*(response|reply)\s*:\s*(.*)$", s, re.IGNORECASE)
            if m and m.group(2).strip():
                out.append(m.group(2).strip())
            continue
        out.append(s)
    return " ".join(out).strip()


def split_blocks(text):
    """Split the batch into response blocks. Prefer `---` horizontal rules;
    fall back to blank-line-separated paragraphs."""
    hr = re.split(r"(?m)^\s*-{3,}\s*$", text)
    blocks = [clean_response_text(b) for b in hr]
    blocks = [b for b in blocks if b]
    if len(blocks) >= 2:
        return blocks
    # fall back to blank-line paragraphs
    paras = re.split(r"\n\s*\n", text)
    blocks = [clean_response_text(p) for p in paras]
    return [b for b in blocks if b]


def check_pii(text):
    findings = []
    for m in RE_SSN.finditer(text):
        findings.append(("ERROR", "PII_SSN", "SSN-like number: %r" % m.group(0)))
    for m in RE_ACCOUNT.finditer(text):
        findings.append(("ERROR", "PII_ACCOUNT",
                         "account/invoice-like reference: %r" % m.group(0).strip()))
    for m in RE_STREET.finditer(text):
        findings.append(("ERROR", "PII_ADDRESS",
                         "street address: %r" % m.group(0).strip()))
    for m in RE_LONGNUM.finditer(text):
        findings.append(("ERROR", "PII_LONGNUM",
                         "long numeric id (%d digits): %r"
                         % (len(m.group(0)), m.group(0))))
    for m in RE_EMAIL.finditer(text):
        findings.append(("WARN", "PII_EMAIL",
                         "email address %r (confirm it is the business line, "
                         "not the customer's)" % m.group(0)))
    for m in RE_PHONE.finditer(text):
        findings.append(("WARN", "PII_PHONE",
                         "phone number %r (confirm it is the business line, "
                         "not the customer's)" % m.group(0)))
    return findings


def check_stuffing(text):
    """Flag a content word or short phrase repeated unnaturally within one
    short response."""
    findings = []
    tokens = tokenize(text)
    n = len(tokens)
    if n == 0:
        return findings
    # content-word repetition
    counts = {}
    for t in tokens:
        if t in STOPWORDS or len(t) < 3:
            continue
        counts[t] = counts.get(t, 0) + 1
    for word, c in sorted(counts.items(), key=lambda kv: -kv[1]):
        if c >= 3:
            findings.append(("WARN", "STUFFING_WORD",
                             "word %r repeated %d times in a %d-word reply"
                             % (word, c, n)))
    # content bigram repetition (a service phrase repeated is the classic tell)
    content_idx = [i for i, t in enumerate(tokens)
                   if t not in STOPWORDS and len(t) >= 3]
    bigrams = {}
    for i in range(len(tokens) - 1):
        a, b = tokens[i], tokens[i + 1]
        if a in STOPWORDS and b in STOPWORDS:
            continue
        if len(a) < 3 and len(b) < 3:
            continue
        key = a + " " + b
        bigrams[key] = bigrams.get(key, 0) + 1
    for phrase, c in sorted(bigrams.items(), key=lambda kv: -kv[1]):
        if c >= 2:
            findings.append(("WARN", "STUFFING_PHRASE",
                             "phrase %r repeated %d times in one reply"
                             % (phrase, c)))
    return findings


def check_off_voice(text):
    findings = []
    low = re.sub(r"[^a-z0-9\s]", "", text.lower())
    low = re.sub(r"\s+", " ", low)
    for tell in OFF_VOICE:
        needle = re.sub(r"[^a-z0-9\s]", "", tell.lower())
        if needle in low:
            findings.append(("WARN", "OFF_VOICE",
                             "corporate/AI tell: %r" % tell))
    return findings


def shingles(text, k=3):
    tokens = [t for t in tokenize(text)]
    if len(tokens) < k:
        return {" ".join(tokens)} if tokens else set()
    return {" ".join(tokens[i:i + k]) for i in range(len(tokens) - k + 1)}


def jaccard(a, b):
    if not a and not b:
        return 0.0
    inter = len(a & b)
    union = len(a | b)
    return inter / union if union else 0.0


def check_duplication(blocks, threshold):
    """Cross-response similarity: flag pairs above the shingle-Jaccard
    threshold, and openings repeated across many responses."""
    findings = []
    shs = [shingles(b) for b in blocks]
    for i in range(len(blocks)):
        for j in range(i + 1, len(blocks)):
            sim = jaccard(shs[i], shs[j])
            if sim >= threshold:
                findings.append(("ERROR", "NEAR_DUPLICATE",
                                 "responses #%d and #%d are %.0f%% similar "
                                 "(templated); rewrite one to its own review"
                                 % (i + 1, j + 1, 100 * sim)))
    # repeated openings (first 5 tokens)
    openings = {}
    for idx, b in enumerate(blocks):
        toks = tokenize(b)[:5]
        if len(toks) >= 3:
            key = " ".join(toks)
            openings.setdefault(key, []).append(idx + 1)
    for key, idxs in openings.items():
        if len(idxs) >= 3:
            findings.append(("WARN", "TEMPLATED_OPENING",
                             "opening %r reused in responses %s; vary it"
                             % (key, ", ".join("#%d" % i for i in idxs))))
    return findings


def lint(text, dup_threshold=0.6):
    blocks = split_blocks(text)
    per_response = []
    for idx, b in enumerate(blocks):
        f = []
        f += check_pii(b)
        f += check_stuffing(b)
        f += check_off_voice(b)
        if EM_DASH in b:
            f.append(("ERROR", "EM_DASH", "em dash (U+2014) present; use a hyphen"))
        per_response.append((idx + 1, b, f))
    cross = check_duplication(blocks, dup_threshold)
    return blocks, per_response, cross


def report(blocks, per_response, cross):
    n_err = 0
    n_warn = 0
    print("Review-response lint: %d response(s)" % len(blocks))
    print("")
    for num, body, findings in per_response:
        preview = (body[:60] + "...") if len(body) > 60 else body
        if not findings:
            print("  #%d ok    %s" % (num, preview))
            continue
        print("  #%d FLAG  %s" % (num, preview))
        for sev, code, msg in findings:
            if sev == "ERROR":
                n_err += 1
            else:
                n_warn += 1
            print("        [%s] %s - %s" % (sev, code, msg))
    if cross:
        print("")
        print("  cross-response:")
        for sev, code, msg in cross:
            if sev == "ERROR":
                n_err += 1
            else:
                n_warn += 1
            print("        [%s] %s - %s" % (sev, code, msg))
    print("")
    if n_err or n_warn:
        print("FAIL  %d error(s), %d warning(s) - fix the flagged responses and re-run"
              % (n_err, n_warn))
        return 1
    print("PASS  batch is clean (no PII, no stuffing, no near-duplication, on voice)")
    return 0


def run(args):
    if args.path == "-":
        text = sys.stdin.read()
        src = "<stdin>"
    else:
        if not os.path.exists(args.path):
            print("error: file not found: %s" % args.path, file=sys.stderr)
            return 1
        with open(args.path, "r", encoding="utf-8") as fh:
            text = fh.read()
        src = args.path
    blocks, per_response, cross = lint(text, dup_threshold=args.dup_threshold)
    if not blocks:
        print("error: no responses found in %s" % src, file=sys.stderr)
        return 1
    return report(blocks, per_response, cross)


def self_test():
    clean = (
        "Thanks, Denise. Glad Marco got the AC cooling again before the weekend "
        "heat rolled in. Appreciate you trusting us with the install, and we are "
        "a phone call away if the new unit ever needs a look.\n"
        "---\n"
        "Sorry the repair did not go the way it should have, and I understand the "
        "frustration with the timing. That is not the standard we hold ourselves "
        "to. I would like to make it right, so please reach me directly and we "
        "will sort it out. - Ray\n"
    )
    dirty = (
        "Thank you for choosing us, the best emergency plumber Austin. Our "
        "emergency plumber Austin team is here for you. Reach you at "
        "john.doe@example.com or 512-555-0148 about invoice #88213 at 123 Oak "
        "Street.\n"
        "---\n"
        "Thanks so much for the kind words. We are really glad our crew could "
        "get your water heater running again the same day, and we appreciate "
        "you trusting a local team.\n"
        "---\n"
        "Thanks so much for the kind words. We are really glad our crew could "
        "get your water heater running again the same day, and we appreciate "
        "you trusting a local business.\n"
    )

    # clean batch must pass
    b1, pr1, cx1 = lint(clean)
    rc_clean = 0
    for _, _, f in pr1:
        if f:
            rc_clean = 1
    if any(s == "ERROR" for _, _, cf in [(None, None, cx1)] for s, _, _ in cf):
        rc_clean = 1
    assert rc_clean == 0, "clean batch should pass, got findings"

    # dirty batch must flag every category
    b2, pr2, cx2 = lint(dirty)
    codes = set()
    for _, _, f in pr2:
        for _, code, _ in f:
            codes.add(code)
    for _, code, _ in cx2:
        codes.add(code)
    assert any(c.startswith("PII_") for c in codes), "should flag PII, got %s" % codes
    assert "STUFFING_PHRASE" in codes or "STUFFING_WORD" in codes, \
        "should flag stuffing, got %s" % codes
    assert "OFF_VOICE" in codes, "should flag off-voice, got %s" % codes
    assert "NEAR_DUPLICATE" in codes, "should flag near-duplication, got %s" % codes

    print("self-test OK")
    print("  clean batch: PASS (2 responses, no findings)")
    print("  dirty batch flagged: %s" % ", ".join(sorted(codes)))
    return 0


def build_parser():
    p = argparse.ArgumentParser(
        description="Lint a batch of review responses for PII, keyword stuffing, "
                    "templated near-duplication, and off-voice tells.")
    p.add_argument("path", nargs="?", default="-",
                   help="path to a responses batch file, or '-' for stdin")
    p.add_argument("--dup-threshold", type=float, default=0.6,
                   help="shingle-Jaccard similarity above which two responses "
                        "are flagged as near-duplicate (default 0.6)")
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
