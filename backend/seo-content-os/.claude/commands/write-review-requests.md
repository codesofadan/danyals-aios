---
description: Write TOS-compliant review-request copy (in-person script, SMS, email, printed/QR, and a review-instructions asset) in the client's owner voice - ask everyone, gate no one, incentivize nothing.
argument-hint: <client-slug> [channels]
allowed-tools: Read, Write, Edit, Bash, Glob, Grep, WebSearch, WebFetch
---

Write review-request copy. Arguments: `$ARGUMENTS` (client slug, and optionally the channels wanted, e.g. `austin-roofing-co sms,email,in-person`). Default to all channels.

Read `CLAUDE.md`, `knowledge/foundations/review-content-strategy.md`, and `knowledge/playbooks/review-requests.md` first if not already in context. This command runs against the **review-requests** playbook. The job: make asking for a review effortless and well-timed so the operator asks more and sooner, which is the honest, compliant way to help review recency (the review sub-lever that actually moves rankings). We cannot post reviews; we only remove the friction from the ask.

**Compliance boundary (non-negotiable, cited in the playbook):**
- **No review gating / no sentiment filtering.** Every asset asks all customers the same way and links to the same public review surface. Never route unhappy customers to a private form. This is a Google review-policy prohibition.
- **No incentivizing.** No discount, gift, draw, cash, or reward tied to leaving a review or to its sentiment (Google policy + FTC final rule on consumer reviews, effective Oct 21 2024).
- **No fabricated urgency** (Law 20). **No fabricated review URL** - mark a placeholder for the operator's real GBP review link.

If a client asks for a gating funnel or an incentive, refuse, cite the policy, and offer the compliant alternative.

## Pipeline

Work in `output/<client-slug>/review-requests/`.

1. **LOAD.** Load `clients/<client-slug>/brand.yaml` (`voice`, vertical, NAP for signatures). Confirm the channels requested and note the operator responsibilities (real review link, SMS/email consent).

2. **DRAFT.** Write each requested asset per the playbook, in the client's voice, timed to peak satisfaction (job completion / same-day): in-person script, SMS (<160 chars, opted-in only), email (subject + body, one button), printed/QR leave-behind, and the review-instructions/landing asset. Reference the real job where the operator supplies it; never fabricate the job detail. Apply the vertical overlay (HIPAA / bar / financial) where relevant.

3. **COMPLIANCE PASS.** Verify every asset asks everyone, gates no one, incentivizes nothing, carries no fabricated urgency, and uses the direct-link placeholder rather than an invented URL. Write `compliance-note.md`.

## Output contract

Confirm in `output/<client-slug>/review-requests/`: `scripts.md` (in-person, SMS, email, printed/QR), `landing.md` (the review-instructions asset), and `compliance-note.md`. Report to the operator: package path, channels produced, the operator responsibilities (insert real GBP review link, honor SMS/email consent, set a same-day cadence), and confirmation that nothing gates or incentivizes.
