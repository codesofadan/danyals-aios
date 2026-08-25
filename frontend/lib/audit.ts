// ============================================================
// AIOS · Audit module data layer
// Grounded in the platform docs — Module 01 (Audit):
//   • The audit engine runs on a URL alone (no logins) as an
//     async job. Every audit is Free or Paid tier — tier decides
//     which paid data sources run behind a cost gate.
//   • Coverage: On-Page, Technical, Off-Page, Local SEO, AI
//     Analysis (GEO), and Strategy. Financial audit is Phase-2 (locked).
//   • Outputs: 20–30+ page house-styled PDF + JSON + numeric
//     scores, a live web version, stored to the client's Google
//     Sheet; on completion the milestone auto-advances + notify.
//   • Job states: queued → running → done (plus failed/retry).
// Swap these mocks for the FastAPI /audits endpoints later.
// ============================================================

import { SERIES } from "@/lib/data";

export type Tier = "Free" | "Paid";
// Crawl BREADTH — a separate axis from `Tier` (which authorises spend) and from
// `AuditTypeKey[]` (which scopes dimensions). Backend enum `audit_depth`.
export type AuditDepth = "free" | "standard" | "deep";
export type JobStatus = "queued" | "running" | "done" | "failed";
export type AuditTypeKey = "onpage" | "offpage" | "technical" | "local" | "geo" | "strategy";

export type AuditType = {
  key: AuditTypeKey;
  label: string;
  short: string;
  icon: string;
  color: string;
  paid: boolean; // relies on a paid data source / AI agents (gated on Free tier)
  blurb: string;
  checks: string[];
};

// The six live audit types + what each one checks. On-Page + Technical are the
// FREE deterministic dimensions; Off-Page, Local SEO, AI (GEO) and Strategy each
// spend on a paid provider or the AI agents.
export const auditTypes: AuditType[] = [
  {
    key: "onpage",
    label: "On-Page audit",
    short: "On-Page",
    icon: "checklist",
    color: SERIES.c1,
    paid: false,
    blurb: "Per-page fixes the team can ship today.",
    checks: ["Titles & meta", "Heading structure", "Content quality", "Internal links", "Image & alt hygiene"],
  },
  {
    key: "technical",
    label: "Technical audit",
    short: "Technical",
    icon: "manage_search",
    color: SERIES.c4,
    paid: false,
    blurb: "Crawl the site and grade its foundations.",
    checks: ["Crawl & indexing", "Core Web Vitals / speed", "Schema markup", "Security headers", "SSL / HTTPS"],
  },
  {
    key: "offpage",
    label: "Off-Page audit",
    short: "Off-Page",
    icon: "hub",
    color: SERIES.c2,
    paid: true,
    blurb: "Off-site authority, SERP position & competitors.",
    checks: ["SERP visibility", "Competitor gap", "Referring domains", "Anchor profile", "Brand authority"],
  },
  {
    key: "local",
    label: "Local SEO",
    short: "Local SEO",
    icon: "location_on",
    color: SERIES.c3,
    paid: true,
    blurb: "Map-pack readiness from Google data.",
    checks: ["Map-pack presence", "GBP categories", "NAP from Google Places", "Reviews & ratings", "Citation consistency"],
  },
  {
    key: "geo",
    label: "AI Analysis (GEO)",
    short: "AI / GEO",
    icon: "auto_awesome",
    color: SERIES.c5,
    paid: true,
    blurb: "How ready the site is for AI answers.",
    checks: ["AI-overview readiness", "Entity coverage", "Answerable content", "llms.txt & AI crawlers", "Citation-worthiness"],
  },
  {
    key: "strategy",
    label: "Strategy",
    short: "Strategy",
    icon: "flag",
    color: "#B18CFF",
    paid: true,
    blurb: "SERP-driven recommendation & sprint plan.",
    checks: ["Competitor benchmark", "Recommended strategy", "Quick wins", "Sprint roadmap", "Priority moves"],
  },
];

// Phase-2, shown as a locked "coming soon" card.
export const financialAudit = {
  label: "Financial audit",
  icon: "payments",
  blurb: "Market capacity & revenue estimate — quantifies the upside behind every fix.",
  checks: ["Market capacity", "Revenue estimate", "Opportunity sizing", "Competitor share"],
};

export const TYPE_LABEL: Record<AuditTypeKey, string> = {
  onpage: "On-Page",
  offpage: "Off-Page",
  technical: "Technical",
  local: "Local SEO",
  geo: "AI / GEO",
  strategy: "Strategy",
};

export type AuditRow = {
  id: string;
  client: string;
  url: string;
  types: AuditTypeKey[];
  tier: Tier;
  status: JobStatus;
  // null on runs created before the depth axis existed (migration 0084). That is
  // "breadth unknown", NOT "free" — those runs took their page budget from a
  // process-wide setting that no row recorded. Render it as unknown, never as a
  // default, or the table will assert a fact the database does not hold.
  depth: AuditDepth | null;
  maxPages: number | null; // the --max-pages ceiling this run was given
  estimatedCost: number | null; // USD quoted pre-flight; compare against the bill
  // The committed USD cost, runtime-derived from the engine's observables. null
  // until the engine actually started — "not yet spent", not "free". The column
  // defaults to 0, so rendering it for a queued row would show $0.00 for work
  // that simply has not happened.
  cost: number | null;
  score: number | null; // 0–100 composite site score; null while pending
  runtime: string; // wall-clock turnaround, or "—" while pending
  when: string; // display timestamp
  pdf: boolean;
  json: boolean;
};

// The three depths an operator can pick, with what each one buys. `pages` is
// indicative for the picker only — the authoritative budget comes back from
// POST /audits/estimate, which reads the server's live settings. Never price a
// run from these numbers.
export type AuditDepthOption = {
  key: AuditDepth;
  label: string;
  blurb: string;
  paidOnly: boolean;
  confirms: boolean; // requires confirming a cost estimate before it runs
};

export const auditDepths: AuditDepthOption[] = [
  {
    key: "free",
    label: "Free",
    blurb: "Condensed lead-magnet crawl. Zero paid providers, enforced at the engine.",
    paidOnly: false,
    confirms: false,
  },
  {
    key: "standard",
    label: "Standard",
    blurb: "The routine client check-in — a macro health read across the main pages.",
    paidOnly: true,
    confirms: false,
  },
  {
    key: "deep",
    label: "Deep",
    blurb: "The full consulting run across the site. Costed and confirmed before it starts.",
    paidOnly: true,
    confirms: true,
  },
];

// Existing agency clients (for the "Run new audit" picker).
export const clientNames: string[] = [
  "NorthPeak Dental", "Lumen Realty", "Verde Cafe", "Atlas Legal",
  "BrightHVAC", "Coastline Fit", "Meridian Wealth", "Orchard Pediatrics",
];

// KPI headline figures for the super-admin view.
export const auditStats = {
  thisMonth: 128,
  avgScore: 76,
  runningNow: 1,
  turnaroundMin: 6,
};
