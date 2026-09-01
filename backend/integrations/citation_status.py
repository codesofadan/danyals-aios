"""Citation ENGINE status board: an honest, PURE read of which submission engines are
actually able to run, and WHY.

THE HEADLINE COMES FIRST AND IT IS THE WHITELIST. On 2026-09-01 this board reported
"3/5 connected" (counting a proxy and a solver) while ZERO directories were
machine-submittable — the binding constraint is the count of ACTIVE directory_specs
(a spec activates only after a dated human DOM check plus one submission that produced
a public listing URL), and a board that omits it flatters every other row. Engines are
transport; a directory is machine-submittable only when its spec is earned.

RETIREMENT RECORD (rows deleted from the board, story kept here — a status board is
for things that can change state, and "no key can enable an endpoint that does not
exist" is not a state):
  * Bing Places direct API — retired 2026-08-23. POST
    ssl.bing.com/webmaster/places/api/v1/locations 301s to www.bing.com and returns
    404; Bing Places API access is a partner programme (placesfeedback@microsoft.com),
    not a public write path. A key cannot enable it; Bing listings are queue work.
  * Foursquare Places direct API — retired 2026-08-23. POST api.foursquare.com/v3/places
    returns 404 (a READ endpoint returning 401 was the control, so a missing route, not
    an auth failure); additions route to community-moderated Placemaker review.
    FOURSQUARE_API_KEY remains LIVE for citation DISCOVERY (a read path) — do not
    delete the key on the strength of this retirement.

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


def citation_engine_status(
    settings: Settings,
    *,
    active_spec_count: int = 0,
    signup_spec_count: int = 0,
) -> list[EngineStatus]:
    """The per-engine board, honestly — REAL engines only (see the retirement record
    in the module docstring for the two deleted ghosts)."""
    captcha = (
        _has_secret(settings.captcha_solver_api_key)
        and settings.captcha_solver_provider not in ("", "none")
    )
    proxy = _has_secret(settings.citation_proxy_url)
    bot_installed = playwright_bot_available()
    data_axle_keyed = _has_secret(settings.data_axle_api_key)
    data_axle_priced = bool(getattr(settings, "data_axle_submits_enabled", False))
    apple = _has_secret(settings.apple_business_api_key) and bool(
        settings.apple_business_org_id
    )
    signup_mailbox = bool(settings.citation_imap_host) and bool(settings.citation_mail_domain)

    statuses: list[EngineStatus] = [
        EngineStatus(
            key="playwright_bot",
            label="Self-hosted Playwright bot (bot_fillable / captcha_assisted)",
            # Installed is necessary; an EARNED spec is what actually lets it act. A
            # board that called an install "connected" while the whitelist was empty is
            # how "3/5 connected" coexisted with zero submittable directories.
            connected=bot_installed and active_spec_count > 0,
            reason=(
                f"Installed, {active_spec_count} earned spec(s) active - those "
                "directories submit automatically; the rest route to the operator queue."
                if bot_installed and active_spec_count > 0
                else (
                    "Installed, but 0 earned specs - every bot-tier row routes to the "
                    "operator queue. Finishing a directory by hand once (and activating "
                    "its spec) is what turns this on, per directory."
                    if bot_installed
                    else "Playwright browser not found on the worker host - bot-tier "
                    "directories HOLD until it is installed."
                )
            ),
            required_config=("playwright browser (worker host)", "an ACTIVE directory spec"),
            external_note=_EXTERNAL,
        ),
        EngineStatus(
            key="data_axle",
            label="Data Axle Local Listings (aggregator API)",
            connected=data_axle_keyed and data_axle_priced,
            reason=(
                "Key + per-Add rate on file - aggregator submissions can run."
                if data_axle_keyed and data_axle_priced
                else (
                    "Blocked until a REAL per-Add rate is on file - set "
                    "DATA_AXLE_ADD_COST_ESTIMATE (O-2: the rate is published nowhere; "
                    "it takes a phone call to Data Axle). A key without a price is a "
                    "way to spend money by accident, so the engine is not built."
                    if data_axle_keyed
                    else "No DATA_AXLE_API_KEY set (and the per-Add rate is also "
                    "unconfigured - O-2). Rows on this route hold as blocked/price_unknown."
                )
            ),
            required_config=("DATA_AXLE_API_KEY", "DATA_AXLE_ADD_COST_ESTIMATE"),
            external_note=_EXTERNAL,
        ),
        EngineStatus(
            key="apple_business",
            label="Apple Business Connect (direct API)",
            connected=apple,
            reason=(
                "Key + org id configured - Apple locations can be submitted."
                if apple
                else "APPLE_BUSINESS_API_KEY / APPLE_BUSINESS_ORG_ID not set - Apple "
                "rows route to the operator queue."
            ),
            required_config=("APPLE_BUSINESS_API_KEY", "APPLE_BUSINESS_ORG_ID"),
            external_note=_EXTERNAL,
        ),
        EngineStatus(
            key="gbp",
            label="Google Business Profile (direct API)",
            # Hard-false: NO ENGINE IS WRITTEN. The catalogue row, the api tier and a
            # config key all exist and make it look wired - credentials alone cannot
            # open this route (mirrors tasks.py's _api_submitters note).
            connected=False,
            reason=(
                "No GBP engine is written; credentials alone cannot open this route. "
                "GBP rows route to the operator queue until an engine exists."
            ),
            required_config=(),
            external_note=_EXTERNAL,
        ),
        EngineStatus(
            key="signup_bot",
            label="Account-signup bot (bot:signup)",
            connected=False,
            reason=(
                "OFF pending the human loop being proven (a deliberate constraint - "
                "auto account creation + IMAP verification comes after Phases 0-3). "
                + (
                    f"Config present ({signup_spec_count} signup spec(s))."
                    if signup_mailbox
                    else "Also unconfigured: CITATION_IMAP_* / CITATION_MAIL_DOMAIN."
                )
            ),
            required_config=("CITATION_IMAP_HOST", "CITATION_MAIL_DOMAIN"),
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
    """The engine board plus the headline that actually binds."""

    engines: list[EngineStatus] = field(default_factory=list)
    connected_count: int = 0
    total_count: int = 0
    # THE binding constraint, first: how many directories a machine may submit to
    # today. Everything else on the board is transport.
    machine_submittable_directories: int = 0
    whitelist_note: str = (
        "A directory becomes machine-submittable only after a dated human DOM check "
        "and one submission that produced a public listing URL (an ACTIVE directory "
        "spec). Engines are transport; the whitelist is the constraint."
    )


def citation_engine_board(
    settings: Settings, *, active_spec_count: int = 0, signup_spec_count: int = 0
) -> EngineBoard:
    engines = citation_engine_status(
        settings,
        active_spec_count=active_spec_count,
        signup_spec_count=signup_spec_count,
    )
    return EngineBoard(
        engines=engines,
        connected_count=sum(1 for e in engines if e.connected),
        total_count=len(engines),
        machine_submittable_directories=active_spec_count,
    )
