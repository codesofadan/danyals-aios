"""Design Replication worker: a URL in, a draft Elementor page on the client's site out.

The ENGINE is ``app.services.replica_publish.replicate`` (the composed pipeline,
already tested): capture at three viewports -> design system -> layout -> Elementor
tree -> validate -> push through the AIOS Publisher plugin. It drives a local
Playwright capture for ~30-60s, which is why it runs HERE - on the ``browser``
queue, under the job contract (docs/JOB-CONTRACT.md) - and never inline in a route.

THE COPYRIGHT GATE LIVES AT THE ROUTE. ``POST /replica`` refuses to enqueue unless
the caller asserted ``owner_confirmed_source`` (the rebuild carries the source's own
copy and imagery), so by the time this task runs the assertion has been made by a
person holding ``publish_content``. The task passes it through as True and RECORDS
it in the result payload, so the ledger row carries the assertion alongside what it
authorised.

The WordPress target is resolved from the client's STORED connection (0058:
``resolve_connection`` -> ``build_client_wp_target``), the same seam the content
publish path uses. Credentials never travel in the task arguments or the request
body. The replica payload (Elementor JSON + design CSS) needs the plugin door, so a
client connected via xmlrpc/app_password is a typed ``blocked``, not a stack trace.

Terminal mapping (the contract's vocabulary, not the engine's):

    ReplicaResult.ok=True   -> completed
    ReplicaResult.ok=False  -> degraded  (reason = the stage note that stopped it)
    no usable WP connection -> blocked   (a typed refusal with a stable reason_code)
"""

from __future__ import annotations

from typing import Any

#: The pinned Celery task name (moving this module must not break routing) and the
#: LOGICAL job name an operator groups by - also what the status route filters on.
TASK_NAME = "aios.replica.run"
JOB_NAME = "replica.publish"


# --------------------------------------------------------------------------- #
# Pure core (no Celery, no DB) - unit-tested directly.
# --------------------------------------------------------------------------- #
def replica_idempotency_key(
    client_id: str, url: str, slug: str | None, generation: int = 1
) -> str:
    """Deterministic key of the WORK: (client, source URL, destination slug, generation).

    Two enqueues of the same rebuild collapse to one run; replicating the same URL
    to a different slug is genuinely different work and gets its own run.

    ``generation`` is what makes a RE-RUN possible. ``job_runs`` carries a unique
    index on ``idempotency_key`` covering the whole table, terminal rows included, so
    a key is spent the moment its first run finishes: the claim answers every later
    enqueue with ``created=False`` and the runner correctly declines to repeat work it
    believes is done. Without a generation that made the first replication of a URL
    the only one that could ever happen - a run that degraded, or was blocked because
    WordPress was not connected yet, could not be retried even after the operator
    fixed the cause.

    Generation 1 is byte-identical to the key this function has always produced, so
    every run already in the ledger keeps matching.
    """
    base = f"{JOB_NAME}:{client_id}:{url}:{slug or ''}"
    return base if generation <= 1 else f"{base}:g{generation}"


def degrade_code(notes: list[str]) -> str:
    """A stable ``reason_code`` from the engine's LAST note - the stage that stopped.

    ``replicate`` is total: it never raises for pipeline reasons, it appends a note
    naming the stage that gave up and returns. The prose stays in ``reason``; this
    maps the stage prefix onto the countable identifier the contract requires.
    """
    last = notes[-1] if notes else ""
    if last.startswith("refused:"):
        return "owner_confirmation_missing"
    if last.startswith("capture"):
        return "capture_degraded"
    if last.startswith("layout"):
        return "layout_degraded"
    if last.startswith("refused by the oracle"):
        return "oracle_refused"
    if last.startswith("publish failed"):
        return "wp_publish_failed"
    return "replica_degraded"


def result_payload(res: Any, *, url: str) -> dict[str, Any]:
    """The job-run result payload the status route reads back (contract shape)."""
    return {
        "url": url,
        "post_id": res.post_id,
        "preview_url": res.preview_url or None,
        "sections": res.sections,
        "widgets": res.widgets,
        "notes": list(res.notes),
        # The ROUTE enforced the assertion (a 400 without it); the ledger records
        # that it was made, so the row explains what authorised carrying the copy.
        "owner_confirmed_source": True,
        # The measured design, so the CONTENT flow can generate pages on it without a
        # second Playwright capture of the same URL. `job_runs.result` is schemaless
        # jsonb, so this needs no migration.
        "design_profile": getattr(res, "design_profile", None),
    }


