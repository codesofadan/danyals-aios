"use client";

// ============================================================
// AIOS · audit data hooks (the first real read-swap slice)
// Backs the AuditWorkspace off the FastAPI /audits endpoints instead of the
// build-time `audits` seed. AuditRow ↔ AuditResponse is contract-locked 11/11,
// so the JSON drops straight into the existing type — no field mapping.
// ============================================================

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type { AuditDepth, AuditRow, Tier } from "@/lib/audit";

export const AUDITS_KEY = ["audits"] as const;
export const AUDIT_STATS_KEY = ["audits", "stats"] as const;

// Matches AuditStatsResponse (serialized: thisMonth/avgScore/runningNow/turnaroundMin).
export type AuditStats = {
  thisMonth: number;
  avgScore: number;
  runningNow: number;
  turnaroundMin: number;
  // Added for the operator dashboard. `avgScore` and `turnaroundMin` are kept in
  // the type because the API still serves them (the aios-audit skill reads them)
  // even though the KPI strip no longer renders them.
  lifetime: number;
  avgCostUsd: number;
};

const isPending = (r: AuditRow) => r.status === "queued" || r.status === "running";

//: The server caps a page at 200 and defaults to 50. Asking for the maximum in
//: one request keeps the polling cheap while covering most agencies' history in
//: a single call; anything beyond it is fetched by raising `pages`.
export const AUDITS_PAGE = 200;

/** The audit list. Polls every 2.5s WHILE any job is in flight, then stops.
 *
 * `pages` fetches N server pages and concatenates them. The list used to take
 * the server default of 50 with no way to ask for more, so an agency past its
 * first fifty audits had older runs that no screen could reach - and the
 * filters and search silently operated on that window, so "failed" could render
 * as "no failures".
 */
export function useAudits(pages = 1) {
  const wanted = Math.max(1, pages);
  return useQuery({
    queryKey: [...AUDITS_KEY, wanted],
    queryFn: async () => {
      const out: AuditRow[] = [];
      for (let i = 0; i < wanted; i += 1) {
        const batch = await api.get<AuditRow[]>(
          `/audits?limit=${AUDITS_PAGE}&offset=${i * AUDITS_PAGE}`,
        );
        out.push(...batch);
        // A short page is the last page. Asking for the next one would be a
        // wasted round trip on every poll.
        if (batch.length < AUDITS_PAGE) break;
      }
      return out;
    },
    refetchInterval: (query) => {
      const rows = query.state.data as AuditRow[] | undefined;
      return rows?.some(isPending) ? 2500 : false;
    },
  });
}

/** ONE audit, by id.
 *
 * The detail page used to find its header row inside `useAudits()`, which the
 * server caps at 50 rows ordered newest-first - so any audit outside that
 * window opened with the coded fallback title and a raw UUID.
 */
export function useAudit(auditId: string) {
  return useQuery({
    queryKey: [...AUDITS_KEY, auditId],
    queryFn: () => api.get<AuditRow>(`/audits/${auditId}`),
    enabled: Boolean(auditId),
  });
}

export function useAuditStats() {
  return useQuery({
    queryKey: AUDIT_STATS_KEY,
    queryFn: () => api.get<AuditStats>("/audits/stats"),
  });
}

export type CreateAuditInput = {
  client_id: string;
  url: string;
  tier: Tier;
  // NO `types`. Depth is the only scope axis: every audit covers every dimension,
  // and depth decides how much paid corroboration it buys. The picker that used to
  // live here promised per-dimension scoping the engine cannot do.
  depth?: AuditDepth;
  // Does the client see this run in their own portal? Server default is FALSE.
  // Before migration 0096 there was no such choice - every client-linked audit
  // appeared in that client's portal the moment it was created.
  visible_to_client?: boolean;
  // The page budget the quote was issued for, echoed back so the run reproduces
  // the price it was quoted without the server re-probing the site. Bounded
  // server-side by the depth's ceiling, so it can only ever narrow the run.
  max_pages?: number;
  // The figure from useAuditEstimate, echoed back. Required by the server for a
  // depth whose quote said `confirmationRequired`; a stale figure is refused with
  // 409 rather than charged, so always re-quote before resubmitting.
  confirmed_estimate?: number;
};

// Mirrors AuditEstimateResponse. `pages` and `agents` are the two variables that
// move the price and are shown alongside it: an operator approving a spend is
// approving a judgement, and a bare dollar figure cannot be reviewed.
export type AuditEstimate = {
  tier: Tier;
  depth: AuditDepth;
  pages: number; // the budget this quote is priced for — echo back as max_pages
  agents: boolean;
  estimatedCost: number;
  confirmationRequired: boolean;
  // What the site's own sitemap reported, or null for "could not tell". null is
  // NOT zero — `pages` then falls back to the depth's ceiling, and showing the
  // null is what lets an operator see that rather than wonder why it is round.
  measuredPages: number | null;
  sizeSource: "robots_sitemap" | "sitemap" | "sitemap_index" | "unknown";
  sizeTruncated: boolean; // measuredPages is a floor on the real total
};

export type AuditEstimateInput = {
  tier: Tier;
  depth?: AuditDepth;
  // Only consulted for a depth that scales to site size (deep). Given it, the
  // quote measures the site's sitemap and prices the run it would actually make.
  url?: string;
};

/**
 * Quote a run before creating it. Spends nothing and creates nothing — it prices
 * the request against the server's live unit costs. A mutation rather than a
 * query because it is a deliberate operator action, and because caching a price
 * is exactly how a confirmation ends up bound to a figure that has since moved.
 */
export function useAuditEstimate() {
  return useMutation({
    mutationFn: (input: AuditEstimateInput) =>
      api.post<AuditEstimate>("/audits/estimate", input),
  });
}

/**
 * Enqueue a new audit. `retry: 0` (inherited from the client's mutation default)
 * so a transient failure never silently doubles a Paid run's spend. On success the
 * list + stats refetch and the new `queued` row appears, then polls to completion.
 */
export function useCreateAudit() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (input: CreateAuditInput) => api.post<AuditRow>("/audits", input),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: AUDITS_KEY });
      void qc.invalidateQueries({ queryKey: AUDIT_STATS_KEY });
    },
  });
}

/**
 * Share an audit into the client's portal, or stop sharing it.
 *
 * Sharing used to be write-once: chosen when the audit was created, absent from
 * every response, and impossible to change afterwards. An operator could put a
 * run in front of a client and then had no way to see that they had. Migration
 * 0096 additionally backfilled `true` for every audit that already had a client,
 * so what is shared today is historical rather than chosen — which only becomes
 * reviewable once it is both readable and reversible.
 *
 * A 404 here means the update matched no row. That is NOT only "no such audit":
 * the `audits_modify` policy is scoped to operator roles and an RLS refusal
 * matches zero rows rather than raising, so a refused write arrives as a 404
 * instead of being reported as a successful share.
 */
export function useSetAuditVisibility() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, visible }: { id: string; visible: boolean }) =>
      api.patch<AuditRow>(`/audits/${id}/visibility`, { visible_to_client: visible }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: AUDITS_KEY });
    },
  });
}
