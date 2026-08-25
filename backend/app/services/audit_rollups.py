"""MACRO: the pillar / subpoint verdict, and the coverage that qualifies it.

THE DEFECT THIS REPLACES, measured twice on real runs:

  * Run 3055416d scored **58.0** overall - the plain mean of on-page 44.2 and
    technical 71.8. ``off_page`` and ``local`` were null and were DROPPED FROM
    THE DENOMINATOR, so a free score and a deep score are computed over different
    denominators and are not comparable. (R4-F6, observed.)
  * Run 837b75d6 scored technical **97.2** having run **25 of 100** technical
    checks. A client reading "your technical SEO is 97/100" was reading a number
    computed over a quarter of the technical checklist.

THE FIX IS NOT TO PATCH THE RENORMALISATION - IT IS TO DELETE THE WEIGHTED
CATEGORY ROLLUP ENTIRELY. Every level uses one flat formula over the checks that
actually ran at that level:

    score = 100 * (1 - severity_mass(failed) / severity_mass(ran))

A pillar score is NOT a weighted average of its subpoints; it is the same formula
over the pillar's own ran-set. There is no per-category weight table, therefore
there is nothing to renormalise, therefore the defect is not representable.

Two further rules make the number honest:

  * ``checks_ran == 0`` yields ``score = None``, which renders as
    "not measured (0 of 71 checks)". Never 0 - a zero score and an unmeasured
    dimension are opposite claims and must not share a value.
  * every row carries ``basis_hash``. Two scores may be compared only when it
    matches, so a tier change or a lapsed provider key cannot silently move a
    trend line.

``url_health_pct`` ships alongside as a second, basis-free number: its
denominator is PAGES, not checks, so it stays comparable across tiers and months
even when the check set changes.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Iterable

from app.services.audit_altitude import Cause

SCORING_MODEL_VERSION = "flat-severity-mass-v1"

#: Same weights the engine's aggregator uses, kept so scores stay comparable with
#: the engine's own composite during the transition.
SEVERITY_WEIGHT: dict[str, float] = {
    "critical": 3.0, "major": 2.0, "minor": 1.0, "info": 0.5,
}
_DEFAULT_WEIGHT = 1.0

LEVEL_SITE = "site"
LEVEL_PILLAR = "pillar"
LEVEL_DIMENSION = "dimension"
LEVEL_SUBPOINT = "subpoint"

PILLAR_LABEL = {
    "on-page": "On-Page", "technical": "Technical",
    "off-page": "Off-Page", "local-seo": "Local SEO",
}
DIMENSION_LABEL = {
    "onpage": "On-Page", "technical": "Technical", "offpage": "Off-Page",
    "local": "Local SEO", "geo": "GEO / AI Search", "strategy": "Strategy",
}


@dataclass(frozen=True, slots=True)
class CheckFacts:
    """The registry facts for one check, as carried in ``coverage.json``.

    The platform deliberately reads these from the artifact rather than from the
    checklist YAML: the engine is a separate process today, and a score that
    depended on the platform having a copy of the engine's checklists would drift
    the moment the two versions differed.
    """
    id: str
    name: str
    pillar: str
    subcategory: str
    dimension: str
    owner_agent: str
    severity_default: str
    automation: str


def registry_from_coverage(coverage: dict[str, Any]) -> dict[str, CheckFacts]:
    out: dict[str, CheckFacts] = {}
    for cid, c in (coverage.get("checks") or {}).items():
        out[cid] = CheckFacts(
            id=cid,
            name=c.get("name", ""),
            pillar=c.get("pillar", ""),
            subcategory=c.get("subcategory", ""),
            dimension=c.get("dimension", ""),
            owner_agent=c.get("owner_agent", ""),
            severity_default=c.get("severity_default", "info"),
            automation=c.get("automation", ""),
        )
    return out


@dataclass(slots=True)
class Rollup:
    level: str
    key: str
    label: str
    checks_applicable: int = 0
    checks_planned: int = 0
    checks_ran: int = 0
    checks_skipped: int = 0
    skip_reasons: dict[str, int] = field(default_factory=dict)
    findings_open: int = 0
    instances_open: int = 0
    pages_affected: int = 0
    pages_crawled: int = 0
    severity_counts: dict[str, int] = field(default_factory=dict)
    status_counts: dict[str, int] = field(default_factory=dict)
    score: float | None = None
    url_health_pct: float | None = None
    basis_hash: str = ""
    scoring_model_version: str = SCORING_MODEL_VERSION


def weight(severity: str) -> float:
    return SEVERITY_WEIGHT.get((severity or "").lower(), _DEFAULT_WEIGHT)


def compute_basis_hash(
    *, tier: str, types: Iterable[str], checks_ran: Iterable[str],
    fingerprint_version: int,
) -> str:
    """Identity of the MEASUREMENT, not of the result.

    Two scores are comparable only when this matches. It deliberately includes
    the exact set of checks that ran: a lapsed provider key changes the set,
    which must change the basis rather than silently move the score.
    """
    payload = {
        "tier": tier,
        "types": sorted(set(types)),
        "checks": sorted(set(checks_ran)),
        "fp": fingerprint_version,
        "model": SCORING_MODEL_VERSION,
    }
    return hashlib.sha1(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()[:16]


def _score(ran_weights: float, failed_weights: float) -> float | None:
    """The one formula, used identically at every level.

    Returns None when nothing ran. That is the difference between "we measured
    this and it is perfect" and "we did not measure this".
    """
    if ran_weights <= 0:
        return None
    raw = 100.0 * (1.0 - (failed_weights / ran_weights))
    return round(max(0.0, min(100.0, raw)), 1)


def _bucket_keys(spec_pillar: str, spec_subcat: str, spec_dimension: str) -> dict[str, str]:
    return {
        LEVEL_SITE: "",
        LEVEL_PILLAR: spec_pillar,
        LEVEL_DIMENSION: spec_dimension,
        LEVEL_SUBPOINT: f"{spec_pillar}/{spec_subcat}",
    }


def subpoint_labels_from_coverage(coverage: dict[str, Any]) -> dict[str, str]:
    """Display names for `pillar/subpoint`, as published by the engine.

    Read from the artifact rather than duplicated here: the engine owns the
    checklist, so it owns what its keys are called. An older artifact without the
    map simply yields raw keys, which is what happened before this existed.
    """
    raw = coverage.get("subpoint_labels") or {}
    return {str(k): str(v) for k, v in raw.items() if v}


def build_rollups(
    *,
    causes: list[Cause],
    coverage: dict[str, Any],
    registry: dict[str, Any],
    pages: list[dict[str, Any]],
    tier: str = "",
    types: Iterable[str] = (),
    fingerprint_version: int = 1,
) -> list[Rollup]:
    """Compute every rollup row for one audit.

    ``registry`` is the canonical check registry (check_id -> spec-like object
    exposing ``pillar``, ``subcategory``, ``dimension``, ``severity_default``).
    ``coverage`` is the engine's coverage.json.
    """
    ran_ids: set[str] = set(coverage.get("ran") or [])
    skipped = coverage.get("skipped") or []
    planned_ids = ran_ids | {
        s["check_id"] for s in skipped if s.get("reason") == "no_finding_emitted"
    }

    basis = compute_basis_hash(
        tier=tier, types=types, checks_ran=ran_ids,
        fingerprint_version=fingerprint_version,
    )

    # Which checks actually FAILED (produced at least one issue cause), and the
    # worst severity observed for each. Severity comes from the observation, not
    # from the default, because that is what was measured.
    failed_severity: dict[str, str] = {}
    for c in causes:
        prev = failed_severity.get(c.check_id)
        if prev is None or weight(c.severity) > weight(prev):
            failed_severity[c.check_id] = c.severity

    sub_labels = subpoint_labels_from_coverage(coverage)
    rollups: dict[tuple[str, str], Rollup] = {}
    ran_mass: dict[tuple[str, str], float] = {}
    failed_mass: dict[tuple[str, str], float] = {}

    def _get(level: str, key: str, label: str) -> Rollup:
        rk = (level, key)
        r = rollups.get(rk)
        if r is None:
            r = Rollup(level=level, key=key, label=label, basis_hash=basis)
            rollups[rk] = r
            ran_mass[rk] = 0.0
            failed_mass[rk] = 0.0
        return r

    # --- coverage + score mass, walked over the WHOLE registry so every level
    # --- always knows its denominator ("25 of 100"), not just its numerator.
    skip_reason_by_id = {s["check_id"]: s.get("reason", "") for s in skipped}
    for check_id, spec in registry.items():
        keys = _bucket_keys(spec.pillar, spec.subcategory, spec.dimension)
        labels = {
            LEVEL_SITE: "Site",
            LEVEL_PILLAR: PILLAR_LABEL.get(spec.pillar, spec.pillar),
            LEVEL_DIMENSION: DIMENSION_LABEL.get(spec.dimension, spec.dimension),
            # The client-facing name, not the internal key. `semantic-3.8-koray`
            # is a researcher's surname and was being printed on a scorecard.
            LEVEL_SUBPOINT: sub_labels.get(
                f"{spec.pillar}/{spec.subcategory}", spec.subcategory
            ),
        }
        for level, key in keys.items():
            r = _get(level, key, labels[level])
            rk = (level, key)
            r.checks_applicable += 1
            if check_id in planned_ids:
                r.checks_planned += 1
            if check_id in ran_ids:
                r.checks_ran += 1
                ran_mass[rk] += weight(spec.severity_default)
                if check_id in failed_severity:
                    failed_mass[rk] += weight(failed_severity[check_id])
            else:
                r.checks_skipped += 1
                reason = skip_reason_by_id.get(check_id, "unknown")
                r.skip_reasons[reason] = r.skip_reasons.get(reason, 0) + 1

    # --- findings + instances
    for c in causes:
        spec = registry.get(c.check_id)
        pillar = c.pillar or (spec.pillar if spec else "")
        subcat = c.subcategory or (spec.subcategory if spec else "")
        dimension = c.dimension or (spec.dimension if spec else "")
        for level, key in _bucket_keys(pillar, subcat, dimension).items():
            r = rollups.get((level, key))
            if r is None:
                continue
            r.findings_open += 1
            r.instances_open += c.instance_count
            r.severity_counts[c.severity] = r.severity_counts.get(c.severity, 0) + 1

    # --- pages: affected per level, crawled globally
    pages_crawled = len(pages)
    urls_by_level: dict[tuple[str, str], set[str]] = {}
    for c in causes:
        spec = registry.get(c.check_id)
        pillar = c.pillar or (spec.pillar if spec else "")
        subcat = c.subcategory or (spec.subcategory if spec else "")
        dimension = c.dimension or (spec.dimension if spec else "")
        urls = {i.url for i in c.instances if i.url}
        for level, key in _bucket_keys(pillar, subcat, dimension).items():
            urls_by_level.setdefault((level, key), set()).update(urls)

    # url_health_pct: the share of crawled pages carrying NO CRITICAL instance.
    # Denominator is pages, so it survives a change of check set - which is
    # precisely what `score` cannot do.
    #
    # CRITICAL ONLY, deliberately. Including `major` was tried against real run
    # 837b75d6 and returned 0.0% - every one of 197 pages carried at least one
    # major finding (alt text, readability), so the metric could not discriminate
    # and told the operator nothing. A page missing an alt attribute is not an
    # UNHEALTHY page; a page that is accidentally noindexed, 404s, or has no H1
    # is. This matches the severity bar Ahrefs uses for its health score, where
    # only errors count and warnings/notices do not.
    unhealthy: set[str] = set()
    for c in causes:
        if c.severity == "critical":
            unhealthy.update(i.url for i in c.instances if i.url)
    health = (
        round(100.0 * (pages_crawled - len(unhealthy)) / pages_crawled, 1)
        if pages_crawled else None
    )

    for rk, r in rollups.items():
        r.pages_crawled = pages_crawled
        r.pages_affected = len(urls_by_level.get(rk, ()))
        r.score = _score(ran_mass[rk], failed_mass[rk])
        r.url_health_pct = health if r.level == LEVEL_SITE else None

    order = {LEVEL_SITE: 0, LEVEL_DIMENSION: 1, LEVEL_PILLAR: 2, LEVEL_SUBPOINT: 3}
    return sorted(rollups.values(), key=lambda r: (order[r.level], r.key))
