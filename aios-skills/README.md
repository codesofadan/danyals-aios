# aios-seo — the Danyal AIOS SEO skills plugin

Expert SEO **operator skills** you run locally in Claude Code. Each slash command drives the
Danyal AIOS FastAPI backend to produce **ranking-grade, grounded** content behind the backend's
14-dimension QA gate and its human review gate. The skills are a thin, disciplined operator
layer: they gather inputs, call the right endpoints in the right order, enforce the review
gate, and return a pinned deliverable. **They never invent data and never re-implement backend
logic.**

> The two AI surfaces of the platform, and where these skills sit:
> - **Local Claude Code skills (this plugin).** Slash commands (`/content`, …) that call the
>   backend from your machine. This is what you install below.
> - **The web dashboard (Anthropic-API).** A separate hosted product; not these skills.
>
> These skills run in **Claude Code (web or CLI)**. They do **not** run in claude.ai chat.

---

## What's in the box

```
aios-skills/
├── .claude-plugin/plugin.json    # plugin manifest (name: aios-seo)
├── AUTHORING-STANDARD.md         # the committed standard every SKILL.md follows
├── README.md                     # this runbook
├── scripts/
│   └── aios_client.py            # the ONE shared backend client every skill calls (stdlib only)
├── reference/
│   ├── CONTENT-DOCTRINE.md       # the ranking rubric (mirror of backend/docs; skills cite it)
│   └── output-formats.md         # the exact backend response fields the skills read
└── skills/
    ├── content/SKILL.md          # /content    - the content module hub
    ├── local-service-page/SKILL.md  # /local-service-page - city+service page (reference impl)
    ├── blog-post/SKILL.md        # /blog-post   - informational blog
    └── titles-meta/SKILL.md      # /titles-meta - bulk titles + meta descriptions
```

The current release ships the **Content** module. Audit, off-page, policy, and report modules
(see the inventory) follow the same standard and land in later releases.

---

## Install (local Claude Code)

You need Python 3 (stdlib only — nothing to `pip install`) and network access to your AIOS
backend.

1. **Get the plugin onto your machine.** Clone or copy this repo; the plugin lives at
   `aios-skills/`.

2. **Install the plugin in Claude Code.** Add this plugin directory as a plugin. In an
   interactive Claude Code session:
   - run `/plugin` and add a local plugin pointing at the `aios-skills/` directory, or
   - add it to your Claude Code settings' plugin list (a marketplace/local entry pointing at
     `aios-skills/`).
   Claude Code reads `.claude-plugin/plugin.json` and registers the `skills/*` as slash
   commands. Restart the session if the commands don't appear.

3. **Trust the workspace.** `allowed-tools` in each skill (the shared client + `Read`) takes
   effect only after you accept the workspace-trust dialog. Review the skills first, then
   trust.

4. **Set the two environment variables** (below). Skills read them at call time.

5. **Verify.** In Claude Code run `/content` — it should reach the backend and print the
   content board, or a clear auth/connection error if the env vars are wrong.

---

## Configure — the skill token + base URL

The skills authenticate to the backend through the **skill-token gateway** using a bearer
token. Set two environment variables in the shell/session that runs Claude Code:

| Variable | Required | Meaning | Default |
|---|---|---|---|
| `AIOS_SKILL_TOKEN` | **yes** | Your skill bearer token (issued by the gateway). Maps to your staff role, which decides what you can do (a client 403s off the staff surface). | — |
| `AIOS_BASE_URL` | no | The API base URL, ending in `/api/v1`. | `http://localhost:8000/api/v1` |

Backward-compatible fallbacks the client also accepts: `AIOS_TOKEN` (for the token) and
`AIOS_API_BASE` (for the base URL). Prefer the `SKILL`/`BASE_URL` names.

**Set them (do not commit the token anywhere):**

```bash
# macOS / Linux / Git Bash
export AIOS_SKILL_TOKEN="paste-your-skill-token"
export AIOS_BASE_URL="https://aios.yourdomain.com/api/v1"   # omit to use localhost:8000
```

```powershell
# Windows PowerShell
$env:AIOS_SKILL_TOKEN = "paste-your-skill-token"
$env:AIOS_BASE_URL   = "https://aios.yourdomain.com/api/v1"
```

The token is only ever sent as an `Authorization: Bearer` header. The shared client
**never prints or logs it**, and no skill body ever contains it. Treat it like a password;
rotate it via the gateway if it leaks.

---

## Usage

Run a skill by typing its slash command in Claude Code. Multi-word arguments must be quoted.

