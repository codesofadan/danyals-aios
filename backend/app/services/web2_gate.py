"""The DB-backed half of the cross-property similarity gate (R2-10 / R2-11).

:mod:`app.services.web2_similarity` is the pure scorer; this module is the seam that
joins it to the corpus. It lives here rather than in the worker because BOTH callers
need it and they are on opposite sides of the app:

* the WRITE worker runs it after drafting, so a collision is visible at review;
* the APPROVE endpoint runs it AGAIN, immediately before the placement is queued to go
  live.

The re-check is not belt-and-braces, it is the load-bearing one for campaigns. A
campaign drafts N properties before a human approves any of them, so at draft time none
of the siblings exists in the corpus yet and they cannot possibly collide with each
other. Fingerprints are persisted on APPROVAL (R2-11), so by the time the second sibling
is approved the first one IS in the corpus - and only a re-check at that moment can see
it. Checking once at draft time would let an entire campaign of near-identical articles
through, each individually "clean" when it was written.

Reading across tenants is deliberate and is confined to this module: it returns a
verdict, a scope label and the colliding property id, and never another client's text.
"""

from __future__ import annotations

from typing import Any, Protocol

from app.config import Settings
from app.logging_setup import get_logger
from app.services import web2_similarity as sim
from app.services.web2_pipeline import SimilarityOutcome

logger = get_logger("services.web2_gate")


class SimilarityStore(Protocol):
    """The two store methods the gate needs (satisfied by ``ServiceOffpageStore``)."""

    def web2_similarity_candidates(
        self,
        *,
        sampled_hashes: Any,
        body_sha256: str,
        client_id: str | None,
        account_id: str | None,
        platform: str,
        exclude_web2_id: str,
        platform_window_days: int = 90,
        min_shared: int = 2,
        limit: int = 200,
    ) -> list[dict[str, Any]]: ...

    def record_web2_fingerprint(
        self,
        *,
        web2_id: str,
        client_id: str,
        account_id: str | None,
        platform: str,
        body_sha256: str,
        shingle_hashes: Any,
        heading_hashes: Any,
        sampled_hashes: Any,
        anchor_norm: str,
        status_at_capture: str,
    ) -> str | None: ...


def scope_of(row: dict[str, Any], *, client_id: str | None, account_id: str | None) -> sim.Scope:
    """Which of the three R2-10 scopes a candidate matched under.

    Most-specific first: a property belonging to the SAME client is reported as a client
    collision even though it also shares the platform, because that is the scope an
    operator can actually act on ("your own other property duplicates this").
    """
    if client_id and str(row.get("client_id") or "") == client_id:
        return "client"
    if account_id and str(row.get("account_id") or "") == account_id:
        return "account"
    return "platform"


def evaluate_draft(
    store: SimilarityStore,
    settings: Settings,
    *,
    web2_id: str,
    row: dict[str, Any],
    body_md: str,
    client_name: str,
    geo: str = "",
) -> SimilarityOutcome:
    """Fingerprint ``body_md`` and score it against the three scopes.

    Raises nothing of its own beyond what the store raises; callers decide the posture
    (``run_write`` converts a failure to ``unavailable`` and carries on, the approval
    endpoint refuses on it).
    """
    platform = str(row.get("platform") or "")
    client_id = str(row.get("client_id") or "") or None
    account_id = str(row.get("account_id") or "") or None
    fp = sim.fingerprint(
        body_md=body_md,
        client_name=client_name,
        geo=geo,
        anchor=str(row.get("anchor") or ""),
    )
    rows = store.web2_similarity_candidates(
        sampled_hashes=list(fp.sampled),
        body_sha256=fp.body_sha256,
        client_id=client_id,
        account_id=account_id,
        platform=platform,
        exclude_web2_id=web2_id,
    )
    candidates = [
        sim.Candidate(
            web2_id=str(r["web2_id"]),
            scope=scope_of(r, client_id=client_id, account_id=account_id),
            body_sha256=str(r.get("body_sha256") or ""),
            body_hashes=frozenset(r.get("shingle_hashes") or ()),
            heading_hashes=frozenset(r.get("heading_hashes") or ()),
            anchor_norm=str(r.get("anchor_norm") or ""),
        )
        for r in rows
    ]
    verdict = sim.evaluate(
        fp,
        candidates,
        body_block=settings.web2_similarity_body_block,
        body_warn=settings.web2_similarity_body_warn,
        heading_block=settings.web2_similarity_heading_block,
        heading_warn=settings.web2_similarity_heading_warn,
    )
    return SimilarityOutcome(
        verdict=verdict.verdict,
        code=sim.error_code(verdict),
        detail="; ".join(verdict.notes),
    )


def record_fingerprint(
    store: SimilarityStore, *, web2_id: str, row: dict[str, Any], body_md: str,
    client_name: str, geo: str = "", status_at_capture: str = "published",
) -> str | None:
    """Persist the approved article's fingerprint into the corpus.

    On APPROVAL, never on draft (R2-11): a rejected or redrafted article must not become
    part of the corpus that later drafts are measured against, or one bad draft would
    permanently block its own client's remaining properties.
    """
    client_id = str(row.get("client_id") or "")
    if not client_id:
        return None  # a property with no tenant cannot be scoped; recording it would
        # place an unattributable document in a cross-tenant corpus.
    fp = sim.fingerprint(
        body_md=body_md, client_name=client_name, geo=geo, anchor=str(row.get("anchor") or "")
    )
    return store.record_web2_fingerprint(
        web2_id=web2_id,
        client_id=client_id,
        account_id=str(row.get("account_id") or "") or None,
        platform=str(row.get("platform") or ""),
        body_sha256=fp.body_sha256,
        shingle_hashes=list(fp.body_hashes),
        heading_hashes=list(fp.heading_hashes),
        sampled_hashes=list(fp.sampled),
        anchor_norm=fp.anchor_norm,
        status_at_capture=status_at_capture,
    )
