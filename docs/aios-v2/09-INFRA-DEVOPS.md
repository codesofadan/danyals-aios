# 09 · Infrastructure and DevOps

One VPS. One environment. Everything below is shaped by that constraint and by the fact
that there is no second host to make mistakes on.

---

## 1. Topology

```
  VPS (single host)
  ├─ caddy          TLS, HTTP/3, compression, static, rate limiting
  ├─ web            Next.js (standalone output)                    ×1
  ├─ api            FastAPI / uvicorn                              ×2
  ├─ job-worker     durable job engine consumers                   ×3
  ├─ browser-worker Playwright + Chromium                          ×2   (separable)
  ├─ scheduler      enqueues scheduled jobs                        ×1   (leader-locked)
  ├─ postgres       PostgreSQL 16 + pgvector                       ×1
  ├─ redis          cache / locks / rate-limit tokens              ×1
  └─ langsmith      self-hosted tracing (optional profile)
```

**Sizing:** start at 8 vCPU / 32 GB / 400 GB NVMe. Chromium is the memory consumer; each
browser worker is budgeted at 2 GB. The documented upgrade trigger is sustained CPU > 70%
for an hour, or p95 job pickup latency > 10 s, or Postgres cache-hit ratio < 0.98.

**Separability:** `browser-worker` is addressed by configuration. Moving it to a second
host must require only an env change and a firewall rule — never a code change. This is
enforced by the fact that browser workers claim jobs over the database, not over a local
socket.

---

## 2. Containers

- `docker compose` is the deployment unit. No orchestrator.
- Every image is multi-stage, runs as non-root, and pins its base by digest.
- Profiles: `default` (everything), `minimal` (api + db + redis, for a fast local loop),
  `staging` (the full stack on ephemeral ports and a scratch database — this is how a
  change is exercised end to end without a second host).
- Health checks on every service; `depends_on: condition: service_healthy` so startup order
  is real, not hopeful.
- Resource limits declared per service. An unbounded Chromium will take the host down.

**`docker compose up` from a clean clone must produce a working, seeded system.** If it
does not, that is a P0 bug — it is the only thing standing in for a staging environment.

---

## 3. Configuration

- One typed settings object (`pydantic-settings`), loaded from the environment. No module
  reads `os.environ` directly.
- `.env.example` lists every variable with a comment and a safe default. Committed.
- `.env` is never committed. Production values live on the host, root-readable only.
- **Startup validates configuration and refuses to start on a contradiction** — for
  example, `LANGSMITH_HOSTED=true` without an acknowledgement flag, or a browser-worker
  address that does not resolve.
- Missing optional provider keys do **not** prevent startup. They mark the capability
  `unconfigured` in the truth table, and every dependent path degrades honestly.

---

## 4. Deployment

```
  PR merged to main
    └─ CI: seven gates
         └─ build images, tag with the commit sha
              └─ push to registry
                   └─ deploy: pull, migrate, rolling restart, verify
```

**Rules:**
1. **Images are tagged by commit sha.** `latest` is never deployed. Rollback is deploying
   the previous sha — no database step required, which is why migrations must be
   backward-compatible (`04-DATA-MODEL.md` §5).
2. **Migrations run before the new image serves traffic**, as a separate one-shot
   container, and the deploy aborts if they fail.
3. **Rolling restart** of `api` replicas so the API does not drop; workers finish their
   current lease before exiting (graceful shutdown with a lease release).
4. **Post-deploy verification** is automated: health, readiness, a smoke request against
   each module's primary read endpoint, and a capability-truth-table diff. A regression in
   the truth table fails the deploy and triggers rollback.
5. **Every deploy is announced** to the activity log with the sha, the migration list and
   who triggered it.

---

## 5. Backups and disaster recovery

| What | How | Frequency | Retention |
|---|---|---|---|
| Postgres | `pg_dump` custom format + WAL archiving | Full nightly, WAL continuous | 30 daily, 12 weekly, 12 monthly |
| Artefacts (screenshots, PDFs, captures) | Object-store sync | Nightly | 90 days |
| Vault KEK | **Offline**, in a password manager and a sealed envelope | On rotation | Forever |
| Configuration | In the repo (`.env.example`) + host `.env` backed up encrypted | On change | 90 days |

