"""What a target WordPress site can actually do, read from the plugin's /ping (P6.4).

`resolve_editor_mode` takes `elementor_available` and its docstring has always said
where that should come from: "a later phase can probe the target site's active-plugin
list instead ... without this function changing". This is that phase. The resolver is
untouched; this is the thing that finally answers its question with evidence rather
than with `settings.content_elementor_enabled`, which is an operator's guess about a
site none of us has looked at.

UNKNOWN IS NOT FALSE, and this is the whole compatibility design.

Plugin 1.7.0 is installed on real client sites right now and its /ping carries no
`capabilities` key. Reading that absence as "Elementor is not installed" would silently
downgrade every one of those sites from Elementor to Gutenberg the moment this shipped -
a fleet-wide regression, invisible, caused by an upgrade to the platform rather than to
the site. So absence resolves to UNKNOWN, and unknown falls back to the configured
default exactly as before. A site only changes behaviour once it can actually tell us
something.

THE META-KEY LIST IS THE PART THAT PREVENTS A FALSE SUCCESS. WordPress silently drops a
REST write to a meta key not registered with `show_in_rest`: 200, with the OLD value
still in the response. `WordPressClient.update_post` already documents this and tells
the caller to verify. Now the caller can do better than verify after the fact - it can
decline to write the key at all and report it HELD, which is an honest outcome rather
than a success that quietly did nothing.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# Post types we ever write meta for.
POST_TYPES: tuple[str, ...] = ("post", "page")


@dataclass(frozen=True)
class SiteCapabilities:
    """What one site reported. ``known`` is False for a plugin too old to answer."""

    known: bool = False
    plugin_version: str = ""
    wp_version: str = ""
    theme_name: str = ""
    theme_stylesheet: str = ""
    elementor: bool = False
    elementor_version: str = ""
    gutenberg: bool = False
    registered_meta: dict[str, frozenset[str]] = field(default_factory=dict)
    notes: tuple[str, ...] = ()

    def elementor_available(self, *, configured_default: bool) -> bool:
        """Whether to render with Elementor.

        ``configured_default`` is `settings.content_elementor_enabled` - what the
        operator asserted. It is used ONLY when the site could not tell us, never to
        override a site that did.
        """
        return self.elementor if self.known else configured_default

    def meta_plan(self, keys: list[str], *, post_type: str = "post") -> MetaPlan:
        """Split ``keys`` into what this site will accept and what it will silently drop.

        With no capability report, nothing is claimed either way: every key comes back
        `unverified`. Reporting them as writable would be a guess, and reporting them
        as held would stop writes that probably work.
        """
        wanted = list(dict.fromkeys(k for k in keys if k))
        if not self.known:
            return MetaPlan(unverified=tuple(wanted))
        registered = self.registered_meta.get(post_type, frozenset())
        return MetaPlan(
            writable=tuple(k for k in wanted if k in registered),
            held=tuple(k for k in wanted if k not in registered),
        )


@dataclass(frozen=True)
class MetaPlan:
    """Which meta keys to send, which to withhold, and which nobody can vouch for."""

    writable: tuple[str, ...] = ()
    held: tuple[str, ...] = ()
    unverified: tuple[str, ...] = ()

    @property
    def to_send(self) -> tuple[str, ...]:
        """Unverified keys ARE sent. The site may well accept them, and withholding
        on a maybe would break every site running an older plugin. They are sent and
        then verified by re-reading, which is the contract `update_post` already
        documents."""
        return (*self.writable, *self.unverified)

    def notes(self) -> tuple[str, ...]:
        out: list[str] = []
        if self.held:
            out.append(
                f"{len(self.held)} meta key(s) not registered with show_in_rest on this "
                f"site and would be silently dropped: {', '.join(self.held)}"
            )
        if self.unverified:
            out.append(
                f"{len(self.unverified)} meta key(s) sent unverified: the plugin is too "
                "old to report registrations, so the write must be confirmed by re-read"
            )
        return tuple(out)


def _as_bool(value: Any) -> bool:
    return value is True


def _as_str(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def parse_ping(payload: Any) -> SiteCapabilities:
    """Read a /ping body into `SiteCapabilities`.

    Total: never raises. A malformed or hostile response degrades to `known=False`,
    which is the same safe state as an old plugin - the body comes from a client's
    server, and a publish path must not be breakable by what it returns.
    """
    if not isinstance(payload, dict):
        return SiteCapabilities(notes=("ping response was not a JSON object",))

    plugin_version = _as_str(payload.get("plugin_version"))
    caps = payload.get("capabilities")
    if not isinstance(caps, dict):
        return SiteCapabilities(
            plugin_version=plugin_version,
            notes=(
                f"plugin {plugin_version or 'version unknown'} reports no capabilities; "
                "falling back to the configured editor default",
            ),
        )

    theme = caps.get("active_theme")
    theme = theme if isinstance(theme, dict) else {}

    registered: dict[str, frozenset[str]] = {}
    raw_meta = caps.get("registered_meta_keys")
    if isinstance(raw_meta, dict):
        for post_type in POST_TYPES:
            values = raw_meta.get(post_type)
            if isinstance(values, list):
                registered[post_type] = frozenset(
                    v.strip() for v in values if isinstance(v, str) and v.strip()
                )

    notes: list[str] = []
    elementor = _as_bool(caps.get("elementor"))
    if elementor and not _as_str(caps.get("elementor_version")):
        notes.append("Elementor reported active but returned no version")
    if not registered:
        notes.append("the site reported no registered meta keys for post or page")

    return SiteCapabilities(
        known=True,
        plugin_version=plugin_version,
        wp_version=_as_str(caps.get("wp_version")),
        theme_name=_as_str(theme.get("name")),
        theme_stylesheet=_as_str(theme.get("stylesheet")),
        elementor=elementor,
        elementor_version=_as_str(caps.get("elementor_version")),
        gutenberg=_as_bool(caps.get("gutenberg")),
        registered_meta=registered,
        notes=tuple(notes),
    )


def verify_meta_write(
    sent: dict[str, Any], returned: Any, *, post_type: str = "post"
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Compare what we sent against what the site now holds: ``(confirmed, dropped)``.

    This is the check `WordPressClient.update_post` says the caller must perform, and
    the reason it exists: a dropped key returns 200 with the OLD value, so only the
    comparison distinguishes a real write from a no-op. Unchanged from the site's
    perspective and unchanged from ours look identical in the status code.
    """
    del post_type  # part of the signature for symmetry with meta_plan; not needed here
    if not isinstance(returned, dict):
        return ((), tuple(sent))
    got = returned.get("meta")
    got = got if isinstance(got, dict) else {}
    confirmed: list[str] = []
    dropped: list[str] = []
    for key, value in sent.items():
        # String-compared: WordPress round-trips numbers and booleans through its own
        # meta storage, so `1` can come back as `"1"` without anything being wrong.
        (confirmed if str(got.get(key, "")) == str(value) else dropped).append(key)
    return (tuple(confirmed), tuple(dropped))
