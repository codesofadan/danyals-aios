---
description: Write a batch of publish-ready review responses (positive, negative, fake) in the client's owner voice, grounded in each real review, then lint the batch for PII, keyword-stuffing, templated duplication, and off-voice patterns.
argument-hint: <client-slug> [path-to-reviews-file]
allowed-tools: Read, Write, Edit, Bash, Glob, Grep, WebSearch, WebFetch
---

Write a batch of review responses. Arguments: `$ARGUMENTS` (client slug, and optionally a path to a file of the reviews to answer, e.g. `austin-roofing-co data/reviews-2026-07.md`). If no reviews file is given, ask the operator to paste the reviews (review text, star rating, platform, and the reviewer's first name only if they disclosed it).

Read `CLAUDE.md`, `knowledge/foundations/review-content-strategy.md`, and `knowledge/playbooks/review-responses.md` first if not already in context. This command runs against the **review-responses** playbook. The job: reply to each review in the business owner's voice, grounded in what the review actually says, so the next prospect trusts the business more and the engine reads honest, specific, non-stuffed text.

**Hard line (Law 8 + Law 16 + Law 20):** no fabrication - never invent a detail, outcome, name, or address the review does not contain, and never manufacture a fact to insert a keyword. No detector-evasion; the response reads human because it is specific and true.

**Trust discipline (the highest-stakes rule here):** no PII. Never publish or confirm a customer's full name, address, account, medical, or legal detail beyond what the reviewer themselves disclosed. In medical/dental (HIPAA) and legal (bar rules) do not even confirm the person was a patient or client. Negatives are composed, non-defensive, moved offline to a real contact path, and disclose no private facts and admit no contested/legal liability. Suspected fake reviews get a calm public reply plus an operator flag to report, never a public accusation.

## Pipeline

Work in `output/<client-slug>/review-responses/<date>/`.

1. **LOAD.** Load `clients/<client-slug>/brand.yaml` (`voice`, `guardrails.review_pii_rule`, vertical). Load the reviews (from the given file or the operator's paste). Classify each as positive / negative / fake-suspicious.

2. **DRAFT.** For each review, write a response per the playbook structure for its type (positive 4-beat; negative 5-beat LATER pattern; fake = composed non-accusatory). Ground every response in that review's real content. Vary openings across the batch. Apply the vertical overlay (HIPAA / bar / financial) where relevant. Service name appears at most once, naturally, never stuffed.

3. **LINT.** Run `python scripts/review_response_lint.py` over the drafted batch. It checks: PII leakage, keyword-stuffing, templated near-duplication across responses, and off-voice patterns. On any flag, fix the specific response and re-run. Max 2 retries, then flag for the operator.

4. **FLAG.** Write `flags.md`: reviews to report as fake, negatives needing a real offline follow-up, and any response the operator must fact-check before posting.

## Output contract

Confirm in `output/<client-slug>/review-responses/<date>/`: `responses.md` (each response paired with the review it answers, PII redacted, labeled by type), `lint-report.md` (the linter output, clean), and `flags.md`. Report to the operator: batch path, counts by type, that the lint passed clean, and any review needing operator action. A batch is not done until the lint passes clean on every response.
