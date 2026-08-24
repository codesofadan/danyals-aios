# SEO System Spine - Canonical Data Contracts

v1.0 - 2026-07-17 PKT. Companion to `seo-system-doctrine.md` (implements Law 14). Portable: copy alongside the doctrine into any workspace that must interoperate with our other SEO systems.

Purpose: the doctrine says how to think; this says the exact shapes every system reads and writes so that multiple systems - including the more advanced ones on other machines - share one crawl cache, one judgment corpus, and one measured-outcome history instead of drifting into divergent copies. A system MAY add fields to a contract. It MUST NOT rename or repurpose the required fields, and MUST NOT invent a second contract for the same concept. When in doubt, extend; never fork.

Conventions: all timestamps ISO-8601 with timezone. All ids are stable and content-addressable where noted. All money in USD. All contracts serialize to JSON (storage may be SQLite/parquet/files - the wire shape is JSON). Field marked `req` is required; `opt` optional.

---

## 1. CrawlRecord - one fetched URL in the persistent store

The store is per-client, keyed by `url_hash`, incremental. Decoupling collection from analysis (doctrine Law 3) means everything downstream reads this, never the live site.

```
CrawlRecord {
  url_hash        req  str   # sha256 of normalized absolute URL - the primary key
  url             req  str   # normalized absolute URL
  client_id       req  str   # owning client (see ClientCaseFile.client_id)
  fetched_at      req  str   # ISO-8601
  status          req  int   # HTTP status
  etag            opt  str   # for If-None-Match incremental refetch
  last_modified   opt  str   # for If-Modified-Since
  content_hash    req  str   # sha256 of raw body - detects change without diffing
  raw_html_ref    req  str   # pointer to stored body (path/blob key), not inlined
  rendered        opt  bool  # true if this row is the JS-rendered DOM, not raw HTML
  extracted {                # single-pass extraction, doctrine Law 3
    title          opt str
    meta_desc      opt str
    canonical      opt str
    h1             opt [str]
    headings       opt [{level:int, text:str}]
    word_count     opt int
    lang           opt str
    hreflang       opt [{lang:str, url:str}]
    schema_types   opt [str]   # JSON-LD @type values found
    links_out      opt [str]   # url_hash list - builds the link graph
    links_in       opt [str]   # url_hash list - populated by graph pass, enables orphan detection
    indexable      opt bool    # robots/meta/canonical resolved
  }
  source          req  str   # "own-crawler" | "screaming-frog" | "dataforseo" | ...
}
```

Interop rule: any crawler writes this shape. Orphan detection, structure analysis, and the twin (frontier bet 2) all read `links_in`/`links_out`; do not compute the link graph anywhere else.

---

## 2. Finding - one detected issue or opportunity

The output of analysis, the input to decisions. Doctrine Law 1's audit layer emits these; the decision layer (Law 4) consumes them. This is the contract that makes an audit machine-actionable rather than a PDF.

```
Finding {
  finding_id      req  str   # stable: sha256(client_id + issue_class + primary_target)
  client_id       req  str
  issue_class     req  str   # controlled vocab: "orphan-page" | "thin-content" | "duplicate" |
                             #   "broken-link" | "missing-meta" | "redirect-chain" |
                             #   "cannibalization" | "schema-gap" | "cwv-fail" |
                             #   "entity-inconsistency" | "answer-gap" | "internal-link-gap" | ...
  primary_target  req  str   # url_hash, or entity id, or query - the thing the finding is about
  affected        req  [str] # url_hash / entity / query list
  evidence        req  obj   # the data that proves it: metric values, snapshots, competitor delta
  severity        req  str   # "critical" | "major" | "minor" | "info"
  confidence      req  float # 0..1 - how sure the detector is
  detected_at     req  str
  detector        req  str   # which agent/rule/tool produced it
  outcome_ref     opt  str   # links to a query outcome that motivated it (answer-gap findings)
}
```

Interop rule (doctrine Law 14 test): a Finding from system A must be consumable by system B with no translation. `issue_class` is a shared controlled vocabulary - adding a class is a doctrine-level change proposed to the founder, not a local invention.

