# AIOS backend - VPS deployment (systemd, no Docker)

The backend runs natively on a single Debian/Ubuntu VPS (Hetzner) as two systemd
services - the FastAPI API and the Celery worker - in front of a native Redis.
Caddy terminates TLS and reverse-proxies public traffic to the API on localhost.

```
Internet --443--> Caddy (auto-TLS) --> 127.0.0.1:8000  aios-api    (uvicorn)
                                                        aios-worker (celery)  --> Redis (127.0.0.1:6379)
                                                        Supabase (managed, over HTTPS)
```

Redis logical DBs (one native instance): app cache `/0`, Celery broker `/1`,
results `/2` - so a cache `FLUSHDB` can never wipe queued jobs.

## First install

```bash
# 1. clone the repo to the deploy root
sudo git clone <repo-url> /opt/aios

# 2. configure secrets (12-factor; never commit this file)
sudo cp /opt/aios/backend/.env.example /opt/aios/backend/.env
sudo nano /opt/aios/backend/.env         # set APP_ENV=prod, Supabase keys, etc.

# 3. provision Redis + venv + systemd units (idempotent)
sudo bash /opt/aios/infra/deploy/install.sh
```

`install.sh` installs `redis-server`, builds the venv at
`/opt/aios/backend/.venv`, does a non-editable `pip install .`, installs the two
unit files to `/etc/systemd/system/`, and enables + starts everything as the
unprivileged `aios` user.

> In **prod** the API fails fast at boot if a required Supabase secret is missing
> (`validate_settings`), so fill `.env` before starting. `GET /health/ready`
> returns 200 only when Supabase **and** Redis are reachable.

## Config note (why no systemd `EnvironmentFile`)

The units set `WorkingDirectory=/opt/aios/backend` and let the app read its own
`.env` via pydantic-settings. We deliberately avoid systemd's `EnvironmentFile=`:
it does not strip inline `# ...` comments, so a `.env` carrying trailing comments
(as `.env.example` does) would feed the comment into the value. Keeping `.env`
loading inside the app avoids that entire class of bug.

## Deploying an update

```bash
cd /opt/aios && sudo git pull
sudo bash infra/deploy/install.sh        # re-installs deps + units idempotently
# (install.sh restarts via enable --now; or restart explicitly:)
sudo systemctl restart aios-api aios-worker
```

The worker does a **warm shutdown** on restart (waits for in-flight tasks up to
`TimeoutStopSec=1800`). `task_acks_late` + `visibility_timeout >= task_time_limit`
make any task that is still killed safe to redeliver - a sequential re-run, never
a concurrent double-run.

## Caddy reverse proxy (TLS)

`/etc/caddy/Caddyfile`:

```
api.example.com {
    reverse_proxy 127.0.0.1:8000
}
```

```bash
sudo apt-get install -y caddy
sudo systemctl reload caddy
```

Caddy obtains and renews a Let's Encrypt certificate automatically. Set
`TRUSTED_HOSTS=api.example.com` and `API_CORS_ORIGINS=https://app.example.com` in
`.env` so `TrustedHostMiddleware` and CORS match the real hostnames.

## Operating

```bash
systemctl status aios-api aios-worker redis-server
journalctl -u aios-api -f            # API logs (structlog JSON in prod)
journalctl -u aios-worker -f         # worker logs
curl -sf http://127.0.0.1:8000/health && echo          # liveness
curl -s  http://127.0.0.1:8000/health/ready | jq        # readiness + per-dep status
```

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
| `redis-server` | (distro package) | broker + cache + results; binds 127.0.0.1 |
| `aios-api` | `uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 2` | behind Caddy; liveness independent of Redis |
| `aios-worker` | `celery -A workers.celery_app worker --concurrency=4` | warm shutdown; acks_late-safe redelivery |

Both app units are hardened (`NoNewPrivileges`, `ProtectSystem=strict`,
`ProtectHome`, `PrivateTmp`, ...) and run as `aios`, never root.
