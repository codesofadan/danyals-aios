#!/usr/bin/env bash
#
# Native-Windows local equivalent of infra/docker/migrate-entrypoint.sh.
#
# Rebuilds the local `aios` database from scratch so its schema matches what the
# VPS runs: drop + recreate, apply EVERY db/migrations/[0-9]*.sql in order through
# the migration ledger, set the authenticated/service_role login passwords from the
# backend/.env DSNs, run the RLS coverage gate, seed the owner login.
#
# Requires the postgres SUPERUSER password (migration 0000's ownership invariant:
# the migration owner must be a BYPASSRLS superuser or the SECURITY DEFINER helpers
# recurse through users_select). Pass it in the environment:
#
#     PGPASSWORD='...' scripts/local-db-rebuild.sh
#
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PATH="/c/Program Files/PostgreSQL/16/bin:$PATH"
VENV_PY="$REPO/backend/.venv/Scripts/python.exe"

log() { printf '\033[1;32m[rebuild]\033[0m %s\n' "$*"; }
err() { printf '\033[1;31m[rebuild]\033[0m %s\n' "$*" >&2; }

: "${PGHOST:=localhost}" "${PGPORT:=5432}" "${PGUSER:=postgres}"
export PGHOST PGPORT PGUSER PGPASSWORD

if [ -z "${PGPASSWORD:-}" ]; then err "set PGPASSWORD to the postgres superuser password"; exit 1; fi

# --- 0. verify we really are a superuser --------------------------------------
if ! psql -d postgres -tAc 'select 1' >/dev/null 2>&1; then
    err "cannot authenticate as ${PGUSER}@${PGHOST}:${PGPORT} — wrong password?"; exit 1
fi
if [ "$(psql -d postgres -tAc "select rolsuper from pg_roles where rolname=current_user")" != "t" ]; then
    err "${PGUSER} is not a superuser; migration 0000 requires one"; exit 1
fi
log "authenticated as superuser ${PGUSER}"

# --- 1. safety dump of whatever is there today --------------------------------
STAMP="$(psql -d postgres -tAc "select to_char(now(),'YYYYMMDD-HH24MISS')")"
DUMP="$REPO/../aios-local-predrop-${STAMP}.dump"
if psql -d postgres -tAc "select 1 from pg_database where datname='aios'" | grep -q 1; then
    log "dumping the existing database to ${DUMP}"
    pg_dump -Fc -d aios -f "$DUMP" || err "dump failed (continuing — data was throwaway)"
fi

# --- 2. drop + recreate --------------------------------------------------------
log "dropping and recreating database aios"
psql -d postgres -v ON_ERROR_STOP=1 -q -c \
  "select pg_terminate_backend(pid) from pg_stat_activity where datname='aios' and pid<>pg_backend_pid();"
psql -d postgres -v ON_ERROR_STOP=1 -q -c 'drop database if exists aios;'
psql -d postgres -v ON_ERROR_STOP=1 -q -c 'create database aios owner postgres;'

export PGDATABASE=aios

# --- 3. migration ledger (non-public schema; the RLS gate only inspects public) -
psql -v ON_ERROR_STOP=1 -q <<'SQL'
create schema if not exists deploy;
create table if not exists deploy.schema_migrations (
  filename    text primary key,
  applied_at  timestamptz not null default now()
);
SQL

# --- 4. apply every migration IN ORDER ----------------------------------------
log "applying migrations from db/migrations"
shopt -s nullglob
count=0
for f in "$REPO"/db/migrations/[0-9]*.sql; do
    base="$(basename "$f")"
    if [ "$(psql -tAc "select 1 from deploy.schema_migrations where filename='${base}'")" = "1" ]; then
        continue
    fi
    log "  applying ${base}"
    psql -v ON_ERROR_STOP=1 -q -f "$f"
    psql -v ON_ERROR_STOP=1 -q -c "insert into deploy.schema_migrations(filename) values ('${base}')"
    count=$((count+1))
done
log "applied ${count} migrations"

# --- 5. set the authenticated / service_role login passwords from the DSNs -----
log "setting authenticated / service_role passwords from backend/.env"
cd "$REPO/backend"
AUTH_PW="$("$VENV_PY" -c "
import re,pathlib
from urllib.parse import urlsplit,unquote
t=pathlib.Path('.env').read_text(encoding='utf-8')
m=re.search(r'^DATABASE_URL=(\S+)',t,re.M)
print(unquote(urlsplit(m.group(1)).password or ''))")"
SVC_PW="$("$VENV_PY" -c "
import re,pathlib
from urllib.parse import urlsplit,unquote
t=pathlib.Path('.env').read_text(encoding='utf-8')
m=re.search(r'^DATABASE_ADMIN_URL=(\S+)',t,re.M)
print(unquote(urlsplit(m.group(1)).password or ''))")"
if [ -z "$AUTH_PW" ] || [ -z "$SVC_PW" ]; then
    err "DATABASE_URL / DATABASE_ADMIN_URL in backend/.env must carry role passwords"; exit 1
fi
AUTH_PW="$AUTH_PW" SVC_PW="$SVC_PW" psql -v ON_ERROR_STOP=1 -q <<'SQL'
\getenv auth_pw AUTH_PW
\getenv svc_pw SVC_PW
alter role authenticated login password :'auth_pw';
alter role service_role  login password :'svc_pw';
SQL

# --- 6. RLS coverage gate ------------------------------------------------------
# rls_check + provision_owner read os.environ DIRECTLY (not backend/.env), so the
# app config must be exported here or the gate aborts with "DATABASE_URL not set".
# The sed strips trailing `# inline comments` that would otherwise land in a value.
set -a
# shellcheck disable=SC1090
source <(grep -E '^[A-Z_]+=' .env | sed -E 's/[[:space:]]+#.*$//')
set +a

log "running the RLS coverage gate"
"$VENV_PY" -m app.db.rls_check

# --- 7. seed the OWNER (idempotent) -------------------------------------------
log "provisioning the seed OWNER"
"$VENV_PY" -m app.cli.provision_owner

log "done — local schema now matches db/migrations HEAD"
