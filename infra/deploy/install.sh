#!/usr/bin/env bash
#
# Provision the WHOLE AIOS platform on a single Ubuntu 22.04+ / Debian VPS - NO
# Docker. Native PostgreSQL 16 + native Redis + a Python venv + a Next.js build +
# four systemd units (aios-api uvicorn, aios-worker celery, aios-beat celery beat,
# aios-web the dashboard) behind Caddy.
#
# aios-web exists because for a long time this script did NOT build one: it
# provisioned an API with no user interface, and an agency that followed this file
# to the letter finished the install with nothing to log in to. The frontend is
# half the product, so it is installed here, not left as a manual afterthought.
#
# What it does (idempotent - safe to re-run after a `git pull` to pick up code,
# migrations, and unit changes):
#   1. installs/ensures PostgreSQL 16 (PGDG apt repo) + Redis, both loopback-only
#   2. seeds /etc/aios/aios.env from the template on first run (then stops so you
#      can fill it in); reads all config from that one root-owned file thereafter
#   3. creates the `aios` database + sets the anon/authenticated/service_role role
#      passwords (from the DSNs) - service_role is BYPASSRLS (created by 0000)
#   4. applies every db/migrations/NNNN_*.sql IN ORDER as the postgres superuser,
#      tracked in a deploy.schema_migrations ledger so re-runs skip applied files
#   5. runs the RLS coverage gate (fails the install if any public table is open)
#   6. builds the venv + editable `pip install -e .`
#   7. provisions the seed OWNER (idempotent) so there is a login
#   7.5 builds the audit-engine venv (crawl+reports extras) + installs a headless
#      Chromium so the report.pdf actually renders (skipped if AUDIT_ENGINE_DIR unset)
#   7.6 installs Node (NodeSource) if absent, then `npm ci` + `npm run build` in
#      frontend/ - the dashboard the operator actually uses
#   8. installs + enables + (re)starts the four systemd units
#
# Prereqs: run as root; clone the repo to $DEPLOY_ROOT first (git clone <repo>
# /opt/aios). Everything lives in the agency's own VPS + accounts - no lock-in.
#
# Usage:  sudo bash infra/deploy/install.sh
set -euo pipefail

DEPLOY_ROOT="${DEPLOY_ROOT:-/opt/aios}"
BACKEND_DIR="${DEPLOY_ROOT}/backend"
FRONTEND_DIR="${DEPLOY_ROOT}/frontend"
VENV_DIR="${BACKEND_DIR}/.venv"
MIGRATIONS_DIR="${DEPLOY_ROOT}/db/migrations"
UNIT_SRC="${DEPLOY_ROOT}/infra/systemd"
APP_USER="${APP_USER:-aios}"
ENV_DIR="/etc/aios"
ENV_FILE="${ENV_DIR}/aios.env"
ENV_TEMPLATE="${DEPLOY_ROOT}/infra/deploy/aios.env.example"
STATE_DIR="/var/lib/aios"
PG_VERSION="16"
# Next 15.5 needs Node >= 18.18; 20 is the floor we accept and 22 (LTS) is what we
# install, because Ubuntu 22.04 ships nodejs 12 and 24.04 ships 18 - both from a
# distro repo that will never move. Override NODE_MAJOR to pin a different line.
NODE_MAJOR="${NODE_MAJOR:-22}"
NODE_MIN_MAJOR=20

log() { printf '\033[1;32m[install]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[install]\033[0m %s\n' "$*" >&2; }
err() { printf '\033[1;31m[install]\033[0m %s\n' "$*" >&2; }

if [[ "${EUID}" -ne 0 ]]; then
    err "must run as root (use sudo)"
    exit 1
fi
if [[ ! -d "${BACKEND_DIR}" ]]; then
    err "expected the repo at ${DEPLOY_ROOT} (missing ${BACKEND_DIR})."
    err "clone it first:  git clone <repo> ${DEPLOY_ROOT}"
    exit 1
fi

export DEBIAN_FRONTEND=noninteractive

