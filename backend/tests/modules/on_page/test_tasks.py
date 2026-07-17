"""On-page workers: the properties that protect a CLIENT'S LIVE WEBSITE.

NO DB, NO network, NO broker: the stores are in-memory, the WordPress editor is the
deterministic offline fake, and the Celery tasks are invoked as plain functions
(``.delay`` is never called).

Every test here maps to something that goes badly wrong in the real world:

1. **Idempotency.** ``task_acks_late`` redelivers on any raise, so a second run must
   NOT write the site again.
2. **The drift-guard.** If a human hand-edited the page after we analysed it, applying
   our proposal DESTROYS their work. It must refuse.
3. **The revert drift-guard.** Same hazard, other direction: restoring our snapshot
   over someone's later edit is just as destructive.
4. **The silent-meta-drop.** WordPress answers 200 and stores NOTHING when an SEO
   plugin has not registered the meta key. Believing that 200 means reporting a fix as
   live forever when the page never changed. This is the single most dangerous failure
   in the module, because it is INVISIBLE.
5. **No credential -> held, never failed.** The recommendation is still good.
6. **`manual` never auto-applies.**
7. **Never re-raise.**
"""

from __future__ import annotations

from typing import Any, ClassVar

import pytest

from app.config import Settings
from app.modules.on_page import tasks as wk
from app.modules.on_page.tasks import (
    ApplyOutcome,
    SsrfGuardedFetcher,
    WpTarget,
    execute_analysis,
    execute_apply,
    execute_revert,
)
from app.services.content_research import FetchedPage
from app.services.cost_gate import CostGate, DialMode, GateContext
from integrations.wordpress import FakeWordPressEditor

pytestmark = pytest.mark.unit

_ACTOR = "00000000-0000-0000-0000-0000000000a1"
_REC = "11111111-1111-1111-1111-111111111111"
_YOAST_TITLE = "_yoast_wpseo_title"
_YOAST_META = "_yoast_wpseo_metadesc"


def _settings() -> Settings:
    return Settings(_env_file=None, app_env="dev")


# --------------------------------------------------------------------------- #
# Fakes.
# --------------------------------------------------------------------------- #
class FakeRecStore:
    """In-memory stand-in for the LEAD-scoped OnPageRepo.

    ``update_recommendation`` honours ``expect_status`` exactly like the real
    optimistic-concurrency SQL (0 rows -> ``None``), because that guard is what turns
    a concurrent double-apply into a no-op instead of a second live write.
    """

    def __init__(self, row: dict[str, Any] | None = None) -> None:
        self.rows: dict[str, dict[str, Any]] = {row["id"]: row} if row else {}
        self.updates: list[tuple[str, dict[str, Any], str | None]] = []

    def get_recommendation(self, rec_id: str) -> dict[str, Any] | None:
        row = self.rows.get(rec_id)
        return dict(row) if row else None

    def update_recommendation(
        self, rec_id: str, changes: dict[str, Any], expect_status: str | None = None
    ) -> dict[str, Any] | None:
        self.updates.append((rec_id, dict(changes), expect_status))
        row = self.rows.get(rec_id)
        if row is None:
            return None
        if expect_status is not None and row.get("status") != expect_status:
            return None  # the real UPDATE ... where status = %s matches 0 rows
        row.update(changes)
        return dict(row)


class FakeAnalysisStore:
    """In-memory stand-in for the privileged ServiceOnPageStore."""

    def __init__(self, row: dict[str, Any] | None = None) -> None:
        self.row = row
        self.recs: list[dict[str, Any]] = []
        self.cleared = 0
        self.updates: list[dict[str, Any]] = []

    def load_analysis(self, code: str) -> dict[str, Any] | None:
        return dict(self.row) if self.row else None

    def update_analysis(self, code: str, fields: dict[str, Any]) -> dict[str, Any] | None:
        self.updates.append(dict(fields))
        if self.row is not None:
            self.row.update(fields)
        return dict(self.row) if self.row else None

    def clear_open_recommendations(self, analysis_id: str) -> int:
        self.cleared += 1
        return 0

    def insert_recommendations(self, analysis_id: str, rows: list[dict[str, Any]]) -> int:
        self.recs.extend(rows)
        return len(rows)

    def audit_json_path(self, audit_id: str) -> str | None:
        return None


