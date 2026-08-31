"""Liveness: a citation is `live` only when someone looked and found the business.

The regression at the bottom of this file is the point of the whole exercise. Before
0106 the gap report populated `live_urls` from `proof_url` - a screenshot key - and the
UI rendered the result as a KPI tile labelled "Live listing URLs" over a heading reading
"Live listings already earned". `test_proof_url_alone_never_counts_as_a_live_listing`
fails if that wiring is ever restored.
"""

from __future__ import annotations

import pytest

from app.modules.citations.service import compute_citation_gap
from app.services.citation_liveness import (
    DELISTED,
    DRIFTED,
    LIVE,
    SUBMITTED,
    LivenessProbe,
    judge_liveness,
    next_recheck_days,
    visible_text,
)

pytestmark = pytest.mark.unit

_NAME = "Bright Harbour Dental"
_PHONE = "+1 (555) 010-9999"
_ADDR = "412 Marine Parade"


def _page(*parts: str) -> str:
    return "<html><body>" + "".join(f"<p>{p}</p>" for p in parts) + "</body></html>"


def _judge(probe: LivenessProbe):
    return judge_liveness(probe, business_name=_NAME, phone=_PHONE, address_line1=_ADDR)


# --------------------------------------------------------------------------- #
# The ladder.
# --------------------------------------------------------------------------- #
def test_name_plus_phone_is_live() -> None:
    v = _judge(LivenessProbe(status_code=200, text=_page(_NAME, "Call 555-010-9999")))
    assert v.status == LIVE
    assert v.is_live
    assert set(v.evidence["matched_fields"]) == {"business_name", "phone"}


def test_name_plus_address_is_live_even_without_the_phone() -> None:
    v = _judge(LivenessProbe(status_code=200, text=_page(_NAME, "412 Marine Parade, Southport")))
    assert v.status == LIVE
    assert "address_line1" in v.evidence["matched_fields"]


def test_street_abbreviation_still_matches() -> None:
    """"88 Harbour St." on the page must match "88 Harbour Street" in our profile -
    reusing local_seo's normaliser is what buys this."""
    v = judge_liveness(
        LivenessProbe(status_code=200, text=_page(_NAME, "88 Harbour St.")),
        business_name=_NAME,
        address_line1="88 Harbour Street",
    )
    assert v.status == LIVE


def test_non_us_street_abbreviations_read_as_drift_not_live() -> None:
    """A KNOWN LIMITATION, pinned so it is a decision and not a surprise.

    `_STREET_FORMS` in local_seo is US-centric: st/rd/ave/blvd/ln/ct/pkwy all expand,
    but the AU/UK forms do not - "Pde" (Parade), "Cres" (Crescent), "Gr" (Grove). A UK
    or AU listing whose address is abbreviated on the page therefore lands as `drifted`
    rather than `live`.

    That is the SAFE direction to fail - it under-claims rather than over-claims, and
    `drifted` still counts as coverage - but it will show up as false drift on the UK
    and AU catalogues, which are 48 of the 226 rows. Fix by extending `_STREET_FORMS`,
    not by loosening the match here."""
    v = judge_liveness(
        LivenessProbe(status_code=200, text=_page(_NAME, "412 Marine Pde.")),
        business_name=_NAME,
        address_line1="412 Marine Parade",
    )
    assert v.status == DRIFTED


def test_phone_split_across_markup_still_matches() -> None:
    """A phone broken up by tags is the common real-world case; digits are read from
    the raw HTML precisely so this does not read as drift."""
    html = f"<html><body><p>{_NAME}</p><span>(555)</span><span> 010-9999</span></body></html>"
    v = _judge(LivenessProbe(status_code=200, text=html))
    assert v.status == LIVE


def test_name_present_but_nap_wrong_is_drifted_not_live() -> None:
    v = _judge(LivenessProbe(status_code=200, text=_page(_NAME, "Call 555-222-3333", "9 Other Road")))
    assert v.status == DRIFTED
    assert v.evidence["matched_fields"] == ["business_name"]


