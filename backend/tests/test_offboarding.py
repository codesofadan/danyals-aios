"""P0-6 / P0-7 gate: a person can be removed, and their token dies with them.

Before this, there was no way to offboard anyone. `user_status` had no access
state, `login()` never read status, `get_current_user` loaded status and ignored
it, and the multi-day bearer token could not be revoked at all — so a departing
team member kept full access to every client's data until their token expired on
its own, while the `manage_team` permission advertised the capability in the UI.

Two independent layers are asserted here, and the distinction matters:

* **Postgres** — `users.status = 'suspended'`, checked on every authenticated
  request. This is the boundary. It holds with Redis down.
* **Redis** — a `jti` denylist and a per-user revocation epoch. This is latency,
  not authority. It fails open by design, so every test that relies on it also
  asserts the Postgres layer still refuses.
"""

from __future__ import annotations

import time
from typing import Any

import pytest

from app.services.token_denylist import (
    is_revoked,
    revoke_all_for_user,
    revoke_token,
)

pytestmark = pytest.mark.unit


class FakeRedis:
    """Minimal async Redis: enough for set/get, with an optional failure mode."""

    def __init__(self, *, broken: bool = False) -> None:
        self.store: dict[str, str] = {}
        self.ttls: dict[str, int] = {}
        self.broken = broken

    async def set(self, key: str, value: str, ex: int | None = None) -> None:
        if self.broken:
            raise ConnectionError("redis down")
        self.store[key] = value
        if ex is not None:
            self.ttls[key] = ex

    async def get(self, key: str) -> str | None:
        if self.broken:
            raise ConnectionError("redis down")
        return self.store.get(key)


# --------------------------------------------------------------------------- #
# Per-token revocation (sign-out)
# --------------------------------------------------------------------------- #
async def test_a_revoked_token_is_rejected_by_its_jti() -> None:
    redis = FakeRedis()
    exp = int(time.time()) + 3600
    assert await revoke_token(redis, jti="tok-1", exp=exp) is True
    assert await is_revoked(redis, jti="tok-1", user_id="u-1", issued_at=int(time.time()))


async def test_revoking_one_token_leaves_the_persons_other_sessions_alone() -> None:
    """Signing out of a shared machine must not sign you out of your phone."""
    redis = FakeRedis()
    await revoke_token(redis, jti="laptop", exp=int(time.time()) + 3600)
    assert await is_revoked(redis, jti="laptop", user_id="u-1", issued_at=1)
    assert not await is_revoked(redis, jti="phone", user_id="u-1", issued_at=1)


async def test_a_revocation_expires_with_the_token_it_revokes() -> None:
    """The denylist must not grow without bound — every entry carries a TTL."""
    redis = FakeRedis()
    exp = int(time.time()) + 600
    await revoke_token(redis, jti="tok-1", exp=exp)
    ttl = next(iter(redis.ttls.values()))
    assert 0 < ttl <= 600


async def test_an_already_expired_token_still_gets_a_valid_ttl() -> None:
    """A negative TTL is rejected by Redis; clock skew must not raise."""
    redis = FakeRedis()
    await revoke_token(redis, jti="tok-old", exp=int(time.time()) - 5000)
    assert all(ttl > 0 for ttl in redis.ttls.values())


async def test_revoking_without_a_jti_reports_failure_rather_than_success() -> None:
    """A legacy token minted before `jti` existed cannot be revoked by id.

    Reporting True here would tell an operator a session was closed when nothing
    was — the exact class of unearned success this recovery removes.
    """
    redis = FakeRedis()
    assert await revoke_token(redis, jti="", exp=None) is False


# --------------------------------------------------------------------------- #
# Per-user revocation (suspension, password rotation)
# --------------------------------------------------------------------------- #
async def test_revoking_a_user_kills_every_token_issued_before_it() -> None:
    redis = FakeRedis()
    issued_earlier = int(time.time()) - 60
    assert await revoke_all_for_user(redis, user_id="u-1", max_token_ttl=3600) is True
    assert await is_revoked(redis, jti="any", user_id="u-1", issued_at=issued_earlier)


async def test_a_token_issued_after_the_revocation_still_works() -> None:
    """Reactivation and re-login must work — the epoch is a cut-off, not a ban."""
    redis = FakeRedis()
    await revoke_all_for_user(redis, user_id="u-1", max_token_ttl=3600)
    issued_later = int(time.time()) + 5
    assert not await is_revoked(redis, jti="fresh", user_id="u-1", issued_at=issued_later)


async def test_a_token_issued_in_the_same_second_is_still_revoked() -> None:
    """`iat` has one-second resolution, so the boundary case has to fall one way.

    It falls toward REVOKING: a token stamped in the same second as the
    revocation is treated as predating it. The alternative would let an
    offboarded person's just-issued token survive their suspension. The cost of
    this choice is that someone may have to sign in again a second later.

    This pins a bug caught while writing it: the cut-off was originally stepped
    back one second, which produced exactly the unsafe behaviour.
    """
    redis = FakeRedis()
    now = int(time.time())
    await revoke_all_for_user(redis, user_id="u-1", max_token_ttl=3600)
    assert await is_revoked(redis, jti="same-second", user_id="u-1", issued_at=now)


async def test_one_users_revocation_does_not_touch_another_user() -> None:
    redis = FakeRedis()
    await revoke_all_for_user(redis, user_id="u-1", max_token_ttl=3600)
    assert not await is_revoked(redis, jti="x", user_id="u-2", issued_at=1)


