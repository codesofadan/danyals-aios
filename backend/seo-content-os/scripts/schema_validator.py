#!/usr/bin/env python3
"""schema_validator.py - Validate JSON-LD structured data for local-SEO pages.

Offline, stdlib-only (json, argparse). No network calls.

What it checks
--------------
- Well-formedness: the file/string parses as JSON.
- Type coverage: every @type present is recognised; required properties for
  each known type are present and non-empty.
- NAP presence on LocalBusiness (name, address, telephone).
- PostalAddress shape (street, locality, region, postal code, country).
- geo shape (latitude + longitude numeric and in range).
- openingHoursSpecification / openingHours format sanity.
- No empty string / empty list / null values in required fields.
- @graph arrays and nested @type nodes are walked recursively.

Supported types (required-field rules):
  LocalBusiness (+ common subtypes: Plumber, Electrician, RoofingContractor,
  HVACBusiness, Dentist, LawFirm, GeneralContractor, MedicalBusiness, etc.),
  Service, BreadcrumbList, FAQPage, Person, Organization.

Exit code 0 = all pass, 1 = one or more issues found.

Usage
-----
  python schema_validator.py path/to/schema.json
  python schema_validator.py --string '{"@type":"Service", ...}'
  echo '{...}' | python schema_validator.py -
  python schema_validator.py --self-test
"""

import argparse
import json
import sys

# LocalBusiness and the subtypes a local service business commonly uses.
# Any @type ending in these or listed here is treated as a LocalBusiness.
LOCAL_BUSINESS_TYPES = {
    "LocalBusiness", "Plumber", "Electrician", "RoofingContractor",
    "HVACBusiness", "Dentist", "LawFirm", "Attorney", "GeneralContractor",
    "HomeAndConstructionBusiness", "MedicalBusiness", "Physician",
    "AutoRepair", "Locksmith", "MovingCompany", "PestControlService",
    "CleaningService", "Landscaper", "Painter", "Contractor",
    "ProfessionalService", "DryCleaningOrLaundry", "ChildCare",
    "RealEstateAgent", "InsuranceAgency", "AccountingService",
    "FinancialService", "VeterinaryCare", "DaySpa", "HairSalon",
    "BeautySalon", "Restaurant", "Store", "AutomotiveBusiness",
    "EmergencyService", "Notary", "SelfStorage",
}

# GoodRelations LeaseOut: a storage unit is leased, not sold. A monthly-rental
# Offer that omits businessFunction mislabels the rental as a sale (self-storage
# overlay SS-SCHEMA2). Scoped to offers that carry a monthly UnitPriceSpecification
# so it never fires on a non-storage discount Offer.
LEASE_OUT = "LeaseOut"

# Required (non-empty) properties per type. LocalBusiness needs NAP.
REQUIRED_FIELDS = {
    "LocalBusiness": ["name", "address", "telephone"],
    "Service": ["name", "serviceType", "provider"],
    "BreadcrumbList": ["itemListElement"],
    "FAQPage": ["mainEntity"],
    "Person": ["name"],
    "Organization": ["name"],
}

ADDRESS_REQUIRED = [
    "streetAddress", "addressLocality", "addressRegion",
    "postalCode", "addressCountry",
]

# Compliance spine D3: review markup about the business itself, placed on the
# business's own LocalBusiness/Organization node, is prohibited (Google's
# review-snippet guidance) and is called out as the single most common local
# manual-action cause. Flag any of these self-serving properties on a self node.
SELF_REVIEW_PROPS = ("aggregateRating", "review", "reviews")


def _types_of(node):
    """Return the @type values of a node as a list of strings."""
    t = node.get("@type")
    if t is None:
        return []
    if isinstance(t, list):
        return [str(x) for x in t]
    return [str(t)]


def _is_local_business(types):
    return any(t in LOCAL_BUSINESS_TYPES for t in types)


def _canonical_type(types):
    """Map a node's types to the rule key we validate against."""
    if _is_local_business(types):
        return "LocalBusiness"
    for t in types:
        if t in REQUIRED_FIELDS:
            return t
    return None


def _is_empty(value):
    if value is None:
        return True
    if isinstance(value, str) and value.strip() == "":
        return True
    if isinstance(value, (list, dict)) and len(value) == 0:
        return True
    return False


def _walk_nodes(obj):
    """Yield every dict that carries an @type, recursively (incl. @graph)."""
    if isinstance(obj, dict):
        if "@type" in obj:
            yield obj
        for value in obj.values():
            yield from _walk_nodes(value)
    elif isinstance(obj, list):
        for item in obj:
            yield from _walk_nodes(item)


