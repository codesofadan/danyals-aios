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
    # report.pdf is the self-contained single-file deliverable rendered from the
    # SAME report.html the dashboard viewer displays, so serving it guarantees the
    # downloaded PDF matches the on-screen report page for page. Prefer it; fall
    # back to the older multi-file reports for runs from an engine that predates it.
    "report.pdf",
    "report-full.pdf",
    "report-consolidated.pdf",
    "report-executive.pdf",
    "remediation.pdf",
    "report-final.pdf",
)

# The self-contained HTML report (CSS inlined) that the AIOS dashboard renders in
# its paginated page-viewer. It is the exact source the served PDF is rendered
# from, so the viewer and the PDF are the same document.
_HTML_CANDIDATES: tuple[str, ...] = ("report.html",)

_FINDINGS_FILE = "findings.json"
_RUN_FILE = "run.json"

# What each DEPTH actually runs. Kept local so integrations never import
# ``app.*``; mirrored by ``app.services.audit_depth`` and pinned by
# ``tests/test_audit_depth.py`` so an estimate always prices the run that will
# actually be launched.
#
# Every audit covers every dimension - the deterministic crawl cannot be scoped,
# and pretending otherwise is the defect this replaced. Depth decides how much
# PAID corroboration is bought on top.
DEPTH_SCOPE: dict[str, dict[str, bool]] = {
    "free": {"psi": False, "serper": False, "places": False,
             "agents": False, "narrative": False},
    "standard": {"psi": True, "serper": True, "places": False,
                 "agents": False, "narrative": False},
    "deep": {"psi": True, "serper": True, "places": True,
             "agents": True, "narrative": True},
}

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
    # The PUBLIC free funnel crawls a CONDENSED slice, not the full breadth
    # (DECISIONS_LOG D-1: "Free (condensed, ~10-15 pages, public lead magnet)").
    # Kept separate from `max_pages` so tuning the paid audit's depth can never
    # silently widen an unauthenticated, unbilled crawl.
    free_max_pages: int = 15


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
    # The self-contained report.html the dashboard viewer displays (same content
    # as the PDF). None when an older engine build produced no such file.
    html_path: str | None = None
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
    *,
    domain: str,
    mode: str,
    max_pages: int,
    profile: str,
    comprehensive: bool = False,
    depth: str | None = None,
) -> list[str]:
    """Build the ``python -m audit_engine.cli.main full ...`` argument vector.

    ``comprehensive=True`` (the authenticated dashboard audit) runs the consulting
    pipeline, scoped by ``depth``.

    WHY DEPTH AND NOT A TYPE PICKER. This used to take an audit-type selection
    (on-page / technical / off-page / local / GEO / strategy) and the operator
    reasonably read it as "audit only these". It never was. The deterministic
    crawl - on-page, technical, AND the AI-search checks - ALWAYS runs and cannot
    be isolated, because the engine has no per-dimension flag. Selecting "on-page
    + technical" still produced GEO and strategy findings, because those checks
    had run regardless. All the picker ever did was gate which PAID providers and
    agents fired, under labels that promised something else.

    So the axis is now the one the engine can actually honour: how much of the
    paid pipeline runs. Every audit covers every dimension; depth decides how
    deeply it is corroborated.

    * ``free``     - the deterministic crawl alone. No paid provider, no agents.
    * ``standard`` - plus PageSpeed/CWV and the SERP + competitor-gap lookup.
    * ``deep``     - plus Google Places, citation discovery, the 21 specialists
      and the AI narrative. ``--profile local`` so the engine unlocks GBP /
      citations / Team D, which it gates behind that profile.

    ``comprehensive=False`` (the PUBLIC free-audit funnel) is the CONDENSED,
    GENUINELY FREE lead magnet - ``--mode free``. See the FREE FUNNEL note below.
    ``--no-moz`` always (Moz needs a separate paid key, out of scope).
    """
    if comprehensive:
        scope = DEPTH_SCOPE.get(depth or "standard", DEPTH_SCOPE["standard"])
        # `deep` unlocks the local pipeline, which the engine gates behind the
        # profile rather than behind a flag: without `--profile local` the
        # `--places` / `--citations` flags are accepted and then do nothing.
        profile_arg = "local" if scope["places"] else profile
        argv = [
            "-m", "audit_engine.cli.main", "full", domain,
            "--profile", profile_arg, "--max-pages", str(max_pages),
            # The mode the CALLER resolved, not a hardcoded "paid". This branch
            # used to pin it, so a `free` depth would have been described to the
            # operator as free and handed to the engine as paid - the same
            # asked-for-free-got-paid shape WU-7 removed from the public funnel.
            "--no-moz", "--mode", mode,
        ]
        argv += ["--psi"] if scope["psi"] else ["--no-psi"]
        argv += ["--serper"] if scope["serper"] else ["--no-serper"]
        argv += (
            ["--places", "--citations"] if scope["places"]
            else ["--no-places", "--no-citations"]
        )
        argv += ["--agents", "on" if scope["agents"] else "off"]
        argv += ["--ai-narrative", "on" if scope["narrative"] else "off"]
        return argv
    # ---------------------------------------------------------------------- #
    # PUBLIC free-audit funnel (comprehensive=False)
    # ---------------------------------------------------------------------- #
    # This path is UNAUTHENTICATED. Anyone on the internet can trigger it with an
    # email address, so whatever it spends per run is multiplied by whatever
    # volume an abuser chooses. It runs ``--mode free``.
    #
    # WHAT THIS REPLACED, and why (P0-2 / AUD-001 / AUD-002 / MT-005 / ADM-026):
    # it previously forced ``engine_mode = "auto"`` with ``--serper --places
    # --citations --psi`` and ``--profile local``, i.e. the caller asked for
    # ``mode="free"`` and this function silently UPGRADED it to a paid-provider
    # run. Combined with a hardcoded ``0.0`` in the worker's cost commit, the
    # platform spent real Serper and Google Places money on every anonymous
    # request and recorded $0.00 against it - a denial-of-wallet vector with no
    # ledger entry to notice it by.
    #
    # ``--mode free`` is the ENGINE-SIDE guarantee, not merely a caller-side
    # intention: the CLI hard-clears psi/moz/serper/places/citations after
    # parsing, so no future flag added here can reintroduce paid spend on this
    # path. Belt and braces, the paid flags are also passed explicitly off.
    #
    # Because the engine then reports ``mode="free"`` in run.json,
    # ``pricing.audit_cost`` returns 0.0 from the run's OWN reported mode. The
    # zero in the cost ledger is therefore DERIVED and true, not asserted - and
    # if this path is ever re-widened to a paid mode, the recorded cost becomes
    # non-zero automatically instead of silently staying at zero.
    #
    # SCOPE (DECISIONS_LOG D-1): free = CONDENSED (~10-15 pages). The full
    # multi-agent narrative run is the paid, authenticated product.
    #
    # KNOWN ENGINE INCONSISTENCY: the engine's own ``--mode`` help text says free
    # mode keeps "free PSI (rate-limited)", but the code sets ``psi = False``.
    # PageSpeed is genuinely free-tier, so a condensed free audit could carry
    # Core Web Vitals. Not changed here: the audit engine is a separate product
    # with its own CI and is explicitly out of the recovery's change scope.
    # `mode` is HONOURED here, never overridden. The bug this replaced was
    # precisely a silent override in this spot - the caller asked for "free" and
    # got "auto" with every provider on. Hardcoding "free" instead would be the
    # same mistake mirrored: a caller asking for "paid" would be silently
    # downgraded. The light path is public-only today, but the function stays a
    # faithful function of its arguments.
    paid = mode == "paid"
    provider_flags = (
        ["--psi", "--serper", "--places", "--citations"]
        if paid
        else ["--no-psi", "--no-serper", "--no-places", "--no-citations"]
    )
    return [
        "-m", "audit_engine.cli.main", "full", domain,
        "--profile", profile, "--max-pages", str(max_pages), "--no-moz",
        "--mode", "paid" if paid else "free",
        *provider_flags,
        # No AI fan-out on the light path in either mode: the 21 specialist agents
        # and the narrative are the comprehensive (authenticated) product.
        "--agents", "off", "--ai-narrative", "off",
    ]


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


