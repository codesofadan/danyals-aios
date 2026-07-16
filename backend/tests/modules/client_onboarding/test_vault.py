"""The onboarding <-> Key Vault seam: the credential path, and the proof that adding
``kind`` (0041) weakened NOTHING.

This is the security-bearing suite of the module. It answers four questions:

1. Where does a collected credential actually GO? (Into the vault's sealed bytea, and
   nowhere else - not onto ``onboarding_steps``, not into a log.)
2. Can it come back OUT through onboarding? (No: the step holds an opaque reference,
   and this module has no reveal path at all.)
3. Does collecting it mark it VERIFIED? (No - never automatically. "Test every login".)
4. Did the ``kind`` column change anything about the vault's existing behaviour? (No:
   the masked list still carries no secret, reveal is still owner-only, the default is
   still ``api_key``, and the wire shape is byte-identical.)

No DB, no master key beyond an injected test key: ``privileged_connection`` is faked.
"""

from __future__ import annotations

import base64
import logging
import os
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

import pytest
from pydantic import SecretStr

from app.modules.client_onboarding import service as svc
from app.modules.client_onboarding.schemas import OnboardingStepResponse
from app.modules.client_onboarding.service import seal_step_credential
from app.services import vault as vault_svc
from app.services.vault import _open, add_key, mask_secret, rotate_key

pytestmark = pytest.mark.unit

# A realistic client access credential - the thing this module must never leak.
_CLIENT_SECRET = "orchard-gbp-manager!P@ss2026"
_AGENCY_KEY = "serper-live-9f2a4c7b8e1d3f0b"


class _Settings:
    """Minimal stand-in for ``get_settings()`` carrying just the master key."""

    def __init__(self, master_key: str | None) -> None:
        self.vault_master_key = SecretStr(master_key) if master_key is not None else None


@pytest.fixture
def master_key(monkeypatch: pytest.MonkeyPatch) -> str:
    key = base64.b64encode(os.urandom(32)).decode()
    monkeypatch.setattr(vault_svc, "get_settings", lambda: _Settings(key))
    return key


class _Cur:
    """A cursor fake covering vault.py's INSERT/UPDATE ... returning paths.

    Deliberately parses the params POSITIONALLY, like the real driver: if the column
    list and the bound values ever drift apart, this blows up rather than silently
    storing a secret in the wrong column.
    """

    def __init__(self, store: dict[str, dict[str, Any]]) -> None:
        self._store = store
        self._row: dict[str, Any] | None = None
        self.statements: list[str] = []

    def execute(self, sql: str, params: tuple[Any, ...]) -> None:
        self.statements.append(sql)
        if sql.strip().lower().startswith("insert"):
            provider, label, masked, sealed, key_version, created_by, kind = params
            # A REAL uuid, like the column: ``rotate_key`` parses the id as one and
            # returns None for anything else, so a "vk-1" fake id would make every
            # rotate test vacuously pass by never reaching the update at all.
            key_id = str(uuid.UUID(int=len(self._store) + 1))
            self._store[key_id] = {
                "id": key_id, "provider": provider, "label": label, "masked": masked,
                "secret_sealed": bytes(sealed), "key_version": key_version,
                "created_by": created_by, "kind": kind, "created_at": datetime.now(UTC),
            }
            self._row = {
                k: self._store[key_id][k]
                for k in ("id", "provider", "label", "masked", "kind", "created_at")
            }
        else:  # update ... returning (rotate)
            sealed, masked, key_id = params
            row = self._store[str(key_id)]
            row.update({"secret_sealed": bytes(sealed), "masked": masked})
            self._row = {
                k: row[k] for k in ("id", "provider", "label", "masked", "kind", "created_at")
            }

    def fetchone(self) -> dict[str, Any] | None:
        return self._row


@pytest.fixture
def store(monkeypatch: pytest.MonkeyPatch, master_key: str) -> Iterator[dict[str, dict[str, Any]]]:
    """A fake vault table + a real seal, so a test can inspect what was PERSISTED."""
    rows: dict[str, dict[str, Any]] = {}
    cursor = _Cur(rows)

    class _Ctx:
        def __enter__(self) -> _Cur:
            return cursor

        def __exit__(self, *_a: Any) -> None:
            return None

    monkeypatch.setattr(vault_svc, "privileged_connection", lambda: _Ctx())
    yield rows


