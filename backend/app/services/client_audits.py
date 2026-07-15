"""Client-portal audit service: run an audit scoped to the caller's OWN client.

The trust rules that make this safe:

* **Tenant is server-pinned.** ``client_id`` comes from the authenticated
  :class:`CurrentClient` (itself derived from the trusted ``users`` row), NEVER
  from the request body (:class:`PortalAuditCreate` has no ``client_id`` field).
* **Paid gating (D5).** A client may run a Paid audit only when its
  ``delivery_tier`` is not ``free``; a ``free`` client is Free-only. The delivery
  tier is read from the client's OWN row through the RLS ``portal_client`` view.
* **Insert on the privileged path (D6).** Clients have no base-table SELECT
  policy, so a user-JWT insert could not read its row back; the insert runs on
  ``privileged_connection`` (service_role, BYPASSRLS) -- mirroring the worker --
  and pins ``client_id`` explicitly. The privileged inserter is injected so the
  router can wire the real psycopg write while unit tests pass a fake.

All DB / DNS calls are blocking and offloaded with ``asyncio.to_thread`` so the
event loop is never blocked. Gating failures raise ``HTTPException`` for the
router to surface unchanged.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

from fastapi import HTTPException, status
from psycopg import sql

from app.core.auth import CurrentClient
from app.core.security import PrivateAddressError, validate_public_host
from app.db.database import privileged_connection
from app.schemas.audits import PortalAuditCreate, tier_to_db
from app.services.activity import record_activity

# The seam the create flow inserts through: a row dict in, the persisted row out.
AuditInserter = Callable[[dict[str, Any]], dict[str, Any]]


def insert_audit_row(row: dict[str, Any]) -> dict[str, Any]:
    """Insert one audit row via ``privileged_connection`` and return it (blocking).

    Runs on the service_role (BYPASSRLS) path because clients have no base-table
    SELECT policy. Column names come from the row's keys as static
    ``sql.Identifier``s; every value is a bound parameter.
    """
    cols = list(row.keys())
    stmt = sql.SQL("insert into public.audits ({cols}) values ({vals}) returning *").format(
        cols=sql.SQL(", ").join(map(sql.Identifier, cols)),
        vals=sql.SQL(", ").join([sql.Placeholder()] * len(cols)),
    )
    with privileged_connection() as cur:
        cur.execute(stmt, list(row.values()))
        inserted = cur.fetchone()
    if inserted is None:  # pragma: no cover - ``returning *`` always yields the row
        raise RuntimeError("audit row could not be read back after insert")
    return inserted


async def create_client_audit(
    *,
    insert_audit: AuditInserter,
    reader: Any,
    scoped: CurrentClient,
    body: PortalAuditCreate,
    enqueue: Callable[[str], None],
) -> dict[str, Any]:
    """Create + enqueue an audit for the caller's own client. Returns the row.

    ``insert_audit`` is the privileged (service_role) inserter; ``reader`` is the
    RLS-scoped ``PortalRepo`` (used only to read the caller's own client row for
    the name snapshot + delivery-tier gate).
    """
    # Free tier makes zero paid-provider spend: reject paid audit types up front
    # (same base rule as the staff endpoint).
    if body.tier == "Free" and body.paid_types():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Paid audit types require the Paid tier: {', '.join(body.paid_types())}",
        )

    # The caller's OWN client row via the portal_client view (RLS-scoped).
    client_row = await asyncio.to_thread(reader.get_client)
    if client_row is None:  # pragma: no cover - client_id is FK-guaranteed
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Client not found")

    # Paid gating (D5): a free delivery tier unlocks only Free audits.
    if body.tier == "Paid" and client_row.get("delivery_tier") == "free":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Paid audits require a paid delivery tier",
        )

    # SSRF guard: getaddrinfo blocks, so validate off the event loop.
    try:
        await asyncio.to_thread(validate_public_host, body.url)
    except PrivateAddressError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"URL is not a public address: {exc}",
        ) from exc

    row = await asyncio.to_thread(
        insert_audit,
        {
            "client_id": scoped.client_id,  # pinned server-side; never from the body
            "client_name": client_row.get("name", ""),
            "url": body.url,
            "types": body.types,
            "tier": tier_to_db(body.tier),
            "status": "queued",
        },
    )
    enqueue(str(row["id"]))
    await record_activity(
        scoped.user, kind="audit", action="ran an audit", target=body.url,
        entity_type="client", entity_id=scoped.client_id,
    )
    return row
