"""Emit the Web 2.0 credential worksheet - what is connected, what is missing, and
exactly what a teammate must go and fetch for each gap.

WHY A GENERATED SHEET AND NOT A DOCUMENT. A hand-written credential list is stale the
day after it is written: platforms get connected, tokens get rotated, tiers get changed,
and the list keeps claiming otherwise. This reads the LIVE state every time - the
platform catalogue, the registered accounts, and whether each sealed credential is
actually complete - and joins it to a curated acquisition guide. Re-run it and the sheet
is correct again; there is nothing to keep in sync by hand.

WHAT IT WILL NOT DO. It never reads or prints a secret. Completeness is decided by
asking the credential factory whether it can BUILD a publisher, which answers "is this
usable" without revealing what the value is. A sheet that leaked tokens could not be
shared with the team, which is the entire point of it.

    python -m app.cli.web2_credentials_sheet                       # to stdout
    python -m app.cli.web2_credentials_sheet --out creds.csv       # to a file
    python -m app.cli.web2_credentials_sheet --out creds.csv --all # incl. out-of-scope
"""

from __future__ import annotations

import argparse
import csv
import sys
from dataclasses import dataclass, field
from typing import Any

from app.config import get_settings
from app.db.database import build_admin_pool, clear_pools, privileged_connection, set_pools
from app.services.vault import find_secret
from app.services.web2_provisioning import GUIDES
from integrations.web2_credentials import build_publisher
from integrations.web2_publishers import PLATFORM_CREDENTIAL_FIELDS

STATUS_CONNECTED = "CONNECTED"
STATUS_INCOMPLETE = "INCOMPLETE"
STATUS_MISSING = "NOT CONNECTED"
#: Needs no human credential at all - a command provisions it. Distinguished from
#: NOT CONNECTED so nobody is assigned an errand that has nothing to fetch.
STATUS_AUTO = "AUTO - run the command"


OUT_OF_SCOPE_NOTE = (
    "Catalogued do_not_use: its terms, its link value, or its content model make a "
    "placement here indefensible. A stored credential does not change that."
)


@dataclass
class Row:
    platform: str
    status: str
    ownership_tier: str
    scope: str
    authority: str
    required: str
    missing: str
    cost: str
    account_needed: str
    where: str
    steps: str
    blocker: str
    priority: str = ""
    fields: list[str] = field(default_factory=list)


def _catalogue() -> list[dict[str, Any]]:
    with privileged_connection() as cur:
        cur.execute(
            "select platform_enum as platform, ownership_tier, topical_scope, "
            "       authority_tier "
            "from public.web2_platforms where platform_enum is not null "
            "order by platform_enum"
        )
        return [dict(r) for r in cur.fetchall()]


def _accounts() -> dict[str, dict[str, Any]]:
    with privileged_connection() as cur:
        cur.execute(
            "select platform, ownership, handle, vault_provider, vault_label "
            "from public.web2_accounts order by created_at"
        )
        return {str(r["platform"]): dict(r) for r in cur.fetchall()}


def _missing_fields(platform: str, account: dict[str, Any] | None) -> list[str]:
    """Which required fields are still blank.

    Asks the credential FACTORY whether it can build a publisher, then, if not, reports
    the field names from the shape. It never reads the secret back, so the sheet can be
    shared without leaking anything.
    """
    required = list(PLATFORM_CREDENTIAL_FIELDS.get(platform, ()))
    if account is None:
        return required
    publisher = build_publisher(
        vault_label=str(account["vault_label"]), platform=platform, lookup=find_secret
    )
    if publisher is not None:
        return []
    # Incomplete: we cannot say WHICH field without reading the secret, so name the
    # shape and let the holder of the credential see what is blank.
    return required


