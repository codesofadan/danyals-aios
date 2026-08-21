"""Resolve the wizard's ``editor_mode`` (auto/gutenberg/elementor/hybrid) into the
ONE renderer a publish actually invokes - the "theme awareness" seam (spec section
18/31): never assume Elementor is installed just because the operator asked for it.

Pure, dependency-free: no network/DB - the caller resolves ``elementor_available``
itself (today: ``settings.content_elementor_enabled`` per client; a later phase can
probe the target site's active-plugin list instead, per ``app.modules.site_builder``'s
future theme-detection task, without this function changing).
"""

from __future__ import annotations

from typing import Literal

RenderTarget = Literal["gutenberg", "elementor"]


def resolve_editor_mode(requested: str, *, elementor_available: bool) -> RenderTarget:
    """The renderer a build actually uses for one of the four wizard choices:

    * ``elementor`` - use Elementor if it is actually installed on the target site,
      else degrade to Gutenberg (never fail the build over an editor preference).
    * ``gutenberg`` - always native WordPress blocks.
    * ``hybrid`` - native blocks/Elementor for text/images/buttons/sections/grids
      (spec section 17); with no custom-component renderer built yet, this
      currently resolves the SAME as ``gutenberg`` (the most broadly editable,
      dependency-free choice) - revisit once a custom-component path exists.
    * ``auto`` - the best compatible choice for the target site: Elementor when
      available (usually the higher-fidelity, more widely-used page builder on
      client sites), else Gutenberg.
    * anything else (an unknown/garbled value) - degrades to Gutenberg, the choice
      that works on every WordPress site with no plugin dependency.
    """
    if requested == "elementor":
        return "elementor" if elementor_available else "gutenberg"
    if requested == "auto":
        return "elementor" if elementor_available else "gutenberg"
    return "gutenberg"
