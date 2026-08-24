#!/usr/bin/env python3
"""experience_gate.py - Check that Experience is shown with proof, not just claimed.

Offline, stdlib-only (argparse, re, os, sys). No network calls.

Operationalizes Law 16 (Experience must be proven, not asserted). Experience is
the first E of E-E-A-T and the one signal no competitor and no model can scrape,
because it lives only in the operator. It is a moat only when it is SHOWN. So
every falsifiable Experience claim (years in business, review count, project
count, credentials) must resolve to a dated, externally checkable first-party
artifact: an original photo, an invoice-backed count, a permit or license
number, a named team member, or a cited source. A claim with no proving
artifact is a fabrication risk and is cut, never softened.

What it checks
--------------
1. Experience markers present in the draft (the good signals):
     PHOTO        - markdown image or <img> reference to an original asset.
     LICENSE_NUM  - a license or permit NUMBER (letters/digits), not the bare
                    word "licensed".
     NAMED_TEAM   - a role plus a proper name ("our founder Jane Doe").
     CITED_SOURCE - a real external hyperlink backing a claim.
   A page with zero markers fails: it asserts Experience it never shows.

2. Falsifiable Experience CLAIMS, each matched to the proof it needs:
     YEARS_IN_BUSINESS / YEARS_COUNT -> a founding-date artifact.
     REVIEW_COUNT / RATING           -> a review source.
     VOLUME_COUNT (customers/jobs)   -> a count source.
     CREDENTIAL (licensed/certified) -> a license number or credential source.
   Proof is drawn from the draft's concrete artifacts AND, if supplied, a
   proof-manifest / brand.yaml. A bare prose number or year is treated as the
   claim, never as its own proof (that would be circular). Any claim with no
   backing artifact is flagged UNPROVEN_CLAIM and fails the gate.

Doctrine posture: this enforces real E-E-A-T. It never rewards claimed-but-
unproven Experience, and it does not fabricate proof; an unprovable claim is
routed back to the SME interview or cut.

Usage
-----
  python experience_gate.py draft.md
  python experience_gate.py draft.md --manifest clients/acme/brand.yaml
  python experience_gate.py draft.md --manifest proof-manifest.md
  python experience_gate.py --self-test

Exit code: 0 = every claim proven and markers present, 1 = unproven claim(s)
or no Experience markers at all.
"""

import argparse
import os
import re
import sys

# --- Experience markers (concrete proving artifacts in the draft) ------------
IMAGE_RE = re.compile(r"!\[[^\]]*\]\([^)]+\)|<img\b[^>]*>", re.I)
LICENSE_NUM_RE = re.compile(
    r"\b(?:license|licence|lic\.?|permit|reg(?:istration)?\.?|cert(?:ificate)?\.?)\s*"
    r"(?:no\.?|number|#)?\s*[:#]?\s*([A-Za-z]{0,4}-?\d{3,}[A-Za-z0-9-]*)", re.I)
CITED_SOURCE_RE = re.compile(r"\]\(\s*https?://[^)]+\)|(?<!\()\bhttps?://\S+", re.I)
NAMED_TEAM_RE = re.compile(
    r"\b(?:[Oo]ur|[Tt]he|[Mm]eet)\s+"
    r"(?:founder|owner|co-owner|president|principal|lead|master|senior|head|"
    r"technician|electrician|plumber|roofer|contractor|manager)\s+"
    r"([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)")

# --- Falsifiable Experience claims, mapped to the proof each one needs -------
# proof-category tokens: founding_date, review_source, count_source,
# license_permit, credential_source, cited_source.
CLAIM_PATTERNS = [
    ("YEARS_IN_BUSINESS",
     re.compile(r"\b(?:since|established|est\.?|founded|serving[^.]{0,40}?since)\s+(?:19|20)\d{2}\b", re.I),
     {"founding_date", "cited_source"}),
    ("YEARS_COUNT",
     re.compile(r"\b\d{1,3}\+?\s+years?\b(?=[^.\n]{0,40}?(?:experience|in business|serving|of service))", re.I),
     {"founding_date", "cited_source"}),
    ("REVIEW_COUNT",
     re.compile(r"\b\d[\d,]*\s+(?:5[- ]star\s+)?(?:reviews|ratings)\b", re.I),
     {"review_source", "cited_source"}),
    ("RATING",
     re.compile(r"\brated\s+\d(?:\.\d)?\s*(?:stars?|/\s*5|out of\s*5)\b", re.I),
     {"review_source", "cited_source"}),
    ("VOLUME_COUNT",
     re.compile(r"\b(?:over|more than|upwards of)?\s*\d[\d,]*\+?\s+"
                r"(?:customers|clients|homeowners|homes|families|jobs|projects|"
                r"installations|roofs|repairs|patients|customers served)\b", re.I),
     {"count_source", "cited_source"}),
    ("CREDENTIAL",
     re.compile(r"\b(?:licensed|bonded|insured|certified|accredited|"
                r"award[- ]winning|bbb[- ]accredited|epa[- ]certified|nate[- ]certified)\b", re.I),
     {"license_permit", "credential_source", "cited_source"}),
]

