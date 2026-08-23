// ============================================================
// AIOS · Content module mock data (Module 02 — Content)
// A content job = content type + topic, moved through an
// ~90% automated pipeline with a human review gate (the "10%").
// Swap these arrays for FastAPI / Postgres queries when the
// backend is wired. Shapes mirror the content_jobs data model.
// ============================================================
import { SERIES } from "@/lib/data";

export type PageType = "service" | "blog" | "local" | "gbp_post";
export type PublishTarget = "WordPress" | "PDF/Markdown";
export type Framework = "AIDA" | "PAS" | "BAB" | "FAB" | "4 Ps" | "PASTOR" | "4 U's";

// The 7 named page-layout templates (the audited section sequences). Mirrors the
// backend PageTemplate literal + app/services/page_blueprints.py TEMPLATES. When a
// template is picked the generated page is built to it and the content is slotted into
// its sections; "Auto" derives it from the page type (or the analyzed site wins).
export type PageTemplate =
  | "service" | "location" | "service_area" | "blog" | "faq" | "local" | "homepage";
export const PAGE_TEMPLATES: { key: PageTemplate; label: string; bestFor: string }[] = [
  { key: "service",      label: "Service page",           bestFor: "A single service — benefits, process, proof, pricing, FAQ." },
  { key: "location",     label: "Location page",          bestFor: "One physical location — NAP, local services, reviews, map." },
  { key: "service_area", label: "Service-area page",      bestFor: "A service across an area — covered areas, local proof." },
  { key: "blog",         label: "Blog / article",         bestFor: "Informational post — ToC, body sections, FAQ, conclusion." },
  { key: "faq",          label: "FAQ page",               bestFor: "A Q&A hub — accordion, simplest questions first." },
  { key: "local",        label: "Local business landing", bestFor: "Local-intent homepage — services, reviews, areas, map." },
  { key: "homepage",     label: "Homepage",               bestFor: "Company homepage — benefits, proof, testimonials, stats." },
];

// Job state machine: queued → drafting → needs_review → publishing → done
// (plus failed/retry and rejected off the review gate).
//
// `degraded` is terminal and is NOT a success: the pipeline finished but the
// outcome was partial — in practice a publish that rendered a real artifact but
// reached no live site (no WordPress credential). It previously reported as
// "done", so a job that put nothing on the client's website looked identical to
// one that did. Never render it with a success affordance.
export type JobStatus =
  | "queued" | "drafting" | "needs_review" | "publishing" | "done"
  | "degraded" | "failed" | "rejected";

export type ContentJob = {
  id: string;
  client: string;
  color: string;        // per-client accent (SERIES slot)
  pageType: PageType;
  topic: string;
  framework: Framework; // resolved framework (Auto picks one)
  auto: boolean;        // was the framework auto-selected
  target: PublishTarget;
  status: JobStatus;
  cost: number;         // per-page cost, ~$10–50
  words: number;        // long-form draft length
  schema: string;       // validated JSON-LD @type
  images: number;       // AI images generated (alt-tagged)
  stage: string;        // current pipeline stage label
  ago: string;
};

// Kanban columns — membership is derived from job.status.
export type ColumnKey =
  | "queued" | "drafting" | "needs_review" | "publishing" | "done" | "degraded";

// The board filters strictly by `status`, so a status with no column here does not
// merely lose its styling — it matches nothing and DISAPPEARS from the board. That is
// why `degraded` is a column and not just a tone: a job that finished without
// reaching the client's site is precisely the one an operator must not lose sight of.
//
// The label says "Not Live" rather than "Degraded" deliberately. `degraded` is the
// platform's vocabulary word (app/jobs/status.py) and stays the key, but a board is
// read at a glance and the operator needs the CONSEQUENCE, not the taxonomy: the page
// is not on the client's website. The card's stage string carries the cause.
export const COLUMNS: { key: ColumnKey; label: string; icon: string; tone: string }[] = [
  { key: "queued",       label: "Queued",       icon: "inbox",         tone: "mut" },
  { key: "drafting",     label: "Drafting",     icon: "auto_awesome",  tone: "info" },
  { key: "needs_review", label: "Needs Review", icon: "rate_review",   tone: "warn" },
  { key: "publishing",   label: "Publishing",   icon: "rocket_launch", tone: "info" },
  { key: "done",         label: "Done",         icon: "check_circle",  tone: "ok" },
  { key: "degraded",     label: "Not Live",     icon: "warning",       tone: "warn" },
];

