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
import type { JobRun } from "@/lib/jobs";
import { isTerminalStatus } from "@/lib/jobs";
import type {
  AuditPlan,
  Backlink,
  BusinessMarket,
  BusinessProfile,
  BusinessProfileInput,
  Citation,
  CitationCampaignInput,
  CitationCampaignResult,
  CitationEngineBoard,
  CitationGap,
  Directory,
  DirectoryTier,
  QueueBlockReason,
  SpecBoard,
  SpecCreateInput,
  DirectorySpec,
  Web2AccountCreate,
  Web2Catalog,
  QueueBoard,
  QueueCompleteResult,
  QueueItem,
  OffpageKpis,
  Web2Campaign,
  Web2Account,
  Web2AccountCheck,
  Web2AnchorCheck,
  Web2AnchorCheckInput,
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
export function useCitations(clientId?: string) {
  return useQuery({
    // Client-scoped when a client is chosen. The unscoped call returns a 50-row
    // GLOBAL page — rendering that under a client-scoped journey was how 45 fresh
    // rows could "not come back" (they sorted below the fold of other clients'
    // rows). The server has had the filter all along; the UI just never passed it.
    queryKey: [...CITATIONS_KEY, clientId ?? "all"],
    queryFn: () =>
      api.get<Citation[]>(
        clientId ? `/offpage/citations?clientId=${encodeURIComponent(clientId)}` : "/offpage/citations",
      ),
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

// DELETED 2026-09-02: useActOnCitation / useBulkUpdateCitations. They drove the
// per-row "Submit"/"Update" buttons that wrote submit_status='submitted' on a click —
// an assertion dressed as a delivery. The backend routes remain (the
// /aios-citation-builder skill's reconcile flow uses them, with a human confirming);
// the dashboard offers no assertion path any more.

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
export const CITATION_AUDIT_RUNS_KEY = ["citation-builder", "audit-runs"] as const;

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
export type CitationAuditQueued = {
  status: string;
  business: string;
  clientId: string;
  detail: string;
  /** The job run to follow. Null only if the ledger could not be read back - the
   *  audit is still queued, there is simply nothing to poll. */
  jobRunId: string | null;
  jobName: string;
  /** The dial's verdict, stated at click time (2026-09-02). willRun false means the
   *  sweep will record a blocked run, not listings — say so, don't let the operator
   *  poll nothing. */
  discovery?: { dial: string; willRun: boolean; detail?: string };
};

export function useRunCitationAudit() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (clientId: string) =>
      api.post<CitationAuditQueued>(`/citation-builder/clients/${clientId}/audit`, {}),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: CITATIONS_KEY });
      void qc.invalidateQueries({ queryKey: CITATION_GAP_KEY });
      void qc.invalidateQueries({ queryKey: OFFPAGE_KPIS_KEY });
      // The run list is what the progress panel reads. Without this the panel sits
      // on a 30s-stale empty list after the POST - and its poll only speeds up once
      // it can SEE a non-terminal run, so it would show nothing for half a minute
      // at exactly the moment the operator is asking "did that start?".
      void qc.invalidateQueries({ queryKey: CITATION_AUDIT_RUNS_KEY });
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
      void qc.invalidateQueries({ queryKey: CITATION_CAMPAIGNS_KEY });
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
  /** "This platform's own rules argue against it for this client, and I'm choosing it
   *  anyway." Unlocks a topical mismatch or an unreviewed platform; it can never
   *  conjure a missing publisher or credential. */
  acknowledgePlatformAdvisory?: boolean;
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

/** The connection board: which accounts exist and whether their credential is usable. */
export function useWeb2Accounts(clientId?: string) {
  return useQuery({
    queryKey: ["web2-accounts", clientId ?? ""],
    queryFn: () =>
      api.get<Web2Account[]>(
        `/offpage/web2/accounts${clientId ? `?clientId=${encodeURIComponent(clientId)}` : ""}`,
      ),
    refetchInterval: 60_000,
  });
}

/** One client's standing Web 2.0 publishing identity: the brand handle stem, the
 *  CLIENT-domain address platform verification mail lands on, and whether the builder
 *  can read that mailbox. Never carries the mailbox password — only `imapPasswordHeld`. */
export type Web2ClientIdentity = {
  clientId: string;
  client: string;
  handleBase: string;
  contactEmail: string;
  imapHost: string;
  imapPort: number;
  imapUser: string;
  imapPasswordHeld: boolean;
  mailboxReady: boolean;
  /** The standing grounding pack every campaign for this client reuses. */
  proofPoints: string[];
  testimonials: string[];
  uniqueData: string[];
  services: string[];
};

export type Web2ClientIdentityInput = {
  handleBase?: string;
  contactEmail?: string;
  imapHost?: string;
  imapPort?: number;
  imapUser?: string;
  /** Write-only. Blank LEAVES an existing seal alone; clearing is explicit. */
  imapPassword?: string;
  clearImapPassword?: boolean;
  proofPoints?: string[];
  testimonials?: string[];
  uniqueData?: string[];
  services?: string[];
};

export function useWeb2ClientIdentity(clientId?: string) {
  return useQuery({
    queryKey: ["web2-identity", clientId ?? ""],
    queryFn: () =>
      api.get<Web2ClientIdentity>(
        `/offpage/web2/clients/${encodeURIComponent(clientId!)}/identity`,
      ),
    enabled: !!clientId,
  });
}

export function useSaveWeb2ClientIdentity(clientId?: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: Web2ClientIdentityInput) =>
      api.put<Web2ClientIdentity>(
        `/offpage/web2/clients/${encodeURIComponent(clientId!)}/identity`,
        body,
      ),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["web2-identity", clientId ?? ""] });
    },
  });
}

