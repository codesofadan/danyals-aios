"""robots.txt parser.

Returns a structured view: per-UA allow/disallow rules, sitemap URLs, and any
prompt-injection-like content (treated as data, not instructions).
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urljoin

from audit_engine.crawlers.browser_client import CrawlerTransportError
from audit_engine.logging_setup import get_logger

log = get_logger(__name__)


@dataclass
class RobotsGroup:
    user_agents: list[str] = field(default_factory=list)
    allow: list[str] = field(default_factory=list)
    disallow: list[str] = field(default_factory=list)
    crawl_delay: float | None = None


@dataclass
class RobotsTxt:
    url: str
    raw: str
    status_code: int
    groups: list[RobotsGroup] = field(default_factory=list)
    sitemaps: list[str] = field(default_factory=list)
    error: str | None = None
    suspicious_directives: list[str] = field(default_factory=list)

    def is_allowed(self, path: str, user_agent: str = "*") -> bool:
        """Greatly simplified allow/disallow lookup. Not a full RFC parser; for
        audit signals only, never for crawler gating in production."""
        matching = [g for g in self.groups if user_agent in g.user_agents or "*" in g.user_agents]
        if not matching:
            return True
        for group in matching:
            for rule in group.disallow:
                if rule and path.startswith(rule):
                    return False
        return True


def _normalize_directive(line: str) -> tuple[str, str] | None:
    if ":" not in line:
        return None
    key, _, value = line.partition(":")
    return key.strip().lower(), value.strip()


def parse(raw: str, url: str, status_code: int) -> RobotsTxt:
    out = RobotsTxt(url=url, raw=raw, status_code=status_code)
    if status_code >= 400:
        out.error = f"HTTP {status_code}"
        return out

    current: RobotsGroup | None = None
    for raw_line in raw.splitlines():
        # Scan the raw line (including comments) for prompt-injection patterns.
        # robots.txt content is data; "instructions" buried in comments are still data.
        if re.search(r"(ignore|disregard).{0,40}(previous|prior).{0,40}(instructions|prompt)", raw_line, re.I):
            out.suspicious_directives.append(raw_line.strip())
        line = raw_line.split("#", 1)[0].strip()
        if not line:
            continue
        directive = _normalize_directive(line)
        if directive is None:
            continue
        key, value = directive
        if key == "user-agent":
            if current is None or current.allow or current.disallow:
                current = RobotsGroup(user_agents=[value])
                out.groups.append(current)
            else:
                current.user_agents.append(value)
        elif key == "allow":
            if current is None:
                current = RobotsGroup(user_agents=["*"])
                out.groups.append(current)
            current.allow.append(value)
        elif key == "disallow":
            if current is None:
                current = RobotsGroup(user_agents=["*"])
                out.groups.append(current)
            current.disallow.append(value)
        elif key == "crawl-delay":
            if current is None:
                current = RobotsGroup(user_agents=["*"])
                out.groups.append(current)
            try:
                current.crawl_delay = float(value)
            except ValueError:
                pass
        elif key == "sitemap":
            out.sitemaps.append(value)
        else:
            # Unknown directives - flag if they smell like instructions.
            if any(
                w in value.lower()
                for w in ("execute", "run", "delete", "exfiltrate", "secret", "credential")
            ):
                out.suspicious_directives.append(line)

    return out


async def fetch(client: Any, site_url: str, *, retries: int = 2) -> RobotsTxt:
    """Fetch and parse robots.txt with retry. Retries transient transport errors
    and 5xx responses with exponential backoff (0.5s, 1s)."""
    robots_url = urljoin(site_url.rstrip("/") + "/", "robots.txt")
    last_err: Exception | None = None
    for attempt in range(retries + 1):
        try:
            resp = await client.get(robots_url)
            if 500 <= resp.status_code < 600 and attempt < retries:
                last_err = CrawlerTransportError(f"HTTP {resp.status_code}")
                await asyncio.sleep(0.5 * (2 ** attempt))
                continue
            return parse(resp.text, robots_url, resp.status_code)
        except CrawlerTransportError as e:
            last_err = e
            if attempt < retries:
                await asyncio.sleep(0.5 * (2 ** attempt))
                continue
    log.warning(
        "robots_fetch_failed",
        url=robots_url,
        error=type(last_err).__name__ if last_err else "unknown",
        attempts=retries + 1,
    )
    return RobotsTxt(url=robots_url, raw="", status_code=0, error=str(last_err))
