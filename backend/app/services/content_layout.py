"""Wave 5: a PURE, deterministic LAYOUT heuristic for a finished content draft.

After the pipeline drafts + guards + images a page, it must present it in a
sensible template before the human review gate. This module owns that one decision:
given the page type and a few observable draft signals (image count, word count,
whether the draft carries a Q&A block, whether it is a local page), it returns ONE
named layout - deterministically, with no I/O and no randomness. Same inputs always
map to the same layout, so the choice is unit-testable and reproducible.

The layout is stored on the job (inside the ``outline`` jsonb) so the dashboard's
Review preview can frame the draft in the right template and the reviewer sees the
chosen presentation. It is intentionally a SIMPLE rule table (the plan calls for a
"simple deterministic heuristic"), not a learned model.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# Word-count boundary at which a blog earns a table-of-contents long-form layout.
_LONG_FORM_WORDS = 1500
# Image count at which a blog earns the media-rich (image-led) layout.
_MEDIA_RICH_IMAGES = 3


@dataclass(frozen=True)
class LayoutChoice:
    """The chosen layout: a stable ``key`` (machine-branchable), a human ``label``,
    and the ``reason`` the heuristic picked it (shown to the reviewer)."""

    key: str
    label: str
    reason: str

    def as_dict(self) -> dict[str, Any]:
        return {"key": self.key, "label": self.label, "reason": self.reason}


# The closed set of layouts, keyed by ``key`` (label + a default rationale).
LAYOUTS: dict[str, str] = {
    "gbp-card": "GBP update card",
    "local-landing": "Local landing page",
    "service-hero": "Service hero + CTA",
    "long-form-toc": "Long-form with contents",
    "media-rich": "Media-rich article",
    "standard-article": "Standard article",
}


def pick_layout(
    page_type: str,
    *,
    images: int = 0,
    words: int = 0,
    has_faq: bool = False,
    has_local: bool = False,
) -> LayoutChoice:
    """Pick ONE layout for a finished draft (pure + deterministic).

    Decision table, first match wins:

    * ``gbp_post`` -> ``gbp-card`` (a single compact Business-Profile update card).
    * ``local`` (or ``has_local``) -> ``local-landing`` (NAP + per-city sections).
    * ``service`` -> ``service-hero`` (hero + benefits + a strong CTA).
    * ``blog`` / other:
        * long (``words >= 1500``) AND a Q&A block -> ``long-form-toc``.
        * image-led (``images >= 3``) -> ``media-rich``.
        * otherwise -> ``standard-article``.
    """
    if page_type == "gbp_post":
        return LayoutChoice("gbp-card", LAYOUTS["gbp-card"], "GMB post: a single Business-Profile card")
    if page_type == "local" or has_local:
        return LayoutChoice("local-landing", LAYOUTS["local-landing"], "local page: NAP + per-city sections")
    if page_type == "service":
        return LayoutChoice("service-hero", LAYOUTS["service-hero"], "service page: hero, benefits, CTA")
    if words >= _LONG_FORM_WORDS and has_faq:
        return LayoutChoice(
            "long-form-toc", LAYOUTS["long-form-toc"],
            f"{words} words with a Q&A block: contents + FAQ layout",
        )
    if images >= _MEDIA_RICH_IMAGES:
        return LayoutChoice("media-rich", LAYOUTS["media-rich"], f"{images} images: an image-led article")
    return LayoutChoice("standard-article", LAYOUTS["standard-article"], "standard article layout")
