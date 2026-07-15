"""P4-4 gate: the client-portal audit create service.

A fake inserter stands in for the privileged (service_role) audit insert, with
fakes for the portal_client read and the enqueuer. Proves: client_id is
server-pinned (a body field is ignored), the free delivery tier blocks paid
audits, paid types need the Paid tier, and the SSRF guard rejects private URLs
before any insert/enqueue.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi import HTTPException

from app.core.auth import CurrentClient, CurrentUser
from app.schemas.audits import PortalAuditCreate
from app.services.client_audits import create_client_audit

pytestmark = pytest.mark.unit

# A public IP literal: passes the SSRF guard with NO DNS lookup (offline-safe).
_PUBLIC_URL = "http://93.184.216.34"


class _FakeInserter:
    """Stand-in for the privileged ``insert_audit_row``: records the row and
    returns the persisted representation the DB would echo back."""

    def __init__(self) -> None:
        self.inserted: list[dict[str, Any]] = []

    def __call__(self, row: dict[str, Any]) -> dict[str, Any]:
        self.inserted.append(row)
        return {"id": "aud-1", "created_at": "2026-07-14T00:00:00Z", "scores": {}, **row}


class _FakeReader:
    def __init__(self, delivery_tier: str = "fully", name: str = "Acme") -> None:
        self._row: dict[str, Any] | None = {"name": name, "delivery_tier": delivery_tier}

    def get_client(self) -> dict[str, Any] | None:
        return self._row


def _scoped(client_id: str = "cl-A") -> CurrentClient:
    user = CurrentUser(
        id="u-1", email="p@acme.com", role="client", status="active",
        name="Acme Portal", title="", avatar_color="#000", phone="", two_fa=False,
        client_id=client_id,
    )
    return CurrentClient(user=user, client_id=client_id)


async def test_create_pins_client_id_ignoring_body_spoof() -> None:
    inserter = _FakeInserter()
    enqueued: list[str] = []
    # A hostile body carrying client_id: PortalAuditCreate has no such field, so
    # it is dropped; the insert must use the scoped tenant, not "cl-EVIL".
    body = PortalAuditCreate.model_validate(
        {"url": _PUBLIC_URL, "tier": "Free", "types": ["technical"], "client_id": "cl-EVIL"}
    )
    row = await create_client_audit(
        insert_audit=inserter, reader=_FakeReader(), scoped=_scoped("cl-A"),  # type: ignore[arg-type]
        body=body, enqueue=enqueued.append,
    )
    assert inserter.inserted[0]["client_id"] == "cl-A"
    assert inserter.inserted[0]["client_name"] == "Acme"
    assert inserter.inserted[0]["status"] == "queued"
    assert enqueued == [str(row["id"])]


async def test_free_delivery_tier_blocks_paid_audit() -> None:
    inserter = _FakeInserter()
    body = PortalAuditCreate(url=_PUBLIC_URL, tier="Paid", types=["technical"])
    with pytest.raises(HTTPException) as exc:
        await create_client_audit(
            insert_audit=inserter, reader=_FakeReader(delivery_tier="free"), scoped=_scoped(),  # type: ignore[arg-type]
            body=body, enqueue=[].append,
        )
    assert exc.value.status_code == 403
    assert inserter.inserted == []


async def test_free_tier_rejects_paid_types() -> None:
    inserter = _FakeInserter()
    body = PortalAuditCreate(url=_PUBLIC_URL, tier="Free", types=["technical", "local"])
    with pytest.raises(HTTPException) as exc:
        await create_client_audit(
            insert_audit=inserter, reader=_FakeReader(delivery_tier="fully"), scoped=_scoped(),  # type: ignore[arg-type]
            body=body, enqueue=[].append,
        )
    assert exc.value.status_code == 400
    assert inserter.inserted == []


async def test_paid_delivery_tier_allows_paid_audit() -> None:
    inserter = _FakeInserter()
    enqueued: list[str] = []
    body = PortalAuditCreate(url=_PUBLIC_URL, tier="Paid", types=["technical", "local"])
    await create_client_audit(
        insert_audit=inserter, reader=_FakeReader(delivery_tier="fully"), scoped=_scoped(),  # type: ignore[arg-type]
        body=body, enqueue=enqueued.append,
    )
    assert inserter.inserted[0]["tier"] == "paid"
    assert len(enqueued) == 1


async def test_ssrf_private_url_blocks_before_insert() -> None:
    inserter = _FakeInserter()
    enqueued: list[str] = []
    body = PortalAuditCreate(url="http://127.0.0.1/admin", tier="Free", types=["technical"])
    with pytest.raises(HTTPException) as exc:
        await create_client_audit(
            insert_audit=inserter, reader=_FakeReader(), scoped=_scoped(),  # type: ignore[arg-type]
            body=body, enqueue=enqueued.append,
        )
    assert exc.value.status_code == 400
    assert inserter.inserted == [] and enqueued == []
