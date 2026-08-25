"""Wave 0 regression guard: an emitted check_id must mean what the checklist says.

Core Web Vitals shipped for months under TECH-070..074 - ids the checklist
defines as crawl-log, Googlebot-activity, server-response, HTML-validation and
semantic-HTML checks. Clients were told their server response was healthy on the
strength of an INP measurement. Nothing failed, because nothing asserted the
binding. These tests assert it.
"""
from __future__ import annotations

import ast
import pathlib
import re
from types import SimpleNamespace

import pytest

from audit_engine.analyzers.extras import iter_cwv_findings, iter_psi_quality_findings
from audit_engine.checklist import load_registry

REGISTRY = load_registry()
ENGINE_ROOT = pathlib.Path(__file__).resolve().parents[1] / "audit_engine"
CHECK_ID_RE = re.compile(r"^(?:TECH|ON|OFF|LOCAL|CONT|M)-\d{3}$")


def _psi(field=None, lab=None, lighthouse=None):
    return SimpleNamespace(
        field_metrics=[SimpleNamespace(name=k, percentile=v) for k, v in (field or {}).items()],
        lab_metrics=[SimpleNamespace(name=k, value=v) for k, v in (lab or {}).items()],
        lighthouse_scores=lighthouse or {},
    )


# --------------------------------------------------------------------------
# The specific binding that was wrong.
# --------------------------------------------------------------------------

# metric id as PSI reports it -> the checklist row it must be filed under
CWV_BINDING = {
    "largest_contentful_paint": "TECH-040",
    "cumulative_layout_shift": "TECH-041",
    "interaction_to_next_paint": "TECH-042",
    "experimental_time_to_first_byte": "TECH-043",
}


@pytest.mark.parametrize("metric,check_id", sorted(CWV_BINDING.items()))
def test_each_cwv_metric_is_filed_under_its_own_checklist_row(metric, check_id):
    findings = {cid: v for cid, _owner, v in iter_cwv_findings(_psi(field={metric: 1.0}))}
    assert check_id in findings, f"{metric} produced no {check_id} finding"
    assert findings[check_id].evidence["metric"] == metric, (
        f"{check_id} ({REGISTRY[check_id].name}) is carrying "
        f"{findings[check_id].evidence['metric']}, not {metric}"
    )


def test_cwv_findings_land_in_the_cwv_subcategory():
    for cid, _owner, _v in iter_cwv_findings(_psi(field=dict.fromkeys(CWV_BINDING, 1.0))):
        assert REGISTRY[cid].subcategory == "cwv", f"{cid} is {REGISTRY[cid].subcategory}"


def test_the_ids_cwv_used_to_squat_no_longer_carry_measurements():
    """TECH-070..074 are crawl-log/Googlebot/server-response/HTML/semantic-HTML."""
    emitted = {cid for cid, _o, _v in iter_cwv_findings(_psi(field=dict.fromkeys(CWV_BINDING, 1.0)))}
    assert emitted.isdisjoint({f"TECH-{n}" for n in range(70, 75)})


def test_first_contentful_paint_is_not_emitted_under_a_borrowed_id():
    """O-4: the checklist has no FCP row. Silence beats a wrong label."""
    emitted = [
        v.evidence.get("metric")
        for _c, _o, v in iter_cwv_findings(_psi(field={"first_contentful_paint": 1200.0}))
    ]
    assert "first_contentful_paint" not in emitted


# --------------------------------------------------------------------------
# Lighthouse categories.
# --------------------------------------------------------------------------

def test_only_the_lighthouse_category_with_a_real_home_is_emitted():
    scores = {"accessibility": 80, "best-practices": 70, "seo": 60}
    found = {cid: v for cid, _o, v in iter_psi_quality_findings(_psi(lighthouse=scores))}
    assert set(found) == {"TECH-092"}, "best-practices/seo have no checklist row (O-3)"
    assert found["TECH-092"].evidence["category"] == "accessibility"
    assert REGISTRY["TECH-092"].subcategory == "accessibility"


def test_lighthouse_no_longer_squats_malware_detection_or_ai_crawl_readiness():
    emitted = {cid for cid, _o, _v in iter_psi_quality_findings(
        _psi(lighthouse={"accessibility": 80, "best-practices": 70, "seo": 60}))}
    assert "TECH-082" not in emitted, "TECH-082 is 'Malware detection'"
    assert "ON-106" not in emitted, "ON-106 is 'AI crawl readiness analysis'"


# --------------------------------------------------------------------------
# The generic drift catcher: no literal may name a check that does not exist.
# --------------------------------------------------------------------------

