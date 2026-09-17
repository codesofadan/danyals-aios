"""The 39 backlink checks, and the three branches every one of them owes.

WHY THIS IS ONE FILE AND NOT THIRTY-NINE. All 39 read the SAME object - one
`BacklinkProfile` fetched once per run - so the interesting cases are properties
of that object, not of individual checks: no profile at all, an empty profile, a
healthy one, a toxic one. Testing them check-by-check would repeat the same four
fixtures 39 times and still miss the invariants that matter, which are the ones
that hold ACROSS the set.

THE INVARIANT THAT MATTERS MOST. A site with no backlinks is a valid and common
answer, not an error. Exactly two checks are allowed to report it as a problem
(OFF-002 authority, OFF-004 profile); every other check must return `n_a`.
Thirty-nine failures for one fact reads to a client as thirty-nine problems, and
scoring them as zeros would drag a whole pillar down over a site that simply has
no links yet. `aggregator` drops `n_a` from the weighted mean, so `n_a` leaves
the score alone where a `fail` at 0.0 would not.

These checks were written and then left unreachable: nothing imported the three
modules, so no check registered and the `backlinks` scope dispatched an empty
list. The string-literal heuristic in `test_ledger` counted them as implemented
anyway, which is how 39 checks were reported as built while none could run.
"""

from __future__ import annotations

import pytest

import audit_engine.cli.main  # noqa: F401  - registers every check module
from audit_engine.analyzers import registry
from audit_engine.analyzers.dispatch import run_scope
from audit_engine.integrations.dataforseo import BacklinkProfile

#: The two allowed to call an empty profile a problem. Every other check must
#: say "not applicable" rather than invent a failure out of the same one fact.
_MAY_FAIL_ON_EMPTY = {"OFF-002", "OFF-004"}


def _ids() -> list[str]:
    return sorted(c for c, r in registry.registered().items() if r.scope == "backlinks")


def _empty() -> BacklinkProfile:
    return BacklinkProfile(target="example.com")


def _unavailable() -> BacklinkProfile:
    return BacklinkProfile(target="example.com", error="402 payment required")


def _healthy() -> BacklinkProfile:
    return BacklinkProfile(
        target="example.com",
        rank=420, backlinks=8_400, referring_domains=610,
        referring_main_domains=580, referring_domains_nofollow=90,
        referring_pages=7_900, referring_pages_nofollow=1_100,
        referring_ips=540, referring_subnets=480,
        broken_backlinks=12, broken_pages=3,
        backlinks_spam_score=8, target_spam_score=4,
        first_seen="2019-04-02 10:00:00 +00:00",
        crawled_pages=210, external_links_count=180, internal_links_count=1_400,
        tld={"com": 300, "org": 120, "co.uk": 90, "net": 60, "io": 40},
        countries={"US": 280, "GB": 150, "DE": 90, "CA": 50, "AU": 40},
        platform_types={"blogs": 240, "news": 130, "cms": 120, "unknown": 120},
        link_types={"anchor": 7_100, "image": 900, "redirect": 400},
        link_attributes={"nofollow": 1_100, "sponsored": 40, "ugc": 60},
        semantic_locations={"article": 3_000, "footer": 400, "sidebar": 300},
        anchors={"example": 180, "example.com": 90, "click here": 60,
                 "https://example.com": 45, "best widgets guide": 30,
                 "widgets": 25, "read more": 20},
        info={"server": "nginx", "cms": "WordPress", "country": "US"},
    )


def _toxic() -> BacklinkProfile:
    p = _healthy()
    return BacklinkProfile(
        **{**p.__dict__,
           "rank": 40,
           "backlinks_spam_score": 78, "target_spam_score": 71,
           "referring_ips": 12, "referring_subnets": 4,
           "broken_backlinks": 900,
           "referring_domains_nofollow": 560,
           "anchors": {"cheap widgets buy now": 520, "example": 10},
           "tld": {"xyz": 500, "com": 20},
           "countries": {"RU": 480, "US": 20},
           "link_attributes": {"nofollow": 8_000, "sponsored": 0, "ugc": 0}}
    )


# --------------------------------------------------------------- reachability