---

## 3. ActionPlan - one proposed change, with its risk tier and rationale

The decision layer turns a Finding into this. Every field exists so a human can approve or reject in ten seconds (doctrine Law 4) and so the safety harness (Law 5) can gate it.

```
ActionPlan {
  action_id       req  str
  finding_id      req  str   # what this fixes
  client_id       req  str
  action          req  str   # "set-meta" | "add-internal-links" | "add-schema" | "fix-canonical" |
                             #   "rewrite" | "merge" | "redirect" | "noindex" | "delete" |
                             #   "restructure" | "escalate"
  target          req  str   # url_hash / entity / route
  change          req  obj   # the concrete diff: before -> after, or the payload to write
  risk_tier       req  str   # "A" (auto after dry-run) | "B" (batch approval) | "C" (explicit sign-off)
  rationale       req  str   # why this action, from the rule catalog, citing evidence
  rule_ref        req  str   # which rule in the catalog fired (RuleCatalogEntry.rule_id)
  write_surface   req  str   # "wp-rest" | "wp-cli" | "git-pr" | "redirect-plugin" | ... (Law 2)
  reversible_by   req  str   # exact rollback action - required, no plan ships without it
  red_team        opt  obj   # frontier bet 4: {attacked_by, verdict, notes}
  created_at      req  str
  status          req  str   # "proposed" | "approved" | "applied" | "rolled-back" | "rejected"
}
```

Hard invariants (from doctrine Law 5, enforced in code not by the model): `action` in {delete, merge, redirect, restructure} forces `risk_tier` >= "B"; any URL change or deletion forces "C"; a target whose CrawlRecord shows authoritative inbound links can never carry `action: delete` at tier A/B. `risk_tier` is never set by an LLM.

---

## 4. ChangeOutcome - what actually happened after a change shipped

Closes the loop (doctrine Law 6) and feeds the causal ledger (frontier bet 3). Without this contract, "measurement" is a claim; with it, it is data.

```
ChangeOutcome {
  outcome_id      req  str
  action_id       req  str   # the change this measures
  client_id       req  str
  vertical        req  str   # for cross-client causal aggregation (bet 7)
  site_size_bucket req str   # "<100" | "100-1k" | "1k-10k" | "10k+"
  applied_at      req  str
  baseline        req  obj   # metrics before: {clicks, impressions, position, citation_share, cwv...}
  window_days     req  int   # measurement window (default 28)
  result          req  obj   # metrics after, same keys as baseline
  verdict         req  str   # "positive" | "inconclusive" | "negative" (statistical, not vibes)
  significance    opt  float # p-value or effect size where computed
  action_taken    opt  str   # "kept" | "rolled-back" | "iterated"
}
```

Interop rule: `vertical` + `site_size_bucket` + `issue_class` (via action -> finding) is the aggregation key for the causal ledger. Anonymized rollups of these are the house meta-brain (bet 7); the raw rows are client-private and never leave their instance (founder rule on team/client separation).

---

## 5. RuleCatalogEntry - one unit of codified judgment

Doctrine Law 4: judgment is versioned code. Rules live as git-diffable files; this is their record shape. LLM judgment is invoked only at `leaf_check`, never to decide the tier.

```
RuleCatalogEntry {
  rule_id         req  str   # stable, e.g. "orphan.high-backlink.reclaim-links"
  issue_class     req  str   # matches Finding.issue_class
  when            req  str   # deterministic condition over Finding.evidence features (expression)
  action          req  str   # the ActionPlan.action it proposes
  default_tier    req  str   # A | B | C
  leaf_check      opt  str   # optional semantic question routed to an LLM ("same intent?")
  rationale_tmpl  req  str   # template that becomes ActionPlan.rationale, must cite evidence
  confidence      req  float # 0..1 - starts as a prior, updated by ChangeOutcome (bet 3)
  vertical_scope  opt  [str] # empty = universal; else applies only to these verticals
  version         req  str
  outcomes_seen   opt  int   # how many ChangeOutcomes have trained this rule's confidence
}
```