class FakeCostStore:
    """Minimal CostStore: a settable dial + a recorder of what was actually spent.

    Mirrors ``tests/modules/keyword_research``'s fake so both modules exercise the
    REAL ``CostGate`` (dial -> cache -> cap -> daily stop) rather than a stub of it.
    """

    def __init__(self, *, mode: DialMode = "api", halted: bool = False) -> None:
        self._mode = mode
        self._halted = halted
        self.recorded: list[tuple[str, float]] = []

    def dial_mode(self, feature_key: str) -> DialMode:
        return self._mode

    def client_budget(self, client_id: str) -> tuple[float, float] | None:
        return None

    def daily_spent(self) -> float:
        return 0.0

    def daily_stop(self) -> float:
        return 100.0

    def is_halted(self) -> bool:
        return self._halted

    def record_cost(self, ctx: GateContext, cost: float, *, cached: bool) -> None:
        self.recorded.append((ctx.feature_key, cost))


class _NullCache:
    def get(self, key: str) -> Any | None:
        return None

    def set(self, key: str, value: Any) -> None:
        return None


def _gate(mode: DialMode = "api") -> tuple[CostGate, FakeCostStore]:
    store = FakeCostStore(mode=mode)
    return CostGate(store, _NullCache()), store


def _post(*, meta: dict[str, Any] | None = None, title: str = "Live title") -> dict[str, Any]:
    """A WP ``context=edit`` post: native fields as {"raw": ...}, flat meta."""
    return {"id": 4471, "title": {"raw": title}, "content": {"raw": "<p>body</p>"},
            "meta": dict(meta) if meta is not None else {}}


def _rec_row(**over: Any) -> dict[str, Any]:
    """An OPEN, applicable title fix whose snapshot matches the live page."""
    row: dict[str, Any] = {
        "id": _REC,
        "client_id": "cl-secret",
        "client_name": "NorthPeak Dental",
        "site_id": "site-1",
        "page_url": "https://np.example/p",
        "issue": "Title is 12 characters - under the 30-character minimum",
        "issue_code": "title_short",
        "impact": "High",
        "status": "open",
        "fix_kind": "title",
        "fix_payload": {"proposed_value": "Invisalign cost in Austin - a straight answer"},
        "current_value": "Old SEO title",
        "wp_post_id": 4471,
        "applied_at": None,
    }
    row.update(over)
    return row


def _editor(
    *, seo_title: str = "Old SEO title", drop: set[str] | None = None
) -> FakeWordPressEditor:
    """A live post whose Yoast keys are REST-registered (present in `meta`), carrying
    ``seo_title`` as the current SEO title."""
    return FakeWordPressEditor(
        {4471: _post(meta={_YOAST_TITLE: seo_title, _YOAST_META: "desc"})},
        drop_meta_keys=drop,
    )


def _resolver(editor: FakeWordPressEditor) -> Any:
    return lambda row, settings: WpTarget(site_url="https://np.example", editor=editor)


def _apply(store: FakeRecStore, editor: FakeWordPressEditor, **kw: Any) -> ApplyOutcome:
    return execute_apply(
        store, _REC, actor_id=_ACTOR, settings=_settings(),
        resolve_wp=_resolver(editor), **kw,
    )


# --------------------------------------------------------------------------- #
# 1. THE APPLY IS IDEMPOTENT - a redelivery must not write the site twice.
# --------------------------------------------------------------------------- #
def test_apply_writes_the_site_once_and_records_the_pre_write_snapshot() -> None:
    store, editor = FakeRecStore(_rec_row()), _editor()
    outcome = _apply(store, editor)

    assert outcome.state == "applied"
    assert len(editor.writes) == 1
    post_id, fields, meta = editor.writes[0]
    assert post_id == 4471
    assert meta == {_YOAST_TITLE: "Invisalign cost in Austin - a straight answer"}
    assert fields == {}  # the SEO title is plugin META, never the native post title

    changes = store.updates[0][1]
    assert changes["status"] == "applied"
    assert changes["applied_by"] == _ACTOR
    assert changes["applied_at"] is not None
    # current_value is re-snapshotted to what was live IMMEDIATELY BEFORE our write -
    # that, not the proposal, is what a revert has to put back.
    assert changes["current_value"] == "Old SEO title"
    assert store.updates[0][2] == "open"  # the optimistic-concurrency guard


