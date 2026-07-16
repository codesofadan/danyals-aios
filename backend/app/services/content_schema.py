"""P7A-5: the JSON-LD structured-data generator + match-visible-content validator.

This is a PURE, DETERMINISTIC service - NO network, NO LLM, NO DB, no hidden
globals. Given a content job's business + page facts it emits a valid Schema.org
JSON-LD ``@graph`` for the page, and cross-validates any graph against the page's
VISIBLE content so we never mark up a claim a human cannot see (Google's #1
structured-data policy, and the fastest way to earn a manual action).

Two entry points:

* :func:`build_json_ld` ``(page_type, business, page, breadcrumbs) -> dict`` - the
  generator. It produces the 2026 rich-result reality per page type:

  - ``service`` -> **Service** (``serviceType`` + ``provider`` ref + ``areaServed``)
    + **BreadcrumbList** + **Organization** (the provider entity).
  - ``local`` -> **LocalBusiness** (the most specific subtype available;
    ``address`` for a STOREFRONT or ``areaServed`` for a service-area business
    [SAB, ``has_public_address=False``, address hidden], ``telephone``, ``geo``,
    ``openingHoursSpecification``, ``priceRange``, ``sameAs``, and
    ``aggregateRating`` ONLY when real reviews back it) + BreadcrumbList +
    Organization.
  - ``blog`` -> **BlogPosting** (an ``Article`` subtype; ``headline``, ``author``,
    ``datePublished``, ``dateModified``, ``publisher`` ref) + BreadcrumbList +
    Organization (the publisher).
  - When the content carries Q&A or steps it ALSO emits **FAQPage** / **HowTo**
    nodes - but :func:`rich_result_eligible` flags them ``False``: Google
    deprecated the FAQ (2023) and HowTo (2023) rich results, so these are kept
    for SEMANTICS / AI extraction only, never promised as a rich result.

* :func:`validate_json_ld` ``(graph, visible_content) -> ValidationResult`` - the
  QA gate. It enforces, per emitted ``@type``:

  1. **Required properties present** (per type; a LocalBusiness needs an
     ``address`` OR an ``areaServed``; a Service needs ``serviceType`` +
     ``provider``; an Article needs ``headline`` + ``author`` + ``datePublished``
     + ``publisher``).
  2. **Correct nesting** (``address`` is a ``PostalAddress`` object not a bare
     string; ``itemListElement`` is a list of ``ListItem``; ``provider`` /
     ``publisher`` resolve to a node in the graph; ``geo`` /
     ``aggregateRating`` are well-formed).
  3. **Match-visible-content** - every ASSERTED claim (name, telephone, service
     type, address / area served, headline, FAQ Q&A, HowTo steps) must actually
     appear in the supplied visible page text. A marked-up claim that is NOT
     visible is rejected.
  4. **No fake / self-serving ``aggregateRating``** - a rating block is rejected
     unless the page actually displays reviews (``visible_content.has_reviews``)
     AND carries a positive ``reviewCount``.

  It returns ``errors`` / ``warnings``, the ``primary_type`` (which feeds the
  content contract's ``schema`` field), and per-type rich-result eligibility.

NOTE on the contract ``schema`` field: ``app.schemas.content.schema_for`` maps
blog -> ``"Article"``; this generator emits the more specific ``"BlogPosting"``
(an ``Article`` subtype - equally valid, better practice). ``primary_type`` returns
the ACTUAL emitted ``@type``; a caller may store either it or ``schema_for``'s
base type in the ``schema`` column.
"""

from __future__ import annotations

import re
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

