"""The three Web 2.0 surfaces an operator can actually reach.

Everything the planners decide is worth nothing until something can invoke it, so these
drive the REAL app through the real dependency graph rather than calling the modules:

* ``GET  /offpage/web2/clients/{id}/connection-plan`` - what the client's ONE login can
  and cannot reach, and the single action that would fix each gap;
* ``POST /offpage/web2/broadcast/plan`` - compose once, tick platforms or All, and see
  the whole fan-out BEFORE anything is drafted or paid for;
* ``GET  /offpage/placed-links`` - every outbound link and what became of it, lost first.

The properties under test are the ones a screen would get wrong: that readiness is not
overclaimed, that an excluded platform is reported rather than dropped, and that a link
nobody has looked at does not read the same as one confirmed gone.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
from fastapi import FastAPI

from app.core.auth import CurrentUser, get_current_user
from app.db.offpage_repo import get_offpage_repo

pytestmark = pytest.mark.unit

CLIENT_ID = "11111111-1111-1111-1111-111111111111"


def _user(role: str = "admin") -> CurrentUser:
    return CurrentUser(
        id="u-1", email="lead@agency.test", role=role, status="active", name="Lead",
        title="Lead", avatar_color="#1FA890", phone="", two_fa=False, client_id=None,
    )


class _FakeRepo:
    """Only the reads these three routes use - a fake that answered everything would
    hide which dependencies a route actually has."""

    def __init__(self, **over: Any) -> None:
        self.identity: dict[str, Any] | None = over.pop("identity", {
            "id": CLIENT_ID, "name": "Leeds Drainage Co",
            "web2_handle_base": "leedsdrainageco",
            "web2_contact_email": "web@leedsdrainage.co.uk",
            "web2_imap_host": "", "web2_imap_port": 993, "web2_imap_user": "",
            "web2_imap_vault_provider": "", "web2_imap_vault_label": "",
            "web2_brief": {},
            "web2_username": "leedsdrainageco",
            "web2_password_vault_provider": "local",
            "web2_password_vault_label": f"{CLIENT_ID}:web2-login",
        })
        self.sealed: dict[str, frozenset[str]] = over.pop("sealed", {})
        self.accounts: list[dict[str, Any]] = over.pop("accounts", [])
        self.links: list[dict[str, Any]] = over.pop("links", [])
        self.counts: dict[str, int] = over.pop("counts", {})
        self.board: list[Any] = over.pop("board", [])

    # --- identity / connection plan ---
    def client_web2_identity(self, client_id: str) -> dict[str, Any] | None:
        return self.identity

    def client_sealed_platform_fields(self, client_id: str) -> dict[str, frozenset[str]]:
        return self.sealed

    # --- broadcast ---
    def client_web2_scope(self, client_id: str) -> str:
        return "general"

    def eligible_catalog(self) -> list[dict[str, Any]]:
        return [
            {
                # `automation_ready` is the real gate: without it the eligibility board
                # answers `not_supported` ("no publisher exists yet"), which is correct
                # for a catalogued-but-unbuilt platform and was simply missing from this
                # fake. Omitting it made the routes look broken when the evaluator was
                # doing exactly its job.
                "name": name, "platform_enum": name, "ownership_tier": "per_client",
                "topical_scope": "general", "authority_tier": "high",
                "terms_position": "permits", "mechanism": "api",
                "automation_ready": True,
            }
            for name in ("Ghost", "Mataroa", "Bluesky")
        ]

    def connected_platforms_for(self, client_id: str) -> set[str]:
        return {"Ghost", "Mataroa", "Bluesky"}

    def list_web2_accounts(self, client_id: str | None = None) -> list[dict[str, Any]]:
        return self.accounts

    def publishing_accounts_for(self, client_id: str) -> dict[str, dict[str, Any]]:
        # Per-client AND house: a house account publishes on behalf of clients, and a
        # planner that only saw client-owned rows refused work the agency can do - which
        # is what the first live run against the real database reported.
        return {str(a["platform"]): a for a in self.accounts}

    # --- placed links ---
    def list_placed_links(self, **kw: Any) -> list[dict[str, Any]]:
        self.last_query = kw
        return self.links

    def placed_link_counts(self, **kw: Any) -> dict[str, int]:
        return self.counts


@pytest.fixture
def as_role(app: FastAPI) -> Callable[[str], None]:
    def _set(role: str) -> None:
        app.dependency_overrides[get_current_user] = lambda: _user(role)

    return _set


def _wire(app: FastAPI, repo: _FakeRepo) -> None:
    app.dependency_overrides[get_offpage_repo] = lambda: repo


def _account(platform: str, **over: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "id": f"acc-{platform}", "platform": platform, "health": "active",
        "property_count": 0, "max_properties": 10, "vault_label": f"acc-{platform}",
    }
    row.update(over)
    return row


# --------------------------------------------------------------------------- #
# The connection plan
# --------------------------------------------------------------------------- #
async def test_the_connection_plan_never_overclaims_readiness(
    client: httpx.AsyncClient, app: FastAPI, as_role: Callable[[str], None]
) -> None:
    """A username and password publishes directly on 8 of 53 adapters; 43 need an OAuth
    grant or a token no password substitutes for. Reporting those as "connected" would
    promise a capability the system does not have, and the operator would find out one
    failed publish at a time."""
    _wire(app, _FakeRepo())
    as_role("admin")

    resp = await client.get(f"/api/v1/offpage/web2/clients/{CLIENT_ID}/connection-plan")

    assert resp.status_code == 200
    body = resp.json()
    assert body["readyCount"] > 0
    assert body["oneStepCount"] > body["readyCount"], (
        "most platforms need a token; a plan claiming otherwise is the overclaim"
    )
    assert "publish now" in body["summary"]


async def test_every_unready_platform_names_the_one_action_that_fixes_it(
    client: httpx.AsyncClient, app: FastAPI, as_role: Callable[[str], None]
) -> None:
    """A grid of cards that all say "Connect" is why a client sits at four connected
    platforms indefinitely - nobody can tell which is one click away."""
    _wire(app, _FakeRepo())
    as_role("admin")

    body = (
        await client.get(f"/api/v1/offpage/web2/clients/{CLIENT_ID}/connection-plan")
    ).json()
    one_step = [p for p in body["platforms"] if p["readiness"] == "one_step"]

    assert one_step
    assert all(p["action"] for p in one_step), "an unready platform with no action is a dead end"
    assert any("leedsdrainageco" in p["action"] for p in one_step), (
        "the action names WHICH login to sign in with"
    )


async def test_a_sealed_credential_moves_a_platform_to_ready(
    client: httpx.AsyncClient, app: FastAPI, as_role: Callable[[str], None]
) -> None:
    """A token fetched last month must not keep appearing as outstanding work."""
    as_role("admin")

    _wire(app, _FakeRepo())
    before = (
        await client.get(f"/api/v1/offpage/web2/clients/{CLIENT_ID}/connection-plan")
    ).json()["readyCount"]

    _wire(app, _FakeRepo(sealed={"dev.to": frozenset({"api_key"})}))
    after = (
        await client.get(f"/api/v1/offpage/web2/clients/{CLIENT_ID}/connection-plan")
    ).json()["readyCount"]

    assert after == before + 1


async def test_a_client_with_no_login_is_told_so(
    client: httpx.AsyncClient, app: FastAPI, as_role: Callable[[str], None]
) -> None:
    _wire(app, _FakeRepo(identity={
        "id": CLIENT_ID, "name": "Leeds Drainage Co", "web2_username": "",
        "web2_password_vault_label": "", "web2_imap_port": 993,
    }))
    as_role("admin")

    body = (
        await client.get(f"/api/v1/offpage/web2/clients/{CLIENT_ID}/connection-plan")
    ).json()
    assert any("no shared login is set" in note for note in body["notes"])


async def test_an_unknown_client_is_a_404(
    client: httpx.AsyncClient, app: FastAPI, as_role: Callable[[str], None]
) -> None:
    _wire(app, _FakeRepo(identity=None))
    as_role("admin")
    resp = await client.get(f"/api/v1/offpage/web2/clients/{CLIENT_ID}/connection-plan")
    assert resp.status_code == 404


# --------------------------------------------------------------------------- #
# The broadcast plan
# --------------------------------------------------------------------------- #
async def test_one_subject_fans_out_into_platform_shaped_variants(
    client: httpx.AsyncClient, app: FastAPI, as_role: Callable[[str], None]
) -> None:
    """The measured reason this is not one post sent everywhere: the same topic on thirty
    platforms produced thirty byte-identical articles (r = 1.000), which the similarity
    gate blocks after thirty metered drafts have been paid for."""
    _wire(app, _FakeRepo(accounts=[_account(p) for p in ("Ghost", "Mataroa", "Bluesky")]))
    as_role("admin")

    resp = await client.post(
        "/api/v1/offpage/web2/broadcast/plan",
        json={
            "clientId": CLIENT_ID, "subject": "cctv drain survey",
            "targetUrl": "https://leedsdrainage.co.uk/cctv-drain-survey",
            "platforms": ["all"], "anchors": ["Leeds Drainage Co"],
        },
    )

    assert resp.status_code == 200
    body = resp.json()
    shapes = {p["platform"]: p["shape"] for p in body["posts"]}
    assert shapes["Ghost"] == "article"
    assert shapes["Bluesky"] == "note"

    articles = [p for p in body["posts"] if p["shape"] == "article"]
    angles = [p["angle"] for p in articles]
    assert len(set(angles)) == len(angles), "two articles sharing an angle is the duplicate case"


async def test_an_excluded_platform_is_reported_with_its_reason(
    client: httpx.AsyncClient, app: FastAPI, as_role: Callable[[str], None]
) -> None:
    """A selection quietly shrunk from twenty to six is a lie the operator finds in a
    report weeks later."""
    _wire(app, _FakeRepo(accounts=[
        _account("Ghost"), _account("Mataroa", health="degraded"), _account("Bluesky"),
    ]))
    as_role("admin")

    body = (
        await client.post(
            "/api/v1/offpage/web2/broadcast/plan",
            json={
                "clientId": CLIENT_ID, "subject": "cctv drain survey",
                "targetUrl": "https://leedsdrainage.co.uk/x", "platforms": ["all"],
            },
        )
    ).json()

    excluded = {row["platform"]: row["reason"] for row in body["excluded"]}
    assert "Mataroa" in excluded
    assert "degraded" in excluded["Mataroa"]
    assert "Mataroa" not in {p["platform"] for p in body["posts"]}


async def test_an_empty_selection_is_refused_rather_than_meaning_everything(
    client: httpx.AsyncClient, app: FastAPI, as_role: Callable[[str], None]
) -> None:
    """"None selected" and "All" are different intentions, and a blank that quietly meant
    the second would publish to every platform by accident."""
    _wire(app, _FakeRepo(accounts=[_account("Ghost")]))
    as_role("admin")

    resp = await client.post(
        "/api/v1/offpage/web2/broadcast/plan",
        json={
            "clientId": CLIENT_ID, "subject": "cctv drain survey",
            "targetUrl": "https://leedsdrainage.co.uk/x", "platforms": [],
        },
    )
    assert resp.status_code == 422
    assert "No platforms were selected" in resp.json()["error"]["message"]


async def test_planning_publishes_nothing(
    client: httpx.AsyncClient, app: FastAPI, as_role: Callable[[str], None]
) -> None:
    """A PLAN, not a commit: the operator sees the whole fan-out before anything is
    drafted or paid for."""
    repo = _FakeRepo(accounts=[_account("Ghost")])
    _wire(app, repo)
    as_role("admin")

    await client.post(
        "/api/v1/offpage/web2/broadcast/plan",
        json={
            "clientId": CLIENT_ID, "subject": "cctv drain survey",
            "targetUrl": "https://leedsdrainage.co.uk/x", "platforms": ["Ghost"],
        },
    )
    assert not hasattr(repo, "created"), "the plan route must not write placements"


async def test_broadcast_is_lead_only(
    client: httpx.AsyncClient, app: FastAPI, as_role: Callable[[str], None]
) -> None:
    _wire(app, _FakeRepo(accounts=[_account("Ghost")]))
    as_role("viewer")
    resp = await client.post(
        "/api/v1/offpage/web2/broadcast/plan",
        json={
            "clientId": CLIENT_ID, "subject": "cctv drain survey",
            "targetUrl": "https://leedsdrainage.co.uk/x", "platforms": ["Ghost"],
        },
    )
    assert resp.status_code == 403


# --------------------------------------------------------------------------- #
# Placed links
# --------------------------------------------------------------------------- #
def _link(state: str, **over: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "id": f"pl-{state}", "client_name": "Leeds Drainage Co", "platform": "Ghost",
        "page_url": "https://ghost.test/post", "target_url": "https://leedsdrainage.co.uk/x",
        "anchor": "Leeds Drainage Co", "state": state, "rel": "",
        "first_seen_at": datetime(2026, 3, 1, tzinfo=UTC),
        "last_checked_at": datetime(2026, 9, 1, tzinfo=UTC),
        "lost_at": None,
    }
    row.update(over)
    return row


async def test_the_board_reports_each_state_separately(
    client: httpx.AsyncClient, app: FastAPI, as_role: Callable[[str], None]
) -> None:
    """`unknown` must not read the same as `live` OR as `removed`: "nobody has looked" is
    a gap in our monitoring, not a clean bill of health and not a loss."""
    _wire(app, _FakeRepo(
        counts={"live": 12, "removed": 2, "nofollowed": 1, "unknown": 3},
        links=[_link("removed", lost_at=datetime(2026, 6, 1, tzinfo=UTC))],
    ))
    as_role("viewer")

    body = (await client.get("/api/v1/offpage/placed-links")).json()

    assert body["live"] == 12
    assert body["removed"] == 2
    assert body["nofollowed"] == 1
    assert body["unknown"] == 3


async def test_a_lost_link_carries_the_date_it_went(
    client: httpx.AsyncClient, app: FastAPI, as_role: Callable[[str], None]
) -> None:
    """The question three loose columns on ``web2_properties`` could never answer: "live
    in March, when did we lose it?"."""
    _wire(app, _FakeRepo(links=[
        _link("removed", lost_at=datetime(2026, 6, 1, tzinfo=UTC)),
    ]))
    as_role("viewer")

    row = (await client.get("/api/v1/offpage/placed-links")).json()["links"][0]
    assert row["state"] == "removed"
    assert row["firstSeenAt"].startswith("2026-03-01")
    assert row["lostAt"].startswith("2026-06-01")


