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
} from "@/lib/hooks/jobs";
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
    </div>
  );
}
