"""Local-SEO wire shapes: the frozen key sets + the two fields that must NEVER leak.

No ``frontend/lib/*.ts`` type mirrors this module, so there is no contract lock to
inherit - these tests ARE the lock. They freeze the emitted key set of every response
model, so a field added/renamed/removed shows up here rather than in a client's
broken dashboard.

Two leak guards are the point of the file:

1. ``oauth_vault_ref`` - the POINTER to a vault-sealed Google refresh token. It is
   absent from ``GbpProfileResponse`` by CONSTRUCTION (not excluded), so no future
   ``model_dump`` flag or serializer change can surface it.
2. ``client_id`` - the internal tenant id; ``client`` (the snapshot name) is what the
   wire carries.

Plus the NULL contract: ``rank=None`` must survive serialization as ``null``. A
coercion to 0 would render as a rank better than #1 on a client's report.

Also pinned here: the 0039 SCOPE GUARD - the migration must create NO ``gbp_posts``
and NO ``gbp_review_replies`` table. GBP posting + auto review-replies are out of
contract scope, and a scope guard that lives only in a docstring is a promise, not a
constraint.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from app.modules.local_seo.schemas import (
    GbpProfileResponse,
    LocalRankHistoryPoint,
    LocalRankingCreate,
    LocalRankingResponse,
    LocalRankingUpdate,
    LocalStats,
    NapAlignmentReport,
    NapDirectoryFinding,
    ProfileUpsert,
    RefreshQueuedResponse,
)

pytestmark = pytest.mark.unit

_RANKING_KEYS = {
    "id", "location", "client", "keyword", "geo", "rank", "previousRank", "change",
    "inMapPack", "foundUrl", "topCompetitors", "provider", "isActive", "lastCheckedAt",
}
_PROFILE_KEYS = {
    "id", "client", "location", "placeId", "primaryCategory", "secondaryCategories",
    "napName", "napAddress", "napPhone", "website", "hours", "reviewCount", "avgRating",
    "completeness", "oauthConnected", "lastSyncedAt",
}
_STATS_KEYS = {"gbpProfiles", "avgMapRank", "citations"}
_HISTORY_KEYS = {"rank", "inMapPack", "provider", "checkedAt"}
_NAP_KEYS = {
    "id", "location", "client", "napName", "napAddress", "napPhone", "directories",
    "consistent", "inconsistent", "missing", "cosmeticOnly", "aligned",
}

_MIGRATION = (
    Path(__file__).resolve().parents[4] / "db" / "migrations" / "0039_local_seo.sql"
)


def _ranking_row(**over: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "id": "rk-1",
        "client_id": "cl-secret",
        "client_name": "Verde Cafe",
        "location_label": "Karachi",
        "keyword": "cafe near me",
        "geo": "Karachi, PK",
        "rank": 2,
        "previous_rank": 4,
        "rank_change": 2,
        "in_map_pack": True,
        "found_url": "https://verde.example",
        "top_competitors": ["Bean There", "Verde Cafe", "Cafe Uno"],
        "provider": "serper_places",
        "is_active": True,
        "last_checked_at": dt.datetime(2026, 7, 1, 12, 0, tzinfo=dt.UTC),
    }
    row.update(over)
    return row


def _profile_row(**over: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "id": "gp-1",
        "client_id": "cl-secret",
        "client_name": "Verde Cafe",
        "location_label": "Karachi",
        "google_location_id": "locations/123",
        "place_id": "ChIJ-secret-place",
        "primary_category": "Cafe",
        "secondary_categories": ["Coffee shop", "Bakery"],
        "nap_name": "Verde Cafe",
        "nap_address": "123 Main Street",
        "nap_phone": "+1 555 010 9999",
        "website_uri": "https://verde.example",
        "regular_hours": {"mon": "9-5"},
        "review_count": 214,
        "avg_rating": 4.6,
        "completeness_score": 86,
        "audit": {"findings": {}},
        "oauth_connected": True,
        "oauth_vault_ref": "vault-key-DO-NOT-LEAK",
        "last_synced_at": dt.datetime(2026, 7, 1, 12, 0, tzinfo=dt.UTC),
    }
    row.update(over)
    return row


# --------------------------------------------------------------------------- #
# 1. The frozen key sets.
# --------------------------------------------------------------------------- #
def test_ranking_response_emits_exactly_the_frozen_key_set() -> None:
    body = LocalRankingResponse.from_row(_ranking_row()).model_dump(by_alias=True)
    assert set(body) == _RANKING_KEYS
    assert body["location"] == "Karachi"  # the profile's label, joined in
    assert body["client"] == "Verde Cafe"  # the snapshot, not the id
    assert body["rank"] == 2
    assert body["change"] == 2
    assert body["topCompetitors"] == ["Bean There", "Verde Cafe", "Cafe Uno"]


def test_profile_response_emits_exactly_the_frozen_key_set() -> None:
    body = GbpProfileResponse.from_row(_profile_row()).model_dump(by_alias=True)
    assert set(body) == _PROFILE_KEYS
    assert body["client"] == "Verde Cafe"
    assert body["completeness"] == 86
    assert body["oauthConnected"] is True


def test_stats_emits_exactly_the_frozen_key_set() -> None:
    body = LocalStats.from_row(
        {"gbp_profiles": 9, "avg_map_rank": 3.24, "citations": 210}
    ).model_dump(by_alias=True)
    assert body == {"gbpProfiles": 9, "avgMapRank": 3.2, "citations": 210}
    assert set(body) == _STATS_KEYS


def test_history_point_emits_exactly_the_frozen_key_set() -> None:
    body = LocalRankHistoryPoint.from_row(
        {
            "rank": 3, "in_map_pack": True, "provider": "serper_places",
            "checked_at": dt.datetime(2026, 7, 1, tzinfo=dt.UTC),
        }
    ).model_dump(by_alias=True)
    assert set(body) == _HISTORY_KEYS
    assert body["checkedAt"].startswith("2026-07-01")


def test_nap_alignment_emits_exactly_the_frozen_key_set() -> None:
    report = NapAlignmentReport(
        id="gp-1", location="Karachi", client="Verde Cafe", nap_name="Verde Cafe",
        nap_address="123 Main Street", nap_phone="5550109999",
        directories=[
            NapDirectoryFinding(
                directory="Yelp", status="consistent", note="", cosmetic_only=False
            )
        ],
        consistent=1, inconsistent=0, missing=0, cosmetic_only=0, aligned=True,
    )
    body = report.model_dump(by_alias=True)
    assert set(body) == _NAP_KEYS
    assert set(body["directories"][0]) == {"directory", "status", "note", "cosmeticOnly"}


# --------------------------------------------------------------------------- #
# 2. The leak guards.
# --------------------------------------------------------------------------- #
def test_the_oauth_vault_ref_is_never_serialized() -> None:
    """The vault ref points at an AES-GCM sealed Google refresh token. Leaking it
    hands an attacker the coordinates of the secret."""
    profile = GbpProfileResponse.from_row(_profile_row())
    assert "oauth_vault_ref" not in profile.model_dump()
    assert "oauth_vault_ref" not in profile.model_dump(by_alias=True)
    assert "vault-key-DO-NOT-LEAK" not in profile.model_dump_json(by_alias=True)


def test_the_response_model_has_no_vault_ref_field_at_all() -> None:
    """Stronger than "it is not emitted": the field does not EXIST on the model, so no
    serializer flag, ``model_dump(mode=...)`` or future refactor can surface it."""
    assert "oauth_vault_ref" not in GbpProfileResponse.model_fields
    assert "oauthVaultRef" not in GbpProfileResponse.model_fields


def test_the_wire_says_only_whether_a_token_is_connected() -> None:
    # The useful half of the secret (does this client have GBP linked?) survives.
    connected = GbpProfileResponse.from_row(_profile_row())
    absent = GbpProfileResponse.from_row(
        _profile_row(oauth_connected=False, oauth_vault_ref=None)
    )
    assert connected.oauth_connected is True
    assert absent.oauth_connected is False


@pytest.mark.parametrize(
    "model_and_row",
    [
        (LocalRankingResponse, _ranking_row()),
        (GbpProfileResponse, _profile_row()),
    ],
)
def test_the_internal_client_id_never_reaches_the_wire(
    model_and_row: tuple[Any, dict[str, Any]],
) -> None:
    model, row = model_and_row
    payload = model.from_row(row).model_dump_json(by_alias=True)
    assert "cl-secret" not in payload  # not the value...
    assert "client_id" not in payload and "clientId" not in payload  # ...nor the key


# --------------------------------------------------------------------------- #
# 3. The NULL contract: "not in the pack" must survive as null.
# --------------------------------------------------------------------------- #
def test_a_null_rank_stays_null_on_the_wire() -> None:
    """NULL = "checked, not in the local pack". Coercing it to 0 would render as a
    rank BETTER than #1; coercing it to a sentinel would invent data."""
    body = LocalRankingResponse.from_row(
        _ranking_row(rank=None, previous_rank=None, in_map_pack=False)
    ).model_dump(by_alias=True)
    assert body["rank"] is None
    assert body["previousRank"] is None
    assert body["inMapPack"] is False