# --------------------------------------------------------------------------- #
# Type vocabularies
# --------------------------------------------------------------------------- #
# LocalBusiness + its refine-when-possible subtypes (from the audit engine's
# schema-org/local-business knowledge). A storefront should always use the most
# specific one; we recognise them all as the "local" family for validation.
_LOCAL_TYPES: frozenset[str] = frozenset(
    {
        "LocalBusiness", "Restaurant", "Store", "ProfessionalService",
        "HomeAndConstructionBusiness", "Plumber", "Electrician",
        "RoofingContractor", "HVACBusiness", "LegalService", "Attorney",
        "Dentist", "Physician", "MedicalBusiness", "AutoRepair",
        "RealEstateAgent", "BeautySalon", "HairSalon", "GeneralContractor",
        "ChildCare", "FoodEstablishment", "Bakery", "BarOrPub",
        "CafeOrCoffeeShop", "ClothingStore", "HardwareStore", "GroceryStore",
        "FurnitureStore", "Locksmith", "MovingCompany", "Notary", "Painter",
    }
)
# The Article family (BlogPosting / NewsArticle are Article subtypes).
_ARTICLE_TYPES: frozenset[str] = frozenset({"Article", "BlogPosting", "NewsArticle"})

# Rich results Google DEPRECATED - still emitted for semantics/AI extraction, but
# never promised as a rich result.
_RICH_DEPRECATED: frozenset[str] = frozenset({"FAQPage", "HowTo"})
# Types that (still) drive a Google rich result in 2026.
_RICH_ELIGIBLE: frozenset[str] = (
    frozenset({"BreadcrumbList", "Product", "Event", "Recipe", "Review"})
    | _ARTICLE_TYPES
    | _LOCAL_TYPES
)

# Required properties by type/family (for validity). LocalBusiness additionally
# needs address OR areaServed - handled specially since which one is legitimate
# depends on storefront vs SAB, inferable from the node alone.
_LOCAL_REQUIRED: frozenset[str] = frozenset({"name", "telephone"})
_ARTICLE_REQUIRED: frozenset[str] = frozenset(
    {"headline", "author", "datePublished", "publisher"}
)
_REQUIRED_BY_TYPE: dict[str, frozenset[str]] = {
    "Service": frozenset({"name", "serviceType", "provider"}),
    "Organization": frozenset({"name"}),
    "BreadcrumbList": frozenset({"itemListElement"}),
    "FAQPage": frozenset({"mainEntity"}),
    "HowTo": frozenset({"name", "step"}),
}

# Recommended-but-not-required properties (missing -> warning, not error).
_RECOMMENDED_BY_FAMILY: dict[str, tuple[str, ...]] = {
    "local": ("url", "image", "priceRange", "geo", "openingHoursSpecification", "sameAs"),
    "service": ("areaServed", "url", "description"),
    "article": ("image", "dateModified", "mainEntityOfPage"),
}

_SCHEMA_CONTEXT = "https://schema.org"

# Match-visible claim kinds.
_TEXT = "text"
_PHONE = "phone"

_ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}")
_WS_RE = re.compile(r"\s+")
_NON_DIGIT_RE = re.compile(r"\D")


# --------------------------------------------------------------------------- #
# Input value objects (pure data - the router assembles these from job rows)
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class PostalAddress:
    """A storefront's postal address. All five parts are needed for a local rich
    result; a missing ``address_country`` is the single most common disqualifier."""

    street_address: str = ""
    address_locality: str = ""
    address_region: str = ""
    postal_code: str = ""
    address_country: str = ""

    def is_empty(self) -> bool:
        return not any(
            (
                self.street_address,
                self.address_locality,
                self.address_region,
                self.postal_code,
                self.address_country,
            )
        )


@dataclass(frozen=True)
class GeoCoordinates:
    """A business's latitude/longitude for the map/local pack."""

    latitude: float
    longitude: float


@dataclass(frozen=True)
class OpeningHours:
    """One opening-hours span: the weekdays it covers + open/close (``HH:MM``)."""

    days: tuple[str, ...]
    opens: str
    closes: str


