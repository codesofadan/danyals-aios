"use client";

// ============================================================
// AIOS · public report hooks (the shared-link surface)
// Backs /leads/<slug> off the public FastAPI endpoints in
// app/routers/public.py. These are the platform's ONLY unauthenticated
// calls — `api.*` sends no bearer token, and the slug IS the capability
// that grants read of one published report.
//
// `useCreatePublicAudit` and `usePublicReport(token)` used to live here too.
// They drove the self-serve funnel retired on 2026-09-17, whose POST
// /public/audits endpoint was removed with it — so the mutation had no server
// to call. They were kept only so the parked funnel components would still
// type-check; those were deleted on 2026-09-19, and these went with them.
// An audit is now run by an operator and SHARED by slug.
// ============================================================

import { useQuery } from "@tanstack/react-query";
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
  /** The readable /leads/<brand> page for this audit, or "" when none is published.
   *  The page was always created on completion; nothing ever showed it to the
   *  person who ran the audit, so the one shareable artifact had no route to its
   *  own owner. */
  publicSlug: string;
};

export type CreatePublicAuditInput = {
  email: string;
  url: string;
  types?: AuditTypeKey[];
};

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

/**
 * Enqueue ONE free audit for an email. `retry: 0` (inherited from the client's
 * mutation default) so a transient failure never silently creates a second lead
 * row. 409/400 surface as an ApiError whose `.status` + `.message` the caller
 * renders as a first-class state.
 */
// --------------------------------------------------------------------------
// Readable public pages: /leads/<slug>
// --------------------------------------------------------------------------
// The token helpers above are unchanged and every existing link still works.
// These address the SAME curated report by its readable slug, and they are the
// only public surface a paid audit has. FILE_BASE for the same reason as above:
// the report streams straight from the API origin rather than through the Next
// rewrite proxy.

/** One headline problem, as the public page shows it (no check ids, no evidence). */
export type PublicFinding = { title: string; severity: string; pages: number };

/** The curated payload behind a readable slug (free or paid, published only). */
export type PublicPage = {
  slug: string;
  kind: "free" | "paid";
  brand: string;
  url: string;
  status: string;
  score: number | null;
  scores: Record<string, unknown>;
  has_pdf: boolean;
  has_report: boolean;
  when: string | null;
  fiverr_url: string;
  /** The worst handful, most severe first. Empty when the run stored no findings. */
  top_findings?: PublicFinding[];
  /** What this run did NOT measure. Read by the page as "not checked", never "clean". */
  not_checked?: string[];
  /** Set when the crawl was thin or refused, so the score is read with that in mind. */
  crawl_note?: string;
};

export const publicPageKey = (slug: string) => ["public-page", slug] as const;

/** Direct URL for the report HTML behind a slug. */
export function publicPageReportHtmlUrl(slug: string): string {
  return `${FILE_BASE}/public/pages/${encodeURIComponent(slug)}/report.html`;
}

/** Direct-download URL for the report PDF behind a slug (only when `has_pdf`). */
export function publicPageReportPdfUrl(slug: string): string {
  return `${FILE_BASE}/public/pages/${encodeURIComponent(slug)}/report.pdf`;
}

/** Fetch the full consulting report HTML for a slug. Throws on 404 so the page
 *  can show a real "not found" rather than an empty viewer. */
export async function fetchPublicPageReportHtml(slug: string): Promise<string> {
  const res = await fetch(publicPageReportHtmlUrl(slug));
  if (!res.ok) throw new Error(`report unavailable (${res.status})`);
  return res.text();
}

/** Read the curated page payload. Not polled: a published page is already done. */
export function usePublicPage(slug: string) {
  return useQuery({
    queryKey: publicPageKey(slug),
    queryFn: () => api.get<PublicPage>(`/public/pages/${encodeURIComponent(slug)}`),
    retry: false,
  });
}
