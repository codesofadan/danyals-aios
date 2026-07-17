"""The key_vault adapter is the SENSITIVE one: prove it can never reach a secret.

The vault has exactly ONE decrypt path in the whole system - ``vault.reveal_secret``,
owner-only behind ``require_owner`` in the vault router. This adapter must not be a
second one, and it must not become one by accident later: ``VaultRepo.list_keys`` is a
``select *``, so the sealed bytes ARE in the row dict handed to the builder. Nothing
but discipline stops a future "just show the masked preview" edit from formatting them
into a cell.

So this file pins the guarantee three ways, each catching a different mistake:

1. STATIC   - the module never imports or names a reveal/seal symbol (catches the edit
              that adds ``from app.services.vault import reveal_secret``).
2. BEHAVIOUR - a sealed blob planted in the row never reaches the response (catches the
              edit that formats ``secret_sealed`` into a cell).
3. ISOLATION - the vault service module is not touched at all while the route runs
              (catches an indirect call through some future helper).
"""

from __future__ import annotations

import ast
import inspect
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI

from app.core.auth import CurrentUser, get_current_user
from app.db.vault_repo import get_vault_repo
from app.modules.tool_workspaces import service as service_mod
from app.modules.tool_workspaces.service import build_key_vault_workspace

pytestmark = pytest.mark.unit

_WORKSPACE = "/api/v1/key-vault/workspace"

# Planted in the fake row's sealed column. If ANY of this reaches a response body, a
# ciphertext is on the wire.
_SEALED = b"\x00SEALED-CIPHERTEXT-DO-NOT-LEAK"
_MASKED = "sk-abc••••••••4cb6"


def _key_row(**over: Any) -> dict[str, Any]:
    """A vault row shaped EXACTLY as ``select * from vault_keys`` returns it - sealed
    column included. The adapter must be safe on THIS row, not on a sanitised one."""
    row: dict[str, Any] = {
        "id": "k1",
        "provider": "Serper.dev",
        "label": "Search",
        "masked": _MASKED,
        "secret_sealed": _SEALED,
        "key_version": 1,
        "kind": "api_key",
        "created_by": "00000000-0000-0000-0000-0000000000ff",
        "created_at": "2026-01-04T09:00:00+00:00",
        "updated_at": "2026-05-04T09:00:00+00:00",
    }
    row.update(over)
    return row


def _owner() -> CurrentUser:
    return CurrentUser(
        id="00000000-0000-0000-0000-0000000000ff", email="owner@aios.dev", role="owner",
        status="active", name="Owner", title="", avatar_color="#7B69EE", phone="",
        two_fa=False,
    )


@pytest.fixture
def wired(app: FastAPI) -> None:
    class _FakeVaultRepo:
        def list_keys(self) -> list[dict[str, Any]]:
            return [_key_row(), _key_row(id="k2", provider="Anthropic", label="Content AI")]

    app.dependency_overrides[get_vault_repo] = _FakeVaultRepo
    app.dependency_overrides[get_current_user] = _owner


# --------------------------------------------------------------------------- #
# 1. STATIC: no reveal/seal symbol is reachable from this module.
#
# Checked over the AST rather than the raw text, for two reasons: an import nested
# inside a function body is invisible to a module-attribute check but plain in the
# tree, and the tree carries no comments - so the modules stay free to DOCUMENT what
# they must not do (as they do at length) while this test still fails the moment any
# of it becomes code.
# --------------------------------------------------------------------------- #
# The module's own source files. Taken as PATHS off the service module rather than by
# importing ``...tool_workspaces.router`` - the package re-exports ``router`` as the
# APIRouter object, so that name does not resolve to the module.
_MODULE_DIR = Path(inspect.getfile(service_mod)).parent
_MODULES = (_MODULE_DIR / "router.py", _MODULE_DIR / "service.py", _MODULE_DIR / "__init__.py")
_MODULE_IDS = [p.name for p in _MODULES]

# Names the adapter has no legitimate reason to reference. `secret_sealed` is the
# column; the rest are the vault service's decrypt machinery.
_FORBIDDEN_SYMBOLS = frozenset(
    {"reveal_secret", "_open", "_seal", "_master_key", "secret_sealed"}
)


