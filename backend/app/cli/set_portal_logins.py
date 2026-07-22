"""Provision or reset the standard portal logins (owner, admin, manager, client).

The app has no public signup and, until now, no admin password-reset path: the
only account CLI was ``provision_owner`` (owner only, and idempotent so it will
NOT change an existing owner's password). This tool fills that gap for the whole
standard set of portal roles, so a fresh or partially-seeded deployment can be
given one working login per portal in a single command.

For each target it RESETS the password in place if the username already exists
(a privileged ``UPDATE auth.users``), otherwise it CREATES the account via the
canonical ``provision_user`` path (argon2id hash + identity row + feature grants,
one atomic privileged transaction). The ``client`` login is scoped to a tenant
(``--client-id`` or the first client by name) and is skipped, not failed, when
the database has no clients yet. Every login is then re-verified against its
stored hash, so a printed ``login_ok=True`` row is a login that actually works.

It runs OUTSIDE the FastAPI lifespan, so it opens the privileged (service_role)
pool itself from ``DATABASE_ADMIN_URL`` and tears it down on exit — the same
pattern as ``provision_owner``.

    python -m app.cli.set_portal_logins                 # DRY RUN — prints the plan
    python -m app.cli.set_portal_logins --yes           # apply (owner1234, admin1234, ...)
    python -m app.cli.set_portal_logins --yes --only manager,client
    python -m app.cli.set_portal_logins --yes --password-suffix 'Pass!2026'

SECURITY: the default password for each login is ``<username> + suffix`` (suffix
defaults to ``1234``) — trivially guessable. On an internet-facing system the
admin/owner login can reveal the client key vault and every tenant's data. Use a
strong ``--password-suffix`` for anything public. The tool is a DRY RUN unless
``--yes`` is passed, and it never logs a password hash.
"""

from __future__ import annotations

import argparse
import sys
from typing import Any

from app.config import get_settings
from app.db.database import (
    build_admin_pool,
    clear_pools,
    privileged_connection,
    set_pools,
)
from app.rbac import UserRole
from app.services.passwords import hash_password, verify_password
from app.services.provisioning import provision_user

# (username, role, feature-grant template) — the standard portal set. owner/admin
# get the full 'super' grants; manager gets the 'va' template; client carries no
# staff grants and is tenant-scoped instead.
_PORTAL_LOGINS: list[tuple[str, UserRole, str | None]] = [
    ("owner", "owner", "super"),
    ("admin", "admin", "super"),
    ("manager", "manager", "va"),
    ("client", "client", None),
]


def _find(cur: Any, username: str) -> Any:
    cur.execute(
        "select id, role from public.users where lower(username) = lower(%s) limit 1",
        (username,),
    )
    return cur.fetchone()


def _first_client_id(cur: Any) -> str | None:
    cur.execute("select id from public.clients order by name limit 1")
    row = cur.fetchone()
    return str(row["id"]) if row else None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Provision/reset the standard portal logins (idempotent, dry-run by default)."
    )
    parser.add_argument(
        "--password-suffix", default="1234", help="password = username + this suffix (default: 1234)"
    )
    parser.add_argument("--only", help="comma-separated usernames to act on (default: all four)")
    parser.add_argument(
        "--client-id", help="tenant UUID for the client login (default: first client by name)"
    )
    parser.add_argument(
        "--email-domain", default="portal.local", help="email domain for CREATED users (default: portal.local)"
    )
    parser.add_argument("--yes", action="store_true", help="actually write; without it this is a dry run")
    args = parser.parse_args(argv)

    only = {u.strip().lower() for u in args.only.split(",")} if args.only else None
    targets = [t for t in _PORTAL_LOGINS if only is None or t[0] in only]
    if not targets:
        print("nothing to do (no usernames matched --only).")
        return 0

    settings = get_settings()
    pool = build_admin_pool(settings.database_admin_url)
    if pool is None:
        print("ERROR: DATABASE_ADMIN_URL is not configured; cannot provision.", file=sys.stderr)
        return 2

    print("!! simple, guessable passwords (username + suffix). On a public system the")
    print("!! admin/owner login can reveal the client vault and all tenant data.")
    if not args.yes:
        print("\nDRY RUN (pass --yes to apply). Would set:")
        for username, role, _ in targets:
            pw = f"{username}{args.password_suffix}"
            print(f"  {username:<10} -> {pw:<16} role={role}")
        return 0

    pool.open()
    set_pools(None, pool)
    results: list[tuple[str, str, str, str]] = []
    try:
        for username, role, template in targets:
            password = f"{username}{args.password_suffix}"
            with privileged_connection() as cur:
                existing = _find(cur, username)
            if existing is not None:
                new_hash = hash_password(password)
                with privileged_connection() as cur:
                    cur.execute(
                        "update auth.users set password_hash = %s where id = %s",
                        (new_hash, existing["id"]),
                    )
                results.append((username, password, str(existing["role"]), "reset"))
                continue

            client_id: str | None = None
            if role == "client":
                client_id = args.client_id
                if client_id is None:
                    with privileged_connection() as cur:
                        client_id = _first_client_id(cur)
                if client_id is None:
                    results.append((username, password, role, "SKIPPED-no-client"))
                    continue
            provision_user(
                email=f"{username}@{args.email_domain}",
                password=password,
                name=username.capitalize(),
                role=role,
                username=username,
                template_key=template,
                client_id=client_id,
            )
            results.append((username, password, role, "created"))

        print(f"\n{'username':<12}{'password':<16}{'role':<12}{'action':<20}login_ok")
        print("-" * 72)
        all_ok = True
        for username, password, urole, action in results:
            if action.startswith("SKIPPED"):
                print(f"{username:<12}{password:<16}{urole:<12}{action:<20}-")
                continue
            with privileged_connection() as cur:
                cur.execute(
                    "select a.password_hash from auth.users a "
                    "join public.users u on u.id = a.id "
                    "where lower(u.username) = lower(%s) limit 1",
                    (username,),
                )
                row = cur.fetchone()
            ok = verify_password(row["password_hash"], password) if row is not None else False
            all_ok = all_ok and ok
            print(f"{username:<12}{password:<16}{urole:<12}{action:<20}{ok}")
        print("-" * 72)
        print("ALL_LOGINS_OK" if all_ok else "SOME_LOGINS_FAILED")
        return 0 if all_ok else 1
    finally:
        pool.close()
        clear_pools()


if __name__ == "__main__":
    raise SystemExit(main())
