"""JSON-LD structured-data validation for local-SEO pages.

Ported from ``seo-content-os/scripts/schema_validator.py`` (P1B).

Validates what the backend's own ``content_schema.build_json_ld`` emits, which makes
this a genuine cross-check between two independently written parts of the system
rather than a rule grading itself.

What it checks: well-formedness, required non-empty properties per recognised @type,
NAP completeness on LocalBusiness, PostalAddress / geo / openingHours shape,
BreadcrumbList and FAQPage internals. ``@graph`` arrays and nested typed nodes are
walked recursively, so a node buried three levels deep is validated like a top-level
one.

TWO CHECKS THAT ARE NOT SHAPE VALIDATION, and are the reason this is worth porting:

  * SELF-SERVING REVIEW MARKUP (compliance spine D3). ``aggregateRating`` / ``review``
    on the business's OWN LocalBusiness or Organization node is prohibited by Google's
    review-snippet guidance, and the corpus names it the single most common cause of a
    local manual action. It also makes the page ineligible for the star feature - so
    the markup that looks like it earns stars is what removes them. Reviews still
    belong on the visible page for humans and for AI extraction; they must not be
    marked up as schema on the self node.
  * LEASE-OUT ON A MONTHLY RENTAL OFFER (self-storage SS-SCHEMA2). A storage unit is
    leased, not sold, so an Offer carrying a monthly UnitPriceSpecification without
    ``businessFunction: LeaseOut`` mislabels a rental as a sale. Deliberately scoped to
    offers with a monthly price spec so it never fires on an ordinary discount Offer.

An UNRECOGNISED @type is not an error - there is simply no rule to apply. Treating
unknown types as failures would make the validator hostile to legitimate schema it has
not been taught, which is how validators get switched off.

PORT CHANGES: no argparse, no file loading, typed results. All rules verbatim.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

LOCAL_BUSINESS_TYPES: frozenset[str] = frozenset({
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
})

LEASE_OUT = "LeaseOut"

REQUIRED_FIELDS: dict[str, list[str]] = {
    "LocalBusiness": ["name", "address", "telephone"],
    "Service": ["name", "serviceType", "provider"],
    "BreadcrumbList": ["itemListElement"],
    "FAQPage": ["mainEntity"],
    "Person": ["name"],
    "Organization": ["name"],
}

ADDRESS_REQUIRED: tuple[str, ...] = (
    "streetAddress", "addressLocality", "addressRegion", "postalCode", "addressCountry",
)

SELF_REVIEW_PROPS: tuple[str, ...] = ("aggregateRating", "review", "reviews")


@dataclass(frozen=True)
class SchemaIssue:
    path: str
    message: str


@dataclass(frozen=True)
class SchemaReport:
    issues: tuple[SchemaIssue, ...] = ()
    node_count: int = 0

    @property
    def passed(self) -> bool:
        return not self.issues

    def messages(self) -> list[str]:
        return [f"{i.path}: {i.message}" for i in self.issues]


def _types_of(node: dict[str, Any]) -> list[str]:
    raw = node.get("@type")
    if raw is None:
        return []
    return [str(x) for x in raw] if isinstance(raw, list) else [str(raw)]


def _is_local_business(types: list[str]) -> bool:
    return any(t in LOCAL_BUSINESS_TYPES for t in types)


def _canonical_type(types: list[str]) -> str | None:
    if _is_local_business(types):
        return "LocalBusiness"
    return next((t for t in types if t in REQUIRED_FIELDS), None)


def _is_empty(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return value.strip() == ""
    if isinstance(value, list | dict):
        return len(value) == 0
    return False


def walk_nodes(obj: Any) -> Iterator[dict[str, Any]]:
    """Every dict carrying an ``@type``, recursively - including inside ``@graph``."""
    if isinstance(obj, dict):
        if "@type" in obj:
            yield obj
        for value in obj.values():
            yield from walk_nodes(value)
    elif isinstance(obj, list):
        for item in obj:
            yield from walk_nodes(item)


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else ([value] if value else [])


def _validate_address(node: dict[str, Any], out: list[SchemaIssue], path: str) -> None:
    addr = node.get("address")
    if _is_empty(addr):
        out.append(SchemaIssue(path, "address is missing or empty (NAP incomplete)"))
        return
    for i, entry in enumerate(addr if isinstance(addr, list) else [addr]):
        if not isinstance(entry, dict):
            out.append(SchemaIssue(path, "address is not a PostalAddress object"))
            continue
        for field in ADDRESS_REQUIRED:
            if _is_empty(entry.get(field)):
                out.append(SchemaIssue(path, f"address[{i}] missing/empty PostalAddress.{field}"))


def _validate_geo(node: dict[str, Any], out: list[SchemaIssue], path: str) -> None:
    geo = node.get("geo")
    if geo is None:
        return  # optional; only the SHAPE is validated when present
    for entry in geo if isinstance(geo, list) else [geo]:
        if not isinstance(entry, dict):
            out.append(SchemaIssue(path, "geo is not a GeoCoordinates object"))
            continue
        for coord, lo, hi in (("latitude", -90, 90), ("longitude", -180, 180)):
            val = entry.get(coord)
            if _is_empty(val):
                out.append(SchemaIssue(path, f"geo missing {coord}"))
                continue
            try:
                num = float(val)
            except (TypeError, ValueError):
                out.append(SchemaIssue(path, f"geo.{coord} is not numeric: {val!r}"))
                continue
            if not lo <= num <= hi:
                out.append(SchemaIssue(path, f"geo.{coord} out of range: {num}"))


def _validate_opening_hours(node: dict[str, Any], out: list[SchemaIssue], path: str) -> None:
    hours = node.get("openingHours")
    if hours is not None:
        for spec in hours if isinstance(hours, list) else [hours]:
            if not isinstance(spec, str) or not spec.strip():
                out.append(SchemaIssue(path, "openingHours entry is empty or not a string"))
            elif ":" not in spec:
                out.append(SchemaIssue(path, f"openingHours {spec!r} has no HH:MM time window"))

    structured = node.get("openingHoursSpecification")
    if structured is not None:
        for spec in structured if isinstance(structured, list) else [structured]:
            if not isinstance(spec, dict):
                out.append(SchemaIssue(path, "openingHoursSpecification entry not an object"))
                continue
            for field in ("dayOfWeek", "opens", "closes"):
                if _is_empty(spec.get(field)):
                    out.append(SchemaIssue(path, f"openingHoursSpecification missing {field}"))


def _validate_breadcrumb(node: dict[str, Any], out: list[SchemaIssue], path: str) -> None:
    items = node.get("itemListElement")
    if _is_empty(items):
        return  # the required-field check already reported it
    if not isinstance(items, list):
        out.append(SchemaIssue(path, "BreadcrumbList.itemListElement is not a list"))
        return
    for i, item in enumerate(items):
        if not isinstance(item, dict):
            out.append(SchemaIssue(path, f"breadcrumb item {i} is not an object"))
            continue
        if _is_empty(item.get("position")):
            out.append(SchemaIssue(path, f"breadcrumb item {i} missing position"))
        if _is_empty(item.get("name")) and _is_empty(item.get("item")):
            out.append(SchemaIssue(path, f"breadcrumb item {i} missing name/item"))


def _validate_faqpage(node: dict[str, Any], out: list[SchemaIssue], path: str) -> None:
    main = node.get("mainEntity")
    if _is_empty(main):
        return
    for i, question in enumerate(main if isinstance(main, list) else [main]):
        if not isinstance(question, dict):
            out.append(SchemaIssue(path, f"FAQ mainEntity[{i}] is not a Question object"))
            continue
        if _is_empty(question.get("name")):
            out.append(SchemaIssue(path, f"FAQ Question[{i}] missing name (the question)"))
        answer = question.get("acceptedAnswer")
        if _is_empty(answer) or (isinstance(answer, dict) and _is_empty(answer.get("text"))):
            out.append(SchemaIssue(path, f"FAQ Question[{i}] missing acceptedAnswer.text"))


def _validate_self_review(node: dict[str, Any], out: list[SchemaIssue], path: str) -> None:
    """D3: self-serving review markup on the business's own node.

    Prohibited by Google's review-snippet guidance and named by the corpus as the
    single most common local manual-action cause. It also makes the page ineligible
    for the star feature - so the markup that looks like it earns stars is exactly what
    removes them.
    """
    for prop in SELF_REVIEW_PROPS:
        if prop in node and not _is_empty(node.get(prop)):
            out.append(SchemaIssue(
                path,
                f"self-serving {prop} markup on the business's own node (compliance "
                "spine D3): remove review/aggregateRating from your own "
                "LocalBusiness/Organization schema",
            ))


def _is_monthly_rental_offer(node: dict[str, Any]) -> bool:
    for spec in _as_list(node.get("priceSpecification")):
        if not isinstance(spec, dict):
            continue
        if "UnitPriceSpecification" in _types_of(spec):
            return True
        if str(spec.get("unitCode", "")).upper() == "MON":
            return True
    return False


def _validate_storage_offer(node: dict[str, Any], out: list[SchemaIssue], path: str) -> None:
    """SS-SCHEMA2: a storage unit is leased, not sold."""
    if not _is_monthly_rental_offer(node):
        return
    business_function = node.get("businessFunction")
    if _is_empty(business_function) or LEASE_OUT not in str(business_function):
        out.append(SchemaIssue(
            path,
            f"storage unit Offer with a monthly UnitPriceSpecification is missing "
            f"businessFunction '{LEASE_OUT}' - a rental mislabeled as a sale "
            "(self-storage SS-SCHEMA2)",
        ))


def validate_node(node: dict[str, Any], out: list[SchemaIssue]) -> None:
    types = _types_of(node)
    key = _canonical_type(types)
    path = "/".join(types) if types else "(no @type)"

    # Checked BEFORE the early return: an Offer is not a canonical-type key, but a
    # monthly storage rental Offer must still declare LeaseOut.
    if "Offer" in types or "AggregateOffer" in types:
        _validate_storage_offer(node, out, path)

    if key is None:
        return  # unrecognised type: no rule to apply, not an error

    for field in REQUIRED_FIELDS[key]:
        if _is_empty(node.get(field)):
            out.append(SchemaIssue(path, f"missing/empty required field: {field}"))

    if key == "LocalBusiness":
        _validate_address(node, out, path)
        _validate_geo(node, out, path)
        _validate_opening_hours(node, out, path)
    elif key == "BreadcrumbList":
        _validate_breadcrumb(node, out, path)
    elif key == "FAQPage":
        _validate_faqpage(node, out, path)

    if key in ("LocalBusiness", "Organization"):
        _validate_self_review(node, out, path)


def validate_schema(data: Any) -> SchemaReport:
    """Validate parsed JSON-LD. Total: never raises, never does I/O."""
    out: list[SchemaIssue] = []
    nodes = list(walk_nodes(data))
    if not nodes:
        out.append(SchemaIssue("(root)", "no @type nodes found - not valid JSON-LD"))
    for node in nodes:
        validate_node(node, out)
    return SchemaReport(issues=tuple(out), node_count=len(nodes))
