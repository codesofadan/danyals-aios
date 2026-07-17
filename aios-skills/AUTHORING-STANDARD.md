# Skills Authoring Standard — Danyal AIOS (`aios-seo` plugin)

**The committed standard every AIOS Agent Skill in this plugin follows.** Read this before
writing or editing any `SKILL.md`. The goal: ~30 skills that read as if **one senior SEO
operator** wrote them — same shape, same voice, same guardrails — so a teammate (or Claude)
can pick up any skill and know exactly what it does, when it fires, what it calls, and what it
returns.

Skills are the platform's **operator layer**. The FastAPI backend (`backend/app/routers/*`)
already owns the money, the state machines, the RLS boundary, and the ranking-grade
generation. A skill is a *thin, disciplined operator* on top of those routes: it gathers the
right inputs, calls the right endpoint(s) in the right order, enforces the human-review gate,
and returns a pinned deliverable. **A skill never re-implements backend logic and never
invents data.**

Authoritative sources this standard is built on (2026):
- Anthropic — *Skill authoring best practices*: https://platform.claude.com/docs/en/agents-and-tools/agent-skills/best-practices
- Anthropic — *Equipping agents for the real world with Agent Skills*: https://www.anthropic.com/engineering/equipping-agents-for-the-real-world-with-agent-skills
- Claude Code — *Extend Claude with skills* (frontmatter + invocation reference): https://code.claude.com/docs/en/skills
- Agent Skills open standard: https://agentskills.io
- obra/superpowers — *writing-skills* (pushy descriptions, rule-then-why, closing loopholes): https://github.com/obra/superpowers/blob/main/skills/writing-skills/SKILL.md
- anthropics/skills — reference skills + spec: https://github.com/anthropics/skills
- Internal ranking rubric skills MUST cite: `reference/CONTENT-DOCTRINE.md` (a verbatim mirror
  of `backend/docs/CONTENT-DOCTRINE.md` — the backend copy is the source of truth).
- Internal audit SOPs skills mirror: `danyals-audit-system/.claude/agents/`, `danyals-audit-system/checklists/`

---

## 0. This plugin's concrete wiring (read before §1)

This is a **Claude Code plugin** named `aios-seo`. Two facts every skill depends on:

- **One shared backend client**, not per-skill curl: `scripts/aios_client.py` at the plugin
  root. Skills invoke it as `python ${CLAUDE_PLUGIN_ROOT}/scripts/aios_client.py <subcommand>`.
  `${CLAUDE_PLUGIN_ROOT}` resolves to this plugin's install directory regardless of cwd.
- **Env-configured auth** (the P9-1 skill-token gateway): `AIOS_BASE_URL` (default
  `http://localhost:8000/api/v1`) and `AIOS_SKILL_TOKEN` (the skill bearer). The client also
  accepts the legacy names `AIOS_API_BASE` / `AIOS_TOKEN` as a fallback. The token is set only
  as an `Authorization` header — **never printed, never in a skill body**.

Skills run in **Claude Code (web or CLI)**, NOT claude.ai chat. The second AI surface is the
web dashboard (Anthropic-API), which is a separate product, not these skills.

---

## 1. RFC-2119 language (used throughout these docs and every skill)

**MUST / MUST NOT / REQUIRED** = non-negotiable; a reviewer rejects the skill if violated.
**SHOULD / SHOULD NOT** = strong default; deviate only with a stated reason.
**MAY** = genuinely optional.

Reserve soft words (*prefer*, *consider*, *usually*) for shaping **output form** only —
**never** for a discipline rule (grounding, the review gate, spend). obra/superpowers rule:
*"Violating the letter of the rules is violating the spirit of the rules."*

---

## 2. Frontmatter rules

YAML frontmatter starts at **byte 0** with `---` and ends with `---`. Only `name` and
`description` are required; everything else is scoped deliberately.

