"""psycopg3 connection seams that carry RLS identity into local PostgreSQL.

This module REPLACES the two Supabase client seams (``app/db/supabase.py``) while
preserving Row-Level Security as the real tenant boundary. Two pools, one per
trust level, mirror the old ``client_for_user`` / ``get_admin_client`` split:

* ``rls_connection(user_id)`` -- the RLS-bound path. Its pool connects AS the
  ``authenticated`` role (RLS APPLIES to it). Each checkout runs inside an
  explicit transaction that sets ``app.user_id`` to the verified server-side
  identity, so ``auth.uid()`` (defined in migration 0000 as a GUC reader) returns
  it and every policy/helper/trigger from 0002-0012 evaluates unchanged. The
  identity is set TRANSACTION-LOCAL, so it auto-clears on commit -> pool-safe.

* ``privileged_connection()`` -- the ``service_role`` path (BYPASSRLS). The
  ``get_admin_client`` equivalent: SERVER-ONLY, reads/writes every tenant. Never
  reachable from a browser; the DSN is never logged.

Security invariant (read before touching this file):
    ONLY trusted server code executes SQL on the authenticated pool. Identity is
    the verified JWT ``sub`` -- never a client-supplied string. ALL values are
    bound params, NEVER string-formatted, because any SQL run on this pool can
    call ``set_config('app.user_id', ...)`` and thereby impersonate a tenant. The
    txn-local identity form below CANNOT be reached by a bound parameter (a param
    is data, never executable SQL), which is what makes injection powerless here.

Pooling note (the cross-tenant-leak trap): a GUC set with ``is_local => false``
(session scope) would survive across pool checkouts and leak one tenant's
identity to the next request. Two defenses stack: (1) ``rls_connection`` only
ever sets ``is_local => true`` inside a txn that commits on exit; (2) the RLS
pool's ``reset`` callback runs ``RESET ALL`` on every return, scrubbing any stray
session GUC before the connection is reused.

Task-table writes MUST stay on the RLS pool in later chunks: the
``tasks_guard_*`` triggers read ``current_app_role()`` off ``auth.uid()``, which
is NULL on the privileged pool (service_role sets no ``app.user_id``), so those
writes would be rejected there. service_role bypasses POLICIES, not TRIGGERS.
"""

from __future__ import annotations

import asyncio
import os
import uuid
from collections.abc import Iterator
from contextlib import contextmanager

from psycopg import Connection, Cursor
from psycopg.abc import Params
from psycopg.rows import DictRow, dict_row
from psycopg.sql import SQL, Composed
from psycopg_pool import ConnectionPool

from app.schemas.health import DependencyStatus

# What ``Cursor.execute`` accepts as its statement. Deliberately excludes
# ``psycopg.abc.Query``'s t-string ``Template`` member (the cursor rejects it) and
# keeps SQL static: repos pass literal SQL, values always go through ``params``.
_Statement = str | bytes | SQL | Composed

_DEPENDENCY_NAME = "postgres"

# One pooled connection maps to one ``asyncio.to_thread`` worker (repos are sync +
# offloaded). Size the pool >= the default thread-pool worker count so a burst of
# concurrent RLS requests never starves on connections. Mirrors CPython's
# ThreadPoolExecutor default of ``min(32, cpu + 4)``.
_MAX_POOL_SIZE = min(32, (os.cpu_count() or 1) + 4)

# Module-level pool singletons, owned by the app lifespan (``set_pools`` on
# startup, ``clear_pools`` on shutdown). Repos reach the RLS/privileged path
# through the seams below WITHOUT threading ``app.state`` through every call.
_rls_pool: ConnectionPool[Connection[DictRow]] | None = None
_admin_pool: ConnectionPool[Connection[DictRow]] | None = None

_RlsPool = ConnectionPool[Connection[DictRow]]


class DatabaseNotConfiguredError(RuntimeError):
    """Raised when a DB pool is requested but its DSN is not configured."""


class InvalidUserIdError(ValueError):
    """Raised when ``rls_connection`` is given a non-UUID identity.

    Rejecting app-side avoids handing Postgres a malformed value (a noisy
    ``22P02 invalid_text_representation``) and, more importantly, guarantees the
    value bound into ``set_config`` is a real UUID -- never attacker-shaped text.
    """


