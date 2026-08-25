"""A page with nothing on it must return n_a, never fail at 0.0.

This is the single most common way an audit lies. A brochure page with no
images is not "failing image optimisation"; there is nothing to optimise. A
check that scores it 0.0 drags the client's score down for content they do not
have, and - because the flat model is
``score = 100 x (1 - severity_mass(failed) / severity_mass(ran))`` - a wrong
fail is strictly worse than an honest n_a.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from audit_engine.analyzers.ai_search import iter_per_page_ai_search
from audit_engine.analyzers.extras import iter_per_page_extras
from audit_engine.analyzers.onpage import iter_per_page_checks
from audit_engine.analyzers.semantic_seo import iter_per_page_semantic_seo
from audit_engine.parsers import html as html_parser

FIXTURES = Path(__file__).parent / "fixtures"
ITERATORS = (
    iter_per_page_checks,
    iter_per_page_ai_search,
    iter_per_page_extras,
    iter_per_page_semantic_seo,
)


@pytest.fixture(scope="module")
def empty():
    return html_parser.parse((FIXTURES / "empty.html").read_text(), "https://example.com/")


def _verdicts(page):
    out = {}
    for it in ITERATORS:
        for cid, *rest in it(page):
            out[cid] = rest[-1]
    return out


def test_the_empty_fixture_really_is_empty(empty):
    """Guard the guard: if the fixture grows content the tests go vacuous."""
    assert not empty.images
    assert not empty.schema_blocks
    assert not empty.links
    assert not list(empty.headings)
    assert empty.word_count < 10


def test_no_check_crashes_on_a_page_with_nothing_on_it(empty):
    """Before the dispatcher, one raise here killed every later check."""
    assert _verdicts(empty)


def test_image_checks_are_not_applicable_rather_than_failing(empty):
    v = _verdicts(empty)
    for cid in ("ON-067", "ON-069", "ON-070", "ON-071"):
        if cid in v:
            assert v[cid].status == "n_a", (
                f"{cid} scored {v[cid].status} on a page with no images. "
                f"There is nothing to fix, so this is a fabricated failure."
            )


def test_link_checks_are_not_applicable_on_a_page_with_no_links(empty):
    v = _verdicts(empty)
    for cid in ("ON-058", "ON-065", "ON-066"):
        if cid in v:
            assert v[cid].status == "n_a", f"{cid} scored {v[cid].status} with no links"


def test_every_verdict_is_well_formed(empty):
    for cid, verdict in _verdicts(empty).items():
        assert verdict.status in {"pass", "warn", "fail", "n_a"}, cid
        assert 0.0 <= verdict.score <= 10.0, cid
        assert 0.0 <= verdict.confidence <= 1.0, cid
        assert isinstance(verdict.evidence, dict), cid


def test_an_n_a_verdict_never_carries_a_remediation(empty):
    """"Not applicable" plus "here is how to fix it" is a contradiction the
    client reads as a defect."""
    offenders = [
        cid for cid, v in _verdicts(empty).items()
        if v.status == "n_a" and v.remediation
    ]
    assert not offenders, offenders


# --------------------------------------------------------------------------
# Static guard: the same contradiction, anywhere in the analyzers.
# --------------------------------------------------------------------------

def test_no_analyzer_anywhere_returns_n_a_with_a_remediation():
    """Found three checks telling a CLIENT to "Configure MOZ_ACCESS_ID +
    MOZ_SECRET_KEY in .env". Operator notes belong in evidence."""
    import ast

    root = Path(__file__).resolve().parents[1] / "audit_engine" / "analyzers"
    offenders = []
    for f in sorted(root.rglob("*.py")):
        for n in ast.walk(ast.parse(f.read_text(), filename=str(f))):
            if not (isinstance(n, ast.Call) and getattr(n.func, "id", None) == "Verdict"):
                continue
            args = n.args
            if not (args and isinstance(args[0], ast.Constant) and args[0].value == "n_a"):
                continue
            positional = len(args) > 5 and not (
                isinstance(args[5], ast.Constant) and args[5].value is None
            )
            keyword = any(
                k.arg == "remediation"
                and not (isinstance(k.value, ast.Constant) and k.value.value is None)
                for k in n.keywords
            )
            if positional or keyword:
                offenders.append(f"{f.name}:{n.lineno}")
    assert not offenders, (
        f"n_a means 'not measured'; a remediation renders it as an action item: {offenders}"
    )


def test_no_remediation_anywhere_tells_a_client_to_edit_configuration():
    """A dental practice cannot 'configure SERPER_API_KEY'."""
    import re

    root = Path(__file__).resolve().parents[1] / "audit_engine" / "analyzers"
    pattern = re.compile(r"(?i)(configure|set)\s+[A-Z_]{4,}(_KEY|_ID|_TOKEN|_SECRET)")
    offenders = []
    for f in sorted(root.rglob("*.py")):
        for i, line in enumerate(f.read_text().splitlines(), 1):
            if "operator_note" in line or line.lstrip().startswith("#"):
                continue
            if pattern.search(line):
                offenders.append(f"{f.name}:{i}")
    assert not offenders, f"client-facing text naming an env var: {offenders}"
