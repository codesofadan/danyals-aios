"""7B-3 unit tests: the Web 2.0 PUBLISH pipeline.

Fully deterministic on the content generator's ``FakeWriter`` + the deterministic
``FakeWeb2Publisher`` + in-memory fakes for the store and cost gate - NO network, NO DB.
Proves the load-bearing guarantees:

* plan -> write HOLDS the placement at ``needs_review`` and NEVER publishes;
* a lead's approval drives publish -> verify -> track (status published, post_url +
  verified recorded);
* footprint diversification varies the platform/account/anchor/timing selection and
  avoids already-used (platform, anchor) pairs (anti-SpamBrain);
* degraded (no writer / no publisher) HOLDS at the review gate rather than crashing;
* the R5 cost pre-check BLOCKS an over-budget write BEFORE any paid work;
* the orchestration is idempotent (redelivery is a no-op) and never publishes an
  article with unresolved ``[NEEDS:]`` gaps.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from typing import Any

import pytest

from app.config import Settings
from app.services import web2_pipeline as pipeline_mod
from app.services.content_generator import SourcePack
from app.services.cost_gate import CostGate, DialMode, GateContext
from app.services.web2_pipeline import (
    Web2Client,
    markdown_to_html,
    plan,
    run_publish,
    run_write,
    split_title_and_body,
    verify_live_and_indexable,
    write,
)
from integrations.llm import LLMResult
from integrations.web2_publishers import (
    PLATFORM_MEDIUM,
    PLATFORM_WORDPRESS,
    FakeWeb2Publisher,
    Web2PublishResult,
    diversify_footprint,
)

pytestmark = pytest.mark.unit


# --------------------------------------------------------------------------- #
# Deterministic fakes.
# --------------------------------------------------------------------------- #
class FakeWriter:
    """Prompt-hash-derived writer (Summarizer): identical prompt => identical prose,
    different prompts => different prose. NO network. Counts calls so a blocked/degraded
    path can prove the writer was never reached."""

    def __init__(self, *, words: int = 60) -> None:
        self._words = words
        self.calls = 0

    def summarize(
        self,
        prompt: str,
        *,
        model: str,
        max_tokens: int,
        system: str | Sequence[str] | None = None,
        cache: Sequence[bool] | None = None,
    ) -> LLMResult:
        self.systems = [*getattr(self, "systems", []), system]
        self.calls += 1
        digest = hashlib.sha256(prompt.encode()).hexdigest()
        base = [digest[i : i + 6] for i in range(0, len(digest), 6)]
        body = " ".join(f"{base[i % len(base)]}{i}" for i in range(self._words))
        return LLMResult(text=body, input_tokens=max(1, len(prompt) // 4), output_tokens=self._words)


class FakeWeb2Store:
    """In-memory ``Web2Store``: load returns a COPY (so a caller mutating the returned
    dict cannot silently change the ledger before an explicit update)."""

    def __init__(self, rows: dict[str, dict[str, Any]] | None = None) -> None:
        self.rows: dict[str, dict[str, Any]] = rows or {}
        self.updates: list[tuple[str, dict[str, Any]]] = []

    def load_web2(self, web2_id: str) -> dict[str, Any] | None:
        row = self.rows.get(web2_id)
        return dict(row) if row is not None else None

    def update_web2(self, web2_id: str, fields: dict[str, Any]) -> None:
        self.updates.append((web2_id, dict(fields)))
        self.rows.setdefault(web2_id, {}).update(fields)


class FakeCostStore:
    """Controllable ``CostStore`` for the gate (mirrors test_cost_gate.FakeStore)."""

    def __init__(
        self,
        *,
        mode: DialMode = "api",
        budget: tuple[float, float] | None = None,
        daily_spent: float = 0.0,
        daily_stop: float = 75.0,
        halted: bool = False,
    ) -> None:
        self._mode = mode
        self._budget = budget
        self._daily_spent = daily_spent
        self._daily_stop = daily_stop
        self._halted = halted
        self.recorded: list[tuple[GateContext, float, bool]] = []

    def dial_mode(self, feature_key: str) -> DialMode:
        return self._mode

    def client_budget(self, client_id: str) -> tuple[float, float] | None:
        return self._budget

    def daily_spent(self) -> float:
        return self._daily_spent

    def daily_stop(self) -> float:
        return self._daily_stop

    def is_halted(self) -> bool:
        return self._halted

    def record_cost(self, ctx: GateContext, cost: float, *, cached: bool) -> None:
        self.recorded.append((ctx, cost, cached))


class _NullCache:
    def get(self, key: str) -> Any | None:
        return None

    def set(self, key: str, value: Any) -> None:
        return None


def _gate(store: FakeCostStore) -> CostGate:
    return CostGate(store, _NullCache())


def _settings() -> Settings:
    return Settings(_env_file=None)  # type: ignore[call-arg]


def _source_pack() -> SourcePack:
    """A pack with first-hand proof + testimonials, so the generator produces a fully
    grounded (publishable, no ``[NEEDS:]``) branded article."""
    return SourcePack(
        client_name="Acme Roofing",
        facts={"years": "18"},
        services=["Roof repair", "Roof replacement"],
        proof_points=["Rebuilt 40 storm-damaged roofs in 2025"],
        unique_data=["Our 2025 study of 500 roofs found 30% needed only spot repair"],
        testimonials=["'They saved our home' - J. Doe"],
        internal_urls={},
    )


def _draft_row(**over: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "id": "w2-1",
        "client_id": "cl-1",
        "client_name": "Acme Roofing",
        "platform": PLATFORM_WORDPRESS,
        "anchor": "roof repair",
        "target_url": "https://acme.example/roof-repair",
        "topic": "roof repair",
        "page_type": "blog",
        "framework": "Auto",
        "status": "draft",
        "post_url": "",
        "verified": "pending",
        "body_md": "",
        "external_id": None,
    }
    row.update(over)
    return row


def _client() -> Web2Client:
    return Web2Client(client_id="cl-1", name="Acme Roofing", source_pack=_source_pack())


# --------------------------------------------------------------------------- #
# plan
# --------------------------------------------------------------------------- #
def test_plan_seeds_brief_and_resolves_framework() -> None:
    the_plan = plan(_client(), PLATFORM_WORDPRESS, "roof repair", "https://acme.example/x")
    assert the_plan.brief.keyword == "roof repair"
    assert the_plan.topic == "roof repair"
    assert the_plan.framework == "PAS"  # blog -> PAS (Auto resolved)
    assert the_plan.brief.low_confidence is True  # no live SERP research backed it


def test_plan_explicit_framework_wins() -> None:
    the_plan = plan(
        _client(), PLATFORM_WORDPRESS, "roofing", "https://x", framework="PASTOR", page_type="service"
    )
    assert the_plan.framework == "PASTOR"


# --------------------------------------------------------------------------- #
# write (via the content generator) + the branded backlink
# --------------------------------------------------------------------------- #
def test_write_produces_grounded_article_with_backlink() -> None:
    the_plan = plan(_client(), PLATFORM_WORDPRESS, "roof repair", "https://acme.example/roof-repair")
    article = write(the_plan, writer=FakeWriter(), source_pack=_source_pack())
    assert article.publishable is True
    assert "[NEEDS:" not in article.body_md
    # The one editorial backlink the property exists to carry is present.
    assert "(https://acme.example/roof-repair)" in article.body_md
    assert article.body_md.startswith("# ")  # a single H1 for the title split


# --------------------------------------------------------------------------- #
# The backlink is placed CONTEXTUALLY, not as a fixed trailing block.
#
# The previous implementation appended a byte-identical two-line section to EVERY
# property of EVERY client. That was a cross-client fingerprint in its own right, and
# its fixed `## More about` heading sat in every document's heading skeleton - which
# would drag the heading-Jaccard similarity gate toward its block line on articles that
# are genuinely distinct, defeating the control with the text it was meant to inspect.
# --------------------------------------------------------------------------- #
# --------------------------------------------------------------------------- #
# The similarity seam: fail-OPEN at draft, fail-CLOSED at approval.
#
# The asymmetry is deliberate. At draft time a block and a pass land in the SAME place
# (needs_review), so refusing to draft because the corpus is unreachable would stop all
# work to prevent nothing. What must never happen is a placement going LIVE unchecked,
# so "unavailable" is recorded honestly and the approval endpoint refuses on it.
# --------------------------------------------------------------------------- #
def test_a_similarity_block_is_recorded_but_still_parks_at_review() -> None:
    store = FakeWeb2Store({"w2-1": _draft_row()})

    def checker(**_kw: Any) -> pipeline_mod.SimilarityOutcome:
        return pipeline_mod.SimilarityOutcome("block", "sim_block:body_sha256:client:w2-9")

    out = run_write(
        store, "w2-1", client=_client(), writer=FakeWriter(), gate=_gate(FakeCostStore(mode="api")),
        settings=_settings(), similarity=checker,
    )
    assert out.state == "needs_review"  # a block HOLDS; it never publishes and never crashes
    assert store.rows["w2-1"]["status"] == "needs_review"
    assert store.rows["w2-1"]["error"] == "sim_block:body_sha256:client:w2-9"


def test_a_checker_that_raises_records_unavailable_and_does_not_break_the_draft() -> None:
    """A gate that cannot reach the corpus must not take the worker down - run_write
    never raises, because acks_late would redeliver and re-spend on Claude."""
    store = FakeWeb2Store({"w2-1": _draft_row()})

    def boom(**_kw: Any) -> pipeline_mod.SimilarityOutcome:
        raise RuntimeError("db down")

    out = run_write(
        store, "w2-1", client=_client(), writer=FakeWriter(), gate=_gate(FakeCostStore(mode="api")),
        settings=_settings(), similarity=boom,
    )
    assert out.state == "needs_review"
    assert store.rows["w2-1"]["error"].startswith("sim_unavailable:")


def test_an_unwired_gate_is_unavailable_not_a_silent_pass() -> None:
    """'Not wired' must be distinguishable from 'approved'. Recording a pass here is how
    a safety control silently covers nothing while looking installed."""
    store = FakeWeb2Store({"w2-1": _draft_row()})
    run_write(
        store, "w2-1", client=_client(), writer=FakeWriter(), gate=_gate(FakeCostStore(mode="api")),
        settings=_settings(), similarity=None,
    )
    assert store.rows["w2-1"]["error"] == "sim_unavailable:not_wired"


def test_the_backlink_no_longer_emits_the_fixed_more_about_section() -> None:
    the_plan = plan(_client(), PLATFORM_WORDPRESS, "roof repair", "https://acme.example/roof-repair")
    body = write(the_plan, writer=FakeWriter(), source_pack=_source_pack()).body_md
    assert "## More about" not in body
    assert "Learn more about [" not in body


def test_an_existing_prose_mention_is_linked_rather_than_a_sentence_appended() -> None:
    """The best placement adds NO new text: if the anchor is already in the prose, that
    occurrence becomes the link. Nothing is appended, so there is no template at all."""
    draft = "# Roof Repair Guide\n\nGood roof repair starts with a survey of the deck.\n"
    out = pipeline_mod._place_backlink(draft, "roof repair", "https://acme.example/x", seed="s")
    assert "[roof repair](https://acme.example/x)" in out
    assert out.count("https://acme.example/x") == 1  # exactly ONE editorial link
    assert len(out.splitlines()) == len(draft.splitlines())  # no line was added


def test_the_existing_mention_keeps_the_prose_casing() -> None:
    """Rewriting 'Roof Repair' to the anchor's lowercase would be a visible tell and
    would read as machine-edited."""
    draft = "# Guide\n\nProfessional Roof Repair begins with a survey.\n"
    out = pipeline_mod._place_backlink(draft, "roof repair", "https://acme.example/x", seed="s")
    assert "[Roof Repair](https://acme.example/x)" in out


def test_the_anchor_is_never_linked_inside_a_heading_or_an_existing_link() -> None:
    draft = (
        "# Roof Repair\n\n"
        "See [roof repair](https://other.example/elsewhere) for context.\n\n"
        "A later paragraph mentions roof repair plainly.\n"
    )
    out = pipeline_mod._place_backlink(draft, "roof repair", "https://acme.example/x", seed="s")
    assert out.splitlines()[0] == "# Roof Repair"  # the H1 is untouched
    assert "[[" not in out and "]](" not in out  # never nested inside the other link
    assert out.count("https://acme.example/x") == 1


def test_a_draft_with_no_mention_gets_one_sentence_inside_an_existing_paragraph() -> None:
    """The fallback must extend a paragraph, never open a new trailing section - a new
    heading is what put the old template into every heading skeleton."""
    draft = "# Gutters\n\nSeasonal clearing prevents overflow damage to the fascia.\n"
    out = pipeline_mod._place_backlink(draft, "Acme Roofing", "https://acme.example/x", seed="s")
    assert "https://acme.example/x" in out
    assert not any(line.startswith("#") for line in out.splitlines()[1:])
    assert out.count("https://acme.example/x") == 1


def test_the_fallback_sentence_differs_across_properties() -> None:
    """Two properties must not share a closing line. A single fixed sentence would just
    be the old fingerprint one line shorter."""
    draft = "# Gutters\n\nSeasonal clearing prevents overflow damage to the fascia.\n"
    variants = {
        pipeline_mod._place_backlink(draft, "Acme Roofing", "https://acme.example/x", seed=s)
        for s in ("a", "b", "c", "d", "e", "f", "g", "h")
    }
    assert len(variants) > 1, "the closing sentence must vary across properties"


def test_placement_is_stable_for_the_same_property() -> None:
    """Deterministic per seed: a redraft puts the link in the same place, so a diff is
    about the prose rather than about link churn. blake2b, not hash() - PYTHONHASHSEED
    randomises the builtin per process, so two workers would disagree."""
    draft = "# Gutters\n\nSeasonal clearing prevents overflow damage to the fascia.\n"
    a = pipeline_mod._place_backlink(draft, "Acme Roofing", "https://acme.example/x", seed="p1")
    b = pipeline_mod._place_backlink(draft, "Acme Roofing", "https://acme.example/x", seed="p1")
    assert a == b


def test_an_empty_target_url_places_no_link_at_all() -> None:
    draft = "# Gutters\n\nSeasonal clearing prevents overflow damage.\n"
    out = pipeline_mod._place_backlink(draft, "Acme Roofing", "", seed="s")
    assert "](" not in out


# --------------------------------------------------------------------------- #
# run_write: HOLDS at needs_review, never publishes
# --------------------------------------------------------------------------- #
def test_run_write_holds_at_needs_review_without_publishing() -> None:
    store = FakeWeb2Store({"w2-1": _draft_row()})
    cost = FakeCostStore(mode="api")
    writer = FakeWriter()
    outcome = run_write(
        store, "w2-1", client=_client(), writer=writer, gate=_gate(cost), settings=_settings()
    )
    assert outcome.state == "needs_review"
    assert outcome.degraded is False
    row = store.rows["w2-1"]
    assert row["status"] == "needs_review"
    assert row["body_md"].startswith("# ")
    assert row["post_url"] == ""  # NOT published
    assert writer.calls > 0  # the draft was written
    assert cost.recorded and cost.recorded[0][2] is False  # the paid write was cost-logged


def test_run_write_idempotent_on_redelivery() -> None:
    store = FakeWeb2Store({"w2-1": _draft_row(status="needs_review", body_md="# Done\n")})
    writer = FakeWriter()
    outcome = run_write(
        store, "w2-1", client=_client(), writer=writer, gate=_gate(FakeCostStore(mode="api")), settings=_settings()
    )
    assert outcome.state == "unchanged"
    assert writer.calls == 0  # no re-draft, no re-spend


def test_run_write_missing_row_is_error_not_crash() -> None:
    store = FakeWeb2Store({})
    outcome = run_write(
        store, "nope", client=_client(), writer=FakeWriter(), gate=_gate(FakeCostStore(mode="api")),
        settings=_settings(),
    )
    assert outcome.state == "error"


# --------------------------------------------------------------------------- #
# run_write: degraded (no writer) HOLDS at review; cost pre-check BLOCKS
# --------------------------------------------------------------------------- #
def test_run_write_degraded_without_writer_holds_at_review() -> None:
    store = FakeWeb2Store({"w2-1": _draft_row()})
    outcome = run_write(
        store, "w2-1", client=_client(), writer=None, gate=_gate(FakeCostStore(mode="api")), settings=_settings()
    )
    assert outcome.state == "needs_review"  # holds at review
    assert outcome.degraded is True
    row = store.rows["w2-1"]
    assert row["status"] == "needs_review"
    assert "[NEEDS:" in row["body_md"]  # a placeholder gap, never fake prose
    assert row["post_url"] == ""  # never published


def test_run_write_cost_precheck_blocks_over_budget() -> None:
    store = FakeWeb2Store({"w2-1": _draft_row()})
    # cap 1.0 already spent 1.0: any estimated write cost tips over -> blocked_cap.
    cost = FakeCostStore(mode="api", budget=(1.0, 1.0))
    writer = FakeWriter()
    outcome = run_write(
        store, "w2-1", client=_client(), writer=writer, gate=_gate(cost), settings=_settings()
    )
    assert outcome.state == "blocked"
    assert writer.calls == 0  # R5: no paid work happened
    assert store.rows["w2-1"]["status"] == "draft"  # unchanged; retriable later
    assert cost.recorded == []  # nothing was charged


def test_run_write_dial_off_blocks() -> None:
    store = FakeWeb2Store({"w2-1": _draft_row()})
    writer = FakeWriter()
    outcome = run_write(
        store, "w2-1", client=_client(), writer=writer, gate=_gate(FakeCostStore(mode="off")),
        settings=_settings(),
    )
    assert outcome.state == "blocked"
    assert writer.calls == 0


# --------------------------------------------------------------------------- #
# run_publish: approval publishes + verifies + tracks
# --------------------------------------------------------------------------- #
def _written_row(**over: Any) -> dict[str, Any]:
    body = (
        "# Roof repair guide\n\nWhy roof repair matters for your home.\n\n"
        "## More about roof repair\n\nLearn more: [roof repair](https://acme.example/roof-repair).\n"
    )
    base = _draft_row(status="publishing", body_md=body)
    base.update(over)
    return base


def test_run_publish_publishes_verifies_and_tracks() -> None:
    store = FakeWeb2Store({"w2-1": _written_row()})
    cost = FakeCostStore(mode="api")
    outcome = run_publish(
        store, "w2-1", publisher=FakeWeb2Publisher(), gate=_gate(cost), settings=_settings()
    )
    assert outcome.state == "published"
    assert outcome.verified is True
    assert outcome.post_url
    row = store.rows["w2-1"]
    assert row["status"] == "published"
    assert row["verified"] == "verified"
    assert row["post_url"] == outcome.post_url
    assert row["external_id"]
    assert row["published_at"] is not None
    assert cost.recorded  # the publish was cost-logged


def test_run_publish_idempotent_when_already_published() -> None:
    store = FakeWeb2Store({"w2-1": _written_row(status="published", post_url="https://x/y")})

    class BoomPublisher:
        def publish(self, platform: str, post: Any) -> Web2PublishResult:  # pragma: no cover
            raise AssertionError("must not re-publish an already-published row")

    outcome = run_publish(
        store, "w2-1", publisher=BoomPublisher(), gate=_gate(FakeCostStore(mode="api")), settings=_settings()
    )
    assert outcome.state == "unchanged"


def test_run_publish_skips_when_not_approved() -> None:
    store = FakeWeb2Store({"w2-1": _written_row(status="needs_review")})
    outcome = run_publish(
        store, "w2-1", publisher=FakeWeb2Publisher(), gate=_gate(FakeCostStore(mode="api")), settings=_settings()
    )
    assert outcome.state == "skipped"  # not approved -> never published


def test_run_publish_degraded_without_publisher_holds_at_review() -> None:
    store = FakeWeb2Store({"w2-1": _written_row()})
    outcome = run_publish(
        store, "w2-1", publisher=None, gate=_gate(FakeCostStore(mode="api")), settings=_settings()
    )
    assert outcome.state == "needs_review"  # holds at the review gate
    assert outcome.degraded is True
    assert store.rows["w2-1"]["status"] == "needs_review"


def test_run_publish_refuses_a_draft_with_unresolved_gaps() -> None:
    store = FakeWeb2Store({"w2-1": _written_row(body_md="# Draft\n\n[NEEDS: real copy]\n")})
    outcome = run_publish(
        store, "w2-1", publisher=FakeWeb2Publisher(), gate=_gate(FakeCostStore(mode="api")), settings=_settings()
    )
    assert outcome.state == "needs_review"  # never publishes an incomplete draft
    assert store.rows["w2-1"]["status"] == "needs_review"


def test_run_publish_cost_precheck_blocks_and_holds() -> None:
    store = FakeWeb2Store({"w2-1": _written_row()})
    # Force a block via a halted org spend-stop (independent of the estimated cost).
    outcome = run_publish(
        store, "w2-1", publisher=FakeWeb2Publisher(), gate=_gate(FakeCostStore(halted=True)),
        settings=_settings(),
    )
    assert outcome.state == "blocked"
    assert store.rows["w2-1"]["status"] == "needs_review"  # held, not published


def test_run_publish_provider_error_marks_failed_never_raises() -> None:
    store = FakeWeb2Store({"w2-1": _written_row()})

    class BoomPublisher:
        def publish(self, platform: str, post: Any) -> Web2PublishResult:
            raise RuntimeError("provider down")

    outcome = run_publish(
        store, "w2-1", publisher=BoomPublisher(), gate=_gate(FakeCostStore(mode="api")), settings=_settings()
    )
    assert outcome.state == "failed"  # never stuck 'publishing', never re-raised
    assert store.rows["w2-1"]["status"] == "failed"


# --------------------------------------------------------------------------- #
# Medium is draft-only
# --------------------------------------------------------------------------- #
def test_medium_publish_is_draft_only_pending() -> None:
    store = FakeWeb2Store({"w2-1": _written_row(platform=PLATFORM_MEDIUM)})
    outcome = run_publish(
        store, "w2-1", publisher=FakeWeb2Publisher(), gate=_gate(FakeCostStore(mode="api")), settings=_settings()
    )
    assert outcome.state == "published"
    assert outcome.verified is False  # Medium is draft-only, never 'live/verified'
    assert store.rows["w2-1"]["verified"] == "pending"


def test_verify_live_and_indexable_rules() -> None:
    ok = Web2PublishResult(post_url="https://x/y", verified=True)
    assert verify_live_and_indexable(ok, PLATFORM_WORDPRESS)[0] is True
    draft = Web2PublishResult(post_url="https://x/y", verified=False, draft_only=True)
    assert verify_live_and_indexable(draft, PLATFORM_MEDIUM)[0] is False
    no_url = Web2PublishResult(post_url="", verified=True)
    assert verify_live_and_indexable(no_url, PLATFORM_WORDPRESS)[0] is False


# --------------------------------------------------------------------------- #
# Footprint diversification (anti-SpamBrain)
# --------------------------------------------------------------------------- #
def test_footprint_diversification_is_deterministic_and_varies() -> None:
    platforms = [PLATFORM_WORDPRESS, "Blogger", "Tumblr"]
    accounts = ["acct-a", "acct-b", "acct-c"]
    anchors = ["roof repair", "roofing services", "roof leak fix"]

    a1 = diversify_footprint(seed="cl-1|t-1", platforms=platforms, accounts=accounts, anchors=anchors)
    a2 = diversify_footprint(seed="cl-1|t-1", platforms=platforms, accounts=accounts, anchors=anchors)
    assert a1 == a2  # deterministic in the seed
    assert a1.platform in platforms and a1.account in accounts and a1.anchor in anchors
    assert 0 <= a1.delay_seconds < 2 * 86_400  # jittered timing

    # Different seeds spread across the inventory (not all identical).
    choices = {
        diversify_footprint(
            seed=f"cl-1|t-{i}", platforms=platforms, accounts=accounts, anchors=anchors
        )
        for i in range(12)
    }
    assert len({c.platform for c in choices}) > 1
    assert len({c.anchor for c in choices}) > 1


def test_footprint_diversification_avoids_used_pairs() -> None:
    platforms = [PLATFORM_WORDPRESS, "Blogger"]
    anchors = ["roof repair", "roofing services"]
    used = [(PLATFORM_WORDPRESS, "roof repair"), (PLATFORM_WORDPRESS, "roofing services")]
    choice = diversify_footprint(
        seed="cl-9|t-9", platforms=platforms, accounts=["a"], anchors=anchors, existing=used
    )
    # Every WordPress.com pair is used -> it must pick a Blogger pair instead.
    assert (choice.platform, choice.anchor) not in used
    assert choice.platform == "Blogger"


def test_footprint_diversification_requires_inventory() -> None:
    with pytest.raises(ValueError, match="at least one"):
        diversify_footprint(seed="x", platforms=[], accounts=["a"], anchors=["b"])


# --------------------------------------------------------------------------- #
# Markdown -> HTML + title split (publish rendering)
# --------------------------------------------------------------------------- #
def test_split_title_and_body_lifts_the_h1() -> None:
    title, rest = split_title_and_body("# My Title\n\nBody paragraph.\n")
    assert title == "My Title"
    assert "My Title" not in rest
    assert "Body paragraph." in rest


def test_markdown_to_html_renders_subset() -> None:
    html = markdown_to_html("## Heading\n\nA [link](https://x).\n\n- one\n- two")
    assert "<h2>Heading</h2>" in html
    assert '<a href="https://x">link</a>' in html
    assert "<ul><li>one</li><li>two</li></ul>" in html


# --------------------------------------------------------------------------- #
# The measured link. "Published" is the platform accepting the post; whether OUR
# link survived on the page is a separate fact, and the one a client is paying for.
# --------------------------------------------------------------------------- #
def test_publishing_records_the_measured_link_and_its_rel() -> None:
    store = FakeWeb2Store({"w2-1": _written_row()})
    page = '<a href="https://acme.example/roof-repair" rel="nofollow">roof repair</a>'
    outcome = run_publish(
        store, "w2-1", publisher=FakeWeb2Publisher(), gate=_gate(FakeCostStore(mode="api")),
        settings=_settings(), fetch_page=lambda url: page,
    )
    assert outcome.state == "published"
    row = store.rows["w2-1"]
    assert row["link_found"] is True
    assert row["link_rel"] == "nofollow"      # found, but passes no equity
    assert row["link_checked_at"] is not None


def test_a_page_missing_our_link_is_recorded_as_missing() -> None:
    """The finding that matters commercially: the platform accepted the post and then
    stripped the link. Without this the placement reports as delivered."""
    store = FakeWeb2Store({"w2-1": _written_row()})
    outcome = run_publish(
        store, "w2-1", publisher=FakeWeb2Publisher(), gate=_gate(FakeCostStore(mode="api")),
        settings=_settings(), fetch_page=lambda url: "<p>no links here</p>",
    )
    assert outcome.state == "published"
    assert store.rows["w2-1"]["link_found"] is False


def test_an_unreachable_page_leaves_the_link_unchecked_not_failed() -> None:
    """`unknown` must not be written as False. A network problem is not evidence that a
    platform removed our link, and recording it as one would send someone chasing a
    defect that does not exist."""
    store = FakeWeb2Store({"w2-1": _written_row()})
    outcome = run_publish(
        store, "w2-1", publisher=FakeWeb2Publisher(), gate=_gate(FakeCostStore(mode="api")),
        settings=_settings(), fetch_page=lambda url: None,
    )
    assert outcome.state == "published"           # the publish still succeeded
    assert store.rows["w2-1"].get("link_found") is None
    assert store.rows["w2-1"].get("link_checked_at") is None


def test_publishing_without_a_fetcher_still_publishes() -> None:
    """The check is additive. A deployment with no outbound access must still publish."""
    store = FakeWeb2Store({"w2-1": _written_row()})
    outcome = run_publish(
        store, "w2-1", publisher=FakeWeb2Publisher(), gate=_gate(FakeCostStore(mode="api")),
        settings=_settings(),
    )
    assert outcome.state == "published"
    assert store.rows["w2-1"].get("link_found") is None


# --------------------------------------------------------------------------- #
# R2-07: a shared-origin property is frozen, not published to again.
# --------------------------------------------------------------------------- #
def test_a_shared_origin_property_is_frozen_before_any_provider_call() -> None:
    """The flag was set by the reconciliation, shown in the reports, and enforced
    nowhere - so a property known to sit on a credential shared across clients would
    happily keep publishing, extending exactly the correlation the flag records."""
    store = FakeWeb2Store({"w2-1": _written_row(shared_origin=True)})
    publisher = FakeWeb2Publisher()
    outcome = run_publish(
        store, "w2-1", publisher=publisher, gate=_gate(FakeCostStore(mode="api")),
        settings=_settings(),
    )
    assert outcome.state == "needs_review"
    assert outcome.reason == "shared_origin_frozen"
    row = store.rows["w2-1"]
    assert row["status"] == "needs_review"
    assert "shared_origin" in row["error"]
    assert row["post_url"] == ""          # nothing went live


def test_the_freeze_does_not_touch_a_normal_property() -> None:
    store = FakeWeb2Store({"w2-1": _written_row()})
    outcome = run_publish(
        store, "w2-1", publisher=FakeWeb2Publisher(), gate=_gate(FakeCostStore(mode="api")),
        settings=_settings(),
    )
    assert outcome.state == "published"


# --------------------------------------------------------------------------- #
# Heading frames vs title-shaped topics
# --------------------------------------------------------------------------- #
def test_a_keyword_topic_still_fills_the_heading_frames() -> None:
    """The local-SEO case must not regress: a real keyword belongs IN the heading."""
    from app.services.content_generator import is_keyword_phrase, render_heading

    assert is_keyword_phrase("emergency drain unblocking")
    assert render_heading(
        "The problem with {primary}", primary="emergency drain unblocking", client="Acme"
    ) == "The problem with emergency drain unblocking"


def test_a_title_shaped_topic_never_lands_inside_a_heading_frame() -> None:
    """The defect this guards: the campaign wizard's OWN placeholder example is a
    title, and interpolating one produced 'What is what a CCTV drain survey shows?' -
    broken English in a client-facing H2. A title drops out of the frame instead."""
    from app.services.content_generator import is_keyword_phrase, render_heading

    title = "what a CCTV drain survey shows"
    assert not is_keyword_phrase(title)

    heading = render_heading("The problem with {primary}", primary=title, client="Acme")
    assert heading == "The problem"
    assert title not in heading

    # And the long declarative form, which is what a real operator typed.
    long_title = "What an AI audit actually measures before anyone automates anything"
    assert not is_keyword_phrase(long_title)
    for frame in ("Why {primary} matters", "How {primary} works", "{primary} features"):
        rendered = render_heading(frame, primary=long_title, client="Acme")
        assert long_title not in rendered, f"{frame!r} still swallowed the title"
        assert "{primary}" not in rendered


def test_seed_brief_faq_questions_survive_a_title_topic() -> None:
    """The FAQ H3s are built from the topic too, and were the worst offender:
    'What is What an AI audit actually measures...?' has two question words."""
    from app.services.web2_pipeline import _seed_brief

    brief = _seed_brief(
        "What an AI audit actually measures before anyone automates anything", None, None
    )
    for question in brief.terms.questions:
        assert not question.lower().startswith("what is what"), question
        assert len(question.split()) <= 8, f"FAQ heading reads as a sentence: {question}"


def test_a_capped_title_never_keeps_a_dangling_separator() -> None:
    """A title is "{lead} | {brand}". When the cap eats the brand, the pipe must go with
    it - "How AI consultancies scope a first automation project |" was published as the
    H1 and as the post title on every platform, brand amputated, separator dangling."""
    from app.services.content_generator import TITLE_MAX_CHARS, _cap

    # A NEUTRAL brand on purpose: `test_builder_branding` scans the tree for the
    # builder's own name, and example data is not a reason to put it back.
    # 72 chars: the cap eats the brand entirely, which is exactly when the separator was
    # left stranded. A NEUTRAL brand on purpose - `test_builder_branding` scans the tree
    # for the builder's own name, and example data is not a reason to put it back.
    capped = _cap(
        "How consultancies scope their first automation project | Acme Consulting",
        TITLE_MAX_CHARS,
    )
    assert not capped.rstrip().endswith("|"), capped
    assert capped == "How consultancies scope their first automation project"
    # A title that FITS keeps its brand - the fix must not strip legitimate separators.
    assert _cap("AI audit | Acme", TITLE_MAX_CHARS) == "AI audit | Acme"


def test_hashnode_never_declares_the_backlink_target_as_the_canonical_source() -> None:
    """``originalArticleURL`` emits <link rel="canonical"> and "Originally published
    at ...". Passing the BACKLINK DESTINATION there made every Hashnode property declare
    itself a duplicate of the client's own page: it drops out of the index as an
    independent document and the editorial link passes nothing - while the placement row
    still reports published and verified."""
    import inspect

    from integrations import web2_publishers

    source = inspect.getsource(web2_publishers.HashnodeClient.publish)
    # Assert against CODE, not commentary: the comment explaining the removal naturally
    # names both the field and the variable.
    code = "\n".join(
        line for line in source.splitlines() if not line.lstrip().startswith("#")
    )
    assert "originalArticleURL" not in code, (
        "the canonical-source field is back in the Hashnode mutation"
    )
    # target_url may still reach the post - but only as the anchor href in the body.
    assert "post.target_url" not in code, (
        "target_url must not be passed to Hashnode outside the rendered body"
    )
