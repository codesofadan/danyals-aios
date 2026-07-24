"use client";

import { useMemo, useState } from "react";
import {
  jobTypeMeta, providerLabel, providerMeta, usd,
  type JobType,
} from "@/lib/cost";
import { useCostLogPage } from "@/lib/hooks/cost";

type Filter = "all" | JobType;

const FILTERS: { key: Filter; label: string }[] = [
  { key: "all", label: "All" },
  { key: "audit", label: "Audit" },
  { key: "content", label: "Content" },
  { key: "backlinks", label: "Backlinks" },
];

const PAGE_SIZE = 25; // default page size (real server pagination, newest-first)

export default function CostLog() {
  const [filter, setFilter] = useState<Filter>("all");
  const [page, setPage] = useState(0); // zero-based page index

  const q = useCostLogPage(page * PAGE_SIZE, PAGE_SIZE);
  const pageRows = q.data ?? [];
  // has-more signal: a full page means there may be another page after it.
  const hasMore = pageRows.length === PAGE_SIZE;

  // The type filter narrows the CURRENT page (server paginates the full log).
  const rows = useMemo(
    () => (filter === "all" ? pageRows : pageRows.filter((r) => r.type === filter)),
    [pageRows, filter],
  );
  const shown = rows.reduce((s, r) => s + r.cost, 0);
  const cachedCount = rows.filter((r) => r.cached).length;

  function changeFilter(f: Filter) {
    setFilter(f);
    setPage(0); // filtering restarts from the newest page
  }

  return (
    <section className="card cst-log">
      <div className="card-h">
        <div>
          <div className="ct">Cost Log</div>
          <div className="cs">Every gated call, logged per job. Cached hits cost nothing.</div>
        </div>
        <div className="tools">
          <div className="log-filters">
            {FILTERS.map((f) => (
              <button
                key={f.key}
                className={filter === f.key ? "chip on" : "chip"}
                onClick={() => changeFilter(f.key)}
              >
                {f.label}
              </button>
            ))}
          </div>
        </div>
      </div>

      <div className="tbl-wrap cst-log-wrap">
        <table className="tbl cst-tbl">
          <thead>
            <tr>
              <th>Job</th>
              <th>Client</th>
              <th>Type</th>
              <th>Provider</th>
              <th>Cached</th>
              <th className="num">Cost</th>
              <th className="num">Time</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r, i) => {
              // Tolerant lookups: the backend logs free-form provider/type
              // strings (audit_engine, serper, ...); never crash on one.
              const jt = jobTypeMeta(r.type);
              const pv = providerMeta(r.provider);
              return (
                <tr key={`${r.id}-${r.provider}-${i}`}>
                  <td><span className="cst-job">{r.id}</span></td>
                  <td className="cst-log-cli">{r.client}</td>
                  <td>
                    <span className={`cst-type ${jt.cls}`}>
                      <span className="material-symbols-rounded">{jt.icon}</span>{jt.label}
                    </span>
                  </td>
                  <td>
                    <span className="cst-prov">
                      <span className="cst-prov-dot" style={{ background: pv.c }} />
                      {providerLabel(r.provider)}
                    </span>
                  </td>
                  <td>
                    {r.cached ? (
                      <span className="cst-cache yes"><span className="material-symbols-rounded">bolt</span>Cached</span>
                    ) : !pv.paid ? (
                      <span className="cst-cache free">Free</span>
                    ) : (
                      <span className="cst-cache no">Live</span>
                    )}
                  </td>
                  <td className={`num cst-cost ${r.cost === 0 ? "zero" : ""}`}>{usd(r.cost, 2)}</td>
                  <td className="num cst-time">{r.time}</td>
                </tr>
              );
            })}
            {rows.length === 0 && (
              <tr>
                <td colSpan={7} className="cst-log-empty">
                  {q.isLoading ? "Loading…" : filter === "all" ? "No gated calls yet." : "No calls of this type on this page."}
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      <div className="cst-budget-foot">
        <span>
          {rows.length} calls on this page · <b>{cachedCount}</b> cached · logged <b>{usd(shown, 2)}</b>
        </span>
        <div className="cst-pager">
          <button
            type="button"
            className="cst-pager-btn"
            onClick={() => setPage((p) => Math.max(0, p - 1))}
            disabled={page === 0 || q.isFetching}
          >
            <span className="material-symbols-rounded">chevron_left</span>Newer
          </button>
          <span className="cst-pager-pos">Page {page + 1}</span>
          <button
            type="button"
            className="cst-pager-btn"
            onClick={() => setPage((p) => p + 1)}
            disabled={!hasMore || q.isFetching}
          >
            Older<span className="material-symbols-rounded">chevron_right</span>
          </button>
        </div>
      </div>
    </section>
  );
}