# --------------------------------------------------------------------------- #
# 1. Where the credential goes: the vault's sealed bytea, and nowhere else.
# --------------------------------------------------------------------------- #
def test_a_collected_credential_is_sealed_not_stored_in_the_clear(
    store: dict[str, dict[str, Any]]
) -> None:
    seal_step_credential(
        step_key="collect_gbp", credential_label="GBP manager login",
        secret=_CLIENT_SECRET, created_by="u-1",
    )
    stored = next(iter(store.values()))
    # The column holds sealed bytes - the plaintext is not recoverable from a dump...
    assert stored["secret_sealed"] != _CLIENT_SECRET.encode()
    assert _CLIENT_SECRET.encode() not in stored["secret_sealed"]
    # ... but decrypts back to the original under the master key.
    assert _open(stored["secret_sealed"]) == _CLIENT_SECRET


def test_the_seal_returns_only_a_reference(store: dict[str, dict[str, Any]]) -> None:
    ref = seal_step_credential(
        step_key="collect_gbp", credential_label="GBP", secret=_CLIENT_SECRET, created_by=None
    )
    assert ref == next(iter(store))  # the vault row's id...
    assert uuid.UUID(ref)  # ... an opaque uuid, nothing more
    assert _CLIENT_SECRET not in ref


def test_the_stored_row_carries_only_a_masked_preview_of_the_credential(
    store: dict[str, dict[str, Any]]
) -> None:
    seal_step_credential(
        step_key="collect_gbp", credential_label="GBP", secret=_CLIENT_SECRET, created_by=None
    )
    stored = next(iter(store.values()))
    assert stored["masked"] == mask_secret(_CLIENT_SECRET)
    assert _CLIENT_SECRET not in stored["masked"]


def test_the_step_row_receives_the_reference_and_nothing_else(
    store: dict[str, dict[str, Any]]
) -> None:
    """The structural claim of 0040: ``onboarding_steps`` has NO secret column, so the
    only thing the seal can hand back to a step is an opaque id."""
    ref = seal_step_credential(
        step_key="collect_gbp", credential_label="GBP", secret=_CLIENT_SECRET, created_by=None
    )
    # What the router writes onto the step:
    step_changes = {"vault_secret_id": ref}
    assert _CLIENT_SECRET not in str(step_changes)
    # ... and what the step then renders:
    body = OnboardingStepResponse.from_row({
        "id": "st-1", "step_key": "collect_gbp", "label": "Collect GBP access",
        "client_name": "Orchard Pediatrics", "status": "completed",
        "vault_secret_id": ref, "verified": False, "sort_order": 2,
    }).model_dump_json(by_alias=True)
    assert _CLIENT_SECRET not in body
    assert ref not in body  # not even the reference
    assert '"hasCredential":true' in body  # only that one EXISTS


def test_nothing_secret_reaches_the_logs(
    store: dict[str, dict[str, Any]], master_key: str, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.DEBUG):
        seal_step_credential(
            step_key="collect_gbp", credential_label="GBP manager login",
            secret=_CLIENT_SECRET, created_by="u-1",
        )
    assert _CLIENT_SECRET not in caplog.text
    assert master_key not in caplog.text


