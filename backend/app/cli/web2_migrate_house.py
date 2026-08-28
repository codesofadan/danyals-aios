"""One-shot reconciliation: turn the legacy per-client web2 vault rows into ACCOUNTS.

The retired seeder (``seed_web2_vault``) wrote one vault row per (client, platform),
each holding a COPY of the same house credential. So the database cannot currently
answer the only question that matters for safety - "is this login shared, and if so by
whom?" - because sharing was expressed as duplication.

This script answers it by GROUPING THE DECRYPTED SECRETS: rows whose plaintext hashes
identical are, by definition, the same login. From that grouping it derives, per
platform:

* one ``house`` account where a secret is used by MORE THAN ONE client (and every
  property published through it is marked ``shared_origin``);
* one ``per_client`` account where a secret belongs to exactly one client.

Why hash the plaintext rather than the sealed bytes: AES-GCM uses a fresh random nonce
per seal (``vault.py``), so two seals of the SAME secret produce completely different
ciphertext. Comparing ``secret_sealed`` would report every row as unique and silently
conclude nothing is shared - the exact opposite of the truth.

The hash is used ONLY to group in memory and is never stored or logged; the plaintext
never leaves this process.

WHAT IT DOES NOT DO. It does not delete the legacy vault rows and it does not freeze
anything. Freezing needs the platform tiering (``web2_platforms.ownership_tier``, a
later migration) to know which platforms are per-client, and deleting a credential a
live property still publishes through is irreversible. Both are deliberate follow-ups;
this step is additive and re-runnable.

DRY RUN by default - it prints the plan and writes nothing. Pass ``--yes`` to apply.

    python -m app.cli.web2_migrate_house              # show what would happen
    python -m app.cli.web2_migrate_house --yes        # create accounts + attribute rows
"""

from __future__ import annotations

import argparse
import hashlib
import sys
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from app.config import get_settings
from app.db.database import build_admin_pool, clear_pools, privileged_connection, set_pools
from app.services.vault import open_sealed
from integrations.web2_credentials import vault_provider_for

OWNERSHIP_PER_CLIENT = "per_client"
OWNERSHIP_HOUSE = "house"


@dataclass(frozen=True)
class LegacyRow:
    """One existing ``vault_keys`` row for a web2 platform, already decrypted."""

    vault_id: str
    platform: str
    client_id: str  # the legacy label
    secret: str


@dataclass
class PlannedAccount:
    """One account the reconciliation would create, plus what it explains."""

    platform: str
    ownership: str
    client_id: str | None
    secret_fingerprint: str  # in-memory grouping key only; never stored
    client_ids: list[str] = field(default_factory=list)

    @property
    def handle(self) -> str:
        """A provisional handle. A house account is openly agency-owned, so naming it
        for the platform is honest. A per-client account gets a placeholder the
        operator MUST correct to the client's real brand handle before it publishes -
        we cannot invent the handle that already exists on the platform, and guessing
        one would write a false fact into the registry."""
        if self.ownership == OWNERSHIP_HOUSE:
            return f"aios-house-{_slug(self.platform)}"
        return f"legacy-{_slug(self.platform)}-{(self.client_ids[0] or '')[:8]}"

    @property
    def shared(self) -> bool:
        return self.ownership == OWNERSHIP_HOUSE


def _slug(value: str) -> str:
    return "".join(ch if ch.isalnum() else "-" for ch in value.lower()).strip("-")


def fingerprint(secret: str) -> str:
    """Stable grouping key for a decrypted credential. sha256 of the exact plaintext -
    two rows share a login iff this matches."""
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


def build_plan(rows: Sequence[LegacyRow]) -> list[PlannedAccount]:
    """Group legacy rows into the accounts they imply. Pure: no DB, no vault, no I/O.

    Grouping is per (platform, secret) - the same credential string on two different
    platforms is a coincidence, not one account."""
    groups: dict[tuple[str, str], list[LegacyRow]] = defaultdict(list)
    for row in rows:
        groups[(row.platform, fingerprint(row.secret))].append(row)

    plan: list[PlannedAccount] = []
    for (platform, fp), members in sorted(groups.items(), key=lambda kv: (kv[0][0], kv[0][1])):
        client_ids = sorted({m.client_id for m in members if m.client_id})
        # More than one CLIENT on one secret is the definition of a shared login. Two
        # rows for the SAME client (a re-seed, a rotation) are still one per-client
        # account, so the test is distinct clients, not row count.
        is_shared = len(client_ids) > 1
        plan.append(
            PlannedAccount(
                platform=platform,
                ownership=OWNERSHIP_HOUSE if is_shared else OWNERSHIP_PER_CLIENT,
                client_id=None if is_shared else (client_ids[0] if client_ids else None),
                secret_fingerprint=fp,
                client_ids=client_ids,
            )
        )
    return plan


