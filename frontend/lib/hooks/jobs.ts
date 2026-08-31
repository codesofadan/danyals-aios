"use client";

// ============================================================
// AIOS · job-contract data hooks (the Operations board)
// Backs the Operations board off the FastAPI /jobs endpoints — the one place the
// platform can answer WHAT RAN, WHAT FAILED, AND WHAT IT COST. Response shapes are
// contract-locked to lib/jobs.ts (the backend emits camelCase via
// serialization_alias), so the JSON drops straight into the existing types.
//
// AUTH mirrors routers/jobs.py exactly:
//   • reads          → require_perm("view_reports") — every staff role, no client
//   • cancel/replay/resolve → require_role(owner|admin|manager) — LEAD ONLY
// Gate the act buttons on `isLeadRole(me.data?.role)` from lib/jobs.ts; the server
// remains the boundary.
//
// LIVE SURFACES POLL. The summary, the runs board and in-flight refetch every 10s
// so a running job's row moves on its own — an operations board that only updates
// on F5 is a screenshot. The single-run detail polls only until the run reaches a
// terminal state, then stops (the audits.ts idiom).
// ============================================================

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type {
  DeadLetter,
  InFlightRow,
  JobRun,
  JobRunFilters,
  JobSummary,
  ReplayResult,
} from "@/lib/jobs";
import { isTerminalStatus } from "@/lib/jobs";

export const JOBS_KEY = ["jobs"] as const;
export const JOB_SUMMARY_KEY = ["jobs", "summary"] as const;
export const JOB_RUNS_KEY = ["jobs", "runs"] as const;
export const IN_FLIGHT_KEY = ["jobs", "in-flight"] as const;
export const DEAD_LETTERS_KEY = ["jobs", "dead-letters"] as const;

/** The live-board poll. Fast enough that a queued→running→completed hop is seen
 *  while the operator is still looking at the row. */
export const JOBS_POLL_MS = 10_000;

// --- reads -------------------------------------------------------------------

/**
 * The operator headline over a window (GET /jobs/summary?windowHours=).
 *
 * `byStatus` keeps `degraded` as its own line — it is never added to a success
 * count, which is the whole reason the vocabulary distinguishes the two. Read
 * `succeededRuns` (completed only) and `needsAttentionRuns` (degraded + blocked +
 * failed) rather than summing statuses by hand.
 */
export function useJobSummary(windowHours = 24) {
  return useQuery({
    queryKey: [...JOB_SUMMARY_KEY, windowHours] as const,
    queryFn: () => api.get<JobSummary>(`/jobs/summary?windowHours=${windowHours}`),
    refetchInterval: JOBS_POLL_MS,
  });
}

/**
 * The runs board, newest first (GET /jobs/runs).
 *
 * `needsAttention: true` is the day-to-day view: every terminal run that was not a
 * clean success, in one list. `correlationId` reassembles a whole fan-out — one
 * nightly sweep and the eighty per-client jobs it enqueued share one id. The server
 * caps `limit` at 200 and defaults to 50.
 */
export function useJobRuns(filters: JobRunFilters = {}) {
  const params = new URLSearchParams();
  if (filters.status) params.set("status", filters.status);
  if (filters.jobName) params.set("jobName", filters.jobName);
  if (filters.clientId) params.set("clientId", filters.clientId);
  if (filters.correlationId) params.set("correlationId", filters.correlationId);
  if (filters.needsAttention) params.set("needsAttention", "true");
  if (filters.limit !== undefined) params.set("limit", String(filters.limit));
  if (filters.offset !== undefined) params.set("offset", String(filters.offset));
  const qs = params.toString();

  return useQuery({
    queryKey: [...JOB_RUNS_KEY, "list", qs] as const,
    queryFn: () => api.get<JobRun[]>(`/jobs/runs${qs ? `?${qs}` : ""}`),
    refetchInterval: JOBS_POLL_MS,
    // Paging/filtering keeps the previous rows on screen instead of flashing an
    // empty board while the new window loads.
    placeholderData: (prev) => prev,
  });
}

/**
 * ONE run, by id (GET /jobs/runs/{run_id}) — the drawer/detail read.
 *
 * Polls at the live cadence while the run can still change, then stops dead: a
 * finished run is immutable, so re-fetching it forever is pure noise.
 */
export function useJobRun(runId: string) {
  return useQuery({
    queryKey: [...JOB_RUNS_KEY, runId] as const,
    queryFn: () => api.get<JobRun>(`/jobs/runs/${runId}`),
    enabled: Boolean(runId),
    refetchInterval: (query) => {
      const run = query.state.data as JobRun | undefined;
      if (!run) return JOBS_POLL_MS;
      return isTerminalStatus(run.status) ? false : JOBS_POLL_MS;
    },
  });
}

