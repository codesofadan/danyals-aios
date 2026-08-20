#!/usr/bin/env python3
"""LOCAL citation handoff finisher — run on YOUR machine (needs a display).

The citation bot creates a directory account + prepares the listing, but some
directories can't be auto-published (a captcha the last step re-checks, a JS category
widget, a paid-claim). Those are handed off here: this opens a REAL (headed) browser,
logs into the directory with the bot-created account, navigates to the add/edit page,
and PAUSES so you click **Publish** yourself. This is why it runs locally, not in the
hosted dashboard — the dashboard can't hold an interactive browser session.

Usage (from the repo root, with a local venv that has playwright):
    python tools/finish_citation.py                 # list the handoff queue
    python tools/finish_citation.py "Brownbook"     # open + log in, then you click Publish
    python tools/finish_citation.py --all           # walk the whole queue one by one

Credentials come from tools/citation_handoffs.json (exported from the run). Every
account shares the password there; each directory has its own alias email. Emails for
verification land in the catch-all inbox (see the file's `_mailbox` note).
"""
from __future__ import annotations
import json, sys, os, re
from pathlib import Path

HANDOFFS = Path(__file__).with_name("citation_handoffs.json")


def _load() -> list[dict]:
    if not HANDOFFS.exists():
        print(f"No handoff file at {HANDOFFS}. Export it from the run first.")
        sys.exit(1)
    data = json.loads(HANDOFFS.read_text(encoding="utf-8"))
    return [d for d in data if isinstance(d, dict) and d.get("name")]


def _list(items: list[dict]) -> None:
    print(f"\n{len(items)} citations ready to finish (log in + click Publish):\n")
    for d in items:
        print(f"  • {d['name']:26}  login={d.get('login','')}")
    print(f"\nPassword for all: {items[0].get('password','') if items else ''}")
    print('Finish one:  python tools/finish_citation.py "<name>"   |   all:  --all\n')


def _finish_one(d: dict, password: str) -> None:
    from playwright.sync_api import sync_playwright  # local import: only needed to act
    login_url = d.get("login_url") or d.get("home") or d.get("add_url")
    add_url = d.get("add_url", "")
    email = d.get("login", "")
    print(f"\n=== {d['name']} ===")
    print(f"  login: {email}  /  {password}")
    print(f"  add page: {add_url}")
    with sync_playwright() as pw:
        # HEADED so you can see + click. No proxy locally (use your own IP).
        b = pw.chromium.launch(headless=False)
        ctx = b.new_context(viewport={"width": 1440, "height": 950})
        pg = ctx.new_page()
        try:
            pg.goto(login_url, timeout=45000)
        except Exception as e:
            print("  (couldn't auto-open login — do it manually in the window)", str(e)[:60])
        # best-effort auto-fill of the login form
        for sel in ("input[type=email]", "input[name=email]", "input[name=username]", "input[name=user_email]"):
            try:
                if pg.query_selector(sel):
                    pg.fill(sel, email, timeout=3000); break
            except Exception:
                pass
        for sel in ("input[type=password]", "input[name=password]", "input[name=user_password]"):
            try:
                if pg.query_selector(sel):
                    pg.fill(sel, password, timeout=3000); break
            except Exception:
                pass
        print("\n  → The browser is open. Log in if not already, go to the add/edit page,")
        print("    fill anything missing, and click PUBLISH. Then press Enter here to close.\n")
        try:
            input()
        except (EOFError, KeyboardInterrupt):
            pg.wait_for_timeout(120000)
        b.close()


def main() -> None:
    items = _load()
    password = items[0].get("password", "") if items else ""
    args = [a for a in sys.argv[1:] if a]
    if not args:
        _list(items); return
    if args[0] == "--all":
        for d in items:
            _finish_one(d, password)
        return
    q = args[0].lower()
    matches = [d for d in items if q in d["name"].lower()]
    if not matches:
        print(f'No handoff matching "{args[0]}". Run with no args to list them.'); return
    _finish_one(matches[0], password)


if __name__ == "__main__":
    main()
