# R6 — The SEO intelligence substrate — three tiers, strict precedence, structured over retrieved

> Track R6 of the AIOS v2 Rescue & Re-engineering Plan. Evidenced decision record.
> **Date: 2026-08-23.** Every claim about an external system carries a source URL and
> that accessed date. Anything not verified at a primary source is marked
> `[UNVERIFIED]` with the exact test that would settle it. Claims about this
> repository cite `path:LINE`.
>
> Sibling tracks: **R3A** owns the content pipeline (topical maps, fact substrate,
> duplicate gate, pacing, decay). **R2** owns Web 2.0 safety. This record owns the
> knowledge layer all of them read from, and deliberately does not restate their
> requirements. Where R6 touches an R3A table it says so and defers.
>
> House rule CONT-21 (zero em dashes) is honoured in the body prose. The title and
> the Sources section use the em dash only because the deliverable format for this
> track mandates the `[label] URL — accessed <date>` citation pattern.

---

## 1. Decision

**We will build the SEO intelligence substrate as a single versioned Postgres table, `knowledge_entries`, discriminated by a `tier` enum (`global` | `agency` | `client`), resolved at read time by a deterministic `DISTINCT ON` query in strict precedence order CLIENT > AGENCY > GLOBAL, with two hard qualifications that make the precedence safe: an entry may carry `overridable = false`, in which case a lower-precedence tier cannot displace it and an attempt to do so produces a blocking conflict record; and every resolution emits a `context_bindings` row naming the exact entry versions the AI output was generated against.** Conflicts are surfaced three ways at once and never silently resolved: a durable `knowledge_conflicts` row, a `conflicts[]` array on the assembled bundle that the module renders on the artefact for the human reviewer, and, for `severity = 'block'`, a refusal to draft that holds the job in a named state rather than producing output. **Audit checks stay code plus structured config and are never retrieved**: the substrate stores each check as a typed `value jsonb` payload (thresholds, term lists, required-element sets, severity) that a deterministic Python function consumes, exactly the pattern the existing `blocklist_lint.py` already uses when it parses `vocabulary-blocklist.md` into regexes at `SEO-CONTENT-OS/scripts/blocklist_lint.py:132` (Tier 1 only today; see 3.5). **We will not use retrieval in the substrate in v1, and we will not build a second vector store.** The existing context module stays exactly as it is (Postgres as source of truth, Pinecone as a derived index, `db/migrations/0014_entity_context.sql`), and the substrate reads its per-entity output through the existing `GET /context/{type}/{id}` door; the substrate's own selection problem, "which knowledge does this task need", is a **closed, finite, enumerable mapping from (task_class, page_type, vertical) to a key set**, which a lookup table answers exactly and an embedding search answers approximately and expensively, so it gets a lookup table. **Prompt assembly is a pure function** `assemble(client_id, task) -> ContextBundle` with a fixed four-segment order (frozen system prefix, global tier, agency tier, client tier) rendered as canonical sorted JSON so the global-plus-agency prefix is byte-identical across every client and every call, which makes it the single best prompt-cache target in the platform and saves a modelled **$239 to $341 per month at 2,600 pages per month** on the Sonnet content path (unit prices verified at [anthropic-pricing]; the 15,000-token prefix and the clustering of calls are stated assumptions, not measurements — see 6.1). **Model routing moves out of constructor defaults and into a settings-driven `MODEL_ROUTES` table keyed by task class**: Sonnet 5 (`claude-sonnet-5`) for content draft, audit narrative, review replies and policy summarisation prose; Opus 5 (`claude-opus-5`) for the QA judge, research synthesis and the paid-audit strategy narrative; Haiku 4.5 (`claude-haiku-4-5-20251001`, the dated id, because that is the id the structured-outputs documentation lists) for enum classification and context folds. Every typed output uses `output_config.format` with `additionalProperties: false`, which is GA and needs no beta header. Finally, **"beats 99% of SEO strategists" is declared unmeasurable as stated and replaced with a computable acceptance test**: a blind pairwise preference trial against purchased human specialist output over 50 briefs, passing at **32 wins out of 50 or better**, because that is the smallest integer whose Wilson 95% lower bound exceeds 0.5.

---

## 2. Context

### 2.1 The question this track had to settle

Every other module in v1 reads from this layer. The audit narrative needs to know what a check means before it can explain a finding. The content generator needs to know the client's voice, the agency's "things we never do", and the current Google position on scaled content before it writes a sentence. The QA judge needs the same definitions the generator was given, or it grades against a different standard than the one that produced the draft. Policy Radar needs somewhere to put a detected change other than a recommendation queue nobody reads twice.

Four things had to be settled before an engineer could write the first migration:

1. **What is the storage and resolution model for three tiers with strict precedence, and what happens when they disagree?** "Conflicts SURFACED rather than silently resolved" is a design intent, not a specification. A conflict record, a warning on the artefact, and a blocking review item are three different products with three different failure modes.
2. **Where exactly is the line between deterministic config and retrieval?** This is the difference between a check a client can be shown the arithmetic for, and a check that is a model's opinion wearing a number's clothing.
3. **Does the substrate need retrieval at all, and if so, through what mechanism?** The platform already has a context module and a derived vector index. Adding a second one would be an architectural error; adding retrieval to a closed query space would be a cost error.
4. **What is the seed content, where does it live, and what does each piece become?** This one turned out to be the most urgent, for the reason in 2.2.

### 2.2 The thing that makes this urgent: the substrate's stated source of truth is not in the repository

`backend/docs/CONTENT-DOCTRINE.md:1-14` performs an explicit authority transfer dated 2026-07-24:

> "This document is **no longer the source of truth** for what a ranking-grade page is. The single canonical spine is now the **SEO-CONTENT-OS knowledge base**, committed in-repo at: `backend/seo-content-os/knowledge/`"

`backend/app/services/content_qa.py:69-70` and `backend/app/services/content_generator.py:54-59` both cite that path as the justification for their numeric constants. **The directory does not exist.** `ls backend/seo-content-os` returns "No such file or directory"; `git ls-files backend/seo-content-os` returns zero rows; `git log --all -- backend/seo-content-os` returns nothing. The only copy of that material in the repository is `SEO-CONTENT-OS.zip`, a **1,160,551-byte (1.1 MB)** binary blob at the repo root, tracked in git since commit `5f98937` (`git log --diff-filter=A -- SEO-CONTENT-OS.zip`), invisible to grep, invisible to code review, and unversioned at the file level. (The 1.43 MB figure quoted elsewhere in this record is the *uncompressed* markdown corpus inside the zip, not the zip.)

This is a fabricated-provenance defect of exactly the class this project exists to fix: fourteen QA dimensions, a weight vector, a 70-point floor and an 85-point threshold all cite passages no engineer on this project can read. R3A reached the same finding independently (`docs/research/R3A-content-intelligence.md:380`, requirement R3A-37(b)). R6 owns the fix, because the fix is the substrate.

---

## 3. Findings

### 3.1 A single table with a tier discriminator beats three tables, and the repository has already made this exact call once

**Conclusion: use one `knowledge_entries` table discriminated by a `tier` enum, not three parallel tables.**

Three arguments, one of them the repo's own precedent.

Precedence resolution across three tables is a three-way `LEFT JOIN` plus `COALESCE` per key, which is unreadable and untestable at any width. Across one table it is a single `DISTINCT ON (key) ... ORDER BY key, tier_rank`, which is a query an engineer can read aloud. Conflict detection across three tables is a three-way join; across one table it is a `GROUP BY key HAVING count(*) > 1`. Adding a fourth scope later (per-site, per-campaign) is an enum label in one table and a migration in three.

The repository already made this decision, deliberately, and documented why. `db/migrations/0027_audit_overlay.sql:12-20` states: "ONE table serves both overlay kinds, discriminated by target_module (the 0019 enum, reused - no new enum) ... payload jsonb carries any structured extra ... so the overlay shape can grow WITHOUT a migration." Following house convention here is worth more than a marginal normalisation argument.

The one genuine objection is row-level security: client-tier rows are tenant data and global/agency rows are not. This is solved without splitting, because the repo's RLS pattern is uniform and already handles exactly this shape. `client_business_profiles` (`db/migrations/0051_client_business_profile.sql:66-77`) is staff-read via `is_staff()`, lead-write via `current_app_role() in ('owner','admin','manager')`, with no client select policy; `entity_context` (`db/migrations/0014_entity_context.sql:82-91` for the RLS, `:92-109` for the view and its grant) exposes a client's own slice through a `security_barrier` view self-filtered by `current_client_id()`. `knowledge_entries` takes the same two policies plus the same view pattern.

### 3.2 Strict precedence alone is unsafe. The missing primitive is a non-overridable flag, and without it a client can switch off Google compliance

**Conclusion: precedence must be qualified by `overridable boolean not null default true`. CLIENT > AGENCY > GLOBAL is correct for facts, voice and preference, and catastrophic for compliance.**

This is the single most important design finding in the track and it is not in the brief.

Consider the concrete case. Google's spam policies name **scaled content abuse**, defined as "Scaled content abuse is when many pages are generated for the primary purpose of manipulating search rankings and not helping users", with "Using generative AI tools or other similar tools to generate many pages without adding value for users" given as an example [google-spam-policies], page last updated **2026-05-15 UTC**. The global tier will carry that as a `policy_summary` entry and the doorway/thin-content check (`G3` in the gate stack, `SEO-CONTENT-OS/knowledge/quality-gates/gates.md:23` in the summary table, `:93` for the gate body) as a `check_config` entry with severity `auto-fail`.

Under unqualified strict precedence, a client-tier entry on the same key with `{"severity": "off"}` wins. A client who wants 200 city pages this month gets them, the agency publishes a doorway network under Google's own published definition, and the platform's own gate signed it off. The same hole exists for the vertical compliance overlays: `SEO-CONTENT-OS/knowledge/verticals/` carries YMYL overlays for legal, medical-dental, financial and home-services, and the self-storage overlay whose fields the client template describes as "a REGULATORY liability, not just an SEO risk" (`SEO-CONTENT-OS/clients/_template/brand.yaml:57`; the phrase is in the template, not in `SYSTEM-MAP.md`).

The fix is one boolean and one rule, stated once:

> A `knowledge_entries` row with `overridable = false` cannot be displaced by a lower-precedence tier. The resolver returns the non-overridable value and writes a `knowledge_conflicts` row with `severity = 'block'`. The attempted override is preserved, visible and refused, never deleted.

Which entries are non-overridable is itself a governance decision, so it is a column and not a hard-coded list: seeded `false` (that is, non-overridable) for every `kind = 'policy_summary'` entry, every `check_config` entry whose gate is auto-fail in the source gate stack, and every vertical compliance overlay. Seeded `true` for voice, tone, framework preference, severity of warning-class checks, and every client fact.

This also resolves a tension the brief does not name. "Policy can only lower a ceiling, never raise it" is the automation-ceiling rule. The knowledge-tier analogue is: **a lower tier may raise a bar, never lower a non-overridable one.** A client who wants a stricter reading level than the agency default gets it. A client who wants no E-E-A-T requirement does not.

### 3.3 "Surfaced" has to mean three things at once, because each one alone fails

**Conclusion: a conflict produces (a) a durable `knowledge_conflicts` row, (b) a `conflicts[]` array on the assembled bundle that the artefact renders for the reviewer, and (c) for `severity='block'`, a refusal to generate that holds the job in a named state. All three, always.**

The brief offers these as alternatives. They are not; each fails alone in a way the other two cover.

A conflict record alone is a table nobody queries. The repository has already demonstrated the adjacent failure mode: `recommendations` (`db/migrations/0019_policy.sql:154`) is a well-built queue whose *scheduled* generator (`generate-policy-daily`) sits in `_BEAT_SCHEDULE_DISABLED` (`backend/workers/celery_app.py:195-235`; `docs/audit/AI_AUDIT.md` §2.5 Schedule row). **Correction found in verification: the queue is not unfed.** The same comment block records that Policy Radar is "ON-DEMAND ONLY: a policy brief is fetched + stored only when a user asks (POST /policy/ask + the lead 'generate brief' path write into the SAME change_events / kb_entries / recommendations tables the Policy page reads)". The real lesson is narrower and still holds: a queue whose only writer is an operator who has to remember to press a button accumulates nothing on its own.

A warning on the artefact alone is not durable, is not aggregatable across clients, and disappears when the artefact is regenerated.

A blocking review item alone is too blunt for the common case. Most tier disagreements are ordinary overrides, not conflicts, and blocking on every one would make the substrate unusable within a week.

So the design is: every *resolution* that displaces a lower tier is normal and produces nothing. Only a *detected conflict* produces records, and the three conflict classes are enumerated in 3.4. Severity decides whether generation proceeds.

**Concretely, "held" means:** the job's status becomes `held_knowledge_conflict`, the bundle is persisted with its `conflicts[]`, no model call is made and no spend is incurred, and the operator sees the winning value, the losing value, both tiers, both entry ids and the detector that fired. This mirrors R3A's fact-gate hold semantics (`docs/research/R3A-content-intelligence.md:280`, R3A-18) so the content pipeline has one hold vocabulary and not two.

### 3.4 A conflict is not "two tiers define the same key". Three detectable classes, and only three

**Conclusion: define conflict narrowly and mechanically, or the conflict table becomes noise.**

**Class 1, non-overridable displacement.** A lower-precedence entry targets a key whose winning entry has `overridable = false`. Detection: pure comparison inside the resolver. Severity: `block`. This is the class from 3.2.

