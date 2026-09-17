# M04 · Citations

Requirements: `REQ-CIT-001` … `REQ-CIT-021`.

An operator-driven browser extension backed by an AI agent that **creates the directory
account**, fills the listing form, and stages it for a human to submit. Aggregator
submission paths (Yext, Data Axle, Apify) are **out** — not deferred, not stubbed.

---

## 1. The division of labour

| Actor | Does |
|---|---|
| **Backend graph** | Decides everything: which fields map to what, what to type, how to create an account, how to verify an email, whether a field is a trap |
| **Extension** | Observes the page, applies a fill plan, shows the operator what will be sent. Holds no credentials, no client data at rest, and **cannot submit** |
| **Human operator** | Opens the directory, reviews the staged values, **presses submit**, confirms the result |

`REQ-CIT-013`: **a human always presses submit.** This is a capability the system does not
have, not a policy it follows — the extension contains no code path that dispatches a form
submission or clicks a submit control, and a test asserts the absence.

---

## 2. Canonical NAP

`REQ-CIT-001`. One canonical NAP per client, per location. Every submission reads from it
and nothing else. It is sourced from the client profile and, where connected, reconciled
against GBP (M10). Any inconsistency between GBP, the site and live citations produces a
NAP consistency score and a task — it never produces a silent choice.

---

## 3. Directory registry

`REQ-CIT-003`. Seeded with ≥160 directories, each carrying:

`name` · `url` · `country` · `vertical` · `authority_tier` · `mechanism` (form / API /
email / offline) · `requires_account` · `verification_kind` (none / email / phone / postal
/ manual) · `submission_url_pattern` · `terms_position` (permits / restricts / forbids
automated submission) · `terms_checked_on` · `state`.

**`terms_position` is load-bearing.** A directory that forbids automated submission is
`human_only`: the extension may pre-fill nothing and the operator works it manually with the
payload shown beside the tab. A directory that forbids third-party listing creation
altogether is `do_not_use` and never enters a queue.

Geography and vertical are how the registry is filtered per client. Gap analysis
(`REQ-CIT-004`) ranks the remainder by authority, vertical fit and effort.

---

## 4. The extension

Chrome MV3. TypeScript. Vite. Roughly 2,000 lines — it should stay small.

```
sidepanel/       the operator's surface: session queue, staged values, confidence flags
background/      service worker: token, API calls, orchestration, session state
content/
  collector.ts   builds the PII-free structural digest
  filler.ts      applies a fill plan; refuses anything not in the plan
lib/             api client (generated), session, messaging
```

### Authentication
A scoped **operator token**: 8 hours, bound to one user, one client and one session, with
only `citations:analyze` and `citations:record`. It cannot read the vault or address another
client (`REQ-CIT-005`).

### The digest
`REQ-CIT-006`. The collector sends a **structural** description of the page's forms:

```jsonc
{
  "forms": [{
    "action_kind": "same_origin_post",
    "fields": [{
      "index": 3, "tag": "input", "type": "text",
      "name_shape": "word_word",            // SHAPE, not the literal name, where the name is identifying
      "label_text": "Business phone",        // visible label text — needed to map
      "placeholder": "(555) 555-5555",
      "required": true, "maxlength": 20,
      "visible": true, "in_viewport": true,
      "nearby_text": "Enter a number customers can reach you on",
      "sibling_hints": ["tel"], "autocomplete": "tel"
    }],
    "structural_fingerprint": "sha256:…"
  }]
}
```

**No typed values, no cookies, no page HTML, no user content leaves the browser.** The
digest is labels and structure — enough to map fields, not enough to reconstruct a page.

### jsdom caveat for tests
jsdom has no layout engine (`offsetParent` is always `null`) and no `CSS.escape`. Both must
be stubbed **and each test must assert its stub is exercised**, or the visibility matcher
measures as crippled and every test passes vacuously. v1's heuristic filler had zero real
coverage for exactly this reason.

---

## 5. Form intelligence

`REQ-CIT-010`. **Heuristic first, model second, cache always.**

```
  digest
   └── structural_fingerprint → form_field_maps cache?
         ├── HIT  → fill plan in <400 ms, no model call, no spend
         └── MISS → heuristic matcher (labels, autocomplete, types, proximity)
                     └── unresolved or low-confidence fields only → LangGraph: form_fill
                           └── plan + per-field confidence + IGNORE list
                                 └── cache under the fingerprint
```

The fingerprint is **structural** — field order, types, label shapes, required flags. It is
deliberately **not** the URL and **not** CSS selectors: directories rotate class names per
load and reuse one form across many URLs, so a selector-keyed cache is wrong in both
directions.

### Honeypots and traps
`REQ-CIT-011`. This is the defect that made v1's citations worthless: its heuristic filler
put the client's website URL into a honeypot field named `url` and **truthfully reported
success**, while the directory silently discarded every submission.

Rules now:
- A field that is hidden, zero-sized, positioned off-screen, has `tabindex="-1"`, or sits
  beside text asking that it be left empty, is classified `IGNORE`.
- The model is asked about every ambiguous field and answers `FILL` or `IGNORE` with a
  reason; it can read "leave this field empty" beside the input, which a heuristic cannot.
- **Touching a honeypot is a hard failure, not a success.** The submission is refused.
- Eval gate: **0% honeypot touches** across the fixture corpus. Not "low" — zero.

