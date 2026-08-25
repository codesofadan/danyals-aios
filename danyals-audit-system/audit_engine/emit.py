"""The altitude contract - the artifacts the platform needs and the engine withheld.

MEASURED PROBLEM (``docs/audit/fixtures/README.md``, run 837b75d6, 197 pages):

* ``findings.json`` carries ``page_id``, a per-run autoincrement, and **no URL**.
  The URL lives only in the engine's ``pages`` table, which was never emitted, so
  the per-page grain was unrecoverable from the artifacts alone.
* ``subcategory`` was populated on **38%** of findings and twice carried a value
  outside the checklist vocabulary.
* **160 of 363** checks fired and nothing recorded which 203 did not, or why - so
  a skipped check and a passing check were indistinguishable to every consumer.

This module writes three things next to the existing report bundle. It is
ADDITIVE: no existing artifact changes shape, so every current consumer keeps
working while the platform gains what it needs.

    pages.json      one row per crawled URL - the page dimension
    coverage.json   all 363 checks: planned / ran / skipped, with a reason
    findings.json   enriched in place with registry-canonical taxonomy fields

Deliberately pure: it reads a sqlite connection and returns dicts. No network, no
clock beyond what the caller passes, no model. That is what lets the platform
re-derive the same answer from the same run.
"""

from __future__ import annotations

import importlib
import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from audit_engine import checklist as cl

# A check that emitted no row at all did not run. A check that emitted `pass`
# DID run and found nothing wrong. Keeping those apart is the entire point.
SKIP_NOT_SELECTED = "not_in_selected_dimensions"
SKIP_SOURCE_NOT_PERMITTED = "source_not_permitted"
SKIP_NO_OUTPUT = "no_finding_emitted"
#: The check produced nothing AND its declared `analyzer:` path does not import.
#:
#: READ THIS AS A DIAGNOSTIC, NOT A VERDICT. The `analyzer:` field is demonstrably
#: stale: on real run 837b75d6 **160 checks ran while only 31 declared paths
#: resolve**, so roughly 129 working checks are dispatched by some route other
#: than their declared path. A path that fails to import therefore does NOT prove
#: the check is unimplemented - it proves the declaration is unusable.
#:
#: What it IS good for: of the 90 free, deterministic checks that produced nothing
#: on that run, 82 had no analyzer module at all and 8 had a module but no
#: function, and none were implemented-but-silent. That is a real, actionable
#: backlog - it just must not be reported to a client as "your site was checked".
SKIP_UNRESOLVED_ANALYZER = "analyzer_path_unresolved"


@lru_cache(maxsize=None)
def analyzer_path_resolves(dotted_path: str) -> bool:
    """Does the check's declared ``analyzer:`` path actually import?

    NOT a test of whether the check is implemented - see SKIP_UNRESOLVED_ANALYZER.
    Many checks that run have stale declarations. Resolved by import rather than
    a hand-kept list, and cached because it is asked once per check per run.
    """
    if not dotted_path:
        return False
    module_path, _, attr = dotted_path.rpartition(".")
    if not module_path:
        return False
    try:
        module = importlib.import_module(module_path)
    except Exception:  # noqa: BLE001 - any import failure means it cannot run
        return False
    return hasattr(module, attr)