def test_a_second_apply_is_a_no_op_and_never_touches_the_site_again() -> None:
    """``task_acks_late`` redelivers a job on any raise. Without this guard the
    redelivery would re-write the client's live page."""
    store, editor = FakeRecStore(_rec_row()), _editor()
    assert _apply(store, editor).state == "applied"

    second = _apply(store, editor)
    assert second.state == "noop"
    assert "idempotent" in second.reason
    assert len(editor.writes) == 1  # STILL one - the site was not touched again


def test_apply_is_a_no_op_on_the_applied_at_stamp_alone() -> None:
    """Keyed on the STAMP, not just the status, so a row that was half-written (stamp
    set, status lagging) is still recognised as done rather than re-applied."""
    store, editor = FakeRecStore(_rec_row(status="open", applied_at="2026-07-17T00:00:00Z")), _editor()
    assert _apply(store, editor).state == "noop"
    assert editor.writes == []


def test_a_concurrent_apply_that_loses_the_race_reports_noop() -> None:
    """The write itself is idempotent (same post, same absolute value), so losing the
    optimistic-concurrency race is a no-op, not an error."""
    store, editor = FakeRecStore(_rec_row()), _editor()
    store.rows[_REC]["status"] = "dismissed"  # a colleague moved it mid-flight
    outcome = _apply(store, editor)
    assert outcome.state == "noop"


# --------------------------------------------------------------------------- #
# 2. THE DRIFT-GUARD - never clobber a human's hand-edit.
# --------------------------------------------------------------------------- #
def test_apply_refuses_when_the_live_value_drifted_from_the_snapshot() -> None:
    """Someone hand-edited the title after we analysed. Applying would silently
    destroy their work, so we refuse - and, crucially, we do NOT write the site."""
    store = FakeRecStore(_rec_row(current_value="Old SEO title"))
    editor = _editor(seo_title="A title a human just wrote by hand")

    outcome = _apply(store, editor)

    assert outcome.state == "blocked"
    assert "overwrite a manual edit" in outcome.reason
    assert editor.writes == []                  # the site was NOT touched
    assert store.rows[_REC]["status"] == "open"  # still actionable


def test_force_re_snapshots_the_drifted_value_and_proceeds() -> None:
    """A lead who has looked at the page may decide ours wins. The re-snapshot matters:
    a later revert must restore THEIR text, not the stale one we first recorded."""
    store = FakeRecStore(_rec_row(current_value="Old SEO title"))
    editor = _editor(seo_title="A title a human just wrote by hand")

    outcome = _apply(store, editor, force=True)

    assert outcome.state == "applied"
    assert len(editor.writes) == 1
    assert store.updates[0][1]["current_value"] == "A title a human just wrote by hand"


def test_a_missing_tag_snapshot_matches_an_empty_live_value() -> None:
    """``current_value`` is NULL when there was no tag to snapshot; the live value is
    then ``""``. These must compare EQUAL or every missing-tag fix would false-drift."""
    store = FakeRecStore(_rec_row(current_value=None, issue_code="title_missing"))
    editor = _editor(seo_title="")
    assert _apply(store, editor).state == "applied"


# --------------------------------------------------------------------------- #
# 3. THE VERIFY - a silently-dropped meta write must NEVER be a reported success.
# --------------------------------------------------------------------------- #
def test_a_silently_dropped_seo_meta_write_becomes_held_not_a_false_success() -> None:
    """THE most dangerous failure in this module. WordPress returns 200 and stores
    NOTHING when the SEO plugin has not registered the key for REST writes. Trusting
    that 200 would mark the fix 'applied' forever while the page never changed - and
    nobody would ever find out."""
    store = FakeRecStore(_rec_row())
    editor = _editor(drop={_YOAST_TITLE})  # WP accepts, stores nothing, reports 200

    outcome = _apply(store, editor)

    assert outcome.state == "held"
    assert "SEO-plugin bridge missing" in outcome.reason
    assert store.rows[_REC]["status"] == "held"
    assert store.rows[_REC]["applied_at"] is None  # NEVER stamped as applied


