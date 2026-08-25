"""A check bound with @check must actually reach findings.json.

Waves 2 onward register their checks through the registry rather than adding a
literal to an iter_* generator. If the dispatcher is not wired into the run,
those checks would register cleanly, pass their unit tests, and silently never
fire in a real audit - which is the failure this test exists to prevent.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from audit_engine.analyzers import registry as reg_mod
from audit_engine.analyzers.common import Verdict
from audit_engine.checklist import load_registry
from audit_engine.cli.main import _emit_registered


@pytest.fixture(autouse=True)
def _clean():
    reg_mod.clear_registry_for_tests()
    yield
    reg_mod.clear_registry_for_tests()


@dataclass
class FakeParsed:
    url: str = "https://example.com/"
    links: list = field(default_factory=list)


@dataclass
class FakePage:
    url: str = "https://example.com/"
    final_url: str = "https://example.com/"
    parsed: FakeParsed | None = None


@dataclass
class FakeCrawl:
    site_url: str = "https://example.com/"
    pages: list = field(default_factory=list)
    sitemaps: list = field(default_factory=list)
    discovered_urls: list = field(default_factory=list)


def _crawl():
    return FakeCrawl(pages=[FakePage(parsed=FakeParsed())])


def _full_ids(n):
    return [c for c, s in load_registry().items() if s.automation == "full"][:n]


def test_nothing_registered_emits_nothing():
    out = _emit_registered(run_id=1, page_id_by_url={}, crawl_result=_crawl(), parsed_pages=[])
    assert out == []


def test_a_registered_page_check_reaches_findings():
    cid = _full_ids(1)[0]

    @reg_mod.check(cid, scope="page")
    def analyzer(p):
        return Verdict("fail", 2.0, "major", 0.9, {"seen": p.url}, "Fix it.")

    out = _emit_registered(
        run_id=7,
        page_id_by_url={"https://example.com/": 42},
        crawl_result=_crawl(),
        parsed_pages=[FakeParsed()],
    )
    assert len(out) == 1
    f = out[0]
    assert f.check_id == cid
    assert f.page_id == 42
    assert f.status == "fail"
    assert f.remediation == "Fix it."
    # taxonomy comes from the checklist, never from the analyzer
    spec = load_registry()[cid]
    assert f.check_name == spec.name
    assert f.category == spec.pillar
    assert f.subcategory == spec.subcategory
    assert f.owner_agent == spec.owner_agent


def test_a_site_crawled_check_receives_the_graph_and_has_no_page_id():
    cid = _full_ids(1)[0]
    seen = {}

    @reg_mod.check(cid, scope="site_crawled")
    def analyzer(ctx):
        seen["home"] = ctx.home
        seen["crawled"] = len(ctx.crawled_urls)
        return Verdict("pass", 10.0, "info", 1.0, {})

    out = _emit_registered(run_id=1, page_id_by_url={}, crawl_result=_crawl(), parsed_pages=[])
    assert seen == {"home": "https://example.com/", "crawled": 1}
    assert out[0].page_id is None


def test_a_failing_registered_check_does_not_break_the_run():
    a, b = _full_ids(2)

    @reg_mod.check(a, scope="page")
    def boom(p):
        raise ValueError("bug")

    @reg_mod.check(b, scope="page")
    def fine(p):
        return Verdict("pass", 10.0, "info", 1.0, {})

    out = _emit_registered(
        run_id=1, page_id_by_url={}, crawl_result=_crawl(), parsed_pages=[FakeParsed()]
    )
    assert {f.check_id for f in out} == {a, b}
    errored = next(f for f in out if f.check_id == a)
    assert errored.status == "n_a" and errored.confidence == 0.0


def test_a_rollup_sees_which_registered_checks_ran():
    target, inp = _full_ids(2)

    @reg_mod.check(inp, scope="page")
    def leaf(p):
        return Verdict("pass", 10.0, "info", 1.0, {})

    @reg_mod.rollup(target, inputs=(inp,), min_inputs_ran=1)
    def roll(ctx):
        return Verdict("pass", 9.0, "info", 1.0, {})

    out = _emit_registered(
        run_id=1, page_id_by_url={}, crawl_result=_crawl(), parsed_pages=[FakeParsed()]
    )
    rolled = next(f for f in out if f.check_id == target)
    assert rolled.status == "pass"
    import json
    ev = json.loads(rolled.evidence_json)
    assert ev["inputs_ran"] == [inp]


def test_a_rollup_whose_inputs_did_not_run_is_gated_not_scored():
    target, inp = _full_ids(2)

    @reg_mod.rollup(target, inputs=(inp,), min_inputs_ran=1)
    def roll(ctx):
        return Verdict("fail", 0.0, "critical", 1.0, {})

    out = _emit_registered(
        run_id=1, page_id_by_url={}, crawl_result=_crawl(), parsed_pages=[FakeParsed()]
    )
    # nothing else registered, so `ran` is empty and the rollup never fires
    assert out == []


def test_permitted_check_ids_restricts_what_runs():
    a, b = _full_ids(2)
    for cid in (a, b):
        @reg_mod.check(cid, scope="page")
        def analyzer(p, _c=cid):
            return Verdict("pass", 10.0, "info", 1.0, {})

    out = _emit_registered(
        run_id=1, page_id_by_url={}, crawl_result=_crawl(),
        parsed_pages=[FakeParsed()], permitted_check_ids={a},
    )
    assert {f.check_id for f in out} == {a}
