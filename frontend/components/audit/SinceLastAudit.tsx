"use client";

// What changed since the last audit of this site.
//
// WHY THIS IS THE PANEL AN OPERATOR OPENS FIRST. An audit answers "what is wrong". A
// retainer is renewed on the answer to a different question - "what did you fix" - and
// before this the platform could not answer it at all: two reports side by side is not an
// answer, it is homework for the client.
//
// TWO RULES THIS SCREEN MUST NOT BREAK, both decided server-side and carried in the payload:
//
//   * NOT RE-CHECKED IS NOT FIXED. A finding that vanished because this run did not measure
//     its dimension - a shallower depth, a lapsed provider key, an agent that did not fire -
//     is listed separately and never counted as work completed. It is the one outright lie
//     this feature is capable of telling a client.
//   * A SCORE DELTA IS WITHHELD when the two runs measured different check sets, because
//     subtracting them describes a change in how we looked rather than a change in the site.
//     When it is withheld the reason is printed in its place, and the page-health figure -
//     whose denominator is pages, not checks - is shown either way.

import { useState } from "react";
import {
  useAuditCompare,
  type CompareFinding,
} from "@/lib/hooks/auditAltitudes";
import QueryGuard from "@/components/ui/QueryGuard";

const SEV_CLASS: Record<string, string> = {
  critical: "crit",
  major: "warn",
  minor: "mut",
  info: "mut",
};

function Rows({ items, empty }: { items: CompareFinding[]; empty: string }) {
  if (items.length === 0) return <p className="cs">{empty}</p>;
  return (
    <table className="alt-table">
      <thead>
        <tr>
          <th>Issue</th>
          <th>Severity</th>
          <th className="num">Pages</th>
        </tr>
      </thead>
      <tbody>
        {items.slice(0, 15).map((f) => (
          <tr key={`${f.checkId}-${f.title}`}>
            <td>{f.title}</td>
            <td>
              <span className={`status-pill ${SEV_CLASS[f.severity] ?? "mut"}`}>{f.severity}</span>
            </td>
            <td className="num">
              {f.pages.toLocaleString()}
              {f.pagesDelta ? (
                <span className="cs" style={{ marginLeft: 6 }}>
                  {f.pagesDelta > 0 ? `+${f.pagesDelta}` : f.pagesDelta}
                </span>
              ) : null}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export default function SinceLastAudit({ auditId }: { auditId: string }) {
  const [baseline, setBaseline] = useState<string>("");
  const q = useAuditCompare(auditId, baseline || undefined);
  const data = q.data;
  const counts = data?.counts;

  return (
    <QueryGuard queries={[q]} label="what changed since the last audit" minHeight={140}>
      {data && data.available === false ? (
        // A calm empty state, not an error: a site's first audit has nothing to compare
        // against, and that is a normal thing for this panel to say.
        <div className="card" style={{ padding: "var(--s-7)" }}>
          <div className="ct">No earlier audit of this site</div>
          <p className="cs" style={{ marginTop: 6 }}>{data.reason}</p>
        </div>
      ) : data ? (
        <div className="card" style={{ padding: "var(--s-7)" }}>
          <div className="card-h" style={{ padding: 0, marginBottom: 12 }}>
            <div>
              <div className="ct">What changed since the last audit</div>
              <div className="cs" style={{ marginTop: 4 }}>
                {data.baseline?.when
                  ? `Measured against the audit of ${new Date(data.baseline.when).toLocaleDateString()}`
                  : "Measured against the previous audit of this site"}
                {data.baseline?.depth ? ` (${data.baseline.depth} depth)` : ""}
              </div>
            </div>
            {(data.runs ?? []).length > 2 ? (
              <label className="cs" style={{ display: "flex", gap: 6, alignItems: "center" }}>
                Compare with
                <select value={baseline} onChange={(e) => setBaseline(e.target.value)}>
                  <option value="">Previous audit</option>
                  {(data.runs ?? [])
                    .filter((r) => r.id !== auditId)
                    .map((r) => (
                      <option key={r.id} value={r.id}>
                        {r.when ? new Date(r.when).toLocaleDateString() : r.id.slice(0, 8)}
                        {r.depth ? ` · ${r.depth}` : ""}
                      </option>
                    ))}
                </select>
              </label>
            ) : null}
          </div>

          <div className="alt-head-stats" style={{ marginBottom: 14 }}>
            <div className="alt-hero t-ok">
              <span className="alt-hero-lab">Fixed</span>
              <span className="alt-hero-val">{(counts?.fixed ?? 0).toLocaleString()}</span>
              <span className="alt-hero-sub">no longer found</span>
            </div>
            <div className="alt-hero t-crit">
              <span className="alt-hero-lab">New</span>
              <span className="alt-hero-val">{(counts?.new ?? 0).toLocaleString()}</span>
              <span className="alt-hero-sub">appeared since</span>
            </div>
            <div className="alt-hero">
              <span className="alt-hero-lab">Still open</span>
              <span className="alt-hero-val">{(counts?.persisting ?? 0).toLocaleString()}</span>
              <span className="alt-hero-sub">found in both runs</span>
            </div>
            <div className="alt-hero t-warn">
              <span className="alt-hero-lab">Not re-checked</span>
              <span className="alt-hero-val">{(counts?.unchecked ?? 0).toLocaleString()}</span>
              <span className="alt-hero-sub">this run did not look</span>
            </div>
          </div>

          {/* The score, only where it means something. */}
          {data.scoreDelta !== null && data.scoreDelta !== undefined ? (
            <p className="cs">
              Site score {data.scoreDelta > 0 ? "up" : data.scoreDelta < 0 ? "down" : "unchanged"}{" "}
              {Math.abs(data.scoreDelta)} points ({data.scoreBefore} → {data.scoreAfter}).
            </p>
          ) : data.reason ? (
            <p className="cs">{data.reason}</p>
          ) : null}
          {data.healthBefore !== null && data.healthAfter !== null ? (
            <p className="cs">
              Pages with no critical issue: {data.healthBefore}% → {data.healthAfter}%.
            </p>
          ) : null}

          <h3 style={{ marginTop: 16 }}>Fixed</h3>
          <Rows items={data.fixed ?? []} empty="Nothing from the last audit has gone away." />

          <h3 style={{ marginTop: 16 }}>New since last time</h3>
          <Rows items={data.new ?? []} empty="Nothing new appeared." />

          {(counts?.unchecked ?? 0) > 0 ? (
            <>
              <h3 style={{ marginTop: 16 }}>Not re-checked</h3>
              <p className="cs">
                These are <b>not fixed</b>. This run did not measure the dimension they
                belong to, so nothing can be said about them either way - usually a
                shallower depth or a provider that was not configured.
              </p>
              <Rows items={data.unchecked ?? []} empty="" />
            </>
          ) : null}
        </div>
      ) : null}
    </QueryGuard>
  );
}
