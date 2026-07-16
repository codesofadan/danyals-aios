"""Integration: ``resolve_budget_client`` maps a context entity to its budget
client against local Postgres (P6B-4).

Proves the entity->client resolution the cost gate needs for per-client budget
caps + the daily spend-stop:

  * ``client`` -> itself;
  * ``site``   -> its owning ``client_id``;
  * ``user``   -> a PORTAL client's ``client_id``, but ``None`` for a STAFF user
    (client_id is NULL for staff per migration 0010);
  * a missing entity / unknown type -> ``None`` (org-level).

Skips unless DATABASE_URL + DATABASE_ADMIN_URL are set; everything is cleaned up
in a finally block.
"""

from __future__ import annotations

import contextlib
from typing import Any
from uuid import uuid4

import pytest

from app.config import get_settings
from app.db.database import (
    build_admin_pool,
    build_rls_pool,
    clear_pools,
    privileged_connection,
    set_pools,
)
from app.services.context_cost import resolve_budget_client
from app.services.provisioning import provision_user

pytestmark = pytest.mark.integration

_PASSWORD = "Passw0rd!ctx-budget-123"


def _require_local_stack() -> Any:
    settings = get_settings()
    if not (settings.database_url and settings.database_admin_url):
        pytest.skip("local Postgres not configured (DATABASE_URL + DATABASE_ADMIN_URL)")
    return settings


async def test_resolve_budget_client_mappings() -> None:
    settings = _require_local_stack()

    rls_pool = build_rls_pool(settings.database_url)
    admin_pool = build_admin_pool(settings.database_admin_url)
    assert rls_pool is not None and admin_pool is not None
    rls_pool.open()
    admin_pool.open()
    set_pools(rls_pool, admin_pool)

    client_id: str | None = None
    site_id: str | None = None
    uids: list[str] = []
    try:
        with privileged_connection(pool=admin_pool) as cur:
            cur.execute("insert into public.clients (name) values ('Budget Co') returning id")
            client_id = str(cur.fetchone()["id"])
            cur.execute(
                "insert into public.sites (client_id, domain) values (%s, 'budget.example') returning id",
                (client_id,),
            )
            site_id = str(cur.fetchone()["id"])

        tag = uuid4().hex[:8]
        uid_client = str(provision_user(
            email=f"bud-c-{tag}@example.com", password=_PASSWORD, name="Budget Client",
            role="client", username=f"bud_c_{tag}", client_id=client_id,
        )["id"])
        uid_staff = str(provision_user(
            email=f"bud-s-{tag}@example.com", password=_PASSWORD, name="Budget Staff",
            role="owner", username=f"bud_s_{tag}", template_key="super",
        )["id"])
        uids += [uid_client, uid_staff]

        # client -> itself
        assert resolve_budget_client("client", client_id) == client_id
        # site -> its owning client
        assert resolve_budget_client("site", site_id) == client_id
        # portal user -> its client_id; staff user -> None (org-level)
        assert resolve_budget_client("user", uid_client) == client_id
        assert resolve_budget_client("user", uid_staff) is None
        # missing entity / unknown type -> None
        assert resolve_budget_client("site", str(uuid4())) is None
        assert resolve_budget_client("user", str(uuid4())) is None
        assert resolve_budget_client("other", client_id) is None
    finally:
        with contextlib.suppress(Exception), privileged_connection(pool=admin_pool) as cur:
            for uid in uids:
                cur.execute("delete from auth.users where id = %s", (uid,))
                cur.execute("delete from public.users where id = %s", (uid,))
            if site_id:
                cur.execute("delete from public.sites where id = %s", (site_id,))
            if client_id:
                cur.execute("delete from public.clients where id = %s", (client_id,))
        clear_pools()
        rls_pool.close()
        admin_pool.close()
