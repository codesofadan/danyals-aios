"""Auto-create HOUSE Web 2.0 accounts (API signup) and print a credential block.

The web2 publish pipeline reads a per-client vault row per (client, platform); those
rows are fanned out from the agency's HOUSE accounts by ``app.cli.seed_web2_vault``.
This CLI creates the house accounts for the platforms that expose a real, no-browser
signup/token API (Telegra.ph's anonymous ``createAccount``, Write.as/WriteFreely's
``/api/auth/signup``) and prints the resulting ``WEB2_HOUSE_CREDENTIALS_JSON`` block --
so an operator can paste it into the env (or a ``--file``) and then run
``seed_web2_vault`` to seal every client's rows.

It NEVER writes a secret to disk or to the repo -- it prints the block to stdout for the
operator to place in the secret store. The catch-all mailbox
(``imap_mailbox_from_settings`` + ``CITATION_MAIL_DOMAIN``) is used for the optional
email-verify step; degrade-safe when unset. The browser-signup platforms
(LiveJournal/Dreamwidth/...) are NOT handled here -- they run through the Playwright
``BrowserSignupProvider`` in a worker, not a one-shot CLI.

    python -m app.cli.web2_signup                       # Telegra.ph + Write.as -> JSON block
    python -m app.cli.web2_signup --platforms "Telegra.ph"
"""

from __future__ import annotations

import argparse
import json
import sys

from app.config import get_settings
from integrations.imap_mailbox import imap_mailbox_from_settings
from integrations.web2_publishers import PLATFORM_TELEGRAPH, PLATFORM_WRITEAS
from integrations.web2_signup import (
    Web2SignupResult,
    api_signup_provider_for,
    house_credentials_block,
    make_context,
)

# The platforms this CLI can create a house account for without a browser.
_API_SIGNUP_PLATFORMS = (PLATFORM_TELEGRAPH, PLATFORM_WRITEAS)
_HOUSE_CLIENT = "house"  # the alias axis for a shared house account (not a real client id)


def _run(platforms: list[str], catchall_domain: str) -> list[Web2SignupResult]:
    settings = get_settings()
    mailbox = imap_mailbox_from_settings(settings)
    results: list[Web2SignupResult] = []
    for platform in platforms:
        provider = api_signup_provider_for(platform)
        if provider is None:
            print(f"skip {platform}: no API signup (browser/manual only)", file=sys.stderr)
            continue
        ctx = make_context(
            platform=platform, client_id=_HOUSE_CLIENT, catchall_domain=catchall_domain, mailbox=mailbox
        )
        result = provider.signup(ctx)
        marker = "OK" if result.status == "created" else result.status.upper()
        print(f"{marker:<8}{platform:<14}{result.error}", file=sys.stderr)
        results.append(result)
    return results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Create HOUSE web2 accounts via API signup and print a "
        "WEB2_HOUSE_CREDENTIALS_JSON block (paste it into the env, then run seed_web2_vault)."
    )
    parser.add_argument(
        "--platforms",
        help=f"comma-separated (default: {', '.join(_API_SIGNUP_PLATFORMS)})",
    )
    args = parser.parse_args(argv)

    if args.platforms:
        platforms = [p.strip() for p in args.platforms.split(",") if p.strip()]
    else:
        platforms = list(_API_SIGNUP_PLATFORMS)

    catchall = get_settings().citation_mail_domain or "mail.example.com"
    results = _run(platforms, catchall)
    block = house_credentials_block(results)
    if not block:
        print("no house accounts created (see the log above).", file=sys.stderr)
        return 1
    print(json.dumps(block, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
