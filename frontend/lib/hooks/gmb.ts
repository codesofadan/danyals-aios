"use client";

// ============================================================
// AIOS · GMB (Google Business Profile) post data hooks (Wave 5)
// Backs GmbWorkspace off the FastAPI /gmb endpoints. Generation is synchronous +
// cost-gated server-side; a keyless/dial-off deploy degrades to a stored draft.
// ============================================================

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type {
  GmbCtaType,
  GmbPost,
  GmbPostType,
  GmbPublishResult,
  GmbStats,
} from "@/lib/gmb";

export const GMB_POSTS_KEY = ["gmb", "posts"] as const;
export const GMB_STATS_KEY = ["gmb", "posts", "stats"] as const;

/** The GBP post board (created_at desc). */
export function useGmbPosts() {
  return useQuery({
    queryKey: GMB_POSTS_KEY,
    queryFn: () => api.get<GmbPost[]>("/gmb/posts"),
  });
}

export function useGmbStats() {
  return useQuery({
    queryKey: GMB_STATS_KEY,
    queryFn: () => api.get<GmbStats>("/gmb/posts/stats"),
  });
}

// POST /gmb/posts body (GmbPostCreate - populate_by_name, so postType/ctaType/ctaUrl
// are the aliases). The server snapshots the client, drafts + policy-checks the post,
// and returns it at the review gate (or a degraded draft).
export type CreateGmbPostInput = {
  client_id: string;
  topic: string;
  postType: GmbPostType;
  ctaType: GmbCtaType;
  ctaUrl: string;
  title: string;
};

export function useCreateGmbPost() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (input: CreateGmbPostInput) => api.post<GmbPost>("/gmb/posts", input),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: GMB_POSTS_KEY });
      void qc.invalidateQueries({ queryKey: GMB_STATS_KEY });
    },
  });
}

// POST /gmb/posts/{code}/review - approve (re-checks the policy hard gate) or reject.
export type ReviewGmbInput = { code: string; action: "approve" | "reject" };

export function useReviewGmbPost() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ code, action }: ReviewGmbInput) =>
      api.post<GmbPost>(`/gmb/posts/${code}/review`, { action }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: GMB_POSTS_KEY });
      void qc.invalidateQueries({ queryKey: GMB_STATS_KEY });
    },
  });
}

// POST /gmb/posts/{code}/publish - the DORMANT publish-to-Google attempt. Always
// returns posted=false with an honest message until the GBP OAuth path is wired.
export function usePublishGmbPost() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (code: string) => api.post<GmbPublishResult>(`/gmb/posts/${code}/publish`),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: GMB_POSTS_KEY });
    },
  });
}
