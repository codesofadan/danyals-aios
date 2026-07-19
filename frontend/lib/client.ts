// ============================================================
// AIOS · Client Dashboard data layer
// The client-facing portal is a THIRD, fully separate experience
// (alongside the admin dashboard and the team portal). A client
// only ever sees the reports/graphs the admin granted them via
// clientReportGrants[clientId] (set in the Add-Client wizard).
//
// Every grantable report from lib/data.ts (clientReports) maps to
// a concrete visualization here (REPORT_VIZ). A report the admin
// did NOT grant stays LOCKED on the dashboard — grayed out behind
// a padlock, and its data is never surfaced. A granted report is
// UNLOCKABLE: the client pops the padlock, a green unlock animation
// plays, and the real chart data draws in.
//
// Mock values are demo-only — swap these arrays for the
// FastAPI / Postgres row-level-security responses when the backend
// is wired. Shapes intentionally mirror the admin modules so the
// same rows can be reused verbatim.
// ============================================================

import {
  SERIES, REPORT_GROUP_COLOR, clientReports, traffic,
  type ClientReport,
} from "@/lib/data";
import { projects, type ClientProject } from "@/lib/milestones";

// --- Visualization kinds a report card can render ---------------------------
export type VizKind = "area" | "bars" | "gauge" | "progress" | "stat";

export type GaugeDatum = { label: string; value: number; unit: string; max: number; good: number };
export type StatDatum = { label: string; value: string; delta?: string; up?: boolean };

export type ReportViz = {
  kind: VizKind;
  headline: string; // the big number shown once unlocked
  unit?: string; // suffix for the headline
  caption: string; // one-line read-out under the headline
  delta?: string; // e.g. "+12.4%"
  up?: boolean; // delta direction (true = good/green)
  labels?: string[]; // x labels for area/bars
  points?: number[]; // series for area / bars
  gauges?: GaugeDatum[]; // for kind = "gauge"
  progress?: number; // 0..100 for kind = "progress"
  stats?: StatDatum[]; // for kind = "stat"
};

const MONTHS = ["Aug", "Sep", "Oct", "Nov", "Dec", "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul"];