/** One account we intend to bring to life, and who is holding the ball right now. */
export type Web2ProvisionItem = {
  id: string;
  client: string;
  clientId: string;
  platform: string;
  status:
    | "queued" | "identity_ready" | "awaiting_account" | "awaiting_verification"
    | "awaiting_credential" | "live" | "blocked" | "cancelled";
  lane: "auto" | "guided";
  handle: string;
  registrationEmail: string;
  setupUrl: string;
  verifyLink: string;
  note: string;
  accountId: string;
};

export function useWeb2Provisioning(clientId?: string) {
  return useQuery({
    queryKey: ["web2-provisioning", clientId ?? ""],
    queryFn: () =>
      api.get<Web2ProvisionItem[]>(
        `/offpage/web2/provisioning${clientId ? `?clientId=${encodeURIComponent(clientId)}` : ""}`,
      ),
  });
}

/** Queue account creation for a client across N platforms. Idempotent: platforms
 *  already in flight come back unchanged rather than duplicated. */
export function useStartWeb2Provisioning() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: { clientId: string; platforms: string[] }) =>
      api.post<Web2ProvisionItem[]>("/offpage/web2/provisioning", body),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["web2-provisioning"] });
    },
  });
}

/** Move one item along. The credential travels on the final step to `live`, where it
 *  is sealed server-side and an account row is created. */
export function useAdvanceWeb2Provisioning() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, ...body }: {
      id: string;
      status: string;
      note?: string;
      credential?: Record<string, string>;
      handle?: string;
      propertyUrl?: string;
    }) => api.post<Web2ProvisionItem>(`/offpage/web2/provisioning/${id}`, body),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["web2-provisioning"] });
      void qc.invalidateQueries({ queryKey: ["web2-accounts"] });
      void qc.invalidateQueries({ queryKey: WEB2_BOARD_KEY });
    },
  });
}

/** Start OAuth for one queue item. Returns a consent URL, or `held` with the reason
 *  when no app is registered for that platform yet. */
export function useConnectWeb2Provisioning() {
  return useMutation({
    mutationFn: (id: string) =>
      api.get<{ held: boolean; reason: string; authorizeUrl: string | null }>(
        `/offpage/web2/provisioning/${id}/connect`,
      ),
  });
}

/** Run the automatic steps: mint the API-signup accounts, and read each client's own
 *  mailbox once for confirmation mail that has arrived. */
