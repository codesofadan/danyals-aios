#!/usr/bin/env python3
"""nap_checker.py - Verify Name, Address, Phone consistency across page copy.

Offline, stdlib-only (re, argparse; optional yaml). No network calls.

Why this exists
---------------
NAP (Name, Address, Phone) must be byte-consistent everywhere it appears, and
consistent with the Google Business Profile. Silent variants (a different phone
format, an abbreviated street, "St." vs "Street") fracture local ranking
signals. This tool holds a canonical NAP and checks one or more page/text files
against it.

What it checks per file
-----------------------
- NAME present exactly as canonical.
- PHONE present. Digits compared canonically (country/area/number), so a match
  on digits with a *different display format* is reported as a formatting
  variant, not a hard miss. An entirely absent or wrong-number phone is a miss.
- ADDRESS street + city + region + postal present. Common abbreviation variants
  (Street/St, Avenue/Ave, Suite/Ste, etc.) are detected and flagged as variants
  rather than misses so you can decide whether to normalise.

Canonical NAP source (either):
  --brand path/to/brand.yaml   (reads nap: block; needs PyYAML, degrades to a
                                tiny built-in parser for the flat nap: fields)
  or explicit flags: --name --phone --street --city --region --postal

Exit code 0 = every file fully consistent, 1 = any miss or variant found.

Usage
-----
  python nap_checker.py --brand clients/acme/brand.yaml page1.md page2.md
  python nap_checker.py --name "Acme Plumbing" --phone "+1-512-555-0100" \
      --street "100 Congress Ave" --city Austin --region TX --postal 78701 page.md
  python nap_checker.py --self-test
"""

import argparse
import os
import re
import sys

ABBREV = {
    "street": ["st", "st."],
    "avenue": ["ave", "ave."],
    "boulevard": ["blvd", "blvd."],
    "road": ["rd", "rd."],
    "drive": ["dr", "dr."],
    "lane": ["ln", "ln."],
    "suite": ["ste", "ste."],
    "apartment": ["apt", "apt."],
    "north": ["n", "n."],
    "south": ["s", "s."],
    "east": ["e", "e."],
    "west": ["w", "w."],
    "highway": ["hwy", "hwy."],
    "parkway": ["pkwy", "pkwy."],
}
# reverse lookup: token -> canonical word
_ABBREV_REV = {}
for _full, _abbrs in ABBREV.items():
    for _a in _abbrs:
        _ABBREV_REV[_a] = _full
    _ABBREV_REV[_full] = _full


def digits_only(phone):
    return re.sub(r"\D", "", phone or "")


def same_number(a, b):
    """True if two digit strings are the same phone, tolerating a country-code
    prefix (e.g. '15125550100' vs '5125550100')."""
    a, b = digits_only(a), digits_only(b)
    if not a or not b:
        return False
    if a == b:
        return True
    lo, hi = sorted((a, b), key=len)
    return len(lo) >= 7 and hi.endswith(lo)


def contains_word(text, phrase):
    """Word-boundary exact-substring test so 'Ave' does not match 'Avenue'."""
    if not phrase:
        return False
    return re.search(r"(?<!\w)" + re.escape(phrase) + r"(?!\w)", text) is not None


def normalise_tokens(text):
    """Lowercase, expand known street abbreviations, collapse whitespace."""
    toks = re.findall(r"[a-z0-9]+", (text or "").lower())
    return [_ABBREV_REV.get(t, t) for t in toks]


def load_brand_nap(path):
    """Read the nap: block from brand.yaml. Uses PyYAML if available, else a
    minimal indent-aware parser for the flat fields this tool needs."""
    with open(path, "r", encoding="utf-8") as fh:
        raw = fh.read()
    nap = {}
    try:
        import yaml  # optional
        data = yaml.safe_load(raw) or {}
        block = data.get("nap", {}) or {}
        nap["name"] = block.get("name", "")
        nap["phone"] = block.get("phone", "")
        nap["street"] = block.get("street", "")
        nap["city"] = block.get("city", "")
        nap["region"] = block.get("state_region", "")
        nap["postal"] = block.get("postal_code", "")
        return nap
    except ImportError:
        pass  # fall through to the tiny parser

    # Minimal parser: find the "nap:" line, read indented "key: value" pairs.
    lines = raw.splitlines()
    in_nap = False
    field_map = {
        "name": "name", "phone": "phone", "street": "street",
        "city": "city", "state_region": "region", "postal_code": "postal",
    }
    for line in lines:
        if re.match(r"^nap:\s*$", line):
            in_nap = True
            continue
        if in_nap:
            if line and not line[0].isspace():
                break  # dedented back to top level, nap block ended
            m = re.match(r"^\s+([a-z_]+):\s*(.*)$", line)
            if m:
                key, val = m.group(1), m.group(2).strip().strip('"').strip("'")
                if key in field_map and val:
                    nap[field_map[key]] = val
    return nap


def check_name(text, name):
    if not name:
        return []
    if name in text:
        return []
    # case-insensitive fallback = variant, exact-absent = miss
    if name.lower() in text.lower():
        return [("NAME", "variant", "present but not byte-exact (case differs)")]
    return [("NAME", "miss", "canonical name not found: %r" % name)]