@dataclass(frozen=True)
class AggregateRating:
    """A review-rating summary. Emitted ONLY when it is backed by real, visible
    reviews (``review_count`` > 0 and the page actually shows them) - never a
    self-serving rating."""

    rating_value: float
    review_count: int
    best_rating: float = 5.0
    worst_rating: float = 1.0


@dataclass(frozen=True)
class Author:
    """A blog post's author (a ``Person`` by default, or an ``Organization``)."""

    name: str
    url: str = ""
    is_organization: bool = False


@dataclass(frozen=True)
class FaqItem:
    """One question + its answer, extracted from the visible Q&A on the page."""

    question: str
    answer: str


@dataclass(frozen=True)
class HowToStep:
    """One step of a how-to, as it appears on the page."""

    name: str
    text: str = ""


@dataclass(frozen=True)
class Business:
    """The business/brand entity behind the page - the Organization, and (for a
    local page) the LocalBusiness. ``has_public_address`` is the SAB switch: a
    service-area business hides its address and markets an ``area_served``
    instead; a storefront publishes its ``address``."""

    name: str
    url: str = ""
    logo: str = ""
    image: str = ""
    telephone: str = ""
    business_type: str = "LocalBusiness"  # refine to a subtype, e.g. "Plumber"
    has_public_address: bool = True  # storefront (True) vs SAB (False)
    address: PostalAddress | None = None
    area_served: tuple[str, ...] = ()
    geo: GeoCoordinates | None = None
    opening_hours: tuple[OpeningHours, ...] = ()
    price_range: str = ""
    same_as: tuple[str, ...] = ()
    aggregate_rating: AggregateRating | None = None


@dataclass(frozen=True)
class Page:
    """The specific page being marked up. Fields are used per page type:
    ``service_type``/``area_served`` for a service page; ``author``/dates/
    ``article_type`` for a blog; ``faqs``/``how_to_steps`` add FAQ/HowTo nodes."""

    url: str
    title: str = ""  # the page name / article headline
    description: str = ""
    service_type: str = ""
    area_served: tuple[str, ...] = ()
    author: Author | None = None
    date_published: str = ""
    date_modified: str = ""
    article_type: str = "BlogPosting"  # or "Article" / "NewsArticle"
    image: str = ""
    faqs: tuple[FaqItem, ...] = ()
    how_to_steps: tuple[HowToStep, ...] = ()


@dataclass(frozen=True)
class Breadcrumb:
    """One trail entry (name + optional URL); position is the list index + 1."""

    name: str
    url: str = ""


@dataclass(frozen=True)
class VisibleContent:
    """The page's VISIBLE facts the validator cross-checks against. ``text`` is the
    rendered body text; ``has_reviews`` asserts real reviews are shown on-page
    (the gate for an ``aggregateRating``)."""

    text: str = ""
    has_reviews: bool = False


# --------------------------------------------------------------------------- #
# Validation result
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class ValidationResult:
    """The QA verdict. ``valid`` is ``True`` only with zero errors; warnings never
    fail the graph. ``primary_type`` is the first node's ``@type`` (feeds the
    content contract's ``schema`` field). ``rich_result_types`` maps every emitted
    ``@type`` to whether it can earn a rich result today (FAQPage/HowTo -> False)."""

    valid: bool
    primary_type: str | None
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    rich_result_types: dict[str, bool] = field(default_factory=dict)
    rich_result_eligible: bool = False


# --------------------------------------------------------------------------- #
# Small helpers
# --------------------------------------------------------------------------- #
def _norm(value: str) -> str:
    """Collapse whitespace + lowercase for tolerant substring matching."""
    return _WS_RE.sub(" ", value).strip().lower()


def _digits(value: str) -> str:
    return _NON_DIGIT_RE.sub("", value)


def _as_list(value: Any) -> list[str]:
    """Coerce a str|list|None into a list of non-empty strings."""
    if value is None:
        return []
    if isinstance(value, str):
        return [value] if value else []
    if isinstance(value, list):
        return [str(v) for v in value if isinstance(v, str) and v]
    return []


