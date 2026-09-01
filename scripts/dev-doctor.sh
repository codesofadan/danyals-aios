#!/usr/bin/env bash
# ============================================================================
# AIOS dev doctor — REPORTS the local environment's health. Never kills anything.
#
# Exists because of 2026-09-01: TWO backends from this tree shared one database
# (:8000 stale, :8099 live), TWO frontends ran (:3000, :3001), and three Celery
# workers all consumed `-Q celery` while `long` and `browser` starved — so the
# extension paired against a dead port, the dashboard talked to another server,
# and the liveness re-check sat stranded in Redis. None of that errored anywhere.
#
# Canonical dev shape (also in RUN-LOCALLY.md):
#   backend   uvicorn on 127.0.0.1:8000
#   frontend  next dev on :3000, BACKEND_ORIGIN=http://127.0.0.1:8000
#   worker    ONE celery worker with -Q celery,interactive,standard,long,browser
#   beat      NOT running — off by owner decision; periodic jobs have manual triggers
#
# Concurrent Claude/dev sessions share this checkout and may own processes you did
# not start: this script only prints the kill commands, it never runs them.
# ============================================================================
set -u

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PY="$ROOT/backend/.venv/bin/python"
FAIL=0

section() { printf '\n== %s ==\n' "$1"; }

# ---------------------------------------------------------------------------- #
section "Listeners on the dev ports (canonical: 8000 backend, 3000 frontend)"
LISTENERS="$(lsof -nP -iTCP -sTCP:LISTEN 2>/dev/null | awk 'NR==1 || $9 ~ /:(8000|8099|3000|3001)$/')"
echo "${LISTENERS:-  (none)}"

count_port() { echo "$LISTENERS" | awk -v p=":$1$" '$9 ~ p' | wc -l | tr -d ' '; }
for PORT in 8099 3001; do
  if [ "$(count_port "$PORT")" -gt 0 ]; then
    PID=$(echo "$LISTENERS" | awk -v p=":$PORT$" '$9 ~ p {print $2; exit}')
    echo "!! non-canonical listener on :$PORT (pid $PID) — a stray or a peer session."
    echo "   If it is yours and stale:  kill $PID"
    FAIL=1
  fi
done
if [ "$(count_port 8000)" -eq 0 ]; then
  echo "!! no backend on 127.0.0.1:8000 — start one: see scripts/dev-up.sh"
  FAIL=1
fi

# ---------------------------------------------------------------------------- #
section "Frontend → backend wiring"
ENVL="$ROOT/frontend/.env.local"
if [ -f "$ENVL" ] && grep -q "^BACKEND_ORIGIN=" "$ENVL"; then
  ORIGIN="$(grep "^BACKEND_ORIGIN=" "$ENVL" | tail -1 | cut -d= -f2-)"
  echo "frontend/.env.local BACKEND_ORIGIN=$ORIGIN"
  case "$ORIGIN" in
    http://127.0.0.1:8000) echo "   ok — canonical." ;;
    *) echo "!! not the canonical http://127.0.0.1:8000 — the dashboard and the"
       echo "   extension can end up talking to two different backends."; FAIL=1 ;;
  esac
else
  echo "no BACKEND_ORIGIN override — next.config defaults to http://127.0.0.1:8000 (ok)."
fi

# ---------------------------------------------------------------------------- #
section "Celery queue coverage (the starved-queue check)"
if [ -x "$PY" ]; then
  if ! ps axo command= | (cd "$ROOT/backend" && "$PY" -m app.jobs.queue_coverage); then
    echo "   start one full-coverage worker:"
    echo "   cd backend && .venv/bin/python -m celery -A workers.celery_app worker \\"
    echo "      -l info -Q celery,interactive,standard,long,browser -c 4 --pool=threads"
    FAIL=1
  fi
else
  echo "!! backend venv missing at backend/.venv"; FAIL=1
fi
BEATS=$(ps axo command= | grep -c "[c]elery.*beat" || true)
[ "${BEATS:-0}" -gt 0 ] && echo "note: a celery beat is running — beat is OFF by owner decision; make sure that is intentional."

# ---------------------------------------------------------------------------- #
section "Backend readiness (Postgres + Redis, as the API sees them)"
READY="$(curl -s --max-time 5 http://127.0.0.1:8000/health/ready || true)"
if [ -n "$READY" ]; then
  echo "$READY"
  echo "$READY" | grep -q '"status":"ok"' || { echo "!! readiness is degraded — the API cannot reach a dependency."; FAIL=1; }
else
  echo "(backend not answering on :8000 — see above)"
fi

# ---------------------------------------------------------------------------- #
printf '\n'
if [ "$FAIL" -eq 0 ]; then
  echo "dev-doctor: healthy."
else
  echo "dev-doctor: findings above. This script never kills anything itself —"
  echo "peer sessions share this tree, so confirm a process is yours before killing it."
fi
exit "$FAIL"
