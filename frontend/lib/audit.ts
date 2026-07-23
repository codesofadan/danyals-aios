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
  score: number | null; // 0–100 composite site score; null while pending
  runtime: string; // wall-clock turnaround, or "—" while pending
  when: string; // display timestamp
  pdf: boolean;
  json: boolean;
};

// Newest first. Varied types / tiers / statuses / scores.
export const audits: AuditRow[] = [
  {
    id: "aud-2041", client: "NorthPeak Dental", url: "northpeakdental.com",
    types: ["technical", "onpage", "local"], tier: "Paid", status: "done",
    score: 82, runtime: "6m 12s", when: "Today · 09:14", pdf: true, json: true,
  },
  {
    id: "aud-2040", client: "Lumen Realty", url: "lumenrealty.com",
    types: ["technical", "geo"], tier: "Paid", status: "running",
    score: null, runtime: "—", when: "Today · 09:02", pdf: false, json: false,
  },
  {
    id: "aud-2039", client: "BrightHVAC", url: "brighthvac.io",
    types: ["technical", "onpage"], tier: "Free", status: "done",
    score: 74, runtime: "4m 48s", when: "Today · 08:37", pdf: true, json: true,
  },
  {
    id: "aud-2038", client: "Verde Cafe", url: "verdecafe.co",
    types: ["local", "offpage"], tier: "Paid", status: "queued",
    score: null, runtime: "—", when: "Today · 08:31", pdf: false, json: false,
  },
  {
    id: "aud-2037", client: "Atlas Legal", url: "atlaslegal.com",
    types: ["technical", "onpage", "geo", "offpage"], tier: "Paid", status: "done",
    score: 91, runtime: "7m 55s", when: "Yesterday · 17:20", pdf: true, json: true,
  },
  {
    id: "aud-2036", client: "Coastline Fit", url: "coastlinefit.com",
    types: [], tier: "Free", status: "failed",
    score: null, runtime: "1m 06s", when: "Yesterday · 15:44", pdf: false, json: false,
  },
  {
    id: "aud-2035", client: "Meridian Wealth", url: "meridianwealth.com",
    types: ["technical", "geo", "offpage"], tier: "Paid", status: "done",
    score: 68, runtime: "8m 21s", when: "Yesterday · 14:02", pdf: true, json: true,
  },
  {
    id: "aud-2034", client: "Orchard Pediatrics", url: "orchardpeds.com",
    types: ["onpage", "local"], tier: "Free", status: "done",
    score: 79, runtime: "5m 33s", when: "Yesterday · 11:48", pdf: true, json: true,
  },
  {
    id: "aud-2033", client: "NorthPeak Dental", url: "northpeakdental.com/blog",
    types: ["onpage"], tier: "Free", status: "done",
    score: 63, runtime: "3m 27s", when: "Jul 08 · 16:10", pdf: true, json: true,
  },
  {
    id: "aud-2032", client: "BrightHVAC", url: "brighthvac.io/service-areas",
    types: ["technical", "local", "offpage"], tier: "Paid", status: "done",
    score: 71, runtime: "6m 40s", when: "Jul 08 · 10:25", pdf: true, json: true,
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
