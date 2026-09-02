"use client";

// ============================================================
// AIOS · Design Replicator data hooks
// Backs the Design Replicator card off POST /replica + GET /replica/{job_id}.
// The mutation queues a rebuild; the job query polls every 4s while the worker
// is moving (queued/running) and stops dead on a terminal state.
// ============================================================

import { useMutation, useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type { JobRun } from "@/lib/jobs";
import { isTerminalStatus } from "@/lib/jobs";
import {
  isReplicaActive,
  type ReplicaCreateInput,
  type ReplicaCreateResponse,
  type ReplicaJob,
} from "@/lib/replica";

export const replicaJobKey = (jobId: string) => ["replica", jobId] as const;
export const REPLICA_RUNS_KEY = ["replica", "runs"] as const;

/** The logical job name replica runs are recorded under in the job ledger. */
export const REPLICA_JOB_NAME = "replica.publish";

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

/**
 * Every recent replication for this client, from the JOB LEDGER
 * (GET /jobs/runs?jobName=replica.publish).
 *
 * This is what makes the queue survive a refresh. The card used to hold the job
 * handle in React state alone, so navigating away or reloading discarded the only
 * reference to a job that was still running - the work continued, invisibly, and
 * the operator had no way back to it. The ledger has always been the durable
 * record; nothing on this screen was reading it.
 *
 * Reuses the generic runs endpoint rather than adding a replica-specific list:
 * JobRun already carries the status vocabulary, the timestamps, the reason/error
 * and the worker's result payload (url, preview_url, post_id, sections, widgets,
 * notes), so a second endpoint would only restate it.
 *
 * Polls on the shared cadence while anything is still moving, then stops.
 */
export function useReplicaRuns(clientId: string | null, limit = 10) {
  const params = new URLSearchParams({ jobName: REPLICA_JOB_NAME, limit: String(limit) });
  if (clientId) params.set("clientId", clientId);
  const qs = params.toString();

  return useQuery({
    queryKey: [...REPLICA_RUNS_KEY, qs] as const,
    queryFn: () => api.get<JobRun[]>(`/jobs/runs?${qs}`),
    // 2s while something is MOVING, not 4s. The worker now reports about eight
    // named stages across a 12-60s rebuild; at a 4s cadence roughly half of them
    // were never rendered, which defeats the point of reporting them. Polling
    // stops dead the moment every run is terminal, so this costs nothing on an
    // idle screen.
    refetchInterval: (query) => {
      const rows = query.state.data as JobRun[] | undefined;
      if (!rows) return 2000;
      return rows.some((r) => !isTerminalStatus(r.status)) ? 2000 : false;
    },
    placeholderData: (prev) => prev,
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
