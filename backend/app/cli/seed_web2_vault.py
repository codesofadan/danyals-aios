"""Seed the per-client Web 2.0 vault rows from the agency's HOUSE accounts.

The Web2 publish pipeline builds its per-client publisher from the VAULT — one
AES-GCM-sealed row per (client, platform): ``provider='web2:<Platform>'``,
``label=<client_id>``, ``kind='client_access'`` (see integrations/web2_credentials.py
and docs/CITATIONS-WEB2-CREDENTIALS.md). The agency publishes through shared HOUSE
accounts (one dev.to / Telegra.ph / Mastodon / ... login used for every client), so
every new client needs the same set of rows copied in — a chore this CLI automates.

The house credentials come from ``WEB2_HOUSE_CREDENTIALS_JSON`` (or ``--file``): a
JSON object mapping the platform display name (exactly as in
``web2_publishers.PLATFORM_CREDENTIAL_FIELDS``) to its credential fields, e.g.::

    {"dev.to": {"api_key": "..."}, "Mastodon": {"access_token": "...",
     "instance_url": "https://mastodon.social"}}

IDEMPOTENT: an existing (provider, label) row is never touched — re-running after
onboarding a new client only adds that client's missing rows, and a row you rotated
by hand keeps its rotated value (``find_secret`` reads the newest row anyway). A
platform with missing/blank required fields is still seeded but WARNED about: the
credential factory degrades an incomplete row to "hold at review", same as absent,
so seeding it early is honest visibility (the dashboard vault list shows it), not a
publish risk.

DRY RUN by default (prints the plan); pass ``--yes`` to write. Runs OUTSIDE the
FastAPI lifespan, so it opens the privileged (service_role) pool itself from
``DATABASE_ADMIN_URL`` — the same pattern as ``set_portal_logins``.

    python -m app.cli.seed_web2_vault                    # dry run — show the plan
    python -m app.cli.seed_web2_vault --yes              # seed every client
    python -m app.cli.seed_web2_vault --yes --client-id <uuid>
    python -m app.cli.seed_web2_vault --yes --platforms "dev.to,Mastodon"
    python -m app.cli.seed_web2_vault --yes --file house-creds.json
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.config import get_settings
from app.db.database import build_admin_pool, clear_pools, privileged_connection, set_pools
from app.services.vault import add_key
from integrations.web2_credentials import vault_provider_for
from integrations.web2_publishers import PLATFORM_CREDENTIAL_FIELDS

ACTION_SEED = "seed"
ACTION_SKIP_EXISTS = "skip-exists"
ACTION_SKIP_UNKNOWN = "skip-unknown-platform"


@dataclass(frozen=True)
class SeedPlanEntry:
    """One (client, platform) decision: what the seeder would do and why."""

    client_id: str
    client_name: str
    platform: str
    provider: str
    action: str
    missing: tuple[str, ...] = field(default=())


def build_plan(
    clients: Sequence[tuple[str, str]],
    house: Mapping[str, Mapping[str, Any]],
    row_exists: Callable[[str, str], bool],
) -> list[SeedPlanEntry]:
    """Pure planning core: cross clients x house platforms into seed decisions.

    ``row_exists(provider, label)`` is the one impure seam (a vault lookup),
    injected so the plan is unit-testable without a database. Unknown platforms
    (no entry in ``PLATFORM_CREDENTIAL_FIELDS``) are skipped — a typo in the house
    JSON must surface as a visible skip, never a dead vault row no publisher reads.
    """
    plan: list[SeedPlanEntry] = []
    for client_id, client_name in clients:
        for platform, creds in house.items():
            provider = vault_provider_for(platform)
            required = PLATFORM_CREDENTIAL_FIELDS.get(platform)
            if required is None:
                plan.append(
                    SeedPlanEntry(client_id, client_name, platform, provider, ACTION_SKIP_UNKNOWN)
                )
                continue
            if row_exists(provider, client_id):
                plan.append(
                    SeedPlanEntry(client_id, client_name, platform, provider, ACTION_SKIP_EXISTS)
                )
                continue
            missing = tuple(f for f in required if not str(creds.get(f, "") or "").strip())
            plan.append(
                SeedPlanEntry(client_id, client_name, platform, provider, ACTION_SEED, missing)
            )
    return plan


def execute_plan(
    plan: Sequence[SeedPlanEntry],
    house: Mapping[str, Mapping[str, Any]],
    add: Callable[..., Any],
) -> int:
    """Write every ``seed`` entry through ``add`` (``app.services.vault.add_key`` in
    production, a recorder in tests); returns how many rows were written. The secret
    payload is the house credential dict re-serialized as compact JSON — exactly the
    shape ``web2_credentials.build_publisher`` parses back."""
    written = 0
    for entry in plan:
        if entry.action != ACTION_SEED:
            continue
        add(
            provider=entry.provider,
            label=entry.client_id,
            secret=json.dumps(dict(house[entry.platform]), separators=(",", ":")),
            kind="client_access",
        )
        written += 1
    return written


def _load_house(file_arg: str | None) -> Mapping[str, Mapping[str, Any]] | None:
    """House credentials from ``--file`` (wins) or ``WEB2_HOUSE_CREDENTIALS_JSON``."""
    if file_arg:
        raw: str | None = Path(file_arg).read_text(encoding="utf-8")
    else:
        secret = get_settings().web2_house_credentials_json
        raw = secret.get_secret_value() if secret else None
    if not raw or not raw.strip():
        return None
    parsed = json.loads(raw)
    if not isinstance(parsed, dict):
        raise ValueError("house credentials must be a JSON object {platform: {field: value}}")
    return {str(k): dict(v) for k, v in parsed.items() if isinstance(v, dict)}


def _fetch_clients(client_id: str | None) -> list[tuple[str, str]]:
    with privileged_connection() as cur:
        if client_id:
            cur.execute("select id::text, name from public.clients where id = %s", (client_id,))
        else:
            cur.execute("select id::text, name from public.clients order by name")
        return [(str(r["id"]), str(r["name"])) for r in cur.fetchall()]


def _row_exists(provider: str, label: str) -> bool:
    with privileged_connection() as cur:
        cur.execute(
            "select 1 from public.vault_keys where provider = %s and label = %s limit 1",
            (provider, label),
        )
        return cur.fetchone() is not None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Seed per-client web2:<Platform> vault rows from the house accounts "
        "(idempotent, dry-run by default)."
    )
    parser.add_argument("--file", help="JSON file of house credentials (default: env)")
    parser.add_argument("--client-id", help="seed ONE client (default: every client)")
    parser.add_argument("--platforms", help="comma-separated platform filter (default: all)")
    parser.add_argument("--yes", action="store_true", help="actually write; else dry run")
    args = parser.parse_args(argv)

    try:
        house = _load_house(args.file)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"ERROR: could not load house credentials: {exc}", file=sys.stderr)
        return 2
    if not house:
        print(
            "ERROR: no house credentials (set WEB2_HOUSE_CREDENTIALS_JSON or pass --file).",
            file=sys.stderr,
        )
        return 2
    if args.platforms:
        wanted = {p.strip() for p in args.platforms.split(",") if p.strip()}
        house = {k: v for k, v in house.items() if k in wanted}
        if not house:
            print("nothing to do (no platforms matched --platforms).", file=sys.stderr)
            return 2

    settings = get_settings()
    pool = build_admin_pool(settings.database_admin_url)
    if pool is None:
        print("ERROR: DATABASE_ADMIN_URL is not configured; cannot seed.", file=sys.stderr)
        return 2
    pool.open()
    set_pools(None, pool)
    try:
        clients = _fetch_clients(args.client_id)
        if not clients:
            print("nothing to do (no clients in the database yet)." )
            return 0
        plan = build_plan(clients, house, _row_exists)

        print(f"{'client':<28}{'platform':<16}{'action':<24}notes")
        print("-" * 84)
        for e in plan:
            notes = f"MISSING: {', '.join(e.missing)}" if e.missing else ""
            print(f"{e.client_name[:26]:<28}{e.platform:<16}{e.action:<24}{notes}")
        print("-" * 84)
        to_seed = sum(1 for e in plan if e.action == ACTION_SEED)
        if not args.yes:
            print(f"DRY RUN — {to_seed} row(s) would be seeded. Pass --yes to write.")
            return 0
        written = execute_plan(plan, house, add_key)
        print(f"seeded {written} vault row(s); {len(plan) - written} skipped.")
        return 0
    finally:
        pool.close()
        clear_pools()


if __name__ == "__main__":
    raise SystemExit(main())
