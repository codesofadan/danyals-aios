"""Adapter for the external SEO audit engine (``danyals-audit-system``).

The engine is a SEPARATE Python product with its OWN dependency set. We never
import it; we invoke its CLI as an external SUBPROCESS using ITS OWN interpreter
(``AUDIT_ENGINE_PYTHON``) with its repo as the working directory
(``AUDIT_ENGINE_DIR``).

Source-verified contract (see the engine's ``audit_engine/cli/main.py``):

* The ``full`` subcommand MINTS its own ``run_uuid`` - we cannot pass one in. It
  prints ``Run UUID: <uuid>`` and ``Artifact dir: <path>`` to stdout (via
  ``rich``; markup is stripped on a non-TTY). It does NOT print a DB run id.
* Artifacts land in ``<engine_dir>/data/audits/<domain-slug>/<run_uuid>/``. A
  ``full`` run writes ``findings.json`` + ``run.json`` (``scores.overall`` is the
  0-100 composite) always, and one of several report PDFs best-effort.
* The engine does NOT catch its own top-level exceptions and never times out
  itself - so the CALLER owns the hard timeout and treats a non-zero exit, a
  timeout, or a missing ``run.json`` as failure. This adapter never leaves a run
  half-owned: it always returns a typed result, ok or not.
* ``--mode free`` forces every paid provider off (zero spend); ``--mode paid``
  uses the engine's OWN keys (its ``.env``). ``--agents``/``--ai-narrative``
  default to ``ask`` which resolves to OFF on a non-TTY - we pass ``off``
  explicitly so behavior never depends on the terminal.

stdout wrapping: ``rich`` soft-wraps to 80 cols off a TTY, which can break a long
artifact-dir path across lines. We set ``COLUMNS=1000`` on the child AND parse
only the fixed-width ``Run UUID`` line, reconstructing the artifact dir from the
(deterministic) slug + uuid - so parsing never depends on the printed path.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.core.security import PrivateAddressError, validate_public_host
from app.logging_setup import get_logger

logger = get_logger("integrations.audit_engine")

# Candidate report PDFs a `full` run may write, most-complete first. The engine
# does NOT produce "report-final.pdf" (that comes from a separate Claude script);
# we accept whichever the pipeline actually emitted, and tolerate none (PDFs are
# skipped when no rendering backend is present - the run still succeeds).
# report-full.pdf is the COMPLETE multi-page report (e.g. 69 pages / 1.2 MB for a real
# run) - the actual client deliverable. report-consolidated.pdf is a thin summary that
# collapses to a near-empty 1-page file on a small site (which read as "empty / failed
# to load" in the browser), so it must NOT be preferred. Full first, always.
_PDF_CANDIDATES: tuple[str, ...] = (
    "report-full.pdf",
    "report-consolidated.pdf",
    "report-executive.pdf",
    "remediation.pdf",
    "report-final.pdf",
)

_FINDINGS_FILE = "findings.json"
_RUN_FILE = "run.json"

# The `Run UUID: <uuid4>` line is only 46 chars, so it never wraps at 80 cols.
_RUN_UUID_RE = re.compile(r"^Run UUID:\s+([0-9a-fA-F-]{36})", re.MULTILINE)


@dataclass(frozen=True)
class AuditEngineConfig:
    """Everything the adapter needs to shell out to the engine."""

    engine_dir: str
    engine_python: str
    timeout_seconds: int = 1500
    max_pages: int = 100
    profile: str = "general"


@dataclass(frozen=True)
class AuditRunResult:
    """The typed outcome of one engine run - ok or a sanitized failure."""

    ok: bool
    run_uuid: str | None = None
    artifact_dir: str | None = None
    score: int | None = None
    scores: dict[str, Any] = field(default_factory=dict)
    findings_path: str | None = None
    pdf_path: str | None = None
    runtime_seconds: int = 0
    exit_code: int | None = None
    error: str | None = None
    # run.json observables the worker turns into a RUNTIME-derived cost (never a
    # flat estimate): pages crawled, the engine mode (free|paid), and -- when a
    # newer engine build reports it -- a `usage` block (real token counts + serper
    # query count). ``usage`` is ``{}`` on an older engine that omits it.
    pages_crawled: int = 0
    mode: str = ""
    usage: dict[str, Any] = field(default_factory=dict)


def domain_to_slug(domain: str) -> str:
    """Replicate the engine's ``_domain_to_slug`` so we can locate its artifacts.

    ``https://example.com/`` -> ``example.com``; ``example.com/shop`` ->
    ``example.com_shop``. No lowercasing (matches the engine exactly).
    """
    return domain.replace("https://", "").replace("http://", "").rstrip("/").replace("/", "_")


def build_argv(
    *, domain: str, mode: str, max_pages: int, profile: str, comprehensive: bool = False
) -> list[str]:
    """Build the ``python -m audit_engine.cli.main full ...`` argument vector.

    ``comprehensive=True`` (the authenticated dashboard audit) runs the FULL
    consulting pipeline: the on-page + technical deterministic checks PLUS off-page
    (Serper SERP/competitors), local (Places/citations when ``profile=local``), the
    21 AI specialist agents, and the narrative. It runs in ``--mode paid`` so the
    paid data sources actually fire. This is the "real audit that takes full time".

    ``comprehensive=False`` (the PUBLIC free-audit funnel) keeps the light, zero-spend
    on-page-only run: ``mode`` is the stored value (``free`` | ``paid``), agents +
    narrative off, and on ``free`` every paid provider is explicitly disabled.
    ``--no-moz`` always (Moz needs a separate paid key, out of scope).
    """
    base = [
        "-m", "audit_engine.cli.main", "full", domain,
        "--profile", profile, "--max-pages", str(max_pages), "--no-moz",
    ]
    if comprehensive:
        return [
            *base,
            "--mode", "paid",
            "--serper", "--places", "--citations",
            "--agents", "on", "--ai-narrative", "on",
        ]
    argv = [*base, "--mode", mode, "--agents", "off", "--ai-narrative", "off"]
    if mode == "paid":
        argv += ["--serper", "--places", "--citations"]
    else:
        argv += ["--no-serper", "--no-places", "--no-citations"]
    return argv


def parse_run_uuid(stdout: str) -> str | None:
    """Extract the engine's self-minted run UUID from captured stdout."""
    match = _RUN_UUID_RE.search(stdout or "")
    return match.group(1) if match else None