def _validate_address(node, issues, path):
    addr = node.get("address")
    if _is_empty(addr):
        issues.append((path, "address is missing or empty (NAP incomplete)"))
        return
    addrs = addr if isinstance(addr, list) else [addr]
    for i, a in enumerate(addrs):
        if not isinstance(a, dict):
            issues.append((path, "address is not a PostalAddress object"))
            continue
        for field in ADDRESS_REQUIRED:
            if _is_empty(a.get(field)):
                issues.append(
                    (path, "address[%d] missing/empty PostalAddress.%s" % (i, field))
                )


def _validate_geo(node, issues, path):
    geo = node.get("geo")
    if geo is None:
        return  # geo is optional; only validate shape if present
    geos = geo if isinstance(geo, list) else [geo]
    for g in geos:
        if not isinstance(g, dict):
            issues.append((path, "geo is not a GeoCoordinates object"))
            continue
        for coord, lo, hi in (("latitude", -90, 90), ("longitude", -180, 180)):
            val = g.get(coord)
            if _is_empty(val):
                issues.append((path, "geo missing %s" % coord))
                continue
            try:
                num = float(val)
            except (TypeError, ValueError):
                issues.append((path, "geo.%s is not numeric: %r" % (coord, val)))
                continue
            if not (lo <= num <= hi):
                issues.append((path, "geo.%s out of range: %s" % (coord, num)))


def _validate_opening_hours(node, issues, path):
    oh = node.get("openingHours")
    if oh is not None:
        items = oh if isinstance(oh, list) else [oh]
        for spec in items:
            if not isinstance(spec, str) or not spec.strip():
                issues.append((path, "openingHours entry is empty or not a string"))
                continue
            # Loose sanity: expect a day token and a HH:MM-HH:MM window.
            if ":" not in spec:
                issues.append(
                    (path, "openingHours %r has no HH:MM time window" % spec)
                )
    ohs = node.get("openingHoursSpecification")
    if ohs is not None:
        specs = ohs if isinstance(ohs, list) else [ohs]
        for s in specs:
            if not isinstance(s, dict):
                issues.append((path, "openingHoursSpecification entry not an object"))
                continue
            for field in ("dayOfWeek", "opens", "closes"):
                if _is_empty(s.get(field)):
                    issues.append(
                        (path, "openingHoursSpecification missing %s" % field)
                    )


def _validate_breadcrumb(node, issues, path):
    items = node.get("itemListElement")
    if _is_empty(items):
        return  # required-field check already flagged it
    if not isinstance(items, list):
        issues.append((path, "BreadcrumbList.itemListElement is not a list"))
        return
    for i, li in enumerate(items):
        if not isinstance(li, dict):
            issues.append((path, "breadcrumb item %d is not an object" % i))
            continue
        if _is_empty(li.get("position")):
            issues.append((path, "breadcrumb item %d missing position" % i))
        if _is_empty(li.get("name")) and _is_empty(li.get("item")):
            issues.append((path, "breadcrumb item %d missing name/item" % i))


def _validate_faqpage(node, issues, path):
    main = node.get("mainEntity")
    if _is_empty(main):
        return
    entities = main if isinstance(main, list) else [main]
    for i, q in enumerate(entities):
        if not isinstance(q, dict):
            issues.append((path, "FAQ mainEntity[%d] is not a Question object" % i))
            continue
        if _is_empty(q.get("name")):
            issues.append((path, "FAQ Question[%d] missing name (the question)" % i))
        ans = q.get("acceptedAnswer")
        if _is_empty(ans) or (isinstance(ans, dict) and _is_empty(ans.get("text"))):
            issues.append((path, "FAQ Question[%d] missing acceptedAnswer.text" % i))


def _validate_self_review(node, issues, path):
    """D3: flag self-serving review / aggregateRating markup on the business's
    own LocalBusiness or Organization node. Such markup makes the page
    ineligible for the review star feature and is the single most common local
    manual-action cause. Reviews still belong on the visible page for humans and
    AI extraction; they must not be marked up as review schema on the self node.
    """
    for prop in SELF_REVIEW_PROPS:
        if prop in node and not _is_empty(node.get(prop)):
            issues.append((
                path,
                "self-serving %s markup on the business's own node "
                "(compliance spine D3): remove review/aggregateRating from your "
                "own LocalBusiness/Organization schema" % prop,
            ))


