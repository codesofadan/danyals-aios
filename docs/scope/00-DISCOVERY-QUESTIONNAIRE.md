# AIOS — Discovery Questionnaire (pre-scope)

**Compiled:** 2026-09-16 · **Purpose:** close every gap needed to write a scope + SDLC
pack that a fresh AI agent can execute without guessing.

**How to answer:** reply with the number and a short answer. Where a **Default** is
given, "ok" accepts it. 🔴 = blocking (the pack will be wrong without it).

---

## §0 — Programme, baseline and the receiving agent

1. 🔴 **Scope of this pack:** v1 only (Portal · Audit · Content · Citations · Web 2.0),
   or the whole system including the modules already in the repo but outside v1
   (`grid_tracker`, `rank_tracker`, `keyword_research`, `indexing`, `gmb`, `local_seo`,
   `site_builder`, `competitor_intel`, `billing`, `data_import`, `content_planning`,
   `content_experience`, `on_page`, `site_analytics`, `tool_workspaces`)?
   *Default: v1 five modules + Policy Radar as the committed baseline; everything else
   documented as v1.1 with a one-paragraph spec each.*
2. 🔴 **Continue or rebuild?** Does the receiving agent extend this ~82k-line codebase,
   or design/build fresh from the scope doc? *Default: continue and harden.*
3. **Who is the agent?** Claude Code in this repo · a cloud agent with repo access · a
   different vendor's agent with no repo access (pack must then be self-contained).
4. **Uncommitted work:** `docs/recovery/RESUME-2026-09-12.md` records 45 changed paths
   green but uncommitted (grid tracking, citation AI form-fill, 4 replicator fixes).
   Commit to `main` before the agent starts? *Default: yes, commit first.*
5. 🔴 **Deadline fixed or scope fixed?** (Open question Q-6, never answered.) Give the
   target date and which one gives.
6. **Client scale:** confirm 50–100 clients, architected beyond. Any client with
   multiple locations? How many?
7. **Policy Radar in v1?** (D-17, still open.) *Default: yes, at built level, daily
   schedule restored.*
8. 🔴 **Rankings source of record** (D-6, still open). Repo now uses DataForSEO Maps for
   the geo-grid. *Default: DataForSEO for organic rank, serper.dev for local pack /
   grid, never mixed, always labelled.*
9. 🔴 **Content QA scorecard: hard publish gate or advisory?** (D-4, still open.)
   *Default: advisory + mandatory acknowledgement until calibrated on ~30 human-graded
   drafts, then hard.*
10. **Credential rotation** for everything exposed in the WhatsApp/key exports (D-15) —
    authorised? *Default: yes, immediately.*
11. **Environments:** is there a staging environment, or is `app.qanry.com` the only
    one? May the agent deploy? Run migrations against prod?

---

## §1 — Module 1: Portal / platform core

12. Confirm the role set (Owner, Super-Admin, Admin, Manager, 4 staff roles, Client) and
    whether the **client** logs in at all in v1, or only receives PDFs/links.
13. Does the client ever self-serve (request work, approve, comment), or is the portal
    read-only for them? (D-18 says staff approve everything.)
14. **Billing/payments** — is money handled in-app (Stripe etc.) or outside? There is a
    `billing` module in the repo.
15. **Notifications:** email is live via Gmail SMTP. Add WhatsApp / Slack / in-app only?
16. **MFA** on Owner/Admin (D-8) — reinstate? *Default: yes, those two roles.*
17. **White-label:** is this ever resold to other agencies (multi-agency tenancy), or
    always one agency (Danyal) with many clients? *Default: single agency.*
18. Onboarding: bulk client import required (MT-012). What does the source data look
    like — CSV, Fiverr export, Sheets?

---

## §2 — Module 2: Audit

19. Confirm the two audit shapes: **Free** (public lead magnet, ~10–15 pages) and
    **Paid** (type-selectable, multi-agent, full narrative). Any third shape?
20. Which paid audit types are in v1? (technical · local · GEO/AI-search · content ·
    off-page · full). Skills exist for technical/local/GEO.
21. **Page/crawl limits** per audit tier, and the hard cost ceiling per audit.
22. Deliverable format: HTML viewer + PDF from one source — confirm. Who is the reader,
    the client or the staff SEO?
23. The audit engine lives at `danyals-audit-system/` and is invoked as a **subprocess**
    (it mints its own run id, never times itself out). Keep that seam, or absorb the
    engine into the backend? *Default: keep the seam, harden the contract.*
24. Free-audit abuse controls (rate limit, email verification, per-domain cooldown) —
    what's acceptable? Who owns the leads?