def rich_result_eligible(type_name: str, *, has_errors: bool = False) -> bool:
    """Whether a Schema.org ``@type`` can earn a Google rich result in 2026.

    ``FAQPage`` / ``HowTo`` are ALWAYS ``False`` (Google deprecated their rich
    results - we still emit them for semantics/AI extraction). A node with
    validity errors is ineligible regardless of type."""
    if type_name in _RICH_DEPRECATED:
        return False
    if has_errors:
        return False
    return type_name in _RICH_ELIGIBLE


# --------------------------------------------------------------------------- #
# Node builders
# --------------------------------------------------------------------------- #
def _org_id(business: Business) -> str:
    return f"{business.url}#organization"


def _organization_node(business: Business) -> dict[str, Any]:
    node: dict[str, Any] = {
        "@type": "Organization",
        "@id": _org_id(business),
        "name": business.name,
    }
    if business.url:
        node["url"] = business.url
    if business.logo:
        node["logo"] = business.logo
    if business.same_as:
        node["sameAs"] = list(business.same_as)
    if business.telephone:
        node["telephone"] = business.telephone
    return node


def _address_node(address: PostalAddress) -> dict[str, Any]:
    node: dict[str, Any] = {"@type": "PostalAddress"}
    if address.street_address:
        node["streetAddress"] = address.street_address
    if address.address_locality:
        node["addressLocality"] = address.address_locality
    if address.address_region:
        node["addressRegion"] = address.address_region
    if address.postal_code:
        node["postalCode"] = address.postal_code
    if address.address_country:
        node["addressCountry"] = address.address_country
    return node


def _geo_node(geo: GeoCoordinates) -> dict[str, Any]:
    return {
        "@type": "GeoCoordinates",
        "latitude": geo.latitude,
        "longitude": geo.longitude,
    }


def _opening_hours_specs(hours: Sequence[OpeningHours]) -> list[dict[str, Any]]:
    return [
        {
            "@type": "OpeningHoursSpecification",
            "dayOfWeek": list(span.days),
            "opens": span.opens,
            "closes": span.closes,
        }
        for span in hours
    ]


def _aggregate_rating_node(rating: AggregateRating) -> dict[str, Any]:
    return {
        "@type": "AggregateRating",
        "ratingValue": rating.rating_value,
        "reviewCount": rating.review_count,
        "bestRating": rating.best_rating,
        "worstRating": rating.worst_rating,
    }


def _breadcrumb_node(page: Page, breadcrumbs: Sequence[Breadcrumb]) -> dict[str, Any] | None:
    if not breadcrumbs:
        return None
    items: list[dict[str, Any]] = []
    for position, crumb in enumerate(breadcrumbs, start=1):
        item: dict[str, Any] = {
            "@type": "ListItem",
            "position": position,
            "name": crumb.name,
        }
        if crumb.url:
            item["item"] = crumb.url
        items.append(item)
    return {
        "@type": "BreadcrumbList",
        "@id": f"{page.url}#breadcrumb",
        "itemListElement": items,
    }


def _faq_node(page: Page) -> dict[str, Any] | None:
    if not page.faqs:
        return None
    return {
        "@type": "FAQPage",
        "@id": f"{page.url}#faq",
        "mainEntity": [
            {
                "@type": "Question",
                "name": item.question,
                "acceptedAnswer": {"@type": "Answer", "text": item.answer},
            }
            for item in page.faqs
        ],
    }


def _howto_node(page: Page) -> dict[str, Any] | None:
    if not page.how_to_steps:
        return None
    return {
        "@type": "HowTo",
        "@id": f"{page.url}#howto",
        "name": page.title or "How to",
        "step": [
            {"@type": "HowToStep", "name": step.name, "text": step.text or step.name}
            for step in page.how_to_steps
        ],
    }