def test_a_seed_failure_log_never_carries_a_credential(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """The module's own warning logs name IDs, never payloads."""

    def _boom(_uid: str) -> Any:
        raise RuntimeError(f"connection string contained {_CLIENT_SECRET}")

    monkeypatch.setattr(svc, "OnboardingRepo", _boom)
    with caplog.at_level(logging.WARNING):
        svc.seed_onboarding_for_client("u-1", "cl-1", "Acme", "u-1", "Sara")
    # The exception text is NOT interpolated into the log line.
    assert _CLIENT_SECRET not in caplog.text


# --------------------------------------------------------------------------- #
# 2. The `kind` dimension: additive, and it grants nothing.
# --------------------------------------------------------------------------- #
def test_a_client_credential_is_sealed_as_client_access(
    store: dict[str, dict[str, Any]]
) -> None:
    seal_step_credential(
        step_key="collect_gbp", credential_label="GBP", secret=_CLIENT_SECRET, created_by=None
    )
    stored = next(iter(store.values()))
    assert stored["kind"] == "client_access"
    # `provider` keeps meaning what it always meant: WHAT this opens.
    assert stored["provider"] == "gbp"


def test_kind_defaults_to_api_key_so_every_existing_caller_is_unchanged(
    store: dict[str, dict[str, Any]]
) -> None:
    """THE additive-change proof: the vault router calls ``add_key`` WITHOUT ``kind``
    (it is not in its signature), and that call must keep behaving exactly as it did
    before 0041 - an agency API key."""
    add_key(provider="serper", label="Prod", secret=_AGENCY_KEY, created_by=None)
    stored = next(iter(store.values()))
    assert stored["kind"] == "api_key"


def test_the_two_populations_are_distinguishable_without_opening_either(
    store: dict[str, dict[str, Any]]
) -> None:
    """Exactly what the dimension buys: telling an agency key from a client login
    WITHOUT any new access to the sealed bytes."""
    add_key(provider="serper", label="Prod", secret=_AGENCY_KEY, created_by=None)
    seal_step_credential(
        step_key="collect_analytics", credential_label="GA4", secret=_CLIENT_SECRET,
        created_by=None,
    )
    kinds = {r["provider"]: r["kind"] for r in store.values()}
    assert kinds == {"serper": "api_key", "analytics": "client_access"}


def test_kind_is_returned_in_the_masked_metadata_and_the_secret_is_not(
    store: dict[str, dict[str, Any]]
) -> None:
    meta = add_key(
        provider="serper", label="Prod", secret=_AGENCY_KEY, created_by=None, kind="api_key"
    )
    assert meta["kind"] == "api_key"
    assert _AGENCY_KEY not in str(meta)  # masked metadata only, exactly as before
    assert "secret_sealed" not in meta  # the sealed bytes never ride along either


def test_rotating_a_secret_does_not_change_its_kind(
    store: dict[str, dict[str, Any]]
) -> None:
    """Replacing a secret's VALUE does not change its SPECIES - a rotated client login
    is still a client login (the same reasoning that leaves key_version alone)."""
    seal_step_credential(
        step_key="collect_gbp", credential_label="GBP", secret=_CLIENT_SECRET, created_by=None
    )
    key_id = next(iter(store))
    meta = rotate_key(key_id, "orchard-gbp-manager!NewP@ss2027")
    assert meta is not None and meta["kind"] == "client_access"
    assert store[key_id]["kind"] == "client_access"


def test_rotating_a_client_credential_reseals_it_under_the_same_master_key(
    store: dict[str, dict[str, Any]]
) -> None:
    seal_step_credential(
        step_key="collect_gbp", credential_label="GBP", secret=_CLIENT_SECRET, created_by=None
    )
    key_id = next(iter(store))
    new_secret = "orchard-gbp-manager!NewP@ss2027"
    rotate_key(key_id, new_secret)
    # Same construction, same guarantees: sealed at rest, openable only server-side.
    assert store[key_id]["secret_sealed"] != new_secret.encode()
    assert _open(store[key_id]["secret_sealed"]) == new_secret
    assert store[key_id]["masked"] == mask_secret(new_secret)


def test_a_client_credential_is_sealed_with_the_same_key_version(
    store: dict[str, dict[str, Any]]
) -> None:
    # kind is orthogonal to master-key rotation: both populations rotate together.
    seal_step_credential(
        step_key="collect_gbp", credential_label="GBP", secret=_CLIENT_SECRET, created_by=None
    )
    assert next(iter(store.values()))["key_version"] == 1


def test_a_client_credential_seals_with_a_fresh_nonce_like_any_other(
    store: dict[str, dict[str, Any]]
) -> None:
    seal_step_credential(
        step_key="collect_gbp", credential_label="A", secret=_CLIENT_SECRET, created_by=None
    )
    seal_step_credential(
        step_key="collect_gbp", credential_label="B", secret=_CLIENT_SECRET, created_by=None
    )
    a, b = (r["secret_sealed"] for r in store.values())
    assert a != b  # distinct random nonces for the same plaintext
    assert _open(a) == _open(b) == _CLIENT_SECRET


# --------------------------------------------------------------------------- #
# 3. The existing vault invariants still hold.
# --------------------------------------------------------------------------- #
def test_the_masked_list_response_shape_is_unchanged_by_kind() -> None:
    """``VaultKeyResponse`` is CONTRACT-LOCKED to the frontend ``VaultKey`` type, so
    ``kind`` lives on the service's masked metadata and is deliberately NOT added to
    the wire model. This pins that the list still carries no secret and no new key."""
    from app.schemas.vault import VaultKeyResponse

    body = VaultKeyResponse.from_row({
        "id": "vk-1", "provider": "gbp", "label": "GBP manager login",
        "masked": mask_secret(_CLIENT_SECRET), "kind": "client_access",
        "secret_sealed": b"\x00\x01", "created_at": datetime.now(UTC).isoformat(),
    }).model_dump(by_alias=True)
    assert body["secret"] == ""  # the masked list NEVER carries a secret
    assert "secret_sealed" not in body  # nor the ciphertext
    assert "kind" not in body  # the frontend contract is untouched


def test_the_vault_response_model_is_still_contract_locked_to_the_frontend() -> None:
    # Belt-and-braces over tests/test_contract_lock.py: adding `kind` to the response
    # would silently break the VaultKey lock, so pin the field set here too.
    from app.schemas.vault import VaultKeyResponse

    assert set(VaultKeyResponse.model_fields) == {
        "id", "provider", "label", "masked", "secret", "scope", "site", "status", "rotated",
    }


def test_there_is_exactly_one_decrypt_path_and_onboarding_is_not_in_it() -> None:
    """The claim 0041's header makes: no new read path to the sealed bytea. The
    onboarding module must not import, re-export, or wrap the reveal."""
    from app.modules.client_onboarding import repo as repo_mod
    from app.modules.client_onboarding import router as router_mod
    from app.modules.client_onboarding import schemas as schemas_mod

    for module in (svc, repo_mod, router_mod, schemas_mod):
        assert not hasattr(module, "reveal_secret")
        assert not hasattr(module, "_open")
    # The service imports exactly ONE thing from the vault: the seal.
    assert hasattr(svc, "add_key")


def test_the_onboarding_module_never_reads_the_sealed_column() -> None:
    """A grep-level guarantee: no statement anywhere in the module names the sealed
    bytea. The step's reference is as close to the secret as onboarding ever gets."""
    from pathlib import Path

    module_dir = Path(svc.__file__).parent
    for path in module_dir.glob("*.py"):
        source = path.read_text(encoding="utf-8")
        assert "secret_sealed" not in source, f"{path.name} names the sealed column"
        assert "reveal_secret" not in source, f"{path.name} reaches for the reveal path"


def test_reveal_remains_owner_only_and_untouched_by_this_module() -> None:
    # The vault router's reveal still sits behind require_owner - onboarding neither
    # widened it nor added a second door.
    import inspect

    from app.routers import vault as vault_router

    source = inspect.getsource(vault_router.reveal_vault_key)
    assert "Owner" in source  # the require_owner-bound annotation
    assert "SUPER-ADMIN ONLY" in source


# --------------------------------------------------------------------------- #
# 4. Collected is not verified.
# --------------------------------------------------------------------------- #
def test_sealing_a_credential_never_sets_verified(
    store: dict[str, dict[str, Any]]
) -> None:
    """The researched agency rule, at the lowest level: ``seal_step_credential``
    returns a REFERENCE and nothing else - it has no way to express "verified", so
    collection can never imply an access test."""
    result = seal_step_credential(
        step_key="collect_gbp", credential_label="GBP", secret=_CLIENT_SECRET, created_by=None
    )
    assert isinstance(result, str)  # just the id - no flag, no tuple, no dict


def test_a_step_with_a_sealed_credential_still_reads_unverified() -> None:
    body = OnboardingStepResponse.from_row({
        "id": "st-1", "step_key": "collect_gbp", "label": "Collect GBP access",
        "client_name": "Acme", "status": "completed", "vault_secret_id": "vk-1",
        "verified": False, "sort_order": 2,
    })
    # "We hold a credential" and "we proved it works" are different facts, and the
    # response says both, separately and honestly.
    assert body.has_credential is True
    assert body.verified is False
