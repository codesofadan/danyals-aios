"use client";

// ============================================================
// AIOS · free-audit LEADS hooks (the admin funnel inbox)
// Backs /admin/leads off the staff-only GET /admin/public-audits endpoint
// (app/routers/admin_public_audits.py). These are the landing-page free audits
// captured per email — write-only until now; this is the admin read surface.
// Mirrors PublicAuditLead in the backend router, field-for-field.
// ============================================================

import { useQuery } from "@tanstack/react-query";
import { ApiError, api } from "@/lib/api";

export type LeadStatus = "queued" | "running" | "done" | "failed";

export type PublicAuditLead = {
  id: string;
  email: string;
  url: string;
  status: LeadStatus;
  score: number | null;
  source: string;
  report_token: string;
  has_pdf: boolean;
  has_report: boolean;
  run_uuid: string | null;
  error: string | null;
  created_at: string;
  updated_at: string | null;
};

export const LEADS_KEY = ["leads"] as const;

const isPending = (r: PublicAuditLead | undefined) =>
  r?.status === "queued" || r?.status === "running";

/** The free-audit lead list. Polls every 5s WHILE any audit is still in flight. */
export function useLeads() {
  return useQuery({
    queryKey: LEADS_KEY,
    queryFn: () => api.get<PublicAuditLead[]>("/admin/public-audits"),
    refetchInterval: (query) => {
      const rows = query.state.data as PublicAuditLead[] | undefined;
      return rows?.some(isPending) ? 5000 : false;
    },
  });
}

export const LEAD_KEY = (token: string) => ["lead", token] as const;

/** ONE lead, by its report token.
 *
 *  The detail page used to find its lead by scanning `useLeads()` — the newest
 *  page of the funnel inbox — so a link to any older lead resolved to "no lead for
 *  this token" while its report sat on disk. A shared link rotted as the funnel
 *  filled. The token is the lead's identity, so it is read by the token. Polls on
 *  the same 5s cadence while the audit is still running.
 */
export function useLead(token: string) {
  return useQuery<PublicAuditLead | null>({
    queryKey: LEAD_KEY(token),
    queryFn: async () => {
      try {
        return await api.get<PublicAuditLead>(
          `/admin/public-audits/${encodeURIComponent(token)}`,
        );
      } catch (err) {
        // A token nobody has is a real answer, not a failure: resolve it to null so
        // the page can say "no lead for this token" instead of "couldn't load", the
        // way the portal surfaces do. Everything else still throws.
        if (err instanceof ApiError && err.status === 404) return null;
        throw err;
      }
    },
    refetchInterval: (query) =>
      isPending(query.state.data as PublicAuditLead | undefined) ? 5000 : false,
  });
}
