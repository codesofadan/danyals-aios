"use client";

// ============================================================
// AIOS · off-page data hooks
// Backs the Off-page workspace (Backlinks / Citations / Web 2.0 + KPIs) off the
// FastAPI /offpage + /citation-builder endpoints. Backlink / Citation / Web2Property
// are contract-locked to their responses (camelCase aliases match), so the JSON
// drops straight into the existing types — no field mapping.
// ============================================================

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type {
  AuditPlan,
  Backlink,
  BusinessMarket,
  BusinessProfile,
  BusinessProfileInput,
  Citation,
  CitationAction,
  CitationCampaignInput,
  CitationCampaignResult,
  CitationEngineBoard,
  CitationGap,
  Directory,
  DirectoryTier,
  OffpageKpis,
  Web2Campaign,
  Web2CampaignApproval,
  Web2CampaignEstimate,
  Web2Placement,
  Web2CampaignInput,
  Web2PlatformStatusRow,
  Web2Property,
  Web2Status,
} from "@/lib/offpage";

export const BACKLINKS_KEY = ["offpage", "backlinks"] as const;
export const CITATIONS_KEY = ["offpage", "citations"] as const;
export const WEB2_KEY = ["offpage", "web2"] as const;
export const OFFPAGE_KPIS_KEY = ["offpage", "kpis"] as const;
export const BUSINESS_PROFILES_KEY = ["citation-builder", "business-profiles"] as const;
export const DIRECTORIES_KEY = ["citation-builder", "directories"] as const;

/** The referring-domain profile (freshest first). */
export function useBacklinks() {
  return useQuery({
    queryKey: BACKLINKS_KEY,
    queryFn: () => api.get<Backlink[]>("/offpage/backlinks"),
  });
}

/** The local directory / NAP listings (now carrying submission-pipeline fields too). */
export function useCitations() {
  return useQuery({
    queryKey: CITATIONS_KEY,
    queryFn: () => api.get<Citation[]>("/offpage/citations"),
  });
}

/** The Web 2.0 property ledger (newest-published first), incl. pipeline `status`. */
export function useWeb2() {
  return useQuery({
    queryKey: WEB2_KEY,
    queryFn: () => api.get<Web2Property[]>("/offpage/web2"),
    // needs_review rows move fast when a lead is actively approving; a short poll
    // keeps the queue fresh without the operator having to refresh by hand.
    refetchInterval: 15_000,
  });
}

/** The off-page summary tiles (live profile size + 30-day deltas + disavow queue). */
export function useOffpageKpis() {
  return useQuery({
    queryKey: OFFPAGE_KPIS_KEY,
    queryFn: () => api.get<OffpageKpis>("/offpage/kpis"),
  });
}

/**
 * Reconcile many NAP listings to `consistent` in one shot (a batch Submit/Update).
 * Lead-only at the backend. `retry: 0` (client default) so a transient failure never
 * silently double-submits. On success the citations list + KPIs refetch.
 */
export function useBulkUpdateCitations() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (ids: string[]) => api.post<Citation[]>("/offpage/citations/bulk", { ids }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: CITATIONS_KEY });
      void qc.invalidateQueries({ queryKey: OFFPAGE_KPIS_KEY });
    },
  });
}

/** Mark ONE listing handled (Submit a missing one / Update a drifted one). Lead-only. */
export function useActOnCitation() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, action }: { id: string; action: CitationAction }) =>
      api.post<Citation>(`/offpage/citations/${id}/action`, { action }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: CITATIONS_KEY });
      void qc.invalidateQueries({ queryKey: OFFPAGE_KPIS_KEY });
    },
  });
}

/** Flag every backlink at/above the spam threshold as toxic (disavow queue). Lead-only. */
export function useFlagToxicBacklinks() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (spamThreshold?: number) =>
      api.post<{ flagged: number }>("/offpage/backlinks/flag-toxic", {
        ...(spamThreshold !== undefined ? { spam_threshold: spamThreshold } : {}),
      }),
    onSuccess: () => void qc.invalidateQueries({ queryKey: BACKLINKS_KEY }),
  });
}

// --- 7B-4: business profiles (canonical NAP) --------------------------------
export function useBusinessProfiles(clientId?: string) {
  return useQuery({
    queryKey: [...BUSINESS_PROFILES_KEY, clientId ?? "all"],
    queryFn: () =>
      api.get<BusinessProfile[]>(
        clientId ? `/citation-builder/business-profiles?clientId=${clientId}` : "/citation-builder/business-profiles",
      ),
  });
}

export function useCreateBusinessProfile() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: BusinessProfileInput) =>
      api.post<BusinessProfile>("/citation-builder/business-profiles", body),
    onSuccess: () => void qc.invalidateQueries({ queryKey: BUSINESS_PROFILES_KEY }),
  });
}