def _service_graph(
    business: Business, page: Page, breadcrumbs: Sequence[Breadcrumb]
) -> list[dict[str, Any]]:
    service: dict[str, Any] = {
        "@type": "Service",
        "@id": f"{page.url}#service",
        "name": page.title or business.name,
        "provider": {"@id": _org_id(business)},
    }
    if page.service_type:
        service["serviceType"] = page.service_type
    area = page.area_served or business.area_served
    if area:
        service["areaServed"] = list(area)
    if page.url:
        service["url"] = page.url
    if page.description:
        service["description"] = page.description

    graph: list[dict[str, Any]] = [service]
    crumb = _breadcrumb_node(page, breadcrumbs)
    if crumb is not None:
        graph.append(crumb)
    graph.append(_organization_node(business))
    return graph


def _local_graph(
    business: Business, page: Page, breadcrumbs: Sequence[Breadcrumb]
) -> list[dict[str, Any]]:
    local: dict[str, Any] = {
        "@type": business.business_type or "LocalBusiness",
        "@id": f"{business.url}#localbusiness",
        "name": business.name,
    }
    if business.telephone:
        local["telephone"] = business.telephone
    if business.url:
        local["url"] = business.url
    if business.image:
        local["image"] = business.image
    if business.price_range:
        local["priceRange"] = business.price_range
    if business.same_as:
        local["sameAs"] = list(business.same_as)

    # SAB vs storefront: a storefront publishes its address; a service-area
    # business hides it and markets an areaServed instead.
    has_address = business.address is not None and not business.address.is_empty()
    area = tuple(business.area_served or page.area_served)
    if business.has_public_address and has_address:
        assert business.address is not None  # narrowed by has_address
        local["address"] = _address_node(business.address)
    elif area:
        local["areaServed"] = list(area)

    if business.geo is not None:
        local["geo"] = _geo_node(business.geo)
    if business.opening_hours:
        local["openingHoursSpecification"] = _opening_hours_specs(business.opening_hours)
    if business.aggregate_rating is not None and business.aggregate_rating.review_count > 0:
        local["aggregateRating"] = _aggregate_rating_node(business.aggregate_rating)
    # Brand entity link (LocalBusiness IS-A Organization; the brand node is the
    # parent for graph cohesion / sameAs consolidation).
    local["parentOrganization"] = {"@id": _org_id(business)}

    graph: list[dict[str, Any]] = [local]
    crumb = _breadcrumb_node(page, breadcrumbs)
    if crumb is not None:
        graph.append(crumb)
    graph.append(_organization_node(business))
    return graph


def _blog_graph(
    business: Business, page: Page, breadcrumbs: Sequence[Breadcrumb]
) -> list[dict[str, Any]]:
    article: dict[str, Any] = {
        "@type": page.article_type or "BlogPosting",
        "@id": f"{page.url}#article",
        "headline": page.title,
        "publisher": {"@id": _org_id(business)},
    }
    if page.author is not None:
        author: dict[str, Any] = {
            "@type": "Organization" if page.author.is_organization else "Person",
            "name": page.author.name,
        }
        if page.author.url:
            author["url"] = page.author.url
        article["author"] = author
    if page.date_published:
        article["datePublished"] = page.date_published
    if page.date_modified:
        article["dateModified"] = page.date_modified
    if page.url:
        article["mainEntityOfPage"] = page.url
    if page.image:
        article["image"] = page.image
    if page.description:
        article["description"] = page.description

    graph: list[dict[str, Any]] = [article]
    crumb = _breadcrumb_node(page, breadcrumbs)
    if crumb is not None:
        graph.append(crumb)
    graph.append(_organization_node(business))
    return graph


_BUILDERS: dict[str, Any] = {
    "service": _service_graph,
    "local": _local_graph,
    "blog": _blog_graph,
}