// The 7 copywriting frameworks, auto-selected by content type + search intent.
export type FrameworkRef = { key: Framework; expansion: string; bestFor: string };
export const FRAMEWORKS: FrameworkRef[] = [
  { key: "AIDA",   expansion: "Attention · Interest · Desire · Action",              bestFor: "Service landing pages that need one clear CTA." },
  { key: "PAS",    expansion: "Problem · Agitate · Solution",                        bestFor: "Blog posts targeting pain-point search intent." },
  { key: "BAB",    expansion: "Before · After · Bridge",                             bestFor: "Transformation & case-study style local pages." },
  { key: "FAB",    expansion: "Features · Advantages · Benefits",                    bestFor: "Spec-heavy service pages that justify value." },
  { key: "4 Ps",   expansion: "Promise · Picture · Proof · Push",                    bestFor: "High-intent conversion & promo pages." },
  { key: "PASTOR", expansion: "Problem · Amplify · Story · Transform · Offer · Response", bestFor: "Long-form authority & sales narratives." },
  { key: "4 U's",  expansion: "Useful · Urgent · Unique · Ultra-specific",           bestFor: "Titles, meta descriptions & bulk headlines." },
];

export const TARGETS: PublishTarget[] = ["WordPress", "PDF/Markdown"];
export const PAGE_TYPES: PageType[] = ["service", "blog", "local", "gbp_post"];
// Display label per page type — CSS text-transform:capitalize handles the plain
// words fine, but "gbp_post" needs an explicit label (no auto de-snake-casing).
export const PAGE_TYPE_LABELS: Record<PageType, string> = {
  service: "Service",
  blog: "Blog",
  local: "Local",
  gbp_post: "GMB Post",
};

// Per-client accent, reusing the existing agency client roster.
const CLR: Record<string, string> = {
  "NorthPeak Dental": SERIES.c1,
  "Lumen Realty": SERIES.c4,
  "Verde Cafe": SERIES.c2,
  "Atlas Legal": SERIES.c5,
  "BrightHVAC": SERIES.c3,
  "Coastline Fit": SERIES.c2,
  "Meridian Wealth": SERIES.c4,
  "Orchard Pediatrics": SERIES.c1,
};
export const clientAccent = (c: string) => CLR[c] ?? SERIES.c1;

// ============================================================
// Research-first bulk content + site-design matcher (Module 02
// extension). These are OPERATIONAL shapes (no backend contract-
// lock mirror); they mirror the FastAPI response models 1:1 so the
// JSON drops straight in. See backend app/schemas/content.py.
// ============================================================

// The six content types the recommender researches. service_location returns
// city × service landing pages (each item carries city + service).
export type ResearchContentType =
  | "service" | "location" | "service_location" | "service_area" | "blog" | "faq";
export type ResearchDifficulty = "easy" | "medium" | "hard";

export const RESEARCH_CONTENT_TYPES: { key: ResearchContentType; label: string }[] = [
  { key: "service", label: "Service" },
  { key: "location", label: "Location" },
  { key: "service_location", label: "Service × Location" },
  { key: "service_area", label: "Service area" },
  { key: "blog", label: "Blog" },
  { key: "faq", label: "FAQ" },
];

export const DIFFICULTY_META: Record<ResearchDifficulty, { label: string; cls: string }> = {
  easy: { label: "Easy", cls: "ok" },
  medium: { label: "Medium", cls: "warn" },
  hard: { label: "Hard", cls: "op-crit" },
};

// One recommended page (a "checkbox"). Symmetric: it comes back from /content/research
// and is posted back unchanged (camelCase) to /content/research/generate as a selection.
// city/service are meaningful only for the service_location type.
export type ResearchItem = {
  title: string;
  pageType: string;
  primaryKeyword: string;
  secondaryKeywords: string[];
  estVolume: number;
  difficulty: ResearchDifficulty;
  rationale: string;
  city: string;
  service: string;
};

// --- Site-design profile (POST /content/site-design) --------------------------
// Snake_case, no aliases: the profile round-trips unchanged from the response into a
// content job's design_profile (source_pack) and back out at publish time.
export type SiteDesignPalette = {
  primary: string;
  secondary: string;
  background: string;
  text: string;
  accent: string;
};
export type SiteDesignTypography = {
  heading_font: string;
  body_font: string;
  base_size: string;
};
// One section of the analyzed page blueprint (its kind + heading + layout variant).
export type SiteDesignSection = {
  kind: string;
  heading: string;
  layout: string;
};
export type SiteDesignLayout = {
  container_width: string;
  section_order: string[];
  // The full ordered blueprint (every section's kind + heading + layout, in exact
  // sequence) — the deep structural capture the publish path builds the page to.
  blueprint: SiteDesignSection[];
  hero_style: string;
  cta_style: string;
};
export type SiteDesignComponents = {
  button_style: string;
  card_style: string;
  spacing_scale: string;
};
export type SiteDesignProfile = {
  palette: SiteDesignPalette;
  typography: SiteDesignTypography;
  layout: SiteDesignLayout;
  components: SiteDesignComponents;
  notes: string;
  // A self-contained, styled HTML snippet (inline <style> + one <section>) that renders a
  // representative hero/homepage section in the extracted colours + fonts + layout, so the
  // operator can SEE how a matching page would look. Rendered in a sandboxed iframe.
  wireframeHtml: string;
};

