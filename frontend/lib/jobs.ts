// ============================================================
// AIOS · Job contract — WIRE TYPES + display metadata.
// Mirrors backend `app/schemas/jobs.py` one-for-one: the Python attributes are
// snake_case with a `serialization_alias`, so the JSON is camelCase and drops
// straight into these types with no field mapping.
//
// THE VOCABULARY IS THE PRODUCT. Two rules this file exists to protect:
//
//   1. `succeeded` is computed SERVER-SIDE by `app.jobs.status.is_success`, which
//      is True for `completed` and NOTHING else. Never re-derive success from a
//      status string in a component — read the flag. `degraded` is not success:
//      a job that published two of ten pages did not keep its promise, and the
//      moment it is allowed to look like it did, the operator stops looking.
//   2. `reason` / `reasonCode` are GUARANTEED non-empty on `degraded` and
//      `blocked` (DB CHECK `job_runs_reason_required_ck`), so a degraded run
//      ALWAYS has a true explanation to render. Render it. "Partially succeeded"
//      with no reason is not a state this API can emit, and must not be a state
//      the board can display.
//
// Same for `needsAttention` (degraded | blocked | failed) — on the wire, computed
// once, not spelled out again per screen.
// ============================================================

// --- the ONE status vocabulary ----------------------------------------------
// Mirrors `public.job_status` / `app.jobs.status.JobStatus`. Seven words, every
// module reports in them, and the whole value is in the distinctions:
//   completed  the promise was kept
//   degraded   it finished but part of the promise was NOT kept
//   blocked    it deliberately did not spend (gate, missing credential, cap)
//   failed     it hit an error it could not recover from
//   cancelled  a human stopped it
export type JobStatus =
  | "queued"
  | "running"
  | "completed"
  | "degraded"
  | "blocked"
  | "failed"
  | "cancelled";

// --- one run of one logical unit of background work -------------------------
export type JobRun = {
  id: string;
  jobName: string;
  task: string;
  queue: string;
  status: JobStatus;

  /** The ONE definition of success, computed server-side. Do NOT re-derive it. */
  succeeded: boolean;
  /** True for degraded | blocked | failed — the three an operator must act on. */
  needsAttention: boolean;

  clientId: string | null;
  clientName: string;
  scopeType: string;
  scopeId: string | null;

  attempt: number;
  maxAttempts: number;

  detail: string;
  /** Non-empty whenever status is degraded or blocked (DB CHECK). Always show it. */
  reason: string;
  /** The machine-readable half of `reason`: a stable snake_case id to group by. */
  reasonCode: string;
  errorType: string;
  errorMessage: string;

  costUsd: number;

  /** Reassembles a fan-out: one nightly sweep and its 80 per-client jobs share it. */
  correlationId: string;
  parentRunId: string | null;
  idempotencyKey: string | null;

  createdAt: string | null;
  startedAt: string | null;
  finishedAt: string | null;
  /** The liveness signal the reaper reads — a stale heartbeat is a reclaimed run. */
  heartbeatAt: string | null;
  scheduledFor: string | null;
  /** Cancellation is COOPERATIVE: this flag is set, the job stops at a checkpoint. */
  cancelRequested: boolean;
  durationSeconds: number | null;

  result: Record<string, unknown> | null;
};

// --- a unit of work the platform ACCEPTED and did not deliver ---------------
// The most operationally important object on the board: it carries the payload,
// so the work is not lost — it is replayable.
export type DeadLetterPayload = {
  args?: unknown[];
  kwargs?: Record<string, unknown>;
};

