---
name: billing
description: Reports the agency's MRR, invoice ledger, and collected revenue, and drives an invoice through its manual lifecycle - draft, finalize, mark paid, void, refund. Use when an operator asks about MRR or recurring revenue, wants an invoice created, finalized, marked paid, voided, or refunded, asks what is outstanding or past due, wants a revenue or collections report, or asks what a client has been billed. Owner/admin only. There is no payment gateway: every status move is a manual operator action, and an issued invoice's amounts are frozen.
argument-hint: "[client] [action]"
arguments: [client, action]
model: sonnet
disable-model-invocation: true
allowed-tools: Bash(python ${CLAUDE_PROJECT_DIR}/.claude/skills/_shared/aios_client.py:*), Read
---

# Report and Drive the Invoice Ledger

**Purpose.** Report the agency's real money picture — MRR from subscriptions, the invoice ledger,
and collected cash — and move an invoice through its manual lifecycle without ever conflating the
three.

**Who runs it.** Reading needs `view_reports` **plus the `billing` feature grant** (which is NOT
in the seo/content/va role templates — only Super Admin/owner holds it by default). **Every
mutation is owner/admin ONLY** — `manager` is excluded here, unlike every other module's lead
write set, and the RLS policy mirrors it. Lacking either → 403 → report which one and STOP.

## Required inputs / keys
- `$client` — the client name, resolved to a real `client_id` (for a create or a filter). Never
  invent an id.
- `$action` — `report` (default), `create`, `finalize`, `mark-paid`, `void`, or `refund`.
- `AIOS_BASE_URL` (default `http://localhost:8000/api/v1`) and `AIOS_SKILL_TOKEN`.
- **No provider key, no gateway, no spend.** There is no Stripe/PayPal integration, no charge, no
  dunning, no webhook, no reconciliation. Nothing here talks to a payment processor.

**Trigger.** MRR / recurring revenue, creating / finalizing / paying / voiding / refunding an
invoice, "what's outstanding or past due", a revenue or collections report, "what has this client
been billed".

## Steps
Copy this checklist and check items off as you go:

```
- [ ] Step 1: Read the stats (MRR comes from subscriptions, NOT from invoices)
- [ ] Step 2: Read the invoice ledger + collected revenue as SEPARATE questions
- [ ] Step 3: Resolve the client, if creating or filtering
- [ ] Step 4: Edit amounts ONLY while the invoice is draft
- [ ] Step 5: Move status one legal transition at a time; render the pinned output
```

1. **Read the stats.** Run `python ${CLAUDE_PROJECT_DIR}/.claude/skills/_shared/aios_client.py get /billing/stats`
   → `GET /billing/stats` → `{mrr, openInvoices, pastDue}`. **`mrr` is read from `clients.mrr`
   (active clients' subscriptions) and never from the invoice table.**

2. **Read the ledger and the cash.** Run `aios_client.py get "/billing/invoices?clientId=<id>"` →
   `GET /billing/invoices` (filter with `&status=open`), one invoice with `aios_client.py get
   /billing/invoices/<number>` → `GET /billing/invoices/{number}` (the only route that carries
   `lines`), and `aios_client.py get "/billing/revenue?months=12"` → `GET /billing/revenue` →
   `[{period, invoices, collected}]`, which is **paid-only cash bucketed on `paid_at`**.

3. **Resolve the client.** Run `aios_client.py resolve-client --client "$client"` → `GET /clients`
   (name match). Capture `client_id`.

4. **Build the invoice while it is a draft.** Create: `aios_client.py post /billing/invoices --json
   '{"clientId":"<id>","kind":"retainer","lines":[{"description":"…","quantity":1,"unitAmount":0}]}'`
   → `POST /billing/invoices` (201; always starts `draft`). Amend: `aios_client.py patch
   /billing/invoices/<number> --json '{"tax":0}'` → `PATCH /billing/invoices/{number}`. Add a line:
   `aios_client.py post /billing/invoices/<number>/lines --json '{"description":"…","quantity":1,"unitAmount":0}'`
   → `POST /billing/invoices/{number}/lines`. Dropping a line is
   `DELETE /billing/invoices/{number}/lines/{line_id}` — **the shared client has no `delete` verb**,
   so the operator removes a line in the dashboard; report that, never claim you removed it.
   **All of these work only while `status == "draft"`.**

5. **Move the status manually, one legal step.** Finalize (`draft → open`): `aios_client.py post
   /billing/invoices/<number>/finalize` → `POST /billing/invoices/{number}/finalize`. Mark paid
   (`open|past_due → paid`): `aios_client.py post /billing/invoices/<number>/mark-paid --json
   '{"paidMethod":"bank transfer"}'` → `POST /billing/invoices/{number}/mark-paid`. Void
   (`draft|open|past_due → void`): `POST /billing/invoices/{number}/void`. Refund (`paid →
   refunded`): `POST /billing/invoices/{number}/refund`. Render the **Output format**.

## Decision points
- If asked for MRR → read **`stats.mrr`** only. **Never compute it from `sum(invoices)`, from
  `/billing/revenue`, or from a client's invoice history.** MRR is the forward subscription
  run-rate over **active** clients; invoices are a separate issued/collected ledger. They answer
  different questions and **will not agree** — that is correct, not a bug to reconcile.
- If MRR, the open/past-due counts, and collected revenue disagree → **report all three as
  distinct facts.** Do not "fix" the discrepancy, do not average them, do not present one as a
  check on another.
- If the client exits **2** with `status: 409` and *"not a draft - issued invoices cannot be
  edited"* → **STOP.** The invoice's amounts, dates, and payer are **frozen** (13 columns, enforced
  by a DB trigger as well as the app). Only `status` and the paid stamps may move. A wrong issued
  invoice is **voided and re-raised**, never edited. Do not retry, do not try another route.