// --- Live page editor model (the editable page a job renders to) --------------
// One section of the page (hero / card grid / steps / accordion FAQ / testimonials /
// CTA / prose). `data` is kind-specific (subhead+buttons, cards[], steps[], faq[],
// quotes[], text+button, html). Mirrors app/services/page_model.py.
export type PageSection = {
  id: string;
  kind: string;
  layout: string;
  heading: string;
  visible: boolean;
  data: Record<string, unknown>;
  images: { url: string; alt: string }[];
};
export type PageModelDoc = {
  title: string;
  design: Record<string, unknown>;
  sections: PageSection[];
};

// ── Template gallery: the 7 seeded "best of the best" page templates, each with a
// visual blueprint (rendered as a live mini-mockup in the Design step) + a curated
// default theme the operator can recolour / re-font. A selected template + theme is
// synthesised into a SiteDesignProfile (profileFromTemplate) so it flows to the backend
// through the SAME design_profile seam a site-match analysis uses — the generated copy
// is then slotted into the template's sections in the chosen look. ────────────────────
export type TemplateTheme = { primary: string; heading: string; body: string };

// One visual block of a template's mock layout. `n` = column/stat count where relevant.
export type PreviewBlock =
  { t: "nav" | "hero" | "heading" | "text" | "cards" | "image" | "stats"
      | "cta" | "faq" | "review" | "map" | "toc" | "split"; n?: number };

// Curated Google Fonts (loaded on demand from fonts.googleapis.com) — a tight, tasteful
// set rather than the full 1500-font firehose. Grouped so headings can pair with a body.
export const GOOGLE_FONTS: { name: string; cat: "sans" | "serif" }[] = [
  { name: "Inter", cat: "sans" }, { name: "Poppins", cat: "sans" },
  { name: "Montserrat", cat: "sans" }, { name: "Manrope", cat: "sans" },
  { name: "Work Sans", cat: "sans" }, { name: "DM Sans", cat: "sans" },
  { name: "Space Grotesk", cat: "sans" }, { name: "Sora", cat: "sans" },
  { name: "Raleway", cat: "sans" }, { name: "Nunito Sans", cat: "sans" },
  { name: "Playfair Display", cat: "serif" }, { name: "Lora", cat: "serif" },
  { name: "Merriweather", cat: "serif" }, { name: "Libre Baskerville", cat: "serif" },
  { name: "Source Serif 4", cat: "serif" },
];

// The default look for each seeded template — a distinct, considered palette + pairing so
// the gallery reads as seven finished designs, not seven identical boxes. All defaults are
// a modern editorial / SaaS system: strong sans-serif headings over Inter body, and a
// confident-but-tasteful accent (no dated serif pairings). `blog` deliberately uses a
// clean Space Grotesk / Inter pairing with an indigo accent — NOT the old Playfair-serif
// violet, which read as outdated on a plain WordPress theme.
export const TEMPLATE_THEME_DEFAULTS: Record<PageTemplate, TemplateTheme> = {
  service:      { primary: "#2563EB", heading: "Space Grotesk", body: "Inter" },
  location:     { primary: "#059669", heading: "Sora",          body: "Inter" },
  service_area: { primary: "#0891B2", heading: "Manrope",       body: "Inter" },
  blog:         { primary: "#4F46E5", heading: "Space Grotesk", body: "Inter" },
  faq:          { primary: "#0EA5E9", heading: "Manrope",       body: "Inter" },
  local:        { primary: "#EA580C", heading: "Montserrat",    body: "Inter" },
  homepage:     { primary: "#0F172A", heading: "Space Grotesk", body: "Inter" },
};

// The visual section blueprint for each template — drives BOTH the mini-mockup and the
// synthesised design profile's section order.
export const TEMPLATE_BLUEPRINTS: Record<PageTemplate, PreviewBlock[]> = {
  service:      [{ t: "hero" }, { t: "heading" }, { t: "text" }, { t: "cards", n: 3 }, { t: "review" }, { t: "stats", n: 3 }, { t: "cta" }, { t: "faq" }],
  location:     [{ t: "hero" }, { t: "map" }, { t: "cards", n: 3 }, { t: "review" }, { t: "cta" }, { t: "faq" }],
  service_area: [{ t: "hero" }, { t: "heading" }, { t: "text" }, { t: "cards", n: 3 }, { t: "map" }, { t: "review" }, { t: "cta" }],
  blog:         [{ t: "nav" }, { t: "heading" }, { t: "toc" }, { t: "text" }, { t: "image" }, { t: "text" }, { t: "faq" }, { t: "cta" }],
  faq:          [{ t: "hero" }, { t: "faq" }, { t: "faq" }, { t: "cta" }],
  local:        [{ t: "hero" }, { t: "cards", n: 3 }, { t: "review" }, { t: "map" }, { t: "stats", n: 3 }, { t: "cta" }],
  homepage:     [{ t: "hero" }, { t: "stats", n: 4 }, { t: "cards", n: 3 }, { t: "review" }, { t: "split" }, { t: "cta" }],
};

