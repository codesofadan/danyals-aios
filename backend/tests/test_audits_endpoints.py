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
    }
    assert body["depth"] == "free"  # Free tier pins the depth
    assert body["maxPages"] == 15
    assert body["estimatedCost"] == 0.0  # a free run fires no paid provider
    assert body["cost"] is None  # queued: nothing spent YET, which is not $0.00
    assert body["types"] == ["technical", "onpage"]
    assert body["status"] == "queued"
    assert body["tier"] == "Free"
    assert body["client"] == "Verde Cafe"
    assert body["score"] is None
    assert body["runtime"] == "—"
    assert body["pdf"] is False and body["json"] is False
    # exactly one job enqueued, for the new row id
    assert enqueued == [body["id"]]


async def test_create_empty_types_is_full_audit(
    client: httpx.AsyncClient, repo: FakeAuditsRepo, enqueued: list[str], wire: Callable[..., None]
) -> None:
    # No types selected = a FULL audit (every type). It must be accepted (not a 422),
    # persist an empty selection, and enqueue. It runs as PAID: an empty selection is
    # the comprehensive pipeline, so every paid provider and all 21 agents fire.
    wire("manager")
    resp = await client.post(
        "/api/v1/audits",
        json={"client_id": "cl-1", "url": _PUBLIC_URL, "tier": "Paid", "types": []},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["types"] == []
    assert enqueued == [body["id"]]
    assert repo.rows[body["id"]]["types"] == []


async def test_empty_types_on_the_free_tier_is_refused_not_run_ungated(
    client: httpx.AsyncClient, enqueued: list[str], wire: Callable[..., None]
) -> None:
    """The regression test for a measured spend-gate bypass.

    This test previously asserted the OPPOSITE - that `{"tier": "Free", "types":
    []}` returns 201 - with the note *"even on the Free tier (paid_types is empty,
    so the Free-tier paid gate never trips)"*. That reasoning was correct about
    `paid_types()` and wrong about the run: an empty selection is not "no paid
    dimensions", it is EVERY dimension.

    Traced end to end, at the commit that introduced this test:

      * the dashboard derived `tier` as `types.some(isPaid)`, which is `false` for
        an empty array, so the full audit was submitted as Free;
      * this endpoint's cost gate is `if body.tier == "Paid"`, so it was skipped;
      * the row persisted `tier=free`, and `execute_audit`'s re-check is
        `if tier == "paid"`, so that was skipped too;
      * `execute_audit` then called the engine with `comprehensive=True`, and
        `run_audit` computes `mode = "paid" if (tier == "paid" or comprehensive)`
        - so the stored tier never reached the engine at all, and `build_argv`
        emitted `--mode paid --serper --places --citations --agents on
        --ai-narrative on`.

    Net: the platform's single largest spend ran with the cost dial, the client
    budget cap AND the global spend halt all bypassed. The cost was still logged
    afterwards (the commit hardcodes `mode="paid"`), so this was ungated spend
    rather than invisible spend - which is precisely what a pre-flight gate exists
    to prevent.

    Refused rather than silently upgraded to Paid, because a silent upgrade is the
    WU-7 defect mirrored: there the caller asked for free and got every provider;
    here it would charge a client budget against a request that said Free.
    """
    wire("manager")
    resp = await client.post(
        "/api/v1/audits",
        json={"client_id": "cl-1", "url": _PUBLIC_URL, "tier": "Free", "types": []},
    )
    assert resp.status_code == 400
    assert "full comprehensive run" in resp.json()["error"]["message"]
    assert enqueued == []  # and above all: nothing ran


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
        # An explicit free-only selection: this test is about the SSRF guard, and
        # an empty selection would now be refused earlier as an ungated full run.
        json={"client_id": "cl-1", "url": "http://127.0.0.1/admin", "types": ["technical"]},
    )
    assert resp.status_code == 400
    assert "public address" in resp.json()["error"]["message"]
    assert enqueued == []  # never enqueued


async def test_free_tier_rejects_paid_types(
    client: httpx.AsyncClient, wire: Callable[..., None]
) -> None:
    wire("manager")
    resp = await client.post(
        "/api/v1/audits",
        json={"client_id": "cl-1", "url": _PUBLIC_URL, "tier": "Free", "types": ["technical", "local"]},
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
