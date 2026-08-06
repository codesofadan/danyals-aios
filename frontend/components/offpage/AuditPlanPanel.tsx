"use client";

// ============================================================
// AIOS · Off-page · Citation audit plan (generic → country → niche)
// Renders the prioritized geo/niche/generic citation audit for a client
// (GET /citation-builder/clients/{id}/audit-plan). Three build-order
// buckets, each directory tagged built|missing. Read-only.
// ============================================================

import { useAuditPlan } from "@/lib/hooks/offpage";
import { AUDIT_PLAN_BUCKETS, TIER_META, type AuditPlanItem } from "@/lib/offpage";
import w from "./Wave4.module.css";

export default function AuditPlanPanel({ clientId }: { clientId?: string }) {
  const planQ = useAuditPlan(clientId);
  const plan = planQ.data;

  if (!clientId) return null;

  return (
    <div style={{ marginTop: 14 }}>
      <div className="op-muted" style={{ marginBottom: 2 }}>
        Citation audit plan — prioritized Generic &rarr; Country &rarr; Niche, each directory built vs missing.
      </div>

      {planQ.isLoading && <div className="op-muted">Building the audit plan…</div>}
      {planQ.isError && (
        <div className="op-muted">
          Couldn&apos;t build the audit plan — {(planQ.error as Error)?.message ?? "try again"}.
        </div>
      )}

      {plan && (
        <>
          <div className={w.rollup}>
            <span>Client: <b>{plan.client}</b></span>
            <span>Market: <b>{plan.market}</b></span>
            <span>Vertical: <b>{plan.resolvedVertical ?? "general only"}</b></span>
          </div>

          <div className={w.planBuckets}>
            {AUDIT_PLAN_BUCKETS.map((b, i) => {
              const rows = plan[b.key];
              const built = rows.filter((r) => r.status === "built").length;
              return (
                <div key={b.key} className={w.planBucket}>
                  <div className={w.planBucketH}>
                    <span className={w.planNum}>{i + 1}</span>
                    <span className={w.planLabel}>{b.label}</span>
                    <span className={w.planCount}>{built}/{rows.length} built</span>
                  </div>
                  <div className={w.planHint}>{b.hint}</div>
                  {rows.length === 0 ? (
                    <div className={w.planEmpty}>No directories in this bucket.</div>
                  ) : (
                    <div className={w.planRows}>
                      {rows.map((d, j) => (
                        <PlanRow key={`${d.directoryName}-${j}`} item={d} />
                      ))}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </>
      )}
    </div>
  );
}

function PlanRow({ item }: { item: AuditPlanItem }) {
  const built = item.status === "built";
  const name = item.url ? (
    <a className={w.planName} href={item.url} target="_blank" rel="noreferrer">{item.directoryName}</a>
  ) : (
    <span className={w.planName}>{item.directoryName}</span>
  );
  return (
    <div className={w.planRow}>
      <span className="material-symbols-rounded" style={{ fontSize: 16, color: built ? "var(--ok)" : "var(--muted-2)" }}>
        {built ? "check_circle" : "radio_button_unchecked"}
      </span>
      {name}
      <span className={w.planTier}>{TIER_META[item.tier].label}</span>
      <span className={`status-pill ${built ? "ok" : "mut"}`}>{built ? "Built" : "Missing"}</span>
    </div>
  );
}
