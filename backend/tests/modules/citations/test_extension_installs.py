"""Installation identity + rotating tokens (0131), and the theft response.

The design under test: every mint binds a 30-day ``extension_installs`` row; the 12h
token is exchanged for its successor instead of re-pasted; and a presented token whose
``rotated_at`` is set is by definition a replay or a theft - the legitimate holder
already holds the successor - so the WHOLE install chain is revoked. The blast radius is
the device, never the operator's dashboard session: the per-user Redis epoch is
deliberately left alone.

The database is faked at the cursor seam (the same statements the service issues,
answered from dicts), so these run in the unit gate with no Postgres.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest
from asgi_lifespan import LifespanManager
from fastapi import HTTPException

import app.services.operator_tokens as ot
from app.main import create_app
from app.services.operator_tokens import (
    DEFAULT_MINT_SCOPES,
    EXTENSION_SCOPES,
    OperatorPrincipal,
    mint_operator_token,
    rotate_operator_token,
    verify_operator_token,
)

pytestmark = pytest.mark.unit


# --------------------------------------------------------------------------- #
# Scope semantics: the one-way legacy mapping.
# --------------------------------------------------------------------------- #
def _principal(*scopes: str) -> OperatorPrincipal:
    return OperatorPrincipal(
        token_id="t1", user_id="u1", scopes=frozenset(scopes), expires_at=None,
    )


def test_the_legacy_umbrella_satisfies_both_granular_queue_scopes() -> None:
    """An operator paired yesterday must keep working until natural 12h expiry - the
    split must never force a fleet-wide re-pair."""
    legacy = _principal("citation_queue")
    assert legacy.has("citation_queue:read")
    assert legacy.has("citation_queue:write")
    assert legacy.has("citation_queue")


def test_a_granular_scope_never_satisfies_a_different_granular_scope() -> None:
    read_only = _principal("citation_queue:read")
    assert read_only.has("citation_queue:read")
    assert not read_only.has("citation_queue:write")
    assert not read_only.has("client_profile:read")
    write_only = _principal("citation_queue:write")
    assert not write_only.has("citation_queue:read")


def test_the_mapping_is_one_way_granular_does_not_reconstitute_the_umbrella() -> None:
    """`citation_queue` is the LEGACY value; new tokens hold the split. If holding both
    halves quietly re-created the umbrella, retiring it would become impossible to
    reason about."""
    granular = _principal("citation_queue:read", "citation_queue:write")
    assert not granular.has("citation_queue")


def test_the_vocabulary_is_seven_values_and_none_touches_a_secret_store() -> None:
    expected = {
        "citation_queue",
        "citation_credential",
        "citation_queue:read",
        "citation_queue:write",
        "client_profile:read",
        "web2_queue:read",
        "web2_queue:write",
    }
    assert expected == EXTENSION_SCOPES


def test_new_mints_default_to_the_granular_working_set() -> None:
    """Granular from day one - and neither the credential scope nor web2 rides along
    uninvited."""
    assert DEFAULT_MINT_SCOPES == (
        "citation_queue:read", "citation_queue:write", "client_profile:read",
    )
    assert set(DEFAULT_MINT_SCOPES) <= EXTENSION_SCOPES
    assert "citation_credential" not in DEFAULT_MINT_SCOPES


# --------------------------------------------------------------------------- #
# A fake database at the cursor seam.
# --------------------------------------------------------------------------- #
class _FakeDb:
    def __init__(self) -> None:
        self.installs: dict[str, dict[str, Any]] = {}
        self.tokens: dict[str, dict[str, Any]] = {}
        self.users: dict[str, dict[str, Any]] = {
            "u-1": {"status": "active", "name": "Operator One", "avatar_color": "#123456"},
            "u-2": {"status": "active", "name": "Operator Two", "avatar_color": "#654321"},
        }

    def token_by_prefix(self, prefix: str) -> dict[str, Any] | None:
        return next(
            (t for t in self.tokens.values() if t["token_prefix"] == prefix), None
        )


class _FakeCursor:
    """Answers exactly the statements `operator_tokens.py` issues - anything else is a
    loud failure, so a new query cannot silently pass against a stale fake."""

    def __init__(self, db: _FakeDb) -> None:
        self.db = db
        self._row: dict[str, Any] | None = None
        self.rowcount = 0

    def execute(self, sql: str, params: tuple[Any, ...] | None = None) -> None:
        s = " ".join(sql.split())
        p = params or ()
        db = self.db
        if s.startswith("insert into public.extension_installs"):
            install_id = str(uuid.uuid4())
            row = {
                "id": install_id,
                "user_id": str(p[0]),
                "device_label": str(p[1]),
                "pairing_expires_at": datetime.now(UTC) + timedelta(days=30),
                "revoked": False,
                "last_seen_at": None,
            }
            db.installs[install_id] = row
            self._row = dict(row)
        elif s.startswith("select id, user_id, device_label, pairing_expires_at, revoked"):
            found = db.installs.get(str(p[0]))
            self._row = dict(found) if found else None
        elif s.startswith("insert into public.operator_tokens"):
            token_id = str(uuid.uuid4())
            row = {
                "id": token_id,
                "user_id": str(p[0]),
                "token_prefix": str(p[1]),
                "token_hash": str(p[2]),
                "scopes": json.loads(str(p[3])),
                "label": str(p[4]),
                "device_label": str(p[5]),
                "expires_at": p[6],
                "created_by": p[7],
                "install_id": str(p[8]) if p[8] else None,
                "revoked": False,
                "created_at": datetime.now(UTC),
                "rotated_to": None,
                "rotated_at": None,
                "last_used_at": None,
            }
            db.tokens[token_id] = row
            self._row = dict(row)
        elif "from public.operator_tokens t join public.users u" in s:
            token = db.token_by_prefix(str(p[0]))
            if token is None:
                self._row = None
            else:
                user = db.users.get(token["user_id"], {})
                install = db.installs.get(token["install_id"]) if token["install_id"] else None
                self._row = {
                    **token,
                    "status": user.get("status"),
                    "name": user.get("name"),
                    "avatar_color": user.get("avatar_color"),
                    "install_revoked": install["revoked"] if install else None,
                    "pairing_expires_at": install["pairing_expires_at"] if install else None,
                }
        elif "set revoked = true, rotated_to = %s, rotated_at = now()" in s:
            row = db.tokens[str(p[1])]
            row["revoked"] = True
            row["rotated_to"] = str(p[0])
            row["rotated_at"] = datetime.now(UTC)
        elif "update public.operator_tokens set revoked = true where install_id" in s:
            self.rowcount = 0
            for t in db.tokens.values():
                if t["install_id"] == str(p[0]) and not t["revoked"]:
                    t["revoked"] = True
                    self.rowcount += 1
        elif "update public.extension_installs set revoked = true where id" in s:
            db.installs[str(p[0])]["revoked"] = True
        elif "update public.extension_installs set last_seen_at = now() where id" in s:
            db.installs[str(p[0])]["last_seen_at"] = datetime.now(UTC)
        elif "update public.operator_tokens set last_used_at = now() where id" in s:
            db.tokens[str(p[0])]["last_used_at"] = datetime.now(UTC)
        else:  # pragma: no cover - a new statement must be taught here explicitly
            raise AssertionError(f"unhandled sql in fake: {s}")

    def fetchone(self) -> dict[str, Any] | None:
        return self._row


def _wire(monkeypatch: pytest.MonkeyPatch, db: _FakeDb) -> list[dict[str, Any]]:
    """Point both connection seams at the fake and capture activity writes."""

    @contextmanager
    def _fake_conn(*args: Any, **kwargs: Any) -> Iterator[_FakeCursor]:
        yield _FakeCursor(db)

    monkeypatch.setattr(ot, "privileged_connection", _fake_conn)
    monkeypatch.setattr(ot, "rls_connection", _fake_conn)
    activity: list[dict[str, Any]] = []
    monkeypatch.setattr(ot, "log_activity", lambda **kw: activity.append(kw))
    return activity


# --------------------------------------------------------------------------- #
# Mint binds an install.
# --------------------------------------------------------------------------- #
def test_a_fresh_mint_creates_an_install_and_binds_the_token_to_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = _FakeDb()
    _wire(monkeypatch, db)
    row, raw = mint_operator_token(user_id="u-1", actor_id="u-1", device_label="laptop")
    assert raw.startswith("aop_")
    install_id = str(row["install_id"])
    assert install_id in db.installs
    assert db.installs[install_id]["user_id"] == "u-1"
    assert db.installs[install_id]["device_label"] == "laptop"
    assert db.tokens[str(row["id"])]["install_id"] == install_id
    # The pairing window travels with the mint so the response can state it.
    assert row["pairing_expires_at"] is not None
    # And the default scopes are the granular working set.
    assert row["scopes"] == list(DEFAULT_MINT_SCOPES)


def test_minting_with_an_owned_install_reuses_it_instead_of_multiplying(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = _FakeDb()
    _wire(monkeypatch, db)
    first, _ = mint_operator_token(user_id="u-1", actor_id="u-1", device_label="laptop")
    second, _ = mint_operator_token(
        user_id="u-1", actor_id="u-1", install_id=str(first["install_id"])
    )
    assert len(db.installs) == 1
    assert str(second["install_id"]) == str(first["install_id"])


@pytest.mark.parametrize("what", ["stranger", "revoked", "lapsed", "malformed", "unknown"])
def test_minting_against_a_dead_or_foreign_install_is_refused(
    monkeypatch: pytest.MonkeyPatch, what: str
) -> None:
    """A supplied installId must be the CALLER's live identity - anything else refuses
    rather than quietly minting under a stranger's (or a dead) install."""
    db = _FakeDb()
    _wire(monkeypatch, db)
    owner = "u-2" if what == "stranger" else "u-1"
    seeded, _ = mint_operator_token(user_id=owner, actor_id=owner, device_label="x")
    install_id = str(seeded["install_id"])
    if what == "revoked":
        db.installs[install_id]["revoked"] = True
    if what == "lapsed":
        db.installs[install_id]["pairing_expires_at"] = datetime.now(UTC) - timedelta(days=1)
    if what == "malformed":
        install_id = "not-a-uuid"
    if what == "unknown":
        install_id = str(uuid.uuid4())
    with pytest.raises(LookupError):
        mint_operator_token(user_id="u-1", actor_id="u-1", install_id=install_id)