**Class 2, set-intersection contradiction.** Two typed array values on *different* keys are mutually unsatisfiable. The motivating real case: a client `no_go` entry `{"topics": ["pricing"]}` against the global service-page conversion check, which requires "A real price or price-driver signal ... A bare 'contact us for pricing' with no driver and no honest reason is the fail" (`SEO-CONTENT-OS/knowledge/quality-gates/gates.md:240`, gate G13). These are individually valid and jointly impossible. Detection: a declared `conflicts_with` predicate list on `check_config` entries, evaluated as set intersection over typed arrays. Severity: `warn` by default, `block` where the intersecting check is auto-fail. This class is why the substrate must be **typed JSON and not prose**: you cannot intersect two paragraphs.

**Class 3, staleness against a newer policy.** An active `policy_summary` entry whose `policy_asof` predates a `kb_entries` row (`db/migrations/0019_policy.sql`) on the same `key`, or a `check_config` whose `source_ref` points at a superseded `policy_summary` version. Detection: a nightly sweep. Severity: `warn`, escalating to `block` if the newer KB entry carries `severity = 'critical'`. This class is the bridge to section 3.8.

Everything else is an override, which is the feature.

### 3.5 The boundary between config and retrieval is already drawn correctly in this codebase, and the test for it is four questions

**Conclusion: the repository's existing discipline is right and should be codified, not redesigned. The formal test a developer applies is below.**

`docs/audit/AI_AUDIT.md` §0 records the audit's verdict on the existing seam: "The specification's rule, *Python computes numbers, AI writes narrative*, is not aspirational in this codebase; it is observably how the system is built." Requirement `AI-001` states it normatively: "Python computes numbers, AI writes narrative, no metric may originate in a model" (`docs/recovery/REQUIREMENTS_TRACEABILITY.md:338`, CONFIRMED, P0).

The best existing demonstration is not in the backend at all. `SEO-CONTENT-OS/scripts/blocklist_lint.py:132` defines `parse_blocklist(path)`, which reads `knowledge/voice/vocabulary-blocklist.md` (a tiered human-readable list: Tier 1 hard ban at `:11`, Tier 2 context-banned at `:138`, Tier 3 structural anti-patterns at `:159`, plus a per-client section at `:207`) and compiles it to regexes with a wildcard placeholder grammar at `:64`. The knowledge lives in one editable artefact; the check is deterministic code; the config is machine-parsed from the artefact. That is exactly the pattern R6 formalises, and it already works.

**Correction found in verification: it works for Tier 1 only.** `parse_blocklist` gates every bullet on `in_tier1` (`blocklist_lint.py:148-153`) and stamps every emitted record `"tier": "Tier 1"` (`:203`); Tier 2 and Tier 3 are present in the markdown and are **not** compiled today. Extra per-client phrases enter through a separate `load_extra_banned(phrases)` entry point at `:250`, not through the markdown. This changes R6-26 Wave 3: seeding `voice.blocklist_tier2` and `_tier3` is new extraction work, not a re-use of an existing parser.

**The developer's test. Four questions; any single "yes" in questions 1 to 3 forces code plus config.**

1. **Does the output cross a threshold?** If the result is a pass, a fail, a score, a rank, a count, a severity, a currency amount, or a set membership decision, it is code plus config. A model may explain the result; it may not produce it.
2. **Must two runs on byte-identical input produce byte-identical output for the result to be trustworthy?** If a reviewer would be alarmed to see the same draft score 78 and then 84, the score is code plus config.
3. **Does a client see the output as a claim about their business or their site?** "Your NAP is inconsistent across 7 of 42 listings" is a claim. It is code plus config. "Inconsistent listings dilute the signals Google uses to associate your business with your address" is an explanation, and may be retrieved or generated.
4. **Is the artefact a sentence rather than a decision?** Only then may it be retrieved or generated.

**The one-line version, for the module CLAUDE.md: if you cannot write a failing unit test for it, it is not a check.**

**What this puts on each side, explicitly.**

| Must be code plus structured config | May be retrieved or generated |
|---|---|
| All 14 gate definitions and their auto-fail / warning class (`quality-gates/gates.md`) | The reviewer-facing rationale for why a gate fired |
| Every threshold: `MIN_DIMENSION_SCORE`, `WEIGHTED_TOTAL_THRESHOLD`, `HARD_GATE_FLOOR`, the 14-entry `DIMENSION_WEIGHTS` vector (`backend/app/services/content_qa.py:104-126`) | Narrative around a score in a client report |
| Taxonomies: search-intent classes, page types, `content_framework` enum, `policy_severity` / `policy_category` / `policy_region` (`db/migrations/0019_policy.sql`) | Which of several equally valid framings to use in a given paragraph |
| The Tier 1/2/3 vocabulary blocklist and per-client banned phrases | Rewriting a flagged sentence |
| Schema type selection per page type, and the required-property set | Prose describing what the schema asserts |
| NAP field values, prices, credentials, licence numbers, service areas | Prose that uses those values verbatim |
| Fact sufficiency counts per page type (R3A-15) | The E-E-A-T story assembled from sufficient facts |
| Severity overrides and the `overridable` flag itself | Examples and teardowns shown **to a human reviewer**, never injected into a generation prompt |

The final row is the boundary's sharpest edge and it is worth stating on its own: `SEO-CONTENT-OS/knowledge/playbooks/examples/` contains 11 vertical teardown files, 2,217 lines of real good-and-bad page analysis. Injecting a competitor teardown into a generation prompt is how a generator learns to reproduce a competitor's page. Showing it to a reviewer is how a human learns to judge one. Same artefact, opposite side of the line, decided by who consumes it.

### 3.6 Retrieval is the wrong instrument for this problem, because the query space is closed. The knowledge base is also 20 times too large to inject, which is why extraction is not optional

**Conclusion: v1 ships with no retrieval in the substrate. Selection is a deterministic key-set resolver. The existing context module is reused unchanged for per-entity client state and is not extended.**

Three independent facts drive this.

**First, the query space is finite and enumerable.** Retrieval earns its cost when a query can be anything. Here, the set of questions the substrate is ever asked is the cross product of task class (audit narrative, content draft, QA score, classification, review reply, policy summary: six), page type (`backend/app/services/page_blueprints.py:138` defines exactly seven: service, location, service_area, blog, faq, local, homepage) and vertical (`SEO-CONTENT-OS/knowledge/verticals/` defines five, plus a null). That is at most 6 × 7 × 6 = 252 distinct knowledge requests, and most combinations are invalid. A 252-row lookup table answers all of them exactly, deterministically, and free. An embedding search answers them approximately, at a per-call cost, with a new dependency, and with no way to snapshot-test the result.

**Second, the corpus cannot be injected, so it must be extracted, and once extracted the retrieval question mostly evaporates.** The knowledge base is 1,429,288 bytes of markdown across 77 files (measured; see the inventory in 3.9). At the conventional 4 characters per token the repository itself uses (`backend/app/services/pricing.py:28`, `_CHARS_PER_TOKEN = 4`), that is roughly **357,000 tokens**, against a 1M context window that also has to hold the task payload, the client tier, the SERP teardown and the draft. A single playbook, `knowledge/playbooks/service-page.md`, is 55,104 bytes on its own. Injecting the corpus is not an option at any budget. The work is therefore extraction of typed config from prose, which is exactly what makes the lookup table possible.

**Third, the deployed image has no vector store, and this was a deliberate decision, twice.** `backend/pyproject.toml:49-58` splits Voyage and Pinecone out of the `[ai]` extra into a separate `[embeddings]` extra with the comment: "SPLIT OUT of `ai` and OUT of the default image: the deployment uses NO Voyage/Pinecone (context vector recall is off)". `docs/audit/AI_AUDIT.md` §1 confirms: "Voyage (embeddings) and Pinecone (vector store) exist behind Protocols but are **deliberately excluded from the deployed image**". R2 reached the same conclusion for its similarity gate: "no embeddings, semantic similarity is the wrong instrument here and the deployment deliberately ships without Voyage/Pinecone" (`docs/research/R2-web2-safety.md` §1). Re-enabling that dependency tree to solve a lookup-table problem would be the wrong trade three times over.

**What the substrate does reuse.** The existing context module stays untouched and remains the door for per-entity live state. `backend/docs/CONTEXT-MODULE.md` describes it accurately: Postgres is the source of truth, `context_vectors` is the authority for what is embedded, Pinecone is a derived index fully reconstructable from that ledger, and `GET /api/v1/context/{type}/{id}` returns summary plus facts plus a freshness signal. The substrate's client tier calls that endpoint for the *living* state (recent activity, folded facts, the freshness `lag`) and stores the *durable* state (voice, no-go topics, constraints, service areas) as its own `knowledge_entries` rows. The division is: `entity_context` is what has recently happened to this client; `knowledge_entries` at tier `client` is what is true about this client until someone changes it.

**If retrieval is ever switched on, the mechanism is already specified and must not be reinvented.** Extend the existing `public.context_entity` enum with a `'knowledge'` label and namespace by tier scope, so `context_vectors` remains the single ledger, the existing `reconcile_context_vectors` sweep keeps working unchanged, and the Pinecone index gains namespaces rather than the platform gaining a store. That is the only sanctioned path. The trigger for revisiting is in Open Items.

### 3.7 Prompt caching on the global-plus-agency prefix is the best cache target in the platform, because unlike every other prefix it is client-independent

**Conclusion: order the bundle stable-first, render it as canonical sorted JSON, place a `cache_control` breakpoint at the end of the agency segment and a second at the end of the client segment. Verified saving of $239 to $341 per month at 2,600 pages per month.**

Verified mechanics, all from the official documentation accessed 2026-08-23:

- Prompt caching multipliers are **1.25x base input for a 5-minute write, 2x for a 1-hour write, and 0.1x for a read** [anthropic-pricing].
- "The cache is refreshed for no additional cost each time the cached content is used", and "The lifetime is measured from the start of the request that writes or reads the cache entry, not from the end of its response" [anthropic-prompt-caching].
- "Organization and workspace isolation: Caches are isolated between organizations. Different organizations never share caches, even if they use identical prompts. Caches are also isolated per workspace within an organization on the Claude API, Claude Platform on AWS, and Microsoft Foundry; Bedrock and Google Cloud use organization-level isolation only" [anthropic-prompt-caching]. **The isolation boundary is the workspace, not the organisation** (corrected in verification; the earlier draft of this record said organisation only). So the sharing property holds if and only if every substrate-carrying call runs under **one organisation and one workspace** — that is, one API key scope. Under that condition a cached prefix written by any client's job is readable by every other client's job. **This is the property that makes the global-plus-agency prefix uniquely valuable and it exists only because those two tiers carry no client data.** **Engineering consequence: do not split the platform's Anthropic key across workspaces (for example one per environment or one per tier of client) without re-running section 6 — a workspace split multiplies the cold-write count by the number of workspaces and can erase the whole saving with no error raised.**
- Minimum cacheable prefix: **512 tokens on Opus 5, 1,024 on Sonnet 5, 4,096 on Haiku 4.5**. "Shorter prompts cannot be cached, even if marked with `cache_control`. Any requests to cache fewer than this number of tokens will be processed without caching, and no error is returned" [anthropic-prompt-caching].
- Maximum 4 breakpoints per request [anthropic-prompt-caching].
- Render order is `tools` then `system` then `messages`; any byte change in the prefix invalidates everything after it.

Two consequences that are design requirements, not observations.

**The Haiku 4.5 minimum of 4,096 tokens is a silent failure.** Classification calls will carry a small taxonomy-only bundle, likely well under 4,096 tokens, and will therefore not cache, with no error raised. The correct response is to accept it and document it, never to pad the prompt to reach the threshold. Padding buys a 0.1x read on tokens that had no reason to exist.

**A mid-day global-tier activation rebuilds the prefix for the whole platform.** Therefore global-tier and agency-tier activations must be **batched to a single daily activation window**, so the shared prefix churns at most once per day. This is a scheduling requirement on the approval workflow, and it is the reason `knowledge_entries` carries `effective_from` rather than activating on write.

The arithmetic is in section 6.

### 3.8 The dated-policy problem is tractable because Google publishes dated updates, and one page kills a whole class of speculative checks

**Conclusion: the global tier holds `policy_summary` entries carrying `policy_asof`; Policy Radar's existing `apply` action becomes the write path; a superseded policy version triggers a re-evaluation sweep over `context_bindings`.**

**Google publishes a dated, machine-checkable ranking-update history.** The current list, verified at the Search Status Dashboard, gives for 2026: August 2026 spam update (18 Aug, 2 days 16 hours), June 2026 spam update (24 Jun, 2 days 1 hour), May 2026 core update (21 May, 11 days 21 hours), March 2026 core update (27 Mar, 12 days 4 hours), March 2026 spam update (24 Mar, 19 hours 30 minutes), February 2026 Discover update (5 Feb, 21 days 17 hours); and for 2025: December 2025 core update (11 Dec), August 2025 spam update (26 Aug), June 2025 core update (30 Jun), March 2025 core update (13 Mar) [google-ranking-history]. This is a real, dated, primary feed, and it is what a `policy_asof` value should be anchored to. R2 used the same source to establish that a "March 2026 Site Reputation Abuse update" cited in a client-delivered document does not exist (`docs/research/R2-web2-safety.md` §3.1), which is a direct demonstration of the value of dating policy entries.

