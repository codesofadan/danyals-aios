# M01 · Portal & Platform Core

**Everything else mounts on this.** Build it first and build it completely — a weak core
means every module reimplements identity, lists, jobs and cost.

Requirements: `REQ-CORE-001` … `REQ-CORE-020`, plus the cross-cutting `REQ-X-*`.

---

## 1. Responsibilities

Identity and access · the client record and its NAP · team and task queue · the review
checkpoint · milestones · notifications · activity log · the key vault · cost control ·
settings · the client portal · the Command Center · the capability truth table.

It also owns the four platform primitives that every other module consumes: the **job
engine**, the **vault**, the **cost gate** and **provenance**. Those are specified in
[`03-ARCHITECTURE.md`](../03-ARCHITECTURE.md) and built as part of this module.

---

## 2. Roles and capabilities

Nine roles. Capabilities are the enforcement unit; roles are a convenience mapping.

| Role | Scope |
|---|---|
| **Owner** | Everything, including provisioning, keys, dials, the global halt and the feed reset |
| **Super-Admin** | Everything except owner-only destructive operations and key material |
| **Admin** | Full client book, team, approvals, cost visibility; no provisioning |
| **Manager** | Assigned clients: assign work, review, approve, publish, start campaigns |
| **SEO** | Audits, keywords, tracking, findings → tasks |
| **Content** | Drafting, editing, QA review; cannot publish live without a manager approval |
| **Off-page** | Citations and Web 2.0 execution; the citation operator role |
| **Support** | Read-most, ticket threads, client communication |
| **Client** | Their own client record only, read-only, plus requests |

**Capability naming:** `<module>:<action>` — `content:publish`, `citations:submit`,
`vault:read`, `cost:set_dial`, `client:offboard`, `team:assign`.

Rules:
- Every endpoint declares its capability. There is no implicit authorisation.
- Role → capability mapping lives in one seeded table and is editable by the Owner.
- `Manager` and below are **client-scoped**: their capability grants are qualified by an
  assignment list. A manager assigned to clients A and B cannot see C.

---

## 3. Data

Covered in [`04-DATA-MODEL.md`](../04-DATA-MODEL.md) §3. Module-specific additions:

```
tasks(id, client_id, kind, title, spec jsonb, assignee_id, priority, state,
      due_at, blocked_reason, sla_breached_at, source_module, source_ref)
reviews(id, client_id, module, subject_type, subject_id, requested_by,
        state, decided_by, decided_at, decision_note, payload jsonb)
milestones(id, client_id, stage, state, entered_at, evidence_ref)
notifications(id, user_id, kind, title, body, link, read_at, digest_key)
settings(scope, key, value jsonb, updated_by, updated_at)   -- scope: agency | client | user
feature_flags(key, scope, scope_id, enabled, updated_by)
capability_probes(capability, state, checked_at, detail jsonb)
```

**`reviews` is generic on purpose.** Content approval, campaign approval, design-profile
approval, `by_hand` cost approval and citation first-run confirmation all enqueue into it.
One queue, one UI, one audit trail.

---

## 4. Key flows

### Onboard a client (J1)
```
create client
  └── capture profile: categories, services, hours, payment methods, descriptions
  └── capture canonical NAP (+ locations if multi-location)
  └── connect WordPress          → capability probe stored
  └── paste PREVIOUS website URL → M03 design extraction job
  └── run keyword research       → M08
  └── generate topical map       → M08
  └── milestone: onboarding complete
```
Target: under 15 minutes of human time. Everything after the two URLs is a job.

### Task lifecycle
`created → assigned → in_progress → (blocked ⇄ in_progress) → done`, with `blocked`
requiring a reason and raising a notification to the assigner. SLA timers run against
`due_at` and surface in the Command Center, not in an email nobody reads.

### Review checkpoint
A module calls `reviews.request(module, subject, payload, capability)`. The item appears in
one queue filtered by the reviewer's capabilities. A decision emits a domain event the
originating module consumes. **The module never polls.**

