"""Matching a directory NAME to the catalog row it refers to.

A leaf module on purpose. It is imported by both the citations service (read-time
matching) and the off-page repo (write-time resolution), and `app.modules.__init__`
pulls in every module router - so importing it through `app.modules.citations` made
`app.db.offpage_repo` -> `app.modules...` -> `app.db.offpage_repo` a cycle. It broke
nothing in the tests, which import the FastAPI app first and therefore never see the
partially-initialised module; it broke the WORKER, which imports the repo first.

Kept free of every other app import so it can never do that again.
"""

from __future__ import annotations


def _norm_directory(name: str) -> str:
    return "".join(ch for ch in name.lower() if ch.isalnum())


# Discovery names a found listing from its DOMAIN (integrations/citation_discovery.py
# `_DIRECTORY_DOMAINS`), and the catalog names the same directory as a product. Where
# those differ, a listing the client demonstrably HAS never matches the catalog row for
# it, so the gap report keeps asking for a build that already exists - and the count
# moves whenever a name happens to line up.
#
# Measured against the live catalog (226 active rows) on 2026-09-01: 20 of the 31 names
# discovery can emit match by normalisation alone; these five are the ones that do not
# AND have exactly one unambiguous target.
#
# THE REST ARE DELIBERATELY ABSENT. "Yellow Pages" has six plausible targets across
# three countries, "BBB" three, "Angi" and "Justia" two apiece (the catalog carries
# genuine duplicates of both), and "Local.com" would collide with "Local.com.au", a
# DIFFERENT country's directory. A wrong merge silently marks a directory covered that
# was never built - NAP pollution is often unremovable, whereas a missed match only
# means a directory is offered twice. So an ambiguous name is left unresolved on
# purpose: this map may only ever grow by evidence, never by resemblance.
_DIRECTORY_ALIASES: dict[str, str] = {
    "googlebusiness": "googlebusinessprofile",
    "bingplaces": "bingplacesforbusiness",
    "facebook": "facebookbusinesspage",
    "foursquare": "foursquareplaces",
    "applemaps": "applebusinessconnect",
}


def canonical_norm(name: str) -> str:
    """The key both sides of a directory match must agree on.

    Used at WRITE time to resolve a discovered listing to its catalog row, and at READ
    time as the fallback for rows that carry no ``directory_id``. Sharing one function
    is what keeps a legacy row and a new row matching by the same rule.
    """
    key = _norm_directory(name)
    return _DIRECTORY_ALIASES.get(key, key)


__all__ = ["_DIRECTORY_ALIASES", "canonical_norm"]