def test_soft_404_is_delisted() -> None:
    """The important one: a removed listing usually 301s to a directory homepage that
    returns a perfectly healthy 200. Status alone would call that live."""
    v = _judge(LivenessProbe(status_code=200, text=_page("Find local dentists near you")))
    assert v.status == DELISTED
    assert "does not contain the business name" in v.evidence["reason"]


def test_404_is_delisted() -> None:
    assert _judge(LivenessProbe(status_code=404, text="")).status == DELISTED


def test_unreachable_host_is_submitted_not_delisted() -> None:
    """Our own DNS blip must never delist a client's citation. An unreachable host is a
    failure to LOOK, which is a different fact from the listing being gone."""
    v = _judge(LivenessProbe(status_code=None))
    assert v.status == SUBMITTED
    assert "not delisted" in v.evidence["reason"]


def test_a_two_character_name_can_never_match() -> None:
    """A name short enough to appear on any page proves nothing, so it must not be
    allowed to promote a row to live."""
    v = judge_liveness(
        LivenessProbe(status_code=200, text=_page("AB", "555-010-9999")),
        business_name="AB",
        phone=_PHONE,
    )
    assert v.status == DELISTED


def test_script_content_does_not_count_as_the_page() -> None:
    """A business name inside a tracking blob is not the listing rendering it."""
    html = f"<html><body><script>var biz='{_NAME}';</script><p>Directory home</p></body></html>"
    v = _judge(LivenessProbe(status_code=200, text=html))
    assert v.status == DELISTED


def test_evidence_carries_the_receipt() -> None:
    v = _judge(
        LivenessProbe(
            status_code=200,
            text=_page(_NAME, "555-010-9999"),
            final_url="https://dir.example/biz/bright-harbour",
            checked_from="probe-egress",
            screenshot_key="ab12.png",
        )
    )
    assert v.evidence["http_status"] == 200
    assert v.evidence["final_url"] == "https://dir.example/biz/bright-harbour"
    assert v.evidence["checked_from"] == "probe-egress"
    assert v.evidence["screenshot_key"] == "ab12.png"
    assert v.method == "http_probe"


def test_visible_text_strips_markup_and_normalises() -> None:
    assert "hello world" in visible_text("<div><b>Hello</b>&nbsp;World</div>")


# --------------------------------------------------------------------------- #
# Cadence.
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(("count", "expected"), [(0, 3), (1, 14), (2, 60)])
def test_new_listings_walk_the_settling_ladder(count: int, expected: int) -> None:
    assert next_recheck_days(recheck_count=count) == expected


def test_route_a_and_core_settle_to_monthly() -> None:
    assert next_recheck_days(recheck_count=3, route="A") == 30
    assert next_recheck_days(recheck_count=9, authority_tier="core") == 30


def test_everything_else_settles_to_quarterly() -> None:
    assert next_recheck_days(recheck_count=3, authority_tier="tier2", route="C") == 90


# --------------------------------------------------------------------------- #
# THE REGRESSION. This is the defect the whole phase exists to close.
# --------------------------------------------------------------------------- #
def test_proof_url_alone_never_counts_as_a_live_listing() -> None:
    """A screenshot is not a listing.

    `proof_url` holds a screenshot key (0045 documents it as "screenshot/receipt") and
    the Playwright bot used to return an absolute server path for it. Reading it into
    `live_urls` published /var/lib/... strings to operators as listings they had earned.
    Neither column may ever be populated from the other."""
    gap = compute_citation_gap(
        directories=[],
        existing_citations=[
            {
                "directory": "Example Directory",
                "submit_status": "submitted",
                "proof_url": "/var/lib/aios/citations/ab12cd34.png",
                "live_url": "",
            }
        ],
    )
    assert gap.live_urls == []


def test_submitted_is_not_live_even_with_a_real_url() -> None:
    """`submitted` means a form was sent and nothing has confirmed a listing came back.
    Only the liveness probe promotes a row, so only `live` may be counted."""
    gap = compute_citation_gap(
        directories=[],
        existing_citations=[
            {
                "directory": "Example Directory",
                "submit_status": "submitted",
                "live_url": "https://dir.example/biz/x",
            }
        ],
    )
    assert gap.live_urls == []


