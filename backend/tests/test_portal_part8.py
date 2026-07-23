"""Part 8 gate: the client-portal completion - report-grant enforcement, the
deliverables / requests / reports surfaces, and the producer deliverable-emit.

No DB, no network: the portal repo, the privileged inserter, the artifact store +
loader, and every producer's store/provider are fakes/monkeypatched. Proves:

* the frontend contract for the SINGLE-LINE TS types the shared multi-line regex in
  test_contract_lock.py cannot parse (GaugeDatum / StatDatum) + ClientDeliverable's
  INLINE kind/status unions,
* an ungranted report key is never surfaced and an ungranted deliverable is hidden,
* ``PortalRequestCreate`` carries no ``client_id`` and the insert pins the tenant,
* the ``pending -> in_review`` status mapping lives in the portal_requests view,
* EACH producing worker (audit / content / reports / off-page) emits a deliverable.
"""

from __future__ import annotations

import re
import typing
from datetime import date
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI

from app.config import Settings
from app.core.auth import CurrentUser, get_current_user
from app.db.portal_repo import get_portal_repo
from app.routers.audits import get_artifact_store
from app.routers.portal import (
    get_portal_deliverable_loader,
    get_portal_request_inserter,
)
from app.schemas.portal_deliverables import (
    DeliverableKind,
    DeliverableStatus,
)
from app.schemas.portal_reports import (
    GaugeDatumResponse,
    PortalReportResponse,
    StatDatumResponse,
)
from app.schemas.portal_requests import PortalRequestCreate
from app.services.report_viz import build_report_viz

pytestmark = pytest.mark.unit

_REPO_ROOT = Path(__file__).resolve().parents[2]
_CLIENT_TS = _REPO_ROOT / "frontend" / "lib" / "client.ts"


def _emitted(model: type[Any]) -> set[str]:
    return {
        f.serialization_alias or f.alias or name
        for name, f in model.model_fields.items()
    }


# --------------------------------------------------------------------------- #
# 1. Contract locks the shared multi-line regex can't cover
# --------------------------------------------------------------------------- #
def _inline_object_fields(name: str) -> set[str]:
    """Field names of a SINGLE-LINE ``export type X = { a: ...; b: ... };``."""
    src = _CLIENT_TS.read_text(encoding="utf-8")
    match = re.search(rf"export type {name}\s*=\s*\{{([^}}]*)\}}", src)
    assert match, f"inline TS type {name} not found in {_CLIENT_TS}"
    return {m.group(1) for m in re.finditer(r"(\w+)\??\s*:", match.group(1))}


def test_gauge_and_stat_datum_match_frontend_single_line_types() -> None:
    assert _emitted(GaugeDatumResponse) == _inline_object_fields("GaugeDatum")
    assert _emitted(StatDatumResponse) == _inline_object_fields("StatDatum")


def _inline_union_on_field(type_name: str, field: str) -> set[str]:
    """The quoted literals of an INLINE ``field: "a" | "b";`` inside a TS object type."""
    src = _CLIENT_TS.read_text(encoding="utf-8")
    block = re.search(rf"export type {type_name}\s*=\s*\{{(.*?)\n\}};", src, re.DOTALL)
    assert block, f"TS type {type_name} not found"
    line = re.search(rf"\b{field}\s*:\s*([^;]+);", block.group(1))
    assert line, f"field {field} not found on {type_name}"
    return set(re.findall(r'"([^"]*)"', line.group(1)))


def test_client_deliverable_inline_unions_match_frontend() -> None:
    # ClientDeliverable.kind / .status are inline unions in lib/client.ts (not
    # exported types), so they are locked here rather than in the enum-contract sweep.
    assert set(typing.get_args(DeliverableKind)) == _inline_union_on_field(
        "ClientDeliverable", "kind"
    )
    assert set(typing.get_args(DeliverableStatus)) == _inline_union_on_field(
        "ClientDeliverable", "status"
    )


def test_portal_request_create_has_no_client_id() -> None:
    # The tenant is pinned server-side; the body must never carry a client_id.
    assert set(PortalRequestCreate.model_fields) == {"kind", "subject", "detail"}


# --------------------------------------------------------------------------- #
# 2. Report-grant enforcement (build_report_viz)
# --------------------------------------------------------------------------- #
def test_report_viz_returns_only_granted_keys_in_canonical_order() -> None:
    # A DB is not configured in the unit gate -> real series degrade to empty; the
    # KEY SET returned must still be exactly the granted keys (ungranted never leaks).
    reports = build_report_viz("cl-1", ["backlinks", "milestones", "audit_scores"])
    keys = [r.key for r in reports]
    assert keys == ["audit_scores", "backlinks", "milestones"]  # canonical order
    assert "traffic" not in keys and "rank_tracker" not in keys