def test_the_backlinks_scope_is_not_empty():
    # The defect this file exists for: the scope, the dispatcher and the emitter
    # were all built, and nothing imported the modules that fill it.
    assert len(_ids()) == 39


def test_every_backlink_check_declares_its_real_analyzer_path():
    from audit_engine.checklist import load_registry
    specs = load_registry()
    wrong = {
        c: (specs[c].analyzer, r.dotted_path)
        for c, r in registry.registered().items()
        if r.scope == "backlinks" and specs[c].analyzer != r.dotted_path
    }
    assert not wrong, wrong


# ------------------------------------------------------- the four whole-profile
# cases, run through the real dispatcher rather than by calling functions direct

@pytest.mark.parametrize("profile", [_empty(), _unavailable(), _healthy(), _toxic()],
                         ids=["empty", "unavailable", "healthy", "toxic"])
def test_every_check_returns_a_verdict_and_none_raise(profile):
    result = run_scope("backlinks", profile)
    got = dict(result.verdicts)
    assert set(got) == set(_ids())
    for cid, v in got.items():
        # The dispatcher converts an exception into an n_a with an
        # `analyzer_error` key, so a crash shows up here rather than silently
        # taking out every check after it.
        assert "analyzer_error" not in v.evidence, f"{cid}: {v.evidence['analyzer_error']}"
        assert 0.0 <= v.score <= 10.0, f"{cid} scored {v.score}"
        assert 0.0 <= v.confidence <= 1.0


def test_an_empty_profile_is_not_thirty_nine_problems():
    got = dict(run_scope("backlinks", _empty()).verdicts)
    wrong = sorted(
        c for c, v in got.items()
        if v.status != "n_a" and c not in _MAY_FAIL_ON_EMPTY
    )
    assert not wrong, f"these treated 'no backlinks yet' as their own failure: {wrong}"


def test_an_empty_profile_still_says_the_one_thing_worth_saying():
    got = dict(run_scope("backlinks", _empty()).verdicts)
    for cid in _MAY_FAIL_ON_EMPTY:
        assert got[cid].status in ("fail", "warn"), cid
        assert got[cid].remediation, f"{cid} reports a problem with no fix"


def test_an_unavailable_profile_is_never_reported_as_a_bad_one():
    # A 402 from the provider says nothing about the site. Scoring it as a
    # failure would invoice the client for our own billing problem.
    got = dict(run_scope("backlinks", _unavailable()).verdicts)
    bad = sorted(c for c, v in got.items() if v.status not in ("n_a", "info"))
    assert not bad, bad
    assert all(v.score == 0.0 or v.status == "n_a" for v in got.values())


def test_a_healthy_profile_mostly_passes():
    got = dict(run_scope("backlinks", _healthy()).verdicts)
    failed = sorted(c for c, v in got.items() if v.status == "fail")
    # Some legitimately cannot be answered from a summary (no per-link history),
    # but a healthy site must not FAIL most of its backlink checks.
    assert len(failed) <= 6, f"healthy profile failed {len(failed)}: {failed}"


def test_a_toxic_profile_is_caught():
    healthy = dict(run_scope("backlinks", _healthy()).verdicts)
    toxic = dict(run_scope("backlinks", _toxic()).verdicts)
    worse = [c for c in _ids() if toxic[c].score < healthy[c].score]
    assert len(worse) >= 6, (
        f"only {len(worse)} checks scored a spam-78, 4-subnet, exact-match-anchor "
        "profile lower than a clean one"
    )


# ------------------------------------------------------------------ the client

def test_no_check_reports_a_problem_without_telling_the_client_what_to_do():
    for profile in (_healthy(), _toxic()):
        for cid, v in run_scope("backlinks", profile).verdicts:
            if v.status in ("fail", "warn"):
                assert v.remediation, f"{cid} reports a problem with no remediation"


def test_evidence_never_leaks_a_raw_provider_payload():
    # Evidence reaches findings.json and the client PDF. A nested dict is the
    # shape a raw API response arrives in.
    for cid, v in run_scope("backlinks", _toxic()).verdicts:
        for k, val in v.evidence.items():
            assert not isinstance(val, dict), f"{cid}.{k} carries a nested dict"