// One visualization per grantable report key (clientReports.key).
// The client dashboard renders exactly these, gated by the padlock.
export const REPORT_VIZ: Record<string, ReportViz> = {
  audit_scores: {
    kind: "area", headline: "94", unit: "/100", caption: "Overall site-health score, trended monthly",
    delta: "+11 pts", up: true, labels: MONTHS,
    points: [71, 74, 73, 78, 80, 83, 82, 86, 88, 90, 92, 94],
  },
  rank_tracker: {
    kind: "area", headline: "148", caption: "Tracked keywords ranking in the top 10",
    delta: "+37", up: true, labels: MONTHS,
    points: [63, 71, 79, 84, 91, 98, 104, 112, 121, 130, 139, 148],
  },
  traffic: {
    kind: "area", headline: "318K", caption: "Organic sessions this month across your site",
    delta: "+9.4%", up: true, labels: traffic.map((t) => t.m),
    points: traffic.map((t) => t.v),
  },
  core_web_vitals: {
    kind: "gauge", headline: "Passing", caption: "Core Web Vitals field data (last 28 days)",
    delta: "All green", up: true,
    gauges: [
      { label: "LCP", value: 2.1, unit: "s", max: 4, good: 2.5 },
      { label: "INP", value: 142, unit: "ms", max: 500, good: 200 },
      { label: "CLS", value: 0.06, unit: "", max: 0.25, good: 0.1 },
    ],
  },
  backlinks: {
    kind: "bars", headline: "1,284", caption: "Referring domains — new links won each month",
    delta: "+64 this mo", up: true, labels: MONTHS,
    points: [22, 31, 28, 40, 37, 45, 52, 48, 57, 61, 58, 64],
  },
  competitor: {
    kind: "bars", headline: "34%", caption: "Your share-of-voice vs the tracked competitor set",
    delta: "+6 pts", up: true, labels: ["You", "Rival A", "Rival B", "Rival C", "Rival D"],
    points: [34, 27, 19, 12, 8],
  },
  local_seo: {
    kind: "area", headline: "88%", caption: "Map-pack visibility across the local search grid",
    delta: "+14 pts", up: true, labels: MONTHS,
    points: [58, 61, 64, 67, 69, 72, 74, 77, 80, 83, 86, 88],
  },
  content_status: {
    kind: "bars", headline: "42", caption: "Pieces published — pipeline output per month",
    delta: "+5 live", up: true, labels: MONTHS,
    points: [2, 3, 3, 4, 4, 5, 4, 5, 6, 5, 6, 5],
  },
  keyword_map: {
    kind: "area", headline: "612", caption: "Target keywords mapped & ranking across your pages",
    delta: "+48", up: true, labels: MONTHS,
    points: [420, 448, 470, 495, 512, 534, 551, 566, 578, 592, 601, 612],
  },
  milestones: {
    kind: "stat", headline: "On-track", caption: "Where your engagement stands right now",
    stats: [
      { label: "Stages complete", value: "3 / 5" },
      { label: "Current stage", value: "Content" },
      { label: "Health", value: "On-track", up: true },
    ],
  },
  progress_dashboard: {
    kind: "progress", headline: "68%", caption: "Overall engagement completion", progress: 68,
    delta: "+8% this mo", up: true,
  },
  monthly_report: {
    kind: "stat", headline: "Ready", caption: "Your latest branded monthly SEO report",
    stats: [
      { label: "Traffic", value: "+9.4%", up: true },
      { label: "Rankings", value: "+37", up: true },
      { label: "Conversions", value: "+21%", up: true },
    ],
  },
  roi_summary: {
    kind: "area", headline: "$48.2K", caption: "Revenue attributed to organic search this month",
    delta: "5.8× ROI", up: true, labels: MONTHS,
    points: [18, 21, 24, 27, 29, 33, 36, 38, 41, 44, 46, 48],
  },
};

// The color a report card is skinned with (once unlocked) — inherited
// from its admin group so the client + admin views stay consistent.
export function reportColor(r: ClientReport): string {
  return REPORT_GROUP_COLOR[r.group];
}

// The full ordered list of report surfaces, each paired with its viz.
// The dashboard walks this and decides locked/unlocked per client grant.
export type DashboardReport = ClientReport & { viz: ReportViz };
// Neutral placeholder ONLY — the real visualization is sent by the backend
// (useClientReports → ClientContext.reportViz). We never fall back to fabricated
// chart numbers: an un-backed report card shows "—" (no current data).
export const dashboardReports: DashboardReport[] = clientReports.map((r) => ({
  ...r,
  viz: { kind: "stat", headline: "—", caption: r.desc, stats: [{ label: r.short, value: "—" }] },
}));

// --- Milestone timeline for a client ---------------------------------------
// The client sees the SAME milestone stages the admin manages — matched
// from the milestones module by client name.
export function projectForClient(clientName: string): ClientProject | undefined {
  return projects.find((p) => p.client === clientName);
}

// --- Client-facing report library (the Reports section) ---------------------
// Deliverables the client can open / download — audits and rollups.
export type ClientDeliverable = {
  id: string;
  title: string;
  kind: "Audit" | "Monthly" | "Content" | "Backlinks" | "Local";
  icon: string;
  period: string; // human period this report covers
  date: string; // issued date
  size: string; // file size label
  status: "ready" | "generating";
  // Which grant key must be held for this deliverable to be visible.
  requires: string;
};

