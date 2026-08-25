"use client";

// ============================================================
// MICRO -> NANO - the fix list, and the evidence behind each item.
//
// One card per PROBLEM, not per occurrence. On a real 197-page audit that is 461
// cards standing in for 8,077 rows:
//
//     [major] Image alt text optimization        121 pages
//             One template: /{slug}
//             > expand -> every one of the 121 URLs
//
// Instances load ONLY when a card is opened. A page showing 50 findings must not
// fire 50 requests for evidence nobody asked to see - that is the whole point of
// progressive disclosure here, and it is also what keeps the 8,077-row case fast.
// ============================================================

import { useState } from "react";
import { useFindingInstances } from "@/lib/hooks/auditAltitudes";
import type { Finding } from "@/lib/auditAltitude";
import {
  blastRadius,
  fixScope,
  isTruncated,
  ownerLabel,
  severityTone,
} from "@/lib/auditAltitude";

/**
 * How many problem cards render before the list asks. Rendering all 461 at once
 * produced a 13,000px page - the same wall-of-data failure the altitude model
 * exists to end. The list is read top-down in priority order, so the first
 * screenful is what matters and the rest is one click away. The remaining count
 * is always on the button.
 */
const PAGE = 25;

function InstancePanel({ auditId, finding }: { auditId: string; finding: Finding }) {
  const { data, isLoading, isError } = useFindingInstances(auditId, finding.id);

  if (isLoading) return <div className="alt-inst-note">Loading occurrences...</div>;
  if (isError) return <div className="alt-inst-note err">Could not load occurrences.</div>;

  const items = data?.items ?? [];
  const total = data?.total ?? 0;
  if (!items.length) {
    return <div className="alt-inst-note">No individual occurrences recorded.</div>;
  }

  return (
    <div className="alt-inst">
      <div className="alt-inst-head">
        Showing {items.length.toLocaleString()} of {total.toLocaleString()} occurrence
        {total === 1 ? "" : "s"}
        {total > items.length ? (
          <span className="alt-inst-more">
            {" "}
            - the complete, uncapped list is in <b>instances.csv</b>
          </span>
        ) : null}
      </div>
      <div className="alt-tbl-wrap">
        <table className="alt-tbl alt-tbl-sm">
          <thead>
            <tr>
              <th>URL</th>
              <th>What was observed</th>
            </tr>
          </thead>
          <tbody>
            {items.map((i) => (
              <tr key={i.id}>
                <td className="alt-url">
                  {i.url ? (
                    <a href={i.url} target="_blank" rel="noreferrer noopener">
                      {i.url}
                    </a>
                  ) : (
                    <span className="alt-muted">{i.instance_kind} (no URL)</span>
                  )}
                </td>
                <td className="alt-mono alt-detail">{i.detail || i.observed || "-"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

type Props = { auditId: string; findings: Finding[]; total: number };

export default function FindingList({ auditId, findings, total }: Props) {
  const [openId, setOpenId] = useState<string | null>(null);
  const [shown, setShown] = useState(PAGE);

  if (!findings.length) {
    return (
      <div className="alt-empty">
        <span className="material-symbols-rounded">task_alt</span>
        <p>No findings match this filter.</p>
      </div>
    );
  }

  return (
    <>
      <div className="alt-count">
        <b>{Math.min(shown, findings.length).toLocaleString()}</b> of {total.toLocaleString()} problem
        {total === 1 ? "" : "s"} - each one is a single fix, however many pages it touches
      </div>

      <div className="alt-findings">
        {findings.slice(0, shown).map((f) => {
          const open = openId === f.id;
          const tone = severityTone(f.severity);
          return (
            <div key={f.id} className={`alt-finding t-${tone} ${open ? "open" : ""}`}>
              <button
                type="button"
                className="alt-finding-head"
                onClick={() => setOpenId(open ? null : f.id)}
                aria-expanded={open}
              >
                <span className={`alt-sev t-${tone}`}>{f.severity}</span>

                <span className="alt-finding-main">
                  <span className="alt-finding-name">{f.check_name}</span>
                  <span className="alt-finding-sub">
                    {f.check_id} · {f.pillar} / {f.subcategory} · {fixScope(f)}
                  </span>
                </span>

                <span className="alt-finding-radius">
                  {blastRadius(f)}
                  {isTruncated(f) ? (
                    <em title="A storage cap applied; the CSV holds the full list">
                      {" "}
                      ({f.instances_stored.toLocaleString()} kept)
                    </em>
                  ) : null}
                </span>

                <span className="material-symbols-rounded alt-chev">
                  {open ? "expand_less" : "expand_more"}
                </span>
              </button>

              {open ? (
                <div className="alt-finding-body">
                  {f.remediation ? (
                    <p className="alt-fix">
                      <span className="material-symbols-rounded">build</span>
                      {f.remediation}
                    </p>
                  ) : null}
                  <div className="alt-meta">
                    <span>
                      Owner <b>{ownerLabel(f)}</b>
                    </span>
                    <span>
                      Pages affected <b>{f.pages_affected.toLocaleString()}</b>
                    </span>
                    <span>
                      Detected by <b>{f.automation === "full" ? "measurement" : "AI-assisted"}</b>
                    </span>
                    {f.confidence !== null ? (
                      <span>
                        Confidence <b>{Math.round(f.confidence * 100)}%</b>
                      </span>
                    ) : null}
                  </div>
                  <InstancePanel auditId={auditId} finding={f} />
                </div>
              ) : null}
            </div>
          );
        })}
      </div>

      {findings.length > shown ? (
        <button
          type="button"
          className="alt-more"
          onClick={() => setShown(shown + PAGE)}
        >
          <span className="material-symbols-rounded">expand_more</span>
          Show {Math.min(PAGE, findings.length - shown)} more of{" "}
          {(findings.length - shown).toLocaleString()} remaining
        </button>
      ) : null}
    </>
  );
}