| Command | What it does | Side effects |
|---|---|---|
| `/content` | The content module hub — create any content job (service/blog/local), read the board + stats, run the review gate. Routes you to the deep skill for the page type. | Creating a job spends metered AI budget. |
| `/local-service-page acme "San Jose" "AC repair"` | A ranking-grade **local** page (city + service) grounded in fresh client context, QA-gated. | Spends AI budget; creates a content job. |
| `/blog-post acme "how tankless water heaters save money"` | A ranking-grade **informational blog** (entity coverage + extractable answer + FAQ). | Spends AI budget; creates a content job. |
| `/titles-meta acme "AC repair San Jose"` | Titles + meta descriptions to spec (title ≤ ~60, meta ≤ ~155, primary front-loaded, grounded). | Spends AI budget; creates a content job. |

**Every content skill ends at the human review gate.** It surfaces the QA scorecard (the 14
dimensions, `weighted_total`, `passed`, `blocked_by`) and any `[NEEDS:]` markers, then STOPS.
A draft with `passed=false` (weighted total < 85, or any critical dimension < 70) is **not**
approved — you send it back to `edit` or supply the missing fact. Approval is a deliberate
LEAD action (owner/admin/manager); the backend re-checks the gate on approve and refuses a
sub-threshold draft (invariant #12).

### Direct client use (for debugging / scripting)

The skills call `scripts/aios_client.py`; you can run it yourself:

```bash
python aios-skills/scripts/aios_client.py stats                    # content board KPIs
python aios-skills/scripts/aios_client.py list-jobs --status needs_review
python aios-skills/scripts/aios_client.py resolve-client --client "Acme HVAC"
python aios-skills/scripts/aios_client.py fetch-job --code CJ-1042  # qa+draft+schema+keywords
python aios-skills/scripts/aios_client.py get content/jobs/stats    # any /api/v1 GET (see note)
```

Exit codes: `0` ok · `2` HTTP error (401/403/404/409 → readable reason) · `3` cannot reach the
API · `4` wait timed out · `5` usage/local error. Every response prints as JSON.

> **Git Bash path note.** For the raw `get`/`post` escape hatch, pass the path **without a
> leading slash** (`content/jobs/stats`, not `/content/jobs/stats`) — Git Bash on Windows
> rewrites a leading-slash argument into a Windows path. The client adds the `/api/v1` base and
> the leading slash for you. The named subcommands (`stats`, `create-job`, …) are unaffected.

---

## Grounding, degrade, and the guardrails (why the output is trustworthy)

- **No invented data, ever.** A skill reports only what the backend returned. A missing fact is
  the backend's literal `[NEEDS: …]` marker — the skill routes it to you, it does not fill it
  in. No hallucinated metrics, DA/DR, traffic, rankings, or citations.
- **The rubric is the source of truth.** Content skills cite `reference/CONTENT-DOCTRINE.md`
  (a mirror of `backend/docs/CONTENT-DOCTRINE.md`) — the 14 QA dimensions, E-E-A-T, entity
  coverage, differentiation angle, local anatomy. See `reference/output-formats.md` for the
  exact response fields.
- **Degrade is reported honestly.** When a provider key (Serper/Anthropic for research +
  generation + the QA judge) is dormant, the backend runs a deterministic fake and the skill
  labels the result "degraded" — it never presents fake output as live.
- **Spend is gated.** Paid steps run the money-dial → cache → client cap → daily spend-stop. A
  spend block holds the job at honest $0; the skill surfaces the hold and does not retry to
  force spend.

---

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `no token: set AIOS_SKILL_TOKEN` | The env var is unset in this session. Export it (above) and re-run. |
| `unauthenticated (check AIOS_SKILL_TOKEN)` (401) | Token missing/expired/wrong. Reissue via the gateway. |
| `forbidden (the token's role lacks the required permission)` (403) | Your role can't do this action (e.g. creating a job needs `publish_content`; approving needs LEAD). |
| `cannot reach the API at …` (exit 3) | `AIOS_BASE_URL` wrong or backend down. Confirm the URL ends in `/api/v1` and the server is up. |
| Slash command not listed | Plugin not registered / workspace not trusted. Re-add via `/plugin`, restart, accept the trust dialog. |
| A job sits in `drafting` at $0 cost | A spend-stop/cap held the paid step. Expected degrade — check budgets; do not spam re-create. |

---

## For skill authors

Read `AUTHORING-STANDARD.md` first, then copy `skills/local-service-page/SKILL.md` (the
fully-worked reference) — do not start a new skill from scratch. Every skill: third-person
WHEN-to-use description, verb-first numbered SOP steps naming their `/api/v1` endpoint +
inputs, explicit `If X → Y` gates, Common Pitfalls, and a pinned output whose fields match the
backend's real response (`reference/output-formats.md`).
