#!/usr/bin/env bash
#
# Provision the AIOS backend on a single Ubuntu 22.04+ / Debian VPS - NO Docker.
# Native PostgreSQL 16 + native Redis + a Python venv + three systemd units
# (aios-api uvicorn, aios-worker celery, aios-beat celery beat) behind Caddy.
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
#   8. installs + enables + (re)starts the three systemd units
#
# Prereqs: run as root; clone the repo to $DEPLOY_ROOT first (git clone <repo>
# /opt/aios). Everything lives in the agency's own VPS + accounts - no lock-in.
#
# Usage:  sudo bash infra/deploy/install.sh
set -euo pipefail

DEPLOY_ROOT="${DEPLOY_ROOT:-/opt/aios}"
BACKEND_DIR="${DEPLOY_ROOT}/backend"
VENV_DIR="${BACKEND_DIR}/.venv"
MIGRATIONS_DIR="${DEPLOY_ROOT}/db/migrations"
UNIT_SRC="${DEPLOY_ROOT}/infra/systemd"
APP_USER="${APP_USER:-aios}"
ENV_DIR="/etc/aios"
ENV_FILE="${ENV_DIR}/aios.env"
ENV_TEMPLATE="${DEPLOY_ROOT}/infra/deploy/aios.env.example"
STATE_DIR="/var/lib/aios"
PG_VERSION="16"

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
(cd "${BACKEND_DIR}" && "${VENV_DIR}/bin/pip" install -e . -q)

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

# --- 8. systemd units ----------------------------------------------------------
log "installing systemd units (aios-api, aios-worker, aios-beat)"
install -m 0644 "${UNIT_SRC}/aios-api.service" /etc/systemd/system/aios-api.service
install -m 0644 "${UNIT_SRC}/aios-worker.service" /etc/systemd/system/aios-worker.service
install -m 0644 "${UNIT_SRC}/aios-beat.service" /etc/systemd/system/aios-beat.service

log "reloading systemd + enabling/starting services"
systemctl daemon-reload
systemctl enable aios-api.service aios-worker.service aios-beat.service
# restart (not just start) so a re-run picks up new code/units.
systemctl restart aios-api.service aios-worker.service aios-beat.service

log "done. next steps:"
log "  1. put Caddy in front for TLS (see infra/deploy/Caddyfile + README-deploy.md)"
log "  2. verify:"
log "       systemctl status aios-api aios-worker aios-beat postgresql redis-server"
log "       journalctl -u aios-api -f"
log "       curl -sf http://127.0.0.1:8000/health  && echo"
log "       curl -s  http://127.0.0.1:8000/health/ready | python3 -m json.tool"
