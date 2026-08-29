# AIOS - VPS deployment (native, systemd, NO Docker)

The whole platform runs natively on a single Ubuntu 22.04+ / Debian VPS - **no
Docker, no Supabase, no managed cloud**. Everything (database, cache, API,
workers, dashboard, TLS) lives on the box, in the agency's own accounts: **no
lock-in.** To move providers you copy one directory and one env file.

```
                       app.example.com --> 127.0.0.1:3000  aios-web    (Next.js dashboard)
Internet --443--> Caddy                                        |
                  (auto-TLS)                                   | /api/v1/* proxied
                                                               v  in-process
                       api.example.com --> 127.0.0.1:8000  aios-api    (uvicorn, FastAPI)
                                                            aios-worker (celery worker)
                                                            aios-beat   (celery beat)
                                       127.0.0.1:5432       PostgreSQL 16  (loopback-only)
                                       127.0.0.1:6379       Redis          (loopback-only)
```

> **This used to be an API with no user interface.** `install.sh` provisioned three
> units and the `Caddyfile` published one host, so following this document to the
> letter produced a working backend and nothing to log in to. `aios-web` and the
> dashboard Caddy block are that missing half. If you are upgrading an existing box,
> a `git pull` + re-run of `install.sh` adds them.

- **PostgreSQL 16** (native, loopback) is the data plane: identity, RBAC, the
  encrypted vault, cost ledger, tasks, context. Row-Level Security is the tenant
  boundary, reached through two DSNs - `authenticated` (RLS applies) and
  `service_role` (BYPASSRLS, server-only).
- **Redis** (native, loopback) is cache + Celery broker/results on **separate
  logical DBs** (`/0` cache, `/1` broker, `/2` results) so a cache `FLUSHDB` can
  never wipe queued jobs.
- **aios-api / aios-worker / aios-beat / aios-web** are four systemd units, run as
  the unprivileged `aios` user, all reading one root-owned env file.
- **aios-web** is the Next.js dashboard (`next start`, loopback `127.0.0.1:3000`).
  The browser talks to **one** origin: the dashboard proxies `/api/v1/*` to the API
  in-process, so there is no CORS and the app's own CSP (`connect-src 'self'`)
  stays true. It deliberately does **not** `Requires=aios-api` - a backend outage
  should surface as the app's own "backend unavailable" banner, not as a browser
  connection error on a dashboard that refused to start.
- **Caddy** terminates TLS and reverse-proxies to both loopback servers. It is the
  only network-facing process.

## First install

```bash
# 1. clone the repo to the deploy root
sudo git clone <repo-url> /opt/aios

# 2. run the provisioner. On the FIRST run it installs PostgreSQL 16 + Redis,
#    seeds /etc/aios/aios.env from the template, and STOPS so you can fill it in.
sudo bash /opt/aios/infra/deploy/install.sh

# 3. edit the secrets (APP_ENV=prod, the two DATABASE_* DSNs, the EdDSA keypair,
#    VAULT_MASTER_KEY, SEED_OWNER_*, real hosts). Comments + generators are inline.
sudo nano /etc/aios/aios.env

# 4. run it again - now it provisions the DB, applies migrations, runs the RLS
#    gate, builds the venv, seeds the owner, BUILDS THE DASHBOARD, and starts the
#    four services.
sudo bash /opt/aios/infra/deploy/install.sh
```

The dashboard build (`npm ci` + `npm run build`) installs Node 22 from NodeSource
first if the box has no Node >= 20 - Ubuntu's own package is far too old for Next
15. If that build fails, the backend is still restarted, `aios-web` is **not**
started, and the script **exits non-zero** naming the cause: an API with no
dashboard is not a successful install, so it does not report itself as one.

`install.sh` is **idempotent** - re-run it any time (it tracks applied migrations
in a `deploy.schema_migrations` ledger and only starts/restarts what changed).

What it does, in order: installs **PostgreSQL 16** (via the PGDG apt repo) +
**Redis**; creates the `aios` database and sets the `anon` / `authenticated` /
`service_role` role passwords from the DSNs (service_role is `BYPASSRLS`); applies
`db/migrations/0000..0028` **in order** as the `postgres` superuser; runs the
**RLS coverage gate** (`app.db.rls_check` - the install FAILS if any `public`
table lacks forced RLS); builds the venv with an editable `pip install -e .`;
provisions the seed **owner** (idempotent); builds the **dashboard**; installs the
four systemd units and starts them.

