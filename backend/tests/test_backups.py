"""Unit tests for the Backups module (7G-1): the four response shapes (Snapshot /
ProtectedStore / StorageSeg keys + aliases + the backupConfig const shape), the
snapshot service (run records a ledger row with the subprocess mocked, degrades
cleanly without a dump root/binary, syncs offsite only when enabled + keyed), the
GUARDED restore (confirmation + status + traversal), the B2 offsite seam (fake vs
key-gated real, degrades to None keyless), and the /backups endpoints with faked
repo + service (staff-read, owner/admin run + config, OWNER-only restore). No DB, no
network, no real pg_dump.
"""

from __future__ import annotations

import re
import types
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI

from app.config import Settings
from app.core.auth import CurrentUser, get_current_user
from app.db.backups_repo import get_backups_repo
from app.routers.backups import get_backup_service
from app.schemas.backups import (
    BackupConfigResponse,
    ProtectedStoreResponse,
    SnapshotResponse,
    StorageSegResponse,
    format_size,
)
from app.services import backups as backups_service
from app.services.backups import BackupService, RestoreResult
from integrations.b2 import (
    BackblazeB2Client,
    FakeOffsiteStore,
    OffsiteStore,
    offsite_store_from_settings,
)
from integrations.errors import ProviderNotConfiguredError

pytestmark = pytest.mark.unit

_REPO_ROOT = Path(__file__).resolve().parents[2]
_BACKUPS_TS = _REPO_ROOT / "frontend/lib/backups.ts"

_SNAPSHOT_KEYS = {"id", "ts", "type", "scope", "size", "duration", "status"}
_STORE_KEYS = {"key", "name", "desc", "icon", "size", "included", "note"}
_SEG_KEYS = {"key", "label", "gb", "color"}
_CONFIG_KEYS = {
    "nightlyTime", "retentionDays", "retained", "lastBackupAgoH",
    "nextBackupInH", "restoreTested", "nightlyOn", "offsiteOn",
}

_DSN = "postgresql://u:p@localhost:5432/testdb"


def _emitted(model: type) -> set[str]:
    return {
        f.serialization_alias or f.alias or name
        for name, f in model.model_fields.items()
    }


# --------------------------------------------------------------------------- #
# Schema fidelity
# --------------------------------------------------------------------------- #
def test_snapshot_emits_exactly_the_contract_keys() -> None:
    assert _emitted(SnapshotResponse) == _SNAPSHOT_KEYS


def test_protected_store_emits_exactly_the_contract_keys() -> None:
    assert _emitted(ProtectedStoreResponse) == _STORE_KEYS


def test_storage_seg_emits_exactly_the_contract_keys() -> None:
    assert _emitted(StorageSegResponse) == _SEG_KEYS


def test_config_emits_exactly_the_contract_keys() -> None:
    assert _emitted(BackupConfigResponse) == _CONFIG_KEYS


def test_storage_seg_matches_frontend_single_line_type() -> None:
    # StorageSeg is a SINGLE-LINE TS type (the shared contract lock parses only
    # multi-line bodies), so pin it here directly.
    src = _BACKUPS_TS.read_text(encoding="utf-8")
    match = re.search(r"export type StorageSeg\s*=\s*\{(.*?)\};", src)
    assert match
    ts_keys = set(re.findall(r"(\w+)\s*:", match.group(1)))
    assert ts_keys == _SEG_KEYS


def test_backup_config_matches_frontend_const() -> None:
    # backupConfig is a const object (not an export type), so pin it here. The line
    # anchor avoids matching the ``02:00`` colon inside the nightlyTime value.
    src = _BACKUPS_TS.read_text(encoding="utf-8")
    match = re.search(r"export const backupConfig\s*=\s*\{(.*?)\n\};", src, re.DOTALL)
    assert match
    ts_keys = set(re.findall(r"^\s*(\w+)\s*:", match.group(1), re.MULTILINE))
    assert ts_keys == _CONFIG_KEYS


def test_snapshot_from_row_formats_derived_fields() -> None:
    resp = SnapshotResponse.from_row(
        {
            "id": "snap-1",
            "type": "Nightly",
            "scope": "Database",
            "size_bytes": 1_954_154_659,  # ~1.82 GB
            "duration_seconds": 228,  # 3m 48s
            "status": "success",
        }
    )
    assert resp.id == "snap-1"
    assert resp.type == "Nightly"
    assert resp.size.endswith(" GB")
    assert resp.duration == "3m 48s"
    assert resp.status == "success"


