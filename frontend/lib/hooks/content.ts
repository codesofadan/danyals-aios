"use client";

// ============================================================
// AIOS · content data hooks
// Backs ContentWorkspace off the FastAPI /content endpoints instead of the
// build-time `contentJobs` seed. ContentJob ↔ ContentJobResponse is
// contract-locked, so the JSON drops straight into the existing type.
// ============================================================

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type {
  ContentJob,
  Framework,
  PageType,
  PublishTarget,
  ResearchContentType,
  ResearchItem,
  SiteDesignProfile,
} from "@/lib/content";

export const CONTENT_JOBS_KEY = ["content", "jobs"] as const;
export const CONTENT_STATS_KEY = ["content", "jobs", "stats"] as const;

// Worker-owned in-flight states: the pipeline is actively advancing these, so the
// board polls while any job sits in one of them (needs_review is a HUMAN gate, not
// worker motion, so it does not keep the poll alive).
const isWorkerActive = (j: ContentJob) =>
  j.status === "queued" || j.status === "drafting" || j.status === "publishing";

/** The content-job board (created_at desc). Polls every 3s while the worker is
 * moving any job, then stops. */
export function useContentJobs() {
  return useQuery({
    queryKey: CONTENT_JOBS_KEY,
    queryFn: () => api.get<ContentJob[]>("/content/jobs"),
    refetchInterval: (query) => {
      const rows = query.state.data as ContentJob[] | undefined;
      return rows?.some(isWorkerActive) ? 3000 : false;
    },
  });
}

// Matches ContentStatsResponse (serialized: inPipeline/awaitingReview/
// publishedThisMonth/avgCost).
export type ContentStats = {
  inPipeline: number;
  awaitingReview: number;
  publishedThisMonth: number;
  avgCost: number;
};

export function useContentStats() {
  return useQuery({
    queryKey: CONTENT_STATS_KEY,
    queryFn: () => api.get<ContentStats>("/content/jobs/stats"),
  });
}

// POST /content/jobs body (ContentJobCreate — populate_by_name, so pageType is the
// alias). The server snapshots the client name/color, resolves Auto → framework and
// the JSON-LD schema, and returns the queued ContentJob.
export type CreateContentJobInput = {
  client_id: string;
  pageType: PageType;
  topic: string;
  framework: Framework | "Auto";
  target: PublishTarget;
  // First-hand grounding the QA publish gate requires (fact_grounding / E-E-A-T).
  // Optional, but a job with none of these hard-fails the publish gate (the
  // generator has nothing real to ground against). camelCase = the server aliases.
  proofPoints?: string[];
  testimonials?: string[];
  uniqueData?: string[];
  services?: string[];
};

export function useCreateContentJob() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (input: CreateContentJobInput) => api.post<ContentJob>("/content/jobs", input),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: CONTENT_JOBS_KEY });
      void qc.invalidateQueries({ queryKey: CONTENT_STATS_KEY });
    },
  });
}

// POST /content/jobs/{code}/review — the human review gate (approve → publishing,
// edit → drafting, reject → rejected). `code` is the public CJ-#### id. `note` is
// the reviewer's GUIDED-EDIT instruction (only meaningful for `edit`): the server
// persists it and the worker re-drafts targeting exactly what was asked.
export type ReviewContentInput = {
  code: string;
  action: "approve" | "edit" | "reject";
  note?: string;
};

export function useReviewContentJob() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ code, action, note }: ReviewContentInput) =>
      api.post<ContentJob>(`/content/jobs/${code}/review`, { action, note }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: CONTENT_JOBS_KEY });
      void qc.invalidateQueries({ queryKey: CONTENT_STATS_KEY });
    },
  });
}

// --- Research-first bulk content (POST /content/research + …/generate) ---------
// The recommender researches a site + content type LIVE (Anthropic server-side
// web_search) and returns a page set to pick from — a single paid call metered under
// the content_research dial. A keyless / dial-blocked / failed run DEGRADES (200,
// status='degraded'), never an error. retry:0 (the client default) so a transient
// failure never double-spends the gated call.
export type ContentResearchInput = {
  site: string;
  contentType: ResearchContentType;
  count?: number;
};
export type ContentResearchResult = {
  status: "ok" | "degraded";
  items: ResearchItem[];
  reason: string;
};

export function useContentResearch() {
  return useMutation({
    mutationFn: (input: ContentResearchInput) =>
      api.post<ContentResearchResult>("/content/research", input),
  });
}

// POST /content/research/generate — fan the SELECTED recommendations into content jobs
// (the SAME create path as POST /content/jobs). Shared client / framework / target /
// grounding / design profile across every item; each item carries its own title +
// pageType. Returns the queued CJ-#### codes; on success the board + stats refetch.
export type BulkGenerateInput = {
  items: ResearchItem[];
  clientId: string;
  framework?: Framework | "Auto";
  target?: PublishTarget;
  proofPoints?: string[];
  testimonials?: string[];
  uniqueData?: string[];
  services?: string[];
  designProfile?: SiteDesignProfile;
};

