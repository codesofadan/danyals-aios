"""The Site Builder worker: drives ONE ``site_generation_jobs`` row from ``queued``
through ``analyzing`` -> ``generating`` (design resolved) -> ``rendering`` ->
``publishing`` -> ``validating`` -> ``completed``/``correcting``, or ``failed`` at
any step. ``run_visual_qa`` is also independently callable at any later point (spec's
Render -> Visual QA -> Correct -> Render-again loop).

Follows the never-stuck / never-re-raise worker template (``workers.tasks.content`` /
``app.modules.on_page.tasks``): with ``task_acks_late`` a raised exception would
redeliver the job and re-run a real browser capture / a real WordPress push, so a
task ACKs and returns a result dict; a redelivery on an already-advanced job is an
idempotent no-op (each core checks the job is still in the status it expects before
doing any work).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from app.logging_setup import get_logger
from app.modules.site_builder.repo import ServiceSiteBuilderStore, service_site_builder_store
from app.modules.site_builder.service import (
    design_ir_from_capture,
    design_ir_from_template,
    design_ir_to_page_model,
    page_title_for_design,
    slugify,
)
from app.services.editor_mode import resolve_editor_mode
from app.services.elementor import elementor_json_from_model
from app.services.gutenberg import model_to_gutenberg
from app.services.page_model import model_to_html, page_model_from_dict
from app.services.visual_diff import diff_design_against_capture
from app.services.wp_connections import ResolvedWpConnection, resolve_connection
from integrations.site_analyzer import SiteAnalyzer, analyze_website, build_site_analyzer
from integrations.wordpress_publisher import (
    PluginPublisher,
    WordPressPluginError,
    WordPressPluginPublisher,
)

logger = get_logger("workers.site_builder")


def _default_publisher(site_url: str, api_key: str) -> PluginPublisher:
    return WordPressPluginPublisher(site_url=site_url, api_key=api_key)


def execute_analyze(
    store: ServiceSiteBuilderStore,
    job_id: str,
    *,
    analyzer_builder: Callable[[], SiteAnalyzer | None] = build_site_analyzer,
) -> dict[str, Any]:
    """The pure-ish orchestration core (I/O injected via ``store`` + ``analyzer_builder``
    - a unit test passes a fake builder so this runs with no real browser). Never
    raises - every failure path returns a result dict after marking the job ``failed``."""
    job = store.get_job(job_id)
    if job is None:
        return {"id": job_id, "status": "failed", "reason": "job not found"}
    if job["status"] != "queued":
        return dict(job)  # already advanced: idempotent no-op on redelivery

    store.update_job(job_id, {"status": "analyzing", "stage_detail": "Analyzing website..."})
    source_type = str(job["source_type"])
    source_url = str(job.get("source_url") or "")
    industry = str(job.get("industry") or "")
    page_type = str(job.get("page_type") or "")

    body: dict[str, Any]
    if source_type in ("existing_site", "reference_site"):
        result = analyze_website(source_url, analyzer=analyzer_builder())
        if result.status != "ok" or result.capture is None:
            updated = store.update_job(
                job_id,
                {
                    "status": "failed",
                    "error": f"analysis_failed:{result.reason}",
                    "stage_detail": "Website could not be analyzed",
                },
            )
            return dict(updated) if updated else {"id": job_id, "status": "failed"}
        body = design_ir_from_capture(
            result.capture, source_type=source_type, source_url=source_url,
            industry=industry, page_type=page_type,
        )
    elif source_type == "template":
        requested = page_type or "homepage"
        # Resolve through the catalog first (a site_templates.key, e.g.
        # "homepage-generic") so new templates are new ROWS, not new Python; a
        # value with no catalog entry falls back to treating it as a raw
        # page_blueprints key directly (back-compat with the 7 built-in names).
        catalog_row = store.get_template_by_key(requested)
        template_name = str(catalog_row["blueprint_key"]) if catalog_row and catalog_row.get("blueprint_key") else requested
        template_body = design_ir_from_template(template_name, industry=industry, page_type=page_type)
        if template_body is None:
            updated = store.update_job(
                job_id,
                {"status": "failed", "error": f"unknown_template:{requested}",
                 "stage_detail": "Template not found"},
            )
            return dict(updated) if updated else {"id": job_id, "status": "failed"}
        if catalog_row is not None:
            template_body["design_style"] = str(catalog_row.get("design_style") or template_body.get("design_style", ""))
        body = template_body
    else:  # manual: seed a blank canvas the wizard's editor starts empty from
        template_body = design_ir_from_template("homepage", industry=industry, page_type=page_type)
        body = dict(template_body) if template_body is not None else {}
        body["source_type"] = "manual"
        body["source_url"] = ""

    design_row = store.insert_design_ir(
        body, client_id=job.get("client_id"), client_name=str(job.get("client_name") or ""),
        created_by=job.get("created_by"),
    )
    updated = store.update_job(
        job_id,
        {"status": "generating", "design_ir_id": design_row["id"],
         "stage_detail": "Design resolved - ready to generate"},
    )
    return dict(updated) if updated else {"id": job_id, "status": "generating"}


def execute_render_and_publish(
    store: ServiceSiteBuilderStore,
    job_id: str,
    *,
    connection_resolver: Callable[[str], ResolvedWpConnection | None] = resolve_connection,
    publisher_factory: Callable[[str, str], PluginPublisher] = _default_publisher,
    elementor_available: bool = True,
    auto_validate: bool = True,
    analyzer_builder: Callable[[], SiteAnalyzer | None] = build_site_analyzer,
) -> dict[str, Any]:
    """Render ONE job's resolved DesignIR (via the SAME PageModel the HTML/Elementor/
    Gutenberg renderers already share) and push it to the client's WordPress as a
    DRAFT through the AIOS Publisher plugin bridge - identical infrastructure to the
    content module's publish path, reused rather than re-implemented. On a
    successful push, immediately runs visual QA against the just-published URL
    (unless ``auto_validate=False``) so a job reaches a genuine terminal verdict in
    one pass. Never raises; every failure path marks the job ``failed`` with a
    machine-branchable reason.
    """
    job = store.get_job(job_id)
    if job is None:
        return {"id": job_id, "status": "failed", "reason": "job not found"}
    if job["status"] != "generating":
        return dict(job)  # already advanced: idempotent no-op on redelivery

    design_ir_id = job.get("design_ir_id")
    if not design_ir_id:
        updated = store.update_job(
            job_id, {"status": "failed", "error": "no_design_to_render",
                      "stage_detail": "Nothing to render - no design resolved yet"},
        )
        return dict(updated) if updated else {"id": job_id, "status": "failed"}
    design_row = store.get_design_ir(str(design_ir_id))
    if design_row is None:
        updated = store.update_job(
            job_id, {"status": "failed", "error": "design_not_found",
                      "stage_detail": "Nothing to render - the resolved design is missing"},
        )
        return dict(updated) if updated else {"id": job_id, "status": "failed"}

    client_id = job.get("client_id")
    if not client_id:
        updated = store.update_job(
            job_id, {"status": "failed", "error": "no_client_assigned",
                      "stage_detail": "Cannot publish - this build has no client assigned"},
        )
        return dict(updated) if updated else {"id": job_id, "status": "failed"}
    connection = connection_resolver(str(client_id))
    if connection is None:
        updated = store.update_job(
            job_id, {"status": "failed", "error": "no_wordpress_connection",
                      "stage_detail": "Cannot publish - no WordPress connection configured for this client"},
        )
        return dict(updated) if updated else {"id": job_id, "status": "failed"}
    if connection.auth_method != "plugin":
        updated = store.update_job(
            job_id, {"status": "failed", "error": f"unsupported_auth_method:{connection.auth_method}",
                      "stage_detail": "Cannot publish - this client's connection needs the AIOS Publisher plugin"},
        )
        return dict(updated) if updated else {"id": job_id, "status": "failed"}

    store.update_job(job_id, {"status": "rendering", "stage_detail": "Building WordPress page..."})
    title = page_title_for_design(design_row)
    model_dict = design_ir_to_page_model(design_row, title=title)
    renderer = resolve_editor_mode(str(job.get("editor_mode") or "auto"), elementor_available=elementor_available)

    payload: dict[str, Any] = {"title": title, "status": "draft", "post_type": "page", "slug": slugify(title)}
    if renderer == "elementor":
        payload["content"] = model_to_html(page_model_from_dict(model_dict), fragment=True)
        payload["elementor_data"] = elementor_json_from_model(model_dict)
        payload["elementor_edit_mode"] = "builder"
    else:
        payload["content"] = model_to_gutenberg(model_dict)

    store.update_job(job_id, {"status": "publishing", "stage_detail": "Publishing to WordPress..."})
    publisher = publisher_factory(connection.site_url, connection.secret)
    try:
        result = publisher.publish(payload)
    except WordPressPluginError as exc:
        updated = store.update_job(
            job_id, {"status": "failed", "error": f"publish_failed:{exc}",
                      "stage_detail": "Publishing to WordPress failed"},
        )
        return dict(updated) if updated else {"id": job_id, "status": "failed"}

    updated = store.update_job(
        job_id, {"stage_detail": f"Published as a draft: {result.edit_url or result.url}"}
    )
    if not auto_validate or not result.url:
        return dict(updated) if updated else {"id": job_id, "status": "publishing"}
    return execute_visual_qa(store, job_id, rendered_url=result.url, analyzer_builder=analyzer_builder)


def execute_visual_qa(
    store: ServiceSiteBuilderStore,
    job_id: str,
    *,
    rendered_url: str,
    analyzer_builder: Callable[[], SiteAnalyzer | None] = build_site_analyzer,
) -> dict[str, Any]:
    """Diff ONE job's resolved DesignIR against a fresh capture of ``rendered_url``
    (the actual published page), persist the structured verdict, and advance the
    job: ``completed`` on a pass, ``correcting`` on a warn/fail (spec's Render ->
    Visual QA -> Correct -> Render-again loop), ``failed`` when nothing can be
    compared (no design yet, or the rendered page could not be captured at all).
    Never raises."""
    job = store.get_job(job_id)
    if job is None:
        return {"id": job_id, "status": "failed", "reason": "job not found"}
    design_ir_id = job.get("design_ir_id")
    if not design_ir_id:
        updated = store.update_job(
            job_id, {"status": "failed", "error": "no_design_to_validate_against",
                      "stage_detail": "Nothing to validate - no design resolved yet"},
        )
        return dict(updated) if updated else {"id": job_id, "status": "failed"}
    design_row = store.get_design_ir(str(design_ir_id))
    if design_row is None:
        updated = store.update_job(
            job_id, {"status": "failed", "error": "design_not_found",
                      "stage_detail": "Nothing to validate - the resolved design is missing"},
        )
        return dict(updated) if updated else {"id": job_id, "status": "failed"}

    store.update_job(job_id, {"status": "validating", "stage_detail": "Checking visual accuracy..."})
    result = analyze_website(rendered_url, analyzer=analyzer_builder())
    if result.status != "ok" or result.capture is None:
        store.insert_visual_validation(
            job_id=job_id, rendered_url=rendered_url, status="fail",
            diagnostics=[
                {"kind": "layout", "section": "page",
                 "detail": f"could not capture the rendered page: {result.reason}", "magnitude": 1.0}
            ],
        )
        updated = store.update_job(
            job_id, {"status": "failed", "error": f"validation_capture_failed:{result.reason}",
                      "stage_detail": "Visual validation failed"},
        )
        return dict(updated) if updated else {"id": job_id, "status": "failed"}

    diff = diff_design_against_capture(design_row, result.capture)
    store.insert_visual_validation(
        job_id=job_id, rendered_url=rendered_url, status=diff.status,
        diagnostics=[d.as_dict() for d in diff.diagnostics],
    )
    if diff.status == "pass":
        updated = store.update_job(
            job_id, {"status": "completed", "stage_detail": "Visual accuracy confirmed"}
        )
    else:
        updated = store.update_job(
            job_id, {"status": "correcting", "stage_detail": f"Visual QA found {len(diff.diagnostics)} issue(s)"}
        )
    return dict(updated) if updated else {"id": job_id, "status": diff.status}


# --------------------------------------------------------------------------- #
# Celery entry points (thin; import the app after the pure cores, per the template)
# --------------------------------------------------------------------------- #
from workers.celery_app import celery_app  # noqa: E402 - after the pure core, per the worker template


@celery_app.task(name="analyze_site")  # type: ignore[untyped-decorator]  # celery's decorator is untyped
def analyze_site(job_id: str) -> dict[str, Any]:
    """Entry point: analyze/resolve the design for ONE ``site_generation_jobs`` row."""
    try:
        return execute_analyze(service_site_builder_store(), job_id)
    except Exception:
        logger.exception("analyze_site_task_failed", job_id=job_id)
        try:
            service_site_builder_store().update_job(
                job_id, {"status": "failed", "error": "task failed", "stage_detail": "Analysis failed"}
            )
        except Exception:
            logger.exception("analyze_site_task_failed_to_mark_failed", job_id=job_id)
        return {"id": job_id, "status": "failed", "reason": "task failed"}


@celery_app.task(name="render_and_publish_site")  # type: ignore[untyped-decorator]  # celery's decorator is untyped
def render_and_publish_site(job_id: str) -> dict[str, Any]:
    """Entry point: render ONE job's resolved design and push it to WordPress,
    then visually validate the published page."""
    try:
        return execute_render_and_publish(service_site_builder_store(), job_id)
    except Exception:
        logger.exception("render_and_publish_site_task_failed", job_id=job_id)
        try:
            service_site_builder_store().update_job(
                job_id, {"status": "failed", "error": "task failed", "stage_detail": "Publishing failed"}
            )
        except Exception:
            logger.exception("render_and_publish_site_task_failed_to_mark_failed", job_id=job_id)
        return {"id": job_id, "status": "failed", "reason": "task failed"}


@celery_app.task(name="run_visual_qa")  # type: ignore[untyped-decorator]  # celery's decorator is untyped
def run_visual_qa(job_id: str, rendered_url: str) -> dict[str, Any]:
    """Entry point: visually validate ONE job's rendered build."""
    try:
        return execute_visual_qa(service_site_builder_store(), job_id, rendered_url=rendered_url)
    except Exception:
        logger.exception("run_visual_qa_task_failed", job_id=job_id)
        try:
            service_site_builder_store().update_job(
                job_id, {"status": "failed", "error": "task failed", "stage_detail": "Visual validation failed"}
            )
        except Exception:
            logger.exception("run_visual_qa_task_failed_to_mark_failed", job_id=job_id)
        return {"id": job_id, "status": "failed", "reason": "task failed"}
