"use client";

import { useMemo, useRef, useState } from "react";
import {
  workbooks as seedWorkbooks,
  syncActivity as seedActivity,
  type Workbook,
  type SyncEvent,
} from "@/lib/reports";
import ReportsKpis from "./ReportsKpis";
import WorkbooksTable from "./WorkbooksTable";
import SheetsConnection from "./SheetsConnection";
import ReportTypes from "./ReportTypes";
import SyncActivity from "./SyncActivity";

let seq = 0;
const nextId = () => `s-live-${Date.now().toString(36)}${seq++}`;

export default function ReportsWorkspace() {
  const [books, setBooks] = useState<Workbook[]>(seedWorkbooks);
  const [log, setLog] = useState<SyncEvent[]>(seedActivity);
  const [syncing, setSyncing] = useState<Set<string>>(new Set());
  const [lastSync, setLastSync] = useState("4m ago");
  const timers = useRef<number[]>([]);

  const rowsToday = useMemo(() => books.reduce((s, b) => s + b.rows, 0), [books]);
  const health = useMemo(() => {
    const errors = books.filter((b) => b.status === "error").length;
    return Math.max(90, 100 - errors * 2);
  }, [books]);

  function runSync(id: string) {
    const wb = books.find((b) => b.id === id);
    if (!wb || syncing.has(id)) return;

    // optimistic: flip to syncing + freshen the clock immediately
    setSyncing((prev) => new Set(prev).add(id));
    setLastSync("just now");

    const added = 24 + wb.tabs.length * 18; // rows this push writes
    const t = window.setTimeout(() => {
      setBooks((prev) =>
        prev.map((b) =>
          b.id === id
            ? { ...b, status: "synced", lastSync: "just now", rows: b.rows + added }
            : b
        )
      );
      setLog((prev) => [
        { id: nextId(), client: wb.client, dataset: wb.tabs[0], rows: added, ago: "just now" },
        ...prev,
      ]);
      setSyncing((prev) => {
        const next = new Set(prev);
        next.delete(id);
        return next;
      });
    }, 950);
    timers.current.push(t);
  }

  function syncAll() {
    books.forEach((b, i) => {
      if (!syncing.has(b.id)) {
        const t = window.setTimeout(() => runSync(b.id), i * 180);
        timers.current.push(t);
      }
    });
  }

  return (
    <>
      <ReportsKpis workbooks={books.length} lastSync={lastSync} rowsToday={rowsToday} health={health} />

      <div className="row">
        <WorkbooksTable workbooks={books} syncing={syncing} onSync={runSync} onSyncAll={syncAll} />
        <SheetsConnection />
      </div>

      <div className="row">
        <SyncActivity log={log} />
        <ReportTypes />
      </div>
    </>
  );
}
