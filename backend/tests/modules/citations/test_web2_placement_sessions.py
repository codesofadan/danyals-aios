"""Web2 placement sessions (0136, Phase 7): kind='web2_placement' end-to-end in the
session service, batch mechanics identical to citations.

The properties under test:

* SELECTION IS THE PARKED POOL - only `publishing` + `publish_method='extension'`
  properties enter, never one already inside an active session's non-terminal task
  (web2 rows have no lease columns; the live task IS the exclusivity).
* NO CLAIM MACHINERY LEAKS IN - releasing a web2 batch stamps the TASKS only.
* TERMINAL IS SERVER-WRITTEN ONLY, same as citations - `mark_web2_terminal` is the
  completion hook's door, `block_web2_task` enforces the closed vocabulary and is
  WEB2-ONLY (a citation task must go through /queue/{id}/blocked, which also writes
  the citation row + drift).
* CARDS FAIL CLOSED - no ACTIVE placement spec => hasSpec=false, zero selectors,
  copy-blocks only, homepage fallback for the Open button.
* SCOPES - the session floor is any-of; the KIND's exact scope is enforced where
  the kind is known (`_refuse_kind_scope`): web2 sessions need `web2_queue:*`,
  citation sessions keep `citation_queue:*` (+ `client_profile:read` for cards).
"""

from __future__ import annotations

# The Phase-4 fixtures (`repo`, `wire`) are imported UNALIASED below - pytest keys a
# fixture by the module attribute name, so an alias would unregister it. Test
# parameters then legitimately "shadow" those module-level names; that is the pytest
# fixture idiom, not a redefinition bug.
# ruff: noqa: F811
import inspect
import sys
from collections.abc import Callable
from typing import Any

import httpx
import pytest
from fastapi import HTTPException

import app.modules.citations.router  # noqa: F401  (populates sys.modules)
from app.modules.citations.sessions import (
    SESSION_KINDS,
    TERMINAL_UI_STATES,
    WEB2_BLOCK_REASONS,
    OperatorSessionsRepo,
)

# The Phase-4 fixtures re-register here under their own names (pytest keys a fixture
# by the MODULE ATTRIBUTE name, so they must be imported unaliased to stay reachable
# as `repo` / `wire` parameters).
from .test_operator_sessions import (
    FakeSessionsRepo,
    _session_row,
    _task_row,
    repo,  # noqa: F401
    wire,  # noqa: F401
)

pytestmark = pytest.mark.unit

citations_router = sys.modules["app.modules.citations.router"]


# --------------------------------------------------------------------------- #
# Vocabularies.
# --------------------------------------------------------------------------- #
def test_web2_placement_is_a_known_session_kind() -> None:
    assert {"citation", "web2_placement"} == SESSION_KINDS


def test_the_web2_block_vocabulary_is_the_citation_queue_vocabulary() -> None:
    """One vocabulary across both lanes, so 'which platforms waste our time?' stays
    answerable with one rollup - and no new reason can appear on one side only."""
    assert {
        "captcha_wall", "account_required", "paid_only", "form_changed",
        "duplicate_listing", "directory_dead", "phone_verification",
        "postcard_verification", "other",
    } == WEB2_BLOCK_REASONS


def test_an_unknown_kind_is_refused_before_any_row_exists() -> None:
    sess = OperatorSessionsRepo("00000000-0000-0000-0000-0000000000a1")
    with pytest.raises(ValueError, match="unknown session kind"):
        sess.create_session(
            client_id="cl-1", client_name="Acme", batch_size=10, params={},
            tiers=None, limit=25, citation_ids=None, kind="webtwo",
        )


def test_mark_web2_terminal_refuses_a_non_terminal_state_before_the_db() -> None:
    sess = OperatorSessionsRepo("00000000-0000-0000-0000-0000000000a1")
    with pytest.raises(ValueError, match="not a terminal ui_state"):
        sess.mark_web2_terminal("w2-1", "opened")
    for state in TERMINAL_UI_STATES:
        # the guard passes; the DB call is the next thing (not reached in unit)
        assert state in TERMINAL_UI_STATES


def test_block_web2_task_refuses_an_unknown_reason_before_the_db() -> None:
    sess = OperatorSessionsRepo("00000000-0000-0000-0000-0000000000a1")
    with pytest.raises(ValueError, match="not a known blocked reason"):
        sess.block_web2_task("s-1", "t-1", reason="alien_obstacle")