def test_a_live_row_with_a_real_url_is_reported() -> None:
    gap = compute_citation_gap(
        directories=[],
        existing_citations=[
            {
                "directory": "Example Directory",
                "submit_status": "live",
                "proof_url": "/var/lib/aios/citations/ab12cd34.png",
                "live_url": "https://dir.example/biz/x",
            }
        ],
    )
    assert gap.live_urls == [
        {"directory": "Example Directory", "url": "https://dir.example/biz/x", "status": "live"}
    ]


# --------------------------------------------------------------------------- #
# Route F: a directory whose terms forbid automated submission can never be queued.
# --------------------------------------------------------------------------- #
def _dir(name: str, **over: object) -> dict:
    row = {
        "id": name.lower().replace(" ", "-"),
        "name": name,
        "tier": "bot_fillable",
        "submit_method": "bot:playwright",
        "authority_tier": "tier1",
        "route": "C",
    }
    row.update(over)
    return row


def test_a_prohibited_directory_is_never_automatable() -> None:
    """Yelp, Trustpilot and Houzz ban automated ACCESS and RETRIEVAL, and a form bot
    must GET the form before it can fill it - so the clause binds us. The catalogue
    seeded `Yelp for Business` as `bot_fillable`, which is exactly the contradiction
    this blocks. It is a hard filter, never a UI warning."""
    from app.modules.citations.service import automatable_directories, is_prohibited

    rows = [_dir("Yelp for Business", route="F"), _dir("Ourbis")]
    assert is_prohibited(rows[0]) is True
    names = [r["name"] for r in automatable_directories(rows)]
    assert names == ["Ourbis"]


def test_route_f_blocks_even_when_the_tier_says_bot_fillable() -> None:
    """The seeded tier and the terms disagreed on four rows. The terms win."""
    from app.modules.citations.service import automatable_directories

    assert automatable_directories([_dir("Houzz", tier="bot_fillable", route="F")]) == []


def test_a_prohibited_row_never_reaches_the_missing_list() -> None:
    """`missing` is what a campaign queues. A route-F row must not appear in it."""
    gap = compute_citation_gap(
        directories=[_dir("Yelp", route="F"), _dir("Ourbis")], existing_citations=[]
    )
    assert [d["name"] for d in gap.missing] == ["Ourbis"]


def test_a_prohibited_row_is_reported_with_its_clause_not_silently_dropped() -> None:
    """Dropping it silently would make a shorter list indistinguishable from a broken
    system. "We did not submit to Yelp, here is the sentence that says we must not" is
    the answer a client is owed."""
    gap = compute_citation_gap(
        directories=[
            _dir(
                "Yelp",
                route="F",
                tos_clause="Use any robot, spider ... to access, retrieve, copy, scrape",
                tos_source_url="https://terms.yelp.com/tos/en_us/",
            )
        ],
        existing_citations=[],
    )
    skips = {s["directory"]: s for s in gap.skipped}
    assert skips["Yelp"]["reason"] == "prohibited_by_terms"
    assert skips["Yelp"]["detail"] == "https://terms.yelp.com/tos/en_us/"
    assert "robot" in skips["Yelp"]["clause"]


def test_an_aggregator_fed_row_is_reported_as_covered_not_missing() -> None:
    """HERE/TomTom/Waze/MapQuest are fed by the spine. Submitting separately would be
    a duplicate; reporting nothing would look like a gap. So: skipped, with a reason."""
    gap = compute_citation_gap(
        directories=[_dir("Waze", submit_method="aggregator:fed_by_data_axle_foursquare")],
        existing_citations=[],
    )
    assert gap.missing == []
    assert gap.skipped[0]["reason"] == "fed_by_aggregator"
    assert gap.skipped[0]["detail"] == "fed by Data Axle, Foursquare"


def test_every_skip_reason_has_a_client_readable_label() -> None:
    """A reason code with no label reaches a client report as a raw enum string."""
    from app.modules.citations.service import (
        SKIP_REASON_LABELS,
        catalog_skips,
        select_campaign_directories,
    )

    rows = [
        _dir("Yelp", route="F"),
        _dir("Waze", submit_method="aggregator:fed_by_x"),
        _dir("Manual Co", tier="manual_only"),
        _dir("Low DA", authority=5),
        _dir("Angi", is_marketplace=True),
        _dir("Dentists Only", verticals=["dental"]),
    ]
    produced = {s["reason"] for s in catalog_skips(rows)}
    produced |= {s["reason"] for s in select_campaign_directories(rows, cap=1).skipped}
    assert produced, "expected the fixtures to trigger at least one skip"
    assert produced <= set(SKIP_REASON_LABELS), f"unlabelled: {produced - set(SKIP_REASON_LABELS)}"