export type DeadLetter = {
  id: string;
  runId: string | null;
  jobName: string;
  task: string;
  queue: string;
  clientId: string | null;
  clientName: string;
  scopeType: string;
  scopeId: string | null;
  correlationId: string | null;
  idempotencyKey: string | null;

  attempts: number;
  /** Carried from the run so the queue groups by CAUSE, not just by job name. */
  reasonCode: string;
  errorType: string;
  errorMessage: string;
  /** Sanitized traceback. Staff-only; secrets are redacted before it is stored. */
  traceback: string;
  /** Everything needed to replay it: {"args": [...], "kwargs": {...}}. */
  payload: DeadLetterPayload;

  deadLetteredAt: string | null;
  firstFailedAt: string | null;
  replayedAt: string | null;
  replayedRunId: string | null;
  resolvedAt: string | null;
  resolution: string;
  /** Still awaiting a human decision — the actual queue. */
  open: boolean;
};

// --- the operator headline over a window ------------------------------------
export type JobStatusCount = {
  status: JobStatus;
  runs: number;
  costUsd: number;
  /** Server-computed: true on the `completed` line and no other. */
  succeeded: boolean;
};

export type JobSummary = {
  windowHours: number;
  /** `degraded` is its own line here and is NEVER folded into a success count. */
  byStatus: JobStatusCount[];
  totalRuns: number;
  /** completed only. */
  succeededRuns: number;
  /** degraded + blocked + failed. */
  needsAttentionRuns: number;
  totalCostUsd: number;
  openDeadLetters: number;
};

// --- what the per-client concurrency cap is currently acting on -------------
// The answer to "why is that client's work not starting": a client at its cap on
// a queue has its next job deferred, then honestly `blocked` — never started.
export type InFlightRow = {
  clientId: string | null;
  clientName: string;
  queue: string;
  running: number;
};

// --- the result of re-running a dead letter ---------------------------------
export type ReplayResult = {
  deadLetterId: string;
  runId: string;
  messageId: string;
  /** `replay:<deadLetterId>` — deliberately NOT the original key, or the replay
   *  would find the old terminal run, skip the work, and look like it succeeded. */
  idempotencyKey: string;
};

// Aliases under the backend model names, so an import written against either
// vocabulary compiles. Same types, no second definition to drift.
export type JobRunResponse = JobRun;
export type DeadLetterResponse = DeadLetter;
export type JobSummaryResponse = JobSummary;
export type InFlightResponse = InFlightRow;
export type ReplayResponse = ReplayResult;

// --- filters for GET /jobs/runs ---------------------------------------------
// Query aliases exactly as the router declares them (status/jobName/clientId/
// correlationId/needsAttention + the shared limit/offset page window, capped at
// 200 server-side).
export type JobRunFilters = {
  status?: JobStatus;
  jobName?: string;
  clientId?: string;
  correlationId?: string;
  /** The view that matters day to day: every terminal run that was not clean. */
  needsAttention?: boolean;
  limit?: number;
  offset?: number;
};

// ---------------------------------------------------------------------------
// Display metadata
// ---------------------------------------------------------------------------
// FOUR tones, and the mapping is load-bearing:
//   ok    the promise was kept        → completed, and nothing else
//   warn  a human must decide         → degraded, blocked
//   bad   it broke                    → failed
//   idle  no verdict (yet, or ever)   → queued, running, cancelled
// `degraded` and `blocked` deliberately DO NOT read as ok. That is the entire
// reason the vocabulary distinguishes them from `completed`.
export type JobTone = "ok" | "warn" | "bad" | "idle";

export type JobStatusMeta = {
  label: string;
  tone: JobTone;
  /** Material Symbols name, matching the rest of the dashboard's meta maps. */
  icon: string;
};

export const JOB_STATUS_META: Record<JobStatus, JobStatusMeta> = {
  queued:    { label: "Queued",    tone: "idle", icon: "schedule" },
  running:   { label: "Running",   tone: "idle", icon: "autorenew" },
  completed: { label: "Completed", tone: "ok",   icon: "check_circle" },
  // Finished, promise partly unkept. Amber, never green — and never without its reason.
  degraded:  { label: "Degraded",  tone: "warn", icon: "warning" },
  // Deliberately did not spend (gate / missing credential / cap). Not an error, not a win.
  blocked:   { label: "Blocked",   tone: "warn", icon: "block" },
  failed:    { label: "Failed",    tone: "bad",  icon: "error" },
  cancelled: { label: "Cancelled", tone: "idle", icon: "cancel" },
};