export function useRunWeb2Provisioning() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () =>
      api.post<{ checked: number; advanced: number; failed: number }>(
        "/offpage/web2/provisioning/run",
        {},
      ),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["web2-provisioning"] });
      void qc.invalidateQueries({ queryKey: ["web2-accounts"] });
    },
  });
}

/** The platform catalogue, including the credential shape each platform needs. */
export function useWeb2Catalog() {
  return useQuery({
    queryKey: ["web2-catalog"],
    queryFn: () => api.get<Web2Catalog>("/offpage/web2/catalog"),
    staleTime: 10 * 60_000,
  });
}

/** Register a publishing account and seal its credential.
 *
 *  The credential travels once, in this request body, and is never read back: no query
 *  caches it, no response carries it. A refusal names the RULE (R2-08 identity hygiene,
 *  the shared catch-all domain) rather than echoing the value. */
export function useRegisterWeb2Account() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: Web2AccountCreate) =>
      api.post<Web2Account>("/offpage/web2/accounts", body),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["web2-accounts"] });
      void qc.invalidateQueries({ queryKey: WEB2_BOARD_KEY });
    },
  });
}

/** Ask the platform, right now, whether this credential still authenticates.
 *  Turns "we find out when a campaign fails" into "we know before it runs". */
export function useCheckWeb2Account() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (accountId: string) =>
      api.post<Web2AccountCheck>(
        `/offpage/web2/accounts/${encodeURIComponent(accountId)}/check`,
        {},
      ),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["web2-accounts"] });
    },
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

// --- the earned whitelist: spec hooks (the teach-the-bot loop, W4.1) -----------

export const SPEC_BOARD_KEY = ["citation-builder", "specs"] as const;

export function useSpecBoard() {
  return useQuery({
    queryKey: SPEC_BOARD_KEY,
    queryFn: () => api.get<SpecBoard>("/citation-builder/specs"),
  });
}

function invalidateSpecs(qc: ReturnType<typeof useQueryClient>) {
  qc.invalidateQueries({ queryKey: SPEC_BOARD_KEY });
  qc.invalidateQueries({ queryKey: ENGINE_STATUS_KEY });
}

/** File a NEW spec revision — always INACTIVE; it has earned nothing yet. */
export function useCreateSpec() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: SpecCreateInput) =>
      api.post<DirectorySpec>("/citation-builder/specs", body),
    onSuccess: () => invalidateSpecs(qc),
  });
}

/** The dated, write-once human DOM check. Sign it only having compared each selector
 *  with the open form. */
export function useVerifySpec() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ specId, notes }: { specId: string; notes?: string }) =>
      api.post<DirectorySpec>(`/citation-builder/specs/${specId}/verify`, {
        selectors: [],
        notes: notes ?? "",
      }),
    onSuccess: () => invalidateSpecs(qc),
  });
}

/** Record the first submission with this exact spec that produced a public listing
 *  URL. The server probes the URL before recording it. */
export function useSpecFirstLive() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ specId, liveUrl }: { specId: string; liveUrl: string }) =>
      api.post<DirectorySpec>(`/citation-builder/specs/${specId}/first-live`, { liveUrl }),
    onSuccess: () => invalidateSpecs(qc),
  });
}

/** Activate: the DB CHECK refuses unless BOTH halves are earned. Promotes the
 *  directory to route B in the same transaction — the only thing that ever does. */
export function useActivateSpec() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (specId: string) =>
      api.post<DirectorySpec>(`/citation-builder/specs/${specId}/activate`, {}),
    onSuccess: () => invalidateSpecs(qc),
  });
}

export function useDeactivateSpec() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ specId, reason }: { specId: string; reason: string }) =>
      api.post<DirectorySpec>(`/citation-builder/specs/${specId}/deactivate`, { reason }),
    onSuccess: () => invalidateSpecs(qc),
  });
}

// --- citation campaigns (0120): the batch as a durable, pollable thing --------

export const CITATION_CAMPAIGNS_KEY = ["citation-builder", "campaigns"] as const;

