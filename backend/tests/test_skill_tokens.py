"""P9-1 gate: the Skills gateway - scoped per-client skill tokens + MCP dispatch.

These unit tests exercise (a) the token crypto/hash core with an in-memory DB fake
(no Postgres), (b) the mint/verify/revoke/list service flow, (c) the MCP gateway's
authenticate -> authorize -> cost-gate -> dispatch core with fakes, and (d) the
endpoint RBAC (owner/admin only mint/revoke; verify self-authenticates via the
skill token). The DB round-trip + RLS boundary are proven in the integration suite;
here the security PROPERTIES are proven at the crypto + scope-resolution layer:

* mint returns the raw token ONCE and stores only its hash (never the secret);
* verify accepts a valid token and rejects expired/revoked/unknown/tampered ones;
* a token cannot exceed its granted perms/tier (scope enforcement);
* BLAST-RADIUS: a token for client A resolves to tenant A only, and dispatch pins
  client_id from the token so a caller can never redirect it to client B.
"""

from __future__ import annotations

import hashlib
import types
import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from fastapi import FastAPI

from app.core.auth import CurrentUser, get_current_user
from app.services import skill_tokens
from app.services.skill_tokens import (
    ScopedPrincipal,
    cap_scopes,
    list_skill_tokens,
    mint_skill_token,
    parse_prefix,
    revoke_skill_token,
    verify_skill_token,
)
from integrations import mcp_gateway
from integrations.mcp_gateway import (
    SKILL_TOOLS,
    GatewayResult,
    SkillAuthError,
    SkillGateway,
    SkillScopeError,
    UnknownSkillToolError,
    authorize_tool,
    describe_tools,
)

pytestmark = pytest.mark.unit

_A = "11111111-1111-1111-1111-111111111111"  # client A
_B = "22222222-2222-2222-2222-222222222222"  # client B
_OWNER = "99999999-9999-9999-9999-999999999999"


# --------------------------------------------------------------------------- #
# In-memory DB fake (mirrors the exact SQL the service issues)
# --------------------------------------------------------------------------- #
_MASKED_KEYS = (
    "id", "client_id", "token_prefix", "scopes", "tier", "revoked",
    "expires_at", "last_used_at", "created_at",
)


def _masked(row: dict[str, Any]) -> dict[str, Any]:
    """Columns the RETURNING/SELECT of ``_MASKED_COLS`` exposes (NO token_hash)."""
    return {k: row[k] for k in _MASKED_KEYS}


class _FakeCursor:
    def __init__(self, store: dict[str, dict[str, Any]]) -> None:
        self._store = store
        self._one: dict[str, Any] | None = None
        self._all: list[dict[str, Any]] = []

    def execute(self, sql: str, params: Any = None) -> None:
        s = " ".join(sql.lower().split())
        p = tuple(params or ())
        if s.startswith("insert into public.skill_tokens"):
            client_id, prefix, token_hash, scopes, tier, expires_at, created_by = p
            scopes_val = getattr(scopes, "obj", scopes)  # unwrap psycopg Jsonb
            new_id = str(uuid.uuid4())
            row = {
                "id": new_id, "client_id": client_id, "token_prefix": prefix,
                "token_hash": token_hash, "scopes": scopes_val, "tier": tier,
                "revoked": False, "expires_at": expires_at, "last_used_at": None,
                "created_at": datetime.now(UTC), "created_by": created_by,
            }
            self._store[new_id] = row
            self._one = _masked(row)
        elif s.startswith("select") and "where token_prefix" in s:
            match = next((r for r in self._store.values() if r["token_prefix"] == p[0]), None)
            self._one = dict(match) if match else None  # verify select includes token_hash
        elif s.startswith("update public.skill_tokens set last_used_at"):
            now, id_ = p
            if id_ in self._store:
                self._store[id_]["last_used_at"] = now
            self._one = None
        elif s.startswith("update public.skill_tokens set revoked"):
            id_ = p[0]
            if id_ in self._store:
                self._store[id_]["revoked"] = True
                self._one = {"id": id_}
            else:
                self._one = None
        elif s.startswith("select") and "order by created_at desc" in s:
            rows = list(self._store.values())
            if "where client_id" in s:
                rows = [r for r in rows if r["client_id"] == p[0]]
            self._all = [_masked(r) for r in rows]
        else:  # pragma: no cover - a new query would need a new branch
            raise AssertionError(f"unexpected SQL: {s}")

    def fetchone(self) -> dict[str, Any] | None:
        return self._one

    def fetchall(self) -> list[dict[str, Any]]:
        return list(self._all)


