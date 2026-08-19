#!/usr/bin/env python3
"""AIOS local dashboard WORKER - the executor Claude Code drives.

This is the ONLY component that holds the bearer token and the ONLY one that touches
the AIOS API, and it touches it exactly the way the skills do: by shelling out to the
shared skills client ``.claude/skills/_shared/aios_client.py``. It pulls pending
intents off the local bridge, maps each to a skills-client invocation, and posts the
JSON result back to the bridge for the browser to render.

    bridge (/api/pending)  ->  worker  ->  aios_client.py <verb> <path>  ->  AIOS API
                               |                                              |
    bridge (/api/fulfill)  <---+------------------ JSON result --------------+

Why a worker and not "the bridge just calls the API"? Because the brief requires every
dashboard action to flow THROUGH Claude Code driving the skills - not a direct
browser->API fetch, and not a secret sitting behind a web server the browser can reach.
Claude Code runs THIS file (or a /loop of it); Claude can inspect a pending write,
apply judgement (e.g. hold a sub-threshold content draft at the review gate), and only
then let it through. Reads are mapped mechanically; writes/spends arrive pre-confirmed
by a human click (the bridge's confirm gate) and are still executed via the skills.

Auth comes from the same env the skills use:
    AIOS_BASE_URL     default http://localhost:8000/api/v1   (or AIOS_API_BASE)
    AIOS_SKILL_TOKEN  the bearer                              (or AIOS_TOKEN)

Run (Claude Code drives this):
    python dashboard/worker.py            # drain the bridge continuously
    python dashboard/worker.py --once     # drain whatever is pending once, then exit
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

BRIDGE = os.environ.get("AIOS_BRIDGE_URL", "http://127.0.0.1:8787").rstrip("/")
REPO_ROOT = Path(__file__).resolve().parents[1]
CLIENT = REPO_ROOT / ".claude" / "skills" / "_shared" / "aios_client.py"
CLIENT_TIMEOUT_S = 120  # a Free audit create returns fast; wait-job style intents are not mapped here


# --------------------------------------------------------------------------- #
# Intent -> skills-client invocation. A tuple builder returns argv for
# aios_client.py; the worker runs it and returns parsed JSON. READ intents are GETs;
# WRITE intents build a POST body from the browser-supplied (confirmed) args.
# --------------------------------------------------------------------------- #
def _get(path: str):
    return ["get", path]


def _intent_argv(intent: str, args: dict) -> list[str] | None:
    a = args or {}
    reads: dict[str, str] = {
        "command.center": "command-center",
        "clients.list": "clients?limit=100",
        "content.stats": "content/jobs/stats",
        "content.board": "content/jobs",
        "audit.board": "audits",
        "audit.stats": "audits/stats",
        "offpage.kpis": "offpage/kpis",
        "policy.changes": "policy/changes",
        "policy.recs": "policy/recommendations",
        "team.me": "me",
        "team.tasks": "tasks",
        "milestones.list": "milestones",
        "keyword.stats": "keyword-research/stats",
        "rank.stats": "rank-tracker/stats",
        "competitor.stats": "competitor-intel/stats",
        "onpage.stats": "on-page/stats",
        "localseo.stats": "local-seo/stats",
        "billing.stats": "billing/stats",
        "dataimport.stats": "data-import/stats",
        "onboarding.stats": "client-onboarding/stats",
        "onboarding.runs": "client-onboarding/runs",
        "reports.connection": "reports/connection",
    }
    if intent in reads:
        path = reads[intent]
        if intent == "content.board" and a.get("status"):
            path = f"content/jobs?status={a['status']}"
        return _get(path)

    # A guarded generic reader so the UI can reach any read endpoint the modules add
    # without a code change here. Path is browser-supplied; the client re-normalises it.
    if intent == "raw.get":
        path = str(a.get("path") or "").strip()
        return _get(path) if path else None

    # ------------------------------------------------------------------ #
    # WRITE / SPEND intents (arrive only after the bridge's human-confirm gate)
    # ------------------------------------------------------------------ #
    if intent == "audit.run":
        body = {
            "client_id": a.get("client_id", ""),
            "url": a.get("url", ""),
            "tier": a.get("tier", "Free"),
            "types": a.get("types", []),
        }
        return ["post", "audits", "--json", json.dumps(body)]

    if intent == "raw.post":
        path = str(a.get("path") or "").strip()
        if not path:
            return None
        return ["post", path, "--json", json.dumps(a.get("body") or {})]

    return None


def _run_client(argv: list[str]) -> tuple[bool, object, dict]:
    """Drive the skills client. Its stdout is JSON; its exit code is the branch signal
    (0 ok, 2 HTTP error, 3 unreachable, 5 usage)."""
    proc = subprocess.run(
        [sys.executable, str(CLIENT), *argv],
        capture_output=True,
        text=True,
        timeout=CLIENT_TIMEOUT_S,
        check=False,
    )
    raw = (proc.stdout or "").strip()
    meta = {"exit": proc.returncode, "argv": ["aios_client.py", *argv[:2]]}
    try:
        data = json.loads(raw) if raw else {}
    except json.JSONDecodeError:
        return False, {"error": "client did not return JSON", "stderr": (proc.stderr or "")[:400]}, meta
    ok = proc.returncode == 0 and not (isinstance(data, dict) and data.get("error"))
    return ok, data, meta


def _http_json(method: str, path: str, body: dict | None = None) -> dict:
    req = urllib.request.Request(f"{BRIDGE}{path}", method=method,
                                 data=json.dumps(body).encode() if body is not None else None)
    if body is not None:
        req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read() or b"{}")


def _fulfill(jid: str, ok: bool, data: object, meta: dict) -> None:
    _http_json("POST", "/api/fulfill", {"id": jid, "ok": ok, "data": data, "meta": meta})


def _handle(job: dict) -> None:
    jid, intent, args = job["id"], job["intent"], job.get("args") or {}
    argv = _intent_argv(intent, args)
    if argv is None:
        _fulfill(jid, False, {"error": f"no mapping for intent '{intent}'"}, {"intent": intent})
        print(f"  [{jid}] {intent}: UNMAPPED")
        return
    try:
        ok, data, meta = _run_client(argv)
    except subprocess.TimeoutExpired:
        _fulfill(jid, False, {"error": "skills client timed out"}, {"intent": intent})
        print(f"  [{jid}] {intent}: TIMEOUT")
        return
    meta["intent"] = intent
    _fulfill(jid, ok, data, meta)
    print(f"  [{jid}] {intent} -> {'OK' if ok else 'ERR'} (aios_client.py {' '.join(argv[:2])})")


def main() -> None:
    ap = argparse.ArgumentParser(description="AIOS dashboard worker (Claude Code drives the skills).")
    ap.add_argument("--once", action="store_true", help="drain what is pending, then exit")
    a = ap.parse_args()
    if not CLIENT.exists():
        sys.exit(f"skills client not found at {CLIENT}")
    if not (os.environ.get("AIOS_SKILL_TOKEN") or os.environ.get("AIOS_TOKEN")):
        print("WARNING: AIOS_SKILL_TOKEN not set - the skills client will refuse with exit 5.", file=sys.stderr)
    base = os.environ.get("AIOS_BASE_URL") or os.environ.get("AIOS_API_BASE") or "http://localhost:8000/api/v1"
    print(f"worker up: bridge={BRIDGE}  api_base={base}  (token from env, never printed)")
    idle_reported = False
    while True:
        try:
            jobs = _http_json("GET", "/api/pending").get("jobs", [])
        except urllib.error.URLError:
            print("bridge unreachable - is dashboard/bridge.py running?", file=sys.stderr)
            if a.once:
                return
            continue
        if jobs:
            idle_reported = False
            print(f"claimed {len(jobs)} job(s)")
            for job in jobs:
                _handle(job)
        elif a.once:
            if not jobs:
                print("nothing pending")
            return
        elif not idle_reported:
            print("idle - waiting for dashboard actions ...")
            idle_reported = True


if __name__ == "__main__":
    main()
