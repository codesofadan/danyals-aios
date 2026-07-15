"use client";

import { useEffect, useRef, useState } from "react";
import anime from "animejs";
import { SERIES, type TeamMemberRecord } from "@/lib/data";

// Team metric distribution — a box-and-whisker plot per KPI (utilization,
// on-time delivery, QA pass rate) across the scored roster. Shows the
// spread the per-member scorecards below can't: min/median/max, the
// inter-quartile box, and every member as a jittered dot.

type Metric = { key: keyof TeamMemberRecord; label: string; c: string };
const METRICS: Metric[] = [
  { key: "utilization", label: "Utilization", c: SERIES.c4 },
  { key: "onTime", label: "On-time delivery", c: SERIES.c1 },
  { key: "quality", label: "QA pass rate", c: SERIES.c2 },
];

function quantile(sorted: number[], q: number): number {
  const pos = (sorted.length - 1) * q;
  const base = Math.floor(pos);
  const rest = pos - base;
  return sorted[base + 1] !== undefined
    ? sorted[base] + rest * (sorted[base + 1] - sorted[base])
    : sorted[base];
}

type Stats = { min: number; q1: number; med: number; q3: number; max: number };
function boxStats(vals: number[]): Stats {
  const s = [...vals].sort((a, b) => a - b);
  return { min: s[0], q1: quantile(s, 0.25), med: quantile(s, 0.5), q3: quantile(s, 0.75), max: s[s.length - 1] };
}

export default function TeamMetricBox({ members }: { members: TeamMemberRecord[] }) {
  const svgRef = useRef<SVGSVGElement>(null);
  const tipRef = useRef<HTMLDivElement>(null);
  const [showTable, setShowTable] = useState(false);

  // Invited members have no metrics yet — exclude them.
  const scored = members.filter((m) => m.status !== "invited");

  useEffect(() => {
    const svg = svgRef.current;
    const tip = tipRef.current;
    if (!svg || !tip) return;
    const NS = "http://www.w3.org/2000/svg";
    const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;

    const W = 760, H = 320, padL = 44, padR = 18, padT = 20, padB = 40;
    const innerW = W - padL - padR, innerH = H - padT - padB;
    const lo = 40, hi = 100; // metrics live in the 60–100 band; give some headroom
    const Y = (v: number) => padT + (1 - (v - lo) / (hi - lo)) * innerH;
    const slot = innerW / METRICS.length;
    const boxW = Math.min(84, slot * 0.42);
    const cx = (i: number) => padL + slot * i + slot / 2;
    const mk = (t: string, a: Record<string, string | number>) => {
      const e = document.createElementNS(NS, t);
      for (const k in a) e.setAttribute(k, String(a[k]));
      return e;
    };

    svg.innerHTML = "";

    // y grid + labels
    const gaxis = mk("g", { class: "tx-axis" });
    const steps = 4;
    for (let i = 0; i <= steps; i++) {
      const v = lo + ((hi - lo) / steps) * i, y = Y(v);
      gaxis.appendChild(mk("line", { class: "tx-grid", x1: padL, y1: y, x2: W - padR, y2: y }));
      const t = mk("text", { x: padL - 9, y: y + 3.5, "text-anchor": "end" });
      t.textContent = `${Math.round(v)}%`;
      gaxis.appendChild(t);
    }
    METRICS.forEach((m, i) => {
      const t = mk("text", { x: cx(i), y: H - 16, "text-anchor": "middle", class: "bx-cat" });
      t.textContent = m.label;
      gaxis.appendChild(t);
    });
    svg.appendChild(gaxis);

    METRICS.forEach((m, i) => {
      const vals = scored.map((s) => s[m.key] as number);
      const st = boxStats(vals);
      const x = cx(i);
      const g = mk("g", {}) as SVGGElement;
      svg.appendChild(g);

      // whisker line (min → max)
      g.appendChild(mk("line", { x1: x, y1: Y(st.max), x2: x, y2: Y(st.min), stroke: "var(--line-2)", "stroke-width": 1.5 }));
      // min / max caps
      for (const v of [st.min, st.max]) {
        g.appendChild(mk("line", { x1: x - boxW * 0.28, y1: Y(v), x2: x + boxW * 0.28, y2: Y(v), stroke: "var(--line-2)", "stroke-width": 1.5 }));
      }
      // IQR box
      const yTop = Y(st.q3), yBot = Y(st.q1);
      const box = mk("rect", {
        x: x - boxW / 2, y: yTop, width: boxW, height: Math.max(1, yBot - yTop), rx: 6,
        fill: m.c, "fill-opacity": 0.16, stroke: m.c, "stroke-width": 2,
        style: `transform-box: fill-box; transform-origin: center; ${reduce ? "" : "transform: scaleY(0);"}`,
        class: "bx-box",
      });
      g.appendChild(box);
      // median line
      g.appendChild(mk("line", { x1: x - boxW / 2, y1: Y(st.med), x2: x + boxW / 2, y2: Y(st.med), stroke: m.c, "stroke-width": 2.6, "stroke-linecap": "round" }));

      // member dots (jittered horizontally, deterministic by index)
      scored.forEach((s, j) => {
        const jitter = ((j % 5) - 2) * (boxW * 0.11);
        g.appendChild(mk("circle", {
          cx: x + jitter, cy: Y(s[m.key] as number), r: 3.4,
          fill: "var(--fg-strong)", "fill-opacity": 0.55,
        }));
      });

      if (!reduce) {
        anime({ targets: box, scaleY: [0, 1], duration: 700, delay: 200 + i * 120, easing: "easeOutCubic" });
      }

      // hover target over the whole column
      const hit = mk("rect", { x: padL + slot * i, y: padT, width: slot, height: innerH, fill: "transparent" });
      hit.addEventListener("pointermove", (e: Event) => {
        const pe = e as PointerEvent;
        const r = svg.getBoundingClientRect();
        tip.innerHTML = `<span class="k">${m.label}</span><br><span class="v">med ${Math.round(st.med)}%</span> <span class="k">· ${Math.round(st.min)}–${Math.round(st.max)}% range</span>`;
        tip.style.left = `${(pe.clientX - r.left)}px`;
        tip.style.top = `${Y(st.q3) / H * r.height}px`;
        tip.classList.add("show");
      });
      hit.addEventListener("pointerleave", () => tip.classList.remove("show"));
      svg.appendChild(hit);
    });
  }, [scored]);

  return (
    <section className="card tm-box-card">
      <div className="card-h">
        <div>
          <div className="ct">Performance Distribution</div>
          <div className="cs">Spread of every specialist across the three delivery KPIs · this cycle</div>
        </div>
        <div className="tools">
          <button className="ghostbtn" onClick={() => setShowTable((s) => !s)}>
            <span className="material-symbols-rounded">table_rows</span>Data
          </button>
        </div>
      </div>

      <div className="svg-wrap">
        <svg ref={svgRef} viewBox="0 0 760 320" preserveAspectRatio="none" aria-label="Box-and-whisker distribution of team utilization, on-time delivery and QA pass rate" />
        <div className="chart-tip" ref={tipRef} />
        <div className="hint">
          <span className="material-symbols-rounded">touch_app</span>Hover a column
        </div>
      </div>

      <div className={showTable ? "dtable show" : "dtable"}>
        <table>
          <thead><tr><th>Member</th>{METRICS.map((m) => <th key={m.key}>{m.label}</th>)}</tr></thead>
          <tbody>
            {scored.map((s) => (
              <tr key={s.id}>
                <td>{s.name}</td>
                {METRICS.map((m) => <td key={m.key}>{s[m.key] as number}%</td>)}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