**The spam policies page carries its own last-updated date and a closed category list.** Last updated **2026-05-15 UTC**, with sixteen named spam categories: cloaking, doorway abuse, expired domain abuse, hacked content, hidden text and link abuse, keyword stuffing, link spam, machine-generated traffic, malicious practices, misleading functionality, scaled content abuse, scraping, site reputation abuse, sneaky redirects, thin affiliation, user-generated spam — **plus a seventeenth section, "Other practices that can lead to demotion or removal"** (legal removals, personal information removals, policy circumvention, scam and fraud), which the earlier draft of this record omitted [google-spam-policies]. Those seventeen headings are a **taxonomy**, which by the test in 3.5 is code plus config, and they should be seeded as a `taxonomy` entry rather than left as prose in a prompt. Seed all seventeen; a sixteen-label taxonomy silently cannot classify a demotion-class finding.

**One primary page removes a class of speculative checks the platform is at risk of inventing.** Google's guidance on AI features states, last updated **2025-12-10**: "There are no additional requirements to appear in AI Overviews or AI Mode, nor other special optimizations necessary", and "You don't need to create new machine readable files, AI text files, or markup to appear in these features" [google-ai-features]. The repository ships an `aios-geo-audit` skill whose description names "llms.txt" as a checked item (`.claude/skills/aios-geo-audit/SKILL.md:3`), and `SEO-CONTENT-OS/knowledge/doctrine/llms-txt-verdict.md` exists in the seed material. **Correction found in verification: both already get this right, so the requirement is a preservation constraint rather than a fix.** The skill already says "llms.txt is an informational positive, not required in 2026" (`:45`), "If llms.txt is absent -> info-level only" (`:53`) and names "Scoring llms.txt absence as critical" as an anti-pattern (`:58`); the seed file opens "**Verdict: SEO-CONTENT-OS does not ship an llms.txt generator as a citation feature. The evidence for a citation lift is absent, and building it as a 'GEO win' would be a fabricated-benefit claim.**" **The requirement therefore stands as a seeding rule: any llms.txt check must be seeded at severity `info` at most, never `block`, and must be labelled in client-facing output as not required by Google — the extraction must not quietly promote it.** R3A reached a parallel conclusion about the Indexing API being unusable for this content class (`docs/research/R3A-content-intelligence.md:168`, §3.7). That one *was* a live defect in shipped code; this one is a standard already held.

**How a detected change becomes a global-tier entry.** The existing machinery is nearly right and needs one new sink, not a rewrite. Today: `policy_watch.detect_change` computes a sha256 diff against `policy_sources.last_hash`; `analyze_change` makes a cost-gated Claude call whose enums are clamped to the 0019 vocabularies by `_clamp` (`backend/app/services/policy_watch.py:200-203`, applied to `severity` / `category` / `region` / `target_module` at `:245-253`; an unrecognised label falls back to the column default rather than erroring, which is correct); the result becomes a `kb_entries` row and a `recommendations` row; a lead moves the recommendation `new -> acknowledged -> applied`; `applied` writes an `audit_overlay` row and **never** mutates the audit engine (`db/migrations/0027_audit_overlay.sql:4-9`). `docs/audit/AI_AUDIT.md` §2.5 calls the overlay design "correct and worth preserving: an AI recommendation can never rewrite evidence."

R6 adds exactly one thing: **`apply` writes a `knowledge_entries` row at tier `global` in the same transaction as the `audit_overlay` row**, with `kind = 'policy_summary'`, `source_kind = 'policy_radar'`, `source_ref = recommendations.kb_ref`, `source_url = kb_entries.source_url`, and `policy_asof` set to the change event's detection date. `audit_overlay.payload` gains a `knowledge_entry_id`. Nothing existing is removed; the overlay keeps doing presentation and the substrate gains the durable, versioned, dated fact.

**Approval is lead-only and already enforced twice.** `db/migrations/0019_policy.sql` restricts recommendation updates to `owner/admin/manager`, and `db/migrations/0027_audit_overlay.sql` restricts overlay writes to the same set, with the comment noting that the app-layer 403 and the DB boundary agree. `knowledge_entries` takes the same policy, so approving a global-tier entry is the same act as applying a recommendation, performed by the same people, guarded in the same two places.

**Identifying content generated under an old policy version is a join, not a search**, because of `context_bindings` (requirement R6-9). Given a superseded entry id, `select job_id from context_bindings where entry_versions @> '[{"entry_id": "..."}]'` returns every artefact generated against it. That query is the entire answer to "how is content generated under an old policy version identified afterwards", and it is why the binding table is not optional.

### 3.9 The seed inventory: 77 knowledge files, 22 deterministic linters, 31 operator skills, one binary blob

**Conclusion: the material exists, is high quality, is substantial, and is currently at risk because its only in-repo form is a zip.**

Everything below was counted by extracting `SEO-CONTENT-OS.zip` and running `find` and `wc`. Paths inside the zip are given relative to `SEO-CONTENT-OS/`.

**A. The knowledge base (inside `SEO-CONTENT-OS.zip`, not present as a directory).** 77 markdown files, 13,247 lines, 1,429,288 bytes.

| Path | Files | Lines | Becomes |
|---|---:|---:|---|
| `knowledge/doctrine/` | 7 | 1,004 | **Global framework** + **global policy_summary**. `google-compliance-spine.md` (33 hard rules), `seo-system-doctrine.md` (Laws 1 to 14), `local-content-laws.md` (Laws 15 to 20), `penalty-casebook.md`, `ai-search-reality-2026.md`, `llms-txt-verdict.md`, `seo-system-spine.md` |
| `knowledge/quality-gates/` | 2 | 308 | **Check definitions.** The PLAN gate plus G0 to G13, each with its auto-fail / warning class and its detection procedure. This is the single highest-value extraction target |
| `knowledge/foundations/` | 18 | 3,217 | **Global framework** + **taxonomy**. `search-intent-taxonomy.md`, `schema-library.md`, `passage-block-protocol.md`, `meta-and-headings.md`, `internal-linking.md`, `keyword-research-method.md`, `topical-map-protocol.md`, `nap-consistency.md`, `local-gbp-signals.md`, `geo-ai-citation.md`, `eeat-framework.md`, `experience-signals.md`, `cluster-graph-protocol.md`, `research-input-protocol.md`, `citation-description-library.md`, `local-link-assets.md`, `review-content-strategy.md`, `storage-topical-map.md` |
| `knowledge/playbooks/` | 12 | 3,971 | **Prompt material** (structure and section specs) + **check_config** (per-page-type required elements). One per page type, plus `gbp-posts.md`, `review-responses.md`, `review-requests.md`, `faq-page.md`, `local-asset.md`, `unit-size-page.md` |
| `knowledge/playbooks/examples/` | 11 | 2,217 | **Reviewer-facing only.** 11 vertical teardowns. Never injected into a generation prompt (see 3.5) |
| `knowledge/frameworks/` | 11 | 420 | **Global framework** + **taxonomy**. A README plus 10 framework files: AIDA/4Ps, PAS/PASTOR, StoryBrand SB7, Cialdini, value-equation, objection-handling, Schwartz awareness, scan-layer formatting, copyhackers, VOC mining. **Maps onto the existing `content_framework` enum only partially** (corrected in verification): the enum is `('AIDA','PAS','BAB','FAB','4 Ps','PASTOR','4 U''s')` (`db/migrations/0017_content.sql:39-40`), so only AIDA, PAS, 4 Ps and PASTOR have both a file and a label; BAB, FAB and 4 U's have a label and no file; the other six files have no label. The mapping is a partial function in both directions and Wave 3 must state which side wins |
| `knowledge/voice/` | 8 | 1,151 | **Check_config** (`vocabulary-blocklist.md`, three tiers plus a per-client section) + **agency SOP** (`brand-voice-template.md`, `natural-voice-engineering.md`, `sentence-rhythm.md`, `sentence-patterns.md`, `hooks-and-titles.md`, `humanization-layer.md`) |
| `knowledge/verticals/` | 5 | 598 | **Global check_config, non-overridable.** Compliance overlays for legal, medical-dental, financial, home-services (YMYL) and self-storage |
| `knowledge/lifecycle/` | 3 | 361 | **Global framework.** `content-decay-refresh-protocol.md`, `editorial-scorecard.md`, `measurement-loop.md`. Feeds R3A's maintenance loop, does not duplicate it |

**B. The deterministic checks (inside the zip).** `scripts/`, 22 Python files, 7,760 lines (counts verified by `find`/`wc` on the extracted zip). These are **already** the "code plus structured config" pattern and are the strongest existing evidence for Rule 1: `blocklist_lint.py`, `compliance_lint.py`, `conversion_linter.py`, `duplication_gate.py`, `experience_gate.py`, `geo_page_linter.py`, `information_gain_scorer.py`, `keyword_density.py`, `link_graph.py`, `nap_checker.py`, `qa_scorecard.py`, `readability_scorer.py`, `schema_validator.py`, `review_response_lint.py`, `topical_map_lint.py`, `storage_lint.py`, `voice_fingerprint.py`, `share_of_answer_tracker.py`, `decay_monitor.py`, `storage_cluster_seed.py`, `report_builder.py`, `enroll.py`.

**C. The prompt sets the brief asks for (inside the zip).** `.claude/commands/`, 18 files, 688 lines. Includes exactly the sets named in the brief: keyword research (`build-topical-map.md`, plus `knowledge/foundations/keyword-research-method.md` at 29,297 bytes), GEO page (`.claude/skills/geo-optimize/SKILL.md` plus `knowledge/foundations/geo-ai-citation.md`), service page (`write-service-page.md`, `write-service-city-page.md`, `write-service-area-page.md`), competitor analysis (`.claude/agents/compliance-auditor.md` and `research/expansion-2026-07/05-competitive-eeat-teardown.md`), GBP post (`write-gbp-posts.md` plus `knowledge/playbooks/gbp-posts.md`), schema (`knowledge/foundations/schema-library.md` at 33,838 bytes plus `scripts/schema_validator.py`). Also `.claude/agents/`, 10 files, 2,019 lines, and `templates/`, 5 markdown files plus one CSV, **720 lines total** (717 markdown + 3 CSV; the earlier draft reported 717 as the total).

**D. The client-tier schema already exists as a file.** `clients/_template/brand.yaml`, 168 lines, 14,297 bytes, with named blocks: `client`, `nap`, `locations[]`, `schema`, `gbp`, `brand_terms`, `services`, `service_areas`, `primary_city`, `storage`, `entity`, `competitive_set`, `eeat`, `vertical`, `trade_is_ymyl`, `voice`, `guardrails`, `case_log`. Two filled examples exist (`clients/sample-dental/`, `clients/sample-storage/`). **This is the client-tier value schema, already designed, already exercised.** It maps cleanly onto the existing `client_business_profiles` table (`db/migrations/0051_client_business_profile.sql`) for the NAP subset, and R3A-12 already proposes `client_locations` for the `locations[]` array. `guardrails` is the "no-go topics" field the brief asks for; `voice` is the voice field; `case_log` is a client-tier fact log.

**E. The live repo material.** 31 `aios-*` operator skills, 3,381 lines of `SKILL.md` across them, each encoding a real operator workflow with its permission gate, its degrade behaviour and its honest-reporting rule. Plus `.claude/skills/_shared/reference/` (5 files: `CONTENT-DOCTRINE.md` 193 lines, `part8-output-formats.md` 468, `output-formats.md` 138, `PAGE-TEMPLATES.md` 130, `skill-parity.md` 44), `backend/app/services/page_blueprints.py` (7 page templates), `backend/app/services/policy_baseline.py` (16 seeded baseline recommendations), and `db/migrations/0050_policy_sources_seed.sql` (8 watched Google sources: Search Central Blog RSS, Search Status Dashboard incidents JSON, Search Essentials, Spam Policies, Ranking Systems Guide, Helpful Content Guidance, Structured Data Policies, Search Central Updates).

**F. The research dossiers (inside the zip).** `research/`, 18 files, 3,821 lines across two sets: `expansion-2026-07/` (9 files on topical authority tooling, local SEO authorities, copywriting, GEO, competitive teardown, process measurement, internal audit, above-the-page architecture) and `self-storage-2026-07/` (9 cited vertical dossiers). These are **provenance for the global tier, not global-tier entries themselves**: they are where a `check_config` entry's `source_url` comes from.

**One material risk that this inventory exposes.** The zip is a single binary blob tracked in git. There is no file-level history, no diff, no code review, and no grep. If the substrate is seeded from it and the zip is later replaced, nobody can tell what changed. **Extracting it to a real directory is a prerequisite to seeding, not a follow-up.**

### 3.10 Model IDs and pricing, verified today, with one repository constant wrong by 50 percent

**Conclusion: current model IDs and prices are as tabulated below. `backend/app/config.py:759-760` overstates Sonnet cost by 50 percent, so every Sonnet spend the cost gate has ever logged is 1.5x the true figure.**

Verified at the official pricing page, accessed 2026-08-23 [anthropic-pricing]:

| Model | Model ID | Base input $/MTok | 5m cache write | 1h cache write | Cache read | Output $/MTok | Batch in | Batch out |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| Claude Opus 5 | `claude-opus-5` | $5.00 | $6.25 | $10.00 | $0.50 | $25.00 | $2.50 | $12.50 |
| Claude Sonnet 5 | `claude-sonnet-5` | $2.00 | $2.50 | $4.00 | $0.20 | $10.00 | $1.00 | $5.00 |
| Claude Haiku 4.5 | `claude-haiku-4-5` | $1.00 | $1.25 | $2.00 | $0.10 | $5.00 | $0.50 | $2.50 |

