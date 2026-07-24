"use client";

import { GROUP_COLOR } from "@/lib/data";
import type { Cell, Tool } from "@/lib/tools";
import EmptyState from "@/components/ui/EmptyState";
import { getToolActions } from "./tools/registry";

function CellView({ cell }: { cell: Cell }) {
  if (typeof cell === "string") return <>{cell}</>;
  return <span className={`status-pill ${cell.tone}`}>{cell.v}</span>;
}

export default function ToolWorkspace({ tool }: { tool: Tool }) {
  const c = GROUP_COLOR[tool.group];
  // The 8 Part-8 modules have a real, callable action panel; the other 9 tools are
  // live readouts (their fetched KPIs/table below ARE the view) and have none.
  const Actions = getToolActions(tool.slug);

  return (
    <div className="tw portal tool-ws">
      <section className="tool-hero" style={{ ["--c" as string]: c }}>
        <span className="tool-medallion"><span className="material-symbols-rounded">{tool.icon}</span></span>
        <div className="tool-hero-id">
          <div className="tool-hero-eyebrow">{tool.group} · Tool</div>
          <div className="tool-hero-name">{tool.label}</div>
          <div className="tool-hero-tag">{tool.desc}</div>
        </div>
        <div className="tool-hero-side">
          <span className="tool-granted"><span className="material-symbols-rounded">verified_user</span>Access granted</span>
        </div>
      </section>

      {/* The working controls — a real form that calls this tool's live endpoints. */}
      {Actions && <Actions accent={c} />}

      {tool.kpis.length > 0 ? (
        <section className="kpis tool-kpis">
          {tool.kpis.map((k) => (
            <div key={k.label} className="kpi">
              <div className="lab">{k.label}</div>
              <div className="val">{k.value}</div>
              {k.delta && (
                <div className="sub">
                  <span className={`delta ${k.dir}`}>
                    <span className="material-symbols-rounded">{k.dir === "up" ? "trending_up" : "trending_down"}</span>
                    {k.delta}
                  </span>{" "}vs. last period
                </div>
              )}
            </div>
          ))}
        </section>
      ) : (
        <section className="card">
          <EmptyState
            icon="monitoring"
            title="No current data"
            hint="This tool has no records yet — its live metrics will appear here as work runs through it."
          />
        </section>
      )}

      {tool.table && (
        <div className="row-single">
          <section className="card">
            <div className="card-h">
              <div>
                <div className="ct">{tool.table.title}</div>
                <div className="cs">Live view — updates as you work.</div>
              </div>
              <div className="tools">
                <span className="material-symbols-rounded" style={{ color: c, fontSize: 22 }}>{tool.table.icon}</span>
              </div>
            </div>
            {tool.table.rows.length > 0 ? (
              <div className="tbl-wrap">
                <table className="tbl">
                  <thead>
                    <tr>{tool.table.cols.map((col, i) => <th key={col} className={i === 0 ? undefined : "num"}>{col}</th>)}</tr>
                  </thead>
                  <tbody>
                    {tool.table.rows.map((row, ri) => (
                      <tr key={ri}>
                        {row.map((cell, ci) => (
                          <td key={ci} className={ci === 0 ? "tool-cell-1" : "num"}><CellView cell={cell} /></td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <EmptyState icon="table_rows" title="No records yet" hint="Nothing to show here yet — records will appear once this tool has activity." compact />
            )}
          </section>
        </div>
      )}
    </div>
  );
}
