"""Integration: the RLS-identity connection layer is leak-proof (P6A-3 acceptance).

These are the leak proofs for the psycopg pooling/identity seam. They run against
the local Postgres named by DATABASE_URL (authenticated role) + DATABASE_ADMIN_URL
(service_role); they auto-skip when either is unset, mirroring the other
integration suites.

The RLS pool is built with ``max_size=1`` so every checkout is forced onto ONE
physical connection -- that is what makes a pool-reuse leak observable: if identity
or session state survived a checkout, the very next checkout on the same socket
would see it. It must not.

What is proven:
  * Pool reuse never leaks identity or rows across tenants A -> (bare) -> B.
  * The ``RESET ALL`` reset callback scrubs a deliberately-planted SESSION GUC.
  * A SQL-injection payload passed as a bound param cannot change the identity,
    and ``rls_connection`` rejects a non-UUID user_id outright.
  * service_role (privileged) sees rows regardless of identity, while an unknown
    authenticated identity sees zero on a staff-only table.
"""

from __future__ import annotations

import contextlib
import os
import uuid
from collections.abc import Iterator
from typing import Any

import pytest

from app.db.database import (
    InvalidUserIdError,
    build_admin_pool,
    build_rls_pool,
    privileged_connection,
    rls_connection,
)

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def db() -> Iterator[dict[str, Any]]:
    """Seed two tenants (A/B) each with a portal client user; yield handles.

    The RLS pool is pinned to a single physical connection (max_size=1) to force
    connection reuse. Everything is seeded/torn down through the privileged pool.
    """
    rls_dsn = os.environ.get("DATABASE_URL")
    admin_dsn = os.environ.get("DATABASE_ADMIN_URL")
    if not rls_dsn or not admin_dsn:
        pytest.skip("DATABASE_URL and DATABASE_ADMIN_URL required")

    rls_pool = build_rls_pool(rls_dsn, max_size=1)
    admin_pool = build_admin_pool(admin_dsn)
    assert rls_pool is not None and admin_pool is not None
    rls_pool.open()
    admin_pool.open()

    tag = uuid.uuid4().hex[:10]
    tenant: dict[str, str] = {}
    client_uid: dict[str, str] = {}
    auth_ids: list[str] = []
    client_ids: list[str] = []

    try:
        with privileged_connection(pool=admin_pool) as cur:
            for key in ("A", "B"):
                cur.execute(
                    "insert into public.clients (name, industry) values (%s, 'RLS-Identity') "
                    "returning id",
                    (f"DBIdentity {key} {tag}",),
                )
                tid = str(cur.fetchone()["id"])
                tenant[key] = tid
                client_ids.append(tid)

                uid = str(uuid.uuid4())
                email = f"dbid-{key.lower()}-{tag}@example.com"
                cur.execute(
                    "insert into auth.users (id, email, password_hash) values (%s, %s, 'x')",
                    (uid, email),
                )
                cur.execute(
                    "insert into public.users (id, email, name, role, client_id) "
                    "values (%s, %s, %s, 'client', %s)",
                    (uid, email, f"DBIdentity {key}", tid),
                )
                client_uid[key] = uid
                auth_ids.append(uid)

        yield {"rls_pool": rls_pool, "admin_pool": admin_pool, "tenant": tenant, "uid": client_uid}
    finally:
        with contextlib.suppress(Exception), privileged_connection(pool=admin_pool) as cur:
            for uid in auth_ids:  # cascades public.users (id FK on delete cascade)
                cur.execute("delete from auth.users where id = %s", (uid,))
            for cid in client_ids:
                cur.execute("delete from public.clients where id = %s", (cid,))
        rls_pool.close()
        admin_pool.close()


