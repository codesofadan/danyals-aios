"""The NAP write-back: what a Maps link is allowed to change on a client's record.

`client_business_profiles` is the record the citations module derives its directory
submissions from. A wrong value here does not stay here - it is submitted to directories
under the client's name, and unpicking it across a live campaign costs far more than
pasting the right link did. So this path has two guards and both are tested:

  * it runs only on a VERIFIED identity, so a rejected/failed lookup can never write; and
  * it writes only fields Google actually returned, so a sparse response cannot ERASE
    an address an operator typed by hand.

The second is the easy one to get wrong: passing the whole dataclass through would send
empty strings for every field the provider omitted, and a "sync" that silently deletes
is worse than no sync at all.
"""

from __future__ import annotations

from dataclasses import dataclass
from importlib import import_module
from typing import Any, ClassVar

import pytest

from app.modules.grid_tracker.maps_center import MapsCenter

# THE MODULE, and it has to be fetched this way. The package's `__init__` does
# `from app.modules.grid_tracker.router import router`, which rebinds the name `router`
# ON THE PACKAGE to the APIRouter object - so both `from app.modules.grid_tracker import
# router` and `import app.modules.grid_tracker.router as x` resolve by attribute lookup
# and hand back the APIRouter, which has no `record_activity` to patch.
grid_router = import_module("app.modules.grid_tracker.router")


@dataclass
class FakeUser:
    id: str = "user-1"


class FakeClientsRepo:
    """Records the upsert it was asked to do. One instance per test."""

    calls: ClassVar[list[dict[str, Any]]] = []

    def __init__(self, user_id: str) -> None:
        self.user_id = user_id

    def upsert_business_profile(
        self, *, client_id: str, client_name: str, fields: dict[str, Any]
    ) -> dict[str, Any]:
        FakeClientsRepo.calls.append(
            {"client_id": client_id, "client_name": client_name, "fields": fields}
        )
        return {"id": "profile-1"}


@pytest.fixture(autouse=True)
def fake_repo_and_activity(monkeypatch: pytest.MonkeyPatch) -> None:
    """Swap the repo and silence the activity trail. No DB, no network."""
    FakeClientsRepo.calls = []
    monkeypatch.setattr("app.db.clients_repo.ClientsRepo", FakeClientsRepo)

    async def noop_activity(*_a: object, **_k: object) -> None:
        return None

    monkeypatch.setattr(grid_router, "record_activity", noop_activity)


VERIFIED = MapsCenter(
    lat=-33.866489,
    lng=151.1958561,
    source="places_details",
    place_id="ChIJN1t_tDeuEmsRUsoyG83frY4",
    name="Google Sydney - Pirrama Road",
    address="Ground Floor/48 Pirrama Rd, Pyrmont NSW 2009, Australia",
    city="Pyrmont",
    region="New South Wales",
    postal_code="2009",
    phone="(02) 9374 4000",
    website="http://google.com/",
    identity_verified=True,
)



async def test_a_verified_listing_writes_every_returned_field() -> None:
    await grid_router._sync_nap_from_maps(FakeUser(), "client-1", "Acme", VERIFIED)

    assert len(FakeClientsRepo.calls) == 1
    call = FakeClientsRepo.calls[0]
    assert call["client_id"] == "client-1"
    assert call["fields"] == {
        "business_name": "Google Sydney - Pirrama Road",
        "address_line1": "Ground Floor/48 Pirrama Rd, Pyrmont NSW 2009, Australia",
        "city": "Pyrmont",
        "region": "New South Wales",
        "postal_code": "2009",
        "phone": "(02) 9374 4000",
        "website_url": "http://google.com/",
    }



async def test_an_unverified_identity_writes_nothing() -> None:
    """A rejected or failed lookup must never reach the client's record."""
    unverified = MapsCenter(
        lat=24.8612211, lng=67.0009876, source="maps_pin",
        identity_verified=False, reason="match_too_far",
    )
    await grid_router._sync_nap_from_maps(FakeUser(), "client-1", "Acme", unverified)
    assert FakeClientsRepo.calls == []



async def test_omitted_fields_are_not_written_as_blanks() -> None:
    """THE ERASURE GUARD. Places legitimately omits a phone or a postcode; sending
    those through as "" would delete details the operator entered by hand."""
    sparse = MapsCenter(
        lat=1.0, lng=2.0, source="places_details",
        name="Corner Shop", address="1 High St",
        city="", region="", postal_code="", phone="", website="",
        identity_verified=True,
    )
    await grid_router._sync_nap_from_maps(FakeUser(), "client-1", "Acme", sparse)

    fields = FakeClientsRepo.calls[0]["fields"]
    assert fields == {"business_name": "Corner Shop", "address_line1": "1 High St"}
    # Named explicitly: an absent key is the whole point, and `in` is what proves it.
    for blank in ("city", "region", "postal_code", "phone", "website_url"):
        assert blank not in fields



async def test_a_verified_listing_with_nothing_in_it_writes_nothing() -> None:
    """`identity_verified` with every field blank is a contradiction, not a write."""
    empty = MapsCenter(lat=1.0, lng=2.0, source="places_details", identity_verified=True)
    await grid_router._sync_nap_from_maps(FakeUser(), "client-1", "Acme", empty)
    assert FakeClientsRepo.calls == []



async def test_a_repo_failure_does_not_propagate(monkeypatch: pytest.MonkeyPatch) -> None:
    """The grid was created correctly; a failed NAP sync must not undo that.

    A SUBCLASS rather than a patched attribute on ``FakeClientsRepo``: assigning onto
    the shared fake would leave the broken method in its ``__dict__`` for whichever
    test ran next, and the resulting failure would appear to be in that test.
    """

    class ExplodingRepo(FakeClientsRepo):
        def upsert_business_profile(self, **_k: Any) -> dict[str, Any]:
            raise RuntimeError("db is down")

    monkeypatch.setattr("app.db.clients_repo.ClientsRepo", ExplodingRepo)

    # No raise: the helper swallows and logs, because the definition it belongs to has
    # already been created and must not be rolled back by a follow-up convenience.
    await grid_router._sync_nap_from_maps(FakeUser(), "client-1", "Acme", VERIFIED)
    assert FakeClientsRepo.calls == []
