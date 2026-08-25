"""P2-8 gate: delivery tiers (free/semi/fully) kept separate from subscription."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import httpx
import pytest
from fastapi import FastAPI

from app.core.auth import CurrentUser, get_current_user
from app.db.tiers_repo import get_tiers_repo
from app.schemas.tiers import delivery_tier_modes

pytestmark = pytest.mark.unit


class FakeTiersRepo:
    def __init__(self) -> None:
        self.clients = {
            "cl-1": {"id": "cl-1", "name": "NorthPeak Dental", "industry": "Healthcare",
                     "contact_color": "#7B69EE", "delivery_tier": "fully"},
        }

    def list_tier_clients(
        self, *, limit: int | None = None, offset: int = 0
    ) -> list[dict[str, Any]]:
        return list(self.clients.values())

    def set_delivery_tier(self, client_id: str, tier: str) -> dict[str, Any] | None:
        if client_id not in self.clients:
            return None
        self.clients[client_id]["delivery_tier"] = tier
        return self.clients[client_id]


def _user(role: str) -> CurrentUser:
    return CurrentUser(
        id="u-1", email="op@x.com", role=role, status="active",  # type: ignore[arg-type]
        name="Op", title="", avatar_color="#000", phone="", two_fa=False,
    )


@pytest.fixture
def repo() -> FakeTiersRepo:
    return FakeTiersRepo()


@pytest.fixture
def wire(app: FastAPI, repo: FakeTiersRepo) -> Callable[[str], None]:
    app.dependency_overrides[get_tiers_repo] = lambda: repo

    def _as(role: str) -> None:
        app.dependency_overrides[get_current_user] = lambda: _user(role)

    return _as


@pytest.mark.unit
def test_delivery_tier_modes_are_presets_over_the_dial() -> None:
    # free is the most restrictive, fully is all-API.
    free = delivery_tier_modes("free")
    fully = delivery_tier_modes("fully")
    assert free["C"] == "off" and free["A"] == "byhand"
    assert all(m == "api" for m in fully.values())


# --------------------------------------------------------------------------- #
# The matrix against the document it was sold from.
#
# `FEATURE_AREAS` is not internal reference data. It is the encoded form of the
# comparison table in `docs/deliverables/danyal-AIOS-Service-Tiers.pdf`, delivered to
# the agency owner on 9 July 2026, and it is served to the portal as an upsell page -
# so a drift here is not a bug, it is the platform telling a client something the
# document they hold contradicts.
#
# Nothing compared the two. This does, from the document's own words.
# --------------------------------------------------------------------------- #

# Transcribed from the delivered PDF's per-area rows. `off` where the document prints
# an explicit "no" mark; `byhand` where it describes a person doing it or an upload;
# `api` where it says it runs on its own / auto / live.
_DELIVERED_MATRIX: dict[str, dict[str, str]] = {
    # A - "Your data & rankings": Free is "upload your own file / only when you ask",
    # Semi is "serper.dev on a schedule, or DataForSEO for top keywords", Fully is
    # "DataForSEO - the most accurate rankings", "every night".
    "A": {"free": "byhand", "semi": "byhand", "fully": "api"},
    # B - "Audits & site health": Free is "upload a Screaming Frog file, or 1 free
    # sample audit", Semi "on request", Fully "runs weekly on its own".
    "B": {"free": "byhand", "semi": "byhand", "fully": "api"},
    # C - "Backlinks (off-page)": Free "upload your own file" for the list but an
    # explicit no-mark on every other row, Semi "we compare your weekly uploads",
    # Fully "pulled auto every week".
    "C": {"free": "off", "semi": "byhand", "fully": "api"},
    # D - "Content & publishing": Free is a no-mark on every row except blog articles,
    # which reads "No (1 sample only)". Semi is "AI writes a draft, a person edits &
    # posts". Fully is "drafts queued auto, posted after one approval".
    "D": {"free": "off", "semi": "byhand", "fully": "api"},
    # E - "Local SEO (Google Business Profile)": Free no-mark throughout, Semi "AI
    # suggests, you apply", Fully "auto-posts", "at scale".
    "E": {"free": "off", "semi": "byhand", "fully": "api"},
    # F - "Competitors & strategy": Free no-mark throughout, Semi "by hand" / "AI
    # drafts, a strategist decides", Fully "auto".
    "F": {"free": "off", "semi": "byhand", "fully": "api"},
    # G - "Reports, alerts & workflow": Free "on request, basic branding" plus a basic
    # portal, Semi "data pulled + AI write-up, you edit", Fully "built & sent on a
    # schedule".
    "G": {"free": "byhand", "semi": "byhand", "fully": "api"},
}


@pytest.mark.unit
def test_the_tier_matrix_still_matches_the_document_it_was_sold_from() -> None:
    from app.schemas.tiers import FEATURE_AREAS

    encoded = {area.id: dict(area.modes) for area in FEATURE_AREAS}
    assert encoded == _DELIVERED_MATRIX, (
        "the served tier matrix no longer matches danyal-AIOS-Service-Tiers.pdf (9 July "
        "2026). This table is shown to clients as what each tier includes; changing it "
        "changes what the platform claims to sell. If the change is intended, the "
        "DOCUMENT is the thing to re-issue, and this transcription follows it."
    )


@pytest.mark.unit
def test_free_is_zero_paid_spend_in_every_area_the_document_switches_off() -> None:
    """The one property the free tier's whole commercial basis rests on.

    The document is unambiguous: *"The client pays nothing and we spend nothing on
    data... There is no automation and no paid data."* An area at ``api`` for ``free``
    would mean a metered provider call for a client paying nothing.

    Note what this test does NOT claim. It pins the MATRIX, not the enforcement. As of
    2026-08-24 ``delivery_tier`` is consulted in exactly one route
    (``services/client_audits.py``) and ``delivery_tier_modes`` has no production
    caller at all - so this matrix is a sales page, not a control. See
    ``KNOWN_LIMITATIONS.md``.
    """
    from app.schemas.tiers import FEATURE_AREAS

    on_paid_apis = sorted(a.id for a in FEATURE_AREAS if a.modes["free"] == "api")
    assert not on_paid_apis, (
        f"feature area(s) {on_paid_apis} are set to run on paid APIs for the FREE tier, "
        "which the delivered document prices at $0 to run"
    )


async def test_list_tiers(client: httpx.AsyncClient, wire: Callable[[str], None]) -> None:
    wire("viewer")
    resp = await client.get("/api/v1/tiers")
    assert resp.status_code == 200
    tiers = {t["key"]: t for t in resp.json()}
    assert set(tiers) == {"free", "semi", "fully"}
    assert tiers["semi"]["popular"] is True
    assert tiers["fully"]["price"] == 54


async def test_feature_areas_matrix(client: httpx.AsyncClient, wire: Callable[[str], None]) -> None:
    wire("viewer")
    resp = await client.get("/api/v1/tiers/feature-areas")
    assert resp.status_code == 200
    areas = resp.json()
    assert len(areas) == 7
    assert areas[0]["modes"]["fully"] == "api"


async def test_list_and_set_delivery_tier(client: httpx.AsyncClient, wire: Callable[[str], None]) -> None:
    wire("viewer")
    listed = await client.get("/api/v1/tiers/clients")
    assert listed.status_code == 200
    row = listed.json()[0]
    assert row["tier"] == "fully"
    assert row["init"] == "ND"

    # setting requires manage_clients
    denied = await client.put("/api/v1/tiers/clients/cl-1", json={"tier": "semi"})
    assert denied.status_code == 403
    wire("manager")
    ok = await client.put("/api/v1/tiers/clients/cl-1", json={"tier": "semi"})
    assert ok.status_code == 200
    assert ok.json()["tier"] == "semi"
    missing = await client.put("/api/v1/tiers/clients/nope", json={"tier": "free"})
    assert missing.status_code == 404
