"use client";

// ============================================================
// AIOS · content data hooks
// Backs ContentWorkspace off the FastAPI /content endpoints instead of the
// build-time `contentJobs` seed. ContentJob ↔ ContentJobResponse is
// contract-locked, so the JSON drops straight into the existing type.
// ============================================================

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type { ContentJob, Framework, PageType, PublishTarget } from "@/lib/content";

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
// edit → drafting, reject → rejected). `code` is the public CJ-#### id.
export type ReviewContentInput = { code: string; action: "approve" | "edit" | "reject" };

export function useReviewContentJob() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ code, action }: ReviewContentInput) =>
      api.post<ContentJob>(`/content/jobs/${code}/review`, { action }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: CONTENT_JOBS_KEY });
      void qc.invalidateQueries({ queryKey: CONTENT_STATS_KEY });
    },
  });
}

// GET /content/jobs/{code}/draft — the server-only draft markdown for the Review
// preview (staff-only rich retrieval; the pipeline populates draft_md at
// needs_review and it survives publish, so the preview works for done jobs too).
export type ContentDraft = { id: string; draft: string | null };

/** The reviewed draft markdown for a job, fetched lazily when a job is selected for
 * preview. Not polled — the draft is settled once the job leaves the worker. */
export function useContentDraft(code: string | null) {
  return useQuery({
    queryKey: ["content", "jobs", code, "draft"] as const,
    queryFn: () => api.get<ContentDraft>(`/content/jobs/${code}/draft`),
    enabled: !!code,
  });
}
