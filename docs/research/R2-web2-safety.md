# R2 — Web 2.0 safety — platform tiers, footprint control, and the similarity gate

**Track:** R2 · Web 2.0 safety
**Status:** Decided — gates the Web 2.0 build
**Date:** 2026-08-23
**Prior decisions touched:** D-5 / Q-5 (tiered account ownership), D-16 (per-campaign), WEB2-001…WEB2-017, DATA-016, DATA-017
**Prior decisions this record CONTRADICTS (with evidence, see §4 and §3.3):** D-5's inclusion of **Hashnode, GitHub Pages and GitLab Pages** in the per-client account tier for local-business clients (`DECISIONS_LOG.md:101` lists WordPress.com · Blogger · Tumblr · Ghost · Hashnode · GitHub Pages · GitLab Pages — note that **dev.to is not in D-5's list at all**; dev.to's automated status comes from the spec's §17.3 "Fully automated" classification, `DANIEL_PROJECT_RECOVERY_SPECIFICATION.md:1223`); the spec's §17.3 classification of **WordPress.com / Blogger / Tumblr** as "one human OAuth run per client, then **fully automated publishing**" (`:1225`) — D-5 itself settles only *account ownership*, not automation depth; the `[CIT-ECON]` claim of a **"March 2026 Site Reputation Abuse update"** (`:1235`, and relied on again at `:420`); WEB2-001's "**50+ platforms with live publishing**" read as a per-client target.

---

## 1. Decision

**We keep the Web 2.0 module, and we narrow it hard.** Publishing eligibility becomes a function of *the client's own topic*, not of how many adapters exist: for a typical local-business client the eligible set is **four properties — WordPress.com, Blogger and Tumblr on per-client accounts the client owns, plus Telegra.ph on a capped house account** — because every other adapter in the catalogue either forbids what we would do in its own published terms, is topically impossible for a plumber or a dentist, has closed its free tier, or carries no link value. The remaining ~50 adapters (54 platform constants less the four eligible) stay in the codebase and stay reachable, but only for clients whose real industry makes the placement genuine (a dev-tools SaaS may legitimately post to dev.to; a plumber may not). Every placement stays at **L3 — a lead approves each article individually, never a batch** — and must clear a **three-part similarity gate** before it can be approved: exact-duplicate hash, **Jaccard resemblance over 5-word shingles (Broder) with a block at r ≥ 0.25**, and a **heading-skeleton Jaccard block at ≥ 0.60**, each evaluated across three scopes — the client's own property set, every client sharing the same house account, and every client publishing to the same platform in a rolling 90 days. The gate is pure Postgres plus Python stdlib, zero marginal cost, no new dependency, and **no embeddings** — semantic similarity is the wrong instrument here and the deployment deliberately ships without Voyage/Pinecone. `seed_web2_vault` is **deleted, not repaired**: fanning one house credential into every client's vault is the exact shared-footprint pattern being retired, and it is replaced by a per-client account registry (`web2_accounts`) plus an OAuth-at-campaign-start flow. Anchors carry a **hard zero-exact-match rule** rather than an invented percentage distribution, because Google publishes no anchor ratio and inventing one would repeat this project's founding defect. Inter-property linking is **banned outright** — it is the clearest network tell we can emit.

---

## 2. Context — the question this track had to settle

The build carries **54 named platform constants** (`backend/integrations/web2_publishers.py:201-266`; `WEB2_PLATFORMS` at `:268` has 54 members) and **53 credential shapes** (`PLATFORM_CREDENTIAL_FIELDS`, `:295-351` — every constant except `PLATFORM_MEDIUM`, which is draft-only), in a 3,217-line module, plus **110 catalogue row literals resolving to 90 unique platform rows** across migrations `0063`, `0066`, `0068`, `0070`, `0072`, `0076`, `0077` (later batches re-insert earlier names under `on conflict (name) do update`, so the catalogue holds 90 distinct platforms, not 110). The adapters are real code. **Eight** platforms are recorded as having a live credential today — Telegra.ph, dev.to, Mataroa, Mastodon, Micro.blog, GitHub Pages, GitLab Pages, Hashnode (`DANIEL_PROJECT_RECOVERY_SPECIFICATION.md:1212`, per `[CIT-CRED]` §3) — the rest have a publisher class and no account.

The module publishes to third-party properties on behalf of clients. Its failure mode is not "a placement fails" — it is **one detectable pattern getting an entire client base actioned at once**. Three specific things blocked the build:

1. **Which platforms may we use at all**, given each vendor's own terms — not our guess about Google's tolerance, but the platform's published rules about programmatic posting and bulk accounts. A ban on WordPress.com destroys a client-owned asset; a ban on a shared house account destroys *every* client's asset on that platform simultaneously.
2. **What the similarity gate actually is.** `REQUIREMENTS_TRACEABILITY.md:308` (WEB2-007) requires a "Cross-property similarity gate blocking above threshold, measured within a client **and** across clients on a shared account" and specifies no algorithm, no threshold, no storage. It is the spec — `DANIEL_PROJECT_RECOVERY_SPECIFICATION.md:1247` (WEB2-7) — that marks it PROPOSED and calls it "the single most important safety control in the module"; that phrase does **not** appear in `REQUIREMENTS_TRACEABILITY.md`. Nothing in the repo implements it: `backend/app/services/web2_pipeline.py` has a human review gate (`:7`, `:22`) and a cost gate, and no similarity check anywhere. **Two reusable primitives do already exist** and the build should not re-invent them: `backend/app/services/content_qa.py:611-618` (`_internal_dup_originality`) already builds 5-word shingles — `shingles = [tuple(words[i : i + 5]) for i in range(len(words) - 4)]` — as a *within-document* duplication proxy, and `backend/app/modules/competitor_intel/service.py:317` (`jaccard_overlap`) already implements `|A ∩ B| / |A ∪ B|`. What is missing is the *cross-document, cross-client* gate: neither primitive compares one draft against another document, and no fingerprint of a published article is persisted anywhere.
3. **Whether the module is worth running at all in 2026.** The client-delivered economics document asserts a specific Google enforcement event as the governing risk. That assertion had to be checked before it was allowed to shape a design.

The existing footprint control is `diversify_footprint` (`web2_publishers.py:3163-3210`), which rotates platform/account/anchor/delay by hashing a seed. It is deterministic and pure, it prefers an unused `(platform, anchor)` pair, and it is scoped to **one client's existing placements only** (`existing: Sequence[tuple[str, str]]`). It cannot see across clients, which is precisely the axis on which a house account fails.

---

## 3. Findings

### 3.1 The governing Google risk is **not** site reputation abuse. It is user-generated spam plus link spam — and one number in a client-delivered document is wrong.

**Finding: `[CIT-ECON]`'s "Google's March 2026 Site Reputation Abuse update" does not exist.** Google's own ranking release history lists exactly six 2026 entries: February 2026 Discover update (5 Feb), **March 2026 spam update (24 Mar, 19h30m)**, March 2026 core update (27 Mar), May 2026 core update (21 May), June 2026 spam update (24 Jun), August 2026 spam update (18 Aug). There is no update named for site reputation abuse in any year, and **the most recent named link spam update is the December 2022 link spam update** (started 14 Dec 2022, 29 days) [google-ranking-history]. A generic March 2026 spam update did occur; it was not a site-reputation-abuse action. The quotation reproduced at `DANIEL_PROJECT_RECOVERY_SPECIFICATION.md:1235` is therefore built on a false premise and must not be used to justify a design — and it is relied on a second time at `:420`, where a hard prohibition is said to be "grounded in the March 2026 Site Reputation Abuse enforcement", so both sites need correcting together. *(Secondary reporting states the March 2026 update explicitly did not target link spam or site reputation abuse [seo-kreativ-mar2026]; the primary dashboard is sufficient on its own to establish that no such named update exists.)*

**Finding: site reputation abuse mostly does not apply to us.** Google defines it as "a tactic where third-party content is published on a host site mainly because of that host's already-established ranking signals, which it has earned primarily from its first-party content," and the policy's own not-abuse list opens with "**Sites designed to allow user-generated content, such as a forum website or comment sections**" [google-spam-policies]. WordPress.com, Blogger and Tumblr are UGC platforms whose ranking signals are not "first-party content" in the sense the policy means. Enforcement was confirmed as **manual-action-only as of 6 May 2024**, with Google's SearchLiaison saying "the enforcement is purely manual for now" and that "the algorithmic portion of the Site Reputation Abuse policy is coming soon" [sej-sra, secondary, dated 2024-05-06] — and the ranking-updates dashboard shows that algorithmic portion has still never shipped under that name [google-ranking-history]. **The further claim that enforcement is scoped to the offending subdirectory/subdomain rather than the whole site is `[UNVERIFIED]`** — the cited SEJ article does not say it (it says only that a manual action "generally means removal from the search index"). Verifying it would require Google's own manual-actions documentation or a dated Search Central statement. This is a real risk for parasite-SEO placements on genuine editorial publishers; it is largely the wrong lens for hosted-blog properties.

**Finding: the policies that DO apply name our exact pattern, twice.** Under **user-generated spam**, Google's first listed example is "**Spammy accounts on hosting services that anyone can register for**" [google-spam-policies]. Under **link spam**, the examples include "**Using automated programs or services to create links to your site**" and "**Low-quality directory or bookmark site links**" [google-spam-policies], page last updated **2026-05-15 UTC**. Every Web 2.0 link this module places is a self-made link created by an automated program. The only thing separating a compliant placement from a policy example is whether the property is a genuine brand property publishing genuine content, with the link as a natural self-reference. That is not a rhetorical distinction — it is the whole safety design, and it is also, independently, what the host platforms demand (§3.2).

**Finding: no anchor-text ratio exists in Google's guidance.** Google publishes no ideal or maximum anchor distribution; the widely-circulated "40-60% branded / <5% exact match" figures are industry folklore from secondary sources with no primary basis [emgi-anchors, secondary; basesearch-anchors, secondary]. **Correction to an earlier draft of this record:** the link-spam list item that mentions keyword-rich links reads, in full, "**Keyword-rich, hidden, or low-quality links embedded in widgets**" [google-spam-policies] — it is scoped to *widgets*, and quoting it as a bare "keyword-rich … links" overstates it. The link-spam item that applies squarely to us is "**Using automated programs or services to create links to your site**". Any percentage this project writes down would still be an invented number of exactly the kind this rescue exists to eliminate. See requirement **R2-14** for the rule we implement instead.

