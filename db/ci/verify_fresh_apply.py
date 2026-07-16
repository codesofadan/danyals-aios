#!/usr/bin/env python
"""Fresh-DB migration apply verification (psql-free, pure psycopg).

Provisions a throwaway *scratch* database, applies ``db/migrations/*.sql`` in
strict filename order as the migration superuser (``DATABASE_MIGRATE_URL``),
then runs the FORCE row-level-security coverage gate (``app.db.rls_check``)
against the freshly built schema.

Why this exists: migrations are frequently authored in isolated worktrees and
merged in parallel, so an ordering or idempotency defect (a later migration that
silently depends on an object a *different* branch created, a non-idempotent
``create`` that only survives because it never re-runs, a gap in the NNNN
sequence) will not surface until someone rebuilds the schema from zero. This
script rebuilds from zero on every run and fails loudly on the first bad
migration, naming the file.

It complements the CI ``db-rls`` job (which applies the same set with ``psql``):
this is the local/portable equivalent that also owns its scratch database, so it
never touches the real one and needs no ``psql`` on PATH.

Usage (from the repo root or ``backend/``)::

    python db/ci/verify_fresh_apply.py            # reads DATABASE_MIGRATE_URL
    python db/ci/verify_fresh_apply.py --keep     # keep the scratch DB on success

The migration DSN is read from ``DATABASE_MIGRATE_URL`` (falling back to
``DATABASE_ADMIN_URL``), from the environment or from ``backend/.env``. Exit 0
on success (scratch DB dropped), non-zero on the first failing migration or on
any table missing FORCE RLS (scratch DB kept for inspection).
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import psycopg
from psycopg import conninfo, sql

_REPO_ROOT = Path(__file__).resolve().parents[2]
_MIGRATIONS_DIR = _REPO_ROOT / "db" / "migrations"
_BACKEND_DIR = _REPO_ROOT / "backend"
_SCRATCH_DB = "aios_fresh_verify"
# 'postgres' always exists on a stock cluster and is never the DB we recreate.
_MAINTENANCE_DB = "postgres"


def _migrate_dsn() -> str:
    """Resolve the superuser migration DSN from env, else ``backend/.env``."""
    for key in ("DATABASE_MIGRATE_URL", "DATABASE_ADMIN_URL"):
        if os.environ.get(key):
            return os.environ[key]
    env_file = _BACKEND_DIR / ".env"
    if env_file.exists():
        for raw in env_file.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            for key in ("DATABASE_MIGRATE_URL", "DATABASE_ADMIN_URL"):
                if line.startswith(f"{key}="):
                    return line.split("=", 1)[1].strip().strip('"').strip("'")
    raise SystemExit(
        "DATABASE_MIGRATE_URL is not set (checked the environment and backend/.env)."
    )


def _with_dbname(dsn: str, dbname: str) -> str:
    """Return ``dsn`` with its database name replaced by ``dbname``."""
    params = conninfo.conninfo_to_dict(dsn)
    params["dbname"] = dbname
    return conninfo.make_conninfo(**params)


def _recreate_scratch(maintenance_dsn: str) -> None:
    """Drop (force-disconnecting) and recreate the scratch database."""
    ident = sql.Identifier(_SCRATCH_DB)
    with psycopg.connect(maintenance_dsn, autocommit=True) as conn, conn.cursor() as cur:
        cur.execute(sql.SQL("drop database if exists {} with (force)").format(ident))
        cur.execute(sql.SQL("create database {}").format(ident))


def _drop_scratch(maintenance_dsn: str) -> None:
    ident = sql.Identifier(_SCRATCH_DB)
    with psycopg.connect(maintenance_dsn, autocommit=True) as conn, conn.cursor() as cur:
        cur.execute(sql.SQL("drop database if exists {} with (force)").format(ident))


def _apply_migrations(scratch_dsn: str) -> int:
    """Apply every migration in filename order, one transaction per file.

    Returns the count applied. Raises ``SystemExit`` naming the first file that
    fails (mirrors ``psql -v ON_ERROR_STOP=1``). The PostgreSQL server parses
    each file's multiple statements and dollar-quoted bodies, so no client-side
    statement splitting is needed.
    """
    files = sorted(_MIGRATIONS_DIR.glob("*.sql"))
    if not files:
        raise SystemExit(f"no migrations found in {_MIGRATIONS_DIR}")
    with psycopg.connect(scratch_dsn) as conn:
        for path in files:
            body = path.read_text(encoding="utf-8")
            try:
                with conn.cursor() as cur:
                    cur.execute(body)
                conn.commit()
            except Exception as exc:  # noqa: BLE001 - re-raised as a labelled SystemExit
                conn.rollback()
                raise SystemExit(
                    f"MIGRATION FAILED (applied out of order or non-idempotent): "
                    f"{path.name}\n  {type(exc).__name__}: {exc}"
                ) from exc
            print(f"  applied {path.name}")
    return len(files)


def _rls_gate(scratch_dsn: str) -> int:
    """Run the real FORCE-RLS coverage gate against the scratch schema.

    Reuses ``app.db.rls_check`` (the same catalog query + ``find_unprotected``
    predicate the CI ``db-rls`` job runs) so this verification and the gate can
    never drift. Returns the number of base tables checked.
    """
    sys.path.insert(0, str(_BACKEND_DIR))
    from app.db.rls_check import _CATALOG_SQL, TableRow, find_unprotected

    with psycopg.connect(scratch_dsn) as conn, conn.cursor() as cur:
        cur.execute(_CATALOG_SQL)
        rows: list[TableRow] = [(str(r[0]), bool(r[1]), bool(r[2])) for r in cur.fetchall()]
    if not rows:
        raise SystemExit("RLS gate: no public base tables found after applying migrations.")
    offenders = find_unprotected(rows)
    if offenders:
        joined = "\n".join(f"  - public.{name}" for name in offenders)
        raise SystemExit(f"RLS gate FAILED - tables without FORCE row-level security:\n{joined}")
    return len(rows)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--keep", action="store_true", help="keep the scratch DB on success (default: drop)"
    )
    args = parser.parse_args(argv)

    dsn = _migrate_dsn()
    maintenance_dsn = _with_dbname(dsn, _MAINTENANCE_DB)
    scratch_dsn = _with_dbname(dsn, _SCRATCH_DB)

    print(f"fresh-apply: rebuilding scratch database '{_SCRATCH_DB}' from zero")
    _recreate_scratch(maintenance_dsn)
    kept = False
    try:
        applied = _apply_migrations(scratch_dsn)
        tables = _rls_gate(scratch_dsn)
    except BaseException:
        # Keep the scratch DB so a failing migration can be inspected.
        kept = True
        print(f"scratch DB '{_SCRATCH_DB}' KEPT for inspection.", file=sys.stderr)
        raise
    finally:
        if not kept and not args.keep:
            _drop_scratch(maintenance_dsn)

    print(
        f"OK: {applied} migration(s) applied in order; "
        f"RLS gate passed - {tables} table(s), all FORCE row-level security."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
