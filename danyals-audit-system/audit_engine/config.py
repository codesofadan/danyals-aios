"""Workspace-wide configuration.

Reads from environment + .env (if python-dotenv is available). All API keys
are optional; an absent key disables the corresponding integration but does
not crash the audit.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, fields
from pathlib import Path

try:
    from dotenv import load_dotenv

    _ENV_PATH = Path(__file__).resolve().parent.parent / ".env"
    if _ENV_PATH.exists():
        load_dotenv(_ENV_PATH)
except ImportError:
    pass


ROOT = Path(__file__).resolve().parent.parent
BRANDING_PATH = ROOT / "branding.json"
DATA_DIR = ROOT / "data"
AUDITS_DIR = DATA_DIR / "audits"
DB_PATH = DATA_DIR / "seo_audit.db"
SCHEMA_PATH = ROOT / "audit_engine" / "db" / "schema.sql"
CHECKLISTS_DIR = ROOT / "checklists"
KNOWLEDGE_DIR = ROOT / "knowledge"
TEMPLATES_DIR = ROOT / "templates"


@dataclass(frozen=True)
class APIKeys:
    moz_access_id: str | None
    moz_secret_key: str | None
    serper: str | None
    # `google` is the legacy/universal fallback. Per-service keys below take
    # precedence; they fall back to this value when blank. This pattern lets
    # the user provision a single unrestricted key OR three API-restricted
    # keys (preferred for least-privilege) without code changes.
    google: str | None
    google_pagespeed: str | None
    google_places: str | None
    google_crux: str | None
    google_nl: str | None
    google_credentials_path: str | None
    firecrawl: str | None
    anthropic: str | None

    @classmethod
    def from_env(cls) -> APIKeys:
        google_fallback = os.getenv("GOOGLE_API_KEY") or None
        return cls(
            moz_access_id=os.getenv("MOZ_ACCESS_ID") or None,
            moz_secret_key=os.getenv("MOZ_SECRET_KEY") or None,
            serper=os.getenv("SERPER_API_KEY") or None,
            google=google_fallback,
            google_pagespeed=os.getenv("GOOGLE_PAGESPEED_API_KEY") or google_fallback,
            google_places=os.getenv("GOOGLE_PLACES_API_KEY") or google_fallback,
            google_crux=os.getenv("GOOGLE_CRUX_API_KEY") or google_fallback,
            google_nl=os.getenv("GOOGLE_NL_API_KEY") or google_fallback,
            google_credentials_path=os.getenv("GOOGLE_APPLICATION_CREDENTIALS") or None,
            firecrawl=os.getenv("FIRECRAWL_API_KEY") or None,
            anthropic=os.getenv("ANTHROPIC_API_KEY") or None,
        )

    @property
    def has_any_google(self) -> bool:
        """True if any Google API key is configured."""
        return any([self.google, self.google_pagespeed, self.google_places, self.google_crux])


@dataclass(frozen=True)
class CrawlConfig:
    max_pages_quick: int = 20
    max_pages_full: int = 500
    max_concurrent: int = 8
    request_timeout_sec: float = 15.0
    user_agent: str = "SEO-AUDIT-OS/0.1 (+https://github.com/xegents/seo-audit-os)"
    respect_robots: bool = True
    follow_redirects: bool = True
    max_redirects: int = 5


@dataclass(frozen=True)
class Branding:
    """Client-facing branding, sourced from branding.json at the repo root.

    The JSON file is the single place to edit when the system is re-skinned
    for a new operator. Missing file or missing keys fall back to these
    defaults so the pipeline never crashes on branding.
    """

    client_name: str = "Danyal"
    brand_name: str = "Danyal's Agency"
    brand_bold: str = "SEO-AUDIT"
    brand_suffix: str = "· OS Audit Engine"
    contact_email: str = "danyal@example.com"
    website: str = ""
    accent_color: str = ""
    logo_path: str = ""

    @classmethod
    def load(cls) -> Branding:
        try:
            raw = json.loads(BRANDING_PATH.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return cls()
        allowed = {f.name for f in fields(cls)}
        clean = {
            k: v.strip()
            for k, v in raw.items()
            if k in allowed and isinstance(v, str) and v.strip()
        }
        return cls(**clean)


def get_branding() -> Branding:
    return Branding.load()


def get_keys() -> APIKeys:
    return APIKeys.from_env()


def ensure_dirs() -> None:
    """Create data/audits dirs if missing. Idempotent."""
    AUDITS_DIR.mkdir(parents=True, exist_ok=True)