**Consequence for the "worth running at all" question:** yes, under constraints — but its value must be honestly reframed. The module's defensible output is **brand-entity properties carrying consistent NAP and one natural self-reference each**, matching the framing already agreed at `DANIEL_PROJECT_RECOVERY_SPECIFICATION.md:1204`. It is not a link-equity engine, and several of the surviving link surfaces are `nofollow` anyway (§3.4). Volume is the enemy, not the goal.

### 3.2 Host-platform terms disqualify more of the catalogue than Google does

Verified against each vendor's own published terms on 2026-08-23. **Fetch-method note:** every row below was retrieved directly on 2026-08-23 **except WordPress.com**, whose `/tos/` and `/support/user-guidelines/` pages both return **HTTP 403 to automated fetch**; the WordPress.com quotations and its 10 April 2026 ToS date are corroborated only through a search engine's index of those same primary URLs and are flagged accordingly in that row.

| Platform | What its own terms say | Effect |
|---|---|---|
| **WordPress.com** `[SOURCE 403 — index-corroborated only]` | User Guidelines, "Spam or machine-generated content": *"Sites primarily dedicated to drive traffic to third party sites, boost SEO, phish, spoof, or promote affiliate marketing aren't cool"* [wpcom-guidelines]. ToS Last Updated **10 April 2026**; termination clause: *"We may terminate your access to all or any part of our Services at any time, with or without cause or notice, effective immediately, including if we believe, in our sole discretion, that you have violated this Agreement, any service guidelines, or other applicable terms"* [wpcom-tos]. **Both pages refused automated fetch (HTTP 403) on 2026-08-23; these are index-corroborated, not directly read** — a human should open both URLs and confirm before this row is relied on in a client-facing or legal context. | **Usable, conditionally.** A genuine client brand blog is permitted. A property whose purpose is the link is explicitly not. The condition is enforceable (R2-09, R2-11). |
| **Blogger** | Content Policy, Spam: *"Do not spam. This may include unwanted promotional or commercial content, **unwanted content that is created by an automated program**, unwanted repetitive content, nonsensical content, or anything that appears to be a mass solicitation."* Under "Impersonation and Misrepresentation of Identity" it also prohibits *"content or accounts misrepresenting or concealing their ownership or primary purpose"* — **but the sentence continues** *"such as misrepresenting or intentionally concealing your country of origin or other material details about yourself when directing content about politics, social issues, or matters of public concern to users in a country other than your own"* [blogger-policy]. Blogger API v3 is live, OAuth 2.0, scope `https://www.googleapis.com/auth/blogger`; the page carries **no quota or rate-limit figures** [blogger-api]. | **Usable, conditionally.** "Unwanted" is the operative qualifier; L3 human approval plus genuine per-client content is the compliance argument. **Corrected:** the ownership-concealment clause is *illustrated* with cross-border political/social-issue content, so reading it as a direct prohibition on our username scheme overstates it. R2-08 stands on the independent footprint argument in §3.5 Finding B (a platform T&S team can enumerate accounts by shared prefix/suffix/domain), not on this clause. |
| **Tumblr** | User Guidelines, **"Mass Registration or Automation. Don't register accounts or post content automatically, systematically, or programmatically."** API License Agreement §(o) No Spamming: *"posting numerous substantially identical pieces of Content, posting misleading or obfuscated links, and executing a large number of native Tumblr actions … in an unnaturally short period of time."* §(s) Genuine Actions: an application *"should not post to the Tumblr Services on a user's behalf without (i) a specific interaction informing a user that such user is making a post … and (ii) an explicit action by such user evincing permission for making the post"* [tumblr-guidelines, tumblr-api-license]. | **Usable only at strict per-post L3.** §(o) and §(s) quotations verified verbatim against Tumblr's own policy repository on 2026-08-23, and the clause letters match their headings. §(s) expressly contemplates posting on a user's behalf *with* per-post explicit permission — that is L3. It does **not** permit batch approval, scheduled fire-and-forget, or programmatic registration. **One precision the source forces:** §(s)'s "user" is the *Tumblr account holder*, so an agency lead's approval satisfies it only where the lead is the account holder or is acting on the client's explicit per-post permission — record which, per client. **This contradicts the spec's §17.3 classification** of Tumblr as "then fully automated publishing" (`DANIEL_PROJECT_RECOVERY_SPECIFICATION.md:1225`); D-5 itself decided only that Tumblr is a per-client-account platform. |
| **dev.to (Forem)** | Content Policy: *"Users must make a good-faith effort to share content that is on-topic, of high-quality, and **is not designed primarily for the purposes of promotion or creating backlinks**. Posts must contain substantial content — they may not merely reference an external link that contains the full post."* [devto-terms] | **Do not use for local-business clients.** A local plumber's article on a developer community is off-topic promotion by construction. dev.to is one of the **eight** platforms recorded with a live credential today (`DANIEL_PROJECT_RECOVERY_SPECIFICATION.md:1212`). Quotation verified verbatim, dev.to Terms §11 Content Policy. |
| **Hashnode** | ToU Effective/Last Updated **15 February 2026**. Acceptable Use prohibits *"spam, including unsolicited promotional content, bulk messages, or **automated content generation for the purpose of manipulating search results** or engagement metrics."* Its own summary states: *"AI content is your responsibility — Review and approve any AI-generated suggestions before publishing."* [hashnode-terms] | **Do not use for local-business clients** (same topical mismatch as dev.to). Note the platform independently mandates human review of AI content — corroborating the L3 ceiling. |
| **Write.as** | Pricing page: free tier is **"Closed for now"**; free tier posting limit **"3 – 15 per day"**; **"Do-follow links"** is a **Pro/Team-only feature** (Pro from $6/mo annual, $9/mo monthly) [writeas-pricing]. | **Do not use.** Signup is closed, and the free tier's links are nofollow. Corroborates `[OFFPAGE-STATUS]`'s "Bot detected" report (`DANIEL_PROJECT_RECOVERY_SPECIFICATION.md:1219`). |
| **GitHub Pages / Gist** | AUP: prohibits *"automated excessive bulk activity and coordinated inauthentic activity, such as spamming"* and *"inauthentic interactions, such as fake accounts and automated inauthentic activity"*; and: *"the primary focus of the Content posted in or through your Account to the Service should not be advertising or promotional marketing"* [github-aup]. Repo's own catalogue note: gist/code links "are typically nofollow" (`db/migrations/0066_web2_platforms_more.sql`). | **Do not use for local-business clients.** A marketing article is the primary content, which the AUP names. No multiple-account prohibition was found in the AUP. |
| **Medium** | API repository archived **2 March 2023**; README states verbatim: *"**The Medium API is no longer supported.** We do not recommend using it."* [medium-api-docs] | **Confirmed dead** — WEB2-016 upheld. The repo already models this correctly as draft-only (`web2_publishers.py:39-43`). |
| **Bluesky** | Community Guidelines: *"Do not send spam or repeatedly post content in ways that disrupt normal conversations or service use. Do not artificially manipulate features or social signals to gain unearned reach"* [bluesky-guidelines]. | **Do not use as a link property.** A ~300-grapheme post is not an article; value is entity/brand, not a page. |
| **Dreamwidth** | The live `/create` form shows a standard self-serve signup (account name, email, password, birthdate, ToS checkbox) with **no invite-code field** on 2026-08-23 — but it **does carry an anti-spam CAPTCHA** [dreamwidth-create]. This contradicts `DANIEL_PROJECT_RECOVERY_SPECIFICATION.md:1218` ("Dreamwidth needs an invite code"), which should be corrected there. Invite codes are re-imposed episodically at Dreamwidth's discretion [dreamwidth-faq105]. | **Do not use** — legacy journal platform, no topical fit for local business, the signup CAPTCHA puts automated registration behind the project's no-CAPTCHA-evasion rule, and the LJ-protocol credential is a raw username+password (`web2_publishers.py` `PLATFORM_LIVEJOURNAL`/`PLATFORM_DREAMWIDTH`). |
| **Ghost** | Ghost(Pro) Starter **$18 USD/mo billed yearly** [ghost-pricing]. | **Do not use as a built property** — see §6. Keep the adapter for clients who already run Ghost. |
| **Weebly / Strikingly / Wix / Substack / Google Sites** | No publish API; all five catalogued `auth_type='automation'` (browser/editor publish) in `db/migrations/0063_web2_platforms_seed.sql` — e.g. Substack, *"automation: editor publish; free {user}.substack.com. No public post-write API"*. **`Squarespace` is not in the catalogue at all** — it appears only in WEB2-016 (`REQUIREMENTS_TRACEABILITY.md:317`) and `DANIEL_PROJECT_RECOVERY_SPECIFICATION.md:1217`, both of which already exclude it. | **Do not use.** Browser-driving a defended signup is exactly what the CAPTCHA-evasion drop forbids. WEB2-016 upheld and extended. |

**The rule this produces, stated generally:** *topical eligibility is a property of the client, not of the platform.* Every one of dev.to, Hashnode, GitHub Pages, HackMD, the paste hosts and the research repositories forbids off-topic promotional content in its own terms — which means the adapter is not the problem and deleting it would be wrong. What must change is that the eligible platform set is **computed per client from the client's real industry**, and defaults to the topic-agnostic set.

### 3.3 The 50+ platform target cannot be met per-client, and should not be

`WEB2-001` ("50+ platforms with live publishing", P0, `REQUIREMENTS_TRACEABILITY.md:302`) is satisfiable as a *catalogue capability* and is not satisfiable as a *per-client delivery target* without breaching the terms in §3.2. D-16 already scoped Web 2.0 to per-campaign delivery and removed the blanket 50×10 volume bar (`DECISIONS_LOG.md:49-57`); this record completes that move by making the per-client eligible set topic-derived and typically **four**. The status board (WEB2-012) must therefore show, per platform, not just connected/missing but **eligible / ineligible-for-this-client with the reason** — otherwise the honest-status requirement produces a dishonest impression of scale.

