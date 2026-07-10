// ============================================================
// AIOS · Content module mock data (Module 02 — Content)
// A content job = content type + topic, moved through an
// ~90% automated pipeline with a human review gate (the "10%").
// Swap these arrays for FastAPI / Postgres queries when the
// backend is wired. Shapes mirror the content_jobs data model.
// ============================================================
import { SERIES } from "@/lib/data";

export type PageType = "service" | "blog" | "local";
export type PublishTarget = "WordPress" | "PDF/Markdown";
export type Framework = "AIDA" | "PAS" | "BAB" | "FAB" | "4 Ps" | "PASTOR" | "4 U's";

// Job state machine: queued → drafting → needs_review → publishing → done
// (plus failed/retry and rejected off the review gate).
export type JobStatus =
  | "queued" | "drafting" | "needs_review" | "publishing" | "done"
  | "failed" | "rejected";

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
export type ColumnKey = "queued" | "drafting" | "needs_review" | "publishing" | "done";
export const COLUMNS: { key: ColumnKey; label: string; icon: string; tone: string }[] = [
  { key: "queued",       label: "Queued",       icon: "inbox",         tone: "mut" },
  { key: "drafting",     label: "Drafting",     icon: "auto_awesome",  tone: "info" },
  { key: "needs_review", label: "Needs Review", icon: "rate_review",   tone: "warn" },
  { key: "publishing",   label: "Publishing",   icon: "rocket_launch", tone: "info" },
  { key: "done",         label: "Done",         icon: "check_circle",  tone: "ok" },
];

// The automated pipeline, in order. Research is optional (Serper SERP+entities).
export const PIPELINE: { label: string; icon: string; optional?: boolean }[] = [
  { label: "Research", icon: "travel_explore", optional: true },
  { label: "Framework", icon: "category" },
  { label: "Outline", icon: "format_list_bulleted" },
  { label: "Draft", icon: "edit_note" },
  { label: "Titles & meta", icon: "title" },
  { label: "Schema", icon: "data_object" },
  { label: "AI images", icon: "imagesmode" },
  { label: "Assemble", icon: "dashboard_customize" },
  { label: "Review", icon: "how_to_reg" },
  { label: "Publish", icon: "public" },
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
export const PAGE_TYPES: PageType[] = ["service", "blog", "local"];

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

export const contentJobs: ContentJob[] = [
  { id: "CJ-4192", client: "Verde Cafe", color: CLR["Verde Cafe"], pageType: "local", topic: "Best brunch in Portland's Pearl District", framework: "BAB", auto: true, target: "PDF/Markdown", status: "queued", cost: 14, words: 0, schema: "LocalBusiness", images: 0, stage: "Queued", ago: "6m ago" },
  { id: "CJ-4188", client: "NorthPeak Dental", color: CLR["NorthPeak Dental"], pageType: "blog", topic: "Do you really need a night guard?", framework: "PAS", auto: true, target: "WordPress", status: "queued", cost: 16, words: 0, schema: "Article", images: 0, stage: "Queued", ago: "22m ago" },
  { id: "CJ-4180", client: "Lumen Realty", color: CLR["Lumen Realty"], pageType: "blog", topic: "2026 first-time homebuyer guide", framework: "PAS", auto: false, target: "WordPress", status: "drafting", cost: 24, words: 1840, schema: "Article", images: 4, stage: "Draft", ago: "just now" },
  { id: "CJ-4175", client: "Orchard Pediatrics", color: CLR["Orchard Pediatrics"], pageType: "local", topic: "Pediatric urgent care in Austin", framework: "AIDA", auto: true, target: "WordPress", status: "drafting", cost: 19, words: 920, schema: "MedicalClinic", images: 2, stage: "Titles & meta", ago: "3m ago" },
  { id: "CJ-4168", client: "NorthPeak Dental", color: CLR["NorthPeak Dental"], pageType: "service", topic: "Emergency dental care in Denver", framework: "FAB", auto: true, target: "WordPress", status: "needs_review", cost: 32, words: 1420, schema: "Service", images: 3, stage: "Review", ago: "18m ago" },
  { id: "CJ-4161", client: "Atlas Legal", color: CLR["Atlas Legal"], pageType: "service", topic: "Personal injury claims: what to expect", framework: "PASTOR", auto: false, target: "WordPress", status: "needs_review", cost: 46, words: 2650, schema: "LegalService", images: 5, stage: "Review", ago: "41m ago" },
  { id: "CJ-4157", client: "Meridian Wealth", color: CLR["Meridian Wealth"], pageType: "service", topic: "Retirement planning for physicians", framework: "4 Ps", auto: false, target: "PDF/Markdown", status: "needs_review", cost: 50, words: 3100, schema: "FinancialService", images: 4, stage: "Review", ago: "1h ago" },
  { id: "CJ-4149", client: "BrightHVAC", color: CLR["BrightHVAC"], pageType: "local", topic: "AC repair near Scottsdale", framework: "AIDA", auto: true, target: "WordPress", status: "publishing", cost: 28, words: 1180, schema: "LocalBusiness", images: 3, stage: "Publish", ago: "12m ago" },
  { id: "CJ-4140", client: "Coastline Fit", color: CLR["Coastline Fit"], pageType: "blog", topic: "12-week strength program for beginners", framework: "PAS", auto: true, target: "WordPress", status: "done", cost: 22, words: 2010, schema: "Article", images: 6, stage: "Published", ago: "Yesterday" },
  { id: "CJ-4131", client: "BrightHVAC", color: CLR["BrightHVAC"], pageType: "service", topic: "Furnace installation & financing options", framework: "FAB", auto: false, target: "WordPress", status: "done", cost: 34, words: 1760, schema: "Service", images: 4, stage: "Published", ago: "2 days ago" },
];
