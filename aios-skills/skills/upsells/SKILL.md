---
name: upsells
description: Surfaces the agency-global Fiverr upsell catalogue (the add-on gigs the client portal can render) and manages it - list, create, edit, toggle active, and reorder. Use when the operator says "upsells", "offers", "add-on services", "Fiverr gigs", "add an upsell", "reorder the offers", or "which upsells convert". Creating/editing/toggling/reordering mutates the shared agency-global catalogue (owner/admin only) and is manual-invocation only.
argument-hint: "[action]"
model: sonnet
disable-model-invocation: true
allowed-tools: Bash(python ${CLAUDE_PLUGIN_ROOT}/scripts/aios_client.py:*), Read
---

# Manage the Upsell Catalogue

**Purpose.** Read and curate the agency-global Fiverr upsell catalogue: the add-on gig cards the client portal surfaces. This skill lists the catalogue with its portal-tracked click counts, and (owner/admin) adds, edits, toggles, or reorders cards. Every mutation changes what EVERY client's portal sees, so writes are deliberate and confirmed.

**Who runs it.** Reading the catalogue needs `view_reports` (any staff). Creating / editing / toggling / reordering requires an OWNER or ADMIN only (not manager) - matching the `upsells` RLS; anyone else is 403'd.

## Required inputs / keys
- `$ARGUMENTS[0]` (optional) - the intent: `list` (default), `add`, `edit`, `toggle`, or `reorder`.
- For `add`/`edit`: the card fields - `title`, `description`, `fiverrUrl`, `price`, `rating`, `reviews`, `icon`, `color`, `active`, `sort_order`. `clicks30d` is portal-tracked and NEVER set by hand (starts at 0).
- `AIOS_API_BASE` (default `http://localhost:8000/api/v1`) and `AIOS_TOKEN` (EdDSA bearer; owner/admin for writes).
- The shared client `${CLAUDE_PLUGIN_ROOT}/scripts/aios_client.py`; shared wiring in `${CLAUDE_PLUGIN_ROOT}/reference/`.
- No provider key or metered spend; these are catalogue CRUD writes. The cost is that they are agency-global.

**Trigger.** A request to view, add, edit, toggle, or reorder the upsell/add-on/Fiverr offers.

## Steps
Copy this checklist and check items off as you go:

```
- [ ] Step 1: Read the current catalogue (GET /upsells)
- [ ] Step 2: If a write was asked, confirm the exact change (owner/admin, agency-global)
- [ ] Step 3: Apply the write (POST /upsells | PATCH /upsells/{id} | POST /upsells/{id}/toggle | POST /upsells/reorder)
- [ ] Step 4: Re-read the catalogue; render the pinned output
```

1. **Read the catalogue.**
   Run `aios_client.py get /upsells` (add `--query active_only=true` for only the portal-visible cards). Capture per card: `id`, `title`, `active`, `clicks30d`, `price`, `rating`, `reviews`, `fiverrUrl`, `sort_order`.

2. **Confirm the write.** For any mutation, restate the exact change and that it is agency-global (every client portal). Require owner/admin + an explicit yes.

3. **Apply the write.**
   - Add: `aios_client.py post /upsells --json '{"title":"...","fiverrUrl":"...","price":...,"active":true}'`.
   - Edit: `aios_client.py patch /upsells/{id} --json '{...only changed fields...}'`.
   - Toggle active: `aios_client.py post /upsells/{id}/toggle`.
   - Reorder: `aios_client.py post /upsells/reorder --json '{"ids":["<id1>","<id2>",...]}'` (each id's `sort_order` becomes its index).

4. **Re-read and render.** Run `aios_client.py get /upsells` again and emit the **Output format**, including the estimated-conversions read (portal click -> Fiverr order rate 0.062 per the upsell catalogue model).

## Decision points
- If the caller is not owner/admin -> **STOP** before any write. Report "managing upsells requires owner or admin (manager cannot)"; deliver the read-only catalogue.
- If asked to set `clicks30d` -> refuse; it is portal-tracked, not editable. Change only the offer fields.
- If a PATCH/toggle targets an unknown id -> the endpoint 404s; re-resolve from Step 1, do not write a guessed id.
- If a reorder list omits some ids -> only the listed ids are re-indexed (unknown ids are skipped server-side); confirm the operator intends a partial reorder.
- If asked which upsells "convert best" -> rank by real `clicks30d`; do not invent conversion counts beyond the documented 0.062 estimate applied to real clicks.

## Common Pitfalls
- Editing an upsell that a client is mid-purchase on without confirming -> the catalogue is agency-global; every portal reflects the change immediately. Confirm first.
- Inventing `clicks30d`, ratings, or review counts -> use only the stored values; `clicks30d` starts at 0 and is portal-tracked.
- Assuming a manager can manage the catalogue -> only owner/admin; a manager read is fine but writes 403.
- Reordering by guesswork -> pass the full explicit `ids` order; the index IS the new `sort_order`.

## Output format
Emit verbatim:

```
UPSELLS - agency-global catalogue
Cards: <count> (<active count> active)
  [<order>] <title>  <active|inactive>  $<price>  <rating>* (<reviews>)  clicks30d=<clicks30d>
  ...
Est. conversions (30d): <sum(clicks30d) * 0.062, rounded>  (portal click -> order estimate)
Change applied: <none | added "<title>" | edited "<title>" (<fields>) | toggled "<title>" -> <active|inactive> | reordered N cards>
Scope note: this catalogue is agency-global (every client portal). Owner/admin only for writes.
```

Rubric enforced (reference, not inlined): the upsell catalogue model (fields + the 0.062 conversion estimate). Shared wiring + roles: `${CLAUDE_PLUGIN_ROOT}/reference/`.
