"""What the TARGET site can render - the builder's licence to use a widget.

THE PROBLEM THIS SOLVES. The replica emitter assumed the free Elementor tier for
every client. That is safe and wrong: a client paying for Elementor Pro got a
DOWNGRADED rebuild of their own site for no reason - a real navigation menu became
a list of links, a contact form became a heading and a button - while the widgets
that would have reproduced it faithfully sat installed and unused.

Emitting a Pro widget blindly is worse, though. Elementor stores an unknown
``widgetType`` and then silently renders NOTHING for it, so an over-ambitious tree
produces a page with holes and no error anywhere. That failure is invisible until
someone looks at the page, which is exactly the class of silent wrongness this
codebase keeps finding.

So the rule is: **ask the site, then build to what it answered.**
``GET /aios/v1/ping`` reports ``elementor_widgets`` - the live widget registry read
from ``widgets_manager->get_widget_types()``. That is strictly better than a
boolean "has Pro", because it also covers third-party packs (Crocoblock, Essential
Addons, theme bundles): the builder uses whatever a given site actually has rather
than a hard-coded idea of two Elementor tiers.

DEGRADATION IS NAMED, NEVER SILENT. When the source uses something the target
cannot render, the profile picks the best available substitute and the pipeline
records WHICH substitution it made, so the operator reads "this site has no
nav-menu widget, the header was rebuilt as an inline link list" instead of
wondering why the rebuild looks flatter than the original.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

#: The free-tier vocabulary this emitter has always been able to build. Used as the
#: floor when a site cannot be asked (an older plugin, a failed ping): assuming the
#: free set is the conservative answer, and it is what shipped before.
FREE_WIDGETS: frozenset[str] = frozenset({
    "heading", "text-editor", "image", "button", "icon-list", "icon-box",
    "star-rating", "testimonial", "icon", "accordion", "divider",
    "google_maps", "social-icons", "spacer",
})

#: Source constructs the builder can express BETTER when the target has the widget,
#: mapped to the fallback it uses otherwise. The fallback is always something in
#: FREE_WIDGETS, so every entry degrades to something renderable.
#:
#: Read as: "if the site has `preferred`, use it; otherwise build `fallback` and say
#: so." The `why` is operator-facing copy, not a log line.
@dataclass(frozen=True)
class Substitution:
    preferred: str
    fallback: str
    why: str


UPGRADES: Mapping[str, Substitution] = {
    "nav": Substitution(
        preferred="nav-menu",
        fallback="icon-list",
        why=("the header was rebuilt as an inline link list because this site has no "
             "nav-menu widget; the links and their order are correct, the dropdown "
             "and mobile drawer behaviour are not reproduced"),
    ),
    "form": Substitution(
        preferred="form",
        fallback="text-editor",
        why=("a contact form was found but this site has no form widget, so the "
             "fields could not be rebuilt - the surrounding copy is kept and the "
             "form itself needs adding by hand"),
    ),
    "slides": Substitution(
        preferred="slides",
        fallback="image",
        why=("a slider was flattened to its first visible slide because this site "
             "has no slides widget"),
    ),
    "gallery": Substitution(
        preferred="gallery",
        fallback="image",
        why=("a gallery was rebuilt as individual images because this site has no "
             "gallery widget"),
    ),
    "tabs": Substitution(
        preferred="tabs",
        fallback="accordion",
        why=("a tab strip was rebuilt as an accordion because this site has no tabs "
             "widget; the content is intact, the interaction differs"),
    ),
    "price-table": Substitution(
        preferred="price-table",
        fallback="icon-list",
        why=("a pricing table was rebuilt as a list because this site has no "
             "price-table widget"),
    ),
    "posts": Substitution(
        preferred="posts",
        fallback="image",
        why=("a dynamic post feed cannot be reproduced without the posts widget; "
             "its visible cards were rebuilt as static content"),
    ),
}


@dataclass(frozen=True)
class TargetCapability:
    """What one client's site can render, as answered by its own plugin."""

    #: Every widget name the live editor has registered. Empty = we could not ask.
    widgets: frozenset[str] = frozenset()
    has_elementor: bool = False
    has_pro: bool = False
    elementor_version: str = ""
    pro_version: str = ""
    #: True when the registry came from the site; False when we fell back to FREE.
    measured: bool = False
    notes: tuple[str, ...] = field(default_factory=tuple)

    @classmethod
    def free_tier(cls, why: str = "the site's widget registry was unavailable") -> TargetCapability:
        """The conservative floor. Used when the plugin is too old to report a
        registry, or the ping failed - never guess UP from silence."""
        return cls(
            widgets=FREE_WIDGETS,
            has_elementor=True,
            measured=False,
            notes=(f"assuming the free Elementor widget set: {why}",),
        )

    @classmethod
    def from_ping(cls, capabilities: Mapping[str, Any]) -> TargetCapability:
        """Build a profile from `GET /aios/v1/ping`'s `capabilities` object."""
        raw = capabilities.get("elementor_widgets")
        names = frozenset(str(w) for w in raw if isinstance(w, str)) if isinstance(raw, list) else frozenset()
        has_elementor = bool(capabilities.get("elementor"))
        if not has_elementor:
            return cls(
                widgets=frozenset(), has_elementor=False, measured=True,
                notes=("this site has no Elementor; the rebuild cannot be published "
                       "as an Elementor document",),
            )
        if not names:
            profile = cls.free_tier("this site's plugin is older than 1.11 and does "
                                    "not report its widget registry")
            return profile
        return cls(
            widgets=names,
            has_elementor=True,
            has_pro=bool(capabilities.get("elementor_pro")),
            elementor_version=str(capabilities.get("elementor_version") or ""),
            pro_version=str(capabilities.get("elementor_pro_version") or ""),
            measured=True,
        )

    def can(self, widget: str) -> bool:
        """Whether the target can render this widget type."""
        return widget in self.widgets

    def resolve(self, construct: str) -> tuple[str, str | None]:
        """The widget to build for a source construct, plus a note when degraded.

        Returns ``(widget_type, note)``. ``note`` is None when the preferred widget
        was available, and operator-facing prose when a substitution was made.
        """
        upgrade = UPGRADES.get(construct)
        if upgrade is None:
            return construct, None
        if self.can(upgrade.preferred):
            return upgrade.preferred, None
        return upgrade.fallback, upgrade.why

    def summary(self) -> str:
        """One line for the replication result, so the operator knows what the
        rebuild was allowed to use."""
        if not self.has_elementor:
            return "target has no Elementor"
        if not self.measured:
            return "target capability unknown; built to the free Elementor set"
        tier = f"Elementor {self.elementor_version or '?'}"
        if self.has_pro:
            tier += f" + Pro {self.pro_version or '?'}"
        return f"target runs {tier} with {len(self.widgets)} widgets available"


def upgraded_constructs(capability: TargetCapability) -> Iterable[str]:
    """Which source constructs this target can reproduce faithfully. Useful for a
    pre-flight answer to "what will this rebuild be able to keep?"."""
    return sorted(c for c, u in UPGRADES.items() if capability.can(u.preferred))
