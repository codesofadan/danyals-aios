"""The re-check sweep: what keeps `live` meaning something a week after it was set.

A listing is not a fact you establish once. Directories delete listings, merge
duplicates, expire unclaimed entries and quietly change a phone number, and none of it
notifies us. Without this sweep, `live` decays from an observation into a claim - the
same class of defect as the screenshot-as-live-URL it replaced.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from app.modules.citations.tasks import execute_liveness_recheck
from app.services.citation_liveness import LivenessProbe

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _allow_example_hosts(monkeypatch: pytest.MonkeyPatch) -> None:
    """`is_public_url` does a real DNS lookup, so the reserved `.example` TLD these
    fixtures use resolves to nothing and is (correctly) refused. Unit tests must not
    depend on DNS, so the guard is stubbed to allow anything that is not loopback -
    `test_a_private_url_is_refused_and_never_fetched` still exercises the real refusal
    path, and the guard itself is covered by app/core/security's own suite."""
    monkeypatch.setattr(
        "app.modules.citations.tasks.is_public_url",
        lambda url: "127.0.0.1" not in url and "localhost" not in url,
    )

_NAME = "Bright Harbour Dental"
_PHONE = "555-010-9999"


class _FakeStore:
    """Records every update so a test asserts on what was WRITTEN, not what was returned."""

    def __init__(self, rows: list[dict[str, Any]], *, load_raises: bool = False) -> None:
        self._rows = rows
        self._load_raises = load_raises
        self.updates: dict[str, dict[str, Any]] = {}

    def due_for_recheck(self, limit: int = 200) -> list[dict[str, Any]]:
        if self._load_raises:
            raise RuntimeError("db down")
        return self._rows[:limit]

    def update_citation(self, citation_id: str, fields: dict[str, Any]) -> None:
        self.updates[citation_id] = fields


def _row(cid: str = "c1", **over: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "id": cid,
        "live_url": "https://directory.example/biz/bright-harbour",
        "submit_status": "live",
        "recheck_count": 3,
        "directory": "Example Directory",
        "directory_authority_tier": "tier2",
        "directory_route": "C",
        "bp_business_name": _NAME,
        "bp_phone": _PHONE,
        "bp_address_line1": "88 Harbour Street",
    }
    row.update(over)
    return row


def _serving(html: str, status: int = 200):
    return lambda _url: LivenessProbe(status_code=status, text=html)


def test_a_still_live_listing_stays_live_and_stamps_verified_at() -> None:
    store = _FakeStore([_row()])
    out = execute_liveness_recheck(store, fetch=_serving(f"<p>{_NAME}</p><p>555-010-9999</p>"))
    assert out["checked"] == 1
    written = store.updates["c1"]
    assert written["submit_status"] == "live"
    assert isinstance(written["live_url_verified_at"], datetime)
    assert written["recheck_count"] == 4


def test_a_vanished_listing_is_delisted() -> None:
    store = _FakeStore([_row()])
    out = execute_liveness_recheck(store, fetch=_serving("", status=404))
    assert store.updates["c1"]["submit_status"] == "delisted"
    assert out["changed"] == 1
    # A delisted row must NOT get a fresh verified-at: "when did we last actually see
    # this?" has to keep pointing at the last real confirmation.
    assert "live_url_verified_at" not in store.updates["c1"]


def test_a_listing_whose_phone_changed_is_drifted_not_delisted() -> None:
    """The listing still EXISTS, so it still covers that directory. The fix is a
    correction, not a fresh submission - and calling it delisted would queue a duplicate."""
    store = _FakeStore([_row()])
    execute_liveness_recheck(store, fetch=_serving(f"<p>{_NAME}</p><p>555-777-1234</p>"))
    assert store.updates["c1"]["submit_status"] == "drifted"