def test_a_null_rank_serializes_as_json_null_not_zero() -> None:
    payload = LocalRankingResponse.from_row(_ranking_row(rank=None)).model_dump_json(
        by_alias=True
    )
    assert '"rank":null' in payload.replace(" ", "")


def test_a_null_history_rank_stays_null() -> None:
    # An out-of-pack day is a real, chartable observation - not a gap, not a zero.
    point = LocalRankHistoryPoint.from_row(
        {"rank": None, "in_map_pack": False, "provider": "fake", "checked_at": None}
    )
    assert point.rank is None
    assert point.checked_at == ""


def test_rank_zero_is_not_confused_with_a_missing_rank() -> None:
    # Guards the `int(x or 0)` bug class from the other direction: a falsy-but-real
    # value must not be swallowed either.
    assert LocalRankingResponse.from_row(_ranking_row(rank=0)).rank == 0


def test_an_unrated_profile_reports_no_rating_rather_than_zero_stars() -> None:
    # 0.0 would render as "rated 0 stars"; None renders as "not rated yet".
    assert GbpProfileResponse.from_row(_profile_row(avg_rating=None)).avg_rating is None
    # A real rating survives (the column is numeric(2,1), so 1dp is the full domain);
    # a psycopg Decimal is coerced to a plain float for JSON.
    assert GbpProfileResponse.from_row(_profile_row(avg_rating=4.6)).avg_rating == 4.6
    assert GbpProfileResponse.from_row(_profile_row(avg_rating=Decimal("4.6"))).avg_rating == 4.6


