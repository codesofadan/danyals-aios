"use client";

import { useMemo, useState } from "react";
import { NAP_META, SUBMIT_STATUS_META, type Citation, type NapStatus } from "@/lib/offpage";
import { useActOnCitation, useBulkUpdateCitations, useCitations } from "@/lib/hooks/offpage";
import CitationCampaignModal from "./CitationCampaignModal";

type FilterKey = "all" | NapStatus;

const FILTERS: { key: FilterKey; label: string }[] = [
  { key: "all", label: "All" },
  { key: "consistent", label: "Consistent" },
  { key: "inconsistent", label: "Inconsistent" },
  { key: "missing", label: "Missing" },
];

export default function CitationsTab() {
  const [filter, setFilter] = useState<FilterKey>("all");
  const citationsQ = useCitations();
  const list: Citation[] = citationsQ.data ?? [];
  const bulk = useBulkUpdateCitations();
  const act = useActOnCitation();
  const [flash, setFlash] = useState<string | null>(null);
  const [showCampaign, setShowCampaign] = useState(false);

  // Mark ONE listing handled — Submit a missing one or Update a drifted one.
  function actOnRow(c: Citation) {
    if (act.isPending) return;
    act.mutate(
      { id: c.id, action: c.action },
      {
        onSuccess: () => {
          setFlash(`${c.action === "Submit" ? "Submitted" : "Updated"} ${c.directory} — NAP synced.`);
          window.setTimeout(() => setFlash(null), 3200);
        },
        onError: (err) => {
          setFlash(`${c.action} failed — ${(err as Error)?.message ?? "try again"}.`);
          window.setTimeout(() => setFlash(null), 3200);
        },
      },
    );
  }

  const rows = useMemo(
    () => list.filter((c) => filter === "all" || c.nap === filter),
    [list, filter],
  );

  const inconsistentCount = list.filter((c) => c.nap === "inconsistent").length;

  // Bulk update — push every drifted listing back to consistent (human-approved run).
  // Backend resolves each id to `consistent`, then the list refetches for fresh state.
  function bulkUpdate() {
    if (inconsistentCount === 0 || bulk.isPending) return;
    const ids = list.filter((c) => c.nap === "inconsistent").map((c) => c.id);
    bulk.mutate(ids, {
      onSuccess: () => {
        setFlash(`Reconciled ${inconsistentCount} inconsistent listing${inconsistentCount > 1 ? "s" : ""} — NAP synced.`);
        window.setTimeout(() => setFlash(null), 3200);
      },
      onError: (err) => {
        setFlash(`Bulk update failed — ${(err as Error)?.message ?? "try again"}.`);
        window.setTimeout(() => setFlash(null), 3200);
      },
    });
  }

  return (
    <div className="panel-in">
      <div className="panel-h">
        <div className="panel-hint">
          <span className="material-symbols-rounded">storefront</span>
          Directory listings &amp; NAP consistency — submit new, update drifted.
        </div>
        <div className="op-toolset">
          <div className="seg">
            {FILTERS.map((f) => (
              <button key={f.key} className={filter === f.key ? "on" : undefined} onClick={() => setFilter(f.key)}>
                {f.label}
              </button>
            ))}
          </div>
          <button className="ghostbtn" onClick={bulkUpdate} disabled={inconsistentCount === 0 || bulk.isPending}>
            <span className="material-symbols-rounded">sync</span>
            {bulk.isPending ? "Syncing…" : `Bulk update (${inconsistentCount})`}
          </button>
          <button className="primary-btn" onClick={() => setShowCampaign(true)}>
            <span className="material-symbols-rounded">rocket_launch</span>
            Build citations
          </button>
        </div>
      </div>

      {showCampaign && <CitationCampaignModal onClose={() => setShowCampaign(false)} />}

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
              <th>Directory</th>
              <th>NAP status</th>
              <th>Detail</th>
              <th>State / action</th>
              <th>Submission</th>
            </tr>
          </thead>
          <tbody>
            {citationsQ.isLoading && (
              <tr><td colSpan={6} className="op-empty">Loading citations…</td></tr>
            )}
            {citationsQ.isError && !citationsQ.isLoading && (
              <tr><td colSpan={6} className="op-empty">Couldn&apos;t load citations — {(citationsQ.error as Error)?.message ?? "try again"}.</td></tr>
            )}
            {!citationsQ.isLoading && !citationsQ.isError && rows.map((c) => {
              const meta = NAP_META[c.nap];
              const submitMeta = SUBMIT_STATUS_META[c.submitStatus];
              return (
                <tr key={c.id}>
                  <td className="op-strong">{c.client}</td>
                  <td>
                    <span className="op-dir">
                      <span className="material-symbols-rounded">location_on</span>{c.directory}
                    </span>
                  </td>
                  <td><span className={`status-pill ${meta.cls}`}>{meta.label}</span></td>
                  <td className="op-muted">{c.note}</td>
                  <td>
                    <button
                      className={c.action === "Submit" ? "op-act submit" : "op-act update"}
                      onClick={() => actOnRow(c)}
                      disabled={act.isPending}
                    >
                      <span className="material-symbols-rounded">
                        {c.action === "Submit" ? "add_location_alt" : "edit_location_alt"}
                      </span>{c.action}
                    </button>
                  </td>
                  <td>
                    <span className={`status-pill ${submitMeta.cls}`}>{submitMeta.label}</span>
                    {c.proofUrl && (
                      <a className="op-url" href={c.proofUrl} target="_blank" rel="noreferrer" style={{ marginLeft: 6 }}>
                        <span className="material-symbols-rounded">image</span>
                      </a>
                    )}
                  </td>
                </tr>
              );
            })}
            {!citationsQ.isLoading && !citationsQ.isError && rows.length === 0 && (
              <tr><td colSpan={6} className="op-empty">No citations match this filter.</td></tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
