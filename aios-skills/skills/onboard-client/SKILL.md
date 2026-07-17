---
name: onboard-client
description: Drives a client's onboarding run through its 11 steps, sealing collected access credentials into the encrypted vault and tracking which of them a human has actually verified. Use when an operator starts onboarding a new client, asks what onboarding is outstanding, wants to advance or complete an onboarding step, needs to record a GBP / CMS / analytics / Search Console login, or asks whether a client's access has been tested. Seals secrets into the vault; a sealed credential is never a verified one until a human signs in and says so.
argument-hint: "[client] [step]"
arguments: [client, step]
model: sonnet
disable-model-invocation: true
allowed-tools: Bash(python ${CLAUDE_PLUGIN_ROOT}/scripts/aios_client.py:*), Read
---

# Onboard a Client

**Purpose.** Create and drive `$client`'s onboarding run through its 11 steps, seal collected
access credentials into the vault, and keep the sealed/verified distinction honest so nobody
believes an untested login works.

**Who runs it.** Reading needs `view_reports`. Creating a run, updating/advancing a step, and
completing a run need **`manage_clients`** (owner/admin/manager). Every route needs the
`client_onboarding` feature grant. Lacking either → 403 → report which one and STOP.

## Required inputs / keys
- `$client` — the client name, resolved to a real `client_id`. Never invent an id.
- `$step` — the step key to act on (see the 11 below), or omitted for a status read.
- `AIOS_BASE_URL` (default `http://localhost:8000/api/v1`) and `AIOS_SKILL_TOKEN`.
- **The vault master key must be configured server-side** to seal a credential. This module makes
  no provider call and has **no cost dial** — nothing here spends.

**The 11 step keys** (template `local_seo_default`, in order): `kickoff`, `collect_gbp`,
`collect_website_cms`, `collect_analytics`, `collect_search_console`, `brand_assets`,
`competitor_list`, `keyword_seeds`, `baseline_audit`, `content_plan`, `reporting_setup`.
**Exactly FOUR are credential-bearing**: the `collect_*` ones. `brand_assets` is labelled "Collect
brand assets" but its key does not start with `collect_`, so it **cannot** carry a credential (400).

**Trigger.** Starting a new client's onboarding, "what onboarding is outstanding", advancing or
completing a step, recording a GBP / CMS / analytics / Search Console login, "has their access
been tested".

## Steps
Copy this checklist and check items off as you go:

```
- [ ] Step 1: Resolve the client (resolve-client)
- [ ] Step 2: Read the existing run, or create one
- [ ] Step 3: Read the run detail (only detail carries the steps array)
- [ ] Step 4: Advance a step; seal a credential ONLY on a collect_* step
- [ ] Step 5: Never flip `verified` without an explicit human access test
- [ ] Step 6: Complete only when nothing is unresolved; render the pinned output
```

1. **Resolve the client.** Run `python ${CLAUDE_PLUGIN_ROOT}/scripts/aios_client.py
   resolve-client --client "$client"` → `GET /clients` (name match). Capture `client_id`.

2. **Read or create the run.** Run `aios_client.py get "/client-onboarding/runs?status=in_progress"`
   → `GET /client-onboarding/runs`. To start one: `aios_client.py post /client-onboarding/runs
   --json '{"clientId":"<id>"}'` → `POST /client-onboarding/runs` (201; defaults to the
   `local_seo_default` template and the caller as owner). A second live run for the same client →
   **409 "Client already has an active onboarding run"** — read that one instead.

3. **Read the run detail.** Run `aios_client.py get /client-onboarding/runs/<run_id>` →
   `GET /client-onboarding/runs/{run_id}`. **Only the detail route populates `steps`** — the list
   route returns `steps: []`. Cross-check outstanding work with `aios_client.py get
   "/client-onboarding/steps?status=pending"` → `GET /client-onboarding/steps` and
   `aios_client.py get /client-onboarding/stats` → `GET /client-onboarding/stats`.

4. **Advance a step / seal a credential.** Run `aios_client.py patch
   /client-onboarding/runs/<run_id>/steps/<step_id> --json '{"status":"in_progress"}'` →
   `PATCH /client-onboarding/runs/{run_id}/steps/{step_id}`, or the intent-equivalent
   `aios_client.py post /client-onboarding/runs/<run_id>/steps/<step_id>/advance --json '{"status":"completed"}'`
   → `POST /client-onboarding/runs/{run_id}/steps/{step_id}/advance` (**same handler, same body,
   same response** — they differ in intent, not mechanics). To seal a credential on a `collect_*`
   step, include `"credential": {"credentialLabel":"…","secret":"…"}`.