export type CampaignSummary = {
  id: string;
  client: string;
  createdAt: string;
  requested: number;
  queued: number;
  liveCount: number;
  estimatedCost: number;
};

export type CampaignRow = {
  id: string;
  directory: string;
  submitStatus: string;
  blockedReason: string;
  liveUrl: string;
  detail: string;
};

export type CampaignRollup = {
  id: string;
  client: string;
  createdAt: string;
  requested: number;
  queued: number;
  estimatedCost: number;
  byStatus: Record<string, number>;
  byBlockedReason: Record<string, number>;
  stuck: number;
  liveUrls: { directory: string; url: string; status: string }[];
  skipped: { directory: string; reason: string; detail?: string; clause?: string }[];
  rows: CampaignRow[];
};

/** Recent campaigns, newest first — how the workspace finds the current one
 *  without the operator holding an id. */
export function useCitationCampaigns(clientId?: string) {
  return useQuery({
    queryKey: [...CITATION_CAMPAIGNS_KEY, clientId ?? "all"],
    queryFn: () =>
      api.get<CampaignSummary[]>(
        clientId
          ? `/citation-builder/campaigns?clientId=${encodeURIComponent(clientId)}`
          : "/citation-builder/campaigns",
      ),
    enabled: clientId !== undefined,
  });
}

/** One campaign's live rollup. Polls every 4s while any row is non-terminal — the
 *  CitationAuditProgress cadence, the house pattern for "watch it go". */
export function useCampaignRollup(campaignId: string | undefined) {
  return useQuery({
    queryKey: [...CITATION_CAMPAIGNS_KEY, "rollup", campaignId ?? ""],
    queryFn: () => api.get<CampaignRollup>(`/citation-builder/campaigns/${campaignId}`),
    enabled: !!campaignId,
    placeholderData: (prev) => prev, // never blank the board between polls
    refetchInterval: (query) => {
      const roll = query.state.data as CampaignRollup | undefined;
      if (!roll) return 4000;
      const moving = (roll.byStatus["queued"] ?? 0) + (roll.byStatus["submitting"] ?? 0);
      return moving > 0 ? 4000 : false;
    },
  });
}

/** POST /citation-builder/recheck — the VISIBLE liveness trigger (beat stays off by
 *  owner decision, so re-checks run when a person asks, and say what they did). */
export function useRecheckCitations() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api.post<{ checked: number; changed: number }>("/citation-builder/recheck", {}),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: CITATIONS_KEY });
      qc.invalidateQueries({ queryKey: CITATION_GAP_KEY });
      qc.invalidateQueries({ queryKey: CITATION_CAMPAIGNS_KEY });
    },
  });
}

// --- citation work queue (0110) ----------------------------------------------

/** The queue at a glance, including the median minutes per finished item. */
export function useCitationQueue() {
  return useQuery({
    queryKey: ["citation-queue"],
    queryFn: () => api.get<QueueBoard>("/citation-builder/queue"),
    refetchInterval: 30_000,
  });
}

/** Take the next available item. Resolves to `null` when the queue is empty. */
export function useClaimQueueItem() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (clientId?: string) =>
      api.post<QueueItem | null>("/citation-builder/queue/claim", clientId ? { clientId } : {}),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["citation-queue"] });
    },
  });
}

/** Extend the lease and bank the seconds worked. Time accumulates server-side, so a
 *  dropped heartbeat costs one interval of measurement, not the whole session. */
export function useQueueHeartbeat() {
  return useMutation({
    mutationFn: ({ citationId, workedSeconds }: { citationId: string; workedSeconds: number }) =>
      api.post<{ ok: boolean }>(`/citation-builder/queue/${citationId}/heartbeat`, {
        workedSeconds,
      }),
  });
}

/** Close an item with the listing's public URL. The server FETCHES that URL and refuses
 *  the completion if the business is not on the page — so `accepted: false` is a normal,
 *  expected outcome and must be shown to the operator, not treated as an error. */