def build_rows(*, include_out_of_scope: bool) -> list[Row]:
    accounts = _accounts()
    rows: list[Row] = []
    for cat in _catalogue():
        platform = str(cat["platform"])
        tier = str(cat["ownership_tier"])
        in_scope = tier != "do_not_use"
        account = accounts.get(platform)
        if not in_scope and account is None and not include_out_of_scope:
            continue

        required = list(PLATFORM_CREDENTIAL_FIELDS.get(platform, ()))
        guide = GUIDES.get(platform)
        missing: list[str] = []
        if platform == "Telegra.ph":
            # Anonymous by design: there is no token for a person to go and get.
            status = STATUS_CONNECTED if account else STATUS_AUTO
        elif account is None:
            status, missing = STATUS_MISSING, required
        else:
            missing = _missing_fields(platform, account)
            status = STATUS_INCOMPLETE if missing else STATUS_CONNECTED

        blocker = guide.blocker if guide else ""
        if not in_scope:
            blocker = (OUT_OF_SCOPE_NOTE + (" " + blocker if blocker else "")).strip()

        rows.append(
            Row(
                platform=platform,
                status=status if in_scope else "NOT IN SCOPE",
                ownership_tier=tier,
                scope=str(cat["topical_scope"]),
                authority=str(cat["authority_tier"]),
                required=", ".join(required) or "(none)",
                missing=", ".join(missing) if missing else "",
                cost=guide.cost if guide else "Free",
                account_needed=(
                    guide.account_needed if guide
                    else ("One account per CLIENT" if tier == "per_client" else "Agency house account")
                ),
                where=guide.where if guide else "",
                steps=guide.steps if guide else "",
                blocker=blocker,
                fields=required,
            )
        )
    return _prioritise(rows)


def _prioritise(rows: list[Row]) -> list[Row]:
    """Order the sheet by what a team should actually pick up first.

    P1 is the set that unlocks a NORMAL client: the three agnostic, high-authority blog
    platforms every local business can legitimately use. Everything else is only useful
    for a client whose industry fits it, so it cannot be the first task.
    """
    def rank(r: Row) -> tuple[int, str]:
        if r.status in (STATUS_CONNECTED, "NOT IN SCOPE", STATUS_AUTO):
            base = 7 if r.status == STATUS_AUTO else (8 if r.status == STATUS_CONNECTED else 9)
        elif r.ownership_tier == "per_client" and r.scope == "agnostic":
            base = 1                                   # unlocks any client
        elif r.status == STATUS_INCOMPLETE:
            base = 2                                   # one field from working
        elif r.authority == "high":
            base = 3
        else:
            base = 4
        return (base, r.platform)

    ordered = sorted(rows, key=rank)
    labels = {1: "P1 - do first", 2: "P2 - nearly there", 3: "P3", 4: "P4",
              7: "ours - no credential", 8: "done", 9: "-"}
    for r in ordered:
        r.priority = labels[rank(r)[0]]
    return ordered


HEADERS = [
    "Priority", "Platform", "Status", "Who it is for", "Account needed",
    "Credentials required", "Still missing", "Cost", "Where to get it",
    "Steps", "Watch out for", "Ownership tier", "Link authority",
]


def to_csv(rows: list[Row], handle: Any) -> None:
    w = csv.writer(handle)
    w.writerow(HEADERS)
    for r in rows:
        w.writerow([
            r.priority, r.platform, r.status, r.scope, r.account_needed,
            r.required, r.missing, r.cost, r.where, r.steps, r.blocker,
            r.ownership_tier, r.authority,
        ])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Generate the Web 2.0 credential worksheet from live platform state."
    )
    parser.add_argument("--out", help="write CSV here (default: stdout)")
    parser.add_argument("--all", action="store_true",
                        help="include platforms tiered do_not_use")
    args = parser.parse_args(argv)

    settings = get_settings()
    pool = build_admin_pool(settings.database_admin_url)
    if pool is None:
        print("ERROR: DATABASE_ADMIN_URL is not configured.", file=sys.stderr)
        return 2
    pool.open()
    set_pools(None, pool)
    try:
        rows = build_rows(include_out_of_scope=args.all)
        if args.out:
            with open(args.out, "w", newline="", encoding="utf-8") as fh:
                to_csv(rows, fh)
            live = sum(1 for r in rows if r.status == STATUS_CONNECTED)
            todo = sum(1 for r in rows if r.status in (STATUS_MISSING, STATUS_INCOMPLETE))
            auto = sum(1 for r in rows if r.status == STATUS_AUTO)
            print(
                f"wrote {args.out}  -  {len(rows)} platform(s): {live} connected, "
                f"{todo} for the team to arrange, {auto} we provision ourselves"
            )
        else:
            to_csv(rows, sys.stdout)
        return 0
    finally:
        pool.close()
        clear_pools()


if __name__ == "__main__":
    raise SystemExit(main())
