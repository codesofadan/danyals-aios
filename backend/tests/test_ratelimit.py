"""Per-user rate limiter: counting, the 429 boundary, and fail-open on Redis error."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi import HTTPException

from app.core.auth import CurrentUser
from app.core.ratelimit import rate_limit


def _user(uid: str = "u1") -> CurrentUser:
    return CurrentUser(
        id=uid, email="u@x.z", role="owner", status="active", name="U",
        title="", avatar_color="#fff", phone="", two_fa=False,
    )


class _FakeRedis:
    def __init__(self, raise_on: str | None = None) -> None:
        self.counts: dict[str, int] = {}
        self.expires: dict[str, int] = {}
        self._raise_on = raise_on

    async def incr(self, key: str) -> int:
        if self._raise_on == "incr":
            raise ConnectionError("redis down")
        self.counts[key] = self.counts.get(key, 0) + 1
        return self.counts[key]

    async def expire(self, key: str, seconds: int) -> None:
        self.expires[key] = seconds


@pytest.mark.unit
async def test_allows_up_to_limit_then_429() -> None:
    dep = rate_limit("audit_create", limit=3, per_seconds=60)
    redis = _FakeRedis()
    user = _user()
    for _ in range(3):
        assert await dep(user=user, redis=redis) is None  # type: ignore[call-arg]
    with pytest.raises(HTTPException) as exc:
        await dep(user=user, redis=redis)  # type: ignore[call-arg]
    assert exc.value.status_code == 429
    assert exc.value.headers is not None and "Retry-After" in exc.value.headers


@pytest.mark.unit
async def test_limit_is_per_user() -> None:
    dep = rate_limit("audit_create", limit=1, per_seconds=60)
    redis = _FakeRedis()
    assert await dep(user=_user("a"), redis=redis) is None  # type: ignore[call-arg]
    # A different user has its own window - not throttled by the first.
    assert await dep(user=_user("b"), redis=redis) is None  # type: ignore[call-arg]


@pytest.mark.unit
async def test_fails_open_when_redis_unavailable() -> None:
    dep = rate_limit("audit_create", limit=1, per_seconds=60)
    redis: Any = _FakeRedis(raise_on="incr")
    # Redis is down -> the limiter must ALLOW (never 500 a legitimate request).
    for _ in range(5):
        assert await dep(user=_user(), redis=redis) is None  # type: ignore[call-arg]


@pytest.mark.unit
async def test_first_hit_sets_expiry() -> None:
    dep = rate_limit("audit_create", limit=5, per_seconds=45)
    redis = _FakeRedis()
    await dep(user=_user(), redis=redis)  # type: ignore[call-arg]
    assert list(redis.expires.values()) == [45]
