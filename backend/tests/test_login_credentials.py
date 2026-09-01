"""A password lives in TWO places, and one writer has to keep them agreeing.

``auth.users.password_hash`` (argon2id) is what AUTHENTICATES. The AES-256-GCM
blob in ``public.vault_keys`` under the ``__login__`` sentinel is what an
owner/admin REOPENS from "Show login" to tell a locked-out person what their
password is. Both are written by :func:`app.services.login_credentials.set_password`
and by nothing else — that is the entire reason the function exists.

Until this file there was no test on the module at all, and the gap was not
theoretical: ``POST /me/password`` had grown its own private
``update auth.users set password_hash`` and so moved one of the two facts without
the other. The result was silent and looked authoritative — the new password
signed in, and Team Management went on displaying the PREVIOUS one for an admin
to read out to somebody. So the round-trip below is asserted through the real
crypto (a real key, a real seal, a real open) against a fake connection: a test
that stubbed the sealing would have passed just as happily on the broken code.
"""

from __future__ import annotations

import base64
import contextlib
import os
import uuid
from typing import Any

import pytest
from pydantic import SecretStr

from app.services import login_credentials as lc
from app.services import vault as vault_svc
from app.services.passwords import verify_password

pytestmark = pytest.mark.unit


class _Settings:
    """Minimal stand-in for ``get_settings()`` carrying just the master key."""

    def __init__(self, master_key: str | None) -> None:
        self.vault_master_key = SecretStr(master_key) if master_key is not None else None


@pytest.fixture
def master_key(monkeypatch: pytest.MonkeyPatch) -> str:
    """A fresh, valid 32-byte key so seal/open is REAL crypto, not a stub."""
    key = base64.b64encode(os.urandom(32)).decode()
    monkeypatch.setattr(vault_svc, "get_settings", lambda: _Settings(key))
    return key


class _FakeStore:
    """An in-memory stand-in for the two tables ``login_credentials`` writes.

    Only the statements that module actually issues are understood; anything else
    raises, so a future rewrite that changes the SQL cannot silently no-op here.
    """

    def __init__(self, known_users: set[str]) -> None:
        self.known = known_users
        self.hashes: dict[str, str] = {}
        self.must_reset: dict[str, bool] = dict.fromkeys(known_users, True)
        self.vault: list[dict[str, Any]] = []
        self.rowcount = 0
        self._fetched: dict[str, Any] | None = None

    def execute(self, query: Any, params: Any = None) -> None:
        q = " ".join(str(query).split())
        if q.startswith("update auth.users set password_hash"):
            pw_hash, uid = params
            hit = str(uid) in self.known
            self.rowcount = 1 if hit else 0
            if hit:
                self.hashes[str(uid)] = pw_hash
        elif q.startswith("update public.users set must_reset"):
            self.must_reset[str(params[0])] = False
        elif q.startswith("delete from public.vault_keys"):
            provider, label = params
            self.vault = [
                r for r in self.vault if not (r["provider"] == provider and r["label"] == label)
            ]
        elif q.startswith("insert into public.vault_keys"):
            provider, label, masked, sealed, key_version, kind = params
            self.vault.append({
                "provider": provider, "label": label, "masked": masked,
                "secret_sealed": sealed, "key_version": key_version, "kind": kind,
            })
        elif q.startswith("select secret_sealed from public.vault_keys"):
            provider, label = params
            rows = [r for r in self.vault if r["provider"] == provider and r["label"] == label]
            self._fetched = {"secret_sealed": rows[-1]["secret_sealed"]} if rows else None
        else:  # pragma: no cover - a guard, not a branch under test
            raise AssertionError(f"unexpected SQL: {q}")

    def fetchone(self) -> dict[str, Any] | None:
        return self._fetched


@pytest.fixture
def user_id() -> str:
    return str(uuid.uuid4())


@pytest.fixture
def store(monkeypatch: pytest.MonkeyPatch, user_id: str) -> _FakeStore:
    fake = _FakeStore({user_id})

    @contextlib.contextmanager
    def _fake_priv() -> Any:
        yield fake

    monkeypatch.setattr(lc, "privileged_connection", _fake_priv)
    return fake


# --- the invariant -----------------------------------------------------------


def test_set_password_writes_both_the_hash_and_the_recoverable_copy(
    store: _FakeStore, user_id: str, master_key: str
) -> None:
    assert lc.set_password(user_id, "first-password-1") is True

    # Authentication side: a real argon2id hash, never the plaintext.
    stored = store.hashes[user_id]
    assert stored.startswith("$argon2id$")
    assert "first-password-1" not in stored
    assert verify_password(stored, "first-password-1") is True

    # Reveal side: sealed, not plaintext, and it really opens.
    assert len(store.vault) == 1
    assert b"first-password-1" not in store.vault[0]["secret_sealed"]
    assert lc.reveal_password(user_id) == "first-password-1"


def test_a_second_set_moves_both_facts_together(
    store: _FakeStore, user_id: str, master_key: str
) -> None:
    """The regression that reached production, stated as an assertion.

    Changing a password must never leave the reveal tool holding the old one — an
    admin reading that value out to a locked-out colleague hands them a string
    that opens nothing, with no signal anywhere that it is stale.
    """
    lc.set_password(user_id, "first-password-1")
    lc.set_password(user_id, "second-password-2")

    assert verify_password(store.hashes[user_id], "second-password-2") is True
    assert verify_password(store.hashes[user_id], "first-password-1") is False
    assert lc.reveal_password(user_id) == "second-password-2"
    assert len(store.vault) == 1, "one current row per user, not an append-only pile"


def test_set_password_clears_must_reset(store: _FakeStore, user_id: str, master_key: str) -> None:
    lc.set_password(user_id, "first-password-1")
    assert store.must_reset[user_id] is False


# --- the honest failure modes ------------------------------------------------


def test_unknown_user_writes_nothing_and_returns_false(
    store: _FakeStore, master_key: str
) -> None:
    assert lc.set_password(str(uuid.uuid4()), "irrelevant-pw-1") is False
    assert store.vault == [], "no sealed copy for a user that does not exist"


def test_malformed_id_returns_false_without_touching_the_database(
    store: _FakeStore, master_key: str
) -> None:
    assert lc.set_password("not-a-uuid", "irrelevant-pw-1") is False
    assert store.hashes == {}


def test_reveal_is_none_when_nothing_was_captured(store: _FakeStore, user_id: str) -> None:
    """'Not captured' and 'the password is blank' must not render the same."""
    assert lc.reveal_password(user_id) is None


def test_missing_vault_key_still_sets_the_password(
    store: _FakeStore, user_id: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Sealing is best-effort BY CONTRACT: no master key must not block a rotation.

    The account simply becomes un-revealable until the key is set and the password
    is next written — which is what ``available: false`` reports to the operator.
    """
    monkeypatch.setattr(vault_svc, "get_settings", lambda: _Settings(None))
    assert lc.set_password(user_id, "first-password-1") is True
    assert verify_password(store.hashes[user_id], "first-password-1") is True
    assert store.vault == []
    assert lc.reveal_password(user_id) is None
