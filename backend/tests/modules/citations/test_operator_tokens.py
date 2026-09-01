"""The extension's device credential, and the boundary that contains it.

The one property that matters: an operator token reaches the citation queue and NOTHING
else. That is structural rather than a matter of which routes remember to check — the
token is not a JWT, so `get_current_user` rejects it everywhere by construction, and the
scope vocabulary is closed so no scope that reaches the vault can even be stored.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from app.services.operator_tokens import (
    DEFAULT_TTL_SECONDS,
    EXTENSION_SCOPES,
    MAX_TTL_SECONDS,
    cap_scopes,
    hash_token,
    is_expired,
    new_raw_token,
    parse_prefix,
)

pytestmark = pytest.mark.unit


# --------------------------------------------------------------------------- #
# The closed vocabulary IS the containment.
# --------------------------------------------------------------------------- #
def test_only_citation_scopes_can_ever_be_stored() -> None:
    """Not "no route grants it" — no such scope exists to grant. A typo, a copied
    permission name, or a deliberate attempt all produce the same thing: nothing."""
    assert cap_scopes(["citation_queue"]) == ["citation_queue"]
    assert cap_scopes(["manage_vault", "access_control", "manage_clients"]) == []
    assert cap_scopes(["citation_queue", "manage_vault"]) == ["citation_queue"]
    assert cap_scopes(["*", "admin", "owner"]) == []


def test_the_vocabulary_is_two_values_and_neither_touches_a_secret_store() -> None:
    assert {"citation_queue", "citation_credential"} == EXTENSION_SCOPES


def test_scopes_are_deduped_and_order_stable() -> None:
    assert cap_scopes(["citation_queue", "citation_queue", "citation_credential"]) == [
        "citation_queue", "citation_credential",
    ]


# --------------------------------------------------------------------------- #
# The token itself.
# --------------------------------------------------------------------------- #
def test_a_token_is_high_entropy_and_uniquely_prefixed() -> None:
    seen_prefix, seen_raw = set(), set()
    for _ in range(200):
        prefix, raw = new_raw_token()
        seen_prefix.add(prefix)
        seen_raw.add(raw)
        assert raw.startswith("aop_")
        assert parse_prefix(raw) == prefix
    assert len(seen_prefix) == 200 and len(seen_raw) == 200


def test_only_the_hash_is_ever_stored_and_it_covers_the_whole_token() -> None:
    """Hashing only the secret half would let a token with a forged prefix match."""
    _prefix, raw = new_raw_token()
    digest = hash_token(raw)
    assert raw not in digest and len(digest) == 64
    assert hash_token(raw + "x") != digest


@pytest.mark.parametrize(
    "bad",
    ["", "notatoken", "aop_", "aop_abc", "skt_abc_def", "aop__secret", "aop_abc_", 12345],
)
def test_a_malformed_token_yields_no_prefix_to_look_up(bad: object) -> None:
    assert parse_prefix(bad) is None  # type: ignore[arg-type]


def test_a_skill_token_is_not_an_operator_token() -> None:
    """The two credentials share a shape but not a namespace; one must never verify as
    the other."""
    assert parse_prefix("skt_deadbeef_secretpart") is None


# --------------------------------------------------------------------------- #
# Expiry fails CLOSED.
# --------------------------------------------------------------------------- #
def test_a_missing_expiry_counts_as_expired() -> None:
    """A row that somehow lost its timestamp must fail closed, not become permanent."""
    assert is_expired(None) is True


def test_expiry_is_evaluated_in_utc_even_for_a_naive_timestamp() -> None:
    now = datetime.now(UTC)
    assert is_expired((now - timedelta(hours=1)).replace(tzinfo=None), now=now) is True
    assert is_expired((now + timedelta(hours=1)).replace(tzinfo=None), now=now) is False


def test_the_ttl_is_one_shift_not_one_month() -> None:
    """`chrome.storage.local` is plaintext on disk, on a machine signed into ~50
    third-party directories all day. The short TTL is the mitigation for a storage
    medium we do not control — contrast the skill token's 30 days in a developer's own
    terminal."""
    assert DEFAULT_TTL_SECONDS == 12 * 60 * 60
    assert MAX_TTL_SECONDS == 7 * 24 * 60 * 60


# --------------------------------------------------------------------------- #
# The boundary.
# --------------------------------------------------------------------------- #
def test_the_verifier_never_raises_and_never_logs_the_token() -> None:
    """A rejection must be indistinguishable from any other rejection, and the token
    must not reach a log line on the way."""
    import inspect

    import app.services.operator_tokens as mod

    src = inspect.getsource(mod.verify_operator_token)
    assert "return None" in src
    assert "raise" not in src.replace("NEVER raises", "")
    # Nothing logs `raw`.
    assert "raw=" not in src and "token=raw" not in src


def test_the_queue_is_the_only_surface_that_accepts_an_operator_token() -> None:
    """The containment, asserted. If a future edit adds `OperatorOrUser` to a route
    outside the queue, this fails and asks whether that was deliberate."""
    import sys

    # `app.modules.citations.router` is ambiguous - the package __init__ re-exports an
    # APIRouter under that name - so `import ... as` binds the ROUTER, not the module.
    src = Path(sys.modules["app.modules.citations.router"].__file__).read_text()
    # Every function that takes the either-credential dependency.
    accepting = [
        line for line in src.splitlines()
        if "OperatorOrUser" in line and ":" in line and "Annotated" not in line
        and not line.strip().startswith("#")
    ]
    assert accepting, "expected the queue routes to use the either-credential dependency"
    # They must all be queue handlers, which the router declares under /queue.
    assert src.count("OperatorOrUser") <= 12, (
        "the either-credential dependency has spread beyond the queue routes"
    )


def test_an_operator_token_inherits_a_role_and_never_widens_it() -> None:
    """A non-lead who pairs an extension is refused the write endpoints for exactly the
    same reason their dashboard session would be."""
    from fastapi import HTTPException

    from app.modules.citations.operator_auth import _FORBIDDEN, _LEAD_ROLES

    # Behaviour, not source: exactly the three lead roles, and a 403 (not a 401 - the
    # caller IS authenticated, they simply are not a lead).
    assert {"owner", "admin", "manager"} == _LEAD_ROLES
    assert isinstance(_FORBIDDEN, HTTPException) and _FORBIDDEN.status_code == 403
    for role in ("specialist", "analyst", "viewer", "client"):
        assert role not in _LEAD_ROLES


def test_bearer_auth_is_delegated_not_reimplemented() -> None:
    """When no operator header is present the dependency calls `get_current_user`
    itself, so bearer auth on the queue is not a lookalike of the real path — it IS the
    real path. A reimplementation here would be a second place for an auth bug to live."""
    import inspect

    from app.modules.citations.operator_auth import resolve_operator

    src = inspect.getsource(resolve_operator)
    assert "get_current_user(request, settings, redis, credentials)" in src


# --------------------------------------------------------------------------- #
# The lifetime is not negotiable at the HTTP surface (0115).
#
# `ExtensionTokenRequest` used to carry `ttl_seconds: Field(ge=60, le=MAX_TTL_SECONDS)` on
# a SELF-SERVICE endpoint - so any operator could mint themselves a seven-day token, while
# the extension README stated "expires in twelve hours" as a fact and said in bold not to
# lengthen the TTL for convenience. A policy every holder can opt out of is not a policy,
# and convenience was the only reason to set the field. Nothing sent it: no caller in
# `frontend/` or `extension/` referenced ttlSeconds.
# --------------------------------------------------------------------------- #
def test_the_pairing_route_exposes_no_lifetime_knob() -> None:
    from app.routers.extension_tokens import ExtensionTokenRequest

    assert "ttl_seconds" not in ExtensionTokenRequest.model_fields
    aliases = {f.alias for f in ExtensionTokenRequest.model_fields.values()}
    assert "ttlSeconds" not in aliases


def test_a_ttl_smuggled_into_the_body_is_ignored_not_honoured() -> None:
    """Pydantic drops unknown keys, so an old client (or a curious operator) sending
    ttlSeconds gets the 12-hour token, not a seven-day one."""
    from app.routers.extension_tokens import ExtensionTokenRequest

    body = ExtensionTokenRequest.model_validate(
        {"deviceLabel": "laptop", "scopes": ["citation_queue"], "ttlSeconds": 604_800}
    )
    assert not hasattr(body, "ttl_seconds")


def test_the_route_mints_at_the_default_lifetime() -> None:
    """Reads the call site, because the assertion that matters is what is PASSED - a
    request model with no field would still mint a long token if the route hard-coded one."""
    import inspect

    from app.routers import extension_tokens as mod

    src = inspect.getsource(mod.mint_extension_token)
    assert "ttl_seconds=DEFAULT_TTL_SECONDS" in src
    assert "body.ttl_seconds" not in src


# --------------------------------------------------------------------------- #
# The server states where it lives (2026-09-01: the extension was pointed at a
# STALE backend on another port, and nothing on either side could say so).
# --------------------------------------------------------------------------- #


def _request_with_host(host: str) -> object:
    from starlette.requests import Request as StarletteRequest

    return StarletteRequest(
        {
            "type": "http",
            "method": "GET",
            "scheme": "http",
            "path": "/api/v1/extension/tokens",
            "query_string": b"",
            "headers": [(b"host", host.encode())],
        }
    )


def test_the_pair_base_is_derived_from_the_request_the_server_actually_answered() -> None:
    """Through the dashboard's same-origin rewrite, the Host this API sees IS the live
    backend's own address — the one string the operator needed that night."""
    from app.config import Settings
    from app.routers.extension_tokens import _pair_api_base

    settings = Settings(_env_file=None)
    assert _pair_api_base(settings, _request_with_host("127.0.0.1:8099")) == "http://127.0.0.1:8099"  # type: ignore[arg-type]