@pytest.fixture
def fake_db(monkeypatch: pytest.MonkeyPatch) -> dict[str, dict[str, Any]]:
    """Bind both DB seams to one in-memory store + pin a deterministic TTL."""
    store: dict[str, dict[str, Any]] = {}

    def _ctx(*_a: Any, **_k: Any) -> Any:
        class _Ctx:
            def __enter__(self) -> _FakeCursor:
                return _FakeCursor(store)

            def __exit__(self, *_e: Any) -> None:
                return None

        return _Ctx()

    monkeypatch.setattr(skill_tokens, "rls_connection", _ctx)
    monkeypatch.setattr(skill_tokens, "privileged_connection", _ctx)
    monkeypatch.setattr(
        skill_tokens, "get_settings", lambda: types.SimpleNamespace(skill_token_ttl_seconds=3600)
    )
    return store


# --------------------------------------------------------------------------- #
# Pure helpers
# --------------------------------------------------------------------------- #
def test_parse_prefix_roundtrips_and_rejects_junk() -> None:
    assert parse_prefix("skt_abc123_secrettail") == "abc123"
    assert parse_prefix("skt_abc123_x_y") == "abc123"  # secret may contain underscores
    assert parse_prefix("nope") is None
    assert parse_prefix("bearer_abc_tail") is None  # wrong scheme
    assert parse_prefix("skt__tail") is None  # empty prefix
    assert parse_prefix("skt_abc_") is None  # empty secret


def test_cap_scopes_drops_unknown_and_dedupes() -> None:
    capped = cap_scopes(
        ["run_audits", "run_audits", "not_a_perm", "view_reports"],
        ["technical_audit", "bogus_feature"],
    )
    assert capped == {"perms": ["run_audits", "view_reports"], "features": ["technical_audit"]}


def test_scoped_principal_scope_checks() -> None:
    p = ScopedPrincipal(
        token_id="t", client_id=_A, perms=frozenset({"run_audits"}),
        features=frozenset({"technical_audit"}), tier="semi",
    )
    assert p.has_perm("run_audits") and not p.has_perm("publish_content")
    assert p.has_feature("technical_audit") and not p.has_feature("billing")
    assert p.allows_tier("free") and p.allows_tier("semi")
    assert not p.allows_tier("fully")  # a semi token cannot reach a fully-tier op


# --------------------------------------------------------------------------- #
# mint / verify / revoke / list
# --------------------------------------------------------------------------- #
def test_mint_returns_raw_once_and_stores_only_the_hash(
    fake_db: dict[str, dict[str, Any]],
) -> None:
    result = mint_skill_token(
        client_id=_A, perms=["run_audits", "view_reports"], features=["technical_audit"],
        created_by=_OWNER, tier="semi",
    )
    raw = result["token"]
    assert raw.startswith("skt_")
    # The masked mint row carries NO secret and NO hash.
    masked = {k: v for k, v in result.items() if k != "token"}
    assert "token_hash" not in masked
    assert raw not in str(masked)
    # Exactly one row stored; it holds the sha256 hash, never the raw secret.
    stored = next(iter(fake_db.values()))
    assert stored["token_hash"] == hashlib.sha256(raw.encode()).hexdigest()
    assert raw not in str(stored["token_hash"])
    assert "token" not in stored  # the raw secret was never persisted
    assert stored["client_id"] == _A
    assert stored["scopes"] == {"perms": ["run_audits", "view_reports"], "features": ["technical_audit"]}


