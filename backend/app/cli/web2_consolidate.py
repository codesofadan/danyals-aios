"""Move the Web 2.0 LEDGER from one database into another. Dry run by default.

WHY THIS EXISTS. Publishing was proved from a second database because that is where the
sealed credentials already were, which left the record of what actually went live in one
database and the portal's own client list in another. Two ledgers for one module is how a
placement stops being findable: the client is in one place, the live URL in the other.

WHAT IT MOVES: properties, campaigns and similarity fingerprints - the RECORD of work.

WHAT IT DELIBERATELY DOES NOT MOVE: credentials. A sealed secret is not copied between
databases by this tool at all. Accounts are matched in the TARGET by (platform, client),
and a property whose account has no match is reported rather than silently re-pointed -
attaching a live placement to the wrong account would misattribute every future publish.
Re-register the credential in the target through the portal's account board.

IDEMPOTENT: a property already present in the target (same post_url, or same client +
platform + topic) is skipped, so the command can be re-run after fixing a mapping.

    python -m app.cli.web2_consolidate --source <DSN> --target <DSN>
    python -m app.cli.web2_consolidate --source <DSN> --target <DSN> --yes
"""

from __future__ import annotations

import argparse
from typing import Any

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

_COPY_COLUMNS = (
    "client_name", "platform", "post_url", "anchor", "verified", "published_at",
    "status", "topic", "page_type", "framework", "target_url", "body_md",
    "external_id", "error", "source_pack", "shared_origin", "scheduled_for",
    "link_rel", "link_found", "link_checked_at",
)


def _clients_by_name(cur: Any) -> dict[str, str]:
    cur.execute("select id, name from public.clients")
    return {str(r["name"]): str(r["id"]) for r in cur.fetchall()}


def _accounts_by_key(cur: Any) -> dict[tuple[str, str], str]:
    """(platform, client_name) -> account id, for the TARGET database."""
    cur.execute(
        "select a.id, a.platform, coalesce(c.name, '') as client_name "
        "from public.web2_accounts a left join public.clients c on c.id = a.client_id"
    )
    return {(str(r["platform"]), str(r["client_name"])): str(r["id"]) for r in cur.fetchall()}


def plan(source: Any, target: Any) -> tuple[list[dict[str, Any]], list[str]]:
    """What would move, and what cannot. Reads only."""
    source.execute(
        "select p.*, coalesce(c.name, p.client_name) as src_client "
        "from public.web2_properties p left join public.clients c on c.id = p.client_id "
        "order by p.created_at"
    )
    rows = [dict(r) for r in source.fetchall()]

    target_clients = _clients_by_name(target)
    target_accounts = _accounts_by_key(target)
    target.execute("select coalesce(post_url, '') u, client_name, platform, topic "
                   "from public.web2_properties")
    existing_urls = set()
    existing_keys = set()
    for r in target.fetchall():
        if r["u"]:
            existing_urls.add(str(r["u"]))
        existing_keys.add((str(r["client_name"]), str(r["platform"]), str(r["topic"])))

    movable: list[dict[str, Any]] = []
    problems: list[str] = []
    for row in rows:
        name = str(row["src_client"])
        key = (name, str(row["platform"]), str(row["topic"]))
        if (row.get("post_url") and str(row["post_url"]) in existing_urls) or key in existing_keys:
            continue  # already there; re-runnable
        client_id = target_clients.get(name)
        if client_id is None:
            problems.append(f"{name}: no client of that name in the target database")
            continue
        account_id = target_accounts.get((str(row["platform"]), name))
        if row.get("account_id") and account_id is None:
            problems.append(
                f"{name} / {row['platform']}: published through an account that does not "
                "exist in the target - register it there first (the credential is NOT copied)"
            )
            continue
        movable.append({**row, "_client_id": client_id, "_account_id": account_id})
    return movable, problems


def apply_move(target: Any, movable: list[dict[str, Any]]) -> int:
    cols = ", ".join(_COPY_COLUMNS)
    placeholders = ", ".join(["%s"] * len(_COPY_COLUMNS))
    moved = 0
    for row in movable:
        target.execute(
            f"insert into public.web2_properties (client_id, account_id, {cols}) "
            f"values (%s, %s, {placeholders})",
            [
                row["_client_id"],
                row["_account_id"],
                # `source_pack` is jsonb: it reads back as a dict and must be re-wrapped,
                # or psycopg cannot adapt it on the way in.
                *[
                    Jsonb(row.get(c) or {}) if c == "source_pack" else row.get(c)
                    for c in _COPY_COLUMNS
                ],
            ],
        )
        moved += 1
    return moved


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, help="DSN to read the ledger FROM")
    parser.add_argument("--target", required=True, help="DSN to write the ledger INTO")
    parser.add_argument("--yes", action="store_true", help="actually write; else dry run")
    args = parser.parse_args(argv)

    with (
        psycopg.connect(args.source, row_factory=dict_row) as src,
        psycopg.connect(args.target, row_factory=dict_row) as tgt,
        src.cursor() as scur,
        tgt.cursor() as tcur,
    ):
        movable, problems = plan(scur, tcur)
        print(f"{len(movable)} propert(y/ies) would move, {len(problems)} blocked\n")
        for row in movable:
            live = row.get("post_url") or "-"
            print(f"  {row['src_client']:<18}{row['platform']:<17}{row['status']:<12}{live[:58]}")
        for problem in problems:
            print(f"  BLOCKED  {problem}")
        if not args.yes:
            print("\nDRY RUN - pass --yes to write.")
            return 0
        moved = apply_move(tcur, movable)
        tgt.commit()
        print(f"\nmoved {moved} propert(y/ies). Credentials were NOT copied.")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
