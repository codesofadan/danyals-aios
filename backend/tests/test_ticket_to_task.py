"""Turning a client's request into work — the loop that did not exist.

A client raised a request; it became a `support_tickets` row, an email to the operator
inbox and a truncated six-row widget on the Clients page. Nothing turned it into a task
anybody was assigned: there was no path at all from a request to the team's queue, so
the only thing joining them was an operator remembering.

The properties pinned here are the ones that make the conversion trustworthy rather
than merely present:

* the tenant comes from the TICKET, never the caller;
* an unlinked request cannot become client work;
* the new task is recorded on the request, so it is not converted twice;
* it is `assign_tasks`-gated, like every other way a task is created.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import httpx
import pytest
from fastapi import FastAPI

from app.core.auth import CurrentUser, get_current_user
from app.db.clients_repo import get_clients_repo
from app.db.tasks_repo import get_tasks_repo
from app.db.threads_repo import get_threads_repo
from app.db.tickets_repo import get_tickets_repo

pytestmark = pytest.mark.unit

_TICKET = {
    "id": "tk-1",
    "code": "T-4821",
    "client_id": "cl-atlas",
    "client_name": "Atlas Legal",
    "subject": "Please refresh the technical audit",
    "channel": "Portal",
    "priority": "high",
    "status": "open",
    "opened_at": "2026-08-01T00:00:00+00:00",
}


class FakeTickets:
    def __init__(self, ticket: dict[str, Any] | None = None) -> None:
        self.ticket = ticket
        self.linked: list[tuple[str, str]] = []

    def get_ticket_by_code(self, code: str) -> dict[str, Any] | None:
        if self.ticket and code == self.ticket["code"]:
            return dict(self.ticket)
        return None

    def link_task(self, ticket_id: str, task_id: str) -> dict[str, Any] | None:
        """Records which task the request became (0117) - the column that makes
        'has this been converted?' answerable without reading thread messages."""
        # Deliberately does NOT mutate `self.ticket`: the router does not re-read the
        # row after linking, and mutating shared fixture state here would make one
        # test's conversion look like an already-converted request to the next.
        self.linked.append((ticket_id, task_id))
        return dict(self.ticket) if self.ticket else None


class FakeTasks:
    def __init__(self) -> None:
        self.inserted: list[dict[str, Any]] = []

    def get_user(self, user_id: str) -> dict[str, Any] | None:
        if user_id == "u-client":
            return {"id": user_id, "role": "client"}
        if user_id == "u-ghost":
            return None
        return {"id": user_id, "role": "specialist"}

    def insert_task(self, row: dict[str, Any]) -> dict[str, Any]:
        self.inserted.append(row)
        return {
            **row,
            "id": "t-uuid",
            "code": "J-1055",
            "due_date": row.get("due_date"),
            "created_at": "2026-08-25T00:00:00+00:00",
            "updated_at": "2026-08-25T00:00:00+00:00",
            "started_at": None,
            "proof_url": None,
        }


class FakeClients:
    def get_client(self, client_id: str) -> dict[str, Any] | None:
        return {"id": client_id, "name": "Atlas Legal"} if client_id == "cl-atlas" else None


class FakeThreads:
    def __init__(self) -> None:
        self.messages: list[dict[str, Any]] = []

    def create_thread(self, *, entity_type: str, entity_id: str, client_id: str | None):
        return {"id": "th-1", "entity_type": entity_type, "entity_id": entity_id, "client_id": client_id}

    def add_message(self, **kw: Any) -> dict[str, Any]:
        self.messages.append(kw)
        return {**kw, "id": "m-1", "author_name": kw["author_name"], "created_at": "2026-08-25T00:00:00+00:00"}


def _user(role: str) -> CurrentUser:
    return CurrentUser(
        id="u-lead", email="lead@x.com", role=role, status="active",  # type: ignore[arg-type]
        name="Lead", title="", avatar_color="#000", phone="", two_fa=False,
    )


@pytest.fixture
def tasks() -> FakeTasks:
    return FakeTasks()


@pytest.fixture
def threads() -> FakeThreads:
    return FakeThreads()


@pytest.fixture
def tickets() -> FakeTickets:
    """The ticket repo double, exposed so a test can inspect what was LINKED - and
    seed an already-converted request. Its ticket is a per-test copy, so one test's
    conversion never leaks into the next."""
    return FakeTickets(dict(_TICKET))


@pytest.fixture
def wire(
    app: FastAPI, tasks: FakeTasks, threads: FakeThreads, tickets: FakeTickets
) -> Callable[..., None]:
    def _as(role: str, *, ticket: dict[str, Any] | None = _TICKET) -> None:
        app.dependency_overrides[get_current_user] = lambda: _user(role)
        if ticket is not _TICKET:
            tickets.ticket = ticket
        app.dependency_overrides[get_tickets_repo] = lambda: tickets
        app.dependency_overrides[get_tasks_repo] = lambda: tasks
        app.dependency_overrides[get_clients_repo] = lambda: FakeClients()
        app.dependency_overrides[get_threads_repo] = lambda: threads

    return _as


_URL = "/api/v1/tickets/T-4821/convert-to-task"


async def test_the_task_inherits_the_tickets_tenant_not_the_callers(
    client: httpx.AsyncClient, wire: Callable[..., None], tasks: FakeTasks
) -> None:
    """`client_id` is resolved from the ticket and is not a body field.

    Accepting it from the caller would let a client's request be converted into work
    billed against a different client.
    """
    wire("manager")
    resp = await client.post(_URL, json={"assignee_id": "u-spec"})
    assert resp.status_code == 201, resp.text
    assert tasks.inserted[0]["client_id"] == "cl-atlas"
    assert tasks.inserted[0]["client_name"] == "Atlas Legal"


async def test_the_title_defaults_to_the_request_itself(
    client: httpx.AsyncClient, wire: Callable[..., None], tasks: FakeTasks
) -> None:
    """The request already says what is needed; retyping it is how the two drift."""
    wire("manager")
    await client.post(_URL, json={"assignee_id": "u-spec"})
    assert tasks.inserted[0]["title"] == "Please refresh the technical audit"


async def test_an_explicit_title_wins(
    client: httpx.AsyncClient, wire: Callable[..., None], tasks: FakeTasks
) -> None:
    wire("manager")
    await client.post(_URL, json={"assignee_id": "u-spec", "title": "Q3 audit refresh"})
    assert tasks.inserted[0]["title"] == "Q3 audit refresh"


async def test_the_link_is_recorded_on_the_request_as_an_internal_note(
    client: httpx.AsyncClient, wire: Callable[..., None], threads: FakeThreads
) -> None:
    """So the next person to open the request does not convert it a second time.

    Internal, not client-visible: a job code is agency bookkeeping, and the client is
    told the work is happening by a reply somebody writes.
    """
    wire("manager")
    await client.post(_URL, json={"assignee_id": "u-spec"})
    assert len(threads.messages) == 1
    msg = threads.messages[0]
    assert msg["visibility"] == "internal"
    assert "J-1055" in msg["body"]


async def test_a_request_with_no_client_cannot_become_client_work(
    client: httpx.AsyncClient, wire: Callable[..., None]
) -> None:
    wire("manager", ticket={**_TICKET, "client_id": None})
    resp = await client.post(_URL, json={"assignee_id": "u-spec"})
    assert resp.status_code == 422
    assert "not linked to a client" in resp.text


async def test_an_unknown_request_is_a_404(
    client: httpx.AsyncClient, wire: Callable[..., None]
) -> None:
    wire("manager", ticket=None)
    assert (await client.post(_URL, json={"assignee_id": "u-spec"})).status_code == 404


async def test_conversion_is_assign_tasks_gated(
    client: httpx.AsyncClient, wire: Callable[..., None]
) -> None:
    """Same gate as every other way a task comes into existence."""
    for role in ("specialist", "analyst", "viewer", "client"):
        wire(role)
        resp = await client.post(_URL, json={"assignee_id": "u-spec"})
        assert resp.status_code == 403, f"{role} could convert a request into a task"
    for role in ("owner", "admin", "manager"):
        wire(role)
        assert (await client.post(_URL, json={"assignee_id": "u-spec"})).status_code == 201


@pytest.mark.parametrize(
    ("assignee", "expected"), [("u-client", 400), ("u-ghost", 404)]
)
async def test_the_assignee_must_be_staff(
    client: httpx.AsyncClient, wire: Callable[..., None], assignee: str, expected: int
) -> None:
    """The 404/400 split is preserved from the original `POST /tasks` path.

    "No such user" and "that user is a client" are different mistakes with different
    fixes, and both ways of creating a task now share one validator.
    """
    wire("manager")
    resp = await client.post(_URL, json={"assignee_id": assignee})
    assert resp.status_code == expected


# --------------------------------------------------------------------------- #
# The link is a COLUMN now, not prose in a thread message (0117).
#
# `assign_task` has always taken an `origin` argument and used it in the activity
# entry and the assignee's notification - and written it nowhere. There is no origin
# column on `tasks` and never was. So the only record that a request had become work
# was a sentence inside a thread, which nothing could query and which is easy to
# miss: the Convert button stayed live, and pressing it again produced a second task
# for work already assigned.
# --------------------------------------------------------------------------- #
async def test_conversion_records_which_task_the_request_became(
    client: httpx.AsyncClient, tickets: FakeTickets, tasks: FakeTasks, wire: Any
) -> None:
    wire("admin")
    resp = await client.post(
        "/api/v1/tickets/T-4821/convert-to-task", json={"assignee_id": "u-staff"}
    )
    assert resp.status_code == 201
    assert len(tickets.linked) == 1
    ticket_id, task_id = tickets.linked[0]
    assert ticket_id == tickets.ticket["id"]
    # The id the repo RETURNED for the new task, which is what the link stores.
    assert task_id == "t-uuid"


async def test_a_request_cannot_be_converted_twice(
    client: httpx.AsyncClient, tickets: FakeTickets, tasks: FakeTasks, wire: Any
) -> None:
    """Two tasks for one request means two people assigned the same work, and a
    client whose single request appears twice on the board."""
    tickets.ticket["task_id"] = "11111111-1111-1111-1111-111111111111"
    wire("admin")
    resp = await client.post(
        "/api/v1/tickets/T-4821/convert-to-task", json={"assignee_id": "u-staff"}
    )
    assert resp.status_code == 409
    assert "already been converted" in resp.json()["error"]["message"]
    assert tasks.inserted == []