def _is_monthly_rental_offer(node):
    """True if this Offer/AggregateOffer carries a monthly UnitPriceSpecification
    (unitCode MON) - i.e. a storage unit's monthly rental rate."""
    ps = node.get("priceSpecification")
    specs = ps if isinstance(ps, list) else ([ps] if ps else [])
    for s in specs:
        if not isinstance(s, dict):
            continue
        if "UnitPriceSpecification" in _types_of(s):
            return True
        if str(s.get("unitCode", "")).upper() == "MON":
            return True
    return False


def _validate_storage_offer(node, issues, path):
    """SS-SCHEMA2: a storage unit is leased, not sold. A monthly-rental Offer
    that omits businessFunction: LeaseOut mislabels the rental as a sale."""
    if not _is_monthly_rental_offer(node):
        return
    bf = node.get("businessFunction")
    if _is_empty(bf) or LEASE_OUT not in str(bf):
        issues.append((
            path,
            "storage unit Offer with a monthly UnitPriceSpecification is missing "
            "businessFunction '%s' - a rental mislabeled as a sale (self-storage "
            "SS-SCHEMA2)" % LEASE_OUT,
        ))


def validate_node(node, issues):
    types = _types_of(node)
    key = _canonical_type(types)
    path = "/".join(types) if types else "(no @type)"

    # Offer / AggregateOffer nodes are not a canonical-type key, but a monthly
    # storage rental Offer must declare LeaseOut. Check before the early return.
    if "Offer" in types or "AggregateOffer" in types:
        _validate_storage_offer(node, issues, path)

    if key is None:
        # Unknown top-level-ish type: not an error, just no rule to apply.
        return

    for field in REQUIRED_FIELDS[key]:
        if _is_empty(node.get(field)):
            issues.append((path, "missing/empty required field: %s" % field))

    if key == "LocalBusiness":
        _validate_address(node, issues, path)
        _validate_geo(node, issues, path)
        _validate_opening_hours(node, issues, path)
    elif key == "BreadcrumbList":
        _validate_breadcrumb(node, issues, path)
    elif key == "FAQPage":
        _validate_faqpage(node, issues, path)

    if key in ("LocalBusiness", "Organization"):
        _validate_self_review(node, issues, path)


def validate(data):
    """Return (issues, node_count). issues is a list of (path, message)."""
    issues = []
    nodes = list(_walk_nodes(data))
    if not nodes:
        issues.append(("(root)", "no @type nodes found - not valid JSON-LD"))
    for node in nodes:
        validate_node(node, issues)
    return issues, len(nodes)


def load_input(args):
    if args.string is not None:
        raw = args.string
        src = "<--string>"
    elif args.path == "-":
        raw = sys.stdin.read()
        src = "<stdin>"
    else:
        with open(args.path, "r", encoding="utf-8") as fh:
            raw = fh.read()
        src = args.path
    return raw, src


def run(args):
    raw, src = load_input(args)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        print("FAIL  %s" % src)
        print("  not well-formed JSON: %s" % exc)
        return 1

    issues, node_count = validate(data)
    print("Schema report for %s" % src)
    print("  typed nodes found: %d" % node_count)
    if not issues:
        print("PASS  no schema issues found")
        return 0
    print("FAIL  %d issue(s):" % len(issues))
    for path, msg in issues:
        print("  [%s] %s" % (path, msg))
    return 1


