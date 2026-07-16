"""Backups service: run a Postgres snapshot, sync it offsite, and (guarded) restore.

The heavy lifting is a SUBPROCESS to ``pg_dump`` / ``pg_restore`` - exactly like the
audit-engine adapter shells out to its CLI. This service OWNS its own hard timeout
(``pg_dump`` never times out itself), never leaves a run half-owned (it always writes
a typed ledger row, ok or failed), and DEGRADES CLEANLY when the artifact root, the
DB DSN, or the ``pg_dump`` binary is absent (a failed row, never a crash).

Two secret-safety rules mirror the rest of the backend:

* The DB password is passed to the child through the libpq ``PG*`` environment
  (``PGPASSWORD`` etc., parsed from the DSN) - NEVER on the argv - so it can never
  leak into a process list or a log line.
* The controlled artifact root is traversal-safe (like ``audit_artifacts``): the dump
  is written under ``<root>/<snapshot_id>/`` and a restore refuses any artifact key
  that escapes the root.

Restore is DELIBERATELY dangerous (it overwrites the live database via
``pg_restore --clean --if-exists``), so it is owner-only at the router AND requires a
confirmation that echoes the snapshot id here - two independent gates on top of the
RLS boundary. In production a restore should target a maintenance window; the service
shape is what this chunk delivers.
"""

from __future__ import annotations

import os
import subprocess
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from psycopg.conninfo import conninfo_to_dict

from app.config import Settings
from app.logging_setup import get_logger
from integrations.b2 import OffsiteStore, offsite_store_from_settings
from integrations.errors import ProviderCallError

logger = get_logger("app.services.backups")

# Custom-format archive (pg_dump -Fc): compact + restorable with pg_restore.
_DUMP_NAME = "dump.pgc"


class _SnapshotWriter(Protocol):
    """The slice of ``BackupsRepo`` the service writes through (kept narrow so a
    fake repo in tests needs only these four methods)."""

    def get_snapshot(self, snapshot_id: str) -> dict[str, Any] | None: ...
    def insert_snapshot(self, row: dict[str, Any]) -> dict[str, Any]: ...
    def get_config(self) -> dict[str, Any] | None: ...
    def update_config(self, changes: dict[str, Any]) -> dict[str, Any] | None: ...


@dataclass(frozen=True)
class _DumpOutcome:
    ok: bool
    size_bytes: int = 0
    artifact_ref: str | None = None
    abs_path: str | None = None
    error: str | None = None


@dataclass(frozen=True)
class RestoreResult:
    """The typed outcome of a guarded restore - ok or a sanitized failure."""

    ok: bool
    error: str | None = None


