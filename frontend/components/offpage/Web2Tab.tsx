"use client";

import { useMemo, useState } from "react";
import { PLATFORM_META, type Web2PipelineStatus, type Web2Platform, type Web2Verified } from "@/lib/offpage";
import { useApproveWeb2, useWeb2 } from "@/lib/hooks/offpage";
import Web2PlanModal from "./Web2PlanModal";

type FilterKey = "all" | Web2Verified;

const FILTERS: { key: FilterKey; label: string }[] = [
  { key: "all", label: "All" },
  { key: "verified", label: "Verified" },
  { key: "pending", label: "Pending" },
];

const PIPELINE_META: Record<Web2PipelineStatus, { label: string; cls: string }> = {
  draft: { label: "Drafting", cls: "mut" },
  needs_review: { label: "Needs review", cls: "warn" },
  publishing: { label: "Publishing", cls: "info" },
  published: { label: "Published", cls: "ok" },
  failed: { label: "Failed", cls: "op-crit" },
  rejected: { label: "Rejected", cls: "mut" },
};

export default function Web2Tab() {
  const [filter, setFilter] = useState<FilterKey>("all");
  const web2Q = useWeb2();
  const web2Properties = web2Q.data ?? [];
  const approve = useApproveWeb2();
  const [showPlan, setShowPlan] = useState(false);
  const [flash, setFlash] = useState<string | null>(null);

  const rows = useMemo(
    () => web2Properties.filter((w) => filter === "all" || w.verified === filter),
    [web2Properties, filter],
  );
  const needsReviewCount = web2Properties.filter((w) => w.status === "needs_review").length;

  function act(id: string, action: "approve" | "reject") {
    approve.mutate(
      { id, action },
      {
        onSuccess: () => {
          setFlash(action === "approve" ? "Approved — publishing now." : "Rejected.");
          window.setTimeout(() => setFlash(null), 3200);
        },
        onError: (err) => {
          setFlash(`${action === "approve" ? "Approve" : "Reject"} failed — ${(err as Error)?.message ?? "try again"}.`);
          window.setTimeout(() => setFlash(null), 3200);
        },
      },
    );
  }

  return (
    <div className="panel-in">
      <div className="panel-h">
        <div className="panel-hint">
          <span className="material-symbols-rounded">rocket_launch</span>
          Branded articles published via official platform APIs — link verified live.
        </div>
        <div className="op-toolset">
          <div className="seg">
            {FILTERS.map((f) => (
              <button key={f.key} className={filter === f.key ? "on" : undefined} onClick={() => setFilter(f.key)}>
                {f.label}
              </button>
            ))}
          </div>
          <button className="primary-btn" onClick={() => setShowPlan(true)}>
            <span className="material-symbols-rounded">add</span>
            Plan property
          </button>
        </div>
      </div>

      {needsReviewCount > 0 && (
        <div className="op-flash" style={{ position: "static" }}>
          <span className="material-symbols-rounded">hourglass_top</span>
          {needsReviewCount} propert{needsReviewCount > 1 ? "ies" : "y"} awaiting a lead&apos;s review below.
        </div>
      )}
      {showPlan && <Web2PlanModal onClose={() => setShowPlan(false)} />}
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
              <th>Platform</th>
              <th>Post URL</th>
              <th>Anchor</th>
              <th>Verified</th>
              <th>Stage</th>
              <th>Published</th>
            </tr>
          </thead>
          <tbody>
            {web2Q.isLoading && (
              <tr><td colSpan={7} className="op-empty">Loading placements…</td></tr>
            )}
            {web2Q.isError && !web2Q.isLoading && (
              <tr><td colSpan={7} className="op-empty">Couldn&apos;t load placements — {(web2Q.error as Error)?.message ?? "try again"}.</td></tr>
            )}
            {!web2Q.isLoading && !web2Q.isError && rows.map((w) => {
              const pm = PLATFORM_META[w.platform as Web2Platform];
              // Fallback for any status the backend emits that isn't in the map
              // (e.g. blocked/unchanged/error/skipped) — never crash the page.
              const pipeline = PIPELINE_META[w.status] ?? { label: w.status, cls: "mut" };
              return (
                <tr key={w.id}>
                  <td className="op-strong">{w.client}</td>
                  <td>
                    <span className="op-plat">
                      <span className="op-plat-ic" style={{ background: pm.c }}>
                        <span className="material-symbols-rounded">{pm.icon}</span>
                      </span>
                      {w.platform}
                    </span>
                  </td>
                  <td>
                    {w.postUrl ? (
                      <a className="op-url" href={`https://${w.postUrl}`} target="_blank" rel="noreferrer">
                        {w.postUrl}<span className="material-symbols-rounded">open_in_new</span>
                      </a>
                    ) : (
                      <span className="op-muted">— not yet published —</span>
                    )}
                  </td>
                  <td><span className="op-anchor">{w.anchor}</span></td>
                  <td>
                    {w.verified === "verified" ? (
                      <span className="status-pill ok">
                        <span className="material-symbols-rounded op-pill-ic">verified</span>Verified
                      </span>
                    ) : (
                      <span className="status-pill info">
                        <span className="material-symbols-rounded op-pill-ic">hourglass_top</span>Pending
                      </span>
                    )}
                  </td>
                  <td>
                    {w.status === "needs_review" ? (
                      <div className="op-toolset" style={{ gap: 6 }}>
                        <button className="op-act update" onClick={() => act(w.id, "approve")} disabled={approve.isPending}>
                          <span className="material-symbols-rounded">check</span>Approve
                        </button>
                        <button className="ghostbtn" onClick={() => act(w.id, "reject")} disabled={approve.isPending}>
                          <span className="material-symbols-rounded">close</span>Reject
                        </button>
                      </div>
                    ) : (
                      <span className={`status-pill ${pipeline.cls}`}>{pipeline.label}</span>
                    )}
                  </td>
                  <td className="op-muted">{w.published}</td>
                </tr>
              );
            })}
            {!web2Q.isLoading && !web2Q.isError && rows.length === 0 && (
              <tr><td colSpan={7} className="op-empty">No placements match this filter.</td></tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
