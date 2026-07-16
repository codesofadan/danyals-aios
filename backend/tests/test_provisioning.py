"""P6A-7 gate: provision_user writes the credential + identity to LOCAL Postgres.

Since the cutover, provisioning inserts ``auth.users`` (argon2id hash) +
``public.users`` (+ template grants) in one ``privileged_connection`` transaction.
Here the connection is faked (a recording cursor) so the WRITES are asserted
without a database: the credential is argon2id, the identity carries role/status/
username/client_id, and the template drives the grant count. The atomic write is
proven live in ``tests/integration/test_auth_login.py`` (local-login E2E).
"""

from __future__ import annotations

import contextlib
from typing import Any

import pytest

from app.services import provisioning
from app.services.provisioning import provision_user

pytestmark = pytest.mark.unit


class _RecordingCursor:
    """Captures execute/executemany calls and serves the final row-read back."""

    def __init__(self) -> None:
        self.executes: list[tuple[str, Any]] = []
        self.many: list[tuple[str, list[Any]]] = []
        self._user_row: dict[str, Any] | None = None

    def execute(self, query: Any, params: Any = None) -> None:
        q = str(query)
        self.executes.append((q, params))
        if "insert into public.users" in q:
            # params: (id, email, username, name, role, title, avatar_color,
            #          must_reset, must_setup_2fa, client_id)  -- status is a literal
            uid, email, username, name, role, title, color, must_reset, must_2fa, client_id = params
            self._user_row = {
                "id": uid, "email": email, "username": username, "name": name,
                "role": role, "title": title, "avatar_color": color,
                "status": "invited", "must_reset": must_reset,
                "must_setup_2fa": must_2fa, "client_id": client_id,
            }

    def executemany(self, query: Any, seq: Any) -> None:
        self.many.append((str(query), list(seq)))

    def fetchone(self) -> dict[str, Any] | None:
        return self._user_row


@pytest.fixture
def cur(monkeypatch: pytest.MonkeyPatch) -> _RecordingCursor:
    recorder = _RecordingCursor()

    @contextlib.contextmanager
    def _fake_priv() -> Any:
        yield recorder

    monkeypatch.setattr(provisioning, "privileged_connection", _fake_priv)
    return recorder


def _auth_insert(cur: _RecordingCursor) -> tuple[str, Any]:
    return next(e for e in cur.executes if "insert into auth.users" in e[0])


def test_provision_writes_argon2_credential_and_identity(cur: _RecordingCursor) -> None:
    row = provision_user(
        email="jane@x.com", password="secret12", name="Jane Doe",
        role="specialist", username="jane", template_key="seo",
    )
    assert row["role"] == "specialist"
    assert row["status"] == "invited"
    assert row["username"] == "jane"
    # The credential is an argon2id hash of the plaintext, NOT the plaintext.
    _q, params = _auth_insert(cur)
    _uid, email, password_hash = params
    assert email == "jane@x.com"
    assert password_hash.startswith("$argon2id$")
    assert "secret12" not in password_hash
    # Template grants seeded via executemany (SEO Specialist = 13 features).
    assert len(cur.many[0][1]) == 13


def test_provision_without_template_seeds_no_grants(cur: _RecordingCursor) -> None:
    provision_user(
        email="v@x.com", password="secret12", name="Vic", role="viewer",
        username="vic", template_key=None,
    )
    assert cur.many == []  # no executemany call


def test_provision_super_template_grants_all_features(cur: _RecordingCursor) -> None:
    provision_user(
        email="boss@x.com", password="secret12", name="The Boss", role="owner",
        username="boss", template_key="super",
    )
    assert len(cur.many[0][1]) == 17


def test_provision_client_pins_client_id(cur: _RecordingCursor) -> None:
    row = provision_user(
        email="portal@acme.com", password="secret12", name="Acme Portal",
        role="client", username="acme", client_id="cl-acme",
    )
    assert row["role"] == "client"
    assert row["client_id"] == "cl-acme"
    assert cur.many == []  # a client login never gets staff feature grants


def test_provision_client_requires_client_id(cur: _RecordingCursor) -> None:
    with pytest.raises(ValueError, match="client login requires client_id"):
        provision_user(
            email="portal@acme.com", password="secret12", name="Acme",
            role="client", username="acme",
        )


def test_provision_staff_rejects_client_id(cur: _RecordingCursor) -> None:
    with pytest.raises(ValueError, match="only a client login may set client_id"):
        provision_user(
            email="staff@x.com", password="secret12", name="Staff",
            role="admin", username="staff", client_id="cl-acme",
        )


def test_provision_flags_default_off(cur: _RecordingCursor) -> None:
    row = provision_user(
        email="v@x.com", password="secret12", name="Vic", role="viewer", username="vic",
    )
    # The plain (explicit-password) path never forces first-login onboarding.
    assert row["must_reset"] is False
    assert row["must_setup_2fa"] is False


def test_provision_explicit_grants_override_template(cur: _RecordingCursor) -> None:
    # An explicit feature_grants map WINS over a template; 'off' entries are dropped.
    provision_user(
        email="c@x.com", password="secret12", name="Cus Tom", role="specialist",
        username="custom", template_key="super",  # would be all 17...
        feature_grants={"rank_tracker": "full", "reporting": "view", "billing": "off"},
        must_reset=True, must_setup_2fa=True,
    )
    seeded = cur.many[0][1]
    assert {(k, lvl) for _uid, k, lvl in seeded} == {
        ("rank_tracker", "full"), ("reporting", "view"),
    }
    # The onboarding flags reach the identity insert.
    users_insert = next(e for e in cur.executes if "insert into public.users" in e[0])
    *_, must_reset, must_2fa, _client = users_insert[1]
    assert must_reset is True and must_2fa is True