async def test_a_link_that_never_went_missing_has_no_lost_date(
    client: httpx.AsyncClient, app: FastAPI, as_role: Callable[[str], None]
) -> None:
    _wire(app, _FakeRepo(links=[_link("live")]))
    as_role("viewer")
    row = (await client.get("/api/v1/offpage/placed-links")).json()["links"][0]
    assert row["lostAt"] == ""


async def test_the_board_can_be_filtered_by_client_and_state(
    client: httpx.AsyncClient, app: FastAPI, as_role: Callable[[str], None]
) -> None:
    repo = _FakeRepo(links=[_link("removed")])
    _wire(app, repo)
    as_role("viewer")

    # `clientId`, the spelling every other filter in this router uses. A query param
    # FastAPI does not recognise is silently ignored rather than rejected, so the wrong
    # spelling would show an operator every client's links on a board they had narrowed
    # to one - and nothing on screen would say so.
    await client.get(f"/api/v1/offpage/placed-links?clientId={CLIENT_ID}&state=removed")
    assert repo.last_query["client_id"] == CLIENT_ID
    assert repo.last_query["state"] == "removed"


async def test_the_snake_case_spelling_is_not_silently_accepted_as_a_filter(
    client: httpx.AsyncClient, app: FastAPI, as_role: Callable[[str], None]
) -> None:
    """The specific failure the alias prevents: an unrecognised param is DROPPED, not
    refused, so a mis-spelled filter reads as "no filter" and the board widens to every
    client without a word on screen."""
    repo = _FakeRepo(links=[_link("removed")])
    _wire(app, repo)
    as_role("viewer")

    await client.get(f"/api/v1/offpage/placed-links?client_id={CLIENT_ID}")
    assert repo.last_query["client_id"] is None