# --------------------------------------------------------------------------- #
# Rotation.
# --------------------------------------------------------------------------- #
def test_rotation_mints_a_successor_and_retires_the_old_token_in_one_move(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = _FakeDb()
    _wire(monkeypatch, db)
    row, raw = mint_operator_token(user_id="u-1", actor_id="u-1", device_label="laptop")
    result = rotate_operator_token(raw)
    assert result is not None
    new_row, new_raw = result
    assert new_raw != raw and new_raw.startswith("aop_")

    old = db.tokens[str(row["id"])]
    assert old["revoked"] is True
    assert old["rotated_to"] == str(new_row["id"])
    assert old["rotated_at"] is not None

    new = db.tokens[str(new_row["id"])]
    assert new["revoked"] is False
    assert new["user_id"] == "u-1"
    assert new["install_id"] == str(row["install_id"])
    assert new["scopes"] == list(DEFAULT_MINT_SCOPES)
    assert new["device_label"] == "laptop"
    # The install was touched, and the response can state the unchanged pairing window.
    assert db.installs[str(row["install_id"])]["last_seen_at"] is not None
    assert new_row["pairing_expires_at"] is not None


def test_the_rotated_successor_actually_verifies(monkeypatch: pytest.MonkeyPatch) -> None:
    """A rotation that returned a dud would silently unpair every device at the 12h
    mark - the success path has to produce a WORKING credential."""
    db = _FakeDb()
    _wire(monkeypatch, db)
    row, raw = mint_operator_token(user_id="u-1", actor_id="u-1")
    result = rotate_operator_token(raw)
    assert result is not None
    principal = verify_operator_token(result[1])
    assert principal is not None
    assert principal.user_id == "u-1"
    assert principal.install_id == str(row["install_id"])
    assert principal.scopes == frozenset(DEFAULT_MINT_SCOPES)


def test_replaying_a_rotated_token_at_rotate_revokes_the_whole_install(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """THE theft response. The legitimate holder already holds the successor, so the old
    token coming back means two parties hold this chain - kill all of it, but only it."""
    db = _FakeDb()
    activity = _wire(monkeypatch, db)
    row, raw = mint_operator_token(user_id="u-1", actor_id="u-1", device_label="laptop")
    result = rotate_operator_token(raw)
    assert result is not None
    _, successor_raw = result

    assert rotate_operator_token(raw) is None  # the replay

    install_id = str(row["install_id"])
    chain = [t for t in db.tokens.values() if t["install_id"] == install_id]
    assert len(chain) == 2 and all(t["revoked"] for t in chain)
    assert db.installs[install_id]["revoked"] is True
    # The successor the thief (or the victim) holds is dead too.
    assert verify_operator_token(successor_raw) is None
    # And the event is on the record, attributed to the token's user.
    assert activity and activity[0]["actor_id"] == "u-1"
    assert "revoked" in activity[0]["action"]


def test_replaying_a_rotated_token_at_verify_revokes_the_whole_install(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Same tripwire on the ordinary request path: a rotated token presented to ANY
    queue route nukes the chain and returns the same None as any bad token."""
    db = _FakeDb()
    activity = _wire(monkeypatch, db)
    row, raw = mint_operator_token(user_id="u-1", actor_id="u-1")
    result = rotate_operator_token(raw)
    assert result is not None

    assert verify_operator_token(raw) is None

    install_id = str(row["install_id"])
    assert db.installs[install_id]["revoked"] is True
    assert all(t["revoked"] for t in db.tokens.values() if t["install_id"] == install_id)
    assert activity, "install-wide revocation must leave an audit trail"


def test_the_theft_response_never_touches_the_dashboard_epoch() -> None:
    """Blast radius is the INSTALL. Bumping the per-user Redis epoch would log the
    operator out of the dashboard because a browser extension was replayed - the service
    must not even be able to reach that lever."""
    src = Path(ot.__file__).read_text(encoding="utf-8")
    # Prose may NAME the epoch (the docstrings explain why it is left alone); what must
    # not exist is a way to reach it: no import of the denylist, no call to the lever.
    assert "from app.services.token_denylist" not in src
    assert "import token_denylist" not in src
    assert "revoke_all_for_user" not in src


@pytest.mark.parametrize(
    "what", ["revoked_install", "lapsed_install", "expired_token", "revoked_token",
             "suspended_user", "legacy_no_install", "wrong_secret"],
)
def test_rotation_refuses_every_dead_precondition(
    monkeypatch: pytest.MonkeyPatch, what: str
) -> None:
    db = _FakeDb()
    _wire(monkeypatch, db)
    row, raw = mint_operator_token(user_id="u-1", actor_id="u-1")
    token = db.tokens[str(row["id"])]
    if what == "revoked_install":
        db.installs[str(row["install_id"])]["revoked"] = True
    elif what == "lapsed_install":
        db.installs[str(row["install_id"])]["pairing_expires_at"] = (
            datetime.now(UTC) - timedelta(minutes=1)
        )
    elif what == "expired_token":
        token["expires_at"] = datetime.now(UTC) - timedelta(minutes=1)
    elif what == "revoked_token":
        token["revoked"] = True
    elif what == "suspended_user":
        db.users["u-1"]["status"] = "suspended"
    elif what == "legacy_no_install":
        token["install_id"] = None
    elif what == "wrong_secret":
        raw = raw + "x"
    before = len(db.tokens)
    assert rotate_operator_token(raw) is None
    assert len(db.tokens) == before, "a refused rotation must not have minted anything"


# --------------------------------------------------------------------------- #
# The rotate endpoint's auth boundary and rate limiting.
# --------------------------------------------------------------------------- #
async def test_rotate_401s_without_an_operator_token_and_ignores_bearer() -> None:
    """No header is 401 (the route-auth sweep's property); a BEARER credential alone is
    also 401, because rotation has no bearer fallback by design - a dashboard session
    must pair, never rotate its way into an extension credential."""
    app = create_app()
    async with LifespanManager(app):
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
            bare = await ac.post("/api/v1/extension/tokens/rotate")
            assert bare.status_code == 401
            bearer = await ac.post(
                "/api/v1/extension/tokens/rotate",
                headers={"Authorization": "Bearer not-a-real-jwt"},
            )
            assert bearer.status_code == 401


async def test_a_bad_operator_token_401s_at_rotate(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.modules.citations.operator_auth as oa

    monkeypatch.setattr(oa, "verify_operator_token", lambda raw: None)
    app = create_app()
    async with LifespanManager(app):
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
            r = await ac.post(
                "/api/v1/extension/tokens/rotate", headers={"X-Operator-Token": "aop_x_y"}
            )
            assert r.status_code == 401


class _FakeRedis:
    def __init__(self, raise_on: str | None = None) -> None:
        self.counts: dict[str, int] = {}
        self._raise_on = raise_on

    async def incr(self, key: str) -> int:
        if self._raise_on == "incr":
            raise ConnectionError("redis down")
        self.counts[key] = self.counts.get(key, 0) + 1
        return self.counts[key]

    async def expire(self, key: str, seconds: int) -> None:
        return None


async def test_rotate_rate_limit_counts_per_user_and_fails_open() -> None:
    """Fail-open like the audit-create limits: the caller is already authenticated and
    the limiter is a brake, never the reason a legitimate rotation 500s."""
    from app.routers.extension_tokens import _ROTATE_LIMIT_PER_MINUTE, _rotate_rate_limit

    redis = _FakeRedis()
    for _ in range(_ROTATE_LIMIT_PER_MINUTE):
        await _rotate_rate_limit(redis, "u-1")  # type: ignore[arg-type]
    with pytest.raises(HTTPException) as excinfo:
        await _rotate_rate_limit(redis, "u-1")  # type: ignore[arg-type]
    assert excinfo.value.status_code == 429
    # Another user's window is their own.
    await _rotate_rate_limit(redis, "u-2")  # type: ignore[arg-type]
    # And an unreachable Redis admits the request rather than 503ing it.
    await _rotate_rate_limit(_FakeRedis(raise_on="incr"), "u-3")  # type: ignore[arg-type]


def test_mint_is_rate_limited_per_user() -> None:
    """Wiring smoke: the mint route carries the shared per-user limiter dependency."""
    import inspect

    from app.routers import extension_tokens as mod

    src = inspect.getsource(mod)
    assert 'rate_limit("extension_token_mint"' in src
    assert "_rotate_rate_limit" in inspect.getsource(mod.rotate_extension_token)


def test_the_rotate_response_mirrors_the_mint_response() -> None:
    """One shape for one secret: the extension parses a single payload whether it came
    from pairing or rotation, installId and pairing window included."""
    from app.routers.extension_tokens import ExtensionTokenMinted, ExtensionTokenRow

    minted_aliases = {
        f.serialization_alias or n for n, f in ExtensionTokenMinted.model_fields.items()
    }
    assert {"installId", "pairingExpiresAt", "expiresAt", "token"} <= minted_aliases
    row_aliases = {
        f.serialization_alias or n for n, f in ExtensionTokenRow.model_fields.items()
    }
    assert {"installId", "pairingExpiresAt"} <= row_aliases
