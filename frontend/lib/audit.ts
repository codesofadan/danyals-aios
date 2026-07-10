// ============================================================
// AIOS · Audit module data layer
// Grounded in the platform docs — Module 01 (Audit):
//   • The audit engine runs on a URL alone (no logins) as an
//     async job. Every audit is Free or Paid tier — tier decides
//     which paid data sources run behind a cost gate.
//   • Coverage: Technical, Actionable, Local & GBP, AI/GEO, and
//     Backlink & citation. Financial audit is Phase-2 (locked).
//   • Outputs: 20–30+ page house-styled PDF + JSON + numeric
//     scores, a live web version, stored to the client's Google
//     Sheet; on completion the milestone auto-advances + notify.
//   • Job states: queued → running → done (plus failed/retry).
// Swap these mocks for the FastAPI /audits endpoints later.
// ============================================================

import { SERIES } from "@/lib/data";

export type Tier = "Free" | "Paid";
export type JobStatus = "queued" | "running" | "done" | "failed";
export type AuditTypeKey = "technical" | "actionable" | "local" | "geo" | "backlink";

export type AuditType = {
  key: AuditTypeKey;
  label: string;
  short: string;
  icon: string;
  color: string;
  paid: boolean; // relies on a paid data source (gated on Free tier)
  blurb: string;
  checks: string[];
};

// The five live audit types + what each one checks.
export const auditTypes: AuditType[] = [
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
    key: "actionable",
    label: "Actionable audit",
    short: "Actionable",
    icon: "checklist",
    color: SERIES.c1,
    paid: false,
    blurb: "Per-page fixes the team can ship today.",
    checks: ["Titles & meta", "Heading structure", "NAP consistency", "Internal links", "Thin / duplicate content"],
  },
  {
    key: "local",
    label: "Local & GBP signals",
    short: "Local & GBP",
    icon: "location_on",
    color: SERIES.c3,
    paid: true,
    blurb: "Map-pack readiness from Google data.",
    checks: ["Map-pack presence", "GBP categories", "NAP from Google Places", "Reviews & ratings", "Business Profile completeness"],
  },
  {
    key: "geo",
    label: "AI / GEO signals",
    short: "AI / GEO",
    icon: "auto_awesome",
    color: SERIES.c5,
    paid: true,
    blurb: "How ready the site is for AI answers.",
    checks: ["AI-overview readiness", "Entity coverage", "Structured data", "Answerable content", "Citation-worthiness"],
  },
  {
    key: "backlink",
    label: "Backlink & citation audit",
    short: "Backlink",
    icon: "hub",
    color: SERIES.c2,
    paid: true,
    blurb: "Off-site authority and listing health.",
    checks: ["Profile strength", "Toxic links", "Referring domains", "Citation consistency", "Listing accuracy"],
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
  technical: "Technical",
  actionable: "Actionable",
  local: "Local & GBP",
  geo: "AI / GEO",
  backlink: "Backlink",
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
    types: ["technical", "actionable", "local"], tier: "Paid", status: "done",
    score: 82, runtime: "6m 12s", when: "Today · 09:14", pdf: true, json: true,
  },
  {
    id: "aud-2040", client: "Lumen Realty", url: "lumenrealty.com",
    types: ["technical", "geo"], tier: "Paid", status: "running",
    score: null, runtime: "—", when: "Today · 09:02", pdf: false, json: false,
  },
  {
    id: "aud-2039", client: "BrightHVAC", url: "brighthvac.io",
    types: ["technical", "actionable"], tier: "Free", status: "done",
    score: 74, runtime: "4m 48s", when: "Today · 08:37", pdf: true, json: true,
  },
  {
    id: "aud-2038", client: "Verde Cafe", url: "verdecafe.co",
    types: ["local", "backlink"], tier: "Paid", status: "queued",
    score: null, runtime: "—", when: "Today · 08:31", pdf: false, json: false,
  },
  {
    id: "aud-2037", client: "Atlas Legal", url: "atlaslegal.com",
    types: ["technical", "actionable", "geo", "backlink"], tier: "Paid", status: "done",
    score: 91, runtime: "7m 55s", when: "Yesterday · 17:20", pdf: true, json: true,
  },
  {
    id: "aud-2036", client: "Coastline Fit", url: "coastlinefit.com",
    types: ["technical"], tier: "Free", status: "failed",
    score: null, runtime: "1m 06s", when: "Yesterday · 15:44", pdf: false, json: false,
  },
  {
    id: "aud-2035", client: "Meridian Wealth", url: "meridianwealth.com",
    types: ["technical", "geo", "backlink"], tier: "Paid", status: "done",
    score: 68, runtime: "8m 21s", when: "Yesterday · 14:02", pdf: true, json: true,
  },
  {
    id: "aud-2034", client: "Orchard Pediatrics", url: "orchardpeds.com",
    types: ["actionable", "local"], tier: "Free", status: "done",
    score: 79, runtime: "5m 33s", when: "Yesterday · 11:48", pdf: true, json: true,
  },
  {
    id: "aud-2033", client: "NorthPeak Dental", url: "northpeakdental.com/blog",
    types: ["actionable"], tier: "Free", status: "done",
    score: 63, runtime: "3m 27s", when: "Jul 08 · 16:10", pdf: true, json: true,
  },
  {
    id: "aud-2032", client: "BrightHVAC", url: "brighthvac.io/service-areas",
    types: ["technical", "local", "backlink"], tier: "Paid", status: "done",
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