// --- 7B-4: the directory catalog ---------------------------------------------
export function useDirectories(filters?: { market?: BusinessMarket[]; tier?: DirectoryTier[] }) {
  const params = new URLSearchParams();
  for (const m of filters?.market ?? []) params.append("market", m);
  for (const t of filters?.tier ?? []) params.append("tier", t);
  const qs = params.toString();
  return useQuery({
    queryKey: [...DIRECTORIES_KEY, qs],
    queryFn: () => api.get<Directory[]>(`/citation-builder/directories${qs ? `?${qs}` : ""}`),
  });
}

// --- Wave 4: NAP gap analysis + auto-derive submission profile ---------------
export const CITATION_GAP_KEY = ["citation-builder", "gap-analysis"] as const;

/** Reconcile a client's citations vs the catalog: existing/covered/missing + live URLs
 * + the resolved NAP source (so the UI stops showing "No business profile yet"). */
export function useCitationGap(clientId?: string) {
  return useQuery({
    queryKey: [...CITATION_GAP_KEY, clientId ?? ""],
    queryFn: () => api.get<CitationGap>(`/citation-builder/gap-analysis?clientId=${clientId}`),
    enabled: !!clientId,
  });
}

/** Resolve (deriving from the client's own NAP when needed) a submission profile for a
 * client. Lead-only at the backend; on success the profiles list refetches. */
export function useEnsureBusinessProfile() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (clientId: string) =>
      api.post<BusinessProfile>(`/citation-builder/clients/${clientId}/ensure-profile`, {}),
    onSuccess: () => void qc.invalidateQueries({ queryKey: BUSINESS_PROFILES_KEY }),
  });
}

/** POST /citation-builder/clients/{id}/audit — the AUDIT-FIRST step: discover which
 *  directories already list this business vs which are missing (writes nap_status
 *  rows the board + gap-analysis read). Requires the client's NAP. */
export function useRunCitationAudit() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (clientId: string) =>
      api.post<{ status: string; business: string; clientId: string; detail: string }>(
        `/citation-builder/clients/${clientId}/audit`,
        {},
      ),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: CITATIONS_KEY });
      void qc.invalidateQueries({ queryKey: CITATION_GAP_KEY });
      void qc.invalidateQueries({ queryKey: OFFPAGE_KPIS_KEY });
    },
  });
}

/** DELETE /citation-builder/clients/{id}/citations — clear a client's citation rows so
 *  it can be re-audited from a clean slate (lead-only). */
export function useClearCitations() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (clientId: string) =>
      api.del<{ clientId: string; removed: number }>(`/citation-builder/clients/${clientId}/citations`),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: CITATIONS_KEY });
      void qc.invalidateQueries({ queryKey: CITATION_GAP_KEY });
      void qc.invalidateQueries({ queryKey: OFFPAGE_KPIS_KEY });
    },
  });
}

// --- audit plan (generic → country → niche) ----------------------------------
export const AUDIT_PLAN_KEY = ["citation-builder", "audit-plan"] as const;

/** The prioritized geo/niche/generic citation audit for a client (GET
 * /citation-builder/clients/{id}/audit-plan). Read-only; each directory tagged
 * built|missing. Fetched only once a client is chosen. */
export function useAuditPlan(clientId?: string) {
  return useQuery({
    queryKey: [...AUDIT_PLAN_KEY, clientId ?? ""],
    queryFn: () => api.get<AuditPlan>(`/citation-builder/clients/${clientId}/audit-plan`),
    enabled: !!clientId,
  });
}

// --- Wave 4: API status boards -----------------------------------------------
export const WEB2_STATUS_KEY = ["citation-builder", "web2-status"] as const;
export const ENGINE_STATUS_KEY = ["citation-builder", "engine-status"] as const;

/** The Web 2.0 API status board: each platform CONNECTED (a vault credential exists)
 * vs MISSING, with the honest reason + external-API caveat. */
export function useWeb2Status() {
  return useQuery({
    queryKey: WEB2_STATUS_KEY,
    queryFn: () => api.get<Web2Status>("/citation-builder/web2-status"),
  });
}

/** The citation-ENGINE status board (Bing/Foursquare/CAPTCHA/bot/proxy). */
export function useCitationEngineStatus() {
  return useQuery({
    queryKey: ENGINE_STATUS_KEY,
    queryFn: () => api.get<CitationEngineBoard>("/citation-builder/engine-status"),
  });
}

// --- 7B-4: campaign dispatch --------------------------------------------------
export function useCreateCitationCampaign() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: CitationCampaignInput) =>
      api.post<CitationCampaignResult>("/citation-builder/campaigns", body),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: CITATIONS_KEY });
      void qc.invalidateQueries({ queryKey: OFFPAGE_KPIS_KEY });
      void qc.invalidateQueries({ queryKey: CITATION_GAP_KEY });
    },
  });
}

// --- Web 2.0 plan / approve ----------------------------------------------------
export type Web2PlanInput = {
  clientId: string;
  platform: string;
  anchor: string;
  targetUrl: string;
  topic?: string;
  pageType?: "service" | "blog" | "local";
  framework?: string;
  // First-hand grounding the writer grounds against — without it the draft holds at
  // review on [NEEDS:] gaps. camelCase = the server aliases.
  proofPoints?: string[];
  testimonials?: string[];
  uniqueData?: string[];
  services?: string[];
};