### 3.4 Link value must be measured, not assumed

Write.as publishes do-follow as a paid feature [writeas-pricing], which establishes that free-tier nofollow is a normal commercial posture rather than an edge case. Mastodon status links carry `rel` values including `nofollow noopener noreferrer` in at least some contexts [mastodon-rel, secondary — the primary source is the rendered page, and reports conflict]. The repo's own catalogue already asserts nofollow for GitHub Gist, GitLab Snippets, Mastodon, Lemmy, Pixelfed and Pastebin (`db/migrations/0066_web2_platforms_more.sql`).

**We stop guessing.** The verify stage already exists (`web2_pipeline.py:427` `verify_live_and_indexable`). It must be extended to fetch the published page, locate the placed link by `target_url`, and record the **actual `rel` attribute** on `web2_properties`. A property whose link resolves to `nofollow` is recorded as a brand/indexation placement, never reported to the client as a ranking link. This converts an unverifiable research claim into a measured per-placement fact — the correct move for this project.

### 3.5 The repo emits two cross-client footprints today, independent of the house-account issue

**Finding A — `seed_web2_vault` fans one credential set into every client.** `backend/app/cli/seed_web2_vault.py:69-101` crosses every client against every platform in `WEB2_HOUSE_CREDENTIALS_JSON`; `:103-124` writes, for each pair, a vault row whose secret is `json.dumps(dict(house[entry.platform]))` — **the identical house credential, keyed by `label=entry.client_id`**. The per-client vault row is therefore a naming convention over a single shared login. The module docstring states it plainly: *"The agency publishes through shared HOUSE accounts (one dev.to / Telegra.ph / Mastodon / … login used for every client)"* (`:6-8`). Config carries `web2_house_credentials_json` at `backend/app/config.py:588`. This is the defect D-5 flagged (`DECISIONS_LOG.md:111`), confirmed at source.

**Finding B — the generated identities are machine-readably correlated, and this one is new.** `backend/integrations/web2_signup.py:533` computes the signup email as `alias_for(directory=platform, client_id=client_id, domain=catchall_domain)`, which returns `f"{_slug(directory)}-{_short(client_id)}@{domain}"` (`backend/integrations/imap_mailbox.py:84`), where `_short` is **the first 10 hex characters of `sha1(client_id)`** (`imap_mailbox.py:71-74`). Line `:537` then derives the account username from that alias via `_username_from_alias` (`web2_signup.py:89-95`), which strips non-alphanumerics and truncates to 24 characters. The result:

- every client's account **on the same platform** shares the same leading platform slug;
- every account **for the same client** shares the same trailing `_short(client_id)` hash;
- **every account across the entire client base shares one catch-all email domain.**

Three joinable keys. A platform trust-and-safety team that suspends one account can enumerate the rest by prefix, by suffix, and by registrant domain. That enumerability is the whole finding and it stands on the code alone; **it does not need a policy citation to be true**, and the Blogger ownership-concealment clause previously invoked here is scoped to cross-border political content (see §3.2) and is withdrawn as support. This is a footprint the similarity gate cannot see and cannot fix.

### 3.6 The similarity gate: shingling wins on the merits, not on cost

**Rejected — embeddings/cosine.** Not on price: `voyage-3.5` is **$0.06 per million tokens** (listed as `$0.00006 per thousand tokens`; note the page now files voyage-3.5 under "Older models", which carry **no** free-token allowance) [voyage-pricing], so 4,000 drafts × ~1,600 tokens ≈ 6.4M tokens ≈ **$0.38/year**. *(4,000 is the deliberately over-sized corpus figure from R2-12; the D-16 campaign-scoped figure in §6 is 640 drafts/yr ≈ $0.06/yr. Both are quoted below their respective assumption sets; neither changes the verdict.)* Rejected because (a) the deployment deliberately ships **without** Voyage and Pinecone — `backend/pyproject.toml:49-58` puts them in an optional `embeddings` extra with the comment *"the deployment uses NO Voyage/Pinecone (context vector recall is off), and this tree … is both heavy and a major contributor to pip-resolver backtracking"*; and (b) **semantic similarity measures the wrong thing**. Two genuinely independent articles about "emergency plumber in Leeds" written for two different Leeds plumbers *should* be semantically near-identical — cosine would fire constantly on legitimately distinct work — while a spun article that swaps synonyms and reorders sentences stays semantically identical to its source and would also fire, giving no discrimination at all. The gate must detect **shared surface form**, which is a syntactic question.

**Rejected — SimHash at Google's parameters.** Manku, Jain and Das Sarma (Google Inc., WWW 2007) state verbatim: *"With simhash, for 8B web pages, 64-bit fingerprints suffice"*, and pose the operating problem as *"whether any of the existing 8B 64-bit fingerprints differs from F in at most k = 3 bit-positions"*, concluding *"Charikar's simhash technique with 64-bit fingerprints seems to work well in practice for a repository of 8B web pages"* [manku-simhash]. Those parameters are tuned to find **near-identical** documents in a **billion-scale** corpus. Our corpus is ~10³–10⁴ documents and our target is **templating**, not duplication. k=3/64 bits yields a binary verdict with no continuous score, so it cannot express a warn band, and it would pass a reworded-but-templated article. Correct algorithm, wrong operating point, wrong scale.

**Selected — Broder resemblance over word shingles.** Broder, Glassman, Manasse and Zweig (1997) define, verbatim: *"Given a document D we define its w-shingling S(D, w) as the set of all unique shingles of size w contained in D"*, and *"For a given shingle size, the resemblance r of two documents A and B is defined as r(A,B) = |S(A) ∩ S(B)| / |S(A) ∪ S(B)|"*; they report *"We calculated our clusters based on a 50% resemblance"* over *"a collection of 30,000,000 HTML and text documents from a walk of the web performed by AltaVista in April of 1996"* [broder-clustering]. This gives a **continuous, bounded, explainable** score, a **primary-sourced anchor** for what "roughly the same" means on the web (r = 0.50), and — critically at our scale — it is **exactly computable**. MinHash exists to approximate this at billion scale; at 10⁴ documents we do not need the approximation. Broder's own **MOD_m** sampling (keep shingles ≡ 0 mod m) gives an unbiased resemblance estimator and shrinks the candidate index m-fold.

**The paper's own operating parameters, which an earlier draft of this record got wrong.** Broder et al. state: *"We sketched all of the documents with 10 word long shingles to produce 40 bit (5 byte) shingle fingerprints"* and *"We use the 'modulus' method for selecting shingles with an m of 25"* [broder-clustering]. So the paper's production values are **w = 10 and m = 25**, not the w = 4 / m = 16 an earlier draft implied. Our **w = 5** and **m = 16** are therefore *our* parameters, not Broder's, chosen for a short-article corpus rather than a 30M-page web walk — a smaller w is more sensitive to local rewording, which is what templating looks like here. They are legitimate choices but they are **unvalidated**, and O-2 now carries the sweep that settles them.

**Threshold provenance, stated honestly.** Broder's 0.50 is the *duplicate* line. A safety gate must trip well before duplicate, because the harm is a **detectable pattern**, not a duplicate. We set the block at **r ≥ 0.25** — half of Broder's duplicate line — and a warn band at **0.15 ≤ r < 0.25**. **These two numbers are agency policy, not vendor guidance, and no published source supports them.** They are set deliberately conservative and are required to be calibrated against a golden set before the gate is allowed to become hard (R2-08, and see §8).

---

## 4. Options considered and why rejected