# --- 1. System packages: PostgreSQL 16 (PGDG) + Redis + Python -----------------
log "installing base packages (curl, gnupg, python venv)"
apt-get update -qq
apt-get install -y -qq curl ca-certificates gnupg lsb-release python3-venv python3-pip

if ! dpkg -l "postgresql-${PG_VERSION}" >/dev/null 2>&1; then
    log "adding the PostgreSQL (PGDG) apt repository for PostgreSQL ${PG_VERSION}"
    install -d /usr/share/postgresql-common/pgdg
    curl -fsSL https://www.postgresql.org/media/keys/ACCC4CF8.asc \
        -o /usr/share/postgresql-common/pgdg/apt.postgresql.org.asc
    # shellcheck disable=SC1091
    . /etc/os-release
    echo "deb [signed-by=/usr/share/postgresql-common/pgdg/apt.postgresql.org.asc] https://apt.postgresql.org/pub/repos/apt ${VERSION_CODENAME}-pgdg main" \
        > /etc/apt/sources.list.d/pgdg.list
    apt-get update -qq
fi
log "installing postgresql-${PG_VERSION} + redis-server"
apt-get install -y -qq "postgresql-${PG_VERSION}" redis-server

log "enabling + starting postgresql and redis-server (loopback-only)"
# PostgreSQL 16 ships listen_addresses='localhost' (loopback) by default; we do
# NOT open it up. Redis ships bind 127.0.0.1 by default. Both stay server-local -
# only the FastAPI API (also localhost) and Caddy face the network.
systemctl enable --now postgresql
systemctl enable --now redis-server

# --- 2. Config: seed /etc/aios/aios.env on first run ---------------------------
install -d -m 0755 "${ENV_DIR}"
if [[ ! -f "${ENV_FILE}" ]]; then
    log "seeding ${ENV_FILE} from the template (0600 root:root)"
    install -m 0600 "${ENV_TEMPLATE}" "${ENV_FILE}"
    err "-------------------------------------------------------------------"
    err " EDIT ${ENV_FILE} now: set APP_ENV=prod, the two DATABASE_* DSNs,"
    err " the EdDSA keypair, VAULT_MASTER_KEY, SEED_OWNER_*, and the real hosts."
    err " Then re-run:  sudo bash ${DEPLOY_ROOT}/infra/deploy/install.sh"
    err "-------------------------------------------------------------------"
    exit 0
fi
chmod 0600 "${ENV_FILE}"

# --- 3. App user + venv (needed before we can parse env / run the gate) --------
if ! id "${APP_USER}" &>/dev/null; then
    log "creating system user '${APP_USER}'"
    useradd --system --home-dir "${DEPLOY_ROOT}" --shell /usr/sbin/nologin "${APP_USER}"
else
    log "system user '${APP_USER}' already exists"
fi

if [[ ! -d "${VENV_DIR}" ]]; then
    log "creating virtualenv at ${VENV_DIR}"
    python3 -m venv "${VENV_DIR}"
fi
log "installing the backend (editable) + deps into the venv"
"${VENV_DIR}/bin/pip" install --upgrade pip -q
# Editable install: a `git pull` updates the running code (a restart picks it up)
# with no reinstall. Add the [ai] extra here if/when the context provider keys land.
#
# [automation] brings Playwright, which the DESIGN CAPTURE path needs - it is the only
# way to read a page's computed styles and rendered geometry, and without it
# `build_site_analyzer()` returns None and every capture degrades to
# "playwright_unconfigured". The Chromium binary itself is already downloaded further
# down this script into ${STATE_DIR}/ms-playwright for the audit engine; the backend
# venv reuses that same download via PLAYWRIGHT_BROWSERS_PATH rather than fetching a
# second ~150MB copy.
(cd "${BACKEND_DIR}" && "${VENV_DIR}/bin/pip" install -e '.[automation]' -q)

log "setting ownership of ${DEPLOY_ROOT} to ${APP_USER}"
chown -R "${APP_USER}:${APP_USER}" "${DEPLOY_ROOT}"

