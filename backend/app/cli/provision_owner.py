"""Idempotently provision the first local OWNER so the app + tests have a login.

Since there is no public signup, a fresh local database has zero users and the
app is unusable until a super-admin exists. This CLI mints exactly one owner
(``role='owner'``, the ``super`` template = all features on) from
``SEED_OWNER_USERNAME``/``SEED_OWNER_PASSWORD`` (or ``--username``/``--password``
overrides). It is IDEMPOTENT: if a user with that username already exists it
prints its id and exits 0, so re-running (in dev, in CI bootstrap) is safe. The
password is read from the environment/args and NEVER printed or logged.

    python -m app.cli.provision_owner            # from SEED_OWNER_* in .env
    python -m app.cli.provision_owner --username owner --password '...'

It runs OUTSIDE the FastAPI lifespan, so it builds + opens the privileged pool
itself (service_role DSN) and tears it down on exit.
"""

from __future__ import annotations

import argparse
import sys

from app.config import get_settings
from app.db.database import (
    build_admin_pool,
    clear_pools,
    privileged_connection,
    set_pools,
)
from app.services.provisioning import provision_user


def _existing_owner_id(username: str) -> str | None:
    """Return the id of an existing user with ``username`` (case-insensitive) or None."""
    with privileged_connection() as cur:
        cur.execute(
            "select id from public.users where lower(username) = lower(%s) limit 1",
            (username,),
        )
        row = cur.fetchone()
    return str(row["id"]) if row else None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Provision the first local OWNER (idempotent).")
    parser.add_argument("--username", help="login username (default: SEED_OWNER_USERNAME)")
    parser.add_argument("--password", help="password (default: SEED_OWNER_PASSWORD); never printed")
    parser.add_argument("--email", help="email (default: SEED_OWNER_EMAIL)")
    parser.add_argument("--name", help="display name (default: SEED_OWNER_NAME)")
    args = parser.parse_args(argv)

    settings = get_settings()
    username = args.username or settings.seed_owner_username
    password = args.password or (
        settings.seed_owner_password.get_secret_value() if settings.seed_owner_password else None
    )
    email = args.email or settings.seed_owner_email
    name = args.name or settings.seed_owner_name

    if not username or not password:
        print(
            "ERROR: username and password are required "
            "(set SEED_OWNER_USERNAME/SEED_OWNER_PASSWORD or pass --username/--password).",
            file=sys.stderr,
        )
        return 2

    admin_pool = build_admin_pool(settings.database_admin_url)
    if admin_pool is None:
        print("ERROR: DATABASE_ADMIN_URL is not configured; cannot provision.", file=sys.stderr)
        return 2

    admin_pool.open()
    set_pools(None, admin_pool)
    try:
        existing = _existing_owner_id(username)
        if existing is not None:
            print(f"OK: owner '{username}' already provisioned (id={existing}); nothing to do.")
            return 0
        row = provision_user(
            email=email,
            password=password,
            name=name,
            role="owner",
            username=username,
            template_key="super",
        )
        print(f"OK: provisioned owner '{username}' (id={row['id']}, email={email}).")
        return 0
    finally:
        admin_pool.close()
        clear_pools()


if __name__ == "__main__":
    raise SystemExit(main())
