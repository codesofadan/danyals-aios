"use client";

import { useMemo, useState } from "react";
import { BACKLINK_META, type Backlink, type BacklinkStatus } from "@/lib/offpage";
import { useBacklinks } from "@/lib/hooks/offpage";

type FilterKey = "all" | BacklinkStatus;

const FILTERS: { key: FilterKey; label: string }[] = [
  { key: "all", label: "All" },
  { key: "new", label: "New" },
  { key: "lost", label: "Lost" },
  { key: "toxic", label: "Toxic" },
];

// Authority 0–100 rendered as a compact meter; hue shifts on strength.
function authorityColor(v: number) {
  if (v >= 70) return "var(--ok)";
  if (v >= 40) return "var(--warn)";
  return "var(--crit)";
}

export default function BacklinksTab() {
  const [filter, setFilter] = useState<FilterKey>("all");
  const backlinksQ = useBacklinks();
  const backlinks = backlinksQ.data ?? [];

  const rows = useMemo(
    () => backlinks.filter((b) => filter === "all" || b.status === filter),
    [backlinks, filter],
  );

  const counts = useMemo(() => {
    const c: Record<FilterKey, number> = { all: backlinks.length, new: 0, lost: 0, toxic: 0 };
    backlinks.forEach((b) => { c[b.status] += 1; });
    return c;
  }, [backlinks]);

  return (
    <div className="panel-in">
      <div className="panel-h">
        <div className="panel-hint">
          <span className="material-symbols-rounded">hub</span>
          Referring domains, anchors &amp; authority — new / lost alerts from DataForSEO.
        </div>
        <div className="seg">
          {FILTERS.map((f) => (
            <button key={f.key} className={filter === f.key ? "on" : undefined} onClick={() => setFilter(f.key)}>
              {f.label} <span className="op-count">{counts[f.key]}</span>
            </button>
          ))}
        </div>
      </div>

      <div className="tbl-wrap">
        <table className="tbl op-tbl">
          <thead>
            <tr>
              <th>Client</th>
              <th>Referring domain</th>
              <th>Anchor</th>
              <th className="num">Authority</th>
              <th className="num">Spam</th>
              <th>First seen</th>
              <th>Status</th>
            </tr>
          </thead>
          <tbody>
            {backlinksQ.isLoading && (
              <tr><td colSpan={7} className="op-empty">Loading backlinks…</td></tr>
            )}
            {backlinksQ.isError && !backlinksQ.isLoading && (
              <tr><td colSpan={7} className="op-empty">Couldn&apos;t load backlinks — {(backlinksQ.error as Error)?.message ?? "try again"}.</td></tr>
            )}
            {!backlinksQ.isLoading && !backlinksQ.isError && rows.map((b: Backlink) => {
              const meta = BACKLINK_META[b.status];
              return (
                <tr key={b.id}>
                  <td className="op-strong">{b.client}</td>
                  <td><span className="op-domain">{b.refDomain}</span></td>
                  <td><span className="op-anchor">{b.anchor}</span></td>
                  <td className="num">
                    <div className="op-auth">
                      <span className="op-auth-n">{b.authority}</span>
                      <span className="op-auth-bar">
                        <i style={{ width: `${b.authority}%`, background: authorityColor(b.authority) }} />
                      </span>
                    </div>
                  </td>
                  <td className="num">
                    <span className={b.spam >= 30 ? "op-spam hot" : "op-spam"}>{b.spam}</span>
                  </td>
                  <td className="op-muted">{b.firstSeen}</td>
                  <td>
                    <span className={`status-pill ${meta.cls}`}>
                      <span className="material-symbols-rounded op-pill-ic">{meta.icon}</span>{meta.label}
                    </span>
                  </td>
                </tr>
              );
            })}
            {!backlinksQ.isLoading && !backlinksQ.isError && rows.length === 0 && (
              <tr><td colSpan={7} className="op-empty">No links match this filter.</td></tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
