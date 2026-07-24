"""Unit gate for the multi-client WordPress Connections registry (0058).

Covers the four security-bearing questions plus the wiring:

1. Does PUT SEAL the credential and store the sealed bytea (never plaintext)? And is
   the sealed secret NEVER returned to a client? (Service test against a fake DB + a
   real seal; router test proves the wire response carries no secret.)
2. Does GET list EVERY client with its per-client connection status?
3. Does a metadata-only edit keep the stored secret (coalesce)?
4. Does the connectivity TEST dispatch to the right adapter per auth method and record
   the verdict?

No DB, no network: ``privileged_connection`` is faked, the master key is injected, and
the publish adapters are faked.
"""

from __future__ import annotations

import base64
import os
from collections.abc import Callable, Iterator
from typing import Any

import httpx
import pytest

from app.config import Settings
from app.core.auth import CurrentUser, get_current_user
from app.db.wp_connections_repo import get_wp_connections_repo
from app.schemas.wp_connections import WpConnectionResponse, WpConnectionUpsert
from app.services import vault as vault_svc
from app.services import wp_connections as wpc
from app.services.vault import open_sealed

pytestmark = pytest.mark.unit

_CLIENT_ID = "11111111-1111-1111-1111-111111111111"
_OTHER_ID = "22222222-2222-2222-2222-222222222222"


# --------------------------------------------------------------------------- #
# Pure schema behaviour
# --------------------------------------------------------------------------- #
def test_upsert_secret_selects_api_key_for_plugin() -> None:
    body = WpConnectionUpsert(site_url="https://a.test", auth_method="plugin", api_key="  key-123  ")
    assert body.secret() == "key-123"  # trimmed


def test_upsert_secret_selects_password_for_login_methods() -> None:
    for method in ("xmlrpc", "app_password"):
        body = WpConnectionUpsert(
            site_url="https://a.test", auth_method=method,  # type: ignore[arg-type]
            username="editor", password="pw-9",
        )
        assert body.secret() == "pw-9"


def test_upsert_secret_blank_is_none_to_keep_existing() -> None:
    # A metadata-only edit omits the secret -> None so the stored one is kept.
    assert WpConnectionUpsert(site_url="https://a.test", auth_method="plugin").secret() is None
    assert WpConnectionUpsert(site_url="https://a.test", auth_method="plugin", api_key="   ").secret() is None


def test_response_from_row_masks_and_flags() -> None:
    row = {
        "client_id": _CLIENT_ID, "client_name": "Verde Cafe",
        "site_url": "https://verde.test", "auth_method": "xmlrpc",
        "username": "editor", "status": "connected", "configured": True,
        "last_tested_at": None,
    }
    resp = WpConnectionResponse.from_row(row)
    dumped = resp.model_dump(by_alias=True)
    assert dumped["status"] == "connected"
    assert dumped["configured"] is True
    assert dumped["authMethod"] == "xmlrpc"
    # No secret material anywhere on the wire.
    assert "secret" not in dumped and "secret_sealed" not in dumped and "password" not in dumped


def test_response_from_row_unconfigured_placeholder() -> None:
    # A client with no connection row (LEFT JOIN nulls) reads as an unconfigured
    # placeholder, defaulting the method to plugin.
    row = {"client_id": _CLIENT_ID, "client_name": "Solo", "configured": False}
    resp = WpConnectionResponse.from_row(row)
    assert resp.status == "unconfigured"
    assert resp.auth_method == "plugin"
    assert resp.configured is False
    assert resp.site_url == ""


# --------------------------------------------------------------------------- #
# Service: a fake wp_connections table + a REAL seal (inspect what is persisted)
# --------------------------------------------------------------------------- #
class _Settings:
    def __init__(self, master_key: str) -> None:
        from pydantic import SecretStr

        self.vault_master_key = SecretStr(master_key)


