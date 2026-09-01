"""§3 — a free-audit lead is reachable by its token, not by its position in a list.

THE DEFECT. The lead detail page found its lead by scanning the paginated funnel
inbox (newest 50). A link to any lead older than that resolved to "not found", so
a shared lead link silently rotted as the funnel filled up - the report existed,
the operator was told it did not.

The second half is the artifact flags. A public audit reaches status "done" even
when the artifact copy never happened (`audit_artifact_dir` is unset by default,
so `_store_artifacts` returns (None, None) and the run still completes). Reading
`bool(row["pdf_path"])` then offers a download button for a file that is not on
the server. The flags are asked of the STORE.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI

from app.core.auth import CurrentUser, get_current_user
from app.routers.admin_public_audits import router as admin_router
from app.routers.public import get_public_artifact_store
from app.services.audit_artifacts import LocalArtifactStore

pytestmark = pytest.mark.unit

_TOKEN = "tok-abc123"


def _row(**over: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "id": "pa-1",
        "email": "lead@example.com",
        "url": "https://lead.example",
        "status": "done",
        "score": 71,
        "source": "landing",
        "report_token": _TOKEN,
        "pdf_path": "public/pa-1/report.pdf",
        "json_path": "public/pa-1/findings.json",
        "run_uuid": "run-1",
        "error": None,
        "created_at": datetime(2026, 9, 1, tzinfo=UTC),
        "updated_at": None,
    }
    row.update(over)
    return row


def _user(role: str = "manager") -> CurrentUser:
    return CurrentUser(
        id="u-1", email="op@x.com", role=role, status="active",  # type: ignore[arg-type]
        name="Op", title="", avatar_color="#000", phone="", two_fa=False,
        client_id="cl-A" if role == "client" else None,
    )


@pytest.fixture
def rows() -> list[dict[str, Any]]:
    return [_row()]


@pytest.fixture
def app(monkeypatch: pytest.MonkeyPatch, rows: list[dict[str, Any]]) -> FastAPI:
    application = FastAPI()
    application.include_router(admin_router, prefix="/api/v1")

    monkeypatch.setattr(
        "app.routers.admin_public_audits._fetch_lead_by_token",
        lambda _uid, token: next((r for r in rows if r["report_token"] == token), None),
    )
    monkeypatch.setattr(
        "app.routers.admin_public_audits._fetch_leads",
        lambda _uid, *, limit, offset: rows[offset : offset + limit],
    )
    application.dependency_overrides[get_current_user] = lambda: _user()
    application.dependency_overrides[get_public_artifact_store] = lambda: None
    return application


@pytest.fixture
async def client(app: FastAPI) -> Any:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        yield c


async def test_a_lead_is_readable_by_its_token(client: httpx.AsyncClient) -> None:
    resp = await client.get(f"/api/v1/admin/public-audits/{_TOKEN}")

    assert resp.status_code == 200
    assert resp.json()["report_token"] == _TOKEN
    assert resp.json()["email"] == "lead@example.com"


async def test_a_lead_outside_the_first_page_is_still_reachable(
    client: httpx.AsyncClient, rows: list[dict[str, Any]]
) -> None:
    """The defect this route exists for: the old page scanned the newest 50, so an
    older lead's shared link resolved to 'not found' while its report sat on disk."""
    rows[:0] = [_row(id=f"pa-{i}", report_token=f"tok-{i}") for i in range(60)]

    listed = await client.get("/api/v1/admin/public-audits", params={"limit": 50})
    assert all(r["report_token"] != _TOKEN for r in listed.json()), "seed is on page 1"

    resp = await client.get(f"/api/v1/admin/public-audits/{_TOKEN}")
    assert resp.status_code == 200


async def test_an_unknown_token_is_a_real_404(client: httpx.AsyncClient) -> None:
    assert (await client.get("/api/v1/admin/public-audits/nope")).status_code == 404


async def test_a_portal_client_cannot_read_leads(app: FastAPI, client: httpx.AsyncClient) -> None:
    """Lead rows carry emails. `view_reports` is staff-only; a client role holds none."""
    app.dependency_overrides[get_current_user] = lambda: _user("client")

    assert (await client.get(f"/api/v1/admin/public-audits/{_TOKEN}")).status_code == 403


async def test_a_missing_file_is_not_advertised_as_a_download(
    app: FastAPI, client: httpx.AsyncClient, tmp_path: Path
) -> None:
    """status='done' with a pdf_path column but no file on disk - the default-config
    case, because audit_artifact_dir is unset and the copy never happened."""
    app.dependency_overrides[get_public_artifact_store] = lambda: LocalArtifactStore(str(tmp_path))

    body = (await client.get(f"/api/v1/admin/public-audits/{_TOKEN}")).json()

    assert body["has_pdf"] is False
    assert body["has_report"] is False


async def test_a_file_that_exists_is_advertised(
    app: FastAPI, client: httpx.AsyncClient, tmp_path: Path
) -> None:
    """The other half: the flags must not be pessimistic either, or a real report
    becomes unreachable."""
    pdf = tmp_path / "public" / "pa-1" / "report.pdf"
    pdf.parent.mkdir(parents=True, exist_ok=True)
    pdf.write_bytes(b"%PDF-1.4")
    app.dependency_overrides[get_public_artifact_store] = lambda: LocalArtifactStore(str(tmp_path))

    body = (await client.get(f"/api/v1/admin/public-audits/{_TOKEN}")).json()

    assert body["has_pdf"] is True
    assert body["has_report"] is False  # findings.json was never written
