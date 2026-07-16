"""P7A-9 gate: /content/jobs endpoints - shapes, RBAC, the create-and-enqueue
seam (Auto framework + schema_for resolution + client snapshot), the LEAD-only
review gate (approve->publishing + publish enqueue, edit->drafting, reject->
rejected), the limited PATCH, the stats math, and the staff-only rich retrieval.
Repo + clients + both enqueuers are faked (no Postgres, no broker). The DB-trigger
3-actor boundary itself is proven in test_content_flow.py (integration)."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from psycopg.types.json import Jsonb

from app.core.auth import CurrentUser, get_current_user
from app.db.clients_repo import get_clients_repo
from app.db.content_repo import get_content_repo
from app.routers.content import get_content_enqueuer, get_content_publish_enqueuer

pytestmark = pytest.mark.unit

_CONTENT_FIELDS = {
    "id", "client", "color", "pageType", "topic", "framework", "auto", "target",
    "status", "cost", "words", "schema", "images", "stage", "ago",
}


class FakeContentRepo:
    def __init__(self) -> None:
        self.jobs: dict[str, dict[str, Any]] = {}
        self._seq = 4200
        self.force_race = False
        self.last_filters: dict[str, Any] | None = None
        self.last_insert: dict[str, Any] | None = None

    def seed(self, **over: Any) -> dict[str, Any]:
        self._seq += 1
        code = over.get("code", f"CJ-{self._seq}")
        row: dict[str, Any] = {
            "id": f"uuid-{self._seq}", "code": code, "client_id": "cl-1",
            "client_name": "Verde Cafe", "color": "#22C55E", "page_type": "blog",
            "topic": "best brunch in portland", "framework": "PAS", "auto": True,
            "target": "WordPress", "status": "queued", "cost": 0, "words": 0,
            "schema_type": "Article", "images": 0, "stage": "Queued",
            "draft_md": "", "keyword_map": {}, "qa_score": {}, "json_ld": {},
            "created_at": datetime.now(UTC).isoformat(),
        }
        row.update(over)
        self.jobs[code] = row
        return row

    def list_jobs(
        self, *, assignee_id: str | None = None, client_id: str | None = None,
        status: str | None = None, limit: int | None = None, offset: int = 0,
    ) -> list[dict[str, Any]]:
        self.last_filters = {"client_id": client_id, "status": status, "limit": limit, "offset": offset}
        rows = list(self.jobs.values())
        if client_id is not None:
            rows = [r for r in rows if r.get("client_id") == client_id]
        if status is not None:
            rows = [r for r in rows if r.get("status") == status]
        return rows

    def get_job_by_code(self, code: str) -> dict[str, Any] | None:
        return self.jobs.get(code)

    def insert_job(self, row: dict[str, Any]) -> dict[str, Any]:
        self._seq += 1
        code = f"CJ-{self._seq}"
        self.last_insert = dict(row)
        rec = {"id": f"uuid-{self._seq}", "code": code, "cost": 0, "words": 0,
               "images": 0, "created_at": datetime.now(UTC).isoformat(), **row}
        self.jobs[code] = rec
        return rec

    def update_job_by_code(
        self, code: str, changes: dict[str, Any], expect_status: str | None = None
    ) -> dict[str, Any] | None:
        row = self.jobs.get(code)
        if row is None:
            return None
        if expect_status is not None and (self.force_race or row.get("status") != expect_status):
            return None  # optimistic-concurrency miss -> 0 rows
        row.update(changes)
        return row


class FakeClientsRepo:
    def __init__(self, exists: bool = True, *, sites: list[dict[str, Any]] | None = None) -> None:
        self.exists = exists
        self._sites = sites if sites is not None else [{"domain": "verdecafe.co"}]

    def get_client(self, client_id: str) -> dict[str, Any] | None:
        if not self.exists:
            return None
        return {
            "id": client_id, "name": "Verde Cafe", "contact_color": "#22C55E",
            "industry": "Restaurants", "since_year": 2015, "contact_name": "Ada Vega",
            "contact_role": "Owner",
        }

    def list_sites(self, client_id: str, *, limit: int | None = None, offset: int = 0) -> list[dict[str, Any]]:
        return list(self._sites)


def _user(role: str, uid: str = "u-1") -> CurrentUser:
    return CurrentUser(
        id=uid, email="op@x.com", role=role, status="active",  # type: ignore[arg-type]
        name="Op", title="", avatar_color="#000", phone="", two_fa=False,
    )


@pytest.fixture
def repo() -> FakeContentRepo:
    return FakeContentRepo()


@pytest.fixture
def enqueued() -> list[str]:
    return []


@pytest.fixture
def published() -> list[str]:
    return []


@pytest.fixture
def wire(
    app: FastAPI, repo: FakeContentRepo, enqueued: list[str], published: list[str]
) -> Callable[..., None]:
    app.dependency_overrides[get_content_repo] = lambda: repo
    app.dependency_overrides[get_content_enqueuer] = lambda: enqueued.append
    app.dependency_overrides[get_content_publish_enqueuer] = lambda: published.append

    def _as(role: str, uid: str = "u-1", *, client_exists: bool = True,
            sites: list[dict[str, Any]] | None = None) -> None:
        app.dependency_overrides[get_current_user] = lambda: _user(role, uid)
        app.dependency_overrides[get_clients_repo] = lambda: FakeClientsRepo(client_exists, sites=sites)

    return _as


# --- reads / RBAC -------------------------------------------------------------

async def test_client_forbidden_from_whole_surface(
    client: httpx.AsyncClient, repo: FakeContentRepo, wire: Callable[..., None]
) -> None:
    repo.seed(code="CJ-1")
    wire("client")  # portal client holds no view_reports
    assert (await client.get("/api/v1/content/jobs")).status_code == 403
    assert (await client.get("/api/v1/content/jobs/stats")).status_code == 403
    assert (await client.get("/api/v1/content/jobs/CJ-1")).status_code == 403
    assert (await client.get("/api/v1/content/jobs/CJ-1/draft")).status_code == 403
    resp = await client.post(
        "/api/v1/content/jobs",
        json={"client_id": "cl-1", "pageType": "blog", "topic": "x"},
    )
    assert resp.status_code == 403
    assert (await client.post("/api/v1/content/jobs/CJ-1/review", json={"action": "approve"})).status_code == 403
    assert (await client.patch("/api/v1/content/jobs/CJ-1", json={"topic": "y"})).status_code == 403


async def test_list_shape_only_content_fields(
    client: httpx.AsyncClient, repo: FakeContentRepo, wire: Callable[..., None]
) -> None:
    repo.seed(code="CJ-4192", status="needs_review", cost=32, words=1420, schema_type="Service")
    wire("viewer")
    body = (await client.get("/api/v1/content/jobs")).json()
    assert set(body[0]) == _CONTENT_FIELDS
    assert body[0]["id"] == "CJ-4192"  # the public code, never a UUID
    assert body[0]["schema"] == "Service"  # schema_type re-aliased to `schema`


async def test_list_filters_by_client_and_status(
    client: httpx.AsyncClient, repo: FakeContentRepo, wire: Callable[..., None]
) -> None:
    repo.seed(code="CJ-1", client_id="cl-1", status="queued")
    repo.seed(code="CJ-2", client_id="cl-2", status="done")
    wire("viewer")
    resp = await client.get("/api/v1/content/jobs", params={"client": "cl-1", "status": "queued"})
    assert resp.status_code == 200
    assert repo.last_filters == {"client_id": "cl-1", "status": "queued", "limit": 50, "offset": 0}
    assert [j["id"] for j in resp.json()] == ["CJ-1"]


async def test_list_default_pagination_caps(
    client: httpx.AsyncClient, repo: FakeContentRepo, wire: Callable[..., None]
) -> None:
    wire("viewer")
    await client.get("/api/v1/content/jobs")
    assert repo.last_filters is not None
    assert (repo.last_filters["limit"], repo.last_filters["offset"]) == (50, 0)
    assert (await client.get("/api/v1/content/jobs", params={"limit": 0})).status_code == 422
    assert (await client.get("/api/v1/content/jobs", params={"limit": 201})).status_code == 422


async def test_get_single_and_404(
    client: httpx.AsyncClient, repo: FakeContentRepo, wire: Callable[..., None]
) -> None:
    repo.seed(code="CJ-9")
    wire("viewer")
    assert (await client.get("/api/v1/content/jobs/CJ-9")).status_code == 200
    assert (await client.get("/api/v1/content/jobs/CJ-nope")).status_code == 404


# --- stats --------------------------------------------------------------------

async def test_stats_math(
    client: httpx.AsyncClient, repo: FakeContentRepo, wire: Callable[..., None]
) -> None:
    repo.seed(status="queued", cost=10)
    repo.seed(status="drafting", cost=20)
    repo.seed(status="needs_review", cost=30)  # awaiting + in-pipeline
    repo.seed(status="publishing", cost=0)     # in-pipeline, unpriced -> not in avg
    repo.seed(status="done", cost=40)          # published this month
    # a done job from a previous month must NOT count toward publishedThisMonth
    old = (datetime.now(UTC) - timedelta(days=60)).isoformat()
    repo.seed(status="done", cost=60, created_at=old)
    wire("viewer")
    body = (await client.get("/api/v1/content/jobs/stats")).json()
    assert set(body) == {"inPipeline", "awaitingReview", "publishedThisMonth", "avgCost"}
    assert body["inPipeline"] == 4       # queued/drafting/needs_review/publishing
    assert body["awaitingReview"] == 1
    assert body["publishedThisMonth"] == 1  # the 60-day-old done excluded
    # avg of priced (>0) jobs: (10+20+30+40+60)/5 = 32.0
    assert body["avgCost"] == 32.0


async def test_stats_empty_ledger(
    client: httpx.AsyncClient, wire: Callable[..., None]
) -> None:
    wire("viewer")
    body = (await client.get("/api/v1/content/jobs/stats")).json()
    assert body == {"inPipeline": 0, "awaitingReview": 0, "publishedThisMonth": 0, "avgCost": 0.0}


# --- rich retrieval (staff-only) ----------------------------------------------

async def test_rich_retrieval_returns_server_columns(
    client: httpx.AsyncClient, repo: FakeContentRepo, wire: Callable[..., None]
) -> None:
    repo.seed(code="CJ-7", draft_md="# Title\n\nBody", keyword_map={"primary": "brunch"},
              qa_score={"passed": True}, json_ld={"@graph": [1]})
    wire("specialist")
    assert (await client.get("/api/v1/content/jobs/CJ-7/draft")).json()["draft"] == "# Title\n\nBody"
    assert (await client.get("/api/v1/content/jobs/CJ-7/keywords")).json()["keywords"] == {"primary": "brunch"}
    assert (await client.get("/api/v1/content/jobs/CJ-7/qa")).json()["qa"] == {"passed": True}
    assert (await client.get("/api/v1/content/jobs/CJ-7/schema")).json()["schema"] == {"@graph": [1]}


async def test_rich_retrieval_unknown_column_404(
    client: httpx.AsyncClient, repo: FakeContentRepo, wire: Callable[..., None]
) -> None:
    repo.seed(code="CJ-7")
    wire("specialist")
    assert (await client.get("/api/v1/content/jobs/CJ-7/secrets")).status_code == 404


async def test_rich_retrieval_client_forbidden(
    client: httpx.AsyncClient, repo: FakeContentRepo, wire: Callable[..., None]
) -> None:
    repo.seed(code="CJ-7", draft_md="secret draft")
    wire("client")
    assert (await client.get("/api/v1/content/jobs/CJ-7/draft")).status_code == 403


# --- create -------------------------------------------------------------------

async def test_create_requires_publish_content(
    client: httpx.AsyncClient, wire: Callable[..., None]
) -> None:
    wire("analyst")  # analyst holds view_reports + run_audits but NOT publish_content
    resp = await client.post(
        "/api/v1/content/jobs",
        json={"client_id": "cl-1", "pageType": "service", "topic": "x"},
    )
    assert resp.status_code == 403


async def test_create_resolves_auto_framework_and_schema(
    client: httpx.AsyncClient, repo: FakeContentRepo, enqueued: list[str], wire: Callable[..., None]
) -> None:
    wire("manager")
    resp = await client.post(
        "/api/v1/content/jobs",
        json={"client_id": "cl-1", "pageType": "service", "topic": "Emergency dental care", "framework": "Auto"},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert set(body) == _CONTENT_FIELDS
    assert body["status"] == "queued"
    assert body["framework"] == "AIDA"   # service -> AIDA (auto_framework)
    assert body["auto"] is True
    assert body["schema"] == "Service"   # service -> Service (schema_for)
    assert body["client"] == "Verde Cafe"
    assert body["color"] == "#22C55E"    # snapshotted from the client contact_color
    assert body["target"] == "WordPress"
    # exactly one pipeline job enqueued, keyed by the new PUBLIC code
    assert enqueued == [body["id"]]


async def test_create_explicit_framework_sets_auto_false(
    client: httpx.AsyncClient, wire: Callable[..., None]
) -> None:
    wire("manager")
    resp = await client.post(
        "/api/v1/content/jobs",
        json={"client_id": "cl-1", "pageType": "blog", "topic": "x", "framework": "PASTOR"},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["framework"] == "PASTOR"
    assert body["auto"] is False


async def test_create_seeds_source_pack_never_leaks_client_id(
    client: httpx.AsyncClient, repo: FakeContentRepo, wire: Callable[..., None]
) -> None:
    wire("manager")
    resp = await client.post(
        "/api/v1/content/jobs",
        json={"client_id": "cl-1", "pageType": "local", "topic": "AC repair", "target": "WordPress"},
    )
    assert resp.status_code == 201
    # client_id is stored on the row but NEVER present in the response body.
    assert "client_id" not in resp.json()
    # source_pack was seeded (jsonb-wrapped) with client facts + the WP site config.
    assert repo.last_insert is not None
    packed = repo.last_insert["source_pack"]
    assert isinstance(packed, Jsonb)
    pack = packed.obj
    assert pack["client_name"] == "Verde Cafe"
    assert pack["facts"]["industry"] == "Restaurants"
    assert pack["facts"]["founded"] == "2015"
    assert pack["wp_site_url"] == "https://verdecafe.co"


async def test_create_pdf_target_omits_wp_config(
    client: httpx.AsyncClient, repo: FakeContentRepo, wire: Callable[..., None]
) -> None:
    wire("manager")
    resp = await client.post(
        "/api/v1/content/jobs",
        json={"client_id": "cl-1", "pageType": "blog", "topic": "x", "target": "PDF/Markdown"},
    )
    assert resp.status_code == 201
    assert repo.last_insert is not None
    pack = repo.last_insert["source_pack"].obj
    assert "wp_site_url" not in pack  # not a WordPress target


async def test_create_unknown_client_404(
    client: httpx.AsyncClient, enqueued: list[str], wire: Callable[..., None]
) -> None:
    wire("manager", client_exists=False)
    resp = await client.post(
        "/api/v1/content/jobs",
        json={"client_id": "nope", "pageType": "blog", "topic": "x"},
    )
    assert resp.status_code == 404
    assert enqueued == []  # never enqueued


# --- review gate (LEAD-only) --------------------------------------------------

async def test_review_role_gated_for_specialist(
    client: httpx.AsyncClient, repo: FakeContentRepo, wire: Callable[..., None]
) -> None:
    repo.seed(code="CJ-1", status="needs_review")
    wire("specialist")  # holds publish_content but is NOT a lead
    resp = await client.post("/api/v1/content/jobs/CJ-1/review", json={"action": "approve"})
    assert resp.status_code == 403


async def test_review_approve_to_publishing_and_enqueues_publish(
    client: httpx.AsyncClient, repo: FakeContentRepo, published: list[str], wire: Callable[..., None]
) -> None:
    repo.seed(code="CJ-1", status="needs_review")
    wire("manager")
    resp = await client.post("/api/v1/content/jobs/CJ-1/review", json={"action": "approve"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "publishing"
    assert published == ["CJ-1"]  # the publish worker was enqueued


async def test_review_edit_to_drafting_no_publish(
    client: httpx.AsyncClient, repo: FakeContentRepo, published: list[str], wire: Callable[..., None]
) -> None:
    repo.seed(code="CJ-1", status="needs_review")
    wire("admin")
    resp = await client.post("/api/v1/content/jobs/CJ-1/review", json={"action": "edit"})
    assert resp.json()["status"] == "drafting"
    assert published == []


async def test_review_reject_to_rejected_no_publish(
    client: httpx.AsyncClient, repo: FakeContentRepo, published: list[str], wire: Callable[..., None]
) -> None:
    repo.seed(code="CJ-1", status="needs_review")
    wire("owner")
    resp = await client.post("/api/v1/content/jobs/CJ-1/review", json={"action": "reject"})
    assert resp.json()["status"] == "rejected"
    assert published == []


async def test_review_not_in_needs_review_is_409(
    client: httpx.AsyncClient, repo: FakeContentRepo, wire: Callable[..., None]
) -> None:
    repo.seed(code="CJ-1", status="drafting")
    wire("manager")
    resp = await client.post("/api/v1/content/jobs/CJ-1/review", json={"action": "approve"})
    assert resp.status_code == 409


async def test_review_optimistic_conflict_409(
    client: httpx.AsyncClient, repo: FakeContentRepo, published: list[str], wire: Callable[..., None]
) -> None:
    repo.seed(code="CJ-1", status="needs_review")
    repo.force_race = True  # a racing transition already moved the row
    wire("manager")
    resp = await client.post("/api/v1/content/jobs/CJ-1/review", json={"action": "approve"})
    assert resp.status_code == 409
    assert published == []  # never enqueued on a lost race


async def test_review_missing_job_404(
    client: httpx.AsyncClient, wire: Callable[..., None]
) -> None:
    wire("manager")
    assert (await client.post("/api/v1/content/jobs/CJ-nope/review", json={"action": "approve"})).status_code == 404


# --- patch (LEAD-only) --------------------------------------------------------

async def test_patch_role_gated_for_specialist(
    client: httpx.AsyncClient, repo: FakeContentRepo, wire: Callable[..., None]
) -> None:
    repo.seed(code="CJ-1")
    wire("specialist")
    resp = await client.patch("/api/v1/content/jobs/CJ-1", json={"topic": "new topic"})
    assert resp.status_code == 403


async def test_patch_edits_topic(
    client: httpx.AsyncClient, repo: FakeContentRepo, wire: Callable[..., None]
) -> None:
    repo.seed(code="CJ-1", topic="old")
    wire("manager")
    resp = await client.patch("/api/v1/content/jobs/CJ-1", json={"topic": "new topic"})
    assert resp.status_code == 200
    assert resp.json()["topic"] == "new topic"


async def test_patch_empty_is_noop(
    client: httpx.AsyncClient, repo: FakeContentRepo, wire: Callable[..., None]
) -> None:
    repo.seed(code="CJ-1", topic="unchanged")
    wire("manager")
    resp = await client.patch("/api/v1/content/jobs/CJ-1", json={})
    assert resp.status_code == 200
    assert resp.json()["topic"] == "unchanged"


async def test_patch_missing_job_404(
    client: httpx.AsyncClient, wire: Callable[..., None]
) -> None:
    wire("manager")
    assert (await client.patch("/api/v1/content/jobs/CJ-nope", json={"topic": "x"})).status_code == 404
