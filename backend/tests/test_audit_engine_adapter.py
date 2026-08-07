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


def test_build_argv_free_is_zero_spend() -> None:
    argv = build_argv(domain="example.com", mode="free", max_pages=20, profile="general")
    assert argv[:4] == ["-m", "audit_engine.cli.main", "full", "example.com"]
    assert "--mode" in argv and argv[argv.index("--mode") + 1] == "free"
    # explicit, deterministic, and paid providers OFF
    for flag in ("--no-moz", "--no-serper", "--no-places", "--no-citations"):
        assert flag in argv
    assert argv[argv.index("--agents") + 1] == "off"
    assert argv[argv.index("--ai-narrative") + 1] == "off"
    assert argv[argv.index("--max-pages") + 1] == "20"


def test_build_argv_paid_enables_providers() -> None:
    argv = build_argv(domain="example.com", mode="paid", max_pages=100, profile="local")
    assert argv[argv.index("--mode") + 1] == "paid"
    for flag in ("--serper", "--places", "--citations"):
        assert flag in argv
    assert "--no-serper" not in argv
    assert argv[argv.index("--profile") + 1] == "local"


def test_build_argv_comprehensive_empty_is_full_audit() -> None:
    # Empty selection = the FULL comprehensive run: every provider + all agents.
    argv = build_argv(
        domain="example.com", mode="paid", max_pages=100, profile="general",
        comprehensive=True, types=[],
    )
    assert argv[argv.index("--mode") + 1] == "paid"
    for flag in ("--serper", "--places", "--citations"):
        assert flag in argv
    assert argv[argv.index("--agents") + 1] == "on"
    assert argv[argv.index("--ai-narrative") + 1] == "on"


def test_build_argv_scoped_local_forces_profile_and_places() -> None:
    # Local SEO selected -> profile local + Places/citations on; no Serper; agents off.
    argv = build_argv(
        domain="example.com", mode="paid", max_pages=100, profile="general",
        comprehensive=True, types=["local"],
    )
    assert argv[argv.index("--profile") + 1] == "local"
    for flag in ("--places", "--citations"):
        assert flag in argv
    assert "--no-serper" in argv
    assert argv[argv.index("--agents") + 1] == "off"
    assert argv[argv.index("--ai-narrative") + 1] == "off"


def test_build_argv_scoped_offpage_enables_serper_only() -> None:
    argv = build_argv(
        domain="example.com", mode="paid", max_pages=100, profile="general",
        comprehensive=True, types=["offpage"],
    )
    assert "--serper" in argv and "--no-serper" not in argv
    assert "--no-places" in argv and "--no-citations" in argv
    assert argv[argv.index("--profile") + 1] == "general"  # not forced to local
    assert argv[argv.index("--agents") + 1] == "off"


def test_build_argv_scoped_geo_turns_agents_on() -> None:
    argv = build_argv(
        domain="example.com", mode="paid", max_pages=100, profile="general",
        comprehensive=True, types=["geo"],
    )
    assert argv[argv.index("--agents") + 1] == "on"
    assert "--no-serper" in argv  # geo needs agents, not Serper


def test_build_argv_scoped_strategy_serper_agents_and_narrative() -> None:
    argv = build_argv(
        domain="example.com", mode="paid", max_pages=100, profile="general",
        comprehensive=True, types=["strategy"],
    )
    assert "--serper" in argv and "--no-serper" not in argv
    assert argv[argv.index("--agents") + 1] == "on"
    assert argv[argv.index("--ai-narrative") + 1] == "on"


def test_build_argv_scoped_technical_toggles_psi() -> None:
    with_tech = build_argv(
        domain="example.com", mode="paid", max_pages=100, profile="general",
        comprehensive=True, types=["technical"],
    )
    assert "--psi" in with_tech and "--no-psi" not in with_tech
    without_tech = build_argv(
        domain="example.com", mode="paid", max_pages=100, profile="general",
        comprehensive=True, types=["onpage"],
    )
    assert "--no-psi" in without_tech


def test_run_audit_forwards_types_to_argv(
    engine: AuditEngineConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    url = "https://example.com"
    captured: dict[str, list[str]] = {}

    def _side(args: list[str], kwargs: dict[str, Any]) -> None:
        captured["argv"] = args
        _write_artifacts(engine.engine_dir, url, _UUID, scores={"overall": 70})

    _fake_run_factory(monkeypatch, returncode=0, stdout=f"Run UUID: {_UUID}\n", side=_side)
    res = run_audit(engine, url=url, tier="paid", comprehensive=True, types=["local"])
    assert res.ok is True
    argv = captured["argv"]
    assert argv[argv.index("--profile") + 1] == "local"  # local scoping reached the engine
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
