# Deploying AIOS on Portainer

This stack runs the whole platform as 7 containers:

| Service   | Image                | Role                                                        |
|-----------|----------------------|-------------------------------------------------------------|
| `db`      | `postgres:16`        | The data plane (RLS tenant boundary). Volume `pgdata`.       |
| `redis`   | `redis:7-alpine`     | App cache (/0) + Celery broker (/1) + results (/2). `redisdata`. |
| `migrate` | `aios-backend`       | **One-shot.** Applies migrations, sets role passwords, runs the RLS gate, seeds the owner, then exits. |
| `api`     | `aios-backend`       | FastAPI (uvicorn). Published on `API_PORT` (8000).           |
| `worker`  | `aios-backend`       | Celery worker — Audit/Content/Off-page/Rank/… jobs.         |
| `beat`    | `aios-backend`       | Celery beat — context compaction, rank checks, billing sweep. |
| `web`     | `aios-web`           | Next.js 15 (standalone). Published on `WEB_PORT` (3000). Proxies `/api/v1/*` → `api:8000`. |

`api`, `worker`, `beat`, `migrate` all share **one** image (`backend/Dockerfile`), selected by the container `command`. `api`/`worker`/`beat` won't start until `migrate` has completed successfully.

---

## Prerequisites

- A Portainer instance with access to a Docker environment (you have `docker.qanry.com`).
- This repo pushed to a Git remote Portainer can reach (`github.com/codesofadan/danyals-aios`).
  If the repo is **private**, create a GitHub Personal Access Token (repo:read) for Portainer.
- **No local Docker required** — Portainer builds the images on the VPS.

---

## Method A — Git repository stack (recommended, builds on the VPS)

1. **Portainer → Stacks → + Add stack.**
2. **Name:** `aios`.
3. **Build method:** choose **Repository**.
4. **Repository URL:** `https://github.com/codesofadan/danyals-aios`
   - **Reference:** `refs/heads/main`
   - **Compose path:** `docker-compose.yml`
   - If private: enable **Authentication** and paste your GitHub username + PAT.
5. **Environment variables:** scroll to the **Environment variables** section, click
   **Advanced mode**, and paste your filled-in env (the contents of the repo-root `.env`,
   or `infra/docker/stack.env.example` with real values). Every `${VAR}` in the compose
   is resolved from here.
6. Click **Deploy the stack.** Portainer clones the repo, builds `aios-backend` (with the
   `.[ai]` extra so the Anthropic key is live) and `aios-web`, then starts everything.
   First build takes a few minutes (Python + Node installs).
7. Watch **Stacks → aios → (containers)**. Order: `db` healthy → `redis` healthy →
   `migrate` runs and **exits 0** → `api`/`worker`/`beat` start → `web` starts.

### Verifying `migrate`
Open the `migrate` container **Logs**. Success ends with:
```
[migrate] running the RLS coverage gate
[migrate] provisioning the seed OWNER (idempotent)
[migrate] bootstrap complete — api/worker/beat may start
```
If it fails, api/worker/beat stay down by design — fix the env and **redeploy the stack**
(migrate is idempotent: it skips applied migrations and re-seeding is a no-op).

---

## Method B — Web editor (only if images are prebuilt in a registry)

The web editor has no source tree, so `build:` cannot run. Use this **only** if you first
build `aios-backend` + `aios-web` elsewhere and push them to a registry, then replace the
`build:` blocks with `image: <registry>/aios-backend:<tag>` etc. For this project, prefer
Method A.

---

## First login & smoke test

- **Frontend:** `http://<vps-host>:3000` (or your fronting domain).
- **API health:** `http://<vps-host>:8000/health` → `{"status":"ok"}`.
- **Owner login:** username `owner`, the `SEED_OWNER_PASSWORD` you set. **Change it after
  first login.**

## TLS / public domain (the `nginx` service)

The stack ships an **`nginx` container (`jonasal/nginx-certbot`)** that is the only
service facing the public network. It terminates HTTPS for **`app.qanry.com`** and
reverse-proxies to `web:3000` (which proxies `/api/v1/*` → `api:8000`, so one domain
fronts the whole app). On first deploy it drops in a dummy cert so nginx boots, then
obtains the real **Let's Encrypt** cert over port 80 (ACME http-01 + the http→https
redirect are handled internally) and auto-renews it. Certs persist in the
`nginx_secrets` volume across redeploys.

To go live on the domain:
1. **DNS:** an `A` record for `app.qanry.com` → the VPS public IP (`192.255.159.242`),
   propagated (`nslookup app.qanry.com` returns it).
2. **Env:** `CERTBOT_EMAIL` (a real inbox), `TRUSTED_HOSTS=app.qanry.com`,
   `API_CORS_ORIGINS=https://app.qanry.com`. To change the domain, edit
   `infra/deploy/nginx.conf` (the `server_name` + the `live/<domain>` cert paths) too.
3. **Firewall:** open ports **80** and **443** on the VPS / cloud security group.
4. Deploy, then browse **`https://app.qanry.com`** — valid padlock, login page.
   `https://app.qanry.com/api/v1/health` → `{"status":"ok"}` proves the api proxy.

Watch the `nginx` container **Logs** on first deploy: it prints the dummy-cert step,
then the successful certbot issuance. If issuance fails, it's almost always (a) DNS not
yet pointing at this box, or (b) port 80 not open — fix and it retries on the next loop.

If you later expose the API on its OWN subdomain instead of the one-domain proxy, set
`API_CORS_ORIGINS` + `TRUSTED_HOSTS` accordingly and point
`GOOGLE_OAUTH_REDIRECT_URI` at `https://<api-domain>/api/v1/site-analytics/oauth/callback`
(also add that exact URI to the Google OAuth client).

---

## Updating the stack

- **Code/config change:** push to `main`, then in Portainer **Stacks → aios → Pull and
  redeploy** (enable *re-pull image* / *re-build*). `migrate` re-runs safely.
- **Env change:** edit the stack's Environment variables → **Update the stack.**

## Data & backups

- Postgres data → `pgdata` volume. Redis AOF → `redisdata`. Artifacts + beat schedule →
  `aios_state` (`/var/lib/aios`). Back up these volumes (or use the built-in Backups module
  once B2 keys are set).

## Security notes

- The repo-root `.env` is git-ignored — real secrets never enter the image or GitHub.
- Narrow `TRUSTED_HOSTS` / `API_CORS_ORIGINS` from `*` to real hosts before going public.
- `db` and `redis` publish **no** host ports (in-network only). Only `web` (3000) and,
  optionally, `api` (8000) are exposed — drop `API_PORT` mapping if the frontend proxy is
  your only entry point.
