"""Mint the readable public page for a completed audit (db/migrations/0126).

One helper for both kinds so the free and paid paths cannot drift. Everything
that matters - slug derivation, collision suffixes, the paid random suffix, and
the published default - lives in the SQL function `ensure_public_audit_page`, so
this is a thin call rather than a second implementation of the rules.

Never fatal by design, exactly like the sheet build and the report build beside
it: a page we failed to mint must not turn a completed audit into a failed one.
The audit is still reachable by its token (free) or in the dashboard (paid), and
a later run of the backfill picks it up.
"""

from __future__ import annotations

from app.db.database import privileged_connection
from app.logging_setup import get_logger

logger = get_logger("services.audit_public_pages")


def ensure_page(
    *, kind: str, public_audit_id: str | None = None, audit_id: str | None = None, url: str = ""
) -> str | None:
    """Claim (or re-read) the slug for one completed report. Returns it, or None.

    `published` is left to the SQL default, which is the security decision: free
    pages publish on completion because the lead magnet is meant to be shared and
    the report is derived wholly from a public crawl; paid pages do NOT, because a
    paid audit is client deliverable work. Do not pass an override here without
    reading 0126's header.
    """
    if kind not in {"free", "paid"}:
        return None
    try:
        with privileged_connection() as cur:
            cur.execute(
                "select public.ensure_public_audit_page(%s, %s, %s, %s, null) as slug",
                (kind, public_audit_id, audit_id, url),
            )
            row = cur.fetchone()
        slug = (row or {}).get("slug")
        if slug:
            logger.info("public_page_minted", kind=kind, slug=slug)
        return str(slug) if slug else None
    except Exception:
        logger.warning("public_page_mint_failed", kind=kind, url=url)
        return None