def _tree(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"))


def _docstrings(tree: ast.Module) -> set[int]:
    """The node ids of every docstring Constant, so prose is excluded from the sweep."""
    out: set[int] = set()
    holders = (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
    for node in ast.walk(tree):
        if isinstance(node, holders) and node.body:
            first = node.body[0]
            if (
                isinstance(first, ast.Expr)
                and isinstance(first.value, ast.Constant)
                and isinstance(first.value.value, str)
            ):
                out.add(id(first.value))
    return out


@pytest.mark.parametrize("path", _MODULES, ids=_MODULE_IDS)
def test_the_module_never_references_a_secret_symbol_in_code(path: Path) -> None:
    """No identifier, attribute, or string literal names the decrypt machinery or the
    sealed column - so ``row["secret_sealed"]`` and ``vault.reveal_secret`` both fail
    here, while the docstrings explaining why remain legal."""
    tree = _tree(path)
    skip = _docstrings(tree)
    offenders: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id in _FORBIDDEN_SYMBOLS:
            offenders.append(f"name {node.id!r} (line {node.lineno})")
        elif isinstance(node, ast.Attribute) and node.attr in _FORBIDDEN_SYMBOLS:
            offenders.append(f"attribute .{node.attr} (line {node.lineno})")
        elif (
            isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and id(node) not in skip
            and node.value in _FORBIDDEN_SYMBOLS
        ):
            offenders.append(f"string {node.value!r} (line {node.lineno})")
    assert not offenders, f"{path.name} reaches for the vault's secrets: {offenders}"


@pytest.mark.parametrize("path", _MODULES, ids=_MODULE_IDS)
def test_the_vault_service_is_never_imported(path: Path) -> None:
    """The adapter reads the repo's masked list; it has no business importing the
    service that holds the master key. Catches a nested (in-function) import too."""
    for node in ast.walk(_tree(path)):
        if isinstance(node, ast.ImportFrom):
            assert node.module != "app.services.vault", f"{path.name} line {node.lineno}"
        elif isinstance(node, ast.Import):
            for alias in node.names:
                assert alias.name != "app.services.vault", f"{path.name} line {node.lineno}"


def test_the_static_sweep_can_actually_see_a_violation() -> None:
    """Guard for the guard: the AST walk above must reject the very code it exists to
    prevent, rather than passing because it looks in the wrong place."""
    tree = ast.parse('def leak(row):\n    return row["secret_sealed"]\n')
    skip = _docstrings(tree)
    hits = [
        n.value for n in ast.walk(tree)
        if isinstance(n, ast.Constant) and isinstance(n.value, str)
        and id(n) not in skip and n.value in _FORBIDDEN_SYMBOLS
    ]
    assert hits == ["secret_sealed"]


# --------------------------------------------------------------------------- #
# 2. BEHAVIOUR: nothing sealed, masked, or secret reaches the response.
# --------------------------------------------------------------------------- #
async def test_no_sealed_bytes_reach_the_response(
    client: httpx.AsyncClient, wired: None
) -> None:
    resp = await client.get(_WORKSPACE)
    assert resp.status_code == 200, resp.text
    body = resp.text
    assert "SEALED" not in body
    assert "CIPHERTEXT" not in body
    assert "secret_sealed" not in body
    assert "secret" not in body.lower()


async def test_even_the_masked_preview_is_not_rendered(
    client: httpx.AsyncClient, wired: None
) -> None:
    """No column asks for it, so the workspace shows strictly LESS than the vault list
    already does. Pinned so a future "nice touch" edit has to argue with a test."""
    resp = await client.get(_WORKSPACE)
    assert _MASKED not in resp.text
    assert "masked" not in resp.text


async def test_the_response_carries_only_the_four_contract_columns(
    client: httpx.AsyncClient, wired: None
) -> None:
    """The table is metadata only: provider + scope + rotation month + a status."""
    body = (await client.get(_WORKSPACE)).json()
    assert body["table"]["cols"] == ["Provider", "Scope", "Last rotated", "Status"]
    first = body["table"]["rows"][0]
    assert first[0] == "Serper.dev"
    assert first[1] == "Search"
    assert first[2] == "May 2026"
    assert first[3] == {"v": "Active", "tone": "ok"}


def test_the_builder_ignores_every_non_display_field() -> None:
    """Feed the builder a row whose EVERY non-display column is a poison value. Only the
    four allow-listed metadata fields may survive into the output.
    """
    poisoned = _key_row(
        secret_sealed=b"POISON-SEALED",
        masked="POISON-MASKED",
        key_version="POISON-VERSION",
        kind="POISON-KIND",
        created_by="POISON-CREATOR",
        id="POISON-ID",
    )
    rendered = build_key_vault_workspace([poisoned]).model_dump_json()
    for poison in ("POISON-SEALED", "POISON-MASKED", "POISON-VERSION", "POISON-KIND",
                   "POISON-CREATOR", "POISON-ID"):
        assert poison not in rendered, f"{poison} survived into the workspace"
    # ... while the legitimate metadata did come through, so this is not passing
    # because the builder rendered nothing at all.
    assert "Serper.dev" in rendered
    assert "Search" in rendered


# --------------------------------------------------------------------------- #
# 3. ISOLATION: the vault service is never entered while the route runs.
# --------------------------------------------------------------------------- #
async def test_the_route_never_calls_into_the_vault_service(
    client: httpx.AsyncClient, wired: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Boobytrap every decrypt-adjacent entry point in the vault service. If the adapter
    ever reaches one - directly or through some future helper - the route explodes
    instead of quietly leaking."""
    tripped: list[str] = []

    def _trap(name: str) -> Any:
        def _boom(*args: Any, **kwargs: Any) -> Any:
            tripped.append(name)
            raise AssertionError(f"the key_vault workspace called vault.{name}")

        return _boom

    for name in ("reveal_secret", "_open", "_seal", "_master_key", "rotate_key", "add_key"):
        monkeypatch.setattr(f"app.services.vault.{name}", _trap(name))

    resp = await client.get(_WORKSPACE)
    assert resp.status_code == 200, resp.text
    assert tripped == []


async def test_an_empty_vault_renders_an_empty_table_not_a_500(
    app: FastAPI, client: httpx.AsyncClient
) -> None:
    class _EmptyVaultRepo:
        def list_keys(self) -> list[dict[str, Any]]:
            return []

    app.dependency_overrides[get_vault_repo] = _EmptyVaultRepo
    app.dependency_overrides[get_current_user] = _owner
    body = (await client.get(_WORKSPACE)).json()
    assert body["table"]["rows"] == []
    assert {k["label"]: k["value"] for k in body["kpis"]} == {
        "Keys stored": "0", "Integrations": "0", "Rotating soon": "—"
    }
