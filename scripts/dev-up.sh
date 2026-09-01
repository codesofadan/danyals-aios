#!/usr/bin/env bash
# ============================================================================
# AIOS dev-up — start the ONE canonical dev stack (macOS/Linux twin of the
# Start-*.bat trio):
#
#   backend   uvicorn on 127.0.0.1:8000         (logs: /tmp/aios-dev/backend.log)
#   worker    celery, ALL queues covered         (logs: /tmp/aios-dev/worker.log)
#   frontend  next dev on :3000                  (logs: /tmp/aios-dev/frontend.log)
#
# NO celery beat — off by owner decision; periodic jobs have visible manual triggers.
#
# Runs dev-doctor first and refuses to stack a second environment on top of a
# broken one. Override (rarely) with DEV_UP_FORCE=1.
# ============================================================================
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LOGDIR="/tmp/aios-dev"
mkdir -p "$LOGDIR"

if ! "$ROOT/scripts/dev-doctor.sh"; then
  if [ "${DEV_UP_FORCE:-0}" != "1" ]; then
    echo
    echo "dev-up: refusing to start on top of the findings above."
    echo "Fix them (or, if you know why, re-run with DEV_UP_FORCE=1)."
    exit 1
  fi
  echo "dev-up: DEV_UP_FORCE=1 — starting anyway."
fi

started=""

if ! lsof -nP -iTCP:8000 -sTCP:LISTEN >/dev/null 2>&1; then
  (cd "$ROOT/backend" && nohup .venv/bin/python -m uvicorn app.main:app \
      --host 127.0.0.1 --port 8000 >"$LOGDIR/backend.log" 2>&1 &)
  started="$started backend"
fi

if ! ps axo command= | grep -q "[c]elery.*workers.celery_app.*worker"; then
  (cd "$ROOT/backend" && nohup .venv/bin/python -m celery -A workers.celery_app worker \
      -l info -Q celery,interactive,standard,long,browser -c 4 --pool=threads \
      >"$LOGDIR/worker.log" 2>&1 &)
  started="$started worker"
fi

if ! lsof -nP -iTCP:3000 -sTCP:LISTEN >/dev/null 2>&1; then
  (cd "$ROOT/frontend" && nohup npm run dev >"$LOGDIR/frontend.log" 2>&1 &)
  started="$started frontend"
fi

echo
echo "dev-up: started:${started:- nothing (everything already running)}"
echo "  dashboard  http://localhost:3000"
echo "  api        http://127.0.0.1:8000   (pair the extension against THIS address)"
echo "  logs       tail -f $LOGDIR/{backend,worker,frontend}.log"
sleep 3
curl -s --max-time 5 http://127.0.0.1:8000/health >/dev/null \
  && echo "  backend answering." \
  || echo "  backend not answering yet — tail $LOGDIR/backend.log"
