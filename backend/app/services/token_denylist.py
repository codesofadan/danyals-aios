"""Token revocation (P0-7): kill an access token before its own expiry.

THE PROBLEM
-----------
Access tokens are self-contained EdDSA JWTs with a multi-day lifetime and no
server-side session. That is what makes verification fast and stateless — and it
is also why, until now, **nothing could stop one**. Signing out cleared the
browser's `localStorage` and left the token itself perfectly valid for anyone who
had copied it. Changing a password did not invalidate the sessions the old
password had opened. The token was, in the audit's words, irrevocable.

TWO MECHANISMS, DELIBERATELY DIFFERENT
--------------------------------------
1. **Per-token (`jti`)** — revokes ONE token. This is sign-out: the person keeps
   their account and their other sessions.

2. **Per-user epoch (`revoked_before`)** — revokes EVERY token issued before an
   instant, in a single write, without the server ever having tracked which
   tokens exist. This is what a password change and a suspension need: "every
   session that predates this moment is over." Enumerating outstanding `jti`s to
   achieve the same thing would require the session table this design exists to
   avoid.

WHY THIS IS A HARDENING LAYER, NOT THE BOUNDARY
-----------------------------------------------
Redis is optional in this application, and this module **fails open** — an
unreachable Redis logs a warning and admits the token. That is a deliberate
choice, and it is only defensible because it is not the real control:

* **Suspension** is enforced against POSTGRES in
  :func:`app.core.auth.get_current_user`, which loads the user row on every
  request. A suspended user is refused whether or not Redis is up.
* **Password change** leaves the old password unusable regardless; the epoch only
  closes sessions the old password had already opened.

So a Redis outage degrades revocation latency, never tenant isolation or account
closure. Failing CLOSED here would instead mean a cache blip logs out every user
of the platform — trading a real, total outage for a marginal, already-covered
risk.

EXPIRY
------
Every key is written with a TTL, so the denylist can never grow without bound:
a `jti` entry lives only as long as the token it revokes could have been valid,
and an epoch lives one maximum-token-lifetime past the revocation.
"""

from __future__ import annotations

import time

from app.logging_setup import get_logger

logger = get_logger("app.token_denylist")

# One namespace, two shapes. Kept on the app cache DB (REDIS_URL, db 0) rather
# than a broker DB: this is request-path state, and a `FLUSHDB` of the cache
# degrades to "revocation forgotten", never to "jobs lost".
_JTI_PREFIX = "auth:revoked:jti:"
_USER_PREFIX = "auth:revoked:before:"

# Floor for any TTL we compute, so clock skew or an already-expired token can
# never write a zero/negative expiry (which Redis rejects).
_MIN_TTL_SECONDS = 60


def _jti_key(jti: str) -> str:
    return f"{_JTI_PREFIX}{jti}"


def _user_key(user_id: str) -> str:
    return f"{_USER_PREFIX}{user_id}"


def _ttl_until(exp: int | None, *, fallback: int) -> int:
    """Seconds until ``exp``, floored — never longer than the token can live."""
    if exp is None:
        return max(fallback, _MIN_TTL_SECONDS)
    return max(int(exp) - int(time.time()), _MIN_TTL_SECONDS)


async def revoke_token(redis: object, *, jti: str, exp: int | None) -> bool:
    """Revoke ONE token by its ``jti`` until it would have expired anyway.

    Returns True when the revocation was durably recorded. False means Redis was
    unreachable — the caller should surface that honestly (a "signed out"
    message that did not actually revoke anything is exactly the kind of false
    success this recovery exists to remove).
    """
    if not jti:
        return False
    try:
        await redis.set(_jti_key(jti), "1", ex=_ttl_until(exp, fallback=3600))  # type: ignore[attr-defined]
        return True
    except Exception as exc:
        logger.warning("token_revoke_failed", error=type(exc).__name__)
        return False


async def revoke_all_for_user(redis: object, *, user_id: str, max_token_ttl: int) -> bool:
    """Revoke every token issued to ``user_id`` at or before this instant.

    The cut-off is the CURRENT second, and :func:`is_revoked` compares with
    ``<=``. That combination is chosen deliberately, because `iat` has only
    one-second resolution and the boundary case has to fall one way or the other:

    * ``<=`` (this choice) can also kill a token minted in the SAME second as the
      revocation. Cost: that person signs in again a second later.
    * ``<`` would let a token minted in that same second SURVIVE a suspension.
      Cost: an offboarded person keeps a working session.

    For an access-revocation control the first cost is an inconvenience and the
    second is the defect this module exists to fix, so the boundary errs toward
    revoking slightly too much. (An earlier version of this function stepped the
    cut-off back a second, which quietly produced the *unsafe* behaviour; the
    test `test_a_token_issued_in_the_same_second_is_still_revoked` pins it.)
    """
    try:
        await redis.set(  # type: ignore[attr-defined]
            _user_key(user_id),
            str(int(time.time())),
            ex=max(max_token_ttl, _MIN_TTL_SECONDS),
        )
        return True
    except Exception as exc:
        logger.warning("token_revoke_all_failed", error=type(exc).__name__)
        return False


async def is_revoked(redis: object, *, jti: str | None, user_id: str, issued_at: int | None) -> bool:
    """Whether this token has been revoked, by either mechanism.

    FAILS OPEN by contract (see the module docstring): an unreachable Redis
    returns False and logs. The Postgres-backed suspension check in
    ``get_current_user`` is what actually holds the line.
    """
    try:
        if jti and await redis.get(_jti_key(jti)) is not None:  # type: ignore[attr-defined]
            return True
        raw = await redis.get(_user_key(user_id))  # type: ignore[attr-defined]
        if raw is None or issued_at is None:
            return False
        cutoff = int(raw if isinstance(raw, (str, int)) else raw.decode())
        # `<=` not `<`: a token whose `iat` equals the cut-off was issued in the
        # same second as the revocation and must NOT survive it. See
        # `revoke_all_for_user` for why the boundary errs this way.
        return int(issued_at) <= cutoff
    except Exception as exc:
        # Never let a cache problem 500 a request or lock a legitimate user out.
        logger.warning("token_revocation_check_unavailable", error=type(exc).__name__)
        return False