def test_snapshot_from_row_defends_bad_enum_values() -> None:
    resp = SnapshotResponse.from_row({"id": "x", "type": "Weekly", "status": "boom"})
    assert resp.type == "Manual"  # unknown -> safe default
    assert resp.status == "success"
    assert resp.size == "—"  # 0/absent bytes -> em-dash


def test_format_size_zero_is_em_dash() -> None:
    assert format_size(0) == "—"
    assert format_size(None) == "—"
    assert format_size(12_288).endswith(" KB")


def test_config_from_row_falls_back_to_defaults() -> None:
    resp = BackupConfigResponse.from_row(None, retained=7).model_dump(by_alias=True)
    assert set(resp) == _CONFIG_KEYS
    assert resp["nightlyTime"] == "02:00 UTC"
    assert resp["retentionDays"] == 30
    assert resp["retained"] == 7
    assert resp["nightlyOn"] is True
    assert resp["offsiteOn"] is False
    assert resp["restoreTested"] == "Never"


def test_config_from_row_reads_stored_toggles() -> None:
    resp = BackupConfigResponse.from_row(
        {"nightly_enabled": False, "offsite_enabled": True, "retention_days": 14},
        retained=3,
    )
    assert resp.nightly_on is False
    assert resp.offsite_on is True
    assert resp.retention_days == 14


# --------------------------------------------------------------------------- #
# Offsite seam (B2)
# --------------------------------------------------------------------------- #
def test_fake_offsite_satisfies_protocol_and_records() -> None:
    store = FakeOffsiteStore()
    assert isinstance(store, OffsiteStore)
    ref = store.upload("snap-1/dump.pgc", "/tmp/dump.pgc")
    assert store.calls == 1
    assert store.store["snap-1/dump.pgc"] == "/tmp/dump.pgc"
    assert ref.endswith("snap-1/dump.pgc")


def test_b2_client_requires_full_credentials() -> None:
    # The creds check fires BEFORE the boto3 import, so this holds with or without boto3.
    with pytest.raises(ProviderNotConfiguredError, match="B2_APPLICATION_KEY"):
        BackblazeB2Client(key_id="", application_key="", bucket="")
    with pytest.raises(ProviderNotConfiguredError):
        BackblazeB2Client(key_id="id", application_key="", bucket="bucket")


def test_offsite_store_degrades_to_none_without_keys() -> None:
    assert offsite_store_from_settings(Settings(_env_file=None)) is None
    # A partial triple (bucket missing) still degrades - never a half-built client.
    partial = Settings(_env_file=None, b2_key_id="id", b2_application_key="secret")  # type: ignore[arg-type]
    assert offsite_store_from_settings(partial) is None


# --------------------------------------------------------------------------- #
# Snapshot service - run_snapshot (subprocess mocked)
# --------------------------------------------------------------------------- #
def _fake_dump_run(argv: list[str], **_kw: Any) -> types.SimpleNamespace:
    """Stand in for pg_dump: writes the ``--file`` target so the artifact exists."""
    if "--file" in argv:
        dest = Path(argv[argv.index("--file") + 1])
        dest.write_bytes(b"PGDMP-fake-archive-bytes")
    return types.SimpleNamespace(returncode=0, stdout="", stderr="")


def _fake_fail_run(_argv: list[str], **_kw: Any) -> types.SimpleNamespace:
    return types.SimpleNamespace(returncode=1, stdout="", stderr="pg_dump: error")


def _fake_ok_run(_argv: list[str], **_kw: Any) -> types.SimpleNamespace:
    return types.SimpleNamespace(returncode=0, stdout="", stderr="")