class _FakeCur:
    """A cursor fake covering the service's SQL: the upsert (with coalesce), the
    resolve SELECT, the status UPDATE, and the DELETE. Keyed by client_id."""

    def __init__(self, store: dict[str, dict[str, Any]]) -> None:
        self._store = store
        self._row: dict[str, Any] | None = None

    def execute(self, sql: str, params: tuple[Any, ...]) -> None:
        s = sql.strip().lower()
        if s.startswith("insert"):
            client_id, site_url, auth_method, username, sealed = params
            prev = self._store.get(str(client_id), {})
            # coalesce(excluded.secret_sealed, existing): a None new secret keeps the old.
            secret = bytes(sealed) if sealed is not None else prev.get("secret_sealed")
            self._store[str(client_id)] = {
                "client_id": str(client_id), "site_url": site_url, "auth_method": auth_method,
                "username": username, "secret_sealed": secret,
                "status": prev.get("status", "unknown"), "last_tested_at": prev.get("last_tested_at"),
            }
            self._row = self._meta(str(client_id))
        elif s.startswith("select"):
            row = self._store.get(str(params[0]))
            self._row = None if row is None else {
                "site_url": row["site_url"], "auth_method": row["auth_method"],
                "username": row["username"], "secret_sealed": row["secret_sealed"],
            }
        elif s.startswith("update"):
            status, client_id = params
            row = self._store.get(str(client_id))
            if row is None:
                self._row = None
            else:
                row["status"] = status
                row["last_tested_at"] = "2026-07-25T00:00:00+00:00"
                self._row = self._meta(str(client_id))
        elif s.startswith("delete"):
            removed = self._store.pop(str(params[0]), None)
            self._row = {"client_id": str(params[0])} if removed is not None else None

    def _meta(self, client_id: str) -> dict[str, Any]:
        row = self._store[client_id]
        return {
            "client_id": client_id, "site_url": row["site_url"], "auth_method": row["auth_method"],
            "username": row["username"], "status": row["status"],
            "last_tested_at": row["last_tested_at"], "configured": row["secret_sealed"] is not None,
        }

    def fetchone(self) -> dict[str, Any] | None:
        return self._row


@pytest.fixture
def fake_db(monkeypatch: pytest.MonkeyPatch) -> Iterator[dict[str, dict[str, Any]]]:
    """A fake table + real AES-256-GCM seal, so a test can inspect what was PERSISTED."""
    key = base64.b64encode(os.urandom(32)).decode()
    monkeypatch.setattr(vault_svc, "get_settings", lambda: _Settings(key))
    rows: dict[str, dict[str, Any]] = {}
    cursor = _FakeCur(rows)

    class _Ctx:
        def __enter__(self) -> _FakeCur:
            return cursor

        def __exit__(self, *_a: Any) -> None:
            return None

    monkeypatch.setattr(wpc, "privileged_connection", lambda: _Ctx())
    yield rows


def test_upsert_seals_secret_and_never_returns_it(fake_db: dict[str, dict[str, Any]]) -> None:
    meta = wpc.upsert_connection(
        client_id=_CLIENT_ID, site_url="https://verde.test", auth_method="app_password",
        username="editor", secret="super-secret-app-pw",
    )
    assert meta is not None
    # The response metadata carries NO secret material - only masked columns + a flag.
    assert "secret_sealed" not in meta and "secret" not in meta and "password" not in meta
    assert meta["configured"] is True
    # What was PERSISTED is the SEALED bytea, and it opens back to the exact plaintext.
    stored = fake_db[_CLIENT_ID]["secret_sealed"]
    assert isinstance(stored, bytes)
    assert stored != b"super-secret-app-pw"  # not plaintext at rest
    assert open_sealed(stored) == "super-secret-app-pw"


def test_resolve_connection_opens_the_secret(fake_db: dict[str, dict[str, Any]]) -> None:
    wpc.upsert_connection(
        client_id=_CLIENT_ID, site_url="https://verde.test", auth_method="xmlrpc",
        username="editor", secret="xml-pass",
    )
    resolved = wpc.resolve_connection(_CLIENT_ID)
    assert resolved is not None
    assert resolved.auth_method == "xmlrpc"
    assert resolved.username == "editor"
    assert resolved.secret == "xml-pass"  # opened server-side, never on the wire


def test_metadata_only_edit_keeps_the_stored_secret(fake_db: dict[str, dict[str, Any]]) -> None:
    wpc.upsert_connection(
        client_id=_CLIENT_ID, site_url="https://old.test", auth_method="plugin",
        username="", secret="plugin-key",
    )
    # Re-save with a NEW site_url but NO secret (secret=None) -> keep the credential.
    wpc.upsert_connection(
        client_id=_CLIENT_ID, site_url="https://new.test", auth_method="plugin",
        username="", secret=None,
    )
    resolved = wpc.resolve_connection(_CLIENT_ID)
    assert resolved is not None
    assert resolved.site_url == "https://new.test"  # metadata updated
    assert resolved.secret == "plugin-key"  # secret preserved


def test_resolve_none_when_no_secret_yet(fake_db: dict[str, dict[str, Any]]) -> None:
    wpc.upsert_connection(
        client_id=_CLIENT_ID, site_url="https://verde.test", auth_method="plugin",
        username="", secret=None,  # site saved, no credential yet
    )
    assert wpc.resolve_connection(_CLIENT_ID) is None
    assert wpc.resolve_connection("33333333-3333-3333-3333-333333333333") is None  # no row


