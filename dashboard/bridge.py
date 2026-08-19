#!/usr/bin/env python3
"""AIOS local dashboard BRIDGE - a dumb, local-only broker between the browser and
Claude Code.

Architecture (why this file holds no token and never calls the AIOS API):

    browser (index.html)  ->  bridge.py (this)  ->  worker.py (Claude Code drives it)  ->  aios_client.py  ->  AIOS API
        127.0.0.1 only          in-memory queue        pulls + fulfills jobs               the skills client     app.qanry.com

The browser NEVER talks to the AIOS API directly and never sees the bearer token. It
only ever POSTs an *intent* ("show the content board", "run a Free audit") to this
bridge. The bridge parks that intent on an in-memory queue and waits. A separate
worker - the thing Claude Code runs - pulls pending intents, fulfils each by driving
the real skills through ``.claude/skills/_shared/aios_client.py``, and posts the JSON
result back here. The bridge then hands that result to the browser.

So every dashboard action flows THROUGH Claude Code / the skills layer, exactly as the
brief requires. This process is deliberately powerless: stdlib only, bound to
127.0.0.1, no secrets, no outbound network. Kill it and nothing leaks.

Run:  python dashboard/bridge.py            # serves the UI on http://127.0.0.1:8787
"""

from __future__ import annotations

import json
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

HOST = "127.0.0.1"
PORT = 8787
UI_FILE = Path(__file__).resolve().parent / "index.html"

# Intents the worker MAY fulfil automatically (pure reads - GET only, no spend). Any
# intent NOT on this list is a WRITE/SPEND action: the bridge marks it needs_confirm
# and the browser must resubmit with confirm=true, so a click - not the machine -
# authorises money/mutations. The mapping intent->endpoint lives in worker.py; this
# set only governs the confirm gate, so the bridge needs no knowledge of the API.
READ_INTENTS = frozenset({
    "command.center", "clients.list", "content.stats", "content.board",
    "audit.board", "audit.stats", "offpage.kpis", "policy.changes", "policy.recs",
    "team.me", "team.tasks", "milestones.list", "keyword.stats", "rank.stats",
    "competitor.stats", "onpage.stats", "localseo.stats", "billing.stats",
    "dataimport.stats", "onboarding.stats", "onboarding.runs", "reports.connection",
    "raw.get",
})

# --------------------------------------------------------------------------- #
# The job store (in-memory; a dashboard session is ephemeral by design)
# --------------------------------------------------------------------------- #
_LOCK = threading.Lock()
_JOBS: dict[str, dict] = {}
JOB_TTL_S = 900          # forget a finished job after 15 min
RESULT_WAIT_S = 90       # browser long-poll ceiling per request


def _now() -> float:
    return time.time()


def _gc() -> None:
    cutoff = _now() - JOB_TTL_S
    for jid in [k for k, v in _JOBS.items() if v.get("done_at", _now()) < cutoff and v["status"] in ("done", "error")]:
        _JOBS.pop(jid, None)


def _submit(intent: str, args: dict) -> dict:
    jid = uuid.uuid4().hex[:12]
    needs_confirm = intent not in READ_INTENTS and not bool(args.get("confirm"))
    job = {
        "id": jid,
        "intent": intent,
        "args": args,
        "status": "needs_confirm" if needs_confirm else "pending",
        "result": None,
        "created_at": _now(),
    }
    with _LOCK:
        _gc()
        _JOBS[jid] = job
    return job


def _claim_pending() -> list[dict]:
    with _LOCK:
        out = []
        for job in _JOBS.values():
            if job["status"] == "pending":
                job["status"] = "claimed"
                job["claimed_at"] = _now()
                out.append({"id": job["id"], "intent": job["intent"], "args": job["args"]})
        return out


def _fulfill(jid: str, ok: bool, data, meta: dict | None) -> bool:
    with _LOCK:
        job = _JOBS.get(jid)
        if job is None:
            return False
        job["status"] = "done" if ok else "error"
        job["result"] = {"ok": ok, "data": data, "meta": meta or {}}
        job["done_at"] = _now()
        return True


# --------------------------------------------------------------------------- #
# HTTP
# --------------------------------------------------------------------------- #
class Handler(BaseHTTPRequestHandler):
    # Quiet the default per-request stderr spam; the worker log is the signal.
    def log_message(self, *_a) -> None:
        return

    def _send(self, code: int, payload, ctype: str = "application/json") -> None:
        body = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        # Local app; lock CORS to the bridge origin only.
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _read_body(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if not length:
            return {}
        try:
            return json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            return {}

    def do_GET(self) -> None:
        route = urlparse(self.path)
        path = route.path
        if path in ("/", "/index.html"):
            if not UI_FILE.exists():
                return self._send(500, {"error": "index.html missing"})
            return self._send(200, UI_FILE.read_bytes(), "text/html; charset=utf-8")
        if path == "/api/health":
            with _LOCK:
                pending = sum(1 for j in _JOBS.values() if j["status"] in ("pending", "claimed"))
            return self._send(200, {"ok": True, "pending": pending, "ts": _now()})
        if path == "/api/pending":
            # The worker pulls here. Long-poll so it reacts instantly without busy-looping.
            deadline = _now() + 25
            while _now() < deadline:
                jobs = _claim_pending()
                if jobs:
                    return self._send(200, {"jobs": jobs})
                time.sleep(0.4)
            return self._send(200, {"jobs": []})
        if path == "/api/result":
            qs = parse_qs(route.query)
            jid = (qs.get("id") or [""])[0]
            deadline = _now() + RESULT_WAIT_S
            while _now() < deadline:
                with _LOCK:
                    job = _JOBS.get(jid)
                    if job is None:
                        return self._send(404, {"error": "unknown job id"})
                    if job["status"] in ("done", "error", "needs_confirm"):
                        return self._send(200, {"status": job["status"], "result": job["result"], "intent": job["intent"]})
                time.sleep(0.4)
            return self._send(200, {"status": "pending", "result": None})
        return self._send(404, {"error": "not found"})

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        body = self._read_body()
        if path == "/api/submit":
            intent = str(body.get("intent") or "").strip()
            if not intent:
                return self._send(400, {"error": "intent required"})
            args = body.get("args") or {}
            if not isinstance(args, dict):
                return self._send(400, {"error": "args must be an object"})
            job = _submit(intent, args)
            return self._send(200, {"id": job["id"], "status": job["status"]})
        if path == "/api/fulfill":
            jid = str(body.get("id") or "")
            ok = bool(body.get("ok"))
            if not _fulfill(jid, ok, body.get("data"), body.get("meta")):
                return self._send(404, {"error": "unknown job id"})
            return self._send(200, {"ok": True})
        return self._send(404, {"error": "not found"})


def main() -> None:
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"AIOS dashboard bridge on http://{HOST}:{PORT}  (browser -> bridge -> Claude Code worker -> skills -> API)")
    print("The bridge holds no token and never calls the API. Start the worker in another shell.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nbridge stopped")
        server.shutdown()


if __name__ == "__main__":
    main()
