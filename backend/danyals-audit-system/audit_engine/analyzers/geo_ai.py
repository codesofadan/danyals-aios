"""GEO / AI Search Readiness analyzers (site-wide slice).

Deterministic, free checks that complement the A5 specialist agent and the
per-page checks in ``audit_engine.analyzers.ai_search``.

Currently exposes:
  - fetch_llms_txt(client, site_url)   : HTTP GET /llms.txt
  - check_llms_txt(status, body)       : ON-106 / TECH-041 site-wide verdict
  - check_ai_crawler_directives(robots): ON-106 robots.txt slice
  - iter_geo_findings(...)             : aggregator yielding (id, owner, verdict)
"""

from __future__ import annotations

from typing import Iterable

import httpx

from audit_engine.analyzers.common import Verdict


AI_CRAWLERS = (
    "GPTBot",
    "ClaudeBot",
    "Claude-Web",
    "Google-Extended",
    "PerplexityBot",
    "ChatGPT-User",
    "OAI-SearchBot",
    "Applebot-Extended",
)


async def fetch_llms_txt(client: httpx.AsyncClient, site_url: str) -> tuple[int, str | None]:
    """Returns (status_code, body_or_none)."""
    url = site_url.rstrip("/") + "/llms.txt"
    try:
        resp = await client.get(url)
        return resp.status_code, resp.text if resp.status_code == 200 else None
    except httpx.TransportError:
        return 0, None


def check_llms_txt(status_code: int, body: str | None) -> Verdict:
    """ON-106 AI crawl readiness (llms.txt slice)."""
    if status_code == 200 and body:
        lines = body.strip().splitlines()
        return Verdict(
            "pass", 10.0, "info", 1.0,
            {"present": True, "lines": len(lines), "preview": body[:200]},
        )
    if status_code == 404:
        return Verdict(
            "warn", 6.0, "minor", 1.0,
            {"present": False, "status": 404},
            "Optional: publish /llms.txt summarizing the site for LLM consumption. Not yet a confirmed ranking signal but a fast-trending best practice in 2026.",
        )
    return Verdict("n_a", 0.0, "info", 0.5, {"status": status_code})


def check_ai_crawler_directives(robots_raw: str | None) -> Verdict:
    """ON-106 AI crawl readiness (robots directives slice)."""
    if not robots_raw:
        return Verdict(
            "warn", 5.0, "minor", 0.8,
            {"reason": "robots.txt not fetched"},
            "Add explicit Allow rules for AI crawlers (GPTBot, ClaudeBot, PerplexityBot, Google-Extended).",
        )
    raw_lower = robots_raw.lower()
    explicitly_allowed = []
    explicitly_blocked = []
    for bot in AI_CRAWLERS:
        bot_l = bot.lower()
        if f"user-agent: {bot_l}" in raw_lower:
            block = raw_lower.split(f"user-agent: {bot_l}", 1)[1].split("user-agent:", 1)[0]
            if "disallow: /" in block:
                explicitly_blocked.append(bot)
            else:
                explicitly_allowed.append(bot)
    if explicitly_blocked:
        return Verdict(
            "warn", 4.0, "major", 1.0,
            {"blocked": explicitly_blocked, "allowed": explicitly_allowed},
            f"Robots blocks AI crawlers: {explicitly_blocked}. Confirm this is intentional with the business owner.",
        )
    if not explicitly_allowed:
        return Verdict(
            "warn", 7.0, "minor", 0.9,
            {"allowed": [], "blocked": []},
            "No explicit AI crawler directives. AI crawlers default to allow; consider explicit Allow rules for clarity and to signal intent.",
        )
    return Verdict("pass", 10.0, "info", 1.0,
                   {"allowed": explicitly_allowed, "blocked": explicitly_blocked})


def iter_geo_findings(
    *,
    llms_status: int,
    llms_body: str | None,
    robots_raw: str | None,
) -> Iterable[tuple[str, str, str, Verdict]]:
    yield ("ON-106", "on-page", "A5", check_llms_txt(llms_status, llms_body))
    yield ("ON-106", "on-page", "A5", check_ai_crawler_directives(robots_raw))
