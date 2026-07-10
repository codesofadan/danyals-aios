// ============================================================
// AIOS · Policy Radar (Module 05) mock data layer
// The platform's always-on brain: Watch → Detect → Research →
// Flag (KB) → Recommend → human-confirm → closed loop into
// audit checks / content guidance / client advisories.
// Swap these arrays for FastAPI / Postgres + the crawler jobs
// when the backend is wired.
// ============================================================
import { SERIES } from "@/lib/data";

// ---- taxonomy -------------------------------------------------
export type Severity = "critical" | "major" | "minor" | "info";
export type Category = "algorithm" | "policy" | "technical" | "content" | "local" | "geo";
export type Region = "global" | "national";
export type TargetModule = "audit" | "content" | "portal";
export type Scope = "global" | "client" | "site";
export type RecStatus = "new" | "acknowledged" | "applied" | "dismissed";
export type SourceStatus = "ok" | "change";

// severity badge classes: critical=crit, major=warn, minor=info, info=mut
export const SEV_META: Record<Severity, { label: string; cls: string; color: string }> = {
  critical: { label: "Critical", cls: "crit", color: "var(--crit)" },
  major: { label: "Major", cls: "warn", color: "var(--warn)" },
  minor: { label: "Minor", cls: "info", color: "var(--c4)" },
  info: { label: "Info", cls: "mut", color: "var(--muted)" },
};

export const CAT_META: Record<Category, { label: string; icon: string; color: string }> = {
  algorithm: { label: "Algorithm", icon: "hub", color: SERIES.c1 },
  policy: { label: "Policy", icon: "gavel", color: SERIES.c5 },
  technical: { label: "Technical", icon: "code", color: SERIES.c4 },
  content: { label: "Content", icon: "article", color: SERIES.c2 },
  local: { label: "Local", icon: "location_on", color: SERIES.c3 },
  geo: { label: "GEO", icon: "auto_awesome", color: SERIES.c1 },
};

export const MODULE_META: Record<TargetModule, { label: string; icon: string }> = {
  audit: { label: "Audit Engine", icon: "fact_check" },
  content: { label: "Content Studio", icon: "edit_note" },
  portal: { label: "Client Portal", icon: "supervisor_account" },
};

// ---- watched sources -----------------------------------------
export type Source = {
  id: string;
  name: string;
  kind: string;
  url: string;
  icon: string;
  lastChecked: string;
  lastHash: string;
  status: SourceStatus;
  note: string;
};

export const sources: Source[] = [
  {
    id: "src-status",
    name: "Google Search Status Dashboard",
    kind: "Ranking & serving incidents",
    url: "https://status.search.google.com/",
    icon: "monitor_heart",
    lastChecked: "38s ago",
    lastHash: "e7c1·a94f",
    status: "change",
    note: "August 2026 core update marked as rolling out",
  },
  {
    id: "src-central",
    name: "Google Search Central",
    kind: "Blog + developer docs",
    url: "https://developers.google.com/search",
    icon: "menu_book",
    lastChecked: "2m ago",
    lastHash: "1b8d·0f52",
    status: "change",
    note: "Spam policies + merchant structured-data docs edited",
  },
  {
    id: "src-qrg",
    name: "Quality Rater Guidelines (QRG)",
    kind: "Search quality evaluator PDF",
    url: "https://guidelines.raterhub.com/searchqualityevaluatorguidelines.pdf",
    icon: "rule",
    lastChecked: "14m ago",
    lastHash: "9a44·c7e0",
    status: "ok",
    note: "v11 ingested · no change since last diff",
  },
];

// ---- detected change events ----------------------------------
export type ChangeEvent = {
  id: string;
  sourceId: string;
  sourceName: string;
  summary: string;
  severity: Severity;
  detected: string;
};

export const changeEvents: ChangeEvent[] = [
  {
    id: "ce-1",
    sourceId: "src-status",
    sourceName: "Search Status Dashboard",
    summary: "August 2026 core update — status flipped to “Rollout in progress”, ~2 week window.",
    severity: "critical",
    detected: "38s ago",
  },
  {
    id: "ce-2",
    sourceId: "src-central",
    sourceName: "Search Central · Blog",
    summary: "Spam policies page diff: “site reputation abuse” scope widened to first-party subfolders.",
    severity: "major",
    detected: "2m ago",
  },
  {
    id: "ce-3",
    sourceId: "src-central",
    sourceName: "Search Central · Docs",
    summary: "Merchant listing schema: shipping & return fields moved from recommended → required for rich results.",
    severity: "major",
    detected: "1h ago",
  },
  {
    id: "ce-4",
    sourceId: "src-central",
    sourceName: "Search Central · Blog",
    summary: "AI Overviews expanding to more queries — new note on surfacing concise, entity-rich answers.",
    severity: "major",
    detected: "5h ago",
  },
  {
    id: "ce-5",
    sourceId: "src-status",
    sourceName: "Search Status Dashboard",
    summary: "Local / Google Business Profile ranking signal adjustment logged for review.",
    severity: "minor",
    detected: "1d ago",
  },
  {
    id: "ce-6",
    sourceId: "src-qrg",
    sourceName: "Quality Rater Guidelines",
    summary: "QRG v11 published — new subsection on AI-generated content & E-E-A-T evaluation.",
    severity: "info",
    detected: "3d ago",
  },
];

// ---- knowledge base entries (versioned, deduped, cited) ------
export type KBEntry = {
  id: string;
  title: string;
  summary: string;
  severity: Severity;
  category: Category;
  region: Region;
  regionLabel: string;
  sourceName: string;
  sourceUrl: string;
  version: string;
  detected: string;
};

