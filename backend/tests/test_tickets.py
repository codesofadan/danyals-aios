"""Unit tests for the Support Tickets module: the response model (the exact 7
``Ticket`` keys + enum fidelity), the ``T-####`` code as the public id, and the
/tickets endpoints with faked repos - list (staff), create + status triage (leads),
and the RBAC/404 edges. No DB, no network.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI

from app.core.auth import CurrentUser, get_current_user
from app.db.clients_repo import get_clients_repo
from app.db.tickets_repo import get_tickets_repo
from app.schemas.tickets import TicketResponse, to_response

pytestmark = pytest.mark.unit

_TICKET_KEYS = {"id", "client", "subject", "channel", "priority", "status", "ago"}
_REPO_ROOT = Path(__file__).resolve().parents[2]


def _row(**over: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "id": "00000000-0000-0000-0000-000000000001",
        "code": "T-4821",
        "client_id": "cl-atlas",
        "client_name": "Atlas Legal",
        "subject": "Invoice past due - renewal on hold",
        "channel": "Email",
        "priority": "urgent",
        "status": "open",
        "opened_at": "2026-07-16T00:00:00+00:00",
        "created_by": "u-owner",
    }
    row.update(over)
    return row


# --- schema shape + enum fidelity --------------------------------------------

def test_response_emits_exactly_the_7_contract_keys() -> None:
    emitted = {
        f.serialization_alias or f.alias or name
        for name, f in TicketResponse.model_fields.items()
    }
    assert emitted == _TICKET_KEYS


def test_id_is_the_public_code_never_the_uuid() -> None:
    dumped = to_response(_row()).model_dump(by_alias=True)
    assert set(dumped) == _TICKET_KEYS
    assert dumped["id"] == "T-4821"  # the public badge, not the uuid
    assert "client_id" not in dumped and "created_by" not in dumped
    assert dumped["client"] == "Atlas Legal"


def test_response_missing_values_fall_back_safely() -> None:
    resp = to_response({"code": "T-1"})
    assert resp.id == "T-1"
    assert resp.client == ""
    assert resp.channel == "Portal"  # unknown/absent -> default
    assert resp.priority == "med"
    assert resp.status == "open"


def _inline_union(type_name: str, field: str) -> set[str]:
    """Harvest the double-quoted literals of an INLINE union field inside a TS type
    (e.g. Ticket's ``channel: "Email" | "Portal" | ...;``)."""
    src = (_REPO_ROOT / "frontend/lib/data.ts").read_text(encoding="utf-8")
    body = re.search(rf"export type {type_name}\s*=\s*\{{(.*?)\n\}};", src, re.DOTALL)
    assert body, f"type {type_name} not found"
    line = re.search(rf"\n\s*{field}\s*:([^\n;]*)", body.group(1))
    assert line, f"field {field} not found on {type_name}"
    return set(re.findall(r'"([^"]*)"', line.group(1)))


def _model_literals(field: str) -> set[str]:
    import typing

    ann = TicketResponse.model_fields[field].annotation
    return {a for a in typing.get_args(ann) if isinstance(a, str)}


@pytest.mark.parametrize("field", ["channel", "priority", "status"])
def test_enum_fields_match_inline_ticket_union(field: str) -> None:
    # §3 fidelity: Ticket's channel/priority/status are INLINE unions in data.ts.
    assert _model_literals(field) == _inline_union("Ticket", field)


# --- endpoints (faked repos) --------------------------------------------------

class FakeTicketsRepo:
    def __init__(self) -> None:
        self.rows: dict[str, dict[str, Any]] = {}
        self._seq = 4821

    def seed(self, **over: Any) -> dict[str, Any]:
        self._seq += 1
        code = over.get("code", f"T-{self._seq}")
        rec = _row(code=code)
        rec.update(over)
        self.rows[code] = rec
        return rec

    def list_tickets(
        self, *, status: str | None = None, limit: int | None = None, offset: int = 0
    ) -> list[dict[str, Any]]:
        rows = list(self.rows.values())
        if status is not None:
            rows = [r for r in rows if r.get("status") == status]
        return rows

    def get_ticket_by_code(self, code: str) -> dict[str, Any] | None:
        return self.rows.get(code)

    def insert_ticket(self, row: dict[str, Any]) -> dict[str, Any]:
        self._seq += 1
        code = f"T-{self._seq}"
        rec = {"id": f"uuid-{self._seq}", "code": code, **row}
        self.rows[code] = rec
        return rec

    def update_ticket_by_code(
        self, code: str, changes: dict[str, Any]
    ) -> dict[str, Any] | None:
        row = self.rows.get(code)
        if row is None:
            return None
        row.update(changes)
        return row


class FakeClientsRepo:
    def __init__(self, exists: bool = True) -> None:
        self._exists = exists

    def get_client(self, client_id: str) -> dict[str, Any] | None:
        return {"id": client_id, "name": "Atlas Legal"} if self._exists else None


def _user(role: str, uid: str = "u-1") -> CurrentUser:
    return CurrentUser(
        id=uid, email="op@x.com", role=role, status="active",  # type: ignore[arg-type]
        name="Op", title="", avatar_color="#000", phone="", two_fa=False,
    )


@pytest.fixture
def repo() -> FakeTicketsRepo:
    return FakeTicketsRepo()


@pytest.fixture
def wire(app: FastAPI, repo: FakeTicketsRepo) -> Callable[..., None]:
    app.dependency_overrides[get_tickets_repo] = lambda: repo
    app.dependency_overrides[get_clients_repo] = lambda: FakeClientsRepo()

    def _as(role: str, uid: str = "u-1", client_exists: bool = True) -> None:
        app.dependency_overrides[get_current_user] = lambda: _user(role, uid)
        app.dependency_overrides[get_clients_repo] = lambda: FakeClientsRepo(client_exists)

    return _as


# reads

async def test_client_forbidden_from_reads(
    client: httpx.AsyncClient, wire: Callable[..., None]
) -> None:
    wire("client")  # a portal client lacks view_reports
    assert (await client.get("/api/v1/tickets")).status_code == 403


async def test_list_shape_and_status_filter(
    client: httpx.AsyncClient, repo: FakeTicketsRepo, wire: Callable[..., None]
) -> None:
    repo.seed(status="open")
    repo.seed(status="resolved")
    wire("viewer")
    body = (await client.get("/api/v1/tickets")).json()
    assert len(body) == 2
    assert set(body[0]) == _TICKET_KEYS
    only_open = (await client.get("/api/v1/tickets", params={"status": "open"})).json()
    assert len(only_open) == 1
    assert only_open[0]["status"] == "open"


# create

async def test_create_requires_manage_clients(
    client: httpx.AsyncClient, wire: Callable[..., None]
) -> None:
    wire("specialist", "u-spec")  # specialists lack manage_clients
    resp = await client.post(
        "/api/v1/tickets", json={"subject": "Help", "client_id": "cl-atlas"}
    )
    assert resp.status_code == 403


async def test_create_happy_path(
    client: httpx.AsyncClient, wire: Callable[..., None]
) -> None:
    wire("manager", "u-mgr")
    resp = await client.post(
        "/api/v1/tickets",
        json={"subject": "Reset portal password", "client_id": "cl-atlas",
              "channel": "Chat", "priority": "high"},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert set(body) == _TICKET_KEYS
    assert body["subject"] == "Reset portal password"
    assert body["client"] == "Atlas Legal"  # snapshotted from the clients repo
    assert body["channel"] == "Chat"
    assert body["status"] == "open"  # always starts open
    assert body["id"].startswith("T-")


async def test_create_unknown_client_404(
    client: httpx.AsyncClient, wire: Callable[..., None]
) -> None:
    wire("admin", "u-admin", client_exists=False)
    resp = await client.post(
        "/api/v1/tickets", json={"subject": "X", "client_id": "ghost"}
    )
    assert resp.status_code == 404


async def test_create_rejects_blank_subject(
    client: httpx.AsyncClient, wire: Callable[..., None]
) -> None:
    wire("owner", "u-owner")
    resp = await client.post("/api/v1/tickets", json={"subject": "", "client_id": "cl-atlas"})
    assert resp.status_code == 422


# status triage

async def test_status_triage_updates(
    client: httpx.AsyncClient, repo: FakeTicketsRepo, wire: Callable[..., None]
) -> None:
    seeded = repo.seed(status="open")
    wire("admin", "u-admin")
    resp = await client.patch(
        f"/api/v1/tickets/{seeded['code']}/status", json={"status": "resolved"}
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "resolved"


async def test_status_unknown_code_404(
    client: httpx.AsyncClient, wire: Callable[..., None]
) -> None:
    wire("admin", "u-admin")
    resp = await client.patch("/api/v1/tickets/T-9999/status", json={"status": "pending"})
    assert resp.status_code == 404


async def test_status_forbidden_for_specialist(
    client: httpx.AsyncClient, repo: FakeTicketsRepo, wire: Callable[..., None]
) -> None:
    seeded = repo.seed()
    wire("specialist", "u-spec")
    resp = await client.patch(
        f"/api/v1/tickets/{seeded['code']}/status", json={"status": "pending"}
    )
    assert resp.status_code == 403


async def test_status_rejects_unknown_value(
    client: httpx.AsyncClient, repo: FakeTicketsRepo, wire: Callable[..., None]
) -> None:
    seeded = repo.seed()
    wire("owner", "u-owner")
    resp = await client.patch(
        f"/api/v1/tickets/{seeded['code']}/status", json={"status": "closed"}
    )
    assert resp.status_code == 422  # not one of open/pending/resolved


# --- all-way comms: a status change emails the client (ADMIN/LEAD -> CLIENT) -------

async def test_status_change_emails_the_client(
    client: httpx.AsyncClient, repo: FakeTicketsRepo, wire: Callable[..., None],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, str]] = []

    async def _fake_email_client(
        client_id: str, subject: str, html: str, text: str = "", **_k: Any
    ) -> None:
        calls.append((client_id, subject))

    monkeypatch.setattr("app.routers.tickets.email_client", _fake_email_client)
    seeded = repo.seed(status="open", client_id="cl-atlas")
    wire("admin", "u-admin")
    resp = await client.patch(
        f"/api/v1/tickets/{seeded['code']}/status", json={"status": "resolved"}
    )
    assert resp.status_code == 200
    assert calls and calls[0][0] == "cl-atlas"  # the request's client is emailed
    assert seeded["subject"] in calls[0][1]  # the subject carries the request title


async def test_status_unchanged_does_not_email(
    client: httpx.AsyncClient, repo: FakeTicketsRepo, wire: Callable[..., None],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, str]] = []

    async def _fake_email_client(
        client_id: str, subject: str, html: str, text: str = "", **_k: Any
    ) -> None:
        calls.append((client_id, subject))

    monkeypatch.setattr("app.routers.tickets.email_client", _fake_email_client)
    seeded = repo.seed(status="resolved", client_id="cl-atlas")
    wire("admin", "u-admin")
    resp = await client.patch(
        f"/api/v1/tickets/{seeded['code']}/status", json={"status": "resolved"}
    )
    assert resp.status_code == 200
    assert calls == []  # no real transition -> no client email


async def test_status_change_survives_email_layer_unconfigured(
    client: httpx.AsyncClient, repo: FakeTicketsRepo, wire: Callable[..., None]
) -> None:
    # No monkeypatch: the real email_client runs with no DB / no Resend key and must
    # degrade to a no-op - the triage still returns 200.
    seeded = repo.seed(status="open", client_id="cl-atlas")
    wire("admin", "u-admin")
    resp = await client.patch(
        f"/api/v1/tickets/{seeded['code']}/status", json={"status": "pending"}
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "pending"


# --- all-way comms: a free-text reply (ADMIN/LEAD -> CLIENT) -----------------------

async def test_reply_requires_manage_clients(
    client: httpx.AsyncClient, repo: FakeTicketsRepo, wire: Callable[..., None]
) -> None:
    seeded = repo.seed()
    wire("specialist", "u-spec")  # specialists lack manage_clients
    resp = await client.post(
        f"/api/v1/tickets/{seeded['code']}/reply", json={"message": "On it."}
    )
    assert resp.status_code == 403


async def test_reply_unknown_code_404(
    client: httpx.AsyncClient, wire: Callable[..., None]
) -> None:
    wire("admin", "u-admin")
    resp = await client.post(
        "/api/v1/tickets/T-9999/reply", json={"message": "hi"}
    )
    assert resp.status_code == 404


async def test_reply_rejects_blank_message(
    client: httpx.AsyncClient, repo: FakeTicketsRepo, wire: Callable[..., None]
) -> None:
    seeded = repo.seed()
    wire("admin", "u-admin")
    resp = await client.post(
        f"/api/v1/tickets/{seeded['code']}/reply", json={"message": ""}
    )
    assert resp.status_code == 422


async def test_reply_writes_the_reply_column_and_emails_the_client(
    client: httpx.AsyncClient, repo: FakeTicketsRepo, wire: Callable[..., None],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, str, str]] = []

    async def _fake_email_client(
        client_id: str, subject: str, html: str, text: str = "", **_k: Any
    ) -> None:
        calls.append((client_id, subject, text))

    monkeypatch.setattr("app.routers.tickets.email_client", _fake_email_client)
    seeded = repo.seed(client_id="cl-atlas")
    wire("admin", "u-admin")
    resp = await client.post(
        f"/api/v1/tickets/{seeded['code']}/reply",
        json={"message": "We reset your portal password - check your inbox."},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert set(body) == _TICKET_KEYS  # the reply text itself never leaks onto the wire

    # the dead `reply` column (0033) is finally written, plus who/when
    row = repo.rows[seeded["code"]]
    assert row["reply"] == "We reset your portal password - check your inbox."
    assert row["replied_by"] == "u-admin"
    assert row["replied_at"]

    # the client gets the REAL reply text, not a canned status label
    assert calls and calls[0][0] == "cl-atlas"
    assert "We reset your portal password" in calls[0][2]


async def test_reply_to_a_non_client_ticket_does_not_email(
    client: httpx.AsyncClient, repo: FakeTicketsRepo, wire: Callable[..., None],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, str]] = []

    async def _fake_email_client(
        client_id: str, subject: str, html: str, text: str = "", **_k: Any
    ) -> None:
        calls.append((client_id, subject))

    monkeypatch.setattr("app.routers.tickets.email_client", _fake_email_client)
    seeded = repo.seed(client_id=None)
    wire("admin", "u-admin")
    resp = await client.post(
        f"/api/v1/tickets/{seeded['code']}/reply", json={"message": "internal note only"}
    )
    assert resp.status_code == 200
    assert calls == []


async def test_reply_survives_email_layer_unconfigured(
    client: httpx.AsyncClient, repo: FakeTicketsRepo, wire: Callable[..., None]
) -> None:
    # No monkeypatch: the real email_client runs with no DB / no Resend key and must
    # degrade to a no-op - the reply still returns 200 and persists.
    seeded = repo.seed(client_id="cl-atlas")
    wire("admin", "u-admin")
    resp = await client.post(
        f"/api/v1/tickets/{seeded['code']}/reply", json={"message": "hello"}
    )
    assert resp.status_code == 200
    assert repo.rows[seeded["code"]]["reply"] == "hello"
