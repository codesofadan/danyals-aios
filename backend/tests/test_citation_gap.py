"""Wave 4 unit gate: the PURE citation gap-analysis + NAP-derive logic, plus the
Web 2.0 / citation-engine API status boards. No DB, no network, no keys.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.config import Settings
from app.modules.citations.service import (
    build_audit_plan,
    compute_citation_gap,
    derive_business_profile_fields,
)
from integrations.citation_status import citation_engine_status
from integrations.web2_status import web2_platform_status, web2_status_board

pytestmark = pytest.mark.unit


def _dir(did: str, name: str, **over: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "id": did, "name": name, "url": f"https://{name.lower()}.example", "market": "US",
        "tier": "bot_fillable", "submit_method": "bot:playwright", "link_rel": "dofollow",
        "price_note": "", "automation_note": "", "active": True, "authority": 60,
        "authority_tier": "core", "access": "open", "is_marketplace": False, "verticals": [],
    }
    row.update(over)
    return row


# --------------------------------------------------------------------------- #
# derive_business_profile_fields: client NAP -> submission profile
# --------------------------------------------------------------------------- #
def test_derive_maps_nap_and_leads_categories_with_primary() -> None:
    client_nap = {
        "business_name": "Acme Dental", "address_line1": "123 Main St", "city": "Bellevue",
        "region": "WA", "postal_code": "98004", "market": "US", "phone": "555-0100",
        "website_url": "https://acme.example", "primary_category": "Dentist",
        "extra_categories": ["Cosmetic dentistry", "Dentist"], "hours": {"mon": "9-5"},
    }
    fields = derive_business_profile_fields(client_nap)
    assert fields["business_name"] == "Acme Dental"
    assert fields["market"] == "US"
    assert fields["is_primary"] is True
    assert fields["label"] == "Primary"
    # primary leads; the duplicate "Dentist" in extras is dropped.
    assert fields["categories"] == ["Dentist", "Cosmetic dentistry"]
    assert fields["hours"] == {"mon": "9-5"}


def test_derive_tolerates_empty_nap() -> None:
    fields = derive_business_profile_fields({})
    assert fields["business_name"] == ""
    assert fields["categories"] == []
    # CHANGED with 0113, and this line is the point of that migration. It asserted "US":
    # a client whose market was never recorded was ASSERTED to be American, and the
    # campaign then selected US-only directories for them. Measured with a Lahore client
    # on 2026-08-30 - the queue offered an operator YellowPages.com, Chamber of Commerce
    # and BBB for a business in Pakistan.
    #
    # A wrong listing is NAP pollution, which is the exact harm a citation campaign
    # exists to prevent and is often unremovable; a missing one is visible in the gap
    # report and recoverable. So an unknown market resolves to the directories that
    # legitimately serve anyone.
    assert fields["market"] == "GLOBAL"


# --------------------------------------------------------------------------- #
# compute_citation_gap: covered vs missing, live URLs, tallies
# --------------------------------------------------------------------------- #
def test_gap_missing_excludes_covered_by_id_and_name() -> None:
    directories = [_dir("d1", "Yelp"), _dir("d2", "Bing Places"), _dir("d3", "Hotfrog")]
    existing = [
        # covered by directory_id (in-flight submission)
        {"id": "c1", "directory": "Yelp", "directory_id": "d1", "submit_status": "submitted",
         "nap_status": "missing", "proof_url": "screenshots/ab12.png"},
        # covered by NAME only (legacy monitoring row, no directory_id), consistent NAP
        {"id": "c2", "directory": "Bing Places", "directory_id": None,
         "submit_status": "not_started", "nap_status": "consistent", "proof_url": ""},
    ]
    gap = compute_citation_gap(directories=directories, existing_citations=existing)
    missing_names = {d["name"] for d in gap.missing}
    assert missing_names == {"Hotfrog"}  # Yelp + Bing already covered
    assert gap.existing_count == 2
    assert gap.covered_count == 2
    # CHANGED with 0106, and this is the point of that migration. This used to assert
    # that a `submitted` row with a `proof_url` "surfaces as a live URL" - i.e. it pinned
    # the defect in place: `proof_url` is a SCREENSHOT key, and `submitted` means a form
    # was sent and nothing has confirmed a listing came back. Neither fact is a live
    # listing, and rendering them as one is what put /var/lib/... paths on an operator's
    # screen under "Live listings already earned". Only a `live` row with a real
    # `live_url` may appear here; see tests/modules/citations/test_liveness.py.
    assert gap.live_urls == []
    assert gap.by_submit_status == {"submitted": 1, "not_started": 1}


def test_gap_failed_and_blocked_rows_are_still_missing() -> None:
    directories = [_dir("d1", "Yelp"), _dir("d2", "Hotfrog")]
    existing = [
        {"id": "c1", "directory": "Yelp", "directory_id": "d1", "submit_status": "failed",
         "nap_status": "missing", "proof_url": ""},
        {"id": "c2", "directory": "Hotfrog", "directory_id": "d2", "submit_status": "blocked",
         "nap_status": "missing", "proof_url": ""},
    ]
    gap = compute_citation_gap(directories=directories, existing_citations=existing)
    # both are retryable outcomes -> still open gaps to close
    assert {d["name"] for d in gap.missing} == {"Yelp", "Hotfrog"}
    assert gap.covered_count == 0
    assert gap.by_submit_status == {"failed": 1, "blocked": 1}


def test_gap_manual_only_directories_are_never_missing() -> None:
    directories = [_dir("d1", "Data Axle", tier="manual_only", submit_method="")]
    gap = compute_citation_gap(directories=directories, existing_citations=[])
    assert gap.missing == []  # manual_only has no worker path -> never a build target


# --------------------------------------------------------------------------- #
# build_audit_plan: Generic -> Country -> Niche buckets, each built|missing
# --------------------------------------------------------------------------- #
def test_audit_plan_groups_generic_country_and_niche() -> None:
    directories = [
        _dir("g1", "Foursquare", market="GLOBAL", verticals=[]),   # generic
        _dir("c1", "YellowPages", market="US", verticals=[]),      # country
        _dir("n1", "Avvo", market="US", verticals=["legal"]),      # niche (legal client)
        _dir("n2", "Healthgrades", market="US", verticals=["medical"]),  # off-vertical
    ]
    plan = build_audit_plan(directories=directories, existing_citations=[], vertical="legal")
    assert {d["name"] for d in plan.generic} == {"Foursquare"}
    assert {d["name"] for d in plan.country} == {"YellowPages"}
    assert {d["name"] for d in plan.niche} == {"Avvo"}  # medical row excluded off-vertical
    # with no citations, every surfaced directory is a missing build target.
    all_items = plan.generic + plan.country + plan.niche
    assert all(d["_status"] == "missing" for d in all_items)


def test_audit_plan_marks_built_vs_missing_from_existing_citations() -> None:
    directories = [
        _dir("g1", "Foursquare", market="GLOBAL", verticals=[]),
        _dir("c1", "YellowPages", market="US", verticals=[]),
    ]
    existing = [
        # a live submission covering Foursquare (by directory_id) -> BUILT
        {"id": "c1", "directory": "Foursquare", "directory_id": "g1",
         "submit_status": "submitted", "nap_status": "missing", "proof_url": "https://p/1"},
    ]
    plan = build_audit_plan(directories=directories, existing_citations=existing, vertical=None)
    statuses = {d["name"]: d["_status"] for d in plan.generic + plan.country}
    assert statuses == {"Foursquare": "built", "YellowPages": "missing"}


def test_audit_plan_is_empty_when_no_directories() -> None:
    plan = build_audit_plan(directories=[], existing_citations=[], vertical="legal")
    assert plan.generic == [] and plan.country == [] and plan.niche == []


# --------------------------------------------------------------------------- #
# Web 2.0 status board
# --------------------------------------------------------------------------- #
def test_web2_board_connected_missing_and_draft_only() -> None:
    statuses = {p.platform: p for p in web2_platform_status({"WordPress.com": 3})}
    wp = statuses["WordPress.com"]
    assert wp.connected is True and wp.configured_count == 3
    assert "oauth_token" in wp.required_fields
    devto = statuses["dev.to"]
    assert devto.connected is False and "Missing" in devto.reason
    medium = statuses["Medium"]
    assert medium.draft_only is True and medium.connected is False
    assert "retired" in medium.reason and medium.external_note == ""
    # a connected, live platform always carries the external caveat
    assert "external" in wp.external_note.lower()


def test_web2_board_rollup_counts() -> None:
    board = web2_status_board({"WordPress.com": 1, "Tumblr": 2})
    assert board.connected_count == 2
    assert board.total_count == len(board.platforms)
    # Whatever the current platform total is, Medium is the only draft-only one.
    assert board.live_count == board.total_count - 1


# --------------------------------------------------------------------------- #
# Citation engine status board
# --------------------------------------------------------------------------- #
def test_engine_status_all_missing_on_keyless_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The bot's availability is install-based, not key-based - and the design-capture
    # work now installs the automation extra into this venv, so its absence is
    # SIMULATED rather than assumed of the environment.
    import integrations.citation_status as cs

    monkeypatch.setattr(cs, "playwright_bot_available", lambda: False)
    settings = Settings(_env_file=None, app_env="dev")  # type: ignore[call-arg]
    engines = {e.key: e for e in citation_engine_status(settings)}
    assert engines["bing_places"].connected is False
    assert engines["playwright_bot"].connected is False  # optional extra, never a key
    # every engine carries an honest reason
    for e in engines.values():
        assert e.reason
    # A RETIRED engine names NO required config, on purpose: listing a key implies
    # "set this and it works", and no key can enable an endpoint that returns 404.
    for key in ("bing_places", "foursquare"):
        assert engines[key].required_config == ()
        assert "RETIRED" in engines[key].label
    for key, e in engines.items():
        if key not in ("bing_places", "foursquare"):
            assert e.required_config


def test_a_key_cannot_reconnect_a_retired_engine() -> None:
    """Bing Places and Foursquare are RETIRED, not merely unconfigured.

    This test used to assert that setting BING_PLACES_API_KEY flips the board to
    CONNECTED. It must not: the coded write endpoints return 404 to a live probe
    (2026-08-23), so a key buys nothing. Reporting CONNECTED would tell an operator a
    submission path exists when the submitter has been deleted."""
    settings = Settings(  # type: ignore[call-arg]
        _env_file=None, app_env="dev",
        bing_places_api_key="k",
        foursquare_api_key="k",
    )
    engines = {e.key: e for e in citation_engine_status(settings)}
    assert engines["bing_places"].connected is False
    assert engines["foursquare"].connected is False
    assert "404" in engines["bing_places"].reason
    # FOURSQUARE_API_KEY is still live for DISCOVERY (a read path) - the reason says so,
    # so nobody deletes the key while something still depends on it.
    assert "DISCOVERY" in engines["foursquare"].reason


# --------------------------------------------------------------------------- #
# Determinism: the cap must not decide what counts as covered.
#
# QA ran the same client's citation audit twice and read two different answers:
# "4 existing / 4 covered / 45 missing", then "4 built / 41 missing". Nothing about
# the client or the catalog had changed.
#
# The cause was the ORDER of two steps. The selection capped the catalog to 45
# first, and covered directories were subtracted from that 45 afterwards - so
# whether a covered listing reduced `missing` depended on whether it happened to
# sit inside the top 45 of the build order. Four covered rows inside it gave 41;
# the same four outside it gave 45, with `covered_count` reading 4 either way.
#
# The fix subtracts first and caps second, so the cap means "the next N to build"
# and the number moves only when the coverage or the catalog really does.
# --------------------------------------------------------------------------- #
def _catalog(n: int) -> list[dict[str, Any]]:
    """n directories in a STABLE build order: d000 sorts first, d049 last."""
    return [
        _dir(f"d{i:03d}", f"Dir{i:03d}", authority=90 - i, authority_tier="core")
        for i in range(n)
    ]


def _covered(directory_id: str, name: str) -> dict[str, Any]:
    return {
        "directory_id": directory_id, "directory": name,
        "submit_status": "live", "nap_status": "consistent", "live_url": "https://x.example/l",
    }


def test_covered_directories_reduce_the_missing_count_wherever_they_sit() -> None:
    """The load-bearing case. Four covered listings must remove four from the
    build target whether they are near the top of the catalog or the bottom -
    otherwise the same client reads 41 one day and 45 the next."""
    cat = _catalog(50)

    near_top = compute_citation_gap(
        directories=cat,
        existing_citations=[_covered(f"d{i:03d}", f"Dir{i:03d}") for i in range(4)],
        cap=45,
    )
    near_bottom = compute_citation_gap(
        directories=cat,
        existing_citations=[_covered(f"d{i:03d}", f"Dir{i:03d}") for i in range(46, 50)],
        cap=45,
    )

    assert near_top.covered_count == near_bottom.covered_count == 4
    # 50 in the catalog, 4 covered, 46 genuinely missing -> capped to 45 in both.
    assert near_top.missing and near_bottom.missing
    assert len(near_top.missing) == len(near_bottom.missing) == 45


def test_the_cap_is_applied_to_what_is_actually_missing() -> None:
    cat = _catalog(50)
    gap = compute_citation_gap(
        directories=cat,
        existing_citations=[_covered(f"d{i:03d}", f"Dir{i:03d}") for i in range(10)],
        cap=45,
    )
    # 50 - 10 covered = 40 missing, which is under the cap, so the cap does nothing.
    assert len(gap.missing) == 40
    assert not any(s["reason"] == "over_campaign_cap" for s in gap.skipped)
    # And nothing already covered leaks back into the build target.
    assert {str(d["id"]) for d in gap.missing}.isdisjoint({f"d{i:03d}" for i in range(10)})


def test_directories_beyond_the_cap_are_recorded_as_deferred_not_dropped() -> None:
    """A shorter-than-expected list must never be indistinguishable from a silent
    failure - the same contract every other skip reason keeps."""
    gap = compute_citation_gap(directories=_catalog(60), existing_citations=[], cap=45)

    assert len(gap.missing) == 45
    deferred = [s for s in gap.skipped if s["reason"] == "over_campaign_cap"]
    assert len(deferred) == 15
    assert "queued in a later campaign" in deferred[0]["detail"]


def test_the_same_inputs_give_the_same_answer_twice() -> None:
    """Determinism, stated directly: the audit is a pure function of the stored
    rows, so two runs over unchanged data cannot disagree."""
    cat = _catalog(50)
    existing = [_covered(f"d{i:03d}", f"Dir{i:03d}") for i in (3, 17, 41, 48)]

    first = compute_citation_gap(directories=cat, existing_citations=existing, cap=45)
    second = compute_citation_gap(directories=cat, existing_citations=existing, cap=45)

    assert first.covered_count == second.covered_count
    assert [d["id"] for d in first.missing] == [d["id"] for d in second.missing]


def test_a_legacy_row_without_a_directory_id_still_counts_as_covered() -> None:
    """Discovery writes citations with a free-text name and no directory_id, so
    name matching is the only thing that stops a found listing being re-queued as
    missing. If this regressed, every discovered listing would be built twice."""
    gap = compute_citation_gap(
        directories=_catalog(10),
        existing_citations=[
            {"directory": "Dir003", "submit_status": "live", "nap_status": "consistent"}
        ],
        cap=45,
    )
    assert gap.covered_count == 1
    assert "d003" not in {str(d["id"]) for d in gap.missing}


# --------------------------------------------------------------------------- #
# canonical_norm: the one rule both sides of a directory match must agree on.
#
# Discovery names a found listing from its DOMAIN; the catalog names the same
# directory as a product. Measured against the live catalog (226 active rows) on
# 2026-09-01, 11 of the 31 names discovery can emit matched nothing - including
# Google Business, Bing Places, Facebook and Foursquare, i.e. the listings a local
# business is most likely to already have. Each of those was reported as MISSING
# every time, and whether it moved the count depended on where it fell against the
# 45-row cap.
# --------------------------------------------------------------------------- #
def test_aliases_map_the_five_verified_name_mismatches() -> None:
    from app.services.directory_names import canonical_norm

    assert canonical_norm("Google Business") == canonical_norm("Google Business Profile")
    assert canonical_norm("Bing Places") == canonical_norm("Bing Places for Business")
    assert canonical_norm("Facebook") == canonical_norm("Facebook Business (Page)")
    assert canonical_norm("Foursquare") == canonical_norm("Foursquare Places")
    assert canonical_norm("Apple Maps") == canonical_norm("Apple Business Connect")


def test_normalisation_still_handles_punctuation_and_case_on_its_own() -> None:
    from app.services.directory_names import canonical_norm

    assert canonical_norm("YellowPages.com") == canonical_norm("yellowpages.com")
    assert canonical_norm("Chamber of Commerce") == canonical_norm("ChamberofCommerce")
    assert canonical_norm("TripAdvisor") == canonical_norm("Tripadvisor")


def test_ambiguous_names_are_left_unresolved_rather_than_guessed() -> None:
    """The safety property. A wrong merge marks a directory covered that was never
    built, and nothing afterwards signals it went wrong - the operator simply never
    builds the listing. A miss only costs a duplicate offer.

    "Yellow Pages" has six plausible catalog targets across three countries, "BBB"
    three, and "Local.com" would collide with "Local.com.au" - a different country's
    directory. None of them may be in the alias map.
    """
    from app.services.directory_names import _DIRECTORY_ALIASES, canonical_norm

    for risky in ("yellowpages", "bbb", "angi", "justia", "localcom"):
        assert risky not in _DIRECTORY_ALIASES

    # And the specific false merge that would matter most:
    assert canonical_norm("Local.com") != canonical_norm("Local.com.au")


def test_an_aliased_discovery_row_suppresses_the_catalog_entry_it_covers() -> None:
    """End to end over the gap: a client whose Google Business listing was FOUND
    must not be told to build Google Business Profile."""
    directories = [
        _dir("d1", "Google Business Profile"),
        _dir("d2", "Bing Places for Business"),
        _dir("d3", "Hotfrog"),
    ]
    # Exactly what discovery writes: the domain-derived name, no directory_id.
    existing = [
        {"directory": "Google Business", "submit_status": "live", "nap_status": "consistent"},
        {"directory": "Bing Places", "submit_status": "live", "nap_status": "consistent"},
    ]
    gap = compute_citation_gap(directories=directories, existing_citations=existing)

    assert gap.covered_count == 2
    assert [d["id"] for d in gap.missing] == ["d3"]
