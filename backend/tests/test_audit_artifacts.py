"""P3-5 gate: artifact store (copy + traversal-safe resolve), the worker copy
step, and the guarded /audits/{id} download endpoints."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI

from app.config import Settings
from app.core.auth import CurrentUser, get_current_user
from app.db.audits_repo import get_audits_repo
from app.routers.audits import get_artifact_store
from app.services.audit_artifacts import LocalArtifactStore
from integrations.audit_engine import AuditEngineConfig, AuditRunResult
from workers.tasks.audit import execute_audit

pytestmark = pytest.mark.unit


# --- the store -----------------------------------------------------------------
def _engine_artifacts(tmp_path: Path) -> tuple[str, str]:
    src = tmp_path / "engine"
    src.mkdir()
    pdf = src / "report-consolidated.pdf"
    pdf.write_bytes(b"%PDF-1.4 hello")
    findings = src / "findings.json"
    findings.write_text(json.dumps([{"check_id": "TECH-001"}]), encoding="utf-8")
    return str(pdf), str(findings)


def test_store_copies_and_returns_keys(tmp_path: Path) -> None:
    pdf_src, findings_src = _engine_artifacts(tmp_path)
    store = LocalArtifactStore(tmp_path / "root")
    pdf_key, json_key = store.store("aud-1", pdf_src=pdf_src, findings_src=findings_src)
    assert pdf_key == "aud-1/report.pdf"
    assert json_key == "aud-1/findings.json"
    assert (tmp_path / "root" / "aud-1" / "report.pdf").is_file()
    assert store.resolve(pdf_key) is not None
    assert store.resolve(json_key) is not None


def test_store_tolerates_missing_sources(tmp_path: Path) -> None:
    store = LocalArtifactStore(tmp_path / "root")
    pdf_key, json_key = store.store("aud-1", pdf_src=None, findings_src=str(tmp_path / "nope.json"))
    assert pdf_key is None
    assert json_key is None


def test_resolve_blocks_traversal(tmp_path: Path) -> None:
    (tmp_path / "secret.txt").write_text("top secret", encoding="utf-8")
    store = LocalArtifactStore(tmp_path / "root")
    (tmp_path / "root").mkdir()
    assert store.resolve("../secret.txt") is None
    assert store.resolve("aud-1/missing.pdf") is None


# --- the worker copy step ------------------------------------------------------
class FakeStore:
    def __init__(self, row: dict[str, Any]) -> None:
        self.row = row
        self.updates: list[dict[str, Any]] = []

    def load(self, audit_id: str) -> dict[str, Any] | None:
        return self.row

    def update(self, audit_id: str, fields: dict[str, Any]) -> None:
        self.updates.append(fields)
        self.row.update(fields)

    def record_cost(self, row: dict[str, Any], cost: float) -> None:
        pass


def test_worker_copies_artifacts_and_sets_flags(tmp_path: Path) -> None:
    pdf_src, findings_src = _engine_artifacts(tmp_path)

    def _runner(
        cfg: AuditEngineConfig, *, url: str, tier: str, comprehensive: bool = False
    ) -> AuditRunResult:
        return AuditRunResult(
            ok=True, run_uuid="u-1", artifact_dir=str(tmp_path / "engine"), score=80,
            scores={"overall": 80}, findings_path=findings_src, pdf_path=pdf_src,
            runtime_seconds=100, exit_code=0,
        )

    store = FakeStore({"id": "aud-1", "url": "https://x.com", "tier": "free", "status": "queued"})
    artifacts = LocalArtifactStore(tmp_path / "root")
    out = execute_audit(store, Settings(_env_file=None), "aud-1", runner=_runner, artifacts=artifacts)
    assert out["status"] == "done"
    done = store.updates[-1]
    assert done["pdf_path"] == "aud-1/report.pdf"
    assert done["json_path"] == "aud-1/findings.json"
    assert (tmp_path / "root" / "aud-1" / "report.pdf").is_file()


# --- the download endpoints ----------------------------------------------------
class FakeAuditsRepo:
    def __init__(self, row: dict[str, Any] | None) -> None:
        self.row = row

    def get_audit(self, audit_id: str) -> dict[str, Any] | None:
        return self.row


def _user() -> CurrentUser:
    return CurrentUser(
        id="u-1", email="op@x.com", role="viewer", status="active",
        name="Op", title="", avatar_color="#000", phone="", two_fa=False,
    )


@pytest.fixture
def wire_dl(app: FastAPI) -> Callable[[dict[str, Any] | None, LocalArtifactStore | None], None]:
    def _wire(row: dict[str, Any] | None, store: LocalArtifactStore | None) -> None:
        app.dependency_overrides[get_current_user] = _user
        app.dependency_overrides[get_audits_repo] = lambda: FakeAuditsRepo(row)
        app.dependency_overrides[get_artifact_store] = lambda: store

    return _wire


async def test_download_pdf_and_findings(
    client: httpx.AsyncClient, tmp_path: Path,
    wire_dl: Callable[[dict[str, Any] | None, LocalArtifactStore | None], None],
) -> None:
    pdf_src, findings_src = _engine_artifacts(tmp_path)
    store = LocalArtifactStore(tmp_path / "root")
    store.store("aud-1", pdf_src=pdf_src, findings_src=findings_src)
    row = {"id": "aud-1", "pdf_path": "aud-1/report.pdf", "json_path": "aud-1/findings.json"}
    wire_dl(row, store)

    pdf = await client.get("/api/v1/audits/aud-1/report.pdf")
    assert pdf.status_code == 200
    assert pdf.headers["content-type"] == "application/pdf"
    assert pdf.content.startswith(b"%PDF")

    fj = await client.get("/api/v1/audits/aud-1/findings.json")
    assert fj.status_code == 200
    assert json.loads(fj.content)[0]["check_id"] == "TECH-001"


async def test_download_404_when_no_artifact(
    client: httpx.AsyncClient, tmp_path: Path,
    wire_dl: Callable[[dict[str, Any] | None, LocalArtifactStore | None], None],
) -> None:
    store = LocalArtifactStore(tmp_path / "root")
    wire_dl({"id": "aud-1", "pdf_path": None, "json_path": None}, store)
    resp = await client.get("/api/v1/audits/aud-1/report.pdf")
    assert resp.status_code == 404


async def test_download_404_when_store_unconfigured(
    client: httpx.AsyncClient,
    wire_dl: Callable[[dict[str, Any] | None, LocalArtifactStore | None], None],
) -> None:
    wire_dl({"id": "aud-1", "pdf_path": "aud-1/report.pdf"}, None)
    resp = await client.get("/api/v1/audits/aud-1/report.pdf")
    assert resp.status_code == 404