# --------------------------------------------------------------------------- #
# Celery entry point (thin; the app imports come last, per the worker template).
# --------------------------------------------------------------------------- #
from app.config import get_settings  # noqa: E402
from app.core.security import PrivateAddressError, validate_public_host  # noqa: E402
from app.jobs import JobBlocked, JobContext, JobOutcome, JobQueue, JobTarget  # noqa: E402
from app.jobs.celery_task import aios_job  # noqa: E402
from app.services.replica_publish import ReplicaPublisher, replicate  # noqa: E402
from app.services.vault import VaultSecretError  # noqa: E402
from app.services.wp_connections import resolve_connection  # noqa: E402


def _target(
    client_id: str,
    url: str,
    title: str | None = None,
    slug: str | None = None,
    client_name: str = "",
    generation: int = 1,
) -> JobTarget:
    return JobTarget(
        idempotency_key=replica_idempotency_key(client_id, url, slug, generation),
        client_id=client_id,
        client_name=client_name,
        scope_id=client_id,
    )


def _plugin_for(client_id: str) -> ReplicaPublisher:
    """The client's stored WP connection -> a ready plugin publisher, or a typed refusal.

    Reuses the content-publish resolution seam (0058): the credential is opened
    server-side by ``resolve_connection`` and never appears in task arguments.
    Imported lazily so importing THIS module (e.g. from the route's enqueuer) does
    not drag the whole content worker in with it.
    """
    from workers.tasks.content import build_client_wp_target

    try:
        conn = resolve_connection(client_id)
    except VaultSecretError as exc:
        raise JobBlocked(
            "wp_credentials_unreadable",
            f"the client's stored WordPress credential could not be opened: {exc}",
        ) from exc
    if conn is None:
        raise JobBlocked(
            "wp_connection_missing",
            "the client has no WordPress connection; connect the site "
            "(Settings -> WordPress Connections) before replicating",
        )
    target = build_client_wp_target(conn, get_settings())
    if target is None or target.plugin is None:
        raise JobBlocked(
            "wp_plugin_required",
            "replica publishing writes Elementor data and design CSS, which needs the "
            f"AIOS Publisher plugin; this client's connection method is '{conn.auth_method}'",
        )
    return target.plugin


@aios_job(
    name=TASK_NAME,
    job_name=JOB_NAME,
    queue=JobQueue.BROWSER,
    # 1, not 3: the engine is total (pipeline failures come back as ok=False, never
    # as an exception), so a raise here is unclassified - and a redelivery could
    # re-push a page that already reached WordPress. Not safely repeatable.
    max_attempts=1,
    # One Chromium capture per client at a time: the browser queue is the scarce,
    # heavy resource, and a client bulk-replicating a site must only starve itself.
    client_concurrency=1,
    scope_type="client",
    target=_target,
)
def run_replica(
    ctx: JobContext,
    client_id: str,
    url: str,
    title: str | None = None,
    slug: str | None = None,
    client_name: str = "",
    generation: int = 1,
) -> JobOutcome:
    """Replicate ``url`` as a draft Elementor page on the client's connected site.

    ``client_name`` rides along purely for the ledger row (the operator board shows
    it); it is not part of the work's identity, so it is not in the idempotency key.

    ``generation`` IS part of the work's identity - it is what distinguishes "the
    same rebuild, enqueued twice" (collapse) from "rebuild this page again, now that
    I have fixed what stopped it last time" (run it). The route picks the number; the
    task only has to pass it to the same key function the claim uses.
    """
    # The route already refused private addresses; re-check at run time (defence in
    # depth, same as the audit worker re-running the enqueue-time gate) so a stale
    # or hand-enqueued message cannot point Chromium at the internal network.
    try:
        validate_public_host(url)
    except PrivateAddressError as exc:
        raise JobBlocked("ssrf_refused", f"URL is not a public address: {exc}") from exc

    publisher = _plugin_for(client_id)

    # Cancellation gate BEFORE the ~30-60s browser capture; the capture itself is
    # one long call, so this is the last stop where a cancel takes effect cheaply.
    ctx.checkpoint()
    # SAY WHAT IS HAPPENING. The run takes 12-60s and used to report only "queued"
    # then a terminal state, so the operator watched an unlabelled spinner for the
    # whole of it and had no way to tell work from a hang. The stages are few and
    # named, so each one is forced past the 30s progress throttle: eight writes per
    # run, against a run that spends most of a minute inside a browser.
    res = replicate(
        url,
        publisher=publisher,
        title=title or None,
        slug=slug or None,
        # The route enforced the assertion; see the module docstring.
        owner_confirmed_source=True,
        on_stage=lambda line: ctx.progress(line, force=True),
    )
    ctx.checkpoint()

    payload = result_payload(res, url=url)
    if res.ok:
        return JobOutcome.completed(
            f"replicated {url}: {res.sections} section(s), {res.widgets} widget(s)",
            result=payload,
        )
    reason = res.notes[-1] if res.notes else "replication did not complete"
    return JobOutcome.degraded(degrade_code(res.notes), reason, result=payload)
