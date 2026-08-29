"""The earned whitelist: coverage as a fact rather than a claim.

`FORM_SPECS` is 50 hand-written guesses whose own docstring says none was verified
against a live DOM. Probed 2026-08-23: 29 answer 403, 8 answer 404, 6 hosts are dead.
None has ever produced a proven live listing. Defaulting the bot to that dict meant the
system claimed 50 directories of coverage and had evidence for none.

The two tests that matter most here are the economic ones: an empty whitelist must be
FREE, not expensive.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.config import Settings
from app.modules.citations.tasks import execute_citation_submit
from integrations.citation_bot import FormSpec, PlaywrightCitationSubmitter
from integrations.citation_submitters import CitationJob

pytestmark = pytest.mark.unit

playwright = pytest.importorskip("playwright", reason="the bot needs Playwright installed")


def _job(directory: str = "Brownbook") -> CitationJob:
    return CitationJob(
        directory_name=directory, directory_url="brownbook.net", market="US",
        submit_method="bot:playwright", business_name="Acme Dental",
        address_line1="123 Main St", address_line2="", city="Bellevue", region="WA",
        postal_code="98004", phone="555-0100", website_url="https://acme.example",
        categories=("dentist",), client_id="cl",
    )


def _spec(directory: str = "Brownbook") -> FormSpec:
    return FormSpec(
        directory_name=directory, url=f"https://{directory.lower()}.net/add",
        fields=(), submit_selector="#go", success_indicator="text=thanks",
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
# The bot refuses anything it has not earned.
# --------------------------------------------------------------------------- #
def test_an_unconfigured_bot_has_no_specs_and_can_submit_nothing() -> None:
    """The default USED to be the 50-entry FORM_SPECS dict, so a caller that forgot to
    wire the whitelist got maximal unverified coverage. It now gets none."""
    bot = PlaywrightCitationSubmitter()
    assert bot.can_submit(_job()) is False


def test_the_in_code_catalogue_is_never_a_fallback() -> None:
    """`Brownbook` IS in FORM_SPECS. If the fallback ever returns, this fails."""
    from integrations.citation_bot import FORM_SPECS

    assert "Brownbook" in FORM_SPECS, "fixture assumption: Brownbook is in the seed dict"
    assert PlaywrightCitationSubmitter().can_submit(_job("Brownbook")) is False


def test_an_injected_spec_is_submittable() -> None:
    bot = PlaywrightCitationSubmitter(specs={"Brownbook": _spec()})
    assert bot.can_submit(_job("Brownbook")) is True
    assert bot.can_submit(_job("Somewhere Else")) is False


def test_a_loader_that_returns_none_means_no_submission() -> None:
    bot = PlaywrightCitationSubmitter(spec_loader=lambda job: None)
    assert bot.can_submit(_job()) is False


def test_a_loader_supplying_a_spec_makes_it_submittable() -> None:
    bot = PlaywrightCitationSubmitter(spec_loader=lambda job: _spec(job.directory_name))
    assert bot.can_submit(_job("Ourbis")) is True


# --------------------------------------------------------------------------- #
# THE ECONOMICS. An empty whitelist must be free.
# --------------------------------------------------------------------------- #
def test_no_verified_spec_blocks_before_the_cost_gate_so_nothing_is_charged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The defect this ordering exists to prevent.

    Engine resolution used to run AFTER the gate: the gate charged, the row went to
    `submitting`, and only then did the worker find there was no engine - billing a
    client for a submission that could not physically happen. Survivable while the bot
    fell back to 50 in-code specs and almost always had something to run. Not survivable
    now that the whitelist starts EMPTY, which makes "no spec" the common case."""
    import app.modules.citations.tasks as tasks

    gate_calls: list[str] = []

    class _Gate:
        def evaluate(self, ctx: Any) -> Any:
            gate_calls.append("evaluate")
            raise AssertionError("the cost gate must not be reached without a spec")

        def commit(self, ctx: Any, cost: float) -> None:
            gate_calls.append("commit")

    monkeypatch.setattr(tasks, "_gate", lambda: _Gate())
    monkeypatch.setattr(
        tasks, "citation_bot_from_settings",
        lambda settings, **kw: PlaywrightCitationSubmitter(spec_loader=lambda job: None),
    )
    store = _FakeStore(_row())
    out = execute_citation_submit(store, Settings(_env_file=None, app_env="dev"), "c1")  # type: ignore[call-arg]

    assert out["state"] == "blocked"
    assert out["reason"] == "no_verified_spec"
    assert gate_calls == [], "nothing may be charged when there is no spec to run"
    assert store.updates["blocked_reason"] == "no_verified_spec"
    assert "nothing was sent, nothing charged" in store.updates["error"]
    assert store.updates["submit_status"] == "blocked"


def test_the_row_never_reaches_submitting_when_there_is_no_spec(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`submitting` means a browser is driving a form. A row that never had a spec must
    not pass through it - an operator watching the board would read it as work starting."""
    import app.modules.citations.tasks as tasks

    seen: list[str] = []

    class _Store(_FakeStore):
        def update_citation(self, citation_id: str, fields: dict[str, Any]) -> None:
            if "submit_status" in fields:
                seen.append(str(fields["submit_status"]))
            super().update_citation(citation_id, fields)

    monkeypatch.setattr(
        tasks, "citation_bot_from_settings",
        lambda settings, **kw: PlaywrightCitationSubmitter(spec_loader=lambda job: None),
    )
    execute_citation_submit(_Store(_row()), Settings(_env_file=None, app_env="dev"), "c1")  # type: ignore[call-arg]
    assert "submitting" not in seen
    assert seen == ["blocked"]


def test_the_worker_passes_the_whitelist_loader_and_the_route() -> None:
    """Wiring, asserted. The bot fails CLOSED when no loader is passed, so a worker that
    forgets to wire one submits nothing at all - a silent zero rather than a crash, which
    is exactly the kind of thing that survives unnoticed."""
    import inspect

    src = inspect.getsource(execute_citation_submit)
    assert "spec_loader=db_spec_loader" in src
    assert "route=" in src