/** Display order for the summary strip: what worked, then what needs a human,
 *  then what is still moving. */
export const JOB_STATUSES: JobStatus[] = [
  "completed",
  "degraded",
  "blocked",
  "failed",
  "running",
  "queued",
  "cancelled",
];

const TERMINAL_STATUSES: ReadonlySet<string> = new Set<string>([
  "completed",
  "degraded",
  "blocked",
  "failed",
  "cancelled",
]);

/** True when nothing further will happen to the run (mirrors `jobs.status.TERMINAL`).
 *  Used to stop polling a finished run — NOT a success test; use `run.succeeded`. */
export function isTerminalStatus(status: JobStatus | string): boolean {
  return TERMINAL_STATUSES.has(String(status));
}

/**
 * Label + tone + icon for a status. TOLERANT by construction: the wire types it
 * as an enum, but `api.get<T>` is an unchecked cast, so a status this build has
 * never heard of must render as an honest neutral chip rather than crash the
 * board (the lesson `providerMeta` in lib/cost.ts was written to remember).
 */
export function statusMeta(status: JobStatus | string): JobStatusMeta {
  const known = (JOB_STATUS_META as Record<string, JobStatusMeta | undefined>)[String(status)];
  if (known) return known;
  const raw = String(status || "").trim();
  return {
    label: raw ? raw[0].toUpperCase() + raw.slice(1).replace(/[_-]+/g, " ") : "Unknown",
    // Neutral, not ok: an unrecognized state has told us nothing, least of all success.
    tone: "idle",
    icon: "help",
  };
}

/**
 * A run's wall-clock duration, from `durationSeconds` (computed server-side from
 * started_at/finished_at). Returns "" for a run that has not finished, so the
 * caller renders its own placeholder rather than a fake "0s".
 */
export function formatDuration(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined || !Number.isFinite(seconds)) return "";
  const s = Math.max(0, seconds);
  if (s < 1) return `${Math.round(s * 1000)}ms`;
  if (s < 10) return `${s.toFixed(1)}s`;
  if (s < 60) return `${Math.round(s)}s`;
  if (s < 3600) {
    const m = Math.floor(s / 60);
    const rest = Math.round(s % 60);
    return rest ? `${m}m ${rest}s` : `${m}m`;
  }
  const h = Math.floor(s / 3600);
  const m = Math.round((s % 3600) / 60);
  return m ? `${h}h ${m}m` : `${h}h`;
}

/**
 * "5m ago" / "in 2h" from an ISO instant. BOTH directions on purpose: a run's
 * `scheduledFor` is in the future, and rendering it as "ago" would be a lie about
 * work that has not happened yet. "" for null/empty/unparseable, so a missing
 * timestamp renders as nothing rather than "Invalid Date".
 */
export { relativeTime } from "@/lib/format";

// --- who may act -------------------------------------------------------------
// Reads need `view_reports` (all six staff roles hold it; a portal client does
// NOT and is 403'd out of the namespace). Cancel / replay / resolve are LEAD
// actions — owner | admin | manager — because replay in particular deliberately
// re-runs work that already spent money once.
//
// The server is the boundary; this is the UX half, so a button that cannot work
// does not invite the click. Compared lowercase: /me serialises a Title-Case role
// while the backend permission check is lowercase.
export const JOB_LEAD_ROLES = ["owner", "admin", "manager"] as const;

export function isLeadRole(role: string | null | undefined): boolean {
  return JOB_LEAD_ROLES.includes(
    String(role ?? "").toLowerCase() as (typeof JOB_LEAD_ROLES)[number],
  );
}
