---
name: on-page-fix
description: Analyzes a client page for on-page SEO issues and applies an approved title/meta fix to the client's LIVE WordPress site behind a drift guard. Use when an operator wants an on-page analysis, a title or meta description fixed, a page's on-page score, a list of on-page recommendations, or wants to apply, revert, or dismiss a suggested fix. MUTATES a live client site: apply is lead-only, needs a literal confirm, refuses to overwrite a page edited since analysis, and never auto-applies a manual fix.
argument-hint: "[client] [page-url] [action]"
arguments: [client, page_url, action]
model: opus
disable-model-invocation: true
allowed-tools: Bash(python ${CLAUDE_PROJECT_DIR}/.claude/skills/_shared/aios_client.py:*), Read
---

# Analyze and Apply an On-Page Fix

**Purpose.** Analyze `$page_url` for `$client`, surface the on-page recommendations with their
real impact, and — only on an explicit operator decision — apply one to the **live WordPress
site** behind the drift guard.

**Who runs it.** Reading needs `view_reports`. `POST /on-page/analyze` needs `run_audits`.
**Apply, apply-bulk, revert, dismiss, and re-analyze are LEAD-only** (owner/admin/manager);
Postgres enforces this a second time via a trigger, so a non-lead write fails even if the API
were bypassed. Every route needs the `on_page` feature grant. Lacking either → 403 → report
which one and STOP.

## Required inputs / keys
- `$client` — the client name, resolved to a real `client_id`. Never invent an id.
- `$page_url` — the exact live URL to analyze.
- `$action` — `analyze` (default), `list`, `apply`, `revert`, or `dismiss`.
- `AIOS_BASE_URL` (default `http://localhost:8000/api/v1`) and `AIOS_SKILL_TOKEN`.
- **A WordPress application password must be sealed in the vault for the site**, or every apply
  HOLDS with "no WordPress credential for this site". The site also needs an SEO plugin (Yoast
  or Rank Math) whose meta keys are REST-registered, or a title/meta apply HOLDS with the
  bridge-missing reason. A hold is the expected state on an unbridged site, not an error.

**Trigger.** An on-page analysis, "fix the title / meta description", a page's on-page score, a
list of on-page recommendations, applying / reverting / dismissing a suggested fix.

## Steps
Copy this checklist and check items off as you go:

```
- [ ] Step 1: Resolve the client (resolve-client)
- [ ] Step 2: Queue the analysis, or read the existing one
- [ ] Step 3: Read the recommendations; read the detail of the one in question
- [ ] Step 4: Check fixKind + quickWin BEFORE proposing an apply
- [ ] Step 5: Apply ONLY on an explicit operator decision, with a literal confirm
- [ ] Step 6: Read the result state honestly; render the pinned output
```

1. **Resolve the client.** Run `python ${CLAUDE_PROJECT_DIR}/.claude/skills/_shared/aios_client.py
   resolve-client --client "$client"` → `GET /clients` (name match). Capture `client_id`.

2. **Queue the analysis.** Run `aios_client.py post /on-page/analyze --json
   '{"clientId":"<id>","pageUrl":"$page_url","targetKeyword":"<kw>"}'` → `POST /on-page/analyze`
   (202, returns `{code, queued}` — **no `reason` field**). To re-analyze after drift:
   `aios_client.py post /on-page/analyze/<code>/re-analyze` → `POST /on-page/analyze/{code}/re-analyze`.
   Read progress with `aios_client.py get "/on-page/analyses?clientId=<id>"` → `GET /on-page/analyses`.

3. **Read the recommendations.** Run `aios_client.py get "/on-page/recommendations?clientId=<id>&status=open"`
   → `GET /on-page/recommendations`, then the one in question with `aios_client.py get
   /on-page/recommendations/<rec_id>` → `GET /on-page/recommendations/{rec_id}` (adds `detail`
   and `analysisStatus`). Fields: `${CLAUDE_PROJECT_DIR}/.claude/skills/_shared/reference/part8-output-formats.md` §4.

4. **Check `fixKind` and `quickWin` before proposing anything.** `autoApplicable` is derived as
   `fixKind != "manual"` and does **not** predict success — only `title` and `meta` reach the
   live site through the SEO-plugin bridge. `quickWin` is the honest signal.

