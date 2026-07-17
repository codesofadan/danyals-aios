"use client";

// ============================================================
// AIOS · client-portal data hooks
// Backs the client portal off the FastAPI /portal/* endpoints instead of the
// build-time seed. A signed-in client is RLS-scoped by its bearer token, so
// every read here returns ONLY the caller's own tenant — there is no client_id
// in any path or body (the server pins it). Response shapes are contract-locked
// to lib/client.ts / lib/milestones.ts, so the JSON drops into the existing
// types with no field mapping.
// ============================================================

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type { ClientDeliverable, ClientRequest, ReportViz, RequestKind } from "@/lib/client";
import type { ClientProject } from "@/lib/milestones";

export const PORTAL_DASHBOARD_KEY = ["portal", "dashboard"] as const;
export const PORTAL_REPORTS_KEY = ["portal", "reports"] as const;
export const PORTAL_DELIVERABLES_KEY = ["portal", "deliverables"] as const;
export const PORTAL_MILESTONES_KEY = ["portal", "milestones"] as const;
export const PORTAL_REQUESTS_KEY = ["portal", "requests"] as const;

// GET /portal/dashboard → ClientDashboard (serialized aliases: deliveryTier /
// latestScore / latestAuditWhen / totalAudits). Carries the client's OWN name,
// delivery tier, sites and headline audit figures — nothing agency-internal.
export type ClientDashboardResponse = {
  client: string; // the client's own name
  deliveryTier: string; // free | semi | fully
  latestScore: number | null;
  latestAuditWhen: string;
  totalAudits: number;
  sites: { id: string; domain: string }[];
};

// GET /portal/reports → the GRANTED report surfaces ONLY (ungranted keys are
// never returned). `viz` mirrors ReportViz byte-for-byte; `placeholder` flags
// representative (not-yet-live) sample data.
export type PortalReport = { key: string; viz: ReportViz; placeholder: boolean };

/** The signed-in client's landing summary (identity + tier + sites + scores). */
export function useClientDashboard() {
  return useQuery({
    queryKey: PORTAL_DASHBOARD_KEY,
    queryFn: () => api.get<ClientDashboardResponse>("/portal/dashboard"),
  });
}

/** The report surfaces the admin granted this client, each with its live viz. */
export function useClientReports() {
  return useQuery({
    queryKey: PORTAL_REPORTS_KEY,
    queryFn: () => api.get<PortalReport[]>("/portal/reports"),
  });
}

/** The client's granted, visible deliverables (newest issued first). */
export function useClientDeliverables() {
  return useQuery({
    queryKey: PORTAL_DELIVERABLES_KEY,
    queryFn: () => api.get<ClientDeliverable[]>("/portal/deliverables"),
  });
}

/**
 * The client's engagement timeline (its ClientProject + 5 lifecycle stages).
 * A client with no project yet gets a 404 — a terminal 4xx (no retry) that the
 * caller renders as its "no milestones" empty state.
 */
export function useClientMilestones() {
  return useQuery({
    queryKey: PORTAL_MILESTONES_KEY,
    queryFn: () => api.get<ClientProject>("/portal/milestones"),
  });
}

/** The client's own requests (newest first). */
export function useClientRequests() {
  return useQuery({
    queryKey: PORTAL_REQUESTS_KEY,
    queryFn: () => api.get<ClientRequest[]>("/portal/requests"),
  });
}

export type CreateRequestInput = { kind: RequestKind; subject: string; detail: string };

/**
 * Raise a request. `client_id` is pinned server-side (never in the body).
 * `retry: 0` (the client's mutation default) so a transient failure never
 * silently doubles a request; on success the request list refetches.
 */
export function useCreateRequest() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (input: CreateRequestInput) => api.post<ClientRequest>("/portal/requests", input),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: PORTAL_REQUESTS_KEY });
    },
  });
}