The pricing page carries an explicit note: "The $2/$10 per million input/output token pricing for Claude Sonnet 5, announced at launch as introductory pricing through August 31, 2026, is now the standard price. The previously scheduled increase to $3/$15 per million input/output tokens on September 1, 2026 will not occur" [anthropic-pricing].

`backend/app/config.py:759-760` sets `price_anthropic_sonnet_input_per_mtok = 3.00` and `price_anthropic_sonnet_output_per_mtok = 15.00`. Those were correct for the pre-launch schedule and are now wrong. Because `backend/app/services/pricing.py:64-75` computes committed spend from these constants (via `anthropic_prices` at `:46-62` and `anthropic_tier` at `:31-43`), every Sonnet call the cost gate has committed is overstated by 50 percent, which propagates to per-client caps, the daily spend-stop and every cost figure shown to Daniel. Correcting it is a two-line change with a test.

Two further verified facts that bear on routing:

- **Batch API is a flat 50 percent discount on both input and output**, and the multipliers stack with prompt caching [anthropic-pricing].
- **Anthropic server-side web search is $10 per 1,000 searches**; **web fetch has no additional charge** beyond the tokens of the fetched content [anthropic-web-search, anthropic-pricing]. `backend/app/config.py:768` already has `price_web_search_per_search = 0.01`, which is correct.

### 3.11 Structured outputs is GA and satisfies the typed-output requirement, but the supported-model list names the dated Haiku id

**Conclusion: use `output_config.format` with `type: "json_schema"` and `additionalProperties: false` for every typed output. No beta header. For Haiku, pin `claude-haiku-4-5-20251001`.**

Verified at the structured outputs documentation, accessed 2026-08-23 [anthropic-structured-outputs]. The request shape is:

```json
{"output_config": {"format": {"type": "json_schema",
  "schema": {"type": "object", "properties": {...},
             "required": [...], "additionalProperties": false}}}}
```

No beta header is required; the old `structured-outputs-2025-11-13` header is still accepted for transition. The documented supported-model list is: `claude-fable-5`, `claude-mythos-5`, `claude-mythos-preview`, `claude-opus-5`, `claude-opus-4-8`, `claude-opus-4-7`, `claude-opus-4-6`, `claude-sonnet-5`, `claude-sonnet-4-6`, `claude-sonnet-4-5-20250929`, `claude-opus-4-5-20251101`, **`claude-haiku-4-5-20251001`**. Note the last entry is the dated snapshot; the undated alias `claude-haiku-4-5` is not on the list. The repository already pins that exact dated id in one place (`docs/audit/AI_AUDIT.md` §1 records "6 + 1 pinned `-20251001`"), so the fix is to make it the routing constant for classification rather than an accident.

Documented schema restrictions that constrain the substrate's own typed payloads: recursive schemas are not supported, external `$ref` is not supported, and **numerical constraints (`minimum`, `maximum`, `multipleOf`) and string constraints (`minLength`, `maxLength`) are not supported**. That last one matters directly: the bounds on a value cannot be delegated to the schema. The docs add one mechanic the first draft omitted: **the Python, TypeScript, Ruby and PHP SDKs automatically transform such schemas** — they strip the unsupported constraint from the schema that is sent, fold it into the field description ("Must be at least 100"), and validate the response against the *original* schema client-side [anthropic-structured-outputs]. So on a raw `messages.create()` call the bound must be re-validated in Pydantic after parsing; on `messages.parse()` the SDK does it. Pick one and state it in the module CLAUDE.md, because the two paths fail differently. Grammar compilation adds latency on the first request with a new schema and compiled grammars are cached for 24 hours; changing `output_config.format` invalidates the prompt cache for that thread, which is another reason to keep one stable schema per task class rather than building schemas dynamically.

This directly closes `AI-006` ("Structured AI output is schema-validated; an output inventing a metric is rejected", PROPOSED, P0, `docs/recovery/REQUIREMENTS_TRACEABILITY.md:343`), which is currently satisfied only by hand-rolled defensive parsing (`backend/app/services/policy_watch.py:_extract_json`, `parse_analysis`).

### 3.12 "Beats 99% of SEO strategists" cannot be measured. The closest honest proxy has a computable bar

**Conclusion: state plainly that the claim is unmeasurable as written, and replace it with a blind pairwise preference trial whose pass mark is 32 wins out of 50.**

The owner's bar is recorded as "content output that beats 99% of SEO strategists" (`docs/research/R3A-content-intelligence.md:21`). It is unmeasurable for three reasons, and saying so is the correct engineering answer rather than a failure of nerve: there is no census or sampling frame of "SEO strategists", so a percentile has no denominator; there is no standardised instrument that scores an SEO deliverable on a comparable scale; and the quantity that would actually matter (ranking outcome) is confounded by domain authority, backlink profile, competition and Google update timing, none of which the content controls.