def test_apply_verifies_with_a_fresh_read_not_the_updates_echo() -> None:
    """A plugin that echoes the request back would fake a success the site never
    stored, so the verify must be an independent re-read of the post."""
    store, editor = FakeRecStore(_rec_row()), _editor()
    _apply(store, editor)
    # read (drift-guard) -> write -> read (verify): the verify is its OWN GET.
    assert [ctx for _id, ctx in editor.reads] == ["edit", "edit"]
    assert len(editor.writes) == 1


def test_apply_holds_when_no_seo_plugin_exposes_a_meta_key_at_all() -> None:
    """No registered key means the write WOULD be dropped. We do not fire a blind
    write at a live site to find that out."""
    store = FakeRecStore(_rec_row())
    editor = FakeWordPressEditor({4471: _post(meta={})})  # no SEO plugin
    outcome = _apply(store, editor)
    assert outcome.state == "held"
    assert "SEO-plugin bridge missing" in outcome.reason
    assert editor.writes == []  # nothing was even attempted


def test_the_rank_math_bridge_is_detected_from_the_live_post() -> None:
    """Yoast vs Rank Math is discovered from the post's own REST-exposed meta keys -
    presence IS the proof the plugin registered it for writes."""
    store = FakeRecStore(_rec_row())
    editor = FakeWordPressEditor(
        {4471: _post(meta={"rank_math_title": "Old SEO title", "rank_math_description": "d"})}
    )
    assert _apply(store, editor).state == "applied"
    assert editor.writes[0][2] == {
        "rank_math_title": "Invisalign cost in Austin - a straight answer"
    }


def test_a_meta_fix_writes_the_description_key_not_the_title_key() -> None:
    store = FakeRecStore(
        _rec_row(fix_kind="meta", issue_code="meta_short", current_value="desc",
                 fix_payload={"proposed_value": "A better description of the page."})
    )
    editor = _editor()
    assert _apply(store, editor).state == "applied"
    assert editor.writes[0][2] == {_YOAST_META: "A better description of the page."}


# --------------------------------------------------------------------------- #
# 4. Credential + applicability: held, never failed; manual never auto-applies.
# --------------------------------------------------------------------------- #
def test_no_wordpress_credential_holds_the_fix_rather_than_failing_it() -> None:
    """The recommendation is still good - only the delivery path is missing. Failing
    it would throw away real analysis over an unconfigured key."""
    store = FakeRecStore(_rec_row())
    outcome = execute_apply(
        store, _REC, actor_id=_ACTOR, settings=_settings(),
        resolve_wp=lambda row, settings: None,  # no per-site WP credential
    )
    assert outcome.state == "held"
    assert "credential" in outcome.reason
    assert store.rows[_REC]["status"] == "held"
    assert store.rows[_REC]["applied_at"] is None


def test_no_resolved_wp_post_holds_rather_than_guessing_at_one() -> None:
    """Every apply UPDATEs a specific post id. Guessing would edit the WRONG page."""
    store, editor = FakeRecStore(_rec_row(wp_post_id=None)), _editor()
    outcome = _apply(store, editor)
    assert outcome.state == "held"
    assert editor.writes == []


def test_a_manual_fix_is_never_auto_applied() -> None:
    store, editor = FakeRecStore(_rec_row(fix_kind="manual")), _editor()
    outcome = _apply(store, editor)
    assert outcome.state == "skipped"
    assert editor.writes == []
    assert editor.reads == []  # we do not even look at the site


@pytest.mark.parametrize("kind", ["heading", "content", "schema"])
def test_a_kind_with_no_proven_write_path_holds_rather_than_guessing(kind: str) -> None:
    """We do not invent a way to rewrite a live page's prose or markup."""
    store, editor = FakeRecStore(_rec_row(fix_kind=kind)), _editor()
    outcome = _apply(store, editor)
    assert outcome.state == "held"
    assert editor.writes == []


def test_an_explicit_native_field_payload_is_written_and_verified() -> None:
    """The escape hatch a future detector uses to deliver a native-field fix without
    guesswork - written through the same verify."""
    store = FakeRecStore(
        _rec_row(fix_kind="content", current_value="<p>body</p>",
                 fix_payload={"proposed_value": "<p>new body</p>",
                              "wp_fields": {"content": "<p>new body</p>"}})
    )
    editor = _editor()
    outcome = _apply(store, editor)
    assert outcome.state == "applied"
    assert editor.writes[0][1] == {"content": "<p>new body</p>"}


