"""P3-4 gate: /audits endpoints - shapes, RBAC, SSRF guard, Free-tier gating,
enqueue, list/get/stats. Repo + enqueuer are faked (no Supabase, no broker)."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from fastapi import FastAPI

from app.core.auth import CurrentUser, get_current_user
from app.db.audits_repo import get_audits_repo
from app.db.clients_repo import get_clients_repo
from app.routers.audits import get_audit_enqueuer, get_paid_audit_gate
from app.services.cost_gate import GateDecision

pytestmark = pytest.mark.unit

# A public IP literal: passes the SSRF guard with NO DNS lookup (offline-safe).
_PUBLIC_URL = "http://93.184.216.34"


class FakeAuditsRepo:
    def __init__(self) -> None:
        self.rows: dict[str, dict[str, Any]] = {}
        self._seq = 0
        self.last_page: tuple[int | None, int] | None = None

    def seed(self, **over: Any) -> dict[str, Any]:
        self._seq += 1
        aid = over.get("id", f"aud-{self._seq}")
        row: dict[str, Any] = {
            "id": aid,
            "client_name": "Verde Cafe",
            "url": "verdecafe.co",
            "types": ["technical"],
            "tier": "free",
            "status": "done",
            "score": 74,
            "runtime_seconds": 288,
            "pdf_path": "x.pdf",
            "json_path": "x.json",
            "created_at": datetime.now(UTC).isoformat(),
        }
        row.update(over)
        self.rows[aid] = row
        return row

    def list_audits(self, *, limit: int | None = None, offset: int = 0) -> list[dict[str, Any]]:
        self.last_page = (limit, offset)
        return list(self.rows.values())

    def get_audit(self, audit_id: str) -> dict[str, Any] | None:
        return self.rows.get(audit_id)

    def insert_audit(self, row: dict[str, Any]) -> dict[str, Any]:
        self._seq += 1
        aid = f"aud-{self._seq}"
        rec = {"id": aid, "created_at": datetime.now(UTC).isoformat(), "score": None,
               "runtime_seconds": None, "pdf_path": None, "json_path": None, **row}
        self.rows[aid] = rec
        return rec

    def set_visibility(self, audit_id: str, *, visible: bool) -> dict[str, Any] | None:
        # Mirrors the real repo: an RLS refusal matches zero rows rather than
        # raising, so an unknown id and a refused UPDATE are indistinguishable
        # here on purpose - both must surface as a 404, never a silent success.
        row = self.rows.get(audit_id)
        if row is None:
            return None
        row["visible_to_client"] = visible
        return row


class FakeClientsRepo:
    def __init__(self, exists: bool = True) -> None:
        self.exists = exists

    def get_client(self, client_id: str) -> dict[str, Any] | None:
        return {"id": client_id, "name": "Verde Cafe"} if self.exists else None


def _user(role: str) -> CurrentUser:
    return CurrentUser(
        id="u-1", email="op@x.com", role=role, status="active",  # type: ignore[arg-type]
        name="Op", title="", avatar_color="#000", phone="", two_fa=False,
    )


@pytest.fixture
def repo() -> FakeAuditsRepo:
    return FakeAuditsRepo()


@pytest.fixture
def enqueued() -> list[str]:
    return []


@pytest.fixture
def wire(
    app: FastAPI, repo: FakeAuditsRepo, enqueued: list[str]
) -> Callable[..., None]:
    app.dependency_overrides[get_audits_repo] = lambda: repo
    app.dependency_overrides[get_audit_enqueuer] = lambda: enqueued.append
    # Default: the paid-audit cost gate ALLOWS the run. Without this override the
    # real gate would hit the DB; a specific test overrides it to a block below.
    app.dependency_overrides[get_paid_audit_gate] = lambda: (
        lambda client_id, client_name, cost: GateDecision("call", cost=cost)
    )

    def _as(role: str, *, client_exists: bool = True) -> None:
        app.dependency_overrides[get_current_user] = lambda: _user(role)
        app.dependency_overrides[get_clients_repo] = lambda: FakeClientsRepo(client_exists)

    return _as


async def test_create_enqueues_queued_row(
    client: httpx.AsyncClient, repo: FakeAuditsRepo, enqueued: list[str], wire: Callable[..., None]
) -> None:
    wire("manager")
    resp = await client.post(
        "/api/v1/audits",
        json={"client_id": "cl-1", "url": _PUBLIC_URL, "tier": "Free", "types": ["technical", "onpage"]},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert set(body) == {
        "id", "client", "url", "types", "tier", "status", "score", "runtime",
        "when", "pdf", "json",
        # The depth axis (migration 0084): what breadth was asked for, and what
        # the pre-flight gate was told it would cost, beside what it actually cost.
        "depth", "maxPages", "estimatedCost", "cost",
        # Whether the run is shared into the client's portal, so exposure is
        # visible wherever an audit is listed rather than write-once and unseen.
        "visibleToClient",
    }
    assert body["visibleToClient"] is False  # internal until someone shares it
    assert body["depth"] == "free"  # Free tier pins the depth
    assert body["maxPages"] == 15
    assert body["estimatedCost"] == 0.0  # a free run fires no paid provider
    assert body["cost"] is None  # queued: nothing spent YET, which is not $0.00
    # Always empty now: the audit-type picker is gone, every run is the full
    # audit, and a client that still sends `types` has it ignored. Historical rows
    # keep whatever they were created with.
    assert body["types"] == []
    assert body["status"] == "queued"
    assert body["tier"] == "Free"
    assert body["client"] == "Verde Cafe"
    assert body["score"] is None
    assert body["runtime"] == "—"
    assert body["pdf"] is False and body["json"] is False
    # exactly one job enqueued, for the new row id
    assert enqueued == [body["id"]]


async def test_a_free_tier_request_cannot_buy_paid_depth(
    client: httpx.AsyncClient, enqueued: list[str], wire: Callable[..., None]
) -> None:
    """The spend bypass this closes, restated on the axis that replaced it.

    Under the old audit-type picker an EMPTY selection meant "the full
    comprehensive run", and `paid_types()` returned [] for it - so a request of
    `{"tier": "Free", "types": []}` skipped the paid gate, stored tier=free, made
    the worker skip its re-check for the same reason, and then called the engine
    with `comprehensive=True`, which forced `mode="paid"` regardless. The
    platform's single largest spend ran with the cost dial, the client budget cap
    AND the global spend halt all bypassed.

    Keyed on DEPTH the shape cannot recur: the same value that names the request
    also picks the engine mode, so there is no value that means "free to ask for
    and paid to run". Refused rather than silently downgraded - a caller told
    nothing would report the wrong thing.
    """
    wire("manager")
    resp = await client.post(
        "/api/v1/audits",
        json={"client_id": "cl-1", "url": _PUBLIC_URL, "tier": "Free", "depth": "deep"},
    )
    assert resp.status_code == 400
    assert "Paid tier" in resp.json()["error"]["message"]
    assert enqueued == []  # and above all: nothing ran


async def test_a_free_tier_request_with_no_depth_runs_free(
    client: httpx.AsyncClient, enqueued: list[str], wire: Callable[..., None]
) -> None:
    # No depth named is not a loophole: it resolves to `free` for a Free tier, and
    # `free` depth runs `--mode free`, which the engine enforces by clearing every
    # provider after parsing.
    wire("manager")
    resp = await client.post(
        "/api/v1/audits",
        json={"client_id": "cl-1", "url": _PUBLIC_URL, "tier": "Free"},
    )
    assert resp.status_code == 201
    assert resp.json()["depth"] == "free"
    assert resp.json()["estimatedCost"] == 0.0
    assert enqueued  # this one legitimately runs


async def test_create_requires_run_audits(
    client: httpx.AsyncClient, wire: Callable[..., None]
) -> None:
    wire("viewer")  # viewer lacks run_audits
    resp = await client.post("/api/v1/audits", json={"client_id": "cl-1", "url": _PUBLIC_URL})
    assert resp.status_code == 403


async def test_create_rejects_private_url(
    client: httpx.AsyncClient, enqueued: list[str], wire: Callable[..., None]
) -> None:
    wire("analyst")
    resp = await client.post(
        "/api/v1/audits",
        json={"client_id": "cl-1", "url": "http://127.0.0.1/admin"},
    )
    assert resp.status_code == 400
    assert "public address" in resp.json()["error"]["message"]
    assert enqueued == []  # never enqueued


async def test_free_tier_rejects_paid_depth(
    client: httpx.AsyncClient, wire: Callable[..., None]
) -> None:
    wire("manager")
    resp = await client.post(
        "/api/v1/audits",
        json={"client_id": "cl-1", "url": _PUBLIC_URL, "tier": "Free", "depth": "standard"},
    )
    assert resp.status_code == 400
    assert "Paid tier" in resp.json()["error"]["message"]


async def test_paid_tier_allows_paid_types(
    client: httpx.AsyncClient, wire: Callable[..., None]
) -> None:
    wire("manager")
    resp = await client.post(
        "/api/v1/audits",
        json={"client_id": "cl-1", "url": _PUBLIC_URL, "tier": "Paid", "types": ["technical", "local", "geo"]},
    )
    assert resp.status_code == 201
    assert resp.json()["tier"] == "Paid"


async def test_paid_audit_over_budget_is_rejected_at_enqueue(
    app: FastAPI, client: httpx.AsyncClient, enqueued: list[str], wire: Callable[..., None]
) -> None:
    # A cost-gate block on a PAID audit must reject at enqueue (402) and NEVER
    # queue the job - the operator learns immediately, no worker run, no spend.
    wire("manager")
    app.dependency_overrides[get_paid_audit_gate] = lambda: (
        lambda client_id, client_name, cost: GateDecision(
            "blocked_cap", reason="client budget cap reached"
        )
    )
    resp = await client.post(
        "/api/v1/audits",
        json={"client_id": "cl-1", "url": _PUBLIC_URL, "tier": "Paid", "types": ["technical"]},
    )
    assert resp.status_code == 402
    assert "cost controls" in resp.json()["error"]["message"]
    assert enqueued == []  # never enqueued


async def test_free_audit_is_not_cost_gated_at_enqueue(
    app: FastAPI, client: httpx.AsyncClient, enqueued: list[str], wire: Callable[..., None]
) -> None:
    # Even if the gate would block, a Free audit is never pre-checked (it makes no
    # paid spend): it enqueues normally.
    wire("manager")
    app.dependency_overrides[get_paid_audit_gate] = lambda: (
        lambda client_id, client_name, cost: GateDecision("blocked_cap", reason="ignored on free")
    )
    resp = await client.post(
        "/api/v1/audits",
        json={"client_id": "cl-1", "url": _PUBLIC_URL, "tier": "Free", "types": ["technical"]},
    )
    assert resp.status_code == 201
    assert enqueued == [resp.json()["id"]]


async def test_create_unknown_client_404(
    client: httpx.AsyncClient, wire: Callable[..., None]
) -> None:
    wire("manager", client_exists=False)
    resp = await client.post(
        "/api/v1/audits",
        json={"client_id": "nope", "url": _PUBLIC_URL, "types": ["technical"]},
    )
    assert resp.status_code == 404


async def test_list_and_get_shape(
    client: httpx.AsyncClient, repo: FakeAuditsRepo, wire: Callable[..., None]
) -> None:
    row = repo.seed(tier="paid", status="done", score=91)
    wire("viewer")
    listed = await client.get("/api/v1/audits")
    assert listed.status_code == 200
    assert listed.json()[0]["tier"] == "Paid"
    got = await client.get(f"/api/v1/audits/{row['id']}")
    assert got.status_code == 200
    assert got.json()["score"] == 91
    missing = await client.get("/api/v1/audits/nope")
    assert missing.status_code == 404


async def test_stats_shape(
    client: httpx.AsyncClient, repo: FakeAuditsRepo, wire: Callable[..., None]
) -> None:
    repo.seed(status="done", score=80, runtime_seconds=360)
    repo.seed(status="done", score=90, runtime_seconds=600)
    repo.seed(status="running", score=None, runtime_seconds=None)
    # an old run (previous month) must not count toward thisMonth
    old = (datetime.now(UTC) - timedelta(days=60)).isoformat()
    repo.seed(status="done", score=50, runtime_seconds=120, created_at=old)
    wire("viewer")
    resp = await client.get("/api/v1/audits/stats")
    assert resp.status_code == 200
    body = resp.json()
    # The four original keys are a PUBLISHED CONTRACT: `.claude/skills/aios-audit`
    # documents and reads them. They stay even though the operator dashboard now
    # renders `lifetime` and `avgCostUsd` instead of avgScore/turnaroundMin.
    assert {"thisMonth", "avgScore", "runningNow", "turnaroundMin"} <= set(body)
    assert set(body) == {
        "thisMonth", "avgScore", "runningNow", "turnaroundMin", "lifetime", "avgCostUsd",
    }
    assert body["runningNow"] == 1
    assert body["thisMonth"] == 3  # the 60-day-old run excluded
    assert body["lifetime"] == 4   # every run ever, not just this month


async def test_stats_average_cost_counts_only_completed_runs(
    client: httpx.AsyncClient, repo: FakeAuditsRepo, wire: Callable[..., None]
) -> None:
    """A queued row's `cost` column defaults to 0. Averaging that in would report
    work that has not happened yet as work that was free, and drag the mean down
    every time an operator queues a run."""
    repo.seed(status="done", score=80, runtime_seconds=60, cost=1.0)
    repo.seed(status="done", score=80, runtime_seconds=60, cost=0.5)
    repo.seed(status="queued", score=None, runtime_seconds=None, cost=0)
    wire("viewer")
    body = (await client.get("/api/v1/audits/stats")).json()
    assert body["avgCostUsd"] == 0.75
    assert body["lifetime"] == 3


async def test_stats_average_cost_is_zero_when_nothing_completed(
    client: httpx.AsyncClient, repo: FakeAuditsRepo, wire: Callable[..., None]
) -> None:
    repo.seed(status="queued", score=None, runtime_seconds=None)
    wire("viewer")
    body = (await client.get("/api/v1/audits/stats")).json()
    assert body["avgCostUsd"] == 0.0


async def test_list_audits_default_pagination(
    client: httpx.AsyncClient, repo: FakeAuditsRepo, wire: Callable[..., None]
) -> None:
    wire("viewer")
    resp = await client.get("/api/v1/audits")
    assert resp.status_code == 200
    assert repo.last_page == (50, 0)  # hard-cap defaults


async def test_list_audits_explicit_pagination(
    client: httpx.AsyncClient, repo: FakeAuditsRepo, wire: Callable[..., None]
) -> None:
    wire("viewer")
    resp = await client.get("/api/v1/audits", params={"limit": 5, "offset": 10})
    assert resp.status_code == 200
    assert repo.last_page == (5, 10)


async def test_list_audits_cap_enforcement(
    client: httpx.AsyncClient, wire: Callable[..., None]
) -> None:
    wire("viewer")
    assert (await client.get("/api/v1/audits", params={"limit": 0})).status_code == 422
    assert (await client.get("/api/v1/audits", params={"limit": 201})).status_code == 422


async def test_an_audit_is_internal_unless_the_operator_shares_it(
    client: httpx.AsyncClient, repo: FakeAuditsRepo, wire: Callable[..., None]
) -> None:
    """Before 0096 there was no such decision: `portal_audits` filtered on
    `client_id` alone, so every client-linked audit was visible in that client's
    portal the moment it was created - including queued and failed runs nobody
    had reviewed. A disclosure control must default to NOT disclosing."""
    wire("manager")
    resp = await client.post(
        "/api/v1/audits",
        json={"client_id": "c-1", "url": _PUBLIC_URL, "tier": "Free",
              "types": ["technical"]},
    )
    assert resp.status_code == 201
    row = next(iter(repo.rows.values()))
    assert row["visible_to_client"] is False


async def test_the_operator_can_share_an_audit_at_creation(
    client: httpx.AsyncClient, repo: FakeAuditsRepo, wire: Callable[..., None]
) -> None:
    wire("manager")
    resp = await client.post(
        "/api/v1/audits",
        json={
            "client_id": "c-1", "url": _PUBLIC_URL, "tier": "Free",
            "types": ["technical"], "visible_to_client": True,
        },
    )
    assert resp.status_code == 201
    row = next(iter(repo.rows.values()))
    assert row["visible_to_client"] is True


# --------------------------------------------------------------------------
# PATCH /audits/{id}/visibility
#
# Sharing was write-once: settable at creation, absent from every response, and
# impossible to change. An operator could expose a client's audit and then had
# no way to see that they had, or to undo it. Migration 0096 additionally
# backfilled `true` for every pre-existing client-linked audit, so the exposed
# set is historical rather than chosen - which is only reviewable once the flag
# is readable and reversible.
# --------------------------------------------------------------------------

async def test_visibility_is_readable_on_every_audit_response(
    client: httpx.AsyncClient, repo: FakeAuditsRepo, wire: Callable[..., None]
) -> None:
    wire("manager")
    repo.seed(id="aud-vis", visible_to_client=True)
    resp = await client.get("/api/v1/audits/aud-vis")
    assert resp.status_code == 200
    assert resp.json()["visibleToClient"] is True


async def test_an_operator_can_revoke_a_shared_audit(
    client: httpx.AsyncClient, repo: FakeAuditsRepo, wire: Callable[..., None]
) -> None:
    wire("manager")
    repo.seed(id="aud-1", visible_to_client=True)
    resp = await client.patch(
        "/api/v1/audits/aud-1/visibility", json={"visible_to_client": False}
    )
    assert resp.status_code == 200
    assert resp.json()["visibleToClient"] is False
    assert repo.rows["aud-1"]["visible_to_client"] is False


async def test_an_operator_can_share_an_existing_audit(
    client: httpx.AsyncClient, repo: FakeAuditsRepo, wire: Callable[..., None]
) -> None:
    wire("manager")
    repo.seed(id="aud-2", visible_to_client=False)
    resp = await client.patch(
        "/api/v1/audits/aud-2/visibility", json={"visible_to_client": True}
    )
    assert resp.status_code == 200
    assert repo.rows["aud-2"]["visible_to_client"] is True


async def test_an_update_that_matched_no_row_is_a_404_not_a_silent_success(
    client: httpx.AsyncClient, repo: FakeAuditsRepo, wire: Callable[..., None]
) -> None:
    """The load-bearing case. `audits_modify` is a `for all` policy scoped to
    operator roles, and an RLS refusal does NOT raise - it matches zero rows. If
    the route returned 200 on an empty result, a refused write would be reported
    to the operator as a successful share."""
    wire("manager")
    resp = await client.patch(
        "/api/v1/audits/does-not-exist/visibility", json={"visible_to_client": True}
    )
    assert resp.status_code == 404


async def test_a_viewer_cannot_change_who_sees_an_audit(
    client: httpx.AsyncClient, repo: FakeAuditsRepo, wire: Callable[..., None]
) -> None:
    """Putting a document in front of a client is an outward-facing act, so it
    is gated on `run_audits` - which is exactly the role set the `audits_modify`
    policy admits. A viewer is refused twice: here, and by RLS underneath."""
    wire("viewer")
    repo.seed(id="aud-3", visible_to_client=False)
    resp = await client.patch(
        "/api/v1/audits/aud-3/visibility", json={"visible_to_client": True}
    )
    assert resp.status_code == 403
    assert repo.rows["aud-3"]["visible_to_client"] is False


async def test_a_portal_client_cannot_reach_the_sharing_control(
    client: httpx.AsyncClient, repo: FakeAuditsRepo, wire: Callable[..., None]
) -> None:
    wire("client")
    repo.seed(id="aud-4", visible_to_client=False)
    resp = await client.patch(
        "/api/v1/audits/aud-4/visibility", json={"visible_to_client": True}
    )
    assert resp.status_code == 403


async def test_the_route_cannot_be_used_to_edit_anything_else(
    client: httpx.AsyncClient, repo: FakeAuditsRepo, wire: Callable[..., None]
) -> None:
    """A wider body would let an operator rewrite a completed run's url or
    quoted cost through a route reviewed as a sharing control."""
    wire("manager")
    repo.seed(id="aud-5", url="verdecafe.co", visible_to_client=False)
    resp = await client.patch(
        "/api/v1/audits/aud-5/visibility",
        json={"visible_to_client": True, "url": "attacker.example", "cost": 999},
    )
    assert resp.status_code == 200
    assert repo.rows["aud-5"]["url"] == "verdecafe.co"
    assert repo.rows["aud-5"].get("cost") != 999
