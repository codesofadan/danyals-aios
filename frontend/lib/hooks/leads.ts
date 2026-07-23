"use client";

// ============================================================
// AIOS · free-audit LEADS hooks (the admin funnel inbox)
// Backs /admin/leads off the staff-only GET /admin/public-audits endpoint
// (app/routers/admin_public_audits.py). These are the landing-page free audits
// captured per email — write-only until now; this is the admin read surface.
// Mirrors PublicAuditLead in the backend router, field-for-field.
// ============================================================

import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";

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

const isPending = (r: PublicAuditLead) => r.status === "queued" || r.status === "running";

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
