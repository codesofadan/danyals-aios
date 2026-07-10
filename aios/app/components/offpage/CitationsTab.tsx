"use client";

import { useMemo, useState } from "react";
import { citations, NAP_META, type Citation, type NapStatus } from "@/lib/offpage";

type FilterKey = "all" | NapStatus;

const FILTERS: { key: FilterKey; label: string }[] = [
  { key: "all", label: "All" },
  { key: "consistent", label: "Consistent" },
  { key: "inconsistent", label: "Inconsistent" },
  { key: "missing", label: "Missing" },
];

export default function CitationsTab() {
  const [filter, setFilter] = useState<FilterKey>("all");
  const [list, setList] = useState<Citation[]>(citations);
  const [flash, setFlash] = useState<string | null>(null);

  const rows = useMemo(
    () => list.filter((c) => filter === "all" || c.nap === filter),
    [list, filter],
  );

  const inconsistentCount = list.filter((c) => c.nap === "inconsistent").length;

  // Bulk update — push every drifted listing back to consistent (human-approved run).
  function bulkUpdate() {
    if (inconsistentCount === 0) return;
    setList((prev) => prev.map((c) =>
      c.nap === "inconsistent" ? { ...c, nap: "consistent", action: "Update", note: "Synced by bulk run" } : c,
    ));
    setFlash(`Reconciled ${inconsistentCount} inconsistent listing${inconsistentCount > 1 ? "s" : ""} — NAP synced.`);
    window.setTimeout(() => setFlash(null), 3200);
  }

  return (
    <div className="panel-in">
      <div className="panel-h">
        <div className="panel-hint">
          <span className="material-symbols-rounded">storefront</span>
          Directory listings &amp; NAP consistency — submit new, update drifted.
        </div>
        <div className="op-toolset">
          <div className="seg">
            {FILTERS.map((f) => (
              <button key={f.key} className={filter === f.key ? "on" : undefined} onClick={() => setFilter(f.key)}>
                {f.label}
              </button>
            ))}
          </div>
          <button className="ghostbtn" onClick={bulkUpdate} disabled={inconsistentCount === 0}>
            <span className="material-symbols-rounded">sync</span>
            Bulk update ({inconsistentCount})
          </button>
        </div>
      </div>

      {flash && (
        <div className="op-flash">
          <span className="material-symbols-rounded">task_alt</span>{flash}
        </div>
      )}

      <div className="tbl-wrap">
        <table className="tbl op-tbl">
          <thead>
            <tr>
              <th>Client</th>
              <th>Directory</th>
              <th>NAP status</th>
              <th>Detail</th>
              <th>State / action</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((c) => {
              const meta = NAP_META[c.nap];
              return (
                <tr key={c.id}>
                  <td className="op-strong">{c.client}</td>
                  <td>
                    <span className="op-dir">
                      <span className="material-symbols-rounded">location_on</span>{c.directory}
                    </span>
                  </td>
                  <td><span className={`status-pill ${meta.cls}`}>{meta.label}</span></td>
                  <td className="op-muted">{c.note}</td>
                  <td>
                    <button className={c.action === "Submit" ? "op-act submit" : "op-act update"}>
                      <span className="material-symbols-rounded">
                        {c.action === "Submit" ? "add_location_alt" : "edit_location_alt"}
                      </span>{c.action}
                    </button>
                  </td>
                </tr>
              );
            })}
            {rows.length === 0 && (
              <tr><td colSpan={5} className="op-empty">No citations match this filter.</td></tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