**What can be measured, and the exact bar.** A blind pairwise preference trial. Purchase 50 human specialist deliverables at market rate against the same 50 briefs the platform runs (Fiverr is already the agency's lead channel, so this is a purchase the agency can make). Strip both outputs of identifying formatting. Three independent senior SEO reviewers, none of whom worked on the platform, pick a winner per pair on the 14 QA dimensions, with the tie option removed. Report the platform's win rate with a Wilson 95 percent confidence interval.

**Pass at 32 wins or more out of 50.** That is the smallest integer at n=50 whose Wilson 95 percent lower bound exceeds 0.5. **Corrected in verification (the first draft's centre and half-width were wrong; the threshold they implied was right):** at x=32, z=1.96, the Wilson centre is **0.6300** with a half-width of **0.1286**, giving a lower bound of **0.5014**. At x=31 the centre is 0.6114, the half-width 0.1299 and the lower bound **0.4815**, below 0.5. The arithmetic is reproducible from the standard Wilson formula and is stated here so nobody has to re-derive it or, worse, invent a threshold.

**The substrate's own contribution is measured separately, by ablation**, because a pairwise win says nothing about which layer produced it. Run the same 50 briefs four times: full substrate, global tier only, global plus agency, and no substrate at all. Measure the deterministic gate pass rate (a number the platform computes, not a judgement) and the pairwise win rate for each arm. If the full substrate does not beat the no-substrate arm on gate pass rate, the substrate is not doing anything and the finding must be reported rather than buried.

---

## 4. Options considered and why rejected

**Three separate tables, one per tier.** Rejected: precedence resolution becomes a three-way `LEFT JOIN` with `COALESCE` per key and conflict detection becomes a three-way join, both untestable at width; adding a per-site or per-campaign scope later becomes three migrations instead of one enum label; and the repository has already chosen the opposite pattern deliberately, with its reasoning recorded at `db/migrations/0027_audit_overlay.sql:12-20`.

**Unqualified strict precedence with no `overridable` flag.** Rejected on a specific, demonstrable failure: a client-tier entry setting the doorway/thin-content check to `off` would win, and the platform would sign off a doorway network that matches Google's own published definition of scaled content abuse [google-spam-policies]. See 3.2.

**Store the substrate as retrieved documents and let the model read the playbooks.** Rejected on three grounds, any one of which is disqualifying. Size: 1,429,288 bytes is roughly 357,000 tokens at the repository's own 4-chars-per-token convention (`backend/app/services/pricing.py:28`), which does not fit alongside a task payload. Determinism: a check whose threshold is retrieved is a check whose threshold varies with the retrieval, which fails `AI-001`. Testability: you cannot snapshot-test a similarity search, and requirement R6-16 makes the assembled bundle snapshot-testable.

**A second vector store dedicated to the substrate.** Rejected as explicitly out of bounds, and independently unnecessary. The context module already has a ledger-backed derived-index design (`db/migrations/0014_entity_context.sql`) that a `'knowledge'` enum label would extend without a new store. It is also unnecessary in v1 because the selection problem is a 252-row lookup table (3.6).

**Turn Pinecone and Voyage back on for the substrate.** Rejected. The deployment deliberately excludes them (`backend/pyproject.toml:49-58`), the exclusion is confirmed by the AI audit and re-confirmed independently by R2, and reversing a documented dependency decision to solve a lookup-table problem is the wrong trade. Kept as a named, triggered option in Open Items.

**Inject the raw playbook markdown for the page type being written.** Rejected: `knowledge/playbooks/service-page.md` alone is 55,104 bytes, roughly 13,800 tokens, before the client tier or the SERP teardown. It is also mostly reviewer-facing rationale, which by 3.5 does not belong in a generation prompt.

**Inject the vertical teardown examples to improve draft quality.** Rejected on a safety ground rather than a cost one: a competitor teardown in a generation prompt is a template for reproducing a competitor's page. The teardowns are reviewer-facing.

**Let a model resolve tier conflicts.** Rejected under `AI-001` and under the automation ceiling. A conflict resolution changes what gets published; that is a decision, not a narrative, and the model may explain it but not make it.

**Batch API for the content draft path.** Not rejected, but deferred and scoped. The 50 percent discount is real and verified [anthropic-pricing], and R3A already models it for bulk fan-out. It is out of scope for R6 because the substrate prefix caching interacts with it (both discounts stack, per the pricing page, but the batch turnaround breaks the 5-minute cache window). R3A owns that call.

**Keep model IDs as constructor defaults.** Rejected: `integrations/llm.py:98-99` hard-codes `model_summary` and `model_heavy`, so a model upgrade is a code change. `docs/audit/AI_AUDIT.md` finding AI-9 already flags this. R6-21 moves them.

**Pad the Haiku classification prompt to reach the 4,096-token cache minimum.** Rejected: it buys a 0.1x read on tokens that had no reason to exist, and the tokens still cost something on the write. Accept no caching on the Haiku path and document it.

---

## 5. Engineering requirements this imposes

### 5.1 Prerequisite

**R6-1. Extract `SEO-CONTENT-OS.zip` to a real, tracked directory before any other R6 work.** Target path `knowledge-base/seo-content-os/` (the repo already has a top-level `knowledge-base/`, so this needs no new top-level directory), preserving the internal layout. Then either delete the zip or move it out of the tree. Then repoint every dangling citation: `backend/docs/CONTENT-DOCTRINE.md:8`, `backend/app/services/content_qa.py:69-70`, `backend/app/services/content_generator.py:54-59`. Add a CI check that fails if any source file cites a path that does not exist. This is R3A-37(b) and R6 owns it; do not do it twice.

### 5.2 The data model

**R6-2. Create the enums.**

```sql
create type public.knowledge_tier as enum ('global', 'agency', 'client');
create type public.knowledge_kind as enum (
  'framework', 'check_config', 'taxonomy', 'sop', 'voice',
  'fact', 'policy_summary', 'no_go', 'severity_override', 'prompt_fragment');
create type public.knowledge_status as enum ('draft', 'active', 'superseded', 'retired');
create type public.knowledge_conflict_severity as enum ('info', 'warn', 'block');
```

**R6-3. Create `public.knowledge_entries`.**

| Column | Type | Notes |
|---|---|---|
| `id` | `uuid pk default gen_random_uuid()` | |
| `tier` | `public.knowledge_tier not null` | |
| `client_id` | `uuid references public.clients(id) on delete cascade` | `not null` iff `tier='client'`; `null` otherwise (check constraint) |
| `key` | `text not null` | dotted resolution key, e.g. `check.g3_doorway`, `voice.blocklist_tier1`, `policy.scaled_content_abuse`, `client.no_go_topics` |
| `kind` | `public.knowledge_kind not null` | |
| `title` | `text not null` | human label |
| `value` | `jsonb not null` | **the typed payload; this is what is injected** |
| `body_md` | `text not null default ''` | prose rationale, reviewer-facing, **never injected into a generation prompt** |
| `overridable` | `boolean not null default true` | see 3.2 |
| `version` | `int not null` | monotonic per `(tier, client_id, key)` |
| `status` | `public.knowledge_status not null default 'draft'` | |
| `effective_from` | `timestamptz not null default now()` | activation is scheduled, not on write (see R6-19) |
| `effective_to` | `timestamptz` | null = open |
| `source_kind` | `text not null default 'operator'` | one of `seed`, `operator`, `policy_radar`, `import` |
| `source_ref` | `text not null default ''` | seed file path, or `recommendations.kb_ref` |
| `source_url` | `text not null default ''` | primary-source citation |
| `policy_asof` | `date` | required when `kind='policy_summary'` (check constraint) |
| `checksum` | `text not null` | sha256 of canonical sorted JSON of `value` |
| `created_by` / `approved_by` | `uuid references public.users(id)` | |
| `approved_at` | `timestamptz` | |
| `created_at` / `updated_at` | `timestamptz not null default now()` | `updated_at` via the shared `set_updated_at` trigger |

Constraints and indexes:
- `check ((tier = 'client') = (client_id is not null))`
- `check (kind <> 'policy_summary' or policy_asof is not null)`
- `unique nulls not distinct (tier, client_id, key, version)` (PostgreSQL 15 and later; the platform is on 16)
- `create unique index knowledge_entries_active_uq on public.knowledge_entries (tier, client_id, key) nulls not distinct where (status = 'active')`, giving at most one active version per key per scope
- `create index knowledge_entries_key_idx on public.knowledge_entries (key)`
- `create index knowledge_entries_client_idx on public.knowledge_entries (client_id) where client_id is not null`

RLS, mirroring `client_business_profiles` exactly: `enable` and `force`; select policy `using (public.is_staff())`; insert and update policies `with check (public.current_app_role() in ('owner','admin','manager'))`; no delete policy. A retired entry is `status='retired'`, never deleted.

**R6-4. Create the client-facing view.** `public.portal_knowledge` as a `security_barrier` view selecting `key, title, value, updated_at` from `knowledge_entries` where `tier='client' and client_id = public.current_client_id() and status='active' and kind in ('voice','no_go','fact')`. Mirrors `portal_context` (`db/migrations/0014_entity_context.sql:92-109` — the view at `:97-104`, the comment at `:106-107`, the grant to `authenticated, anon` at `:109`) exactly, including that grant. Clients see their own voice, no-go topics and facts; never the global or agency tiers, never a check threshold, never another tenant.

**R6-5. Create `public.knowledge_conflicts`.**

| Column | Type |
|---|---|
| `id` | `uuid pk` |
| `client_id` | `uuid references public.clients(id) on delete cascade` (null for a global/agency conflict) |
| `key` | `text not null` |
| `conflict_class` | `text not null` in (`non_overridable`, `set_intersection`, `stale_policy`) |
| `severity` | `public.knowledge_conflict_severity not null` |
| `winning_entry_id` | `uuid not null references public.knowledge_entries(id)` |
| `losing_entry_id` | `uuid not null references public.knowledge_entries(id)` |
| `detector` | `text not null` in (`resolve`, `import`, `policy_apply`, `nightly_sweep`) |
| `detail` | `jsonb not null default '{}'` (for class 2: the intersecting members) |
| `status` | `text not null default 'open'` in (`open`, `acknowledged`, `resolved`) |
| `acknowledged_by` / `acknowledged_at` / `note` | |
| `detected_at` / `created_at` / `updated_at` | |

Partial unique index: `unique (key, winning_entry_id, losing_entry_id) where status = 'open'`, so re-detecting an open conflict is idempotent. Same RLS as `knowledge_entries`.

**R6-6. Create `public.context_bindings`, the provenance record.**

| Column | Type | Notes |
|---|---|---|
| `id` | `uuid pk` | |
| `job_type` | `text not null` | `content_job`, `audit`, `policy_brief`, `review_reply`, `web2_article` |
| `job_id` | `text not null` | the module's own public code, e.g. `CJ-1234` |
| `client_id` | `uuid` | null for a non-client job |
| `task_class` | `text not null` | see R6-20 |
| `assembled_at` | `timestamptz not null default now()` | |
| `bundle_checksum` | `text not null` | sha256 of the canonical bundle JSON |
| `entry_versions` | `jsonb not null` | array of `{entry_id, tier, key, version}` |
| `conflict_ids` | `uuid[] not null default '{}'` | |
| `token_count` | `int not null` | measured, not estimated |
| `model` | `text not null` | the resolved model id |
| `prefix_checksum` | `text not null` | sha256 of the cached global+agency prefix, for cache-hit debugging |

Index: `create index context_bindings_entry_gin on public.context_bindings using gin (entry_versions jsonb_path_ops)`, which is what makes the supersession query in R6-18 a lookup rather than a scan. Insert-only: no update policy, no delete policy, mirroring R3A-43's evidence-table discipline.

### 5.3 Resolution, conflict detection and assembly

**R6-7. The resolver is one query and it is the only path.** `backend/app/db/knowledge_repo.py::resolve(client_id, keys)`:

```sql
select distinct on (key) id, tier, key, kind, value, version, overridable
from public.knowledge_entries
where status = 'active'
  and effective_from <= now()
  and (effective_to is null or effective_to > now())
  and key = any($2)
  and (tier in ('global','agency') or client_id = $1)
order by key,
         case tier when 'client' then 0 when 'agency' then 1 else 2 end,
         version desc;
```

`DISTINCT ON (key)` with that `ORDER BY` is strict precedence CLIENT > AGENCY > GLOBAL, expressed once. No other code path may read `knowledge_entries` for resolution.

**R6-8. The non-overridable rule, enforced in the resolver, not in a caller.** After the query above, re-select the same keys and detect any row where a higher-precedence entry displaced a lower-precedence entry carrying `overridable = false`. In that case the resolver **returns the non-overridable value** and emits a `knowledge_conflicts` row with `conflict_class='non_overridable'`, `severity='block'`. The resolver never returns the losing value silently and never drops the attempted override.

**R6-9. Every assembly writes a `context_bindings` row before any model call.** No exception, including degraded and fake-provider paths. The binding is written first so that a job that later crashes still records what it was going to be generated against.

**R6-10. Conflict class 2 is declared, not inferred.** A `check_config` entry's `value` may carry `"conflicts_with": [{"key": "client.no_go_topics", "predicate": "intersects", "field": "topics", "members": ["pricing"]}]`. The detector evaluates the predicate as a set intersection over typed arrays. Seed the first instance from gate G13 versus `brand.yaml.guardrails`, which is the real case from 3.4.

**R6-11. Conflict class 3 runs as a nightly Celery beat task** `sweep_stale_policy_knowledge`, comparing `knowledge_entries` where `kind='policy_summary'` against `kb_entries.detected_at` on the same key. This task must not be scheduled until the job contract (P0-3 in `docs/implementation/KNOWN_LIMITATIONS.md` §1) lands, per the plan's own ordering rule; until then it is invocable on demand.

**R6-12. `assemble()` is a pure function with no I/O.** `backend/app/services/knowledge_assembly.py::assemble(resolved_entries, task, client_snapshot) -> ContextBundle`. The repository layer does the reads; the assembler does no network and no database access, mirroring the purity convention already used by `content_qa.py`, `content_guard.py` and `policy_watch.py`'s pure cores.

### 5.4 The prompt-assembly contract

**R6-13. Four segments, this order, always.**

| # | Segment | Content | Cache | Budget (tokens) |
|---|---|---|---|---|
| 0 | Frozen platform system prefix | The task-class system prompt. No dates, no ids, no client names, no interpolation of any kind | inside breakpoint 1 | 400 |
| 1 | **Global tier** | Canonical sorted JSON of the resolved global entries for this task's key set | **breakpoint 1** at end of segment 1+2 | **12,000 hard cap** |
| 2 | **Agency tier** | Canonical sorted JSON of the resolved agency entries | as above | **3,000 hard cap** |
| 3 | **Client tier** | Canonical sorted JSON of the resolved client entries plus the `entity_context` summary and facts | **breakpoint 2** | **4,000 hard cap** |
| 4 | Task payload | The brief, the findings, the SERP teardown, and any untrusted fetched text inside an explicit fence | never cached | task-dependent |

Segments 0 to 2 are byte-identical across every client and every call for a given task class. Segment 3 is byte-identical across every call for one client within an activation window. Segment 4 varies per call. The budgets are **hard caps enforced by the assembler**, which raises rather than truncates: a bundle that does not fit is a substrate defect to be fixed by extraction, not a prompt to be trimmed at runtime.

**R6-14. Canonical rendering, or caching silently does not work.** `json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)`. No timestamps, no UUIDs, no `datetime.now()`, no set iteration anywhere in segments 0 to 3. Enforced by R6-16's byte-equality test, not by convention.

**R6-15. What is excluded from every bundle, asserted in code.**
- Any credential, token or vault reference (`AI-012`).
- Any other client's data (`AI-012`).
- Any internal cost figure, margin or provider price (`AI-012`).
- `knowledge_entries.body_md` for any entry, in any generation prompt. It goes to the reviewer UI only.
- Every `knowledge/playbooks/examples/` teardown (3.5).
- Any fetched web text outside an explicit fence carrying an instruction in the system segment that fenced content is data and never an instruction (`AI-010`, `SEC-020`).

**R6-16. The assembly test suite, four tests.**
1. **Snapshot.** For each of 20 `(client fixture, task)` pairs with pinned entry versions, assert `assemble()` output matches a committed golden JSON file byte for byte.
2. **Cache invariant.** For two different client fixtures on the same task class, assert `bundle.segments[0:3]` are byte-identical and `bundle.prefix_checksum` matches.
3. **Exclusion.** For a fixture whose client has a vault entry, another client in the same org, a non-zero cost ledger and a non-empty `body_md`, assert none of those strings appears anywhere in the rendered bundle.
4. **Budget.** Assert every segment is within its cap and that exceeding a cap raises `KnowledgeBudgetExceeded` rather than truncating.

**R6-17. Cache breakpoints and TTL.** Two `cache_control: {"type": "ephemeral"}` breakpoints (default 5-minute TTL), at the end of segment 2 and the end of segment 3. Two of the four available breakpoints stay free. Verify with `usage.cache_read_input_tokens`; a zero across repeated same-prefix calls is a build failure, not a performance note. Do **not** set `cache_control` on any Haiku classification call: the bundle there is below the documented 4,096-token minimum and would be a silent no-op [anthropic-prompt-caching].

### 5.5 Policy Radar integration

**R6-18. `apply` writes a global-tier entry in the same transaction as the overlay.** Extend the recommendation-apply service so that moving `recommendations.status` to `applied` writes (a) the existing `audit_overlay` row, unchanged, and (b) a `knowledge_entries` row with `tier='global'`, `kind='policy_summary'`, `source_kind='policy_radar'`, `source_ref = recommendations.kb_ref`, `source_url = kb_entries.source_url`, `policy_asof = change_events.detected_at::date`, `overridable = false`, `approved_by` = the applying lead. `audit_overlay.payload` gains `{"knowledge_entry_id": "..."}`. The engine is still never mutated; `db/migrations/0027_audit_overlay.sql`'s hard rule is untouched.

**R6-19. Global and agency activation is batched to one daily window.** An entry is written with `status='draft'`; a lead approves it; approval sets `status='active'` and `effective_from` to the next daily activation boundary (default 03:00 in `workspace_settings.timezone`, `db/migrations/0025_settings.sql:42`). Client-tier entries activate immediately. Rationale in 3.7: an unbatched global activation rebuilds the shared prompt-cache prefix for the entire platform.

**R6-20. Supersession triggers re-evaluation.** When an entry moves to `superseded`, enqueue `reevaluate_bindings(entry_id)`, which runs the GIN-indexed query on `context_bindings.entry_versions`, and for each affected published page raises an R3A `maintenance_items` row with `trigger = 'KNOWLEDGE_SUPERSEDED'`, `evidence` carrying the old and new entry ids, versions and `policy_asof` values. R6 does not create a second maintenance queue; it writes into R3A-49's.

### 5.6 Model routing and the API contract

**R6-21. Replace the constructor defaults with a settings-driven route table.** Delete the hard-coded `model_summary` and `model_heavy` defaults at `backend/integrations/llm.py:98-99` as the routing authority (keep them as last-resort fallbacks) and add `MODEL_ROUTES: dict[str, ModelRoute]` in `backend/app/config.py`, env-overridable per key:

| Task class | Model id | Effort / notes | Why |
|---|---|---|---|
| `content_draft` | `claude-sonnet-5` | streaming | Highest-volume generative call. At $2/$10 it is 2.5x cheaper than Opus 5 on both legs, and the draft is heavily constrained by the substrate and the fact set, so headroom buys little. Matches R3A's recommended mix |
| `qa_judge` | `claude-opus-5` | `effort: high` | The judge's output gates publication for a human. It is the one place where a wrong call is expensive and the token volume is small (3,000 output tokens per page) |
| `research_synthesis` | `claude-opus-5` | `effort: high`, `web_search_20260209` | Open-ended synthesis over untrusted web text. R3A assigns Opus 5 here; do not diverge |
| `audit_narrative` | `claude-sonnet-5` | | Long-form prose over already-computed findings. The findings are the hard part and Python did them |
| `audit_strategy` (paid only) | `claude-opus-5` | `effort: high` | The executive summary of a paid audit is the client-facing judgement artefact |
| `review_reply` | `claude-sonnet-5` | | Tone-sensitive, short, always human-approved at L3 |
| `policy_summary_prose` | `claude-sonnet-5` | | A global-tier entry steers every downstream module. See the note below |
| `policy_classification` | `claude-haiku-4-5-20251001` | `output_config.format` | Six-way and four-way enum classification. Honours `AI-003` / `AI-R3`. Dated id because that is the id the structured-outputs docs list |
| `context_fold` | `claude-haiku-4-5-20251001` | | Bounded living summary. Unchanged from today |
| `directory_classification` | `claude-haiku-4-5-20251001` | `output_config.format` | Matching a listing to a canonical business |
| `intent_classification` | `claude-haiku-4-5-20251001` | `output_config.format` | Semantic label from a closed taxonomy |

**Explicit note on a prior decision.** `AI-003` records "Policy categorisation uses Claude Haiku" as CONFIRMED from `[OVERHAUL]` §D, at P2 (`docs/recovery/REQUIREMENTS_TRACEABILITY.md:340`), and `AI-R3` records "Policy categorisation explicitly uses Haiku | CONFIRMED — `[OVERHAUL]` §D" (`docs/recovery/DANIEL_PROJECT_RECOVERY_SPECIFICATION.md:1324`). (The first draft quoted a composite of the two that appears in neither; corrected in verification.) R6 **splits** that call rather than contradicting it: **categorisation** (the `severity` / `category` / `region` / `target_module` enums) stays on Haiku, honouring the requirement literally; the **summary prose and recommended action**, which are not categorisation and which become a non-overridable global-tier entry, move to Sonnet 5. The cost of the split is under $2 per month (section 6). Flagging it here rather than doing it silently.

**R6-22. Correct the Sonnet price constants.** `backend/app/config.py:759-760`: `price_anthropic_sonnet_input_per_mtok` 3.00 to **2.00**, `price_anthropic_sonnet_output_per_mtok` 15.00 to **10.00** [anthropic-pricing]. Add a test asserting each constant against a committed, dated table, so the next price change is a visible test failure and not a silent drift.

**R6-23. Add cache-price constants.** `price_anthropic_{haiku,sonnet,opus}_cache_write_5m_per_mtok` and `..._cache_read_per_mtok`, and extend `backend/app/services/pricing.py::anthropic_cost` to price `cache_creation_input_tokens` and `cache_read_input_tokens` separately from `input_tokens`. Today `anthropic_cost` (`backend/app/services/pricing.py:64-75`) sees only `input_tokens` and `output_tokens`, so once caching is enabled it will **understate** spend, because the cache write is billed at 1.25x and appears in a field the function does not read.

**R6-24. Every typed output uses `output_config.format`.** Replace the hand-rolled `_extract_json` plus `parse_analysis` defensive parse (`backend/app/services/policy_watch.py`) with a declared JSON schema per task class, `additionalProperties: false`, one stable schema object per task class held as a module constant so the grammar cache and the prompt cache both hold. Keep the enum clamping (`_clamp` at `policy_watch.py:200-203`, applied at `:245-253`) as a second line of defence: the schema constrains the shape, the clamp constrains the vocabulary, and both are cheap.

**R6-25. Token-budget discipline, three ceilings.** (a) Per-segment caps from R6-13, enforced by the assembler. (b) A per-call `max_tokens` set from the task class, never a global default. (c) A per-job token ceiling recorded on the job and enforced by the cost gate before dispatch, which is `AI-009` / `AI-R7` (PROPOSED, P1) and is currently unbuilt. Without (c), one runaway generation can consume a client's monthly cap.

### 5.7 Seeding

**R6-26. Seed in four numbered waves, each with its own migration and its own acceptance test.**

- **Wave 1, checks.** `knowledge/quality-gates/gates.md` (308 lines) to `kind='check_config'`, one entry per gate: PLAN, G0 to G13. Each `value` carries `{"gate_id", "auto_fail": bool, "applies_to_page_types": [...], "thresholds": {...}, "detect": "<procedure id>", "conflicts_with": [...]}`. Every gate marked auto-fail in the source gets `overridable = false`. Acceptance: `content_qa.py`'s 14 dimensions each resolve to a seeded entry, and a test asserts the mapping is total in both directions.
- **Wave 2, doctrine and policy.** `knowledge/doctrine/` (7 files, 1,004 lines) to `kind='framework'` for the law sets and `kind='policy_summary'` for each Google position, each with `policy_asof` and `source_url` pointing at the primary Google page. The **17** spam-policy headings (16 named spam categories plus "Other practices that can lead to demotion or removal") become one `kind='taxonomy'` entry sourced from [google-spam-policies]. `llms-txt-verdict.md` seeds at severity `info` with an explicit note citing [google-ai-features]. All `overridable = false`.
- **Wave 3, voice and agency SOP.** `knowledge/voice/vocabulary-blocklist.md` to `kind='voice'`, one entry per tier (`voice.blocklist_tier1`, `_tier2`, `_tier3`) with `value.terms[]` in the same grammar `term_to_regex` compiles (`blocklist_lint.py:67`). **Scope note from verification: `parse_blocklist` today extracts Tier 1 only (`:148-153`), so `_tier2` and `_tier3` require new parsing, and the per-client phrases arrive through `load_extra_banned` (`:250`) rather than the markdown.** `knowledge/frameworks/` (10 framework files plus a README) to `kind='taxonomy'`; **the mapping onto the existing `content_framework` enum is partial in both directions** (see 3.9), so Wave 3 must decide explicitly whether the enum is extended, the extra files are seeded as taxonomy-only entries with no enum label, or both — and a test must assert whichever total mapping is chosen. Agency-tier SOPs seeded empty with a documented shape, because they are Daniel's to write (see Open Items).
- **Wave 4, client tier.** `clients/_template/brand.yaml`'s 18 named blocks become the client-tier key schema. `nap`, `services`, `service_areas`, `primary_city`, `gbp` back-fill from the existing `client_business_profiles` row (`db/migrations/0051_client_business_profile.sql`). `guardrails` becomes `kind='no_go'`. `voice` becomes `kind='voice'`. `eeat`, `entity`, `competitive_set`, `case_log` become `kind='fact'`. `locations[]` defers to R3A-12's `client_locations`; do not duplicate it here.

**R6-27. The 252-row selection table.** `knowledge_key_sets(task_class, page_type, vertical, key text[])`, seeded from the load order documented at **`SEO-CONTENT-OS/CLAUDE.md:86` ("Load order (read only what the task needs, in this order)")** — corrected in verification; `SYSTEM-MAP.md` describes `CLAUDE.md` as the file that carries the load order (`SYSTEM-MAP.md:266`) but does not itself contain one. This table, not a similarity search, decides which keys a given task resolves. Adding a page type or a vertical is a row, not a code change.

**R6-28. Do not seed from prose at runtime.** Seeding is a migration that runs a parser once, commits typed JSON, and is reviewable in the diff. The markdown stays in the tree as the human-editable artefact and as the `source_ref`, exactly as `vocabulary-blocklist.md` relates to `blocklist_lint.py` today. A drift test asserts that re-parsing the markdown reproduces the seeded `checksum`; a mismatch is a build failure that forces a deliberate re-seed.

### 5.8 Evaluation

**R6-29. Build the golden set as five separate suites, not one.** (a) 20 assembly snapshots (R6-16). (b) 15 seeded conflicts, one per class per severity, asserting detection, class and severity. (c) The 50-brief pairwise trial (R6-30). (d) The four-arm ablation (3.12). (e) An injection corpus over `body_md` and imported client text, closing `AI-010` / `SEC-020` for the substrate surface specifically.

**R6-30. The pairwise trial, stated so it cannot be re-litigated.** 50 briefs; 50 purchased human specialist deliverables against the same briefs; identifying formatting stripped from both; three independent senior SEO reviewers who did not work on the platform; forced choice, no tie option; graded on the 14 QA dimensions. **Pass at 32 or more wins out of 50** (the smallest integer whose Wilson 95 percent lower bound exceeds 0.5: centre **0.6300**, half-width **0.1286**, lower bound **0.5014**; at 31 the lower bound is 0.4815). Report the interval, not just the count. **The claim "beats 99% of SEO strategists" is not to be used in any client-facing or investor-facing material**, because it is unmeasurable as stated and this project's founding defect was asserting numbers nobody had measured.

---

## 6. Cost model at 100 clients

All Anthropic unit prices verified at [anthropic-pricing], accessed 2026-08-23. Volume assumptions come from R3A's paced-publication recommendation so the two records agree: 100 clients at 6 pages per client per week is **2,600 pages per month**, and R3A's sub-call model is 5 model calls per page, giving **13,000 substrate-carrying content calls per month**.

**Assumption stated plainly:** the 15,000-token stable prefix (12,000 global + 3,000 agency) is a **design budget imposed by R6-13**, not a measurement of an extraction that has not happened yet. If the extraction does not fit, the requirement is to extract harder, not to raise the budget. Everything below scales linearly with that number. (Noted in verification: the cached region in R6-13 is segments 0+1+2 = 400 + 12,000 + 3,000 = **15,400** tokens, so every figure below understates by about 2.7 percent. The direction is conservative and the conclusion is unaffected; use 15,400 when the extraction is measured for real.)

### 6.1 The substrate prefix, cached versus uncached (Sonnet 5)

Per call, 15,000 prefix tokens:

- Uncached input: 15,000 x $2.00 / 1,000,000 = **$0.03000**
- 5-minute cache write: 15,000 x $2.50 / 1,000,000 = **$0.03750**
- Cache read: 15,000 x $0.20 / 1,000,000 = **$0.00300**

Break-even: write plus one read is $0.04050 against two uncached calls at $0.06000. **Caching pays from the second call onward.**

Monthly, 13,000 calls:

| Scenario | Writes | Reads | Cost |
|---|---:|---:|---:|
| No caching | 0 | 0 | 13,000 x $0.03000 = **$390.00** |
| **A. Batched work, one cold write per active hour** (~300/month) | 300 | 12,700 | 300 x $0.03750 + 12,700 x $0.00300 = $11.25 + $38.10 = **$49.35** |
| **B. Sparse traffic, one cold write per 4 calls** | 3,250 | 9,750 | 3,250 x $0.03750 + 9,750 x $0.00300 = $121.88 + $29.25 = **$151.13** |

**Saving: $238.87 (scenario B) to $340.65 (scenario A) per month.** The true figure depends on how clustered the work is, and R3A's paced scheduler makes clustering the norm, so the real number should sit nearer A than B. The 1-hour TTL is worse here: at 2x write ($0.06000) with roughly 730 hourly pre-warms, the cost is 730 x $0.06000 + 12,270 x $0.00300 = $43.80 + $36.81 = $80.61, which beats B but loses to A. **Recommendation: 5-minute TTL, and let the scheduler's clustering do the work.** A keep-warm ping against the same prefix would extend scenario A further, and the `max_tokens: 0` mechanic for it is **verified at the primary docs page** (corrected in verification; the first draft marked it `[UNVERIFIED]`): the "Pre-warming the cache" section states "Set `max_tokens: 0` in your request. The API reads your prompt into the model and writes the cache at any `cache_control` breakpoint, then returns immediately without generating any output" [anthropic-prompt-caching]. A keep-warm ping still costs a cache write or read, so it earns its place only where the alternative is a cold write.

Same prefix on Opus 5 (for the `qa_judge` and `research_synthesis` routes, roughly 2,600 QA calls per month at one per page): uncached 15,000 x $5.00/1M = $0.07500; write $0.09375; read $0.00750. Uncached monthly $195.00; scenario-A cached 60 x $0.09375 + 2,540 x $0.00750 = $5.63 + $19.05 = **$24.68**. **Saving roughly $170 per month.**

**Combined substrate caching saving: roughly $409 to $511 per month at 2,600 pages.** (Low end pairs the Sonnet scenario B with the Opus scenario A; high end is A on both.) Against R3A's modelled content cost the substrate prefix is the difference between the substrate being nearly free and being a large fraction of the bill. **Corrected in verification:** R3A's $0.371 and $0.441 per page are the *model-mix* figures, not all-in. R3A's own monthly table (`docs/research/R3A-content-intelligence.md:497-499`) gives **$965/month** at $0.371 (bulk drafting on the Batch API) and **$1,310/month** at $0.504 (the mix *plus* amortised research), not $1,147; and it excludes image generation, which R3A leaves `[UNVERIFIED]` and flags as possibly larger than the entire LLM bill (`:508`).

**One apparent contradiction with R3A, resolved.** R3A concludes "**Caching does not pay here** ... Do not enable caching per page" (`:487`). That verdict is about a *different* prefix: a ~50,000-token per-page prefix written once and read four times inside one page's five sub-calls, where the 1.25x write is not amortised. R6's prefix is the client-independent global-plus-agency segment, written at most a few hundred times a month and read across all 13,000 calls of every client. Both are correct; an implementer must not read R3A's rule as forbidding R6-17.

### 6.2 Policy summarisation, and the cost of the Haiku-to-Sonnet split

Bounded by existing constants: `_PROMPT_MAX_CHARS = 12_000` (`backend/app/services/policy_watch.py:46`), which at 4 chars per token is 3,000 input tokens; `_ANALYSIS_MAX_TOKENS = 900` (`:45`). Eight seeded sources (`db/migrations/0050_policy_sources_seed.sql`), polled daily.

- Haiku 4.5: 8 x (3,000 x $1.00/1M + 900 x $5.00/1M) = 8 x ($0.00300 + $0.00450) = $0.0600/day = **$1.83/month**
- Sonnet 5: 8 x (3,000 x $2.00/1M + 900 x $10.00/1M) = 8 x ($0.00600 + $0.00900) = $0.1200/day = **$3.65/month**

**Delta for R6-21's split: $1.82 per month.** For that, every global-tier policy entry, which is non-overridable and steers every downstream module, is written by the stronger model. This is the cheapest quality upgrade in the entire platform.

The daily brief (`_GEN_MAX_TOKENS = 8000` at `backend/app/services/policy_generate.py:61`, `_MAX_ITEMS = 12` at `:62`): Sonnet 5 at roughly 500 input and 8,000 output tokens is $0.001 + $0.080 = $0.081/day = **$2.46/month**. On Opus 5 it would be $0.2025/day = $6.16/month. Sonnet 5 is the right call; the brief is a digest, not a judgement.

### 6.3 Storage and retrieval

- `knowledge_entries` at, say, 400 global entries + 100 agency + 40 per client x 100 clients = 4,500 rows with jsonb payloads. Immaterial against a 16 GB VPS Postgres.
- **Embedding and vector-store cost: $0.00**, because R6 ships no retrieval. For contrast, the repository's own assumed Voyage price is `price_voyage_per_mtok = 0.06` (`backend/app/config.py:778`), which is the platform's assumption and not a figure this record verified.
- Anthropic web search stays confined to `research_synthesis` and is billed at $10 per 1,000 searches [anthropic-web-search]; the substrate itself performs no searches.

### 6.4 Total substrate-attributable monthly cost at 100 clients

| Line | Monthly |
|---|---:|
| Substrate prefix, Sonnet 5 content path, scenario A | $49.35 |
| Substrate prefix, Opus 5 judge path, scenario A | $24.68 |
| Policy summarisation (8 sources daily, Sonnet 5) | $3.65 |
| Daily policy brief (Sonnet 5) | $2.46 |
| Embeddings and vector store | $0.00 |
| **Total** | **$80.14** |

Against the same prefix uncached and unsplit, the naive figure is $390.00 + $195.00 + $1.83 + $2.46 = **$589.29**. The substrate design, correctly cached, costs about **14 percent** of the naive figure. Scenario B raises the total to roughly $181.

---

## 7. Risks and failure modes

**The substrate becomes a second uncalibrated authority.** The platform already ships one uncalibrated hard number set (`WEIGHTED_TOTAL_THRESHOLD = 85`, `PROVISIONAL = True`, `backend/app/services/content_qa.py:104-107`). Seeding those same numbers into `knowledge_entries` as `check_config` gives them a database row and an air of settledness they have not earned. **Mitigation: every seeded threshold carries `value.provisional = true` and a `source_ref`, and the reviewer UI renders provisional thresholds differently from calibrated ones.** A number without provenance must look different from one with it.

**A client-tier entry is used to switch off compliance.** This is the failure the `overridable` flag exists to prevent, and the flag only works if the seeding gets the flag right. **Mitigation: R6-26 Wave 1 sets `overridable = false` from the source gate stack's own auto-fail marking, mechanically, not by hand, and a test asserts that every gate marked auto-fail in `gates.md` resolves to a non-overridable entry.**

**Prompt-cache prefix churn destroys the saving silently.** A single interpolated timestamp, an unsorted `json.dumps`, or an unbatched global activation turns a $49 line into a $390 line with no error raised. **Mitigation: R6-14 canonical rendering, R6-16 test 2 asserting byte equality, R6-19 batched activation, and a production alert on `cache_read_input_tokens = 0` across a rolling window.**

**The 12,000-token global budget is not achievable and someone raises it instead of extracting harder.** 1.43 MB of source prose has to become 12,000 tokens of typed config, a roughly 30-to-1 compression. **Mitigation: the cap raises rather than truncates (R6-13), so the failure is loud; and the key-set table (R6-27) means a task loads only its own slice, so the cap is per-task, not per-corpus.**

**The seed material's provenance and licence are unestablished.** 1.43 MB of high-quality SEO doctrine arrived as a zip with no authorship record. If any of it is a third party's copyrighted work, it is now the substrate of a client-facing product. **Mitigation: see Open Items. This must be answered by a human before Wave 2 seeds it.**

**Conflict fatigue.** If class-2 detection is tuned loosely, every client with a `guardrails` entry generates conflicts and operators stop reading them. **Mitigation: class 2 is declared, not inferred (R6-10); a conflict exists only where a `check_config` entry explicitly declares a `conflicts_with` predicate.**

**Retrieval creeps back in through a side door.** The pressure to "just embed the playbooks" will recur. **Mitigation: R6-27's key-set table makes the deterministic path the path of least resistance, and the only sanctioned retrieval mechanism is the existing `context_vectors` ledger with a `'knowledge'` enum label (3.6). Any new vector store is a rejected option, on the record.**

**The zip is lost or silently replaced.** The only in-repo copy of the seed material is a binary blob. **Mitigation: R6-1, and it is a prerequisite, not a follow-up.**

**Model deprecation moves under the route table.** Model ids and prices change; the pricing page carries retirement notices for four models today. **Mitigation: R6-22's dated constant test turns a price change into a failing build, and R6-21's settings-driven routes turn a model change into an env var.**

---

## 8. Open items

**O-1. Who writes and maintains the agency tier?** The global tier extracts from existing material and the client tier back-fills from `client_business_profiles` plus onboarding. The agency tier ("our SOPs, our severity overrides, the things we never do") has no source: it is Daniel's professional judgement and it does not exist in written form anywhere in this repository. **Settled by:** a working session with Daniel producing a first agency-tier key set. Until then, seed the agency tier empty with a documented shape and let it resolve to nothing, so the substrate works with two tiers and gains the third when the content exists.

**O-2. Provenance and licence of `SEO-CONTENT-OS.zip`.** `[UNVERIFIED]` who authored the 1.43 MB knowledge base, under what terms, and whether it may be embedded in a product delivered to a third party. The internal SYSTEM-MAP is dated 2026-07-20 PKT and reads as first-party work, but that is an inference. **Settled by:** the owner confirming authorship in writing, before Wave 2 seeds it. This blocks seeding, not design.

**O-3. Does the undated `claude-haiku-4-5` alias support structured outputs?** The documented list names `claude-haiku-4-5-20251001` and not the bare alias [anthropic-structured-outputs]. `[UNVERIFIED]` whether the alias resolves to a snapshot that accepts `output_config.format`. **Settled by:** one API call with `output_config.format` set against `claude-haiku-4-5` and checking for a 400. R6-21 pins the dated id regardless, so this is a cleanliness question, not a blocker.

**O-4. ~~The `max_tokens: 0` cache pre-warm.~~ CLOSED in verification, 2026-08-23.** The mechanic is documented at the primary source: the prompt-caching page's "Pre-warming the cache" section states "Set `max_tokens: 0` in your request. The API reads your prompt into the model and writes the cache at any `cache_control` breakpoint, then returns immediately without generating any output" [anthropic-prompt-caching]. No open question remains. What is still a judgement call, not a fact, is whether a pre-warm schedule beats letting the scheduler's clustering do the work, since each ping costs a write or a read; that is a tuning decision after the first month of `cache_read_input_tokens` telemetry.

**O-5. The real size of the extracted global bundle.** The 12,000-token budget in R6-13 is a design cap, not a measurement. `[UNVERIFIED]` whether the gate stack, the doctrine and the taxonomies compress to that. **Settled by:** performing Wave 1 and Wave 2 of R6-26 and measuring with `client.messages.count_tokens`, never with a character-count estimate. If it does not fit, the correct response is a narrower key set per task, not a larger cap.

**O-6. Whether QA calibration should re-derive from the substrate or replace it.** `backend/docs/CONTENT-DOCTRINE.md` records that the SEO-CONTENT-OS model is "a fail-fast gate stack (auto-fail / warning per gate) plus a fail-count kill gate, not a weighted 0-100 score with a single >=85 threshold", and that migrating means preserving `QaScore.passed` and `.blocked_by` while re-deriving the decision. That migration is R3A's to sequence, not R6's. **Settled by:** R3A and D-4 together. R6 seeds both models (the gate classes and the weight vector) so whichever wins has its config in one place.

**O-7. When, if ever, retrieval gets switched on.** The trigger is not "when we have budget". It is: **the substrate needs retrieval only when the query space stops being enumerable**, which would happen if the platform starts answering free-text operator questions against the knowledge base rather than serving fixed task classes. `POST /policy/ask` is the closest existing thing and it currently uses no tools and no retrieval (`backend/app/services/policy_ask.py`). **Settled by:** a named product decision to support open-ended knowledge queries. Until that decision exists, the answer is no.

---

## 9. Sources

- [anthropic-pricing] https://platform.claude.com/docs/en/about-claude/pricing — accessed 2026-08-23
- [anthropic-prompt-caching] https://platform.claude.com/docs/en/build-with-claude/prompt-caching — accessed 2026-08-23
- [anthropic-structured-outputs] https://platform.claude.com/docs/en/build-with-claude/structured-outputs — accessed 2026-08-23
- [anthropic-web-search] https://platform.claude.com/docs/en/agents-and-tools/tool-use/web-search-tool — accessed 2026-08-23
- [google-spam-policies] https://developers.google.com/search/docs/essentials/spam-policies — accessed 2026-08-23 (page last updated 2026-05-15 UTC)
- [google-ranking-history] https://status.search.google.com/products/rGHU1u87FJnkP6W2GwMi/history — accessed 2026-08-23 (reached via the 301 from https://developers.google.com/search/updates/ranking)
- [google-ai-features] https://developers.google.com/search/docs/appearance/ai-features — accessed 2026-08-23 (page last updated 2025-12-10)

**Repository sources** (verified in-tree at commit `79d1036`, 2026-08-23):

- `db/migrations/0014_entity_context.sql` — `entity_context` + `context_vectors` + `portal_context`; Postgres as source of truth, Pinecone derived
- `db/migrations/0019_policy.sql` — `policy_sources`, `change_events`, `kb_entries`, `recommendations`; the seven policy enums; lead-only manage RLS
- `db/migrations/0025_settings.sql:42` — `workspace_settings.timezone`
- `db/migrations/0027_audit_overlay.sql:4-10, 12-20` — the never-mutate-the-engine rule; the one-table-with-discriminator precedent. Lead-only overlay writes at `:75-80`
- `db/migrations/0050_policy_sources_seed.sql` — the 8 seeded Google watch sources
- `db/migrations/0051_client_business_profile.sql:66-77` — client NAP, categories, hours; staff-read / lead-write RLS; the client-tier back-fill source
- `backend/pyproject.toml:39-58` — the `[ai]` extra at `:44-48`, the `[embeddings]` split at `:49-58`; Voyage and Pinecone out of the deployed image
- `backend/app/config.py:157-158, 759-762, 768, 778` — model defaults and unit prices
- `backend/app/services/pricing.py:28, 64-75` — `_CHARS_PER_TOKEN = 4` (at `:28`, not `:27`, which is `_MTOK`); `anthropic_cost` reads only `input_tokens` / `output_tokens`
- `backend/app/services/content_qa.py:69-70, 76-126` — the dangling `seo-content-os` citation; the 14 dimensions, weights and provisional thresholds
- `backend/app/services/content_generator.py:54-59` — the same dangling citation
- `backend/app/services/policy_watch.py:45-46, 200-203, 245-253` — reply and prompt bounds (`_ANALYSIS_MAX_TOKENS` at `:45`, `_PROMPT_MAX_CHARS` at `:46`); `_clamp` at `:200-203`, applied at `:245-253`
- `backend/app/services/page_blueprints.py:138` — the 7 page templates
- `backend/app/services/policy_baseline.py:24` — `BASELINE_RECOMMENDATIONS`, 16 seeded baseline recommendations (counted)
- `backend/integrations/llm.py:98-99, 116-123` — hard-coded `model_summary` / `model_heavy` defaults; the `cache_control: ephemeral` system block at `:120`. (Note `docs/audit/AI_AUDIT.md` §6 cites `llm.py:96-97` for the same defaults; the current file has them at `:98-99`)
- `backend/docs/CONTEXT-MODULE.md` — the context module's governing principle and freshness invariant
- `backend/docs/CONTENT-DOCTRINE.md:1-14` — the 2026-07-24 authority transfer to a path that does not exist
- `SEO-CONTENT-OS.zip` (1,160,551 bytes, tracked since commit `5f98937`) — `SYSTEM-MAP.md` (generated 2026-07-20 PKT, addendum 2026-07-23 PKT), `CLAUDE.md`, `knowledge/` (77 md, 13,247 lines, 1,429,288 bytes), `scripts/` (22 py, 7,760 lines), `.claude/commands/` (18, 688 lines), `.claude/agents/` (10, 2,019 lines), `.claude/skills/` (2: `geo-optimize`, `corpus-voice-ingest`), `templates/` (5 md + 1 csv, 720 lines), `clients/_template/brand.yaml` (168 lines, 14,297 bytes), `research/` (18 files, 3,821 lines). Every count in this line re-verified by extracting the zip and running `find`/`wc` on 2026-08-23
- `.claude/skills/aios-*/SKILL.md` — 31 operator skills, 3,381 lines
- `docs/audit/AI_AUDIT.md` §0, §1, §2.5, §6 — the AI architecture audit, model inventory, overlay verdict, cost review
- `docs/recovery/REQUIREMENTS_TRACEABILITY.md:338-353` — AI-001 to AI-016
- `docs/recovery/DANIEL_PROJECT_RECOVERY_SPECIFICATION.md` §14.3-14.5, §18.1-18.4, §27.3 — content context requirements, AI component contract, model routing, the acceptance bar
- `docs/recovery/DECISIONS_LOG.md` — D-1, D-3, D-4, D-17
- `docs/implementation/KNOWN_LIMITATIONS.md` §1-§3 — P0-3 job contract, the nine red beat tests, the advisory-QA correction
- `docs/research/R2-web2-safety.md` §1, §3.1 — no embeddings; the non-existent March 2026 SRA update
- `docs/research/R3A-content-intelligence.md:21` (the 99% bar), `:168` (Indexing API), `:280` (R3A-18 hold), `:380` (R3A-37 provenance), `:487-502` (per-page and monthly cost model) — the content pipeline, evidence tables, maintenance queue, per-page cost model

---

## Verification pass — 2026-08-23

Adversarial verification of every repository citation and every external factual claim in this record. The instruction was to refute, not to agree. **Verdict: the record's architecture survives intact — the `overridable` primitive, the no-retrieval decision, the config/retrieval boundary, the Policy Radar sink and the caching design are all sound and correctly sourced — but twenty-two claims were wrong or overstated and are corrected above. Two of the wrong ones (a fabricated Wilson interval and an incomplete Google taxonomy) are exactly the failure class this project exists to eliminate.**

### What was checked

**Repository.** Every `path:LINE` citation in the record was resolved against the working tree at commit `79d1036`. `SEO-CONTENT-OS.zip` was extracted and every file count, line count and byte count in section 3.9 was re-derived with `find` and `wc`. Every SQL object the requirements depend on (`public.users`, `public.clients`, `is_staff()`, `current_app_role()`, `current_client_id()`, `set_updated_at()`, `gen_random_uuid`) was confirmed to exist, and PostgreSQL 16 was confirmed from `docker-compose.yml:137`, so `unique nulls not distinct` (PG15+) is available as R6-3 assumes.

**External.** Six highest-stakes claims were checked by fetching the primary source, not by recall: the Anthropic pricing table and the Sonnet 5 introductory-pricing note (the whole cost model and R6-22's code change rest on it); the prompt-caching minimums, multipliers and isolation rules (the $409-$511 saving rests on them); the structured-outputs GA status and supported-model list (R6-24 and the Haiku pin rest on them); Google's spam policies page (the `overridable` argument in 3.2 rests on it); Google's ranking-update history (the `policy_asof` design rests on it); and Google's AI-features guidance (the llms.txt constraint rests on it).

**Sources fetched 2026-08-23:**

- `https://platform.claude.com/docs/en/about-claude/pricing`
- `https://platform.claude.com/docs/en/build-with-claude/prompt-caching`
- `https://platform.claude.com/docs/en/build-with-claude/structured-outputs`
- `https://developers.google.com/search/docs/essentials/spam-policies`
- `https://status.search.google.com/products/rGHU1u87FJnkP6W2GwMi/history`
- `https://developers.google.com/search/docs/appearance/ai-features`

### What survived unchanged, and must not be re-hedged

- **Every Anthropic unit price in 3.10 is exact**, including all three cache-write and cache-read columns and every Batch API row. The Sonnet 5 note is quoted verbatim and correctly: **$2/$10 is now the standard price and the 1 September 2026 increase to $3/$15 will not occur.** `backend/app/config.py:759-760` is therefore genuinely wrong, and **R6-22 stands: every Sonnet spend the cost gate has committed is 1.5x the true figure.** (Note for implementers: some cached model tables still show Sonnet 5 at $3/$15 with the intro pricing expiring 2026-08-31. The live pricing page supersedes them.)
- **Cache minimums are exactly as stated**: 512 on Opus 5, 1,024 on Sonnet 5, 4,096 on Haiku 4.5, with the "no error is returned" sentence quoted verbatim. Four breakpoints per request, verbatim. The refresh-at-no-cost and lifetime-from-start-of-request sentences, verbatim. The silent-failure argument for the Haiku classification path is correct as written.
- **Structured outputs is GA, no beta header**, the old `structured-outputs-2025-11-13` header is still accepted for transition, and the supported-model list is exactly the twelve ids given — **including that `claude-haiku-4-5-20251001` is listed and the bare `claude-haiku-4-5` alias is not.** The unsupported-keyword list (recursive schemas, external `$ref`, `minimum`/`maximum`/`multipleOf`, `minLength`/`maxLength`), the 24-hour grammar cache, and "changing `output_config.format` invalidates the prompt cache" are all accurate. R6-21's dated Haiku pin is correct and should not be softened.
- **Google spam policies**: last updated 2026-05-15 UTC as stated, and both quoted sentences on scaled content abuse are verbatim. The 3.2 argument is fully supported.
- **Google ranking-update history**: all six 2026 entries and all four 2025 entries match the dashboard exactly, names, start dates and durations.
- **Google AI features**: last updated 2025-12-10 as stated; both quoted sentences verbatim.
- **Web search $10 per 1,000 searches; web fetch no additional charge** — both verbatim, and `config.py:768`'s `0.01` is correct.
- **Every cost-model calculation in section 6 recomputes exactly** ($0.03000 / $0.03750 / $0.00300 per call; $390.00 / $49.35 / $151.13; the $80.61 one-hour comparison; $195.00 / $24.68 on Opus; $1.825 / $3.65 / $2.46 / $6.16 on the policy paths; the $80.14 total against the $589.29 naive figure at 13.6 percent). 2,600 pages/month reconciles to 100 clients x 6 pages x 52 / 12.
- **Every zip inventory count in 3.9 is exact**: 77 markdown files, 13,247 lines, 1,429,288 bytes; all eight per-directory file and line counts; 22 scripts / 7,760 lines; 18 commands / 688 lines; 10 agents / 2,019 lines; 18 research files / 3,821 lines; `brand.yaml` 168 lines / 14,297 bytes; `service-page.md` 55,104 bytes; `keyword-research-method.md` 29,297 bytes; `schema-library.md` 33,838 bytes; 33 rules in `google-compliance-spine.md`; Laws 1-14 and 15-20 in the two doctrine files. The 31 live `aios-*` skills at 3,381 lines and all five `_shared/reference/` line counts are exact.
- **The core repository defect in 2.2 is real**: `backend/seo-content-os/` does not exist, `git ls-files` and `git log --all` on that path both return zero rows, and `CONTENT-DOCTRINE.md:8`, `content_qa.py:70` and `content_generator.py:55,59` all cite it.

### Corrections made

1. **Fabricated Wilson interval (3.12, R6-30).** The record stated centre 0.6349, half-width 0.1334 at x=32, n=50. Recomputed: **centre 0.6300, half-width 0.1286, lower bound 0.5014**. The two wrong figures happened to subtract to a plausible lower bound. **The 32-of-50 threshold itself is correct** (at x=31 the lower bound is 0.4815), so the acceptance test stands; only the stated interval was invented.
2. **Incomplete Google spam taxonomy (3.8, R6-26 Wave 2).** The page carries **seventeen** headings, not sixteen: the sixteen named categories plus "Other practices that can lead to demotion or removal". Seeding sixteen would leave the taxonomy unable to classify a demotion-class finding.
3. **Cache isolation understated (3.7).** Isolation is **per workspace within an organisation**, not per organisation. Added the full verbatim quote and an engineering consequence: splitting the Anthropic key across workspaces multiplies cold writes and can erase the entire saving with no error raised.
4. **`max_tokens: 0` pre-warm was wrongly marked `[UNVERIFIED]` (6.1, O-4).** It is documented at the primary source under "Pre-warming the cache". Over-hedging a verified fact is also a defect; the hedge is removed, the quote added, and O-4 is closed.
5. **Zip size wrong (2.2).** Stated 3.0 MB; actual **1,160,551 bytes (1.1 MB)**. The 1.43 MB figure elsewhere is the uncompressed corpus and is correct; the two are now distinguished.
6. **`blocklist_lint.py` overstated (3.5, R6-26 Wave 3, Decision).** `parse_blocklist` compiles **Tier 1 only** (`:148-153`, every record stamped `"tier": "Tier 1"` at `:203`). Tiers 2 and 3 are in the markdown and are not parsed; per-client phrases enter via `load_extra_banned` at `:250`. Seeding `_tier2` and `_tier3` is new extraction work, not parser re-use.
7. **`content_framework` mapping overstated (3.9, R6-26 Wave 3).** The enum is `('AIDA','PAS','BAB','FAB','4 Ps','PASTOR','4 U''s')` (`db/migrations/0017_content.sql:39-40`). Only 4 of the 10 framework files have a matching label; BAB, FAB and 4 U's have no file; six files have no label. The mapping is partial in both directions and Wave 3 must resolve it explicitly.
8. **"The queue exists and is not fed" was wrong (3.3).** `backend/workers/celery_app.py:195-208` records that Policy Radar is on-demand only and that `/policy/ask` and the lead "generate brief" path write into the same `change_events` / `kb_entries` / `recommendations` tables. Only the *scheduled* generator is disabled. The narrower lesson is retained.
9. **llms.txt framing wrong (3.8).** The record implied the platform is at risk of inventing this check. Both `aios-geo-audit/SKILL.md` (`:45`, `:53`, `:58`) and `llms-txt-verdict.md` already score it info-level and name the over-scoring as an anti-pattern. Reframed as a preservation constraint on the extraction.
10. **"REGULATORY liability" misattributed (3.2).** The phrase is in `SEO-CONTENT-OS/clients/_template/brand.yaml:57`, not in `SYSTEM-MAP.md`.
11. **R6-27's load order misattributed.** The load order is at `SEO-CONTENT-OS/CLAUDE.md:86`, not in `SYSTEM-MAP.md` (which only names `CLAUDE.md` as its home, at `:266`).
12. **R3A cost figures mischaracterised (6.1).** $0.371 and $0.441 are model-mix per-page figures, not "all-in". R3A's own table gives $965/month and **$1,310/month** (at $0.504/page including amortised research), not $1,147; and image generation is excluded and `[UNVERIFIED]` in R3A.
13. **Apparent R3A contradiction resolved (6.1).** R3A publishes "Do not enable caching per page". That verdict is about a per-page 50,000-token prefix read four times; R6's prefix is client-independent and read across all 13,000 monthly calls. Both are correct and an implementer must not read one as forbidding the other.
14. **Prefix budget arithmetic (6.1).** R6-13's cached region is 15,400 tokens (400 + 12,000 + 3,000), not 15,000. Every figure in 6.1 understates by ~2.7 percent. Direction is conservative; flagged rather than re-tabulated.
15. **"Evidenced" downgraded to "modelled" in the Decision.** The unit prices are evidenced; the 15,000-token prefix and the clustering assumption are not.
16. **Misquoted requirement (R6-21).** The record quoted "Policy categorisation explicitly uses Claude Haiku", which appears in neither source. `AI-003` reads "Policy categorisation uses Claude Haiku" (`REQUIREMENTS_TRACEABILITY.md:340`, P2); `AI-R3` reads "Policy categorisation explicitly uses Haiku" (`DANIEL_PROJECT_RECOVERY_SPECIFICATION.md:1324`).
17. **Structured-outputs constraint handling incomplete (3.11).** The SDKs strip unsupported constraints, fold them into the field description and validate client-side. Raw `create()` and `parse()` fail differently; the module must pick one.
18. **Ten off-by-a-few line citations corrected.** `0027_audit_overlay.sql:20-22` → `:12-20`; `0014_entity_context.sql:79-101` → `:82-91` + `:92-109`, and `:88-101` → `:92-109`; `0051_client_business_profile.sql:64-75` → `:66-77`; `gates.md:24` → `:23`; `pricing.py:27` → `:28` (three sites); `pricing.py:64-77` → `:64-75` (two sites); `pyproject.toml:51-60` → `:49-58` and `39-60` → `39-58`; `policy_watch.py:203-206` → `:200-203` plus `:245-253`; `0025_settings.sql:44` → `:42` (two sites).
19. **Three R3A cross-references corrected.** Indexing API `:153` → `:168`; R3A-18 `:260` → `:280`; R3A-37 `:355` → `:380`.
20. **Templates line count (3.9).** 717 was markdown only; the total including the CSV is **720**.
21. **`_GEN_MAX_TOKENS` given a citation (6.2).** `backend/app/services/policy_generate.py:61`, with `_MAX_ITEMS = 12` at `:62`.
22. **Sources section tightened.** Zip line now carries the byte count and the extraction date; `llm.py` line notes that `AI_AUDIT.md` §6's own `:96-97` citation has drifted from the current `:98-99`; `policy_baseline.py` now cites `:24` and states the 16 was counted.

### What remains `[UNVERIFIED]`, and why

- **O-2, the provenance and licence of the seed corpus.** Unchanged and still the hardest blocker. Nothing in the zip establishes authorship. `SYSTEM-MAP.md:3` says it was "Generated 2026-07-20 PKT by direct read of every file in the workspace" and reads as first-party work, and the 2026-07-23 addendum reads the same way, but a self-describing document is not a licence. **No amount of further reading settles this; only the owner's written confirmation does, and it must precede Wave 2.**
- **O-5, the real extracted size of the global bundle.** Still a design cap, not a measurement, and the record is honest about that. Verification did not shrink 1.43 MB of prose into 12,000 tokens of typed config, and no arithmetic can predict whether that compression is achievable. Settled only by performing Waves 1 and 2 and measuring with `client.messages.count_tokens`.
- **O-3, whether the bare `claude-haiku-4-5` alias accepts `output_config.format`.** The documented list still names only the dated snapshot, which is now confirmed at the primary source. Whether the alias also works is unstated in the docs and is settled only by one API call. R6-21 pins the dated id regardless, so nothing depends on it.
- **The clustering assumption behind scenario A** (~300 cold writes per month). It is a stated assumption about how R3A's paced scheduler distributes work, not a measurement. The break-even arithmetic is verified and holds from the second call onward regardless, so the *direction* is safe; the magnitude is not yet evidenced. Settled by one month of `cache_read_input_tokens` telemetry.
- **The per-page five-sub-call model** carried over from R3A. Verified as R3A's stated figure (`:487`), not as an observed property of code that does not yet exist.

### Two judgements flagged rather than corrected

- **The three-tables rejection (section 4) is thinner than the others.** It rests on readability, testability at width, migration count and house convention. Those are good engineering reasons but the first two are preference, not disqualifying facts; the migration-count argument and the `0027` precedent are the load-bearing halves. The decision is still right; the justification should not be presented as though a fact forced it.
- **The teardown-injection rejection is a safety judgement, not a fact.** "A competitor teardown in a generation prompt is a template for reproducing a competitor's page" is a plausible and prudent inference; no source establishes it. It is the correct call and it should be labelled a judgement in any document that carries it forward.