export function useCompleteQueueItem() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      citationId,
      liveUrl,
      workedSeconds,
      note,
    }: {
      citationId: string;
      liveUrl: string;
      workedSeconds: number;
      note?: string;
    }) =>
      api.post<QueueCompleteResult>(`/citation-builder/queue/${citationId}/complete`, {
        liveUrl,
        workedSeconds,
        note: note ?? "",
      }),
    onSuccess: (result) => {
      if (result.accepted) {
        qc.invalidateQueries({ queryKey: ["citation-queue"] });
        // The REAL keys. This used to invalidate ["citations"] — a key that matches
        // nothing (the board's key is ["offpage","citations"]) — so finishing an item
        // never refreshed the citations page and the two screens diverged until a hard
        // reload. Gap + KPIs move too: a verified listing changes both.
        qc.invalidateQueries({ queryKey: CITATIONS_KEY });
        qc.invalidateQueries({ queryKey: CITATION_GAP_KEY });
        qc.invalidateQueries({ queryKey: OFFPAGE_KPIS_KEY });
      }
    },
  });
}

/** Report an item as not done, with a reason. A first-class outcome, not a failure. */
export function useBlockQueueItem() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      citationId,
      reason,
      detail,
      workedSeconds,
    }: {
      citationId: string;
      reason: QueueBlockReason;
      detail?: string;
      workedSeconds: number;
    }) =>
      api.post<void>(`/citation-builder/queue/${citationId}/blocked`, {
        reason,
        detail: detail ?? "",
        workedSeconds,
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["citation-queue"] });
      // A block flips the row to `blocked` — the citations board and the gap must see it.
      qc.invalidateQueries({ queryKey: CITATIONS_KEY });
      qc.invalidateQueries({ queryKey: CITATION_GAP_KEY });
    },
  });
}

/** Hand an item back without finishing it. The attempt still counts. */
export function useReleaseQueueItem() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ citationId, workedSeconds }: { citationId: string; workedSeconds: number }) =>
      api.post<void>(`/citation-builder/queue/${citationId}/release`, { workedSeconds }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["citation-queue"] });
    },
  });
}

/**
 * Ask whether an anchor is usable BEFORE planning anything
 * (`POST /offpage/web2/anchor-check`).
 *
 * The plan route already refuses an exact-match commercial anchor — but it refuses at
 * submission, as a 422 the modal used to swallow, so the operator was shown a queued
 * property that did not exist. This lets the form answer beside the field instead.
 *
 * Free server-side: no write, no enqueue, no outbound call. The rule is NOT ported to
 * TypeScript — the brand exemption needs the client name from the database, and a
 * second copy would drift from the one the write path enforces.
 */
export function useCheckWeb2Anchor() {
  return useMutation({
    mutationFn: (body: Web2AnchorCheckInput) =>
      api.post<Web2AnchorCheck>("/offpage/web2/anchor-check", body),
  });
}


/**
 * The citation audit's own run history, newest first.
 *
 * The audit used to be invisible: POST returned a bare {"status":"queued"} with no
 * id, the underlying task produced no ledger row at all, and the UI showed a flash
 * that faded after four seconds. After that an operator had no way to tell a sweep
 * still working from one that died - or from one that never started because no
 * worker was consuming the queue.
 *
 * It is a job under the contract now, so its state, its live stage line and its
 * counts are all readable from the ledger every other long job already uses.
 */
export function useCitationAuditRuns(clientId: string | null, limit = 5) {
  const params = new URLSearchParams({ jobName: "offpage.monitor", limit: String(limit) });
  if (clientId) params.set("clientId", clientId);
  const qs = params.toString();

  return useQuery({
    queryKey: [...CITATION_AUDIT_RUNS_KEY, qs] as const,
    queryFn: () => api.get<JobRun[]>(`/jobs/runs?${qs}`),
    enabled: Boolean(clientId),
    refetchInterval: (query) => {
      const rows = query.state.data as JobRun[] | undefined;
      if (!rows) return 4000;
      return rows.some((r) => !isTerminalStatus(r.status)) ? 4000 : false;
    },
    placeholderData: (prev) => prev,
  });
}
