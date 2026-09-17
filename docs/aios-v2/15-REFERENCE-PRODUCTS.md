# 15 · Reference Products

Two products named by the owner as inspiration. This file records **what was actually
verified** and **what was not**, because a specification built on a guess about a
competitor's feature list is a specification built on nothing.

---

## A · SoMePoster — someposter.ai

**Role:** the reference product for **M05 (Web 2.0 & Social Publishing)**.
**Verification:** marketing site fetched, pricing page fetched, and a logged-in dashboard
screenshot supplied by the owner (2026-09-16). **This is well-evidenced.**

### Verified in-app navigation
`Create Posts` · `Create Video Post` · `AI Studio` · `Parasite Poster` · `Automations` ·
`My Calendar` · `My Posts` · `Comments` · `Analytics` · `Company` · `Accounts Connectivity`

### Verified connection grid (32 platform cards, each `Connect` / `NOT LINKED`)
X (Twitter) · Facebook · LinkedIn Business · Instagram · Threads · Bluesky · Blogger ·
WordPress.com · TikTok · YouTube · LiveJournal · Mailchimp · Pinterest · GMB Profile ·
WordPress (Self-hosted) · Ghost · DEV.to · Telegram · Nostr · Mastodon · Webflow · Wix ·
Shopify · n8n · Make.com · Telegraph · Pastebin · Google Drive · Diigo · Micro.blog ·
Raindrop · Discord

Also advertised on the site: Slack; "coming soon" Notion and Directify. Free lead-magnet
tools: Instagram Grid Maker, Caption Analyzer, Text on Photos.

### Verified pricing
| Tier | Price | Limits |
|---|---|---|
| Starter | Free | 3 accounts · 10 posts/month · basic analytics |
| Pro | $19/mo | 15 accounts · unlimited posts · AI writing assistant · advanced analytics |
| Business | $49/mo | unlimited accounts · unlimited posts · team collaboration · white-label reports |

Add-on: extra X posts at $30 per 100. Fair-use policy per platform.

### What we take, and what we add
Fully specified in [`modules/M05-web2-and-social.md`](modules/M05-web2-and-social.md) §1.
In short: we copy the surface (connection grid, compose-once editor, calendar, AI studio,
Parasite Poster, analytics) and add what a single-workspace posting tool has no reason to
have — **multi-tenancy, per-client identity and ownership tiering, an anchor-text strategy,
internal linking, link-liveness monitoring, account-health gating, human-paced publishing,
and approval + cost gates.**

**"Parasite Poster" is the strategically important one.** It is publishing keyword-targeted
content onto high-authority third-party domains so the host's authority carries the page
into the SERP. That is precisely the SEO purpose of our Web 2.0 module, and M05 §6
specifies it with the guardrails a client-facing agency needs.

---

## B · SEOSignalX — seosignalx.com

**Role:** candidate inspiration for **M02 (Audit)**, **M08 (Keyword Research)** and
possibly a new GSC connector.
**Verification: INCOMPLETE.** The site is a client-rendered single-page application; a
fetch returns only the shell, and web search carries no feature breakdown. `\tools` and
`/gsc/` both returned the same empty shell.

### What is verifiable
| Claim | Source | Confidence |
|---|---|---|
| Positioning: **"Real-time SEO Crawl Intelligence"** | Site title, repeated across search results | High |
| **60+ SEO tools in a single architectural framework** | Search result summary of the homepage | Medium — the number is marketing copy, not a verified inventory |
| **Deep NLP and entity extraction** as a differentiator | Same | Medium |
| A **Google Search Console integration** exists at `/gsc/` with its own authenticated area | The URL exists and is indexed with a "Welcome back" title | High that it exists; nothing known about what it does |

### What this suggests, held as hypotheses not requirements

1. **Real-time crawl intelligence** — a crawler that streams findings as it goes rather than
   producing a report at the end. Our M02 already runs section analyzers in parallel with
   per-section degradation; streaming partial findings to the viewer as they land is a
   natural and cheap extension. *Worth doing regardless of what SEOSignalX does.*
2. **Entity/NLP extraction** — this is already `REQ-CNT-013` (the entity / must-mention set
   per cluster) and `REQ-KW-004` (semantic clustering). If SEOSignalX's differentiator is
   entity coverage scoring, our equivalent is the topical-coverage dimension of the QA
   scorecard, and it should be given real depth rather than treated as one score among nine.
3. **Google Search Console integration** — **this is a genuine gap.** Nothing in the current
   AIOS scope reads GSC. GSC gives impressions, clicks, average position and query data for
   pages we publish, which is the only *first-party* measurement of whether the content
   module is working. Every other ranking number we hold is third-party and sampled.

### Recommendation — one new decision needed

> **Add a Google Search Console connector to M07 (Tracking) as `REQ-RNK-008`, P1.**
>
> Rationale: it is free, first-party, requires only an OAuth scope the client already grants
> for GBP, and it turns "we published 50 pages" into "these 43 pages are getting
> impressions for these queries". It is the highest-value-per-hour item found in this
> review. It does **not** replace DataForSEO for rank position — GSC reports an average
> position, not a real one, which is exactly why v1's documents flagged the two as different
> sources. Both, labelled, never mixed (`REQ-RNK-001`).

Recorded as **ADR-021** in [`12-DECISIONS-ADR.md`](12-DECISIONS-ADR.md), pending owner
approval.

### What is still needed from the owner

To use SEOSignalX as a real reference rather than a vague one, supply the same thing that
made SoMePoster usable: **screenshots of the logged-in dashboard** — the tool list, one or
two tool screens, and the GSC area. Without that, anything written here about its 60 tools
would be invention, and this pack does not invent.