# --------------------------------------------------------------------------- #
# 4. Defensive row coercion.
# --------------------------------------------------------------------------- #
def test_every_response_model_survives_a_completely_empty_row() -> None:
    # RLS/joins can hand back sparse rows; a KeyError here would 500 a whole list.
    assert LocalRankingResponse.from_row({}).rank is None
    assert GbpProfileResponse.from_row({}).completeness == 0
    assert LocalStats.from_row({}).citations == 0
    assert LocalRankHistoryPoint.from_row({}).rank is None


@pytest.mark.parametrize("bad", [None, "not-a-list", 42, {}])
def test_a_non_list_competitors_column_degrades_to_empty(bad: Any) -> None:
    assert LocalRankingResponse.from_row(_ranking_row(top_competitors=bad)).top_competitors == []


@pytest.mark.parametrize("bad", [None, "not-a-dict", 42, []])
def test_a_non_dict_hours_column_degrades_to_empty(bad: Any) -> None:
    assert GbpProfileResponse.from_row(_profile_row(regular_hours=bad)).hours == {}


def test_a_never_checked_ranking_reports_an_empty_timestamp() -> None:
    assert LocalRankingResponse.from_row(_ranking_row(last_checked_at=None)).last_checked_at == ""


# --------------------------------------------------------------------------- #
# 5. Request models.
# --------------------------------------------------------------------------- #
def test_ranking_create_accepts_camel_case_aliases() -> None:
    body = LocalRankingCreate.model_validate(
        {"profileId": "gp-1", "keyword": "cafe near me", "geo": "Karachi, PK"}
    )
    assert body.profile_id == "gp-1" and body.geo == "Karachi, PK"


def test_ranking_create_allows_a_geo_less_row() -> None:
    # geo is optional: an omitted locale means the profile's default market. 0039's
    # `nulls not distinct` index is what keeps that row deduping.
    assert LocalRankingCreate.model_validate({"profileId": "gp-1", "keyword": "x"}).geo is None


@pytest.mark.parametrize("body", [
    {"profileId": "gp-1", "keyword": ""},          # blank keyword
    {"keyword": "cafe"},                            # no profile
    {"profileId": "gp-1", "keyword": "x" * 201},   # over-long keyword
])
def test_ranking_create_rejects_a_bad_body(body: dict[str, Any]) -> None:
    with pytest.raises(ValueError):
        LocalRankingCreate.model_validate(body)


def test_ranking_create_carries_no_grid_parameters() -> None:
    """The SCOPE GUARD at the wire: a single position per (profile, keyword, geo).

    No lat/lng, no radius, no point count - a grid request is not merely ignored, it
    is unrepresentable in this model.
    """
    fields = set(LocalRankingCreate.model_fields)
    assert fields == {"profile_id", "keyword", "geo"}
    for banned in ("lat", "lng", "latitude", "longitude", "radius", "grid", "points"):
        assert banned not in fields


