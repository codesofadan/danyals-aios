"""Phase 5 verification sweeps: backlink liveness + Web 2.0 link recheck (0133/0134).

What is protected here, in one sentence each:

* The VERDICT MAPPING is honest - `found` -> live, `missing` -> missing, a
  redirector-wrapped href -> missing (not the link we placed), and a failed fetch ->
  `unknown`, never a silent pass or a false accusation.
* LOSS IS CONFIRMED, not inferred: one missing look schedules a +7d re-look; only a
  second miss flips the monitoring status to `lost` and fires the alert seam - and a
  `toxic` link never leaves the disavow queue just because it went dark.
* The Web 2.0 recheck DEMOTES on evidence (stripped link, 404'd post) and alerts on
  the TRANSITION; a failed look touches only `link_checked_at`.
* Ingest PERSISTS the verification coordinates (`url_from`/`url_to` ->
  source_url/target_url), because a row without its referring page can never be
  checked.
* The automation kinds exist, are free (`paid=False`), name real tasks, and 0134
  seeds them PAUSED.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from app.config import Settings
from app.services.cost_gate import CostGate, GateContext
from integrations.backlinks import BacklinkRecord, CsvBacklinkImporter, _record_from_dfs
from workers.tasks import offpage as wk

pytestmark = pytest.mark.unit

_NOW = datetime(2026, 9, 5, 12, 0, tzinfo=UTC)

TARGET = "https://client.example/page"
FOUND_HTML = f'<p>intro</p><a href="{TARGET}" rel="nofollow ugc">Acme</a><p>rest</p>'
MISSING_HTML = '<a href="https://other.example/">someone else</a>'
# A platform redirector wrapping our URL is NOT our link - equity flows to the
# redirector's domain, and inspect_html reports it missing on purpose.
REDIRECTOR_HTML = (
    '<a href="https://redirect.example/out?u=https%3A%2F%2Fclient.example%2Fpage">Acme</a>'
)


# --------------------------------------------------------------------------- #
# Fakes.
# --------------------------------------------------------------------------- #
class _CannedFetcher:
    """An EvidenceFetcher stand-in: canned HTML (or None) + a canned status."""

    def __init__(self, html: str | None, status: int | None = 200, detail: str = "") -> None:
        self._html = html
        self.status = status
        self.detail = detail

    def __call__(self, url: str) -> str | None:
        return self._html


def _factory(fetcher: _CannedFetcher) -> Any:
    return lambda: fetcher


class _VerifyStore:
    """Fake ServiceOffpageStore for the backlink sweep."""

    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows
        self.recorded: list[tuple[str, dict[str, Any]]] = []

    def claim_due_backlink_checks(self, *, limit: int = 25) -> list[dict[str, Any]]:
        return [dict(r) for r in self.rows[:limit]]

    def record_backlink_check(self, backlink_id: str, **kw: Any) -> None:
        self.recorded.append((backlink_id, kw))


class _BoomStore:
    def claim_due_backlink_checks(self, *, limit: int = 25) -> list[dict[str, Any]]:
        raise RuntimeError("db down")

    def list_published_web2_for_recheck(self, *, limit: int = 50) -> list[dict[str, Any]]:
        raise RuntimeError("db down")


class _RecheckStore:
    """Fake ServiceOffpageStore for the Web 2.0 recheck."""

    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows
        self.updated: dict[str, dict[str, Any]] = {}

    def list_published_web2_for_recheck(self, *, limit: int = 50) -> list[dict[str, Any]]:
        return [dict(r) for r in self.rows[:limit]]

    def update_web2(self, web2_id: str, fields: dict[str, Any]) -> None:
        self.updated.setdefault(web2_id, {}).update(fields)


def _bl_row(
    row_id: str = "b1",
    *,
    liveness: str = "unchecked",
    status: str = "new",
    source_url: str = "https://blog.example/post",
    target_url: str = TARGET,
) -> dict[str, Any]:
    return {
        "id": row_id, "client_id": "cl-1", "client_name": "Acme",
        "source_url": source_url, "target_url": target_url,
        "liveness": liveness, "status": status,
    }


def _w2_row(
    row_id: str = "w1", *, link_found: Any = True, post_url: str = "https://dev.to/acme/p1"
) -> dict[str, Any]:
    return {
        "id": row_id, "client_id": "cl-1", "client_name": "Acme", "platform": "dev.to",
        "post_url": post_url, "target_url": TARGET, "link_found": link_found,
        "link_rel": "", "link_checked_at": None,
    }


def _run_verify(
    store: Any, fetcher: _CannedFetcher, **kw: Any
) -> dict[str, Any]:
    return wk.execute_verify_backlinks(
        store, fetcher_factory=_factory(fetcher), notify=kw.pop("notify", lambda *a: None),
        now=_NOW, **kw,
    )


# --------------------------------------------------------------------------- #
# Backlink verdict mapping over inspect_html fixtures.
# --------------------------------------------------------------------------- #
def test_a_found_link_is_live_and_its_rel_is_recorded() -> None:
    store = _VerifyStore([_bl_row()])
    result = _run_verify(store, _CannedFetcher(FOUND_HTML))
    assert result == {
        "state": "ok", "checked": 1, "outcomes": {"live": 1}, "lost_confirmed": 0,
    }
    (backlink_id, kw), = store.recorded
    assert backlink_id == "b1"
    assert kw["liveness"] == "live"
    assert kw["link_rel"] == "nofollow ugc"  # equity truth rides along, unjudged here
    assert kw["mark_lost"] is False
    assert kw["next_check_at"] == _NOW + timedelta(days=30)


def test_a_fetched_page_without_our_link_is_missing() -> None:
    store = _VerifyStore([_bl_row()])
    _run_verify(store, _CannedFetcher(MISSING_HTML))
    (_id, kw), = store.recorded
    assert kw["liveness"] == "missing"
    # +7d: the loss must be CONFIRMED by a second, separated look before any flip.
    assert kw["next_check_at"] == _NOW + timedelta(days=7)
    assert kw["mark_lost"] is False  # first miss never flips


def test_a_redirector_wrapped_href_is_missing_not_live() -> None:
    """The destination is ours but the LINK is the redirector's - calling it live
    would hide a real change in what the client received."""
    store = _VerifyStore([_bl_row()])
    _run_verify(store, _CannedFetcher(REDIRECTOR_HTML))
    (_id, kw), = store.recorded
    assert kw["liveness"] == "missing"


def test_a_failed_fetch_is_unknown_never_missing() -> None:
    store = _VerifyStore([_bl_row()])
    _run_verify(store, _CannedFetcher(None, status=503, detail="http 503"))
    (_id, kw), = store.recorded
    assert kw["liveness"] == "unknown"  # could-not-look is not evidence of absence
    assert kw["mark_lost"] is False
    # Nothing was learned - retry soon rather than consuming a month of not-looking.
    assert kw["next_check_at"] == _NOW + timedelta(days=1)
    assert kw["check_evidence"]["http_status"] == 503


@pytest.mark.parametrize("gone_status", [404, 410])
def test_a_gone_referring_page_is_missing_not_unknown(gone_status: int) -> None:
    """A deleted referring page is the COMMONEST loss mode - and it yields no HTML,
    so check_link alone says 'unknown'. The sweep must read the 404/410 the fetcher
    saw as evidence (the page - and the link on it - is gone), exactly as the web2
    recheck does, or the two-observation `lost` ladder can never start and the row
    burns one fetch per day forever."""
    store = _VerifyStore([_bl_row()])
    _run_verify(store, _CannedFetcher(None, status=gone_status, detail=f"http {gone_status}"))
    (_id, kw), = store.recorded
    assert kw["liveness"] == "missing"
    assert kw["mark_lost"] is False  # first observation only schedules the confirm
    assert kw["next_check_at"] == _NOW + timedelta(days=7)


def test_a_second_gone_look_confirms_the_loss() -> None:
    notified: list[Any] = []
    store = _VerifyStore([_bl_row(liveness="missing")])
    result = _run_verify(
        store, _CannedFetcher(None, status=404, detail="http 404"),
        notify=lambda *a: notified.append(a),
    )
    assert result["lost_confirmed"] == 1
    (_id, kw), = store.recorded
    assert kw["liveness"] == "missing" and kw["mark_lost"] is True
    assert notified, "the confirmed loss must fire the alert seam"


def test_the_evidence_receipt_carries_status_detail_and_a_server_side_stamp() -> None:
    store = _VerifyStore([_bl_row()])
    _run_verify(store, _CannedFetcher(FOUND_HTML, status=200))
    (_id, kw), = store.recorded
    evidence = kw["check_evidence"]
    assert evidence["http_status"] == 200
    assert "link is on the page" in evidence["detail"]
    assert evidence["checked_at"] == _NOW.isoformat()
    assert kw["checked_at"] == _NOW


# --------------------------------------------------------------------------- #
# Confirmed loss: flip + notify, and who never flips.
# --------------------------------------------------------------------------- #
def test_a_second_miss_confirms_the_loss_flips_status_and_notifies() -> None:
    store = _VerifyStore([_bl_row(liveness="missing", status="new")])
    calls: list[Any] = []
    result = _run_verify(
        store, _CannedFetcher(MISSING_HTML),
        notify=lambda cid, cname, new, lost: calls.append((cid, cname, new, lost)),
    )
    (_id, kw), = store.recorded
    assert kw["mark_lost"] is True
    assert result["lost_confirmed"] == 1
    assert len(calls) == 1
    cid, cname, new, lost = calls[0]
    assert (cid, cname, new) == ("cl-1", "Acme", [])
    assert lost[0]["id"] == "b1"


def test_a_toxic_link_that_went_dark_stays_toxic() -> None:
    """The disavow queue must keep it: toxicity outranks lost, exactly as it does in
    classify_backlink."""
    store = _VerifyStore([_bl_row(liveness="missing", status="toxic")])
    calls: list[Any] = []
    _run_verify(store, _CannedFetcher(MISSING_HTML), notify=lambda *a: calls.append(a))
    (_id, kw), = store.recorded
    assert kw["liveness"] == "missing"  # the observation is still recorded
    assert kw["mark_lost"] is False  # but the status never flips
    assert calls == []


def test_a_recovered_link_leaves_the_missing_ladder() -> None:
    store = _VerifyStore([_bl_row(liveness="missing", status="new")])
    _run_verify(store, _CannedFetcher(FOUND_HTML))
    (_id, kw), = store.recorded
    assert kw["liveness"] == "live" and kw["mark_lost"] is False
    assert kw["next_check_at"] == _NOW + timedelta(days=30)


def test_a_row_with_no_target_url_is_unknown_not_a_crash() -> None:
    store = _VerifyStore([_bl_row(target_url="")])
    result = _run_verify(store, _CannedFetcher(FOUND_HTML))
    (_id, kw), = store.recorded
    assert kw["liveness"] == "unknown"
    assert result["state"] == "ok"


def test_an_unreadable_due_list_degrades_honestly() -> None:
    """`completed, 0 checked` would claim nothing was due - a different fact."""
    result = wk.execute_verify_backlinks(_BoomStore(), fetcher_factory=_factory(_CannedFetcher(None)))  # type: ignore[arg-type]
    assert result["state"] == "error"


def test_one_bad_row_does_not_stop_the_sweep() -> None:
    class _RecordBoomStore(_VerifyStore):
        def record_backlink_check(self, backlink_id: str, **kw: Any) -> None:
            if backlink_id == "b1":
                raise RuntimeError("db blip")
            super().record_backlink_check(backlink_id, **kw)

    store = _RecordBoomStore([_bl_row("b1"), _bl_row("b2")])
    result = _run_verify(store, _CannedFetcher(FOUND_HTML))
    assert result["state"] == "ok"
    assert [rid for rid, _ in store.recorded] == ["b2"]


# --------------------------------------------------------------------------- #
# Due-row selection (the claim's SQL contract).
# --------------------------------------------------------------------------- #
def test_the_claim_sql_selects_the_due_and_only_the_checkable() -> None:
    """The claim must take unchecked + past-due rows, skip locked rows, refuse rows
    with no referring page, and pin the own-profile invariant. Checked at the source
    because the predicate IS the behaviour and a fake store cannot exercise SQL."""
    src = (
        Path(__file__).resolve().parents[1] / "app" / "db" / "offpage_repo.py"
    ).read_text(encoding="utf-8")
    start = src.index("def claim_due_backlink_checks")
    end = src.index("def record_backlink_check")
    claim = src[start:end]
    assert "for update skip locked" in claim
    assert "source_url <> ''" in claim  # nothing to fetch -> never claimed
    assert "liveness = 'unchecked'" in claim
    assert "next_check_at <= now()" in claim
    assert "competitor_id is null" in claim  # 0037 own-profile pin


# --------------------------------------------------------------------------- #
# Web 2.0 link recheck: demotion + notification, honest unknowns.
# --------------------------------------------------------------------------- #
def _run_recheck(store: Any, fetcher: _CannedFetcher, alerts: list[Any]) -> dict[str, Any]:
    return wk.execute_web2_link_recheck(
        store, fetcher_factory=_factory(fetcher), now=_NOW,
        alert=lambda *a: alerts.append(a),
    )


def test_a_still_present_link_stays_green_and_stamps_the_check() -> None:
    store = _RecheckStore([_w2_row(link_found=None)])
    alerts: list[Any] = []
    result = _run_recheck(store, _CannedFetcher(FOUND_HTML), alerts)
    assert result["outcomes"] == {"found": 1} and result["demoted"] == 0
    assert store.updated["w1"] == {
        "link_found": True, "link_rel": "nofollow ugc", "link_checked_at": _NOW,
    }
    assert alerts == []


def test_a_vanished_link_demotes_and_alerts_on_the_transition() -> None:
    store = _RecheckStore([_w2_row(link_found=True)])
    alerts: list[Any] = []
    result = _run_recheck(store, _CannedFetcher(MISSING_HTML), alerts)
    assert result["demoted"] == 1
    assert store.updated["w1"]["link_found"] is False
    assert alerts == [("cl-1", "Acme", "dev.to", "https://dev.to/acme/p1")]


def test_an_already_demoted_link_is_not_re_alarmed_every_day() -> None:
    """A lost link is reported once; a daily re-alarm is how alerts become noise."""
    store = _RecheckStore([_w2_row(link_found=False)])
    alerts: list[Any] = []
    result = _run_recheck(store, _CannedFetcher(MISSING_HTML), alerts)
    assert store.updated["w1"]["link_found"] is False  # still recorded
    assert result["demoted"] == 0 and alerts == []  # but not re-alarmed


def test_a_404d_post_is_evidence_the_placement_is_gone() -> None:
    store = _RecheckStore([_w2_row(link_found=True)])
    alerts: list[Any] = []
    result = _run_recheck(store, _CannedFetcher(None, status=404, detail="http 404"), alerts)
    assert result["outcomes"] == {"missing": 1}
    assert store.updated["w1"]["link_found"] is False
    assert len(alerts) == 1


def test_a_failed_look_touches_only_the_checked_stamp() -> None:
    """Our own network blip must not invent a client-facing defect."""
    store = _RecheckStore([_w2_row(link_found=True)])
    alerts: list[Any] = []
    result = _run_recheck(store, _CannedFetcher(None, status=None, detail="fetch failed"), alerts)
    assert result["outcomes"] == {"unknown": 1}
    assert store.updated["w1"] == {"link_checked_at": _NOW}  # link_found untouched
    assert alerts == []


def test_an_unreadable_property_list_degrades_honestly() -> None:
    result = wk.execute_web2_link_recheck(_BoomStore())  # type: ignore[arg-type]
    assert result["state"] == "error"


# --------------------------------------------------------------------------- #
# Ingest persists the verification coordinates.
# --------------------------------------------------------------------------- #
def test_the_dataforseo_record_carries_the_referring_page_and_target() -> None:
    rec = _record_from_dfs(
        {
            "domain_from": "blog.example", "anchor": "acme", "rank": 40,
            "backlink_spam_score": 5, "first_seen": "2026-07-08 12:00:00",
            "url_from": "https://blog.example/post-1",
            "url_to": TARGET,
        }
    )
    assert rec.source_url == "https://blog.example/post-1"
    assert rec.target_url == TARGET


def test_the_monitor_persists_source_and_target_urls() -> None:
    class _Store:
        def __init__(self) -> None:
            self.inserted: list[dict[str, Any]] = []

        def list_backlinks_for_client(self, client_id: str) -> list[dict[str, Any]]:
            return []

        def insert_backlink(self, **kw: Any) -> None:
            self.inserted.append(kw)

        def set_backlink_status(self, backlink_id: str, status: str) -> None:
            raise AssertionError("nothing stored -> nothing to lose")

    class _CostStore:
        def dial_mode(self, feature_key: str) -> str:
            return "api"

        def client_budget(self, client_id: str) -> Any:
            return None

        def daily_spent(self) -> float:
            return 0.0

        def daily_stop(self) -> float:
            return 75.0

        def is_halted(self) -> bool:
            return False

        def record_cost(self, ctx: GateContext, cost: float, *, cached: bool) -> None:
            return None

    class _NullCache:
        def get(self, key: str) -> Any:
            return None

        def set(self, key: str, value: Any) -> None:
            return None

    class _Provider:
        def fetch_backlinks(self, target: str, *, limit: int = 100) -> list[BacklinkRecord]:
            return [
                BacklinkRecord(
                    ref_domain="blog.example", anchor="acme", authority=40, spam=3,
                    first_seen=date(2026, 7, 1),
                    source_url="https://blog.example/post-1", target_url=TARGET,
                )
            ]

    store = _Store()
    result = wk.run_backlink_monitor(
        store, _Provider(), CostGate(_CostStore(), _NullCache()),  # type: ignore[arg-type]
        Settings(_env_file=None),  # type: ignore[call-arg]
        client_id="cl-1", client_name="Acme", domain="acme.example",
        notify=lambda *a: None,
    )
    assert result["state"] == "ok" and result["new"] == 1
    (row,) = store.inserted
    assert row["source_url"] == "https://blog.example/post-1"
    assert row["target_url"] == TARGET


def test_the_csv_importer_keeps_urls_only_when_they_are_fetchable() -> None:
    csv_text = (
        "referring page url,target url,anchor,domain rating,spam score\n"
        "https://blog.example/post-1,https://client.example/page,acme,40,5\n"
        "bare-domain.example,client.example,acme,40,5\n"
    )
    first, second = CsvBacklinkImporter().parse(csv_text)
    assert first.source_url == "https://blog.example/post-1"
    assert first.target_url == "https://client.example/page"
    # A bare-domain cell is not a page we can fetch - dropped, never guessed.
    assert second.source_url == "" and second.target_url == ""


# --------------------------------------------------------------------------- #
# Automation kinds (0134) + idempotency keys.
# --------------------------------------------------------------------------- #
def test_both_verify_kinds_are_registered_free_and_name_the_real_tasks() -> None:
    from app.jobs.automation_capabilities import CAPABILITIES

    verify = CAPABILITIES["offpage.verify_backlinks"]
    recheck = CAPABILITIES["web2.link_recheck"]
    assert verify.task == "verify_backlinks"
    assert recheck.task == "recheck_web2_links"
    # Plain HTTP GETs: neither may ever be shown to an operator as a paid sweep.
    assert verify.paid is False and recheck.paid is False
    assert verify.scope == "platform" and recheck.scope == "platform"


def test_0134_seeds_only_real_kinds_and_seeds_them_paused() -> None:
    import re

    from app.jobs.automation_capabilities import CAPABILITIES

    sql = (
        Path(__file__).resolve().parents[2]
        / "db" / "migrations" / "0134_seed_offpage_verify_automations.sql"
    ).read_text(encoding="utf-8")
    body = sql.split("insert into", 1)[1]  # the comment header may NAME kinds freely
    seeded = set(re.findall(r"'([a-z_2]+\.[a-z_]+)'", body))
    assert seeded == {"offpage.verify_backlinks", "web2.link_recheck"}
    assert seeded <= set(CAPABILITIES), "0134 must never seed a kind with no capability"
    assert ", false" in body, "every seeded automation starts PAUSED (0118/0128 rule)"


def test_the_sweep_idempotency_keys_bucket_by_day() -> None:
    verify_key = wk._verify_backlinks_target().idempotency_key
    recheck_key = wk._recheck_web2_target().idempotency_key
    today = f"{datetime.now(UTC):%Y-%m-%d}"
    assert verify_key == f"backlinks:verify:{today}"
    assert recheck_key == f"web2:linkcheck:{today}"