/**
 * Running work per (client, queue) — exactly what the per-client concurrency cap
 * acts on (GET /jobs/in-flight). This is the answer to "why is that client's work
 * not starting": a client at its cap has its next job deferred, and after
 * `max_queue_seconds` honestly blocked rather than deferred forever.
 */
export function useInFlight() {
  return useQuery({
    queryKey: IN_FLIGHT_KEY,
    queryFn: () => api.get<InFlightRow[]>("/jobs/in-flight"),
    refetchInterval: JOBS_POLL_MS,
  });
}

/**
 * Work the platform ACCEPTED and did not deliver (GET /jobs/dead-letters?openOnly=).
 *
 * Open items come OLDEST first — the opposite of every other feed here, and
 * deliberately: the longest-unresolved lost job is the most urgent one, not the
 * least. Each row carries the payload that makes it replayable.
 */
export function useDeadLetters(openOnly = true) {
  return useQuery({
    queryKey: [...DEAD_LETTERS_KEY, openOnly] as const,
    queryFn: () => api.get<DeadLetter[]>(`/jobs/dead-letters?openOnly=${openOnly}`),
  });
}

// --- lead-only mutations -----------------------------------------------------

export type CancelRunInput = {
  runId: string;
  /** Recorded on the activity log (who + why), not on the run row. Max 500 chars. */
  reason?: string;
};

/**
 * Ask a run to stop (POST /jobs/runs/{run_id}/cancel). LEAD ONLY.
 *
 * COOPERATIVE, not a kill: a Celery task cannot be safely torn down part-way
 * through writing to a client's website. This sets a flag — a queued run never
 * starts, a running one stops at its next `ctx.checkpoint()`, and a job that never
 * checkpoints cannot be stopped at all. An already-finished run returns 409 rather
 * than overwriting a real outcome with the fiction "cancelled".
 */
export function useCancelRun() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ runId, reason }: CancelRunInput) =>
      api.post<JobRun>(`/jobs/runs/${runId}/cancel`, { reason: reason ?? "" }),
    onSuccess: () => {
      // ["jobs","runs"] prefix-matches both the list keys and every detail key.
      void qc.invalidateQueries({ queryKey: JOB_RUNS_KEY });
      void qc.invalidateQueries({ queryKey: JOB_SUMMARY_KEY });
      void qc.invalidateQueries({ queryKey: IN_FLIGHT_KEY });
    },
  });
}

/**
 * Re-run a lost unit of work with its original arguments
 * (POST /jobs/dead-letters/{id}/replay). LEAD ONLY.
 *
 * Deliberately re-runs something that already spent money once, so the server makes
 * it safe twice over: the replay gets its OWN idempotency key (`replay:<id>`), and
 * `mark_replayed` only matches a still-open dead letter, so a double click cannot
 * enqueue the work twice (the second returns 409). Returns the new run id
 * immediately — the board can follow the replay from the moment it is accepted.
 */
export function useReplayDeadLetter() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (deadLetterId: string) =>
      api.post<ReplayResult>(`/jobs/dead-letters/${deadLetterId}/replay`),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: DEAD_LETTERS_KEY });
      // A replay creates a real queued run: the board, the headline and the
      // concurrency picture all moved.
      void qc.invalidateQueries({ queryKey: JOB_RUNS_KEY });
      void qc.invalidateQueries({ queryKey: JOB_SUMMARY_KEY });
      void qc.invalidateQueries({ queryKey: IN_FLIGHT_KEY });
    },
  });
}

export type ResolveDeadLetterInput = {
  deadLetterId: string;
  /** REQUIRED and non-blank — enforced by the schema AND a DB CHECK. */
  resolution: string;
};

/**
 * Close a dead letter with a written decision
 * (POST /jobs/dead-letters/{id}/resolve). LEAD ONLY.
 *
 * The resolution text is mandatory on purpose: a queue closed with no reasons
 * written is a graveyard — the next person cannot tell "we fixed the underlying
 * bug" from "we gave up on this one". Send a real sentence, not a placeholder.
 */
export function useResolveDeadLetter() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ deadLetterId, resolution }: ResolveDeadLetterInput) =>
      api.post<DeadLetter>(`/jobs/dead-letters/${deadLetterId}/resolve`, { resolution }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: DEAD_LETTERS_KEY });
      // `openDeadLetters` on the headline just changed.
      void qc.invalidateQueries({ queryKey: JOB_SUMMARY_KEY });
    },
  });
}

export type ReapResult = {
  /** `ok` (nothing to do) or `degraded` (rows were reaped — real work was lost). */
  status: string;
  reaped: number;
  /** Human-readable: "no stale runs", or "reaped run_audit_job x3, run_content_job x1". */
  detail: string;
};

