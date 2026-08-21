"""Site Builder request/response models - SERVER-AUTHORITATIVE (no frontend/lib
type mirrors this new module).

``DesignIR`` is the platform-independent design record (migration 0069): it never
depends on Elementor/Gutenberg-specific shapes - it is the intermediate language a
renderer (Phase 3) reads to emit either. Section ``kind``/``layout`` reuse the SAME
controlled vocabulary as ``app.services.page_blueprints`` (``SECTION_KINDS`` /
``LAYOUT_VARIANTS``) so a DesignIR-driven page can resolve through the EXISTING
``page_blueprints.resolve_blueprint`` / ``page_model`` / ``elementor`` renderers
unchanged - a new IR source, not a competing one.

Python attributes stay snake_case; a multi-word wire key re-aliases to camelCase
(``serialization_alias`` on response-only models, matching ``app.modules.on_page``'s
convention; ``alias`` + ``populate_by_name=True`` on ``AnalyzeRequest`` so it accepts
the wire's camelCase body while still constructible from Python by field name).
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

SourceType = Literal["existing_site", "reference_site", "template", "manual"]
EditorMode = Literal["auto", "gutenberg", "elementor", "hybrid"]
FidelityMode = Literal["max_editability", "max_fidelity", "balanced"]
SiteJobStatus = Literal[
    "queued", "analyzing", "generating", "uploading_assets", "rendering",
    "validating", "correcting", "publishing", "completed", "failed",
]

# The terminal states, kept here (not just in Postgres) so a pure caller can reason
# about legal transitions without a DB round-trip.
TERMINAL_STATUSES: frozenset[str] = frozenset({"completed", "failed"})


class Palette(BaseModel):
    model_config = ConfigDict(extra="ignore")
    primary: str = "#111827"
    secondary: str = "#4b5563"
    background: str = "#ffffff"
    text: str = "#111827"
    accent: str = "#2563eb"


class Typography(BaseModel):
    model_config = ConfigDict(extra="ignore")
    heading_font: str = Field(default="system-ui, sans-serif", serialization_alias="headingFont")
    body_font: str = Field(default="system-ui, sans-serif", serialization_alias="bodyFont")
    base_size: str = Field(default="16px", serialization_alias="baseSize")


class ResponsiveBreakpoint(BaseModel):
    """What actually changes at ONE measured viewport - observed, not guessed."""

    model_config = ConfigDict(extra="ignore")
    viewport: Literal["desktop", "tablet", "mobile"]
    width: int = 0
    container_width_px: float | None = Field(default=None, serialization_alias="containerWidthPx")
    base_font_size: str = Field(default="", serialization_alias="baseFontSize")
    section_count: int = Field(default=0, serialization_alias="sectionCount")


class Components(BaseModel):
    model_config = ConfigDict(extra="ignore")
    button_style: str = Field(default="solid rounded", serialization_alias="buttonStyle")
    card_style: str = Field(default="soft shadow", serialization_alias="cardStyle")
    spacing_scale: str = Field(default="comfortable", serialization_alias="spacingScale")


class DesignAsset(BaseModel):
    model_config = ConfigDict(extra="ignore")
    url: str
    alt: str = ""
    width: float = 0.0
    height: float = 0.0
    kind: Literal["logo", "image"] = "image"


# The content-slot names a given section KIND is expected to carry - the AI content
# engine (a later phase) fills these into the placeholders a renderer emits, so
# generation targets a NAMED slot ("hero_heading") rather than a raw text blob.
_SLOTS_BY_KIND: dict[str, tuple[str, ...]] = {
    "hero": ("heading", "subhead", "cta_label", "cta_url"),
    "faq": ("heading", "items"),
    "testimonials": ("heading", "quotes"),
    "cta": ("heading", "text", "button_label", "button_url"),
    "pricing": ("heading", "tiers"),
    "process": ("heading", "steps"),
}
_DEFAULT_SLOTS: tuple[str, ...] = ("heading", "body")


def _default_supported_editors() -> list[EditorMode]:
    return ["elementor"]


def slots_for_kind(kind: str) -> list[str]:
    """The named content slots a section of this kind exposes to the content
    engine - a stable default (``heading``/``body``) for any kind not listed above,
    so every section is fillable even outside the special-cased kinds."""
    return list(_SLOTS_BY_KIND.get(kind, _DEFAULT_SLOTS))


class DesignIRSection(BaseModel):
    """One section of the ordered component tree: its ``kind``/``layout`` (the
    SAME vocabulary ``page_blueprints`` uses) + the content slots it exposes +
    what was actually measured there (a real bounding box + real colours), when the
    IR came from analyzing a page rather than a template."""

    model_config = ConfigDict(extra="ignore")
    kind: str
    heading: str = ""
    layout: str = "stacked"
    content: bool = True
    slots: list[str] = Field(default_factory=list)
    text_sample: str = Field(default="", serialization_alias="textSample")
    bg_color: str = Field(default="", serialization_alias="bgColor")
    text_color: str = Field(default="", serialization_alias="textColor")


class DesignIR(BaseModel):
    """The platform-independent design record persisted in ``design_irs``."""

    model_config = ConfigDict(extra="ignore")
    id: str
    client_id: str | None = Field(default=None, serialization_alias="clientId")
    source_type: SourceType = Field(serialization_alias="sourceType")
    source_url: str = Field(default="", serialization_alias="sourceUrl")
    industry: str = ""
    page_type: str = Field(default="", serialization_alias="pageType")
    design_style: str = Field(default="", serialization_alias="designStyle")
    version: int = 1
    palette: Palette = Field(default_factory=Palette)
    typography: Typography = Field(default_factory=Typography)
    container_width_px: float | None = Field(default=None, serialization_alias="containerWidthPx")
    section_order: list[str] = Field(default_factory=list, serialization_alias="sectionOrder")
    responsive: list[ResponsiveBreakpoint] = Field(default_factory=list)
    components: Components = Field(default_factory=Components)
    assets: list[DesignAsset] = Field(default_factory=list)
    sections: list[DesignIRSection] = Field(default_factory=list)
    supported_editors: list[EditorMode] = Field(
        default_factory=_default_supported_editors, serialization_alias="supportedEditors"
    )
    notes: str = ""
    wireframe_html: str = Field(default="", serialization_alias="wireframeHtml")
    created_at: str = Field(default="", serialization_alias="createdAt")
    updated_at: str = Field(default="", serialization_alias="updatedAt")


class AnalyzeRequest(BaseModel):
    """The wizard's "where should the design come from" step, resolved to one job.

    ``source_url`` is required for ``existing_site``/``reference_site`` (validated
    in the router, not here, so a malformed URL yields a clean 422 with the SSRF
    guard's own message rather than a generic pydantic error)."""

    model_config = ConfigDict(extra="ignore", populate_by_name=True)
    source_type: SourceType = Field(alias="sourceType")
    source_url: str = Field(default="", alias="sourceUrl")
    template: str = ""
    industry: str = ""
    page_type: str = Field(default="", alias="pageType")
    editor_mode: EditorMode = Field(default="auto", alias="editorMode")
    fidelity_mode: FidelityMode = Field(default="balanced", alias="fidelityMode")
    client_id: str | None = Field(default=None, alias="clientId")


class SiteGenerationJob(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str
    code: str
    client_id: str | None = Field(default=None, serialization_alias="clientId")
    status: SiteJobStatus
    source_type: SourceType = Field(serialization_alias="sourceType")
    source_url: str = Field(default="", serialization_alias="sourceUrl")
    page_type: str = Field(default="", serialization_alias="pageType")
    industry: str = ""
    editor_mode: EditorMode = Field(serialization_alias="editorMode")
    fidelity_mode: FidelityMode = Field(serialization_alias="fidelityMode")
    design_ir_id: str | None = Field(default=None, serialization_alias="designIrId")
    stage_detail: str = Field(default="", serialization_alias="stageDetail")
    error: str | None = None
    created_at: str = Field(default="", serialization_alias="createdAt")
    updated_at: str = Field(default="", serialization_alias="updatedAt")


def job_row_to_response(row: dict[str, Any]) -> SiteGenerationJob:
    return SiteGenerationJob(
        id=str(row["id"]), code=str(row["code"]), client_id=str(row["client_id"]) if row.get("client_id") else None,
        status=row["status"], source_type=row["source_type"], source_url=str(row.get("source_url") or ""),
        page_type=str(row.get("page_type") or ""), industry=str(row.get("industry") or ""),
        editor_mode=row["editor_mode"], fidelity_mode=row["fidelity_mode"],
        design_ir_id=str(row["design_ir_id"]) if row.get("design_ir_id") else None,
        stage_detail=str(row.get("stage_detail") or ""), error=row.get("error"),
        created_at=str(row.get("created_at") or ""), updated_at=str(row.get("updated_at") or ""),
    )


class SiteTemplate(BaseModel):
    """One catalog entry (migration 0070): the taxonomy (industry/pageType/
    designStyle/category) + marketplace-shaped metadata a wizard recommends from.
    ``blueprint_key`` XOR ``design_ir_id`` names where its actual structure lives."""

    model_config = ConfigDict(extra="ignore")
    id: str
    key: str
    name: str
    category: str = ""
    industry: str = ""
    page_type: str = Field(default="", serialization_alias="pageType")
    design_style: str = Field(default="", serialization_alias="designStyle")
    blueprint_key: str | None = Field(default=None, serialization_alias="blueprintKey")
    design_ir_id: str | None = Field(default=None, serialization_alias="designIrId")
    supported_editors: list[str] = Field(
        default_factory=list, serialization_alias="supportedEditors"
    )
    preview_image_url: str = Field(default="", serialization_alias="previewImageUrl")
    description: str = ""
    author: str = "AIOS"
    version: int = 1
    rating: float | None = None
    is_active: bool = Field(default=True, serialization_alias="isActive")


def template_row_to_response(row: dict[str, Any]) -> SiteTemplate:
    return SiteTemplate(
        id=str(row["id"]), key=str(row["key"]), name=str(row["name"]),
        category=str(row.get("category") or ""), industry=str(row.get("industry") or ""),
        page_type=str(row.get("page_type") or ""), design_style=str(row.get("design_style") or ""),
        blueprint_key=row.get("blueprint_key"), design_ir_id=str(row["design_ir_id"]) if row.get("design_ir_id") else None,
        supported_editors=list(row.get("supported_editors") or []),
        preview_image_url=str(row.get("preview_image_url") or ""), description=str(row.get("description") or ""),
        author=str(row.get("author") or "AIOS"), version=int(row.get("version") or 1),
        rating=float(row["rating"]) if row.get("rating") is not None else None,
        is_active=bool(row.get("is_active", True)),
    )


def design_ir_row_to_response(row: dict[str, Any]) -> DesignIR:
    return DesignIR(
        id=str(row["id"]), client_id=str(row["client_id"]) if row.get("client_id") else None,
        source_type=row["source_type"], source_url=str(row.get("source_url") or ""),
        industry=str(row.get("industry") or ""), page_type=str(row.get("page_type") or ""),
        design_style=str(row.get("design_style") or ""), version=int(row.get("version") or 1),
        palette=Palette(**(row.get("palette") or {})), typography=Typography(**(row.get("typography") or {})),
        container_width_px=(row.get("layout") or {}).get("container_width_px"),
        section_order=(row.get("layout") or {}).get("section_order") or [],
        responsive=[ResponsiveBreakpoint(**r) for r in (row.get("responsive") or []) if isinstance(r, dict)],
        components=Components(**(row.get("components") or {})),
        assets=[DesignAsset(**a) for a in (row.get("assets") or []) if isinstance(a, dict)],
        sections=[DesignIRSection(**s) for s in (row.get("sections") or []) if isinstance(s, dict)],
        supported_editors=row.get("supported_editors") or ["elementor"],
        notes=str(row.get("notes") or ""), wireframe_html=str(row.get("wireframe_html") or ""),
        created_at=str(row.get("created_at") or ""), updated_at=str(row.get("updated_at") or ""),
    )


VisualQaStatus = Literal["pass", "warn", "fail"]


class VisualDiagnostic(BaseModel):
    model_config = ConfigDict(extra="ignore")
    kind: str
    section: str
    detail: str
    magnitude: float = 0.0


class VisualValidation(BaseModel):
    """One QA pass over a rendered build (migration 0071) - a structured,
    multi-dimension verdict, never a single similarity percentage."""

    model_config = ConfigDict(extra="ignore")
    id: str
    job_id: str = Field(serialization_alias="jobId")
    rendered_url: str = Field(default="", serialization_alias="renderedUrl")
    status: VisualQaStatus
    diagnostics: list[VisualDiagnostic] = Field(default_factory=list)
    created_at: str = Field(default="", serialization_alias="createdAt")


class VisualQaRequest(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)
    rendered_url: str = Field(alias="renderedUrl", min_length=1)


def visual_validation_row_to_response(row: dict[str, Any]) -> VisualValidation:
    return VisualValidation(
        id=str(row["id"]), job_id=str(row["job_id"]), rendered_url=str(row.get("rendered_url") or ""),
        status=row["status"],
        diagnostics=[VisualDiagnostic(**d) for d in (row.get("diagnostics") or []) if isinstance(d, dict)],
        created_at=str(row.get("created_at") or ""),
    )