| Option | Disqualifying fact |
|---|---|
| **Keep the shared house-account model as built** | One shared login is one shared failure domain: a suspension on WordPress.com removes every client's property at once, and `[CIT-ECON]` promised the client the opposite ("never shared across clients (keeps them safe from bans)"). Confirmed at source: `seed_web2_vault.py:103-124`. |
| **Per-client accounts on all 54 platforms** | dev.to and Hashnode forbid content "designed primarily for … creating backlinks" / "for the purpose of manipulating search results" for an off-topic client [devto-terms, hashnode-terms]; GitHub's AUP forbids accounts whose primary focus is promotional marketing [github-aup]; Write.as free signup is closed [writeas-pricing]; and **32 of the 90 catalogue rows are classified `auth_type='automation'`** — no public write API, browser/editor publish only (counted across `0063`–`0077`). Per-client accounts do not cure a terms breach. |
| **Fully automate Tumblr publishing (the spec's §17.3 position, `:1225` — *not* D-5's, which decides account ownership only)** | Tumblr User Guidelines, "Mass Registration or Automation": *"Don't register accounts or post content automatically, systematically, or programmatically."* Its API License §(s) permits posting on a user's behalf only with per-post explicit permission from the account holder [tumblr-guidelines, tumblr-api-license]. Batch approval is out. |
| **Automate account signup with browser automation** | Write.as free tier is "Closed for now" [writeas-pricing]; Tumblr forbids programmatic registration [tumblr-guidelines]; CAPTCHA evasion is dropped as project policy. The existing `BrowserSignupProvider` (`web2_signup.py`) is retired for Tier-A platforms and its `blocked` path becomes the only path. |
| **Embeddings + cosine for the similarity gate** | Wrong instrument (§3.6): fires on legitimately-distinct local-SEO content, passes synonym-spun content. Also requires re-adding a dependency tree the deployment explicitly excludes (`pyproject.toml:49-58`). |
| **SimHash 64-bit / Hamming k ≤ 3** | Google's own stated parameters target near-identical detection across 8 billion pages [manku-simhash]. Binary verdict, no warn band, misses reworded templating at our scale. |
| **Adopt a published anchor-text ratio (e.g. 60/20/15/5)** | No such ratio exists in Google's guidance — confirmed by reading the spam-policy page end to end on 2026-08-23; the circulating figures are secondary folklore [emgi-anchors, basesearch-anchors]. Writing one into the product would be a fabricated number — the exact defect this rescue exists to eliminate. Replaced by a rule that needs no ratio (R2-14). |
| **Drop the Web 2.0 module entirely** | Rejected: the narrowed form (brand properties, NAP consistency, one natural self-reference, L3) is a legitimate local-SEO practice, is already sold, and is defensible against the actual policy text. What is dropped is *volume*. |
| **Use `diversify_footprint` as the safety control** | It is per-client only (`web2_publishers.py:3163-3169`, `existing` is one client's placements) and rotates metadata, not content. It cannot see the cross-client axis, which is where a shared account fails. Keep it as a *selection* helper; it is not a gate. |

---

## 5. Engineering requirements this imposes

### Platform tiering and eligibility

**R2-01 · Add `web2_accounts` as a first-class table (closes DATA-016).** New migration `db/migrations/0081_web2_accounts.sql`:

```sql
create type public.web2_ownership as enum ('per_client', 'house');
create type public.web2_account_health as enum
  ('active', 'degraded', 'suspended', 'deleted', 'unverified');

create table public.web2_accounts (
  id                 uuid primary key default gen_random_uuid(),
  platform           public.web2_platform not null,
  ownership          public.web2_ownership not null,
  client_id          uuid references public.clients (id) on delete restrict,  -- NOT NULL when ownership='per_client'
  handle             text not null,             -- the real account/blog name on the platform
  property_url       text not null default '',
  registration_email text not null default '',
  registration_domain text not null default '',
  vault_provider     text not null,             -- 'web2:<Platform>', mirrors integrations/web2_credentials.vault_provider_for
  vault_label        text not null,             -- the account id, NOT the client id (see R2-06)
  health             public.web2_account_health not null default 'unverified',
  health_checked_at  timestamptz,
  property_count     int not null default 0,
  max_properties     int not null default 1,    -- the cap; see R2-13
  created_at         timestamptz not null default now(),
  updated_at         timestamptz not null default now(),
  constraint web2_accounts_per_client_has_client
    check (ownership <> 'per_client' or client_id is not null),
  constraint web2_accounts_house_has_no_client
    check (ownership <> 'house' or client_id is null)
);
create unique index web2_accounts_platform_handle_uq on public.web2_accounts (platform, handle);
create unique index web2_accounts_per_client_uq
  on public.web2_accounts (platform, client_id) where ownership = 'per_client';
```
ENABLE + FORCE RLS with the same staff-read / lead-write shape as `public.web2_properties` (`db/migrations/0018_offpage.sql:125-126`), so `app/db/rls_check.py` stays green.

**R2-02 · Add `account_id uuid references public.web2_accounts(id)` to `public.web2_properties`**, backfilled and then `not null`. The same migration must add the two columns later requirements assume but which **do not exist today** (verified: no `shared_origin`, `link_rel` or `link_found` anywhere in `db/` or `backend/`): `shared_origin boolean not null default false` (used by R2-07), and `link_rel text not null default ''` plus `link_found boolean` (used by R2-16). `public.web2_properties` today carries only the 0018 DDL (`db/migrations/0018_offpage.sql:95-105`) plus the 0028 pipeline columns (`status`, `topic`, `page_type`, `framework`, `target_url`, `body_md`, `external_id`, `error` — `0028_web2_publish.sql:35-55`). Every placement must be attributable to exactly one account; the cross-client similarity scope (R2-10) and the house cap (R2-13) both key off it.

**R2-03 · Add tier and topical scope to the platform catalogue.** `alter table public.web2_platforms add column ownership_tier text not null default 'do_not_use' check (ownership_tier in ('per_client','house','do_not_use'))`, plus `topical_scope text not null default 'niche' check (topical_scope in ('agnostic','developer','research','creative','niche'))` and `terms_position text not null default ''` / `terms_source_url text not null default ''` / `terms_checked_on date` (closes **WEB2-015**). Seed from §3.2. Set `ownership_tier='per_client'` for WordPress.com, Blogger, Tumblr; `'house'` for Telegra.ph; `'do_not_use'` for everything else until a per-client topical match is recorded.

**R2-04 · Eligibility is computed, not configured.** A platform is eligible for a client iff `ownership_tier <> 'do_not_use'` **and** (`topical_scope = 'agnostic'` **or** `topical_scope` matches the client's recorded industry on `public.clients` / `client_business_profile`). **Implementation gap a developer will hit immediately, and must not paper over:** `public.web2_platforms.name` is **free text and deliberately decoupled from the `public.web2_platform` enum** (stated outright in `db/migrations/0062_web2_platforms.sql:18-26`). The enum has **54** values (0018 + the `add value` batches in 0045/0068/0070/0072/0076/0077) while the catalogue holds **90** free-text names, several of which are instance-level and have no enum value at all ("Mastodon (mastodon.social)", "Mastodon (mas.to)", "Bear Blog", "About.me"…). R2-03's tier columns therefore live on rows the publishing path cannot key off directly. The migration must add an explicit `platform_enum public.web2_platform null` mapping column to `public.web2_platforms`, populated only for the 54 names that have an enum value, and eligibility must resolve through it — never through a name string match. The planner (`web2_pipeline.plan`, `web2_pipeline.py:189`) must call this and must refuse to plan an ineligible platform. The status board (WEB2-012) renders three states per platform: **connected · not connected (reason) · not eligible for this client (reason)**.

**R2-05 · Tier assignment rule, implemented as the check that gates R2-03 edits.**
*Per-client (Tier A)* requires **all** of: (1) a documented first-party publish API drivable by a per-client credential, no browser automation; (2) published terms that do not prohibit programmatic posting outright; (3) self-serve signup completable by a human in ≤ 15 minutes without defeating a defence; (4) the property is a client-branded, client-owned asset (client-named subdomain or blog); (5) the page's primary purpose can honestly be genuine content.
*House (Tier B)* requires **all** of: (1) publishing is anonymous or implies no durable personal identity; (2) a shared account misrepresents no authorship; (3) the placement's value is indexation/reference diversity, not link equity; (4) volume is capped (R2-13).
*Do not use (Tier C)* if **any** of: terms prohibit programmatic posting or registration; no publish API (browser-only against a defended signup); free-tier links are nofollow **and** authority is low; the content model is not an article; or our intended use would breach the platform's own content policy for this client's topic.

### Credentials, identity and the `seed_web2_vault` replacement

**R2-06 · Delete `backend/app/cli/seed_web2_vault.py`, `backend/tests/test_seed_web2_vault.py`, and `Settings.web2_house_credentials_json` (`backend/app/config.py:588`).** Do not repair it — its purpose is the retired pattern. Replace with `backend/app/cli/web2_accounts.py` supporting `register` (record a manually-created per-client account and seal its credential under `vault_label = <web2_accounts.id>`), `list`, and `rotate`. The vault convention changes from `label=<client_id>` to `label=<web2_account_id>`; update `integrations/web2_credentials.py` to resolve a publisher from `web2_properties.account_id → web2_accounts.vault_provider/vault_label`.

**R2-07 · Migration path for already-seeded clients.** A one-shot migration script must, for every existing `vault_keys` row with `provider like 'web2:%'`: (a) group rows by the **sha256 of the decrypted secret**; (b) where one secret maps to more than one client label, create **one** `web2_accounts` row with `ownership='house'`, `client_id=null`, re-point it, and mark every `web2_properties` row published through it with `shared_origin=true`; (c) where a secret is unique to one client, create a `per_client` row; (d) delete the duplicate per-client vault rows. Then: **every `web2_properties` row with `shared_origin=true` on a platform now tiered `per_client` is frozen** — no further publishing to it, an operator task is raised per client to re-create the property under a client-owned account, and the client-facing portal must not present a frozen property as an active deliverable. Existing published articles are left in place (deleting them is a bigger signal than leaving them); only new publishing is blocked.

**R2-08 · Registration-data hygiene (fixes §3.5 Finding B).** The signup identity generator is retired for Tier A. Concretely:
1. `web2_signup.py:533-537` must no longer derive Tier-A usernames from the alias. **Account handles for per-client accounts must be operator-entered and derived from the client's brand** (e.g. `leedsdrainageco`), validated against a regex that **rejects any handle containing a platform slug or a hex run of 8 or more characters** — the two current tells. (Corrected: the tell in the code is a **10**-hex-character `sha1(client_id)` prefix, `imap_mailbox.py:71-74`, not a 6-character one; the regex threshold is set at 8 so a truncated variant is still caught.)
2. **Registration email must use the client's own domain** where the client has one (`client_business_profile`), e.g. `web@clientdomain.co.uk`; the shared catch-all (`imap_mailbox.alias_for`) is permitted **only** for `ownership='house'` accounts. Where the client has no domain, the account is not created and an operator task is raised.
3. `web2_accounts.registration_domain` records what was actually used; a report flags any platform where more than **3** per-client accounts share one registration domain.

### The cross-property similarity gate (closes WEB2-007 / WEB2-002)

**R2-09 · Storage.** New migration `db/migrations/0082_web2_similarity.sql`:

```sql
create table public.web2_doc_fingerprints (
  id             uuid primary key default gen_random_uuid(),
  web2_id        uuid not null references public.web2_properties (id) on delete cascade,
  client_id      uuid not null references public.clients (id) on delete cascade,
  account_id     uuid not null references public.web2_accounts (id) on delete cascade,
  platform       public.web2_platform not null,
  body_sha256    bytea  not null,                 -- exact-duplicate gate
  shingle_hashes bigint[] not null,               -- ALL 5-word shingle hashes, sorted+deduped
  shingle_count  int not null,
  heading_hashes bigint[] not null default '{}',  -- normalized H2/H3 skeleton
  anchor_norm    text not null default '',
  status_at_capture public.web2_status not null,
  created_at     timestamptz not null default now()
);
create index web2_doc_fp_client_idx  on public.web2_doc_fingerprints (client_id);
create index web2_doc_fp_account_idx on public.web2_doc_fingerprints (account_id);
create index web2_doc_fp_plat_time_idx on public.web2_doc_fingerprints (platform, created_at desc);
create unique index web2_doc_fp_web2_uq on public.web2_doc_fingerprints (web2_id);

-- Candidate generation: Broder MOD_16 sample only (~1/16 of shingles).
create table public.web2_shingle_index (
  shingle_hash   bigint not null,
  fingerprint_id uuid   not null references public.web2_doc_fingerprints (id) on delete cascade,
  primary key (shingle_hash, fingerprint_id)
);
create index web2_shingle_index_fp_idx on public.web2_shingle_index (fingerprint_id);
```
ENABLE + FORCE RLS, staff-read / service_role-write. **The gate itself must run on the privileged pool** — it is the one place that legitimately reads across tenants, and it must return only a boolean plus a scope label, never another client's text (this is explicitly a "client-invisible" fact per `DANIEL_PROJECT_RECOVERY_SPECIFICATION.md:773`).

**R2-10 · Algorithm, in `backend/app/services/web2_similarity.py` (new, pure, no new dependency).**
1. **Normalize:** strip markdown/HTML, case-fold, collapse whitespace, strip punctuation, **keep stopwords** (stopwords carry the template).
2. **Shingle:** `w = 5` contiguous words; hash each with `hashlib.blake2b(s.encode(), digest_size=8)` → signed 64-bit; dedupe; sort.
3. **Index:** insert the **MOD_16** subset (`h % 16 == 0`) into `web2_shingle_index`.
4. **Candidate generation:** select `fingerprint_id`s sharing **≥ 2** sampled hashes with the draft, restricted to the three scopes below.
5. **Exact score:** for each candidate (cap 200, ordered by shared-sample count desc), compute exact `r = |A ∩ B| / |A ∪ B|` over the full `shingle_hashes` arrays.
6. **Heading score:** Jaccard over `heading_hashes`.
7. **Verdict:** `block` / `warn` / `pass` plus the worst-offending scope and the `web2_id` it collided with.

**Scopes — all three are evaluated, against both `published` and `needs_review` rows:**
- **S1 · same client, all platforms, all time** — `client_id = :client_id`.
- **S2 · same house account, all clients, all time** — `account_id = :account_id` (only meaningful where `ownership='house'`; this is the cross-client axis WEB2-007 names).
- **S3 · same platform, all clients, rolling 90 days** — `platform = :platform and created_at > now() - interval '90 days'`.

**Thresholds (agency policy — see §8 before hardening):**

| Check | Block | Warn | Notes |
|---|---|---|---|
| `body_sha256` equality | any match | — | unconditional, no override |
| Body resemblance `r` (w=5) | `r ≥ 0.25` | `0.15 ≤ r < 0.25` | half of Broder's 0.50 duplicate line |
| Heading-skeleton Jaccard | `≥ 0.60` | `0.45 ≤ x < 0.60` | catches same-outline/different-words templating |
| Anchor string equality within S1 or S2 | any match | — | see R2-14 |

**R2-11 · Wiring.** `web2_pipeline.run_write` (`web2_pipeline.py:477`) must call the gate **after** drafting and **before** parking at `needs_review`. A `block` sets `status='needs_review'` with a machine-readable `error` naming the check, the scope and the colliding `web2_id`, and the row **cannot be approved** until re-drafted — the approval endpoint must re-run the gate and refuse on `block`. A `warn` is surfaced in the approval UI and requires an explicit acknowledgement. Fingerprints are written on **approval**, not on draft, so rejected drafts do not pollute the corpus; the draft's own fingerprint is compared but not persisted until approved.

**R2-12 · Performance budget.** A 1,200-word article yields ~1,196 shingles → ~75 MOD_16 probes. The corpus figure below (**100 clients × 10 properties × 4 articles/year ≈ 4,000 documents**) is a deliberate **6× over-estimate** and does not describe the delivery model this record adopts: under D-16 plus R2-13's own caps (4 properties per client per campaign, 40 campaign clients) the real corpus is ~640 documents/year, as §6 uses. The over-estimate is kept because sizing storage and latency against a corpus the caps rule out is the safe direction. At 4,000 documents, `web2_shingle_index` holds ≈ 4,000 × 75 = **300,000 rows** and `web2_doc_fingerprints.shingle_hashes` ≈ 4,000 × 1,196 × 8 bytes ≈ **38 MB**. Candidate scoring is ≤ 200 set intersections of ~1,200 elements. Budget: **< 250 ms p95** on the existing VPS Postgres, no new service. Assert this in a load test at 10× corpus (40,000 docs) before hardening.

### Footprint controls

**R2-13 · Pacing and caps.** All values are **agency policy defaults**, stored in **`public.workspace_settings`** — the singleton `id = 1` settings row (`db/migrations/0025_settings.sql:38`, read/written through `backend/app/db/settings_repo.py:42`); **there is no `public.settings` table**, so a developer must add columns there (or a dedicated `web2_pacing` settings table) rather than assume one exists. Tunable without a deploy, enforced in the publish scheduler, and derived from one principle: *a property must look like a real, low-volume brand blog.*

| Control | Default | Enforced where |
|---|---|---|
| Min interval, same property | **7 days** | publish scheduler |
| Min interval, same client + same platform | **72 hours** | publish scheduler |
| Min interval, same client, any platform | **24 hours** | publish scheduler |
| Max publishes per client per day | **1** | publish scheduler |
| Max publishes per **house account** per day | **3** | keyed on `web2_accounts.id` |
| Max publishes per **house account** per rolling 30 days | **20** | keyed on `web2_accounts.id` |
| Max **properties** per house account (`max_properties`) | **10** | hard cap; refuse the 11th (closes **WEB2-008**) |
| Max properties per client per campaign | **4** | planner |
| Publish jitter | uniform **0–36 h** added to the scheduled slot | reuse `diversify_footprint`'s `delay_seconds`, raise `max_delay_seconds` from `2*_DAY` (`web2_publishers.py:3170`) |
| No second property for a client within | **14 days** of the first | planner |
| Platform-published rate limits | honour where documented — e.g. Write.as free "3 – 15 per day" [writeas-pricing] | per-adapter |

**R2-14 · Anchor rules (closes WEB2-014 / DATA-017), with no invented ratio.**
1. **Hard rule: zero exact-match commercial anchors.** Every Web 2.0 anchor must be one of `brand` · `brand + location` · `bare URL` · `natural in-sentence phrase`. A validator rejects any anchor whose normalized form equals or contains the client's target keyword string for the campaign. **Justification, restated correctly:** Google's link-spam list names "**Using automated programs or services to create links to your site**" [google-spam-policies], and every Web 2.0 link we place is exactly that — a self-made link created by an automated program. (The "keyword-rich" item in the same list is scoped to links *embedded in widgets* and is **not** load-bearing here; see §3.1.) The rule stands on the automation item, which needs no ratio and no interpretation.
2. **Uniqueness:** no anchor string may repeat within a client's Web 2.0 set (S1) or within a house account (S2). Enforced by the anchor check in R2-10.
3. **Reporting, not gating:** render the client's Web 2.0 anchor distribution alongside the distribution of their **imported organic backlink profile** (the Ahrefs/SEMrush import path already in scope, `DANIEL_PROJECT_RECOVERY_SPECIFICATION.md:258`). The comparison is the signal; there is no published target number to gate on, and the product must say so on the surface where it is displayed.

**R2-15 · Inter-property linking is banned.** A draft is rejected if any outbound URL in its body matches any `web2_properties.post_url` for **any** client, or any `web2_accounts.property_url`. Exactly **one** link to the client's money site per article (WEB2-005, already stated); all other outbound links must be to genuine third-party references. Implemented as a URL-set check in the same pass as R2-10. A property graph with edges between properties is the single clearest network tell available to a platform or to Google.

**R2-16 · Measure `rel`, never assume it (see §3.4).** Extend `verify_live_and_indexable` (`web2_pipeline.py:427`) to fetch the published URL, locate the anchor whose href matches `target_url`, and persist `link_rel text` and `link_found boolean` on `web2_properties`. Re-check on the link-liveness schedule (**WEB2-013**): **every 14 days** for the first 90 days, monthly thereafter; a link that disappears or gains `nofollow` raises an alert and sets `web2_accounts.health='degraded'`.

**R2-17 · Automation ceiling, restated in code.** Web 2.0 publishing is capped at **L3**. The approval endpoint must accept **one `web2_id` per call** — no batch-approve endpoint may exist for this resource type, because Tumblr's API License requires per-post explicit permission [tumblr-api-license] and the ceiling is a property of the task class. Account **registration** for Tier A is L0/manual: `BrowserSignupProvider` is disabled for `ownership='per_client'` platforms and its `blocked` result routes to an operator task (**WEB2-017**, one-time OAuth at campaign start per D-16).

---

## 6. Cost model at 100 clients

Assumption set: 100 clients, Web 2.0 running per-campaign (D-16) — assume **40 clients on a campaign in a given year**, 4 properties each, 4 articles per property per year.

**Platform subscription cost — the reason Ghost is out.**

| Platform | Unit price | 40 clients | Source |
|---|---|---|---|
| WordPress.com free subdomain | **$0** | $0 | [wpcom-tos] |
| Blogger / blogspot | **$0** | $0 | [blogger-api] |
| Tumblr | **$0** | $0 | [tumblr-guidelines] |
| Telegra.ph (house) | **$0** | $0 | anonymous, no account |
| *Ghost(Pro) Starter, if used* | **$18/mo billed yearly** | 40 × $18 × 12 = **$8,640/yr** | [ghost-pricing] |
| *Write.as Pro, if used* | **$6/mo annual** | 40 × $6 × 12 = **$2,880/yr** | [writeas-pricing] |

**Ghost and Write.as are excluded on this arithmetic alone**: $8,640/yr and $2,880/yr against a $0 alternative of equal or higher authority. *(How many properties each paid plan would actually yield is `[UNVERIFIED]` — neither pricing page states a per-plan site/blog count in what was fetched on 2026-08-23. It does not change the exclusion: the comparator is $0.)* The chosen four-platform set carries **$0/yr in platform subscription cost**.

**Similarity gate marginal cost: $0.** Pure Python stdlib (`hashlib.blake2b`) plus Postgres already running. No new dependency, no external API, no vector database. Storage at 10× the projected corpus (40,000 documents) is ≈ 380 MB of `bigint[]` plus a 3M-row index — comfortably inside one VPS Postgres.

**Rejected embeddings alternative, for comparison:** 40 clients × 4 properties × 4 articles = **640 drafts/yr**; at ~1,600 tokens each = 1.02M tokens; `voyage-3.5` at **$0.06/M** [voyage-pricing] = **$0.06/yr** in embedding calls. The cost was never the objection — §3.6 is. Pinecone hosting cost is **[UNVERIFIED]** and irrelevant, since the option is rejected on correctness.

**Human cost — the real number, corrected.** An earlier draft read D-5 as "~10–15 minutes per client **per platform**" and multiplied by three. **Both source documents say otherwise.** `DECISIONS_LOG.md:110` reads "roughly 10–15 minutes per client **per campaign**", and `DECISIONS_REQUIRED.md:92` is explicit: *"one manual OAuth or signup run per client per high-authority platform. **At 5 platforms that is roughly 10–15 minutes per client, one time.**"* — i.e. 10–15 minutes is the **total** for the whole set, not the per-platform unit. Corrected arithmetic: 40 campaign clients × 12.5 min ≈ **8 hours per year** of account setup, one-time at campaign start. Plus L3 approval: 640 articles × ~4 min review ≈ **43 hours per year**. Total ≈ **51 operator-hours/year**, not 68. The approval load, not the setup, is the dominant cost — and it is the load-bearing safety control, so it cannot be optimised away. *(If Danyal's own experience is that 10–15 min is per platform rather than per client, setup rises to ~25 h and the total to ~68 h; the source text does not support that reading and this is worth one confirming question.)*

**Per-unit check against the `[CIT-ECON]` ≤10¢ marginal commitment:** the marginal *machine* cost per Web 2.0 article is the Claude drafting call (already metered through `CostGate`, `web2_pipeline.py:68`) plus $0 for the gate, $0 for the platform. Whether the drafting call lands under 10¢ is **R1/content's** number, not this track's — **[UNVERIFIED here]**; this track adds **zero** marginal cost to it.

---

## 7. Risks and failure modes

1. **A per-client account is suspended anyway.** WordPress.com terminates "at any time, with or without cause or notice" [wpcom-tos]. Blast radius is now one client (that is the point of the tiering), but the client loses an asset we told them they own. *Mitigation:* R2-16 health monitoring; the portal must never describe a Web 2.0 property as a guaranteed permanent asset.
2. **The 0.25 threshold is wrong in either direction.** Too low and every draft blocks and operators learn to override; too high and templating ships. This is the single highest-uncertainty number in the record. *Mitigation:* §8 calibration is a **precondition** to making the gate hard; ship it as warn-plus-mandatory-acknowledgement first, exactly as D-4 does for the content QA gate.
3. **The gate cannot see the identity footprint.** §3.5 Finding B is invisible to any content-similarity check. If R2-08 is skipped, the module remains linkable across clients no matter how distinct the prose is. *This is the requirement most likely to be dropped under schedule pressure and the one that would most quietly re-create the original defect.*
4. **Historic shared-origin properties are already published.** R2-07 freezes them rather than deleting them. Frozen properties published from one house account on a now-Tier-A platform remain a live, existing correlation we cannot retract. *Mitigation:* record them explicitly in the hand-over documentation as accepted, pre-existing risk.
5. **A platform silently changes its terms.** All of §3.2 is a 2026-08-23 snapshot. Hashnode's ToU is dated 15 Feb 2026 (~6 months before this record) and WordPress.com's 10 Apr 2026 (~4.5 months); both are recent revisions. *Mitigation:* `terms_checked_on` on `web2_platforms` (R2-03) with a **90-day** staleness alert routed to Policy Radar; a platform whose terms are >180 days unchecked is auto-demoted to `do_not_use`.
6. **Operators route around the ceiling.** L3 with 640 approvals/year invites a "approve all" habit. *Mitigation:* R2-17's one-`web2_id`-per-call constraint is structural, not advisory.
7. **Narrowing to four platforms reads as a capability regression to the client.** It is a regression against WEB2-001-as-written. *Mitigation:* present it as the §3.3 reframing with the terms evidence attached; the catalogue and adapters remain, and a client whose topic fits unlocks more.
8. **Telegra.ph is the sole house platform and is fully anonymous** — which is also why it carries near-zero authority. If it proves worthless in measurement, the house tier becomes empty. That would be a correct outcome, not a failure.

---

## 8. Open items

| # | Unsettled | Exactly what would settle it |
|---|---|---|
| **O-1** | **The r ≥ 0.25 body threshold and the 0.60 heading threshold are unvalidated policy numbers.** No published source supports them. | Build a golden set of **60 article pairs** drawn from the existing published corpus and from deliberately-templated drafts, graded independently by two humans as *distinct / uncomfortably similar / templated*. Compute the resemblance distribution per class and set the block at the point where the *distinct* class's 99th percentile sits below it. Until then the gate ships as **warn + mandatory acknowledgement**, never hard. |
| **O-2** | **Shingle size w = 5 and sample modulus m = 16 are chosen, not validated — and they are *not* Broder's.** Corrected on 2026-08-23: the paper's own production parameters are stated outright — *"We sketched all of the documents with 10 word long shingles to produce 40 bit (5 byte) shingle fingerprints"* and *"We use the 'modulus' method for selecting shingles with an m of 25"* [broder-clustering]. So **w = 10, m = 25** is the primary-sourced pair; w = 4 appears only in the paper's illustrative example. Our w = 5 is defensible for short articles (more sensitive to local rewording) but is unsupported by any source. | Run the O-1 golden set at **w ∈ {4, 5, 7, 10}** and pick the w that maximises separation between the *distinct* and *templated* classes; record the chosen value with its measured separation, and state plainly in the code comment that it is ours, not Broder's. Re-check that m = 16 does not degrade candidate recall against exhaustive scoring on the same set. |
| **O-3** | **Actual `rel` attribute on the placed link for WordPress.com, Blogger, Tumblr and Telegra.ph.** Reports conflict for Mastodon [mastodon-rel]; nothing authoritative was found for the four chosen platforms. | R2-16 settles it by measurement: publish one property per platform and parse the rendered anchor. This is a build task, not a research task, and must be done before any client-facing claim about link value. |
| **O-4** | **Documented API rate limits / quotas for the Blogger API v3 and the WordPress.com REST API.** Re-verified 2026-08-23: the Blogger "Using the API" page documents OAuth 2.0 and the scope `https://www.googleapis.com/auth/blogger` but carries **no quota or rate-limit figures at all** [blogger-api]; WordPress.com's are **[UNVERIFIED]** (its pages refuse automated fetch — see §3.2). | Blogger: read the per-project quota in the Google Cloud console for the Blogger API after enabling it. WordPress.com: instrument the adapter to log `429`/`Retry-After` and derive the limit empirically over the first campaign. Our pacing (R2-13) is far below any plausible limit, so this is a monitoring item, not a blocker. |
| **O-5** | **Whether Tumblr's "Mass Registration or Automation" clause is enforced against per-post-approved API posting.** The API License §(s) appears to permit it; the User Guidelines appear to forbid it. Both are Tumblr's own documents and they are in tension. | Ask Tumblr support/developer relations in writing and keep the reply. Until then Tumblr ships at strict per-post L3 with manual registration, which is the reading most favourable to compliance. If Danyal would rather not carry the ambiguity, **dropping Tumblr leaves a two-platform per-client tier** and costs little. |
| **O-6** | **Whether Danyal's Fiverr client base is predominantly local-business** (which drives the topical-eligibility default). Two existing questions bear on it: `OPEN_QUESTIONS.md:156-157` (Q-16, *markets* beyond US/UK/CA/AU) and — the closer match — `OPEN_QUESTIONS.md:159-160` (Q-17, *"Which niches, for niche-directory selection?"*, which already notes the audit engine supports client profiles general / local / ecommerce / saas / content, i.e. the taxonomy R2-04 needs). | Answerable by Danyal from his own client list. If a meaningful share are SaaS/dev-tools, the eligible set widens materially at no additional safety cost. |
| **O-7** | **Whether the `[CIT-ECON]` document delivered to Danyal on 17 July 2026 should be corrected.** It states a Google enforcement event that §3.1 shows does not exist. Note the same false premise is load-bearing in **two** places inside the repo's own spec — `DANIEL_PROJECT_RECOVERY_SPECIFICATION.md:1235` and `:420` — and those two are correctable without touching the client's copy. | A decision by the project owner. Recording it here is not the same as correcting a document already in the client's hands, and the module's non-negotiable-quality framing in that document remains sound even though its stated justification is wrong. |

---

## 9. Sources

**Google — primary**
- [google-spam-policies] https://developers.google.com/search/docs/essentials/spam-policies — accessed 2026-08-23 (page states Last updated 2026-05-15 UTC)
- [google-ranking-history] https://status.search.google.com/products/rGHU1u87FJnkP6W2GwMi/history — accessed 2026-08-23
- [google-qualify-links] https://developers.google.com/search/docs/crawling-indexing/qualify-outbound-links — accessed 2026-08-23 (page states Last updated 2025-12-10 UTC). **Not cited anywhere in the body of this record** — retained only as background for §3.4's `rel` measurement; it supports no claim above.
- [blogger-policy] https://www.blogger.com/go/contentpolicy — accessed 2026-08-23
- [blogger-api] https://developers.google.com/blogger/docs/3.0/using — accessed 2026-08-23

**Platform terms — primary**
- [wpcom-guidelines] https://wordpress.com/support/user-guidelines/ — **HTTP 403 to automated fetch on 2026-08-23**; quotation corroborated only via a search engine's index of this URL. Needs a human to open it.
- [wpcom-tos] https://wordpress.com/tos/ — **HTTP 403 to automated fetch on 2026-08-23**; "Last Updated: April 10, 2026" and the termination clause corroborated only via a search engine's index of this URL. Needs a human to open it.
- [tumblr-guidelines] https://raw.githubusercontent.com/tumblr/policy/master/user-guidelines.txt — accessed 2026-08-23 (Tumblr's own published policy repository)
- [tumblr-api-license] https://raw.githubusercontent.com/tumblr/policy/master/api-license-agreement.txt — accessed 2026-08-23
- [devto-terms] https://dev.to/terms — accessed 2026-08-23
- [hashnode-terms] https://hashnode.com/terms — accessed 2026-08-23 (Effective / Last Updated: February 15, 2026)
- [github-aup] https://docs.github.com/en/site-policy/acceptable-use-policies/github-acceptable-use-policies — accessed 2026-08-23
- [bluesky-guidelines] https://bsky.social/about/support/community-guidelines — accessed 2026-08-23
- [medium-api-docs] https://github.com/Medium/medium-api-docs — accessed 2026-08-23 (repository archived 2 March 2023)
- [dreamwidth-create] https://www.dreamwidth.org/create — accessed 2026-08-23
- [dreamwidth-faq105] https://www.dreamwidth.org/support/faqbrowse?faqid=105 — accessed 2026-08-23

**Pricing — primary**
- [ghost-pricing] https://ghost.org/pricing/ — accessed 2026-08-23
- [writeas-pricing] https://write.as/pricing — accessed 2026-08-23
- [voyage-pricing] https://docs.voyageai.com/docs/pricing — accessed 2026-08-23

**Algorithms — primary**
- [broder-clustering] Broder, Glassman, Manasse, Zweig, "Syntactic Clustering of the Web", *Computer Networks and ISDN Systems* 29 (1997) 1157-1166 — https://cadmo.ethz.ch/education/lectures/FS18/SDBS/papers/broder.pdf — accessed 2026-08-23. Quotations verified against the WWW6 HTML edition of the same paper, https://www.ambuehler.ethz.ch/CDstore/www6/Technical/Paper205/Paper205.html (the PDF above is not machine-readable via automated fetch).
- [manku-simhash] Manku, Jain, Das Sarma (Google Inc.), "Detecting Near-Duplicates for Web Crawling", WWW 2007 — https://research.google.com/pubs/archive/33026.pdf — accessed 2026-08-23

**Secondary (labelled as such in text)**
- [sej-sra] https://www.searchenginejournal.com/google-confirms-site-reputation-abuse-update/515584/ — accessed 2026-08-23; **article dated 2024-05-06**. Supports "manual-action-only" and "algorithmic portion coming soon"; does **not** support subdirectory/subdomain scoping.
- [seo-kreativ-mar2026] https://www.seo-kreativ.de/en/blog/google-march-2026-spam-update/ — accessed 2026-08-23
- [emgi-anchors] https://emgigroup.com/blog/anchor-text-saas-link-building/ — accessed 2026-08-23
- [basesearch-anchors] https://www.basesearchmarketing.com/blog/right-ratio-of-exact-match-anchor-text-in-link-building/ — accessed 2026-08-23
- [mastodon-rel] https://github.com/mastodon/mastodon/issues/5480 — accessed 2026-08-23

**Repository (ground truth for current-implementation claims)**
- `backend/integrations/web2_publishers.py:201-266` (**54** platform constants), `:268` (`WEB2_PLATFORMS`, 54 members), `:289` (`DRAFT_ONLY_PLATFORMS = {Medium}`), `:295-351` (`PLATFORM_CREDENTIAL_FIELDS`, **53** credential shapes — all but Medium), `:3163-3210` (`diversify_footprint`, `max_delay_seconds` default at `:3170`), `:36-39` (Medium draft-only docstring)
- `backend/app/cli/seed_web2_vault.py:6-8` (house-account docstring), `:69-100` (`build_plan`), `:103-123` (`execute_plan`)
- `backend/integrations/web2_signup.py:533-537` (alias → username derivation), `:89-95` (`_username_from_alias`)
- `backend/integrations/imap_mailbox.py:66-69` (`_slug`), `:71-74` (`_short`, sha1[:10]), `:77-84` (`alias_for`)
- `backend/app/services/content_qa.py:611-618` (`_internal_dup_originality` — an existing 5-word shingle helper), `backend/app/modules/competitor_intel/service.py:317` (`jaccard_overlap` — an existing Jaccard)
- `db/migrations/0025_settings.sql:38` (`public.workspace_settings`; there is no `public.settings`)
- `backend/app/services/web2_pipeline.py:7,22` (human review gate), `:189` (`plan`), `:427` (`verify_live_and_indexable`), `:477` (`run_write`)
- `backend/app/config.py:588` (`web2_house_credentials_json`)
- `backend/pyproject.toml:49-58` (Voyage/Pinecone deliberately excluded from the deployment image)
- `db/migrations/0018_offpage.sql:95-105` (`web2_properties` DDL), `:125-126` (its ENABLE + FORCE RLS), `db/migrations/0028_web2_publish.sql:28-55` (`web2_status` enum + pipeline columns incl. `error`), `db/migrations/0062_web2_platforms.sql` (catalogue DDL + `web2_auth_type` enum), `0063_web2_platforms_seed.sql`, `0066_web2_platforms_more.sql` (nofollow notes for GitHub Gist, GitLab Snippets, Mastodon, Misskey, Pixelfed, Lemmy, Pastebin) — **110 row literals across `0063`/`0066`/`0068`/`0070`/`0072`/`0076`/`0077` resolving to 90 unique catalogue rows** (48 `api`, 32 `automation`, 7 `oauth`, 3 `anonymous`)
- `docs/recovery/DECISIONS_LOG.md:49-57` (D-16), `:98-111` (D-5; the per-client platform list is at `:101`, the 10–15 min figure at `:110`, the `seed_web2_vault` finding at `:111`), `docs/recovery/DECISIONS_REQUIRED.md:84-96` (D-5 rationale; the "at 5 platforms … per client, one time" costing at `:92`)
- `docs/recovery/DANIEL_PROJECT_RECOVERY_SPECIFICATION.md:1200-1261` (§17 Web 2.0), `:1212` (eight live-credential platforms), `:1218` ("Bot detected" / Dreamwidth invite code), `:1223-1229` (§17.3 automation classification), `:1235` (the `[CIT-ECON]` March-2026 quotation), `:1247` (WEB2-7, "single most important safety control"), `:420` (the same false premise re-used), `:773` (client-invisible facts), `:258` (backlink imports)
- `docs/recovery/REQUIREMENTS_TRACEABILITY.md:302-318` (WEB2-001…017; WEB2-001 at `:302`, WEB2-007 at `:308`, WEB2-016 at `:317`), `:441-442` (DATA-016/017)
- `docs/recovery/OPEN_QUESTIONS.md:156-157` (Q-16 markets), `:159-160` (Q-17 niches)

---

## Verification pass — 2026-08-23

Adversarial verification of every repository citation and every external factual claim in this record. The instruction was to refute, not to agree. **Verdict: the record's central findings survive — §3.1's refutation of the "March 2026 Site Reputation Abuse update" is exactly right, the platform-terms table is quotation-accurate, and the algorithm choice is sound — but nine repository claims and four external claims were wrong and are corrected above.**

### Sources actually fetched (not merely cited)

| Source | Result |
|---|---|
| [google-spam-policies] | **Fetched.** SRA definition, UGS first example, both link-spam items and "Last updated 2026-05-15 UTC" all confirmed verbatim. **Two quotations were wrong** — see corrections 10 and 11. |
| [google-ranking-history] | **Fetched.** All six 2026 entries confirmed with matching dates and durations (Discover 5 Feb; spam 24 Mar, 19h30m; core 27 Mar; core 21 May; spam 24 Jun; spam 18 Aug). No update named for site reputation abuse in any year. Most recent link spam update = December 2022 (14 Dec, 29 days). **§3.1 is fully confirmed.** |
| [tumblr-guidelines] · [tumblr-api-license] | **Fetched.** "Mass Registration or Automation" confirmed verbatim. §(o) and §(s) confirmed verbatim including sub-parts (i)/(ii); clause letters match their headings. |
| [ghost-pricing] | **Fetched.** Starter = "$18 USD / mo Billed yearly" confirmed. No separate monthly price shown. |
| [writeas-pricing] | **Fetched.** All four claims confirmed: free tier "Closed for now"; "3 – 15 per day"; "Do-follow links" present for Pro/Team and "—" for Free; Pro from $6/mo annual, $9/mo monthly. |
| [voyage-pricing] | **Fetched.** voyage-3.5 = "$0.00006 per thousand tokens" = $0.06/M confirmed. Added: it now sits under "Older models" with no free-token allowance. |
| [devto-terms] · [hashnode-terms] · [github-aup] · [bluesky-guidelines] · [blogger-policy] · [blogger-api] · [medium-api-docs] · [dreamwidth-create] · [seo-kreativ-mar2026] · [sej-sra] | **All fetched.** Quotations confirmed verbatim. GitHub's "no multiple-account prohibition" confirmed. Blogger API page confirmed to carry no quota figures. Medium repo archived 2 March 2023 confirmed. |
| [broder-clustering] | **Fetched** (via the WWW6 HTML edition; the PDF is not machine-readable). Definitions, "50% resemblance" and 30,000,000 documents confirmed verbatim — **and the paper's own w = 10 / m = 25 parameters found, refuting O-2 as written.** |
| [manku-simhash] | **Fetched and text-extracted from the PDF.** All three quotations confirmed verbatim, including "Luckily, Charikar's simhash technique with 64-bit fingerprints seems to work well in practice for a repository of 8B web pages." |
| [wpcom-guidelines] · [wpcom-tos] | **NOT fetched — HTTP 403 to automated retrieval.** Corroborated only through a search engine's index of the same primary URLs. Flagged in §3.2 and §9. |

### Corrections made

1. **§2 — platform counts were reversed.** The record said "53 platform constants and 54 credential shapes". The repository has **54** constants (`web2_publishers.py:201-266`; `WEB2_PLATFORMS` at `:268` has 54 members) and **53** credential shapes (`:295-351` — every constant except `PLATFORM_MEDIUM`). The original grep missed `PLATFORM_FC2` because its name contains a digit.
2. **§2 — catalogue row count was wrong.** "67 seeded catalogue rows" is not what the migrations contain: **110 row literals** across the seven seed files, resolving to **90 unique platform rows** (48 `api`, 32 `automation`, 7 `oauth`, 3 `anonymous`) because later batches re-insert earlier names under `on conflict (name) do update`.
3. **§2 — "roughly five platforms have a working house credential" was wrong.** The spec records **eight** (`:1212`, per `[CIT-CRED]` §3): Telegra.ph, dev.to, Mataroa, Mastodon, Micro.blog, GitHub Pages, GitLab Pages, Hashnode. Propagated to the dev.to row in §3.2.
4. **§2 — a quotation was attributed to the wrong document.** "The single most important safety control in the module" does **not** appear in `REQUIREMENTS_TRACEABILITY.md:308`; it is the spec's WEB2-7 gloss at `DANIEL_PROJECT_RECOVERY_SPECIFICATION.md:1247`. WEB2-007's actual text is now quoted instead.
5. **§2 — the "grep returns no production hit" claim was false.** `backend/app/services/content_qa.py:611-618` already builds 5-word shingles and `backend/app/modules/competitor_intel/service.py:317` already implements a Jaccard. The true, narrower claim — no *cross-document, cross-client* gate and no persisted fingerprint — replaces it, and both existing primitives are now named so the build reuses rather than re-invents them.
6. **§3.1 — the `[CIT-ECON]` quotation's line number was wrong** (`:1246` → `:1235`), and the same false premise is relied on a **second** time at `:420`, which the record had missed. Both now recorded, and O-7 updated.
7. **§3.1 / §9 — [sej-sra]'s subdirectory/subdomain scoping is not in the source.** The article (dated **2024-05-06**) supports manual-action-only enforcement and "the algorithmic portion … is coming soon"; it says nothing about subdirectory/subdomain targeting. That clause is now marked `[UNVERIFIED]` with what would settle it.
8. **§3.2 — Squarespace is not in the catalogue.** It appears only in WEB2-016 and spec `:1217`, both of which already exclude it. Removed from the "catalogued `automation`" row; the other five names in that row were confirmed present with `auth_type='automation'`.
9. **§3.2 / R2-02 — three columns the requirements assume do not exist.** No `shared_origin`, `link_rel` or `link_found` anywhere in `db/` or `backend/`. R2-02 now specifies them, so R2-07 and R2-16 are implementable without a developer inventing schema.
10. **§3.1 — the "not site reputation abuse" quotation was a paraphrase presented as verbatim.** Google's actual wording is "Sites designed to allow user-generated content, such as a forum website or comment sections", not "User-generated content platforms like forums or comment sections". The finding it supports is unchanged.
11. **§3.1 / R2-14 — "keyword-rich … links" was a misleading ellipsis.** The policy item reads in full "Keyword-rich, hidden, or low-quality links embedded in widgets" — scoped to widgets. R2-14's hard zero-exact-match rule is now justified on "Using automated programs or services to create links to your site", which is squarely on point and needs no interpretation. **The rule itself is unchanged; only its stated basis is corrected.**
12. **§3.2 / §3.5 — the Blogger ownership-concealment clause was quoted without its qualifier.** The sentence continues "…such as misrepresenting or intentionally concealing your country of origin or other material details about yourself when directing content about politics, social issues, or matters of public concern to users in a country other than your own." Reading it as a direct prohibition on our username scheme overstated it; that support is withdrawn and R2-08 now rests on the §3.5 enumerability argument, which stands on the code alone.
13. **§3.5 / R2-08 — the hash-run length was wrong.** `imap_mailbox._short` returns a **10**-hex-character `sha1` prefix (`:71-74`), not 6. The R2-08 validator regex is retargeted at hex runs of 8 or more.
14. **§3.6 / O-2 — Broder's own parameters refute what O-2 claimed.** O-2 said the production shingle size was `[UNVERIFIED]`; the paper states it: *"We sketched all of the documents with 10 word long shingles…"* and *"…the 'modulus' method for selecting shingles with an m of 25."* Our w = 5 / m = 16 are now labelled as ours, not Broder's, and O-2's sweep includes w = 10.
15. **§4 — "~12 catalogue entries have no publish API" was wrong.** **32** of the 90 catalogue rows carry `auth_type='automation'`.
16. **Header / §3.2 / §4 — D-5 was mis-cited three ways.** D-5's per-client list (`DECISIONS_LOG.md:101`) is WordPress.com · Blogger · Tumblr · Ghost · Hashnode · GitHub Pages · GitLab Pages — **dev.to is not in it**, and D-5 decides *account ownership only*, not automation depth. The "fully automated publishing" position this record contradicts is the spec's §17.3 (`:1225`). The header, the Tumblr row and the options table now attribute each contradiction to the document that actually holds it.
17. **§6 — the human-cost figure was inflated ~3×.** The record read D-5 as "10–15 minutes per client **per platform**". `DECISIONS_LOG.md:110` says "per client per **campaign**" and `DECISIONS_REQUIRED.md:92` is explicit: *"At 5 platforms that is roughly 10–15 minutes per client, one time."* Setup drops from ~25 h/yr to **~8 h/yr** and the total from 68 to **~51 operator-hours/year**. The alternative reading is flagged as one confirming question, not assumed.
18. **R2-13 — `public.settings` does not exist.** The real singleton is `public.workspace_settings` (`db/migrations/0025_settings.sql:38`, read via `settings_repo.py:42`).
19. **R2-04 — the eligibility lookup as written cannot be implemented.** `web2_platforms.name` is free text and deliberately decoupled from the `public.web2_platform` enum (`0062_web2_platforms.sql:18-26`): 90 catalogue names against 54 enum values, several catalogue rows being instance-level names with no enum value. R2-04 now requires an explicit `platform_enum` mapping column.
20. **R2-12 — the corpus assumption contradicted the record's own caps.** 100 clients × 10 properties is ruled out by R2-13's 4-properties-per-client cap and §6's 40-campaign-client figure (~640 docs/yr). Kept as a deliberate 6× over-estimate, now labelled as such so nobody reads it as the delivery model.
21. **§3.2 — Dreamwidth's `/create` carries an anti-spam CAPTCHA** (observed on the live form). Added, because it independently puts automated registration behind the no-CAPTCHA-evasion rule. Also noted: the live form shows **no invite-code field**, which contradicts spec `:1218` and should be corrected there.
22. **Minor citation drift corrected**: Medium draft-only docstring `:39-43` → `:36-39` (plus `:289` for `DRAFT_ONLY_PLATFORMS`); `build_plan` `:69-101` → `:69-100`; `execute_plan` `:103-124` → `:103-123`; `_username_from_alias` file disambiguated; D-5 range `:95-115` → `:98-111`; spec §17 range `:1200-1266` → `:1200-1261`; §7's "both within six months" made accurate; §1's "~49 adapters" → "~50"; §9's repository list rebuilt against the files.

### Repository claims checked and found **correct** (not changed)

`web2_publishers.py:3163-3210` and `:3170` (`diversify_footprint`, `max_delay_seconds = 2*_DAY`) · `seed_web2_vault.py:6-8` docstring quotation and `:103-123` writing `json.dumps(dict(house[entry.platform]))` under `label=entry.client_id` · `web2_signup.py:533`, `:537`, `:89-95` · `imap_mailbox.py:84` alias f-string · `web2_pipeline.py:7`, `:22`, `:68`, `:189`, `:427`, `:477` · `config.py:588` · `pyproject.toml:49-58` including the quoted comment · `0018_offpage.sql:95-105` and `:125-126` · `0028_web2_publish.sql:28-55` · the nofollow assertions in `0066` for GitHub Gist, GitLab Snippets, Mastodon, Lemmy, Pixelfed and Pastebin · `REQUIREMENTS_TRACEABILITY.md:302`, `:308`, `:317`, `:441-442` · `DECISIONS_LOG.md:49-57` (D-16) and `:111` · `DECISIONS_REQUIRED.md:84-96` · spec `:773`, `:258`, `:1204`. Also confirmed sound: `public.web2_platform` has been grown to **54** values across 0018/0045/0068/0070/0072/0076/0077, so R2-01's use of the enum is valid.

### Does the decision still follow?

**Yes.** No correction touches the load-bearing chain: the four-platform eligible set rests on directly-fetched, verbatim-confirmed terms from dev.to, Hashnode, GitHub, Tumblr, Bluesky, Blogger and Write.as; the L3 ceiling rests on Tumblr §(s) and Hashnode's own AI-review requirement, both confirmed; the $0 platform cost rests on confirmed Ghost and Write.as pricing; the shingling choice rests on confirmed Broder and Manku text. Two rejections were re-based rather than weakened — R2-14's anchor rule and R2-08's identity rule — and both now rest on stronger ground than before. The standing constraints hold: L3 with a structural one-`web2_id`-per-call limit, no CAPTCHA evasion (reinforced by the Dreamwidth finding), no Kubernetes, and every unsourced number either labelled agency policy or marked `[UNVERIFIED]`.

### Still `[UNVERIFIED]` after this pass, and why

| Item | Why it could not be settled here |
|---|---|
| **WordPress.com's User Guidelines quotation, its ToS date and its termination clause** | Both pages return HTTP 403 to automated fetch. Corroborated via search index only. **A human must open both URLs and confirm** before this is relied on in a client-facing or legal context — WordPress.com is the highest-value platform in the chosen set. |
| **Whether SRA manual actions are scoped to the offending subdirectory/subdomain** | The cited SEJ article does not say it. Needs Google's manual-actions documentation or a dated Search Central statement. |
| **The r ≥ 0.25 and 0.60 thresholds** | Unchanged from O-1: agency policy, no published source, calibration is a precondition to hardening the gate. Correctly labelled already. |
| **w = 5 and m = 16** | Now known *not* to be Broder's values. O-2's sweep settles them. |
| **WordPress.com REST API quotas** | Not obtainable without an account; O-4's empirical `429`/`Retry-After` approach stands. Blogger's absence of published quotas is now confirmed. |
| **Per-plan property counts for Ghost(Pro) Starter and Write.as Pro** | Neither pricing page stated one in what was fetched. Does not affect the exclusion, whose comparator is $0. |
| **Actual `rel` on the four chosen platforms** | Unchanged from O-3: settled by measurement (R2-16), not research. |
| **Which reading of "10–15 minutes" D-5 intends** | `DECISIONS_REQUIRED.md:92` clearly means per client one time across 5 platforms; if Danyal's lived experience differs, the total moves from ~51 to ~68 operator-hours/year. One question to the owner. |
| **Whether Tumblr enforces "Mass Registration or Automation" against per-post-approved API posting** | Unchanged from O-5: both documents are Tumblr's and they are in tension. Only Tumblr can resolve it. |
