# M05 · Web 2.0 & Social Publishing

Requirements: `REQ-W2-001` … `REQ-W2-017`.

**Reference product: [someposter.ai](https://someposter.ai) (SoMePoster).** Its surface is
the model for this module — the connection grid, the compose-once/publish-everywhere
editor, the calendar, the AI studio, the analytics roll-up and "Parasite Poster". We rebuild
that surface **multi-tenant**, and add the spine it does not have: per-client identity,
an anchor-text strategy, internal linking, link-liveness monitoring and account-health
gating.

---

## 1. What we are reverse-engineering, and what we add

### SoMePoster's shape (the parts worth copying)

| Surface | What it does | We build it |
|---|---|---|
| **Accounts Connectivity** | A grid of ~32 platform cards, each `Connect` / `NOT LINKED`, with a connected-accounts counter | Yes — but **per client**, with ownership tier and health on every card |
| **Create Posts** | One composer; toggle target accounts; platform-aware character limits and image ratios; hashtags, links, media | Yes |
| **Create Video Post** | Upload once → TikTok, Reels, YouTube, Facebook | Yes, P1 |
| **AI Studio** | Caption generation, hooks, platform-specific tone and length, emoji and hashtag suggestions | Yes — but sourced from the M03 pipeline so posts inherit client voice and the keyword bank |
| **Parasite Poster** | Publishing keyword-targeted content onto high-authority third-party domains | **Yes — this is the SEO core of the module** (§6) |
| **Automations** | Rules that publish without a human each time | Yes, gated: a campaign must be approved before automation runs |
| **My Calendar** | Cross-platform schedule, drag to reschedule | Yes |
| **My Posts** | The ledger of what went out, where, and its state | Yes |
| **Comments** | Inbound comment/mention management | P2 |
| **Analytics** | Unified cross-platform performance | Yes, P1, with provenance |
| **Company** | Workspace/brand settings | Becomes **Client** — the tenant |
| Free tools (grid maker, caption analyzer, text-on-photos) | Lead magnets | Out of scope |

### What SoMePoster does not do, and we must

| Gap | Why it matters here |
|---|---|
| **Multi-tenancy** | It is one workspace with one set of accounts. We run 50–100 clients, each with their own identities, sealed from each other |
| **Ownership tiering** | Shared house accounts across clients are a shared ban domain. We tier per-client vs house (§4) |
| **Anchor-text strategy** | A posting tool does not care where links point. A link-building system does — distribution caps, target rotation, naked/branded/exact mix |
| **Internal linking** | Multi-post properties need post-to-post links to read as real properties, not link dumps |
| **Link liveness** | A link that was published is not a link that still exists. We re-check |
| **Account health gating** | Keep publishing to a limited account and you lose it. We stop |
| **Human-paced publishing** | Ten properties posting in the same minute is a footprint |
| **Cost and approval gates** | Agency spend and client-blast-radius controls |

---

## 2. Platform matrix

`REQ-W2-001`. 32 platforms in v2.0, matching the connection grid, each a row in `platforms`.

**Every field must be measured or read from the platform's own documentation and dated.
Nothing in this table is assumed at runtime** — `link_policy` in particular is verified by
publishing a test post and reading the rendered anchor, because platforms change it.

| Platform | Category | Auth | API | Content | Ownership |
|---|---|---|---|---|---|
| X (Twitter) | social | OAuth 2.0 PKCE | API v2 (paid tier) | short + media | per-client |
| Facebook (Page) | social | OAuth, page token | Graph API | post + media | per-client |
| Instagram | social | OAuth via FB Page | Graph Content Publishing | image/reel + caption | per-client |
| LinkedIn Business | social | OAuth 2.0 | Share/Posts API (org) | post + media | per-client |
| Threads | social | OAuth | Threads API | short + media | per-client |
| Bluesky | social | app password / OAuth | AT Protocol | short + media | per-client |
| Mastodon | social | per-instance OAuth | REST | short + media | per-client |
| Nostr | social | keypair (nsec) | NIP-01 signed events | short | house allowed |
| TikTok | video | OAuth | Content Posting API | video | per-client |
| YouTube | video | OAuth | Data API v3 | video | per-client |
| Pinterest | social | OAuth | API v5 | pin + link | per-client |
| **Blogger** | blog | Google OAuth | Blogger API v3 | full HTML post | **per-client** |
| **WordPress.com** | blog | OAuth 2.0 | WP.com REST | full HTML post | **per-client** |
| **WordPress (self-hosted)** | blog | application password | WP REST v2 | full HTML post | **per-client** |
| **Ghost** | blog | Admin API key → JWT | Admin API | full HTML post | **per-client** |
| **DEV.to** | blog | API key | Articles API | markdown | per-client |
| **Micro.blog** | blog | token | Micropub | short/long post | per-client |
| **LiveJournal** | blog | XML-RPC | legacy | full post | house allowed |
| **Telegraph** | blog | open (`createAccount`) | Telegraph API | full post | **house** |
| Medium | blog | — | **API withdrawn** | — | `unsupported` |
| Webflow | site | OAuth / site token | CMS API v2 | CMS item | per-client |
| Wix | site | OAuth app | Blog API | post | per-client |
| Shopify | site | Admin access token | Admin API (articles) | blog article | per-client |
| GMB Profile | local | Google OAuth | Business Profile API | local post | per-client (→ M10) |
| Mailchimp | email | OAuth / API key | Marketing API | campaign | per-client |
| Telegram | messaging | bot token | Bot API | channel message | per-client |
| Discord | messaging | webhook / bot | webhook | channel message | per-client |
| Slack | messaging | incoming webhook | Web API | channel message | per-client |
| Pastebin | paste | api dev key | Pastebin API | plain text | house |
| Google Drive | storage | Google OAuth | Drive API | document | per-client |
| Diigo | bookmark | api key + basic | API v2 | bookmark | house allowed |
| Raindrop | bookmark | OAuth / token | REST | bookmark | house allowed |
| n8n | bridge | webhook | outbound | payload | agency |
| Make.com | bridge | webhook | outbound | payload | agency |

`REQ-W2-002`: **official APIs only.** A platform with no usable API is `unsupported` and is
never browser-automated. Medium is the worked example — its publishing API was withdrawn, so
it is out, not scripted.

`REQ-W2-015`: n8n and Make.com are **outbound destinations** — we fire a webhook with the
post payload so the operator can extend the system. Neither is ever a dependency in a
publishing path.

---

## 3. Data

Schema in [`04-DATA-MODEL.md`](../04-DATA-MODEL.md) §4. The load-bearing constraints:

- `web2_accounts.ownership = 'house'` **requires** `client_id IS NULL` and counts against a
  per-account property cap. `ownership = 'per_client'` **requires** a `client_id` and is
  sealed to that client's vault.
- `web2_posts.idempotency_key` is unique. Re-running a publish job cannot double-post — which
  on a social platform is not a cosmetic bug, it is a spam signal.
- `placed_links.state` ∈ `live | removed | nofollowed | unknown`, each set from a fetch,
  never assumed.

---

## 4. Account ownership — tiered

`REQ-W2-003`.

**Per-client identity** on every platform where a ban costs something or the property should
carry the client's brand: WordPress.com, Blogger, Tumblr, Ghost, Hashnode, DEV.to,
Micro.blog, GitHub/GitLab Pages, and every social network.

**House accounts** permitted only on anonymous or throwaway tiers: Telegra.ph, Pastebin,
low-stakes Fediverse instances, bookmarking services — each with a **hard cap on properties
per house account** (`REQ-W2-003`), because a platform that can link 40 unrelated local
businesses to one account has been handed the exact pattern it polices.

**Provisioning happens at campaign start, not at onboarding** — roughly 10–15 minutes of
staff OAuth per client per campaign, and only for clients actually running a campaign
(`REQ-W2-004`). A client not on a campaign must see no Web 2.0 surface in their portal.

---

## 5. Campaign flow

```
  campaign: client + platforms + target pages + budget
    └── provision identities        (staff OAuth, per platform, at campaign start)
    └── LangGraph: campaign_content
          ├── pull target pages + keyword bank + client voice from M03
          ├── per platform: shape the post to that platform's content model
          │     (length, media rules, markdown vs HTML, tag model, SEO fields)
          ├── images: generated or selected, sized per platform, alt text
          ├── SEO fields: title, slug, meta description, canonical, tags, OG/Twitter
          ├── internal links: post→post within multi-post properties
          └── outbound link: anchor drawn from the anchor bank under its distribution cap
    └── MANAGER APPROVES the plan and the first post per platform     ← REQ-W2-014
    └── pacing engine schedules
    └── publish via official API, idempotent, per-platform rate-limited
    └── link liveness + account health monitoring
```

### Content rules
`REQ-W2-006`: every post is produced by the M03 pipeline in a **platform-shaped variant**.
Never spun, never duplicated across properties. Two properties carrying the same body is the
footprint the whole exercise exists to avoid.

`REQ-W2-007`/`008`/`009`: images on every post that supports them; SEO fields wherever the
platform has them; post-to-post internal links on multi-post properties.

### Anchors
`REQ-W2-010`. An anchor bank per client with a distribution policy — branded / naked /
partial-match / exact-match shares, with a hard cap on exact-match. Anchors are assigned at
plan time and the distribution is enforced then, not audited afterwards. The bank tracks
`used_count` against `cap` per anchor.

### Pacing
`REQ-W2-011`. Human-plausible intervals, per-platform daily caps, jitter, and a global rule
that no two properties publish in the same minute. The pacing engine is a scheduler over the
job queue, so a paused campaign stops cleanly and a resumed one does not burst.

### Health
`REQ-W2-013`. Per-account state (`active` / `limited` / `suspended`), publish success rate,
and an **eligibility gate** that removes a degrading account from scheduling before it is
lost. A suspended account raises a task; it does not silently drop posts.

`REQ-W2-012`. Link liveness re-checks every placed link on a schedule; a removed or
newly-nofollowed link raises a task and updates the client-facing report.

---

## 6. Parasite Poster

SoMePoster's headline SEO feature, and the reason this module exists for an SEO agency.

**What it is:** publishing keyword-targeted content onto high-authority third-party domains
so that the *host domain's* authority carries the page into the SERP for terms the client's
own site cannot yet rank for.

**How it works here:**

```
  target term (from the keyword bank, with volume + difficulty)
    └── host selection: platforms whose domain authority and topical fit
        suit this term, filtered by the client's vertical and geography
    └── content: a genuinely useful page on that term, written by the M03 pipeline
        in the client's voice, with the client's entity and a link home
    └── publish to the host property
    └── TRACK THE HOSTED URL as a tracked keyword in M07 — the parasite page's own
        ranking is the deliverable, measured, not assumed
```

**Guardrails, because this is the part that gets abused:**
- Only on platforms whose terms permit it. A platform's `terms_position` governs, and a
  platform that forbids promotional or third-party-client content is not a parasite host.
- The content must stand on its own as useful. The QA scorecard applies unchanged.
- One parasite page per term per host. No doorway sets.
- The hosted page is tracked and reported to the client as a deliverable with its ranking —
  which also means it is visible if it is removed.

---

## 7. Surfaces

| Screen | Contents |
|---|---|
| **Accounts Connectivity** | Per-client platform grid: card per platform with state (`NOT LINKED` / connected / token expiring / limited / suspended), ownership tier, property count against cap, and `Connect` |
| **Create Post** | One composer; account toggles; live per-platform preview with character count, media rules and link policy; media library; schedule or queue |
| **Create Video Post** | Upload once → TikTok / Reels / YouTube / Facebook with per-platform trim and caption (P1) |
| **AI Studio** | Generate captions, hooks, tone and length variants, hashtags — seeded from the client's keyword bank and voice, not a blank prompt |
| **Parasite Poster** | Term → host recommendation → content → publish → tracked ranking |
| **Campaigns** | Plan, approval state, platforms, anchor plan, budget, progress |
| **Calendar** | Cross-client, cross-platform, drag to reschedule (`REQ-W2-016`) |
| **My Posts** | Ledger with terminal states and the external URL |
| **Placed Links** | Every outbound link, its anchor, its target, and its live state |
| **Analytics** | Per-platform metrics where the API provides them, each with provenance and a measured-at (`REQ-W2-017`) |

---

## 8. Acceptance criteria

| # | Criterion |
|---|---|
| A1 | One campaign publishes across **≥15 platforms** with per-client identities, images, SEO fields and internal links, entirely through official APIs, with no platform ban |
| A2 | Every platform card reflects real token state; an expiring token raises an alarm before it expires |
| A3 | Re-running a publish job produces exactly one post on the platform |
| A4 | No two properties publish within the same minute; per-platform daily caps hold under a 200-post campaign |
| A5 | Exact-match anchor share never exceeds its configured cap across a full campaign |
| A6 | A house account cannot be used for a client once its property cap is reached |
| A7 | A `per_client` account cannot be created without a `client_id`, enforced at the database level |
| A8 | Link liveness correctly detects a removed link and a link changed to `nofollow` |
| A9 | An account marked `limited` is removed from scheduling within one cycle and raises a task |
| A10 | A client not on a campaign sees no Web 2.0 surface in their portal |
| A11 | A Parasite Poster page is published, tracked in M07, and its ranking appears in the client report |
| A12 | A platform marked `unsupported` (Medium) has no publishing code path at all |
| A13 | Two properties never carry the same body text — asserted by similarity check across a campaign |