def _read_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _composite_score(run_meta: dict[str, Any]) -> tuple[int | None, dict[str, Any]]:
    """Pull the 0-100 composite (``scores.overall``) + the per-category detail."""
    scores = run_meta.get("scores")
    if not isinstance(scores, dict):
        return None, {}
    overall = scores.get("overall")
    composite = round(overall) if isinstance(overall, (int, float)) else None
    return composite, scores


def _find_pdf(artifact_dir: Path) -> str | None:
    for name in _PDF_CANDIDATES:
        candidate = artifact_dir / name
        if candidate.is_file():
            return str(candidate)
    return None


def run_audit(
    cfg: AuditEngineConfig, *, url: str, tier: str, comprehensive: bool = False
) -> AuditRunResult:
    """Run one audit end-to-end and return a typed result (never raises).

    ``tier`` is the stored value (``free`` | ``paid``); it selects the engine
    ``--mode`` for the light path. ``comprehensive=True`` overrides that and runs the
    full consulting pipeline (all dimensions + AI agents, paid mode) - used for the
    authenticated dashboard audit. The URL is SSRF-validated here (defense in depth -
    the endpoint already validated at enqueue) before any subprocess is spawned.
    """
    # 1) SSRF guard. Sync context (a Celery worker, no event loop) so a direct
    # call is fine - no to_thread needed off the loop.
    try:
        validate_public_host(url)
    except PrivateAddressError as exc:
        return AuditRunResult(ok=False, error=f"target URL rejected: {exc}")

    if not cfg.engine_dir or not cfg.engine_python:
        return AuditRunResult(ok=False, error="audit engine is not configured")
    if not Path(cfg.engine_python).exists():
        return AuditRunResult(ok=False, error="audit engine interpreter not found")

    mode = "paid" if (tier == "paid" or comprehensive) else "free"
    argv = build_argv(
        domain=url, mode=mode, max_pages=cfg.max_pages, profile=cfg.profile,
        comprehensive=comprehensive,
    )

    child_env = {**os.environ, "COLUMNS": "1000", "PYTHONIOENCODING": "utf-8"}
    started = time.monotonic()
    logger.info("audit_engine_start", mode=mode, max_pages=cfg.max_pages)
    try:
        proc = subprocess.run(
            [cfg.engine_python, *argv],
            cwd=cfg.engine_dir,
            capture_output=True,
            text=True,
            timeout=cfg.timeout_seconds,
            env=child_env,
            check=False,
        )
    except subprocess.TimeoutExpired:
        elapsed = int(time.monotonic() - started)
        logger.warning("audit_engine_timeout", seconds=elapsed)
        return AuditRunResult(
            ok=False,
            runtime_seconds=elapsed,
            error=f"engine timed out after {cfg.timeout_seconds}s",
        )
    except OSError as exc:
        return AuditRunResult(ok=False, error=f"failed to launch engine: {exc}")

    elapsed = int(time.monotonic() - started)
    run_uuid = parse_run_uuid(proc.stdout)

    if proc.returncode != 0:
        logger.warning("audit_engine_nonzero_exit", code=proc.returncode)
        return AuditRunResult(
            ok=False,
            run_uuid=run_uuid,
            runtime_seconds=elapsed,
            exit_code=proc.returncode,
            error=f"engine exited with code {proc.returncode}",
        )

    if run_uuid is None:
        return AuditRunResult(
            ok=False,
            runtime_seconds=elapsed,
            exit_code=0,
            error="could not parse run UUID from engine output",
        )

    # Reconstruct the artifact dir deterministically (slug + uuid) rather than
    # trusting the possibly-wrapped printed path.
    slug = domain_to_slug(url)
    artifact_dir = Path(cfg.engine_dir) / "data" / "audits" / slug / run_uuid
    run_meta = _read_json(artifact_dir / _RUN_FILE)
    if not run_meta:
        return AuditRunResult(
            ok=False,
            run_uuid=run_uuid,
            artifact_dir=str(artifact_dir),
            runtime_seconds=elapsed,
            exit_code=0,
            error="engine produced no run.json (incomplete run)",
        )

    score, scores = _composite_score(run_meta)
    findings = artifact_dir / _FINDINGS_FILE
    usage = run_meta.get("usage")
    logger.info("audit_engine_done", run_uuid=run_uuid, score=score, seconds=elapsed)
    return AuditRunResult(
        ok=True,
        run_uuid=run_uuid,
        artifact_dir=str(artifact_dir),
        score=score,
        scores=scores,
        findings_path=str(findings) if findings.is_file() else None,
        pdf_path=_find_pdf(artifact_dir),
        runtime_seconds=elapsed,
        exit_code=0,
        pages_crawled=int(run_meta["pages_crawled"])
        if isinstance(run_meta.get("pages_crawled"), (int, float))
        else 0,
        mode=str(run_meta.get("mode") or ""),
        usage=usage if isinstance(usage, dict) else {},
    )
