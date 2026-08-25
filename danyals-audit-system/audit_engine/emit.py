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
from functools import cache
from pathlib import Path
from typing import Any

from audit_engine import checklist as cl

# A check that emitted no row at all did not run. A check that emitted `pass`
# DID run and found nothing wrong. Keeping those apart is the entire point.
SKIP_NOT_SELECTED = "not_in_selected_dimensions"
SKIP_SOURCE_NOT_PERMITTED = "source_not_permitted"
SKIP_NO_OUTPUT = "no_finding_emitted"
#: The check is dispatched to an AI agent, and no agent output reached this run
#: - no key, agents disabled, or the agent returned nothing for it.
SKIP_AI_NOT_RUN = "ai_assisted_not_run"
#: The check IS implemented and its inputs were permitted, but this command did
#: not dispatch it. A third state that no reason enum could previously express,
#: and the honest answer for a check the `quick` pipeline does not reach.
SKIP_NOT_DISPATCHED = "not_dispatched_by_this_command"
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


@cache
def analyzer_path_resolves(dotted_path: str, check_id: str = "") -> bool:
    """Is there real code behind this check?

    Answers the REGISTRY first when a ``check_id`` is given. A check bound with
    ``@check`` records the true dotted path of its function, so for those the
    answer is a fact rather than an inference about a metadata field.

    Falls back to importing the checklist's ``analyzer:`` declaration. That
    field is stale for most legacy checks - on a real run 160 checks ran while
    only 31 declared paths resolved - so a False from this fallback means "the
    declaration does not import", NOT "the check is unimplemented". The two
    were being conflated, which told a client their site was checked when it
    may not have been.
    """
    if check_id:
        try:
            from audit_engine.analyzers import registry as _registry

            if check_id in _registry.registered():
                return True
        except Exception:
            pass
    if not dotted_path:
        return False
    module_path, _, attr = dotted_path.rpartition(".")
    if not module_path:
        return False
    try:
        module = importlib.import_module(module_path)
    except Exception:
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


def _counts_by_reason(skipped: list[dict[str, str]]) -> dict[str, int]:
    """How many checks each reason accounts for.

    The old shape exposed two hand-picked totals, one of which
    (`analyzer_path_unresolved`) was the untrustworthy diagnostic. A count per
    reason lets a report name the real blocker and its size.
    """
    out: dict[str, int] = {}
    for row in skipped:
        key = str(row.get("reason") or "unknown")
        out[key] = out.get(key, 0) + 1
    return dict(sorted(out.items()))


def _why_no_output(check_id: str, spec: cl.CheckSpec) -> dict[str, str]:
    """The honest reason a permitted check emitted nothing.

    Order matters. The ledger is consulted FIRST because "we have not built
    this" outranks any observation about the run.
    """
    from audit_engine.analyzers import ledger as _ledger

    entry = _ledger.reason_for(check_id)
    if entry is not None:
        return {
            "check_id": check_id,
            "reason": entry.reason.value,
            "blocked_on": entry.blocked_on,
            "note": entry.note,
        }
    if spec.automation != "full":
        return {
            "check_id": check_id,
            "reason": SKIP_AI_NOT_RUN,
            "blocked_on": "AI agent dispatch",
            "note": "This check is answered by an AI specialist rather than a "
                    "deterministic analyzer, and no agent output reached this run.",
        }
    # Every `full` check is either registered or ledgered - a test enforces it -
    # so reaching here means it IS built and this command simply did not run it.
    return {
        "check_id": check_id,
        "reason": SKIP_NOT_DISPATCHED,
        "blocked_on": "this audit command",
        "note": "The check is implemented and its data sources were permitted, "
                "but this pipeline does not dispatch it.",
    }


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
            skipped.append({
                "check_id": cid, "reason": SKIP_NOT_SELECTED,
                "blocked_on": "dimension selection",
                "note": "This audit was scoped to a subset of dimensions and "
                        "this check is outside it.",
            })
            continue
        if not spec.runs_under(permitted_cost_classes):
            skipped.append({
                "check_id": cid, "reason": SKIP_SOURCE_NOT_PERMITTED,
                "blocked_on": "run tier",
                "note": "This check needs data this run was not permitted to "
                        f"buy: {', '.join(sorted(spec.cost_classes))}.",
            })
            continue
        planned.append(cid)

    ran = sorted(c for c in planned if c in emitted)
    # Why a PLANNED check produced nothing.
    #
    # This used to ask whether the checklist's `analyzer:` field imports, and
    # reported `analyzer_path_unresolved` when it did not - a reason this
    # module's own docstring describes as untrustworthy, and which was 100% of
    # skips on a fully-permitted paid run. The field is stale metadata for most
    # checks, so it answered a question nobody asked.
    #
    # The ledger knows the real answer for every unimplemented check: a typed
    # reason, what it is blocked on, and a note written for a person. Two states
    # the ledger cannot express are derived here instead.
    for c in planned:
        if c in emitted:
            continue
        skipped.append(_why_no_output(c, registry[c]))

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
        # A count per reason, so a report can say "22 checks need backlink data
        # you have not purchased" instead of one opaque `skipped` total.
        "counts": {
            "planned": len(planned),
            "ran": len(ran),
            "skipped": len(skipped),
            **_counts_by_reason(skipped),
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
