#!/usr/bin/env python3
"""Shared AIOS backend API client for the aios-seo skills.

Every skill calls the backend through THIS one script (not ad-hoc curl) so the call
is consistent, testable, and never leaks the token. It is RUN, not read: only its
JSON stdout enters the skill's context (progressive disclosure).

Auth + base URL come from the environment (the P9-1 skill-token gateway
authenticates the bearer):

    AIOS_BASE_URL     the API base, default http://localhost:8000/api/v1
                      (falls back to AIOS_API_BASE if AIOS_BASE_URL is unset)
    AIOS_SKILL_TOKEN  the skill bearer token issued by the gateway
                      (falls back to AIOS_TOKEN if AIOS_SKILL_TOKEN is unset)

The token is ONLY ever set as an Authorization header - it is NEVER printed or
logged. Every response is printed as JSON on stdout. Exit codes are distinct so a
skill's Decision points can branch on them:

    0  ok
    2  HTTP error the API returned (401/403/404/409/... -> operator-readable reason)
    3  transport error (cannot reach the API)
    4  wait timed out before the job reached a terminal state
    5  usage / local error (missing token, no matching client, bad JSON body)

Stdlib only (urllib) so it needs no install on the client's box. Forward-slash
paths work on the Windows dev box and the Linux VPS alike.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

# --------------------------------------------------------------------------- #
# Config (documented constants - no magic numbers)
# --------------------------------------------------------------------------- #
BASE = (
    os.environ.get("AIOS_BASE_URL")
    or os.environ.get("AIOS_API_BASE")
    or "http://localhost:8000/api/v1"
).rstrip("/")
TOKEN = os.environ.get("AIOS_SKILL_TOKEN") or os.environ.get("AIOS_TOKEN", "")

# The content pipeline (research -> draft -> QA) runs in minutes, not seconds, so
# poll gently and give it comfortably more than the backend content task_time_limit.
POLL_INTERVAL_S = 5        # seconds between status polls
DEFAULT_TIMEOUT_S = 900    # 15 min ceiling for wait-job
REQUEST_TIMEOUT_S = 30     # per-request socket timeout
CLIENT_PAGE_SIZE = 100     # page size when scanning /clients for a name match
CLIENT_MAX_PAGES = 20      # scan at most this many pages before giving up

# A content job is "done moving" (for wait-job) at any of these statuses.
TERMINAL = frozenset({"needs_review", "failed", "rejected", "done"})
# The rich reviewer columns exposed by GET /content/jobs/{code}/{column}.
RICH_COLUMNS = ("qa", "draft", "schema", "keywords")

# HTTP status -> the reason a skill surfaces to the operator.
_HTTP_REASON = {
    400: "bad request (check the inputs)",
    401: "unauthenticated (check AIOS_SKILL_TOKEN)",
    403: "forbidden (the token's role lacks the required permission)",
    404: "not found (client or job code)",
    409: "conflict (the job changed or is not awaiting review)",
    422: "unprocessable (a field failed validation)",
    429: "rate limited (skill-token gateway throttle)",
}


def _fail(payload: dict, code: int) -> None:
    """Print a structured error to stdout and exit with a branchable code."""
    print(json.dumps(payload))
    sys.exit(code)


def _require_token() -> None:
    if not TOKEN:
        _fail(
            {"error": "no token: set AIOS_SKILL_TOKEN (or AIOS_TOKEN) in the environment"},
            5,
        )


# --------------------------------------------------------------------------- #
# Transport (solve, don't punt: every failure maps to a clear message)
# --------------------------------------------------------------------------- #
def _req(method: str, path: str, body: dict | None = None):
    url = f"{BASE}{path}"
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Authorization", f"Bearer {TOKEN}")  # header only, never logged
    req.add_header("Accept", "application/json")
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT_S) as resp:
            raw = resp.read() or b""
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        reason = _HTTP_REASON.get(exc.code, exc.reason or "http error")
        detail = ""
        try:
            detail = json.loads(exc.read() or b"{}").get("detail", "")
        except Exception:  # noqa: BLE001 - detail is best-effort context only
            detail = ""
        _fail({"error": reason, "status": exc.code, "detail": detail, "path": path}, 2)
    except urllib.error.URLError as exc:
        _fail({"error": f"cannot reach the API at {BASE}: {exc.reason}", "path": path}, 3)


# --------------------------------------------------------------------------- #
# Generic verbs (any /api/v1 path)
# --------------------------------------------------------------------------- #
def cmd_get(a: argparse.Namespace) -> None:
    print(json.dumps(_req("GET", _norm(a.path))))


def cmd_post(a: argparse.Namespace) -> None:
    print(json.dumps(_req("POST", _norm(a.path), _parse_json_body(a.json))))


def cmd_patch(a: argparse.Namespace) -> None:
    """A partial update of any /api/v1 path (mirrors POST: bearer header, --json
    body, the same HTTP error/exit-code mapping). Skills that edit-in-place -
    /upsells, /tasks/{id}/assign-task, the content PATCH - reach the backend
    through THIS verb rather than an ad-hoc curl."""
    print(json.dumps(_req("PATCH", _norm(a.path), _parse_json_body(a.json))))


def _parse_json_body(raw: str) -> dict | None:
    """Parse a ``--json`` request body, or ``None`` when omitted. A malformed body
    is a local usage error (exit 5), never a silent empty POST/PATCH."""
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        _fail({"error": f"--json is not valid JSON: {exc}"}, 5)
        return None  # unreachable (_fail exits); satisfies the type checker


def _norm(path: str) -> str:
    """Accept a path with or without the leading slash."""
    return path if path.startswith("/") else f"/{path}"


# --------------------------------------------------------------------------- #
# Client resolution + fresh context (grounding step)
# --------------------------------------------------------------------------- #
def cmd_resolve_client(a: argparse.Namespace) -> None:
    """Match a client by name (case-insensitive, exact then substring) and return
    its id plus fresh context + freshness health. GET /clients is not searchable, so
    we page through it and match locally; the backend NEVER accepts an invented id."""
    wanted = a.client.strip().lower()
    exact: dict | None = None
    partial: dict | None = None
    for page in range(CLIENT_MAX_PAGES):
        offset = page * CLIENT_PAGE_SIZE
        rows = _req("GET", f"/clients?limit={CLIENT_PAGE_SIZE}&offset={offset}")
        if not rows:
            break
        for row in rows:
            name = str(row.get("name", "")).strip().lower()
            if name == wanted:
                exact = row
                break
            if partial is None and wanted in name:
                partial = row
        if exact is not None or len(rows) < CLIENT_PAGE_SIZE:
            break
    match = exact or partial
    if match is None:
        _fail({"error": f"no client matches '{a.client}'", "client": a.client}, 5)
    cid = str(match.get("id"))
    ctx = _req("GET", f"/context/client/{cid}")
    health = _req("GET", f"/context/client/{cid}/health")
    print(
        json.dumps(
            {
                "client_id": cid,
                "client_name": match.get("name"),
                "match": "exact" if exact is not None else "partial",
                "context": ctx,
                "health": health,
            }
        )
    )


# --------------------------------------------------------------------------- #
# Content jobs
# --------------------------------------------------------------------------- #
def cmd_create_job(a: argparse.Namespace) -> None:
    """POST /content/jobs. The server RESOLVES framework (Auto) + schema_type +
    source_pack; do not try to set them here beyond the page_type + topic + target."""
    row = _req(
        "POST",
        "/content/jobs",
        {
            "client_id": a.client_id,
            "page_type": a.page_type,
            "topic": a.topic,
            "framework": a.framework,
            "target": a.target,
        },
    )
    print(json.dumps({"code": row.get("id"), "status": row.get("status"), "job": row}))


def cmd_wait_job(a: argparse.Namespace) -> None:
    """Poll GET /content/jobs/{code} until the status is terminal (or timeout).
    The worker owns queued->drafting->needs_review; this never forces a transition."""
    deadline = time.time() + a.timeout
    last: dict = {}
    while time.time() < deadline:
        last = _req("GET", f"/content/jobs/{a.code}")
        status = str(last.get("status", ""))
        if status in TERMINAL:
            print(json.dumps({"code": a.code, "status": status, "job": last}))
            return
        time.sleep(POLL_INTERVAL_S)
    _fail(
        {
            "code": a.code,
            "status": "timeout",
            "last_status": last.get("status"),
            "waited_s": a.timeout,
        },
        4,
    )


def cmd_fetch_job(a: argparse.Namespace) -> None:
    """Bundle the reviewer's rich columns: qa (the 14-dim scorecard), draft
    (markdown), schema (JSON-LD), keywords (keyword_map). One call per column."""
    columns = a.columns.split(",") if a.columns else list(RICH_COLUMNS)
    out: dict = {"code": a.code}
    for col in columns:
        col = col.strip()
        if col not in RICH_COLUMNS:
            _fail({"error": f"unknown rich column '{col}'", "valid": list(RICH_COLUMNS)}, 5)
        payload = _req("GET", f"/content/jobs/{a.code}/{col}")
        out[col] = payload.get(col)
    print(json.dumps(out))


def cmd_list_jobs(a: argparse.Namespace) -> None:
    q = []
    if a.client:
        q.append(f"client={urllib.parse.quote(a.client)}")
    if a.status:
        q.append(f"status={urllib.parse.quote(a.status)}")
    qs = ("?" + "&".join(q)) if q else ""
    print(json.dumps(_req("GET", f"/content/jobs{qs}")))


def cmd_stats(_a: argparse.Namespace) -> None:
    print(json.dumps(_req("GET", "/content/jobs/stats")))


def cmd_review(a: argparse.Namespace) -> None:
    """POST /content/jobs/{code}/review. approve|edit|reject only. LEAD-only server
    side; approve enqueues publish and the DB re-checks the QA gate (invariant #12)."""
    row = _req("POST", f"/content/jobs/{a.code}/review", {"action": a.action})
    print(json.dumps({"code": row.get("id"), "status": row.get("status"), "job": row}))


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="AIOS backend client for the aios-seo skills.")
    sub = p.add_subparsers(dest="cmd", required=True)

    g = sub.add_parser("get", help="authenticated GET of any /api/v1 path")
    g.add_argument("path")
    g.set_defaults(fn=cmd_get)

    po = sub.add_parser("post", help="authenticated POST of any /api/v1 path")
    po.add_argument("path")
    po.add_argument("--json", default="", help="JSON request body")
    po.set_defaults(fn=cmd_post)

    pa = sub.add_parser("patch", help="authenticated PATCH (partial update) of any /api/v1 path")
    pa.add_argument("path")
    pa.add_argument("--json", default="", help="JSON request body")
    pa.set_defaults(fn=cmd_patch)

    rc = sub.add_parser("resolve-client", help="match a client by name -> id + fresh context + health")
    rc.add_argument("--client", required=True)
    rc.set_defaults(fn=cmd_resolve_client)

    cj = sub.add_parser("create-job", help="POST /content/jobs")
    cj.add_argument("--client-id", dest="client_id", required=True)
    cj.add_argument("--page-type", dest="page_type", required=True, choices=["service", "blog", "local"])
    cj.add_argument("--topic", required=True)
    cj.add_argument("--framework", default="Auto")
    cj.add_argument("--target", default="WordPress", choices=["WordPress", "PDF/Markdown"])
    cj.set_defaults(fn=cmd_create_job)

    w = sub.add_parser("wait-job", help="poll GET /content/jobs/{code} until terminal")
    w.add_argument("--code", required=True)
    w.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT_S)
    w.set_defaults(fn=cmd_wait_job)

    f = sub.add_parser("fetch-job", help="GET the qa/draft/schema/keywords rich columns")
    f.add_argument("--code", required=True)
    f.add_argument("--columns", default="", help="comma list subset of qa,draft,schema,keywords")
    f.set_defaults(fn=cmd_fetch_job)

    lj = sub.add_parser("list-jobs", help="GET /content/jobs")
    lj.add_argument("--client", default="", help="filter by client_id")
    lj.add_argument("--status", default="", help="filter by status")
    lj.set_defaults(fn=cmd_list_jobs)

    st = sub.add_parser("stats", help="GET /content/jobs/stats")
    st.set_defaults(fn=cmd_stats)

    rv = sub.add_parser("review", help="POST /content/jobs/{code}/review (LEAD-only)")
    rv.add_argument("--code", required=True)
    rv.add_argument("--action", required=True, choices=["approve", "edit", "reject"])
    rv.set_defaults(fn=cmd_review)

    return p


def main() -> None:
    args = _build_parser().parse_args()
    # stats needs no token check? It still calls the API -> require the token.
    _require_token()
    args.fn(args)


if __name__ == "__main__":
    main()