- If the client exits **2** with `status: 409` and *"Illegal invoice transition"* → the move is not
  on the state machine. Legal: `draft→open|void`, `open→paid|past_due|void`, `past_due→paid|void`,
  `paid→refunded`; `void` and `refunded` are **terminal**. Re-finalizing an already-`open` invoice
  is also a 409 (the diagonal is not legal). Report the current status; never force a jump.
- If a payment needs collecting → **there is no gateway.** Marking paid **records** an operator's
  statement that money arrived; it does not move money. `paidMethod` is free text. Never imply the
  platform charged anyone or that a payment link exists.
- If an invoice is `past_due` → a nightly sweep flipped an already-issued `open` invoice past its
  due date plus a grace period. It only noticed a date passed; no one was chased.
- If asked to delete an invoice → **there is no DELETE route.** Void it.
- If the client exits **2** with `status: 409` and *"Invoice changed concurrently"* → someone else
  moved it. Re-read `GET /billing/invoices/{number}` before acting again.
- If a PATCH sets nothing → **400 "No fields to update"**.

## Common Pitfalls
- "MRR is the sum of this month's invoices." → No. MRR reads `clients.mrr` for **active** clients.
  Summing invoices mixes one-offs, arrears, and voids into a run-rate and is wrong every time.
- "Revenue collected should equal MRR × 12." → It should not. Collected is **paid-only cash on
  `paid_at`**; MRR is a forward run-rate. Different questions, different numbers.
- "The issued invoice has a typo in the amount, I'll PATCH it." → Frozen. Void and re-raise. The DB
  trigger refuses the write even if the app guard were bypassed.
- Marking an invoice paid because the client said they sent it → `mark-paid` is a **financial
  record**, not a note. Only an operator confirming receipt may ask for it.
- Assuming a payment link / receipt / gateway status exists → none do. No `payment_intent`, no
  `receipt_url`, no dunning.
- Using `total` → the wire key is **`amount`**. There is no `total`, no `id`, no `clientId` on the
  wire; the identifier is **`number`** (`INV-####`).
- Reading `lines` off the LIST route → only `GET /billing/invoices/{number}` carries them.
- Assuming a manager can issue invoices → billing writes are **owner/admin only**.
- Treating `refunded` as a re-openable state → `void` and `refunded` are terminal.

## Output format
Emit verbatim (values copied from the endpoints; never from memory):

```
BILLING — <client|agency-wide>
MRR (from clients.mrr, ACTIVE subscriptions — NOT from invoices): $<mrr>
Open invoices: <openInvoices>     Past due: <pastDue>
  ^ These three answer DIFFERENT questions (forward run-rate / ledger counts / see below)
    and are not expected to agree.

INVOICES (ledger):
  <number>  <client>  <amount> <currency>  <status>  <kind>
            issued=<issued|not issued>  due=<due|—>  period=<periodStart>..<periodEnd>
            paid: <paidAt|—> via <paidMethod|—>
  ...

DETAIL (if a single invoice):
  <number> — <client>   subtotal=<subtotal>  tax=<tax>  amount=<amount> <currency>
  Lines:
    <sortOrder>. <description>  qty=<quantity> × <unitAmount> = <lineTotal>
    ...
  Editable: <YES (draft) | NO — issued: amounts/dates/payer are FROZEN; void and re-raise>

COLLECTED REVENUE (paid-only cash, bucketed on paid_at — NOT MRR, NOT billings):
  <period>  invoices=<invoices>  collected=$<collected>
  ...

Action taken: <read-only | invoice created (draft) | line added/removed | finalized (draft->open)
  | marked paid (manual record — no gateway moved money) | voided | refunded>
Legal next moves from <status>: <draft->open,void | open->paid,past_due,void | past_due->paid,void
  | paid->refunded | void/refunded: TERMINAL>
<if 409> 409 (verbatim): "<detail>"
  -> STOP. <frozen: void and re-raise, never edit | illegal transition: re-read the status>
Payment note: there is no payment gateway. Every status move is a manual operator action.
```

Exact response fields + the MRR-source, freeze, and transition rules:
`${CLAUDE_PROJECT_DIR}/.claude/skills/_shared/reference/part8-output-formats.md` §8.