class FakeBackupsRepo:
    """In-memory stand-in for BackupsRepo (the four service-touched methods + reads)."""

    def __init__(self) -> None:
        self.snapshots: list[dict[str, Any]] = []
        self.config: dict[str, Any] = {"id": 1}
        self.inserted: list[dict[str, Any]] = []

    def list_snapshots(self, *, limit: int | None = None, offset: int = 0) -> list[dict[str, Any]]:
        return list(self.snapshots)

    def get_snapshot(self, snapshot_id: str) -> dict[str, Any] | None:
        return next((s for s in self.snapshots if str(s.get("id")) == snapshot_id), None)

    def insert_snapshot(self, row: dict[str, Any]) -> dict[str, Any]:
        stored = dict(row)
        self.snapshots.insert(0, stored)
        self.inserted.append(stored)
        return stored

    def count_snapshots(self) -> int:
        return len(self.snapshots)

    def get_config(self) -> dict[str, Any]:
        return self.config

    def update_config(self, changes: dict[str, Any]) -> dict[str, Any]:
        self.config.update(changes)
        return self.config


def _service(repo: FakeBackupsRepo, tmp: Path, *, offsite: Any = None) -> BackupService:
    return BackupService(repo=repo, artifact_dir=str(tmp), dsn=_DSN, offsite=offsite)


def test_run_snapshot_records_success_row(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(backups_service.subprocess, "run", _fake_dump_run)
    repo = FakeBackupsRepo()
    row = _service(repo, tmp_path).run_snapshot(snap_type="Manual", scope="Database")
    assert row["status"] == "success"
    assert row["size_bytes"] > 0
    assert row["artifact_ref"].endswith("dump.pgc")
    assert row["offsite_synced"] is False  # no offsite store
    assert len(repo.inserted) == 1
    assert repo.config.get("last_backup") is not None  # marker advanced


def test_run_snapshot_records_failed_row_on_nonzero_exit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(backups_service.subprocess, "run", _fake_fail_run)
    repo = FakeBackupsRepo()
    row = _service(repo, tmp_path).run_snapshot(snap_type="Nightly", scope="Database")
    assert row["status"] == "failed"
    assert row["size_bytes"] == 0
    assert row["artifact_ref"] is None
    assert "last_backup" not in repo.config  # no marker advance on failure


def test_run_snapshot_degrades_without_artifact_dir(monkeypatch: pytest.MonkeyPatch) -> None:
    # No dump root -> degrade BEFORE spawning any subprocess (prove it never runs).
    def _boom(*_a: Any, **_k: Any) -> Any:
        raise AssertionError("subprocess must not run when degraded")

    monkeypatch.setattr(backups_service.subprocess, "run", _boom)
    repo = FakeBackupsRepo()
    svc = BackupService(repo=repo, artifact_dir=None, dsn=_DSN)
    row = svc.run_snapshot(snap_type="Nightly", scope="Database")
    assert row["status"] == "failed"
    assert row["size_bytes"] == 0


def test_run_snapshot_syncs_offsite_when_enabled_and_keyed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(backups_service.subprocess, "run", _fake_dump_run)
    repo = FakeBackupsRepo()
    repo.config = {"id": 1, "offsite_enabled": True}
    store = FakeOffsiteStore()
    row = _service(repo, tmp_path, offsite=store).run_snapshot(snap_type="Manual", scope="Database")
    assert row["offsite_synced"] is True
    assert store.calls == 1


def test_run_snapshot_skips_offsite_when_disabled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(backups_service.subprocess, "run", _fake_dump_run)
    repo = FakeBackupsRepo()
    repo.config = {"id": 1, "offsite_enabled": False}
    store = FakeOffsiteStore()
    row = _service(repo, tmp_path, offsite=store).run_snapshot(snap_type="Manual", scope="Database")
    assert row["offsite_synced"] is False
    assert store.calls == 0  # never attempted when the toggle is off


# --------------------------------------------------------------------------- #
# Snapshot service - restore (guarded)
# --------------------------------------------------------------------------- #
def _seed_snapshot(repo: FakeBackupsRepo, tmp: Path, *, on_disk: bool = True) -> str:
    snapshot_id = "snap-restore-1"
    ref = f"{snapshot_id}/dump.pgc"
    if on_disk:
        dest = tmp / snapshot_id / "dump.pgc"
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"archive")
    repo.snapshots.append({"id": snapshot_id, "status": "success", "artifact_ref": ref})
    return snapshot_id


def test_restore_rejects_bad_confirmation(tmp_path: Path) -> None:
    repo = FakeBackupsRepo()
    sid = _seed_snapshot(repo, tmp_path)
    result = _service(repo, tmp_path).restore(sid, confirm="not-the-id")
    assert result.ok is False
    assert result.error is not None and "confirmation" in result.error


