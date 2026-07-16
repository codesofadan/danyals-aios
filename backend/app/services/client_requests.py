"""Client-portal request service: raise a support request scoped to the caller's
OWN client.

Mirrors :func:`app.services.client_audits.create_client_audit`:

* **Tenant is server-pinned.** ``client_id`` comes from the authenticated
  :class:`CurrentClient` (derived from the trusted ``users`` row), NEVER from the
  request body (:class:`PortalRequestCreate` has no ``client_id`` field).
* **Insert on the privileged path.** Clients have no base-table write policy, so the
  insert into ``support_tickets`` runs on ``privileged_connection`` (service_role,
  BYPASSRLS) and pins ``client_id`` + a ``client_name`` snapshot explicitly. The
  inserter is injected so the router wires the real psycopg write while tests pass a
  fake.

The row lands as a ``kind``-tagged, ``Portal``-channel, ``open`` ticket so it shares
the staff triage queue (0024/0033); the response is the frontend ``ClientRequest``
shape. A best-effort activity entry keeps the client's context fresh.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

from fastapi import HTTPException, status
from psycopg import sql

from app.core.auth import CurrentClient
from app.db.database import privileged_connection
from app.schemas.portal_requests import PortalRequestCreate
from app.services.activity import record_activity

# The seam the create flow inserts through: a row dict in, the persisted row out.
RequestInserter = Callable[[dict[str, Any]], dict[str, Any]]


def insert_request_row(row: dict[str, Any]) -> dict[str, Any]:
    """Insert one support-ticket (portal request) row via ``privileged_connection``
    and return it (blocking). Runs on the service_role path because clients have no
    base-table write policy. Column names are static ``sql.Identifier``s; every value
    is a bound parameter."""
    cols = list(row.keys())
    stmt = sql.SQL(
        "insert into public.support_tickets ({cols}) values ({vals}) returning *"
    ).format(
        cols=sql.SQL(", ").join(map(sql.Identifier, cols)),
        vals=sql.SQL(", ").join([sql.Placeholder()] * len(cols)),
    )
    with privileged_connection() as cur:
        cur.execute(stmt, list(row.values()))
        inserted = cur.fetchone()
    if inserted is None:  # pragma: no cover - ``returning *`` always yields the row
        raise RuntimeError("request row could not be read back after insert")
    return inserted


async def create_client_request(
    *,
    insert_request: RequestInserter,
    reader: Any,
    scoped: CurrentClient,
    body: PortalRequestCreate,
) -> dict[str, Any]:
    """Create a portal request for the caller's own client. Returns the persisted row.

    ``insert_request`` is the privileged inserter; ``reader`` is the RLS-scoped
    ``PortalRepo`` (used only to read the caller's own client row for the name
    snapshot). ``client_id`` is pinned from ``scoped`` - never from the body.
    """
    # The caller's OWN client row via the portal_client view (RLS-scoped) - for the
    # display-name snapshot so client_id never has to be surfaced downstream.
    client_row = await asyncio.to_thread(reader.get_client)
    if client_row is None:  # pragma: no cover - client_id is FK-guaranteed
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Client not found")

    row = await asyncio.to_thread(
        insert_request,
        {
            "client_id": scoped.client_id,  # pinned server-side; never from the body
            "client_name": client_row.get("name", ""),
            "subject": body.subject,
            "detail": body.detail,
            "kind": body.kind,
            "channel": "Portal",
            "priority": "med",
            "status": "open",
            "created_by": scoped.user.id,
        },
    )
    await record_activity(
        scoped.user, kind="client", action="raised a request", target=body.subject,
        entity_type="client", entity_id=scoped.client_id,
    )
    return row
