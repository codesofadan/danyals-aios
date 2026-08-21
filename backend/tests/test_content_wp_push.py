"""Unit gate for the APPROVE -> PUSH-to-WordPress-plugin publish wiring
(``workers.tasks.content.publish_content_job`` with a plugin target).

Proves, with a fake store + a fake/injected plugin publisher (NO Celery, DB, or
network):

* an approved job with a plugin target is PUSHED as a DRAFT: the returned permalink +
  edit link land on ``wp_url`` / ``wp_edit_url`` (+ ``wp_post_id``), the job goes
  ``publishing -> done``, and the stage reads "Pushed to WordPress (draft)";
* the pushed payload is the rendered HTML draft at status ``draft`` (a human publishes
  it on WordPress) - and carries NO raw secret (the adapter injects the key);
* a plugin push FAILURE is swallowed and the job still ADVANCES (falls back to the
  artifact path), never crashing the approve;
* NO plugin target configured = NO push - the existing app-password path runs
  unchanged and no wp_url is written.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.config import Settings
from integrations.wordpress import FakeWordPressPublisher
from integrations.wordpress_publisher import (
    FakeWordPressPluginPublisher,
    PluginPublishResult,
    WordPressPluginError,
)
from workers.tasks.content import WpTarget, publish_content_job

pytestmark = pytest.mark.unit


class FakeContentStore:
    """In-memory ``ContentStore`` keyed by ``code`` (mirrors the privileged repo)."""

    def __init__(self, row: dict[str, Any]) -> None:
        self.row = dict(row)
        self.updates: list[dict[str, Any]] = []

    def load(self, code: str) -> dict[str, Any] | None:
        return dict(self.row) if self.row.get("code") == code else None

    def update(self, code: str, fields: dict[str, Any]) -> dict[str, Any] | None:
        self.updates.append(dict(fields))
        self.row.update(fields)
        return dict(self.row)


def _settings(**over: Any) -> Settings:
    return Settings(_env_file=None, app_env="dev", **over)


def _publish_row(**over: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "code": "CJ-4200",
        "client_id": None,  # skip the deliverable/email legs - hermetic
        "client_name": "Verde Cafe",
        "page_type": "blog",
        "topic": "best brunch in portland",
        "target": "WordPress",
        "status": "publishing",
        "draft_md": "# Best Brunch in Portland\n\nA grounded, reviewed draft body.\n\n- one\n- two\n",
        "qa_score": {"passed": True, "blocked_by": [], "weighted_total": 91},
        "wp_post_id": None,
        "outline": {"meta": {"title": "Best Brunch in Portland (2026)", "description": "The definitive guide."}},
        "keyword_map": {"primary": "best brunch in portland"},
        "json_ld": {"@graph": [{"@type": "Article"}]},
    }
    row.update(over)
    return row


def _plugin(publisher: Any) -> Any:
    """A resolve_wp_plugin that returns the given publisher for any row."""
    return lambda row, settings: publisher


def _never_wp(row: dict[str, Any], settings: Settings) -> None:
    """A resolve_wp that never yields an app-password target."""
    return None


def _wp(publisher: Any, site_url: str = "https://verde.example") -> Any:
    return lambda row, settings: WpTarget(site_url=site_url, publisher=publisher)


class _RaisingPlugin:
    """A plugin publisher whose push always fails (to prove the fallback)."""

    def ping(self) -> bool:
        return True

    def publish(self, payload: dict[str, Any]) -> PluginPublishResult:
        raise WordPressPluginError("boom")


# --------------------------------------------------------------------------- #
# 1. Approve -> push to the plugin as a DRAFT, store the URLs, mark done.
# --------------------------------------------------------------------------- #
def test_approve_pushes_to_plugin_and_stores_wp_urls() -> None:
    store = FakeContentStore(_publish_row())
    fake = FakeWordPressPluginPublisher(site_url="https://verde.example")

    out = publish_content_job(
        store, None, "CJ-4200",
        settings=_settings(), resolve_wp_plugin=_plugin(fake),
    )

    assert out.state == "published"
    assert out.status == "done"
    assert store.row["status"] == "done"
    assert store.row["wp_url"].startswith("https://verde.example/")
    assert store.row["wp_edit_url"].startswith("https://verde.example/wp-admin/")
    assert store.row["wp_post_id"]  # recorded
    assert "Pushed to WordPress (draft)" in store.row["stage"]

    # The pushed payload is the rendered HTML draft, pushed as a DRAFT, and carries no
    # raw secret (the real adapter injects the key; the fake receives only content).
    pushed = fake.published[0]
    assert pushed["status"] == "draft"
    assert "<h1>Best Brunch in Portland</h1>" in pushed["content"]
    assert pushed["meta_title"] == "Best Brunch in Portland (2026)"
    assert pushed["focus_keyword"] == "best brunch in portland"
    assert "schema_jsonld" in pushed  # the JSON-LD graph rode along
    assert "api_key" not in pushed


# --------------------------------------------------------------------------- #
# 2. A plugin push FAILURE is swallowed; the job still advances (artifact path).
# --------------------------------------------------------------------------- #
def test_plugin_push_failure_is_swallowed_and_job_advances(tmp_path: Any) -> None:
    from app.services.content_artifacts import LocalContentArtifactStore

    artifacts = LocalContentArtifactStore(tmp_path)
    store = FakeContentStore(_publish_row())

    out = publish_content_job(
        store, None, "CJ-4200",
        settings=_settings(), artifacts=artifacts,
        resolve_wp_plugin=_plugin(_RaisingPlugin()),  # push raises
        resolve_wp=_never_wp,                          # no app-password fallback
    )

    # Fell back to the artifact path: still delivered, NEVER failed / crashed.
    assert out.status == "done"
    assert out.state == "degraded"
    assert store.row["status"] == "done"
    assert store.row.get("wp_url") is None  # nothing pushed
    assert store.row["md_path"] == "CJ-4200/content.md"


# --------------------------------------------------------------------------- #
# 3. NO plugin target = NO push - the legacy app-password path runs unchanged.
# --------------------------------------------------------------------------- #
def test_no_plugin_target_uses_legacy_wordpress_path() -> None:
    store = FakeContentStore(_publish_row())

    out = publish_content_job(
        store, None, "CJ-4200",
        settings=_settings(),
        resolve_wp_plugin=lambda row, settings: None,   # no plugin target
        resolve_wp=_wp(FakeWordPressPublisher()),        # legacy app-password target
    )

    assert out.state == "published"
    assert out.reason == "drafted to WordPress"  # the legacy REST path, not the plugin (drafts)
    assert store.row["status"] == "done"
    assert store.row.get("wp_url") is None  # the plugin push never ran
    assert store.row["stage"].startswith("Draft on WordPress")


# --------------------------------------------------------------------------- #
# 4. QA is ADVISORY: a sub-threshold draft still pushes (human review is the gate).
# --------------------------------------------------------------------------- #
def test_qa_does_not_block_plugin_push() -> None:
    store = FakeContentStore(_publish_row(qa_score={"passed": False, "blocked_by": ["fact_grounding"]}))
    fake = FakeWordPressPluginPublisher(site_url="https://verde.example")

    out = publish_content_job(
        store, None, "CJ-4200",
        settings=_settings(), resolve_wp_plugin=_plugin(fake),
    )

    assert out.state == "published"   # QA score no longer blocks publish
    assert len(fake.published) == 1   # pushed despite the failing QA score
    assert store.row["status"] == "done"


# --------------------------------------------------------------------------- #
# 5. The article-template components are derived from the draft into the payload.
# --------------------------------------------------------------------------- #
def test_plugin_payload_derives_article_components() -> None:
    from workers.tasks.content import _derive_faq, _derive_takeaways, _plugin_payload

    draft = (
        "# The Title\n\n"
        "An intro paragraph.\n\n"
        "## Key Takeaways\n\n"
        "- First point\n"
        "- Second **bold** point\n\n"
        "## Details\n\n"
        "Some body copy here.\n\n"
        "## FAQ\n\n"
        "### Is it fast?\n\n"
        "Yes, very fast.\n\n"
        "### Is it safe?\n\n"
        "Absolutely safe.\n"
    )
    assert _derive_takeaways(draft) == ["First point", "Second bold point"]
    assert _derive_faq(draft) == [
        {"question": "Is it fast?", "answer": "Yes, very fast."},
        {"question": "Is it safe?", "answer": "Absolutely safe."},
    ]

    payload = _plugin_payload(_publish_row(), draft, "The Title")
    assert payload["key_takeaways"] == ["First point", "Second bold point"]
    assert len(payload["faq"]) == 2
    # A CTA is always present (best practice) and defaults to a contact button.
    assert payload["cta"]["button_label"] == "Get in touch"


def test_plugin_payload_no_faq_when_draft_has_none() -> None:
    from workers.tasks.content import _plugin_payload

    payload = _plugin_payload(_publish_row(), "# T\n\nBody only, no FAQ.\n", "T")
    assert "faq" not in payload  # absent -> the plugin omits the FAQ component
    assert "cta" in payload


# --------------------------------------------------------------------------- #
# 6. Featured image: the plugin sideloads the draft's HERO image into the
# WordPress media library (spec: in-body images must not stay hotlinked forever
# to the AIOS content-image host).
# --------------------------------------------------------------------------- #
def test_first_image_url_is_the_first_markdown_image() -> None:
    from workers.tasks.content import _first_image_url

    draft = (
        "# T\n\n![Hero shot](https://img.example/hero.png)\n\nIntro copy.\n\n"
        "## Section\n\n![Second](https://img.example/second.png)\n"
    )
    assert _first_image_url(draft) == "https://img.example/hero.png"


def test_first_image_url_empty_when_no_images() -> None:
    from workers.tasks.content import _first_image_url

    assert _first_image_url("# T\n\nJust text, no images.\n") == ""


def test_plugin_payload_carries_featured_image_url_from_the_hero_image() -> None:
    from workers.tasks.content import _plugin_payload

    draft = "# T\n\n![Hero shot](https://img.example/hero.png)\n\nIntro copy.\n"
    payload = _plugin_payload(_publish_row(), draft, "T")
    assert payload["featured_image_url"] == "https://img.example/hero.png"


def test_plugin_payload_omits_featured_image_url_when_draft_has_no_images() -> None:
    from workers.tasks.content import _plugin_payload

    payload = _plugin_payload(_publish_row(), "# T\n\nNo images here.\n", "T")
    assert "featured_image_url" not in payload