---

## §3 — Module 3: Content system (largest module)

### 3a. Design analysis — "client pastes his client's previous website URL"

25. 🔴 **Whose URL is it?** The client's **own existing live site** (the one we will
    publish onto), a **previous/old version** of their site, or a **reference /
    competitor** site whose look they want copied? Your wording said "previous website".
26. Can there be **more than one** reference URL per client (e.g. "match this site's
    layout but that site's colour")? *Default: one primary, optional extras.*
27. How many **pages** of the reference site do we analyse — just the pasted URL, or
    crawl N pages (home + service + blog) to learn the system? *Default: up to 5,
    auto-picked by type.*
28. 🔴 **Fidelity target:** pixel-accurate replication of the source page, or "a new page
    that is unmistakably the same design system" (same tokens, new composition)?
    *Default: same design system, new composition.*
29. Confirm the capture list. Currently extracted: palette + roles, typography (family,
    size scale, weight, line-height), spacing/padding/margin scale, section order,
    component styles, border-radius, shadows, container width, wireframe preview.
    **Anything missing you need** — buttons/CTA styles, form styles, image treatment
    (rounded/duotone), icon set, dark mode, breakpoints/responsive rules, animation,
    header/footer variants, nav style?
30. Is the extracted **design profile reviewed and approved by a human** before pages are
    built on it, and is it **editable** in the dashboard (change a colour, swap a font)?
    *Default: yes to both.*
31. **Versioning / staleness:** if the reference site is redesigned, do we re-analyse on a
    schedule, on demand, or never? Do already-published pages get re-skinned?
    *Default: on demand + a staleness badge; published pages untouched.*
32. When a new page needs a **section type the source site doesn't have** (FAQ accordion,
    comparison table, pricing tiers), how is it styled? *Default: synthesise from the
    captured tokens and flag it as "inferred, not observed".*
33. 🔴 **Does the design profile need to survive as a real Elementor/Gutenberg block
    tree** (so the client can edit every element in the builder), or is a
    styled-HTML block acceptable for v1? The README says the block-tree translation is
    the missing piece. *Default: genuinely editable Elementor is the v1 requirement.*

### 3b. Word bank

34. 🔴 **What is the word bank, precisely?** Pick all that apply:
    (a) client brand lexicon / approved terminology and tone,
    (b) SEO keyword bank from keyword research (head, long-tail, volumes),
    (c) entity / NLP term bank for topical completeness (the "must mention" set),
    (d) banned-words list (AI tells, competitor names, compliance words),
    (e) anchor-text bank for internal + off-page links.
35. **Where does it come from?** Keyword API (which — DataForSEO? Serper?), competitor
    SERP scrape, the client's own site, a client-supplied glossary, or AI-generated?
36. **Scope:** per client · per niche · per page-set · global? *Default: per client,
    seeded from niche templates.*
37. **Enforcement:** does the writer have to hit coverage targets (use N of M terms, each
    at a density), and does the QA gate score against it? Or is it advisory?
38. Is the word bank **human-editable** in the UI, and who owns it (SEO lead)?
39. Does it carry **per-term intent/stage** (informational, commercial, transactional) so
    the planner can map terms → page types?

### 3c. Planning, generation and publishing

40. 🔴 **Who decides how many pages a run produces** — the AI topical map proposes and a
    human approves, or the operator states "build these 12 pages"? *Default: AI proposes
    a page set, human approves, then fan-out.*
41. Confirm the **page types** in v1: home · service · location · service×location ·
    blog/article · about · contact · comparison · FAQ · category hub. Others?
42. **Volume acceptance bar:** is the 50-page run the definition of done for Content?
    Pages per client per month in normal operation?
43. **Word count / depth targets** per page type, and who sets them.
44. **Internal linking:** automatic from the topical map (silo rules), and does it edit
    *existing* pages to link to the new ones? *Default: propose, never auto-edit
    existing pages.*
45. **Schema markup** required per page type (LocalBusiness, Service, FAQPage,
    BreadcrumbList, Article)? *Default: yes, per type.*
46. **Images:** AI-generated (an OpenAI image key is wired), stock, client-supplied, or
    scraped from the reference site? Licensing constraints? Alt text automatic?
47. **Publish target:** WordPress only in v1 (Elementor primary, Gutenberg fallback), or
    must other CMSs land in v1? *Default: WordPress only.*
48. Does the client's WordPress have **Elementor Pro**? Which theme? Is our plugin
    (`wordpress-plugin/aios-publisher`) installable on every client site?
