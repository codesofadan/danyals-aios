"""Citation ENGINE status board: an honest, PURE read of which submission engines are
actually able to run, and WHY.

THE HEADLINE COMES FIRST AND IT IS THE WHITELIST. On 2026-09-01 this board reported
"3/5 connected" (counting a proxy and a solver) while ZERO directories were
machine-submittable — the binding constraint is the count of ACTIVE directory_specs
(a spec activates only after a dated human DOM check plus one submission that produced
a public listing URL), and a board that omits it flatters every other row. Engines are
transport; the constraint is what a machine may honestly do.

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
  * Playwright form bot — retired 2026-09-05 (off-page redesign Phase 3, plan C1). The
    engine shipped with stealth launch args, fingerprint masking, human-cadence typing,
    a residential proxy and live CapMonster CAPTCHA solving — anti-abuse evasion this
    platform has ruled out. Route B is retired with it (0132); bot_fillable and
    captcha_assisted directories are HUMAN work in the operator queue, and an earned
    directory spec now powers the extension's autofill there instead of a bot. The
    board's `human_queue` lane states this rather than pretending a bot lane is merely
    unconfigured.
  * CAPTCHA solver (CapSolver/CapMonster) + submission proxy — retired with the bot.
    A CAPTCHA is a workflow boundary the operator clears themselves; a directory that
    needs a proxy to look human is defended, and a defended directory is queue work.
  * Account-signup bot (bot:signup) — retired with the bot; it inherited the same
    anti-detection wholesale and no catalogue row ever routed to it. Directory
    accounts are created by the operator during queue work and sealed into
    `citation_accounts`.

Every remaining status carries the EXTERNAL caveat: a CONNECTED engine can still be
refused by the provider (a revoked key, a 4xx from a moved endpoint). Configuration
presence is necessary, not sufficient - the board never claims a live submit will
succeed, only that the credential exists.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.config import Settings


@dataclass(frozen=True)
class EngineStatus:
    """One submission lane's state for the status board."""

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
) -> list[EngineStatus]:
    """The per-lane board, honestly — the human queue stated as what it is (the retired
    bot's honest successor, not an unconfigured engine), then the REAL API engines."""
    data_axle_keyed = _has_secret(settings.data_axle_api_key)
    data_axle_priced = bool(getattr(settings, "data_axle_submits_enabled", False))
    apple = _has_secret(settings.apple_business_api_key) and bool(
        settings.apple_business_org_id
    )

    statuses: list[EngineStatus] = [
        EngineStatus(
            key="human_queue",
            label="Operator queue + Chrome extension (form directories)",
            # Always available: this lane IS the product for bot_fillable /
            # captcha_assisted directories now that the Playwright bot is retired.
            # No configuration can switch it off, so `connected` is a statement of
            # design, not of a credential.
            connected=True,
            reason=(
                "The Playwright form bot is retired (2026-09-05) - every form-tier "
                f"directory routes to the operator queue. {active_spec_count} earned "
                "spec(s) power extension autofill there; the operator always reviews "
                "and submits in their own browser."
            ),
            required_config=(),
            external_note=(
                "A directory can still refuse a human submission (paid listings, "
                "phone/postcard verification) - the queue records those as blocked "
                "with the reason."
            ),
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
    ]
    return statuses


@dataclass
class EngineBoard:
    """The engine board plus the headline that actually binds."""

    engines: list[EngineStatus] = field(default_factory=list)
    connected_count: int = 0
    total_count: int = 0
    # The count of ACTIVE earned specs. Since the bot's retirement this no longer means
    # "a machine submits here" - it means the extension can AUTOFILL here while the
    # operator submits. The response key is contract-stable; the note below carries the
    # honest semantics.
    machine_submittable_directories: int = 0
    whitelist_note: str = (
        "The Playwright form bot is retired: NO machine submits a directory form. An "
        "ACTIVE directory spec (earned by a dated human DOM check plus one submission "
        "that produced a public listing URL) now powers extension AUTOFILL in the "
        "operator queue - the operator reviews and submits in their own browser."
    )


def citation_engine_board(
    settings: Settings, *, active_spec_count: int = 0
) -> EngineBoard:
    engines = citation_engine_status(settings, active_spec_count=active_spec_count)
    return EngineBoard(
        engines=engines,
        connected_count=sum(1 for e in engines if e.connected),
        total_count=len(engines),
        machine_submittable_directories=active_spec_count,
    )
