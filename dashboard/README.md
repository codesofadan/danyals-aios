# AIOS Local Control Dashboard

A thin **local** dashboard that runs visually in your browser but sends **every request
through Claude Code driving the skills** - never a direct browser-to-API call, and the
API bearer token never reaches the browser.

```
  browser (index.html)        bridge.py                 worker.py                 aios_client.py            AIOS API
  ------------------- POST -> ----------- /api/pending ->----------- subprocess ->--------------- HTTPS -> ----------
  clicks an "intent"          in-memory queue           Claude Code drives it     the ONE skills client    app.qanry.com
  127.0.0.1 only, no token    127.0.0.1 only, no token  holds the token (env)     (per AUTHORING-STANDARD)
  <----------------- result --<----------- /api/fulfill --<---------- JSON -------<--------------- JSON --<----------
```

## Why three pieces (the design)

The brief: a local UI whose actions are **fulfilled by Claude Code driving the
skills/API**, not by the browser hitting the API. So the responsibilities are split so
that the only component allowed to touch the API is the one Claude Code runs:

| Component | Holds the token? | Calls the API? | Role |
|---|---|---|---|
| `index.html` (browser) | **no** | **no** | Emits *intents* ("show the content board", "run a Free audit"), renders JSON. Talks only to the bridge. |
| `bridge.py` | **no** | **no** | A powerless local broker: parks intents on an in-memory queue, hands results back. Bound to `127.0.0.1`. Enforces the human-confirm gate for write/spend intents. |
| `worker.py` | **yes** (from env) | **yes**, via the skills | The executor **Claude Code drives**. Pulls pending intents, maps each to an `aios_client.py` invocation (the exact skills path), posts the result back. |

Because the worker fulfils actions by shelling out to
`.claude/skills/_shared/aios_client.py`, the dashboard and the slash-command skills go
down the **same** path to the backend - one contract, one auth, one place drift can be
caught. Claude Code can sit in the loop: it runs the worker, can inspect a pending write
before letting it through, and applies the same discipline the skills do (e.g. hold a
sub-threshold content draft at the review gate rather than auto-publishing).

## Run it

Two shells. Set the same env the skills use (never commit the token):

```bash
export AIOS_BASE_URL="https://app.qanry.com/api/v1"   # or your backend
export AIOS_SKILL_TOKEN="<your skill/owner bearer>"    # AIOS_TOKEN also accepted
```

```bash
# shell 1 - the broker + UI (no token needed here)
python dashboard/bridge.py           # http://127.0.0.1:8787

# shell 2 - the executor Claude Code drives (token comes from env)
python dashboard/worker.py           # drains the bridge continuously
#   or: python dashboard/worker.py --once   to drain once and exit
```

Open <http://127.0.0.1:8787>. The header shows **bridge up** and **worker idle/ready**
when both are live. Click a module action; the activity log shows
`browser -> bridge -> worker -> skills` and the panel renders the live result.

> **Claude-in-the-loop mode.** Instead of a long-running `worker.py`, Claude Code can
> drain the queue itself: `GET /api/pending` to see clicked intents, run the mapped
> skill, `POST /api/fulfill`. `worker.py --once` is exactly that loop, one pass - so a
> Claude Code `/loop` over it *is* Claude Code fulfilling the dashboard.

## What you can do

- **Reads (auto-fulfilled through the skills):** Command Center, content board + KPIs,
  audit board + KPIs, off-page KPIs, policy change-events + recommendations, team record
  + task queue, milestones, clients, onboarding, reports connection, and every Part-8
  tool-module KPI. These map to `aios_client.py get <path>`.
- **Writes / spends (human-confirm gated):** the **Run a Free audit** form on the Audits
  tab. Submitting a write returns `needs_confirm`; the UI shows a confirm bar; only on the
  click does the worker run `aios_client.py post audits`. Free + `[onpage,technical]` = zero
  paid spend; paid types (`offpage,local,geo,strategy`) require the Paid tier and are
  rejected 400 on Free (surfaced verbatim). The confirm gate mirrors the skills' rule that
  money/publish is never auto-fired.

## Intents

The browser sends `{intent, args}`. The intent->skill mapping lives in `worker.py`
(`_intent_argv`). Read intents are on an allow-list in `bridge.py` (`READ_INTENTS`);
anything else is treated as a write and must carry `confirm:true`. Two escape hatches
(`raw.get {path}`, `raw.post {path, body}`) let the UI reach any endpoint the modules add
without editing the worker - `raw.post` is still confirm-gated.

## Safety

- Both servers bind `127.0.0.1` only; no outbound network except the worker's calls to
  the AIOS API via the skills client.
- The token is read from the environment by the worker and set only as an
  `Authorization` header inside `aios_client.py`; it is never logged, never sent to the
  browser, never written to disk.
- The bridge state is in-memory and ephemeral - stop it and nothing persists.
- Stdlib only (`http.server`, `urllib`, `subprocess`); nothing to `pip install`.
