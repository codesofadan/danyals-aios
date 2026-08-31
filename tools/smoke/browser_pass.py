#!/usr/bin/env python3
"""Does every screen RENDER, or does it merely return 200?

Every screen in this product has been checked for HTTP 200 at some point. That
proves the route exists and the server did not throw. It does not prove the page
painted, that its data arrived, or that a component blew up during hydration -
a React error boundary still returns 200, and so does a screen that renders a
confident "0" because its request failed.

So this signs in with a real browser and, per route, records: console errors,
uncaught page exceptions, HTTP >= 400 the page itself provoked, whether any
meaningful text was ever painted, and whether the app rendered one of its own
failure states.

USAGE (with the stack already running - see infra/deploy/README-deploy.md, or
RUN-LOCALLY.md for a dev stack):

    cd backend
    AIOS_USER=admin AIOS_PASSWORD='...' \
      .venv/bin/python ../tools/smoke/browser_pass.py > pass.json

    # against a different host
    WEB=https://app.example.com AIOS_USER=... AIOS_PASSWORD=... \
      .venv/bin/python ../tools/smoke/browser_pass.py

Exit status is 1 if any route produced a finding, so it can gate a deploy.
Playwright comes from the backend venv (it is already a dependency of the site
replication work); `playwright install chromium` if the browser is missing.

THREE MEASUREMENT TRAPS, all hit while writing this - do not reintroduce them:

  * `wait_until="networkidle"` NEVER FIRES on the screens that poll for job
    progress, so it turns a healthy page into a timeout. Wait for paint instead.
  * A fixed sleep measures a LOADING SKELETON when the dev server is still
    compiling the route (`next dev` compiles on first hit). The wait below is on
    painted text, with the timeout recorded rather than raised.
  * Navigating to the same URL twice to "warm it up" makes the second navigation
    return instantly, so the body gets measured before the client render runs.
    Every route here is visited exactly once.

Dev-server compile time is not a product defect. If you want numbers that mean
something, run against a production build (`npx next build && npx next start`)
on a machine that is not also running the test suites.
"""
from __future__ import annotations

import json
import os
import re
import sys

from playwright.sync_api import sync_playwright

WEB = os.environ.get("WEB", "http://127.0.0.1:3000")

ROUTES = [
    "/admin", "/admin/clients", "/admin/audit", "/admin/leads", "/admin/content",
    "/admin/content/new", "/admin/wordpress", "/admin/web2", "/admin/citations",
    "/admin/citations/queue", "/admin/policy-radar", "/admin/tasks",
    "/admin/milestones", "/admin/reports", "/admin/team", "/admin/operations",
    "/admin/cost", "/admin/vault", "/admin/settings",
]

# Not defects: dev-mode React chatter and the browser's own complaints about
# things the page does not control.
IGNORE = re.compile(
    r"Download the React DevTools|React Router Future Flag|"
    r"Warning: ReactDOM\.render|favicon\.ico|\[Fast Refresh\]",
    re.I,
)

# The app's OWN honest failure states. Finding one is not automatically a bug -
# a backend that is genuinely down should produce exactly these - but a screen
# showing one while the API is up is a real finding.
FAILURE_TEXT = re.compile(
    r"couldn't load|could not load|failed to load|something went wrong|"
    r"unable to load|application error",
    re.I,
)


def main() -> int:
    try:
        user = os.environ["AIOS_USER"]
        password = os.environ["AIOS_PASSWORD"]
    except KeyError as exc:
        print(f"set {exc.args[0]} (and AIOS_USER/AIOS_PASSWORD both)", file=sys.stderr)
        return 2

    results: list[dict[str, object]] = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(viewport={"width": 1440, "height": 900})
        page = ctx.new_page()

        page.goto(f"{WEB}/login", wait_until="domcontentloaded", timeout=150_000)
        page.wait_for_timeout(1500)
        # Select by autocomplete, not by type: the password field's `type` flips
        # to "text" behind the show/hide toggle, so `input[type=password]` is not
        # a stable selector.
        page.fill('input[autocomplete="username"]', user)
        page.fill('input[autocomplete="current-password"]', password)
        page.click("button[type=submit]")
        try:
            page.wait_for_url(re.compile(r"/(admin|team|client)"), timeout=60_000)
        except Exception:
            print(json.dumps({"fatal": "login did not navigate", "url": page.url,
                              "body": page.inner_text("body")[:400]}, indent=1))
            return 2
        print(f"signed in -> {page.url}", file=sys.stderr)

        for route in ROUTES:
            console: list[str] = []
            page_errors: list[str] = []
            bad_requests: list[str] = []

            # A FRESH PAGE PER ROUTE, sharing the context (so the session cookie
            # carries over). Listeners registered on one long-lived page are never
            # removed and close over the loop's list variables by REFERENCE, so
            # after route 2 every route's events land in the current route's lists
            # and the attribution is silently wrong. A page per route makes each
            # set of listeners die with the page it belongs to.
            page = ctx.new_page()
            page.on("console", lambda m, sink=console: sink.append(f"{m.type}: {m.text}")
                    if m.type == "error" and not IGNORE.search(m.text) else None)
            page.on("pageerror", lambda e, sink=page_errors: sink.append(str(e)))
            page.on("response", lambda r, sink=bad_requests:
                    sink.append(f"{r.status} {r.url.split('?')[0]}")
                    if r.status >= 400 and not IGNORE.search(r.url) else None)

            entry: dict[str, object] = {"route": route}
            try:
                page.goto(f"{WEB}{route}", wait_until="domcontentloaded", timeout=150_000)
                try:
                    page.wait_for_function(
                        "document.body && document.body.innerText.trim().length > 150",
                        timeout=60_000)
                    entry["painted"] = True
                except Exception:
                    entry["painted"] = False
                page.wait_for_timeout(2000)  # let late client fetches land
                body = page.inner_text("body")
                entry["chars"] = len(body.strip())
                entry["failure_text"] = sorted({m.group(0).lower() for m in FAILURE_TEXT.finditer(body)})
            except Exception as exc:  # report it, never abort the sweep
                entry["nav_error"] = f"{type(exc).__name__}: {exc}"[:300]

            entry["console_errors"] = console[:8]
            entry["page_errors"] = page_errors[:5]
            entry["bad_requests"] = sorted(set(bad_requests))[:12]
            results.append(entry)
            page.close()
            print(f"  {route}: {entry.get('chars', '-')} chars, {len(console)} console, "
                  f"{len(page_errors)} throw, {len(set(bad_requests))} http>=400",
                  file=sys.stderr)
        browser.close()

    findings = [r for r in results
                if r.get("nav_error") or not r.get("painted", True) or r.get("console_errors")
                or r.get("page_errors") or r.get("bad_requests") or r.get("failure_text")]
    print(json.dumps(results, indent=1))
    print(f"\n{len(results)} routes checked, {len(findings)} with a finding", file=sys.stderr)
    for r in findings:
        print(f"  ! {r['route']}", file=sys.stderr)
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