### Bulk client import
`POST /clients/import:dry-run` returns a per-row diff and validation report; the operator
reviews; `:commit` applies inside one transaction with an import id that can be reversed.
100 clients by hand is not viable — this is a P1 that becomes P0 the moment the client book
grows.

---

## 5. Capability truth table (`REQ-CORE-020`)

The single most important trust feature in the product.

A background job probes each capability on a schedule and on demand, and records the real
result:

| Capability | Probe |
|---|---|
| `audit.technical` | Provider keys present **and** a canary crawl of a known URL returns expected structure |
| `content.publish.elementor` | A WordPress fixture site accepts a block-tree write and returns an editable page |
| `citations.account_create` | The mailbox is reachable over IMAP and the CAPTCHA balance is above the floor |
| `web2.<platform>` | The stored token refreshes and a metadata read succeeds |
| `tracking.organic` | DataForSEO responds to a cheap probe |
| `tracking.grid` | serper.dev responds and the monthly quota is not exhausted |
| `indexing.google` | Indexing API credentials valid and quota remaining |
| `ai.reasoning` | A minimal model call succeeds on the configured backend |

States: `operational` · `degraded` (with the reason) · `unconfigured` · `unknown`.

This page is what the owner looks at before telling a client something works. It is derived
from probes, never from a hand-maintained list.

---

## 6. Command Center

One operator home answering four questions:

1. **What is blocked?** Jobs in `blocked`, reviews waiting, tasks blocked, tokens expiring.
2. **What is failing?** Dead letters, provider error rates, degraded capabilities.
3. **What is it costing?** Spend against caps by client and module, with the trailing rate.
4. **What is the system doing right now?** Queue depth, running jobs, recent publishes.

No vanity metrics. Every tile links to the list that produced it.

---

## 7. Client portal

Read-only. Shows: engagement status and milestone stage · deliverables (audits, published
pages, citations, campaign summaries) with dates · the monthly report archive · a request
thread. **Never shows** internals, job states, costs, or a capability that is not running
for them (`REQ-W2` — a client not on a Web 2.0 campaign must see no Web 2.0 surface).

The client does not approve anything. If they raise a request, it becomes a task.

---

## 8. Notifications

- Channels: in-app and email. WhatsApp and Slack are v2.1.
- **Digest batching is mandatory.** A 50-page fan-out completing must produce one
  notification, not fifty. Batching is keyed on `digest_key` with a short window.
- Per-user preference per kind.
- Transactional email (invites, verification, reports) is separated from digest email so a
  digest failure never blocks an invite.

---

## 9. API

See [`05-API-CONTRACT.md`](../05-API-CONTRACT.md) §4 Platform for the endpoint list.

---

## 10. Acceptance criteria

| # | Criterion |
|---|---|
| A1 | A new client is created, profiled, NAP-captured, WordPress-connected and design-extraction-queued in under 15 minutes of human time |
| A2 | Every endpoint rejects a principal lacking its capability, proven by a generated test over the full route table |
| A3 | A manager assigned to clients A and B receives zero rows for client C on **every** list endpoint |
| A4 | MFA is enforced for Owner and Admin and cannot be bypassed by a refresh-token path |
| A5 | A vault secret cannot be retrieved through any API response, log line or Sentry event — proven by a scanning test over a full exercise run |
| A6 | A 50-child fan-out produces exactly one digest notification |
| A7 | The capability truth table reflects reality: removing a provider key flips its capability to `unconfigured` within one probe cycle |
| A8 | Bulk import of 100 clients completes with a reviewable dry-run diff and is reversible |
| A9 | Every list endpoint is server-paginated and returns in under 200 ms p95 at 100 clients' data volume |
| A10 | The activity log contains an entry for every state-changing action taken during a full end-to-end exercise, with before/after |