def test_apply_holds_when_there_is_no_proposed_value() -> None:
    store, editor = FakeRecStore(_rec_row(fix_payload={})), _editor()
    assert _apply(store, editor).state == "held"
    assert editor.writes == []


def test_an_unknown_recommendation_fails_cleanly() -> None:
    outcome = execute_apply(
        FakeRecStore(), _REC, actor_id=_ACTOR, settings=_settings(),
        resolve_wp=lambda row, settings: None,
    )
    assert outcome.state == "failed"


# --------------------------------------------------------------------------- #
# 5. NEVER RE-RAISE - acks_late would redeliver and re-write the site.
# --------------------------------------------------------------------------- #
def test_apply_never_re_raises_when_the_site_call_explodes() -> None:
    class _Exploding:
        def get_post(self, *a: Any, **k: Any) -> dict[str, Any]:
            raise RuntimeError("wordpress is on fire")

        def update_post(self, *a: Any, **k: Any) -> dict[str, Any]:
            raise RuntimeError("wordpress is on fire")

    outcome = execute_apply(
        FakeRecStore(_rec_row()), _REC, actor_id=_ACTOR, settings=_settings(),
        resolve_wp=lambda row, settings: WpTarget("https://np.example", _Exploding()),  # type: ignore[arg-type]
    )
    assert outcome.state == "failed"
    assert "wordpress is on fire" in outcome.reason


def test_apply_never_re_raises_when_the_resolver_explodes() -> None:
    def _boom(row: Any, settings: Any) -> Any:
        raise RuntimeError("vault unreachable")

    outcome = execute_apply(
        FakeRecStore(_rec_row()), _REC, actor_id=_ACTOR, settings=_settings(), resolve_wp=_boom
    )
    assert outcome.state == "failed"


def test_a_hold_write_failure_still_returns_an_outcome() -> None:
    class _BadStore(FakeRecStore):
        def update_recommendation(self, *a: Any, **k: Any) -> dict[str, Any] | None:
            raise RuntimeError("db down")

    outcome = execute_apply(
        _BadStore(_rec_row()), _REC, actor_id=_ACTOR, settings=_settings(),
        resolve_wp=lambda row, settings: None,
    )
    assert outcome.state == "held"  # the hold-write failure did not become an exception


# --------------------------------------------------------------------------- #
# 6. THE REVERT - it drift-guards too.
# --------------------------------------------------------------------------- #
def _applied_row(**over: Any) -> dict[str, Any]:
    """A row as it looks AFTER a successful apply: status applied, and current_value
    holding the pre-apply value the revert must restore."""
    row = _rec_row(status="applied", applied_at="2026-07-17T00:00:00Z",
                   current_value="Old SEO title")
    row.update(over)
    return row


def _revert(store: FakeRecStore, editor: FakeWordPressEditor, **kw: Any) -> ApplyOutcome:
    return execute_revert(
        store, _REC, actor_id=_ACTOR, settings=_settings(),
        resolve_wp=_resolver(editor), **kw,
    )


def test_revert_restores_the_pre_apply_snapshot() -> None:
    store = FakeRecStore(_applied_row())
    # The live page still carries exactly what we applied.
    editor = _editor(seo_title="Invisalign cost in Austin - a straight answer")

    outcome = _revert(store, editor)

    assert outcome.state == "reverted"
    assert editor.writes[0][2] == {_YOAST_TITLE: "Old SEO title"}
    assert store.rows[_REC]["status"] == "reverted"
    assert store.updates[0][2] == "applied"  # optimistic concurrency


def test_revert_refuses_when_the_page_changed_after_we_applied() -> None:
    """The symmetric hazard: restoring our snapshot over someone's LATER hand-edit is
    exactly as destructive as a blind apply. It must refuse."""
    store = FakeRecStore(_applied_row())
    editor = _editor(seo_title="A newer title a human wrote after our fix")

    outcome = _revert(store, editor)

    assert outcome.state == "blocked"
    assert "later manual edit" in outcome.reason
    assert editor.writes == []                      # the site was NOT touched
    assert store.rows[_REC]["status"] == "applied"  # unchanged


