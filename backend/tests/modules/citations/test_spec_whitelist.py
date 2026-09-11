"""The retired bot's replacement behavior, pinned.

Until Phase 3 (plan C1) a `bot:*` row was dispatched to a Playwright engine gated on
the earned-spec whitelist. The engine is DELETED — stealth args, fingerprint masking,
CAPTCHA solving, proxy and all — so the pins here are about what replaced it:

* a form-route row goes STRAIGHT to the operator queue (`ready_for_human`) with the
  honest code `human_queue` — before the cost gate, so it is free;
* it never passes through `submitting` (no browser ever drives it);
* the earned specs survive as EXTENSION AUTOFILL data (`integrations.directory_specs`),
  fail-closed exactly as before: no active row, no selectors.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.config import Settings
from app.modules.citations.tasks import execute_citation_submit
from integrations.citation_submitters import CitationJob
from integrations.directory_specs import FormField, FormSpec, db_spec_loader

pytestmark = pytest.mark.unit


def _job(directory: str = "Brownbook") -> CitationJob:
    return CitationJob(
        directory_name=directory, directory_url="brownbook.net", market="US",
        submit_method="bot:playwright", business_name="Acme Dental",
        address_line1="123 Main St", address_line2="", city="Bellevue", region="WA",
        postal_code="98004", phone="555-0100", website_url="https://acme.example",
        categories=("dentist",), client_id="cl",
    )


class _FakeStore:
    def __init__(self, row: dict[str, Any]) -> None:
        self.row = row
        self.updates: dict[str, Any] = {}

    def load_citation_with_directory(self, citation_id: str) -> dict[str, Any]:
        return self.row

    def update_citation(self, citation_id: str, fields: dict[str, Any]) -> None:
        self.updates.update(fields)


def _row(**over: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "id": "c1", "client_id": "cl", "client_name": "Acme",
        "submit_status": "queued", "submit_method": "bot:playwright",
        "directory_name": "Brownbook", "directory_url": "brownbook.net",
        "directory_tier": "bot_fillable", "directory_route": "C",
        "bp_business_name": "Acme Dental", "bp_address_line1": "123 Main St",
        "bp_address_line2": "", "bp_city": "Bellevue", "bp_region": "WA",
        "bp_postal_code": "98004", "bp_phone": "555-0100",
        "bp_website_url": "https://acme.example", "bp_categories": ["dentist"],
        "external_ref": None,
    }
    row.update(over)
    return row


# --------------------------------------------------------------------------- #
# THE ECONOMICS, unchanged in spirit: routing a form row to a person must be FREE.
# --------------------------------------------------------------------------- #
def test_a_form_route_row_goes_to_the_queue_before_the_cost_gate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The defect this ordering exists to prevent survives the retirement: nothing may
    be charged for a submission no machine will make."""
    import app.modules.citations.tasks as tasks

    gate_calls: list[str] = []

    class _Gate:
        def evaluate(self, ctx: Any) -> Any:
            gate_calls.append("evaluate")
            raise AssertionError("the cost gate must not be reached for a form-route row")

        def commit(self, ctx: Any, cost: float) -> None:
            gate_calls.append("commit")

    monkeypatch.setattr(tasks, "_gate", lambda: _Gate())
    store = _FakeStore(_row())
    out = execute_citation_submit(store, Settings(_env_file=None, app_env="dev"), "c1")  # type: ignore[call-arg]

    assert gate_calls == [], "nothing may be charged for human-queue work"
    assert out["state"] == "ready_for_human"
    assert store.updates["submit_status"] == "ready_for_human"
    # The HONEST code: this is a person's work by design, not an engine gap.
    assert store.updates["blocked_reason"] == "human_queue"
    assert "retired" in store.updates["error"]


def test_the_row_never_reaches_submitting_on_a_form_route() -> None:
    """`submitting` means an engine is driving a submission. There is no engine for a
    form row any more, so the status must go straight to the queue — an operator
    watching the board must never read 'work starting' for work no machine does."""
    seen: list[str] = []

    class _Store(_FakeStore):
        def update_citation(self, citation_id: str, fields: dict[str, Any]) -> None:
            if "submit_status" in fields:
                seen.append(str(fields["submit_status"]))
            super().update_citation(citation_id, fields)

    execute_citation_submit(_Store(_row()), Settings(_env_file=None, app_env="dev"), "c1")  # type: ignore[call-arg]
    assert "submitting" not in seen
    assert seen == ["ready_for_human"]


def test_every_bot_era_method_lands_in_the_queue() -> None:
    """`bot:signup` too: the signup engine was deleted with the bot (it inherited the
    anti-detection wholesale and no catalogue row ever routed to it)."""
    for method in ("bot:playwright", "bot:signup", "aggregator:data_axle", "manual"):
        store = _FakeStore(_row(submit_method=method))
        out = execute_citation_submit(store, Settings(_env_file=None, app_env="dev"), "c1")  # type: ignore[call-arg]
        assert out["state"] == "ready_for_human", method
        assert store.updates["blocked_reason"] == "human_queue", method


def test_fed_by_aggregator_is_still_never_offered_as_work() -> None:
    store = _FakeStore(_row(submit_method="aggregator:fed_by_data_axle"))
    out = execute_citation_submit(store, Settings(_env_file=None, app_env="dev"), "c1")  # type: ignore[call-arg]
    assert out["state"] == "blocked"
    assert store.updates["blocked_reason"] == "fed_by_aggregator"


# --------------------------------------------------------------------------- #
# The earned specs survive as autofill data, fail-closed.
# --------------------------------------------------------------------------- #
def test_the_spec_loader_fails_closed_to_no_autofill(monkeypatch: pytest.MonkeyPatch) -> None:
    """No active row (or no reachable database) means NO selectors — the queue then
    shows copy-buttons, never a fabricated selector."""
    import integrations.directory_specs as ds

    monkeypatch.setattr(ds, "active_form_specs", lambda **kw: {})
    assert db_spec_loader(_job()) is None


def test_the_spec_loader_serves_an_active_spec_by_directory_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import integrations.directory_specs as ds

    spec = FormSpec(
        directory_name="Brownbook", url="https://brownbook.net/add",
        fields=(FormField("input[name='business_name']", "business_name"),),
        submit_selector="#go", success_indicator="text=thanks",
    )
    monkeypatch.setattr(ds, "active_form_specs", lambda **kw: {"Brownbook": spec})
    loaded = db_spec_loader(_job("Brownbook"))
    assert loaded is spec


def test_a_legacy_captcha_key_in_the_stored_spec_is_ignored() -> None:
    """0108 rows written in the bot era may carry a `captcha` block. Nothing solves
    CAPTCHAs any more, so rehydration reads the fields and drops the key rather than
    resurrecting a solver dependency."""
    from integrations.directory_specs import spec_from_json

    spec = spec_from_json(
        {
            "url": "https://brownbook.net/add",
            "fields": [{"selector": "#name", "value_key": "business_name"}],
            "submit_selector": "#go",
            "success_indicator": "text=thanks",
            "captcha": {"kind": "recaptcha_v2", "site_key_selector": ".g-recaptcha"},
        },
        "Brownbook",
    )
    assert spec.fields == (FormField("#name", "business_name"),)
    assert not hasattr(spec, "captcha")