# --------------------------------------------------------------------------- #
# Identity validation
# --------------------------------------------------------------------------- #
def _validate_user_id(user_id: str) -> str:
    """Return the canonical UUID string for ``user_id`` or raise cleanly.

    ``uuid.UUID`` accepts only well-formed UUIDs; anything else (empty string,
    injection payload, arbitrary text) raises ``InvalidUserIdError`` before a
    connection is ever touched.
    """
    try:
        return str(uuid.UUID(str(user_id)))
    except (ValueError, AttributeError, TypeError) as exc:
        raise InvalidUserIdError("user_id must be a well-formed UUID") from exc


# --------------------------------------------------------------------------- #
# Pool construction
# --------------------------------------------------------------------------- #
def _configure_rls_connection(conn: Connection[DictRow]) -> None:
    """Assert every RLS connection is non-autocommit (runs once per new socket).

    Txn-local identity relies on an explicit transaction: with autocommit ON,
    ``set_config(..., true)`` would apply to an implicit single-statement txn and
    the identity would be gone before the repo queries ran. Fail loudly rather
    than serve unscoped queries.
    """
    if conn.autocommit:
        raise RuntimeError(
            "rls_pool connection must have autocommit disabled "
            "(transaction-local identity depends on it)"
        )


def _reset_rls_connection(conn: Connection[DictRow]) -> None:
    """Scrub session state on return to the pool (defense-in-depth).

    ``RESET ALL`` clears every session GUC -- including any stray
    ``app.user_id`` that some code set with session scope -- so the next checkout
    starts identity-less. Committed because ``RESET`` is transactional under a
    non-autocommit connection; leaving the txn open would make the pool discard
    the connection.
    """
    conn.execute("RESET ALL")
    conn.commit()


def build_rls_pool(dsn: str | None, *, min_size: int = 1, max_size: int = _MAX_POOL_SIZE) -> _RlsPool | None:
    """Build the RLS pool (role ``authenticated``) or ``None`` when unconfigured.

    Constructed with ``open=False``; the caller (lifespan) opens it so startup
    never blocks on the database being reachable. A missing DSN is a clean
    "not configured", not a crash -- mirroring the old Supabase seam.
    """
    if not dsn:
        return None
    return ConnectionPool(
        dsn,
        connection_class=Connection[DictRow],
        kwargs={"autocommit": False, "row_factory": dict_row},
        min_size=min_size,
        max_size=max_size,
        configure=_configure_rls_connection,
        reset=_reset_rls_connection,
        open=False,
        name="rls_pool",
    )


def build_admin_pool(dsn: str | None, *, min_size: int = 1, max_size: int = _MAX_POOL_SIZE) -> _RlsPool | None:
    """Build the privileged pool (role ``service_role``, BYPASSRLS) or ``None``.

    SERVER-ONLY. Sets no identity GUC (service_role bypasses policies outright),
    so it needs no ``configure``/``reset`` identity scrubbing; the DSN is never
    logged. Constructed with ``open=False`` like the RLS pool.
    """
    if not dsn:
        return None
    return ConnectionPool(
        dsn,
        connection_class=Connection[DictRow],
        kwargs={"autocommit": False, "row_factory": dict_row},
        min_size=min_size,
        max_size=max_size,
        open=False,
        name="admin_pool",
    )


def set_pools(rls: _RlsPool | None, admin: _RlsPool | None) -> None:
    """Register the process-wide pools (called from the app lifespan on startup)."""
    global _rls_pool, _admin_pool
    _rls_pool = rls
    _admin_pool = admin


def clear_pools() -> None:
    """Forget the process-wide pools (called from the app lifespan on shutdown)."""
    global _rls_pool, _admin_pool
    _rls_pool = None
    _admin_pool = None


def get_rls_pool() -> _RlsPool:
    """Return the RLS pool or raise ``DatabaseNotConfiguredError`` when absent."""
    if _rls_pool is None:
        raise DatabaseNotConfiguredError("DATABASE_URL is required for the RLS pool")
    return _rls_pool


def get_admin_pool() -> _RlsPool:
    """Return the privileged pool or raise ``DatabaseNotConfiguredError``."""
    if _admin_pool is None:
        raise DatabaseNotConfiguredError("DATABASE_ADMIN_URL is required for the privileged pool")
    return _admin_pool