def test_verify_accepts_valid_token(fake_db: dict[str, dict[str, Any]]) -> None:
    raw = mint_skill_token(
        client_id=_A, perms=["run_audits"], features=[], created_by=_OWNER, tier="semi"
    )["token"]
    principal = verify_skill_token(raw)
    assert principal is not None
    assert principal.client_id == _A
    assert principal.perms == frozenset({"run_audits"})
    assert principal.tier == "semi"
    # last_used_at was bumped on the row.
    assert next(iter(fake_db.values()))["last_used_at"] is not None


def test_verify_rejects_unknown_tampered_and_malformed(
    fake_db: dict[str, dict[str, Any]],
) -> None:
    raw = mint_skill_token(client_id=_A, perms=[], features=[], created_by=_OWNER)["token"]
    assert verify_skill_token("skt_deadbeef_nothere") is None  # unknown prefix
    assert verify_skill_token("garbage") is None  # malformed
    # Right prefix, wrong secret -> hash mismatch -> rejected.
    prefix = parse_prefix(raw)
    assert verify_skill_token(f"skt_{prefix}_wrongsecret") is None


def test_verify_rejects_revoked(fake_db: dict[str, dict[str, Any]]) -> None:
    raw = mint_skill_token(client_id=_A, perms=[], features=[], created_by=_OWNER)["token"]
    token_id = next(iter(fake_db.values()))["id"]
    assert revoke_skill_token(_OWNER, token_id) is True
    assert verify_skill_token(raw) is None


def test_verify_rejects_expired(fake_db: dict[str, dict[str, Any]]) -> None:
    raw = mint_skill_token(client_id=_A, perms=[], features=[], created_by=_OWNER)["token"]
    # Force the stored expiry into the past.
    next(iter(fake_db.values()))["expires_at"] = datetime.now(UTC) - timedelta(seconds=1)
    assert verify_skill_token(raw) is None


def test_revoke_unknown_returns_false(fake_db: dict[str, dict[str, Any]]) -> None:
    assert revoke_skill_token(_OWNER, str(uuid.uuid4())) is False


def test_list_is_masked_and_client_filterable(fake_db: dict[str, dict[str, Any]]) -> None:
    mint_skill_token(client_id=_A, perms=["run_audits"], features=[], created_by=_OWNER)
    mint_skill_token(client_id=_B, perms=["view_reports"], features=[], created_by=_OWNER)
    all_rows = list_skill_tokens(_OWNER)
    assert len(all_rows) == 2
    assert all("token_hash" not in r for r in all_rows)  # never expose the hash
    only_a = list_skill_tokens(_OWNER, client_id=_A)
    assert len(only_a) == 1 and only_a[0]["client_id"] == _A


def test_blast_radius_tokens_resolve_to_their_own_tenant(
    fake_db: dict[str, dict[str, Any]],
) -> None:
    """A token for A resolves to tenant A; a token for B to tenant B - never crossed."""
    raw_a = mint_skill_token(client_id=_A, perms=["run_audits"], features=[], created_by=_OWNER)["token"]
    raw_b = mint_skill_token(client_id=_B, perms=["run_audits"], features=[], created_by=_OWNER)["token"]
    pa = verify_skill_token(raw_a)
    pb = verify_skill_token(raw_b)
    assert pa is not None and pb is not None
    assert pa.client_id == _A and pb.client_id == _B
    assert pa.client_id != pb.client_id


# --------------------------------------------------------------------------- #
# MCP gateway: authorize -> cost-gate -> dispatch core
# --------------------------------------------------------------------------- #
def _principal(perms: set[str], *, client_id: str = _A, tier: str = "semi") -> ScopedPrincipal:
    return ScopedPrincipal(
        token_id="tok", client_id=client_id, perms=frozenset(perms),
        features=frozenset(), tier=tier,
    )


def test_all_tool_perms_are_real_rbac_perms() -> None:
    from app.rbac import PERM_KEYS

    valid = set(PERM_KEYS)
    for tool in SKILL_TOOLS.values():
        assert tool.required_perm is None or tool.required_perm in valid
    # The exposed surface never includes vault / team / billing management.
    assert not any("vault" in name or "team" in name for name in SKILL_TOOLS)


