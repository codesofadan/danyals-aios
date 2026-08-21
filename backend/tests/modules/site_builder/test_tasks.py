"""``app.modules.site_builder.tasks.execute_analyze``: the never-stuck orchestration
core.

NO DB, NO network, NO broker, NO real browser: the store is in-memory and the
analyzer is injected via ``analyzer_builder`` - the Celery task itself is never
invoked (``.delay`` is never called). Mirrors ``tests/modules/on_page/test_tasks.py``'s
own framing: every test here maps to something that goes wrong for real -
redelivery double-running a browser capture, an unreachable site, an unknown
template, a fully offline (no-Playwright) box.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.modules.site_builder.tasks import (
    execute_analyze,
    execute_render_and_publish,
    execute_visual_qa,
)
from app.services.wp_connections import ResolvedWpConnection
from integrations.site_analyzer import (
    DEGRADE_CAPTURE_FAILED,
    CaptureResult,
    SectionSnapshot,
    SiteCapture,
    ViewportCapture,
)
from integrations.wordpress_publisher import FakeWordPressPluginPublisher, WordPressPluginError

pytestmark = pytest.mark.unit


class FakeStore:
    """In-memory stand-in for :class:`ServiceSiteBuilderStore`."""

    def __init__(self) -> None:
        self.jobs: dict[str, dict[str, Any]] = {}
        self.designs: list[dict[str, Any]] = []
        self.templates: dict[str, dict[str, Any]] = {}
        self.validations: list[dict[str, Any]] = []
        self._next_design_id = 1

    def get_template_by_key(self, key: str) -> dict[str, Any] | None:
        row = self.templates.get(key)
        return dict(row) if row else None

    def get_design_ir(self, design_ir_id: str) -> dict[str, Any] | None:
        return next((dict(d) for d in self.designs if d["id"] == design_ir_id), None)

    def insert_visual_validation(
        self, *, job_id: str, rendered_url: str, status: str, diagnostics: list[dict[str, Any]],
    ) -> dict[str, Any]:
        row = {"id": f"vv-{len(self.validations) + 1}", "job_id": job_id, "rendered_url": rendered_url,
               "status": status, "diagnostics": diagnostics}
        self.validations.append(row)
        return row

    def get_job(self, job_id: str) -> dict[str, Any] | None:
        row = self.jobs.get(job_id)
        return dict(row) if row else None

    def update_job(self, job_id: str, fields: dict[str, Any]) -> dict[str, Any] | None:
        row = self.jobs.get(job_id)
        if row is None:
            return None
        row.update(fields)
        return dict(row)

    def insert_design_ir(
        self, body: dict[str, Any], *, client_id: str | None, client_name: str, created_by: str | None,
    ) -> dict[str, Any]:
        row = {"id": f"design-{self._next_design_id}", "client_id": client_id, **body}
        self._next_design_id += 1
        self.designs.append(row)
        return row


def _job(**over: Any) -> dict[str, Any]:
    base = {
        "id": "job-1", "status": "queued", "source_type": "template", "source_url": "",
        "page_type": "homepage", "industry": "", "client_id": None, "client_name": "",
        "created_by": None,
    }
    base.update(over)
    return base


def test_unknown_job_id_fails_cleanly() -> None:
    result = execute_analyze(FakeStore(), "missing")  # type: ignore[arg-type]
    assert result["status"] == "failed"


def test_redelivery_on_an_already_advanced_job_is_a_noop() -> None:
    store = FakeStore()
    store.jobs["job-1"] = _job(status="generating")
    result = execute_analyze(store, "job-1")  # type: ignore[arg-type]
    assert result["status"] == "generating"
    assert store.designs == []  # no double-analysis, no double-spend


def test_template_source_resolves_a_design_and_advances_to_generating() -> None:
    store = FakeStore()
    store.jobs["job-1"] = _job(source_type="template", page_type="service")
    result = execute_analyze(store, "job-1")  # type: ignore[arg-type]
    assert result["status"] == "generating"
    assert result["design_ir_id"] == store.designs[0]["id"]
    assert store.designs[0]["source_type"] == "template"


def test_template_resolves_through_the_catalog_key_when_one_matches() -> None:
    """A ``site_templates.key`` (e.g. "homepage-generic") resolves via its
    ``blueprint_key`` rather than being treated as a raw page_blueprints name."""
    store = FakeStore()
    store.templates["homepage-generic"] = {
        "key": "homepage-generic", "blueprint_key": "homepage", "design_style": "modern",
    }
    store.jobs["job-1"] = _job(source_type="template", page_type="homepage-generic")
    result = execute_analyze(store, "job-1")  # type: ignore[arg-type]
    assert result["status"] == "generating"
    assert store.designs[0]["design_style"] == "modern"


def test_unknown_template_fails_the_job() -> None:
    store = FakeStore()
    store.jobs["job-1"] = _job(source_type="template", page_type="not-a-real-template")
    result = execute_analyze(store, "job-1")  # type: ignore[arg-type]
    assert result["status"] == "failed"
    assert "unknown_template" in result["error"]
    assert store.designs == []


def test_manual_source_seeds_a_blank_canvas() -> None:
    store = FakeStore()
    store.jobs["job-1"] = _job(source_type="manual")
    result = execute_analyze(store, "job-1")  # type: ignore[arg-type]
    assert result["status"] == "generating"
    assert store.designs[0]["source_type"] == "manual"
    assert store.designs[0]["source_url"] == ""


def test_existing_site_uses_the_injected_analyzer_and_resolves_a_design() -> None:
    store = FakeStore()
    store.jobs["job-1"] = _job(source_type="existing_site", source_url="https://example.com")

    class _Ok:
        def capture(self, url: str, *, viewports: Any) -> CaptureResult:
            return CaptureResult(
                status="ok",
                capture=SiteCapture(
                    url=url, title="Example",
                    viewports=[ViewportCapture(viewport="desktop", width=1440, height=900)],
                ),
            )

    result = execute_analyze(store, "job-1", analyzer_builder=lambda: _Ok())  # type: ignore[arg-type]
    assert result["status"] == "generating"
    assert store.designs[0]["source_type"] == "existing_site"
    assert store.designs[0]["source_url"] == "https://example.com"


def test_a_failed_capture_fails_the_job_with_the_reason_not_a_crash() -> None:
    store = FakeStore()
    store.jobs["job-1"] = _job(source_type="existing_site", source_url="https://example.com")

    class _Failing:
        def capture(self, url: str, *, viewports: Any) -> CaptureResult:
            return CaptureResult(status="degraded", capture=None, reason=DEGRADE_CAPTURE_FAILED)

    result = execute_analyze(store, "job-1", analyzer_builder=lambda: _Failing())  # type: ignore[arg-type]
    assert result["status"] == "failed"
    assert DEGRADE_CAPTURE_FAILED in result["error"]
    assert store.designs == []


def test_no_playwright_installed_fails_the_job_cleanly() -> None:
    store = FakeStore()
    store.jobs["job-1"] = _job(source_type="existing_site", source_url="https://example.com")
    result = execute_analyze(store, "job-1", analyzer_builder=lambda: None)  # type: ignore[arg-type]
    assert result["status"] == "failed"
    assert "playwright_unconfigured" in result["error"]


# --------------------------------------------------------------------------- #
# execute_visual_qa
# --------------------------------------------------------------------------- #
def _design_row(**over: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "id": "design-1", "typography": {}, "layout": {"container_width_px": 1200},
        "sections": [{"kind": "hero", "bg_color": "rgb(255, 255, 255)", "width": 1440, "height": 560}],
        "assets": [], "responsive": [],
    }
    base.update(over)
    return base


def test_visual_qa_with_no_design_yet_fails_cleanly() -> None:
    store = FakeStore()
    store.jobs["job-1"] = _job(design_ir_id=None)
    result = execute_visual_qa(store, "job-1", rendered_url="https://example.com")  # type: ignore[arg-type]
    assert result["status"] == "failed"
    assert "no_design_to_validate_against" in result["error"]


def test_visual_qa_matching_capture_completes_the_job() -> None:
    store = FakeStore()
    store.designs.append(_design_row())
    store.jobs["job-1"] = _job(design_ir_id="design-1")

    class _Match:
        def capture(self, url: str, *, viewports: Any) -> CaptureResult:
            return CaptureResult(
                status="ok",
                capture=SiteCapture(
                    url=url,
                    viewports=[
                        ViewportCapture(
                            viewport="desktop", width=1440, height=900, container_width_px=1200,
                            sections=[
                                SectionSnapshot(tag="div", role="section", bg_color="rgb(255, 255, 255)", width=1440, height=560)
                            ],
                        )
                    ],
                ),
            )

    result = execute_visual_qa(
        store, "job-1", rendered_url="https://example.com", analyzer_builder=lambda: _Match()  # type: ignore[arg-type]
    )
    assert result["status"] == "completed"
    assert store.validations[0]["status"] == "pass"


def test_visual_qa_mismatched_capture_moves_the_job_to_correcting() -> None:
    store = FakeStore()
    store.designs.append(_design_row())
    store.jobs["job-1"] = _job(design_ir_id="design-1")

    class _Mismatch:
        def capture(self, url: str, *, viewports: Any) -> CaptureResult:
            return CaptureResult(
                status="ok",
                capture=SiteCapture(
                    url=url,
                    viewports=[
                        ViewportCapture(
                            viewport="desktop", width=1440, height=900, container_width_px=500,
                            sections=[
                                SectionSnapshot(tag="div", role="section", bg_color="rgb(0, 0, 0)", width=400, height=200)
                            ],
                        )
                    ],
                ),
            )

    result = execute_visual_qa(
        store, "job-1", rendered_url="https://example.com", analyzer_builder=lambda: _Mismatch()  # type: ignore[arg-type]
    )
    assert result["status"] == "correcting"
    assert store.validations[0]["status"] in ("warn", "fail")
    assert store.validations[0]["diagnostics"]  # structured, not just a score


def test_visual_qa_capture_failure_fails_the_job_and_records_a_verdict() -> None:
    store = FakeStore()
    store.designs.append(_design_row())
    store.jobs["job-1"] = _job(design_ir_id="design-1")

    result = execute_visual_qa(
        store, "job-1", rendered_url="https://example.com", analyzer_builder=lambda: None  # type: ignore[arg-type]
    )
    assert result["status"] == "failed"
    assert store.validations[0]["status"] == "fail"


# --------------------------------------------------------------------------- #
# execute_render_and_publish
# --------------------------------------------------------------------------- #
_CONN = ResolvedWpConnection(
    client_id="cl-1", site_url="https://example.com", auth_method="plugin",
    username="", secret="shared-key",
)


def _publish_design_row(**over: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "id": "design-1", "source_type": "template", "page_type": "homepage",
        "palette": {}, "typography": {}, "components": {},
        "sections": [
            {"kind": "hero", "heading": "Welcome to Acme", "layout": "split",
             "text_sample": "We build great things.", "content": True},
        ],
    }
    base.update(over)
    return base


def _matching_capture_analyzer() -> Any:
    class _Ok:
        def capture(self, url: str, *, viewports: Any) -> CaptureResult:
            return CaptureResult(
                status="ok",
                capture=SiteCapture(url=url, viewports=[ViewportCapture(viewport="desktop", width=1440, height=900)]),
            )

    return _Ok()


def test_publish_redelivery_on_a_non_generating_job_is_a_noop() -> None:
    store = FakeStore()
    store.jobs["job-1"] = _job(status="completed")
    result = execute_render_and_publish(store, "job-1")  # type: ignore[arg-type]
    assert result["status"] == "completed"


def test_publish_with_no_design_fails_cleanly() -> None:
    store = FakeStore()
    store.jobs["job-1"] = _job(status="generating", design_ir_id=None)
    result = execute_render_and_publish(store, "job-1")  # type: ignore[arg-type]
    assert result["status"] == "failed"
    assert "no_design_to_render" in result["error"]


def test_publish_with_no_client_fails_cleanly() -> None:
    store = FakeStore()
    store.designs.append(_publish_design_row())
    store.jobs["job-1"] = _job(status="generating", design_ir_id="design-1", client_id=None)
    result = execute_render_and_publish(store, "job-1")  # type: ignore[arg-type]
    assert result["status"] == "failed"
    assert "no_client_assigned" in result["error"]


def test_publish_with_no_wordpress_connection_fails_cleanly() -> None:
    store = FakeStore()
    store.designs.append(_publish_design_row())
    store.jobs["job-1"] = _job(status="generating", design_ir_id="design-1", client_id="cl-1")
    result = execute_render_and_publish(store, "job-1", connection_resolver=lambda cid: None)  # type: ignore[arg-type]
    assert result["status"] == "failed"
    assert "no_wordpress_connection" in result["error"]


def test_publish_with_an_unsupported_auth_method_fails_cleanly() -> None:
    store = FakeStore()
    store.designs.append(_publish_design_row())
    store.jobs["job-1"] = _job(status="generating", design_ir_id="design-1", client_id="cl-1")
    xmlrpc_conn = ResolvedWpConnection(client_id="cl-1", site_url="https://x.example", auth_method="xmlrpc", username="u", secret="p")
    result = execute_render_and_publish(
        store, "job-1", connection_resolver=lambda cid: xmlrpc_conn  # type: ignore[arg-type]
    )
    assert result["status"] == "failed"
    assert "unsupported_auth_method" in result["error"]


def test_publish_happy_path_pushes_to_wordpress_and_stops_before_qa() -> None:
    store = FakeStore()
    store.designs.append(_publish_design_row())
    store.jobs["job-1"] = _job(status="generating", design_ir_id="design-1", client_id="cl-1")
    fake_publisher = FakeWordPressPluginPublisher(site_url=_CONN.site_url)

    result = execute_render_and_publish(
        store, "job-1",  # type: ignore[arg-type]
        connection_resolver=lambda cid: _CONN,
        publisher_factory=lambda url, key: fake_publisher,
        auto_validate=False,
    )
    assert result["status"] == "publishing"
    assert len(fake_publisher.published) == 1
    assert fake_publisher.published[0]["title"] == "Welcome to Acme"
    assert fake_publisher.published[0]["post_type"] == "page"


def test_publish_gutenberg_mode_sends_block_markup_as_content() -> None:
    store = FakeStore()
    store.designs.append(_publish_design_row())
    store.jobs["job-1"] = _job(status="generating", design_ir_id="design-1", client_id="cl-1", editor_mode="gutenberg")
    fake_publisher = FakeWordPressPluginPublisher(site_url=_CONN.site_url)

    execute_render_and_publish(
        store, "job-1", connection_resolver=lambda cid: _CONN,  # type: ignore[arg-type]
        publisher_factory=lambda url, key: fake_publisher, auto_validate=False,
    )
    assert "<!-- wp:heading" in fake_publisher.published[0]["content"]
    assert "elementor_data" not in fake_publisher.published[0]


def test_publish_elementor_mode_sends_elementor_data_and_flat_html() -> None:
    store = FakeStore()
    store.designs.append(_publish_design_row())
    store.jobs["job-1"] = _job(status="generating", design_ir_id="design-1", client_id="cl-1", editor_mode="elementor")
    fake_publisher = FakeWordPressPluginPublisher(site_url=_CONN.site_url)

    execute_render_and_publish(
        store, "job-1", connection_resolver=lambda cid: _CONN,  # type: ignore[arg-type]
        publisher_factory=lambda url, key: fake_publisher, auto_validate=False, elementor_available=True,
    )
    payload = fake_publisher.published[0]
    assert payload["elementor_edit_mode"] == "builder"
    assert "elType" in payload["elementor_data"]


def test_publish_failure_fails_the_job_not_a_crash() -> None:
    store = FakeStore()
    store.designs.append(_publish_design_row())
    store.jobs["job-1"] = _job(status="generating", design_ir_id="design-1", client_id="cl-1")

    class _ExplodingPublisher:
        def ping(self) -> bool:
            return True

        def publish(self, payload: dict[str, Any]) -> Any:
            raise WordPressPluginError("boom")

    result = execute_render_and_publish(
        store, "job-1", connection_resolver=lambda cid: _CONN,  # type: ignore[arg-type]
        publisher_factory=lambda url, key: _ExplodingPublisher(),
    )
    assert result["status"] == "failed"
    assert "publish_failed" in result["error"]


def test_publish_then_auto_validates_and_completes() -> None:
    store = FakeStore()
    store.designs.append(_publish_design_row())
    store.jobs["job-1"] = _job(status="generating", design_ir_id="design-1", client_id="cl-1")
    fake_publisher = FakeWordPressPluginPublisher(site_url=_CONN.site_url)

    result = execute_render_and_publish(
        store, "job-1", connection_resolver=lambda cid: _CONN,  # type: ignore[arg-type]
        publisher_factory=lambda url, key: fake_publisher,
        analyzer_builder=_matching_capture_analyzer,
    )
    assert result["status"] in ("completed", "correcting")  # visual QA ran and reached a verdict
    assert len(store.validations) == 1
