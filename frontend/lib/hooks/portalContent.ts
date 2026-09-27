"use client";

// ============================================================
// AIOS · client-portal CONTENT hooks (/portal/content, /portal/experience)
//
// WHAT WAS MISSING. The pipeline can halt a page because it needs a fact only the business
// owner has — a licence number, how many vans they run, what a real job taught them. The
// backend has asked the client for that since 0155/0156, and there was no screen for them
// to answer on: the questions reached them by someone copying a job code into a message.
//
// The tenant is pinned SERVER-SIDE from the session on every route here — there is no
// client_id in any path or body, and a code belonging to another client answers 404, the
// same as one that does not exist. So nothing in this file needs to (or can) scope a read.
// ============================================================

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";

export const PORTAL_CONTENT_KEY = ["portal", "content"] as const;
export const PORTAL_EXPERIENCE_KEY = ["portal", "experience"] as const;
export const portalExperienceKey = (code: string) => ["portal", "experience", code] as const;

// GET /portal/content → PortalContentJobResponse[] (the client-safe column subset: no
// cost, no model, no internal ids).
export type PortalContentJob = {
  code: string;
  pageType: string;
  topic: string;
  status: string;
  stage: string;
  words: number;
  images: number;
  /** The permalink, once a publish actually reached their site; empty before that. */
  url: string;
  publishAt: string | null;
  createdAt: string;
  updatedAt: string | null;
};

/** One pickable answer, and the words that say where it came from. */
export type PortalExperienceOption = { value: string; evidence: string; kind: string };

export type PortalExperienceSlot = {
  slotKey: string;
  question: string;
  answer: string;
  artifactUrl: string;
  answered: boolean;
  answerEvidence?: string;
  answeredOn?: string;
  source?: string;
  options?: PortalExperienceOption[];
};

export type PortalExperience = {
  code: string;
  /** empty | partial | complete | not_started (the page has not run yet) */
  status: string;
  clusterKey?: string;
  topic?: string;
  slots: PortalExperienceSlot[];
  /** Set by the answer call: whether a completed set actually re-queued the page. */
  resumed?: boolean;
};

/** One page waiting on the client — the portal's own to-do list. */
export type PortalExperienceTodo = {
  code: string;
  topic: string;
  pageType: string;
  status: string;
  stage: string;
  clusterKey: string;
  slots: number;
  answered: number;
};

export type PortalAnswer = {
  slot_key: string;
  answer?: string;
  artifact_url?: string;
  answer_evidence?: string;
};

const inFlight = (j: PortalContentJob) =>
  j.status === "queued" || j.status === "drafting" || j.status === "publishing";

/**
 * The client's own pages. Polls every 5s WHILE one is actually moving, so a page they just
 * unblocked visibly progresses — and stops polling the moment nothing is in flight.
 */
export function useClientContent() {
  return useQuery({
    queryKey: PORTAL_CONTENT_KEY,
    queryFn: () => api.get<PortalContentJob[]>("/portal/content"),
    refetchInterval: (q) => ((q.state.data ?? []).some(inFlight) ? 5_000 : false),
  });
}

/** Every page of theirs that is waiting on their answers. */
export function useClientExperienceTodo() {
  return useQuery({
    queryKey: PORTAL_EXPERIENCE_KEY,
    queryFn: () => api.get<PortalExperienceTodo[]>("/portal/experience"),
  });
}

/** The questions for one of their pages, with options drawn from their own evidence. */
export function useClientExperience(code: string | null) {
  return useQuery({
    queryKey: portalExperienceKey(String(code)),
    queryFn: () => api.get<PortalExperience>(`/portal/experience/${code}`),
    enabled: Boolean(code),
  });
}

/**
 * Record the client's answers. A complete set resumes the held page server-side, so both
 * the to-do list and the page list change — hence both are invalidated, not just this one.
 */
export function useAnswerClientExperience(code: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (answers: PortalAnswer[]) =>
      api.put<PortalExperience>(`/portal/experience/${code}`, { answers }),
    onSuccess: (fresh) => {
      qc.setQueryData(portalExperienceKey(code), fresh);
      void qc.invalidateQueries({ queryKey: PORTAL_EXPERIENCE_KEY });
      void qc.invalidateQueries({ queryKey: PORTAL_CONTENT_KEY });
    },
  });
}
