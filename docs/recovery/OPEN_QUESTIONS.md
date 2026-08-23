# OPEN QUESTIONS — Daniel Project Recovery

**Companion to** `DANIEL_PROJECT_RECOVERY_SPECIFICATION.md`
**Compiled:** 2026-08-23
**Purpose:** every point where the evidence is insufficient to determine the correct answer. Nothing here has been silently resolved.

Each question states: what is unclear · why it matters · what the evidence says on each side · what happens if it stays unanswered · who can answer it.

**Status key:** 🔴 BLOCKING — work will be built wrong without an answer · 🟠 HIGH — changes design, answerable in a sentence · 🟡 OPERATIONAL — needed before hand-off.

> ## ⚠️ READ `DECISIONS_LOG.md` FIRST
>
> On **2026-08-23** the project owner decided five of the thirteen conflicts recorded in §30.
> Where this document and `DECISIONS_LOG.md` disagree, **the decisions log wins.**
>
> **The v1 scope baseline is now fixed at five modules:**
> **Portal · Audit · Content (including the whole WordPress subsystem) · Citations · Web 2.0.**
> Everything else evidenced as committed to Danyal — GBP posts, the Indexing module, backlink
> monitoring, Sheets reporting, the financial audit report, Fiverr data import, extra CMS
> connectors — moves to **v1.1**, built after v1 ships to the client.
>
> Also decided: scale target **50–100 clients** with headroom architecture · citation cost
> **≤10¢ marginal, 20¢ hard fail line, loaded cost disclosed** · Web 2.0 accounts **tiered**
> (per-client on high-authority platforms) · Web 2.0 runs **per-campaign, not for every client**.
>
> Still open and blocking: **D-17** (is Policy Radar in v1? — it was sold to Danyal as Module 04
> of four), **D-4** (content QA gate), **D-6** (rankings source), **D-15** (credential rotation).


---

## 🔴 BLOCKING

### Q-1 · How many clients does Danyal actually have?

**Unclear:** every delivered document says "the starting set of 15 clients" and prices "all 15 clients together". The operator states Danyal has *hundreds* of clients.

**Evidence for 15:** `danyal-AIOS-Client-Onboarding-Checklist` §1.5 and `danyal-AIOS-Service-Tiers` §06 both use 15. **But** the identical figure appears in Haseeb's documents, and Haseeb genuinely has ~15–20 facilities — which makes template inheritance the more likely explanation than a statement of fact about Danyal.

**Evidence for hundreds:** operator statement, 2026-08-23, given as context for why isolation and per-client data safety matter.

**Why it matters:** it changes the isolation model, queue and concurrency design, provider quota planning, browser-worker capacity, the UI's list/search/pagination patterns, backup strategy, the entire cost model, and whether a single VPS is viable at all. At 15 clients the current architecture is adequate. At 300 it is not.

**If unanswered:** the team builds for 15, ships, and discovers the ceiling in production.

**Answerable by:** Zain / Danyal. **Ideal form of answer:** a number, plus how many are active retainers versus historical, plus how many have multiple locations.

---

### Q-2 · Which citation cost ceiling is the commitment of record — 10¢ or 20¢?

**Unclear:** a document delivered to the client on 17 July 2026 headlines **"Under 10¢"** per citation and per backlink, and proves it with a per-route cost table. The operator now states a maximum of **20 cents**.

**Why it matters:** it decides whether Apify (25¢/unit) is ever permissible, whether human-assisted class-C citations are commercially viable, and — most importantly — what the client believes he was promised. A client holding a document that says 10¢ will not accept 20¢ silently.

**If unanswered:** the team may build to 20¢ and be measured against 10¢.

**Recommended answer, needing confirmation:** engineer to **≤10¢ marginal**, treat **20¢ as the hard fail line**, and report a separate **loaded** cost that includes human handoff minutes, proxy bandwidth and CAPTCHA spend. Report all three figures to the client.

**Answerable by:** Zain.

---

### Q-3 · What is the single official rankings source — DataForSEO or serper.dev?

**Unclear:** the service-tiers document flags this against itself: *"The main plan and full tool list say use DataForSEO for rankings (Search Console shows an average, not the real position); the client setup checklist says serper.dev … please pick one official rankings source before we build, because the cost and the data pipeline both depend on it."* It was never picked.

**Why it matters:** cost model, accuracy claims made to clients, the definition of the three tiers, the geo-grid design, and whether rank history is comparable over time. Mixing sources makes historical rank data meaningless.

**If unanswered:** rank data will be inconsistent and the tier pricing will be wrong.

**Answerable by:** Zain, ideally with a cost comparison at the real client count (which depends on Q-1).

---

### Q-4 · Is the content QA scorecard a hard publish gate or advisory?

