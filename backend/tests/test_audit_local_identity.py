"""The audit must look up the GBP of the business the platform actually holds.

THE DEFECT. The worker passed ``business_name=row["client_name"]`` - the CRM DISPLAY
name, whatever an operator typed into the client list ("Acme (retainer)", "Smith -
Dental") - and no city at all, with the comment "the engine's domain check is what
actually proves identity". But the domain check is a VERIFIER, not a finder: it can only
confirm or reject whichever candidates a text search returned, and a bad query returns
five wrong ones for it to reject.

Meanwhile ``client_business_profiles`` holds the client's canonical registered name,
city, region and phone - the same record the citations module submits to directories. If
the audit and the citation builder disagree about the business's name, they are auditing
and building listings for two different businesses.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.config import Settings
from app.services.cost_gate import GateDecision
from integrations.audit_engine import AuditEngineConfig, AuditRunResult, build_argv
from workers.tasks.audit import execute_audit, resolve_local_identity

pytestmark = pytest.mark.unit


class _Store:
    """The row + profile seam, recording what was asked for."""

    def __init__(
        self, row: dict[str, Any] | None, profile: dict[str, Any] | None = None
    ) -> None:
        self.row = row
        self.profile = profile
        self.lookups: list[str] = []
        self.updates: list[dict[str, Any]] = []

    def load(self, audit_id: str) -> dict[str, Any] | None:
        return self.row

    def update(self, audit_id: str, fields: dict[str, Any]) -> None:
        self.updates.append(fields)
        if self.row is not None:
            self.row.update(fields)

    def evaluate(self, row: dict[str, Any], cost: float) -> GateDecision:
        return GateDecision("call", cost=cost)

    def record_cost(self, row: dict[str, Any], cost: float) -> None:
        return None

    def business_profile(self, client_id: str) -> dict[str, Any] | None:
        self.lookups.append(client_id)
        return self.profile


class _StoreWithoutProfiles(_Store):
    """A store predating the profile lookup - the Protocol is structural, so nothing
    forces the method to exist and a missing one must DEGRADE, not raise."""

    business_profile = None  # type: ignore[assignment]


def _row(**over: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "id": "aud-1",
        "url": "https://smithdental.com",
        "tier": "paid",
        "status": "queued",
        "client_id": "cl-1",
        "client_name": "Smith - Dental (retainer)",
        "is_local_business": True,
    }
    row.update(over)
    return row


def _profile(**over: Any) -> dict[str, Any]:
    profile: dict[str, Any] = {
        "business_name": "Smith Family Dental",
        "city": "Austin",
        "region": "TX",
        "postal_code": "78701",
        "phone": "+1 512-555-0100",
    }
    profile.update(over)
    return profile


def _settings() -> Settings:
    return Settings(_env_file=None, app_env="dev", audit_paid_cost_estimate=1.5)


# --------------------------------------------------------------------------- #
# The resolver.
# --------------------------------------------------------------------------- #
def test_the_canonical_business_name_and_city_beat_the_crm_display_name() -> None:
    """THE fix. Re-inject by returning row["client_name"] and this fails."""
    store = _Store(_row(), _profile())
    name, city = resolve_local_identity(store, _row())
    assert name == "Smith Family Dental"
    assert city == "Austin"
    assert store.lookups == ["cl-1"]


def test_a_client_with_no_profile_falls_back_to_the_display_name() -> None:
    """Exactly today's behaviour for a client nobody has filled a NAP in for - the fix
    must not make an unprofiled client worse."""
    name, city = resolve_local_identity(_Store(_row(), None), _row())
    assert name == "Smith - Dental (retainer)"
    assert city == ""


def test_a_profile_with_a_blank_name_falls_back_to_the_display_name() -> None:
    store = _Store(_row(), _profile(business_name="   "))
    name, city = resolve_local_identity(store, _row())
    assert name == "Smith - Dental (retainer)"
    assert city == "Austin"  # a known city is still worth sending


def test_no_client_id_means_no_lookup_at_all() -> None:
    store = _Store(_row(client_id=None), _profile())
    name, city = resolve_local_identity(store, _row(client_id=None))
    assert name == "Smith - Dental (retainer)"
    assert city == ""
    assert store.lookups == []


def test_a_lookup_failure_degrades_instead_of_failing_the_audit() -> None:
    """An audit of a SaaS client has nothing to do with local SEO; a NAP lookup hiccup
    must not fail it."""

    class _Exploding(_Store):
        def business_profile(self, client_id: str) -> dict[str, Any] | None:
            raise RuntimeError("db down")

    name, city = resolve_local_identity(_Exploding(_row(), None), _row())
    assert name == "Smith - Dental (retainer)"
    assert city == ""


def test_a_store_without_the_method_degrades_rather_than_raising() -> None:
    """`AuditStore` is a Protocol: nothing structurally forces the method to exist, so
    the absence is asked about explicitly rather than caught as an AttributeError."""
    name, city = resolve_local_identity(_StoreWithoutProfiles(_row(), None), _row())
    assert name == "Smith - Dental (retainer)"
    assert city == ""


# --------------------------------------------------------------------------- #
# End to end: what the runner is actually handed.
# --------------------------------------------------------------------------- #
def test_the_worker_hands_the_engine_the_canonical_name_and_city() -> None:
    seen: dict[str, Any] = {}

    def _runner(
        cfg: AuditEngineConfig,
        *,
        url: str,
        tier: str,
        comprehensive: bool = False,
        depth: str | None = None,
        max_pages: int | None = None,
        business_name: str | None = None,
        city: str | None = None,
        is_local_business: bool = False,
    ) -> AuditRunResult:
        seen.update(business_name=business_name, city=city, is_local=is_local_business)
        return AuditRunResult(
            ok=True, run_uuid="u-1", artifact_dir="/art/u-1", score=70,
            scores={"overall": 70}, runtime_seconds=10, exit_code=0,
        )

    store = _Store(_row(), _profile())
    execute_audit(store, _settings(), "aud-1", runner=_runner)
    assert seen["business_name"] == "Smith Family Dental"
    assert seen["city"] == "Austin"
    assert seen["is_local"] is True


def test_an_unprofiled_client_sends_no_city_rather_than_an_empty_string() -> None:
    """None, not '': `build_argv` skips a falsy city either way, but passing '' through
    the runner boundary invites a caller to treat it as a real answer."""
    seen: dict[str, Any] = {}

    def _runner(cfg: Any, **kw: Any) -> AuditRunResult:
        seen.update(kw)
        return AuditRunResult(ok=True, run_uuid="u-1", artifact_dir="/a", score=1,
                              scores={}, runtime_seconds=1, exit_code=0)

    execute_audit(_Store(_row(), None), _settings(), "aud-1", runner=_runner)
    assert seen["city"] is None


# --------------------------------------------------------------------------- #
# The argv the engine receives.
# --------------------------------------------------------------------------- #
def test_the_city_reaches_the_engine_as_a_flag() -> None:
    argv = build_argv(
        domain="https://smithdental.com", mode="paid", max_pages=40, profile="general",
        comprehensive=True, depth="deep", business_name="Smith Family Dental",
        city="Austin", is_local_business=True,
    )
    assert "--business-name" in argv
    assert argv[argv.index("--business-name") + 1] == "Smith Family Dental"
    assert "--city" in argv
    assert argv[argv.index("--city") + 1] == "Austin"
    # And the local pipeline is actually unlocked, or the name/city buy nothing.
    assert "--profile" in argv and argv[argv.index("--profile") + 1] == "local"
    assert "--places" in argv


def test_a_non_local_client_gets_no_local_pipeline_however_good_the_name_is() -> None:
    """A SaaS client must not pay for Places lookups about a GBP it does not have."""
    argv = build_argv(
        domain="https://saas.example", mode="paid", max_pages=40, profile="general",
        comprehensive=True, depth="deep", business_name="Acme Cloud", city="Austin",
        is_local_business=False,
    )
    assert "--no-places" in argv
    assert argv[argv.index("--profile") + 1] != "local"


def test_a_blank_name_or_city_is_not_passed_as_an_empty_flag() -> None:
    argv = build_argv(
        domain="https://x.example", mode="paid", max_pages=40, profile="general",
        comprehensive=True, depth="deep", business_name="   ", city="",
        is_local_business=True,
    )
    assert "--business-name" not in argv
    assert "--city" not in argv
