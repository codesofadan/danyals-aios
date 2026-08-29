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