**Unclear:** the codebase states it is a hard gate, re-checked at publish, that never publishes a sub-threshold draft. The August research plan states the scorecard is *"now advisory, not a blocker."*

**Compounding problem:** the threshold (weighted ≥85, no dimension <70) and the weight vector are marked **PROVISIONAL** and were never calibrated against a human SEO grade.

**Why it matters:** an uncalibrated hard gate either blocks good work or passes bad work, and nobody currently knows which. This must be resolved **before** any 50-page volume run, or the run proves nothing.

**Recommended answer:** make it advisory-with-mandatory-acknowledgement until calibrated against ~30 human-graded drafts, then make it hard at the calibrated threshold.

**Answerable by:** Zain + whoever will do the SEO grading.

---

### Q-5 · Web 2.0 accounts — per-client identity or shared house accounts?

**Unclear:** the client-delivered economics document promises *"Per-client platform accounts under the client's own identity — never shared across clients (keeps them safe from bans)."* The credentials guide describes the built system: *"The agency publishes Web 2.0 through shared house accounts."*

**Why it matters:** shared accounts are a shared footprint and a shared failure domain. One client's ban removes every client's properties from that platform, and a platform that can link 30 unrelated local businesses to one account has been handed the exact pattern it polices. It is also a promise-versus-delivery gap the client could discover.

**If unanswered:** the system ships with a systemic client-safety risk that was explicitly promised against.

**Recommended answer:** per-client accounts on the high-authority platforms (WordPress.com, Blogger, Tumblr, Ghost, Hashnode); house accounts permitted only on anonymous or throwaway-tier platforms (Telegra.ph), with a hard cap on properties per house account.

**Answerable by:** Zain.

---

### Q-6 · Is the deadline fixed, or is the scope fixed?

**Unclear:** the deadline has already been extended once and is described as very close. The scope has roughly tripled since the 3–5 week estimate and has never been re-baselined.

**Why it matters:** these cannot both hold. The recovery plan is entirely different depending on the answer:
- **Deadline fixed** → ship a smaller, verified, honest subset and publish a capability truth table. Recovery priorities 1–3 only.
- **Scope fixed** → re-baseline the date in writing with the client now, not later.

**If unanswered:** the team will attempt both and deliver neither, which is what has already happened once.

**Answerable by:** Zain. **This is the single most consequential question in this document.**

---

### Q-7 · What exactly has the client already seen, been shown, and been promised?

**Unclear:** the evidence shows at least eight documents delivered to Danyal, a live system at `app.qanry.com`, Loom walkthroughs, and a hand-over meeting that was being scheduled. It is not clear which capabilities he has personally seen working, which he believes are complete, and what he was told verbally on calls (several call recordings exist but were not available to this analysis).

**Why it matters:** the recovery must close the gap between *what he believes he has* and *what exists*. That gap cannot be measured without knowing the first half.

**If unanswered:** the team may fix things the client does not care about while leaving something he believes is finished broken.

**Answerable by:** Zain + Adan. **Ideal form:** a list of every document sent, every demo given, and every verbal commitment made.

---

## 🟠 HIGH IMPACT

### Q-8 · How many of Danyal's clients have multiple locations?
Local SEO for a multi-branch business needs one business profile, one GBP, one citation set and one location-page set **per location**. The data model is currently client-scoped. If even 10% of clients are multi-location, the location entity is required now, not later. **Answerable by:** Danyal.

### Q-9 · Is Manager a distinct portal, or folded into Admin?
The architecture says Manager is optional in v1 and its scope folds into Admin if deferred. Six roles exist in code. **Answerable by:** Zain, based on whether Danyal will actually employ account managers.

### Q-10 · Do clients get branded portals on their own domains?
Haseeb's brief includes per-client branding and per-client domains. Danyal's evidence does not mention it. The operator's "hundreds of clients" framing raises the question. This is a substantial engineering item (DNS, TLS, per-tenant theming) and is currently assumed **out**. **Answerable by:** Zain.

### Q-11 · Does the end client approve content drafts, or only the agency lead?
Every document says a human approves. It never says *which* human. Client approval is a different workflow (notification, deadline, revision loop, delegated approval) from internal approval. **Answerable by:** Danyal.

### Q-12 · Does the client approve publishing to their own live site?
Publishing to a client's production website without their sign-off is a commercial and legal risk, even with agency approval. **Recommended:** a one-time standing authorisation captured at onboarding, plus per-page approval as a configurable option. **Answerable by:** Danyal.

### Q-13 · Are Fiverr upsells in or out?
The kickoff locked them in as a deliberate brand decision. The overhaul backlog says remove the Upsells section "for now" while simultaneously requiring the free-audit page to use Danyal's real gigs. **Answerable by:** Danyal.