# --- helpers that read the (trusted, root-owned) env file via python-dotenv ----
# We never `source` the env file into the shell (a DSN password or PEM could carry
# shell metacharacters). python-dotenv parses it safely; the venv has it.
env_get() { # env_get <KEY> -> value (empty if unset)
    "${VENV_DIR}/bin/python" - "$1" <<'PY'
import sys
from dotenv import dotenv_values
# interpolate=False: treat $ literally, matching how systemd EnvironmentFile does.
sys.stdout.write((dotenv_values("/etc/aios/aios.env", interpolate=False).get(sys.argv[1]) or ""))
PY
}
dsn_field() { # dsn_field <KEY> <user|password|host|port|dbname>
    "${VENV_DIR}/bin/python" - "$1" "$2" <<'PY'
import sys
from urllib.parse import urlsplit, unquote
from dotenv import dotenv_values
u = urlsplit(dotenv_values("/etc/aios/aios.env", interpolate=False).get(sys.argv[1]) or "")
sys.stdout.write({
    "user": unquote(u.username or ""),
    "password": unquote(u.password or ""),
    "host": u.hostname or "",
    "port": str(u.port or 5432),
    "dbname": (u.path or "/").lstrip("/"),
}[sys.argv[2]])
PY
}
run_py_module() { # run_py_module <module.path> [args...]  (as APP_USER, env loaded)
    local module="$1"; shift
    sudo -u "${APP_USER}" "${VENV_DIR}/bin/python" - "$module" "$@" <<'PY'
import os, sys, runpy
from dotenv import dotenv_values
for k, v in dotenv_values("/etc/aios/aios.env", interpolate=False).items():
    if v is not None:
        os.environ[k] = v
module = sys.argv[1]
sys.argv = [module, *sys.argv[2:]]
runpy.run_module(module, run_name="__main__")
PY
}

ADMIN_DBNAME="$(dsn_field DATABASE_ADMIN_URL dbname)"
AUTH_PW="$(dsn_field DATABASE_URL password)"
SVC_PW="$(dsn_field DATABASE_ADMIN_URL password)"
: "${ADMIN_DBNAME:=aios}"
if [[ -z "${AUTH_PW}" || -z "${SVC_PW}" ]]; then
    err "DATABASE_URL / DATABASE_ADMIN_URL in ${ENV_FILE} must carry role passwords"
    err "(e.g. postgresql://authenticated:PW@localhost:5432/aios). Fill them and re-run."
    exit 1
fi

# --- 4. Database + roles + migrations (as the postgres superuser, peer auth) ---
log "ensuring database '${ADMIN_DBNAME}' exists"
if ! sudo -u postgres psql -tAc "select 1 from pg_database where datname = '${ADMIN_DBNAME}'" | grep -q 1; then
    sudo -u postgres createdb "${ADMIN_DBNAME}"
fi

log "applying migrations from ${MIGRATIONS_DIR} (in lexical order, superuser owner)"
# A tiny ledger in a NON-public schema (the RLS gate only inspects `public`) makes
# re-runs skip already-applied files, so migrations that aren't self-idempotent are
# never replayed. 0000 (the substrate: auth schema + roles) is applied first and IS
# idempotent, so it is safe even before the ledger exists.
sudo -u postgres psql -v ON_ERROR_STOP=1 -d "${ADMIN_DBNAME}" -q <<'SQL'
create schema if not exists deploy;
create table if not exists deploy.schema_migrations (
  filename    text primary key,
  applied_at  timestamptz not null default now()
);
SQL
for f in "${MIGRATIONS_DIR}"/[0-9]*.sql; do
    base="$(basename "$f")"
    already="$(sudo -u postgres psql -tAc \
        "select 1 from deploy.schema_migrations where filename = '${base}'" -d "${ADMIN_DBNAME}")"
    if [[ "${already}" == "1" ]]; then
        continue
    fi
    log "  applying ${base}"
    sudo -u postgres psql -v ON_ERROR_STOP=1 -d "${ADMIN_DBNAME}" -q -f "$f"
    sudo -u postgres psql -v ON_ERROR_STOP=1 -d "${ADMIN_DBNAME}" -q \
        -c "insert into deploy.schema_migrations(filename) values ('${base}')"
