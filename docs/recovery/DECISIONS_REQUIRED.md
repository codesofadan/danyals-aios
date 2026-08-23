# DECISIONS REQUIRED — Daniel Project Recovery


**Companion to** `DANIEL_PROJECT_RECOVERY_SPECIFICATION.md`
**Compiled:** 2026-08-23
**Purpose:** decisions only the project owner (or the client) can make. Each carries a recommendation, but none has been actioned.

**Ordering:** by how much downstream work is blocked.

> **⚠️ D-1, D-2, D-3, D-5 and D-16 were decided by the owner on 2026-08-23.**
> See `DECISIONS_LOG.md` for the decisions, their effects, and what they supersede.
> **The v1 scope baseline is now fixed at five modules: Portal · Audit · Content (incl. WordPress) ·
> Citations · Web 2.0.** Everything else evidenced as committed to Danyal moves to v1.1.
> Two new open items came out of that conversation: **D-16** (Web 2.0 is per-campaign, resolved)
> and **D-17** (is Policy Radar in v1? — still open).
> The entries for the decided items below are retained as the record of what was weighed.


---

## ✅ D-1 · [DECIDED — hybrid, with an off-page scope correction] Deadline fixed, or scope fixed?

**Decision needed:** which of the two is immovable.

**Context.** The original estimate was 3–5 weeks for three modules. The scope has since absorbed Policy Radar, the entire off-page module (citations + Web 2.0), GBP posting, a research module, bulk page generation, Elementor-editable output, design matching, per-client citation account creation, and a new indexing module. The estimate was never restated. The deadline has already been extended once.

**Options.**

**A — Deadline is fixed.** Ship a narrower, fully verified, honestly labelled subset. Concretely: truthfulness sweep + scheduling restored + audit end-to-end + content-to-WordPress end-to-end, plus a capability truth table showing exactly what is live, degraded, manual and planned. Citations and Web 2.0 ship at whatever verified coverage is real on the day, with every gap explained.

**B — Scope is fixed.** Re-baseline the date with the client in writing this week, listing every addition since 2026-07-03 with its cost. Then deliver the full scope to the §27 quality gates.

**C — Hybrid.** Ship A on the current date as "v1 delivered", with B as a scheduled v1.1 the client has agreed to in writing.

**Recommendation: C.** It preserves the relationship, protects the deadline, and does not require pretending the scope did not change. A is survivable; B alone risks a second missed date, which is far more damaging than the first.

**Blocks:** every sequencing decision in the recovery.

---

## ✅ D-2 · [DECIDED — 10¢ marginal / 20¢ hard line / loaded cost disclosed] The citation cost ceiling of record

**Decision needed:** is the commitment 10¢ or 20¢, and what is measured — marginal or loaded cost?

**Context.** A document delivered to Danyal on 17 July headlines "Under 10¢" with a per-route proof table. The operator now states 20¢. Separately, Danyal has raised Apify's costing as a concern, and Apify is 25¢ per submission — above both figures.

**Options.**
**A** — Hold the 10¢ commitment as delivered. Apify effectively banned. Class-C human-assisted citations priced separately as a manual service.
**B** — Renegotiate to 20¢ with the client explicitly. Apify still banned at 25¢.
**C** — Keep 10¢ as the marginal engineering target, 20¢ as the hard fail line, and report loaded cost separately and honestly.

**Recommendation: C**, with the loaded figure disclosed to the client proactively. The 10¢ table in the delivered document is a *marginal* cost — it excludes human handoff minutes, proxy bandwidth and CAPTCHA balance at volume. Disclosing that before the client discovers it is a credibility gain; discovering it after is a dispute.

**Blocks:** citation engineering priorities, whether Apify is wired at all, and the commercial model for class-C directories.

---

## ✅ D-3 · [DECIDED — 50–100 clients now, architected to scale far beyond] True client count and the target scale

**Decision needed:** design for 15, for 100, or for 500?