def enrich_findings(findings: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Join each finding to its registry entry and fill the taxonomy fields.

    Returns the enriched list and a small stats dict. The registry WINS on
    disagreement: an analyzer that emitted ``geo-ai`` when the checklist says
    ``ai-search`` is corrected, and the correction is counted so the drift is
    visible rather than absorbed.

    ``category`` is deliberately left alone - it is already correct on every
    observed row and downstream reporters key off it.
    """
    stats = {"enriched": 0, "corrected": 0, "unknown_check_id": 0, "total": len(findings)}
    out: list[dict[str, Any]] = []
    for raw in findings:
        f = dict(raw)
        spec = cl.get(str(f.get("check_id") or ""))
        if spec is None:
            stats["unknown_check_id"] += 1
            f.setdefault("dimension", None)
            out.append(f)
            continue
        current = (f.get("subcategory") or "").strip()
        if not current:
            stats["enriched"] += 1
        elif current != spec.subcategory:
            stats["corrected"] += 1
        f["subcategory"] = spec.subcategory
        f["owner_agent"] = f.get("owner_agent") or spec.owner_agent
        # New fields. Additive - nothing downstream reads them yet.
        f["dimension"] = spec.dimension
        f["pillar"] = spec.pillar
        f["automation"] = spec.automation
        f["check_name"] = f.get("check_name") or spec.name
        out.append(f)
    return out, stats


def build_pages(page_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The page dimension, in the shape the platform ingests.

    ``id`` is kept under its own name because it is the join key ``findings.page_id``
    points at, and it is explicitly labelled per-run so nobody mistakes it for a
    stable identifier across runs.
    """
    pages: list[dict[str, Any]] = []
    for r in page_rows:
        pages.append({
            "page_id": r.get("id"),
            "url": r.get("url"),
            "canonical_url": r.get("canonical_url"),
            "page_type": r.get("page_type"),
            "http_status": r.get("http_status"),
            "response_ms": r.get("response_ms"),
            "title": r.get("title"),
            "meta_description": r.get("meta_description"),
            "h1": r.get("h1"),
            "word_count": r.get("word_count"),
            "indexable": r.get("indexable"),
            "crawl_depth": r.get("crawl_depth"),
            "is_orphan": r.get("is_orphan"),
        })
    return pages


def build_coverage(
    findings: list[dict[str, Any]],
    *,
    dimensions: frozenset[str] | None,
    permitted_cost_classes: frozenset[str],
) -> dict[str, Any]:
    """What ran, what did not, and why - over the whole 363-check registry.

    ``ran`` is defined as *emitted at least one finding row*, which is the only
    thing observable from the artifacts. It is named that way on purpose: this
    function does not claim to know that an analyzer executed, only that it
    produced output.

    Skip reasons are assigned in precedence order, most specific first, so a
    check outside the selected dimensions is reported as such rather than as a
    provider problem.
    """
    registry = cl.load_registry()
    selected = cl.checks_for_dimensions(dimensions)
    emitted: dict[str, int] = {}
    for f in findings:
        cid = str(f.get("check_id") or "")
        if cid:
            emitted[cid] = emitted.get(cid, 0) + 1

    planned: list[str] = []
    skipped: list[dict[str, str]] = []
    for cid, spec in registry.items():
        if cid not in selected:
            skipped.append({"check_id": cid, "reason": SKIP_NOT_SELECTED})
            continue
        if not spec.runs_under(permitted_cost_classes):
            skipped.append({"check_id": cid, "reason": SKIP_SOURCE_NOT_PERMITTED})
            continue
        planned.append(cid)

    ran = sorted(c for c in planned if c in emitted)
    # Separate "ran and found nothing" from "its analyzer declaration does not
    # even import". Both previously read as `no_finding_emitted`, which implies a
    # clean bill of health for a check that may never have executed.
    no_output: list[dict[str, str]] = []
    unresolved: list[dict[str, str]] = []
    for c in planned:
        if c in emitted:
            continue
        if analyzer_path_resolves(registry[c].analyzer):
            no_output.append({"check_id": c, "reason": SKIP_NO_OUTPUT})
        else:
            unresolved.append({"check_id": c, "reason": SKIP_UNRESOLVED_ANALYZER})
    skipped.extend(no_output)
    skipped.extend(unresolved)

    # Rollups by the two axes the report is organised around. `applicable` is what
    # the FULL registry holds for that key, so a section can always say "3 of 71"
    # rather than only "3".
    def _rollup(attr: str) -> dict[str, dict[str, int]]:
        out: dict[str, dict[str, int]] = {}
        for cid, spec in registry.items():
            key = getattr(spec, attr)
            b = out.setdefault(key, {"applicable": 0, "planned": 0, "ran": 0, "findings": 0})
            b["applicable"] += 1
            if cid in planned:
                b["planned"] += 1
            if cid in emitted:
                b["ran"] += 1
                b["findings"] += emitted[cid]
        return dict(sorted(out.items()))

    subpoint: dict[str, dict[str, int]] = {}
    for cid, spec in registry.items():
        key = f"{spec.pillar}/{spec.subcategory}"
        b = subpoint.setdefault(key, {"applicable": 0, "planned": 0, "ran": 0, "findings": 0})
        b["applicable"] += 1
        if cid in planned:
            b["planned"] += 1
        if cid in emitted:
            b["ran"] += 1
            b["findings"] += emitted[cid]

    # The registry facts each check carries, embedded so coverage.json is
    # SELF-CONTAINED: the platform can score, roll up and label a run without
    # needing the checklist YAML on its own filesystem. ~363 small entries.
    checks = {
        cid: {
            "name": spec.name,
            "pillar": spec.pillar,
            "subcategory": spec.subcategory,
            "dimension": spec.dimension,
            "owner_agent": spec.owner_agent,
            "severity_default": spec.severity_default,
            "automation": spec.automation,
            "analyzer_path_resolves": analyzer_path_resolves(spec.analyzer),
            "data_sources": list(spec.data_sources),
            "cost_classes": sorted(spec.cost_classes),
        }
        for cid, spec in sorted(registry.items())
    }

    # Display names for every pillar/subpoint pair, so the platform can label a
    # scorecard without carrying its own copy of the vocabulary. The engine owns
    # the checklist, therefore the engine owns what its keys are CALLED.
    subpoint_labels = {
        f"{spec.pillar}/{spec.subcategory}": cl.subpoint_label(spec.pillar, spec.subcategory)
        for spec in registry.values()
    }

    return {
        "registry_total": len(registry),
        "checks": checks,
        "subpoint_labels": dict(sorted(subpoint_labels.items())),
        "selected_dimensions": sorted(dimensions) if dimensions else [],
        "permitted_cost_classes": sorted(permitted_cost_classes),
        "counts": {
            "planned": len(planned),
            "ran": len(ran),
            "skipped": len(skipped),
            "no_output": len(no_output),
            "analyzer_path_unresolved": len(unresolved),
        },
        "ran": ran,
        "skipped": sorted(skipped, key=lambda d: d["check_id"]),
        "by_pillar": _rollup("pillar"),
        "by_dimension": _rollup("dimension"),
        "by_subpoint": dict(sorted(subpoint.items())),
    }


def _write(path: Path, payload: Any) -> Path:
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, default=str), encoding="utf-8"
    )
    return path


def write_altitude_artifacts(
    artifact_dir: Path,
    *,
    findings: list[dict[str, Any]],
    page_rows: list[dict[str, Any]],
    dimensions: frozenset[str] | None,
    permitted_cost_classes: frozenset[str],
) -> dict[str, Path]:
    """Write pages.json + coverage.json and re-write findings.json enriched.

    Returns the paths written. Callers treat a failure here as non-fatal: these
    artifacts are additive, and a report that already rendered must not be lost
    because a supplementary file could not be written.
    """
    artifact_dir.mkdir(parents=True, exist_ok=True)
    enriched, stats = enrich_findings(findings)
    coverage = build_coverage(
        enriched,
        dimensions=dimensions,
        permitted_cost_classes=permitted_cost_classes,
    )
    coverage["enrichment"] = stats
    return {
        "findings_json": _write(artifact_dir / "findings.json", enriched),
        "pages_json": _write(artifact_dir / "pages.json", build_pages(page_rows)),
        "coverage_json": _write(artifact_dir / "coverage.json", coverage),
    }