export const clientDeliverables: ClientDeliverable[] = [
  { id: "rp-audit-07", title: "Technical SEO Audit", kind: "Audit", icon: "fact_check", period: "July 2026", date: "Jul 3, 2026", size: "2.4 MB", status: "ready", requires: "audit_scores" },
  { id: "rp-monthly-06", title: "Monthly SEO Report", kind: "Monthly", icon: "summarize", period: "June 2026", date: "Jul 1, 2026", size: "1.8 MB", status: "ready", requires: "monthly_report" },
  { id: "rp-monthly-05", title: "Monthly SEO Report", kind: "Monthly", icon: "summarize", period: "May 2026", date: "Jun 1, 2026", size: "1.7 MB", status: "ready", requires: "monthly_report" },
  { id: "rp-content-q2", title: "Content Performance", kind: "Content", icon: "article", period: "Q2 2026", date: "Jun 28, 2026", size: "980 KB", status: "ready", requires: "content_status" },
  { id: "rp-backlinks-06", title: "Backlink Profile", kind: "Backlinks", icon: "hub", period: "June 2026", date: "Jun 30, 2026", size: "1.1 MB", status: "ready", requires: "backlinks" },
  { id: "rp-local-06", title: "Local & Map Pack", kind: "Local", icon: "storefront", period: "June 2026", date: "Jun 29, 2026", size: "820 KB", status: "ready", requires: "local_seo" },
  { id: "rp-monthly-07", title: "Monthly SEO Report", kind: "Monthly", icon: "summarize", period: "July 2026", date: "In progress", size: "—", status: "generating", requires: "monthly_report" },
];

export const DELIVERABLE_COLOR: Record<ClientDeliverable["kind"], string> = {
  Audit: SERIES.c4, Monthly: SERIES.c1, Content: SERIES.c3, Backlinks: SERIES.c5, Local: SERIES.c2,
};

// --- Requests (client → admin) ---------------------------------------------
export type RequestKind = "Report" | "Access" | "Support" | "Feature" | "Billing";
export type RequestStatus = "open" | "in_review" | "resolved";

export const REQUEST_KINDS: { key: RequestKind; label: string; icon: string; c: string }[] = [
  { key: "Report", label: "New report", icon: "summarize", c: SERIES.c1 },
  { key: "Access", label: "Unlock a graph", icon: "lock_open", c: SERIES.c4 },
  { key: "Support", label: "Support / issue", icon: "support_agent", c: SERIES.c3 },
  { key: "Feature", label: "New feature", icon: "auto_awesome", c: SERIES.c2 },
  { key: "Billing", label: "Billing", icon: "receipt_long", c: SERIES.c5 },
];

export const REQUEST_STATUS_META: Record<RequestStatus, { label: string; cls: string; icon: string }> = {
  open: { label: "Open", cls: "info", icon: "schedule" },
  in_review: { label: "In review", cls: "warn", icon: "hourglass_top" },
  resolved: { label: "Resolved", cls: "ok", icon: "check_circle" },
};

export type ClientRequest = {
  id: string;
  kind: RequestKind;
  subject: string;
  detail: string;
  status: RequestStatus;
  ago: string;
  reply?: string; // latest admin reply, if any
};

// Seeded so a fresh portal isn't empty — the client's own past requests.
export const seedRequests: ClientRequest[] = [
  {
    id: "req-3012", kind: "Access", subject: "Please unlock the Backlink Profile graph",
    detail: "We'd love to see referring-domain growth alongside rankings.",
    status: "in_review", ago: "2h ago",
    reply: "On it — we're validating your Ahrefs connection before switching it on.",
  },
  {
    id: "req-3007", kind: "Report", subject: "Add a quarterly executive summary",
    detail: "A one-pager we can forward to the leadership team each quarter.",
    status: "open", ago: "1d ago",
  },
  {
    id: "req-2990", kind: "Support", subject: "Audit PDF wouldn't open on the second site",
    detail: "The July audit export returned a blank page for our clinic location.",
    status: "resolved", ago: "4d ago",
    reply: "Fixed — the export now renders both sites. Re-download from Reports.",
  },
];

let reqSeq = 3013;
export function nextRequestId(): string {
  return `req-${reqSeq++}`;
}
