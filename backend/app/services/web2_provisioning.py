"""How a human actually obtains each platform's publishing credential.

WHY THIS IS A SERVICE AND NOT CLI DATA. These guides were researched against each
platform's own documentation, and they answer the question that actually blocks a
campaign: "this platform says NOT CONNECTED - what do I do about it?" That question is
asked by an operator looking at the board in the portal, not by an engineer running a CLI.
Leaving the answer inside a command-line script made provisioning an engineer's errand,
which is precisely why a client can sit at zero connected platforms indefinitely.

The CSV export and the portal both read from here, so a guide corrected in one place is
corrected everywhere - a second hand-maintained copy would drift, and a teammate would be
sent to fetch a token on terms that changed months ago.
"""

from __future__ import annotations

from dataclasses import dataclass


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
            "3) Give us: api_token + site_id."
        ),
    ),
    "Neocities": Guide(
        where="https://neocities.org/settings",
        steps=(
            "1) Create the site (free tier is fine: 1 GB, 200 GB/month). "
            "2) Settings -> Manage Site Settings -> API key. "
            "3) Give us BOTH: api_key AND sitename (the subdomain you chose, "
            "e.g. 'acme' for acme.neocities.org)."
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
        steps=(
            "Settings -> Personal access tokens -> create with osf.full_write. "
            "Give us: access_token."
        ),
        blocker="Academic-integrity norms apply; only for genuinely research-adjacent clients.",
    ),
    "Figshare": Guide(
        where="https://figshare.com/account/applications",
        steps="Account -> Applications -> Create personal token. Give us: access_token.",
        blocker="As with Zenodo: a published item is permanent and citable.",
    ),
    "Telegra.ph": Guide(
        where="(nothing to fetch)",
        steps=(
            "Nothing to fetch. Run: python -m app.cli.web2_signup --platforms 'Telegra.ph' "
            "; it mints an anonymous access_token, which is the whole credential. Register that access_token with app.cli.web2_accounts."
        ),
        cost="Free",
        account_needed="Agency HOUSE account (already provisioned)",
        blocker="Zero identity means low trust and low link value. Use it for reach, not authority.",
    ),
}

#: Platforms whose credential we already hold but which the catalogue has tiered
#: `do_not_use`. Kept in the sheet - with the reason - because "we have a token for it"
#: is exactly the fact that makes someone assume it is usable.
