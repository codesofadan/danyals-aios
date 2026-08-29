"""Citation ENGINE status board (Wave 4): an honest, PURE read of which submission
engines are actually configured vs missing, and WHY.

The citation-builder dispatches a queued directory to one of several engines by its
``tier``/``submit_method`` (see ``integrations.citation_submitters``): a direct API
(Bing Places / Foursquare), the self-hosted Playwright bot, and a CAPTCHA solver
that gates the ``captcha_assisted`` tier. When a submit "shows
failed/blocked" the first question is always "is that engine even set up?" - this
board answers it up front instead of after a paid, dead-end run.

Every status carries the EXTERNAL caveat: a CONNECTED engine can still be refused by
the provider (a revoked key, a 4xx from a moved endpoint, an actor that no longer
covers a directory). Configuration presence is necessary, not sufficient - the board
never claims a live submit will succeed, only that the credential exists.
"""

from __future__ import annotations

import importlib.util
import os
from dataclasses import dataclass, field
from pathlib import Path

from app.config import Settings


def playwright_bot_available() -> bool:
    """True when the Playwright package is importable AND a Chromium browser build is
    present on the host. Both are baked into the worker image (``backend/Dockerfile``
    installs the ``.[automation]`` extra + ``playwright install chromium``); this probe
    stays honest if that ever fails, degrading the bot to a 'blocked' status rather than
    crashing a submit at runtime. Pure + side-effect-free (never launches a browser)."""
    if importlib.util.find_spec("playwright") is None:
        return False
    candidates: list[Path] = []
    root = os.environ.get("PLAYWRIGHT_BROWSERS_PATH", "").strip()
    if root:
        candidates.append(Path(root))
    home = Path.home()
    candidates += [
        home / ".cache" / "ms-playwright",  # Linux default
        home / "AppData" / "Local" / "ms-playwright",  # Windows default
        home / "Library" / "Caches" / "ms-playwright",  # macOS default
    ]
    for base in candidates:
        try:
            if base.is_dir() and any(base.glob("chromium-*")):
                return True
        except OSError:
            continue
    return False


@dataclass(frozen=True)
class EngineStatus:
    """One submission engine's configuration state for the status board."""

    key: str
    label: str
    connected: bool
    reason: str
    required_config: tuple[str, ...] = ()
    external_note: str = ""


# The shared caveat every engine carries - configuration is necessary, not sufficient.
_EXTERNAL = (
    "Even when connected, a live submit can still be refused by the provider "
    "(revoked/invalid key, a moved endpoint, rate limits) - that is the external "
    "API's call, not a platform bug."
)


def _has_secret(value: object) -> bool:
    """True when a ``SecretStr | None`` (or plain str) setting holds a non-empty value.
    A blank ``SecretStr('')`` counts as missing, mirroring ``validate_settings``."""
    if value is None:
        return False
    getter = getattr(value, "get_secret_value", None)
    if callable(getter):
        return bool(getter())
    return bool(value)


def citation_engine_status(settings: Settings) -> list[EngineStatus]:
    """The per-engine CONNECTED/MISSING board for the citation-builder, honestly."""
    captcha = (
        _has_secret(settings.captcha_solver_api_key)
        and settings.captcha_solver_provider not in ("", "none")
    )
    proxy = _has_secret(settings.citation_proxy_url)

    statuses: list[EngineStatus] = [
        # RETIRED, and reported as retired rather than removed - an operator who set
        # BING_PLACES_API_KEY or expected a Foursquare submit deserves to be told WHY it
        # stopped, not to find the row silently gone. `connected` is hard-False: no key
        # can enable an endpoint that does not exist, so this must never read as MISSING
        # (a missing key implies "set it and it works", which is the lie being removed).
        EngineStatus(
            key="bing_places",
            label="Bing Places for Business (direct API) - RETIRED",
            connected=False,
            reason=(
                "Retired 2026-08-23: the coded write endpoint "
                "POST ssl.bing.com/webmaster/places/api/v1/locations 301s to www.bing.com "
                "and returns 404. Bing Places API access is a partner programme reached "
                "via placesfeedback@microsoft.com, not a public write path. Setting a key "
                "cannot enable this; Bing listings are a human-queue item."
            ),
            required_config=(),
            external_note=_EXTERNAL,
        ),
        EngineStatus(
            key="foursquare",
            label="Foursquare Places (direct API) - RETIRED",
            connected=False,
            reason=(
                "Retired 2026-08-23: POST api.foursquare.com/v3/places returns 404 "
                "\"Endpoint '/v3/places' not found\", and the current host has no write "
                "path either (a READ endpoint returning 401 is the control, so this is a "
                "missing route, not an auth failure). Foursquare routes place additions "
                "to community-moderated Placemaker review. FOURSQUARE_API_KEY is still "
                "used - by citation DISCOVERY, which reads."
            ),
            required_config=(),
            external_note=_EXTERNAL,
        ),
        EngineStatus(
            key="captcha_solver",
            label=f"CAPTCHA solver ({settings.captcha_solver_provider or 'none'})",
            connected=captcha,
            reason=(
                "Solver key configured - captcha_assisted directories can be driven."
                if captcha
                else "No CAPTCHA_SOLVER_API_KEY set - captcha_assisted directories cannot "
                "be auto-solved; they hold for manual handling."
            ),
            required_config=("CAPTCHA_SOLVER_PROVIDER", "CAPTCHA_SOLVER_API_KEY"),
            external_note=_EXTERNAL,
        ),
        EngineStatus(
            key="playwright_bot",
            label="Self-hosted Playwright bot (bot_fillable)",
            # The browser automation extra is an install/ops capability, not a key -
            # probed live on the worker host (import + a Chromium build present).
            connected=playwright_bot_available(),
            reason=(
                "Playwright + Chromium present on the worker - bot_fillable directories "
                "can be auto-filled and submitted."
                if playwright_bot_available()
                else "Playwright browser not found on the worker host - bot_fillable "
                "directories HOLD as 'blocked' until it is installed."
            ),
            required_config=("playwright browser (worker host)",),
            external_note=_EXTERNAL,
        ),
        EngineStatus(
            key="proxy",
            label="Submission proxy (optional)",
            connected=proxy,
            reason=(
                "Proxy configured - bot submissions egress through it."
                if proxy
                else "No CITATION_PROXY_URL set - bot submissions use the worker's own IP "
                "(fine for low volume; a proxy reduces block rates at scale)."
            ),
            required_config=("CITATION_PROXY_URL",),
        ),
    ]
    return statuses


@dataclass
class EngineBoard:
    """The engine board plus a one-line rollup for the header."""

    engines: list[EngineStatus] = field(default_factory=list)
    connected_count: int = 0
    total_count: int = 0


def citation_engine_board(settings: Settings) -> EngineBoard:
    engines = citation_engine_status(settings)
    return EngineBoard(
        engines=engines,
        connected_count=sum(1 for e in engines if e.connected),
        total_count=len(engines),
    )