def build_json_ld(
    page_type: str,
    business: Business,
    page: Page,
    breadcrumbs: Sequence[Breadcrumb] = (),
) -> dict[str, Any]:
    """Build the Schema.org JSON-LD ``@graph`` for a content job.

    Dispatches on ``page_type`` (service / local / blog; an unknown type falls
    back to the blog/Article shape, matching ``schema_for``). Any FAQ Q&A or
    how-to steps on ``page`` append **FAQPage** / **HowTo** nodes (kept for
    semantics - :func:`rich_result_eligible` flags them non-rich). The return is a
    single ``{"@context": ..., "@graph": [...]}`` document; the FIRST node is the
    page's primary type."""
    key = (page_type or "").strip().lower()
    builder = _BUILDERS.get(key, _blog_graph)
    graph = builder(business, page, breadcrumbs)

    faq = _faq_node(page)
    if faq is not None:
        graph.append(faq)
    howto = _howto_node(page)
    if howto is not None:
        graph.append(howto)

    return {"@context": _SCHEMA_CONTEXT, "@graph": graph}


# --------------------------------------------------------------------------- #
# Validation
# --------------------------------------------------------------------------- #
def _primary_type(node: Mapping[str, Any]) -> str | None:
    """The node's primary ``@type`` (the first entry when ``@type`` is a list)."""
    value = node.get("@type")
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        for item in value:
            if isinstance(item, str):
                return item
    return None


