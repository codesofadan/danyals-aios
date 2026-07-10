"use client";

import { useState } from "react";
import { kbEntries, SEV_META, CAT_META, type Severity, type Category } from "@/lib/policy";

const SEVERITIES: (Severity | "all")[] = ["all", "critical", "major", "minor", "info"];
const CATEGORIES: (Category | "all")[] = ["all", "algorithm", "policy", "technical", "content", "local", "geo"];

export default function KnowledgeBase() {
  const [sev, setSev] = useState<Severity | "all">("all");
  const [cat, setCat] = useState<Category | "all">("all");

  const rows = kbEntries.filter(
    (e) => (sev === "all" || e.severity === sev) && (cat === "all" || e.category === cat)
  );

  return (
    <section className="card pr-kb">
      <div className="card-h">
        <div>
          <div className="ct">Knowledge Base</div>
          <div className="cs">Every change researched into a versioned, deduped, source-cited entry.</div>
        </div>
        <div className="tools">
          <span className="panel-hint"><span className="material-symbols-rounded">library_books</span>{rows.length} of {kbEntries.length}</span>
        </div>
      </div>

      <div className="pr-filters">
        <div className="pr-filter-grp">
          <span className="pr-filter-lab">Severity</span>
          <div className="pr-chips">
            {SEVERITIES.map((s) => (
              <button key={s} className={sev === s ? "chip on" : "chip"} onClick={() => setSev(s)}>
                {s === "all" ? "All" : SEV_META[s].label}
              </button>
            ))}
          </div>
        </div>
        <div className="pr-filter-grp">
          <span className="pr-filter-lab">Category</span>
          <div className="pr-chips">
            {CATEGORIES.map((c) => (
              <button key={c} className={cat === c ? "chip on" : "chip"} onClick={() => setCat(c)}>
                {c === "all" ? "All" : CAT_META[c].label}
              </button>
            ))}
          </div>
        </div>
      </div>

      <div className="tbl-wrap pr-kb-tbl">
        <table className="tbl">
          <thead>
            <tr>
              <th>Severity</th>
              <th>Entry</th>
              <th>Category</th>
              <th>Region</th>
              <th>Source</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((e) => {
              const sm = SEV_META[e.severity];
              const cm = CAT_META[e.category];
              return (
                <tr key={e.id}>
                  <td>
                    <span className={`pr-sev pr-sev-${sm.cls}`}>{sm.label}</span>
                    <span className="pr-ver">{e.version}</span>
                  </td>
                  <td>
                    <div className="pr-kb-title">{e.title}</div>
                    <div className="pr-kb-sum">{e.summary}</div>
                  </td>
                  <td>
                    <span className="pr-cat" style={{ color: cm.color, borderColor: `${cm.color}44`, background: `${cm.color}18` }}>
                      <span className="material-symbols-rounded">{cm.icon}</span>{cm.label}
                    </span>
                  </td>
                  <td>
                    <span className={`pr-region ${e.region}`}>
                      <span className="material-symbols-rounded">{e.region === "global" ? "public" : "flag"}</span>
                      {e.regionLabel}
                    </span>
                  </td>
                  <td>
                    <a className="pr-src-link" href={e.sourceUrl} target="_blank" rel="noreferrer" title={e.sourceName}>
                      {e.sourceName}<span className="material-symbols-rounded">open_in_new</span>
                    </a>
                  </td>
                </tr>
              );
            })}
            {rows.length === 0 && (
              <tr><td colSpan={5}><div className="pr-empty">No entries match these filters.</div></td></tr>
            )}
          </tbody>
        </table>
      </div>
    </section>
  );
}
