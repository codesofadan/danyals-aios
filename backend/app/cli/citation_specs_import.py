"""Seed the 50 in-code form specs into the whitelist, INACTIVE - the verification queue.

WHAT THIS IS FOR. `FORM_SPECS` in `integrations/citation_bot.py` holds 50 hand-written
directory form specs. Their own module docstring says none was ever verified against a
live DOM, and a 2026-08-23 probe found 29 of the URLs answering 403, 8 answering 404 and
6 hosts dead. They were never coverage; they were a list of guesses.

They are still worth importing, because a guess is a starting point for a verification.
This writes each one into `directory_specs` (0111) as `active = false, verified_at = NULL`
- so it changes NOTHING about what the bot will submit to, and everything about what an
operator can see. It turns "somebody should check these one day" into a work queue with
50 named rows.

WHY THIS IS A CLI AND NOT A MIGRATION. The specs live in Python and SQL cannot read
Python. Inlining them as SQL literals would fork the source of truth into two places that
silently drift. The two states are also behaviourally identical - the bot loads only
`active = true` rows, and this inserts none - so the import is never a correctness step
and the migration is safe to apply without it.

WHAT IT WILL NOT DO. It will not activate anything, it will not overwrite an existing
spec (they are immutable by design - a revision is a new row), and it will not invent a
directory. A spec whose name matches no catalogue row is REPORTED, not created: the
mismatch is the useful output, because it means the spec was written against a directory
we do not actually track.

    python -m app.cli.citation_specs_import              # dry run - prints the plan
    python -m app.cli.citation_specs_import --apply      # insert the inactive rows
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field
from typing import Any

from app.config import get_settings
from app.db.database import build_admin_pool, clear_pools, privileged_connection, set_pools
from integrations.citation_bot import FORM_SPECS


@dataclass
class ImportPlan:
    """What the import would do, before it does any of it."""

    insertable: list[tuple[str, str]] = field(default_factory=list)  # (directory, url)
    already_present: list[str] = field(default_factory=list)
    no_such_directory: list[str] = field(default_factory=list)
    host_mismatch: list[tuple[str, str, str]] = field(default_factory=list)


def _spec_payload(name: str) -> dict[str, Any]:
    spec = FORM_SPECS[name]
    return {
        "url": spec.url,
        "fields": [{"selector": f.selector, "value_key": f.value_key} for f in spec.fields],
        "submit_selector": spec.submit_selector,
        "success_indicator": spec.success_indicator,
        **(
            {
                "captcha": {
                    "kind": spec.captcha.kind,
                    "site_key_selector": spec.captcha.site_key_selector,
                    "response_field_name": spec.captcha.response_field_name,
                }
            }
            if spec.captcha is not None
            else {}
        ),
    }


def build_plan() -> ImportPlan:
    """Work out what can be imported, WITHOUT writing anything.

    The host-mismatch bucket is the interesting one. 0111 binds a spec's URL to its own
    directory's host, because that URL is a browser navigation target. A spec that fails
    that check is not a schema problem - it is a spec pointing somewhere the directory
    does not live, which is exactly the kind of rot the probe found (three of the fifty
    point at directories that have since been acquired, renamed or absorbed)."""
    plan = ImportPlan()
    with privileged_connection() as cur:
        cur.execute("select id, name, url from public.directories")
        catalogue = {str(r["name"]): (str(r["id"]), str(r["url"] or "")) for r in cur.fetchall()}
        cur.execute(
            "select d.name from public.directory_specs s "
            "join public.directories d on d.id = s.directory_id"
        )
        have = {str(r["name"]) for r in cur.fetchall()}

        for name in sorted(FORM_SPECS):
            if name not in catalogue:
                plan.no_such_directory.append(name)
                continue
            if name in have:
                plan.already_present.append(name)
                continue
            url = FORM_SPECS[name].url
            cur.execute(
                "select public._spec_host_of(%s) as spec_host, public._spec_host_of(%s) as dir_host",
                (url, catalogue[name][1]),
            )
            hosts = cur.fetchone() or {}
            spec_host = str(hosts.get("spec_host") or "")
            dir_host = str(hosts.get("dir_host") or "")
            if not dir_host or (spec_host != dir_host and not spec_host.endswith("." + dir_host)):
                plan.host_mismatch.append((name, spec_host, dir_host))
                continue
            plan.insertable.append((name, url))
    return plan


def apply_plan(plan: ImportPlan) -> int:
    """Insert the importable specs as INACTIVE rows. Returns how many landed."""
    inserted = 0
    with privileged_connection() as cur:
        for name, _url in plan.insertable:
            cur.execute("select id from public.directories where name = %s limit 1", (name,))
            row = cur.fetchone()
            if row is None:  # pragma: no cover - raced with a catalogue edit
                continue
            import json as _json

            cur.execute(
                "insert into public.directory_specs (directory_id, spec) values (%s, %s::jsonb)",
                (row["id"], _json.dumps(_spec_payload(name))),
            )
            inserted += 1
    return inserted


def _report(plan: ImportPlan, *, applied: int | None) -> None:
    print(f"\n{len(FORM_SPECS)} in-code specs considered.\n")
    print(f"  importable (as INACTIVE)      : {len(plan.insertable)}")
    print(f"  already in the whitelist       : {len(plan.already_present)}")
    print(f"  no matching catalogue directory: {len(plan.no_such_directory)}")
    print(f"  spec url is not on the directory's own host: {len(plan.host_mismatch)}")
    if plan.host_mismatch:
        print(
            "\n  These are NOT schema failures - the spec points somewhere the directory\n"
            "  does not live. Three of the fifty are known to have been acquired, renamed\n"
            "  or absorbed since they were written.\n"
        )
        for name, spec_host, dir_host in plan.host_mismatch:
            print(f"    {name:32} spec={spec_host or '?':28} directory={dir_host or '?'}")
    if plan.no_such_directory:
        print("\n  Specs with no catalogue row (the spec names a directory we do not track):")
        for name in plan.no_such_directory:
            print(f"    {name}")
    if applied is None:
        print(
            f"\nDRY RUN - nothing was written. Re-run with --apply to insert "
            f"{len(plan.insertable)} INACTIVE rows.\n"
            "Nothing becomes submittable: the bot loads only active specs, and a spec\n"
            "activates only after a dated human DOM check AND one submission that\n"
            "produced a public listing URL.\n"
        )
    else:
        print(f"\nInserted {applied} inactive spec(s). None is active; none can submit yet.\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply", action="store_true",
        help="actually insert the rows (default is a dry run that writes nothing)",
    )
    args = parser.parse_args(argv)

    settings = get_settings()
    pool = build_admin_pool(settings.database_admin_url)
    if pool is None:
        print("ERROR: DATABASE_ADMIN_URL is not configured.", file=sys.stderr)
        return 2
    pool.open()  # the pool is built lazily; a CLI has no lifespan to open it
    set_pools(None, pool)
    try:
        plan = build_plan()
        applied = apply_plan(plan) if args.apply else None
        _report(plan, applied=applied)
    finally:
        clear_pools()
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
