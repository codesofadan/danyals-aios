"""Shared data layer for the REVISED access-requirements deliverables.

Revision, 12 Sep 2026, per Danyal:
  * The 6 "still needed" agency keys are NOT needed - dropped entirely.
  * DataForSEO IS needed from the client (we are funding it ourselves today).
  * A WORKING signup/verification email account is needed (the one just sent fails).
  * Anthropic is reached through AgentRouter -> label it "Anthropic / AgentRouter".
  * The platform has NO Google Business Profile, website-CMS, Analytics or
    Search Console module - those four per-client asks are removed.
  * Web 2.0 AND citations both run through the browser EXTENSION as the primary
    lane. Direct APIs exist but never reach 100%, so they are a fallback only.
"""
import json
import pathlib

SP = pathlib.Path(__file__).parent

WEB2 = json.loads((SP / "web2.json").read_text(encoding="utf-8"))
DIRS = json.loads((SP / "dirs.json").read_text(encoding="utf-8"))
INTEG = json.loads((SP / "integrations.json").read_text(encoding="utf-8"))

# ---------------------------------------------------------------- core APIs
# What we still need FROM the client.
NEEDED = [
    {
        "name": "DataForSEO",
        "area": "Rankings & keyword data",
        "key": "DATAFORSEO_LOGIN + DATAFORSEO_PASSWORD",
        "powers": "Map-pack grid probes (every numbered rank pin), keyword volumes, "
                  "backlink and referring-domain data",
        "why": "This is the one SEO data source that has never been supplied. We are "
               "paying for it out of our own account today, so every grid probe, "
               "keyword figure and backlink number in the platform is billed to us.",
        "without": "Grid rank tracking, keyword volumes and the backlink profile all "
                   "stop the moment our own credit runs out",
        "where": "dataforseo.com - one account, covers every client",
        "cost": "Paid, per API call",
    },
    {
        "name": "A working email account",
        "area": "Account signup & verification",
        "key": "IMAP host, user and password (plus SMTP to send)",
        "powers": "Creating and verifying every citation-directory and Web 2.0 account, "
                  "then reading back the confirmation link each platform emails",
        "why": "An email account was sent recently but it does not work - it will not "
               "authenticate, so no confirmation mail can be read and no new account "
               "can be activated. We need a working one: ideally a catch-all domain "
               "mailbox, or a Gmail with IMAP enabled and an app password.",
        "without": "No new directory or Web 2.0 account can be created or confirmed - "
                   "the whole extension lane stalls at signup",
        "where": "Any mailbox you control, with IMAP switched on",
        "cost": "Free",
    },
]

# Keys already installed and paid for on our side. Anthropic is proxied via AgentRouter.
INSTALLED = [
    ("Anthropic / AgentRouter", "AI / Content",
     "All content research and writing, and the AI form-fill that maps a value to the "
     "right field on a page it has never seen",
     "ANTHROPIC_API_KEY + ANTHROPIC_BASE_URL (AgentRouter proxy)"),
    ("Serper.dev", "Rankings",
     "Live Google SERP reads - rankings and the coordinates behind grid tracking",
     "SERPER_API_KEY"),
    ("Google APIs", "OAuth",
     "The Google OAuth client that Google platform logins run through, Blogger included",
     "GOOGLE_OAUTH_CLIENT_ID + GOOGLE_OAUTH_CLIENT_SECRET"),
    ("Image Generation", "AI / Content",
     "Images generated inside articles and Web 2.0 posts", "IMAGE_GEN_API_KEY"),
    ("Google Sheets", "Storage",
     "Service account behind the Sheets-backed stores", "GOOGLE_SHEETS_SA_JSON"),
    ("Resend", "Delivery",
     "Transactional email - reports and client notifications", "RESEND_API_KEY"),
    ("Foursquare", "Off-page",
     "Independent check that a citation actually went live", "FOURSQUARE_API_KEY"),
]

# Explicitly REMOVED from the ask, with the reason. This page exists because the
# previous revision asked for all of these.
REMOVED = [
    ("Google Business Profile access", "There is no GBP module in this platform. GBP is "
     "one citation target in the directory list, not a connected module."),
    ("Website / CMS login", "There is no website-CMS module. We do not make on-page "
     "changes to the client's own site from here."),
    ("Google Analytics", "No analytics module. No traffic data is read, stored or reported."),
    ("Search Console", "No Search Console module. Impressions and indexing state are not "
     "part of this platform."),
    ("Voyage Embeddings", "Not needed. Content is written without a semantic memory layer."),
    ("Pinecone", "Not needed - it only ever existed to hold those embeddings."),
    ("Slack webhook", "Not needed. Failures surface in the dashboard."),
    ("Bing Places API", "Not needed. Bing is covered as an ordinary directory in the "
     "citation list."),
    ("BrightLocal", "Not needed. Citation status is verified by fetching the live listing "
     "URL, not by a third-party subscription."),
    ("Backblaze B2", "Not needed from you - backups are ours to run."),
]