def _find_html(artifact_dir: Path) -> str | None:
    for name in _HTML_CANDIDATES:
        candidate = artifact_dir / name
        if candidate.is_file():
            return str(candidate)
    return None


def run_audit(
    cfg: AuditEngineConfig,
    *,
    url: str,
    tier: str,
    comprehensive: bool = False,
    depth: str | None = None,
    max_pages: int | None = None,
) -> AuditRunResult:
    """Run one audit end-to-end and return a typed result (never raises).

    ``tier`` is the stored value (``free`` | ``paid``); it selects the engine
    ``--mode`` for the light path. ``comprehensive=True`` runs the consulting
    pipeline for the authenticated dashboard audit; ``depth`` then decides how
    much of the paid pipeline it buys (see ``build_argv``). The URL is
    SSRF-validated here (defense in depth - the endpoint already validated at
    enqueue) before any subprocess is spawned.

    ``max_pages`` is the PER-RUN breadth, snapshotted onto the audit row at
    enqueue from its depth (migration 0084). It overrides the config default so
    two runs launched minutes apart can legitimately differ - which the previous
    arrangement could not express, because breadth came from one process-wide
    setting read at run time. Omitted (or non-positive) falls back to the config
    default, which is what every caller predating the depth axis gets: unchanged
    behaviour, including the public funnel's condensed crawl.
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

    # `free` depth spends nothing, so it runs `--mode free` even on the
    # authenticated path. The flags in `DEPTH_SCOPE` already turn every provider
    # off; `--mode free` is the ENGINE-SIDE guarantee on top - the CLI hard-clears
    # psi/moz/serper/places/citations after parsing, so no flag added here later
    # can reintroduce spend on a run the operator was told is free. It also makes
    # the recorded cost DERIVED rather than asserted: `pricing.audit_cost` reads
    # the mode the run itself reported, so a zero in the ledger is true by
    # construction.
    if comprehensive and (depth or "standard") == "free":
        mode = "free"
    else:
        mode = "paid" if (tier == "paid" or comprehensive) else "free"
    # The public funnel crawls the condensed breadth; the authenticated audit
    # keeps the full one. Selected here (not inside build_argv) so the argv
    # builder stays a pure function of its arguments.
    pages = cfg.max_pages if comprehensive else cfg.free_max_pages
    if max_pages is not None and max_pages > 0:
        pages = max_pages
    argv = build_argv(
        domain=url, mode=mode, max_pages=pages, profile=cfg.profile,
        comprehensive=comprehensive, depth=depth,
    )

    child_env = {**os.environ, "COLUMNS": "1000", "PYTHONIOENCODING": "utf-8"}
    started = time.monotonic()
    logger.info("audit_engine_start", mode=mode, max_pages=pages)
    try:
        proc = subprocess.run(
            [cfg.engine_python, *argv],
            cwd=cfg.engine_dir,
            capture_output=True,
            text=True,
            # DECODE AS UTF-8 EXPLICITLY. The child is already told to WRITE utf-8
            # (PYTHONIOENCODING above), but `text=True` alone decodes with the parent's
            # locale codec -- cp1252 on Windows. `rich` prints box-drawing glyphs, whose
            # bytes are undefined in cp1252, so the read raised UnicodeDecodeError, the
            # "Run UUID:" line was never parsed, and EVERY audit (free and paid) failed
            # with "could not parse run UUID from engine output". errors="replace" means
            # an odd byte can never again turn a finished audit into a failed one.
            encoding="utf-8",
            errors="replace",
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
        html_path=_find_html(artifact_dir),
        runtime_seconds=elapsed,
        exit_code=0,
        pages_crawled=int(run_meta["pages_crawled"])
        if isinstance(run_meta.get("pages_crawled"), (int, float))
        else 0,
        mode=str(run_meta.get("mode") or ""),
        usage=usage if isinstance(usage, dict) else {},
    )
