# 13 · Glossary

Read before writing any identifier. A term used two ways is a bug waiting to be written.

---

## Domain

**Agency** — the single tenant operating the platform (Danyal's business). There is one.
Not modelled as a tenant; it is the environment.

**Client** — a business the agency serves. **The tenant boundary.** Every row with
`client_id` belongs to exactly one. 50–100 of them.

**Location** — a physical place belonging to a client. NAP, GBP, citations and grids are
location-scoped. A single-location client has one.

**NAP** — Name, Address, Phone. The canonical record a client is identified by across the
web. Consistency across GBP, the site and every citation is a measured score.

**Citation** — a listing of a business's NAP on a third-party directory. Not a backlink,
though it often carries one.

**Directory** — a site that accepts business listings. 160+ in the registry, each with a
terms position governing what we may do there.

**Web 2.0 property** — a page or blog we own on a third-party platform, used to carry a link
and topical relevance to a client's site.

**Parasite Poster / parasite SEO** — publishing keyword-targeted content onto a
high-authority third-party domain so the *host's* authority carries the page into the SERP
for a term the client's own site cannot yet reach.

**Anchor** — the clickable text of an outbound link. Distribution across branded / naked /
partial-match / exact-match is capped and enforced at plan time.

**Campaign** — a scoped Web 2.0 engagement for one client: platforms, targets, anchors,
schedule, budget. Web 2.0 runs per campaign, not as standing delivery for every client.

**Topical map** — clusters mapped to page types; the proposal a human approves before a page
set is drafted.

**Cluster** — a group of semantically related keywords with a pillar term and an entity set.
The unit that maps to a page.

**Word bank / keyword bank** — the SEO keyword bank with volumes, per client. **The single
upstream of content targeting.** A term absent from it cannot be targeted or tracked.

**Entity set / must-mention set** — the terms a page on a topic must mention to read as
authoritative. Measured as the topical-coverage dimension of the QA scorecard.

**Page set** — a group of pages proposed together from the topical map and approved as a
unit before drafting.

**GEO (audit type)** — generative-engine optimisation: readiness for AI Overviews and LLM
citation. Not geography. When geography is meant, the word is "local" or "geo-grid".

**Geo-grid** — a lattice of coordinates around a location, each queried independently to
produce a local-visibility heat map.

---

## Platform primitives

**DesignIR** — the captured design system of a client's previous website: colour roles,
typography scale, spacing scale, layout, shape language, component specs, section grammar.
The contract between design analysis and page generation.

**Token conformance** — the invariant that a generated page uses only values present in its
approved DesignIR. The fidelity test. Not a pixel diff.

**Section grammar** — the ordered vocabulary of section kinds observed on the source site
(hero, trust bar, services grid, testimonials, CTA band). New pages compose from it.

**Block tree** — the Elementor element tree (`container` → `container` → widget) written to
`_elementor_data`. A single HTML widget is **not** a block tree.

**Global kit** — Elementor's global colour and typography tokens. Our widgets reference them
rather than hard-coding values, so a client restyle propagates.

**Job** — a durable unit of long-running or spending work with an idempotency key, persisted
state, a lease, bounded retry and an honest terminal state.

**Idempotency key** — the value that makes re-running a job safe. Unique per (kind, natural
key). Propagates from HTTP header → job → side-effect ledger.

**Side effect** — an external, irreversible act (a publish, a submission, a paid call).
Recorded in a ledger before attempt and checked before retry.

**Lease** — a worker's time-bounded claim on a job. Expiry releases it for re-pickup.

**Dead letter** — a job that exhausted retries, retained with its full failure context and
requeueable.

**Outbox** — the table where domain events commit in the same transaction as the state change
that produced them.

**Cost gate** — the check before every paid call: global halt, module dial, client cap.
Blocks before the provider is contacted.

**Money dial** — a module's spend switch: `off` · `by_hand` (queue for approval) · `on`.

**Marginal cost** — provider spend per unit. **Loaded cost** — marginal plus human minutes at
a configured rate. Both are always reported together.

**Provenance** — how a value was obtained: `measured` · `derived` · `declared` · `inferred` ·
`defaulted`, with source and timestamp. A value without it cannot be displayed.

**Capability truth table** — the live, probe-derived statement of which capabilities are
`operational` · `degraded` · `unconfigured` · `unknown`.

**Structural fingerprint** — a hash of a form's shape (field order, types, label shapes) used
to cache citation field mappings. Deliberately not the URL and not CSS selectors.

**Operator token** — a short-lived credential scoped to one user, one client and one
extension session, carrying only citation capabilities.

---

## States, and what they mean

### Job terminal states
| State | Meaning |
|---|---|
| `succeeded` | The work completed **and the effect was confirmed** |
| `partial` | Some children succeeded, some did not |
| `failed` | Retryable attempts exhausted |
| `blocked` | A precondition is missing — no credentials, capability absent, cost gate refused. **Not a failure of the code** |
| `timed_out` | Exceeded its limit |
| `dead` | Dead-lettered with context |

**`succeeded` requires confirmation, not attempt.** A publish that returned 200 but whose
page does not resolve is not `succeeded`.

### Measurement states
| State | Meaning |
|---|---|
| `ranked` | Measured, found at position N |
| `absent` | **Measured**, not present |
| `error` | **Never measured** |
| `unknown` | Measured but indeterminate |

`absent` and `error` are different facts and never collapse.

### Provider result
| Status | Meaning |
|---|---|
| `ok` | Real data, measured |
| `degraded` | No data, with a machine-branchable `reason` enum. **Never a substituted value** |

---

## Naming conventions

- Tables plural, snake_case: `content_pages`, `citation_submissions`
- The tenant column is always `client_id`, never `tenant_id` or `customer_id`
- Capabilities are `<module>:<action>`: `content:publish`, `citations:submit`
- Job kinds are `<module>.<noun>.<verb>`: `content.page_set.run`, `citations.account.create`
- Events are `<module>.<noun>.<past-tense>`: `content.page.published`
- Money is `*_cents`, integer, never float
- Timestamps are `*_at`, `timestamptz`, UTC
- Requirement ids are `REQ-<MODULE>-<NNN>`; decisions are `ADR-<NNN>`

---

## Words we do not use

| Avoid | Because | Use |
|---|---|---|
| "tenant" | Ambiguous — the agency is not one | **client** |
| "user" for a client business | Conflates a login with a business | **client** (business) / **user** (login) |
| "sync" | Hides direction and failure | **pull from X** / **push to X** |
| "process" | Says nothing | the actual verb |
| "temporarily" in a comment | It never is | state the condition for removal |
| "should work" | Either verified or not | say which |
| "done" for unconfirmed work | The v1 defect | the honest terminal state |