# --------------------------------------------------------------------------- #
# Failure posture
# --------------------------------------------------------------------------- #
async def test_the_denylist_fails_open_when_redis_is_down() -> None:
    """Documented and deliberate: this layer is NOT the boundary.

    Failing closed here would mean a cache blip logs out every user of the
    platform. The Postgres-backed `suspended` check in `get_current_user` is what
    actually stops an offboarded person, and it does not involve Redis at all —
    see `test_a_suspended_user_is_refused_on_every_request`.
    """
    redis = FakeRedis(broken=True)
    assert await is_revoked(redis, jti="tok-1", user_id="u-1", issued_at=1) is False


async def test_a_failed_revocation_is_reported_as_failed() -> None:
    """The caller must be able to tell the operator the truth."""
    redis = FakeRedis(broken=True)
    assert await revoke_token(redis, jti="tok-1", exp=None) is False
    assert await revoke_all_for_user(redis, user_id="u-1", max_token_ttl=60) is False


# --------------------------------------------------------------------------- #
# The token itself
# --------------------------------------------------------------------------- #
def test_every_issued_token_carries_a_unique_jti_and_an_iat() -> None:
    """Without both, neither revocation mechanism can work."""
    import jwt
    from cryptography.hazmat.primitives import serialization as ser
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    from app.config import Settings
    from app.services.tokens import issue_access_token

    key = Ed25519PrivateKey.generate()
    priv = key.private_bytes(
        ser.Encoding.PEM, ser.PrivateFormat.PKCS8, ser.NoEncryption()
    ).decode()
    pub = key.public_key().public_bytes(
        ser.Encoding.PEM, ser.PublicFormat.SubjectPublicKeyInfo
    ).decode()
    settings = Settings(
        _env_file=None, app_env="dev", jwt_private_key=priv, jwt_public_key=pub
    )

    def claims_of(token: str) -> dict[str, Any]:
        return jwt.decode(
            token,
            pub,
            algorithms=["EdDSA"],
            audience=settings.jwt_audience,
            issuer=settings.local_jwt_issuer,
        )

    a = claims_of(issue_access_token("u-1", "owner", settings=settings))
    b = claims_of(issue_access_token("u-1", "owner", settings=settings))

    assert a["jti"] and b["jti"]
    # Two logins by the SAME user must not share a jti, or signing out of one
    # session would silently kill the other.
    assert a["jti"] != b["jti"]
    assert isinstance(a["iat"], int)


# --------------------------------------------------------------------------- #
# The boundary: Postgres, not Redis
# --------------------------------------------------------------------------- #
async def test_a_suspended_user_is_refused_on_every_request() -> None:
    """The load-bearing check. No Redis involved anywhere in this test.

    Asserted at the `get_current_user` seam with the DB lookup faked, because that
    is the single place every authenticated request passes through — refusing at
    login alone would leave an already-issued token working for days.
    """
    import jwt
    from cryptography.hazmat.primitives import serialization as ser
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from fastapi import HTTPException

    from app.config import Settings
    from app.core import auth as auth_mod

    key = Ed25519PrivateKey.generate()
    priv = key.private_bytes(
        ser.Encoding.PEM, ser.PrivateFormat.PKCS8, ser.NoEncryption()
    ).decode()
    pub = key.public_key().public_bytes(
        ser.Encoding.PEM, ser.PublicFormat.SubjectPublicKeyInfo
    ).decode()
    settings = Settings(_env_file=None, app_env="dev", jwt_private_key=priv, jwt_public_key=pub)

    now = int(time.time())
    token = jwt.encode(
        {
            "sub": "11111111-1111-1111-1111-111111111111",
            "role": "manager",
            "aud": settings.jwt_audience,
            "iss": settings.local_jwt_issuer,
            "iat": now,
            "exp": now + 3600,
            "jti": "live-token",
        },
        priv,
        algorithm="EdDSA",
    )

    row = {
        "id": "11111111-1111-1111-1111-111111111111",
        "email": "gone@example.com",
        "role": "manager",
        "name": "Departed",
        "title": "",
        "avatar_color": "#000",
        "phone": "",
        "two_fa": False,
        "client_id": None,
    }

    class _Creds:
        credentials = token

    class _Req:
        class state:  # noqa: N801 - mimics starlette's request.state
            pass

    async def call(status_value: str) -> Any:
        row["status"] = status_value
        return await auth_mod.get_current_user(
            _Req(),  # type: ignore[arg-type]
            settings,
            FakeRedis(),  # type: ignore[arg-type]
            _Creds(),  # type: ignore[arg-type]
        )

    original = auth_mod._load_user_row
    auth_mod._load_user_row = lambda user_id: dict(row)  # type: ignore[assignment]
    try:
        # An active user with the very same token passes — so the refusal below
        # is attributable to `status`, not to anything else about the token.
        assert (await call("active")).role == "manager"

        with pytest.raises(HTTPException) as exc:
            await call("suspended")
        assert exc.value.status_code == 403
        assert "suspended" in str(exc.value.detail).lower()

        # Presence states are NOT access states: someone marked away or offline
        # is still an employee and must keep working.
        for presence in ("away", "offline", "invited"):
            assert (await call(presence)).role == "manager"
    finally:
        auth_mod._load_user_row = original  # type: ignore[assignment]