def test_report_viz_flags_placeholder_vs_real() -> None:
    by_key = {r.key: r for r in build_report_viz("cl-1", ["audit_scores", "backlinks"])}
    assert by_key["backlinks"].placeholder is True  # sample data
    assert by_key["audit_scores"].placeholder is False  # real (empty) series
    # a real-but-empty client gets an honest zero series, never an exception
    assert by_key["audit_scores"].viz.headline == "—"


def test_report_viz_empty_grant_is_empty_list() -> None:
    assert build_report_viz("cl-1", []) == []


# --------------------------------------------------------------------------- #
# 3. pending -> in_review mapping lives in the portal_requests view
# --------------------------------------------------------------------------- #
def test_pending_maps_to_in_review_in_the_view() -> None:
    sql = (_REPO_ROOT / "db" / "migrations" / "0033_support_tickets_portal.sql").read_text(
        encoding="utf-8"
    )
    normalized = " ".join(sql.split())
    assert "case status when 'pending' then 'in_review' else status::text end as status" in normalized
    # the client-facing union has no 'pending' - the internal state never surfaces
    from app.schemas.portal_requests import RequestStatus

    assert "pending" not in set(typing.get_args(RequestStatus))
    assert "in_review" in set(typing.get_args(RequestStatus))


# --------------------------------------------------------------------------- #
# 4. Portal endpoints (fake repo + fake inserter/loader/store)
# --------------------------------------------------------------------------- #
def _client_user(client_id: str | None = "cl-A") -> CurrentUser:
    return CurrentUser(
        id="00000000-0000-0000-0000-0000000000aa", email="p@acme.com", role="client",
        status="active", name="Acme Portal", title="", avatar_color="#000", phone="",
        two_fa=False, client_id=client_id,
    )


class FakePortalRepo:
    def __init__(self) -> None:
        self.client_row: dict[str, Any] = {"id": "cl-A", "name": "Acme"}
        self.deliverables: list[dict[str, Any]] = []
        self.requests: list[dict[str, Any]] = []
        self.granted: list[str] = []
        self.deliverable_by_id: dict[str, dict[str, Any]] = {}

    def get_client(self) -> dict[str, Any]:
        return self.client_row

    def list_deliverables(self, *, limit: int | None = None, offset: int = 0) -> list[dict[str, Any]]:
        return list(self.deliverables)

    def get_deliverable(self, deliverable_id: str) -> dict[str, Any] | None:
        return self.deliverable_by_id.get(deliverable_id)

    def list_requests(self, *, limit: int | None = None, offset: int = 0) -> list[dict[str, Any]]:
        return list(self.requests)

    def granted_report_keys(self) -> list[str]:
        return list(self.granted)


class FakeRequestInserter:
    def __init__(self) -> None:
        self.inserted: list[dict[str, Any]] = []

    def __call__(self, row: dict[str, Any]) -> dict[str, Any]:
        self.inserted.append(row)
        return {"code": "T-9001", "opened_at": "2026-07-17T10:00:00Z", "reply": None, **row}


@pytest.fixture
def repo() -> FakePortalRepo:
    return FakePortalRepo()


@pytest.fixture
def wire(app: FastAPI, repo: FakePortalRepo) -> Any:
    app.dependency_overrides[get_portal_repo] = lambda: repo

    def _as(user: CurrentUser) -> None:
        app.dependency_overrides[get_current_user] = lambda: user

    return _as


async def test_reports_endpoint_returns_only_granted(
    client: httpx.AsyncClient, repo: FakePortalRepo, wire: Any
) -> None:
    repo.granted = ["audit_scores", "backlinks"]
    wire(_client_user())
    resp = await client.get("/api/v1/portal/reports")
    assert resp.status_code == 200, resp.text
    keys = [r["key"] for r in resp.json()]
    assert keys == ["audit_scores", "backlinks"]
    assert "traffic" not in keys  # ungranted never surfaced


async def test_deliverables_endpoint_shape_and_hidden_columns(
    client: httpx.AsyncClient, repo: FakePortalRepo, wire: Any
) -> None:
    repo.deliverables = [
        {
            "id": "d-1", "title": "Technical SEO Audit", "kind": "Audit", "icon": "fact_check",
            "period": "July 2026", "issued_at": "2026-07-03T00:00:00Z", "size_label": "2.4 MB",
            "status": "ready", "requires": "audit_scores",
        }
    ]
    wire(_client_user())
    resp = await client.get("/api/v1/portal/deliverables")
    assert resp.status_code == 200
    row = resp.json()[0]
    assert set(row) == {"id", "title", "kind", "icon", "period", "date", "size", "status", "requires"}
    # no server-only column ever surfaces
    assert not ({"client_id", "artifact_key", "media_type", "source_kind", "source_id"} & set(row))


