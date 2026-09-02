"""The DB-backed similarity gate seam, and the campaign hole only the RE-CHECK closes.

The property this file exists to pin, verified end-to-end against real Postgres before
being written down here:

    A campaign drafts N properties BEFORE a human approves any of them. At draft time
    none of the siblings is in the corpus, so every one of them scores CLEAN - even when
    they are byte-identical. Fingerprints enter the corpus as properties go live, so the
    duplicate is only visible at APPROVAL, and only if the gate runs again there.

Checking once at draft time therefore waves through an entire campaign of identical
articles, each individually "clean" when it was written. That is precisely the "fans ONE
branded article out to every selected platform" behaviour the old UI advertised and that
WEB2-002 forbids, so the re-check is the load-bearing half of the control, not a
belt-and-braces repeat of it.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.config import Settings
from app.services import web2_gate

pytestmark = pytest.mark.unit

_CLIENT = "cl-1"
_BODY = (
    "# Emergency Drain Unblocking in Leeds\n\n"
    "Leeds Drainage clears blocked drains across Leeds using jetting and a camera\n"
    "survey so the customer can see the pipe is genuinely clear afterwards.\n\n"
    "## What It Costs\n"
    "Most Leeds jobs are a single visit and the quote is fixed before work begins.\n"
)


class FakeSimStore:
    """An in-memory stand-in for the ``ServiceOffpageStore`` methods the gate uses.

    It models the real query's shape closely enough to be honest: candidates are only
    returned from the recorded corpus, and scoping is applied - so a test cannot pass by
    accident on a store that returns everything.
    """

    def __init__(self) -> None:
        self.corpus: list[dict[str, Any]] = []
        #: R2-15's corpus. Empty by default so these similarity tests exercise only the
        #: similarity rule; the link rule has its own suite.
        self.property_urls: set[str] = set()

    def known_web2_urls(self) -> set[str]:
        return set(self.property_urls)

    def web2_similarity_candidates(
        self, *, sampled_hashes: Any, body_sha256: str, client_id: str | None,
        account_id: str | None, platform: str, exclude_web2_id: str,
        platform_window_days: int = 90, min_shared: int = 2, limit: int = 200,
    ) -> list[dict[str, Any]]:
        sampled = set(sampled_hashes)
        out: list[dict[str, Any]] = []
        for row in self.corpus:
            if row["web2_id"] == exclude_web2_id:
                continue
            in_scope = (
                (client_id and row.get("client_id") == client_id)
                or (account_id and row.get("account_id") == account_id)
                or row.get("platform") == platform
            )
            if not in_scope:
                continue
            # The real query unions an EXACT sha lookup with the MOD_16 sample probe.
            exact = row.get("body_sha256") == body_sha256
            shared = len(sampled & set(row.get("_sampled") or ()))
            if exact or shared >= min_shared:
                out.append(row)
        return out[:limit]

    def record_web2_fingerprint(
        self, *, web2_id: str, client_id: str, account_id: str | None, platform: str,
        body_sha256: str, shingle_hashes: Any, heading_hashes: Any, sampled_hashes: Any,
        anchor_norm: str, status_at_capture: str,
    ) -> str | None:
        self.corpus = [r for r in self.corpus if r["web2_id"] != web2_id]
        self.corpus.append(
            {
                "web2_id": web2_id, "client_id": client_id, "account_id": account_id,
                "platform": platform, "body_sha256": body_sha256,
                "shingle_hashes": list(shingle_hashes), "heading_hashes": list(heading_hashes),
                "anchor_norm": anchor_norm, "_sampled": list(sampled_hashes),
            }
        )
        return f"fp-{web2_id}"


def _row(web2_id: str) -> dict[str, Any]:
    return {
        "id": web2_id, "client_id": _CLIENT, "client_name": "Leeds Drainage",
        "platform": "Blogger", "anchor": "drain unblocking", "account_id": None,
    }


def _settings() -> Settings:
    return Settings(_env_file=None)  # type: ignore[call-arg]


def _check(store: FakeSimStore, web2_id: str, body: str = _BODY) -> str:
    return web2_gate.evaluate_draft(
        store, _settings(), web2_id=web2_id, row=_row(web2_id), body_md=body,
        client_name="Leeds Drainage", geo="Leeds",
    ).verdict


def _publish(store: FakeSimStore, web2_id: str, body: str = _BODY) -> None:
    web2_gate.record_fingerprint(
        store, web2_id=web2_id, row=_row(web2_id), body_md=body,
        client_name="Leeds Drainage", geo="Leeds",
    )


# --------------------------------------------------------------------------- #
# THE campaign property.
# --------------------------------------------------------------------------- #
def test_identical_campaign_drafts_all_pass_at_draft_time() -> None:
    """Not a bug - a fact about ordering, and the reason the re-check must exist. The
    corpus is empty when the batch is written, so nothing can collide yet."""
    store = FakeSimStore()
    assert [_check(store, f"w2-{i}") for i in range(3)] == ["pass", "pass", "pass"]


def test_the_recheck_blocks_the_siblings_once_the_first_one_is_live() -> None:
    store = FakeSimStore()
    for i in range(3):
        assert _check(store, f"w2-{i}") == "pass"
    _publish(store, "w2-0")  # the first property goes live and enters the corpus
    assert _check(store, "w2-1") == "block"
    assert _check(store, "w2-2") == "block"


def test_a_campaign_of_distinct_articles_still_passes_after_siblings_publish() -> None:
    """The other half: the gate must not block a correctly-built campaign, or operators
    learn to override it and it protects nothing."""
    store = FakeSimStore()
    bodies = {
        "w2-0": _BODY,
        "w2-1": (
            "# Choosing A Drainage Contractor\n\n"
            "Ask whether the quote covers a post-job survey and whether the engineer is\n"
            "insured for work on shared drains before agreeing anything.\n"
        ),
        "w2-2": (
            "# Reading A CCTV Drain Survey\n\n"
            "The footage should show the full run rather than a single still frame, and\n"
            "the recording belongs to you once the visit is paid for.\n"
        ),
    }
    for wid, body in bodies.items():
        assert _check(store, wid, body) == "pass"
        _publish(store, wid, body)
    for wid, body in bodies.items():
        assert _check(store, wid, body) == "pass", f"{wid} collided with its own siblings"


# --------------------------------------------------------------------------- #
# Corpus hygiene.
# --------------------------------------------------------------------------- #
def test_a_property_never_collides_with_its_own_earlier_fingerprint() -> None:
    """A redraft re-scores against the corpus MINUS itself. Without the exclusion a
    republished property would block itself forever."""
    store = FakeSimStore()
    _publish(store, "w2-0")
    assert _check(store, "w2-0") == "pass"


def test_recording_the_same_property_twice_replaces_rather_than_accumulates() -> None:
    store = FakeSimStore()
    _publish(store, "w2-0")
    _publish(store, "w2-0")
    assert len([r for r in store.corpus if r["web2_id"] == "w2-0"]) == 1


def test_a_property_with_no_client_is_not_entered_into_a_cross_tenant_corpus() -> None:
    """An unattributable document cannot be scoped, so recording it would put a row in a
    cross-tenant corpus that no scope can explain."""
    store = FakeSimStore()
    out = web2_gate.record_fingerprint(
        store, web2_id="w2-x", row={"id": "w2-x", "client_id": "", "platform": "Blogger"},
        body_md=_BODY, client_name="X",
    )
    assert out is None
    assert store.corpus == []


def test_the_scope_label_reports_the_most_actionable_relationship() -> None:
    """Same-client is reported over same-platform even though both are true: 'your own
    other property duplicates this' is the finding an operator can act on."""
    assert web2_gate.scope_of(
        {"client_id": "cl-1", "account_id": "acct-1"}, client_id="cl-1", account_id="acct-1"
    ) == "client"
    assert web2_gate.scope_of(
        {"client_id": "cl-9", "account_id": "acct-1"}, client_id="cl-1", account_id="acct-1"
    ) == "account"
    assert web2_gate.scope_of(
        {"client_id": "cl-9", "account_id": "acct-9"}, client_id="cl-1", account_id="acct-1"
    ) == "platform"