- Backups are **encrypted with a key that is not on the VPS**, and shipped off-host.
- **Targets: RPO 1 hour, RTO 4 hours.**
- **A restore drill is mandatory before hand-over** and quarterly after: restore into a
  clean host, run the data-integrity check, record the elapsed time. An untested backup is
  not a backup.
- A restore procedure runbook lives in `docs/runbooks/restore.md` and is written so
  someone who is not the author can follow it at 3am.

---

## 6. Observability

| Signal | Tool | What it answers |
|---|---|---|
| Errors | Sentry (backend, frontend, extension) | What broke, for whom, in which release |
| Traces | OpenTelemetry → the collector | Where the time went across request → job → provider |
| AI traces | LangSmith | What the model saw, what it returned, what it cost |
| Logs | Structured JSON → the host's log driver, shipped | What happened, with a correlation id |
| Metrics | Prometheus-format endpoint → a lightweight scraper | Rates, saturation, queue depth, spend |
| Uptime | External monitor against `/ready` | Is it up, from outside |

**Dashboards that must exist:**
job queue depth and age · job outcomes by terminal state · spend by module and client
against caps · provider error rates and latency · cache-hit rate per AI module · publish
and submission success rates · capability truth table.

**Alerts that page:** see [`07-SECURITY.md`](07-SECURITY.md) §9, plus: queue age > 15 min,
dead-letter rate above baseline, disk > 80%, backup failure, certificate expiry < 14 days.

---

## 7. Runbooks

Each is a numbered procedure in `docs/runbooks/`, written to be followed under pressure.

`restore.md` · `rotate-credential.md` · `provider-outage.md` · `stuck-job.md` ·
`dead-letter-triage.md` · `spend-spike.md` · `wordpress-publish-failure.md` ·
`platform-account-suspended.md` · `rollback-deploy.md` · `client-offboarding.md` ·
`scale-up-vps.md`

---

## 8. Scheduling

Recurring work is rows in `schedules`, executed by a leader-locked scheduler that enqueues
ordinary jobs — so scheduled work inherits idempotency, retry and dead-lettering.

**Schedules ship disabled.** A schedule is enabled only after its job kind has passed the
chaos suite. This is the deliberate inverse of v1, where the schedule was disabled *because*
the job contract was unsafe and nobody could tell which was which.

Initial schedule set, in the order they are expected to be enabled:

| Schedule | Cadence | Enabled after |
|---|---|---|
| OAuth token refresh | hourly | M05 job contract proven |
| Policy source sweep | daily 06:00 | M06 proven |
| Daily policy brief | daily 07:00 | above |
| Citation liveness re-check | daily | M04 proven |
| Web 2.0 link liveness | daily | M05 proven |
| Rank tracking run | weekly per client | M07 proven |
| Geo-grid sweep | weekly per client | M07 proven |
| Monthly client reports | monthly, staggered | M11 proven |
| Job/artefact retention sweep | nightly | always safe |
| Backup verification | nightly | always safe |

---

## 9. Local development

```
git clone … && cd aios
cp .env.example .env
make dev            # compose up, migrate, seed, open http://localhost:3000
make gates          # everything CI runs, locally
make eval           # AI eval suite against fixtures
make chaos          # kill-the-worker suite
```

Requirements: Docker, `uv`, Node 22+, `pnpm`. Nothing else. A developer must not need a
production credential to work on any module — every provider has a fake and a fixture set.

---

## 10. Cost of operation

Tracked as a first-class number, because it decides tier pricing.

| Line | Driver | Control |
|---|---|---|
| VPS | Fixed | Sized to a documented upgrade trigger |
| Anthropic tokens | Content volume, audit depth | Prompt caching, task tiering, Batch API for bulk work, per-module dials |
| DataForSEO | Keyword volumes, organic rank checks | Tier-based keyword allowances |
| serper.dev | Local pack and grid points | Grid size and cadence per tier. **Note: the free tier is 2,500 searches/month in total, not per client — this must be a paid plan before launch** |
| Firecrawl / rendering | Design capture, audit crawl | Page caps per audit type |
| CAPTCHA solving | Citation volume | Per-solve accounting; human fallback |
| Proxies | Citation and liveness traffic | Bandwidth accounting per client |
| Image generation | Pages and posts | Per-image cost line, reuse where valid |
| Sentry / LangSmith | Volume | Self-host LangSmith; sample Sentry traces |

Every one of these is metered into the cost ledger with a `client_id`, so "what does this
client cost us" is a query, not an estimate.
