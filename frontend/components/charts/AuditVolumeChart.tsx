"use client";

import { useEffect, useRef, useState } from "react";
import anime from "animejs";
import type { CCAuditPoint } from "@/lib/hooks/commandCenter";

// Clean 2D bar chart (animated SVG · anime.js). Bars grow from the
// baseline; hover raises a bar and shows a tooltip. Week labels sit
// on the x-axis; a "Data" toggle exposes the underlying table.
export default function AuditVolumeChart({ audits }: { audits: CCAuditPoint[] }) {
  const svgRef = useRef<SVGSVGElement>(null);
  const tipRef = useRef<HTMLDivElement>(null);
  const [showTable, setShowTable] = useState(false);

  useEffect(() => {
    const svg = svgRef.current;
    const tip = tipRef.current;
    if (!svg || !tip) return;
    const NS = "http://www.w3.org/2000/svg";
    const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;

    const W = 760, H = 330, padL = 40, padR = 14, padT = 22, padB = 34;
    const innerW = W - padL - padR, innerH = H - padT - padB;
    const baseY = padT + innerH;
    const vals = audits.map((d) => d.v);
    const maxV = Math.ceil(Math.max(...vals) / 20) * 20;
    const N = audits.length;
    const slot = innerW / N;
    const barW = Math.min(30, slot * 0.6);
    const X = (i: number) => padL + slot * i + (slot - barW) / 2;
    const Y = (v: number) => padT + (1 - v / maxV) * innerH;
    const mk = (t: string, a: Record<string, string | number>) => {
      const e = document.createElementNS(NS, t);
      for (const k in a) e.setAttribute(k, String(a[k]));
      return e;
    };

    svg.innerHTML = "";
    const defs = mk("defs", {});
    defs.innerHTML =
      `<linearGradient id="barg" x1="0" y1="0" x2="0" y2="1">
         <stop offset="0" stop-color="#432B52"/><stop offset="1" stop-color="#211B29"/>
       </linearGradient>
       <linearGradient id="barg-hi" x1="0" y1="0" x2="0" y2="1">
         <stop offset="0" stop-color="#5B3A6E"/><stop offset="1" stop-color="#432B52"/>
       </linearGradient>`;
    svg.appendChild(defs);

    // y grid + labels
    const gaxis = mk("g", { class: "tx-axis" });
    const steps = 4;
    for (let i = 0; i <= steps; i++) {
      const v = (maxV / steps) * i, y = Y(v);
      gaxis.appendChild(mk("line", { class: "tx-grid", x1: padL, y1: y, x2: W - padR, y2: y }));
      const t = mk("text", { x: padL - 9, y: y + 3.5, "text-anchor": "end" });
      t.textContent = String(Math.round(v));
      gaxis.appendChild(t);
    }
    // x labels
    audits.forEach((d, i) => {
      const t = mk("text", { x: X(i) + barW / 2, y: H - 12, "text-anchor": "middle" });
      t.textContent = d.w;
      gaxis.appendChild(t);
    });
    svg.appendChild(gaxis);

    // bars
    type BarRef = { rect: SVGRectElement; val: SVGTextElement; d: typeof audits[number]; th: number };
    const bars: BarRef[] = [];
    audits.forEach((d, i) => {
      const th = (1 - d.v / maxV) * innerH; // target y-offset from top
      const targetY = padT + th;
      const targetH = baseY - targetY;
      const rect = mk("rect", {
        x: X(i), width: barW, rx: 6,
        y: reduce ? targetY : baseY, height: reduce ? targetH : 0,
        fill: "url(#barg)", class: "bar-rect",
      }) as SVGRectElement;
      const val = mk("text", { x: X(i) + barW / 2, y: targetY - 8, "text-anchor": "middle", class: "bar-val", opacity: reduce ? 1 : 0 }) as SVGTextElement;
      val.textContent = String(d.v);
      svg.appendChild(rect);
      svg.appendChild(val);
      bars.push({ rect, val, d, th: targetH });

      if (!reduce) {
        const o = { h: 0 };
        anime({
          targets: o, h: targetH, duration: 1000, delay: 120 + i * 55, easing: "easeOutCubic",
          update: () => {
            rect.setAttribute("height", String(o.h));
            rect.setAttribute("y", String(baseY - o.h));
          },
        });
        anime({ targets: val, opacity: [0, 1], duration: 400, delay: 620 + i * 55, easing: "easeOutQuad" });
      }
    });

    // hover highlight + tooltip
    let hovered: BarRef | null = null;
    const setHover = (b: BarRef | null) => {
      if (hovered === b) return;
      if (hovered) hovered.rect.setAttribute("fill", "url(#barg)");
      hovered = b;
      if (b) b.rect.setAttribute("fill", "url(#barg-hi)");
    };
    const onMove = (e: PointerEvent) => {
      const r = svg.getBoundingClientRect();
      const sx = (e.clientX - r.left) / r.width * W;
      let i = Math.floor((sx - padL) / slot);
      i = Math.max(0, Math.min(N - 1, i));
      const b = bars[i];
      setHover(b);
      tip.innerHTML = `<span class="k">${b.d.w} · free audits</span><br><span class="v">${b.d.v}</span>`;
      tip.style.left = `${(X(i) + barW / 2) / W * r.width}px`;
      tip.style.top = `${Y(b.d.v) / H * r.height}px`;
      tip.classList.add("show");
    };
    const onLeave = () => { setHover(null); tip.classList.remove("show"); };
    svg.addEventListener("pointermove", onMove);
    svg.addEventListener("pointerleave", onLeave);

    return () => {
      svg.removeEventListener("pointermove", onMove);
      svg.removeEventListener("pointerleave", onLeave);
    };
  }, [audits]);

  return (
    <section className="card">
      <div className="card-h">
        <div>
          <div className="ct">Free Audit Volumes</div>
          <div className="cs">Audits run from the client portal · last 12 weeks</div>
        </div>
        <div className="tools">
          <button className="ghostbtn" onClick={() => setShowTable((s) => !s)}>
            <span className="material-symbols-rounded">table_rows</span>Data
          </button>
        </div>
      </div>

      <div className="svg-wrap bar-wrap">
        <svg ref={svgRef} viewBox="0 0 760 330" preserveAspectRatio="none" aria-label="Free audits run per week over the last 12 weeks" />
        <div className="chart-tip" ref={tipRef} />
        <div className="hint">
          <span className="material-symbols-rounded">touch_app</span>Hover a bar
        </div>
      </div>

      <div className={showTable ? "dtable show" : "dtable"}>
        <table>
          <thead><tr><th>Week</th><th>Free audits</th></tr></thead>
          <tbody>
            {audits.map((d) => (
              <tr key={d.w}><td>{d.w}</td><td>{d.v}</td></tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
