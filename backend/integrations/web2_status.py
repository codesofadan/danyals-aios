"""Web 2.0 API status board (Wave 4): an honest, PURE read of which Web 2.0
publishing platforms are actually wired vs missing, and WHY.

A Web 2.0 placement publishes through the platform's own API using a per-client,
per-platform credential sealed in the VAULT (one ``vault_keys`` row,
``provider = "web2:<platform>"``, ``label = client_id`` - see
``integrations.web2_credentials``). This board answers, per platform:

* is there a REAL publisher client for it at all (Medium is draft-only: its publish
  API is retired, so there is nothing to connect)?
* which credential FIELDS a client's vault blob must carry;
* how many client credentials are actually stored (CONNECTED when >= 1, else MISSING);
* the exact reason, plus the standing caveat that a live publish can still be refused
  by the EXTERNAL platform even when a credential exists.

The vault COUNTS (never secrets) are gathered by the caller and passed in, so this
stays a pure, fully unit-testable function with no DB and no decryption.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from integrations.web2_credentials import vault_provider_for
from integrations.web2_publishers import (
    DRAFT_ONLY_PLATFORMS,
    PLATFORM_CREDENTIAL_FIELDS,
    WEB2_PLATFORMS,
)

_EXTERNAL = (
    "Even with a stored credential, a live publish can still be refused by the "
    "platform (expired/revoked token, API change, rate limit, account suspension) - "
    "that is the external API's call, not a platform bug."
)


@dataclass(frozen=True)
class PlatformStatus:
    """One Web 2.0 platform's connection state for the status board."""

    platform: str
    connected: bool
    draft_only: bool
    configured_count: int
    required_fields: tuple[str, ...]
    vault_provider: str
    reason: str
    external_note: str = ""


def web2_platform_status(credential_counts: dict[str, int]) -> list[PlatformStatus]:
    """The per-platform CONNECTED/MISSING board.

    ``credential_counts`` maps a platform label -> how many client vault credentials
    are stored for it (0 when none). A platform is CONNECTED when at least one client
    credential exists; Medium is always draft-only (no live publisher to connect)."""
    statuses: list[PlatformStatus] = []
    for platform in sorted(WEB2_PLATFORMS):
        draft_only = platform in DRAFT_ONLY_PLATFORMS
        fields = PLATFORM_CREDENTIAL_FIELDS.get(platform, ())
        count = int(credential_counts.get(platform, 0))
        if draft_only:
            reason = (
                "Draft-only: this platform's publish API is retired, so a post is "
                "prepared as a draft for a human to publish by hand - there is no live "
                "API credential to connect."
            )
            connected = False
        elif count > 0:
            reason = (
                f"Connected: {count} client credential"
                f"{'s' if count != 1 else ''} stored in the vault."
            )
            connected = True
        else:
            reason = (
                "Missing: no client credential stored yet. Seal a per-client vault row "
                f"({vault_provider_for(platform)}) carrying "
                f"[{', '.join(fields) or 'the platform token'}] to enable publishing."
            )
            connected = False
        statuses.append(
            PlatformStatus(
                platform=platform,
                connected=connected,
                draft_only=draft_only,
                configured_count=count,
                required_fields=fields,
                vault_provider=vault_provider_for(platform),
                reason=reason,
                external_note="" if draft_only else _EXTERNAL,
            )
        )
    return statuses


@dataclass
class Web2Board:
    """The platform board plus a one-line rollup for the header."""

    platforms: list[PlatformStatus] = field(default_factory=list)
    connected_count: int = 0
    live_count: int = 0
    total_count: int = 0


def web2_status_board(credential_counts: dict[str, int]) -> Web2Board:
    platforms = web2_platform_status(credential_counts)
    return Web2Board(
        platforms=platforms,
        connected_count=sum(1 for p in platforms if p.connected),
        live_count=sum(1 for p in platforms if not p.draft_only),
        total_count=len(platforms),
    )