export const kbEntries: KBEntry[] = [
  {
    id: "kb-core-aug26",
    title: "August 2026 Core Update",
    summary: "Broad core update rewarding genuinely helpful, people-first content; sitewide quality signals re-weighted.",
    severity: "critical",
    category: "algorithm",
    region: "global",
    regionLabel: "Global",
    sourceName: "Search Status Dashboard",
    sourceUrl: "https://status.search.google.com/",
    version: "v3",
    detected: "38s ago",
  },
  {
    id: "kb-spam-reputation",
    title: "Site Reputation Abuse — scope widened",
    summary: "Third-party & thin first-party “parasite” content hosted under a trusted domain now explicitly in-scope for manual actions.",
    severity: "major",
    category: "policy",
    region: "global",
    regionLabel: "Global",
    sourceName: "Search Central · Spam policies",
    sourceUrl: "https://developers.google.com/search/docs/essentials/spam-policies",
    version: "v2",
    detected: "2m ago",
  },
  {
    id: "kb-merchant-schema",
    title: "Merchant listing: shipping & returns now required",
    summary: "Product rich results require valid shippingDetails and returnPolicy; missing fields drop the merchant snippet.",
    severity: "major",
    category: "technical",
    region: "global",
    regionLabel: "Global",
    sourceName: "Search Central · Structured data docs",
    sourceUrl: "https://developers.google.com/search/docs/appearance/structured-data/product",
    version: "v1",
    detected: "1h ago",
  },
  {
    id: "kb-ai-overviews",
    title: "AI Overviews / GEO expansion",
    summary: "Generative answers surfacing on more queries; concise, well-structured, entity-rich passages are favored for citation.",
    severity: "major",
    category: "geo",
    region: "global",
    regionLabel: "Global",
    sourceName: "Search Central · Blog",
    sourceUrl: "https://developers.google.com/search/blog",
    version: "v1",
    detected: "5h ago",
  },
  {
    id: "kb-gbp-local",
    title: "Google Business Profile — local ranking tweak",
    summary: "Proximity + review-recency weighting adjusted for service-area businesses; NAP consistency more decisive.",
    severity: "minor",
    category: "local",
    region: "national",
    regionLabel: "US · National",
    sourceName: "Search Status Dashboard",
    sourceUrl: "https://status.search.google.com/",
    version: "v1",
    detected: "1d ago",
  },
  {
    id: "kb-qrg-v11",
    title: "QRG v11 — AI content & E-E-A-T",
    summary: "New rater guidance: AI-assisted content is acceptable when it demonstrates real experience and expertise; scaled low-value content rated Lowest.",
    severity: "info",
    category: "content",
    region: "global",
    regionLabel: "Global",
    sourceName: "Quality Rater Guidelines v11",
    sourceUrl: "https://guidelines.raterhub.com/searchqualityevaluatorguidelines.pdf",
    version: "v1",
    detected: "3d ago",
  },
];

// ---- recommendations (Command Center) ------------------------
export type Recommendation = {
  id: string;
  kbId: string;
  title: string;        // what changed
  why: string;          // why it matters
  action: string;       // recommended action
  scope: Scope;
  target: TargetModule;
  region: Region;
  regionLabel: string;
  status: RecStatus;
  clients?: string;     // affected clients, when scoped
};

export const recommendations: Recommendation[] = [
  {
    id: "rec-1",
    kbId: "kb-core-aug26",
    title: "August 2026 core update is rolling out",
    why: "Core updates re-weight sitewide quality — thin, templated or AI-scaled pages are the biggest risk to rankings during the window.",
    action: "Add audit check “E-E-A-T & helpful-content depth scan” and re-run full audits for all clients before rollout completes.",
    scope: "global",
    target: "audit",
    region: "global",
    regionLabel: "Global",
    status: "new",
  },
  {
    id: "rec-2",
    kbId: "kb-merchant-schema",
    title: "Shipping & returns structured data now required",
    why: "Product rich results silently disappear when shippingDetails / returnPolicy are missing — directly hits e-commerce visibility & CTR.",
    action: "Add audit check “Merchant schema completeness” validating shippingDetails + returnPolicy on all product pages.",
    scope: "global",
    target: "audit",
    region: "global",
    regionLabel: "Global",
    status: "new",
  },
  {
    id: "rec-3",
    kbId: "kb-ai-overviews",
    title: "AI Overviews favor concise, entity-rich answers",
    why: "As generative answers expand, pages that lead with a clear, citable summary win the AI Overview reference and referral traffic.",
    action: "Adjust content guidance: require a 40–60 word answer summary + entity list at the top of every new brief.",
    scope: "global",
    target: "content",
    region: "global",
    regionLabel: "Global",
    status: "acknowledged",
  },
  {
    id: "rec-4",
    kbId: "kb-gbp-local",
    title: "Local ranking tweak affects service-area clients",
    why: "Proximity & review-recency reweighting hits map-pack visibility for local, service-area businesses in the US market.",
    action: "Raise a client advisory for national/local clients and schedule a GBP + NAP consistency review.",
    scope: "client",
    target: "portal",
    region: "national",
    regionLabel: "US · National",
    status: "new",
    clients: "NorthPeak Dental · BrightHVAC · Verde Cafe",
  },
  {
    id: "rec-5",
    kbId: "kb-spam-reputation",
    title: "Site reputation abuse scope widened",
    why: "Guest-post, coupon and thin partner sections under a client domain can now trigger a manual action against the whole site.",
    action: "Add audit check “Reputation-abuse exposure” and advise clients hosting third-party content to no-index or gate it.",
    scope: "global",
    target: "audit",
    region: "global",
    regionLabel: "Global",
    status: "new",
  },
];

// ---- KPI helpers ---------------------------------------------
export const REC_OPEN: RecStatus[] = ["new", "acknowledged"];