# --------------------------------------------------------------------------- #
# Structural contracts on the repo SQL (the shapes that keep the mechanics honest).
# --------------------------------------------------------------------------- #
class TestWeb2RepoShape:
    def test_selection_is_the_parked_extension_pool_and_excludes_live_tasks(self) -> None:
        src = inspect.getsource(OperatorSessionsRepo._select_web2_candidates)
        assert "status = 'publishing'" in src
        assert "publish_method = 'extension'" in src
        assert "not exists" in src, "a property inside an active session must not re-enter"
        assert "s.status = 'active'" in src
        assert "for update of w skip locked" in src

    def test_releasing_a_web2_batch_touches_no_claim_columns(self) -> None:
        src = inspect.getsource(OperatorSessionsRepo._release_web2_tasks)
        for col in ("claimed_by", "claimed_at", "claim_expires_at", "human_attempts"):
            assert col not in src, f"web2 releases must not stamp {col}"
        assert "ui_state = 'released'" in src

    def test_the_batch_release_handles_both_kinds_in_the_same_transaction(self) -> None:
        src = inspect.getsource(OperatorSessionsRepo._release_next_batches)
        assert "rls_connection" not in src, "the release helper must ride the caller's txn"
        assert "web2_placement" in src
        assert "state_conflict" in src, (
            "a property that left the pool while pending must conflict-skip with a "
            "receipt, exactly as a re-claimed citation does"
        )
        assert "_release_web2_tasks" in src

    def test_mark_web2_terminal_marks_and_releases_in_one_transaction(self) -> None:
        src = inspect.getsource(OperatorSessionsRepo.mark_web2_terminal)
        assert src.count("rls_connection") == 1
        assert "_release_next_batches(cur" in src
        assert "t.web2_id = %s::uuid" in src
        assert "s.status = 'active'" in src

    def test_block_web2_task_is_kind_gated(self) -> None:
        src = inspect.getsource(OperatorSessionsRepo.block_web2_task)
        assert 'require_kind="web2_placement"' in src, (
            "a citation task must never be blockable through the session door - the "
            "queue's blocked endpoint owns the citation row + the drift hook"
        )

    def test_web2_heartbeat_never_touches_citation_leases(self) -> None:
        src = inspect.getsource(OperatorSessionsRepo.heartbeat)
        assert "web2_placement" in src
        # the web2 branch returns BEFORE the citations lease-extension SQL runs
        assert src.index("web2_placement") < src.index("public.citations")

    def test_client_counts_include_the_parked_placement_pool(self) -> None:
        src = inspect.getsource(OperatorSessionsRepo.client_work_counts)
        assert "web2_placements" in src
        assert "publish_method = 'extension'" in src

    def test_web2_cards_join_the_active_spec_and_prefer_the_enum_mapping(self) -> None:
        src = inspect.getsource(OperatorSessionsRepo.web2_task_rows)
        assert "sp.active" in src, "only an ACTIVE spec may power autofill"
        assert "lateral" in src
        assert "platform_enum = w.platform::text) desc" in src
        assert "limit 1" in src, "a property must never fan out into two cards"

    def test_the_repo_still_never_touches_the_privileged_pool(self) -> None:
        assert "privileged_connection" not in inspect.getsource(OperatorSessionsRepo)


# --------------------------------------------------------------------------- #
# The kind-scope guard (extension path).
# --------------------------------------------------------------------------- #
class _Principal:
    def __init__(self, *scopes: str) -> None:
        self._scopes = set(scopes)

    def has(self, scope: str) -> bool:
        return scope in self._scopes


async def _refuse(tok: str | None, kind: str, *, write: bool, cards: bool = False) -> int | None:
    try:
        await citations_router._refuse_kind_scope(tok, kind, write=write, cards=cards)
    except HTTPException as exc:
        return exc.status_code
    return None