export function useGenerateFromResearch() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (input: BulkGenerateInput) =>
      api.post<{ jobs: string[] }>("/content/research/generate", input),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: CONTENT_JOBS_KEY });
      void qc.invalidateQueries({ queryKey: CONTENT_STATS_KEY });
    },
  });
}

// POST /content/site-design — extract the target site's existing design so a new page
// can be built to MATCH it. A single paid call metered under the content dial; a
// keyless / dial-blocked / failed analysis DEGRADES (200, status='degraded',
// profile=null). retry:0 so a transient failure never double-spends.
export type SiteDesignInput = { site: string; maxPages?: number };
export type SiteDesignResult = {
  status: "ok" | "degraded";
  profile: SiteDesignProfile | null;
  reason: string;
};

export function useSiteDesign() {
  return useMutation({
    mutationFn: (input: SiteDesignInput) =>
      api.post<SiteDesignResult>("/content/site-design", input),
  });
}

// --- Rich retrieval (GET /content/jobs/{code}/{column}) -----------------------
// The server-only pipeline columns the full SEO Review preview reads. Each endpoint
// returns { id, <column>: value }. All are staff-only and settle once the job
// leaves the worker, so they are fetched lazily (never polled).

/** Generic lazy fetch of one rich column for a job (keyed by column so each tab
 * caches independently). */
function useContentColumn<T>(code: string | null, column: string) {
  return useQuery({
    queryKey: ["content", "jobs", code, column] as const,
    queryFn: () => api.get<T>(`/content/jobs/${code}/${column}`),
    enabled: !!code,
  });
}

// (a) ARTICLE — the draft markdown, rendered to HTML in the preview iframe.
export type ContentDraft = { id: string; draft: string | null };
export function useContentDraft(code: string | null) {
  return useContentColumn<ContentDraft>(code, "draft");
}

// (b) SCHEMA — the assembled JSON-LD graph (the schema.org markup + @type).
export type ContentSchema = { id: string; schema: Record<string, unknown> | null };
export function useContentSchema(code: string | null) {
  return useContentColumn<ContentSchema>(code, "schema");
}

// (c) META + (d) OUTLINE — headings, layout, and the rendered <title>/<meta
// description> (outline.meta) the pipeline persists for the preview.
export type ContentOutline = {
  id: string;
  outline: {
    headings?: { level: number; text: string }[];
    meta?: { title?: string; description?: string };
    heading_blueprint?: string[];
    section_roles?: string[];
    needs?: string[];
    layout?: { key?: string; label?: string } & Record<string, unknown>;
    [k: string]: unknown;
  } | null;
};
export function useContentOutline(code: string | null) {
  return useContentColumn<ContentOutline>(code, "outline");
}

// (d) KEYWORD coverage — the primary/secondary/semantic keyword plan.
export type ContentKeywords = {
  id: string;
  keywords: {
    primary?: string;
    secondary?: string[];
    semantic_entities?: string[];
    questions?: string[];
    intent?: string;
    [k: string]: unknown;
  } | null;
};
export function useContentKeywords(code: string | null) {
  return useContentColumn<ContentKeywords>(code, "keywords");
}

// (d) INTERNAL-LINK coverage — the pillar↔cluster anchor suggestions.
export type ContentLinks = {
  id: string;
  links: { links?: { anchor: string; url: string; keyword: string }[] } | null;
};
export function useContentLinks(code: string | null) {
  return useContentColumn<ContentLinks>(code, "links");
}

// (e) QA SCORECARD — the 14-dimension result (pass/fail per dimension + total).
export type QaScorecard = {
  dimensions: Record<string, number>;
  weighted_total: number;
  passed: boolean;
  blocked_by: string[];
  provisional: boolean;
  notes: string[];
};
export type ContentQa = { id: string; qa: QaScorecard | null };
export function useContentQa(code: string | null) {
  return useContentColumn<ContentQa>(code, "qa");
}

// (f) WORDPRESS push: the permalink + wp-admin edit link captured when an approved
// job was pushed to the client's AIOS Publisher plugin (the host-independent push).
// All fields are null until the job is pushed; fetched lazily like the other rich
// columns. Kept OUT of the 15-key ContentJob contract, so it rides its own endpoint.
export type ContentWp = {
  id: string;
  wp: {
    url: string | null;
    edit_url: string | null;
    post_id: string | null;
    status: string | null;
    target: string | null;
  } | null;
};
export function useContentWp(code: string | null) {
  return useContentColumn<ContentWp>(code, "wp");
}