def _literal_check_ids() -> dict[str, set[str]]:
    """Every check-id-shaped string constant in engine source, by file."""
    out: dict[str, set[str]] = {}
    for path in sorted(ENGINE_ROOT.rglob("*.py")):
        tree = ast.parse(path.read_text(), filename=str(path))
        ids = {
            n.value
            for n in ast.walk(tree)
            if isinstance(n, ast.Constant)
            and isinstance(n.value, str)
            and CHECK_ID_RE.match(n.value)
        }
        if ids:
            out[str(path.relative_to(ENGINE_ROOT))] = ids
    return out


def test_every_check_id_literal_in_engine_source_exists_in_the_checklist():
    unknown = {
        f: sorted(ids - REGISTRY.keys())
        for f, ids in _literal_check_ids().items()
        if ids - REGISTRY.keys()
    }
    assert not unknown, f"check ids that no checklist row defines: {unknown}"


def test_no_override_table_can_rename_a_checklist_row():
    """_CHECK_META_OVERRIDES existed to make squatted ids read correctly.

    Six of its seven rows renamed real checklist rows, which is how the CWV
    squat was made to look right in client-facing output. It is retired; check
    names now come from the checklist and nowhere else.
    """
    import audit_engine.cli.main as main

    assert not hasattr(main, "_CHECK_META_OVERRIDES")
    for cid in ("TECH-040", "TECH-043", "ON-095", "ON-106", "TECH-097", "ON-099"):
        assert main._check_name_for(cid) == REGISTRY[cid].name


# --------------------------------------------------------------------------
# Hand-built Findings bypass _meta_for() and hardcode their own name/pillar/
# subcategory. That is a second source of truth for what a check is called.
# --------------------------------------------------------------------------

def _hardcoded_finding_meta() -> list[tuple[int, str, str, str | None, str | None]]:
    """(line, check_id, check_name, category, subcategory) for literal Finding(...)."""
    main_py = ENGINE_ROOT / "cli" / "main.py"
    tree = ast.parse(main_py.read_text(), filename=str(main_py))
    out = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and getattr(node.func, "id", None) == "Finding"):
            continue
        kw = {
            k.arg: k.value.value
            for k in node.keywords
            if isinstance(k.value, ast.Constant) and isinstance(k.value.value, str)
        }
        if "check_id" in kw and "check_name" in kw:
            out.append((node.lineno, kw["check_id"], kw["check_name"],
                        kw.get("category"), kw.get("subcategory")))
    return out


def test_hardcoded_findings_exist_and_are_discoverable():
    """Guard the guard: if this drops to zero the assertions below go vacuous."""
    assert len(_hardcoded_finding_meta()) >= 6


@pytest.mark.parametrize(
    "line,check_id,name,category,subcategory",
    _hardcoded_finding_meta(),
    ids=lambda v: str(v) if isinstance(v, str) else None,
)
def test_hardcoded_finding_metadata_matches_the_checklist(line, check_id, name, category, subcategory):
    spec = REGISTRY.get(check_id)
    assert spec is not None, f"main.py:{line} emits {check_id}, which no checklist row defines"
    assert name == spec.name, f"main.py:{line} calls {check_id} {name!r}; checklist says {spec.name!r}"
    assert category == spec.pillar, f"main.py:{line} files {check_id} under {category}, not {spec.pillar}"
    assert subcategory == spec.subcategory, (
        f"main.py:{line} files {check_id} under {subcategory}, not {spec.subcategory}"
    )


def test_no_check_id_is_emitted_twice_by_the_same_per_page_iterator_set():
    """One page must not carry two scores for one check.

    ON-048 and ON-049 had competing implementations in onpage.py and
    ai_search.py, both firing per page. Whichever landed last in the list won
    in some readers and lost in others; the two disagreed on score.
    """
    from audit_engine.analyzers.ai_search import iter_per_page_ai_search
    from audit_engine.analyzers.onpage import iter_per_page_checks
    from audit_engine.parsers import html as html_parser

    for name in ("clean.html", "thin.html", "broken-schema.html"):
        fixture = pathlib.Path(__file__).parent / "fixtures" / name
        page = html_parser.parse(fixture.read_text(), "https://example.com/")
        emitted: list[str] = []
        for it in (iter_per_page_checks, iter_per_page_ai_search):
            emitted.extend(cid for cid, *_rest in it(page))
        dupes = sorted({c for c in emitted if emitted.count(c) > 1})
        assert not dupes, f"{name}: emitted twice for one page: {dupes}"