# --- Manifest / brand.yaml keyword -> proof category it supplies -------------
MANIFEST_SIGNALS = [
    ("founding_date", re.compile(r"\b(?:established|founded|est\.?|since|year_founded|founding_year|in_business_since)\b", re.I)),
    ("review_source", re.compile(r"\b(?:review|reviews|rating|ratings|testimonial|testimonials|gbp_reviews)\b", re.I)),
    ("count_source", re.compile(r"\b(?:completed|projects|jobs_done|customers|clients|installs|installations|homes_served)\b", re.I)),
    ("license_permit", re.compile(r"\b(?:license|licence|license_no|permit|registration|lic_number)\b", re.I)),
    ("credential_source", re.compile(r"\b(?:certification|certified|accreditation|accredited|award|awards|bbb)\b", re.I)),
    ("photo", re.compile(r"\b(?:photo|photos|image|images|gallery|original_photo)\b", re.I)),
    ("named_team", re.compile(r"\b(?:founder|owner|team|staff|technician|crew_member)\b", re.I)),
]


def find_markers(text):
    """Return {marker: [(lineno, snippet), ...]} for concrete proving artifacts."""
    markers = {"PHOTO": [], "LICENSE_NUM": [], "NAMED_TEAM": [], "CITED_SOURCE": []}
    for i, line in enumerate(text.splitlines(), 1):
        for m in IMAGE_RE.finditer(line):
            markers["PHOTO"].append((i, m.group(0)[:70]))
        for m in LICENSE_NUM_RE.finditer(line):
            markers["LICENSE_NUM"].append((i, m.group(0).strip()[:70]))
        for m in CITED_SOURCE_RE.finditer(line):
            markers["CITED_SOURCE"].append((i, m.group(0)[:70]))
        for m in NAMED_TEAM_RE.finditer(line):
            markers["NAMED_TEAM"].append((i, m.group(0).strip()[:70]))
    return markers


def available_signals(markers, manifest_text):
    """Set of proof-category tokens available from the draft and the manifest."""
    signals = set()
    if markers["PHOTO"]:
        signals.add("photo")
    if markers["LICENSE_NUM"]:
        signals.add("license_permit")
    if markers["NAMED_TEAM"]:
        signals.add("named_team")
    if markers["CITED_SOURCE"]:
        signals.add("cited_source")
    if manifest_text:
        for cat, rx in MANIFEST_SIGNALS:
            if rx.search(manifest_text):
                signals.add(cat)
    return signals


def find_claims(text):
    """Return [(lineno, claim_type, snippet, needed_proof_set), ...]."""
    claims = []
    for i, line in enumerate(text.splitlines(), 1):
        for ctype, rx, needed in CLAIM_PATTERNS:
            for m in rx.finditer(line):
                claims.append((i, ctype, m.group(0).strip()[:70], needed))
    return claims


def evaluate(text, manifest_text=None):
    markers = find_markers(text)
    signals = available_signals(markers, manifest_text)
    claims = find_claims(text)

    marker_total = sum(len(v) for v in markers.values())
    issues = []

    if marker_total == 0:
        issues.append(("ERROR", "NO_EXPERIENCE_MARKERS", 0,
                       "no proving artifact anywhere (no photo, license number, "
                       "named team member, or cited source): Experience is asserted, never shown"))

    for lineno, ctype, snippet, needed in claims:
        if needed & signals:
            continue
        issues.append(("ERROR", "UNPROVEN_CLAIM", lineno,
                       "%s %r has no proving artifact (needs one of: %s)"
                       % (ctype, snippet, ", ".join(sorted(needed)))))

    return {
        "markers": markers,
        "marker_total": marker_total,
        "signals": signals,
        "claims": claims,
        "issues": issues,
    }