# --------------------------------------------------------------------------- #
# I/O (privileged; service_role)
# --------------------------------------------------------------------------- #
def load_legacy_rows() -> list[LegacyRow]:
    """Read + decrypt every web2 vault row. A row that fails to open is SKIPPED with a
    warning rather than aborting: one unreadable secret must not block the migration of
    every other client, and a row we cannot read is one we must not claim to classify."""
    with privileged_connection() as cur:
        cur.execute(
            """
            select id, provider, label, secret_sealed
            from public.vault_keys
            where provider like 'web2:%%'
            order by provider, label, created_at
            """
        )
        raw = cur.fetchall()

    rows: list[LegacyRow] = []
    for r in raw:
        rec: dict[str, Any] = (
            r
            if isinstance(r, dict)
            else {"id": r[0], "provider": r[1], "label": r[2], "secret_sealed": r[3]}
        )
        provider = str(rec["provider"])
        platform = provider.split(":", 1)[1] if ":" in provider else provider
        try:
            secret = open_sealed(rec["secret_sealed"])
        except Exception:
            print(f"  WARNING: could not open vault row {rec['id']} ({provider}); skipped",
                  file=sys.stderr)
            continue
        rows.append(
            LegacyRow(
                vault_id=str(rec["id"]),
                platform=platform,
                client_id=str(rec["label"] or ""),
                secret=secret,
            )
        )
    return rows


def apply_plan(plan: Sequence[PlannedAccount], rows: Sequence[LegacyRow]) -> tuple[int, int]:
    """Create the accounts and attribute existing properties. Returns
    (accounts_created, properties_attributed). Idempotent: an account already present
    for (platform, handle) is reused, and a property that already has an account_id is
    left alone."""
    by_key = {(r.platform, fingerprint(r.secret)): r for r in rows}
    created = attributed = 0

    with privileged_connection() as cur:
        for account in plan:
            legacy = by_key.get((account.platform, account.secret_fingerprint))
            if legacy is None or not account.client_ids:
                # No clients on this credential means nothing to attribute. Guarding
                # here (rather than passing an empty list down) keeps the UPDATE's
                # parameter always a real list of ids.
                continue
            cur.execute(
                "select id from public.web2_accounts where platform = %s and handle = %s",
                (account.platform, account.handle),
            )
            found = cur.fetchone()
            if found is not None:
                account_id = str(found["id"] if isinstance(found, dict) else found[0])
            else:
                cur.execute(
                    """
                    insert into public.web2_accounts
                      (platform, ownership, client_id, handle, vault_provider, vault_label,
                       health, max_properties)
                    values (%s, %s, %s, %s, %s, %s, 'unverified', %s)
                    returning id
                    """,
                    (
                        account.platform,
                        account.ownership,
                        account.client_id,
                        account.handle,
                        vault_provider_for(account.platform),
                        # The legacy label stays the vault label: the sealed credential
                        # still lives under it, and re-sealing it under a new label
                        # would duplicate a secret this migration exists to de-duplicate.
                        legacy.client_id,
                        10 if account.shared else 1,
                    ),
                )
                inserted = cur.fetchone()
                if inserted is None:
                    continue
                account_id = str(inserted["id"] if isinstance(inserted, dict) else inserted[0])
                created += 1

            # Attribute only rows that are still unattributed, so a re-run is a no-op.
            cur.execute(
                """
                update public.web2_properties
                   set account_id = %s, shared_origin = %s
                 where platform = %s
                   and account_id is null
                   -- ::text is deliberate. The labels are plain strings, and while
                   -- psycopg does infer uuid[] for an uncast `any(%s)` (so real ids
                   -- match either way), any label that is not a well-formed uuid then
                   -- raises InvalidTextRepresentation and aborts the whole migration.
                   -- Legacy labels are operator-written data, not a guaranteed uuid.
                   and client_id::text = any(%s)
                """,
                (account_id, account.shared, account.platform, account.client_ids),
            )
            attributed += cur.rowcount or 0
    return created, attributed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Reconcile legacy per-client web2 vault rows into web2_accounts "
        "(dry run by default)."
    )
    parser.add_argument("--yes", action="store_true", help="actually write; else dry run")
    args = parser.parse_args(argv)

    settings = get_settings()
    pool = build_admin_pool(settings.database_admin_url)
    if pool is None:
        print("ERROR: DATABASE_ADMIN_URL is not configured.", file=sys.stderr)
        return 2
    pool.open()
    set_pools(None, pool)
    try:
        rows = load_legacy_rows()
        if not rows:
            print("nothing to do (no web2:* vault rows).")
            return 0
        plan = build_plan(rows)
        shared = [a for a in plan if a.shared]

        print(f"{'platform':<20}{'ownership':<12}{'clients':<9}handle")
        print("-" * 78)
        for a in plan:
            print(f"{a.platform[:18]:<20}{a.ownership:<12}{len(a.client_ids):<9}{a.handle}")
        print("-" * 78)
        print(f"{len(rows)} vault row(s) -> {len(plan)} account(s); {len(shared)} SHARED.")
        if shared:
            print(
                "\nEvery property published through a shared account is marked "
                "shared_origin=true. Those properties keep their live articles, but "
                "must not receive new publishes once platform tiering lands (R2-07)."
            )
        if not args.yes:
            print("\nDRY RUN - nothing written. Pass --yes to apply.")
            return 0

        created, attributed = apply_plan(plan, rows)
        print(f"\ncreated {created} account(s); attributed {attributed} propert(y/ies).")
        print(
            "NEXT: correct each per-client account's placeholder handle to the client's "
            "real brand handle (python -m app.cli.web2_accounts list)."
        )
        return 0
    finally:
        pool.close()
        clear_pools()


if __name__ == "__main__":
    raise SystemExit(main())