> In **prod** the API fails fast at boot if a required secret is missing
> (`validate_settings`): `database_url`, `database_admin_url`, `jwt_private_key`,
> `jwt_public_key`, `vault_master_key`. `GET /health/ready` returns 200 only when
> **Postgres and Redis** are both reachable.

## Config - one root-owned env file

All config lives in **`/etc/aios/aios.env`** (0600 root:root). systemd loads it as
`EnvironmentFile` for all four units; the app reads it from the process
environment. See `aios.env.example` for the annotated template.

The template documents ~100 of the code's ~220 settings, and the ~120 it omits are
omitted on a stated rule: **a setting is in the template if leaving it out degrades
the platform silently.** Required secrets fail fast at boot, key-gated modules
announce themselves as `degraded` / "not configured", and tuning knobs have correct
defaults - none of those need a template entry to be discoverable. The ones that
keep returning 200s while producing a wrong answer do, and they are collected under
*SETTINGS WHOSE ABSENCE DEGRADES SILENTLY* at the bottom of the file, each with the
specific failure you get by skipping it.

> **Frontend settings are BUILD-TIME.** `BACKEND_ORIGIN` and every `NEXT_PUBLIC_*`
> are baked into the bundle by `npm run build` (install.sh exports them for it).
> Editing one in `aios.env` and running `systemctl restart aios-web` changes
> **nothing**, silently - re-run `install.sh` instead.

> **Footgun:** systemd's `EnvironmentFile` does **not** strip a trailing inline
> `# comment` from a value line. So every comment in `aios.env` must sit on its own
> line, never after a value. The template already follows this - keep it that way.

Optional provider keys (audit engine, context AI, content, off-page, reports,
email/Slack, Backblaze offsite) are all **deferred**: each module ships on
deterministic fakes and lights up when its key lands. A keyless deploy degrades
gracefully; it never crashes. After adding the context keys, also install the AI
SDKs on the box: `sudo -u aios /opt/aios/backend/.venv/bin/pip install -e '.[ai]'`.

## TLS - Caddy reverse proxy

See **`infra/deploy/Caddyfile`** for the annotated snippet (install commands +
security headers). It publishes **two** hosts - the dashboard and the API. Copy it
to `/etc/caddy/Caddyfile`, set both real hostnames (both DNS records must already
point here), then `sudo systemctl reload caddy`. Caddy auto-obtains and auto-renews
the certificates.

Keep `TRUSTED_HOSTS`, `API_CORS_ORIGINS`, `ADMIN_BASE_URL` and
`PUBLIC_FILE_BASE_URL` in `aios.env` matched to the real hostnames.

> **`TRUSTED_HOSTS` must keep `127.0.0.1` in the list.** The dashboard's rewrite
> proxy runs with `changeOrigin: true`, so a call it forwards reaches uvicorn as
> `Host: 127.0.0.1:8000`, not as your API hostname - and Starlette's
> `TrustedHostMiddleware` compares the Host header with the port stripped. Drop the
> loopback entry and every dashboard request becomes a `400` while the pages
> themselves keep loading perfectly, which is what makes it expensive to diagnose.

## Deploying an update

```bash
cd /opt/aios && sudo git pull
sudo bash infra/deploy/install.sh     # re-applies new migrations, re-installs deps
                                      # + units, and restarts the three services
```

Because the install is **editable** and the migration ledger skips applied files,
a pull + re-run is the whole update. The dashboard is **not** editable in that
sense - it is a compiled bundle, so the re-run's `npm ci` + `npm run build` is what
picks up frontend changes (and any change to `BACKEND_ORIGIN` / `NEXT_PUBLIC_*`). The worker does a **warm shutdown** on restart
(waits for in-flight tasks up to `TimeoutStopSec=1800`); `task_acks_late` +
`visibility_timeout >= task_time_limit` make any task that is still killed safe to
redeliver - a sequential re-run, never a concurrent double-run.

## Operating

```bash
systemctl status aios-api aios-worker aios-beat aios-web postgresql redis-server
journalctl -u aios-api -f            # API logs (structlog JSON in prod)
journalctl -u aios-worker -f         # worker logs
journalctl -u aios-beat -f           # beat (schedule dispatcher) logs
journalctl -u aios-web -f            # dashboard (Next.js server) logs
curl -sf http://127.0.0.1:8000/health && echo             # liveness
curl -s  http://127.0.0.1:8000/health/ready | python3 -m json.tool   # readiness
curl -sfI http://127.0.0.1:3000/login | head -1           # dashboard serving
```