def test_ranking_update_is_the_activate_deactivate_flag() -> None:
    assert LocalRankingUpdate.model_validate({"isActive": False}).is_active is False
    assert set(LocalRankingUpdate.model_fields) == {"is_active"}


def test_profile_upsert_cannot_set_a_derived_or_secret_column() -> None:
    """completeness/audit are SERVER-DERIVED and the vault ref is a secret pointer:
    none may be driven from request JSON."""
    fields = set(ProfileUpsert.model_fields)
    for banned in (
        "completeness_score", "completeness", "audit", "oauth_vault_ref",
        "oauth_connected", "review_count", "avg_rating",
    ):
        assert banned not in fields


def test_profile_upsert_ignores_unknown_extra_keys() -> None:
    # A caller cannot smuggle a column in by name.
    body = ProfileUpsert.model_validate(
        {"clientId": "cl-1", "locationLabel": "Karachi", "oauthVaultRef": "pwn",
         "completenessScore": 100}
    )
    assert "oauthVaultRef" not in body.model_dump(exclude_unset=True)
    assert body.model_dump(exclude_unset=True) == {
        "client_id": "cl-1", "location_label": "Karachi"
    }


def test_refresh_queued_response_can_express_an_honest_hold() -> None:
    held = RefreshQueuedResponse(id="gp-1", queued=False, held=True, reason="no_oauth_client")
    assert held.model_dump() == {
        "id": "gp-1", "queued": False, "held": True, "reason": "no_oauth_client"
    }
    assert RefreshQueuedResponse(id="rk-1", queued=True).held is False


# --------------------------------------------------------------------------- #
# 6. THE SCOPE GUARD - pinned against the migration, not merely promised.
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("banned", ["gbp_posts", "gbp_review_replies"])
def test_0039_creates_no_gbp_posts_or_review_replies_table(banned: str) -> None:
    """GBP posting + auto review-replies are explicitly NOT in the client's contract
    (they appear only in a frontend tier bullet). GBP here is profile management + NAP,
    READ-ONLY.

    This asserts on the MIGRATION rather than on a code comment: a scope guard that
    lives only in a docstring is a promise, and the next agent to touch this module
    will not read the docstring. A `create table ... gbp_posts` fails HERE.
    """
    sql = _MIGRATION.read_text(encoding="utf-8").lower()
    assert f"create table if not exists public.{banned}" not in sql
    assert f"create table public.{banned}" not in sql


def test_0039_creates_exactly_the_three_intended_tables() -> None:
    # Stronger than banning two names: enumerate what 0039 is ALLOWED to create, so an
    # out-of-scope table under any OTHER name is caught too.
    import re

    sql = _MIGRATION.read_text(encoding="utf-8").lower()
    created = set(re.findall(r"create table (?:if not exists )?public\.(\w+)", sql))
    assert created == {"gbp_profiles", "local_rankings", "local_rank_history"}


def test_0039_does_not_redefine_the_citations_table_it_only_reads() -> None:
    """The citations ledger is owned by 0018_offpage. A second definition here would
    fork the schema and silently break the off-page module."""
    sql = _MIGRATION.read_text(encoding="utf-8").lower()
    assert "create table if not exists public.citations" not in sql
    assert "alter table public.citations" not in sql


def test_0039_declares_the_ranking_index_nulls_not_distinct() -> None:
    """A geo-less row (geo NULL) must dedupe like a geo-scoped one.

    Under DEFAULT SQL NULL semantics every NULL is distinct, so the unique constraint
    would never fire for a geo-less row and `on conflict (profile_id, keyword, geo)`
    could never catch a duplicate - the exact bug already fixed once in 0035.
    """
    normalized = " ".join(_MIGRATION.read_text(encoding="utf-8").lower().split())
    assert "unique nulls not distinct (profile_id, keyword, geo)" in normalized


def test_0039_forces_rls_on_every_table_it_creates() -> None:
    normalized = " ".join(_MIGRATION.read_text(encoding="utf-8").lower().split())
    for table in ("gbp_profiles", "local_rankings", "local_rank_history"):
        assert f"alter table public.{table} enable row level security" in normalized
        assert f"alter table public.{table} force row level security" in normalized


def test_0039_leaves_the_rank_history_append_only() -> None:
    """A rank timeline that can be rewritten is not evidence: history gets select +
    insert policies and deliberately NO update/delete policy."""
    normalized = " ".join(_MIGRATION.read_text(encoding="utf-8").lower().split())
    assert "create policy local_rank_history_select" in normalized
    assert "create policy local_rank_history_insert" in normalized
    assert "create policy local_rank_history_update" not in normalized
    assert "create policy local_rank_history_delete" not in normalized
