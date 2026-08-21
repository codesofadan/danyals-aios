// Site Builder: types + static reference data for the website-reconstruction
// wizard. Mirrors the backend's wire shapes 1:1 (camelCase, matching
// app/modules/site_builder/schemas.py's serialization_alias fields) — no
// frontend-only reshaping, so `api.get<SiteGenerationJob>(...)` round-trips as-is.

export type SourceType = "existing_site" | "reference_site" | "template" | "manual";
export type EditorMode = "auto" | "gutenberg" | "elementor" | "hybrid";
export type FidelityMode = "max_editability" | "max_fidelity" | "balanced";
export type SiteJobStatus =
  | "queued" | "analyzing" | "generating" | "uploading_assets" | "rendering"
  | "validating" | "correcting" | "publishing" | "completed" | "failed";

export type SiteGenerationJob = {
  id: string;
  code: string;
  clientId: string | null;
  status: SiteJobStatus;
  sourceType: SourceType;
  sourceUrl: string;
  pageType: string;
  industry: string;
  editorMode: EditorMode;
  fidelityMode: FidelityMode;
  designIrId: string | null;
  stageDetail: string;
  error: string | null;
  createdAt: string;
  updatedAt: string;
};

export type DesignSection = {
  kind: string;
  heading: string;
  layout: string;
  content: boolean;
  slots: string[];
  textSample: string;
  bgColor: string;
  textColor: string;
};

export type DesignIR = {
  id: string;
  clientId: string | null;
  sourceType: SourceType;
  sourceUrl: string;
  industry: string;
  pageType: string;
  designStyle: string;
  version: number;
  palette: { primary: string; secondary: string; background: string; text: string; accent: string };
  typography: { headingFont: string; bodyFont: string; baseSize: string };
  containerWidthPx: number | null;
  sectionOrder: string[];
  responsive: { viewport: "desktop" | "tablet" | "mobile"; width: number; containerWidthPx: number | null; baseFontSize: string; sectionCount: number }[];
  components: { buttonStyle: string; cardStyle: string; spacingScale: string };
  assets: { url: string; alt: string; width: number; height: number; kind: "logo" | "image" }[];
  sections: DesignSection[];
  supportedEditors: EditorMode[];
  notes: string;
  wireframeHtml: string;
  createdAt: string;
  updatedAt: string;
};

export type SiteTemplate = {
  id: string;
  key: string;
  name: string;
  category: string;
  industry: string;
  pageType: string;
  designStyle: string;
  blueprintKey: string | null;
  designIrId: string | null;
  supportedEditors: string[];
  previewImageUrl: string;
  description: string;
  author: string;
  version: number;
  rating: number | null;
  isActive: boolean;
};

export type VisualDiagnostic = { kind: string; section: string; detail: string; magnitude: number };
export type VisualValidation = {
  id: string;
  jobId: string;
  renderedUrl: string;
  status: "pass" | "warn" | "fail";
  diagnostics: VisualDiagnostic[];
  createdAt: string;
};

export type CreateSiteBuilderJobInput = {
  sourceType: SourceType;
  sourceUrl?: string;
  template?: string;
  industry?: string;
  pageType?: string;
  editorMode?: EditorMode;
  fidelityMode?: FidelityMode;
  clientId?: string | null;
};

// --- Step 1: "What are you creating?" — a curated page-type starting point ------
export const CREATION_TYPES: { key: string; pageType: string; label: string; icon: string; hint: string }[] = [
  { key: "website", pageType: "homepage", label: "New Website", icon: "language", hint: "A full homepage — hero, benefits, proof, CTA." },
  { key: "page", pageType: "service", label: "New Page", icon: "description", hint: "A single service/detail page." },
  { key: "blog", pageType: "blog", label: "Blog Article", icon: "article", hint: "A long-form article — ToC, body, FAQ." },
  { key: "landing", pageType: "local", label: "Landing Page", icon: "flag", hint: "A focused, one-CTA campaign page." },
];

// --- Step 2: "Where should the design come from?" -------------------------------
export const SOURCE_TYPES: { key: SourceType; label: string; icon: string; hint: string }[] = [
  { key: "existing_site", label: "Existing Website", icon: "sync", hint: "Reconstruct a site you already own — layout + real content." },
  { key: "reference_site", label: "Reference URL", icon: "visibility", hint: "Borrow the LAYOUT of a site you like — never its copy." },
  { key: "template", label: "Template", icon: "grid_view", hint: "Start from an audited, best-practice page template." },
  { key: "manual", label: "Blank", icon: "add_box", hint: "Start from a blank canvas you build by hand." },
];

export const EDITOR_MODES: { key: EditorMode; label: string; hint: string }[] = [
  { key: "auto", label: "Auto", hint: "Elementor if the site has it, else native blocks." },
  { key: "gutenberg", label: "Gutenberg", hint: "Native WordPress blocks — works on every site." },
  { key: "elementor", label: "Elementor", hint: "A drag-and-drop Elementor page." },
  { key: "hybrid", label: "Hybrid", hint: "Native blocks for everything (today: same as Gutenberg)." },
];

export const FIDELITY_MODES: { key: FidelityMode; label: string; hint: string }[] = [
  { key: "max_editability", label: "Max Editability", hint: "Simplest structure — easiest to hand-edit." },
  { key: "balanced", label: "Balanced", hint: "The default — a practical mix of fidelity and editability." },
  { key: "max_fidelity", label: "Max Fidelity", hint: "Match the source as closely as possible." },
];

export const STATUS_META: Record<SiteJobStatus, { label: string; cls: "ok" | "info" | "warn" | "mut" }> = {
  queued: { label: "Queued", cls: "mut" },
  analyzing: { label: "Analyzing", cls: "info" },
  generating: { label: "Generating", cls: "info" },
  uploading_assets: { label: "Uploading assets", cls: "info" },
  rendering: { label: "Rendering", cls: "info" },
  validating: { label: "Validating", cls: "info" },
  correcting: { label: "Correcting", cls: "warn" },
  publishing: { label: "Publishing", cls: "info" },
  completed: { label: "Completed", cls: "ok" },
  failed: { label: "Failed", cls: "warn" },
};

export const ACTIVE_STATUSES: SiteJobStatus[] = [
  "queued", "analyzing", "generating", "uploading_assets", "rendering", "validating", "publishing",
];
