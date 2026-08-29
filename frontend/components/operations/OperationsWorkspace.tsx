"use client";

// ============================================================
// AIOS · OPERATIONS — the job board
//
// The three questions the job contract exists to answer, on one screen: WHAT RAN,
// WHAT FAILED, WHAT IT COST. Everything here speaks the backend's single status
// vocabulary (completed · degraded · blocked · failed · cancelled, plus queued and
// running) and never re-derives a verdict the server already computed.
//
// LEAD-ONLY ACTIONS. Cancel, replay and resolve are owner/admin/manager server-side
// (routers/jobs.py's LeadOnly dependency). This is a UX gate only — the backend
// remains the boundary — but a button that cannot work should not invite the click,
// so a non-lead sees the whole board and none of the act buttons. Compared
// case-insensitively: /me serialises Title-Case roles while the permission check is
// lowercase (same treatment as the content review gate).
// ============================================================

import { useState } from "react";
import { useMe } from "@/lib/hooks/portal";
import {
  useDeadLetters,
  useInFlight,
  useJobRuns,
  useJobSummary,
  useReapStuckJobs,
} from "@/lib/hooks/jobs";
import ConfirmDialog from "@/components/ui/ConfirmDialog";
import { useToast } from "@/components/ui/Toast";
import type { JobRun } from "@/lib/jobs";
import JobSummaryTiles, { type WindowHours } from "./JobSummaryTiles";
import InFlightStrip from "./InFlightStrip";
import DeadLetterQueue from "./DeadLetterQueue";
import JobRunsTable, {
  PAGE_SIZE,
  attentionParam,
  statusParam,
  type Filter,
} from "./JobRunsTable";
import JobRunDrawer from "./JobRunDrawer";

const LEAD_ROLES = ["owner", "admin", "manager"];

export default function OperationsWorkspace() {
  const [windowHours, setWindowHours] = useState<WindowHours>(24);
  const [filter, setFilter] = useState<Filter>("all");
  const [jobName, setJobName] = useState("");
  const [page, setPage] = useState(0);
  const [openOnly, setOpenOnly] = useState(true);
  // The run the drawer is showing. `fallback` is the clicked row, so the drawer
  // paints immediately while its own fresh read lands; a replay opens the drawer
  // with no row in hand, and fetches.
  const [drawer, setDrawer] = useState<{ runId: string; fallback: JobRun | null } | null>(null);

  const me = useMe();
  const isLead = LEAD_ROLES.includes((me.data?.role ?? "").toLowerCase());
  // Reaping is OWNER-only server-side, a narrower gate than the lead actions: it
  // writes terminal outcomes onto runs that may still be alive.
  const isOwner = (me.data?.role ?? "").toLowerCase() === "owner";

  const [reapOpen, setReapOpen] = useState(false);
  const reap = useReapStuckJobs();
  const toast = useToast();

  const summaryQ = useJobSummary(windowHours);
  const runsQ = useJobRuns({
    status: statusParam(filter),
    // The Attention chip is a SERVER filter, not a status: degraded + blocked +
    // failed in one list. Without this it silently returned every run and the
    // chip looked like it worked.
    needsAttention: attentionParam(filter),
    jobName: jobName || undefined,
    limit: PAGE_SIZE,
    offset: page * PAGE_SIZE,
  });
  const inFlightQ = useInFlight();
  const deadQ = useDeadLetters(openOnly);

  const readError =
    summaryQ.isError || runsQ.isError || inFlightQ.isError || deadQ.isError
      ? ((summaryQ.error ?? runsQ.error ?? inFlightQ.error ?? deadQ.error) as Error)?.message
      : null;

  return (
    <div className="ops">
      {readError && (
        <div className="cs" role="alert" style={{ color: "var(--warn)", marginBottom: 8 }}>
          Some operations data couldn&apos;t load. {readError ?? "Try again"}.
        </div>
      )}

      <JobSummaryTiles
        summary={summaryQ.data}
        windowHours={windowHours}
        onWindow={setWindowHours}
        loading={summaryQ.isLoading}
      />

      <div className="row-single">
        <InFlightStrip rows={inFlightQ.data ?? []} loading={inFlightQ.isLoading} />
        {/* The reaper sits beside the in-flight strip because that is where its
            problem is VISIBLE: a run left `running` by an OOM kill or a host reboot
            shows here forever and holds a concurrency slot the client never gets
            back. With cron parked this endpoint is the reaper's only caller, and
            until this button existed calling it meant an owner-token curl. */}
        {isOwner && (
          <div className="ops-reap">
            <button
              type="button"
              className="ghostbtn"
              onClick={() => setReapOpen(true)}
              disabled={reap.isPending}
            >
              <span className="material-symbols-rounded">mop</span>
              {reap.isPending ? "Sweeping…" : "Reap stuck runs"}
            </button>
          </div>
        )}
      </div>

      {/* Undelivered work sits ABOVE the log on purpose: the log is the reference,
          this is the to-do list, and a lost job buried under 25 rows of history is a
          lost job nobody replays. */}
      <div className="row-single">
        <DeadLetterQueue
          rows={deadQ.data ?? []}
          loading={deadQ.isLoading}
          openOnly={openOnly}
          onOpenOnly={setOpenOnly}
          canAct={isLead}
          onFollowRun={(runId) => setDrawer({ runId, fallback: null })}
        />
      </div>

      <div className="row-single">
        <JobRunsTable
          rows={runsQ.data ?? []}
          loading={runsQ.isLoading}
          fetching={runsQ.isFetching}
          page={page}
          onPage={setPage}
          filter={filter}
          onFilter={setFilter}
          jobName={jobName}
          onJobName={setJobName}
          onOpenRun={(run) => setDrawer({ runId: run.id, fallback: run })}
        />
      </div>

      {drawer && (
        <JobRunDrawer
          runId={drawer.runId}
          fallback={drawer.fallback}
          canAct={isLead}
          onClose={() => setDrawer(null)}
        />
      )}

      <ConfirmDialog
        open={reapOpen}
        tone="caution"
        title="Reap stuck runs?"
        body={
          <>
            <div>
              Every run whose worker died without writing an outcome will be marked
              failed, and the concurrency slot it was holding is returned to that
              client.
            </div>
            <div style={{ marginTop: "var(--s-5)" }}>
              A run is only reaped once it has stopped sending heartbeats, so live
              work is not affected. Nothing is re-queued: reaping records what was
              lost, it does not retry it. Replay anything worth re-running from the
              dead-letter queue above.
            </div>
          </>
        }
        reassurance="Runs inline, so the answer here is the result — it is not handed to the worker pool that may itself be stuck."
        confirmLabel="Reap stuck runs"
        pending={reap.isPending}
        onCancel={() => setReapOpen(false)}
        onConfirm={() => {
          setReapOpen(false);
          reap.mutate(undefined, {
            // Say WHAT was reaped, not just that something happened: "reaped 0" and
            // "reaped run_audit_job x3" are the difference between a healthy queue
            // and three clients who lost work and need telling.
            onSuccess: (r) =>
              r.reaped > 0
                ? toast.info(`Reaped ${r.reaped} stuck run${r.reaped === 1 ? "" : "s"}`, r.detail)
                : toast.success("No stuck runs", "Every running job is alive and reporting."),
            onError: (e) => toast.fromError("Could not sweep the job ledger", e),
          });
        }}
      />
    </div>
  );
}
