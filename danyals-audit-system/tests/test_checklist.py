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
    assert len(seen) == 53
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
    assert n(ZERO) == 197
    assert n(ZERO_QUOTA) == 219
    assert n(ZERO_QUOTA_CONN) == 228
    assert n(ALL) == 363
    assert n(ZERO, True) == 171
    assert n(ZERO_QUOTA, True) == 193
    assert n(ZERO_QUOTA_CONN, True) == 197


def test_automation_split_is_frozen(registry):
    counts = collections.Counter(s.automation for s in registry.values())
    assert dict(counts) == {"full": 276, "ai-assisted": 87}


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