async def test_download_hidden_deliverable_404(
    app: FastAPI, client: httpx.AsyncClient, repo: FakePortalRepo, wire: Any
) -> None:
    # An ungranted/unknown deliverable is not returned by the view -> get_deliverable
    # is None -> 404, and the artifact path is never resolved.
    app.dependency_overrides[get_portal_deliverable_loader] = lambda: (lambda _id: None)
    app.dependency_overrides[get_artifact_store] = lambda: object()
    wire(_client_user())
    resp = await client.get("/api/v1/portal/deliverables/d-hidden/download")
    assert resp.status_code == 404


async def test_download_generating_deliverable_404(
    app: FastAPI, client: httpx.AsyncClient, repo: FakePortalRepo, wire: Any
) -> None:
    repo.deliverable_by_id["d-gen"] = {"id": "d-gen", "status": "generating"}

    class _Store:
        def resolve(self, key: str | None) -> Path | None:
            return None

    app.dependency_overrides[get_artifact_store] = lambda: _Store()
    app.dependency_overrides[get_portal_deliverable_loader] = lambda: (
        lambda _id: {"artifact_key": "k", "media_type": "application/pdf", "status": "generating"}
    )
    wire(_client_user())
    resp = await client.get("/api/v1/portal/deliverables/d-gen/download")
    assert resp.status_code == 404  # still generating -> nothing to serve


async def test_create_request_pins_tenant(
    app: FastAPI, client: httpx.AsyncClient, repo: FakePortalRepo, wire: Any
) -> None:
    inserter = FakeRequestInserter()
    app.dependency_overrides[get_portal_request_inserter] = lambda: inserter
    wire(_client_user("cl-A"))
    resp = await client.post(
        "/api/v1/portal/requests",
        json={"kind": "Access", "subject": "Unlock backlinks", "detail": "please", "client_id": "cl-EVIL"},
    )
    assert resp.status_code == 201, resp.text
    assert inserter.inserted[0]["client_id"] == "cl-A"  # body's cl-EVIL ignored
    assert inserter.inserted[0]["channel"] == "Portal" and inserter.inserted[0]["status"] == "open"
    body = resp.json()
    assert set(body) == {"id", "kind", "subject", "detail", "status", "ago", "reply"}
    assert body["id"] == "T-9001" and body["status"] == "open"


# --------------------------------------------------------------------------- #
# 5. Per-producer deliverable-emit (each producing worker emits a deliverable)
# --------------------------------------------------------------------------- #
class _EmitSpy:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def __call__(self, **kw: Any) -> None:
        self.calls.append(kw)


def test_audit_worker_emits_audit_deliverable(monkeypatch: pytest.MonkeyPatch) -> None:
    from integrations.audit_engine import AuditEngineConfig, AuditRunResult
    from workers.tasks import audit as wk

    spy = _EmitSpy()
    monkeypatch.setattr(wk, "emit_deliverable", spy)

    class FakeStore:
        def __init__(self) -> None:
            self.row: dict[str, Any] = {
                "id": "aud-1", "url": "https://ex.com", "tier": "free", "status": "queued",
                "client_id": "cl-1", "client_name": "Verde",
            }

        def load(self, audit_id: str) -> dict[str, Any]:
            return self.row

        def update(self, audit_id: str, fields: dict[str, Any]) -> None:
            self.row.update(fields)

        def record_cost(self, row: dict[str, Any], cost: float) -> None:
            return None

    class FakeArtifacts:
        def store(self, audit_id: str, *, pdf_src: Any, findings_src: Any) -> tuple[str, None]:
            return f"{audit_id}/report.pdf", None

    def runner(
        cfg: AuditEngineConfig, *, url: str, tier: str, comprehensive: bool = False,
        types: list[str] | None = None,
    ) -> AuditRunResult:
        return AuditRunResult(ok=True, run_uuid="u-1", artifact_dir="/a", score=88,
                              scores={"overall": 88}, runtime_seconds=100, exit_code=0)

    out = wk.execute_audit(
        FakeStore(), Settings(_env_file=None, app_env="dev"), "aud-1",
        runner=runner, artifacts=FakeArtifacts(),
    )
    assert out["status"] == "done"
    assert len(spy.calls) == 1
    call = spy.calls[0]
    assert call["kind"] == "Audit" and call["requires"] == "audit_scores"
    assert call["client_id"] == "cl-1" and call["artifact_key"] == "aud-1/report.pdf"