def test_forced_revert_overrides_the_drift_guard() -> None:
    store = FakeRecStore(_applied_row())
    editor = _editor(seo_title="A newer title a human wrote after our fix")
    assert _revert(store, editor, force=True).state == "reverted"
    assert editor.writes[0][2] == {_YOAST_TITLE: "Old SEO title"}


def test_reverting_something_never_applied_is_a_no_op() -> None:
    store, editor = FakeRecStore(_rec_row(status="open")), _editor()
    outcome = _revert(store, editor)
    assert outcome.state == "noop"
    assert editor.writes == []


def test_revert_holds_without_a_credential_and_never_re_raises() -> None:
    store = FakeRecStore(_applied_row())
    assert execute_revert(
        store, _REC, actor_id=_ACTOR, settings=_settings(),
        resolve_wp=lambda row, settings: None,
    ).state == "held"

    def _boom(row: Any, settings: Any) -> Any:
        raise RuntimeError("vault unreachable")

    assert execute_revert(
        store, _REC, actor_id=_ACTOR, settings=_settings(), resolve_wp=_boom
    ).state == "failed"


def test_a_dropped_revert_write_holds_rather_than_claiming_a_rollback() -> None:
    store = FakeRecStore(_applied_row())
    editor = _editor(seo_title="Invisalign cost in Austin - a straight answer",
                     drop={_YOAST_TITLE})
    outcome = _revert(store, editor)
    assert outcome.state == "held"
    assert store.rows[_REC]["status"] == "applied"  # NOT falsely marked reverted


# --------------------------------------------------------------------------- #
# 7. THE ANALYSIS - idempotent, gate-first, SSRF-guarded, never re-raising.
# --------------------------------------------------------------------------- #
_HTML = (
    "<html><head><title>Short</title></head>"
    '<body class="postid-4471"><h1>Hi</h1><p>Some words here.</p></body></html>'
)


def _analysis_row(**over: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "id": "an-1", "code": "OP-0001", "client_id": "cl-1", "client_name": "NorthPeak",
        "site_id": "site-1", "page_url": "https://np.example/p",
        "target_keyword": "invisalign cost", "status": "queued",
        "source_audit_id": None, "wp_post_id": None,
    }
    row.update(over)
    return row


class _Fetcher:
    def __init__(self, html: str | None = _HTML) -> None:
        self.html = html
        self.calls: list[str] = []

    def fetch(self, url: str, *, timeout: float) -> FetchedPage | None:
        self.calls.append(url)
        return FetchedPage(url=url, html=self.html, status=200) if self.html else None


def _analyze(store: FakeAnalysisStore, fetcher: Any, **kw: Any):
    gate, _ = _gate(kw.pop("mode", "api"))
    return execute_analysis(
        store, "OP-0001", settings=_settings(), gate=gate, fetcher=fetcher, **kw  # type: ignore[arg-type]
    )


def test_analysis_detects_persists_and_completes() -> None:
    store, fetcher = FakeAnalysisStore(_analysis_row()), _Fetcher()
    outcome = _analyze(store, fetcher)

    assert outcome.status == "done"
    assert outcome.recommendations > 0
    assert store.cleared == 1  # stale OPEN recs rebuilt
    codes = {r["issue_code"] for r in store.recs}
    assert "title_short" in codes
    assert store.updates[0] == {"status": "analyzing"}  # queued -> analyzing first


def test_analysis_resolves_the_wp_post_id_exactly_once_from_the_page() -> None:
    """Resolved ONCE, at analysis time: a re-resolve per apply could drift onto a
    different post and edit the wrong page."""
    store, fetcher = FakeAnalysisStore(_analysis_row()), _Fetcher()
    _analyze(store, fetcher)
    assert store.row is not None
    assert store.row["wp_post_id"] == 4471  # read off the body class


def test_analysis_never_guesses_a_wp_post_id_it_cannot_prove() -> None:
    store = FakeAnalysisStore(_analysis_row())
    _analyze(store, _Fetcher("<html><head><title>Short</title></head><body>x</body></html>"))
    assert store.row is not None
    assert store.row.get("wp_post_id") is None


def test_analysis_snapshots_current_value_for_the_drift_guard() -> None:
    store, fetcher = FakeAnalysisStore(_analysis_row()), _Fetcher()
    _analyze(store, fetcher)
    title_rec = next(r for r in store.recs if r["issue_code"] == "title_short")
    assert title_rec["current_value"] == "Short"