class BackupService:
    """Runs snapshots + restores against a target Postgres over subprocess.

    Constructed with the RLS-scoped repo (writes the ledger on the caller's
    authenticated path), the controlled artifact root, the target DSN, the binary
    names + hard timeout, and an optional (key-gated) offsite store.
    """

    def __init__(
        self,
        *,
        repo: _SnapshotWriter,
        artifact_dir: str | None,
        dsn: str | None,
        pg_dump_bin: str = "pg_dump",
        pg_restore_bin: str = "pg_restore",
        timeout_seconds: int = 1800,
        offsite: OffsiteStore | None = None,
    ) -> None:
        self._repo = repo
        self._artifact_dir = artifact_dir
        self._dsn = dsn
        self._pg_dump_bin = pg_dump_bin
        self._pg_restore_bin = pg_restore_bin
        self._timeout = timeout_seconds
        self._offsite = offsite

    # --- Snapshot ------------------------------------------------------------
    def run_snapshot(self, *, snap_type: str, scope: str) -> dict[str, Any]:
        """Run one snapshot end-to-end and RECORD a ledger row (never raises).

        A missing root/DSN/binary or a non-zero ``pg_dump`` degrades to a ``failed``
        row (size 0) - honest, and matching the frontend which shows failed nightlies.
        On success the row carries the artifact key + real size/duration, an offsite
        copy is attempted when config enables it AND a key is present, and the config's
        ``last_backup`` marker advances.
        """
        started = time.monotonic()
        snapshot_id = str(uuid.uuid4())  # minted up front so the artifact path is stable
        config = self._repo.get_config() or {}

        outcome = self._dump(snapshot_id)
        offsite_synced = False
        if outcome.ok and bool(config.get("offsite_enabled")) and outcome.artifact_ref:
            offsite_synced = self._sync_offsite(outcome.artifact_ref, outcome.abs_path)

        duration = int(time.monotonic() - started)
        status = "success" if outcome.ok else "failed"
        logger.info(
            "backup_snapshot_done", type=snap_type, status=status,
            size_bytes=outcome.size_bytes, offsite_synced=offsite_synced,
        )
        row = self._repo.insert_snapshot(
            {
                "id": snapshot_id,
                "type": snap_type,
                "scope": scope,
                "size_bytes": outcome.size_bytes,
                "duration_seconds": duration,
                "status": status,
                "artifact_ref": outcome.artifact_ref,
                "offsite_synced": offsite_synced,
            }
        )
        if outcome.ok:
            # Advance the last-successful-backup marker (best-effort; upserts the row).
            self._repo.update_config({"last_backup": datetime.now(UTC)})
        return row

    def _dump(self, snapshot_id: str) -> _DumpOutcome:
        """Shell out to ``pg_dump`` (custom format) under the hard timeout. Returns a
        typed outcome; a degraded/failed run is an outcome, never an exception."""
        if not self._artifact_dir:
            return _DumpOutcome(ok=False, error="backup artifact dir is not configured")
        if not self._dsn:
            return _DumpOutcome(ok=False, error="database DSN is not configured")

        root = Path(self._artifact_dir).resolve()
        dest_dir = Path(self._artifact_dir) / snapshot_id
        dest = dest_dir / _DUMP_NAME
        if not dest.resolve().is_relative_to(root):  # snapshot_id is a uuid; guard anyway
            return _DumpOutcome(ok=False, error="resolved dump path escapes the artifact root")
        dest_dir.mkdir(parents=True, exist_ok=True)

        argv = [
            self._pg_dump_bin,
            "--format=custom",
            "--no-owner",
            "--no-privileges",
            "--file",
            str(dest),
        ]
        # Fixed binary, no shell; the DB password rides the env (never the argv).
        try:
            proc = subprocess.run(
                argv,
                capture_output=True,
                text=True,
                timeout=self._timeout,
                env=self._pg_env(),
                check=False,
            )
        except subprocess.TimeoutExpired:
            logger.warning("backup_dump_timeout", seconds=self._timeout)
            return _DumpOutcome(ok=False, error=f"pg_dump timed out after {self._timeout}s")
        except OSError as exc:
            # The pg_dump binary is missing / not executable.
            return _DumpOutcome(ok=False, error=f"failed to launch pg_dump: {exc}")

        if proc.returncode != 0:
            logger.warning("backup_dump_nonzero_exit", code=proc.returncode)
            return _DumpOutcome(ok=False, error=f"pg_dump exited with code {proc.returncode}")
        if not dest.is_file():
            return _DumpOutcome(ok=False, error="pg_dump produced no artifact")
        return _DumpOutcome(
            ok=True,
            size_bytes=dest.stat().st_size,
            artifact_ref=f"{snapshot_id}/{_DUMP_NAME}",
            abs_path=str(dest),
        )

    def _sync_offsite(self, artifact_ref: str, abs_path: str | None) -> bool:
        """Best-effort copy of the artifact to the offsite store. A failure leaves the
        LOCAL snapshot successful and simply records the offsite copy as not-synced."""
        if self._offsite is None or not abs_path:
            return False
        try:
            self._offsite.upload(artifact_ref, abs_path)
        except ProviderCallError:
            logger.warning("backup_offsite_failed", artifact_ref=artifact_ref)
            return False
        return True

    # --- Restore (guarded) ---------------------------------------------------
    def restore(self, snapshot_id: str, *, confirm: str) -> RestoreResult:
        """Restore a snapshot over the live DB (never raises). GUARDED:

        The caller (router) has already enforced owner-only; here ``confirm`` MUST
        echo ``snapshot_id`` (a second, independent friction gate). The snapshot must
        exist, be ``success``, and have a reachable artifact within the root. On
        success the config's ``restore_tested_at`` marker advances (a verified restore).
        """
        if confirm != snapshot_id:
            return RestoreResult(ok=False, error="confirmation does not match the snapshot id")
        snap = self._repo.get_snapshot(snapshot_id)
        if snap is None:
            return RestoreResult(ok=False, error="snapshot not found")
        if snap.get("status") != "success":
            return RestoreResult(ok=False, error="only a successful snapshot can be restored")
        artifact_ref = snap.get("artifact_ref")
        if not artifact_ref:
            return RestoreResult(ok=False, error="snapshot has no artifact to restore")
        path = self._resolve(str(artifact_ref))
        if path is None:
            return RestoreResult(ok=False, error="snapshot artifact is missing or unreachable")
        if not self._dsn:
            return RestoreResult(ok=False, error="database DSN is not configured")

        argv = [
            self._pg_restore_bin,
            "--clean",
            "--if-exists",
            "--no-owner",
            "--no-privileges",
            "--dbname",
            self._db_name(),
            str(path),
        ]
        # Fixed binary, no shell; the DB password rides the env (never the argv).
        try:
            proc = subprocess.run(
                argv,
                capture_output=True,
                text=True,
                timeout=self._timeout,
                env=self._pg_env(),
                check=False,
            )
        except subprocess.TimeoutExpired:
            logger.warning("backup_restore_timeout", seconds=self._timeout)
            return RestoreResult(ok=False, error=f"pg_restore timed out after {self._timeout}s")
        except OSError as exc:
            return RestoreResult(ok=False, error=f"failed to launch pg_restore: {exc}")

        if proc.returncode != 0:
            logger.warning("backup_restore_nonzero_exit", code=proc.returncode)
            return RestoreResult(ok=False, error=f"pg_restore exited with code {proc.returncode}")
        self._repo.update_config({"restore_tested_at": datetime.now(UTC)})
        logger.info("backup_restore_done", snapshot_id=snapshot_id)
        return RestoreResult(ok=True)

    # --- Helpers -------------------------------------------------------------
    def _resolve(self, key: str) -> Path | None:
        """Resolve a stored artifact key to a real file within the root, or ``None``.

        Refuses any key that escapes the root (``..`` / absolute) - a crafted key can
        never read an arbitrary file (mirrors ``audit_artifacts.LocalArtifactStore``)."""
        if not key or not self._artifact_dir:
            return None
        root = Path(self._artifact_dir).resolve()
        target = (Path(self._artifact_dir) / key).resolve()
        if not target.is_relative_to(root):
            return None
        return target if target.is_file() else None

    def _pg_env(self) -> dict[str, str]:
        """The child environment carrying the DB connection via libpq ``PG*`` vars
        (parsed from the DSN) so the password NEVER rides the argv or a log line."""
        env = {**os.environ, "PGCONNECT_TIMEOUT": "10"}
        if not self._dsn:
            return env
        try:
            params = conninfo_to_dict(self._dsn)
        except Exception:
            return env
        for key, env_key in (
            ("host", "PGHOST"),
            ("port", "PGPORT"),
            ("user", "PGUSER"),
            ("password", "PGPASSWORD"),
            ("dbname", "PGDATABASE"),
        ):
            value = params.get(key)
            if value:
                env[env_key] = str(value)
        return env

    def _db_name(self) -> str:
        """The target database name parsed from the DSN (``postgres`` as a fallback)."""
        if not self._dsn:
            return "postgres"
        try:
            params = conninfo_to_dict(self._dsn)
        except Exception:
            return "postgres"
        return str(params.get("dbname") or "postgres")


def build_backup_service(repo: _SnapshotWriter, settings: Settings) -> BackupService:
    """Assemble a ``BackupService`` from settings + the RLS-scoped repo.

    ``offsite_store_from_settings`` degrades to ``None`` without the B2 credential
    triple, so the service keeps the local snapshot and never attempts an offsite copy.
    """
    return BackupService(
        repo=repo,
        artifact_dir=settings.backup_artifact_dir,
        dsn=settings.database_admin_url,
        pg_dump_bin=settings.pg_dump_bin,
        pg_restore_bin=settings.pg_restore_bin,
        timeout_seconds=settings.backup_timeout_seconds,
        offsite=offsite_store_from_settings(settings),
    )
