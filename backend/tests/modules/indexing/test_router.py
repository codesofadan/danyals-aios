"""Indexing endpoints: the access gates + the degrade-safe submit fan-out.

NO DB, NO network: the privileged append store + the RLS read repo are in-memory fakes
injected via ``dependency_overrides``, and the submit test targets only the (disabled by
default) IndexNow + Google engines so the fan-out records 'skipped' rows without ever
touching the network. Auth (401) is also swept app-wide by
``tests/test_route_auth_guard.py``; re-pinned here alongside the perm gates.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest
from fastapi import FastAPI

from app.core.auth import CurrentUser, get_current_user
from app.modules.indexing.repo import get_indexing_repo
from app.modules.indexing.router import get_indexing_store

pytestmark = pytest.mark.unit

_SUBMIT = "/api/v1/indexing/submit"
_LIST = "/api/v1/indexing/submissions"

# publish_content holders (may submit) vs. staff who only hold view_reports.
_PUBLISHERS = ["owner", "admin", "manager", "specialist"]
_READ_ONLY = ["analyst", "viewer"]


def _user(role: str) -> CurrentUser:
    return CurrentUser(
        id="00000000-0000-0000-0000-0000000000a1", email="op@aios.dev", role=role,  # type: ignore[arg-type]
        status="active", name="Op", title="", avatar_color="#000", phone="", two_fa=False,
        client_id="cl-A" if role == "client" else None,
    )


class FakeStore:
    """In-memory ``ServiceIndexingStore``: records + echoes a real-shaped row."""

    def __init__(self) -> None:
        self.rows: list[dict[str, Any]] = []

    def record(
        self, *, client_id: str | None, url: str, engine: str, status: str, detail: str
    ) -> dict[str, Any]:
        row = {
            "id": f"row-{len(self.rows)}", "client_id": client_id, "url": url,
            "engine": engine, "status": status, "detail": detail, "created_at": None,
        }
        self.rows.append(row)
        return row


class FakeRepo:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows
        self.kwargs: dict[str, Any] | None = None

    def list_submissions(self, **kwargs: Any) -> list[dict[str, Any]]:
        self.kwargs = kwargs
        return list(self.rows)


def _as(app: FastAPI, role: str) -> None:
    app.dependency_overrides[get_current_user] = lambda: _user(role)


# --------------------------------------------------------------------------- #
# Auth + perm gates.
# --------------------------------------------------------------------------- #
async def test_submit_rejects_unauthenticated(client: httpx.AsyncClient) -> None:
    assert (await client.post(_SUBMIT, json={"urls": ["https://acme.example/a"]})).status_code == 401


async def test_list_rejects_unauthenticated(client: httpx.AsyncClient) -> None:
    assert (await client.get(_LIST)).status_code == 401


@pytest.mark.parametrize("role", _READ_ONLY)
async def test_non_publisher_cannot_submit(
    app: FastAPI, client: httpx.AsyncClient, role: str
) -> None:
    _as(app, role)
    app.dependency_overrides[get_indexing_store] = lambda: FakeStore()
    resp = await client.post(_SUBMIT, json={"urls": ["https://acme.example/a"], "engines": ["indexnow"]})
    assert resp.status_code == 403, resp.text


# --------------------------------------------------------------------------- #
# Submit fan-out (engines disabled by default -> skipped rows, no network).
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("role", _PUBLISHERS)
async def test_publisher_submit_records_skipped_when_engines_off(
    app: FastAPI, client: httpx.AsyncClient, role: str
) -> None:
    _as(app, role)
    store = FakeStore()
    app.dependency_overrides[get_indexing_store] = lambda: store
    resp = await client.post(
        _SUBMIT,
        json={"urls": ["https://acme.example/a"], "engines": ["indexnow", "google"], "clientId": "cl-1"},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["submitted"] == 2 and data["skipped"] == 2 and data["ok"] == 0
    engines = {r["engine"] for r in data["results"]}
    assert engines == {"indexnow", "google"}
    # client_id never leaks a raw column name; it echoes as camelCase clientId.
    assert all(r["clientId"] == "cl-1" for r in data["results"])
    assert len(store.rows) == 2


async def test_submit_requires_at_least_one_url(app: FastAPI, client: httpx.AsyncClient) -> None:
    _as(app, "owner")
    app.dependency_overrides[get_indexing_store] = lambda: FakeStore()
    assert (await client.post(_SUBMIT, json={"urls": []})).status_code == 422


# --------------------------------------------------------------------------- #
# List ledger.
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("role", [*_PUBLISHERS, *_READ_ONLY])
async def test_every_staff_role_may_read_the_ledger(
    app: FastAPI, client: httpx.AsyncClient, role: str
) -> None:
    _as(app, role)
    row = {
        "id": "11111111-1111-1111-1111-111111111111", "client_id": "cl-1",
        "url": "https://acme.example/a", "engine": "indexnow", "status": "ok",
        "detail": "202 accepted", "created_at": None,
    }
    app.dependency_overrides[get_indexing_repo] = lambda: FakeRepo([row])
    resp = await client.get(_LIST)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body[0]["engine"] == "indexnow" and body[0]["clientId"] == "cl-1"