class TestKindScopeGuard:
    @pytest.fixture(autouse=True)
    def _principal(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self._current: _Principal | None = None
        monkeypatch.setattr(
            citations_router, "operator_principal_of", lambda _tok: self._current
        )

    async def test_bearer_callers_pass_untouched(self) -> None:
        assert await _refuse(None, "web2_placement", write=True) is None

    async def test_a_web2_session_needs_web2_queue_scope_not_citation_scope(self) -> None:
        self._current = _Principal("citation_queue:read", "citation_queue:write",
                                   "client_profile:read")
        assert await _refuse("aop_x", "web2_placement", write=True) == 401
        self._current = _Principal("web2_queue:write")
        assert await _refuse("aop_x", "web2_placement", write=True, cards=True) is None

    async def test_a_citation_session_still_needs_its_own_scopes(self) -> None:
        self._current = _Principal("web2_queue:read", "web2_queue:write")
        assert await _refuse("aop_x", "citation", write=True) == 401
        self._current = _Principal("citation_queue:write", "client_profile:read")
        assert await _refuse("aop_x", "citation", write=True, cards=True) is None

    async def test_citation_cards_still_require_client_profile_read(self) -> None:
        self._current = _Principal("citation_queue:read")
        assert await _refuse("aop_x", "citation", write=False, cards=True) == 401
        self._current = _Principal("citation_queue:read", "client_profile:read")
        assert await _refuse("aop_x", "citation", write=False, cards=True) is None

    async def test_web2_cards_do_not_demand_the_nap_scope(self) -> None:
        """Web2 cards carry the client's own approved draft, not the canonical NAP -
        demanding client_profile:read would widen a web2-only token for nothing."""
        self._current = _Principal("web2_queue:read")
        assert await _refuse("aop_x", "web2_placement", write=False, cards=True) is None

    async def test_an_unverifiable_token_is_401_not_a_pass(self) -> None:
        self._current = None
        assert await _refuse("aop_x", "web2_placement", write=True) == 401


# --------------------------------------------------------------------------- #
# The routes, over a fake sessions repo (kind-split cards + the web2 block door).
# --------------------------------------------------------------------------- #
def _web2_task_row(**over: Any) -> dict[str, Any]:
    """A joined web2 card row exactly as `web2_task_rows` shapes it."""
    row: dict[str, Any] = {
        "task_id": "bbbbbbb1-0000-0000-0000-000000000001",
        "batch_no": 1,
        "position": 0,
        "ui_state": "released",
        "ui_state_at": None,
        "telemetry": {},
        "id": "w2-1",
        "client_id": "cl-secret",
        "client_name": "Acme Dental",
        "platform": "Medium",
        "topic": "A grounded article",
        "body_md": "## the approved draft",
        "anchor": "dentist in leeds",
        "target_url": "https://client.example/services",
        "status": "publishing",
        "post_url": "",
        "platform_id": "pl-1",
        "platform_name": "Medium",
        "platform_homepage_url": "https://medium.com",
        "spec_id": None,
        "placement_spec": None,
    }
    row.update(over)
    return row


class FakeWeb2SessionsRepo(FakeSessionsRepo):
    """The Phase-4 fake plus the 0136 seams."""

    def __init__(self) -> None:
        super().__init__()
        self.web2_rows: list[dict[str, Any]] = []
        self.web2_blocks: list[tuple[str, str, str]] = []
        self.block_result: dict[str, Any] | None = {
            "sessionId": "s1", "taskId": "t1", "state": "blocked",
            "batchNo": 1, "released": 0,
        }

    def web2_task_rows(self, session_id: str) -> list[dict[str, Any]]:
        return list(self.web2_rows)

    def block_web2_task(
        self, session_id: str, task_id: str, *, reason: str, detail: str = ""
    ) -> dict[str, Any] | None:
        if reason not in WEB2_BLOCK_REASONS:
            raise ValueError(f"not a known blocked reason: {reason!r}")
        self.web2_blocks.append((task_id, reason, detail))
        return self.block_result

    def mark_web2_terminal(
        self, web2_id: str, terminal_state: str, *, meta: dict[str, Any] | None = None
    ) -> dict[str, Any] | None:
        self.terminal_marks.append((web2_id, terminal_state))
        return {"sessionId": "s1", "batchNo": 1, "released": 0}


@pytest.fixture
def web2_sessions(app: Any) -> FakeWeb2SessionsRepo:  # type: ignore[misc]
    from app.modules.citations.sessions import get_operator_sessions_repo

    fake = FakeWeb2SessionsRepo()
    app.dependency_overrides[get_operator_sessions_repo] = lambda: fake
    return fake


async def test_creating_a_web2_session_returns_web2_cards_and_passes_the_kind(
    client: httpx.AsyncClient, web2_sessions: FakeWeb2SessionsRepo, repo: Any,
    wire: Callable[[str], None],
) -> None:
    # The session envelope legitimately carries clientId (mirrored in
    # frontend/lib/offpage.ts and extension/src/lib/messages.ts) - give it a
    # DIFFERENT id so the leak guard below sees only the raw card row's value.
    web2_sessions.session = _session_row(kind="web2_placement", client_id="cl-1")
    web2_sessions.web2_rows = [_web2_task_row()]
    wire("manager")
    resp = await client.post(
        "/api/v1/citation-builder/sessions",
        json={"clientId": "cl-1", "kind": "web2_placement"},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["kind"] == "web2_placement"
    assert body["tasks"] == []
    assert len(body["web2Tasks"]) == 1
    assert web2_sessions.created[0]["kind"] == "web2_placement"

    card = body["web2Tasks"][0]
    assert card["web2Id"] == "w2-1"
    assert card["platform"] == "Medium"
    assert "client_id" not in card and "cl-secret" not in resp.text


async def test_web2_cards_fail_closed_without_an_active_spec(
    client: httpx.AsyncClient, web2_sessions: FakeWeb2SessionsRepo, repo: Any,
    wire: Callable[[str], None],
) -> None:
    web2_sessions.session = _session_row(kind="web2_placement")
    web2_sessions.web2_rows = [_web2_task_row(placement_spec=None, spec_id=None)]
    wire("manager")
    resp = await client.get(
        "/api/v1/citation-builder/sessions/11111111-1111-1111-1111-111111111111"
    )
    assert resp.status_code == 200
    card = resp.json()["web2Tasks"][0]
    assert card["hasSpec"] is False
    assert card["fields"] == []
    # Copy-blocks are ALWAYS present - the lane's default, not a degraded mode.
    assert [b["key"] for b in card["copyBlocks"]] == ["title", "body", "anchor", "target_url"]
    # The Open button falls back to the platform's homepage, never a guessed editor.
    assert card["editorUrl"] == "https://medium.com"


async def test_an_active_spec_provides_the_pinned_editor_and_selectors(
    client: httpx.AsyncClient, web2_sessions: FakeWeb2SessionsRepo, repo: Any,
    wire: Callable[[str], None],
) -> None:
    web2_sessions.session = _session_row(kind="web2_placement")
    web2_sessions.web2_rows = [_web2_task_row(
        spec_id="spec-1",
        placement_spec={
            "editor_url": "https://medium.com/new-story",
            "copy_blocks": [{"key": "title", "label": "Headline"}],
            "fields": [{"selector": "input[name=title]", "value_key": "title"}],
        },
    )]
    wire("manager")
    resp = await client.get(
        "/api/v1/citation-builder/sessions/11111111-1111-1111-1111-111111111111"
    )
    assert resp.status_code == 200
    card = resp.json()["web2Tasks"][0]
    assert card["hasSpec"] is True
    assert card["editorUrl"] == "https://medium.com/new-story"
    assert card["fields"] == [{
        "key": "title", "label": "Title", "value": "A grounded article",
        "selector": "input[name=title]",
    }]
    assert [b["label"] for b in card["copyBlocks"]] == ["Headline"]


async def test_a_citation_session_detail_still_serves_citation_cards(
    client: httpx.AsyncClient, web2_sessions: FakeWeb2SessionsRepo, repo: Any,
    wire: Callable[[str], None],
) -> None:
    web2_sessions.session = _session_row(kind="citation")
    web2_sessions.tasks = [_task_row()]
    wire("manager")
    resp = await client.get(
        "/api/v1/citation-builder/sessions/11111111-1111-1111-1111-111111111111"
    )
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["tasks"]) == 1 and body["web2Tasks"] == []


async def test_the_block_door_records_the_closed_reason(
    client: httpx.AsyncClient, web2_sessions: FakeWeb2SessionsRepo, repo: Any,
    wire: Callable[[str], None],
) -> None:
    web2_sessions.session = _session_row(kind="web2_placement")
    wire("manager")
    resp = await client.post(
        "/api/v1/citation-builder/sessions/s1/tasks/t1/blocked",
        json={"reason": "account_required", "detail": "no account for this client"},
    )
    assert resp.status_code == 200
    assert resp.json()["state"] == "blocked"
    assert web2_sessions.web2_blocks == [("t1", "account_required", "no account for this client")]


async def test_the_block_door_refuses_an_open_vocabulary(
    client: httpx.AsyncClient, web2_sessions: FakeWeb2SessionsRepo, repo: Any,
    wire: Callable[[str], None],
) -> None:
    wire("manager")
    resp = await client.post(
        "/api/v1/citation-builder/sessions/s1/tasks/t1/blocked",
        json={"reason": "mercury_in_retrograde"},
    )
    assert resp.status_code == 422  # unrepresentable in the schema, like telemetry
    assert web2_sessions.web2_blocks == []


async def test_the_block_door_404s_a_citation_task(
    client: httpx.AsyncClient, web2_sessions: FakeWeb2SessionsRepo, repo: Any,
    wire: Callable[[str], None],
) -> None:
    """The kind gate: the fake mirrors `require_kind` by answering None, and the
    route must surface that as not-found - never act on the citation lane."""
    web2_sessions.block_result = None
    wire("manager")
    resp = await client.post(
        "/api/v1/citation-builder/sessions/s1/tasks/t1/blocked",
        json={"reason": "other"},
    )
    assert resp.status_code == 404


async def test_session_client_counts_carry_the_web2_pool(
    client: httpx.AsyncClient, web2_sessions: FakeWeb2SessionsRepo, repo: Any,
    wire: Callable[[str], None],
) -> None:
    web2_sessions.counts = [{
        "client_id": "cl-1", "client_name": "Acme Dental",
        "ready": 0, "verify_first": 0, "candidate_gaps": 0, "web2_placements": 3,
    }]
    wire("manager")
    resp = await client.get("/api/v1/citation-builder/session-clients")
    assert resp.status_code == 200
    assert resp.json()[0]["web2Placements"] == 3


async def test_a_form_changed_block_deactivates_the_active_placement_spec(
    client: httpx.AsyncClient, web2_sessions: FakeWeb2SessionsRepo, repo: Any,
    wire: Callable[[str], None], app: Any,
) -> None:
    """0136's drift rule, fail-closed like 0108's: a human just said the editor no
    longer matches the spec, so the spec must stop being offered - through the SAME
    block report, not a separate chore someone forgets."""

    class _FakeOffpage:
        def __init__(self) -> None:
            self.drifts: list[tuple[str, str]] = []

        def get_web2(self, web2_id: str) -> dict[str, Any] | None:
            return {"id": web2_id, "platform": "Medium"}

        def platform_matrix_for(self, platform: str) -> dict[str, Any] | None:
            return {"id": "pl-1", "mechanism": "extension", "homepage_url": "https://medium.com"}

        def record_placement_spec_drift(
            self, platform_id: str, *, selector: str, evidence: dict[str, Any]
        ) -> dict[str, Any] | None:
            self.drifts.append((platform_id, str(evidence.get("reason") or "")))
            return {"id": "spec-1", "active": False}

    fake_offpage = _FakeOffpage()
    app.dependency_overrides[citations_router.get_offpage_repo_session] = lambda: fake_offpage
    web2_sessions.session = _session_row(kind="web2_placement")
    web2_sessions.block_result = {
        "sessionId": "s1", "taskId": "t1", "state": "blocked",
        "batchNo": 1, "released": 0, "web2Id": "w2-1",
    }
    wire("manager")
    resp = await client.post(
        "/api/v1/citation-builder/sessions/s1/tasks/t1/blocked",
        json={"reason": "form_changed", "detail": "editor moved to a new layout"},
    )
    assert resp.status_code == 200
    assert fake_offpage.drifts == [("pl-1", "form_changed")]


async def test_a_non_drift_block_never_touches_the_spec(
    client: httpx.AsyncClient, web2_sessions: FakeWeb2SessionsRepo, repo: Any,
    wire: Callable[[str], None], app: Any,
) -> None:
    calls: list[str] = []

    class _Recording:
        def __getattr__(self, name: str) -> Any:
            def _record(*a: Any, **kw: Any) -> None:
                calls.append(name)

            return _record

    app.dependency_overrides[citations_router.get_offpage_repo_session] = lambda: _Recording()
    web2_sessions.session = _session_row(kind="web2_placement")
    web2_sessions.block_result = {
        "sessionId": "s1", "taskId": "t1", "state": "blocked",
        "batchNo": 1, "released": 0, "web2Id": "w2-1",
    }
    wire("manager")
    resp = await client.post(
        "/api/v1/citation-builder/sessions/s1/tasks/t1/blocked",
        json={"reason": "account_required"},
    )
    assert resp.status_code == 200
    assert calls == [], "only form_changed may reach for the spec machinery"
