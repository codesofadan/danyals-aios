"use client";

// ============================================================
// AIOS · Design Replicator data hooks
// Backs the Design Replicator card off POST /replica + GET /replica/{job_id}.
// The mutation queues a rebuild; the job query polls every 4s while the worker
// is moving (queued/running) and stops dead on a terminal state.
// ============================================================

import { useMutation, useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import {
  isReplicaActive,
  type ReplicaCreateInput,
  type ReplicaCreateResponse,
  type ReplicaJob,
} from "@/lib/replica";

export const replicaJobKey = (jobId: string) => ["replica", jobId] as const;

/** Queue a design replication (POST /replica → 202 {job_id, status:"queued"}).
 * retry:0 (the client default) — a queued rebuild must never be double-submitted
 * by a transient retry. The server 400s if owner_confirmed_source is false and
 * 422/400s an SSRF-refused URL; both surface as the ApiError message. */
export function useReplicate() {
  return useMutation({
    mutationFn: (input: ReplicaCreateInput) =>
      api.post<ReplicaCreateResponse>("/replica", input),
  });
}

/** One replica job's live state (GET /replica/{job_id}). Polls every 4s while
 * the job is queued/running, then stops on any terminal state. */
export function useReplicaJob(jobId: string | null) {
  return useQuery({
    queryKey: replicaJobKey(jobId ?? ""),
    queryFn: () => api.get<ReplicaJob>(`/replica/${jobId}`),
    enabled: !!jobId,
    refetchInterval: (query) => {
      const job = query.state.data as ReplicaJob | undefined;
      // No data yet (first fetch in flight) → keep polling; terminal → stop.
      return job && !isReplicaActive(job.status) ? false : 4000;
    },
  });
}
