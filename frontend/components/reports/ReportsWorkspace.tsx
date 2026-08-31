"use client";

import { useMemo, useState } from "react";
import {
  useWorkbooks, useSyncEvents, useSyncWorkbook, useSyncAllWorkbooks,
} from "@/lib/hooks/reports";
import ReportsKpis from "./ReportsKpis";
import ReportsLibrary from "./ReportsLibrary";
import SheetsConnection from "./SheetsConnection";
import WorkbooksTable from "./WorkbooksTable";
import SyncActivity from "./SyncActivity";
import ReportTypes from "./ReportTypes";

// Reporting has three distinct audiences, so it has three tabs rather than one long
// scroll: what RUNS on its own, what has been PRODUCED for clients, and the Sheets
// plumbing underneath.
//
// Restored 2026-08-25. The page had been trimmed to Scheduled Jobs alone at the
// operator's request, which left eight `/reports/*` endpoints with no caller and no
// way to see a produced report, a workbook, or whether Sheets was even connected.
// Every panel below was already wired to a live endpoint with its own loading, error
// and empty states — the only thing missing was a route that rendered them.
// "Scheduled jobs" moved to /admin/operations, which already owns job runs, the
// dead-letter queue and in-flight work. Reports keeps what only it does: the produced
// reports themselves and the Sheets sync - both of which feed the CLIENT portal's
// /client/reports, so the page stays.
const TABS = [
  { key: "library", label: "Report library", icon: "summarize" },
  { key: "sheets", label: "Sheets sync", icon: "table_view" },
] as const;

type TabKey = (typeof TABS)[number]["key"];

export default function ReportsWorkspace() {
  const [tab, setTab] = useState<TabKey>("library");

  // The Sheets tab's three panels are presentational; the workspace owns their data
  // so one fetch feeds all of them and a sync refreshes the whole tab at once.
  const workbooksQ = useWorkbooks();
  const eventsQ = useSyncEvents();
  const syncOne = useSyncWorkbook();
  const syncAll = useSyncAllWorkbooks();

  const workbooks = useMemo(() => workbooksQ.data ?? [], [workbooksQ.data]);
  const events = useMemo(() => eventsQ.data ?? [], [eventsQ.data]);

  // A row is "syncing" while its own mutation is in flight, or while a sync-all is.
  const syncing = useMemo(() => {
    if (syncAll.isPending) return new Set(workbooks.map((w) => w.id));
    return new Set(syncOne.isPending && syncOne.variables ? [syncOne.variables] : []);
  }, [syncAll.isPending, syncOne.isPending, syncOne.variables, workbooks]);

  const rowsToday = workbooks.reduce((sum, w) => sum + w.rows, 0);
  const lastSync = workbooks.find((w) => w.lastSync)?.lastSync ?? "—";
  // Health is the share of workbooks not in an error state - derived, never invented.
  const health = workbooks.length
    ? Math.round((workbooks.filter((w) => w.status !== "error").length / workbooks.length) * 100)
    : 0;

  const errText = (e: unknown) => (e instanceof Error ? e.message : null);

  return (
    <>
      <div className="seg rp-tabs" role="tablist" aria-label="Reporting sections">
        {TABS.map((t) => (
          <button
            key={t.key}
            role="tab"
            aria-selected={tab === t.key}
            className={tab === t.key ? "on" : ""}
            onClick={() => setTab(t.key)}
          >
            <span className="material-symbols-rounded">{t.icon}</span>
            {t.label}
          </button>
        ))}
      </div>

      {tab === "library" && (
        <>
          <ReportsKpis
            workbooks={workbooks.length}
            lastSync={lastSync}
            rowsToday={rowsToday}
            health={health}
          />
          <div className="row-single">
            <ReportsLibrary />
          </div>
        </>
      )}

      {tab === "sheets" && (
        <>
          {(syncOne.error || syncAll.error) && (
            <div className="login-error" role="alert">
              <span className="material-symbols-rounded">error</span>
              Couldn&apos;t sync — {errText(syncOne.error) ?? errText(syncAll.error)}
            </div>
          )}
          <div className="row b">
            <SheetsConnection />
            <SyncActivity
              log={events}
              loading={eventsQ.isLoading}
              error={errText(eventsQ.error)}
            />
          </div>
          <div className="row-single">
            <WorkbooksTable
              workbooks={workbooks}
              syncing={syncing}
              onSync={(id) => syncOne.mutate(id)}
              onSyncAll={() => syncAll.mutate()}
              loading={workbooksQ.isLoading}
              error={errText(workbooksQ.error)}
            />
          </div>
          <div className="row-single">
            <ReportTypes />
          </div>
        </>
      )}
    </>
  );
}