### Confidence
Every planned value carries a confidence. Low-confidence fields are **offered, never
silently typed** — the panel highlights them and the operator confirms. The operator can
correct any value, and a correction is fed back as a cache improvement with the operator as
`verified_by`.

---

## 6. Account creation

`REQ-CIT-007`. The real gap. In v1, 12 of 155 directories had accounts, and there was no
path to the other 143.

A prominent **"Create account"** action in the panel starts a graph:

```
  account_creation graph
    ├── generate identity     ── username policy per directory, strong password
    │                             → VAULTED SERVER-SIDE. The extension never sees it.
    ├── allocate email alias  ── client-scoped alias on the agency catch-all domain
    ├── fill signup form      ── same form-intelligence path
    ├── CAPTCHA               ── solver where permitted; otherwise the human in the tab
    ├── HUMAN PRESSES SUBMIT
    ├── await verification    ── interrupt(): the graph parks, durable, survives restarts
    │     └── IMAP consumer polls the alias, extracts the link or code,
    │         completes verification
    └── record account        ── state=verified, health=new
```

### Email identities
`REQ-CIT-008`. A per-client **addressed alias** on an agency-owned catch-all domain —
`client-slug+directory@citations.<agency-domain>` or a per-client subaddress scheme. One
mailbox, deterministic routing, no per-client inbox to provision. The IMAP consumer is a
scheduled job with per-directory extraction rules and a generic link-finder fallback.

### Phone / SMS
`REQ-CIT-009`. Surfaced as a **human task** with the client's real number. No SMS-receive
services: a pooled or virtual number is exactly the signal directories use to detect
fake listings, and it puts the client's listing at risk to save a few minutes.

### CAPTCHA
`REQ-CIT-012`. Automatic solving where the directory's terms permit it, with per-solve cost
recorded against the citation. Otherwise the panel asks the operator to solve it in the tab.

---

## 7. Submission and proof

```
  operator reviews staged values in the panel
    └── presses SUBMIT in the page (their action, their click)
          └── extension captures: full-page screenshot, the submitted field set,
              timestamp, resulting URL, the directory's response text
                └── POST /citations/submissions/{id}/proof
```

`REQ-CIT-015`. The proof artefact is what makes a citation defensible to a client six
months later.

### Liveness
`REQ-CIT-016`. A submission is not `live` because it was submitted. It is `live` when the
listing URL has been **fetched and matched against the canonical NAP**. Re-verification at
7, 30 and 90 days, then quarterly. A listing that changes or disappears raises a task.

### Duplicates
`REQ-CIT-019`. If the citation audit or the operator finds an existing listing for the
business, it is **reported as a claim task**, never submitted over. Claim flows (postcard,
phone PIN) are explicitly out of scope — they are human work outside the tool.

---

## 8. Isolation

`REQ-CIT-017`. Per-client browser profile, and a per-client proxy where proxies are used. No
cookie, session or fingerprint is shared between clients. An operator working client A and
then client B uses two profiles, and the panel makes the active client unmistakable — a
submission recorded against the wrong client is worse than no submission.

---

## 9. Economics

`REQ-CIT-018`. Two figures, both reported:

| Figure | Contents |
|---|---|
| **Marginal** | CAPTCHA solves, proxy bandwidth, model tokens for cache misses, email infrastructure amortised |
| **Loaded** | Marginal **plus operator minutes** at a configured rate |

The 10¢ marginal target and 20¢ hard line were set for a fully automated route. With a human
pressing submit, the loaded figure is the honest one, and it must be reported to the client
as such. The cache is the primary marginal-cost lever: a cache hit costs no model tokens at
all, and directories are re-used across clients, so the fiftieth client on a given directory
costs nearly nothing to map.

Per-directory analytics: cache-hit rate, average operator minutes, success rate, failure
reasons. This is how the directory set gets pruned to the ones worth doing.

---

## 10. Operator session board

`REQ-CIT-020`. The panel shows the queue of directories for this client, each item's state,
and a **resume point** — closing the browser mid-session must lose nothing. The session is a
server-side record; the extension is a view of it.

---

## 11. Acceptance criteria

| # | Criterion |
|---|---|
| A1 | **100 live, NAP-verified citations** for one client, with proof artefacts, built through the extension |
| A2 | Account creation succeeds end to end on ≥25 directories including automated email verification |
| A3 | **Zero honeypot touches** across the 25-form fixture corpus, including five known trap forms |
| A4 | Field mapping accuracy ≥95% on the fixture corpus; cache hit returns a plan in <400 ms with no model spend |
| A5 | The extension contains no code path that submits a form — asserted by a test over the built bundle |
| A6 | Credentials generated during account creation are never present in extension storage, the DOM, a log, or an API response |
| A7 | Killing the browser mid-session loses no state; the session resumes at the same directory |
| A8 | A submission recorded against client A is invisible to client B at every layer including RLS |
| A9 | Loaded cost per citation is reported and within the agreed ceiling across the 100-citation run |
| A10 | A directory marked `human_only` presents the payload for manual entry and pre-fills nothing |
| A11 | A duplicate listing produces a claim task, not a submission |
| A12 | Liveness re-check correctly flags a listing whose NAP was altered by the directory |
