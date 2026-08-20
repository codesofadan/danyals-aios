# AIOS — Platform & Credentials Provisioning Checklist

This is everything I need to build **Web 2.0 backlinks** and **citations** for a client.
Create the account, then hand me the **exact fields** listed (mostly API tokens, not
passwords). Legend: ✅ = fully automatable once you give me the credential · ⚠️ = works
but has a catch · 🔴 = needs a human step I can't automate.

---

# PART A — WEB 2.0 PLATFORMS (article backlinks)

For each, I publish through the platform's **API token / OAuth token**, not your login
password. Where to generate the token is noted. Give me the bracketed fields per platform.

### Ready-to-go (simple token) — do these first
| # | Platform | Sign up at | Give me | Where to get it |
|---|----------|-----------|---------|-----------------|
| 1 | **dev.to** ✅ | https://dev.to | `api_key` | Settings → Extensions → "Generate API Key" |
| 2 | **Mastodon** ✅ | https://mastodon.social (any instance) | `access_token` + `instance_url` | Preferences → Development → New application (scope: `write:statuses`) |
| 3 | **Mataroa** ✅ | https://mataroa.blog | `api_key` | Settings → API |
| 4 | **Write.as** ✅ | https://write.as | `token` + `alias` (blog subdomain) | Account → API / Tokens |
| 5 | **GitHub Pages** ✅ | https://github.com (+ a public repo) | `token` (PAT) + `owner` (username) + `repo` | Settings → Developer settings → Fine-grained PAT · Contents + Pages = Read/Write on that repo |
| 6 | **GitLab Pages** ⚠️ | https://gitlab.com (+ a project) | `token` (PAT, `api` scope) + `project_id` | Settings → Access Tokens · **also needs a Pages CI job** (I'll add the `.gitlab-ci.yml`) |
| 7 | **Micro.blog** ⚠️ | https://micro.blog (~$5/mo paid) | `token` | Account → App tokens (endpoint was flaky; I'll patch format) |

### Need an OAuth app registered (a bit more setup)
| # | Platform | Sign up at | Give me | Where to get it |
|---|----------|-----------|---------|-----------------|
| 8 | **WordPress.com** ✅ | https://wordpress.com | `oauth_token` + `site` (yourblog.wordpress.com) | Register app at https://developer.wordpress.com/apps → OAuth user token |
| 9 | **Blogger** ✅ | Google account → https://blogger.com | `oauth_token` + `blog_id` | Google Cloud Console → enable Blogger API → OAuth token |
| 10 | **Tumblr** ✅ | https://tumblr.com | `oauth_token` + `blog` (yourblog.tumblr.com) | Register app at https://www.tumblr.com/oauth/apps |
| 11 | **Ghost** ✅ | a Ghost site (ghost.io or self-host) | `admin_api_key` + `api_url` | Ghost Admin → Settings → Integrations → Custom integration |
| 12 | **Hashnode** ✅ | https://hashnode.com (+ create publication) | `pat` + `publication_id` | Settings → Developer → Personal Access Token |
| 13 | **Hatena Blog** ✅ | https://www.hatena.ne.jp (Japanese) | `hatena_id` + `blog_id` + `api_key` | Account → AtomPub API key |

### Username + password (no token)
| # | Platform | Sign up at | Give me | Notes |
|---|----------|-----------|---------|-------|
| 14 | **LiveJournal** ✅ | https://www.livejournal.com | `username` + `password` | Signup has a reCAPTCHA (you create it) |
| 15 | **Dreamwidth** ✅ | https://www.dreamwidth.org | `username` + `password` | **Needs an invite code** to register |

### Excluded (don't bother)
- 🔴 **Telegra.ph** — anonymous, no account needed, BUT **network-blocked on your machine** (regional). Only works from a different network/VPN.
- 🔴 **Medium** — its publish API is retired. Nothing brings it back.

> With tokens for **~10 of the above**, I get you **10 real articles on 10 distinct platforms**, fully automated (same pipeline that already published 11).

---

# PART B — CITATIONS (local business listings)

**Important:** for citations, a login alone often isn't enough — many directories block
automation (Cloudflare captcha), moved/removed their submit forms, or gate behind a
credit card. So citations split into three tiers by how well they actually work.

