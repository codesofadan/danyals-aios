"""Binding the staged pipeline to real dependencies - the missing entry point.

Every stage in this package is written to be injected: `run_page` takes a dict of
already-bound callables so the sequence can be exercised against fakes without a
network or a database. That design was complete and the dict was never built,
which is why the whole package had no production caller - sixteen modules, a
`PAGE_STAGES` sequence, an LLM judge, and nothing that could invoke any of it.

This module is that dict, and NOTHING else. It constructs no writer, no provider
and no store: the caller (the worker) owns construction, because that is where
the settings, the cost gate and the tenant identity live. Keeping construction
out of here is what lets a test bind the same stages to fakes and get the
same sequence the worker runs.

WHY EVERY STAGE IS OPTIONAL. `run_page` skips a stage that is absent from the
dict rather than treating it as an error, and this honours that: a caller with no
researcher gets a pipeline without the research stage instead of a crash. The one
thing this module will not do is silently substitute a fake for a missing real
dependency - a page drafted by a stub writer that reports success is precisely
the "faking success" failure the job contract exists to prevent.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from typing import Any, Protocol

from app.config import Settings
from app.services.content_pipeline.claims import run_claims
from app.services.content_pipeline.context import PipelineContext, StageResult
from app.services.content_pipeline.convert import run_convert
from app.services.content_pipeline.draft import run_draft
from app.services.content_pipeline.gate import run_gate
from app.services.content_pipeline.grounding import run_grounding
from app.services.content_pipeline.guided_edit import run_guided_edit
from app.services.content_pipeline.images import run_images
from app.services.content_pipeline.outline import run_outline
from app.services.content_pipeline.research import run_research
from app.services.content_pipeline.schema_links import run_schema_links
from app.services.content_pipeline.sme import run_sme
from app.services.content_pipeline.title_meta import run_title_meta
from app.services.content_pipeline.voice import run_voice
from app.services.content_pipeline.writer import DoctrineWriter
from app.services.content_schema import Business
from app.services.cost_gate import CostGate
from integrations.images import ImageGenerator

StageFn = Callable[[PipelineContext], StageResult]


class PageStores(Protocol):
    """The one store the pipeline reads and writes.

    `ContentPlanningStore` satisfies this in production. It is a Protocol here so
    the assembly does not import a module that reaches Postgres - the tests bind
    an in-memory double with the same five methods.
    """

    def get_or_create_dossier(self, *, engagement_id: str, cluster_key: str = "") -> Any: ...
    def upsert_slot(self, **kwargs: Any) -> None: ...
    def refresh_dossier_status(self, dossier_id: str) -> str: ...
    def record_shingles(self, **kwargs: Any) -> int: ...
    def find_overlaps(self, **kwargs: Any) -> list[Any]: ...
    def metrics_for(self, engagement_id: str | None, keyword: str) -> dict[str, Any] | None: ...


def build_page_stages(
    *,
    edit_instruction: str = "",
    writer: DoctrineWriter | None = None,
    researcher: Any | None = None,
    store: PageStores | None = None,
    business: Business | None = None,
    page_url: str = "",
    client_da: float | None = None,
    serp_date: str | None = None,
    cluster_key: str = "",
    model: str | None = None,
    images: ImageGenerator | None = None,
    cost_gate: CostGate | None = None,
    settings: Settings | None = None,
    internal_urls: Mapping[str, str] | None = None,
    allowed_contacts: frozenset[str] = frozenset(),
    vendor_terms: Iterable[str] = (),
) -> dict[str, StageFn]:
    """Bind the per-page stages to the dependencies they actually need.

    Returns the mapping `run_page` consumes. A stage whose hard dependency is
    absent is OMITTED from the mapping, which `run_page` reads as "skip", rather
    than being bound to something that would pretend to work:

    * `sme` needs the dossier store - without it there is nowhere for Experience
      to live, and the gate that refuses to draft ungoverned pages cannot run.
    * `research`, `outline`, `draft`, `convert`, `voice`, `title_meta` each need a
      real provider seam.
    * `schema_links` needs neither - it is deterministic and free, so it is always
      bound.
    * `gate` scores with the LLM judge when a writer exists and deterministically
      when one does not, so it is always bound too.
    * `images` needs THREE things - a generator, the cost gate, and the price table
      - because it is the one stage that spends outside the metered writer seam.
      An absent generator omits it (a page with no photos is a visible absence);
      an absent GATE omits it too, because generating an image with nothing to
      meter it is unbilled, uncapped spend, and the spend halt would not stop it.
    """
    stages: dict[str, StageFn] = {}

    if store is not None:
        stages["sme"] = lambda ctx: run_sme(
            ctx, store=store, writer=writer, cluster_key=cluster_key
        )

    if researcher is not None:
        stages["research"] = lambda ctx: run_research(
            ctx, researcher=researcher, plan=store,
            client_da=client_da, serp_date=serp_date,
        )

    if writer is not None:
        # The uniqueness gate reads and writes shingles; without the store it still
        # runs, just without sibling comparison, which `run_outline` handles.
        stages["outline"] = lambda ctx: run_outline(
            ctx, writer=writer, store=store, model=model
        )
        stages["draft"] = lambda ctx: run_draft(ctx, writer=writer, model=model)
        stages["convert"] = lambda ctx: run_convert(ctx, writer=writer, model=model)
        stages["voice"] = lambda ctx: run_voice(ctx, writer=writer, model=model)
        stages["grounding"] = lambda ctx: run_grounding(ctx, writer=writer, model=model)
        stages["guided_edit"] = lambda ctx: run_guided_edit(
            ctx, writer=writer, instruction=edit_instruction, model=model
        )
        stages["title_meta"] = lambda ctx: run_title_meta(ctx, writer=writer, model=model)

    if images is not None and cost_gate is not None and settings is not None:
        stages["images"] = lambda ctx: run_images(
            ctx, generator=images, gate=cost_gate, settings=settings
        )

    # DELIBERATELY OUTSIDE the writer block. Every other stage above is bound only
    # when its provider exists, so a deployment missing a key simply omits it - the
    # honest-degrade rule. This one is deterministic and free, and it is the check
    # that stops an invented certification reaching a client's live page, so there
    # is no dependency whose absence should be allowed to skip it.
    stages["claims"] = lambda ctx: run_claims(
        ctx, allowed_contacts=allowed_contacts, vendor_terms=vendor_terms,
    )

    stages["schema_links"] = lambda ctx: run_schema_links(
        ctx, business=business, url=page_url, internal_urls=internal_urls,
    )
    stages["gate"] = lambda ctx: run_gate(ctx, writer=writer, model=model)

    return stages