| Field | Req? | AIOS rule |
|---|---|---|
| `name` | **MUST** | lowercase letters/numbers/hyphens, ≤64 chars, **exactly equals the parent folder** (`local-service-page/SKILL.md` → `name: local-service-page`). No `anthropic`/`claude`, no XML/angle brackets anywhere in frontmatter. |
| `description` | **MUST** | Third person, ≤1024 chars. **State WHEN to use, not a workflow summary** (§3). Pack trigger keywords. |
| `argument-hint` | SHOULD | Autocomplete hint of expected args, e.g. `[client] [city] [service]`. Every operator skill that takes input MUST declare it. |
| `arguments` | MAY | Named positional args for `$name` substitution (space-separated or YAML list). Use when the skill reads ≥2 ordered inputs. |
| `allowed-tools` | **MUST** (if it calls out) | Tightest set that lets the skill run without per-call prompts (§6). |
| `disallowed-tools` | MAY | Remove a tool for the skill's active turn (e.g. `AskUserQuestion` on an autonomous loop). |
| `model` | SHOULD | `opus` for reasoning/judgement-heavy skills (§5); omit (inherit) or `sonnet` for mechanical ones. |
| `disable-model-invocation` | **MUST decide** | `true` for any skill with money/publish/external-write/destructive side effects (§5). Documented per skill in the INVENTORY. |
| `user-invocable` | MAY | `false` only for pure background-knowledge skills users shouldn't run as a command. AIOS operator skills stay `true`. |
| `context` / `agent` | MAY | `context: fork` to run a heavy skill in an isolated subagent (only for skills with an explicit task + prompt). |
| `metadata` / `license` | MAY | Standard passthrough fields. |

**Substitutions available in the body:** `$ARGUMENTS` (all args; auto-appended as
`ARGUMENTS: …` if you never reference it), `$ARGUMENTS[N]` / `$N` (0-based positional),
`$name` (from `arguments`), `${CLAUDE_PLUGIN_ROOT}` (this plugin's install dir — use it to
reference `scripts/aios_client.py` regardless of cwd), `${CLAUDE_SKILL_DIR}` (this skill's own
dir — use it for skill-local `reference/` files), `${CLAUDE_PROJECT_DIR}`, `${CLAUDE_SESSION_ID}`.
Multi-word positional args MUST be quoted when invoked: `/local-service-page acme "San Jose" "AC repair"`.

**Dynamic context injection:** a `` !`<command>` `` line runs a shell command and inlines its
output **before** Claude sees the body — use it to pull the caller's fresh state (e.g. the
client's current context health) into the skill at load time. It requires the command to be
in `allowed-tools`.

---

## 3. The description is the whole ballgame

The description is the **only** part of a skill loaded at startup (~100 tokens/skill); the
body loads only on activation. If the description doesn't match the request, the body is
never read. Rules:

1. **Third person, always.** "Generates a ranking-grade local service page…" — never "I can…"
   or "You can…". Point-of-view drift breaks discovery.
2. **WHEN to use, NOT a workflow summary.** obra/superpowers proved a description that
   summarizes steps makes Claude follow the summary and *skip reading the body* (it did ONE
   review when the body required TWO). State triggers and symptoms; let the body own the steps.
3. **Be pushy — Claude under-triggers.** Front-load concrete trigger phrases the operator
   actually types: page types, city+service shapes, endpoint nouns, deliverable names,
   "monthly report", "toxic backlinks", "GBP", "citation", "policy change".
4. **Name the boundary.** If a skill has a side effect, say so ("…creates a content job and
   spends metered AI budget", "…writes to the client's Google Sheet").
5. **Two-part shape:** `<verb-first what it produces>. Use when <observable triggers / inputs / who is asking>.`

Good: `Generates a ranking-grade LOCAL service page (city + service) grounded in fresh client context, runs the QA §11 gate, and returns draft + JSON-LD + QA score. Use when an operator needs a city/service landing page, a "<service> in <city>" page, or a local page for a client with a physical service area.`

Bad: `Helps with content.` / `Creates a page then reviews it then publishes it.` (workflow leak)

---

## 4. The SOP body shape (every skill uses this skeleton)

Body ≤ **500 lines**, ideally far less. State what to do; don't narrate why at length (the
rubric doc holds the "why"). Fixed section order — mirrors the audit-engine agent SOPs
(`danyals-audit-system/.claude/agents/*` → *Checks you own · Inputs · Rubric · Hard rules ·
Output*), tuned for operator skills:

1. **`# <Verb-first Title>`** — e.g. `# Generate a Local Service Page`. One line.
2. **Purpose (one line).** What ranking-grade artifact/outcome this produces. No preamble.
3. **Who runs it.** The backend role/permission the caller must hold (e.g. *`publish_content`
   lead*, *any `view_reports` staff*, *owner/admin/manager only*). If the operator lacks it,
   the endpoint 403s — say so.
