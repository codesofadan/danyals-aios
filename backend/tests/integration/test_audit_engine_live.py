"""Integration: run one tiny REAL audit through the external engine.

Auto-skips unless AUDIT_ENGINE_DIR + AUDIT_ENGINE_PYTHON are set AND that
interpreter exists (the engine is a separate product with its own venv, so this
never runs in the default suite). It shells out to the engine for real - no
mocking - on a Free-tier (zero paid-spend) run against a small public site, and
asserts the adapter parses the engine's self-minted run_uuid + artifact dir and
reads the composite score. Override the target with AUDIT_LIVE_URL.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from integrations.audit_engine import AuditEngineConfig, run_audit

_LIVE_URL = os.environ.get("AUDIT_LIVE_URL", "https://example.com")


def _require_engine() -> AuditEngineConfig:
    engine_dir = os.environ.get("AUDIT_ENGINE_DIR")
    engine_python = os.environ.get("AUDIT_ENGINE_PYTHON")
    if not engine_dir or not engine_python or not Path(engine_python).exists():
        pytest.skip("audit engine not configured (AUDIT_ENGINE_DIR + AUDIT_ENGINE_PYTHON)")
    return AuditEngineConfig(
        engine_dir=engine_dir,
        engine_python=engine_python,
        timeout_seconds=int(os.environ.get("AUDIT_LIVE_TIMEOUT", "600")),
        max_pages=int(os.environ.get("AUDIT_LIVE_MAX_PAGES", "3")),
        profile="general",
    )


@pytest.mark.integration
def test_live_free_audit_end_to_end() -> None:
    cfg = _require_engine()
    result = run_audit(cfg, url=_LIVE_URL, tier="free")

    assert result.ok, f"engine run failed: {result.error}"
    assert result.run_uuid, "adapter did not parse the engine's run UUID"
    assert result.artifact_dir and Path(result.artifact_dir).is_dir()
    # a `full` run always writes findings.json
    assert result.findings_path and Path(result.findings_path).is_file()
    # composite score is a 0-100 number, or None when nothing scored
    assert result.score is None or 0 <= result.score <= 100
