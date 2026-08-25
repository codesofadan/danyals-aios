"use client";

// ============================================================
// MACRO, one level down - the pillar x subpoint spine.
//
// The subpoint vocabulary comes from the checklists themselves (39 subpoints
// under on-page, 30 technical, 17 off-page, 8 local). It was only 38% populated
// on emitted findings until the registry join landed, which is why this view
// could not previously be trusted.
//
// DEFAULTS TO THE SUBPOINTS THAT HAVE SOMETHING TO SAY. On a real audit this is
// 95 rows, and roughly half are "100 / 0 issues" or "not measured" - a wall that
// buries the ~30 rows an operator actually needs. Hiding them by default is not
// hiding bad news: a clean subpoint and an unmeasured one are both one click
// away, and the counts are stated on the toggle so nothing is silently dropped.
//
// Sorted worst-measured first; unmeasured sinks to the bottom rather than being
// removed, because "we did not check this" is itself something to see.
// ============================================================

import { useMemo, useState } from "react";
import type { Rollup } from "@/lib/auditAltitude";
import {
  coverageLabel,
  isMeasured,
  notMeasuredReason,
  scoreDisplay,
  scoreTone,
} from "@/lib/auditAltitude";

export default function SubpointTable({ rollups }: { rollups: Rollup[] }) {
  const [showAll, setShowAll] = useState(false);

  const all = useMemo(
    () =>
      rollups
        .filter((r) => r.level === "subpoint")
        .slice()
        .sort((a, b) => {
          const am = isMeasured(a);
          const bm = isMeasured(b);
          if (am !== bm) return am ? -1 : 1;
          if (!am) return a.key.localeCompare(b.key);
          return (a.score ?? 0) - (b.score ?? 0);
        }),
    [rollups],
  );

  const withIssues = useMemo(() => all.filter((r) => r.findings_open > 0), [all]);
  const rows = showAll ? all : withIssues;
  const hidden = all.length - withIssues.length;

  if (!all.length) return null;

  return (
    <>
      <div className="alt-sub-bar">
        <span>
          {showAll ? (
            <>Showing all <b>{all.length}</b> subpoints</>
          ) : (
            <>
              Showing the <b>{withIssues.length}</b> subpoints with findings
            </>
          )}
        </span>
        {hidden > 0 ? (
          <button type="button" className="alt-clear" onClick={() => setShowAll(!showAll)}>
            <span className="material-symbols-rounded">
              {showAll ? "unfold_less" : "unfold_more"}
            </span>
            {showAll
              ? "Only subpoints with findings"
              : `Show ${hidden} clean or unmeasured`}
          </button>
        ) : null}
      </div>

      <div className="alt-tbl-wrap">
        <table className="alt-tbl">
          <thead>
            <tr>
              <th>Pillar</th>
              <th>Subpoint</th>
              <th className="num">Score</th>
              <th>Coverage</th>
              <th className="num">Issues</th>
              <th className="num">Occurrences</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => {
              const [pillar, sub] = r.key.split("/");
              const measured = isMeasured(r);
              return (
                <tr key={r.key} className={measured ? "" : "dim"}>
                  <td className="alt-mono">{pillar}</td>
                  <td>{sub}</td>
                  <td className={`num alt-score t-${scoreTone(measured ? r.score : null)}`}>
                    {scoreDisplay(r)}
                  </td>
                  <td className="alt-cov-cell">
                    ran {coverageLabel(r)}
                    {measured ? null : <em> - {notMeasuredReason(r)}</em>}
                  </td>
                  <td className="num">{r.findings_open.toLocaleString()}</td>
                  <td className="num">{r.instances_open.toLocaleString()}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </>
  );
}