def check_phone(text, phone):
    if not phone:
        return []
    # gather candidate phone-like strings from the page
    found = re.findall(r"[\+\(]?[\d][\d\-\.\(\)\s]{6,}\d", text)
    exact = phone in text
    digit_match = any(same_number(f, phone) for f in found)
    if exact:
        return []
    if digit_match:
        return [("PHONE", "variant",
                 "correct number, different display format than %r" % phone)]
    return [("PHONE", "miss", "canonical phone not found: %r" % phone)]


def check_address(text, nap):
    issues = []
    text_tokens = normalise_tokens(text)
    text_norm = " ".join(text_tokens)
    text_raw = text

    street = nap.get("street", "")
    if street:
        if contains_word(text_raw, street):
            pass  # exact
        else:
            street_norm = " ".join(normalise_tokens(street))
            if street_norm and street_norm in text_norm:
                issues.append(("ADDRESS.street", "variant",
                               "street present but abbreviated differently than %r"
                               % street))
            else:
                issues.append(("ADDRESS.street", "miss",
                               "street not found: %r" % street))

    for key, label in (("city", "ADDRESS.city"),
                       ("region", "ADDRESS.region"),
                       ("postal", "ADDRESS.postal")):
        val = nap.get(key, "")
        if not val:
            continue
        if contains_word(text_raw, val):
            continue
        if contains_word(text_raw.lower(), val.lower()):
            issues.append((label, "variant", "%s present, case differs: %r"
                           % (key, val)))
        else:
            issues.append((label, "miss", "%s not found: %r" % (key, val)))
    return issues


def check_file(path, nap):
    with open(path, "r", encoding="utf-8") as fh:
        text = fh.read()
    issues = []
    issues += check_name(text, nap.get("name", ""))
    issues += check_phone(text, nap.get("phone", ""))
    issues += check_address(text, nap)
    return issues


def report(path, issues):
    if not issues:
        print("PASS  %s  (NAP consistent)" % path)
        return
    misses = sum(1 for _, sev, _ in issues if sev == "miss")
    variants = sum(1 for _, sev, _ in issues if sev == "variant")
    print("FAIL  %s  (%d miss, %d variant)" % (path, misses, variants))
    for field, sev, msg in issues:
        print("  [%-7s] %-14s %s" % (sev.upper(), field, msg))


def run(args):
    if args.brand:
        nap = load_brand_nap(args.brand)
    else:
        nap = {
            "name": args.name or "", "phone": args.phone or "",
            "street": args.street or "", "city": args.city or "",
            "region": args.region or "", "postal": args.postal or "",
        }
    if not any(nap.values()):
        print("error: no canonical NAP provided (use --brand or the NAP flags)",
              file=sys.stderr)
        return 1
    if not args.files:
        print("error: no page/text files given", file=sys.stderr)
        return 1

    print("Canonical NAP:")
    for k in ("name", "phone", "street", "city", "region", "postal"):
        if nap.get(k):
            print("  %-7s %s" % (k + ":", nap[k]))
    print("")

    any_fail = False
    for path in args.files:
        if not os.path.exists(path):
            print("FAIL  %s  (file not found)" % path)
            any_fail = True
            continue
        issues = check_file(path, nap)
        report(path, issues)
        if issues:
            any_fail = True
    return 1 if any_fail else 0


def self_test():
    import tempfile
    nap = {"name": "Acme Plumbing", "phone": "+1-512-555-0100",
           "street": "100 Congress Ave", "city": "Austin",
           "region": "TX", "postal": "78701"}
    consistent = ("Call Acme Plumbing at +1-512-555-0100. We are at "
                  "100 Congress Ave, Austin, TX 78701.")
    variant = ("Call Acme Plumbing at (512) 555-0100. Visit us at "
               "100 Congress Avenue, Austin, TX 78701.")
    missing = "Welcome to our website. We do great work in Texas."

    d = tempfile.mkdtemp()
    paths = {}
    for label, content in (("ok", consistent), ("var", variant),
                           ("miss", missing)):
        p = os.path.join(d, label + ".md")
        with open(p, "w", encoding="utf-8") as fh:
            fh.write(content)
        paths[label] = p

    i_ok = check_file(paths["ok"], nap)
    i_var = check_file(paths["var"], nap)
    i_miss = check_file(paths["miss"], nap)

    assert i_ok == [], "consistent page should pass, got %s" % i_ok
    assert any(s == "variant" for _, s, _ in i_var), "variant page should flag variants"
    assert any(s == "miss" for _, s, _ in i_miss), "missing page should flag misses"
    print("self-test OK")
    print("  consistent: 0 issues")
    print("  variant:    %d issues (phone + street format)" % len(i_var))
    print("  missing:    %d issues" % len(i_miss))
    return 0


def build_parser():
    p = argparse.ArgumentParser(
        description="Verify NAP (Name, Address, Phone) consistency across pages.",
    )
    p.add_argument("files", nargs="*", help="page/text files to check")
    p.add_argument("--brand", help="path to brand.yaml (reads its nap: block)")
    p.add_argument("--name")
    p.add_argument("--phone")
    p.add_argument("--street")
    p.add_argument("--city")
    p.add_argument("--region")
    p.add_argument("--postal")
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
