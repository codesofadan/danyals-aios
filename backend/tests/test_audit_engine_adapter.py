"""P3-2 gate: the audit-engine adapter - argv, stdout parsing, and the run
lifecycle with the subprocess MOCKED (no real engine, no network)."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

import integrations.audit_engine as ae
from integrations.audit_engine import (
    AuditEngineConfig,
    build_argv,
    domain_to_slug,
    parse_run_uuid,
    run_audit,
)

pytestmark = pytest.mark.unit

_UUID = "1234abcd-1234-4abc-8def-1234567890ab"


def test_domain_to_slug() -> None:
    assert domain_to_slug("https://example.com/") == "example.com"
    assert domain_to_slug("http://example.com/shop") == "example.com_shop"
    assert domain_to_slug("example.com") == "example.com"


def test_build_argv_public_funnel_is_condensed_and_spends_nothing() -> None:
    """P0-2: the UNAUTHENTICATED funnel must reach no paid provider.

    This test previously asserted the DEFECT: it required ``--mode auto`` with
    ``--serper --places --citations --psi`` on, because the funnel had been
    widened to a "comprehensive lead-gen audit" without anyone costing it. The
    worker then committed a hardcoded $0.00, so the spend was invisible. Per
    DECISIONS_LOG D-1 the free audit is CONDENSED and genuinely free.
    """
    argv = build_argv(domain="example.com", mode="free", max_pages=15, profile="general")
    assert argv[:4] == ["-m", "audit_engine.cli.main", "full", "example.com"]

    # `--mode free` is the ENGINE-SIDE guarantee: the CLI hard-clears
    # psi/moz/serper/places/citations after parsing, so no flag added here later
    # can reintroduce paid spend on this path.
    assert argv[argv.index("--mode") + 1] == "free"

    # Belt and braces: every paid integration is ALSO passed explicitly off, so
    # the intent is readable in the command line an operator sees in a log.
    for flag in ("--no-psi", "--no-serper", "--no-places", "--no-citations", "--no-moz"):
        assert flag in argv, f"{flag} missing — the free funnel could spend"
    for flag in ("--serper", "--places", "--citations", "--psi"):
        assert flag not in argv, f"{flag} present — the free funnel would spend"

    # `--profile local` is what unlocks Places + citations in the engine; the free
    # path must not request it.
    assert argv[argv.index("--profile") + 1] == "general"

    # No AI fan-out either: agents and narrative are the other paid dimension.
    assert argv[argv.index("--agents") + 1] == "off"
    assert argv[argv.index("--ai-narrative") + 1] == "off"

    # Condensed breadth (D-1: ~10-15 pages), not the paid audit's full crawl.
    assert argv[argv.index("--max-pages") + 1] == "15"


def test_the_free_funnel_uses_its_own_crawl_breadth() -> None:
    """`free_max_pages` is a SEPARATE knob from `max_pages` on purpose.

    Sharing one would mean raising the paid audit's depth silently widens an
    unauthenticated, unbilled crawl.
    """
    from integrations.audit_engine import AuditEngineConfig

    cfg = AuditEngineConfig(engine_dir="/x", engine_python="/x/py")
    assert cfg.free_max_pages < cfg.max_pages
    assert cfg.free_max_pages <= 15  # DECISIONS_LOG D-1: "condensed, ~10-15 pages"


def test_build_argv_paid_enables_providers() -> None:
    argv = build_argv(domain="example.com", mode="paid", max_pages=100, profile="local")
    assert argv[argv.index("--mode") + 1] == "paid"
    for flag in ("--serper", "--places", "--citations"):
        assert flag in argv
    assert "--no-serper" not in argv
    assert argv[argv.index("--profile") + 1] == "local"


def test_build_argv_deep_is_the_full_audit() -> None:
    # `deep` = every provider + all agents + the narrative.
    argv = build_argv(
        domain="example.com", mode="paid", max_pages=100, profile="general",
        comprehensive=True, depth="deep",
    )
    assert argv[argv.index("--mode") + 1] == "paid"
    for flag in ("--serper", "--places", "--citations"):
        assert flag in argv
    assert argv[argv.index("--agents") + 1] == "on"
    assert argv[argv.index("--ai-narrative") + 1] == "on"
    # Places/citations are gated behind the profile, not the flag: passing
    # `--places` under `--profile general` is accepted and then does nothing.
    assert argv[argv.index("--profile") + 1] == "local"


def test_build_argv_standard_buys_corroboration_not_agents() -> None:
    argv = build_argv(
        domain="example.com", mode="paid", max_pages=100, profile="general",
        comprehensive=True, depth="standard",
    )
    assert "--psi" in argv and "--no-psi" not in argv
    assert "--serper" in argv and "--no-serper" not in argv
    assert "--no-places" in argv and "--no-citations" in argv
    assert argv[argv.index("--profile") + 1] == "general"  # not forced to local
    assert argv[argv.index("--agents") + 1] == "off"
    assert argv[argv.index("--ai-narrative") + 1] == "off"


def test_build_argv_free_depth_fires_no_paid_work_at_all() -> None:
    argv = build_argv(
        domain="example.com", mode="free", max_pages=15, profile="general",
        comprehensive=True, depth="free",
    )
    # The mode the caller resolved, NOT a hardcoded "paid". This branch used to
    # pin it, so a run described to the operator as free was handed to the engine
    # as paid - the asked-for-free-got-paid shape WU-7 removed from the funnel.
    assert argv[argv.index("--mode") + 1] == "free"
    for flag in ("--no-psi", "--no-serper", "--no-places", "--no-citations"):
        assert flag in argv
    assert argv[argv.index("--agents") + 1] == "off"
    assert argv[argv.index("--ai-narrative") + 1] == "off"


def test_build_argv_defaults_an_unknown_depth_to_standard() -> None:
    # A row written before the depth axis carries NULL. Standard is what those
    # runs already did; inventing `deep` would spend money retroactively.
    argv = build_argv(
        domain="example.com", mode="paid", max_pages=100, profile="general",
        comprehensive=True, depth=None,
    )
    assert argv[argv.index("--agents") + 1] == "off"
    assert "--serper" in argv


def test_run_audit_forwards_depth_to_argv(
    engine: AuditEngineConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    url = "https://example.com"
    captured: dict[str, list[str]] = {}

    def _side(args: list[str], kwargs: dict[str, Any]) -> None:
        captured["argv"] = args
        _write_artifacts(engine.engine_dir, url, _UUID, scores={"overall": 70})

    _fake_run_factory(monkeypatch, returncode=0, stdout=f"Run UUID: {_UUID}\n", side=_side)
    res = run_audit(engine, url=url, tier="paid", comprehensive=True, depth="deep")
    assert res.ok is True
    argv = captured["argv"]
    assert argv[argv.index("--profile") + 1] == "local"
    assert "--places" in argv


def test_parse_run_uuid() -> None:
    assert parse_run_uuid(f"some rule\nRun UUID: {_UUID}\nArtifact dir: /x") == _UUID
    assert parse_run_uuid("no uuid here") is None


@pytest.fixture
def engine(tmp_path: Path) -> AuditEngineConfig:
    py = tmp_path / "python.exe"
    py.write_text("", encoding="utf-8")  # just needs to exist; subprocess is mocked
    return AuditEngineConfig(
        engine_dir=str(tmp_path), engine_python=str(py), timeout_seconds=60, max_pages=10
    )


def _write_artifacts(
    engine_dir: str, domain: str, uuid: str, *, scores: dict[str, Any], pdf: bool = True
) -> Path:
    art = Path(engine_dir) / "data" / "audits" / domain_to_slug(domain) / uuid
    art.mkdir(parents=True, exist_ok=True)
    (art / "run.json").write_text(json.dumps({"scores": scores}), encoding="utf-8")
    (art / "findings.json").write_text(json.dumps([{"check_id": "TECH-001"}]), encoding="utf-8")
    if pdf:
        (art / "report-consolidated.pdf").write_bytes(b"%PDF-1.4 fake")
    return art


def _fake_run_factory(
    monkeypatch: pytest.MonkeyPatch, *, returncode: int, stdout: str, side: Any = None
) -> None:
    # public-host guard must not hit DNS in a unit test
    monkeypatch.setattr(ae, "validate_public_host", lambda url: url)

    def _fake_run(args: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        if side is not None:
            side(args, kwargs)
        return subprocess.CompletedProcess(args=args, returncode=returncode, stdout=stdout, stderr="")

    monkeypatch.setattr(ae.subprocess, "run", _fake_run)


def test_run_audit_success(engine: AuditEngineConfig, monkeypatch: pytest.MonkeyPatch) -> None:
    url = "https://example.com"

    def _side(args: list[str], kwargs: dict[str, Any]) -> None:
        # the engine writes artifacts before it exits
        _write_artifacts(engine.engine_dir, url, _UUID, scores={"overall": 82.4, "technical": 90})
        assert kwargs["cwd"] == engine.engine_dir
        assert kwargs["env"]["COLUMNS"] == "1000"  # anti-wrap guard set

    _fake_run_factory(monkeypatch, returncode=0, stdout=f"Run UUID: {_UUID}\n", side=_side)

    res = run_audit(engine, url=url, tier="free")
    assert res.ok is True
    assert res.run_uuid == _UUID
    assert res.score == 82  # round(82.4)
    assert res.scores["technical"] == 90
    assert res.pdf_path is not None and res.pdf_path.endswith("report-consolidated.pdf")
    assert res.findings_path is not None and res.findings_path.endswith("findings.json")
    assert res.exit_code == 0


def test_run_audit_timeout_marks_failed(
    engine: AuditEngineConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(ae, "validate_public_host", lambda url: url)

    def _raise(args: list[str], **kwargs: Any) -> None:
        raise subprocess.TimeoutExpired(cmd=args, timeout=60)

    monkeypatch.setattr(ae.subprocess, "run", _raise)
    res = run_audit(engine, url="https://example.com", tier="paid")
    assert res.ok is False
    assert res.error is not None and "timed out" in res.error


def test_run_audit_nonzero_exit_marks_failed(
    engine: AuditEngineConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    _fake_run_factory(monkeypatch, returncode=1, stdout=f"Run UUID: {_UUID}\n")
    res = run_audit(engine, url="https://example.com", tier="free")
    assert res.ok is False
    assert res.exit_code == 1
    assert res.run_uuid == _UUID  # captured for cleanup even on failure


def test_run_audit_missing_run_json_marks_failed(
    engine: AuditEngineConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    # exit 0 + a uuid, but the engine crashed before writing run.json
    _fake_run_factory(monkeypatch, returncode=0, stdout=f"Run UUID: {_UUID}\n")
    res = run_audit(engine, url="https://example.com", tier="free")
    assert res.ok is False
    assert res.error is not None and "run.json" in res.error


def test_run_audit_rejects_private_url(engine: AuditEngineConfig) -> None:
    # real SSRF guard, literal private IP -> no DNS, no subprocess
    res = run_audit(engine, url="http://127.0.0.1/admin", tier="free")
    assert res.ok is False
    assert res.error is not None and "rejected" in res.error


def test_run_audit_unconfigured_engine(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ae, "validate_public_host", lambda url: url)
    cfg = AuditEngineConfig(engine_dir="", engine_python="")
    res = run_audit(cfg, url="https://example.com", tier="free")
    assert res.ok is False
    assert res.error is not None and "not configured" in res.error