4. **Required inputs / keys.** Bullet list. Every input the numbered steps consume, named
   exactly as the step uses it. Include env/keys: `AIOS_BASE_URL`, `AIOS_SKILL_TOKEN`, and any
   provider key the underlying route needs live (Serper/Anthropic for content; Google for
   reports). State the **degrade behavior** if a key is dormant.
5. **Trigger.** One line restating when to fire (echoes the description; anchors the body).
6. **Steps — verb-first, numbered, testable.** Each step: a verb, the exact endpoint it hits
   (`POST /api/v1/content/jobs`), and the **input it names**. A reader must be able to check
   each step happened. Prefer a copy-paste **checklist block** for ≥4 steps (Anthropic
   workflow pattern) so Claude tracks progress and never skips the QA gate.
7. **Decision points — explicit `If X → Y`.** Every branch is spelled out, not implied:
   `If qa.passed is false → STOP, surface the failing dimensions + [NEEDS:] markers, do NOT
   approve.` `If context health lag > 0 → warn the operator the draft may miss recent facts.`
   Use a small flowchart ONLY for a real decision fork or a "stop too early" loop — never for
   linear steps or reference.
8. **Common Pitfalls.** 3–8 bullets of the specific ways this skill goes wrong, each paired
   with the correction (the obra/superpowers rationalization table). E.g. *"Approving a draft
   with an unresolved `[NEEDS:]` — the QA gate will reject it at publish; resolve the fact
   first."*
9. **Pinned output format.** A fenced template the skill MUST emit verbatim (strict template
   pattern). Same shape across a module's skills so deliverables are comparable. Include the
   real fields the endpoint returns (`qa.weighted_total`, `qa.passed`, `qa.blocked_by`, the
   14 named dimensions, the job code) — never invented numbers.

Voice: senior consultant register (McKinsey/iPullRank/Aleyda Solis). State the exact action.
No marketing fluff, no softening adverbs, no em/en dashes in generated client-facing prose
(the audit renderer strips them; match it). Consistent terminology — pick one term
("content job", "the QA gate", "grounding", "the review gate") and reuse it everywhere.

---

## 5. Model selection & invocation control

**`model: opus`** for skills whose value is *judgement*: reviewing a draft against the
14 QA dimensions, choosing a differentiation angle, prioritizing audit findings, writing the
monthly-report narrative, reading a client snapshot, technical/local/GEO audit reasoning,
policy-brief impact analysis. These skills reason over rubrics and evidence — give them the
strongest model.

**Inherit / `sonnet`** for mechanical skills: listing/reordering upsells, syncing a sheet,
routing/assigning a task, reading team status, building a citation from fixed fields. Don't
pay opus for CRUD.

**`disable-model-invocation: true`** (manual `/skill` only, kept out of auto-trigger) for any
skill that **spends money, publishes/goes live, writes to an external system, or is
destructive**. Rationale (Claude Code docs): *"You don't want Claude deciding to deploy
because your code looks ready."* In AIOS that means: web2 build/approve, report sync &
sheets-sync (external Google write), monthly-report (external write), assign-task (creates
work + reassigns), upsells (mutates agency-global offers), and the content-creation skills
(each job spends metered research/generation budget). **Read-only** skills (client-snapshot,
team-status, audit read views) stay model-invocable so Claude can surface them proactively.

The human-review gate is **never** auto-approved by a skill. A skill MAY draft and MAY call
`POST …/review` **only** to route `edit`/`reject`; an `approve` that pushes to publish is a
deliberate operator action, and the skill MUST surface the QA scorecard and pause for the
lead. This mirrors backend invariant #12 (the QA §11 scorecard is a hard publish gate).

---

## 6. `allowed-tools` scoping

Scope to the **minimum** that lets the skill run without nagging the operator, and no more.
`allowed-tools` grants no-prompt permission for the listed tools while active; it does **not**
restrict the pool (permissions still govern the rest). For a plugin skill it takes effect
only after the workspace-trust dialog — so review before trusting.