# --------------------------------------------------------------------------- #
# R2-15 is WIRED, not just written.
# --------------------------------------------------------------------------- #
def test_the_gate_refuses_a_draft_that_links_to_another_property() -> None:
    """The regression that matters: `known_web2_urls()` existed with a docstring citing
    R2-15 and had ZERO callers, so the ban was documentation. This asserts the gate
    itself refuses - if the wiring is removed, the corpus goes unread and this passes a
    self-link straight through."""
    store = FakeSimStore()
    store.property_urls = {"https://otherclient.wordpress.com/2026/08/a-post"}

    row = {**_row("w2-link"), "target_url": "https://leedsdrainage.co.uk/services"}
    outcome = web2_gate.evaluate_draft(
        store, _settings(), web2_id="w2-link", row=row,
        body_md=(
            "Background: https://otherclient.wordpress.com/2026/08/a-post\n\n"
            "We handle this at https://leedsdrainage.co.uk/services"
        ),
        client_name="Leeds Drainage", geo="Leeds",
    )

    assert outcome.blocked
    assert outcome.code.startswith("link_block:self_reference:")


def test_the_gate_still_passes_a_draft_citing_genuine_third_parties() -> None:
    store = FakeSimStore()
    store.property_urls = {"https://otherclient.wordpress.com/2026/08/a-post"}

    row = {**_row("w2-ok"), "target_url": "https://leedsdrainage.co.uk/services"}
    outcome = web2_gate.evaluate_draft(
        store, _settings(), web2_id="w2-ok", row=row,
        body_md=(
            "Per https://gov.uk/drainage-standards the survey matters.\n\n"
            "We handle this at https://leedsdrainage.co.uk/services"
        ),
        client_name="Leeds Drainage", geo="Leeds",
    )

    assert not outcome.blocked