done

log "setting the anon/authenticated/service_role role passwords from the DSNs"
# psql's :'var' quotes the value as a safe SQL literal; \getenv keeps the password
# out of the process argv (passed only through the environment). service_role and
# authenticated are LOGIN roles (created by 0000); anon stays NOLOGIN (vestigial).
AUTH_PW="${AUTH_PW}" SVC_PW="${SVC_PW}" sudo -u postgres --preserve-env=AUTH_PW,SVC_PW \
    psql -v ON_ERROR_STOP=1 -d "${ADMIN_DBNAME}" -q <<'SQL'
\getenv auth_pw AUTH_PW
\getenv svc_pw SVC_PW
alter role authenticated login password :'auth_pw';
alter role service_role  login password :'svc_pw';
SQL

# --- 5. RLS coverage gate ------------------------------------------------------
log "running the RLS coverage gate (every public table must FORCE row-level security)"
run_py_module app.db.rls_check

# --- 6. Writable state (artifact dirs under /var/lib/aios) ---------------------
# StateDirectory=aios in the worker/beat units creates /var/lib/aios at start, but
# create it now too so the operator can drop AUDIT/CONTENT/BACKUP artifact dirs
# under it. Any artifact dir set in aios.env that lives under /var/lib/aios is
# created + owned here so the worker (ProtectSystem=strict) can write it.
install -d -o "${APP_USER}" -g "${APP_USER}" -m 0750 "${STATE_DIR}"
for key in AUDIT_ARTIFACT_DIR CONTENT_ARTIFACT_DIR BACKUP_ARTIFACT_DIR; do
    dir="$(env_get "${key}")"
    if [[ -n "${dir}" && "${dir}" == "${STATE_DIR}"/* ]]; then
        install -d -o "${APP_USER}" -g "${APP_USER}" -m 0750 "${dir}"
    fi
done

# --- 7. Seed owner (idempotent) -----------------------------------------------
if [[ -n "$(env_get SEED_OWNER_USERNAME)" && -n "$(env_get SEED_OWNER_PASSWORD)" ]]; then
    log "provisioning the seed OWNER (idempotent)"
    run_py_module app.cli.provision_owner
else
    warn "SEED_OWNER_USERNAME/PASSWORD not set in ${ENV_FILE}; skipping owner provisioning."
    warn "provision one later:  sudo -u ${APP_USER} ${VENV_DIR}/bin/python -m app.cli.provision_owner --username <u> --password <p>"
fi

# --- 7.5 Audit engine (Module 01): its OWN venv + a headless browser -----------
# The engine (danyals-audit-system) is a SEPARATE product with its OWN interpreter
# (AUDIT_ENGINE_PYTHON), invoked by the worker as a subprocess - it is NOT part of
# the backend venv above. A full audit CRAWLS with Playwright and RENDERS the
# consulting report.pdf with a headless browser; on a server with no system Chrome
# the engine falls back to Playwright's bundled Chromium. Without a render backend
# the engine still writes findings.json but produces NO downloadable report.pdf
# (which surfaces in the dashboard as a "pdf error" on download). So we build the
# engine venv WITH its crawl+reports extras and install Chromium (+ OS libs) into a
# shared path the sandboxed worker can read.
ENGINE_DIR="$(env_get AUDIT_ENGINE_DIR)"
if [[ -n "${ENGINE_DIR}" && -f "${ENGINE_DIR}/pyproject.toml" ]]; then
    ENGINE_PY="$(env_get AUDIT_ENGINE_PYTHON)"
    if [[ -n "${ENGINE_PY}" ]]; then
        ENGINE_VENV="$(dirname "$(dirname "${ENGINE_PY}")")"
    else
        ENGINE_VENV="${ENGINE_DIR}/.venv"
        warn "AUDIT_ENGINE_PYTHON is unset; set it to ${ENGINE_VENV}/bin/python in ${ENV_FILE}."
    fi
    if [[ ! -d "${ENGINE_VENV}" ]]; then
        log "creating audit-engine virtualenv at ${ENGINE_VENV}"
        python3 -m venv "${ENGINE_VENV}"
    fi
    log "installing the audit engine (editable, crawl+reports extras) into its venv"
    "${ENGINE_VENV}/bin/pip" install --upgrade pip -q
    # [crawl] = the Playwright crawler (also a PDF backend); [reports] = markdown +
    # weasyprint + pygments. Both are needed for a full audit to RUN and RENDER; a
    # bare `pip install -e .` ships neither (they are optional extras).
    (cd "${ENGINE_DIR}" && "${ENGINE_VENV}/bin/pip" install -e '.[crawl,reports]' -q)

    # Playwright's bundled Chromium, into a shared path the sandboxed worker can
    # read: StateDirectory=/var/lib/aios is the worker's only writable+readable tree
    # (ProtectSystem=strict + ProtectHome=true). The worker unit exports
    # PLAYWRIGHT_BROWSERS_PATH to the same path so the engine subprocess finds it.
    # install-deps needs root (apt); the browser download inherits the same path.
    PLAYWRIGHT_DIR="${STATE_DIR}/ms-playwright"
    install -d -o "${APP_USER}" -g "${APP_USER}" -m 0750 "${PLAYWRIGHT_DIR}"
    log "installing Playwright Chromium OS libraries (apt)"
    "${ENGINE_VENV}/bin/python" -m playwright install-deps chromium \
        || warn "playwright install-deps failed (unsupported distro?); PDF rendering may be degraded"
    log "downloading Playwright Chromium into ${PLAYWRIGHT_DIR}"
    PLAYWRIGHT_BROWSERS_PATH="${PLAYWRIGHT_DIR}" "${ENGINE_VENV}/bin/python" -m playwright install chromium \
        || warn "playwright chromium download failed; report.pdf may not render"

    chown -R "${APP_USER}:${APP_USER}" "${ENGINE_VENV}" "${PLAYWRIGHT_DIR}"
else
    warn "AUDIT_ENGINE_DIR not set (or no pyproject.toml there); skipping audit-engine setup."
    warn "audits stay unavailable until AUDIT_ENGINE_DIR + AUDIT_ENGINE_PYTHON are set in ${ENV_FILE}."
fi

# --- 7.6 Dashboard (aios-web): Node + `npm ci` + `npm run build` ---------------
# WHY THIS EXISTS: before this block the install produced an API and no user
# interface. Nothing failed - there was simply nothing to open, which is the worst
# shape a failure can take, so the dashboard is built here as a first-class step.
#
# A failure here is NOT fatal to the rest of the install (a `git pull` + re-run must
# still be able to restart the backend when the frontend build is what broke), but it
# is never silent either: `WEB_STATUS` carries the cause, step 8 refuses to start
# aios-web, and the script exits non-zero with that cause named. "API is up" is not a
# successful install of this platform.
WEB_STATUS="ok"

node_major() { # node_major -> installed node major version, or 0 if absent
    if ! command -v node >/dev/null 2>&1; then
        echo 0
        return
    fi
    node -p 'process.versions.node.split(".")[0]' 2>/dev/null || echo 0
}

if [[ ! -f "${FRONTEND_DIR}/package.json" ]]; then
    WEB_STATUS="no frontend/package.json under ${DEPLOY_ROOT} (incomplete clone?)"
    err "${WEB_STATUS}"
else
    if [[ "$(node_major)" -lt "${NODE_MIN_MAJOR}" ]]; then
        log "installing Node.js ${NODE_MAJOR}.x from NodeSource (found: $(node --version 2>/dev/null || echo none))"
        # NodeSource, not `apt-get install nodejs`: the distro package is Node 12 on
        # 22.04 and 18 on 24.04, and Next 15.5 refuses to build on either. The
        # `nodistro` suite is NodeSource's single distribution-independent channel.
        install -d /usr/share/keyrings
        curl -fsSL https://deb.nodesource.com/gpgkey/nodesource-repo.gpg.key \
            | gpg --batch --yes --dearmor -o /usr/share/keyrings/nodesource.gpg
        echo "deb [signed-by=/usr/share/keyrings/nodesource.gpg] https://deb.nodesource.com/node_${NODE_MAJOR}.x nodistro main" \
            > /etc/apt/sources.list.d/nodesource.list
        apt-get update -qq
        apt-get install -y -qq nodejs
    else
        log "Node.js $(node --version) already present (>= ${NODE_MIN_MAJOR}); leaving it alone"
    fi
fi

if [[ "${WEB_STATUS}" == "ok" ]]; then
    # --- BUILD-TIME configuration. READ THIS BEFORE CHANGING IT ---------------
    # These are NOT runtime settings, however much they look like them:
    #   * every NEXT_PUBLIC_* is textually INLINED into the JS bundle by
    #     `next build`;
    #   * BACKEND_ORIGIN is read by next.config.mjs to build the /api/v1 rewrite,
    #     and `next build` freezes the result into .next/routes-manifest.json.
    # So putting them only in the unit's EnvironmentFile does nothing at all - the
    # value that wins is whatever was in the environment during THIS build. (Proof
    # that this bites: a routes-manifest checked on a dev box had a developer's
    # personal 127.0.0.1:8099 baked into it.) They are therefore read out of
    # aios.env here and exported for the build, and re-running install.sh is what
    # applies a change to any of them.
    WEB_PORT="$(env_get AIOS_WEB_PORT)"
    : "${WEB_PORT:=3000}"
    BACKEND_ORIGIN="$(env_get BACKEND_ORIGIN)"
    : "${BACKEND_ORIGIN:=http://127.0.0.1:8000}"
    export BACKEND_ORIGIN
    export NEXT_TELEMETRY_DISABLED=1
    # NOTE: NODE_ENV is deliberately NOT exported here, even though this is a
    # production install and the unit sets it. `npm ci` reads NODE_ENV and OMITS
    # devDependencies when it is "production" - which is where typescript, the
    # @types packages and eslint-config-next live, so the build would then fail on a
    # missing compiler. `next build` sets NODE_ENV=production for the build itself;
    # it does not need help, and helping here breaks the install.

    # Exported ONLY when non-empty, and that is a guard, not tidiness. lib/api.ts
    # reads `process.env.NEXT_PUBLIC_API_BASE_URL ?? "/api/v1"`, and `??` falls back
    # on undefined but NOT on "". Next inlines any NEXT_PUBLIC_* that is merely
    # PRESENT, so exporting a blank one bakes `""` into the bundle, API_BASE becomes
    # the empty string, and every call goes to `/audits` instead of `/api/v1/audits`
    # - a fully-loading dashboard where nothing works. A blank line in aios.env
    # must mean "unset", so it is dropped here rather than exported empty.
    for key in NEXT_PUBLIC_API_BASE_URL NEXT_PUBLIC_FILE_BASE_URL; do
        value="$(env_get "${key}")"
        if [[ -n "${value}" ]]; then
            export "${key}=${value}"
            log "  build-time ${key}=${value}"
        fi
    done
    log "building the dashboard (npm ci + npm run build) with BACKEND_ORIGIN=${BACKEND_ORIGIN}"

    # `npm ci`, not `npm install`: ci installs exactly what package-lock.json pins and
    # fails loudly if the lock and package.json disagree, so a deploy can never resolve
    # a different dependency tree than the one that was tested.
    if ! (cd "${FRONTEND_DIR}" && npm ci --no-audit --no-fund); then
        WEB_STATUS="npm ci failed in ${FRONTEND_DIR}"
    elif ! (cd "${FRONTEND_DIR}" && npm run build); then
        WEB_STATUS="npm run build failed in ${FRONTEND_DIR}"
    elif [[ ! -f "${FRONTEND_DIR}/.next/BUILD_ID" ]]; then
        # Checking the ARTIFACT, not just the exit code: this is the file `next start`
        # needs, and its absence is the difference between "built" and "the command
        # returned 0". Starting the unit without it produces a crash-loop whose journal
        # line ("Could not find a production build") is three steps from the cause.
        WEB_STATUS="npm run build produced no .next/BUILD_ID in ${FRONTEND_DIR}"
    fi

    if [[ "${WEB_STATUS}" == "ok" ]]; then
        # ProtectSystem=strict + ReadWritePaths=<frontend>/.next/cache in
        # aios-web.service: systemd REFUSES TO START a unit whose ReadWritePaths entry
        # does not exist, and the build does not always leave this directory behind.
        install -d -o "${APP_USER}" -g "${APP_USER}" -m 0750 "${FRONTEND_DIR}/.next/cache"
        # The tree-wide chown ran in step 3, before node_modules and .next existed.
        chown -R "${APP_USER}:${APP_USER}" "${FRONTEND_DIR}"
        log "dashboard built; it will listen on 127.0.0.1:${WEB_PORT}"
    else
        err "${WEB_STATUS}"
    fi
fi

# --- 8. systemd units ----------------------------------------------------------
log "installing systemd units (aios-api, aios-worker, aios-beat, aios-web)"
# The units are written against the default /opt/aios. DEPLOY_ROOT is advertised
# as configurable at the top of this script, and installing them verbatim made
# that a lie: any other root produced units pointing at a directory that does not
# exist, so they failed to start with no obvious cause. Substitute the real root
# on the way in rather than hardcoding it in the unit files, which would just move
# the problem. aios-web carries THREE /opt/aios paths (WorkingDirectory, the node
# entrypoint, and ReadWritePaths), so this substitution is load-bearing for it in
# a way it is not for the backend units - a missed one there is a unit that
# refuses to start on the mount namespace, not a clean error.
#
# aios-web's unit FILE is written unconditionally even when the build failed, so a
# later successful re-run only has to start it - but it is not enabled or started
# below unless the build actually produced one.
for unit in aios-api aios-worker aios-beat aios-web; do
  sed "s|/opt/aios|${DEPLOY_ROOT}|g" "${UNIT_SRC}/${unit}.service" \
    > "/etc/systemd/system/${unit}.service"
  chmod 0644 "/etc/systemd/system/${unit}.service"
done

log "reloading systemd + enabling/starting services"
systemctl daemon-reload
systemctl enable aios-api.service aios-worker.service aios-beat.service
# restart (not just start) so a re-run picks up new code/units.
systemctl restart aios-api.service aios-worker.service aios-beat.service

if [[ "${WEB_STATUS}" == "ok" ]]; then
    systemctl enable aios-web.service
    systemctl restart aios-web.service
else
    # Deliberately NOT enabled/restarted. Enabling it would schedule a crash-loop at
    # every boot for a build that is known to be missing, and restarting it would
    # take down a dashboard from a previous good build - punishing the operator twice
    # for one failure. Whatever is running now keeps running; the error below says so.
    err "aios-web NOT started: ${WEB_STATUS}"
fi

log "done. next steps:"
log "  1. put Caddy in front for TLS (see infra/deploy/Caddyfile + README-deploy.md)"
log "     it publishes BOTH hosts: the API and the dashboard."
log "  2. verify:"
log "       systemctl status aios-api aios-worker aios-beat aios-web postgresql redis-server"
log "       journalctl -u aios-api -f"
log "       curl -sf http://127.0.0.1:8000/health  && echo"
log "       curl -s  http://127.0.0.1:8000/health/ready | python3 -m json.tool"
log "       curl -sfI http://127.0.0.1:${WEB_PORT:-3000}/login | head -1"

if [[ "${WEB_STATUS}" != "ok" ]]; then
    err "-------------------------------------------------------------------"
    err " INSTALL INCOMPLETE. The backend is running, but the DASHBOARD is not:"
    err "   ${WEB_STATUS}"
    err " There is no user interface on this box until that is fixed. Re-run this"
    err " script once it is; nothing else needs undoing."
    err "-------------------------------------------------------------------"
    # Non-zero on purpose. An API with no dashboard is not a successful install of
    # this platform, and an exit 0 here is exactly the "looks fine" that let a
    # UI-less deploy ship in the first place.
    exit 1
fi