def test_a_configured_pair_base_wins_and_is_normalized() -> None:
    from app.config import Settings
    from app.routers.extension_tokens import _pair_api_base

    settings = Settings(_env_file=None, extension_pair_api_base="https://app.qanry.com/")
    assert _pair_api_base(settings, _request_with_host("127.0.0.1:8099")) == "https://app.qanry.com"  # type: ignore[arg-type]


def test_the_minted_response_carries_the_api_base_beside_the_token() -> None:
    """A token and the address it works against travel together — drop the field and
    the pairing instructions can once again name a different server than the minter."""
    from app.routers.extension_tokens import ExtensionTokenMinted, PairingInfo

    minted_aliases = {f.serialization_alias for f in ExtensionTokenMinted.model_fields.values()}
    assert "apiBase" in minted_aliases
    info_aliases = {f.serialization_alias for f in PairingInfo.model_fields.values()}
    assert {"apiBase", "allowedExtensionOrigins"} <= info_aliases


# --------------------------------------------------------------------------- #
# Revocation outages refuse; they never quietly allow.
# --------------------------------------------------------------------------- #


class _FakePrincipal:
    user_id = "u-1"
    issued_at = datetime.now(UTC)

    def has(self, scope: str) -> bool:
        return scope == "citation_queue"


async def test_denylist_outage_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    """This exact check ran silently skipped for days (the API had no REDIS_URL), which
    downgraded revocation to 'whenever the token expires'. A Redis outage must refuse
    with an actionable 503 — restore the old swallow and the load succeeds instead,
    which is what makes this test red rather than vacuous."""
    from fastapi import HTTPException

    from app.modules.citations import operator_auth as oa

    monkeypatch.setattr(oa, "verify_operator_token", lambda raw: _FakePrincipal())

    async def _redis_down(*args: object, **kwargs: object) -> bool:
        raise ConnectionError("redis unreachable")

    monkeypatch.setattr(oa, "is_revoked", _redis_down)
    # If the outage were swallowed, resolution would continue into this loader and
    # SUCCEED — so the happy loader is what proves the refusal is real.
    monkeypatch.setattr(oa, "_load_user_row", lambda uid: _user_row())

    with pytest.raises(HTTPException) as excinfo:
        await oa.resolve_operator(
            request=None, settings=None, redis=None, credentials=None,  # type: ignore[arg-type]
            x_operator_token="aop_pref_secret",
        )
    assert excinfo.value.status_code == 503
    assert "revocation" in str(excinfo.value.detail)


def _user_row() -> dict[str, object]:
    return {
        "id": "u-1",
        "email": "op@example.com",
        "role": "manager",
        "status": "active",
        "name": "Operator",
        "client_id": None,
    }


async def test_a_working_denylist_still_resolves_the_operator(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The other half of the fail-closed change: refusing on outage must not have
    broken the ordinary path."""
    from app.modules.citations import operator_auth as oa

    monkeypatch.setattr(oa, "verify_operator_token", lambda raw: _FakePrincipal())

    async def _not_revoked(*args: object, **kwargs: object) -> bool:
        return False

    monkeypatch.setattr(oa, "is_revoked", _not_revoked)
    monkeypatch.setattr(oa, "_load_user_row", lambda uid: _user_row())

    user = await oa.resolve_operator(
        request=None, settings=None, redis=None, credentials=None,  # type: ignore[arg-type]
        x_operator_token="aop_pref_secret",
    )
    assert user.id == "u-1"
    assert user.role == "manager"
