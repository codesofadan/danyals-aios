"""Register and manage Web 2.0 publishing ACCOUNTS (replaces ``seed_web2_vault``).

The retired seeder copied ONE house credential into every client's vault row, keyed
``label=<client_id>``. That is the shared-footprint pattern R2-06 removes: one shared
login is one shared failure domain (a suspension takes every client's property down at
once), and the per-client copies made the clients mutually identifiable. Here an
account is a ROW in ``public.web2_accounts`` and its credential is sealed ONCE under
``label=<web2_accounts.id>``.

Two account shapes, and the difference is the whole point:

* ``per_client`` - the CLIENT owns the property. The handle is operator-entered and
  derived from the client's BRAND, and the registration email uses the client's own
  domain. Blast radius of a ban is one client.
* ``house``      - the agency publishes through it where publishing implies no durable
  identity (Telegra.ph and the like). Capped (``--max-properties``) because a ban here
  costs every client on it.

R2-08 identity hygiene is ENFORCED, not documented: a per-client handle is rejected if
it embeds the platform slug or a long hex run, because those were the two machine-
readable tells the generated identities used to emit (a shared platform prefix and a
``sha1(client_id)`` fragment), which let a platform enumerate our whole client base
from one suspended account.

DRY RUN by default; pass ``--yes`` to write. Runs OUTSIDE the FastAPI lifespan, so it
opens the privileged (service_role) pool itself from ``DATABASE_ADMIN_URL`` - the same
pattern as ``set_portal_logins``.

    python -m app.cli.web2_accounts list
    python -m app.cli.web2_accounts register --platform "Blogger" \
        --ownership per_client --client-id <uuid> --handle acmeroofing \
        --email web@acmeroofing.co.uk --credential-file creds.json --yes
    python -m app.cli.web2_accounts register --platform "Telegra.ph" \
        --ownership house --handle aios-house-telegraph --max-properties 10 --yes
    python -m app.cli.web2_accounts rotate --account-id <uuid> --credential-file new.json --yes
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.config import get_settings
from app.db.database import build_admin_pool, clear_pools, privileged_connection, set_pools
from app.services.vault import add_key
from integrations.web2_credentials import VAULT_KIND_CLIENT_ACCESS, vault_provider_for
from integrations.web2_publishers import PLATFORM_CREDENTIAL_FIELDS

OWNERSHIP_PER_CLIENT = "per_client"
OWNERSHIP_HOUSE = "house"

# A run of 8+ hex characters. The retired generator embedded the first 10 hex chars of
# sha1(client_id) in every handle it made, so every account for one client shared that
# fragment and every account across the base shared its shape. 8 (not 10) so a
# truncated variant of the same tell is still caught.
_HEX_RUN_RE = re.compile(r"[0-9a-f]{8,}", re.IGNORECASE)


class HandleRejectedError(ValueError):
    """A proposed per-client handle carries a footprint tell (R2-08)."""


def platform_slug(platform: str) -> str:
    """The lower-case alphanumeric reduction of a platform name, e.g.
    ``"WordPress.com" -> "wordpresscom"``. This is the shape the retired alias
    generator prefixed onto every handle, so it is what a handle must NOT contain."""
    return re.sub(r"[^a-z0-9]", "", platform.lower())


def validate_handle(handle: str, *, platform: str) -> str:
    """Return the handle, or raise :class:`HandleRejectedError` naming the tell.

    Enforces R2-08 for per-client accounts: the handle must read as the CLIENT'S BRAND,
    not as something our automation minted. Rejecting is deliberate - a warning would
    be ignored and the footprint would ship."""
    cleaned = handle.strip()
    if not cleaned:
        raise HandleRejectedError("handle is empty")
    if len(cleaned) < 3:
        raise HandleRejectedError("handle is too short to be a real brand handle")
    slug = platform_slug(platform)
    if slug and slug in platform_slug(cleaned):
        raise HandleRejectedError(
            f"handle embeds the platform name ({platform!r}); a real brand handle does "
            "not announce which platform it is on - that is the prefix a trust-and-"
            "safety team groups accounts by"
        )
    tell = _HEX_RUN_RE.search(cleaned)
    if tell is not None:
        raise HandleRejectedError(
            f"handle contains a hex run ({tell.group(0)!r}); generated ids are the "
            "fragment that links one client's accounts to each other"
        )
    return cleaned


def validate_registration_email(email: str, *, ownership: str, shared_domains: set[str]) -> str:
    """Per-client accounts must register on the CLIENT's own domain (R2-08.2).

    A shared catch-all domain across the whole client base is a single joinable key: a
    platform that suspends one account can enumerate the rest by registrant domain. It
    stays legitimate for house accounts, which are not pretending to be a client."""
    cleaned = email.strip().lower()
    if ownership != OWNERSHIP_PER_CLIENT:
        return cleaned
    if not cleaned or "@" not in cleaned:
        raise HandleRejectedError(
            "a per-client account needs a registration email on the client's own domain"
        )
    domain = cleaned.rsplit("@", 1)[-1]
    if domain in shared_domains:
        raise HandleRejectedError(
            f"registration domain {domain!r} is the shared catch-all; a per-client "
            "account must register on the client's own domain (R2-08.2)"
        )
    return cleaned


@dataclass(frozen=True)
class AccountSpec:
    """One account to register: the row plus the credential that seals with it."""

    platform: str
    ownership: str
    handle: str
    client_id: str | None
    registration_email: str
    property_url: str
    max_properties: int
    credential: dict[str, Any]

    @property
    def registration_domain(self) -> str:
        return self.registration_email.rsplit("@", 1)[-1] if "@" in self.registration_email else ""

    def missing_fields(self) -> list[str]:
        """Required credential keys this spec does not supply. An incomplete credential
        is still recorded (the factory degrades it to hold-at-review, same as absent),
        but the operator is told which field to go and get."""
        required = PLATFORM_CREDENTIAL_FIELDS.get(self.platform, ())
        return [f for f in required if not str(self.credential.get(f, "")).strip()]


def build_spec(
    *,
    platform: str,
    ownership: str,
    handle: str,
    client_id: str | None,
    registration_email: str,
    property_url: str,
    max_properties: int,
    credential: dict[str, Any],
    shared_domains: set[str],
) -> AccountSpec:
    """Validate the inputs into an :class:`AccountSpec`, or raise ``HandleRejectedError`` /
    ``ValueError``. Pure - no DB, no vault - so the rules are unit-testable."""
    if ownership not in (OWNERSHIP_PER_CLIENT, OWNERSHIP_HOUSE):
        raise ValueError(f"unknown ownership {ownership!r}")
    if platform not in PLATFORM_CREDENTIAL_FIELDS:
        raise ValueError(f"unknown platform {platform!r} (no credential shape is defined for it)")
    if ownership == OWNERSHIP_PER_CLIENT and not client_id:
        raise ValueError("a per_client account requires --client-id")
    if ownership == OWNERSHIP_HOUSE and client_id:
        raise ValueError("a house account must NOT name a client (it serves many)")

    checked_handle = handle.strip()
    if ownership == OWNERSHIP_PER_CLIENT:
        # House handles are exempt: they are openly agency-owned and pretend to be
        # nobody, so an 'aios-house-*' name is honest rather than a tell.
        checked_handle = validate_handle(handle, platform=platform)
    email = validate_registration_email(
        registration_email, ownership=ownership, shared_domains=shared_domains
    )
    return AccountSpec(
        platform=platform,
        ownership=ownership,
        handle=checked_handle,
        client_id=client_id or None,
        registration_email=email,
        property_url=property_url.strip(),
        max_properties=max(1, int(max_properties)),
        credential=credential,
    )


# --------------------------------------------------------------------------- #
# DB / vault I/O (privileged; service_role)
# --------------------------------------------------------------------------- #
def insert_account(spec: AccountSpec) -> str:
    """Insert the account row and return its id. The vault label IS this id, so the row
    must exist before the credential is sealed."""
    with privileged_connection() as cur:
        cur.execute(
            """
            insert into public.web2_accounts
              (platform, ownership, client_id, handle, property_url,
               registration_email, registration_domain, vault_provider, vault_label,
               max_properties)
            values (%s, %s, %s, %s, %s, %s, %s, %s, '', %s)
            returning id
            """,
            (
                spec.platform,
                spec.ownership,
                spec.client_id,
                spec.handle,
                spec.property_url,
                spec.registration_email,
                spec.registration_domain,
                vault_provider_for(spec.platform),
                spec.max_properties,
            ),
        )
        row = cur.fetchone()
        if row is None:  # an INSERT ... RETURNING that yields nothing is not recoverable
            raise RuntimeError("web2_accounts insert returned no id")
        account_id = str(row["id"] if isinstance(row, dict) else row[0])
        # The label is only knowable after the insert, so it is set in the same txn.
        cur.execute(
            "update public.web2_accounts set vault_label = %s where id = %s",
            (account_id, account_id),
        )
        return account_id


def list_accounts() -> list[dict[str, Any]]:
    with privileged_connection() as cur:
        cur.execute(
            """
            select a.id, a.platform, a.ownership, a.handle, a.health,
                   a.property_count, a.max_properties, coalesce(c.name, '') as client_name
            from public.web2_accounts a
            left join public.clients c on c.id = a.client_id
            order by a.ownership, a.platform, a.handle
            """
        )
        rows = cur.fetchall()
    out: list[dict[str, Any]] = []
    for r in rows:
        out.append(
            r
            if isinstance(r, dict)
            else {
                "id": r[0], "platform": r[1], "ownership": r[2], "handle": r[3],
                "health": r[4], "property_count": r[5], "max_properties": r[6],
                "client_name": r[7],
            }
        )
    return out


def _load_credential(path: str | None) -> dict[str, Any]:
    if not path:
        return {}
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("credential file must be a JSON object of field -> value")
    return data


def _shared_domains() -> set[str]:
    """Domains that must never back a per-client registration: the agency catch-all."""
    settings = get_settings()
    domains = set()
    for attr in ("citation_mail_domain", "mailbox_catchall_domain"):
        value = str(getattr(settings, attr, "") or "").strip().lower()
        if value:
            domains.add(value)
    return domains


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Register and manage Web 2.0 publishing accounts (dry-run by default)."
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("list", help="list registered accounts")

    reg = sub.add_parser("register", help="register one account and seal its credential")
    reg.add_argument("--platform", required=True)
    reg.add_argument("--ownership", required=True, choices=[OWNERSHIP_PER_CLIENT, OWNERSHIP_HOUSE])
    reg.add_argument("--handle", required=True, help="the real account name on the platform")
    reg.add_argument("--client-id", help="required for --ownership per_client")
    reg.add_argument("--email", default="", help="registration email (client domain for per_client)")
    reg.add_argument("--property-url", default="")
    reg.add_argument("--max-properties", type=int, default=1)
    reg.add_argument("--credential-file", help="JSON file of the platform's credential fields")
    reg.add_argument("--yes", action="store_true", help="actually write; else dry run")

    rot = sub.add_parser("rotate", help="seal a NEW credential for an existing account")
    rot.add_argument("--account-id", required=True)
    rot.add_argument("--credential-file", required=True)
    rot.add_argument("--yes", action="store_true")

    args = parser.parse_args(argv)

    settings = get_settings()
    pool = build_admin_pool(settings.database_admin_url)
    if pool is None:
        print("ERROR: DATABASE_ADMIN_URL is not configured.", file=sys.stderr)
        return 2
    pool.open()
    set_pools(None, pool)
    try:
        if args.command == "list":
            rows = list_accounts()
            if not rows:
                print("no web2 accounts registered yet.")
                return 0
            print(f"{'platform':<18}{'ownership':<12}{'handle':<26}{'health':<12}props  client")
            print("-" * 92)
            for r in rows:
                props = f"{r['property_count']}/{r['max_properties']}"
                print(
                    f"{str(r['platform'])[:16]:<18}{r['ownership']!s:<12}"
                    f"{str(r['handle'])[:24]:<26}{r['health']!s:<12}{props:<7}{r['client_name']}"
                )
            return 0

        if args.command == "register":
            try:
                spec = build_spec(
                    platform=args.platform,
                    ownership=args.ownership,
                    handle=args.handle,
                    client_id=args.client_id,
                    registration_email=args.email,
                    property_url=args.property_url,
                    max_properties=args.max_properties,
                    credential=_load_credential(args.credential_file),
                    shared_domains=_shared_domains(),
                )
            except (HandleRejectedError, ValueError, OSError, json.JSONDecodeError) as exc:
                print(f"REFUSED: {exc}", file=sys.stderr)
                return 2

            missing = spec.missing_fields()
            print(f"platform    : {spec.platform}")
            print(f"ownership   : {spec.ownership}")
            print(f"handle      : {spec.handle}")
            print(f"client_id   : {spec.client_id or '-'}")
            print(f"registration: {spec.registration_email or '-'}")
            print(f"cap         : {spec.max_properties} propert(y/ies)")
            if missing:
                print(f"MISSING     : {', '.join(missing)} (will hold at review until supplied)")
            if not args.yes:
                print("DRY RUN - pass --yes to write.")
                return 0

            account_id = insert_account(spec)
            if spec.credential:
                add_key(
                    provider=vault_provider_for(spec.platform),
                    label=account_id,
                    secret=json.dumps(spec.credential),
                    kind=VAULT_KIND_CLIENT_ACCESS,
                )
            print(f"registered account {account_id}")
            return 0

        # rotate
        try:
            credential = _load_credential(args.credential_file)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 2
        if not credential:
            print("ERROR: --credential-file is empty.", file=sys.stderr)
            return 2
        with privileged_connection() as cur:
            cur.execute(
                "select platform from public.web2_accounts where id = %s", (args.account_id,)
            )
            found = cur.fetchone()
        if found is None:
            print(f"ERROR: no account {args.account_id}.", file=sys.stderr)
            return 2
        platform = str(found[0] if not isinstance(found, dict) else found["platform"])
        if not args.yes:
            print(f"DRY RUN - would rotate the {platform} credential. Pass --yes to write.")
            return 0
        # find_secret reads the NEWEST row, so a rotation is an insert, not an update:
        # the previous sealed value stays for audit and is simply no longer selected.
        add_key(
            provider=vault_provider_for(platform),
            label=args.account_id,
            secret=json.dumps(credential),
            kind=VAULT_KIND_CLIENT_ACCESS,
        )
        print(f"rotated the {platform} credential for {args.account_id}")
        return 0
    finally:
        pool.close()
        clear_pools()


if __name__ == "__main__":
    raise SystemExit(main())
