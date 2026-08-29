"""Directory accounts: closing the irrecoverable-login defect.

`citation_signup.py` generates a strong password, types it into the signup form, and
never stores it. Every account the bot has created has a login nobody can recover — so
those listings cannot be corrected, cannot be removed, and cannot be handed to an
operator. The only remaining move is to abandon the account and create a duplicate, which
is exactly what a citation campaign exists to prevent.
"""

from __future__ import annotations

import re
from typing import Any

import pytest

from app.services.citation_accounts import (
    _ALPHABET,
    _PASSWORD_LENGTH,
    create_account_with_credential,
    generate_password,
)

pytestmark = pytest.mark.unit


# --------------------------------------------------------------------------- #
# The password itself.
# --------------------------------------------------------------------------- #
def test_passwords_are_long_unique_and_drawn_from_secrets() -> None:
    """`secrets`, never `random`: this is a credential, and `random` is seeded and
    predictable. The module imports `secrets` — asserted, because a later edit reaching
    for `random.choice` would look harmless."""
    import inspect

    import app.services.citation_accounts as mod

    src = inspect.getsource(mod)
    assert "import secrets" in src
    assert "secrets.choice" in src
    assert not re.search(r"\brandom\.(choice|randint|sample)\b", src)

    pws = {generate_password() for _ in range(200)}
    assert len(pws) == 200, "generated passwords must not repeat"
    assert all(len(p) == _PASSWORD_LENGTH for p in pws)


def test_the_alphabet_excludes_characters_that_get_mistyped_or_break_forms() -> None:
    """A human reads these off a screen, and a directory form parses them. 0/O and 1/l/I
    get mistyped; quotes and backslashes break naive forms."""
    for ch in "0O1lI'\"`\\":
        assert ch not in _ALPHABET, f"{ch!r} should not be in the password alphabet"


# --------------------------------------------------------------------------- #
# The ordering that the whole design rests on.
# --------------------------------------------------------------------------- #
class _FakeCursor:
    def __init__(self, sink: dict[str, Any]) -> None:
        self.sink = sink
        self._row: dict[str, Any] | None = None
        self.rowcount = 1

    def execute(self, sql: str, params: Any = None) -> None:
        self.sink.setdefault("sql", []).append(sql)
        self.sink.setdefault("params", []).append(params)
        if sql.lstrip().lower().startswith("insert"):
            self._row = {
                "id": "acct-1", "client_id": "cl-1", "directory_id": "dir-1",
                "registration_email": "acme.brownbook@mail.example",
                # As the DATABASE would set them (0111's trigger), not as any caller asked.
                "vault_provider": "citation:Brownbook", "vault_label": "acct-1",
                "health": "unverified", "credential_sealed_at": None,
            }

    def fetchone(self) -> dict[str, Any] | None:
        return self._row


class _FakeConn:
    def __init__(self, sink: dict[str, Any]) -> None:
        self.sink = sink

    def __enter__(self) -> _FakeCursor:
        return _FakeCursor(self.sink)

    def __exit__(self, *a: Any) -> None:
        return None


@pytest.fixture
def wired(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    import app.services.citation_accounts as mod

    sink: dict[str, Any] = {"sealed": []}
    monkeypatch.setattr(mod, "rls_connection", lambda uid: _FakeConn(sink))

    def _add_key(**kw: Any) -> dict[str, Any]:
        sink["sealed"].append(kw)
        return {"id": "vk-1"}

    monkeypatch.setattr(mod.vault, "add_key", _add_key)
    return sink


def test_the_row_is_created_before_the_secret_is_sealed(wired: dict[str, Any]) -> None:
    """Forced by the schema and it is the whole design: the vault label IS the account
    row's own id, so the row must exist before the secret can be named."""
    account, plaintext = create_account_with_credential(
        user_id="u1", client_id="cl-1", directory_id="dir-1",
        registration_email="acme.brownbook@mail.example",
    )
    order = [s.strip().split()[0].lower() for s in wired["sql"]]
    assert order[0] == "insert", "the account row must exist first"
    assert order[-1] == "update", "sealed-at is stamped only after the vault call returned"
    assert len(wired["sealed"]) == 1
    assert account.id == "acct-1"
    assert plaintext and len(plaintext) == _PASSWORD_LENGTH


def test_the_secret_is_sealed_under_the_coordinates_the_database_chose(
    wired: dict[str, Any],
) -> None:
    """Not coordinates a caller supplied. This is what stops a lead pointing a citation
    account at some other row in the vault and reading it back through a citation route."""
    create_account_with_credential(
        user_id="u1", client_id="cl-1", directory_id="dir-1",
        registration_email="acme.brownbook@mail.example",
    )
    sealed = wired["sealed"][0]
    assert sealed["provider"] == "citation:Brownbook"
    assert sealed["label"] == "acct-1"
    assert sealed["kind"] == "client_access"


def test_a_failed_seal_deletes_the_row_rather_than_leaving_a_credentialless_account(
    monkeypatch: pytest.MonkeyPatch, wired: dict[str, Any],
) -> None:
    """A citation_account with no credential is WORSE than no row: it looks like an
    account we hold, and the unique (client_id, directory_id) constraint would then block
    the retry that would have created a working one."""
    import app.services.citation_accounts as mod

    def _boom(**kw: Any) -> dict[str, Any]:
        raise RuntimeError("vault master key missing")

    monkeypatch.setattr(mod.vault, "add_key", _boom)
    with pytest.raises(RuntimeError):
        create_account_with_credential(
            user_id="u1", client_id="cl-1", directory_id="dir-1",
            registration_email="acme.brownbook@mail.example",
        )
    assert any(s.strip().lower().startswith("delete") for s in wired["sql"]), (
        "a failed seal must remove the row it created"
    )


def test_no_password_is_ever_logged(monkeypatch: pytest.MonkeyPatch, wired: dict[str, Any]) -> None:
    """The one thing that must never reach a log line, an exception body, or a repr."""
    logged: list[tuple[Any, dict[str, Any]]] = []
    import app.services.citation_accounts as mod

    monkeypatch.setattr(mod.logger, "info", lambda *a, **kw: logged.append((a, kw)))
    monkeypatch.setattr(mod.logger, "warning", lambda *a, **kw: logged.append((a, kw)))

    _account, plaintext = create_account_with_credential(
        user_id="u1", client_id="cl-1", directory_id="dir-1",
        registration_email="acme.brownbook@mail.example",
    )
    blob = repr(logged)
    assert plaintext not in blob
    # And it is not passed to the database as anything but the vault call.
    assert plaintext not in repr(wired["params"])


def test_the_service_has_no_reveal_path() -> None:
    """Reading a directory password back is `vault.reveal_secret` — owner-only, enforced
    in its own router, audited in one place. A convenience reveal added here would be a
    second, unaudited one; an operator finishing a listing signs into the directory in
    their own browser and never needs the password."""
    import inspect

    import app.services.citation_accounts as mod

    src = inspect.getsource(mod)
    assert "reveal_secret" not in src.replace("`vault.reveal_secret`", "")
    assert "open_sealed" not in src