export function usePlanWeb2() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: Web2PlanInput) => api.post<Web2Property>("/offpage/web2/plan", body),
    onSuccess: () => void qc.invalidateQueries({ queryKey: WEB2_KEY }),
  });
}

export function useApproveWeb2() {
  const qc = useQueryClient();
  return useMutation({
    // `acknowledgeSimilarity` is only sent when the operator has actually seen a
    // similarity finding and confirmed the article is distinct. A plain approve
    // deliberately does not carry it, so a collision cannot be clicked past by habit.
    mutationFn: ({ id, action, acknowledgeSimilarity }: {
      id: string;
      action: "approve" | "reject";
      acknowledgeSimilarity?: boolean;
    }) =>
      api.post<Web2Property>(`/offpage/web2/${id}/approve`, {
        action,
        ...(acknowledgeSimilarity ? { acknowledgeSimilarity: true } : {}),
      }),
    onSuccess: () => void qc.invalidateQueries({ queryKey: WEB2_KEY }),
  });
}

// --- Web 2.0 campaigns --------------------------------------------------------

export const WEB2_CAMPAIGNS_KEY = ["offpage", "web2", "campaigns"] as const;
export const WEB2_BOARD_KEY = ["offpage", "web2", "platform-board"] as const;

/**
 * The three-state platform board for ONE client.
 *
 * This replaces reading a hard-coded platform list on the client: which platforms a
 * client may use is a server-side judgement (their own topical scope against each
 * platform's published terms), so the UI asks rather than assumes. Every catalogue row
 * comes back — the ineligible ones carry the platform's own reason — which is what lets
 * the board show the system's full reach instead of a silently shorter list.
 */
export function useWeb2PlatformBoard(clientId: string | undefined) {
  return useQuery({
    queryKey: [...WEB2_BOARD_KEY, clientId ?? ""],
    queryFn: () =>
      api.get<Web2PlatformStatusRow[]>(
        `/offpage/web2/platform-board?clientId=${encodeURIComponent(clientId ?? "")}`,
      ),
    enabled: !!clientId,
  });
}

/** Campaigns for the board (optionally narrowed to one client). */
export function useWeb2Campaigns(clientId?: string) {
  return useQuery({
    queryKey: [...WEB2_CAMPAIGNS_KEY, clientId ?? ""],
    queryFn: () =>
      api.get<Web2Campaign[]>(
        `/offpage/web2/campaigns${clientId ? `?clientId=${encodeURIComponent(clientId)}` : ""}`,
      ),
    refetchInterval: 30_000,
  });
}

/**
 * Price and schedule a campaign WITHOUT creating anything.
 *
 * Separate from create on purpose: thirty articles is thirty metered drafting runs and,
 * at the default pacing, about a month of publishing. Both belong in front of the
 * operator at the moment they decide, not afterwards.
 */
export function useEstimateWeb2Campaign() {
  return useMutation({
    mutationFn: (body: Web2CampaignInput) =>
      api.post<Web2CampaignEstimate>("/offpage/web2/campaigns/estimate", body),
  });
}

/** Every placement in one campaign — the report behind the rollup. */
export function useCampaignPlacements(campaignId: string | null) {
  return useQuery({
    queryKey: ["web2-placements", campaignId ?? ""],
    queryFn: () =>
      api.get<Web2Placement[]>(
        `/offpage/web2/campaigns/${encodeURIComponent(campaignId ?? "")}/placements`,
      ),
    enabled: Boolean(campaignId),
    refetchInterval: 20_000,
  });
}

/** The cross-campaign ledger: everything ever built, newest first. */
export function useWeb2Placements(clientId?: string) {
  return useQuery({
    queryKey: ["web2-placements-all", clientId ?? ""],
    queryFn: () =>
      api.get<Web2Placement[]>(
        `/offpage/web2/placements${clientId ? `?clientId=${encodeURIComponent(clientId)}` : ""}`,
      ),
    refetchInterval: 30_000,
  });
}

/** ONE operator decision for the whole campaign. The server still transitions each
 *  property individually (Tumblr requires a per-post human action), so this is a single
 *  click over structurally-individual approvals - not a batch write. */
export function useApproveWeb2Campaign() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ campaignId, action }: { campaignId: string; action: "approve" | "reject" }) =>
      api.post<Web2CampaignApproval>(
        `/offpage/web2/campaigns/${encodeURIComponent(campaignId)}/approve`,
        { action },
      ),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: WEB2_CAMPAIGNS_KEY });
      void qc.invalidateQueries({ queryKey: WEB2_KEY });
    },
  });
}

export function useCreateWeb2Campaign() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: Web2CampaignInput) =>
      api.post<Web2Campaign>("/offpage/web2/campaigns", body),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: WEB2_CAMPAIGNS_KEY });
      void qc.invalidateQueries({ queryKey: WEB2_KEY });
    },
  });
}
