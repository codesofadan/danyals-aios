"use client";

import { useMemo, useState } from "react";
import {
  useWorkbooks,
  useSyncEvents,
  useSyncWorkbook,
  useSyncAllWorkbooks,
} from "@/lib/hooks/reports";
import ReportsKpis from "./ReportsKpis";
import WorkbooksTable from "./WorkbooksTable";
import SheetsConnection from "./SheetsConnection";
import ReportTypes from "./ReportTypes";
import SyncActivity from "./SyncActivity";
import ScheduledJobs from "./ScheduledJobs";

export default function ReportsWorkspace() {
  const workbooksQ = useWorkbooks(); // GET /reports/workbooks (freshest sync first)
  const eventsQ = useSyncEvents(); // GET /reports/sync-events
  const syncOne = useSyncWorkbook(); // POST /reports/sync
  const syncAllM = useSyncAllWorkbooks(); // POST /reports/sync-all

  const books = workbooksQ.data ?? [];
  const log = eventsQ.data ?? [];

  // Which workbooks are mid-push. A real sync flips the row to `synced` server-side,
  // so on settle we clear the id and the invalidated queries refetch the fresh state.
  const [syncing, setSyncing] = useState<Set<string>>(new Set());

  const rowsToday = useMemo(() => books.reduce((s, b) => s + b.rows, 0), [books]);
  const health = useMemo(() => {
    const errors = books.filter((b) => b.status === "error").length;
    return Math.max(90, 100 - errors * 2);
  }, [books]);
  // Server returns workbooks freshest-first; the top row's relative time is the clock.
  const lastSync = books[0]?.lastSync ?? "—";

  function runSync(id: string) {
    if (syncing.has(id)) return;
    setSyncing((prev) => new Set(prev).add(id));
    syncOne.mutate(id, {
      onSettled: () =>
        setSyncing((prev) => {
          const next = new Set(prev);
          next.delete(id);
          return next;
        }),
    });
  }

  function syncAll() {
    if (syncAllM.isPending || books.length === 0) return;
    const ids = books.map((b) => b.id);
    setSyncing((prev) => new Set([...prev, ...ids]));
    syncAllM.mutate(undefined, { onSettled: () => setSyncing(new Set()) });
  }

  const workbooksErr = workbooksQ.isError
    ? (workbooksQ.error as Error)?.message ?? "Couldn't load workbooks."
    : null;
  const eventsErr = eventsQ.isError
    ? (eventsQ.error as Error)?.message ?? "Couldn't load sync activity."
    : null;

  return (
    <>
      <ReportsKpis workbooks={books.length} lastSync={lastSync} rowsToday={rowsToday} health={health} />

      <div className="row">
        <WorkbooksTable
          workbooks={books}
          syncing={syncing}
          onSync={runSync}
          onSyncAll={syncAll}
          loading={workbooksQ.isLoading}
          error={workbooksErr}
        />
        <SheetsConnection />
      </div>

      <div className="row">
        <SyncActivity log={log} loading={eventsQ.isLoading} error={eventsErr} />
        <ReportTypes />
      </div>

      <div className="row">
        <ScheduledJobs />
      </div>
    </>
  );
}