# --------------------------------------------------------------------------- #
def test_pooled_connection_never_leaks_identity_or_rows(db: dict[str, Any]) -> None:
    """A -> (bare reuse) -> B on ONE physical connection: no GUC/row bleed.

    Step 1 binds tenant A and confirms A's scoped visibility. Step 2 checks the
    SAME pooled connection out again WITHOUT setting identity and asserts it is
    identity-less (empty GUC, NULL auth.uid()) and sees zero rows -- no bleed from
    A. Step 3 binds tenant B and asserts B-only visibility (A never appears).
    """
    rls_pool = db["rls_pool"]
    tenant, uid = db["tenant"], db["uid"]

    # Step 1: identity A -> sees ONLY tenant A through the portal view.
    with rls_connection(uid["A"], pool=rls_pool) as cur:
        cur.execute("select auth.uid() as who")
        assert str(cur.fetchone()["who"]) == uid["A"]
        cur.execute("select id from public.portal_client")
        a_rows = [str(r["id"]) for r in cur.fetchall()]
    assert a_rows == [tenant["A"]], "identity A should see exactly its own tenant"

    # Step 2: reuse the SAME physical connection with NO identity set.
    with rls_pool.connection() as conn:
        assert not conn.execute("select current_setting('app.user_id', true) as v").fetchone()["v"], (
            "app.user_id leaked from the previous (identity A) checkout"
        )
        assert conn.execute("select auth.uid() as u").fetchone()["u"] is None, (
            "auth.uid() leaked from the previous (identity A) checkout"
        )
        assert conn.execute("select id from public.portal_client").fetchall() == [], (
            "tenant rows leaked to an identity-less checkout"
        )

    # Step 3: identity B -> sees ONLY tenant B; tenant A must NOT appear.
    with rls_connection(uid["B"], pool=rls_pool) as cur:
        cur.execute("select id from public.portal_client")
        b_rows = [str(r["id"]) for r in cur.fetchall()]
    assert b_rows == [tenant["B"]], "identity B should see exactly its own tenant"
    assert tenant["A"] not in b_rows, "tenant A leaked to identity B on connection reuse"


def test_reset_scrubs_stray_session_guc(db: dict[str, Any]) -> None:
    """A session-scoped (is_local=false) GUC is scrubbed by RESET ALL on return."""
    rls_pool = db["rls_pool"]
    victim = str(uuid.uuid4())

    # Plant a SESSION-level app.user_id (survives the txn) directly on the socket.
    with rls_pool.connection() as conn:
        conn.execute("select set_config('app.user_id', %s, false)", (victim,))
        conn.commit()
        assert str(conn.execute("select auth.uid() as u").fetchone()["u"]) == victim

    # Next checkout of the same physical connection must be identity-less.
    with rls_pool.connection() as conn:
        assert not conn.execute("select current_setting('app.user_id', true) as v").fetchone()["v"], (
            "RESET ALL did not scrub the planted session GUC"
        )
        assert conn.execute("select auth.uid() as u").fetchone()["u"] is None


def test_impersonation_via_bound_param_is_powerless(db: dict[str, Any]) -> None:
    """An injection payload passed as a bound param cannot change the identity."""
    rls_pool = db["rls_pool"]
    tenant, uid = db["tenant"], db["uid"]
    payload = f"'; select set_config('app.user_id','{uid['B']}',true); --"

    with rls_connection(uid["A"], pool=rls_pool) as cur:
        # The payload is DATA, not SQL: set_config never runs; identity stays A.
        cur.execute("select %s::text as note, auth.uid() as who", (payload,))
        row = cur.fetchone()
        assert row["note"] == payload
        assert str(row["who"]) == uid["A"], "identity was changed by an injection payload"
        # And visibility is still A-only (never B, the impersonation target).
        cur.execute("select id from public.portal_client")
        assert [str(r["id"]) for r in cur.fetchall()] == [tenant["A"]]


def test_rls_connection_rejects_non_uuid_identity(db: dict[str, Any]) -> None:
    """A non-UUID user_id is rejected app-side before any connection is touched."""
    rls_pool = db["rls_pool"]
    for bad in ("not-a-uuid", "", "'; drop table users; --", "123"):
        with pytest.raises(InvalidUserIdError):  # noqa: SIM117 - explicit per-input
            with rls_connection(bad, pool=rls_pool):
                pass


def test_service_role_bypass_vs_authenticated_bind(db: dict[str, Any]) -> None:
    """Privileged sees seeded rows regardless of identity; unknown identity sees 0."""
    rls_pool, admin_pool = db["rls_pool"], db["admin_pool"]
    tenant = db["tenant"]

    # service_role bypasses RLS -> both seeded tenants are visible.
    with privileged_connection(pool=admin_pool) as cur:
        cur.execute(
            "select count(*) as n from public.clients where id = any(%s)",
            ([tenant["A"], tenant["B"]],),
        )
        assert cur.fetchone()["n"] == 2

    # An unknown authenticated identity is not staff -> 0 rows on the base table.
    with rls_connection(str(uuid.uuid4()), pool=rls_pool) as cur:
        cur.execute("select count(*) as n from public.clients")
        assert cur.fetchone()["n"] == 0, "an unknown identity must see zero clients rows"
