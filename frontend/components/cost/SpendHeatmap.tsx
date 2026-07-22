"use client";

import { useEffect, useRef, useState } from "react";
import anime from "animejs";
import {
  PROVIDERS, JOB_TYPE_META, providerLabel, providerMeta, usd,
  type Provider, type JobType, type CostEntry,
} from "@/lib/cost";

// Spend heatmap — provider (rows) × job type (columns), cell shaded by
// how much of the month's spend flowed through that pairing. A sequential
// single-hue ramp (magnitude), so the hot cells (where the money goes)
// pop against the cold ones. Complements the 1-D "Spend by Provider" bars.

const PROVIDER_ROWS = Object.keys(PROVIDERS) as Provider[];
const JOB_COLS: JobType[] = ["audit", "content", "backlinks"];

type Cell = { spend: number; calls: number };

export default function SpendHeatmap({ log }: { log: CostEntry[] }) {
  const rootRef = useRef<HTMLDivElement>(null);
  const tipRef = useRef<HTMLDivElement>(null);
  const [showTable, setShowTable] = useState(false);

  // Aggregate the per-job cost log into a provider × job-type matrix. The log's
  // provider strings are FREE-FORM (audit_engine, serper, …), so rows are the
  // known providers PLUS any provider actually seen in the log — spend must
  // never be silently invisible, and an unknown name must never crash.
  const seen = [...new Set(log.map((e) => String(e.provider)))];
  const allRows = [...new Set([...PROVIDER_ROWS, ...seen])] as Provider[];
  const matrix: Record<string, Cell> = {};
  let max = 0;
  for (const p of allRows) {
    for (const j of JOB_COLS) matrix[`${p}|${j}`] = { spend: 0, calls: 0 };
  }
  for (const e of log) {
    const cell = matrix[`${e.provider}|${e.type}`];
    if (!cell) continue; // unknown job type — column set is fixed
    cell.spend += e.cost;
    cell.calls += 1;
    if (cell.spend > max) max = cell.spend;
  }
  const rowsUsed = allRows.filter((p) =>
    JOB_COLS.some((j) => matrix[`${p}|${j}`].calls > 0),
  );

  useEffect(() => {
    const root = rootRef.current;
    if (!root) return;
    if (matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    const cells = root.querySelectorAll<HTMLElement>(".hm-cell");
    const a = anime({
      targets: cells,
      opacity: [0, 1],
      scale: [0.9, 1],
      duration: 480,
      delay: anime.stagger(24, { start: 100 }),
      easing: "easeOutQuad",
    });
    return () => a.pause();
  }, []);

  const onCell = (e: React.PointerEvent, p: Provider, j: JobType) => {
    const tip = tipRef.current, host = rootRef.current;
    if (!tip || !host) return;
    const c = matrix[`${p}|${j}`];
    const r = host.getBoundingClientRect();
    tip.innerHTML = `<span class="k">${p} · ${JOB_TYPE_META[j].label}</span><br><span class="v">${usd(c.spend, 2)}</span> <span class="k">· ${c.calls} call${c.calls === 1 ? "" : "s"}</span>`;
    tip.style.left = `${e.clientX - r.left}px`;
    tip.style.top = `${e.clientY - r.top}px`;
    tip.classList.add("show");
  };
  const hideTip = () => tipRef.current?.classList.remove("show");

  return (
    <section className="card">
      <div className="card-h">
        <div>
          <div className="ct">Spend Heatmap</div>
          <div className="cs">Where the month&apos;s paid calls concentrate · provider × job type</div>
        </div>
        <div className="tools">
          <div className="hm-scale">
            <span className="hm-scale-lbl">low</span>
            <span className="hm-scale-ramp" />
            <span className="hm-scale-lbl">high</span>
          </div>
          <button className="ghostbtn" onClick={() => setShowTable((s) => !s)}>
            <span className="material-symbols-rounded">table_rows</span>Data
          </button>
        </div>
      </div>

      <div className="hmap" ref={rootRef} onPointerLeave={hideTip}>
        <div className="hm-grid" style={{ gridTemplateColumns: `minmax(96px, 1.1fr) repeat(${JOB_COLS.length}, 1fr)` }}>
          <div className="hm-corner" />
          {JOB_COLS.map((j) => (
            <div className="hm-colh" key={j}>
              <span className="material-symbols-rounded">{JOB_TYPE_META[j].icon}</span>
              {JOB_TYPE_META[j].label}
            </div>
          ))}
          {rowsUsed.map((p) => (
            <FragmentRow key={p} p={p} matrix={matrix} max={max} onCell={onCell} />
          ))}
        </div>
        <div className="chart-tip" ref={tipRef} />
      </div>

      <div className={showTable ? "dtable show" : "dtable"}>
        <table>
          <thead><tr><th>Provider</th>{JOB_COLS.map((j) => <th key={j}>{JOB_TYPE_META[j].label}</th>)}</tr></thead>
          <tbody>
            {rowsUsed.map((p) => (
              <tr key={p}>
                <td>{p}</td>
                {JOB_COLS.map((j) => <td key={j}>{usd(matrix[`${p}|${j}`].spend, 2)}</td>)}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

// One provider row: label + a coloured cell per job type.
function FragmentRow({
  p, matrix, max, onCell,
}: {
  p: Provider;
  matrix: Record<string, Cell>;
  max: number;
  onCell: (e: React.PointerEvent, p: Provider, j: JobType) => void;
}) {
  return (
    <>
      <div className="hm-rowh">
        <span className="hm-dot" style={{ background: providerMeta(p).c }} />
        {providerLabel(p)}
      </div>
      {JOB_COLS.map((j) => {
        const c = matrix[`${p}|${j}`];
        const t = max > 0 ? c.spend / max : 0;
        const empty = c.calls === 0;
        // Sequential lime ramp: opacity carries magnitude on the accent hue.
        const bg = empty ? "var(--well)" : `color-mix(in srgb, var(--c1) ${12 + t * 78}%, transparent)`;
        return (
          <div
            key={j}
            className={`hm-cell${empty ? " empty" : ""}`}
            style={{ background: bg }}
            onPointerMove={(e) => onCell(e, p, j)}
          >
            {empty ? "" : (t > 0.55 ? usd(c.spend, 2) : usd(c.spend, 0))}
          </div>
        );
      })}
    </>
  );
}
