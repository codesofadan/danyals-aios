// ============================================================
// AIOS · Client Dashboard data layer
// The client-facing portal is a THIRD, fully separate experience
// (alongside the admin dashboard and the team portal). A client
// only ever sees the reports/graphs the admin granted them.
//
// This module is now backend-wired: the LIVE per-key visualization,
// deliverables and requests all arrive from the RLS-scoped /portal/*
// endpoints (see lib/hooks/portalClient.ts → ClientContext). What
// stays here is purely the static CATALOG + display metadata that
// never comes off the wire: the report card skin colors, the request
// kind/status chrome, and the neutral report catalog placeholder.
// No fabricated metrics live here anymore.
// ============================================================

import {
  SERIES, REPORT_GROUP_COLOR, clientReports,
  type ClientReport,
} from "@/lib/data";

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

// --- Client-facing report library (the Reports section) ---------------------
// Deliverables the client can open / download — audits and rollups. The live
// list arrives from GET /portal/deliverables (useClientDeliverables); only the
// TYPE + color metadata below is static.
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

// The client's own requests arrive from GET /portal/requests (useClientRequests).
export type ClientRequest = {
  id: string;
  kind: RequestKind;
  subject: string;
  detail: string;
  status: RequestStatus;
  ago: string;
  reply?: string; // latest admin reply, if any
};
