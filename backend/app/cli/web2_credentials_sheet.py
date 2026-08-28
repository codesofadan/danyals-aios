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
from integrations.web2_credentials import build_publisher
from integrations.web2_publishers import PLATFORM_CREDENTIAL_FIELDS

STATUS_CONNECTED = "CONNECTED"
STATUS_INCOMPLETE = "INCOMPLETE"
STATUS_MISSING = "NOT CONNECTED"
#: Needs no human credential at all - a command provisions it. Distinguished from
#: NOT CONNECTED so nobody is assigned an errand that has nothing to fetch.
STATUS_AUTO = "AUTO - run the command"


@dataclass(frozen=True)
class Guide:
    """How a human actually obtains this platform's credential.

    Researched against each platform's own documentation. `cost` and `blocker` are the
    fields that decide whether a task is worth assigning at all - a teammate sent to
    fetch a token that turns out to need a paid plan, or that expires in seven days,
    has been sent on an errand nobody costed.
    """

    where: str
    steps: str
    cost: str = "Free"
    blocker: str = ""
    account_needed: str = "One account per CLIENT"
    fields_note: str = ""


# --------------------------------------------------------------------------- #
# The acquisition guide. Verified against each platform's own docs, 2026-08-27.
# --------------------------------------------------------------------------- #
GUIDES: dict[str, Guide] = {
    "WordPress.com": Guide(
        where="https://developer.wordpress.com/apps/",
        steps=(
            "1) Create an application (any title; set a Redirect URL you control). "
            "2) Note the client_id + client_secret. "
            "3) Run the OAuth2 authorize flow SIGNED IN AS THE CLIENT'S WordPress.com "
            "account, approving the target blog. "
            "4) Exchange the code for an access_token. "
            "5) Give us: oauth_token + site (the blog's slug, e.g. clientname.wordpress.com)."
        ),
        blocker=(
            "The token is minted for the account that approves it, so the CLIENT (or you "
            "acting on a blog you created for them) must complete the consent step - the "
            "app credentials alone cannot post."
        ),
    ),
    "Blogger": Guide(
        where="https://console.cloud.google.com/ (Blogger API v3) + https://www.blogger.com/",
        steps=(
            "1) Google Cloud project -> enable 'Blogger API v3'. "
            "2) OAuth consent screen -> add scope https://www.googleapis.com/auth/blogger. "
            "3) Create an OAuth client (Desktop or Web). "
            "4) Run the consent flow as the account that owns the blog; keep the REFRESH "
            "token. "
            "5) Give us: oauth_token + blog_id (the long number in the Blogger dashboard URL)."
        ),
        blocker=(
            "THE BIG ONE. While the consent screen is in 'Testing', Google expires the "
            "refresh token after 7 DAYS - publishing silently dies every week. Moving the "
            "app to 'Production' requires Google verification. Budget for that review, or "
            "accept re-authorising every client weekly. We hold app client_id/secret "
            "already; what is missing is a per-blog token."
        ),
    ),
    "Tumblr": Guide(
        where="https://www.tumblr.com/oauth/apps",
        steps=(
            "1) Register an application (a valid OAuth2 redirect URL is required). "
            "2) Note consumer key + secret. "
            "3) Authorise as the client's Tumblr account with scopes: basic write "
            "offline_access. "
            "4) Give us: oauth_token + blog (e.g. clientblog.tumblr.com)."
        ),
        blocker=(
            "Request 'offline_access' or the token cannot be refreshed and posting stops "
            "when it expires. Tumblr's API License also requires a per-post human action, "
            "which our approval step already satisfies."
        ),
    ),
    "dev.to": Guide(
        where="https://dev.to/settings/extensions",
        steps="Settings -> Extensions -> 'DEV Community API Keys' -> generate. Give us: api_key.",
        blocker=(
            "Links are nofollow and dev.to's rules forbid off-topic promotional posts - "
            "only genuinely developer-audience clients belong here."
        ),
    ),
    "Hashnode": Guide(
        where="https://hashnode.com/settings/developer",
        steps=(
            "1) Settings -> Developer -> generate a Personal Access Token. "
            "2) Take the publication id from the dashboard URL "
            "(hashnode.com/dashboards/<PUBLICATION_ID>/general). "
            "3) Give us: pat + publication_id."
        ),
        cost="PAID - Hashnode Pro, $5 per seat / month",
        blocker=(
            "As of 13 May 2026 BOTH read and publish access to Hashnode's GraphQL API "
            "require a Pro subscription. A token issued on a free account will be rejected. "
            "Do not assign this until someone decides to pay."
        ),
    ),
    "GitHub Pages": Guide(
        where="https://github.com/settings/personal-access-tokens",
        steps=(
            "1) Create a fine-grained PAT scoped to the client's repo with Contents: "
            "Read+Write and Pages: Read+Write. "
            "2) Create the repo and enable Pages if it does not exist. "
            "3) Give us: token + owner + repo."
        ),
        blocker="We hold a token already; owner + repo are missing, so nothing can publish yet.",
    ),
    "GitLab Pages": Guide(
        where="https://gitlab.com/-/user_settings/personal_access_tokens",
        steps=(
            "1) Create a PAT with the 'api' scope. "
            "2) Take the numeric Project ID from the project's home page. "
            "3) Give us: token + project_id."
        ),
        blocker=(
            "Pages only appear after CI runs, so a placement is not live the instant the "
            "API accepts it. We hold a token; project_id is missing."
        ),
    ),
    "GitHub Gist": Guide(
        where="https://github.com/settings/personal-access-tokens",
        steps="Create a token with Gists: Read+Write. Give us: token.",
        blocker="Gist links are nofollow - useful for reach, not for link equity.",
    ),
    "GitLab Snippets": Guide(
        where="https://gitlab.com/-/user_settings/personal_access_tokens",
        steps="Create a PAT with the 'api' scope. Give us: token.",
        blocker="Snippet links are nofollow.",
    ),
    "HackMD": Guide(
        where="https://hackmd.io/settings#api",
        steps="Settings -> API -> create an API token. Give us: token.",
    ),
    "Netlify": Guide(
        where="https://app.netlify.com/user/applications#personal-access-tokens",
        steps=(
            "1) User settings -> Applications -> New access token. "
            "2) Create the site (or take an existing one) and copy its Site ID from "
            "Site configuration. "
            "3) Give us: token + site_id."
        ),
    ),
    "Neocities": Guide(
        where="https://neocities.org/settings",
        steps=(
            "1) Create the site (free tier is fine: 1 GB, 200 GB/month). "
            "2) Settings -> Manage Site Settings -> API key. "
            "3) Give us: api_key."
        ),
    ),
    "Codeberg Pages": Guide(
        where="https://codeberg.org/user/settings/applications",
        steps=(
            "1) Settings -> Applications -> Generate a token with repository write access. "
            "2) Create the 'pages' repo for the client. "
            "3) Give us: token + owner + repo."
        ),
    ),
    "Sourcehut Pages": Guide(
        where="https://meta.sr.ht/oauth2",
        steps="Generate a personal access token. Give us: token + the site domain.",
        cost="Free during the public alpha for basic publishing",
        blocker=(
            "Publishing via the BUILD system needs a paid sourcehut account; the direct "
            "tarball upload we use does not. Treat the free path as alpha-grade."
        ),
    ),
    "Zenodo": Guide(
        where="https://zenodo.org/account/settings/applications/tokens/new/",
        steps="Create a personal access token with deposit:write (and deposit:actions). Give us: access_token.",
        blocker=(
            "A Zenodo record is a permanent, citable research artefact with a DOI - it "
            "cannot be quietly deleted later. Only use it for clients with genuine "
            "research or data output."
        ),
        account_needed="One account per CLIENT (or the client's institution)",
    ),
    "OSF": Guide(
        where="https://osf.io/settings/tokens",
        steps="Settings -> Personal access tokens -> create with osf.full_write. Give us: token.",
        blocker="Academic-integrity norms apply; only for genuinely research-adjacent clients.",
    ),
    "Figshare": Guide(
        where="https://figshare.com/account/applications",
        steps="Account -> Applications -> Create personal token. Give us: token.",
        blocker="As with Zenodo: a published item is permanent and citable.",
    ),
    "Telegra.ph": Guide(
        where="(nothing to fetch)",
        steps=(
            "Nothing to fetch. Run: python -m app.cli.web2_signup --platforms 'Telegra.ph' "
            "then register the printed credential with app.cli.web2_accounts."
        ),
        cost="Free",
        account_needed="Agency HOUSE account (already provisioned)",
        blocker="Zero identity means low trust and low link value. Use it for reach, not authority.",
    ),
}

#: Platforms whose credential we already hold but which the catalogue has tiered
#: `do_not_use`. Kept in the sheet - with the reason - because "we have a token for it"
#: is exactly the fact that makes someone assume it is usable.
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