Interop rule: catalogs are per-system extensible but the `issue_class` vocabulary and the `default_tier` semantics are shared. A per-client overlay (doctrine Law 4: "your judgment, encoded, owned by you") is a layer on top of the shared base catalog, referenced by client_id, never a fork of it.

---

## 6. ClientCaseFile - the compounding per-client record

Doctrine Law 10: the brain is files that compound. This is the append-only spine of one client's history. Every run reads it in and appends to it.

```
ClientCaseFile {
  client_id       req  str
  domain          req  str
  vertical        req  str
  hosting         req  obj   # who controls the site, which write surfaces we hold (Law 2)
  entities        opt  [obj] # the entity/knowledge-graph state we are engineering (bet 5)
  money_queries   req  [str] # the queries/answers that define success (bets 1, Law 13)
  quirks          opt  [str] # client-specific constraints learned over time
  run_log         req  [obj] # append-only: {run_at, what_found, what_shipped, outcomes_ref}
  answer_presence opt  [obj] # Law 13 tracking: {query, engine, cited?, sampled_at}
}
```

Interop rule: this file is the anchor. `client_id` here is the foreign key every other contract points to. Growth of `run_log` between two runs is the Law 10 compounding test.

---

## For developers - how you actually use this

You do not read these schemas and re-type them. You import them. The executable form is `seo_spine.py` (Pydantic v2, sitting next to this file) - vendor it into the system or import from a shared package.

Daily workflow:
1. **Data crosses module boundaries only as these contracts.** Your crawler returns `CrawlRecord`s; your analyzer emits `Finding`s; your decision layer emits `ActionPlan`s; your measurement job writes `ChangeOutcome`s. Never pass a private dict for a concept that has a contract.
2. **Construct through the models, not around them.** `ActionPlan(...)` refuses to build a delete/redirect/restructure below tier C, refuses any plan with no `reversible_by`, and (via `enforce_backlink_rule`) refuses to auto-delete a page with authoritative backlinks. That is doctrine Law 5 enforced at construction time - a malformed plan raises before it can ship, not in review.
3. **Definition of Done for any capability:** its inputs and outputs are spine contracts, and it constructs them through `seo_spine.py` so the invariants run. A feature that hand-rolls its own dict for a Finding or an ActionPlan is not done - it has forked a contract (Law 14 VIOLATED).
4. **Extending is fine; forking is not.** Add fields to a model in your system freely. Do not rename a required field, and do not add a value to `IssueClass` / `ActionType` locally - those vocabularies are shared, so a new value is a founder-level doctrine change (otherwise system A emits a class system B has never heard of, and the handshake breaks).
5. **The case file is the anchor.** Every run reads the `ClientCaseFile` in and appends to `run_log`. Growth of that log between runs is the Law 10 compounding test, checkable in a diff.

If you are wiring a system for the first time, the entry point is not this file - it is the doctrine's Part IV audit, which tells you which contracts the system is already missing (usually `ChangeOutcome` and `RuleCatalogEntry`, because most systems have no measurement and no codified judgment). Those gaps are the build targets.

## Applying the spine

When a doctrine audit (doctrine Part IV) reaches Law 14 on a system that must interoperate:
1. For each of the six contracts, find where the system already represents that concept and check the required fields exist under these names (or a documented mapping does).
2. Where a concept exists in a private shape, write an adapter to this contract - do not rewrite the system, wrap it.
3. Where a concept is missing entirely (commonly ChangeOutcome and RuleCatalogEntry - most systems have no measurement or no codified judgment), that is a Law-6 or Law-4 gap the doctrine already flagged; the missing contract is the build target.
4. Register the system as a producer/consumer of each contract in the workspace build log, so the shared-brain topology is explicit.

These schemas are minimal on purpose - enough to interoperate, not so rigid they block a more advanced system. Add fields freely; keep the required core identical everywhere. The spine is the handshake, not the whole hand.
