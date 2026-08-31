"""The check registry is a contract, not a convenience.

Every number asserted here was independently reproduced from the YAML on
2026-08-24 and matches the counts in ``docs/research/R4-audit-tiering.md``. They
are frozen because the tier system DERIVES its check set from them: if a check's
``data_sources`` change, the set a zero-spend tier may run changes with it, and
that must break a test rather than silently widen what "free" means.
"""

from __future__ import annotations

import collections

import pytest

from audit_engine import checklist as cl

ZERO = frozenset({"zero"})
ZERO_QUOTA = frozenset({"zero", "free_quota"})
ZERO_QUOTA_CONN = frozenset({"zero", "free_quota", "connection"})
ALL = frozenset({"zero", "free_quota", "connection", "billable"})


@pytest.fixture(scope="module")
def registry():
    cl.load_registry.cache_clear()
    return cl.load_registry()


def test_every_check_loads_and_the_total_is_frozen(registry):
    assert len(registry) == 363


def test_every_check_carries_every_field(registry):
    """The 38%-populated subcategory defect existed because nothing asserted this."""
    for spec in registry.values():
        assert spec.id and spec.name, spec
        assert spec.subcategory, f"{spec.id} has no subpoint"
        assert spec.owner_agent, f"{spec.id} has no owning agent"
        assert spec.severity_default in {"critical", "major", "minor", "info"}, spec
        assert spec.data_sources, f"{spec.id} declares no data source"
        assert spec.automation in {"full", "ai-assisted"}, spec


def test_pillar_counts_match_the_files(registry):
    counts = collections.Counter(s.pillar for s in registry.values())
    assert dict(counts) == {
        "on-page": 142, "technical": 101, "off-page": 80, "local-seo": 40,
    }


def test_dimension_carve_out_sums_to_the_whole(registry):
    """GEO (A5) and Strategy (M2) are carved out of their home files by owning
    agent. The carve-out must PARTITION the set - an earlier draft of R4
    double-counted the M2 checks and summed to 384."""
    counts = collections.Counter(s.dimension for s in registry.values())
    assert dict(counts) == {
        "onpage": 122, "technical": 100, "offpage": 71,
        "local": 36, "geo": 13, "strategy": 21,
    }
    assert sum(counts.values()) == 363


def test_every_data_source_is_deliberately_classified(registry):
    """An unclassified source falls to ``billable``. That is the safe default, but
    it must never happen silently - every source in the checklists is named in
    one of the four sets."""
    known = cl._ZERO | cl._FREE_QUOTA | cl._CONNECTION | cl._BILLABLE
    seen = {s for spec in registry.values() for s in spec.data_sources}
    assert len(seen) == 52
    assert seen <= known, f"unclassified data sources: {sorted(seen - known)}"


def test_an_unknown_source_is_billable_not_free():
    """Fail closed. This is the exact defect that let google_nl spend on a free
    run: absence from a list read as permission."""
    assert cl.cost_class("some_new_paid_api_nobody_classified") == "billable"


def test_containment_counts_are_frozen(registry):
    def n(permitted, deterministic_only=False):
        return sum(
            1 for s in registry.values()
            if s.cost_classes <= permitted and (s.is_deterministic or not deterministic_only)
        )
    # Rendering moved zero -> free_quota when it was implemented against
    # Firecrawl rather than a local browser: a metered monthly allowance is not
    # "no quota is consumed". Nine checks left the truly-free tier as a result.
    # ZERO_QUOTA is unchanged because free_quota still admits them.
    # O-9 RESOLVED. Fourteen page-scope checks declared a provider their
    # implementation cannot reach - `check_title_tag(p: ParsedHTML)` was declared
    # against `serper_top10` and never called it - so the cost gate excluded
    # checks that spend nothing. They ran anyway while the legacy generators
    # bypassed the gate; the moment the registry started honouring it, all
    # fourteen vanished from a free run. The declarations were corrected to what
    # the code reads. Every one is still a `crawled_html` check, so the free tier
    # gained 14 checks it had always in fact been running.
    assert n(ZERO) == 202
    assert n(ZERO_QUOTA) == 233
    assert n(ZERO_QUOTA_CONN) == 240
    assert n(ALL) == 363
    # Wave A moved 17 checks from ai-assisted to full: Python already computed
    # every one of them, so the model call was paying for a second opinion that
    # then collided with the first. Nine of the 17 declare only zero-cost
    # sources, so they now count as free-tier runnable - which they always were
    # in practice. The other eight declared sources their deterministic
    # implementation never reads - that was O-9, and it is now resolved: the
    # declarations were corrected to what the code actually reads, so those
    # checks count as free-tier runnable too.
    assert n(ZERO, True) == 186
    assert n(ZERO_QUOTA, True) == 216
    assert n(ZERO_QUOTA_CONN, True) == 220


