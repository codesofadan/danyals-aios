"use client";

import { useMemo, useState } from "react";
import {
  JOB_TYPE_META, PROVIDERS, usd,
  type CostEntry, type JobType,
} from "@/lib/cost";

type Props = { log: CostEntry[] };
type Filter = "all" | JobType;

const FILTERS: { key: Filter; label: string }[] = [
  { key: "all", label: "All" },
  { key: "audit", label: "Audit" },
  { key: "content", label: "Content" },
  { key: "backlinks", label: "Backlinks" },
];

export default function CostLog({ log }: Props) {
  const [filter, setFilter] = useState<Filter>("all");

  const rows = useMemo(
    () => (filter === "all" ? log : log.filter((r) => r.type === filter)),
    [log, filter],
  );
  const shown = rows.reduce((s, r) => s + r.cost, 0);
  const cachedCount = rows.filter((r) => r.cached).length;

  return (
    <section className="card cst-log">
      <div className="card-h">
        <div>
          <div className="ct">Cost Log</div>
          <div className="cs">Every gated call, logged per job — cached hits cost nothing.</div>
        </div>
        <div className="tools">
          <div className="log-filters">
            {FILTERS.map((f) => (
              <button
                key={f.key}
                className={filter === f.key ? "chip on" : "chip"}
                onClick={() => setFilter(f.key)}
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
              const jt = JOB_TYPE_META[r.type];
              const pv = PROVIDERS[r.provider];
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
                      {r.provider}
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
          </tbody>
        </table>
      </div>

      <div className="cst-budget-foot">
        <span>{rows.length} calls · <b>{cachedCount}</b> served from cache</span>
        <span className="cst-foot-hint">Logged spend <b>{usd(shown, 2)}</b></span>
      </div>
    </section>
  );
}