- Skills call the backend through the **shared plugin client**, not ad-hoc curl, so the call
  is consistent and testable:
  `allowed-tools: Bash(python ${CLAUDE_PLUGIN_ROOT}/scripts/aios_client.py:*), Read`.
- Keep the base URL + token in env (`AIOS_BASE_URL`, `AIOS_SKILL_TOKEN`), never hardcoded and
  never echoed. The client never prints the token.
- Read-only skills that only render a view: `Read` (+ the call script). No `Write`, no `Edit`.
- **MCP tools** MUST be fully qualified: `GoogleSheets:append_rows`, not `append_rows`.
- Never grant `Bash(*)` or a broad wildcard. Never grant `Write`/`Edit` unless the skill
  legitimately produces a local file deliverable.

---

## 7. Progressive disclosure & bundling

The context window is a public good. Keep the body lean; push depth to bundled files loaded
only when needed.

- **Body < 500 lines.** Approaching it → split into `reference/`.
- **References one level deep from SKILL.md.** `SKILL.md → reference/qa-rubric.md` ✅.
  Never `SKILL.md → a.md → b.md` (Claude partially reads nested files and gets incomplete
  info).
- **Reference files > 100 lines get a table of contents** at the top so a partial read still
  sees the full scope.
- **The ranking rubric is referenced, never inlined.** Content skills cite
  `reference/CONTENT-DOCTRINE.md` (the 14 QA dimensions, entity coverage, E-E-A-T,
  differentiation angle, frameworks). Audit skills cite the relevant
  `danyals-audit-system/checklists/*.yaml` + agent SOP. One source of truth; skills point at
  it. If a number changes, it changes in the doc (and the backend constant it governs) — not
  copied into 5 skills.
- **Scripts: say run-vs-read.** *"Run `aios_client.py create-job …`"* (execute — the default;
  cheaper, deterministic, no code in context) vs *"See `aios_client.py` for the mapping"*
  (read as reference). Most backend-call scripts are **run**.
- **Bundled scripts solve, don't punt.** Handle the 401/403/404/409/timeout explicitly with a
  clear message; no magic constants (document every timeout/retry). Stdlib only (no install).
- Forward slashes in all paths (works on the Windows dev box and Linux VPS alike).

---

## 8. Grounding, evidence & the human gate (the SEO non-negotiables)

These are MUST rules inherited from `CONTENT-DOCTRINE.md` and the audit "every finding has
evidence" philosophy. They apply to **every** SEO skill:

1. **No invented data. Ever.** A skill states only what the backend returned (source pack +
   fresh 6B context). A missing fact surfaces as the backend's literal `[NEEDS: …]` marker —
   the skill routes it to a human, it does NOT fill it in. No hallucinated metrics, DA/DR
   numbers, traffic, rankings, or citations.
2. **Cite the rubric.** Content skills embed/point to the CONTENT-DOCTRINE sections they
   enforce (E-E-A-T §2, entity coverage §3, extractable answer §4, frameworks §6,
   differentiation angle §7, local anatomy §8, QA §11). Audit skills point to the check IDs.
3. **Ground to real data.** Rankings, SERP teardown, entities, competitor gaps come from the
   backend's research/audit output — never from the model's memory.
4. **Human-review gate is mandatory and explicit.** Every generative skill ends at a human
   checkpoint before anything is published/live. Surface the QA scorecard + the differentiation
   angle + any `[NEEDS:]`; a sub-threshold draft (QA `passed=false`, weighted total < 85, or a
   critical dim below the 70 floor) is **STOP**, not "approve anyway".
5. **E-E-A-T / Experience is the differentiator.** Skills that draft MUST require a first-hand
   Experience/authority block and a grounded differentiation angle (unique data → first-hand
   experience → better format → missed angle). Zero first-hand signal caps QA `eeat_experience`.

---

## 9. The evaluation loop (evaluation-driven, not doc-driven)

Anthropic: **build evaluations BEFORE writing extensive documentation**, and refine with the
Claude-A-authors / Claude-B-uses / observe loop.

