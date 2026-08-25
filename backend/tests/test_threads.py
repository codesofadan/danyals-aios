"""Unit tests for discussion threads (0098) - the staff surface, with faked repos.

The DB-level guarantee (a client can never read an internal message) is proven in
``tests/integration/test_thread_visibility.py`` against real Postgres on the
``authenticated`` role. THIS file covers the layer above it: the response shapes, who
may post, the safe default, code-addressing, and the 404 that makes an entity the
caller cannot see indistinguishable from one that does not exist.

No DB, no network.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import httpx
import pytest
from fastapi import FastAPI

from app.core.auth import CurrentUser, get_current_user
from app.db.tasks_repo import get_tasks_repo
from app.db.threads_repo import get_threads_repo
from app.db.tickets_repo import get_tickets_repo
from app.schemas.threads import (
    MessageCreate,
    PortalMessageResponse,
    ThreadMessageResponse,
)

pytestmark = pytest.mark.unit

_STAFF_KEYS = {"id", "author", "authorKind", "body", "visibility", "createdAt", "ago"}
# The client shape deliberately omits `visibility` (and any author id).
_PORTAL_KEYS = {"id", "author", "authorKind", "body", "createdAt", "ago"}


def _msg(**over: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "id": "00000000-0000-0000-0000-0000000000aa",
        "thread_id": "00000000-0000-0000-0000-0000000000bb",
        "author_id": "u-1",
        "author_name": "Rae Lindqvist",
        "author_kind": "staff",
        "body": "Picked this up.",
        "visibility": "internal",
        "created_at": "2026-08-25T09:00:00+00:00",
    }
    row.update(over)
    return row


# --- shapes -------------------------------------------------------------------

def test_the_client_shape_cannot_carry_visibility() -> None:
    """Structural, not incidental.

    The portal response has no `visibility` field, so an internal note could not be
    described as one even if a query mistakenly returned it. That is a second,
    independent statement of the boundary the view already enforces.
    """
    emitted = {
        f.serialization_alias or f.alias or n
        for n, f in PortalMessageResponse.model_fields.items()
    }
    assert emitted == _PORTAL_KEYS
    assert "visibility" not in emitted
    assert "authorId" not in emitted and "author_id" not in emitted


def test_the_staff_shape_carries_visibility() -> None:
    emitted = {
        f.serialization_alias or f.alias or n
        for n, f in ThreadMessageResponse.model_fields.items()
    }
    assert emitted == _STAFF_KEYS


def test_neither_shape_leaks_an_internal_id() -> None:
    for model in (ThreadMessageResponse, PortalMessageResponse):
        dumped = model.from_row(_msg()).model_dump(by_alias=True)
        assert "thread_id" not in dumped and "threadId" not in dumped
        assert "author_id" not in dumped and "authorId" not in dumped


def test_visibility_defaults_to_internal() -> None:
    """The safe direction for a mistake is a note the client does NOT see."""
    assert MessageCreate(body="hello").visibility == "internal"


def test_a_blank_body_is_rejected() -> None:
    for blank in ("", "   ", "\n\t "):
        with pytest.raises(ValueError):
            MessageCreate(body=blank)


def test_body_is_trimmed() -> None:
    assert MessageCreate(body="  hi  ").body == "hi"


# --- endpoints ----------------------------------------------------------------

class FakeThreadsRepo:
    def __init__(self) -> None:
        self.threads: dict[tuple[str, str], dict[str, Any]] = {}
        self.messages: list[dict[str, Any]] = []

    def get_thread(self, entity_type: str, entity_id: str) -> dict[str, Any] | None:
        return self.threads.get((entity_type, entity_id))

    def create_thread(
        self, *, entity_type: str, entity_id: str, client_id: str | None
    ) -> dict[str, Any]:
        key = (entity_type, entity_id)
        if key not in self.threads:
            self.threads[key] = {
                "id": f"th-{len(self.threads) + 1}",
                "entity_type": entity_type,
                "entity_id": entity_id,
                "client_id": client_id,
            }
        return self.threads[key]

    def list_messages(
        self, thread_id: str, *, limit: int | None = None, offset: int = 0
    ) -> list[dict[str, Any]]:
        return [m for m in self.messages if m["thread_id"] == thread_id]

    def add_message(
        self, *, thread_id: str, author_id: str, author_name: str, body: str, visibility: str
    ) -> dict[str, Any]:
        row = _msg(
            id=f"m-{len(self.messages) + 1}",
            thread_id=thread_id,
            author_id=author_id,
            author_name=author_name,
            body=body,
            visibility=visibility,
        )
        self.messages.append(row)
        return row


class FakeEntityRepo:
    """Stands in for both the tasks and tickets repos.

    Returning None models BOTH "does not exist" and "RLS hid it from this caller" -
    which is the point: the API must answer them identically.
    """

    def __init__(self, code: str | None = "J-1042", client_id: str | None = "cl-1") -> None:
        self._code = code
        self._client_id = client_id

    def _row(self, code: str) -> dict[str, Any] | None:
        if self._code is None or code != self._code:
            return None
        return {"id": "ent-1", "code": code, "client_id": self._client_id}

    def get_task_by_code(self, code: str) -> dict[str, Any] | None:
        return self._row(code)

    def get_ticket_by_code(self, code: str) -> dict[str, Any] | None:
        return self._row(code)


def _user(role: str, uid: str = "u-1") -> CurrentUser:
    return CurrentUser(
        id=uid, email="op@x.com", role=role, status="active",  # type: ignore[arg-type]
        name="Op", title="", avatar_color="#000", phone="", two_fa=False,
    )


@pytest.fixture
def repo() -> FakeThreadsRepo:
    return FakeThreadsRepo()


@pytest.fixture
def wire(app: FastAPI, repo: FakeThreadsRepo) -> Callable[..., None]:
    def _as(role: str, *, code: str | None = "J-1042", client_id: str | None = "cl-1") -> None:
        entity = FakeEntityRepo(code, client_id)
        app.dependency_overrides[get_current_user] = lambda: _user(role)
        app.dependency_overrides[get_threads_repo] = lambda: repo
        app.dependency_overrides[get_tasks_repo] = lambda: entity
        app.dependency_overrides[get_tickets_repo] = lambda: entity

    return _as


async def test_a_portal_client_cannot_reach_the_staff_thread_at_all(
    client: httpx.AsyncClient, wire: Callable[..., None]
) -> None:
    wire("client")
    for method in ("get", "post"):
        resp = await getattr(client, method)(
            "/api/v1/threads/task/J-1042/messages",
            **({"json": {"body": "hi"}} if method == "post" else {}),
        )
        assert resp.status_code == 403, resp.text


async def test_no_thread_yet_is_an_empty_list_not_an_error(
    client: httpx.AsyncClient, wire: Callable[..., None]
) -> None:
    wire("specialist")
    resp = await client.get("/api/v1/threads/task/J-1042/messages")
    assert resp.status_code == 200
    assert resp.json() == []


async def test_any_staff_member_may_comment(
    client: httpx.AsyncClient, wire: Callable[..., None]
) -> None:
    """Commenting is not a privileged act.

    Restricting it to leads would reproduce the exact gap this table closes: a
    specialist doing the work, with no way to ask a question about it.
    """
    for role in ("owner", "admin", "manager", "specialist", "analyst", "viewer"):
        wire(role)
        resp = await client.post(
            "/api/v1/threads/task/J-1042/messages", json={"body": f"note from {role}"}
        )
        assert resp.status_code == 201, f"{role}: {resp.text}"
        assert resp.json()["visibility"] == "internal"  # the safe default


async def test_a_reply_can_be_addressed_to_the_client(
    client: httpx.AsyncClient, wire: Callable[..., None]
) -> None:
    wire("manager")
    resp = await client.post(
        "/api/v1/threads/ticket/J-1042/messages",
        json={"body": "We will report Friday.", "visibility": "client_visible"},
    )
    assert resp.status_code == 201
    assert resp.json()["visibility"] == "client_visible"


async def test_an_unreachable_entity_is_a_404_not_a_403(
    client: httpx.AsyncClient, wire: Callable[..., None]
) -> None:
    """A task the caller cannot see must look exactly like one that never existed.

    Distinguishing them would let a caller enumerate other people's work by watching
    which codes answer differently.
    """
    wire("specialist", code=None)
    assert (await client.get("/api/v1/threads/task/J-9999/messages")).status_code == 404
    resp = await client.post("/api/v1/threads/task/J-9999/messages", json={"body": "x"})
    assert resp.status_code == 404


async def test_an_unknown_entity_type_is_rejected_by_the_path(
    client: httpx.AsyncClient, wire: Callable[..., None]
) -> None:
    """The entity set is closed - each value implies a tenancy rule the views encode."""
    wire("admin")
    resp = await client.get("/api/v1/threads/invoice/J-1042/messages")
    assert resp.status_code == 422


async def test_the_conversation_reads_oldest_first(
    client: httpx.AsyncClient, wire: Callable[..., None], repo: FakeThreadsRepo
) -> None:
    wire("admin")
    for text in ("first", "second", "third"):
        await client.post("/api/v1/threads/task/J-1042/messages", json={"body": text})
    resp = await client.get("/api/v1/threads/task/J-1042/messages")
    assert [m["body"] for m in resp.json()] == ["first", "second", "third"]


async def test_a_thread_on_a_clientless_task_carries_no_tenant(
    client: httpx.AsyncClient, wire: Callable[..., None], repo: FakeThreadsRepo
) -> None:
    """An internal task belongs to no client, so its thread must not claim one."""
    wire("admin", client_id=None)
    await client.post("/api/v1/threads/task/J-1042/messages", json={"body": "internal work"})
    assert repo.threads[("task", "ent-1")]["client_id"] is None


# --- the notification legs ----------------------------------------------------
# Moving the conversation into threads must not quietly stop clients being told they
# have an answer. `POST /tickets/{code}/reply` emailed them; a client_visible thread
# message has to do the same, or the upgrade is a silent regression in the one place
# the client actually notices.

async def test_a_client_visible_reply_emails_the_client(
    client: httpx.AsyncClient, wire: Callable[..., None], monkeypatch: pytest.MonkeyPatch
) -> None:
    sent: list[tuple[str, str]] = []

    async def _fake_email(cid: str, subject: str, html: str, text: str = "", **_: Any) -> None:
        sent.append((cid, subject))

    monkeypatch.setattr("app.routers.threads.email_client", _fake_email)
    wire("manager", client_id="cl-77")

    resp = await client.post(
        "/api/v1/threads/ticket/J-1042/messages",
        json={"body": "Report attached.", "visibility": "client_visible"},
    )
    assert resp.status_code == 201
    assert len(sent) == 1, "a client-visible reply did not email the client"
    assert sent[0][0] == "cl-77"
    assert "J-1042" in sent[0][1]


async def test_an_internal_note_never_emails_the_client(
    client: httpx.AsyncClient, wire: Callable[..., None], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The whole point of `internal`: the client is not told, and is not sent it."""
    sent: list[str] = []

    async def _fake_email(cid: str, *a: Any, **k: Any) -> None:
        sent.append(cid)

    monkeypatch.setattr("app.routers.threads.email_client", _fake_email)
    wire("manager", client_id="cl-77")

    resp = await client.post(
        "/api/v1/threads/ticket/J-1042/messages",
        json={"body": "Do not start - unpaid.", "visibility": "internal"},
    )
    assert resp.status_code == 201
    assert sent == [], "an INTERNAL note was emailed to the client"


async def test_a_reply_on_a_clientless_entity_emails_nobody(
    client: httpx.AsyncClient, wire: Callable[..., None], monkeypatch: pytest.MonkeyPatch
) -> None:
    sent: list[str] = []

    async def _fake_email(cid: str, *a: Any, **k: Any) -> None:
        sent.append(cid)

    monkeypatch.setattr("app.routers.threads.email_client", _fake_email)
    wire("admin", client_id=None)

    resp = await client.post(
        "/api/v1/threads/task/J-1042/messages",
        json={"body": "internal work", "visibility": "client_visible"},
    )
    assert resp.status_code == 201
    assert sent == []
