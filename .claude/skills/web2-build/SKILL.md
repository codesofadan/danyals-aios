---
name: web2-build
description: Plans a branded Web 2.0 link property (WordPress.com / Blogger / Tumblr / Medium) carrying ONE editorial backlink, lets the write worker draft it and park it at needs_review, then holds at the human quality gate for a LEAD to approve or reject - it NEVER auto-publishes. Use when an operator says "web 2.0", "tiered link property", "branded asset / property", "build a web2 backlink", or "publish a web 2.0 post". Spends metered AI generation budget (cost-gated server-side), publishes to an external platform on approval, and enforces footprint diversification + no spam.
argument-hint: "[client] [platform] [anchor] [target-url]"
arguments: [client, platform, anchor, target_url]
model: opus
disable-model-invocation: true
allowed-tools: Bash(python ${CLAUDE_PROJECT_DIR}/.claude/skills/_shared/aios_client.py:*), Read
---

# Build a Web 2.0 Property (Human-Gated)

**Purpose.** Queue a branded Web 2.0 property for `$client` that carries one editorial backlink (`$anchor` -> `$target_url`), let the worker draft it to `needs_review`, then STOP at the human quality gate. A LEAD reviews footprint diversity + anchor safety + draft quality and explicitly approves (publish) or rejects. This skill never publishes on its own.

**Who runs it.** Both `POST /offpage/web2/plan` and `POST /offpage/web2/{id}/approve` are LEAD-only (owner/admin/manager). A non-lead call 403s - report "requires a LEAD", STOP.

## Required inputs / keys
- `$client` - the client id (`clientId`). Snapshotted server-side; an unknown/invisible client 404s. Never invent one.
- `$platform` - one of 17 (exact): `WordPress.com`, `Blogger`, `Tumblr`, `Medium`, `dev.to`, `Write.as`, `Telegra.ph`, `Mataroa`, `Ghost`, `Mastodon`, `GitHub Pages`, `GitLab Pages`, `Micro.blog`, `Hashnode`, `Hatena Blog`, `LiveJournal`, `Dreamwidth`. Choose it for FOOTPRINT DIVERSITY against the client's existing web2 ledger - the wider set makes this much easier than picking among 4. `Medium` is DRAFT-ONLY (its publish API is retired) - plan it only if the operator explicitly wants a manually-finished draft.
- `$anchor` - the single editorial anchor text. Keep it branded/natural; an exact-match commercial anchor is a footprint risk.
- `$target_url` - the client page the backlink points to.
- Optional: `topic` (defaults to the anchor), `pageType` (`service|blog|local`, default `blog`), `framework` (`Auto`).
- `AIOS_API_BASE` (default `http://localhost:8000/api/v1`) and `AIOS_TOKEN` (EdDSA bearer).
- The draft generation spends metered AI budget (cost-gated: money-dial -> cache -> client cap -> daily spend-stop). If a spend-stop holds it, the property stays `draft`/held at honest $0 - report the hold; do not retry-loop to force spend.

**Trigger.** "Web 2.0 / tiered link property / branded asset / build a web2 backlink".

## Steps
Copy this checklist and check items off as you go:

```
- [ ] Step 1: Read the existing web2 ledger for footprint diversity (GET /offpage/web2)
- [ ] Step 2: Plan the property (POST /offpage/web2/plan); capture the id
- [ ] Step 3: Wait for the draft to reach needs_review (GET /offpage/web2)
- [ ] Step 4: STOP - present platform/anchor/target for the LEAD quality gate
- [ ] Step 5: On explicit LEAD go -> approve or reject (POST /offpage/web2/{id}/approve)
```

