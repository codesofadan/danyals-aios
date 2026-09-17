"""JSON-LD validation helpers.

Lightweight Schema.org awareness for the on-page MVP. Validates @type, required
keys per common types (LocalBusiness, Article, FAQPage, Service, BreadcrumbList),
and computes rich-result eligibility per Google docs.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# Minimal required-property map per Schema.org type for common rich results.
REQUIRED_PROPERTIES: dict[str, set[str]] = {
    "LocalBusiness": {"name", "address"},
    "Restaurant": {"name", "address"},
    "Store": {"name", "address"},
    "Organization": {"name"},
    "Article": {"headline", "datePublished", "author"},
    "NewsArticle": {"headline", "datePublished", "author"},
    "BlogPosting": {"headline", "datePublished", "author"},
    "FAQPage": {"mainEntity"},
    "Service": {"name", "provider"},
    "Product": {"name"},
    "BreadcrumbList": {"itemListElement"},
    "Event": {"name", "startDate", "location"},
}

RICH_RESULT_ELIGIBLE_TYPES = set(REQUIRED_PROPERTIES.keys())


@dataclass
class SchemaValidationResult:
    type: str | None
    valid: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    rich_result_eligible: bool = False


def _get_types(block: dict) -> list[str]:
    t = block.get("@type")
    if isinstance(t, list):
        return [str(x) for x in t]
    if isinstance(t, str):
        return [t]
    return []


def validate_block(block: dict[str, Any]) -> SchemaValidationResult:
    types = _get_types(block)
    if not types:
        return SchemaValidationResult(type=None, valid=False, errors=["missing @type"])

    primary = types[0]
    errs: list[str] = []
    warns: list[str] = []

    required = REQUIRED_PROPERTIES.get(primary)
    if required is None:
        warns.append(f"no required-property rules registered for type '{primary}'")
    else:
        for key in required:
            if key not in block or not block[key]:
                errs.append(f"missing required '{key}' for {primary}")

    if "@context" not in block:
        warns.append("missing @context (should be https://schema.org)")
    elif "schema.org" not in str(block.get("@context")):
        warns.append(f"unexpected @context: {block.get('@context')}")

    eligible = primary in RICH_RESULT_ELIGIBLE_TYPES and not errs

    return SchemaValidationResult(
        type=primary, valid=not errs, errors=errs, warnings=warns, rich_result_eligible=eligible
    )


def validate_all(blocks: list[dict]) -> list[SchemaValidationResult]:
    return [validate_block(b) for b in blocks if isinstance(b, dict)]