def test_authorize_rejects_missing_perm_and_low_tier() -> None:
    # audit.run needs run_audits: a token without it is denied.
    with pytest.raises(SkillScopeError):
        authorize_tool(_principal(set()), SKILL_TOOLS["audit.run"])
    # A granted perm passes.
    authorize_tool(_principal({"run_audits"}), SKILL_TOOLS["audit.run"])
    # content.create needs publish_content - a run_audits-only token cannot exceed its scope.
    with pytest.raises(SkillScopeError):
        authorize_tool(_principal({"run_audits"}), SKILL_TOOLS["content.create"])


class _FakeGate:
    """A CostGate stand-in: block on demand; record evaluate/commit calls."""

    def __init__(self, *, allow: bool) -> None:
        self._allow = allow
        self.evaluated: list[Any] = []
        self.committed: list[Any] = []

    def evaluate(self, ctx: Any) -> Any:
        self.evaluated.append(ctx)
        outcome = "call" if self._allow else "blocked_cap"
        return types.SimpleNamespace(
            outcome=outcome, allowed=self._allow, reason="" if self._allow else "cap reached"
        )

    def commit(self, ctx: Any, cost: float, **_k: Any) -> None:
        self.committed.append((ctx, cost))


def test_dispatch_pins_client_id_from_token_not_args() -> None:
    seen: dict[str, Any] = {}

    def handler(principal: ScopedPrincipal, args: dict[str, Any]) -> dict[str, Any]:
        seen["client_id"] = principal.client_id
        seen["args"] = args
        return {"ok": True}

    gw = SkillGateway(handlers={"audit.read": handler})
    # A malicious arg tries to redirect to client B; it must be dropped.
    res = gw.dispatch(_principal({"view_reports"}), "audit.read", {"client_id": _B, "url": "x"})
    assert res.status == "ok"
    assert seen["client_id"] == _A  # pinned from the token, never B
    assert "client_id" not in seen["args"]  # the injected tenant was stripped


def test_dispatch_cost_gate_blocks_paid_tool_without_calling_handler() -> None:
    called = {"n": 0}

    def handler(_p: ScopedPrincipal, _a: dict[str, Any]) -> Any:
        called["n"] += 1
        return "ran"

    gate = _FakeGate(allow=False)
    gw = SkillGateway(cost_gate=gate, handlers={"audit.run": handler})  # type: ignore[arg-type]
    res = gw.dispatch(_principal({"run_audits"}), "audit.run", {"url": "x"})
    assert res.status == "blocked"
    assert called["n"] == 0  # the paid provider call never happened
    assert gate.committed == []  # nothing was charged


def test_dispatch_paid_tool_allowed_calls_handler_and_commits() -> None:
    gate = _FakeGate(allow=True)
    gw = SkillGateway(
        cost_gate=gate,  # type: ignore[arg-type]
        handlers={"audit.run": lambda _p, _a: "queued"},
    )
    res = gw.dispatch(_principal({"run_audits"}), "audit.run", {"url": "x"})
    assert res.status == "ok" and res.data == "queued"
    assert len(gate.evaluated) == 1 and len(gate.committed) == 1


def test_dispatch_unknown_tool_raises() -> None:
    with pytest.raises(UnknownSkillToolError):
        SkillGateway().dispatch(_principal({"view_reports"}), "vault.reveal", {})


def test_call_authenticates_then_dispatches() -> None:
    principal = _principal({"view_reports"})
    gw = SkillGateway(
        verify=lambda _t: principal,
        handlers={"audit.read": lambda _p, _a: "rows"},
    )
    res = gw.call("skt_x_y", "audit.read", {})
    assert isinstance(res, GatewayResult) and res.data == "rows"


def test_call_rejects_invalid_token() -> None:
    gw = SkillGateway(verify=lambda _t: None)
    with pytest.raises(SkillAuthError):
        gw.call("skt_bad_token", "audit.read", {})


def test_describe_tools_emits_mcp_descriptors() -> None:
    tools = describe_tools()
    assert {t["name"] for t in tools} == set(SKILL_TOOLS)
    assert all({"name", "description", "inputSchema"} <= set(t) for t in tools)


def test_run_stdio_server_is_documented_stub() -> None:
    with pytest.raises(NotImplementedError):
        mcp_gateway.run_stdio_server()