1. **Read the ledger for footprint.** Run `aios_client.py get /offpage/web2?clientId=<id>`. Check the platform mix + anchors already used so the new property diversifies (no stacking the same platform/anchor).
2. **Plan the property.** Run `aios_client.py post /offpage/web2/plan --json '{"clientId":"<id>","platform":"<platform>","anchor":"<anchor>","targetUrl":"<url>","pageType":"blog","framework":"Auto"}'` -> creates a `draft` and hands it to the write worker. Capture the returned `id`.
3. **Wait for needs_review.** Poll `aios_client.py get /offpage/web2?clientId=<id>` until the row's `status` field reaches `needs_review` (the worker owns `draft -> needs_review`; never force it). The ledger exposes 8 fields (id, client, platform, postUrl, anchor, verified, published, status) - the article BODY is still reviewed in the platform draft out-of-band, not via this API, but `status` itself is now directly readable (no more inferring it from a blank postUrl).
4. **STOP at the quality gate.** Present the metadata this skill CAN see (platform, anchor -> target, footprint fit) plus the reviewer checklist below. Do NOT approve on your own; approval publishes to an external platform.
5. **Approve or reject on the LEAD's explicit decision.** On an explicit LEAD go: `aios_client.py post /offpage/web2/{id}/approve --json '{"action":"approve"}'` (moves `needs_review -> publishing`, enqueues publish -> verify -> track) or `{"action":"reject"}` (-> `rejected`). 409 if it is not awaiting review.

Reviewer checklist the LEAD applies at the gate (footprint diversification + no spam):
- Platform diversifies the ledger (not the same platform/anchor stacked).
- Exactly ONE editorial backlink; anchor is branded/natural, not exact-match commercial (OFF-018/OFF-020 over-optimization risk).
- The article reads as a genuine branded asset, not thin/spun link bait (no PBN footprint, OFF-036).
- The draft body has been read in the platform draft (this API does not expose it).

## Decision points
- If the caller is not a LEAD -> `plan`/`approve` 403s -> report "requires a LEAD", STOP.
- If a spend-stop/cap holds the draft (stays `draft`, honest $0) -> report the hold; do NOT retry to force spend.
- If the row never reaches `needs_review` within the poll window -> report the held state; do not approve a property that is not drafted.
- If the operator has not explicitly approved at the gate -> STOP; NEVER auto-approve. Approval publishes externally.
- If footprint/anchor review fails (same platform stacked, exact-match anchor, thin draft) -> recommend `reject` (or re-plan on a different platform/anchor); do not approve a spammy footprint.
- If `approve` returns 409 (not awaiting review) -> the property is not in `needs_review`; re-read its status, do not retry blindly.

## Common Pitfalls
- "The draft is queued, I'll approve it to save a step." -> approval PUBLISHES externally and is a LEAD's manual call; this skill stops at the gate.
- Stacking the same platform/anchor as prior properties -> a footprint signal; diversify platform + anchor.
- Using an exact-match commercial anchor -> over-optimization (OFF-018/OFF-020); prefer branded/natural.
- Claiming the article is good without reading the body -> the body is not in this API; the LEAD must read the platform draft before approving.
- Retrying `plan`/publish when a spend-stop held it -> honest degrade; surface the $0 hold, do not force spend.
- Reading `verified=pending` as a live verified backlink -> pending is not verified; verification happens post-publish.

## Output format
Emit verbatim:

```
WEB 2.0 BUILD - <client>
Property: <id>   Platform: <platform>   Status: <draft|needs_review|publishing|rejected>
Backlink: "<anchor>" -> <target_url>
Footprint check: <"diversifies ledger" | "RISK: same platform/anchor stacked">
Anchor safety: <"branded/natural" | "RISK: exact-match commercial">
Draft body reviewed (platform draft, out-of-band): <yes/no - REQUIRED before approve>
Spend: <"generated" | "HELD by spend-stop/cap - honest $0">
Gate decision (LEAD only): <"awaiting LEAD" | "APPROVED -> publishing" | "REJECTED">
Note: this skill never auto-publishes; approve is a deliberate LEAD action.
Next: <LEAD reads draft + approves/rejects | re-plan on a different platform | monitor publish>
```

Rubric enforced (reference, not inlined): draft quality per `backend/docs/CONTENT-DOCTRINE.md`; footprint/anchor safety per `danyals-audit-system/checklists/off-page.yaml` + the Team C SOP `danyals-audit-system/.claude/agents/offpage/c2-anchor-toxicity.md` (OFF-017..023 anchors, OFF-036 PBN footprint). Shared depth in `${CLAUDE_PROJECT_DIR}/.claude/skills/_shared/reference/`.