## B1 — Aggregators (BEST ROI — one account pushes to dozens) ✅ recommended
One paid subscription distributes NAP to many directories cleanly, with real listing URLs.
This is what the pipeline was designed to ride and avoids per-directory captcha fights.
| Service | Sign up at | Give me |
|---|---|---|
| **Yext** | https://www.yext.com | account API key / login |
| **BrightLocal Citation Builder** | https://www.brightlocal.com | account login (they do the manual submits) |
| **Uberall / Whitespark / Moz Local** | respective sites | account login / API key |
| **Bing Places API** | https://www.bingplaces.com | `bing_places_api_key` (Microsoft account) |

## B2 — Major / high-authority platforms (do these per client) ⚠️/🔴
These carry the most SEO weight but usually require the **client's real business identity +
verification** (phone code, postcard, or video) that I can't complete for you.
| Platform | Sign up at | Give me | Catch |
|---|---|---|---|
| **Google Business Profile** 🔴 | https://www.google.com/business | account login | Verification (phone/video/postcard) is human + anti-bot |
| **Bing Places** ⚠️ | https://www.bingplaces.com | login or API key | Can import from Google; API is automatable |
| **Apple Business Connect** 🔴 | https://businessconnect.apple.com | Apple ID login | Apple verification |
| **Facebook Page** ⚠️ | https://facebook.com/pages/create | page access token | Needs the client's FB |
| **Yelp for Business** ⚠️ | https://biz.yelp.com | login | Claim/verify flow |
| **Foursquare / Swarm** ⚠️ | https://foursquare.com | login / API | Their public submit API returned 410 (deprecated) |

## B3 — Free directory catalog (50 in the system)
An account per directory helps (removes signup), but **I still have to rebuild each form's
selectors against its current page**, and many are captcha-blocked or dead. Give me logins
only for the ones you want me to pursue; I'll report which actually accept a submission.
US · UK · CA · AU grouped below. (Status from my live scan: many need per-site work.)

**US:** Brownbook · MerchantCircle · Chamber of Commerce · Hotfrog · EZLocal · ShowMeLocal · Cylex USA · CitySquares · Callupcontact · Cybo · Storeboard · YaSabe · Superpages (Thryv) · Tupalo · YellowBot · Judy's Book · Infobel · EnrollBusiness · MyHuckleberry · n49 · Opendi · Tuugo · Apsense · Yellow.place · AGreaterTown · FindIt · Justia (lawyers) · Houzz · MenuPix · Wellness.com
**UK:** Thomson Local · FreeIndex · Scoot · Cylex UK · 192.com · Hotfrog UK · Applegate
**CA:** 411.ca · Ourbis · ProfileCanada · Weblocal.ca · Cylex Canada · Canadian Business Directory
**AU:** True Local · StartLocal · Aussie Web · Local.com.au · White Pages AU · Cylex AU · Local Search

Full URLs for all 50 are in `backend/integrations/citation_bot.py` (`FORM_SPECS`) — I can export them as a spreadsheet if useful.

---

# HOW TO HAND ME THE CREDENTIALS
Per platform, give me a line like:
```
dev.to        api_key=xxxxxxxx
Mastodon      access_token=xxxx  instance_url=https://mastodon.social
GitHub Pages  token=ghp_xxxx  owner=youraccount  repo=web2
```
I load them into the encrypted per-client vault (AES-GCM) and publish. **Treat these as
secrets** — anyone with them can post as that account; rotate any you consider sensitive
after we're done.

---

# WHAT ALSO NEEDS FIXING (so the dashboard flow works, not just my scripts)
1. **Apply the missing DB migrations** (local DB is behind the code) — needs your local
   **PostgreSQL 16 `postgres` superuser password** (the one in root `.env` is for the
   Docker stack and doesn't match your native install). Without it the dashboard's own
   web2 *plan → AI-draft* flow stays broken locally.
2. **Slug-collision bug** in the web2 pipeline (`slug = title or anchor`) — fix so multiple
   properties per platform don't collide.
3. **A real client site** — the test client "Atlas Legal" uses a placeholder domain, so
   the backlinks point nowhere. Real clients need a real `targetUrl`.
