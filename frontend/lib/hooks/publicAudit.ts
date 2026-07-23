"use client";

// ============================================================
// AIOS · public free-audit hooks (the unauthenticated funnel)
// Backs /free-audit off the REAL FastAPI public endpoints
// (app/routers/public.py) instead of the old client-side PRNG report.
// These are the platform's ONLY unauthenticated calls — `api.*` sends
// no bearer token (none is needed; the endpoint is public and the
// opaque `report_token` IS the capability that grants read of one report).
//   • useCreatePublicAudit — POST /public/audits {email,url,types?} →
//     {report_token,status}. 409 = "one free audit per email" already used;
//     400 = a paid audit type or a non-public URL. Both carry a human
//     reason on ApiError.message.
//   • usePublicReport(token) — GET /public/audits/{token}; polls every
//     2.5s WHILE queued/running, then stops (mirrors hooks/audits.ts).
// ============================================================

import { useMutation, useQuery } from "@tanstack/react-query";
import { api, FILE_BASE } from "@/lib/api";
import type { AuditTypeKey } from "@/lib/audit";

// 201 response from POST /public/audits (the capability token + initial status).
export type PublicAuditCreated = { report_token: string; status: string };

export type PublicStatus = "queued" | "running" | "done" | "failed";

// The CURATED public report — mirrors `PublicReport` in app/routers/public.py.
// Deliberately THIN: an overall score, a per-category `scores` map, the status
// lifecycle, artifact flags, and the Fiverr upsell link. No internal id / email
// / error / paths, and no fabricated per-check detail.
export type PublicReport = {
  status: PublicStatus;
  score: number | null;
  scores: Record<string, unknown>;
  has_pdf: boolean;
  has_report: boolean;
  url: string;
  when: string | null;
  fiverr_url: string;
};

export type CreatePublicAuditInput = {
  email: string;
  url: string;
  types?: AuditTypeKey[];
};

const publicAuditKey = (token: string) => ["public-audit", token] as const;

// The PDF href uses FILE_BASE (lib/api.ts): the multi-MB report must stream
// straight from the API origin, not crawl through the Next rewrite proxy. A
// plain browser GET, not an api.* fetch — the token in the path is the guard.

/** Direct-download URL for the report PDF (only meaningful when `has_pdf`). */
export function publicReportPdfUrl(token: string): string {
  return `${FILE_BASE}/public/audits/${encodeURIComponent(token)}/report.pdf`;
}

/** Direct URL for the self-contained report.html the in-page viewer renders. */
export function publicReportHtmlUrl(token: string): string {
  return `${FILE_BASE}/public/audits/${encodeURIComponent(token)}/report.html`;
}

/**
 * Fetch the condensed free report.html for a token (unauthenticated — the token
 * in the path is the capability). Returns the HTML string the ReportViewer
 * renders; a 404 (no report yet) throws so the caller shows a fallback.
 */
export async function fetchPublicReportHtml(token: string): Promise<string> {
  const res = await fetch(publicReportHtmlUrl(token));
  if (!res.ok) throw new Error(`report unavailable (${res.status})`);
  return res.text();
}

const isPending = (r: PublicReport | undefined) => r?.status === "queued" || r?.status === "running";

/**
 * Enqueue ONE free audit for an email. `retry: 0` (inherited from the client's
 * mutation default) so a transient failure never silently creates a second lead
 * row. 409/400 surface as an ApiError whose `.status` + `.message` the caller
 * renders as a first-class state.
 */
export function useCreatePublicAudit() {
  return useMutation<PublicAuditCreated, unknown, CreatePublicAuditInput>({
    mutationFn: (input) => api.post<PublicAuditCreated>("/public/audits", input),
  });
}

/**
 * Poll the curated report for a token. Disabled until a token exists; polls
 * every 2.5s WHILE the job is queued/running, then stops on done/failed.
 */
export function usePublicReport(token: string | null) {
  return useQuery({
    queryKey: token ? publicAuditKey(token) : (["public-audit", "idle"] as const),
    queryFn: () => api.get<PublicReport>(`/public/audits/${token}`),
    enabled: !!token,
    refetchInterval: (query) => (isPending(query.state.data as PublicReport | undefined) ? 2500 : false),
  });
}