def test_content_publish_emits_content_deliverable(monkeypatch: pytest.MonkeyPatch) -> None:
    from workers.tasks import content as wk

    spy = _EmitSpy()
    monkeypatch.setattr(wk, "emit_deliverable", spy)

    row: dict[str, Any] = {
        "id": "job-1", "code": "CJ-1", "client_id": "cl-1", "client_name": "Verde",
        "topic": "Best HVAC", "status": "publishing", "qa_score": {"passed": True},
        "target": "PDF", "draft_md": "# Best HVAC\nbody",
    }

    class FakeStore:
        def load(self, code: str) -> dict[str, Any]:
            return row

        def update(self, code: str, fields: dict[str, Any]) -> dict[str, Any]:
            row.update(fields)
            return row

    class FakeArtifacts:
        def store(self, code: str, *, markdown: str, title: str) -> tuple[str, str]:
            return f"{code}/post.pdf", f"{code}/post.md"

    outcome = wk.publish_content_job(
        FakeStore(), None, "CJ-1",
        settings=Settings(_env_file=None, app_env="dev"), artifacts=FakeArtifacts(),
    )
    assert outcome.status == "done"
    assert len(spy.calls) == 1
    assert spy.calls[0]["kind"] == "Content" and spy.calls[0]["requires"] == "content_status"
    assert spy.calls[0]["client_id"] == "cl-1"


async def test_reports_sync_emits_monthly_deliverable(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.routers import reports as wk

    spy = _EmitSpy()
    monkeypatch.setattr(wk, "emit_deliverable", spy)

    class FakeReportsRepo:
        def mark_synced(self, workbook_id: str, *, rows_added: int) -> dict[str, Any]:
            return {"id": workbook_id, "client_name": "Verde"}

    wb = {"id": "wb-1", "client_id": "cl-1", "client_name": "Verde", "sheet_id": ""}
    actor = _client_user()  # any user; _sync_one only reads the workbook
    updated = await wk._sync_one(FakeReportsRepo(), object(), actor, wb)
    assert updated["id"] == "wb-1"
    assert len(spy.calls) == 1
    assert spy.calls[0]["kind"] == "Monthly" and spy.calls[0]["requires"] == "monthly_report"
    assert spy.calls[0]["client_id"] == "cl-1"


def test_offpage_monitor_emits_backlinks_deliverable(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services.cost_gate import CostGate
    from integrations.backlinks import BacklinkRecord
    from workers.tasks import offpage as wk

    spy = _EmitSpy()
    monkeypatch.setattr(wk, "emit_deliverable", spy)

    class FakeStore:
        def list_backlinks_for_client(self, client_id: str) -> list[dict[str, Any]]:
            return []  # empty ledger -> the fetched link is NEW

        def insert_backlink(self, **kw: Any) -> None:
            return None

        def set_backlink_status(self, backlink_id: str, status: str) -> None:
            return None

    class FakeProvider:
        def fetch_backlinks(self, domain: str, *, limit: int = 100) -> list[BacklinkRecord]:
            return [BacklinkRecord(ref_domain="fresh.example", anchor="a", authority=50,
                                   spam=2, first_seen=date(2026, 7, 1))]

    class _NullCache:
        def get(self, key: str) -> Any | None:
            return None

        def set(self, key: str, value: Any) -> None:
            return None

    class FakeCostStore:
        def dial_mode(self, feature_key: str) -> str:
            return "api"

        def client_budget(self, client_id: str) -> None:
            return None

        def daily_spent(self) -> float:
            return 0.0

        def daily_stop(self) -> float:
            return 75.0

        def is_halted(self) -> bool:
            return False

        def record_cost(self, ctx: Any, cost: float, *, cached: bool) -> None:
            return None

    result = wk.run_backlink_monitor(
        FakeStore(), FakeProvider(), CostGate(FakeCostStore(), _NullCache()),
        Settings(_env_file=None, app_env="dev"),
        client_id="cl-1", client_name="Verde", domain="verde.example", notify=lambda *a: None,
    )
    assert result["state"] == "ok" and result["new"] == 1
    assert len(spy.calls) == 1
    assert spy.calls[0]["kind"] == "Backlinks" and spy.calls[0]["requires"] == "backlinks"
    assert spy.calls[0]["client_id"] == "cl-1"


def test_all_report_response_models_are_pydantic() -> None:
    # Sanity: the wrapper carries the placeholder flag OUTSIDE the viz (byte-for-byte).
    assert set(PortalReportResponse.model_fields) == {"key", "viz", "placeholder"}
