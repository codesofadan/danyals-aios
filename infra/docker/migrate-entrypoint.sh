#!/usr/bin/env bash
#
# One-shot DB bootstrap for the Docker stack — the container equivalent of
# infra/deploy/install.sh sections 4 + 7 (which target a native VPS). Runs as the
# `migrate` service, then exits; api/worker/beat wait for it to complete.
#
# Superuser ops (create the ledger, apply migrations, set role passwords) use the
# PG* env (PGUSER=postgres). The app-level steps (RLS gate, owner seed) use the
# app's DATABASE_URL / DATABASE_ADMIN_URL. Migration 0000 CREATES the roles
# (authenticated / service_role / anon); this script sets their login passwords
# from the DSNs afterward — exactly as the native installer does.
set -euo pipefail

log() { printf '\033[1;32m[migrate]\033[0m %s\n' "$*"; }
err() { printf '\033[1;31m[migrate]\033[0m %s\n' "$*" >&2; }

: "${PGHOST:=db}" "${PGPORT:=5432}" "${PGUSER:=postgres}" "${PGDATABASE:=aios}"
export PGHOST PGPORT PGUSER PGDATABASE PGPASSWORD

# --- 1. wait for postgres ------------------------------------------------------
log "waiting for postgres at ${PGHOST}:${PGPORT} ..."
for i in $(seq 1 60); do
    if psql -tAc 'select 1' >/dev/null 2>&1; then
        break
    fi
    if [ "${i}" -eq 60 ]; then
        err "postgres not reachable after 120s"
        exit 1
    fi
    sleep 2
done
log "postgres is up"

# --- 2. migration ledger (non-public schema; the RLS gate only inspects public) -
psql -v ON_ERROR_STOP=1 -q <<'SQL'
create schema if not exists deploy;
create table if not exists deploy.schema_migrations (
  filename    text primary key,
  applied_at  timestamptz not null default now()
);
SQL

# --- 3. apply every migration IN ORDER, skipping already-applied files ---------
log "applying migrations from /app/db/migrations"
shopt -s nullglob
for f in /app/db/migrations/[0-9]*.sql; do
    base="$(basename "$f")"
    if [ "$(psql -tAc "select 1 from deploy.schema_migrations where filename='${base}'")" = "1" ]; then
        continue
    fi
    log "  applying ${base}"
    psql -v ON_ERROR_STOP=1 -q -f "$f"
    psql -v ON_ERROR_STOP=1 -q -c "insert into deploy.schema_migrations(filename) values ('${base}')"
done

# --- 4. set the authenticated / service_role login passwords from the DSNs -----
# (0000 created them with NO password; the runtime pools log in with these.)
log "setting authenticated / service_role passwords from the app DSNs"
AUTH_PW="$(python -c "import os;from urllib.parse import urlsplit,unquote;print(unquote(urlsplit(os.environ['DATABASE_URL']).password or ''))")"
SVC_PW="$(python -c "import os;from urllib.parse import urlsplit,unquote;print(unquote(urlsplit(os.environ['DATABASE_ADMIN_URL']).password or ''))")"
if [ -z "${AUTH_PW}" ] || [ -z "${SVC_PW}" ]; then
    err "DATABASE_URL / DATABASE_ADMIN_URL must carry role passwords"
    err "(e.g. postgresql://authenticated:PW@db:5432/aios). Fill them and redeploy."
    exit 1
fi
# \getenv keeps the password out of argv; :'var' quotes it as a safe SQL literal.
AUTH_PW="${AUTH_PW}" SVC_PW="${SVC_PW}" psql -v ON_ERROR_STOP=1 -q <<'SQL'
\getenv auth_pw AUTH_PW
\getenv svc_pw SVC_PW
alter role authenticated login password :'auth_pw';
alter role service_role  login password :'svc_pw';
SQL

# --- 5. RLS coverage gate (every public table must FORCE row-level security) ----
log "running the RLS coverage gate"
python -m app.db.rls_check

# --- 6. seed the OWNER (idempotent) so there is a login ------------------------
if [ -n "${SEED_OWNER_USERNAME:-}" ] && [ -n "${SEED_OWNER_PASSWORD:-}" ]; then
    log "provisioning the seed OWNER (idempotent)"
    python -m app.cli.provision_owner
else
    log "SEED_OWNER_USERNAME/PASSWORD not set; skipping owner seed"
fi

log "bootstrap complete — api/worker/beat may start"