def test_an_unreachable_directory_holds_the_row_and_never_downgrades_it() -> None:
    """Our own timeout must never remove a client's citation.

    This was a real bug in the first cut of this sweep: `judge_liveness` returns
    `submitted` for an unreachable host (meaning "ask again"), and writing that verdict
    downgraded a confirmed `live` row to `submitted` because DNS blipped - silently
    dropping a real citation out of the client's live count. That is the same harm as
    delisting it. The status must be left exactly as it was."""

    def _boom(_url: str) -> LivenessProbe:
        raise TimeoutError("connect timeout")

    store = _FakeStore([_row(submit_status="live")])
    out = execute_liveness_recheck(store, fetch=_boom)
    written = store.updates["c1"]
    assert "submit_status" not in written, "an unreachable host must not rewrite the status"
    assert written["verification_evidence"].obj["checked_from"] == "fetch-error"
    assert out["changed"] == 0


def test_an_unreachable_directory_retries_soon_and_does_not_burn_a_ladder_rung() -> None:
    """A network failure must not push the next REAL check out by three months, and must
    not consume one of the +3d/+14d/+60d settling checks a new listing gets."""

    def _boom(_url: str) -> LivenessProbe:
        raise TimeoutError("connect timeout")

    store = _FakeStore([_row(recheck_count=1)])
    before = datetime.now(UTC)
    execute_liveness_recheck(store, fetch=_boom)
    written = store.updates["c1"]
    assert (written["next_recheck_at"] - before).days in (0, 1)
    assert "recheck_count" not in written, "a failed look is not a check"


def test_a_private_url_is_refused_and_never_fetched() -> None:
    """SSRF: `live_url` is provider/operator-supplied and this runs server-side."""
    calls: list[str] = []

    def _spy(url: str) -> LivenessProbe:
        calls.append(url)
        return LivenessProbe(status_code=200, text=_NAME)

    store = _FakeStore([_row(live_url="http://127.0.0.1:8000/admin")])
    execute_liveness_recheck(store, fetch=_spy)
    assert calls == [], "a loopback URL must never reach the fetcher"
    assert store.updates["c1"]["verification_evidence"].obj["checked_from"] == "refused:non-public-url"


def test_one_bad_row_does_not_cost_the_others_their_recheck() -> None:
    """With acks_late a raised exception redelivers the whole sweep. 200 rows must not
    hinge on one unreachable directory."""

    def _fetch(url: str) -> LivenessProbe:
        if "bad" in url:
            raise RuntimeError("boom")
        return LivenessProbe(status_code=200, text=f"<p>{_NAME}</p><p>555-010-9999</p>")

    store = _FakeStore(
        [_row("c1"), _row("c2", live_url="https://bad.example/x"), _row("c3")]
    )
    out = execute_liveness_recheck(store, fetch=_fetch)
    assert out["checked"] == 3
    assert store.updates["c1"]["submit_status"] == "live"
    assert store.updates["c3"]["submit_status"] == "live"


def test_the_sweep_never_raises_even_when_the_database_is_down() -> None:
    store = _FakeStore([], load_raises=True)
    out = execute_liveness_recheck(store, fetch=_serving(""))
    assert out["state"] == "error" and out["checked"] == 0


def test_cadence_is_applied_from_the_directory_not_the_citation() -> None:
    """A route-A anchor is re-checked monthly; an ordinary row quarterly. The tier and
    route come from the joined DIRECTORY columns, aliased to avoid colliding with the
    citation's own `route`."""
    store = _FakeStore([_row("core", directory_route="A"), _row("tail")])
    before = datetime.now(UTC)
    execute_liveness_recheck(store, fetch=_serving(f"<p>{_NAME}</p><p>555-010-9999</p>"))
    core_days = (store.updates["core"]["next_recheck_at"] - before).days
    tail_days = (store.updates["tail"]["next_recheck_at"] - before).days
    assert core_days == 29 or core_days == 30
    assert tail_days == 89 or tail_days == 90


def test_a_brand_new_listing_walks_the_settling_ladder() -> None:
    """First three checks are +3d, +14d, +60d - a submission is most likely to become
    live, or be rejected, in its first fortnight, which is exactly when a client asks."""
    store = _FakeStore([_row(recheck_count=0)])
    before = datetime.now(UTC)
    execute_liveness_recheck(store, fetch=_serving(f"<p>{_NAME}</p><p>555-010-9999</p>"))
    days = (store.updates["c1"]["next_recheck_at"] - before).days
    assert days in (2, 3)