def test_delete_removes_the_connection(fake_db: dict[str, dict[str, Any]]) -> None:
    wpc.upsert_connection(
        client_id=_CLIENT_ID, site_url="https://verde.test", auth_method="plugin",
        username="", secret="k",
    )
    assert wpc.delete_connection(_CLIENT_ID) is True
    assert _CLIENT_ID not in fake_db
    assert wpc.delete_connection(_CLIENT_ID) is False  # already gone


# --------------------------------------------------------------------------- #
# verify_connection: dispatch to the right adapter per auth method (faked)
# --------------------------------------------------------------------------- #
def _resolved(method: str, *, secret: str = "s", site: str = "https://verde.test") -> wpc.ResolvedWpConnection:
    return wpc.ResolvedWpConnection(
        client_id=_CLIENT_ID, site_url=site, auth_method=method, username="editor", secret=secret
    )


def test_verify_empty_site_is_false() -> None:
    ok, detail = wpc.verify_connection(_resolved("plugin", site=""), Settings(_env_file=None, app_env="dev"))
    assert ok is False and "site url" in detail.lower()


def test_verify_plugin_uses_ping(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, Any] = {}

    class _FakePlugin:
        def __init__(self, **kw: Any) -> None:
            seen.update(kw)

        def ping(self) -> bool:
            return True

    monkeypatch.setattr("integrations.wordpress_publisher.WordPressPluginPublisher", _FakePlugin)
    ok, _detail = wpc.verify_connection(_resolved("plugin", secret="the-key"), Settings(_env_file=None, app_env="dev"))
    assert ok is True
    assert seen["api_key"] == "the-key"  # the resolved secret is handed to the adapter


def test_verify_xmlrpc_and_app_password_use_verify(monkeypatch: pytest.MonkeyPatch) -> None:
    class _FakeXml:
        def __init__(self, **_kw: Any) -> None: ...
        def verify(self, site_url: str) -> tuple[bool, str]:
            return True, "xml ok"

    class _FakeRest:
        def __init__(self, **_kw: Any) -> None: ...
        def verify(self, site_url: str) -> tuple[bool, str]:
            return False, "rest bad creds"

    monkeypatch.setattr("integrations.wordpress.XmlRpcWordPressPublisher", _FakeXml)
    monkeypatch.setattr("integrations.wordpress.WordPressClient", _FakeRest)
    s = Settings(_env_file=None, app_env="dev")
    assert wpc.verify_connection(_resolved("xmlrpc"), s) == (True, "xml ok")
    assert wpc.verify_connection(_resolved("app_password"), s) == (False, "rest bad creds")


# --------------------------------------------------------------------------- #
# Router: RBAC, per-client listing, PUT masks + delegates sealing, test endpoint
# --------------------------------------------------------------------------- #
class _FakeRepo:
    """A fake WpConnectionsRepo: the RLS join read surface (no DB)."""

    def __init__(self, rows: list[dict[str, Any]], *, client_exists: bool = True) -> None:
        self._rows = rows
        self._client_exists = client_exists

    def list_with_clients(self) -> list[dict[str, Any]]:
        return list(self._rows)

    def get_for_client(self, client_id: str) -> dict[str, Any] | None:
        if not self._client_exists:
            return None
        for r in self._rows:
            if str(r["client_id"]) == str(client_id):
                return r
        return {"client_id": client_id, "client_name": "Verde Cafe", "configured": False}


def _user(role: str) -> CurrentUser:
    return CurrentUser(
        id="00000000-0000-0000-0000-0000000000aa", email="op@x.com", role=role,  # type: ignore[arg-type]
        status="active", name="Op", title="", avatar_color="#000", phone="", two_fa=False,
    )


@pytest.fixture
def wire(app: Any) -> Callable[..., _FakeRepo]:
    def _as(role: str, rows: list[dict[str, Any]] | None = None, *, client_exists: bool = True) -> _FakeRepo:
        repo = _FakeRepo(rows or [], client_exists=client_exists)
        app.dependency_overrides[get_current_user] = lambda: _user(role)
        app.dependency_overrides[get_wp_connections_repo] = lambda: repo
        return repo

    return _as


async def test_list_returns_per_client_status(client: httpx.AsyncClient, wire: Callable[..., _FakeRepo]) -> None:
    wire("admin", [
        {"client_id": _CLIENT_ID, "client_name": "Verde", "site_url": "https://verde.test",
         "auth_method": "plugin", "username": "", "status": "connected", "configured": True,
         "last_tested_at": None},
        {"client_id": _OTHER_ID, "client_name": "Solo", "site_url": None, "auth_method": None,
         "username": None, "status": None, "configured": False, "last_tested_at": None},
    ])
    resp = await client.get("/api/v1/wp-connections")
    assert resp.status_code == 200
    body = resp.json()
    assert {r["clientName"] for r in body} == {"Verde", "Solo"}
    by_name = {r["clientName"]: r for r in body}
    assert by_name["Verde"]["status"] == "connected" and by_name["Verde"]["configured"] is True
    assert by_name["Solo"]["status"] == "unconfigured"  # LEFT-JOIN placeholder
    # Never a secret on the wire.
    assert all("secret" not in r and "password" not in r for r in body)


