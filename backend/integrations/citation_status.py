"""Citation ENGINE status board (Wave 4): an honest, PURE read of which submission
engines are actually configured vs missing, and WHY.

The citation-builder dispatches a queued directory to one of several engines by its
``tier``/``submit_method`` (see ``integrations.citation_submitters``): a direct API
(Bing Places / Foursquare), the self-hosted Playwright bot, an Apify actor fallback,
and a CAPTCHA solver that gates the ``captcha_assisted`` tier. When a submit "shows
failed/blocked" the first question is always "is that engine even set up?" - this
board answers it up front instead of after a paid, dead-end run.

Every status carries the EXTERNAL caveat: a CONNECTED engine can still be refused by
the provider (a revoked key, a 4xx from a moved endpoint, an actor that no longer
covers a directory). Configuration presence is necessary, not sufficient - the board
never claims a live submit will succeed, only that the credential exists.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.config import Settings


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
    bing = _has_secret(settings.bing_places_api_key)
    foursquare = _has_secret(settings.foursquare_api_key)
    apify = _has_secret(settings.apify_api_token) and bool(settings.apify_citation_actor_id)
    captcha = (
        _has_secret(settings.captcha_solver_api_key)
        and settings.captcha_solver_provider not in ("", "none")
    )
    proxy = _has_secret(settings.citation_proxy_url)

    statuses: list[EngineStatus] = [
        EngineStatus(
            key="bing_places",
            label="Bing Places for Business (direct API)",
            connected=bing,
            reason=(
                "API key configured - direct-API submits are enabled."
                if bing
                else "No BING_PLACES_API_KEY set - direct Bing submits fall through to "
                "the Apify fallback (if configured)."
            ),
            required_config=("BING_PLACES_API_KEY",),
            external_note=_EXTERNAL,
        ),
        EngineStatus(
            key="foursquare",
            label="Foursquare Places (direct API)",
            connected=foursquare,
            reason=(
                "API key configured - direct-API submits are enabled."
                if foursquare
                else "No FOURSQUARE_API_KEY set - Foursquare submits fall through to the "
                "Apify fallback (if configured)."
            ),
            required_config=("FOURSQUARE_API_KEY",),
            external_note=_EXTERNAL,
        ),
        EngineStatus(
            key="apify",
            label="Apify Citation Builder (fallback engine)",
            connected=apify,
            reason=(
                "Token + actor id configured - the fallback engine can build a directory "
                "the self-hosted bot cannot reach."
                if apify
                else "Missing APIFY_API_TOKEN and/or APIFY_CITATION_ACTOR_ID - a directory "
                "with no other engine HOLDS as 'blocked', it is not force-failed."
            ),
            required_config=("APIFY_API_TOKEN", "APIFY_CITATION_ACTOR_ID"),
            external_note=(
                "The Apify actor only covers a fixed 48-directory network; a catalog "
                "name outside it is reported honestly, never billed for nothing. " + _EXTERNAL
            ),
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
            # The browser automation extra is an optional dependency, not a key - it is
            # absent in most deploys until explicitly installed, so this is honestly
            # reported as an install/ops step rather than a missing credential.
            connected=False,
            reason=(
                "Requires the Playwright browser extra installed on the worker host; "
                "until then bot_fillable directories route to the Apify fallback."
            ),
            required_config=("playwright browser extra (worker host)",),
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
