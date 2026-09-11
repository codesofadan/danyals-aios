"""Extension-assisted Web 2.0 placement (0136, off-page redesign Phase 7).

The properties under test, in order of how expensive they'd be to get wrong:

* ROUTING - a lead's approval of an extension-lane property PARKS it
  (`publishing` + `publish_method='extension'`) and enqueues NOTHING, while an
  api-lane approval keeps the existing enqueue path byte-for-byte.
* COMPLETION IS CHECKED, NOT ASSERTED - the server's own fetch must land on the
  platform's OWN host and find the client's target link, or the completion is
  refused (`accepted:false`) - and a refusal advances nothing: not the property,
  not the spec counters.
* FAIL-CLOSED AUTOFILL - without an ACTIVE placement spec there are no selectors
  and no spec editor URL: copy-blocks only, homepage fallback, never a guess.
* SCOPE - the completion door takes a lead bearer OR an extension token holding
  `web2_queue:write`; a non-lead is 403, unauthenticated is 401.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import httpx
import pytest
from fastapi import FastAPI

from app.db.offpage_repo import get_offpage_repo
from app.routers import offpage as offpage_router
from app.services.web2_eligibility import evaluate_catalog, resolve_selection
from app.services.web2_placement import (
    PlacementVerdict,
    copy_blocks_for,
    editor_url_for,
    host_belongs_to,
    host_of,
    judge_placement,
    spec_selectors,
)

from .test_offpage import FakeOffpageRepo, _user

pytestmark = pytest.mark.unit


# --------------------------------------------------------------------------- #
# The pure verdict: host pinning + link evidence.
# --------------------------------------------------------------------------- #
class TestHostRules:
    def test_host_of_normalizes_case_port_and_www(self) -> None:
        assert host_of("https://WWW.Medium.com:443/p/x") == "medium.com"
        assert host_of("https://blog.medium.com/p/x") == "blog.medium.com"
        assert host_of("") == ""
        assert host_of("not a url") == ""

    def test_subdomain_match_is_dot_anchored(self) -> None:
        assert host_belongs_to("medium.com", "medium.com")
        assert host_belongs_to("blog.medium.com", "medium.com")
        # The attack shape 0108/0114 close at the DB, closed identically here.
        assert not host_belongs_to("evil-medium.com", "medium.com")
        assert not host_belongs_to("medium.com.evil.com", "medium.com")
        assert not host_belongs_to("medium.com", "")
        assert not host_belongs_to("", "medium.com")


_PAGE_WITH_LINK = '<html><a href="https://client.example/services" rel="">go</a></html>'
_PAGE_WITHOUT_LINK = '<html><a href="https://elsewhere.example/">go</a></html>'


class TestJudgePlacement:
    def test_accepts_only_platform_host_plus_link(self) -> None:
        verdict = judge_placement(
            _PAGE_WITH_LINK, "https://medium.com/@op/post",
            platform_host="medium.com", target_url="https://client.example/services",
        )
        assert verdict.accepted and verdict.link.state == "found"

    def test_off_host_page_is_refused_even_with_the_link_on_it(self) -> None:
        verdict = judge_placement(
            _PAGE_WITH_LINK, "https://evil-medium.com/@op/post",
            platform_host="medium.com", target_url="https://client.example/services",
        )
        assert not verdict.accepted
        assert "evil-medium.com" in verdict.reason

    def test_the_final_redirected_host_is_what_is_judged(self) -> None:
        """A pasted medium.com URL that redirected elsewhere is judged on where it
        LANDED - a redirector off the platform must not smuggle a page through."""
        verdict = judge_placement(
            _PAGE_WITH_LINK, "https://tracker.example/x",
            platform_host="medium.com", target_url="https://client.example/services",
        )
        assert not verdict.accepted

    def test_missing_link_is_refused(self) -> None:
        verdict = judge_placement(
            _PAGE_WITHOUT_LINK, "https://medium.com/@op/post",
            platform_host="medium.com", target_url="https://client.example/services",
        )
        assert not verdict.accepted and verdict.link.state == "missing"

    def test_unfetchable_page_is_refused_not_guessed(self) -> None:
        verdict = judge_placement(
            None, "", platform_host="medium.com",
            target_url="https://client.example/services",
        )
        assert not verdict.accepted

    def test_unknown_platform_host_refuses_rather_than_skipping_the_pin(self) -> None:
        """No recorded homepage host must NOT degrade to 'any host passes'."""
        verdict = judge_placement(
            _PAGE_WITH_LINK, "https://medium.com/@op/post",
            platform_host="", target_url="https://client.example/services",
        )
        assert not verdict.accepted


# --------------------------------------------------------------------------- #
# Copy-blocks + spec selectors: fail-closed without an ACTIVE spec.
# --------------------------------------------------------------------------- #
def _draft_row(**over: Any) -> dict[str, Any]:
    row = {
        "topic": "A grounded article",
        "body_md": "## the approved draft",
        "anchor": "plumber in leeds",
        "target_url": "https://client.example/services",
    }
    row.update(over)
    return row


class TestCopyBlocksFailClosed:
    def test_default_blocks_are_the_draft_values_in_order(self) -> None:
        blocks = copy_blocks_for(_draft_row())
        assert [b["key"] for b in blocks] == ["title", "body", "anchor", "target_url"]
        assert blocks[0]["value"] == "A grounded article"

    def test_empty_values_are_dropped_not_rendered_blank(self) -> None:
        blocks = copy_blocks_for(_draft_row(anchor="", body_md="  "))
        assert [b["key"] for b in blocks] == ["title", "target_url"]

    def test_a_spec_reorders_and_relabels_but_cannot_conjure_values(self) -> None:
        spec = {"copy_blocks": [
            {"key": "body", "label": "Story"},
            {"key": "title", "label": "Headline"},
            {"key": "tags", "label": "Tags"},  # no such draft value - must vanish
        ]}
        blocks = copy_blocks_for(_draft_row(), spec)
        assert [(b["key"], b["label"]) for b in blocks] == [
            ("body", "Story"), ("title", "Headline"),
        ]

    def test_no_spec_means_zero_selectors(self) -> None:
        assert spec_selectors(None) == {}
        assert spec_selectors({}) == {}
        assert spec_selectors({"fields": "not-a-list"}) == {}
        assert spec_selectors({"fields": [{"selector": "", "value_key": "title"}]}) == {}

    def test_an_active_spec_with_fields_licenses_exactly_those_selectors(self) -> None:
        spec = {"fields": [
            {"selector": "input[name=title]", "value_key": "title"},
            {"bogus": True},
        ]}
        assert spec_selectors(spec) == {"title": "input[name=title]"}

    def test_editor_url_prefers_the_pinned_spec_then_homepage_then_nothing(self) -> None:
        platform = {"homepage_url": "https://medium.com"}
        assert editor_url_for({"editor_url": "https://medium.com/new-story"}, platform) \
            == "https://medium.com/new-story"
        assert editor_url_for(None, platform) == "https://medium.com"
        assert editor_url_for(None, None) == ""


# --------------------------------------------------------------------------- #
# Eligibility: the plan door may opt an extension-lane platform in; campaigns not.
# --------------------------------------------------------------------------- #
def _extension_catalog_row(**over: Any) -> dict[str, Any]:
    row = {
        "name": "Medium", "platform_enum": "Medium", "ownership_tier": "per_client",
        "topical_scope": "agnostic", "automation_ready": False,
        "authority_tier": "high", "terms_position": "", "mechanism": "extension",
    }
    row.update(over)
    return row


class TestExtensionLaneSelection:
    def test_campaigns_still_refuse_extension_lane_platforms(self) -> None:
        board = evaluate_catalog([_extension_catalog_row()], client_scope="agnostic")
        verdict = resolve_selection(board, ["Medium"])
        assert verdict.allowed == [] and len(verdict.blocked) == 1

    def test_the_plan_door_opts_in_with_allow_extension(self) -> None:
        board = evaluate_catalog([_extension_catalog_row()], client_scope="agnostic")
        verdict = resolve_selection(board, ["Medium"], allow_extension=True)
        assert verdict.allowed == ["Medium"] and verdict.blocked == []

    def test_an_enum_less_extension_platform_stays_blocked_with_the_structural_reason(
        self,
    ) -> None:
        """The ledger's platform column is the enum type - a property row cannot
        exist for 'Substack' until the enum grows, and the refusal must say so."""
        board = evaluate_catalog(
            [_extension_catalog_row(name="Substack", platform_enum=None)],
            client_scope="agnostic",
        )
        verdict = resolve_selection(board, ["Substack"], allow_extension=True)
        assert verdict.allowed == []
        assert any("publishing-enum" in reason for reason in verdict.blocked)


# --------------------------------------------------------------------------- #
# The router: routing on approval + the completion door. Faked repo, no DB.
# --------------------------------------------------------------------------- #
def _needs_review_row(repo: FakeOffpageRepo, *, platform: str = "Medium") -> str:
    row = {
        "id": "w2-1", "client_id": "cl-1", "client_name": "Acme", "platform": platform,
        "anchor": "plumber in leeds", "target_url": "https://client.example/services",
        "topic": "A grounded article", "body_md": "## draft", "status": "needs_review",
        "post_url": "", "verified": "pending", "published_at": None,
        "publish_method": "api", "error": "", "scheduled_for": None,
    }
    repo.web2_by_id["w2-1"] = row
    repo.client_names["cl-1"] = "Acme"
    return "w2-1"


@pytest.fixture
def repo() -> FakeOffpageRepo:
    return FakeOffpageRepo()


@pytest.fixture
def wire(app: FastAPI, repo: FakeOffpageRepo) -> Callable[..., None]:
    from app.core.auth import get_current_user

    app.dependency_overrides[get_offpage_repo] = lambda: repo
    # The completion door's repo is bound to the hybrid write floor (so the extension
    # credential can reach it) - override that binding too, or the door would open a
    # real RLS connection under test.
    app.dependency_overrides[offpage_router.get_offpage_repo_placement] = lambda: repo

    def _as(role: str, uid: str = "u-1") -> None:
        app.dependency_overrides[get_current_user] = lambda: _user(role, uid)
        # The completion door resolves through the hybrid operator guard; override it
        # by identity exactly as the citation-queue tests override resolve_operator.
        app.dependency_overrides[offpage_router.resolve_web2_operator_write] = (
            lambda: _user(role, uid)
        )

    return _as


@pytest.fixture
def publishes(app: FastAPI) -> list[str]:
    sent: list[str] = []
    app.dependency_overrides[offpage_router.get_web2_publish_enqueuer] = (
        lambda: sent.append
    )
    # The similarity recheck must not reach for the privileged store in a unit test.
    app.dependency_overrides[offpage_router.get_web2_similarity_rechecker] = (
        lambda: (lambda _web2_id: "")
    )
    return sent


async def test_extension_lane_approval_parks_and_enqueues_nothing(
    client: httpx.AsyncClient, repo: FakeOffpageRepo,
    wire: Callable[..., None], publishes: list[str],
) -> None:
    web2_id = _needs_review_row(repo)
    repo.set_matrix("Medium", {
        "id": "pl-1", "name": "Medium", "platform_enum": "Medium",
        "mechanism": "extension", "homepage_url": "https://medium.com",
    })
    wire("manager")
    resp = await client.post(f"/api/v1/offpage/web2/{web2_id}/approve", json={"action": "approve"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "publishing"
    assert body["publishMethod"] == "extension"
    assert publishes == []  # the parked row waits for an OPERATOR, not a worker
    assert repo.web2_by_id[web2_id]["publish_method"] == "extension"


async def test_api_lane_approval_keeps_the_enqueue_path(
    client: httpx.AsyncClient, repo: FakeOffpageRepo,
    wire: Callable[..., None], publishes: list[str],
) -> None:
    web2_id = _needs_review_row(repo)
    repo.set_matrix("Medium", {
        "id": "pl-1", "name": "Medium", "platform_enum": "Medium",
        "mechanism": "api", "homepage_url": "https://medium.com",
    })
    wire("manager")
    resp = await client.post(f"/api/v1/offpage/web2/{web2_id}/approve", json={"action": "approve"})
    assert resp.status_code == 200
    assert resp.json()["publishMethod"] == "api"
    assert publishes == [web2_id]


async def test_uncatalogued_platform_keeps_the_api_lane_byte_for_byte(
    client: httpx.AsyncClient, repo: FakeOffpageRepo,
    wire: Callable[..., None], publishes: list[str],
) -> None:
    web2_id = _needs_review_row(repo)  # no matrix row registered at all
    wire("manager")
    resp = await client.post(f"/api/v1/offpage/web2/{web2_id}/approve", json={"action": "approve"})
    assert resp.status_code == 200
    assert publishes == [web2_id]


# --- the completion door -----------------------------------------------------------


def _parked_row(repo: FakeOffpageRepo) -> str:
    web2_id = _needs_review_row(repo)
    repo.web2_by_id[web2_id].update({"status": "publishing", "publish_method": "extension"})
    repo.set_matrix("Medium", {
        "id": "pl-1", "name": "Medium", "platform_enum": "Medium",
        "mechanism": "extension", "homepage_url": "https://medium.com",
    })
    return web2_id


def _stub_fetch(monkeypatch: pytest.MonkeyPatch, html: str | None, final_url: str) -> None:
    from app.services import web2_placement

    monkeypatch.setattr(
        web2_placement, "fetch_placement_page", lambda _url: (html, final_url)
    )


def _public_urls_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(offpage_router, "is_public_url", lambda _url: True)


async def test_completion_accepts_only_a_host_and_link_verified_url(
    client: httpx.AsyncClient, repo: FakeOffpageRepo,
    wire: Callable[..., None], monkeypatch: pytest.MonkeyPatch,
) -> None:
    web2_id = _parked_row(repo)
    wire("manager")
    _public_urls_ok(monkeypatch)
    _stub_fetch(monkeypatch, _PAGE_WITH_LINK, "https://medium.com/@op/post")
    resp = await client.post(
        f"/api/v1/offpage/web2/placements/{web2_id}/complete",
        json={"url": "https://medium.com/@op/post"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["accepted"] is True and body["status"] == "published"
    assert body["linkFound"] is True
    row = repo.web2_by_id[web2_id]
    assert row["status"] == "published"
    assert row["post_url"] == "https://medium.com/@op/post"
    assert row["verified"] == "verified"
    assert row["link_found"] is True and row["link_checked_at"] is not None


async def test_a_refusal_never_advances_state(
    client: httpx.AsyncClient, repo: FakeOffpageRepo,
    wire: Callable[..., None], monkeypatch: pytest.MonkeyPatch,
) -> None:
    web2_id = _parked_row(repo)
    repo.set_active_placement_spec("pl-1", {"id": "spec-1", "spec": {}})
    wire("manager")
    _public_urls_ok(monkeypatch)
    # Off-host page (a lookalike domain) - refused, and NOTHING moves.
    _stub_fetch(monkeypatch, _PAGE_WITH_LINK, "https://evil-medium.com/@op/post")
    resp = await client.post(
        f"/api/v1/offpage/web2/placements/{web2_id}/complete",
        json={"url": "https://evil-medium.com/@op/post"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["accepted"] is False and body["reason"]
    row = repo.web2_by_id[web2_id]
    assert row["status"] == "publishing" and row["post_url"] == ""
    # A refusal writes no spec bookkeeping either.
    assert getattr(repo, "_spec_successes", []) == []


async def test_a_page_missing_the_link_is_refused(
    client: httpx.AsyncClient, repo: FakeOffpageRepo,
    wire: Callable[..., None], monkeypatch: pytest.MonkeyPatch,
) -> None:
    web2_id = _parked_row(repo)
    wire("manager")
    _public_urls_ok(monkeypatch)
    _stub_fetch(monkeypatch, _PAGE_WITHOUT_LINK, "https://medium.com/@op/post")
    resp = await client.post(
        f"/api/v1/offpage/web2/placements/{web2_id}/complete",
        json={"url": "https://medium.com/@op/post"},
    )
    assert resp.status_code == 200
    assert resp.json()["accepted"] is False
    assert repo.web2_by_id[web2_id]["status"] == "publishing"


async def test_a_non_public_url_is_refused_before_any_fetch(
    client: httpx.AsyncClient, repo: FakeOffpageRepo,
    wire: Callable[..., None], monkeypatch: pytest.MonkeyPatch,
) -> None:
    web2_id = _parked_row(repo)
    wire("manager")
    monkeypatch.setattr(offpage_router, "is_public_url", lambda _url: False)

    def _explode(_url: str) -> tuple[str | None, str]:
        raise AssertionError("the fetch must never run for a non-public URL")

    from app.services import web2_placement

    monkeypatch.setattr(web2_placement, "fetch_placement_page", _explode)
    resp = await client.post(
        f"/api/v1/offpage/web2/placements/{web2_id}/complete",
        json={"url": "http://169.254.169.254/latest"},
    )
    assert resp.status_code == 200
    assert resp.json()["accepted"] is False


async def test_completion_on_a_non_parked_row_is_409(
    client: httpx.AsyncClient, repo: FakeOffpageRepo, wire: Callable[..., None],
) -> None:
    web2_id = _needs_review_row(repo)  # still needs_review, api lane
    wire("manager")
    resp = await client.post(
        f"/api/v1/offpage/web2/placements/{web2_id}/complete",
        json={"url": "https://medium.com/@op/post"},
    )
    assert resp.status_code == 409


async def test_an_accepted_completion_banks_the_active_spec_success(
    client: httpx.AsyncClient, repo: FakeOffpageRepo,
    wire: Callable[..., None], monkeypatch: pytest.MonkeyPatch,
) -> None:
    web2_id = _parked_row(repo)
    repo.set_active_placement_spec("pl-1", {"id": "spec-1", "spec": {}})
    wire("manager")
    _public_urls_ok(monkeypatch)
    _stub_fetch(monkeypatch, _PAGE_WITH_LINK, "https://medium.com/@op/post")
    resp = await client.post(
        f"/api/v1/offpage/web2/placements/{web2_id}/complete",
        json={"url": "https://medium.com/@op/post"},
    )
    assert resp.status_code == 200 and resp.json()["accepted"] is True
    assert getattr(repo, "_spec_successes", []) == ["spec-1"]


async def test_completion_is_lead_only(
    client: httpx.AsyncClient, repo: FakeOffpageRepo, wire: Callable[..., None],
) -> None:
    web2_id = _parked_row(repo)
    wire("specialist")  # staff, holds view_reports, NOT a lead
    resp = await client.post(
        f"/api/v1/offpage/web2/placements/{web2_id}/complete",
        json={"url": "https://medium.com/@op/post"},
    )
    assert resp.status_code == 403


async def test_completion_unauthenticated_is_401(
    client: httpx.AsyncClient, repo: FakeOffpageRepo,
) -> None:
    resp = await client.post(
        "/api/v1/offpage/web2/placements/w2-1/complete",
        json={"url": "https://medium.com/@op/post"},
    )
    assert resp.status_code == 401


def test_placement_verdict_defaults_are_honest() -> None:
    """An unfilled verdict must read as 'nothing verified', never as a pass."""
    verdict = PlacementVerdict(accepted=False)
    assert verdict.link.state == "unknown" and verdict.link.found is None


# --------------------------------------------------------------------------- #
# fetch_placement_page: redirects followed MANUALLY, every hop SSRF-re-validated
# BEFORE it is fetched (the EvidenceFetcher pattern; plan §8's contract).
# --------------------------------------------------------------------------- #
class _HopResp:
    def __init__(self, status_code: int, *, text: str = "", location: str = "") -> None:
        self.status_code = status_code
        self.text = text
        self.headers = {"location": location} if location else {}


def _scripted_httpx(
    monkeypatch: pytest.MonkeyPatch, pages: dict[str, _HopResp]
) -> list[str]:
    import httpx

    fetched: list[str] = []

    class _Client:
        def __init__(self, **kw: Any) -> None:
            # The contract under test: no transparent redirect following.
            assert kw.get("follow_redirects") is False

        def __enter__(self) -> _Client:
            return self

        def __exit__(self, *a: Any) -> bool:
            return False

        def get(self, url: str) -> _HopResp:
            fetched.append(url)
            return pages[url]

    monkeypatch.setattr(httpx, "Client", _Client)
    return fetched


class TestFetchPlacementPageRedirects:
    def test_a_hop_into_a_private_host_is_refused_before_it_is_fetched(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The blind SSRF: a lead pastes a public URL that 302s to the metadata
        service or an internal admin GET. The internal request must never be ISSUED —
        refusing on final_url after the fetch would be too late (side effects fire),
        and an internal hop that redirects back onto the platform host would pass the
        post-hoc check entirely."""
        import app.core.security as security
        from app.services.web2_placement import fetch_placement_page

        monkeypatch.setattr(security, "is_public_url", lambda u: "internal" not in u)
        fetched = _scripted_httpx(monkeypatch, {
            "https://pub.example/r": _HopResp(302, location="http://internal.host/admin"),
        })

        assert fetch_placement_page("https://pub.example/r") == (None, "")
        assert fetched == ["https://pub.example/r"], (
            "the private redirect target must never be requested"
        )

    def test_a_public_chain_is_followed_and_the_landing_page_returned(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import app.core.security as security
        from app.services.web2_placement import fetch_placement_page

        monkeypatch.setattr(security, "is_public_url", lambda u: True)
        fetched = _scripted_httpx(monkeypatch, {
            "https://medium.com/short": _HopResp(301, location="https://medium.com/@op/post"),
            "https://medium.com/@op/post": _HopResp(200, text="<html>the post</html>"),
        })

        html, final_url = fetch_placement_page("https://medium.com/short")
        assert html == "<html>the post</html>"
        assert final_url == "https://medium.com/@op/post"
        assert fetched == ["https://medium.com/short", "https://medium.com/@op/post"]

    def test_an_http_error_returns_none_with_the_answering_url(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import app.core.security as security
        from app.services.web2_placement import fetch_placement_page

        monkeypatch.setattr(security, "is_public_url", lambda u: True)
        _scripted_httpx(monkeypatch, {
            "https://medium.com/gone": _HopResp(404),
        })
        assert fetch_placement_page("https://medium.com/gone") == (
            None, "https://medium.com/gone",
        )

    def test_a_redirect_loop_gives_up(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import app.core.security as security
        from app.services.web2_placement import fetch_placement_page

        monkeypatch.setattr(security, "is_public_url", lambda u: True)
        _scripted_httpx(monkeypatch, {
            "https://medium.com/a": _HopResp(302, location="https://medium.com/a"),
        })
        assert fetch_placement_page("https://medium.com/a") == (None, "")