async def test_portal_client_is_forbidden(client: httpx.AsyncClient, wire: Callable[..., _FakeRepo]) -> None:
    wire("client")  # a portal client holds no view_reports / manage_clients
    assert (await client.get("/api/v1/wp-connections")).status_code == 403
    assert (await client.put(f"/api/v1/wp-connections/{_CLIENT_ID}", json={"siteUrl": "x"})).status_code == 403


async def test_viewer_reads_but_cannot_write(client: httpx.AsyncClient, wire: Callable[..., _FakeRepo]) -> None:
    wire("viewer")  # holds view_reports, NOT manage_clients
    assert (await client.get("/api/v1/wp-connections")).status_code == 200
    put = await client.put(f"/api/v1/wp-connections/{_CLIENT_ID}", json={"siteUrl": "https://x.test"})
    assert put.status_code == 403


async def test_put_seals_via_service_and_never_returns_secret(
    client: httpx.AsyncClient, wire: Callable[..., _FakeRepo], monkeypatch: pytest.MonkeyPatch
) -> None:
    wire("admin", [
        {"client_id": _CLIENT_ID, "client_name": "Verde", "site_url": "https://verde.test",
         "auth_method": "app_password", "username": "editor", "status": "unknown",
         "configured": True, "last_tested_at": None},
    ])
    calls: list[dict[str, Any]] = []

    def _spy(**kw: Any) -> dict[str, Any]:
        calls.append(kw)
        return {"client_id": _CLIENT_ID, "configured": True}

    monkeypatch.setattr("app.services.wp_connections.upsert_connection", _spy)
    resp = await client.put(
        f"/api/v1/wp-connections/{_CLIENT_ID}",
        json={"siteUrl": "https://verde.test", "authMethod": "app_password",
              "username": "editor", "password": "top-secret-pw"},
    )
    assert resp.status_code == 200
    # The router handed the PLAINTEXT secret to the service (which seals it) ...
    assert calls[0]["secret"] == "top-secret-pw"
    assert calls[0]["auth_method"] == "app_password"
    # ... and the secret is NOWHERE in the wire response.
    assert "top-secret-pw" not in resp.text
    assert "secret" not in resp.json() and "password" not in resp.json()


async def test_put_404_when_client_missing(
    client: httpx.AsyncClient, wire: Callable[..., _FakeRepo]
) -> None:
    wire("admin", client_exists=False)
    resp = await client.put(f"/api/v1/wp-connections/{_CLIENT_ID}", json={"siteUrl": "https://x.test"})
    assert resp.status_code == 404


async def test_delete_connection(
    client: httpx.AsyncClient, wire: Callable[..., _FakeRepo], monkeypatch: pytest.MonkeyPatch
) -> None:
    wire("admin", [{"client_id": _CLIENT_ID, "client_name": "Verde", "configured": True,
                    "site_url": "https://v.test", "auth_method": "plugin", "username": "",
                    "status": "connected", "last_tested_at": None}])
    removed: list[str] = []
    monkeypatch.setattr("app.services.wp_connections.delete_connection", lambda cid: removed.append(cid) or True)
    resp = await client.delete(f"/api/v1/wp-connections/{_CLIENT_ID}")
    assert resp.status_code == 204
    assert removed == [_CLIENT_ID]


async def test_test_endpoint_returns_ok_and_detail(
    client: httpx.AsyncClient, wire: Callable[..., _FakeRepo], monkeypatch: pytest.MonkeyPatch
) -> None:
    wire("admin", [{"client_id": _CLIENT_ID, "client_name": "Verde", "configured": True,
                    "site_url": "https://v.test", "auth_method": "xmlrpc", "username": "editor",
                    "status": "unknown", "last_tested_at": None}])

    def _spy_test(cid: str, settings: Any) -> tuple[bool, str, dict[str, Any]]:
        return True, "XML-RPC reachable and the credentials were accepted", {"status": "connected"}

    monkeypatch.setattr("app.services.wp_connections.test_connection", _spy_test)
    resp = await client.post(f"/api/v1/wp-connections/{_CLIENT_ID}/test")
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert "reachable" in body["detail"].lower()
    assert body["status"] == "connected"