def run(args):
    if args.path == "-":
        text = sys.stdin.read()
        src = "<stdin>"
    else:
        with open(args.path, "r", encoding="utf-8") as fh:
            text = fh.read()
        src = args.path

    manifest_text = None
    if args.manifest:
        with open(args.manifest, "r", encoding="utf-8") as fh:
            manifest_text = fh.read()

    result = evaluate(text, manifest_text)
    print("Experience gate for %s" % src)
    if args.manifest:
        print("  proof manifest: %s" % args.manifest)
    print("  Experience markers found: %d  (%s)"
          % (result["marker_total"],
             ", ".join("%s=%d" % (k, len(v)) for k, v in result["markers"].items())))
    print("  falsifiable Experience claims found: %d" % len(result["claims"]))
    print("  proof signals available: %s"
          % (", ".join(sorted(result["signals"])) if result["signals"] else "(none)"))
    print("")

    errors = [i for i in result["issues"] if i[0] == "ERROR"]
    for sev, code, ln, msg in result["issues"]:
        loc = ("line %d" % ln) if ln else "-"
        print("  [%-5s] %-22s %-9s %s" % (sev, code, loc, msg))

    print("")
    if errors:
        print("FAIL  %d unproven-Experience issue(s). Attach a dated artifact to each"
              % len(errors))
        print("      flagged claim (photo, license/permit number, review or count")
        print("      source, named person) or cut the claim. Do not fabricate proof.")
        return 1
    print("PASS  every falsifiable Experience claim resolves to a proving artifact")
    return 0


def self_test():
    good = (
        "# About Acme Roofing\n\n"
        "We have patched roofs across Round Rock since 2004. Our founder Jane Doe "
        "leads a licensed crew (License #TX-48213). Last spring we replaced 42 "
        "squares of hail-damaged shingle on Gattis School Road; the photo below "
        "shows the finished ridge.\n\n"
        "![Finished ridge on Gattis School Road](/img/gattis-ridge.jpg)\n\n"
        "Over 1,200 Williamson County homeowners have trusted us, rated 4.9 out "
        "of 5 across 318 reviews.\n"
    )
    good_manifest = (
        "business_name: Acme Roofing\n"
        "established: 2004\n"
        "license_no: TX-48213\n"
        "reviews: 318\n"
        "avg_rating: 4.9\n"
        "completed_jobs: 1200\n"
        "founder: Jane Doe\n"
        "photos: /img/\n"
    )
    bad = (
        "# About Us\n\n"
        "We are a family-owned company, proudly serving the area since 1998. With "
        "over 25 years of experience and more than 5,000 satisfied customers, our "
        "award-winning team is the most trusted name in town. We are fully "
        "licensed and insured, rated 5 out of 5 across 900 reviews.\n"
    )

    r_good = evaluate(good, good_manifest)
    r_bad = evaluate(bad, None)

    good_errors = [i for i in r_good["issues"] if i[0] == "ERROR"]
    assert not good_errors, "good draft should pass, got: %s" % good_errors
    assert r_good["marker_total"] > 0, "good draft should have Experience markers"

    bad_codes = [c for _, c, _, _ in r_bad["issues"]]
    assert "NO_EXPERIENCE_MARKERS" in bad_codes, (
        "bad draft has no proving artifact and should be flagged: %s" % bad_codes)
    assert bad_codes.count("UNPROVEN_CLAIM") >= 3, (
        "bad draft should flag multiple unproven claims, got: %s" % bad_codes)

    print("self-test OK")
    print("  good draft: %d markers, %d claims, 0 errors (PASS)"
          % (r_good["marker_total"], len(r_good["claims"])))
    print("  bad  draft: %d markers, %d unproven-claim flags (FAIL)"
          % (r_bad["marker_total"], bad_codes.count("UNPROVEN_CLAIM")))
    return 0


def build_parser():
    p = argparse.ArgumentParser(
        description="Flag Experience claims that lack a proving artifact (Law 16).",
    )
    p.add_argument("path", nargs="?", default="-",
                   help="path to the draft markdown/text, or '-' for stdin")
    p.add_argument("--manifest", "--brand",
                   help="optional proof-manifest or brand.yaml supplying proving artifacts")
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