49. **Publish workflow:** draft → QA → staff review → publish live. Do we ever publish
    **scheduled** or **as draft in WP** for the client to review? Revert/rollback
    required? *Default: publish as WP draft by default, one-click live, revert kept.*
50. **Multilingual / non-English** content in v1? *Default: English only.*
51. **Plagiarism / AI-detection** checks required before publish (Copyscape, Originality)?
    Who pays?

---

## §4 — Module 4: Citations (AI browser extension)

52. 🔴 **Confirm the approach change.** The README says citations were being rebuilt
    around "data aggregators plus a human work queue". You now describe an **AI
    extension that fills the directory form** with a human or AI submitting. Is the
    extension the primary v1 route, and are aggregators (Yext/Data Axle) out?
53. **Who drives it** — agency staff / VA, or the client? How many operators at once?
54. 🔴 **Account creation is the real gap.** Does the extension also do **signup**
    (create the directory account), including **email verification** and sometimes
    **phone/SMS verification**? *Default: yes, signup included; email verification
    automated via a catch-all inbox; phone verification is a human task.*
55. **Email identities:** one catch-all domain for all clients, or a real mailbox per
    client? Who owns those inboxes? (Current: a single Gmail SMTP account.)
56. **Phone numbers** for directories that demand one — client's real number always, or a
    pool? Any SMS-receive service allowed?
57. **CAPTCHA:** CapMonster is wired. Auto-solve always, or fall back to the human in the
    tab? Budget per solve.
58. 🔴 **Submit action:** default to **AI auto-submits** or **human clicks submit** after
    reviewing the filled form? *Default: human-confirm for the first N per directory,
    then auto once the mapping is trusted.*
59. **Directory list:** how many and where from? The repo has `verticals.py` (131 lines)
    and ~163 directories are referenced in the access docs. Give the authoritative list
    or the sourcing rule (by country, by niche, by DA).
60. **Geography:** which countries/markets? (Changes the entire directory set.)
61. **Payload per directory:** NAP, categories, description(s), hours, services, payment
    methods, logo/photos, social links, year founded. Do descriptions need to be
    **unique per directory** (duplicate-content risk)? *Default: 3 length variants, each
    reused at most N times.*
62. **Proof and verification:** screenshot + live URL + status; re-check cadence
    (30/60/90 days)? What counts as "live"?
63. **Existing / duplicate listings:** detect and **claim** rather than create? Is claim
    flow (postcard, phone PIN) in scope? *Default: detect + report, claim is a human
    task outside the tool.*
64. **Isolation:** separate browser profile / proxy per client? Residential proxies are
    wired. Confirm per-client identity separation.
65. **Cost:** 10¢ marginal / 20¢ hard line was set for an automated route. With a human
    in the loop, what is the acceptable **loaded** cost per citation and minutes per
    citation?
66. **Volume:** citations per client per month, and the total backlog to clear at launch.
67. **Browser support:** Chrome/Edge only, or Firefox too? Chrome Web Store listing, or
    unpacked/enterprise install?

---

## §5 — Module 5: Web 2.0 / social posting

68. 🔴 **Which is it?** "Web 2.0" in SEO usually means **blog properties for links**
    (WordPress.com, Blogger, Tumblr, Medium, Ghost, Hashnode, Telegra.ph). You said
    "basically like social platforms posting" — do you also mean **social media**
    (Facebook, Instagram, X, LinkedIn, Pinterest, Reddit, YouTube)? If both, are they
    one module or two?
69. If social media is included: is it **link-building** (posts carrying links) or **SMM
    for the client** (brand presence, calendar, scheduling, engagement)? These need
    different products.
70. **Official APIs preferred** — confirmed. For platforms with **no usable API**
    (Medium is closed, Substack has none, Reddit/X have paid tiers), what do we do:
    skip the platform · browser automation · the same extension as citations?
    *Default: skip; never browser-automate a platform that forbids it.*
71. **Open-source tools:** are you open to self-hosting an existing publisher (e.g.
    Postiz / Mixpost) for social scheduling instead of building it? Any licence
    constraints (must be MIT/Apache, no AGPL)?
72. **Platform list for v1** — give it, or confirm the tiering in D-5:
    per-client identity on WordPress.com · Blogger · Tumblr · Ghost · Hashnode ·
    GitHub Pages · GitLab Pages; house accounts only on Telegra.ph and throwaways.
73. **OAuth:** per-client OAuth at campaign start — **who physically clicks it**, staff or
    client? ~10–15 min per client per campaign.
74. **Content for Web 2.0:** same content pipeline and design system, or a separate
    lighter writer? Unique per property (no spinning)? Word count?