def test_is_prohibited_reads_the_directory_route_on_a_joined_worker_row() -> None:
    """A bug caught while writing the guard, pinned so it cannot come back.

    The worker's query is `select c.*, d.* as directory_*`, so the joined row carries
    BOTH `route` (the citation's own column, default 'C') and `directory_route` (the
    catalogue's). Reading a bare `route` off that row reads the citation's copy, and the
    terms guard would silently never fire on a prohibited directory - a block that
    always passes is worse than no block, because it reads as protection."""
    from app.modules.citations.service import is_prohibited

    joined = {"route": "C", "directory_route": "F", "directory_name": "Yelp"}
    assert is_prohibited(joined) is True

    # And the citation's own 'F' must not be ignored when there is no join.
    assert is_prohibited({"route": "F"}) is True
    assert is_prohibited({"route": "C", "directory_route": "C"}) is False


def test_skip_reason_labels_match_the_frontend_copy() -> None:
    """The reason vocabulary lives in two files and must not drift.

    A code the frontend has no label for renders to a client as a raw enum string like
    "marketplace_not_opted_in". This is the same single-source discipline
    `test_rbac_single_source.py` applies to the feature matrix."""
    import re
    from pathlib import Path

    from app.modules.citations.service import SKIP_REASON_LABELS

    ts = Path(__file__).resolve().parents[3].parent / "frontend" / "lib" / "offpage.ts"
    assert ts.exists(), f"expected the frontend type at {ts}"
    block = ts.read_text().split("SKIP_REASON_LABEL: Record<CitationSkipReason, string> = {", 1)[1]
    block = block.split("};", 1)[0]
    frontend_keys = set(re.findall(r"^\s*(\w+):", block, re.M))
    assert frontend_keys == set(SKIP_REASON_LABELS), (
        f"backend-only: {set(SKIP_REASON_LABELS) - frontend_keys}; "
        f"frontend-only: {frontend_keys - set(SKIP_REASON_LABELS)}"
    )


def test_the_database_enum_and_the_wire_type_hold_the_same_values() -> None:
    """The gap that let a 500 through, closed.

    `citation_submit_status` is a Postgres enum; `CitationSubmitStatus` is the Pydantic
    Literal the API serialises through. Nothing tied them together, so 0106 added `live`,
    `drifted` and `delisted` to the database while the Literal still listed eight values -
    and the FIRST re-check to write `live` would have failed validation and 500'd
    `GET /offpage/citations` for that client.

    `test_contract_lock.py` already holds the Literal and the frontend union identical.
    This holds the Literal to the migrations, which is the other half."""
    import re
    from pathlib import Path
    from typing import get_args

    from app.schemas.offpage import CitationSubmitStatus

    migrations = Path(__file__).resolve().parents[3].parent / "db" / "migrations"
    assert migrations.is_dir(), f"expected migrations at {migrations}"

    db_values: set[str] = set()
    for path in sorted(migrations.glob("*.sql")):
        text = path.read_text()
        # The CREATE TYPE ... AS ENUM (...) body.
        for body in re.findall(
            r"create type public\.citation_submit_status as enum\s*\((.*?)\)", text, re.I | re.S
        ):
            db_values |= set(re.findall(r"'([a-z_]+)'", body))
        # Every later `alter type ... add value 'x'`.
        db_values |= set(
            re.findall(
                r"alter type public\.citation_submit_status add value(?: if not exists)? '([a-z_]+)'",
                text,
                re.I,
            )
        )

    assert db_values, "found no citation_submit_status values in db/migrations"
    literal_values = set(get_args(CitationSubmitStatus))
    assert db_values == literal_values, (
        f"db-only: {sorted(db_values - literal_values)}; "
        f"literal-only: {sorted(literal_values - db_values)}"
    )