`aios-web` logs one warning at every start - *"next start" does not work with
"output: standalone"*. It is expected and harmless: `next.config.mjs` sets
`output: "standalone"` for the **Docker** image, and `next start` serves the normal
build tree correctly regardless. The standalone bundle is deliberately not used
here because it omits `.next/static` and `public/`, which have to be copied in by
hand - and a deploy that forgets that copy serves a page with no CSS or JS.

Smoke-test the worker round-trip (broker + worker) from the venv:

```bash
sudo -u aios /opt/aios/backend/.venv/bin/python - <<'PY'
from workers.tasks.ping import ping
print(ping.delay().get(timeout=10))   # -> "pong"
PY
```

## Services

| Unit | Command | Notes |
|---|---|---|
| `postgresql` | (distro / PGDG) | data plane; loopback `127.0.0.1:5432`; RLS boundary |
| `redis-server` | (distro package) | cache `/0` + broker `/1` + results `/2`; loopback |
| `aios-api` | `uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 2` | behind Caddy; liveness independent of Redis |
| `aios-worker` | `celery -A workers.celery_app worker --concurrency=4` | warm shutdown; acks_late-safe redelivery; writes artifacts to `/var/lib/aios` |
| `aios-beat` | `celery -A workers.celery_app beat` | **exactly one** cluster-wide; enqueues the context dispatch + reconcile schedules (and future policy/report/backup schedules) |
| `aios-web` | `next start -H 127.0.0.1 -p $AIOS_WEB_PORT` | the dashboard; behind Caddy; proxies `/api/v1/*` to the API same-origin; not bound to `aios-api` |

All four app units are hardened (`NoNewPrivileges`, `ProtectSystem=strict`,
`ProtectHome`, `PrivateTmp`, ...) and run as `aios`, never root. `aios-web`'s only
writable path is `frontend/.next/cache` (Next's incremental cache) - note that
systemd **refuses to start** a unit whose `ReadWritePaths` entry does not exist, so
`install.sh` creates it. The worker + beat get a writable
`StateDirectory=/var/lib/aios` for the beat schedule and the
audit/content/backup artifacts - keep those artifact dirs under `/var/lib/aios`
(as the template does) so `ProtectSystem=strict` still covers them.

## Backup & restore

Postgres is the source of truth (Google Sheets holds client-facing operational
records; Pinecone is a fully-rebuildable derived index). The **Backups module**
(owner/admin) drives `pg_dump` snapshots and a doubly-guarded `pg_restore`:

```bash
# run a manual snapshot now (owner/admin token):
curl -sf -X POST http://127.0.0.1:8000/api/v1/backups/run \
  -H "Authorization: Bearer $TOKEN" -H 'content-type: application/json' \
  -d '{"type":"manual","scope":"full"}'

# restore is OWNER-ONLY and doubly guarded (the body must echo the snapshot id):
curl -sf -X POST http://127.0.0.1:8000/api/v1/backups/<snapshot_id>/restore \
  -H "Authorization: Bearer $TOKEN" -H 'content-type: application/json' \
  -d '{"confirm":"<snapshot_id>"}'
```

Snapshots land under `BACKUP_ARTIFACT_DIR` (default `/var/lib/aios/backups`); set
the Backblaze **B2** triple in `aios.env` for an automatic S3-compatible offsite
copy (the local snapshot still succeeds if offsite is unconfigured). A raw manual
snapshot without the app is always available too:

```bash
sudo -u postgres pg_dump -Fc aios > /var/lib/aios/backups/aios-$(date +%F).dump
# restore:  sudo -u postgres pg_restore --clean --if-exists -d aios <file>.dump
```

## No lock-in

Everything runs on infrastructure the agency owns: the VPS, the Postgres cluster,
the Redis instance, the domain, and (as they land) the agency's own provider
accounts (Anthropic, Voyage, Pinecone, Serper, Google, DataForSEO, BrightLocal,
Resend, Backblaze). There is no proprietary managed backend to be captive to -
migrating hosts is a `git clone`, an `aios.env` copy, a database `pg_restore`, and
one `install.sh` run.
