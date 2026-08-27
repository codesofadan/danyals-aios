"use client";

// The Search workspace: the five SEO tool modules as first-class admin screens.
//
// Until now these lived ONLY as RBAC-gated team-portal pages (/team/tools/[slug]),
// so an admin literally could not reach 95 backend operations from the admin
// portal - and five of the modules' mutation hooks had no caller anywhere in the
// product. The action panels are SHARED with the team portal (one registry,
// components/portal/tools/), so a fix or a new action lands in both portals.

import { useRouter } from "next/navigation";
import { useState } from "react";
import { getToolBySlug, type Cell } from "@/lib/tools";
import { useToolWorkspace } from "@/lib/hooks/tools";
import { GROUP_COLOR } from "@/lib/data";
import TabBar, { useUrlTab } from "@/components/ui/TabBar";
import QueryGuard from "@/components/ui/QueryGuard";
import EmptyState from "@/components/ui/EmptyState";
import { getToolActions } from "@/components/portal/tools/registry";
import DataImportActions from "@/components/portal/tools/DataImportActions";

const TABS = [
  { key: "keywords", label: "Keywords", icon: "travel_explore", slug: "keyword-research" },
  { key: "rankings", label: "Rankings", icon: "query_stats", slug: "rank-tracker" },
  { key: "competitors", label: "Competitors", icon: "visibility", slug: "competitor-intel" },
  { key: "on-page", label: "On-Page", icon: "plagiarism", slug: "on-page" },
  { key: "local", label: "Local", icon: "add_location_alt", slug: "local-seo" },
] as const;

function CellView({ cell }: { cell: Cell }) {
  if (typeof cell === "string") return <>{cell}</>;
  return <span className={`status-pill ${cell.tone}`}>{cell.v}</span>;
}

/** One tool's live readout (KPIs + table), admin register: a failed fetch says
 *  so — it never renders the static KPI labels with blank values the way the
 *  portal page degrades, because here nothing else on screen explains a gap. */
function ToolReadout({ slug }: { slug: string }) {
  const q = useToolWorkspace(slug, true);
  return (
    <QueryGuard queries={[q]} label="the tool's live data" minHeight={160}>
      {q.data && (
        <>
          {q.data.kpis.length > 0 ? (
            <section className="kpis" style={{ marginTop: 14 }}>
              {q.data.kpis.map((k) => (
                <div key={k.label} className="kpi">
                  <div className="lab">{k.label}</div>
                  <div className="val">{k.value ?? "—"}</div>
                </div>
              ))}
            </section>
          ) : null}
          {q.data.table && (
            <section className="card" style={{ marginTop: 14 }}>
              <div className="card-h">
                <div>
                  <div className="ct">{q.data.table.title}</div>
                  <div className="cs">Live view — refreshes as actions above complete.</div>
                </div>
              </div>
              {q.data.table.rows.length > 0 ? (
                <div className="tbl-wrap">
                  <table className="tbl">
                    <thead>
                      <tr>{q.data.table.cols.map((c, i) => <th key={c} className={i === 0 ? undefined : "num"}>{c}</th>)}</tr>
                    </thead>
                    <tbody>
                      {q.data.table.rows.map((row, ri) => (
                        <tr key={ri}>
                          {row.map((cell, ci) => (
                            <td key={ci} className={ci === 0 ? undefined : "num"}><CellView cell={cell} /></td>
                          ))}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : (
                <EmptyState icon="monitoring" title="No records yet" hint="Run an action above — its results land here." />
              )}
            </section>
          )}
        </>
      )}
    </QueryGuard>
  );
}

/** Keywords → Content: the bridge between the two halves of the product. The
 *  keyword rides as ?keyword= and the content wizard picks it up as a manual
 *  page (its title IS the primary keyword there), pre-selected. */
function SendToContentCard() {
  const router = useRouter();
  const [kw, setKw] = useState("");
  return (
    <section className="card tool-action-card">
      <div className="card-h">
        <div>
          <div className="ct">Send a keyword to Content</div>
          <div className="cs">Hands the keyword to the content wizard as a ready-selected page.</div>
        </div>
        <div className="tools">
          <span className="material-symbols-rounded" style={{ color: "var(--accent)", fontSize: 22 }}>forward</span>
        </div>
      </div>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          if (kw.trim()) router.push(`/admin/content?keyword=${encodeURIComponent(kw.trim())}`);
        }}
      >
        <div className="fld" style={{ marginTop: 12 }}>
          <label>Keyword</label>
          <input value={kw} onChange={(e) => setKw(e.target.value)} placeholder="water heater repair austin" />
        </div>
        <button type="button" className="ghostbtn wide" style={{ marginTop: 12 }} disabled={!kw.trim()}
          onClick={() => kw.trim() && router.push(`/admin/content?keyword=${encodeURIComponent(kw.trim())}`)}>
          <span className="material-symbols-rounded">forward</span>Draft content for this keyword
        </button>
      </form>
    </section>
  );
}

const TAB_DEFS = TABS.map((t) => ({ key: t.key, label: t.label, icon: t.icon }));

export default function SearchWorkspace() {
  const [tab, setTab] = useUrlTab(TAB_DEFS);
  const active = TABS.find((t) => t.key === tab) ?? TABS[0];
  const tool = getToolBySlug(active.slug);
  const accent = tool ? GROUP_COLOR[tool.group] : "var(--accent)";
  const Actions = getToolActions(active.slug);

  return (
    <div className="tw">
      <TabBar tabs={TAB_DEFS} active={tab} onSelect={setTab} />
      <div style={{ display: "grid", gap: 14, marginTop: 14 }}>
        {Actions && <Actions accent={accent} />}
        {active.key === "keywords" && (
          <>
            <DataImportActions accent={accent} />
            <SendToContentCard />
          </>
        )}
        <ToolReadout slug={active.slug} />
      </div>
    </div>
  );
}