# --------------------------------------------------------------------------- #
# The two connection seams
# --------------------------------------------------------------------------- #
@contextmanager
def rls_connection(user_id: str, *, pool: _RlsPool | None = None) -> Iterator[Cursor[DictRow]]:
    """Yield an RLS-scoped cursor bound to ``user_id`` (the ONLY authenticated seam).

    Replaces ``client_for_user``: it carries the verified server-side identity,
    NOT a raw JWT. The connection is role ``authenticated`` (RLS applies); the
    identity is set with the PARAMETERIZED, transaction-local form so it cannot be
    forged by any bound value and auto-clears on commit (pool-safe).

        with rls_connection(user_id) as cur:
            cur.execute("select * from public.clients order by name")
            rows = cur.fetchall()   # dict_row -> list[dict]

    ``user_id`` is validated as a UUID app-side (raises ``InvalidUserIdError``).
    ``SET LOCAL app.user_id = %s`` is deliberately NOT used: ``SET LOCAL`` cannot
    bind a parameter, so ``set_config(..., true)`` is the only injection-safe way
    to set a transaction-local GUC from a bound value.
    """
    canonical = _validate_user_id(user_id)
    active_pool = pool if pool is not None else get_rls_pool()
    # autocommit off (asserted in configure); conn is bound before conn.transaction()
    # / conn.cursor() are evaluated (context managers enter left-to-right).
    with active_pool.connection() as conn, conn.transaction(), conn.cursor() as cur:
        # Transaction-local identity; auto-clears on commit. Bound param, never
        # string-formatted -> impersonation via a value is impossible.
        cur.execute("select set_config('app.user_id', %s, true)", (canonical,))
        yield cur


@contextmanager
def privileged_connection(*, pool: _RlsPool | None = None) -> Iterator[Cursor[DictRow]]:
    """Yield a privileged cursor (role ``service_role``, BYPASSRLS). SERVER-ONLY.

    Replaces ``get_admin_client``: it reads/writes every tenant's rows regardless
    of identity. NEVER expose it (or its DSN) to a browser; never log the DSN.
    Wrapped in an explicit transaction so multi-statement writes are atomic.

    Reminder for later chunks: writes that fire the ``tasks_guard_*`` triggers
    (which read ``current_app_role()`` off ``auth.uid()``) must use
    ``rls_connection`` instead -- ``auth.uid()`` is NULL here.
    """
    active_pool = pool if pool is not None else get_admin_pool()
    with active_pool.connection() as conn, conn.transaction(), conn.cursor() as cur:
        yield cur


# --------------------------------------------------------------------------- #
# Row helpers (so repo bodies read like the old PostgREST chains)
# --------------------------------------------------------------------------- #
def fetch_all(cur: Cursor[DictRow], query: _Statement, params: Params | None = None) -> list[DictRow]:
    """Run ``query`` and return all rows as ``list[dict]`` (empty -> ``[]``)."""
    cur.execute(query, params)
    return cur.fetchall()


def fetch_one(cur: Cursor[DictRow], query: _Statement, params: Params | None = None) -> DictRow | None:
    """Run ``query`` and return the first row as ``dict`` or ``None`` (``.limit(1)``)."""
    cur.execute(query, params)
    return cur.fetchone()


def execute(cur: Cursor[DictRow], query: _Statement, params: Params | None = None) -> None:
    """Run ``query`` for its side effect (no rows expected)."""
    cur.execute(query, params)


# --------------------------------------------------------------------------- #
# Readiness
# --------------------------------------------------------------------------- #
async def db_ping(pool: _RlsPool | None, timeout: float) -> DependencyStatus:
    """Bounded ``select 1`` readiness for a pool. Never raises; sanitized detail.

    A blank ``pool`` (unconfigured DSN) reports ``not_configured`` and, per the
    readiness policy, does NOT make the app not-ready. The sync checkout runs in a
    worker thread under an overall deadline; the DSN is never echoed.
    """
    if pool is None:
        return DependencyStatus(name=_DEPENDENCY_NAME, status="not_configured")

    def _probe() -> None:
        with pool.connection(timeout=timeout) as conn:
            conn.execute("select 1").fetchone()

    try:
        await asyncio.wait_for(asyncio.to_thread(_probe), timeout + 1.0)
    except TimeoutError:
        # asyncio.TimeoutError is an alias of the builtin TimeoutError on 3.11+.
        return DependencyStatus(name=_DEPENDENCY_NAME, status="timeout", detail="ping timed out")
    except Exception:
        # Sanitized: never echo the DSN, credentials, or raw exception text.
        return DependencyStatus(name=_DEPENDENCY_NAME, status="error", detail="connection failed")
    return DependencyStatus(name=_DEPENDENCY_NAME, status="ok")