// Blend a hex toward black/white by `amt` (0..1). Small, dependency-free.
function _mixHex(hex: string, toward: "black" | "white", amt: number): string {
  const m = /^#?([0-9a-f]{6})$/i.exec(hex.trim());
  if (!m) return hex;
  const n = parseInt(m[1], 16);
  const t = toward === "black" ? 0 : 255;
  const ch = (sh: number) => {
    const c = (n >> sh) & 0xff;
    return Math.round(c + (t - c) * amt).toString(16).padStart(2, "0");
  };
  return `#${ch(16)}${ch(8)}${ch(0)}`;
}

// Map a preview block to a design-profile section (kind/heading/layout).
const _BLOCK_SECTION: Record<PreviewBlock["t"], { kind: string; heading: string; layout: string } | null> = {
  nav: null,
  hero: { kind: "hero", heading: "Hero", layout: "split" },
  heading: { kind: "prose", heading: "Overview", layout: "text" },
  text: { kind: "prose", heading: "Details", layout: "text" },
  cards: { kind: "cards", heading: "Highlights", layout: "grid-3" },
  image: { kind: "media", heading: "Feature image", layout: "image" },
  stats: { kind: "stats", heading: "By the numbers", layout: "row" },
  cta: { kind: "cta", heading: "Get started", layout: "band" },
  faq: { kind: "faq", heading: "FAQ", layout: "accordion" },
  review: { kind: "testimonials", heading: "Reviews", layout: "cards" },
  map: { kind: "map", heading: "Find us", layout: "map" },
  toc: { kind: "toc", heading: "Contents", layout: "list" },
  split: { kind: "split", heading: "Two-column", layout: "two-col" },
};

// Synthesise a full SiteDesignProfile from a template + theme, so a chosen template rides
// the existing design_profile publish seam (palette + typography + ordered blueprint). The
// wireframeHtml renders a representative hero in the theme for the shared preview iframe.
export function profileFromTemplate(key: PageTemplate, theme: TemplateTheme): SiteDesignProfile {
  const blocks = TEMPLATE_BLUEPRINTS[key] ?? [];
  const blueprint: SiteDesignSection[] = blocks
    .map((b) => _BLOCK_SECTION[b.t])
    .filter((s): s is { kind: string; heading: string; layout: string } => !!s);
  const label = PAGE_TEMPLATES.find((t) => t.key === key)?.label ?? key;
  const wf = `<style>*{margin:0;box-sizing:border-box}.h{font-family:'${theme.heading}',system-ui,sans-serif}`
    + `.b{font-family:'${theme.body}',system-ui,sans-serif}section{padding:34px 30px;background:${_mixHex(theme.primary, "white", 0.9)}}`
    + `h1{color:${_mixHex(theme.primary, "black", 0.35)};font-size:30px;line-height:1.1;margin-bottom:10px}`
    + `p{color:#4a4a4a;font-size:14px;max-width:52ch;margin-bottom:16px}`
    + `a{display:inline-block;background:${theme.primary};color:#fff;font-size:13px;font-weight:700;padding:10px 18px;border-radius:8px;text-decoration:none}</style>`
    + `<section><h1 class="h">${label} headline goes here</h1>`
    + `<p class="b">Your generated, fact-grounded copy is slotted into this ${label.toLowerCase()} — in your chosen colour and fonts.</p>`
    + `<a class="b" href="#">Primary call to action</a></section>`;
  return {
    palette: {
      primary: theme.primary,
      secondary: _mixHex(theme.primary, "black", 0.28),
      background: "#ffffff",
      text: "#14181f",
      accent: _mixHex(theme.primary, "white", 0.12),
    },
    typography: { heading_font: theme.heading, body_font: theme.body, base_size: "16px" },
    layout: {
      container_width: "1120px",
      section_order: blueprint.map((s) => s.heading),
      blueprint,
      hero_style: key === "blog" || key === "faq" ? "centered" : "split",
      cta_style: "band",
    },
    components: { button_style: "solid rounded", card_style: "soft shadow", spacing_scale: "comfortable" },
    notes: `Template "${label}" in a custom theme — primary ${theme.primary}, ${theme.heading} headings over ${theme.body} body.`,
    wireframeHtml: wf,
  };
}