1. **Baseline.** Run the target task with **no skill**. Record the exact failures and the
   verbatim rationalizations Claude produces ("the QA score is close enough", "I'll fill the
   NAP myself").
2. **Three evals minimum** per skill: a representative happy path, a degrade path (a dormant
   provider key / a `[NEEDS:]` present), and a boundary/permission path (wrong role → 403,
   sub-threshold QA → STOP). Assert on observable behavior (the pinned output shape, the gate
   held, the endpoint called), not vibes.
3. **Write the minimal skill** that passes the evals and closes each observed rationalization
   with an explicit counter in *Common Pitfalls*.
4. **Test on the models it will run on** (opus for judgement skills; also try sonnet if it may
   fall back). What Opus infers, Sonnet may need spelled out.
5. **Iterate on observed behavior**, not assumptions: if Claude skips the gate, make the gate
   step more prominent / use stronger MUST language / move it earlier. Re-run evals until
   green.
6. **Contract-lock the output shape.** A skill's pinned output MUST match the fields the
   backend actually returns; when a response model changes, the skill's template changes with
   it (same discipline as the backend's `test_contract_lock`).

---

## 10. Platform wiring facts (shared by every skill)

- **Base URL:** all business routes are under **`/api/v1`** (e.g. `POST /api/v1/content/jobs`).
  Health is at root. Env: `AIOS_BASE_URL` (default `http://localhost:8000/api/v1`).
- **Auth:** the P9-1 **skill-token gateway** authenticates an `Authorization: Bearer
  $AIOS_SKILL_TOKEN`. The token maps to a provisioned staff role; the role decides 401/403.
  No public signup.
- **Roles/permissions the skills key off:** `view_reports` (all 6 staff roles — read surface;
  a portal client holds none and is 403'd off the staff namespace), `publish_content`
  (create content jobs), `run_audits` (create audits), `assign_tasks` (create/route tasks),
  `manage_clients`, `manage_upsells`, and **LEAD** = owner/admin/manager (review gates,
  off-page approvals, report sync).
- **State machines live at the DB, not the skill.** Content = `queued→drafting→needs_review→
  publishing→done` with ONE human gate (invariant #12); tasks = `todo→in_progress→[review]→
  done` (invariant, Part 5). A skill drives the *legal* transition via the endpoint and lets
  the DB trigger enforce the rest. A skill NEVER tries to force an illegal jump.
- **Provider keys are gated dormant→live.** Serper/Anthropic (content research + generation +
  the AI QA judge), Google (reports/Sheets), Voyage/Pinecone (context). When a key is dormant
  the route degrades to a deterministic fake/no-op and never crashes — the skill MUST report
  the degrade honestly ("research ran on the deterministic fake; live SERP pending Serper
  key") and NOT present fake output as live.
- **Cost is gated.** Paid calls run the money-dial → cache → client cap → daily spend-stop. A
  spend block **degrades** (holds the job, honest $0) — the skill surfaces the hold, it does
  not retry-loop to force spend.

---

## 11. Reviewer checklist (a skill is not done until all pass)

Core quality
- [ ] `name` == folder; frontmatter valid; no angle brackets.
- [ ] Description is third-person, states WHEN (not a workflow summary), packs trigger keywords, names any side effect.
- [ ] Body < 500 lines; references one level deep; long refs have a TOC.
- [ ] SOP shape present in order: Purpose · Who runs it · Inputs/keys · Trigger · numbered testable steps · explicit `If X → Y` · Common Pitfalls · pinned output.
- [ ] Every step names its endpoint (`/api/v1/...`) and its input; ≥4 steps use a checklist block.

Discipline / SEO
- [ ] `model` set (opus for judgement); `disable-model-invocation` decided per §5 and logged in INVENTORY.
- [ ] `allowed-tools` is the minimum; no `Bash(*)`; no stray `Write`/`Edit`.
- [ ] Cites the rubric (CONTENT-DOCTRINE section / checklist IDs) instead of inlining it.
- [ ] Grounding rule stated: no invented data; `[NEEDS:]` routed to a human.
- [ ] Human-review gate explicit; sub-threshold QA = STOP; approve is never auto.
- [ ] Degrade behavior stated for every dormant-key path.

Testing
- [ ] ≥3 evals (happy / degrade / boundary); baseline recorded; rationalizations countered in Common Pitfalls.
- [ ] Output template matches the endpoint's real response fields.
- [ ] Tested on the model(s) it runs on.

---

*This standard is the source of truth for skill shape. The `/local-service-page` skill is the
fully-worked reference implementation that conforms to it — copy that skill, don't start from
scratch.*
