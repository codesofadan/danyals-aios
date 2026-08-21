"use client";

// Site Builder API hooks — mirrors lib/hooks/content.ts's exact pattern (the hook
// itself calls api.get/post inline in queryFn/mutationFn; polling is a function of
// current data via refetchInterval, not a fixed constant).
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import {
  ACTIVE_STATUSES,
  type CreateSiteBuilderJobInput,
  type DesignIR,
  type SiteGenerationJob,
  type SiteTemplate,
  type VisualValidation,
} from "@/lib/site-builder";

export const SITE_BUILDER_JOBS_KEY = ["site-builder", "jobs"] as const;
export const siteBuilderJobKey = (code: string) => ["site-builder", "jobs", code] as const;
export const siteBuilderDesignKey = (id: string) => ["site-builder", "designs", id] as const;
export const siteBuilderTemplatesKey = (industry: string, pageType: string) =>
  ["site-builder", "templates", industry, pageType] as const;
export const siteBuilderValidationsKey = (code: string) => ["site-builder", "jobs", code, "visual-validations"] as const;

const isJobActive = (j: SiteGenerationJob) => (ACTIVE_STATUSES as string[]).includes(j.status);

/** The build queue (newest first). Polls every 3s while ANY job is still moving,
 * then stops — identical shape to useContentJobs. */
export function useSiteBuilderJobs() {
  return useQuery({
    queryKey: SITE_BUILDER_JOBS_KEY,
    queryFn: () => api.get<SiteGenerationJob[]>("/site-builder/jobs"),
    refetchInterval: (query) => {
      const rows = query.state.data as SiteGenerationJob[] | undefined;
      return rows?.some(isJobActive) ? 3000 : false;
    },
  });
}

/** Poll ONE job by its SB-#### code — used once the wizard has a job to track,
 * so the progress copy updates without re-fetching the whole queue. */
export function useSiteBuilderJob(code: string | null) {
  return useQuery({
    queryKey: siteBuilderJobKey(code ?? ""),
    queryFn: () => api.get<SiteGenerationJob>(`/site-builder/jobs/${code}`),
    enabled: !!code,
    refetchInterval: (query) => {
      const job = query.state.data as SiteGenerationJob | undefined;
      return job && isJobActive(job) ? 2000 : false;
    },
  });
}

export function useCreateSiteBuilderJob() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (input: CreateSiteBuilderJobInput) => api.post<SiteGenerationJob>("/site-builder/analyze", input),
    onSuccess: () => void qc.invalidateQueries({ queryKey: SITE_BUILDER_JOBS_KEY }),
  });
}

export function usePublishSiteBuilderJob() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (code: string) => api.post<SiteGenerationJob>(`/site-builder/jobs/${code}/publish`),
    onSuccess: (_data, code) => {
      void qc.invalidateQueries({ queryKey: SITE_BUILDER_JOBS_KEY });
      void qc.invalidateQueries({ queryKey: siteBuilderJobKey(code) });
    },
  });
}

export function useSiteBuilderDesign(designId: string | null) {
  return useQuery({
    queryKey: siteBuilderDesignKey(designId ?? ""),
    queryFn: () => api.get<DesignIR>(`/site-builder/designs/${designId}`),
    enabled: !!designId,
  });
}

/** The template gallery (Step 2/3 — "Template"), ranked by relevance when an
 * industry/pageType is supplied. */
export function useSiteBuilderTemplates(industry: string, pageType: string) {
  return useQuery({
    queryKey: siteBuilderTemplatesKey(industry, pageType),
    queryFn: () => {
      const params = new URLSearchParams();
      if (industry) params.set("industry", industry);
      if (pageType) params.set("pageType", pageType);
      const qs = params.toString();
      return api.get<SiteTemplate[]>(`/site-builder/templates${qs ? `?${qs}` : ""}`);
    },
  });
}

export function useSiteBuilderVisualValidations(code: string | null) {
  return useQuery({
    queryKey: siteBuilderValidationsKey(code ?? ""),
    queryFn: () => api.get<VisualValidation[]>(`/site-builder/jobs/${code}/visual-validations`),
    enabled: !!code,
  });
}