def test_a_redelivered_non_queued_analysis_is_a_no_op() -> None:
    """Only a queued analysis is the worker's. Re-running a done one would re-fetch,
    re-spend, and rebuild a board a lead may already be working through."""
    store, fetcher = FakeAnalysisStore(_analysis_row(status="done")), _Fetcher()
    outcome = _analyze(store, fetcher)
    assert outcome.state == "noop"
    assert fetcher.calls == []
    assert store.recs == []


def test_an_unfetchable_page_holds_rather_than_failing() -> None:
    """Held, not failed: the analysis is still valid work that a re-analyze picks
    straight back up."""
    store = FakeAnalysisStore(_analysis_row())
    outcome = _analyze(store, _Fetcher(html=None))
    assert outcome.status == "held"
    assert store.row is not None
    assert store.row["status"] == "held"


def test_an_ssrf_blocked_target_fails_and_is_never_retried_as_held() -> None:
    """Terminal by nature - a private address will not become public on a retry."""
    from app.core.security import PrivateAddressError

    class _Ssrf:
        def fetch(self, url: str, *, timeout: float) -> FetchedPage | None:
            raise PrivateAddressError("private/local address not allowed: 169.254.169.254")

    store = FakeAnalysisStore(_analysis_row())
    outcome = _analyze(store, _Ssrf())
    assert outcome.status == "failed"
    assert "169.254.169.254" in outcome.reason


def test_analysis_never_re_raises_on_an_unexpected_error() -> None:
    class _Boom:
        def fetch(self, url: str, *, timeout: float) -> FetchedPage | None:
            raise RuntimeError("kaboom")

    outcome = _analyze(FakeAnalysisStore(_analysis_row()), _Boom())
    assert outcome.status == "failed"
    assert "kaboom" in outcome.reason


def test_a_missing_analysis_fails_cleanly() -> None:
    assert _analyze(FakeAnalysisStore(None), _Fetcher()).state == "failed"


# --------------------------------------------------------------------------- #
# 8. The R5 cost pre-check on the paid entity pull.
# --------------------------------------------------------------------------- #
class _Entities:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def entities_for(self, keyword: str) -> list[str]:
        self.calls.append(keyword)
        return ["Invisalign", "aligners"]


def test_the_gate_is_consulted_before_the_paid_entity_pull() -> None:
    """A dial that is off must mean the provider is never called. A decision taken
    after the call would already have spent the money it exists to prevent."""
    store, source = FakeAnalysisStore(_analysis_row()), _Entities()
    outcome = _analyze(store, _Fetcher(), entity_source=source, mode="off")

    assert source.calls == []          # NOT called
    assert outcome.state == "degraded"  # and it degraded rather than failing
    assert store.row is not None
    assert store.row["status"] == "done"


def test_a_blocked_dial_degrades_the_score_to_deterministic_only() -> None:
    store = FakeAnalysisStore(_analysis_row())
    _analyze(store, _Fetcher(), entity_source=_Entities(), mode="off")
    assert store.row is not None
    assert store.row["score"]["degraded"] is True
    assert "entity_coverage" not in store.row["score"]["sub_scores"]


def test_an_allowed_dial_pulls_entities_and_commits_the_spend() -> None:
    gate, cost_store = _gate("api")
    store, source = FakeAnalysisStore(_analysis_row()), _Entities()
    execute_analysis(
        store, "OP-0001", settings=_settings(), gate=gate,
        fetcher=_Fetcher(), entity_source=source,
    )
    assert source.calls == ["invisalign cost"]
    assert [f for f, _c in cost_store.recorded] == ["on_page"]
    assert store.row is not None
    assert store.row["score"]["degraded"] is False


def test_no_entity_source_degrades_without_touching_the_gate() -> None:
    """The keyless path: no Serper key -> no source -> deterministic-only, no crash."""
    gate, cost_store = _gate("api")
    store = FakeAnalysisStore(_analysis_row())
    outcome = execute_analysis(
        store, "OP-0001", settings=_settings(), gate=gate,
        fetcher=_Fetcher(), entity_source=None,
    )
    assert outcome.state == "degraded"
    assert cost_store.recorded == []  # nothing was even evaluated as spend