# --------------------------------------------------------------- web 2.0
def web2_rows():
    """Every Web 2.0 platform, extension-first, with what the operator needs."""
    out = []
    for p in WEB2["platforms"]:
        anon = p["authType"] == "anonymous"
        out.append({
            "name": p["name"],
            "authority": p["authorityTier"],
            "signup": p["signupUrl"] or "",
            "account": "No account (anonymous)" if anon else "Account needed",
            "api_fallback": "yes" if p["mechanism"] == "api" and p["automationReady"] else "no",
            "excluded": p["mechanism"] == "unsupported",
            "notes": p["notes"] or "",
        })
    out.sort(key=lambda r: (r["excluded"], {"high": 0, "medium": 1, "low": 2}[r["authority"]],
                            r["name"].lower()))
    return out


W2 = web2_rows()
W2_USE = [r for r in W2 if not r["excluded"]]
W2_EXCL = [r for r in W2 if r["excluded"]]
W2_ACCOUNT = [r for r in W2_USE if r["account"] == "Account needed"]
W2_API_FALLBACK = [r for r in W2_USE if r["api_fallback"] == "yes"]
W2_BY_AUTH = {t: [r for r in W2_USE if r["authority"] == t] for t in ("high", "medium", "low")}

# ------------------------------------------------------------- citations
_ACCESS_LABEL = {
    "open": "Account needed - open signup",
    "apply_gated": "Account needed - application reviewed",
    "aggregator": "No account - fed from a data partner",
}


def dir_rows():
    out = []
    for x in DIRS:
        out.append({
            "name": x["name"],
            "url": x["url"],
            "market": x["market"],
            "tier": x["authorityTier"],
            "account": _ACCESS_LABEL.get(x["access"], "Account needed"),
            "captcha": x["tier"] == "captcha_assisted",
            "manual": x["tier"] == "manual_only",
            "aggregator": x["access"] == "aggregator",
            "price": (x["priceNote"] or "").split("|")[0].strip() or "Free",
            "notes": x["automationNote"] or "",
            "verticals": ", ".join(x["verticals"]),
        })
    out.sort(key=lambda r: ({"core": 0, "tier1": 1, "tier2": 2}[r["tier"]], r["name"].lower()))
    return out


def host_of(u):
    u = (u or "").lower().replace("https://", "").replace("http://", "").rstrip("/")
    u = u.split("/")[0]
    return u[4:] if u.startswith("www.") else u


def dedupe_by_host(rows):
    """One sign-up per DOMAIN. The registry carries per-market rows (Brownbook, Brownbook
    (UK), Brownbook (Canada)) that all resolve to one account, so counting rows would
    overstate the work by a third."""
    seen, out = {}, []
    for r in rows:
        h = host_of(r["url"])
        if h in seen:
            seen[h]["also"].append(r["market"])
            continue
        r = dict(r, host=h, also=[r["market"]])
        seen[h] = r
        out.append(r)
    return out


CIT = dir_rows()
CIT_ACCOUNT = [r for r in CIT if not r["aggregator"]]
CIT_SIGNUPS = dedupe_by_host(CIT_ACCOUNT)
CIT_AGG = [r for r in CIT if r["aggregator"]]
CIT_BY_MARKET = {}
for _r in CIT:
    CIT_BY_MARKET.setdefault(_r["market"], []).append(_r)
CIT_BY_TIER = {t: [r for r in CIT if r["tier"] == t] for t in ("core", "tier1", "tier2")}

TOTALS = {
    "web2_total": len(W2),
    "web2_use": len(W2_USE),
    "web2_excluded": len(W2_EXCL),
    "web2_accounts": len(W2_ACCOUNT),
    "web2_api_fallback": len(W2_API_FALLBACK),
    "cit_total": len(CIT),
    "cit_accounts": len(CIT_ACCOUNT),
    "cit_signups": len(CIT_SIGNUPS),
    "cit_aggregator": len(CIT_AGG),
    "cit_captcha": sum(1 for r in CIT if r["captcha"]),
    "accounts_total": len(W2_ACCOUNT) + len(CIT_SIGNUPS),
    "needed_keys": len(NEEDED),
    "installed_keys": len(INSTALLED),
    "removed": len(REMOVED),
}

if __name__ == "__main__":
    for k, v in TOTALS.items():
        print(f"{k:22} {v}")
    print("markets", {k: len(v) for k, v in CIT_BY_MARKET.items()})
    print("web2 auth", {k: len(v) for k, v in W2_BY_AUTH.items()})