75. **Linking strategy:** links per property, anchor-text mix (from the anchor bank),
    which target pages, pacing between posts. Give the rules or confirm the built ones.
76. **Volume:** properties per campaign, posts per property, campaign length.
77. **Health:** account-health monitoring and link-liveness re-checks — confirm in scope
    (`web2_linkcheck` / `web2_eligibility` exist).

---

## §6 — Cross-cutting AI stack (LangChain · LangGraph · LangSmith · Sentry)

78. 🔴 **Adoption breadth:** LangChain/LangGraph across **every** AI path (content
    pipeline, audit narrative, policy radar, design analysis, citations), or **only the
    citation form-filling agent** for now? The backend currently calls the model
    directly, so a full migration is a large, risky refactor with little user-visible
    gain. *Default: LangGraph for the citation agent + any new multi-step agent;
    wrap existing paths in LangSmith tracing only.*
79. 🔴 **Where does the graph run?** The extension is TypeScript in a browser; LangGraph
    is strongest in Python. *Default: the graph runs in the backend, the extension is a
    thin actuator (observe DOM → send digest → receive fill plan → execute).* Confirm,
    or do you want LangGraph.js inside the extension?
80. **LangSmith hosting:** hosted SaaS (client page content, NAP and credentials-adjacent
    data leave the VPS) or self-hosted? Is hosted acceptable to the client?
81. **Sentry:** sentry.io SaaS or self-hosted? PII scrubbing rules? Frontend + backend +
    extension, or backend only? (`app/core/observability.py` already exists.)
82. 🔴 **Model routing:** the platform currently calls **agentrouter.org**, not Anthropic
    directly, and the premium tier is budget-exhausted (only `deepseek-v4-flash` and
    `glm-5.3` have quota). Is that the intended long-term routing, or do we move to a
    direct Anthropic key? Which model for which task tier?
83. **Budget:** monthly AI spend ceiling overall, and per client per month.
84. **Missing keys** — confirm which will be provided: DataForSEO · Voyage (embeddings) ·
    Apify actor id · Bing · Hashnode/GitHub/GitLab tokens · WordPress app passwords per
    client · a real transactional email provider (Resend is wired).
85. **Evals:** do you want a regression eval suite for the AI outputs (content quality,
    form-fill accuracy), and what is the pass bar?

---

## §7 — Data, infrastructure, operations

86. **Hosting:** single VPS today. Specs? Is a second host for browser workers approved
    (MT-013)?
87. **Postgres 16 + RLS** is the tenant boundary — confirm it stays. Is the
    **Sheets-as-store** layer still used anywhere, or formally retired?
88. **Backups / DR:** what RPO/RTO does the client expect? Backups tested?
89. **Scheduling:** `beat_schedule` is empty — nothing runs automatically. Restoring it
    is gated on a job contract (retry, idempotency, dead-letter). Is "nothing is
    scheduled" acceptable today, and what is the target date to restore it?
90. **CI/CD:** what must pass on every change (ruff, mypy, pytest, tsc, migration
    fresh-apply, RLS gate)? Is there a deploy pipeline or manual?
91. **Alerting:** who gets paged, on what, through what channel?
92. **Data retention:** how long do we keep client page content, screenshots, credentials,
    audit artefacts? Any deletion-on-offboarding requirement?
93. **Legal/compliance:** is there a DPA with the client? Any jurisdiction constraint on
    where data lives?

---

## §8 — SDLC and the working agreement for the AI agent

94. **Branching & PRs:** trunk-based on `main` with PRs, or direct commits? Who reviews —
    you, or an automated review gate?
95. **Definition of done:** tests written · mypy/ruff clean · migration applies from zero
    · docs updated · demo on a real client? State the gate.
96. **Test policy:** ~4,900 tests exist. Must every change ship tests? Any coverage bar?
97. **May the agent** touch production, run migrations, spend money on provider calls, or
    publish to a real client site? *Default: no to all four without an explicit human
    go-ahead per action.*
98. **Team:** Adan (backend), Huzaifa (frontend), Arham (db) — is the AI agent working
    alongside them (so it needs file-ownership boundaries) or alone?
99. **Cadence & reporting:** what does the agent report, how often, and where?
100. **Which documents are authoritative** when they conflict? *Default order:
     DECISIONS_LOG.md → this scope pack → code → older docs.*

---

## §9 — Anything I have not asked

101. What has Danyal actually **seen working**, and what does he believe is finished?
     (Open question Q-7 — never answered, and it sets the recovery tone.)
102. What is the single thing that, if it fails at hand-over, loses the client?