### Q-14 · GBP — will Danyal grant owned API access, or is this drafts-only?
GBP posting, review replies and insights need Manager access and an approved API project, which takes time and has an eligibility bar (roughly 60 days of profile history). The current code's GBP sync *always holds because no reader is wired*. Whether that is a bug or an unbuilt dependency turns on this answer. **Answerable by:** Danyal.

### Q-15 · Elementor or Gutenberg as the default output?
The recommended architecture is capability-driven per site. But a default matters for sites where both are possible, and it determines which composer gets the deeper investment and the regression-test suite. **Recommended:** Elementor where the site already uses it, Gutenberg otherwise, flat HTML never except as a labelled degradation. **Answerable by:** Zain.

### Q-16 · Which markets beyond US, UK, Canada and Australia?
The catalogue covers four markets (155 directories, 15 global). If Danyal's Fiverr client base spans more, the directory catalogue and Web 2.0 mix need extension. **Answerable by:** Danyal.

### Q-17 · Which niches, for niche-directory selection?
The citation audit prioritises generic → country → **niche**. Niche prioritisation needs a niche taxonomy. The audit engine already supports client profiles (general, local, ecommerce, saas, content). **Answerable by:** Danyal.

---

## 🟡 OPERATIONAL

### Q-18 · Where does the vault master key live, who holds it, and how is it rotated?
The entire credential store is sealed under `VAULT_MASTER_KEY`. Nothing in the evidence states its custody, its backup, its rotation procedure, or whether a database restore can decrypt without it. **This is a business-continuity risk, not only a security one.**

### Q-19 · Who operates this system day to day after hand-off?
Danyal alone? A VA? A team? The answer determines how much the UI must explain itself, how complete the runbooks must be, and whether the Virtual Assistant role template is the primary persona.

### Q-20 · What is Danyal contractually owed?
This analysis has seen scope documents and conversations, not a contract or a statement of work. Acceptance criteria and the re-baselining conversation both depend on it.

### Q-21 · Who owns the VPS, the domain and the provider accounts after hand-off?
The client pack says everything is in Danyal's name from day one with no lock-in. Chat evidence shows Xegents provisioning and holding access, and one exchange notes the VPS was purchased below the recommended specification against advice. Confirm actual ownership and confirm the spec is adequate for browser-worker load.

### Q-22 · Which credentials in the WhatsApp export are still live?
Admin, team, client, WordPress and VPS credentials appear in plaintext across at least six messages. Every one must be enumerated and rotated. Until that list exists, the system must be treated as compromised.

### Q-23 · Does the audit engine ship to Danyal, or remain a Xegents asset?
It is a separate repository with its own keys and its own `.env`. If Danyal owns the platform outright, does he own the engine? This changes the architecture recommendation (vendor it in, or keep the subprocess seam) and the commercial position.

### Q-24 · Who owns the leads generated by the public free audit?
The free audit is designed as a lead magnet with follow-up email sequencing. Whether those leads are Danyal's, and whether the sequences run under his brand, is unspecified.

### Q-25 · What is the expected concurrency of human reviewers?
Every published artefact passes a human gate. At the acceptance volume (50 pages, 50 citations, 10 businesses) the gate becomes the bottleneck. How many people will be doing this, and for how many hours?

---

## EVIDENCE THAT COULD NOT BE READ

Recorded for honesty; each may contain requirements not captured in this analysis.

| Item | Why not read | Risk |
|---|---|---|
| ~660 media files in the Adan chat, ~230 in Team Dev — several hundred `.opus` voice notes, ~30 videos, ~200 photos | No transcription performed | **Medium-High.** The chats repeatedly reference substantive content being delivered by voice: *"Today's tasks in a voice message"*, *"ik voice message krna mujhe, and btana everything about haseeb's this month aios"*, *"send me a detailed vn on the update"*. Requirements almost certainly exist only in audio. |
| `00000129-Danial Project discussion _260709_053203.pdf` | Image-only PDF, no text layer, and no PDF renderer available in this environment | **Medium.** Filename and date (2026-07-09) suggest it captures a Danyal requirements discussion. |
| Fathom call recordings (several share links in chat) | External links, not fetched | **Medium.** The 2026-07-03 kickoff was summarised into meeting notes, but at least four other recordings are referenced. |
| Loom walkthroughs (several) | External links | Low-Medium. Likely demonstrations rather than requirements. |
| Screenshots and whiteboard photos | Not read | Low-Medium. Several are explicitly of planning boards. |
| Google Docs / Sheets links (Haseeb's working files, frontend structure docs, backend audit docs) | External, permissioned | Low for Danyal; several are Haseeb-specific. |

**Recommendation:** before Phase 2 begins, transcribe the voice notes from 2026-07-03 to 2026-07-25 (the requirements-dense window) and render the image-only PDF. Two of the highest-density days are 04/07 and 08/07. This is a few hours of work and is the cheapest remaining source of requirement discovery.