def test_a_failing_entity_provider_degrades_rather_than_failing_the_analysis() -> None:
    class _BadSource:
        def entities_for(self, keyword: str) -> list[str]:
            raise RuntimeError("serper down")

    store = FakeAnalysisStore(_analysis_row())
    outcome = _analyze(store, _Fetcher(), entity_source=_BadSource())
    assert outcome.status == "done"
    assert store.row is not None
    assert store.row["score"]["degraded"] is True


def test_entity_source_from_settings_is_none_without_a_serper_key() -> None:
    assert wk.entity_source_from_settings(_settings()) is None


# --------------------------------------------------------------------------- #
# 9. The SSRF fetcher re-validates EVERY redirect hop.
# --------------------------------------------------------------------------- #
def test_the_fetcher_revalidates_every_hop_not_just_the_first(
    monkeypatch: pytest.MonkeyPatch
) -> None:
    """One-shot validation is insufficient: a 30x can bounce a validated public host
    straight at the cloud metadata endpoint. Every hop must go back through the guard."""
    from app.core.security import PrivateAddressError

    checked: list[str] = []

    def _validate(value: str) -> str:
        checked.append(value)
        if "169.254.169.254" in value:
            raise PrivateAddressError("private/local address not allowed")
        return value

    class _Resp:
        def __init__(self, status: int, location: str = "") -> None:
            self.status_code = status
            self.headers = {"location": location} if location else {}
            self.text = "<html></html>"

    class _Client:
        def __init__(self, *a: Any, **k: Any) -> None: ...
        def __enter__(self) -> _Client:
            return self

        def __exit__(self, *a: Any) -> None: ...
        def get(self, url: str) -> _Resp:
            # The public first hop redirects to the AWS metadata service.
            return _Resp(302, "http://169.254.169.254/latest/meta-data/")

    import httpx

    monkeypatch.setattr(wk, "validate_public_host", _validate)
    monkeypatch.setattr(httpx, "Client", _Client)

    with pytest.raises(PrivateAddressError):
        SsrfGuardedFetcher().fetch("https://np.example/p", timeout=1.0)

    assert checked == ["https://np.example/p", "http://169.254.169.254/latest/meta-data/"]


def test_the_fetcher_bounds_a_redirect_loop(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Resp:
        status_code = 302
        headers: ClassVar[dict[str, str]] = {"location": "/next"}
        text = ""

    class _Client:
        def __init__(self, *a: Any, **k: Any) -> None: ...
        def __enter__(self) -> _Client:
            return self

        def __exit__(self, *a: Any) -> None: ...
        def get(self, url: str) -> _Resp:
            return _Resp()

    import httpx

    monkeypatch.setattr(wk, "validate_public_host", lambda v: v)
    monkeypatch.setattr(httpx, "Client", _Client)
    assert SsrfGuardedFetcher().fetch("https://np.example/p", timeout=1.0) is None


def test_the_fetcher_returns_none_on_a_transport_error(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Client:
        def __init__(self, *a: Any, **k: Any) -> None: ...
        def __enter__(self) -> _Client:
            return self

        def __exit__(self, *a: Any) -> None: ...
        def get(self, url: str) -> Any:
            raise OSError("connection reset")

    import httpx

    monkeypatch.setattr(wk, "validate_public_host", lambda v: v)
    monkeypatch.setattr(httpx, "Client", _Client)
    assert SsrfGuardedFetcher().fetch("https://np.example/p", timeout=1.0) is None


# --------------------------------------------------------------------------- #
# 10. The Celery entry points never re-raise.
# --------------------------------------------------------------------------- #
def test_the_celery_entry_points_swallow_a_catastrophic_failure(
    monkeypatch: pytest.MonkeyPatch
) -> None:
    """A raise out of a task is a REDELIVERY under acks_late - i.e. a second live-site
    write. Every entry point must return a result dict instead."""
    def _boom(*a: Any, **k: Any) -> Any:
        raise RuntimeError("everything is broken")

    monkeypatch.setattr(wk, "get_settings", _boom)
    assert wk.analyze_page("OP-0001")["state"] == "failed"
    assert wk.apply_onpage_fix(_REC, _ACTOR)["state"] == "failed"
    assert wk.revert_onpage_fix(_REC, _ACTOR)["state"] == "failed"