/**
 * Fail every job run whose worker died without writing an outcome
 * (POST /maintenance/reap-stuck-jobs). OWNER ONLY.
 *
 * `JobRunsStore.start` counts `running` rows against the per-client concurrency cap,
 * so a run left `running` by an OOM kill or a host reboot permanently removes a slot
 * from that client — their queue gets quietly narrower and nothing reports it. The
 * reaper is the only thing that clears one.
 *
 * With cron parked (`beat_schedule = {}`), the `reap-stale-job-runs` schedule does not
 * fire, so THIS is the only caller. That is why it needs a button: until this hook
 * existed, unwedging a client's queue meant an owner-token curl.
 *
 * The endpoint runs the sweep INLINE rather than enqueueing it, because dispatching
 * the repair onto the very worker pool that may be wedged is how "I pressed the button
 * and nothing happened" happens. It answers 503 rather than a 200 with a zero count
 * when the ledger is unreachable: "reaped 0" and "could not look" are different
 * answers and only one of them means the queue is healthy.
 */
export function useReapStuckJobs() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api.post<ReapResult>("/maintenance/reap-stuck-jobs"),
    onSuccess: () => {
      // Reaping writes terminal outcomes onto runs the board is showing as running,
      // and frees concurrency slots, so all three of these moved.
      void qc.invalidateQueries({ queryKey: JOB_RUNS_KEY });
      void qc.invalidateQueries({ queryKey: JOB_SUMMARY_KEY });
      void qc.invalidateQueries({ queryKey: IN_FLIGHT_KEY });
    },
  });
}

// --- automations --------------------------------------------------------------
// Scheduled work an admin controls. The fourteen periodic jobs this platform had
// were switched off wholesale on 2026-08-19 because a static beat schedule is read
// at process start: pausing one, re-timing one, or scoping one to some clients each
// needed a deploy. They are rows now (0118), all seeded paused.

export const AUTOMATIONS_KEY = ["automations"] as const;

export type AutomationCapability = {
  kind: string;
  label: string;
  description: string;
  scope: "platform" | "client";
  /** True when a run can spend metered budget. Shown BEFORE anyone enables it. */
  paid: boolean;
  defaultIntervalSeconds: number;
  needs: string[];
};

export type Automation = {
  id: string;
  name: string;
  kind: string;
  kindLabel: string;
  scope: "platform" | "client";
  paid: boolean;
  params: Record<string, unknown>;
  scheduleKind: "interval" | "cron";
  intervalSeconds: number | null;
  cronExpr: string | null;
  /** "every 30 minutes" / "cron: 0 2 * * *" */
  cadence: string;
  enabled: boolean;
  notifyOnFailure: boolean;
  notifyChannels: Record<string, unknown>;
  nextDueAt: string | null;
  lastFiredAt: string | null;
  /** Null before it has ever run - which is not the same as a run that failed. */
  lastRunId: string | null;
  lastStatus: string | null;
  lastFinishedAt: string | null;
  lastDetail: string;
};

export function useAutomations() {
  return useQuery({
    queryKey: AUTOMATIONS_KEY,
    queryFn: () => api.get<Automation[]>("/automations"),
    refetchInterval: JOBS_POLL_MS,
  });
}

export function useAutomationCapabilities() {
  return useQuery({
    queryKey: [...AUTOMATIONS_KEY, "capabilities"] as const,
    queryFn: () => api.get<AutomationCapability[]>("/automations/capabilities"),
    staleTime: Infinity, // a code-level registry; it cannot change under a session
  });
}

export type AutomationInput = {
  name: string;
  kind: string;
  params?: Record<string, unknown>;
  scheduleKind: "interval" | "cron";
  intervalSeconds?: number | null;
  cronExpr?: string | null;
  enabled?: boolean;
  notifyOnFailure?: boolean;
};

export function useCreateAutomation() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (input: AutomationInput) => api.post<Automation>("/automations", input),
    onSuccess: () => void qc.invalidateQueries({ queryKey: AUTOMATIONS_KEY }),
  });
}

/** Edit, pause or resume. Pausing is this call with `enabled: false`. */
export function useUpdateAutomation() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, changes }: { id: string; changes: Partial<AutomationInput> }) =>
      api.patch<Automation>(`/automations/${id}`, changes),
    onSuccess: () => void qc.invalidateQueries({ queryKey: AUTOMATIONS_KEY }),
  });
}

export function useDeleteAutomation() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.del<void>(`/automations/${id}`),
    onSuccess: () => void qc.invalidateQueries({ queryKey: AUTOMATIONS_KEY }),
  });
}

/** Fire it once now without changing its schedule - how an automation is tested
 *  before being enabled, and how a missed window is recovered. */
export function useRunAutomationNow() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) =>
      api.post<{ automationId: string; runId: string | null; dispatched: number }>(
        `/automations/${id}/run`,
        {},
      ),
    onSuccess: () => void qc.invalidateQueries({ queryKey: AUTOMATIONS_KEY }),
  });
}
