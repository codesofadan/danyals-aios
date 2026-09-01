"""blocked_reason hygiene: a hold always says why, and a requeue forgets the old why.

2026-09-01: a spend-gate refusal wrote `blocked` with NO blocked_reason — the exact
"blocked with an empty machine-readable reason" state 0106 §0.5 forbids — so a dial
refusal was indistinguishable from a directory problem on every surface that maps the
code to a sentence. And `requeue_citation` reset status+error but not blocked_reason,
so a requeued row carried last campaign's verdict into its fresh life.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.config import Settings
from app.modules.citations.tasks import execute_citation_submit
from integrations.citation_bot import FormSpec, PlaywrightCitationSubmitter

pytestmark = pytest.mark.unit


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


def _spec(directory: str) -> FormSpec:
    return FormSpec(
        directory_name=directory, url=f"https://{directory.lower()}.net/add",
        fields=(), submit_selector="#go", success_indicator="text=thanks",
    )


def test_a_spend_refusal_writes_its_machine_reason(monkeypatch: pytest.MonkeyPatch) -> None:
    """Reintroduce the reason-less write in tasks.py's gate branch and this goes red:
    the assert is on the exact column, not the error string."""
    import app.modules.citations.tasks as tasks

    class _Decision:
        allowed = False
        outcome = "manual"

    class _Gate:
        def evaluate(self, ctx: Any) -> Any:
            return _Decision()

        def commit(self, ctx: Any, cost: float) -> None:  # pragma: no cover
            raise AssertionError("a refused row must never commit spend")

    monkeypatch.setattr(tasks, "_gate", lambda: _Gate())
    # A spec EXISTS, so the row passes engine resolution and reaches the gate.
    monkeypatch.setattr(
        tasks, "citation_bot_from_settings",
        lambda settings, **kw: PlaywrightCitationSubmitter(
            spec_loader=lambda job: _spec(job.directory_name)
        ),
    )
    store = _FakeStore(_row())
    out = execute_citation_submit(store, Settings(_env_file=None, app_env="dev"), "c1")  # type: ignore[arg-type]

    assert out["state"] == "blocked"
    assert store.updates["submit_status"] == "blocked"
    assert store.updates["blocked_reason"] == "spend_blocked"
    assert "nothing was sent and nothing was charged" in store.updates["error"]


def test_requeue_clears_the_stale_reason_in_the_same_update() -> None:
    """The repo method is one SQL statement; the guard reads its source because the
    defect was one missing assignment in that statement. Drop `blocked_reason = ''`
    from the UPDATE and this goes red."""
    import inspect

    from app.modules.citations.repo import CitationsRepo

    src = inspect.getsource(CitationsRepo.requeue_citation)
    assert "blocked_reason = ''" in src
    assert "submit_status = 'queued'" in src
