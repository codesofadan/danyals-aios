"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import {
  clientReports, reportBundles, REPORT_GROUP_COLOR,
  type ClientReport, type ClientRecord,
} from "@/lib/data";

const SHARDS = [
  { x: 46, y: 0 }, { x: 23, y: 40 }, { x: -23, y: 40 },
  { x: -46, y: 0 }, { x: -23, y: -40 }, { x: 23, y: -40 },
];

// Edit which reports/graphs an existing client is allowed to see.
// Opens pre-filled with the client's current grants; Save writes them back.
export default function ClientAccessEditor({
  client, current, onClose, onSave,
}: {
  client: ClientRecord;
  current: string[];
  onClose: () => void;
  onSave: (reports: string[]) => void;
}) {
  const [granted, setGranted] = useState<Set<string>>(new Set(current));
  const [popping, setPopping] = useState<Set<string>>(new Set());
  const timers = useRef<ReturnType<typeof setTimeout>[]>([]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("keydown", onKey);
      timers.current.forEach(clearTimeout);
    };
  }, [onClose]);

  const reduce = typeof window !== "undefined" && matchMedia("(prefers-reduced-motion: reduce)").matches;

  function playPop(keys: string[]) {
    if (reduce || keys.length === 0) return;
    setPopping((prev) => { const n = new Set(prev); keys.forEach((k) => n.add(k)); return n; });
    const t = setTimeout(() => {
      setPopping((prev) => { const n = new Set(prev); keys.forEach((k) => n.delete(k)); return n; });
    }, 560);
    timers.current.push(t);
  }

  function toggleBubble(key: string) {
    setGranted((prev) => {
      const n = new Set(prev);
      if (n.has(key)) { n.delete(key); } else { n.add(key); playPop([key]); }
      return n;
    });
  }

  function applyBundle(key: string) {
    if (!key) return;
    const b = reportBundles.find((x) => x.key === key);
    const next = new Set(b ? b.grants : []);
    const newlyOn = [...next].filter((k) => !granted.has(k));
    setGranted(next);
    playPop(newlyOn);
  }

  const changed = useMemo(() => {
    if (granted.size !== current.length) return true;
    return current.some((k) => !granted.has(k));
  }, [granted, current]);

  return (
    <div className="tw">
      <div className="modal-scrim" onClick={onClose}>
        <div className="modal wide wiz" onClick={(e) => e.stopPropagation()}>
          <div className="modal-h">
            <div>
              <div className="modal-t">Report access · {client.cn}</div>
              <div className="modal-s">
                Update what this client can see. Un-popped reports are hidden and their data is never sent to the client.
              </div>
            </div>
            <button type="button" className="modal-x" onClick={onClose} aria-label="Close">
              <span className="material-symbols-rounded">close</span>
            </button>
          </div>

          <div className="wiz-body">
            <div className="tpl-row">
              <label className="tpl-label">Apply bundle</label>
              <div className="tpl-select">
                <span className="material-symbols-rounded tpl-ic">tune</span>
                <select value="" onChange={(e) => applyBundle(e.target.value)} aria-label="Apply bundle">
                  <option value="">Keep current selection…</option>
                  {reportBundles.map((x) => (
                    <option key={x.key} value={x.key}>{x.label} — {x.tagline}</option>
                  ))}
                </select>
              </div>
              <div className="grant-count">
                <b>{granted.size}</b> / {clientReports.length} visible
              </div>
              {granted.size > 0 && (
                <button className="clear-btn" onClick={() => setGranted(new Set())}>
                  <span className="material-symbols-rounded">restart_alt</span>Hide all
                </button>
              )}
            </div>

            <div className="bubble-field">
              {clientReports.map((r, i) => (
                <Bubble
                  key={r.key}
                  report={r}
                  index={i}
                  granted={granted.has(r.key)}
                  popping={popping.has(r.key)}
                  onClick={() => toggleBubble(r.key)}
                />
              ))}
            </div>

            <div className="bubble-legend">
              <span><span className="lg-swatch open" /> Hidden — the client can&apos;t see it</span>
              <span><span className="lg-swatch popped" /> Visible to the client</span>
            </div>

            <div className="modal-f">
              <button type="button" className="ghostbtn" onClick={onClose}>Cancel</button>
              <button type="button" className="primary-btn" disabled={!changed} onClick={() => onSave([...granted])}>
                <span className="material-symbols-rounded">save</span>Save access
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

function Bubble({ report, index, granted, popping, onClick }: {
  report: ClientReport; index: number; granted: boolean; popping: boolean; onClick: () => void;
}) {
  const color = REPORT_GROUP_COLOR[report.group];
  return (
    <button
      type="button"
      className={`bubble${granted ? " granted" : ""}${popping ? " popping" : ""}`}
      style={{ ["--c" as string]: color, ["--i" as string]: index }}
      onClick={onClick}
      aria-pressed={granted}
      title={`${report.label} — ${report.desc}`}
    >
      <span className="bubble-core">
        <span className="bubble-sheen" />
        <span className="bubble-ic material-symbols-rounded">{granted ? "visibility" : report.icon}</span>
        <span className="bubble-lbl">{report.short}</span>
      </span>
      <span className="burst" aria-hidden />
      {SHARDS.map((s, i) => (
        <span key={i} className="shard" aria-hidden style={{ ["--sx" as string]: `${s.x}px`, ["--sy" as string]: `${s.y}px` }} />
      ))}
    </button>
  );
}