5. **Apply only when the operator explicitly says to.** Run `aios_client.py post
   /on-page/recommendations/<rec_id>/apply --json '{"confirm": true}'` → `POST
   /on-page/recommendations/{rec_id}/apply`. `confirm` must be a **literal JSON `true`** — `1`,
   `"true"`, `"yes"` are all 422'd before the route runs. To undo: `aios_client.py post
   /on-page/recommendations/<rec_id>/revert --json '{"confirm": true}'` → `POST
   /on-page/recommendations/{rec_id}/revert`. To close without touching the site:
   `aios_client.py post /on-page/recommendations/<rec_id>/dismiss` → `POST
   /on-page/recommendations/{rec_id}/dismiss`. Bulk (max 50 ids): `aios_client.py post
   /on-page/recommendations/apply-bulk --json '{"ids":["…"],"confirm":true}'` → `POST
   /on-page/recommendations/apply-bulk`.

6. **Read the result honestly.** Apply the Decision points, render the **Output format**. Read
   the stats with `aios_client.py get /on-page/stats` → `GET /on-page/stats`.

## Decision points
- If the client exits **2** with `status: 409` → **STOP.** The live page changed after the
  analysis: someone hand-edited it and applying would overwrite a human's work. **Re-analyze**
  (`POST /on-page/analyze/{code}/re-analyze`), then re-read the recommendation. Do **NOT** pass
  `force: true` to push past it — `force` overwrites a real person's edit and only an operator
  who has seen the current live value may ask for it.
- If `state` is **`held`** → **this is NOT success and NOT a failure. Nothing was written to the
  site.** Report the `reason` verbatim and what it needs:
  - bridge missing → the site needs Yoast / Rank Math with the meta key REST-registered
    (`show_in_rest`). Route to a human to install/configure the WP bridge.
  - no WordPress credential → seal the site's application password in the vault.
  - no WordPress post is linked / no automated apply path / no proposed value → a human makes the
    change by hand.
- If `fixKind` is **`manual`** → **it NEVER auto-applies.** Single apply 422s; in apply-bulk it
  comes back `state: "skipped"`, `reason: "manual fixes must be made by a human"` and the batch
  continues. Hand the change to a human. Do not try to route it through another endpoint.
- If `state` is **`noop`** (`"already applied (idempotent)"`) → the fix is already live. Report
  it as already-applied, not as a fresh win.
- If `confirm` is missing or not a literal `true` → **422**. Do not "fix" it by sending `1` or
  `"true"`; send `{"confirm": true}` or do not apply.
- If the operator asks to apply everything → use apply-bulk, but read the results array
  per-id. **`skipped` lumps together skipped + blocked + held + failed** — there is no per-state
  tally, so report each result's own `state`, never the summary count alone.
- If `analysisStatus` is not `done` → the recommendation may be mid-flight. Wait; do not apply
  off a partial analysis.

## Common Pitfalls
- "It 409'd, I'll re-run with force to get it applied." → No. The 409 means a human edited that
  page after our analysis; force silently overwrites their work. Re-analyze and look at what
  changed. `force` is an operator's informed decision, never a retry strategy.
- "`state: held` and no error, so it worked." → A hold wrote **nothing** to the site. Report it as
  needing the WordPress bridge / credential, not as an applied fix.
- "`autoApplicable: true`, so this will land." → It only means `fixKind != "manual"`. A
  `heading` / `schema` / `content` fix holds with "no automated apply path". Trust `quickWin`.
- Sending `{"confirm": 1}` after a 422 → `confirm` is a strict bool; `1` is refused on purpose, so
  a truthy accident can never mutate a live site. Send a literal `true`.
- Applying a `manual` fix "since the proposed value is right there" → manual means a human must
  make the change. The endpoint refuses it, and so should the skill.
- Reporting `applied: 3, skipped: 2` from a bulk run as "3 fixed, 2 not applicable" → `skipped`
  hides blocked (drift!) and held rows. Enumerate the per-id states.
- Quoting `score` as a breakdown → it is a **flat float**. There is no `score.total` or sub-score
  on the wire.
- Inventing a drift hash / etag / version → there is none. The guard is a plain string comparison
  of the live field against the analysis-time snapshot. Describe it that way.

## Output format
Emit verbatim (values copied from the endpoints; never from memory):

```
ON-PAGE — <client> · <page>
Analysis: <OP-####>   Status: <queued|analyzing|done|failed|held>   Score: <score>
Open: <openCount>   Applied: <appliedCount>   <error, if non-empty>

Recommendations (open):
  [<rec_id>] <issue> (<issueCode>)  impact=<High|Med|Low>  fixKind=<kind>  quickWin=<bool>  priority=<priority>
    current:  "<current or (empty)>"
    proposed: "<proposed or (empty)>"
    bridge-deliverable: <yes (title/meta) | NO -> will hold ("no automated apply path")>
  ...

Action taken: <none (read-only) | apply | revert | dismiss | apply-bulk>
Result: state=<applied|reverted|noop|skipped|held|failed>   reason: "<reason or none>"
  <held  -> NOT applied, nothing written to the site. Needs: <the reason, verbatim>>
  <noop  -> already applied (idempotent); not a fresh change>
  <409   -> STOPPED: the live page changed after this analysis. Re-analyze; do NOT force.>
  <422   -> refused: <manual fix | confirm was not a literal true>>
Bulk (if used): applied=<applied>  skipped=<skipped>  (skipped lumps skipped+blocked+held+failed)
  per-id: <rec_id>=<state> ("<reason>") ...
```

Exact response fields, the hold reasons verbatim, the 409 messages, and the confirm rule:
`${CLAUDE_PROJECT_DIR}/.claude/skills/_shared/reference/part8-output-formats.md` §4.
