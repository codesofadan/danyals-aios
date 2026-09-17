# 11 · Acceptance Criteria & Traceability

Nothing is "done" because it was built. It is done when the criterion below is demonstrated
**on real data, in the running system**, with evidence attached to the requirement.

---

## 1. The eight release gates

v2.0 ships when all eight hold. These are restated from
[`00-EXECUTIVE-SCOPE.md`](00-EXECUTIVE-SCOPE.md) §6 with their evidence form.

| # | Gate | Evidence |
|---|---|---|
| **S1** | **50-page content run** — generated, QA'd, reviewed and published to a real WordPress site as editable Elementor block trees in the client's design system, **zero manual repair** | Recorded run: job id, 50 page URLs, token-conformance report, a screen recording of one page being edited in Elementor |
| **S2** | **100 citations** — live, NAP-verified, with proof artefacts, loaded cost inside the ceiling | Citation ledger export with proof keys and the cost report |
| **S3** | **One Web 2.0 campaign** across ≥15 platforms, per-client identities, images, internal links, correct SEO fields, official APIs only, no ban | Campaign report with live URLs and the placed-links table |
| **S4** | **Audit parity** — each of the six paid types completes inside its cost ceiling with zero degraded sections on a fully-keyed environment | Six audit ids with coverage blocks |
| **S5** | **Isolation proof** — adversarial cross-tenant reads fail on every table | `rls_gate` CI output over the full table list |
| **S6** | **Truth proof** — with every provider key removed, no unlabelled number appears anywhere | `keyless_smoke` CI output plus a UI walkthrough capture |
| **S7** | **Recovery proof** — each of the eight long-running job kinds resumes or dead-letters correctly under a mid-run kill, with no double-spend | Chaos suite report |
| **S8** | **Restore proof** — full restore into a clean host, verified by a data-integrity check | Drill log with elapsed time against RPO/RTO |

---

## 2. Requirement → module → criterion

Abbreviated map. The authoritative per-criterion detail lives in each module spec's
acceptance table.

| Requirement range | Module | Acceptance table |
|---|---|---|
| `REQ-CORE-001…020` | M01 Portal & Platform Core | [M01 §10](modules/M01-portal-and-platform-core.md) |
| `REQ-AUD-001…010` | M02 Audit | [M02 §8](modules/M02-audit.md) |
| `REQ-CNT-001…031` | M03 Content System | [M03 §E](modules/M03-content-system.md) |
| `REQ-CIT-001…021` | M04 Citations | [M04 §11](modules/M04-citations.md) |
| `REQ-W2-001…017` | M05 Web 2.0 & Social | [M05 §8](modules/M05-web2-and-social.md) |
| `REQ-POL-001…007` | M06 Policy Radar | [M06 §7](modules/M06-policy-radar.md) |
| `REQ-RNK-001…008` | M07 Rank & Grid Tracking | [M07 §7](modules/M07-rank-and-grid-tracking.md) |
| `REQ-KW-001…007` | M08 Keyword Research | [M08 §5](modules/M08-keyword-research.md) |
| `REQ-IDX-001…005` | M09 Indexing | [M09 §5](modules/M09-indexing.md) |
| `REQ-LOC-001…006` | M10 Local SEO & GBP | [M10 §6](modules/M10-local-seo-and-gbp.md) |
| `REQ-REP-001…006` | M11 Reporting | [M11 §5](modules/M11-reporting-and-deliverables.md) |
| `REQ-BIL-001…008` | M12 Billing, Tiers & Cost | [M12 §6](modules/M12-billing-tiers-and-cost.md) |
| `REQ-X-001…010` | Cross-cutting | §3 below |

---

## 3. Cross-cutting acceptance

| Req | Criterion |
|---|---|
| `REQ-X-001` | Every long-running operation is a job with an idempotency key; running it twice produces one effect and one charge |
| `REQ-X-002` | One client's 50-page run cannot starve another client's queue; per-provider rate limits hold across all clients |
| `REQ-X-003` | Every AI interaction appears in LangSmith with client, module, job and cost attached |
| `REQ-X-004` | Sentry captures an error from backend, frontend and extension, each with PII scrubbed |
| `REQ-X-005` | One correlation id traces a request through its job to its provider call in the logs |
| `REQ-X-006` | Removing a provider key flips its capability in the truth table within one probe cycle |
| `REQ-X-007` | A nightly backup restores into a clean host and passes the integrity check |
| `REQ-X-008` | Offboarding a client destroys their key, hard-deletes their rows after the window, and records it |
| `REQ-X-009` | All six eval suites run in CI and fail the build below baseline |
| `REQ-X-010` | A module can be enabled for one client and remain off for the rest, evaluated server-side |

---

## 4. The invariants that are never negotiable

These are asserted continuously, not at a milestone. A build that violates one does not
merge, regardless of what else it achieves.

| # | Invariant | Gate |
|---|---|---|
| **I1** | No code path presents unmeasured data as measured | Truth gate (`pytest -m truth`) |
| **I2** | `absent` and `unmeasured` never collapse; ratios divide by measured only | CHECK constraints + unit tests |
| **I3** | Every tenant table has FORCE RLS and passes adversarial cross-tenant reads | RLS gate |
| **I4** | No terminal state claims success for work that did not happen | Per-path blocked-state tests |
| **I5** | No paid call bypasses the cost gate | Call-site enumeration test |
| **I6** | No secret appears in an API response, log, trace or Sentry event | Scanning test over a full exercise run |
| **I7** | Every generated page uses only approved DesignIR tokens | Token-conformance check pre-publish |
| **I8** | The citation extension cannot submit a form | Bundle assertion |
| **I9** | Zero honeypot touches | Form-fill eval |
| **I10** | Every test fails when its defect is re-injected | Review discipline + spot-check in CI |

---

## 5. Evidence discipline

For each requirement, the closing artefact records: the requirement id · what was done ·
**how it was verified in the running system** · the evidence reference (job id, URL,
screenshot key, CI run) · anything deliberately not done, with a follow-up id.

A requirement closed with "tests pass" and no runtime evidence is not closed.
