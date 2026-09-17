# M12 · Billing, Tiers & Cost Control

Requirements: `REQ-BIL-001` … `REQ-BIL-008`.

**Payment collection is out of scope** (`REQ-BIL-008`). Tiers are records that gate
entitlements; money changes hands outside the platform. What this module really owns is the
thing that decides whether the business is viable: **knowing what each client costs.**

---

## 1. Tiers and entitlements

`REQ-BIL-001`. A tier is a named set of entitlements:

```
tiers(id, name, rank, entitlements jsonb)

entitlements:
  keywords_tracked_max      grid_points_max        grid_cadence
  pages_per_month           audits_per_month       audit_types_allowed[]
  citations_per_month       web2_campaign_eligible  platforms_max
  gbp_posts_per_month       report_cadence          support_sla
  ai_spend_cap_cents        storage_mb
```

**Entitlements are enforced at the API, never only in the UI.** An over-limit request returns
`403` with the entitlement that blocked it and the tier that would allow it — which is also
where the upsell surface comes from (`REQ-BIL-007`, P2).

---

## 2. Money dials

`REQ-BIL-002`. Per module, three states:

| State | Behaviour |
|---|---|
| `off` | No paid call in this module happens. Callers degrade honestly |
| `by_hand` | The call is **queued for human approval** with its estimate, not refused. The operator sees the cost and approves or declines |
| `on` | The call proceeds, subject to caps |

The dial state is visible **at the point of spend** in the UI, not buried in settings. An
operator pressing a button that will cost $18 should see $18 on the button.

---

## 3. Caps and the halt

| Control | Scope | Behaviour |
|---|---|---|
| **Client monthly cap** (`REQ-BIL-003`) | Per client | Hard stop at the cap; operator alert at 80% |
| **Global halt** (`REQ-BIL-004`) | Everything | Owner-operated. **No code path may bypass it** — asserted by a test over every paid call site |
| **Per-job ceiling** | One job | A fan-out that would exceed its own estimate by a configured factor stops and reports `partial` |

---

## 4. Cost accounting

`REQ-BIL-005`. Every paid operation: **estimate before, actual after, variance recorded.**

```
cost_ledger(at, module, client_id, job_id, provider, unit, quantity,
            estimate_cents, actual_cents, kind)     -- kind: marginal | loaded
```

- The estimate gates. The actual is committed from real usage (token counts, unit counts,
  solve counts) — never from the estimate.
- A module whose actual consistently exceeds its estimate by >25% has a broken estimator and
  raises a task. An estimator nobody checks is a budget nobody has.

### Loaded cost
`REQ-BIL-006`. Marginal cost plus **human minutes at a configured rate**. This is the figure
that matters for citations (a human presses every submit) and for Web 2.0 (staff perform
every OAuth). Both figures are reported, always together.

The commercial history here matters: a document delivered to the client headlines "Under
10¢" per citation as a *marginal* figure. With a human in the loop the loaded figure is
higher, and it must be disclosed proactively rather than discovered. Reporting all three
numbers — marginal, loaded, and the ceiling — is a credibility gain; being found out is a
dispute.

---

## 5. Cost reporting

| View | Answers |
|---|---|
| **Per client, per month** | What does this client cost us, marginal and loaded, against their tier price |
| **Per module** | Where is the money going |
| **Per unit** | Cost per citation, per page, per audit, per post — the numbers that set pricing |
| **Variance** | Where are the estimators wrong |
| **Trailing rate** | Are we about to hit a cap |

This is the module that tells the owner whether a tier is priced above its cost. Without it,
tier pricing is a guess — which is how v1 arrived at a per-citation commitment it could not
verify.

---

## 6. Acceptance criteria

| # | Criterion |
|---|---|
| A1 | An over-entitlement request is refused at the API with the blocking entitlement named |
| A2 | A `by_hand` dial queues the call for approval with its estimate, rather than failing it |
| A3 | Setting a dial `off` prevents every paid call in that module — asserted over every call site |
| A4 | The global halt cannot be bypassed by any path, including scheduled jobs and retries |
| A5 | Every paid operation records estimate and actual; actual is derived from real usage |
| A6 | Loaded cost per citation and per campaign is reported alongside marginal |
| A7 | A client hitting 80% of cap alerts; hitting 100% stops spend and surfaces clearly |
| A8 | Per-unit cost reports reconcile with the provider's own billing within a documented tolerance |