def _graph_nodes(graph: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Flatten a JSON-LD document to its list of typed nodes. Accepts the
    ``@graph`` array form or a single bare node."""
    inner = graph.get("@graph")
    if isinstance(inner, list):
        return [n for n in inner if isinstance(n, dict)]
    if "@type" in graph:
        return [dict(graph)]
    return []


def _family(type_name: str | None) -> str:
    if type_name in _LOCAL_TYPES:
        return "local"
    if type_name in _ARTICLE_TYPES:
        return "article"
    if type_name == "Service":
        return "service"
    return type_name or ""


def _coerce_visible(visible_content: VisibleContent | str | None) -> VisibleContent:
    if isinstance(visible_content, VisibleContent):
        return visible_content
    if isinstance(visible_content, str):
        return VisibleContent(text=visible_content)
    return VisibleContent()


def _content_claims(node: Mapping[str, Any]) -> Iterator[tuple[str, str, str]]:
    """Yield ``(label, value, kind)`` for every ASSERTED content claim on a node
    that must be visible on the page. Identity/metadata (url, dates, @id, sameAs,
    priceRange, geo) is intentionally excluded - only human-visible claims."""
    family = _family(_primary_type(node))
    if family == "local":
        name = node.get("name")
        if isinstance(name, str) and name:
            yield ("name", name, _TEXT)
        phone = node.get("telephone")
        if isinstance(phone, str) and phone:
            yield ("telephone", phone, _PHONE)
        address = node.get("address")
        if isinstance(address, dict):
            for key in ("streetAddress", "addressLocality", "addressRegion", "postalCode"):
                part = address.get(key)
                if isinstance(part, str) and part:
                    yield (key, part, _TEXT)
        for area in _as_list(node.get("areaServed")):
            yield ("areaServed", area, _TEXT)
    elif family == "service":
        name = node.get("name")
        if isinstance(name, str) and name:
            yield ("name", name, _TEXT)
        service_type = node.get("serviceType")
        if isinstance(service_type, str) and service_type:
            yield ("serviceType", service_type, _TEXT)
        for area in _as_list(node.get("areaServed")):
            yield ("areaServed", area, _TEXT)
    elif family == "article":
        headline = node.get("headline")
        if isinstance(headline, str) and headline:
            yield ("headline", headline, _TEXT)
    elif _primary_type(node) == "FAQPage":
        for question in node.get("mainEntity", []) or []:
            if not isinstance(question, dict):
                continue
            q_name = question.get("name")
            if isinstance(q_name, str) and q_name:
                yield ("FAQ question", q_name, _TEXT)
            answer = question.get("acceptedAnswer")
            if isinstance(answer, dict):
                text = answer.get("text")
                if isinstance(text, str) and text:
                    yield ("FAQ answer", text, _TEXT)
    elif _primary_type(node) == "HowTo":
        for step in node.get("step", []) or []:
            if not isinstance(step, dict):
                continue
            value = step.get("name") or step.get("text")
            if isinstance(value, str) and value:
                yield ("HowTo step", value, _TEXT)


def _visible_match(value: str, kind: str, visible: VisibleContent) -> bool:
    """Whether an asserted claim appears in the visible page text. Phone numbers
    match on their trailing (local) digits so formatting/country-code differences
    do not cause a false miss."""
    if not value:
        return True
    if kind == _PHONE:
        wanted = _digits(value)
        if not wanted:
            return True
        return wanted[-10:] in _digits(visible.text)
    return _norm(value) in _norm(visible.text)


def _check_required(
    node: Mapping[str, Any], type_name: str, errors: list[str]
) -> None:
    family = _family(type_name)
    if family == "local":
        required: frozenset[str] = _LOCAL_REQUIRED
    elif family == "article":
        required = _ARTICLE_REQUIRED
    else:
        required = _REQUIRED_BY_TYPE.get(type_name or "", frozenset())
    for key in sorted(required):
        if not node.get(key):
            errors.append(f"{type_name}: missing required property '{key}'")
    if family == "local" and not node.get("address") and not node.get("areaServed"):
        errors.append(
            f"{type_name}: needs an 'address' (storefront) or 'areaServed' (SAB) - neither present"
        )


def _check_recommended(
    node: Mapping[str, Any], type_name: str, warnings: list[str]
) -> None:
    family = _family(type_name)
    for key in _RECOMMENDED_BY_FAMILY.get(family, ()):
        if key not in node:
            warnings.append(f"{type_name}: recommended property '{key}' missing")


def _check_nesting(
    node: Mapping[str, Any], type_name: str, ids: set[str], errors: list[str], warnings: list[str]
) -> None:
    address = node.get("address")
    if address is not None and not isinstance(address, dict):
        errors.append(f"{type_name}: 'address' must be a PostalAddress object, not a bare string")
    elif isinstance(address, dict):
        if address.get("@type") != "PostalAddress":
            warnings.append(f"{type_name}: 'address' should declare @type PostalAddress")
        if not address.get("addressCountry"):
            warnings.append(f"{type_name}: 'address' missing addressCountry (rich-result ineligible)")

    for ref_key in ("provider", "publisher"):
        ref = node.get(ref_key)
        if ref is None:
            continue
        if not isinstance(ref, dict):
            errors.append(f"{type_name}: '{ref_key}' must be an object or an @id reference")
            continue
        ref_id = ref.get("@id")
        if isinstance(ref_id, str) and ref_id and ref_id not in ids and not ref.get("name"):
            warnings.append(f"{type_name}: '{ref_key}' @id '{ref_id}' resolves to no node in the graph")

    item_list = node.get("itemListElement")
    if item_list is not None:
        if not isinstance(item_list, list) or not item_list:
            errors.append(f"{type_name}: 'itemListElement' must be a non-empty list of ListItem")
        else:
            for entry in item_list:
                if not isinstance(entry, dict) or "position" not in entry or not (
                    entry.get("name") or entry.get("item")
                ):
                    errors.append(
                        f"{type_name}: each 'itemListElement' needs a position and a name/item"
                    )
                    break

    geo = node.get("geo")
    if isinstance(geo, dict) and ("latitude" not in geo or "longitude" not in geo):
        errors.append(f"{type_name}: 'geo' needs both latitude and longitude")

    for date_key in ("datePublished", "dateModified"):
        value = node.get(date_key)
        if isinstance(value, str) and value and not _ISO_DATE_RE.match(value):
            warnings.append(f"{type_name}: '{date_key}' is not ISO 8601 (YYYY-MM-DD)")


def _check_aggregate_rating(
    node: Mapping[str, Any], type_name: str, visible: VisibleContent, errors: list[str]
) -> None:
    rating = node.get("aggregateRating")
    if rating is None:
        return
    if not isinstance(rating, dict):
        errors.append(f"{type_name}: 'aggregateRating' must be an AggregateRating object")
        return
    if not visible.has_reviews:
        errors.append(
            f"{type_name}: 'aggregateRating' present but the page shows no reviews "
            "(self-serving/fake rating - not allowed)"
        )
        return
    count = rating.get("reviewCount")
    if count is None:
        count = rating.get("ratingCount")
    if not isinstance(count, (int, float)) or count <= 0:
        errors.append(
            f"{type_name}: 'aggregateRating' has no positive reviewCount (unbacked rating)"
        )
    rating_value = rating.get("ratingValue")
    best = rating.get("bestRating", 5)
    if (
        isinstance(rating_value, (int, float))
        and isinstance(best, (int, float))
        and rating_value > best
    ):
        errors.append(f"{type_name}: 'ratingValue' exceeds 'bestRating'")


def _check_match_visible(
    node: Mapping[str, Any], type_name: str, visible: VisibleContent, errors: list[str]
) -> None:
    for label, value, kind in _content_claims(node):
        if not _visible_match(value, kind, visible):
            errors.append(
                f"{type_name}: marked-up {label} '{value}' is not present in the visible content"
            )


def _validate_node(
    node: Mapping[str, Any], visible: VisibleContent, ids: set[str]
) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    type_name = _primary_type(node)
    if type_name is None:
        errors.append("node is missing an @type")
        return errors, warnings
    _check_required(node, type_name, errors)
    _check_recommended(node, type_name, warnings)
    _check_nesting(node, type_name, ids, errors, warnings)
    _check_aggregate_rating(node, type_name, visible, errors)
    _check_match_visible(node, type_name, visible, errors)
    return errors, warnings


def validate_json_ld(
    graph: Mapping[str, Any], visible_content: VisibleContent | str | None
) -> ValidationResult:
    """Validate a JSON-LD document against the page's visible content.

    Enforces required properties, correct nesting, match-visible-content (no
    marking up a claim absent from ``visible_content``), and the no-fake-rating
    rule. Returns errors + warnings, the ``primary_type`` (first node's ``@type``,
    which feeds the content contract's ``schema`` field), and per-type
    rich-result eligibility. ``valid`` is ``True`` iff there are zero errors."""
    visible = _coerce_visible(visible_content)
    nodes = _graph_nodes(graph)
    if not nodes:
        return ValidationResult(
            valid=False,
            primary_type=None,
            errors=["graph has no typed nodes"],
        )

    context = graph.get("@context")
    warnings: list[str] = []
    if context is None:
        warnings.append("missing @context (should be https://schema.org)")
    elif "schema.org" not in str(context):
        warnings.append(f"unexpected @context: {context!r}")

    ids = {n["@id"] for n in nodes if isinstance(n.get("@id"), str)}
    errors: list[str] = []
    rich_types: dict[str, bool] = {}
    for node in nodes:
        node_errors, node_warnings = _validate_node(node, visible, ids)
        errors.extend(node_errors)
        warnings.extend(node_warnings)
        type_name = _primary_type(node)
        if type_name is not None:
            rich_types[type_name] = rich_result_eligible(
                type_name, has_errors=bool(node_errors)
            )

    return ValidationResult(
        valid=not errors,
        primary_type=_primary_type(nodes[0]),
        errors=errors,
        warnings=warnings,
        rich_result_types=rich_types,
        rich_result_eligible=any(rich_types.values()),
    )