def test_automation_split_is_frozen(registry):
    counts = collections.Counter(s.automation for s in registry.values())
    # 276/87 before Wave A. The 17 demoted checks were emitted by Python AND
    # sent to an agent, so each could be scored twice in one run.
    assert dict(counts) == {"full": 293, "ai-assisted": 70}


def test_an_ai_assisted_check_never_runs_on_a_zero_spend_tier(registry):
    """A model call is billable no matter how cheap its INPUT data is. Without
    this rule, containment alone would admit 26 ai-assisted checks into the free
    tier because their data sources happen to be zero-cost."""
    for spec in registry.values():
        if not spec.is_deterministic:
            assert not spec.runs_under(ZERO_QUOTA), spec.id


def test_empty_dimension_selection_means_everything(registry):
    assert len(cl.checks_for_dimensions(None)) == 363
    assert len(cl.checks_for_dimensions(frozenset())) == 363


def test_dimension_selection_is_exact(registry):
    assert len(cl.checks_for_dimensions(frozenset({"geo"}))) == 13
    assert len(cl.checks_for_dimensions(frozenset({"local"}))) == 36
    both = cl.checks_for_dimensions(frozenset({"geo", "local"}))
    assert len(both) == 49


def test_subpoint_vocabulary_is_complete_and_nonempty(registry):
    subs = cl.subpoints()
    assert set(subs) == {"on-page", "technical", "off-page", "local-seo"}
    assert {k: len(v) for k, v in subs.items()} == {
        "on-page": 39, "technical": 30, "off-page": 17, "local-seo": 8,
    }
    for pillar, names in subs.items():
        assert all(n for n in names), pillar


def test_lookup_is_trimmed_and_total(registry):
    assert cl.get("  LOC-001 ") is not None
    assert cl.get("LOC-001").dimension == "local"
    assert cl.get("NOPE-999") is None
    for cid in registry:
        assert cl.get(cid) is not None


# ----------------------------------------------- subpoint display names

def test_every_subpoint_has_a_client_readable_name(registry):
    """The keys are internal and several are research shorthand - `semantic-3.8-koray`
    is a researcher's surname, `semantic-3.9-info-quality` is a section number -
    and they were being printed straight onto a client-facing scorecard."""
    for spec in registry.values():
        label = cl.subpoint_label(spec.pillar, spec.subcategory)
        assert label, f"{spec.pillar}/{spec.subcategory} has no name"
        assert label != spec.subcategory or "-" not in spec.subcategory, (
            f"{spec.pillar}/{spec.subcategory} still renders its raw key"
        )
        # no internal shorthand may survive into a label
        assert "semantic-" not in label.lower()
        assert not any(ch.isdigit() for ch in label) or label in {"AMP"}


def test_the_label_map_covers_the_whole_vocabulary(registry):
    unmapped = {
        (s.pillar, s.subcategory)
        for s in registry.values()
        if s.subcategory not in cl.SUBPOINT_LABEL.get(s.pillar, {})
    }
    assert unmapped == set(), f"unmapped subpoints: {sorted(unmapped)}"
    assert sum(len(v) for v in cl.SUBPOINT_LABEL.values()) == 94


def test_the_same_key_can_mean_different_things_in_different_pillars():
    """`crawlability` on-page is one page's own directives; `crawl` in technical is
    site-wide access. Keying the map on subcategory alone would conflate them."""
    assert cl.subpoint_label("on-page", "crawlability") != cl.subpoint_label("technical", "crawl")
    assert cl.subpoint_label("on-page", "schema") == cl.subpoint_label("technical", "schema")
    assert cl.subpoint_label("local-seo", "schema") == "Local schema"


def test_an_unmapped_subpoint_degrades_to_a_readable_fallback():
    """A new key should read awkwardly, never disappear from a scorecard."""
    assert cl.subpoint_label("on-page", "some-new-thing") == "Some new thing"
    assert cl.subpoint_label("nope", "") == ""