**Context.** All delivered documents say 15 (likely inherited from Haseeb's brief). The operator says hundreds.

**Recommendation:** get the real number, then **design for 3× it**. If the answer is "about 100 active", build for 300. The specific things that change: per-client job concurrency caps, a browser-worker fleet separate from the API host, server-side pagination and search everywhere, pre-aggregated rollups, per-client provider rate limits, and bulk client onboarding by import.

**Blocks:** architecture, infrastructure sizing, cost model, UI patterns, and whether the current single VPS is adequate.

---

## D-4 · The content QA gate

**Decision needed:** hard gate or advisory, and at what threshold?

**Context.** The code enforces it as a hard publish gate at weighted ≥85 with no dimension below 70. The August plan describes it as advisory. The threshold and weights are explicitly marked provisional and were never calibrated against human judgement.

**Recommendation:** **advisory with mandatory acknowledgement** until calibrated. Calibrate against roughly 30 drafts graded by a human SEO. Then set the threshold at the level that correctly separates the human grades, and make it hard. Publish the calibration so the number means something.

**Do this before the 50-page volume run**, or the run cannot be interpreted.

**Blocks:** the content acceptance run, and therefore the content module's definition of done.

---

## ✅ D-5 · [DECIDED — tiered, per-client on high-authority platforms] Web 2.0 account ownership

**Decision needed:** per-client accounts, shared house accounts, or a tiered mix?

**Context.** The client was promised per-client accounts under their own identity, explicitly framed as ban protection. The system was built on shared house accounts.

**Recommendation: tiered.** Per-client accounts on the high-authority platforms where a ban actually costs something and where the client's brand should own the property — WordPress.com, Blogger, Tumblr, Ghost, Hashnode, GitHub/GitLab Pages. House accounts permitted only on anonymous or low-stakes platforms (Telegra.ph, throwaway Fediverse instances), with a hard cap on properties per account and footprint monitoring.

**Cost of the recommendation:** one manual OAuth or signup run per client per high-authority platform. At 5 platforms that is roughly 10–15 minutes per client, one time. That is a real cost and should be priced into onboarding.

**Blocks:** the Web 2.0 module's safety design, and closing a promise-versus-delivery gap.

---

## D-6 · Rankings source

**Decision needed:** DataForSEO or serper.dev as the single official rank source.

**Context.** The service-tiers document flags the contradiction itself and asks for the decision "before we build". It was not made.

**Recommendation:** **serper.dev for local-pack and map-pack position checks and for the geo-grid; DataForSEO for organic rank tracking, keyword metrics and volume-sensitive work.** Use exactly one source per metric type, never mixed, and label every displayed rank with its source. Historical rank data is worthless if the source changed mid-stream.

**Blocks:** the rank tracker, geo-grid, tier definitions and cost model.

---

## D-7 · Fiverr upsells — in or out

**Context.** Locked in at kickoff as a deliberate brand decision (upsells point at Fiverr gigs, not internal services, to protect the agency's Fiverr-centred public identity). The overhaul backlog then says "Remove the Upsells section (for now)" under Reports, while requiring the free-audit page to show Danyal's *real* gigs.

**Reading:** these may not actually conflict — the removal instruction is scoped to the Reports tab, and the free-audit instruction confirms upsells remain elsewhere. But it needs confirming rather than interpreting.

**Recommendation:** keep upsells in the client portal and on the free-audit result with Danyal's real gigs; remove only the Reports-tab instance. Confirm with Danyal.

---

## D-8 · MFA on Owner and Admin accounts

**Context.** The overhaul backlog instructs removing Two-Factor Auth from Settings, along with Change Password, Security and Workspace tabs. The Owner account can reveal every credential in the vault, including client WordPress passwords and directory logins.

**Recommendation:** keep the Settings trim for the other tabs; **reinstate MFA for Owner and Admin only**, before production hand-off.

**This is a recorded disagreement with an existing instruction.** If the instruction stands, the risk is accepted knowingly and should be noted in the hand-over documentation.

---

## D-9 · Multi-location modelling — now or later?

**Context.** The data model is client-scoped. Local SEO for multi-branch businesses requires per-location business profiles, GBP records, citation sets and location pages. A sibling project's independent audit named the absence of a first-class location entity as one of its three most consequential architectural gaps.

**Recommendation:** if **any** current client has more than one location, model it now. Retrofitting a location entity after citations and content are live means migrating public records, which is far more expensive than building it correctly.

**Depends on:** Q-8.

---

## D-10 · The audit engine seam

**Decision needed:** keep the subprocess, vendor the engine in, or run it as a service?

**Context.** The engine is a separate product with its own dependency set, its own `.env` key store, its own minted run identifiers, no top-level exception handling and no self-imposed timeout. The platform's adapter compensates competently but the seam carries two key stores, two release cycles and a stdout-parsed contract.

**Options.**
**A — Keep the subprocess, harden the contract.** Give the engine a structured exit contract, accept an externally-supplied run id, and read keys from the platform vault. Cheapest; preserves independence.
**B — Vendor the engine into the platform as a library.** One dependency set, one key store, real exception propagation. Loses the engine's independent life as a Claude-Code product.
**C — Run it as an HTTP service.** Clean contract, independent scaling, but new infrastructure.

**Recommendation: A now, C later if audit volume demands it.** B only if D-11 says the engine ships to Danyal anyway.

---

## D-11 · Does the audit engine ship to Danyal?

**Context.** The client pack says Danyal owns everything with no lock-in. The audit engine is a separate Xegents repository that the platform invokes.

**Recommendation:** decide explicitly and tell the client. If it ships, vendor it (D-10 option B) and hand over one system. If it does not, the "no lock-in" claim needs qualifying, and the seam must be hardened (option A) because the client cannot fix it.

---

## D-12 · Elementor or Gutenberg default

**Recommendation:** capability-driven — Elementor where the site uses it, Gutenberg otherwise, flat HTML never except as an explicitly labelled degradation. The decision needed is which composer receives the deeper investment and the regression-test suite. **Recommend Elementor**, because that is where the client's editability expectation actually lives and where a third-party format change would hurt most.

---

## D-13 · Free audit as a public lead magnet — scope and ownership

**Decision needed:** is the public free audit part of the delivered product, and who owns the leads?

**Context.** The free audit is described as generating leads, feeding a follow-up email sequence with personalised cron-driven follow-ups, and converting through Fiverr gigs. It is a public, unauthenticated, compute-spending endpoint.

**Recommendation:** yes, ship it — it is a genuine differentiator — but with abuse controls (per-domain and per-IP rate limits, a queue cap, domain validation) and an explicit statement of who owns the lead data. Confirm the email sequences run under Danyal's brand.

---

## D-14 · Acceptance criteria and the testing waves

**Decision needed:** formally adopt the owner's stated bar.

**The bar, verbatim:** *"I want 50 audits / pages / citations built for 10 different businesses. Only then is testing phase 1 done. Then it comes to me. Then to the client for the third wave of testing."*

**Recommendation:** adopt it verbatim as the acceptance criteria, with the per-module evidence requirements in §35.2 of the specification. Schedule the three waves explicitly with dates. **Do not let the client see the system before wave 2 has passed** — a second discovery of demo data would be far more damaging than a delay.

---

## D-15 · Credential rotation

**Decision needed:** authorise an immediate rotation of every credential exposed in the WhatsApp exports.

**Context.** Admin, team, client, WordPress and VPS credentials appear in plaintext in at least six messages across the two exports, and those exports currently sit inside the project working tree.

**Recommendation:** authorise now. Enumerate every credential in the exports, rotate all of them, move the export out of the repository tree, and establish a credential channel that is not a messaging app. This costs hours and closes a live exposure.

---

## DECISION SUMMARY

| ID | Decision | Recommendation | Blocks |
|---|---|---|---|
| D-1 | Deadline vs scope | Hybrid: verified v1 now, agreed v1.1 next | Everything |
| D-2 | Citation ceiling | 10¢ marginal target, 20¢ hard line, loaded cost disclosed | Citation engineering + commercials |
| D-3 | Client count / scale | Get the number, design for 3× | Architecture + infrastructure |
| D-4 | QA gate | Advisory until calibrated, then hard | Content acceptance run |
| D-5 | Web 2.0 accounts | Tiered: per-client on high-authority | Client safety |
| D-6 | Rankings source | Split by metric type, never mixed, always labelled | Rank tracker + tiers |
| D-7 | Upsells | Keep in portal + free audit; remove only from Reports | Client portal |
| D-8 | MFA | Reinstate for Owner/Admin | Security posture |
| D-9 | Multi-location | Model now if any client has >1 location | Data model |
| D-10 | Audit engine seam | Harden the subprocess now | Audit reliability |
| D-11 | Engine ownership | Decide and tell the client | Lock-in claim |
| D-12 | Editor default | Capability-driven; invest in Elementor | Content output |
| D-13 | Free audit | Ship with abuse controls; confirm lead ownership | Lead flow |
| D-14 | Acceptance criteria | Adopt the owner's bar verbatim | Definition of done |
| D-15 | Credential rotation | Authorise immediately | Security |