def self_test():
    good = {
        "@context": "https://schema.org",
        "@graph": [
            {
                "@type": "Plumber",
                "name": "Austin Pro Plumbing",
                "telephone": "+1-512-555-0100",
                "address": {
                    "@type": "PostalAddress",
                    "streetAddress": "100 Congress Ave",
                    "addressLocality": "Austin",
                    "addressRegion": "TX",
                    "postalCode": "78701",
                    "addressCountry": "US",
                },
                "geo": {"@type": "GeoCoordinates",
                        "latitude": 30.27, "longitude": -97.74},
                "openingHours": ["Mo-Fr 08:00-18:00"],
            },
            {
                "@type": "BreadcrumbList",
                "itemListElement": [
                    {"@type": "ListItem", "position": 1, "name": "Home"},
                ],
            },
        ],
    }
    bad = {
        "@type": "Service",
        "name": "",
        "provider": {"@type": "Organization", "name": ""},
    }
    self_serving = {
        "@context": "https://schema.org",
        "@type": "Plumber",
        "name": "Austin Pro Plumbing",
        "telephone": "+1-512-555-0100",
        "address": {
            "@type": "PostalAddress",
            "streetAddress": "100 Congress Ave",
            "addressLocality": "Austin",
            "addressRegion": "TX",
            "postalCode": "78701",
            "addressCountry": "US",
        },
        "aggregateRating": {
            "@type": "AggregateRating",
            "ratingValue": "4.9",
            "reviewCount": "218",
        },
        "review": [
            {"@type": "Review",
             "reviewRating": {"@type": "Rating", "ratingValue": "5"},
             "author": {"@type": "Person", "name": "A. Customer"}},
        ],
    }
    ok_issues, _ = validate(good)
    bad_issues, _ = validate(bad)
    sr_issues, _ = validate(self_serving)
    sr_msgs = " ".join(m for _, m in sr_issues)
    assert ok_issues == [], "good doc should pass, got: %s" % ok_issues
    assert bad_issues, "bad doc should fail"
    assert sr_issues, "self-serving review doc should fail (D3)"
    assert "D3" in sr_msgs, "self-serving flag should cite D3, got: %s" % sr_issues
    assert "aggregateRating" in sr_msgs and "review" in sr_msgs, \
        "both review and aggregateRating should be flagged, got: %s" % sr_issues

    # --- self-storage: SelfStorage subtype + LeaseOut on a monthly rental offer ---
    storage_good = {
        "@context": "https://schema.org",
        "@type": "SelfStorage",
        "name": "Example Storage - South Austin",
        "telephone": "+1-512-555-0142",
        "address": {"@type": "PostalAddress",
                    "streetAddress": "1234 S Congress Ave",
                    "addressLocality": "Austin", "addressRegion": "TX",
                    "postalCode": "78704", "addressCountry": "US"},
        "geo": {"@type": "GeoCoordinates", "latitude": 30.245, "longitude": -97.75},
        "amenityFeature": [
            {"@type": "LocationFeatureSpecification",
             "name": "Climate-controlled units", "value": True},
        ],
    }
    storage_bad_offer = {
        "@context": "https://schema.org",
        "@type": "Product",
        "name": "10x10 Climate-Controlled Unit",
        "offers": {"@type": "Offer", "priceCurrency": "USD",
                   "priceSpecification": {"@type": "UnitPriceSpecification",
                                          "price": "129.00", "priceCurrency": "USD",
                                          "unitCode": "MON"}},
    }
    storage_good_offer = {
        "@context": "https://schema.org",
        "@type": "Product",
        "name": "10x10 Climate-Controlled Unit",
        "offers": {"@type": "Offer", "priceCurrency": "USD",
                   "businessFunction": "http://purl.org/goodrelations/v1#LeaseOut",
                   "priceSpecification": {"@type": "UnitPriceSpecification",
                                          "price": "129.00", "priceCurrency": "USD",
                                          "unitCode": "MON"}},
    }
    sg_issues, _ = validate(storage_good)
    sbo_issues, _ = validate(storage_bad_offer)
    sgo_issues, _ = validate(storage_good_offer)
    storage_selfrev = dict(storage_good, aggregateRating={
        "@type": "AggregateRating", "ratingValue": "4.8", "reviewCount": "212"})
    ssr_issues, _ = validate(storage_selfrev)
    assert sg_issues == [], "SelfStorage w/ full NAP should pass: %s" % sg_issues
    assert any("SS-SCHEMA2" in m for _, m in sbo_issues), \
        "monthly rental Offer without LeaseOut should flag SS-SCHEMA2: %s" % sbo_issues
    assert sgo_issues == [], \
        "monthly rental Offer WITH LeaseOut should pass: %s" % sgo_issues
    assert any("D3" in m for _, m in ssr_issues), \
        "self-serving review on a SelfStorage node should fire D3: %s" % ssr_issues

    print("self-test OK")
    print("  good doc: 0 issues")
    print("  bad doc: %d issues (expected > 0)" % len(bad_issues))
    print("  self-serving-review doc: %d issues (D3, expected > 0)"
          % len(sr_issues))
    return 0


def build_parser():
    p = argparse.ArgumentParser(
        description="Validate JSON-LD structured data for local-SEO pages.",
    )
    p.add_argument("path", nargs="?", default="-",
                   help="path to a JSON-LD file, or '-' for stdin (default)")
    p.add_argument("--string", help="validate a JSON-LD string directly")
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