# --------------------------------------------------------------------------- #
# Endpoint RBAC (owner/admin only mint/revoke; verify self-authenticates)
# --------------------------------------------------------------------------- #
def _user(role: str) -> CurrentUser:
    return CurrentUser(
        id=_OWNER, email="op@x.com", role=role,  # type: ignore[arg-type]
        status="active", name="Op", title="", avatar_color="#000", phone="", two_fa=False,
    )


@pytest.fixture
def as_role(app: FastAPI) -> Callable[[str], None]:
    def _set(role: str) -> None:
        app.dependency_overrides[get_current_user] = lambda: _user(role)

    return _set


async def test_mint_endpoint_admin_only_and_returns_token_once(
    client: httpx.AsyncClient, as_role: Callable[[str], None], monkeypatch: pytest.MonkeyPatch
) -> None:
    minted = {
        "token": "skt_pfx_rawsecret", "id": "tok1", "client_id": _A, "token_prefix": "pfx",
        "scopes": {"perms": ["run_audits"], "features": []}, "tier": "semi", "revoked": False,
        "expires_at": datetime.now(UTC).isoformat(), "last_used_at": None,
        "created_at": datetime.now(UTC).isoformat(),
    }
    monkeypatch.setattr("app.routers.skills.mint_skill_token", lambda **_k: dict(minted))
    # A manager (lacks owner/admin) is forbidden.
    as_role("manager")
    denied = await client.post(
        "/api/v1/skills/tokens", json={"client_id": _A, "perms": ["run_audits"], "tier": "semi"}
    )
    assert denied.status_code == 403
    # An admin may mint; the raw token is returned exactly once.
    as_role("admin")
    ok = await client.post(
        "/api/v1/skills/tokens", json={"client_id": _A, "perms": ["run_audits"], "tier": "semi"}
    )
    assert ok.status_code == 201
    body = ok.json()
    assert body["token"] == "skt_pfx_rawsecret"
    assert body["token_prefix"] == "pfx" and body["perms"] == ["run_audits"]


async def test_revoke_endpoint_admin_only(
    client: httpx.AsyncClient, as_role: Callable[[str], None], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("app.routers.skills.revoke_skill_token", lambda *_a: True)
    as_role("analyst")  # not owner/admin
    denied = await client.post("/api/v1/skills/tokens/tok1/revoke")
    assert denied.status_code == 403
    as_role("owner")
    ok = await client.post("/api/v1/skills/tokens/tok1/revoke")
    assert ok.status_code == 200
    assert ok.json() == {"id": "tok1", "revoked": True}


async def test_revoke_endpoint_404_when_missing(
    client: httpx.AsyncClient, as_role: Callable[[str], None], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("app.routers.skills.revoke_skill_token", lambda *_a: False)
    as_role("owner")
    resp = await client.post("/api/v1/skills/tokens/missing/revoke")
    assert resp.status_code == 404


async def test_verify_endpoint_requires_token_and_returns_scope_only(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    principal = ScopedPrincipal(
        token_id="tok1", client_id=_A, perms=frozenset({"run_audits"}),
        features=frozenset({"technical_audit"}), tier="semi",
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )

    def _verify(raw: str) -> ScopedPrincipal | None:
        return principal if raw == "skt_good_token" else None

    monkeypatch.setattr("app.routers.skills.verify_skill_token", _verify)
    # No header -> 401 (route is protected; the token IS the credential).
    missing = await client.post("/api/v1/skills/verify")
    assert missing.status_code == 401
    # A bad token -> 401.
    bad = await client.post("/api/v1/skills/verify", headers={"X-Skill-Token": "skt_bad_x"})
    assert bad.status_code == 401
    # A good token -> 200 with the capped scope, and NO secret/hash in the body.
    good = await client.post("/api/v1/skills/verify", headers={"X-Skill-Token": "skt_good_token"})
    assert good.status_code == 200
    body = good.json()
    assert body["client_id"] == _A and body["perms"] == ["run_audits"]
    assert body["tier"] == "semi"
    assert "token" not in body and "token_hash" not in body and "secret" not in body
