"""Site Builder endpoints: the access gates (``run_audits`` to queue, ``view_reports``
to read) + the SSRF pre-check + the happy path.

No DB, no network, no Celery: the repo is an in-memory fake injected through
``dependency_overrides`` and the analyze enqueuer is a recorder - the Celery task is
never invoked (``.delay`` is never called).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import httpx
import pytest
from fastapi import FastAPI

from app.core.auth import CurrentUser, get_current_user
from app.modules.site_builder.repo import get_site_builder_repo
from app.modules.site_builder.router import (
    get_analyze_enqueuer,
    get_publish_enqueuer,
    get_visual_qa_enqueuer,
)

pytestmark = pytest.mark.unit

_LEAD_AND_SPECIALIST = ["owner", "admin", "manager", "specialist", "analyst"]  # all hold run_audits
_VIEWER_ONLY = ["viewer"]  # holds view_reports but NOT run_audits
_LEADS = ["owner", "admin", "manager"]
_NON_LEAD_STAFF = ["specialist", "analyst", "viewer"]


def _message(resp: httpx.Response) -> str:
    return str(resp.json()["error"]["message"])


def _user(role: str, uid: str = "00000000-0000-0000-0000-0000000000a1") -> CurrentUser:
    return CurrentUser(
        id=uid, email="sb@aios.dev", role=role, status="active",  # type: ignore[arg-type]
        name="SB", title="", avatar_color="#000", phone="", two_fa=False, client_id=None,
    )


def _job_row(**over: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "id": "job-1", "code": "SB-0001", "client_id": None, "status": "generating",
        "source_type": "template", "source_url": "", "page_type": "homepage", "industry": "",
        "editor_mode": "auto", "fidelity_mode": "balanced", "design_ir_id": None,
        "stage_detail": "", "error": None, "created_at": "", "updated_at": "",
    }
    base.update(over)
    return base


class FakeSiteBuilderRepo:
    def __init__(self) -> None:
        self.jobs_by_code: dict[str, dict[str, Any]] = {}
        self.designs_by_id: dict[str, dict[str, Any]] = {}
        self.templates_by_key: dict[str, dict[str, Any]] = {}
        self.validations: list[dict[str, Any]] = []
        self.created: list[dict[str, Any]] = []
        self._next = 1

    def create_job(self, **kwargs: Any) -> dict[str, Any]:
        self.created.append(kwargs)
        code = f"SB-{self._next:04d}"
        self._next += 1
        row = {
            "id": f"job-{self._next}", "code": code, "status": "queued",
            "stage_detail": "", "error": None, "design_ir_id": None,
            "created_at": "2026-01-01T00:00:00Z", "updated_at": "2026-01-01T00:00:00Z",
            **kwargs,
        }
        self.jobs_by_code[code] = row
        return row

    def list_jobs(self, **kwargs: Any) -> list[dict[str, Any]]:
        return list(self.jobs_by_code.values())

    def get_job_by_code(self, code: str) -> dict[str, Any] | None:
        return self.jobs_by_code.get(code)

    def get_design_ir(self, design_ir_id: str) -> dict[str, Any] | None:
        return self.designs_by_id.get(design_ir_id)

    def list_templates(self, **kwargs: Any) -> list[dict[str, Any]]:
        return list(self.templates_by_key.values())

    def get_template_by_key(self, key: str) -> dict[str, Any] | None:
        return self.templates_by_key.get(key)

    def list_visual_validations(self, job_id: str) -> list[dict[str, Any]]:
        return [v for v in self.validations if v["job_id"] == job_id]


@pytest.fixture
def repo() -> FakeSiteBuilderRepo:
    return FakeSiteBuilderRepo()


@pytest.fixture
def visual_qa_enqueued(app: FastAPI) -> list[tuple[str, str]]:
    calls: list[tuple[str, str]] = []
    app.dependency_overrides[get_visual_qa_enqueuer] = lambda: (lambda job_id, url: calls.append((job_id, url)))
    return calls


@pytest.fixture
def publish_enqueued(app: FastAPI) -> list[str]:
    calls: list[str] = []
    app.dependency_overrides[get_publish_enqueuer] = lambda: calls.append
    return calls


@pytest.fixture
def enqueued(app: FastAPI) -> list[str]:
    calls: list[str] = []
    app.dependency_overrides[get_analyze_enqueuer] = lambda: calls.append
    return calls


@pytest.fixture
def wire(
    app: FastAPI, repo: FakeSiteBuilderRepo, monkeypatch: pytest.MonkeyPatch
) -> Callable[[str], None]:
    app.dependency_overrides[get_site_builder_repo] = lambda: repo
    monkeypatch.setattr("app.core.security.validate_public_host", lambda value: value)

    def _as(role: str) -> None:
        app.dependency_overrides[get_current_user] = lambda: _user(role)

    return _as


async def test_unauthenticated_analyze_rejected(client: httpx.AsyncClient) -> None:
    resp = await client.post("/api/v1/site-builder/analyze", json={"source_type": "template"})
    assert resp.status_code == 401


async def test_unauthenticated_read_rejected(client: httpx.AsyncClient) -> None:
    assert (await client.get("/api/v1/site-builder/jobs")).status_code == 401


@pytest.mark.parametrize("role", _VIEWER_ONLY)
async def test_viewer_cannot_queue_a_build(
    client: httpx.AsyncClient, wire: Callable[[str], None], enqueued: list[str], role: str,
) -> None:
    wire(role)
    resp = await client.post(
        "/api/v1/site-builder/analyze", json={"source_type": "template", "page_type": "homepage"}
    )
    assert resp.status_code == 403, resp.text
    assert "run_audits" in _message(resp)
    assert enqueued == []


@pytest.mark.parametrize("role", _LEAD_AND_SPECIALIST)
async def test_queueing_a_template_build_succeeds_and_enqueues(
    client: httpx.AsyncClient, wire: Callable[[str], None], enqueued: list[str],
    repo: FakeSiteBuilderRepo, role: str,
) -> None:
    wire(role)
    resp = await client.post(
        "/api/v1/site-builder/analyze",
        json={"source_type": "template", "page_type": "homepage", "editorMode": "auto"},
    )
    assert resp.status_code == 202, resp.text
    body = resp.json()
    assert body["status"] == "queued"
    assert body["sourceType"] == "template"
    assert len(enqueued) == 1
    assert repo.created[0]["source_type"] == "template"


async def test_existing_site_requires_a_source_url(
    client: httpx.AsyncClient, wire: Callable[[str], None], enqueued: list[str],
) -> None:
    wire("specialist")
    resp = await client.post("/api/v1/site-builder/analyze", json={"source_type": "existing_site"})
    assert resp.status_code == 422
    assert enqueued == []


async def test_a_private_host_is_blocked_before_queueing(
    client: httpx.AsyncClient, wire: Callable[[str], None], enqueued: list[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    wire("specialist")

    def _deny(value: str) -> str:
        from app.core.security import PrivateAddressError

        raise PrivateAddressError(f"private/local address not allowed: {value}")

    monkeypatch.setattr("app.core.security.validate_public_host", _deny)
    resp = await client.post(
        "/api/v1/site-builder/analyze",
        json={"source_type": "existing_site", "sourceUrl": "http://127.0.0.1/admin"},
    )
    assert resp.status_code == 422
    assert enqueued == []


async def test_reads_require_view_reports_and_return_the_job(
    client: httpx.AsyncClient, wire: Callable[[str], None], repo: FakeSiteBuilderRepo,
) -> None:
    wire("analyst")
    repo.create_job(
        source_type="template", source_url="", page_type="homepage", industry="",
        editor_mode="auto", fidelity_mode="balanced", client_id=None, client_name="", created_by="u",
    )
    code = next(iter(repo.jobs_by_code))
    resp = await client.get(f"/api/v1/site-builder/jobs/{code}")
    assert resp.status_code == 200
    assert resp.json()["code"] == code


async def test_unknown_job_code_is_404(
    client: httpx.AsyncClient, wire: Callable[[str], None],
) -> None:
    wire("analyst")
    resp = await client.get("/api/v1/site-builder/jobs/SB-9999")
    assert resp.status_code == 404


async def test_template_gallery_lists_and_ranks_by_relevance(
    client: httpx.AsyncClient, wire: Callable[[str], None], repo: FakeSiteBuilderRepo,
) -> None:
    wire("analyst")
    repo.templates_by_key["homepage-generic"] = {
        "id": "t-1", "key": "homepage-generic", "name": "Homepage", "page_type": "homepage",
        "industry": "", "category": "business",
    }
    repo.templates_by_key["re-homepage"] = {
        "id": "t-2", "key": "re-homepage", "name": "Real Estate Homepage", "page_type": "homepage",
        "industry": "real_estate", "category": "real_estate",
    }
    resp = await client.get("/api/v1/site-builder/templates?pageType=homepage&industry=real_estate")
    assert resp.status_code == 200
    names = [t["name"] for t in resp.json()]
    assert names[0] == "Real Estate Homepage"  # exact industry+pageType match ranks first


async def test_unknown_template_key_is_404(
    client: httpx.AsyncClient, wire: Callable[[str], None],
) -> None:
    wire("analyst")
    resp = await client.get("/api/v1/site-builder/templates/not-a-real-key")
    assert resp.status_code == 404


async def test_get_template_by_key(
    client: httpx.AsyncClient, wire: Callable[[str], None], repo: FakeSiteBuilderRepo,
) -> None:
    wire("analyst")
    repo.templates_by_key["homepage-generic"] = {
        "id": "t-1", "key": "homepage-generic", "name": "Homepage", "blueprint_key": "homepage",
    }
    resp = await client.get("/api/v1/site-builder/templates/homepage-generic")
    assert resp.status_code == 200
    assert resp.json()["blueprintKey"] == "homepage"


async def test_queue_visual_qa_requires_run_audits(
    client: httpx.AsyncClient, wire: Callable[[str], None], repo: FakeSiteBuilderRepo,
    visual_qa_enqueued: list[tuple[str, str]],
) -> None:
    wire("viewer")
    repo.jobs_by_code["SB-0001"] = _job_row()
    resp = await client.post(
        "/api/v1/site-builder/jobs/SB-0001/visual-qa", json={"renderedUrl": "https://example.com"}
    )
    assert resp.status_code == 403, resp.text
    assert visual_qa_enqueued == []


async def test_queue_visual_qa_happy_path_enqueues_and_returns_the_job(
    client: httpx.AsyncClient, wire: Callable[[str], None], repo: FakeSiteBuilderRepo,
    visual_qa_enqueued: list[tuple[str, str]],
) -> None:
    wire("specialist")
    repo.jobs_by_code["SB-0001"] = _job_row()
    resp = await client.post(
        "/api/v1/site-builder/jobs/SB-0001/visual-qa", json={"renderedUrl": "https://example.com"}
    )
    assert resp.status_code == 202, resp.text
    assert visual_qa_enqueued == [("job-1", "https://example.com")]


async def test_queue_visual_qa_unknown_job_is_404(
    client: httpx.AsyncClient, wire: Callable[[str], None], visual_qa_enqueued: list[tuple[str, str]],
) -> None:
    wire("specialist")
    resp = await client.post(
        "/api/v1/site-builder/jobs/SB-9999/visual-qa", json={"renderedUrl": "https://example.com"}
    )
    assert resp.status_code == 404
    assert visual_qa_enqueued == []


async def test_list_visual_validations_for_a_job(
    client: httpx.AsyncClient, wire: Callable[[str], None], repo: FakeSiteBuilderRepo,
) -> None:
    wire("analyst")
    repo.jobs_by_code["SB-0001"] = _job_row(status="completed")
    repo.validations.append(
        {"id": "vv-1", "job_id": "job-1", "rendered_url": "https://example.com", "status": "pass",
         "diagnostics": [], "created_at": ""}
    )
    resp = await client.get("/api/v1/site-builder/jobs/SB-0001/visual-validations")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    assert body[0]["status"] == "pass"


@pytest.mark.parametrize("role", _NON_LEAD_STAFF)
async def test_publish_is_lead_only(
    client: httpx.AsyncClient, wire: Callable[[str], None], repo: FakeSiteBuilderRepo,
    publish_enqueued: list[str], role: str,
) -> None:
    wire(role)
    repo.jobs_by_code["SB-0001"] = _job_row(status="generating")
    resp = await client.post("/api/v1/site-builder/jobs/SB-0001/publish")
    assert resp.status_code == 403, resp.text
    assert publish_enqueued == []


@pytest.mark.parametrize("role", _LEADS)
async def test_publish_happy_path_enqueues(
    client: httpx.AsyncClient, wire: Callable[[str], None], repo: FakeSiteBuilderRepo,
    publish_enqueued: list[str], role: str,
) -> None:
    wire(role)
    repo.jobs_by_code["SB-0001"] = _job_row(status="generating")
    resp = await client.post("/api/v1/site-builder/jobs/SB-0001/publish")
    assert resp.status_code == 202, resp.text
    assert publish_enqueued == ["job-1"]


async def test_publish_before_a_design_is_resolved_is_a_conflict(
    client: httpx.AsyncClient, wire: Callable[[str], None], repo: FakeSiteBuilderRepo,
    publish_enqueued: list[str],
) -> None:
    wire("owner")
    repo.jobs_by_code["SB-0001"] = _job_row(status="analyzing")
    resp = await client.post("/api/v1/site-builder/jobs/SB-0001/publish")
    assert resp.status_code == 409
    assert publish_enqueued == []


async def test_publish_unknown_job_is_404(
    client: httpx.AsyncClient, wire: Callable[[str], None], publish_enqueued: list[str],
) -> None:
    wire("owner")
    resp = await client.post("/api/v1/site-builder/jobs/SB-9999/publish")
    assert resp.status_code == 404
    assert publish_enqueued == []