def test_restore_rejects_non_success_snapshot(tmp_path: Path) -> None:
    repo = FakeBackupsRepo()
    repo.snapshots.append({"id": "s2", "status": "failed", "artifact_ref": "s2/dump.pgc"})
    result = _service(repo, tmp_path).restore("s2", confirm="s2")
    assert result.ok is False
    assert result.error is not None and "successful" in result.error


def test_restore_rejects_missing_artifact(tmp_path: Path) -> None:
    repo = FakeBackupsRepo()
    sid = _seed_snapshot(repo, tmp_path, on_disk=False)  # ledger row but no file
    result = _service(repo, tmp_path).restore(sid, confirm=sid)
    assert result.ok is False
    assert result.error is not None and "unreachable" in result.error


def test_restore_rejects_traversal_artifact_key(tmp_path: Path) -> None:
    repo = FakeBackupsRepo()
    repo.snapshots.append(
        {"id": "s3", "status": "success", "artifact_ref": "../../../etc/passwd"}
    )
    result = _service(repo, tmp_path).restore("s3", confirm="s3")
    assert result.ok is False  # the traversal key resolves outside the root -> None


def test_restore_success_advances_restore_tested(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(backups_service.subprocess, "run", _fake_ok_run)
    repo = FakeBackupsRepo()
    sid = _seed_snapshot(repo, tmp_path)
    result = _service(repo, tmp_path).restore(sid, confirm=sid)
    assert result == RestoreResult(ok=True)
    assert repo.config.get("restore_tested_at") is not None


# --------------------------------------------------------------------------- #
# Endpoints (faked repo + service)
# --------------------------------------------------------------------------- #
class FakeBackupService:
    def __init__(self) -> None:
        self.ran: list[tuple[str, str]] = []
        self.restored: list[tuple[str, str]] = []
        self.restore_result = RestoreResult(ok=True)

    def run_snapshot(self, *, snap_type: str, scope: str) -> dict[str, Any]:
        self.ran.append((snap_type, scope))
        return {
            "id": "new-snap", "type": snap_type, "scope": scope, "size_bytes": 1024,
            "duration_seconds": 5, "status": "success", "artifact_ref": "new-snap/dump.pgc",
            "offsite_synced": False,
        }

    def restore(self, snapshot_id: str, *, confirm: str) -> RestoreResult:
        self.restored.append((snapshot_id, confirm))
        return self.restore_result


def _user(role: str, uid: str = "u-1") -> CurrentUser:
    return CurrentUser(
        id=uid, email="op@x.com", role=role, status="active",  # type: ignore[arg-type]
        name="Op", title="", avatar_color="#000", phone="", two_fa=False,
    )


@pytest.fixture
def repo() -> FakeBackupsRepo:
    return FakeBackupsRepo()


@pytest.fixture
def service() -> FakeBackupService:
    return FakeBackupService()


@pytest.fixture
def wire(
    app: FastAPI, repo: FakeBackupsRepo, service: FakeBackupService
) -> Callable[..., None]:
    app.dependency_overrides[get_backups_repo] = lambda: repo
    app.dependency_overrides[get_backup_service] = lambda: service

    def _as(role: str, uid: str = "u-1") -> None:
        app.dependency_overrides[get_current_user] = lambda: _user(role, uid)

    return _as


# reads: any staff; client excluded
async def test_snapshots_client_forbidden(
    client: httpx.AsyncClient, wire: Callable[..., None]
) -> None:
    wire("client")
    assert (await client.get("/api/v1/backups/snapshots")).status_code == 403


async def test_snapshots_ok_for_staff(
    client: httpx.AsyncClient, repo: FakeBackupsRepo, wire: Callable[..., None]
) -> None:
    repo.snapshots.append(
        {"id": "s1", "type": "Nightly", "scope": "Database", "size_bytes": 1024,
         "duration_seconds": 10, "status": "success"}
    )
    wire("viewer", "u-v")
    resp = await client.get("/api/v1/backups/snapshots")
    assert resp.status_code == 200
    assert set(resp.json()[0]) == _SNAPSHOT_KEYS


async def test_stores_returns_four(
    client: httpx.AsyncClient, wire: Callable[..., None]
) -> None:
    wire("analyst", "u-a")
    body = (await client.get("/api/v1/backups/stores")).json()
    assert len(body) == 4
    assert set(body[0]) == _STORE_KEYS


async def test_storage_returns_three(
    client: httpx.AsyncClient, wire: Callable[..., None]
) -> None:
    wire("analyst", "u-a")
    body = (await client.get("/api/v1/backups/storage")).json()
    assert len(body) == 3
    assert set(body[0]) == _SEG_KEYS


async def test_config_get_ok_for_staff(
    client: httpx.AsyncClient, wire: Callable[..., None]
) -> None:
    wire("specialist", "u-s")
    resp = await client.get("/api/v1/backups/config")
    assert resp.status_code == 200
    assert set(resp.json()) == _CONFIG_KEYS


# run: owner/admin only
async def test_run_forbidden_for_viewer(
    client: httpx.AsyncClient, wire: Callable[..., None]
) -> None:
    wire("viewer", "u-v")
    assert (await client.post("/api/v1/backups/run", json={})).status_code == 403


async def test_run_ok_for_admin(
    client: httpx.AsyncClient, service: FakeBackupService, wire: Callable[..., None]
) -> None:
    wire("admin", "u-admin")
    resp = await client.post("/api/v1/backups/run", json={"type": "Manual", "scope": "Database"})
    assert resp.status_code == 201
    assert set(resp.json()) == _SNAPSHOT_KEYS
    assert service.ran == [("Manual", "Database")]


# config PUT: owner/admin only
async def test_config_put_forbidden_for_manager(
    client: httpx.AsyncClient, wire: Callable[..., None]
) -> None:
    wire("manager", "u-mgr")
    resp = await client.put("/api/v1/backups/config", json={"nightlyOn": False})
    assert resp.status_code == 403


async def test_config_put_toggles_for_admin(
    client: httpx.AsyncClient, repo: FakeBackupsRepo, wire: Callable[..., None]
) -> None:
    wire("admin", "u-admin")
    resp = await client.put(
        "/api/v1/backups/config", json={"nightlyOn": False, "offsiteOn": True, "retentionDays": 14}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["nightlyOn"] is False
    assert body["offsiteOn"] is True
    assert body["retentionDays"] == 14
    # camelCase aliases resolved to DB columns server-side.
    assert repo.config["nightly_enabled"] is False
    assert repo.config["offsite_enabled"] is True


# restore: OWNER only, guarded
async def test_restore_forbidden_for_admin(
    client: httpx.AsyncClient, wire: Callable[..., None]
) -> None:
    wire("admin", "u-admin")  # restore is owner-only, admin is not enough
    resp = await client.post("/api/v1/backups/snap-1/restore", json={"confirm": "snap-1"})
    assert resp.status_code == 403


async def test_restore_404_for_unknown_snapshot(
    client: httpx.AsyncClient, wire: Callable[..., None]
) -> None:
    wire("owner", "u-owner")  # repo has no snapshots
    resp = await client.post("/api/v1/backups/nope/restore", json={"confirm": "nope"})
    assert resp.status_code == 404


async def test_restore_400_on_guard_failure(
    client: httpx.AsyncClient, repo: FakeBackupsRepo, service: FakeBackupService,
    wire: Callable[..., None],
) -> None:
    repo.snapshots.append({"id": "snap-1", "status": "success", "artifact_ref": "snap-1/dump.pgc"})
    service.restore_result = RestoreResult(ok=False, error="confirmation does not match")
    wire("owner", "u-owner")
    resp = await client.post("/api/v1/backups/snap-1/restore", json={"confirm": "wrong"})
    assert resp.status_code == 400


async def test_restore_ok_for_owner(
    client: httpx.AsyncClient, repo: FakeBackupsRepo, service: FakeBackupService,
    wire: Callable[..., None],
) -> None:
    repo.snapshots.append({"id": "snap-1", "status": "success", "artifact_ref": "snap-1/dump.pgc"})
    wire("owner", "u-owner")
    resp = await client.post("/api/v1/backups/snap-1/restore", json={"confirm": "snap-1"})
    assert resp.status_code == 200
    assert resp.json() == {"restored": True, "id": "snap-1"}
    assert service.restored == [("snap-1", "snap-1")]
