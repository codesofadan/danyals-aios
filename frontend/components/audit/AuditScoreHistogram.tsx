"use client";

import { useEffect, useRef, useState } from "react";
import anime from "animejs";
import type { AuditRow } from "@/lib/audit";
import EmptyState from "@/components/ui/EmptyState";

// Audit score distribution — a histogram of composite site scores across
// every completed audit, binned into 10-point bands. Bars are coloured by
// health band (crit / warn / ok) so the shape of the book's site-health
// reads at a glance. Same animated-SVG idiom as AuditVolumeChart.

const BINS = [
  { lo: 50, hi: 60 }, { lo: 60, hi: 70 }, { lo: 70, hi: 80 },
  { lo: 80, hi: 90 }, { lo: 90, hi: 100 },
];

function bandColor(lo: number): string {
  if (lo >= 80) return "#2F8A73"; // ok
  if (lo >= 70) return "#A96913"; // warn
  return "#B74355";               // crit
}

export default function AuditScoreHistogram({ rows = [] }: { rows?: AuditRow[] }) {
  const svgRef = useRef<SVGSVGElement>(null);
  const tipRef = useRef<HTMLDivElement>(null);
  const [showTable, setShowTable] = useState(false);

  const scored = rows.filter((r): r is AuditRow & { score: number } => r.score !== null);
  const bins = BINS.map((b) => {
    // Last bin is inclusive of 100.
    const items = scored.filter((r) => r.score >= b.lo && (b.hi === 100 ? r.score <= 100 : r.score < b.hi));
    return { ...b, count: items.length, items };
  });

  useEffect(() => {
    const svg = svgRef.current;
    const tip = tipRef.current;
    if (!svg || !tip) return;
    const NS = "http://www.w3.org/2000/svg";
    const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;

    const W = 760, H = 320, padL = 38, padR = 16, padT = 22, padB = 46;
    const innerW = W - padL - padR, innerH = H - padT - padB;
    const baseY = padT + innerH;
    const maxCount = Math.max(1, ...bins.map((b) => b.count));
    const maxV = Math.max(2, Math.ceil(maxCount));
    const N = bins.length;
    const slot = innerW / N;
    const barW = Math.min(96, slot * 0.82); // histogram bars sit close together
    const X = (i: number) => padL + slot * i + (slot - barW) / 2;
    const Y = (v: number) => padT + (1 - v / maxV) * innerH;
    const mk = (t: string, a: Record<string, string | number>) => {
      const e = document.createElementNS(NS, t);
      for (const k in a) e.setAttribute(k, String(a[k]));
      return e;
    };

    svg.innerHTML = "";

    // y grid + integer labels
    const gaxis = mk("g", { class: "tx-axis" });
    for (let v = 0; v <= maxV; v++) {
      const y = Y(v);
      gaxis.appendChild(mk("line", { class: "tx-grid", x1: padL, y1: y, x2: W - padR, y2: y }));
      const t = mk("text", { x: padL - 9, y: y + 3.5, "text-anchor": "end" });
      t.textContent = String(v);
      gaxis.appendChild(t);
    }
    bins.forEach((b, i) => {
      const t = mk("text", { x: X(i) + barW / 2, y: H - 22, "text-anchor": "middle" });
      t.textContent = `${b.lo}–${b.hi === 100 ? 100 : b.hi - 1}`;
      gaxis.appendChild(t);
    });
    svg.appendChild(gaxis);

    // x-axis title
    const xTitle = mk("text", { x: padL + innerW / 2, y: H - 6, "text-anchor": "middle", class: "sc-axis-title" });
    xTitle.textContent = "Composite site score →";
    svg.appendChild(xTitle);

    // bars (2px surface gap via barW < slot)
    type BarRef = { rect: SVGRectElement; b: typeof bins[number]; i: number };
    const bars: BarRef[] = [];
    bins.forEach((b, i) => {
      const targetY = Y(b.count);
      const targetH = baseY - targetY;
      const col = bandColor(b.lo);
      const rect = mk("rect", {
        x: X(i), width: barW, rx: 6,
        y: reduce ? targetY : baseY, height: reduce ? targetH : 0,
        fill: col, "fill-opacity": 0.82, class: "hist-bar",
      }) as SVGRectElement;
      svg.appendChild(rect);
      // count label above bar
      const val = mk("text", { x: X(i) + barW / 2, y: targetY - 8, "text-anchor": "middle", class: "bar-val", opacity: reduce ? 1 : 0 }) as SVGTextElement;
      val.textContent = b.count ? String(b.count) : "";
      svg.appendChild(val);
      bars.push({ rect, b, i });

      if (!reduce) {
        const o = { h: 0 };
        anime({
          targets: o, h: targetH, duration: 900, delay: 140 + i * 70, easing: "easeOutCubic",
          update: () => {
            rect.setAttribute("height", String(o.h));
            rect.setAttribute("y", String(baseY - o.h));
          },
        });
        anime({ targets: val, opacity: [0, 1], duration: 380, delay: 640 + i * 70, easing: "easeOutQuad" });
      }
    });

    // hover
    let hovered: BarRef | null = null;
    const setHover = (h: BarRef | null) => {
      if (hovered === h) return;
      if (hovered) hovered.rect.setAttribute("fill-opacity", "0.82");
      hovered = h;
      if (h) h.rect.setAttribute("fill-opacity", "1");
    };
    const onMove = (e: PointerEvent) => {
      const r = svg.getBoundingClientRect();
      const sx = (e.clientX - r.left) / r.width * W;
      let i = Math.floor((sx - padL) / slot);
      i = Math.max(0, Math.min(N - 1, i));
      const bar = bars[i];
      setHover(bar);
      const names = bar.b.items.map((x) => x.client).join(", ") || "—";
      tip.innerHTML = `<span class="k">Score ${bar.b.lo}–${bar.b.hi === 100 ? 100 : bar.b.hi - 1}</span><br><span class="v">${bar.b.count}</span> <span class="k">audit${bar.b.count === 1 ? "" : "s"}${bar.b.count ? " · " + names : ""}</span>`;
      tip.style.left = `${(X(i) + barW / 2) / W * r.width}px`;
      tip.style.top = `${Y(bar.b.count) / H * r.height}px`;
      tip.classList.add("show");
    };
    const onLeave = () => { setHover(null); tip.classList.remove("show"); };
    svg.addEventListener("pointermove", onMove);
    svg.addEventListener("pointerleave", onLeave);

    return () => {
      svg.removeEventListener("pointermove", onMove);
      svg.removeEventListener("pointerleave", onLeave);
    };
  }, [rows]); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <section className="card">
      <div className="card-h">
        <div>
          <div className="ct">Score Distribution</div>
          <div className="cs">How completed audits spread across the composite site-health bands</div>
        </div>
        <div className="tools">
          <button className="ghostbtn" onClick={() => setShowTable((s) => !s)}>
            <span className="material-symbols-rounded">table_rows</span>Data
          </button>
        </div>
      </div>

      {scored.length === 0 ? (
        <EmptyState
          icon="bar_chart"
          title="No current data"
          hint="No completed audits with a score yet — run an audit to see the score distribution."
        />
      ) : (
        <div className="svg-wrap bar-wrap">
          <svg ref={svgRef} viewBox="0 0 760 320" preserveAspectRatio="none" aria-label="Histogram of composite audit scores by 10-point band" />
          <div className="chart-tip" ref={tipRef} />
          <div className="hint">
            <span className="material-symbols-rounded">touch_app</span>Hover a band
          </div>
        </div>
      )}

      <div className={showTable && scored.length > 0 ? "dtable show" : "dtable"}>
        <table>
          <thead><tr><th>Score band</th><th>Audits</th></tr></thead>
          <tbody>
            {bins.map((b) => (
              <tr key={b.lo}><td>{b.lo}–{b.hi === 100 ? 100 : b.hi - 1}</td><td>{b.count}</td></tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