5. **Never flip `verified` yourself.** Send `{"verified": true}` **only** when a human states they
   signed in and the access works. Nothing else in the module writes it.

6. **Complete the run.** Run `aios_client.py post /client-onboarding/runs/<run_id>/complete --json '{}'`
   → `POST /client-onboarding/runs/{run_id}/complete`. Unresolved steps → **422** listing them.
   Render the **Output format**.

## Decision points
- If a step has `hasCredential: true` but `verified: false` → **the credential was TYPED, not
  tested.** Report it as "collected, NOT verified". Sealing proves someone entered a secret; it
  proves nothing about whether it works. Never describe a sealed credential as working access.
- If asked to mark access verified → **only a human's explicit access test flips `verified`.** Do
  not infer it from `hasCredential`, from a completed step, or from the credential "looking right".
  If the operator has not said they signed in, leave it false and say why.
- If asked to seal a credential on a non-`collect_*` step (including `brand_assets`) → **400
  "Only a collect_* step may carry a credential"**. Four steps take credentials; `brand_assets`'s
  label is misleading. Do not retry against another step.
- If asked to read back or confirm a secret → **impossible and refused.** `secret` exists on one
  request model and **no response model**; `vaultSecretId` never reaches the wire either. There is
  no reveal path in this module. **Never echo a secret back**, never repeat it into a report or a
  message, never restate it "to confirm".
- If the operator asks which step tests the logins → **there is no such step.** "Test every login"
  is a rule encoded by the `verified` / `hasCredential` separation, not a step key. Do not name a
  step that does not exist; point at the unverified `collect_*` steps instead.
- If `POST /client-onboarding/runs/{run_id}/complete` returns **422** → steps are unresolved.
  Surface the returned labels; resolve or `skipped` them deliberately. Do **not** reach for
  `{"force": true}` unless the operator explicitly accepts closing an incomplete onboarding.
- If a step owner is being set → the id must be a **staff** user (404 "Owner must be a staff user";
  a portal client is refused). An explicit `null` unassigns.
- If a PATCH body sets nothing → **400 "No fields to update"**.

## Common Pitfalls
- "The credential is sealed, so their access is confirmed." → No. Sealing is typing, not testing.
  `verified` flips only on a human's explicit access test. This is the whole point of the split.
- Flipping `verified: true` alongside the seal "to save a round trip" → forbidden. It fabricates a
  test that nobody ran, and the next person will trust it.
- Echoing the secret back in the summary "so the operator can double-check it" → never. Secrets go
  in and never come out; there is no reveal path here.
- Trying to seal a credential on `brand_assets` because it says "Collect" → its key is not
  `collect_*`; the API 400s. There are exactly four credential-bearing steps.
- Naming a "test logins" step → it does not exist. Report unverified `collect_*` steps instead.
- Reading `steps` off the LIST route → it is `[]` there. Use the detail route.
- Forcing a run complete to tidy the board → `force` closes an onboarding with real gaps in it.
  Only an operator who accepts the gaps may ask for it.
- Reporting `due` / `target` as an ISO date → they are **formatted display strings**
  (`"Aug 14, 2026"`, or `"—"` when unset). Do not parse or re-format them.

## Output format
Emit verbatim (values copied from the endpoints; never from memory):

```
ONBOARDING — <client>
Run: <id>   Template: <template>   Status: <in_progress|on_hold|completed|archived>
Owner: <owner>   Progress: <progress>%   Target: <target>
Current step: <step> (<stepStatus>)
Agency-wide: inOnboarding=<inOnboarding>  stepsPending=<stepsPending>  completed30d=<completed30d>

Steps (11):
  <sortOrder>. <stepKey> — <label>
     status=<pending|in_progress|blocked|completed|skipped>  owner=<owner|unassigned>  due=<due>
     <if collect_*> credential: <sealed | not collected>   verified: <VERIFIED (human tested) | NOT VERIFIED>
     notes: <notes or none>
  ...

CREDENTIALS (4 collect_* steps — sealed is NOT verified):
  <stepKey>: hasCredential=<bool>  verified=<bool>  -> <"collected, NOT verified - a human must
    sign in and confirm before this counts as working access" | "verified by a human access test">
  ...
Secrets: never displayed. Sealed into the vault; no reveal path exists in this module.

Action taken: <read-only | run created | step advanced | credential sealed | verified flipped by
  human confirmation | run completed>
Blocked (if complete 422'd): <the unresolved step labels, verbatim>
```

Exact response fields + the sealed-vs-verified and collect_* rules:
`reference/part8-output-formats.md` §6.
