"use client";

import { useMemo, useState } from "react";
import { PLATFORM_META, type Web2Platform, type Web2Verified } from "@/lib/offpage";
import { useWeb2 } from "@/lib/hooks/offpage";

type FilterKey = "all" | Web2Verified;

const FILTERS: { key: FilterKey; label: string }[] = [
  { key: "all", label: "All" },
  { key: "verified", label: "Verified" },
  { key: "pending", label: "Pending" },
];

export default function Web2Tab() {
  const [filter, setFilter] = useState<FilterKey>("all");
  const web2Q = useWeb2();
  const web2Properties = web2Q.data ?? [];

  const rows = useMemo(
    () => web2Properties.filter((w) => filter === "all" || w.verified === filter),
    [web2Properties, filter],
  );

  return (
    <div className="panel-in">
      <div className="panel-h">
        <div className="panel-hint">
          <span className="material-symbols-rounded">rocket_launch</span>
          Branded articles published via official platform APIs — link verified live.
        </div>
        <div className="seg">
          {FILTERS.map((f) => (
            <button key={f.key} className={filter === f.key ? "on" : undefined} onClick={() => setFilter(f.key)}>
              {f.label}
            </button>
          ))}
        </div>
      </div>

      <div className="tbl-wrap">
        <table className="tbl op-tbl">
          <thead>
            <tr>
              <th>Client</th>
              <th>Platform</th>
              <th>Post URL</th>
              <th>Anchor</th>
              <th>Verified</th>
              <th>Published</th>
            </tr>
          </thead>
          <tbody>
            {web2Q.isLoading && (
              <tr><td colSpan={6} className="op-empty">Loading placements…</td></tr>
            )}
            {web2Q.isError && !web2Q.isLoading && (
              <tr><td colSpan={6} className="op-empty">Couldn&apos;t load placements — {(web2Q.error as Error)?.message ?? "try again"}.</td></tr>
            )}
            {!web2Q.isLoading && !web2Q.isError && rows.map((w) => {
              const pm = PLATFORM_META[w.platform as Web2Platform];
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
                    <a className="op-url" href={`https://${w.postUrl}`} target="_blank" rel="noreferrer">
                      {w.postUrl}<span className="material-symbols-rounded">open_in_new</span>
                    </a>
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
                  <td className="op-muted">{w.published}</td>
                </tr>
              );
            })}
            {!web2Q.isLoading && !web2Q.isError && rows.length === 0 && (
              <tr><td colSpan={6} className="op-empty">No placements match this filter.</td></tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
